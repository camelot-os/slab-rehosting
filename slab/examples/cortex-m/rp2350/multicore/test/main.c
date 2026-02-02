/*
 * RP2350 Multicore Test Firmware
 *
 * Tests dual-core Cortex-M33 functionality:
 * - Inter-core FIFO communication
 * - Spinlock synchronization
 * - Shared memory access
 * - TrustZone (ARM mode)
 * - CDC ACM interface for test commands
 *
 * Commands via CDC:
 *   PING           -> PONG
 *   CPUID          -> Return current core ID
 *   ARCH           -> Return architecture (ARM/RISCV)
 *   FIFO xxxx      -> Send value to other core via FIFO, return response
 *   SPINLOCK n     -> Test spinlock n (0-31)
 *   SHARED xxxx    -> Write to shared memory, other core increments, read back
 *   STRESS nn      -> Run nn FIFO round-trips
 *   SHA256 xxxx    -> Compute SHA-256 of hex data (RP2350-specific)
 *   TRNG           -> Get random number from TRNG (RP2350-specific)
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include <stdbool.h>
#include "rp2350.h"

/* CDC Interface (memory-mapped) */
#define CDC_OUT     (*(volatile uint32_t *)0xE0000000)
#define CDC_IN      (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS  (*(volatile uint32_t *)0xE0000008)
#define CDC_RX_READY    0x01
#define CDC_TX_READY    0x02

/* Shared SRAM region for multicore communication */
#define SHARED_BASE     0x20078000  /* Top of SRAM (RP2350 has more SRAM) */
typedef struct {
    volatile uint32_t core1_ready;
    volatile uint32_t shared_value;
    volatile uint32_t command;
    volatile uint32_t response;
} SharedData;
#define SHARED ((SharedData *)SHARED_BASE)

/* Multicore commands via shared memory */
#define CMD_NONE        0x00000000
#define CMD_INCREMENT   0x00000001
#define CMD_MULTIPLY    0x00000002
#define CMD_DONE        0xFFFFFFFF

/* Core 1 entry point address */
#define CORE1_ENTRY     0x10001000

/* String helpers */
static void cdc_putc(char c)
{
    CDC_OUT = c;
}

static void cdc_puts(const char *s)
{
    while (*s) {
        cdc_putc(*s++);
    }
}

static void cdc_put_hex8(uint8_t val)
{
    const char hex[] = "0123456789abcdef";
    cdc_putc(hex[(val >> 4) & 0xF]);
    cdc_putc(hex[val & 0xF]);
}

static void cdc_put_hex32(uint32_t val)
{
    cdc_put_hex8((val >> 24) & 0xFF);
    cdc_put_hex8((val >> 16) & 0xFF);
    cdc_put_hex8((val >> 8) & 0xFF);
    cdc_put_hex8(val & 0xFF);
}

static int cdc_getline(char *buf, int maxlen)
{
    int i = 0;
    while (i < maxlen - 1) {
        while (!(CDC_STATUS & CDC_RX_READY));
        char c = CDC_IN & 0xFF;
        if (c == '\n' || c == '\r') break;
        buf[i++] = c;
    }
    buf[i] = '\0';
    return i;
}

static uint32_t parse_hex(const char *s, int digits)
{
    uint32_t val = 0;
    for (int i = 0; i < digits && s[i]; i++) {
        char c = s[i];
        int d;
        if (c >= '0' && c <= '9') d = c - '0';
        else if (c >= 'a' && c <= 'f') d = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') d = c - 'A' + 10;
        else break;
        val = (val << 4) | d;
    }
    return val;
}

static int strcmp(const char *a, const char *b)
{
    while (*a && *b && *a == *b) { a++; b++; }
    return *a - *b;
}

static int strncmp(const char *a, const char *b, int n)
{
    for (int i = 0; i < n; i++) {
        if (a[i] != b[i]) return a[i] - b[i];
        if (a[i] == 0) return 0;
    }
    return 0;
}

