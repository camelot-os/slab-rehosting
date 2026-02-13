/*
 * Slab Cortex-M - Generic ARM Cortex-M Machine with Peripheral Export
 *
 * This machine provides a generic ARM Cortex-M emulator with peripherals
 * exported via TCP or shared memory for external analysis tools.
 *
 * Supported CPUs:
 *   - ARMv6-M: Cortex-M0, M0+
 *   - ARMv7-M: Cortex-M3, M4, M7
 *   - ARMv8-M: Cortex-M23, M33, M35P (with TrustZone)
 *   - ARMv8.1-M: Cortex-M55, M85 (with TrustZone + Helium/MVE)
 *
 * Features:
 *   - Dual-Core support (asymmetric multiprocessing - AMP)
 *   - Bootrom loading for SoC emulation
 *   - ARM CoreSight Debug support (DWT, ITM, FPB, ETM, TPIU)
 *   - TrustZone support with configurable SAU regions
 *   - TCP peripheral proxy (remote/networked operation)
 *   - Shared memory peripheral bridge (low-latency local operation)
 *
 * Usage:
 *   # Single core ARMv7-M with TCP proxy
 *   qemu-system-arm \
 *     -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555 \
 *     -kernel firmware.bin -nographic
 *
 *   # With shared memory (lower latency)
 *   qemu-system-arm \
 *     -M slab-cortex-m,cpu-type=cortex-m4,shm-name=/slab_periph \
 *     -kernel firmware.bin -nographic
 *
 *   # Dual-Core with TrustZone
 *   qemu-system-arm \
 *     -M slab-cortex-m,cpu-type=cortex-m33,dual-core=true,trustzone=on \
 *     -kernel secure_firmware.bin -nographic
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2026 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/error-report.h"
#include "hw/arm/armv7m.h"
#include "target/arm/cpu.h"
#include "hw/arm/boot.h"
#include "hw/arm/machines-qom.h"
#include "hw/core/boards.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/qdev-clock.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/misc/unimp.h"
#include "hw/core/loader.h"
#include "system/system.h"
#include "system/address-spaces.h"
#include "exec/tb-flush.h"
#include "qemu/sockets.h"
#include "qemu/main-loop.h"
#include "qom/object.h"
#include "qemu/timer.h"
#include "qemu/cutils.h"

#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <poll.h>

/* ========================================================================= */
/*                      SHARED MEMORY DEFINITIONS                            */
/* ========================================================================= */

/*
 * Shared Memory Protocol Header (compatible with Python slab_cortex_m.shm_peripheral)
 *
 * Layout:
 *   [0:4]   - Magic (0x534C4142 = "SLAB")
 *   [4:8]   - Version
 *   [8:12]  - Command (from QEMU)
 *   [12:16] - Status (from Python)
 *   [16:20] - Address
 *   [20:24] - Data
 *   [24:28] - Size
 *   [28:32] - Sequence number
 *   [32:36] - IRQ status
 *   [36:40] - Snapshot flags (save/restore)
 *   [40:44] - Bus attributes (BusAttributes.pack() format, bit8=NS)
 *   [44:48] - Program Counter (PC, for bootloop debugging)
 *   [48:64] - Reserved
 *   [64:..] - Peripheral data region
 */

#define SHM_MAGIC       0x534C4142  /* "SLAB" */
#define SHM_VERSION     1
#define SHM_HEADER_SIZE 64

/* Shared memory commands */
#define SHM_CMD_NOP         0
#define SHM_CMD_READ8       1
#define SHM_CMD_READ16      2
#define SHM_CMD_READ32      3
#define SHM_CMD_WRITE8      4
#define SHM_CMD_WRITE16     5
#define SHM_CMD_WRITE32     6
#define SHM_CMD_IRQ_SET     7
#define SHM_CMD_IRQ_CLEAR   8
#define SHM_CMD_RESET       9
#define SHM_CMD_SYNC        10
#define SHM_CMD_MPU_SYNC    13  /* MPU state sync to Python */
#define SHM_CMD_SNAPSHOT_SAVE    15  /* Dump CPU state to SHM */
#define SHM_CMD_SNAPSHOT_RESTORE 16  /* Load CPU state from SHM */
#define SHM_CMD_FAULT_NOTIFY     17  /* Fault notification (plugin→Python) */
#define SHM_CMD_DMA_READ         18  /* Python→QEMU: DMA memory read */
#define SHM_CMD_DMA_WRITE        19  /* Python→QEMU: DMA memory write */

/* SHM DMA command area in header (words 12-15) */
#define SHM_DMA_CMD_OFF     48   /* header[12] byte offset */
#define SHM_DMA_ADDR_OFF    52   /* header[13] byte offset */
#define SHM_DMA_SIZE_OFF    56   /* header[14] byte offset */
#define SHM_DMA_STATUS_OFF  60   /* header[15] byte offset */
#define SHM_DMA_DATA_OFF    128  /* DMA data region offset */
#define SHM_DMA_MAX_SIZE    (1024 * 1024 - SHM_DMA_DATA_OFF)

/* MPU state area in SHM data region (offset 64) */
#define SHM_MPU_OFFSET      SHM_HEADER_SIZE  /* starts at byte 64 */
#define SHM_MPU_MAX_REGIONS 16
/* Layout: [0:4] MPU_CTRL, [4:132] up to 16 regions × {RBAR(4), RASR(4)} */
#define SHM_MPU_STATE_SIZE  (4 + SHM_MPU_MAX_REGIONS * 8)

/*
 * Snapshot area in SHM (for CPU state save/restore)
 *
 * Layout at SHM offset 256 (SHM_SNAPSHOT_OFFSET):
 *   [0:4]   Architecture (0=ARM Cortex-M, 1=RISC-V)
 *   [4:8]   Number of registers
 *   [8:N]   Register values (4 bytes each):
 *           ARM: R0-R12, SP, LR, PC, xPSR, MSP, PSP, CONTROL,
 *                PRIMASK, FAULTMASK, BASEPRI, FPSCR, S0-S31
 */
#define SHM_SNAPSHOT_OFFSET     256
#define SHM_SNAPSHOT_MAX_REGS   56
#define SHM_SNAPSHOT_HEADER_SIZE 8
#define SHM_SNAPSHOT_STATE_SIZE (SHM_SNAPSHOT_HEADER_SIZE + SHM_SNAPSHOT_MAX_REGS * 4)

/* Cortex-M register indices in snapshot (must match Python CortexMReg) */
#define SNAP_REG_R0       0
#define SNAP_REG_SP       13
#define SNAP_REG_LR       14
#define SNAP_REG_PC       15
#define SNAP_REG_XPSR     16
#define SNAP_REG_MSP      17
#define SNAP_REG_PSP      18
#define SNAP_REG_CONTROL  19
#define SNAP_REG_PRIMASK  20
#define SNAP_REG_FAULTMASK 21
#define SNAP_REG_BASEPRI  22
#define SNAP_REG_FPSCR    23
#define SNAP_REG_S0       24  /* S0-S31 at indices 24-55 */

/* ARM Debug region addresses */
#define ARM_PPB_BASE        0xE0000000
#define ARM_ITM_BASE        0xE0000000
#define ARM_DWT_BASE        0xE0001000
#define ARM_FPB_BASE        0xE0002000
#define ARM_SCS_BASE        0xE000E000
#define ARM_TPIU_BASE       0xE0040000
#define ARM_ETM_BASE        0xE0041000
#define ARM_ROM_TABLE_BASE  0xE00FF000
#define ARM_PPB_SIZE        0x00100000

/* Maximum cores and IRQs */
#define MAX_CPUS 2
#define MAX_IRQS 240
#define PROXY_RECV_BUF_SIZE 256

/* ========================================================================= */
/*                       PERIPHERAL PROXY DEVICE                             */
/* ========================================================================= */

#define TYPE_SLAB_PERIPH_PROXY "slab-periph-proxy"
OBJECT_DECLARE_SIMPLE_TYPE(SlabPeriphProxyState, SLAB_PERIPH_PROXY)

typedef enum {
    PROXY_MODE_TCP,
    PROXY_MODE_SHM,
} ProxyMode;

/* TCP receive state machine states */
typedef enum {
    RECV_TAG,     /* Waiting for first byte ('I' = IRQ, else response) */
    RECV_IRQ,     /* Reading 5 remaining IRQ bytes [irq_le32 + level] */
    RECV_DATA,    /* Reading 4 remaining response bytes */
    RECV_MEM_HDR, /* Reading 8-byte DMA header [addr:4][size:4] */
    RECV_MEM_WR,  /* Reading N-byte DMA write payload */
} ProxyRecvState;

struct SlabPeriphProxyState {
    /*< private >*/
    SysBusDevice parent_obj;

    /*< public >*/
    MemoryRegion iomem;
    MemoryRegion iomem_ns;  /* Non-Secure alias for TrustZone */

    /* Configuration properties */
    uint32_t base_addr;
    uint32_t size;
    int32_t tcp_port;
    char *shm_name;
    char *name;
    bool trustzone_enabled;
    ProxyMode mode;

    /* TCP connection state */
    int listen_fd;
    int client_fd;
    bool tcp_connected;

    /* Shared memory state */
    int shm_fd;
    void *shm_ptr;
    size_t shm_size;
    uint32_t shm_seq;

    /* SHM IRQ polling timer (for async IRQ delivery) */
    QEMUTimer *shm_irq_timer;
    uint32_t shm_irq_prev;  /* Previous IRQ bitmap to detect changes */

    /* Register cache (for disconnected operation) */
    GHashTable *reg_cache;

    /* IRQ outputs to NVIC */
    qemu_irq irqs[MAX_IRQS];
    uint32_t num_irqs;

