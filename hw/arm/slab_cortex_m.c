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
 *   qemu-system-arm -M slab-cortex-m \
 *     -global slab-cortex-m.cpu-type=cortex-m4 \
 *     -global slab-cortex-m.tcp-port=5555 \
 *     -kernel firmware.bin
 *
 *   # With shared memory (lower latency)
 *   qemu-system-arm -M slab-cortex-m \
 *     -global slab-cortex-m.cpu-type=cortex-m4 \
 *     -global slab-cortex-m.shm-name=/slab_periph \
 *     -kernel firmware.bin
 *
 *   # Dual-Core with TrustZone
 *   qemu-system-arm -M slab-cortex-m \
 *     -global slab-cortex-m.cpu-type=cortex-m33 \
 *     -global slab-cortex-m.dual-core=true \
 *     -global slab-cortex-m.trustzone=true \
 *     -kernel secure_firmware.bin
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
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

#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/mman.h>
#include <sys/stat.h>

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
 *   [36:64] - Reserved
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

/* MPU state area in SHM data region (offset 64) */
#define SHM_MPU_OFFSET      SHM_HEADER_SIZE  /* starts at byte 64 */
#define SHM_MPU_MAX_REGIONS 8
/* Layout: [0:4] MPU_CTRL, [4:68] 8 regions × {RBAR(4), RASR(4)} = 68 bytes */
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

    /* Register cache (for disconnected operation) */
    GHashTable *reg_cache;

    /* IRQ outputs to NVIC */
    qemu_irq irqs[MAX_IRQS];
    uint32_t num_irqs;

    /* Receive buffer for async IRQ commands */
    uint8_t recv_buf[PROXY_RECV_BUF_SIZE];
    int recv_len;

    /* TrustZone: current transaction security state */
    bool current_secure;
};

/* Forward declarations */
static void slab_proxy_try_connect_tcp(SlabPeriphProxyState *s);
static void slab_proxy_check_incoming(SlabPeriphProxyState *s);
static bool slab_proxy_init_shm(SlabPeriphProxyState *s);

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
    CPUARMState *env;
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
    mpu_area = (volatile uint32_t *)((uint8_t *)s->shm_ptr + SHM_MPU_OFFSET);

    /* Write MPU_CTRL */
    mpu_area[0] = env->v7m.mpu_ctrl[0];  /* M_REG_NS bank */

    /* Write per-region RBAR + RASR */
    for (i = 0; i < SHM_MPU_MAX_REGIONS && i < cpu->pmsav7_dregion; i++) {
        uint32_t rbar = env->pmsav7.drbar[i];
        uint32_t rasr = env->pmsav7.drsr[i] | (env->pmsav7.dracr[i] << 16);
        mpu_area[1 + i * 2] = rbar;
        mpu_area[1 + i * 2 + 1] = rasr;
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
    CPUARMState *env;
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

    snap = (volatile uint32_t *)((uint8_t *)s->shm_ptr + SHM_SNAPSHOT_OFFSET);

    /* Header: architecture + register count */
    snap[0] = 0;   /* ARCH_ARM_CORTEX_M */
    snap[1] = 23;  /* Core registers (R0-R12, SP, LR, PC, xPSR, MSP, PSP,
                      CONTROL, PRIMASK, FAULTMASK, BASEPRI) */

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
    CPUARMState *env;
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

    snap = (volatile uint32_t *)((uint8_t *)s->shm_ptr + SHM_SNAPSHOT_OFFSET);

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
    uint32_t irq_status = header[8];
    for (uint32_t i = 0; i < s->num_irqs && i < 32; i++) {
        qemu_set_irq(s->irqs[i], (irq_status >> i) & 1);
    }

    return result;
}

/*
 * TCP transaction
 */
static uint64_t slab_proxy_tcp_transaction(SlabPeriphProxyState *s, bool is_write,
                                            uint32_t addr, uint32_t size,
                                            uint64_t write_val)
{
    uint8_t req[16];
    uint8_t resp[8];
    int req_len;
    ssize_t n;
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

    /* Send request */
    n = send(s->client_fd, req, req_len, MSG_NOSIGNAL);
    if (n != req_len) {
        close(s->client_fd);
        s->client_fd = -1;
        s->tcp_connected = false;
        return 0;
    }

    /* Receive response (blocking).
     * The Python server may send IRQ packets (6 bytes, starting with 'I')
     * interleaved with the transaction response (5 bytes). This can happen
     * when trigger_irq() is called during a register read/write handler.
     * Handle IRQ packets inline until we get the actual response. */
    while (1) {
        n = recv(s->client_fd, resp, 1, MSG_WAITALL);
        if (n != 1) {
            close(s->client_fd);
            s->client_fd = -1;
            s->tcp_connected = false;
            return 0;
        }

        if (resp[0] == 'I') {
            /* Inline IRQ packet: read remaining 5 bytes */
            uint8_t irq_buf[5];
            n = recv(s->client_fd, irq_buf, 5, MSG_WAITALL);
            if (n != 5) {
                close(s->client_fd);
                s->client_fd = -1;
                s->tcp_connected = false;
                return 0;
            }
            uint32_t irq_num = irq_buf[0] | (irq_buf[1] << 8) |
                               (irq_buf[2] << 16) | (irq_buf[3] << 24);
            int level = irq_buf[4];
            if (irq_num < s->num_irqs) {
                qemu_set_irq(s->irqs[irq_num], level);
            }
            continue;  /* Read next byte - might be another IRQ or the response */
        }

        /* First byte of transaction response, read remaining 4 bytes */
        n = recv(s->client_fd, resp + 1, 4, MSG_WAITALL);
        if (n != 4) {
            close(s->client_fd);
            s->client_fd = -1;
            s->tcp_connected = false;
            return 0;
        }
        break;
    }

    value = resp[0] | (resp[1] << 8) | (resp[2] << 16) | (resp[3] << 24);

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
 * MemoryRegion read callback
 */
static uint64_t slab_proxy_read(void *opaque, hwaddr offset, unsigned size)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    uint32_t addr = s->base_addr + offset;

    s->current_secure = s->trustzone_enabled ? false : true;
    slab_proxy_check_incoming(s);

    return slab_proxy_transaction(s, false, addr, size, 0);
}