/* ============================================================================
 * SIO / Multicore Functions
 * ============================================================================ */

static uint32_t get_core_id(void)
{
    return SIO->CPUID;
}

static bool fifo_push(uint32_t value)
{
    /* Check if TX FIFO has space (RDY bit) */
    if (SIO->FIFO_ST & 0x02) {
        SIO->FIFO_WR = value;
        return true;
    }
    return false;
}

static bool fifo_pop(uint32_t *value)
{
    /* Check if RX FIFO has data (VLD bit) */
    if (SIO->FIFO_ST & 0x01) {
        *value = SIO->FIFO_RD;
        return true;
    }
    return false;
}

static bool fifo_push_blocking(uint32_t value, uint32_t timeout)
{
    while (timeout > 0) {
        if (fifo_push(value)) return true;
        timeout--;
    }
    return false;
}

static bool fifo_pop_blocking(uint32_t *value, uint32_t timeout)
{
    while (timeout > 0) {
        if (fifo_pop(value)) return true;
        timeout--;
    }
    return false;
}

static bool spinlock_try_claim(uint32_t lock_num)
{
    if (lock_num >= 32) return false;
    /* Reading spinlock attempts to claim it; returns non-zero if claimed */
    return ((&SIO->SPINLOCK0)[lock_num] != 0);
}

static void spinlock_release(uint32_t lock_num)
{
    if (lock_num < 32) {
        /* Writing any value releases the spinlock */
        (&SIO->SPINLOCK0)[lock_num] = 0;
    }
}

/* ============================================================================
 * RP2350-Specific: SHA256 Hardware Accelerator
 * ============================================================================ */

static void sha256_compute(const uint8_t *data, uint32_t len, uint8_t *hash)
{
    /* Start hash */
    SHA256->CSR = (1 << 1) | (1 << 0);  /* START | EN */

    /* Feed data (in 32-bit words) */
    const uint32_t *words = (const uint32_t *)data;
    uint32_t word_count = len / 4;

    for (uint32_t i = 0; i < word_count; i++) {
        while (!(SHA256->CSR & (1 << 16)));  /* Wait for WDATA_RDY */
        SHA256->WDATA = words[i];
    }

    /* Handle remaining bytes if any */
    uint32_t remain = len % 4;
    if (remain > 0) {
        uint32_t last = 0;
        for (uint32_t i = 0; i < remain; i++) {
            last |= data[len - remain + i] << (i * 8);
        }
        while (!(SHA256->CSR & (1 << 16)));
        SHA256->WDATA = last;
    }

    /* Finalize (disable to complete) */
    SHA256->CSR = 0;

    /* Wait for result */
    while (!(SHA256->CSR & (1 << 24)));  /* SUM_VLD */

    /* Read hash result (big-endian format) */
    for (int i = 0; i < 8; i++) {
        uint32_t word = (&SHA256->SUM0)[i];
        hash[i*4 + 0] = (word >> 24) & 0xFF;
        hash[i*4 + 1] = (word >> 16) & 0xFF;
        hash[i*4 + 2] = (word >> 8) & 0xFF;
        hash[i*4 + 3] = word & 0xFF;
    }
}

/* ============================================================================
 * RP2350-Specific: True Random Number Generator
 * ============================================================================ */

static uint32_t trng_get_random(void)
{
    /* Enable RNG */
    TRNG->RND_SOURCE_ENABLE = 1;

    /* Wait for valid entropy */
    while (!(TRNG->TRNG_VALID));

    /* Read random data */
    uint32_t random = TRNG->EHR_DATA0;

    return random;
}

/* ============================================================================
 * Core 1 Code
 * ============================================================================ */