    /* TCP receive state machine */
    uint8_t recv_buf[PROXY_RECV_BUF_SIZE];
    int recv_len;
    ProxyRecvState proto_state;
    int recv_needed;        /* Bytes remaining for current message */
    bool response_ready;    /* Transaction response assembled */
    uint32_t response_value;

    /* TrustZone: current transaction security state */
    bool current_secure;

    /* DMA memory access (Python→QEMU) */
    uint8_t  dma_cmd;           /* 'M'=read, 'N'=write, 0=none */
    uint32_t dma_addr;          /* Target address */
    uint32_t dma_size;          /* Transfer size */
    uint8_t *dma_buf;           /* Dynamic buffer for DMA write data */
    uint32_t dma_buf_alloc;     /* Allocated size of dma_buf */
};

/* Forward declarations */
static void slab_proxy_try_connect_tcp(SlabPeriphProxyState *s);
static void slab_proxy_disconnect(SlabPeriphProxyState *s);
static bool slab_proxy_tcp_feed(SlabPeriphProxyState *s,
                                const uint8_t *data, int len);
static void slab_proxy_fd_read(void *opaque);
static bool slab_proxy_flush_send(SlabPeriphProxyState *s,
                                  const uint8_t *data, int len);
static bool slab_proxy_init_shm(SlabPeriphProxyState *s);
static void slab_proxy_shm_check_irqs(SlabPeriphProxyState *s);

/*
 * Sync MPU state from CPU to shared memory.
 *
 * Writes the current ARMv7-M PMSAv7 MPU configuration into
 * the SHM data region so Python can mirror the protection policy.
 *
 * Layout at SHM offset 64 (SHM_MPU_OFFSET):
 *   [0:4]   MPU_CTRL (enable, hfnmiena, privdefena)
 *   [4:68]  8 regions × {RBAR(4 bytes), RASR(4 bytes)}
 *           RASR = drsr | (dracr << 16)
 */
static void slab_proxy_sync_mpu_state(SlabPeriphProxyState *s)
{
    ARMCPU *cpu;
    CPUArchState *env;
    /* volatile: cross-process shared memory access */
    volatile uint32_t *mpu_area;
    int i;

    if (!s->shm_ptr) {
        return;
    }

    cpu = ARM_CPU(first_cpu);
    if (!cpu) {
        return;
    }
    env = &cpu->env;

    /* Point to MPU state area in SHM */
    mpu_area = (volatile uint32_t *)((uint8_t *)s->shm_ptr
                                     + SHM_MPU_OFFSET);

    /* Write MPU_CTRL */
    mpu_area[0] = env->v7m.mpu_ctrl[0];  /* M_REG_NS bank */

    /*
     * Write per-region RBAR + RASR/RLAR.
     * PMSAv7 (Cortex-M3/M4/M7): drbar/drsr/dracr arrays
     * PMSAv8 (Cortex-M23/M33/M55): rbar[bank]/rlar[bank] arrays
     */
    if (env->pmsav7.drbar) {
        /* PMSAv7 */
        for (i = 0; i < SHM_MPU_MAX_REGIONS && i < cpu->pmsav7_dregion; i++) {
            uint32_t rbar = env->pmsav7.drbar[i];
            uint32_t rasr = env->pmsav7.drsr[i] | (env->pmsav7.dracr[i] << 16);
            mpu_area[1 + i * 2] = rbar;
            mpu_area[1 + i * 2 + 1] = rasr;
        }
    } else if (env->pmsav8.rbar[0]) {
        /* PMSAv8 -- write RBAR + RLAR pairs */
        for (i = 0; i < SHM_MPU_MAX_REGIONS && i < cpu->pmsav7_dregion; i++) {
            mpu_area[1 + i * 2] = env->pmsav8.rbar[0][i];
            mpu_area[1 + i * 2 + 1] = env->pmsav8.rlar[0][i];
        }
    } else {
        /* No MPU -- zero all regions */
        i = 0;
    }

    /* Zero out unused regions */
    for (; i < SHM_MPU_MAX_REGIONS; i++) {
        mpu_area[1 + i * 2] = 0;
        mpu_area[1 + i * 2 + 1] = 0;
    }

    __sync_synchronize();
}

/*
 * Save CPU register state to SHM snapshot area.
 *
 * Dumps all Cortex-M registers into the SHM data region at
 * SHM_SNAPSHOT_OFFSET for the Python-side SnapshotManager to read.
 *
 * Register layout matches Python CortexMReg enum indices.
 * Ref: ARMv7-M ARM DDI 0403E, Section B1.4.2 "The registers"
 */
static void slab_proxy_save_snapshot(SlabPeriphProxyState *s)
{
    ARMCPU *cpu;
    CPUArchState *env;
    /* volatile: cross-process shared memory access */
    volatile uint32_t *snap;
    int i;

    if (!s->shm_ptr) {
        return;
    }

    cpu = ARM_CPU(first_cpu);
    if (!cpu) {
        return;
    }
    env = &cpu->env;

    snap = (volatile uint32_t *)((uint8_t *)s->shm_ptr
                                 + SHM_SNAPSHOT_OFFSET);

    /* Header: architecture + register count */
    snap[0] = 0;   /* ARCH_ARM_CORTEX_M */
    /*
     * Core registers: R0-R12, SP, LR, PC, xPSR, MSP, PSP,
     * CONTROL, PRIMASK, FAULTMASK, BASEPRI
     */
    snap[1] = 23;

    /* General purpose registers R0-R12 */
    for (i = 0; i < 13; i++) {
        snap[2 + i] = env->regs[i];
    }

    /* SP (R13) - current stack pointer */
    snap[2 + SNAP_REG_SP] = env->regs[13];

    /* LR (R14) */
    snap[2 + SNAP_REG_LR] = env->regs[14];

    /* PC (R15) */
    snap[2 + SNAP_REG_PC] = env->regs[15];

    /* xPSR (combined APSR + IPSR + EPSR) */
    snap[2 + SNAP_REG_XPSR] = xpsr_read(env);

    /* MSP and PSP */
    snap[2 + SNAP_REG_MSP] = env->v7m.other_sp;
    snap[2 + SNAP_REG_PSP] = env->regs[13];  /* Approximation */

    /* Special registers */
    snap[2 + SNAP_REG_CONTROL] = env->v7m.control[0];
    snap[2 + SNAP_REG_PRIMASK] = env->v7m.primask[0];
    snap[2 + SNAP_REG_FAULTMASK] = env->v7m.faultmask[0];
    snap[2 + SNAP_REG_BASEPRI] = env->v7m.basepri[0];

    __sync_synchronize();
}

/*
 * Restore CPU register state from SHM snapshot area.
 *
 * Loads Cortex-M registers from the SHM data region written by Python.
 * Used for snapshot-based fuzzing (reset to known state before each input).
 *
 * Ref: ARMv7-M ARM DDI 0403E, Section B1.4
 */
static void slab_proxy_restore_snapshot(SlabPeriphProxyState *s)
{
    ARMCPU *cpu;
    CPUArchState *env;
    /* volatile: cross-process shared memory access */
    volatile uint32_t *snap;
    int i;

    if (!s->shm_ptr) {
        return;
    }

    cpu = ARM_CPU(first_cpu);
    if (!cpu) {
        return;
    }
    env = &cpu->env;

    snap = (volatile uint32_t *)((uint8_t *)s->shm_ptr
                                 + SHM_SNAPSHOT_OFFSET);

    /* Verify architecture */
    if (snap[0] != 0) {  /* Must be ARCH_ARM_CORTEX_M */
        return;
    }

    __sync_synchronize();

    /* General purpose registers R0-R12 */
    for (i = 0; i < 13; i++) {
        env->regs[i] = snap[2 + i];
    }

    /* SP (R13) */
    env->regs[13] = snap[2 + SNAP_REG_SP];

    /* LR (R14) */
    env->regs[14] = snap[2 + SNAP_REG_LR];

    /* PC (R15) */
    env->regs[15] = snap[2 + SNAP_REG_PC];

    /* xPSR */
    xpsr_write(env, snap[2 + SNAP_REG_XPSR], 0xFFFFFFFF);

    /* Special registers */
    env->v7m.control[0] = snap[2 + SNAP_REG_CONTROL];
    env->v7m.primask[0] = snap[2 + SNAP_REG_PRIMASK];
    env->v7m.faultmask[0] = snap[2 + SNAP_REG_FAULTMASK];
    env->v7m.basepri[0] = snap[2 + SNAP_REG_BASEPRI];

    /* Flush TB cache after register modification */
    queue_tb_flush(CPU(cpu));
}

/*
 * Shared memory transaction
 */