/*
 * MemoryRegion write callback
 */
static void slab_proxy_write(void *opaque, hwaddr offset, uint64_t value,
                             unsigned size)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    uint32_t addr = s->base_addr + offset;

    s->current_secure = s->trustzone_enabled ? false : true;

    /* Update cache immediately */
    g_hash_table_insert(s->reg_cache, GUINT_TO_POINTER(addr),
                       GUINT_TO_POINTER((uint32_t)value));

    slab_proxy_check_incoming(s);
    slab_proxy_transaction(s, true, addr, size, value);
}

static const MemoryRegionOps slab_proxy_ops = {
    .read = slab_proxy_read,
    .write = slab_proxy_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .impl = {
        .min_access_size = 1,
        .max_access_size = 4,
    },
};

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
    s->mode = PROXY_MODE_SHM;

    info_report("Slab Proxy [%s]: Shared memory %s ready (%zu bytes)",
                s->name, s->shm_name, s->shm_size);
    return true;
}

/*
 * Check for incoming IRQ injection commands (TCP)
 */
static void slab_proxy_check_incoming(SlabPeriphProxyState *s)
{
    uint8_t buf[8];
    ssize_t n;

    if (s->mode == PROXY_MODE_SHM) {
        /* For SHM, IRQs are checked during transactions */
        return;
    }

    if (!s->tcp_connected || s->client_fd < 0) {
        return;
    }

    /* Non-blocking receive */
    while (1) {
        n = recv(s->client_fd, buf, 6, MSG_DONTWAIT);
        if (n <= 0) {
            break;
        }

        if (n == 6 && buf[0] == 'I') {
            uint32_t irq_num = buf[1] | (buf[2] << 8) | (buf[3] << 16) | (buf[4] << 24);
            int level = buf[5];

            if (irq_num < s->num_irqs) {
                qemu_set_irq(s->irqs[irq_num], level);
            }
        }
    }
}

/*
 * FD handler callback: called by QEMU main loop when data arrives on TCP socket.
 * This allows IRQ injection from the Python server to work even when the
 * firmware is not accessing peripheral registers (e.g., in its main loop).
 */
static void slab_proxy_fd_read(void *opaque)
{
    SlabPeriphProxyState *s = SLAB_PERIPH_PROXY(opaque);
    slab_proxy_check_incoming(s);
}

/*
 * Try to establish TCP connection
 */