__attribute__((section(".core1")))
void core1_main(void)
{
    uint32_t value;

    /* Signal ready */
    SHARED->core1_ready = 0xC0DE0001;
    __asm__ volatile("dsb" ::: "memory");

    /* Main loop: wait for FIFO commands */
    while (1) {
        if (fifo_pop(&value)) {
            /* Echo back with modification (add 0x1000) */
            uint32_t response = value + 0x1000;
            fifo_push_blocking(response, 100000);
        }

        /* Check shared memory command */
        if (SHARED->command == CMD_INCREMENT) {
            SHARED->shared_value++;
            __asm__ volatile("dsb" ::: "memory");
            SHARED->command = CMD_DONE;
        } else if (SHARED->command == CMD_MULTIPLY) {
            SHARED->shared_value *= 2;
            __asm__ volatile("dsb" ::: "memory");
            SHARED->command = CMD_DONE;
        }
    }
}

/* ============================================================================
 * Command Handlers (Core 0)
 * ============================================================================ */

static void cmd_cpuid(void)
{
    cdc_put_hex8(get_core_id());
    cdc_puts("\n");
}

static void cmd_arch(void)
{
    /* RP2350 can be ARM (Cortex-M33) or RISC-V (Hazard3) */
    /* Check CPACR for FPU presence to detect ARM mode */
    #if defined(__ARM_ARCH_8M_MAIN__)
    cdc_puts("ARM-M33\n");
    #else
    cdc_puts("RISCV-HAZARD3\n");
    #endif
}

static void cmd_fifo(const char *args)
{
    while (*args == ' ') args++;

    if (!*args) {
        cdc_puts("ERROR: Need hex value\n");
        return;
    }

    uint32_t value = parse_hex(args, 8);
    uint32_t response;

    /* Check if Core 1 is ready */
    if (SHARED->core1_ready != 0xC0DE0001) {
        cdc_puts("ERROR: Core1 not ready\n");
        return;
    }

    /* Send via FIFO */
    if (!fifo_push_blocking(value, 100000)) {
        cdc_puts("ERROR: FIFO push timeout\n");
        return;
    }

    /* Wait for response */
    if (!fifo_pop_blocking(&response, 100000)) {
        cdc_puts("ERROR: FIFO pop timeout\n");
        return;
    }

    cdc_put_hex32(response);
    cdc_puts("\n");
}

static void cmd_spinlock(const char *args)
{
    while (*args == ' ') args++;

    uint32_t lock_num = parse_hex(args, 2);
    if (lock_num >= 32) {
        cdc_puts("ERROR: Lock 0-31\n");
        return;
    }

    /* Try to claim */
    if (spinlock_try_claim(lock_num)) {
        cdc_puts("CLAIMED\n");
        spinlock_release(lock_num);
    } else {
        cdc_puts("BUSY\n");
    }
}

static void cmd_shared(const char *args)
{
    while (*args == ' ') args++;

    if (!*args) {
        cdc_puts("ERROR: Need hex value\n");
        return;
    }

    uint32_t value = parse_hex(args, 8);

    /* Check if Core 1 is ready */
    if (SHARED->core1_ready != 0xC0DE0001) {
        cdc_puts("ERROR: Core1 not ready\n");
        return;
    }

    /* Write value and ask Core 1 to increment */
    SHARED->shared_value = value;
    SHARED->command = CMD_INCREMENT;
    __asm__ volatile("dsb" ::: "memory");

    /* Wait for Core 1 to complete */
    uint32_t timeout = 100000;
    while (SHARED->command != CMD_DONE && timeout > 0) {
        timeout--;
    }

    if (timeout == 0) {
        cdc_puts("ERROR: Timeout\n");
        return;
    }

    /* Return incremented value */
    cdc_put_hex32(SHARED->shared_value);
    cdc_puts("\n");
}

static void cmd_stress(const char *args)
{
    while (*args == ' ') args++;

    uint32_t iterations = parse_hex(args, 4);
    if (iterations == 0) iterations = 100;
    if (iterations > 10000) iterations = 10000;

    /* Check if Core 1 is ready */
    if (SHARED->core1_ready != 0xC0DE0001) {
        cdc_puts("ERROR: Core1 not ready\n");
        return;
    }

    uint32_t errors = 0;
    for (uint32_t i = 0; i < iterations; i++) {
        uint32_t value = i * 17;
        uint32_t expected = value + 0x1000;
        uint32_t response;

        if (!fifo_push_blocking(value, 10000)) {
            errors++;
            continue;
        }

        if (!fifo_pop_blocking(&response, 10000)) {
            errors++;
            continue;
        }

        if (response != expected) {
            errors++;
        }
    }

    cdc_put_hex32(iterations);
    cdc_puts(" ");
    cdc_put_hex32(errors);
    cdc_puts("\n");
}