static uint64_t slab_proxy_shm_transaction(SlabPeriphProxyState *s,
                                            bool is_write, uint32_t addr,
                                            uint32_t size, uint64_t write_val)
{
    /*
     * Volatile is required here for shared memory communication:
     * the header is modified by both QEMU and external Python tools
     * without synchronization primitives.
     */
    volatile uint32_t *header;
    uint32_t result = 0;
    int timeout_us = 10000;  /* 10ms timeout */

    if (!s->shm_ptr) {
        return 0;
    }

    /* volatile for cross-process shared memory access */
    header = (volatile uint32_t *)s->shm_ptr;

    /* Increment sequence number */
    s->shm_seq++;

    /* Set up command based on size */
    int cmd;
    if (is_write) {
        if (size == 1) {
            cmd = SHM_CMD_WRITE8;
        } else if (size == 2) {
            cmd = SHM_CMD_WRITE16;
        } else {
            cmd = SHM_CMD_WRITE32;
        }
    } else {
        if (size == 1) {
            cmd = SHM_CMD_READ8;
        } else if (size == 2) {
            cmd = SHM_CMD_READ16;
        } else {
            cmd = SHM_CMD_READ32;
        }
    }

    /* Sync MPU state before each transaction */
    slab_proxy_sync_mpu_state(s);

    /*
     * Check for snapshot requests from Python (header[9] = offset 36).
     * bit 0: save snapshot, bit 1: restore snapshot
     * These are piggy-backed on regular transactions for low-latency.
     */
    {
        uint32_t snap_flags = header[9];
        if (snap_flags & 0x01) {
            slab_proxy_save_snapshot(s);
            header[9] = snap_flags & ~0x01U;
            __sync_synchronize();
        }
        if (snap_flags & 0x02) {
            slab_proxy_restore_snapshot(s);
            header[9] = snap_flags & ~0x02U;
            __sync_synchronize();
        }
    }

    /* Write command to shared memory */
    header[2] = cmd;           /* Command */
    header[3] = 0;             /* Status (clear) */
    header[4] = addr;          /* Address */
    header[5] = is_write ? (uint32_t)write_val : 0;  /* Data */
    header[6] = size;          /* Size */
    header[7] = s->shm_seq;    /* Sequence */

    /* Bus attributes: NS bit in BusAttributes.pack() format (bit 8) */
    header[10] = (s->current_secure ? 0 : 1) << 8;

    /* Current PC for bootloop debugging */
    {
        ARMCPU *cpu = ARM_CPU(first_cpu);
        header[11] = cpu ? cpu->env.regs[15] : 0;
    }

    /* Memory barrier */
    __sync_synchronize();

    /* Wait for response (status != 0) */
    while (header[3] == 0 && timeout_us > 0) {
        usleep(10);
        timeout_us -= 10;
    }

    if (header[3] != 0) {
        result = header[5];  /* Data field contains result */
    }

    /* Check for IRQ changes */
    slab_proxy_shm_check_irqs(s);

    return result;
}

/*
 * TCP transaction (non-blocking state machine).
 *
 * Disables the fd handler during the transaction to avoid races between
 * the main-loop poll and the recv loop here, then re-enables it after.
 * Interleaved IRQ packets are handled inline by the state machine.
 */
static uint64_t slab_proxy_tcp_transaction(SlabPeriphProxyState *s, bool is_write,
                                            uint32_t addr, uint32_t size,
                                            uint64_t write_val)
{
    uint8_t req[20];
    int req_len;
    uint32_t value = 0;

    /* Try to connect if not connected */
    if (!s->tcp_connected) {
        slab_proxy_try_connect_tcp(s);
    }

    if (!s->tcp_connected) {
        /* Fallback to cached value */
        gpointer cached = g_hash_table_lookup(s->reg_cache,
                                               GUINT_TO_POINTER(addr));
        if (cached) {
            return GPOINTER_TO_UINT(cached);
        }
        return 0;
    }

    /* Build request packet with TrustZone support */
    if (s->trustzone_enabled && s->current_secure) {
        req[0] = is_write ? 'T' : 'S';  /* Secure access */
    } else {
        req[0] = is_write ? 'W' : 'R';  /* Non-Secure access */
    }
    req[1] = (addr >> 0) & 0xFF;
    req[2] = (addr >> 8) & 0xFF;
    req[3] = (addr >> 16) & 0xFF;
    req[4] = (addr >> 24) & 0xFF;
    req[5] = (size >> 0) & 0xFF;
    req[6] = (size >> 8) & 0xFF;
    req[7] = (size >> 16) & 0xFF;
    req[8] = (size >> 24) & 0xFF;

    if (is_write) {
        req[9] = (write_val >> 0) & 0xFF;
        req[10] = (write_val >> 8) & 0xFF;
        req[11] = (write_val >> 16) & 0xFF;
        req[12] = (write_val >> 24) & 0xFF;
        req[13] = s->current_secure ? 1 : 0;
        req_len = 14;
    } else {
        req[9] = s->current_secure ? 1 : 0;
        req_len = 10;
    }

    /* Append PC for bootloop debugging */
    {
        ARMCPU *cpu = ARM_CPU(first_cpu);
        uint32_t pc = cpu ? cpu->env.regs[15] : 0;
        req[req_len + 0] = (pc >> 0) & 0xFF;
        req[req_len + 1] = (pc >> 8) & 0xFF;
        req[req_len + 2] = (pc >> 16) & 0xFF;
        req[req_len + 3] = (pc >> 24) & 0xFF;
        req_len += 4;
    }

    /* 1. Disable fd handler to avoid racing with main-loop POLLIN */
    qemu_set_fd_handler(s->client_fd, NULL, NULL, NULL);

    /* 2. Send request (non-blocking with backpressure retry) */
    if (!slab_proxy_flush_send(s, req, req_len)) {
        slab_proxy_disconnect(s);
        return 0;
    }

    /* 3. Poll + recv state machine until response is ready */
    s->response_ready = false;
    {
        struct pollfd pfd;
        pfd.fd = s->client_fd;
        pfd.events = POLLIN;

        while (!s->response_ready) {
            int ret = poll(&pfd, 1, 10000 /* 10s timeout */);
            if (ret <= 0) {
                warn_report("Slab Proxy: TCP transaction timeout/error");
                slab_proxy_disconnect(s);
                return 0;
            }

            uint8_t buf[64];
            ssize_t n = recv(s->client_fd, buf, sizeof(buf), MSG_DONTWAIT);
            if (n <= 0) {
                slab_proxy_disconnect(s);
                return 0;
            }
            slab_proxy_tcp_feed(s, buf, (int)n);
        }
    }

    value = s->response_value;

    /* 4. Re-enable fd handler for async IRQ delivery */
    qemu_set_fd_handler(s->client_fd, slab_proxy_fd_read, NULL, s);

    /* Cache the value for disconnected fallback */
    if (!is_write) {
        g_hash_table_insert(s->reg_cache, GUINT_TO_POINTER(addr),
                           GUINT_TO_POINTER(value));
    }

    return value;
}

/*
 * Unified transaction dispatcher
 */
static uint64_t slab_proxy_transaction(SlabPeriphProxyState *s, bool is_write,
                                        uint32_t addr, uint32_t size,
                                        uint64_t write_val)
{
    if (s->mode == PROXY_MODE_SHM && s->shm_ptr) {
        return slab_proxy_shm_transaction(s, is_write, addr, size, write_val);
    } else {
        return slab_proxy_tcp_transaction(s, is_write, addr, size, write_val);
    }
}

/*
 * MemoryRegion read callback (with attrs for TrustZone security state)
 */
static MemTxResult slab_proxy_read_with_attrs(void *opaque, hwaddr offset,
                                               uint64_t *data, unsigned size,
                                               MemTxAttrs attrs)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    uint32_t addr = s->base_addr + offset;

    s->current_secure = s->trustzone_enabled ? attrs.secure : true;

    *data = slab_proxy_transaction(s, false, addr, size, 0);
    return MEMTX_OK;
}

/*
 * MemoryRegion write callback (with attrs for TrustZone security state)
 */
static MemTxResult slab_proxy_write_with_attrs(void *opaque, hwaddr offset,
                                                uint64_t value, unsigned size,
                                                MemTxAttrs attrs)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    uint32_t addr = s->base_addr + offset;

    s->current_secure = s->trustzone_enabled ? attrs.secure : true;

    /* Update cache immediately */
    g_hash_table_insert(s->reg_cache, GUINT_TO_POINTER(addr),
                       GUINT_TO_POINTER((uint32_t)value));

    slab_proxy_transaction(s, true, addr, size, value);
    return MEMTX_OK;
}

static const MemoryRegionOps slab_proxy_ops = {
    .read_with_attrs = slab_proxy_read_with_attrs,
    .write_with_attrs = slab_proxy_write_with_attrs,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .impl = {
        .min_access_size = 1,
        .max_access_size = 4,
    },
};

/*
 * Check SHM IRQ bitmap and deliver pending IRQs to the NVIC.
 *
 * Used by both the polling timer (async delivery) and the synchronous
 * transaction path.  Only fires qemu_set_irq() on delta (changed bits)
 * to avoid redundant NVIC updates.
 */
static void slab_proxy_shm_check_irqs(SlabPeriphProxyState *s)
{
    /* volatile: cross-process shared memory access */
    volatile uint32_t *header;
    uint32_t irq_status;

    if (!s->shm_ptr) {
        return;
    }

    header = (volatile uint32_t *)s->shm_ptr;
    irq_status = header[8];

    if (irq_status != s->shm_irq_prev) {
        for (uint32_t i = 0; i < s->num_irqs && i < 32; i++) {
            int new_level = (irq_status >> i) & 1;
            int old_level = (s->shm_irq_prev >> i) & 1;
            if (new_level != old_level) {
                qemu_set_irq(s->irqs[i], new_level);
            }
        }
        s->shm_irq_prev = irq_status;
    }
}

/*
 * SHM IRQ polling timer callback.
 *
 * Adaptive interval:
 *   - 10us when CPU is halted (WFI) -- CPU is idle, minimal overhead
 *   - 100us when CPU is running -- IRQs already checked on each MMIO
 *     access via slab_proxy_shm_check_irqs(), timer is just a safety net
 */
#define SHM_IRQ_POLL_US      100  /* Running: 100 microseconds */
#define SHM_IRQ_POLL_WFI_US  10   /* Halted (WFI): 10 microseconds */

/*
 * Process DMA commands from Python via SHM header[12-15].
 *
 * Python writes: header[12]=cmd, header[13]=addr, header[14]=size, header[15]=1 (pending)
 * QEMU reads/writes via address_space and sets header[15]=2 (done).
 * DMA data lives at SHM offset 128+.
 */