static void slab_proxy_try_connect_tcp(SlabPeriphProxyState *s)
{
    struct sockaddr_in addr;
    int fd;
    int opt = 1;

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

    s->client_fd = fd;
    s->tcp_connected = true;

    /* Register FD handler so QEMU main loop calls us when data arrives.
     * This is critical for IRQ delivery when firmware is idle. */
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

    /* TrustZone configuration */
    bool trustzone;
    uint32_t secure_flash_size;
    uint32_t secure_sram_size;

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

    /* Apply defaults (only for fields that can't be zero).
     * Memory layout defaults are set in instance_init() to allow
     * flash_base=0 (e.g. nRF52840). */
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
    info_report("  Flash:       0x%08X - 0x%08X (%d KB)",
                s->flash_base, s->flash_base + s->flash_size - 1,
                s->flash_size / 1024);
    info_report("  SRAM:        0x%08X - 0x%08X (%d KB)",
                s->sram_base, s->sram_base + s->sram_size - 1,
                s->sram_size / 1024);
    info_report("  Peripherals: 0x%08X - 0x%08X",
                s->periph_base, s->periph_base + s->periph_size - 1);
    info_report("  TCP Port:    %d", s->tcp_port);
    if (s->shm_name && strlen(s->shm_name) > 0) {
        info_report("  Shared Mem:  %s", s->shm_name);
    }
    info_report("  IRQs:        %d", s->num_irqs);
    info_report("  Clock:       %d Hz", s->sysclk_hz);
    info_report("================================================================");

    /* Create system clock */
    s->sysclk = clock_new(OBJECT(machine), "SYSCLK");
    clock_set_hz(s->sysclk, s->sysclk_hz);

    /* ========== BOOTROM SETUP ========== */
    if (s->bootrom_file && strlen(s->bootrom_file) > 0) {
        if (s->bootrom_size == 0) {
            s->bootrom_size = 0x10000;  /* 64KB */
        }
        if (s->bootrom_base == 0) {
            s->bootrom_base = 0x1FFF0000;
        }

        memory_region_init_rom(&s->bootrom, NULL, "slab.bootrom",
                               s->bootrom_size, &error_fatal);
        memory_region_add_subregion(get_system_memory(), s->bootrom_base, &s->bootrom);
    }

    /* Initialize Flash memory */
    memory_region_init_rom(&s->flash, NULL, "slab.flash",
                           s->flash_size, &error_fatal);
    memory_region_add_subregion(get_system_memory(), s->flash_base, &s->flash);

    /* Flash alias at address 0 for vector table.
     * Skip when flash is already at 0 (e.g. nRF52840) to avoid overlap. */
    if (s->flash_base != 0) {
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

    /* Create peripheral proxy */
    proxy_dev = qdev_new(TYPE_SLAB_PERIPH_PROXY);
    object_property_add_child(OBJECT(machine), "periph-proxy", OBJECT(proxy_dev));
    qdev_prop_set_uint32(proxy_dev, "base", s->periph_base);
    qdev_prop_set_uint32(proxy_dev, "size", s->periph_size);
    qdev_prop_set_int32(proxy_dev, "tcp-port", s->tcp_port);
    qdev_prop_set_uint32(proxy_dev, "num-irqs", s->num_irqs);
    qdev_prop_set_string(proxy_dev, "name", "slab-periph");
    if (s->shm_name && strlen(s->shm_name) > 0) {
        qdev_prop_set_string(proxy_dev, "shm-name", s->shm_name);
    }
    sysbus_realize(SYS_BUS_DEVICE(proxy_dev), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(proxy_dev), 0, s->periph_base);
    s->proxy = SLAB_PERIPH_PROXY(proxy_dev);

    /* ========== DEBUG PROXY ========== */
    if (s->debug_proxy) {
        DeviceState *dbg_proxy_dev = qdev_new(TYPE_SLAB_PERIPH_PROXY);
        object_property_add_child(OBJECT(machine), "debug-proxy-dev", OBJECT(dbg_proxy_dev));
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
    qdev_prop_set_bit(armv7m_dev, "enable-bitband", true);
    qdev_connect_clock_in(armv7m_dev, "cpuclk", s->sysclk);
    object_property_set_link(OBJECT(armv7m_dev), "memory",
                            OBJECT(get_system_memory()), &error_abort);
    sysbus_realize(SYS_BUS_DEVICE(armv7m_dev), &error_fatal);
    s->armv7m = armv7m_dev;

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

static void slab_cortex_m_set_cpu_type(Object *obj, const char *value, Error **errp)
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

static void slab_cortex_m_set_bootrom(Object *obj, const char *value, Error **errp)
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

static void slab_cortex_m_set_shm_name(Object *obj, const char *value, Error **errp)
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

static void slab_cortex_m_set_debug_proxy(Object *obj, bool value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    s->debug_proxy = value;
}

static char *slab_cortex_m_get_tcp_port(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("%d", s->tcp_port);
}

static void slab_cortex_m_set_tcp_port(Object *obj, const char *value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    int port = atoi(value);
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

static void slab_cortex_m_set_usbip_port(Object *obj, const char *value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    int port = atoi(value);
    if (port < 0 || port > 65535) {
        error_setg(errp, "usbip-port must be between 0 and 65535 (0 = disabled)");
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

static void slab_cortex_m_set_flash_base(Object *obj, const char *value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v = strtoull(value, NULL, 0);
    s->flash_base = (uint32_t)v;
}

static char *slab_cortex_m_get_flash_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%x", s->flash_size);
}

static void slab_cortex_m_set_flash_size(Object *obj, const char *value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v = strtoull(value, NULL, 0);
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

static void slab_cortex_m_set_sram_base(Object *obj, const char *value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v = strtoull(value, NULL, 0);
    s->sram_base = (uint32_t)v;
}

static char *slab_cortex_m_get_sram_size(Object *obj, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    return g_strdup_printf("0x%x", s->sram_size);
}

static void slab_cortex_m_set_sram_size(Object *obj, const char *value, Error **errp)
{
    SlabCortexMState *s = SLAB_CORTEX_M_MACHINE(obj);
    uint64_t v = strtoull(value, NULL, 0);
    if (v == 0 || v > 64 * 1024 * 1024) {
        error_setg(errp, "sram-size must be between 1 and 64MB");
        return;
    }
    s->sram_size = (uint32_t)v;
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