static void cmd_sha256(const char *args)
{
    while (*args == ' ') args++;

    if (!*args) {
        cdc_puts("ERROR: Need hex data\n");
        return;
    }

    /* Parse hex data (up to 64 bytes) */
    uint8_t data[64];
    int len = 0;
    while (args[len*2] && args[len*2+1] && len < 64) {
        data[len] = (parse_hex(&args[len*2], 2));
        len++;
        /* Check for end of hex */
        char c1 = args[len*2];
        char c2 = args[len*2+1];
        if (!((c1 >= '0' && c1 <= '9') || (c1 >= 'a' && c1 <= 'f') || (c1 >= 'A' && c1 <= 'F'))) break;
        if (!((c2 >= '0' && c2 <= '9') || (c2 >= 'a' && c2 <= 'f') || (c2 >= 'A' && c2 <= 'F'))) break;
    }

    if (len == 0) {
        cdc_puts("ERROR: Invalid hex\n");
        return;
    }

    /* Compute SHA-256 */
    uint8_t hash[32];
    sha256_compute(data, len, hash);

    /* Output hash */
    for (int i = 0; i < 32; i++) {
        cdc_put_hex8(hash[i]);
    }
    cdc_puts("\n");
}

static void cmd_trng(void)
{
    uint32_t random = trng_get_random();
    cdc_put_hex32(random);
    cdc_puts("\n");
}

static void cmd_core1_status(void)
{
    if (SHARED->core1_ready == 0xC0DE0001) {
        cdc_puts("READY\n");
    } else {
        cdc_put_hex32(SHARED->core1_ready);
        cdc_puts("\n");
    }
}

static void process_command(const char *cmd)
{
    if (strcmp(cmd, "PING") == 0) {
        cdc_puts("PONG\n");
    } else if (strcmp(cmd, "CPUID") == 0) {
        cmd_cpuid();
    } else if (strcmp(cmd, "ARCH") == 0) {
        cmd_arch();
    } else if (strncmp(cmd, "FIFO ", 5) == 0) {
        cmd_fifo(cmd + 5);
    } else if (strncmp(cmd, "SPINLOCK ", 9) == 0) {
        cmd_spinlock(cmd + 9);
    } else if (strncmp(cmd, "SHARED ", 7) == 0) {
        cmd_shared(cmd + 7);
    } else if (strncmp(cmd, "STRESS ", 7) == 0) {
        cmd_stress(cmd + 7);
    } else if (strncmp(cmd, "SHA256 ", 7) == 0) {
        cmd_sha256(cmd + 7);
    } else if (strcmp(cmd, "TRNG") == 0) {
        cmd_trng();
    } else if (strcmp(cmd, "STATUS") == 0) {
        cmd_core1_status();
    } else if (cmd[0] != '\0') {
        cdc_puts("ERROR: Unknown command\n");
    }
}

/* ============================================================================
 * Main (Core 0)
 * ============================================================================ */

int main(void)
{
    char cmd_buffer[64];

    /* Initialize shared memory */
    SHARED->core1_ready = 0;
    SHARED->shared_value = 0;
    SHARED->command = CMD_NONE;
    __asm__ volatile("dsb" ::: "memory");

    /* Core 1 will be started by the emulator/test harness */

    /* Main command loop */
    while (1) {
        cdc_getline(cmd_buffer, sizeof(cmd_buffer));
        process_command(cmd_buffer);
    }

    return 0;
}

/* Reset handler for Core 0 */
void Reset_Handler(void)
{
    main();
    while (1);
}