static void slab_proxy_shm_check_dma(SlabPeriphProxyState *s)
{
    volatile uint32_t *header;
    uint32_t dma_cmd, dma_addr, dma_size;

    if (!s->shm_ptr) {
        return;
    }

    header = (volatile uint32_t *)s->shm_ptr;
    dma_cmd = header[12];
    if (dma_cmd == 0 || header[15] != 1) {
        return;  /* No pending DMA command */
    }

    dma_addr = header[13];
    dma_size = header[14];

    if (dma_size > SHM_DMA_MAX_SIZE) {
        header[15] = 3;  /* Error: too large */
        __sync_synchronize();
        return;
    }

    uint8_t *data_region = (uint8_t *)s->shm_ptr + SHM_DMA_DATA_OFF;
    MemTxAttrs attrs = MEMTXATTRS_UNSPECIFIED;

    if (dma_cmd == SHM_CMD_DMA_READ) {
        address_space_read(&address_space_memory, dma_addr,
                           attrs, data_region, dma_size);
    } else if (dma_cmd == SHM_CMD_DMA_WRITE) {
        address_space_write(&address_space_memory, dma_addr,
                            attrs, data_region, dma_size);
    }

    /* Signal completion */
    header[12] = 0;   /* Clear command */
    header[15] = 2;   /* Done */
    __sync_synchronize();
}

static void slab_proxy_shm_irq_timer(void *opaque)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    int64_t interval_us;

    slab_proxy_shm_check_irqs(s);
    slab_proxy_shm_check_dma(s);

    /*
     * When CPU is in WFI, poll aggressively for low wake-up latency.
     * The CPU is sleeping so there's no instruction waste.
     */
    interval_us = (first_cpu && first_cpu->halted)
                  ? SHM_IRQ_POLL_WFI_US : SHM_IRQ_POLL_US;

    timer_mod_ns(s->shm_irq_timer,
                 qemu_clock_get_ns(QEMU_CLOCK_REALTIME)
                 + interval_us * 1000);
}

/*
 * Initialize shared memory
 */
static bool slab_proxy_init_shm(SlabPeriphProxyState *s)
{
    if (!s->shm_name || strlen(s->shm_name) == 0) {
        return false;
    }

    s->shm_size = 1024 * 1024;  /* 1MB */

    /* Open or create shared memory */
    /* Use restrictive permissions (0600) for security */
    s->shm_fd = shm_open(s->shm_name, O_RDWR | O_CREAT, 0600);
    if (s->shm_fd < 0) {
        warn_report("Failed to open shared memory %s: %s",
                    s->shm_name, strerror(errno));
        return false;
    }

    /* Set size */
    if (ftruncate(s->shm_fd, s->shm_size) < 0) {
        warn_report("Failed to set shared memory size: %s", strerror(errno));
        close(s->shm_fd);
        s->shm_fd = -1;
        return false;
    }

    /* Map shared memory */
    s->shm_ptr = mmap(NULL, s->shm_size, PROT_READ | PROT_WRITE,
                      MAP_SHARED, s->shm_fd, 0);
    if (s->shm_ptr == MAP_FAILED) {
        warn_report("Failed to map shared memory: %s", strerror(errno));
        close(s->shm_fd);
        s->shm_fd = -1;
        s->shm_ptr = NULL;
        return false;
    }

    /* Initialize header */
    uint32_t *header = (uint32_t *)s->shm_ptr;
    header[0] = SHM_MAGIC;
    header[1] = SHM_VERSION;
    header[2] = SHM_CMD_NOP;
    header[3] = 0;  /* Status */
    header[7] = 0;  /* Sequence */
    header[8] = 0;  /* IRQ status */

    s->shm_seq = 0;
    s->shm_irq_prev = 0;
    s->mode = PROXY_MODE_SHM;

    /* Start IRQ polling timer for async IRQ delivery (100us interval) */
    s->shm_irq_timer = timer_new_ns(QEMU_CLOCK_REALTIME,
                                     slab_proxy_shm_irq_timer, s);
    timer_mod_ns(s->shm_irq_timer,
                 qemu_clock_get_ns(QEMU_CLOCK_REALTIME)
                 + (int64_t)SHM_IRQ_POLL_US * 1000);

    info_report("Slab Proxy [%s]: Shared memory %s ready (%zu bytes)",
                s->name, s->shm_name, s->shm_size);
    return true;
}

/*
 * Disconnect from TCP server and reset state machine.
 */
static void slab_proxy_disconnect(SlabPeriphProxyState *s)
{
    if (s->client_fd >= 0) {
        qemu_set_fd_handler(s->client_fd, NULL, NULL, NULL);
        close(s->client_fd);
        s->client_fd = -1;
    }
    s->tcp_connected = false;
    s->proto_state = RECV_TAG;
    s->recv_len = 0;
    s->recv_needed = 0;
    s->response_ready = false;
}

/*
 * Process received bytes through the TCP receive state machine.
 *
 * Handles partial message reassembly: TCP may deliver IRQ packets (6 bytes)
 * or transaction responses (5 bytes) split across multiple recv() calls.
 * The state machine accumulates bytes in recv_buf until a complete message
 * is assembled, then dispatches it (IRQ delivery or response_ready flag).
 *
 * Returns true if a transaction response has been assembled.
 */
static bool slab_proxy_tcp_feed(SlabPeriphProxyState *s,
                                const uint8_t *data, int len)
{
    int pos = 0;

    while (pos < len) {
        switch (s->proto_state) {
        case RECV_TAG: {
            uint8_t tag = data[pos++];
            if (tag == 'I') {
                s->proto_state = RECV_IRQ;
                s->recv_len = 0;
                s->recv_needed = 5;
            } else if (tag == 'M' || tag == 'N') {
                /* DMA memory read ('M') or write ('N') from Python */
                s->dma_cmd = tag;
                s->proto_state = RECV_MEM_HDR;
                s->recv_len = 0;
                s->recv_needed = 8;  /* addr(4) + size(4) */
            } else {
                s->recv_buf[0] = tag;
                s->recv_len = 1;
                s->recv_needed = 4;
                s->proto_state = RECV_DATA;
            }
            break;
        }
        case RECV_IRQ: {
            int want = s->recv_needed;
            int avail = len - pos;
            int copy = (avail < want) ? avail : want;
            memcpy(s->recv_buf + s->recv_len, data + pos, copy);
            s->recv_len += copy;
            s->recv_needed -= copy;
            pos += copy;
            if (s->recv_needed == 0) {
                /* Complete IRQ packet: 4 bytes irq_num LE32 + 1 byte level */
                uint32_t irq_num = s->recv_buf[0] |
                    ((uint32_t)s->recv_buf[1] << 8) |
                    ((uint32_t)s->recv_buf[2] << 16) |
                    ((uint32_t)s->recv_buf[3] << 24);
                int level = s->recv_buf[4];
                if (irq_num < s->num_irqs) {
                    qemu_set_irq(s->irqs[irq_num], level);
                }
                s->proto_state = RECV_TAG;
                s->recv_len = 0;
            }
            break;
        }
        case RECV_DATA: {
            int want = s->recv_needed;
            int avail = len - pos;
            int copy = (avail < want) ? avail : want;
            memcpy(s->recv_buf + s->recv_len, data + pos, copy);
            s->recv_len += copy;
            s->recv_needed -= copy;
            pos += copy;
            if (s->recv_needed == 0) {
                /* Complete response: 5 bytes = [data LE32] + [status] */
                s->response_value = s->recv_buf[0] |
                    ((uint32_t)s->recv_buf[1] << 8) |
                    ((uint32_t)s->recv_buf[2] << 16) |
                    ((uint32_t)s->recv_buf[3] << 24);
                s->response_ready = true;
                s->proto_state = RECV_TAG;
                s->recv_len = 0;
                return true;
            }
            break;
        }
        case RECV_MEM_HDR: {
            int want = s->recv_needed;
            int avail = len - pos;
            int copy = (avail < want) ? avail : want;
            memcpy(s->recv_buf + s->recv_len, data + pos, copy);
            s->recv_len += copy;
            s->recv_needed -= copy;
            pos += copy;
            if (s->recv_needed == 0) {
                s->dma_addr = s->recv_buf[0] |
                    ((uint32_t)s->recv_buf[1] << 8) |
                    ((uint32_t)s->recv_buf[2] << 16) |
                    ((uint32_t)s->recv_buf[3] << 24);
                s->dma_size = s->recv_buf[4] |
                    ((uint32_t)s->recv_buf[5] << 8) |
                    ((uint32_t)s->recv_buf[6] << 16) |
                    ((uint32_t)s->recv_buf[7] << 24);

                if (s->dma_cmd == 'M') {
                    /* DMA read: read from address space, send to Python */
                    MemTxAttrs attrs = MEMTXATTRS_UNSPECIFIED;
                    uint8_t *buf = g_malloc(s->dma_size);
                    address_space_read(&address_space_memory, s->dma_addr,
                                       attrs, buf, s->dma_size);

                    /* Send response: [m:1][size:4][data:N] */
                    uint8_t hdr[5];
                    hdr[0] = 'm';
                    hdr[1] = (s->dma_size >> 0) & 0xFF;
                    hdr[2] = (s->dma_size >> 8) & 0xFF;
                    hdr[3] = (s->dma_size >> 16) & 0xFF;
                    hdr[4] = (s->dma_size >> 24) & 0xFF;
                    slab_proxy_flush_send(s, hdr, 5);
                    slab_proxy_flush_send(s, buf, s->dma_size);
                    g_free(buf);

                    s->proto_state = RECV_TAG;
                    s->recv_len = 0;
                } else {
                    /* DMA write: need to receive payload data first */
                    if (s->dma_size > s->dma_buf_alloc) {
                        g_free(s->dma_buf);
                        s->dma_buf_alloc = s->dma_size;
                        s->dma_buf = g_malloc(s->dma_buf_alloc);
                    }
                    s->proto_state = RECV_MEM_WR;
                    s->recv_len = 0;
                    s->recv_needed = s->dma_size;
                }
            }
            break;
        }
        case RECV_MEM_WR: {
            /* Accumulate DMA write payload into dma_buf */
            int want = s->recv_needed;
            int avail = len - pos;
            int copy = (avail < want) ? avail : want;
            memcpy(s->dma_buf + s->recv_len, data + pos, copy);
            s->recv_len += copy;
            s->recv_needed -= copy;
            pos += copy;
            if (s->recv_needed == 0) {
                /* Write data to QEMU address space */
                MemTxAttrs attrs = MEMTXATTRS_UNSPECIFIED;
                address_space_write(&address_space_memory, s->dma_addr,
                                    attrs, s->dma_buf, s->dma_size);

                /* Send ack: [n:1][status:1] */
                uint8_t ack[2] = { 'n', 0 };
                slab_proxy_flush_send(s, ack, 2);

                s->proto_state = RECV_TAG;
                s->recv_len = 0;
            }
            break;
        }
        }
    }
    return false;
}

/*
 * Non-blocking send with backpressure retry.
 * Returns true on success, false on error.
 */
static bool slab_proxy_flush_send(SlabPeriphProxyState *s,
                                  const uint8_t *data, int len)
{
    int sent = 0;
    while (sent < len) {
        ssize_t n = send(s->client_fd, data + sent, len - sent,
                         MSG_NOSIGNAL | MSG_DONTWAIT);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                struct pollfd pfd;
                pfd.fd = s->client_fd;
                pfd.events = POLLOUT;
                if (poll(&pfd, 1, 5000) <= 0) {
                    return false;
                }
                continue;
            }
            return false;
        }
        sent += (int)n;
    }
    return true;
}

/*
 * FD handler callback: called by QEMU main loop when data arrives on TCP socket.
 *
 * Only active in IDLE state (between transactions). Processes incoming IRQ
 * packets through the state machine with proper partial reassembly.
 * During transactions the fd handler is disabled to avoid racing with
 * the transaction's own recv loop.
 */
static void slab_proxy_fd_read(void *opaque)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    uint8_t buf[64];

    if (!s->tcp_connected || s->client_fd < 0) {
        return;
    }

    while (1) {
        ssize_t n = recv(s->client_fd, buf, sizeof(buf), MSG_DONTWAIT);
        if (n <= 0) {
            if (n == 0 || (errno != EAGAIN && errno != EWOULDBLOCK)) {
                slab_proxy_disconnect(s);
            }
            break;
        }
        slab_proxy_tcp_feed(s, buf, (int)n);

        /* In idle state, a transaction response is a protocol error */
        if (s->response_ready) {
            warn_report("Slab Proxy: unexpected transaction response "
                        "in idle state (discarded)");
            s->response_ready = false;
        }
    }
}

/*
 * Try to establish TCP connection
 */
static void slab_proxy_try_connect_tcp(SlabPeriphProxyState *s)
{
    struct sockaddr_in addr;
    int fd;
    int opt = 1;
    int flags;

    if (s->tcp_connected) {
        return;
    }

    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        return;
    }

    /* Set TCP_NODELAY for low latency */
    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(s->tcp_port);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        close(fd);
        return;
    }

    /* Set non-blocking after connect succeeds */
    flags = fcntl(fd, F_GETFL, 0);
    if (flags >= 0) {
        fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    }

    s->client_fd = fd;
    s->tcp_connected = true;

    /* Initialize state machine */
    s->proto_state = RECV_TAG;
    s->recv_len = 0;
    s->recv_needed = 0;
    s->response_ready = false;

    /*
     * Register FD handler so QEMU main loop calls us when
     * data arrives.  Critical for IRQ delivery when idle.
     */
    qemu_set_fd_handler(fd, slab_proxy_fd_read, NULL, s);

    info_report("Slab Proxy [%s]: Connected to TCP 127.0.0.1:%d",
                s->name, s->tcp_port);
}

/*
 * Device realize
 */
static void slab_proxy_realize(DeviceState *dev, Error **errp)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(dev);

    /* Initialize memory region */
    memory_region_init_io(&s->iomem, OBJECT(s), &slab_proxy_ops, s,
                         s->name ? s->name : "slab-proxy", s->size);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);

    /* Initialize IRQ outputs */
    for (uint32_t i = 0; i < s->num_irqs; i++) {
        sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irqs[i]);
    }

    /* Initialize register cache */
    s->reg_cache = g_hash_table_new(g_direct_hash, g_direct_equal);

    /* Initialize connection state */
    s->listen_fd = -1;
    s->client_fd = -1;
    s->tcp_connected = false;
    s->shm_fd = -1;
    s->shm_ptr = NULL;
    s->proto_state = RECV_TAG;
    s->recv_len = 0;
    s->recv_needed = 0;
    s->response_ready = false;

    /* Try shared memory first, fall back to TCP */
    if (!slab_proxy_init_shm(s)) {
        s->mode = PROXY_MODE_TCP;
        info_report("Slab Proxy [%s]: Using TCP mode on port %d",
                    s->name ? s->name : "periph", s->tcp_port);
    }
}

/*
 * Device properties
 */
static const Property slab_proxy_properties[] = {
    DEFINE_PROP_UINT32("base", SlabPeriphProxyState, base_addr, 0x40000000),
    DEFINE_PROP_UINT32("size", SlabPeriphProxyState, size, 0x20000000),
    DEFINE_PROP_INT32("tcp-port", SlabPeriphProxyState, tcp_port, 5555),
    DEFINE_PROP_STRING("shm-name", SlabPeriphProxyState, shm_name),
    DEFINE_PROP_STRING("name", SlabPeriphProxyState, name),
    DEFINE_PROP_UINT32("num-irqs", SlabPeriphProxyState, num_irqs, MAX_IRQS),
    DEFINE_PROP_BOOL("trustzone", SlabPeriphProxyState, trustzone_enabled, false),
};

static void slab_proxy_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = slab_proxy_realize;
    device_class_set_props(dc, slab_proxy_properties);
}

static const TypeInfo slab_proxy_info = {
    .name = TYPE_SLAB_PERIPH_PROXY,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SlabPeriphProxyState),
    .class_init = slab_proxy_class_init,
};


/* ========================================================================= */
/*                       SLAB CORTEX-M MACHINE                               */
/* ========================================================================= */

#define TYPE_SLAB_CORTEX_M_MACHINE MACHINE_TYPE_NAME("slab-cortex-m")
OBJECT_DECLARE_SIMPLE_TYPE(SlabCortexMState, SLAB_CORTEX_M_MACHINE)

struct SlabCortexMState {
    /*< private >*/
    MachineState parent_obj;

    /*< public >*/
    DeviceState *armv7m;        /* Primary CPU (CPU0) */
    DeviceState *armv7m_cpu1;   /* Secondary CPU (CPU1) for dual-core */
    SlabPeriphProxyState *proxy;
    SlabPeriphProxyState *proxy_dbg;  /* Debug region proxy (PPB) */

    /* Memory regions */
    MemoryRegion flash;
    MemoryRegion flash_alias;
    MemoryRegion sram;
    MemoryRegion bootrom;
    MemoryRegion shared_sram;
    MemoryRegion ns_flash;

    /* Clock */
    Clock *sysclk;
    Clock *sysclk_cpu1;

    /* Configuration */
    char *cpu_type;
    uint32_t flash_base;
    uint32_t flash_size;
    uint32_t sram_base;
    uint32_t sram_size;
    uint32_t periph_base;
    uint32_t periph_size;
    int32_t tcp_port;
    char *shm_name;
    uint32_t num_irqs;
    uint32_t sysclk_hz;
    uint32_t mpu_regions;       /* Override MPU region count (0 = CPU default) */

    /* TrustZone configuration */
    bool trustzone;
    uint32_t secure_flash_size;
    uint32_t secure_sram_size;
    uint32_t ns_flash_base;
    uint32_t ns_flash_size;

    /* Bootrom configuration */
    char *bootrom_file;
    uint32_t bootrom_base;
    uint32_t bootrom_size;

    /* Dual-core configuration */
    bool dual_core;
    char *cpu1_type;
    uint32_t cpu1_vector_table;
    uint32_t cpu1_sysclk_hz;
    bool cpu1_start_powered;
    uint32_t shared_sram_base;
    uint32_t shared_sram_size;

    /* Debug configuration */
    bool debug_proxy;

    /* USBIP configuration */
    int32_t usbip_port;
};


static void slab_cortex_m_init(MachineState *machine)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(machine);
    DeviceState *armv7m_dev;
    DeviceState *proxy_dev;
    bool is_armv8m = false;

    /*
     * Apply defaults (only for fields that can't be zero).
     * Memory layout defaults are set in instance_init() to allow
     * flash_base=0 (e.g. nRF52840).
     */
    if (!s->cpu_type || strlen(s->cpu_type) == 0) {
        s->cpu_type = g_strdup("cortex-m4");
    }

    /* Detect ARMv8-M CPUs (TrustZone capable) */
    is_armv8m = (strstr(s->cpu_type, "cortex-m23") != NULL ||
                 strstr(s->cpu_type, "cortex-m33") != NULL ||
                 strstr(s->cpu_type, "cortex-m35p") != NULL ||
                 strstr(s->cpu_type, "cortex-m55") != NULL ||
                 strstr(s->cpu_type, "cortex-m85") != NULL);

    /* Print configuration */
    info_report("================================================================");
    info_report("              Slab Cortex-M Machine");
    info_report("================================================================");
    info_report("  CPU:         %s", s->cpu_type);
    info_report("  Architecture:%s",
                is_armv8m ? "ARMv8-M (TrustZone capable)" : "ARMv6-M/ARMv7-M");
    info_report("  Flash:       0x%08x - 0x%08x (%u KB)",
                s->flash_base, s->flash_base + s->flash_size - 1,
                s->flash_size / 1024);
    info_report("  SRAM:        0x%08x - 0x%08x (%u KB)",
                s->sram_base, s->sram_base + s->sram_size - 1,
                s->sram_size / 1024);
    info_report("  Peripherals: 0x%08x - 0x%08x",
                s->periph_base, s->periph_base + s->periph_size - 1);
    info_report("  TCP Port:    %d", s->tcp_port);
    if (s->shm_name && strlen(s->shm_name) > 0) {
        info_report("  Shared Mem:  %s", s->shm_name);
    }
    info_report("  IRQs:        %u", s->num_irqs);
    info_report("  Clock:       %u Hz", s->sysclk_hz);
    info_report("================================================================");

    /* Create system clock */
    s->sysclk = clock_new(OBJECT(machine), "SYSCLK");
    clock_set_hz(s->sysclk, s->sysclk_hz);

    /* ========== BOOTROM SETUP ========== */
    bool bootrom_at_zero = false;
    if (s->bootrom_file && strlen(s->bootrom_file) > 0) {
        if (s->bootrom_size == 0) {
            s->bootrom_size = 0x10000;  /* 64KB */
        }

        memory_region_init_rom(&s->bootrom, NULL, "slab.bootrom",
                               s->bootrom_size, &error_fatal);
        memory_region_add_subregion(get_system_memory(), s->bootrom_base, &s->bootrom);
        bootrom_at_zero = (s->bootrom_base == 0);
    }

    /* Initialize Flash memory */
    memory_region_init_rom(&s->flash, NULL, "slab.flash",
                           s->flash_size, &error_fatal);
    memory_region_add_subregion(get_system_memory(), s->flash_base, &s->flash);

    /* Flash alias at address 0 for vector table.
     * Skip when flash is already at 0 (e.g. nRF52840) or when bootrom
     * occupies address 0 (e.g. RP2040) to avoid overlap. */
    if (s->flash_base != 0 && !bootrom_at_zero) {
        memory_region_init_alias(&s->flash_alias, NULL, "slab.flash.alias",
                                 &s->flash, 0, s->flash_size);
        memory_region_add_subregion(get_system_memory(), 0, &s->flash_alias);
    }

    /* Initialize SRAM */
    memory_region_init_ram(&s->sram, NULL, "slab.sram",
                           s->sram_size, &error_fatal);
    memory_region_add_subregion(get_system_memory(), s->sram_base, &s->sram);

    /* ========== DUAL-CORE: SHARED SRAM ========== */
    if (s->dual_core) {
        if (s->shared_sram_size == 0) {
            s->shared_sram_size = 0x8000;  /* 32KB */
        }
        if (s->shared_sram_base == 0) {
            s->shared_sram_base = 0x38000000;
        }

        memory_region_init_ram(&s->shared_sram, NULL, "slab.shared_sram",
                               s->shared_sram_size, &error_fatal);
        memory_region_add_subregion(get_system_memory(),
                                    s->shared_sram_base, &s->shared_sram);
    }

    /* ========== NS FLASH (TrustZone dual-image) ========== */
    if (s->ns_flash_base != 0 && s->ns_flash_size != 0) {
        memory_region_init_rom(&s->ns_flash, NULL, "slab.ns_flash",
                               s->ns_flash_size, &error_fatal);
        memory_region_add_subregion(get_system_memory(),
                                    s->ns_flash_base, &s->ns_flash);
        info_report("  NS Flash:    0x%08x - 0x%08x (%u KB)",
                    s->ns_flash_base,
                    s->ns_flash_base + s->ns_flash_size - 1,
                    s->ns_flash_size / 1024);
    }

    /* Create peripheral proxy */
    proxy_dev = qdev_new(TYPE_SLAB_PERIPH_PROXY);
    object_property_add_child(OBJECT(machine), "periph-proxy", OBJECT(proxy_dev));
    qdev_prop_set_uint32(proxy_dev, "base", s->periph_base);
    qdev_prop_set_uint32(proxy_dev, "size", s->periph_size);
    qdev_prop_set_int32(proxy_dev, "tcp-port", s->tcp_port);
    qdev_prop_set_uint32(proxy_dev, "num-irqs", s->num_irqs);
    qdev_prop_set_string(proxy_dev, "name", "slab-periph");
    qdev_prop_set_bit(proxy_dev, "trustzone", s->trustzone);
    if (s->shm_name && strlen(s->shm_name) > 0) {
        qdev_prop_set_string(proxy_dev, "shm-name", s->shm_name);
    }
    sysbus_realize(SYS_BUS_DEVICE(proxy_dev), &error_fatal);
    /*
     * Map proxy at priority -1 so that flash, SRAM, and bootrom regions
     * (at priority 0) take precedence in overlapping address ranges.
     * This allows periph-base to be set below 0x40000000 (e.g. 0x14000000
     * for RP2040 XIP/SSI) without conflicting with SRAM at 0x20000000.
     */
    memory_region_add_subregion_overlap(get_system_memory(), s->periph_base,
        sysbus_mmio_get_region(SYS_BUS_DEVICE(proxy_dev), 0), -1);
    s->proxy = SLAB_PERIPH_PROXY(proxy_dev);

    /* ========== DEBUG PROXY ========== */
    if (s->debug_proxy) {
        DeviceState *dbg_proxy_dev = qdev_new(TYPE_SLAB_PERIPH_PROXY);
        object_property_add_child(OBJECT(machine),
                                  "debug-proxy-dev",
                                  OBJECT(dbg_proxy_dev));
        qdev_prop_set_uint32(dbg_proxy_dev, "base", ARM_PPB_BASE);
        qdev_prop_set_uint32(dbg_proxy_dev, "size", ARM_PPB_SIZE);
        qdev_prop_set_int32(dbg_proxy_dev, "tcp-port", s->tcp_port);
        qdev_prop_set_uint32(dbg_proxy_dev, "num-irqs", 0);
        qdev_prop_set_string(dbg_proxy_dev, "name", "slab-debug");
        sysbus_realize(SYS_BUS_DEVICE(dbg_proxy_dev), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(dbg_proxy_dev), 0, ARM_PPB_BASE);
        s->proxy_dbg = SLAB_PERIPH_PROXY(dbg_proxy_dev);
    }

    /* ========== CPU0 INITIALIZATION ========== */
    armv7m_dev = qdev_new(TYPE_ARMV7M);
    object_property_add_child(OBJECT(machine), "armv7m", OBJECT(armv7m_dev));
    qdev_prop_set_uint32(armv7m_dev, "num-irq", s->num_irqs);
    qdev_prop_set_string(armv7m_dev, "cpu-type",
                         g_strdup_printf("%s-arm-cpu", s->cpu_type));
    /*
     * Bitband is an ARMv7-M feature (Cortex-M3/M4/M7).  It was removed
     * in ARMv8-M (Cortex-M23/M33/M55/M85).  On ARMv8-M the former
     * bitband alias region 0x42000000-0x43FFFFFF is used for AHB2
     * peripherals (e.g. USB OTG HS at 0x42040000 on STM32U5).
     * Enabling bitband on v8-M would intercept those accesses and
     * convert them to single-bit operations on the wrong address.
     */
    qdev_prop_set_bit(armv7m_dev, "enable-bitband", !is_armv8m);
    qdev_connect_clock_in(armv7m_dev, "cpuclk", s->sysclk);
    object_property_set_link(OBJECT(armv7m_dev), "memory",
                            OBJECT(get_system_memory()), &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(armv7m_dev), &error_fatal);
    s->armv7m = armv7m_dev;

    /* Override MPU region count if configured.
     * QEMU's Cortex-M33 defaults to 16 regions, but many SoCs (e.g.
     * STM32U5) only implement 8.  Firmware may assert on the exact count
     * via MPU_TYPE.DREGION, so we must match the real hardware. */
    if (s->mpu_regions > 0) {
        ARMCPU *cpu = ARM_CPU(first_cpu);
        cpu->pmsav7_dregion = s->mpu_regions;
        info_report("  MPU regions: %u (override)", s->mpu_regions);
    }

    /*
     * TrustZone: QEMU's Cortex-M33/M55 always set ARM_FEATURE_M_SECURITY
     * which banks PSP into PSP_S/PSP_NS and requires SAU/IDAU setup.
     * When trustzone=off (default), disable the Security Extension so
     * the CPU uses a single unbanked PSP and accepts extended ARMv8-M
     * EXC_RETURN values without Non-Secure state transitions.
     */
    if (is_armv8m && !s->trustzone) {
        ARMCPU *cpu = ARM_CPU(first_cpu);
        unset_feature(&cpu->env, ARM_FEATURE_M_SECURITY);
        cpu->env.v7m.secure = false;
        info_report("  TrustZone:   disabled (M_SECURITY cleared)");
    } else if (s->trustzone) {
        info_report("  TrustZone:   enabled");
    }

    /* Connect proxy IRQs to NVIC */
    for (uint32_t i = 0; i < s->num_irqs; i++) {
        sysbus_connect_irq(SYS_BUS_DEVICE(proxy_dev), i,
                          qdev_get_gpio_in(armv7m_dev, i));
    }

    /* ========== USBIP DWC2 DEVICE CONTROLLER ========== */
    if (s->usbip_port > 0) {
        DeviceState *usbip_dev = qdev_new("slab-usbip");
        object_property_add_child(OBJECT(machine), "usbip", OBJECT(usbip_dev));
        qdev_prop_set_int32(usbip_dev, "usbip-port", s->usbip_port);
        sysbus_realize(SYS_BUS_DEVICE(usbip_dev), &error_fatal);
        /* Map at 0x50000000 with priority 1 (overrides peripheral proxy) */
        memory_region_add_subregion_overlap(get_system_memory(), 0x50000000,
            sysbus_mmio_get_region(SYS_BUS_DEVICE(usbip_dev), 0), 1);
        /* Connect OTG_FS IRQ (IRQn 67) */
        sysbus_connect_irq(SYS_BUS_DEVICE(usbip_dev), 0,
                          qdev_get_gpio_in(armv7m_dev, 67));
        info_report("  USBIP:       port %d (DWC2 @ 0x50000000, IRQ 67)",
                    s->usbip_port);
    }

    /* ========== CPU1 INITIALIZATION (DUAL-CORE) ========== */
    if (s->dual_core) {
        DeviceState *cpu1_dev;
        const char *cpu1_type_str = s->cpu1_type && strlen(s->cpu1_type) > 0
                                    ? s->cpu1_type : s->cpu_type;

        if (s->cpu1_sysclk_hz == 0) {
            s->cpu1_sysclk_hz = s->sysclk_hz / 2;
        }
        s->sysclk_cpu1 = clock_new(OBJECT(machine), "SYSCLK_CPU1");
        clock_set_hz(s->sysclk_cpu1, s->cpu1_sysclk_hz);

        cpu1_dev = qdev_new(TYPE_ARMV7M);
        object_property_add_child(OBJECT(machine), "armv7m-cpu1", OBJECT(cpu1_dev));
        qdev_prop_set_uint32(cpu1_dev, "num-irq", s->num_irqs);
        qdev_prop_set_string(cpu1_dev, "cpu-type",
                             g_strdup_printf("%s-arm-cpu", cpu1_type_str));
        qdev_prop_set_bit(cpu1_dev, "enable-bitband", true);
        qdev_connect_clock_in(cpu1_dev, "cpuclk", s->sysclk_cpu1);
        object_property_set_link(OBJECT(cpu1_dev), "memory",
                                OBJECT(get_system_memory()), &error_abort);

        if (s->cpu1_vector_table != 0) {
            qdev_prop_set_uint32(cpu1_dev, "init-svtor", s->cpu1_vector_table);
        }

        if (s->cpu1_start_powered) {
            sysbus_realize(SYS_BUS_DEVICE(cpu1_dev), &error_fatal);
        }
        s->armv7m_cpu1 = cpu1_dev;
    }

    /* ========== FIRMWARE LOADING ========== */
    if (s->bootrom_file && strlen(s->bootrom_file) > 0) {
        Error *err = NULL;
        ssize_t loaded = load_image_targphys(s->bootrom_file,
                                              s->bootrom_base,
                                              s->bootrom_size, &err);
        if (loaded < 0) {
            error_report("Could not load bootrom '%s'", s->bootrom_file);
            error_free(err);
        }
    }

    if (machine->firmware) {
        armv7m_load_kernel(ARM_CPU(first_cpu), machine->firmware,
                          s->flash_base, s->flash_size);
    } else if (machine->kernel_filename) {
        armv7m_load_kernel(ARM_CPU(first_cpu), machine->kernel_filename,
                          s->flash_base, s->flash_size);
    } else {
        warn_report("No firmware specified. Use -kernel <file.bin>");
    }
}

/*
 * Machine property setters/getters
 *
 * QEMU machines use object properties instead of device properties.
 * These are set via -global slab-cortex-m.<property>=<value>
 */

static char *slab_cortex_m_get_cpu_type(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup(s->cpu_type ? s->cpu_type : "cortex-m4");
}

static void slab_cortex_m_set_cpu_type(Object *obj,
                                       const char *value,
                                       Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    g_free(s->cpu_type);
    s->cpu_type = g_strdup(value);
}

static char *slab_cortex_m_get_bootrom(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup(s->bootrom_file ? s->bootrom_file : "");
}

static void slab_cortex_m_set_bootrom(Object *obj,
                                      const char *value,
                                      Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    g_free(s->bootrom_file);
    s->bootrom_file = g_strdup(value);
}

static char *slab_cortex_m_get_shm_name(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup(s->shm_name ? s->shm_name : "");
}

static void slab_cortex_m_set_shm_name(Object *obj,
                                       const char *value,
                                       Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    g_free(s->shm_name);
    s->shm_name = g_strdup(value);
}

static bool slab_cortex_m_get_trustzone(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return s->trustzone;
}

static void slab_cortex_m_set_trustzone(Object *obj, bool value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    s->trustzone = value;
}

static bool slab_cortex_m_get_dual_core(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return s->dual_core;
}

static void slab_cortex_m_set_dual_core(Object *obj, bool value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    s->dual_core = value;
}

static bool slab_cortex_m_get_debug_proxy(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return s->debug_proxy;
}

static void slab_cortex_m_set_debug_proxy(Object *obj, bool value,
                                          Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    s->debug_proxy = value;
}

static char *slab_cortex_m_get_tcp_port(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("%d", s->tcp_port);
}

static void slab_cortex_m_set_tcp_port(Object *obj,
                                       const char *value,
                                       Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    long port;

    if (qemu_strtol(value, NULL, 10, &port)) {
        error_setg(errp, "Invalid tcp-port value: '%s'", value);
        return;
    }
    if (port <= 0 || port > 65535) {
        error_setg(errp, "tcp-port must be between 1 and 65535");
        return;
    }
    s->tcp_port = port;
}

static char *slab_cortex_m_get_usbip_port(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("%d", s->usbip_port);
}

static void slab_cortex_m_set_usbip_port(Object *obj,
                                         const char *value,
                                         Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    long port;

    if (qemu_strtol(value, NULL, 10, &port)) {
        error_setg(errp, "Invalid usbip-port value: '%s'", value);
        return;
    }
    if (port < 0 || port > 65535) {
        error_setg(errp,
                   "usbip-port must be 0-65535 (0 = disabled)");
        return;
    }
    s->usbip_port = port;
}

/* ---- Memory layout property getters/setters ---- */

static char *slab_cortex_m_get_flash_base(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%08x", s->flash_base);
}

static void slab_cortex_m_set_flash_base(Object *obj,
                                         const char *value,
                                         Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid flash-base: '%s'", value);
        return;
    }
    s->flash_base = (uint32_t)v;
}

static char *slab_cortex_m_get_flash_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%x", s->flash_size);
}

static void slab_cortex_m_set_flash_size(Object *obj,
                                         const char *value,
                                         Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid flash-size: '%s'", value);
        return;
    }
    if (v == 0 || v > 64 * 1024 * 1024) {
        error_setg(errp, "flash-size must be between 1 and 64MB");
        return;
    }
    s->flash_size = (uint32_t)v;
}

static char *slab_cortex_m_get_sram_base(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%08x", s->sram_base);
}

static void slab_cortex_m_set_sram_base(Object *obj,
                                        const char *value,
                                        Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid sram-base: '%s'", value);
        return;
    }
    s->sram_base = (uint32_t)v;
}

static char *slab_cortex_m_get_sram_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%x", s->sram_size);
}

static void slab_cortex_m_set_sram_size(Object *obj,
                                        const char *value,
                                        Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid sram-size: '%s'", value);
        return;
    }
    if (v == 0 || v > 64 * 1024 * 1024) {
        error_setg(errp, "sram-size must be between 1 and 64MB");
        return;
    }
    s->sram_size = (uint32_t)v;
}

static char *slab_cortex_m_get_sysclk_hz(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("%u", s->sysclk_hz);
}

static void slab_cortex_m_set_sysclk_hz(Object *obj,
                                        const char *value,
                                        Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid sysclk-hz: '%s'", value);
        return;
    }
    if (v == 0 || v > 1000000000) {
        error_setg(errp, "sysclk-hz must be between 1 and 1000000000");
        return;
    }
    s->sysclk_hz = (uint32_t)v;
}

static char *slab_cortex_m_get_mpu_regions(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("%u", s->mpu_regions);
}

static void slab_cortex_m_set_mpu_regions(Object *obj,
                                          const char *value,
                                          Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid mpu-regions: '%s'", value);
        return;
    }
    if (v > 16) {
        error_setg(errp, "mpu-regions must be 0-16 (0 = CPU default)");
        return;
    }
    s->mpu_regions = (uint32_t)v;
}

static char *slab_cortex_m_get_ns_flash_base(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%08x", s->ns_flash_base);
}

static void slab_cortex_m_set_ns_flash_base(Object *obj,
                                            const char *value,
                                            Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid ns-flash-base: '%s'", value);
        return;
    }
    s->ns_flash_base = (uint32_t)v;
}

static char *slab_cortex_m_get_ns_flash_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%08x", s->ns_flash_size);
}

static void slab_cortex_m_set_ns_flash_size(Object *obj,
                                            const char *value,
                                            Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid ns-flash-size: '%s'", value);
        return;
    }
    if (v > 64 * 1024 * 1024) {
        error_setg(errp, "ns-flash-size must be <= 64MB");
        return;
    }
    s->ns_flash_size = (uint32_t)v;
}

/* ---- Bootrom layout property getters/setters ---- */

static char *slab_cortex_m_get_bootrom_base(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%08x", s->bootrom_base);
}

static void slab_cortex_m_set_bootrom_base(Object *obj,
                                           const char *value,
                                           Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid bootrom-base: '%s'", value);
        return;
    }
    s->bootrom_base = (uint32_t)v;
}

static char *slab_cortex_m_get_bootrom_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%x", s->bootrom_size);
}

static void slab_cortex_m_set_bootrom_size(Object *obj,
                                           const char *value,
                                           Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid bootrom-size: '%s'", value);
        return;
    }
    if (v == 0 || v > 1024 * 1024) {
        error_setg(errp, "bootrom-size must be between 1 and 1MB");
        return;
    }
    s->bootrom_size = (uint32_t)v;
}

/* ---- Peripheral proxy range property getters/setters ---- */

static char *slab_cortex_m_get_periph_base(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%08x", s->periph_base);
}

static void slab_cortex_m_set_periph_base(Object *obj,
                                          const char *value,
                                          Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid periph-base: '%s'", value);
        return;
    }
    s->periph_base = (uint32_t)v;
}

static char *slab_cortex_m_get_periph_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%x", s->periph_size);
}

static void slab_cortex_m_set_periph_size(Object *obj,
                                          const char *value,
                                          Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v;

    if (qemu_strtou64(value, NULL, 0, &v)) {
        error_setg(errp, "Invalid periph-size: '%s'", value);
        return;
    }
    if (v == 0 || v > 0xC0000000ULL) {
        error_setg(errp, "periph-size must be between 1 and 3GB");
        return;
    }
    s->periph_size = (uint32_t)v;
}

static void slab_cortex_m_instance_init(Object *obj)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);

    /* Set defaults */
    s->cpu_type = NULL;
    s->flash_base = 0x08000000;
    s->flash_size = 0x100000;
    s->sram_base = 0x20000000;
    s->sram_size = 0x40000;
    s->periph_base = 0x40000000;
    s->periph_size = 0x20000000;
    s->tcp_port = 5555;
    s->num_irqs = 240;
    s->sysclk_hz = 168000000;
    s->bootrom_base = 0x1FFF0000;
    s->bootrom_size = 0x10000;
    s->shared_sram_base = 0x38000000;
    s->shared_sram_size = 0x8000;
    s->ns_flash_base = 0;  /* 0 = disabled */
    s->ns_flash_size = 0;
}

static void slab_cortex_m_class_init(ObjectClass *oc, const void *data)
{
    MachineClass *mc = MACHINE_CLASS(oc);

    mc->desc = "Slab Cortex-M - Generic ARM Cortex-M with peripheral export";
    mc->init = slab_cortex_m_init;
    mc->max_cpus = 2;  /* Support dual-core */
    mc->default_cpus = 1;
    mc->default_ram_size = 256 * 1024;

    /*
     * Add machine properties using object_class_property_add_*
     * These can be set via: -M slab-cortex-m,<property>=<value>
     */

    /* CPU configuration */
    object_class_property_add_str(oc, "cpu-type",
                                  slab_cortex_m_get_cpu_type,
                                  slab_cortex_m_set_cpu_type);
    object_class_property_set_description(oc, "cpu-type",
        "ARM Cortex-M CPU type (cortex-m0, cortex-m0+, cortex-m3, "
        "cortex-m4, cortex-m7, cortex-m23, cortex-m33, cortex-m55)");

    /* Bootrom configuration */
    object_class_property_add_str(oc, "bootrom-file",
                                  slab_cortex_m_get_bootrom,
                                  slab_cortex_m_set_bootrom);
    object_class_property_set_description(oc, "bootrom-file",
        "Path to bootrom binary file (optional)");

    /* Shared memory */
    object_class_property_add_str(oc, "shm-name",
                                  slab_cortex_m_get_shm_name,
                                  slab_cortex_m_set_shm_name);
    object_class_property_set_description(oc, "shm-name",
        "POSIX shared memory name for low-latency peripheral proxy");

    /* TrustZone */
    object_class_property_add_bool(oc, "trustzone",
                                   slab_cortex_m_get_trustzone,
                                   slab_cortex_m_set_trustzone);
    object_class_property_set_description(oc, "trustzone",
        "Enable TrustZone security extensions (ARMv8-M only)");

    /* Dual-core */
    object_class_property_add_bool(oc, "dual-core",
                                   slab_cortex_m_get_dual_core,
                                   slab_cortex_m_set_dual_core);
    object_class_property_set_description(oc, "dual-core",
        "Enable second CPU core for asymmetric multiprocessing");

    /* TCP port for peripheral proxy */
    object_class_property_add_str(oc, "tcp-port",
                                  slab_cortex_m_get_tcp_port,
                                  slab_cortex_m_set_tcp_port);
    object_class_property_set_description(oc, "tcp-port",
        "TCP port for peripheral proxy server (default: 5555)");

    /* Debug proxy */
    object_class_property_add_bool(oc, "debug-proxy",
                                   slab_cortex_m_get_debug_proxy,
                                   slab_cortex_m_set_debug_proxy);
    object_class_property_set_description(oc, "debug-proxy",
        "Forward debug region (0xE0000000) accesses to peripheral proxy");

    /* USBIP port */
    object_class_property_add_str(oc, "usbip-port",
                                  slab_cortex_m_get_usbip_port,
                                  slab_cortex_m_set_usbip_port);
    object_class_property_set_description(oc, "usbip-port",
        "USBIP server port for DWC2 USB device controller (0 = disabled, default: 0)");

    /* System clock */
    object_class_property_add_str(oc, "sysclk-hz",
                                  slab_cortex_m_get_sysclk_hz,
                                  slab_cortex_m_set_sysclk_hz);
    object_class_property_set_description(oc, "sysclk-hz",
        "System clock frequency in Hz (default: 168000000)");

    /* MPU region count override */
    object_class_property_add_str(oc, "mpu-regions",
                                  slab_cortex_m_get_mpu_regions,
                                  slab_cortex_m_set_mpu_regions);
    object_class_property_set_description(oc, "mpu-regions",
        "Override MPU region count (0 = CPU default, e.g. 8 for STM32U5)");

    /* Memory layout properties */
    object_class_property_add_str(oc, "flash-base",
                                  slab_cortex_m_get_flash_base,
                                  slab_cortex_m_set_flash_base);
    object_class_property_set_description(oc, "flash-base",
        "Flash base address (default: 0x08000000)");

    object_class_property_add_str(oc, "flash-size",
                                  slab_cortex_m_get_flash_size,
                                  slab_cortex_m_set_flash_size);
    object_class_property_set_description(oc, "flash-size",
        "Flash size in bytes (default: 0x100000 = 1MB)");

    object_class_property_add_str(oc, "sram-base",
                                  slab_cortex_m_get_sram_base,
                                  slab_cortex_m_set_sram_base);
    object_class_property_set_description(oc, "sram-base",
        "SRAM base address (default: 0x20000000)");

    object_class_property_add_str(oc, "sram-size",
                                  slab_cortex_m_get_sram_size,
                                  slab_cortex_m_set_sram_size);
    object_class_property_set_description(oc, "sram-size",
        "SRAM size in bytes (default: 0x40000 = 256KB)");

    object_class_property_add_str(oc, "ns-flash-base",
                                  slab_cortex_m_get_ns_flash_base,
                                  slab_cortex_m_set_ns_flash_base);
    object_class_property_set_description(oc, "ns-flash-base",
        "Non-secure flash base address for TrustZone (default: 0 = disabled)");

    object_class_property_add_str(oc, "ns-flash-size",
                                  slab_cortex_m_get_ns_flash_size,
                                  slab_cortex_m_set_ns_flash_size);
    object_class_property_set_description(oc, "ns-flash-size",
        "Non-secure flash size in bytes (default: 0 = disabled)");

    /* Bootrom layout */
    object_class_property_add_str(oc, "bootrom-base",
                                  slab_cortex_m_get_bootrom_base,
                                  slab_cortex_m_set_bootrom_base);
    object_class_property_set_description(oc, "bootrom-base",
        "Bootrom base address (default: 0x1FFF0000, set 0 for RP2040)");

    object_class_property_add_str(oc, "bootrom-size",
                                  slab_cortex_m_get_bootrom_size,
                                  slab_cortex_m_set_bootrom_size);
    object_class_property_set_description(oc, "bootrom-size",
        "Bootrom size in bytes (default: 0x10000 = 64KB)");

    /* Peripheral proxy range */
    object_class_property_add_str(oc, "periph-base",
                                  slab_cortex_m_get_periph_base,
                                  slab_cortex_m_set_periph_base);
    object_class_property_set_description(oc, "periph-base",
        "Peripheral proxy base address (default: 0x40000000)");

    object_class_property_add_str(oc, "periph-size",
                                  slab_cortex_m_get_periph_size,
                                  slab_cortex_m_set_periph_size);
    object_class_property_set_description(oc, "periph-size",
        "Peripheral proxy region size (default: 0x20000000 = 512MB)");
}

static const TypeInfo slab_cortex_m_info = {
    .name = TYPE_SLAB_CORTEX_M_MACHINE,
    .parent = TYPE_MACHINE,
    .instance_size = sizeof(SlabCortexMState),
    .instance_init = slab_cortex_m_instance_init,
    .class_init = slab_cortex_m_class_init,
    .interfaces = arm_machine_interfaces,
};


/* ========================================================================= */
/*                           TYPE REGISTRATION                               */
/* ========================================================================= */

static void slab_cortex_m_register_types(void)
{
    type_register_static(&slab_proxy_info);
    type_register_static(&slab_cortex_m_info);
}

type_init(slab_cortex_m_register_types)
