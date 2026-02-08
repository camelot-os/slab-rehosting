/*
 * STM32H745 Multicore Test Firmware
 *
 * Tests dual-core heterogeneous functionality (Cortex-M7 + Cortex-M4):
 * - Hardware semaphore synchronization (HSEM)
 * - Shared memory access via SRAM
 * - Inter-processor communication (IPC)
 * - CDC ACM interface for test commands
 *
 * Commands via CDC:
 *   PING           -> PONG
 *   CPUID          -> Return current core ID (M7=0, M4=1)
 *   HSEM n         -> Test hardware semaphore n (0-31)
 *   SHARED xxxx    -> Write to shared memory, M4 increments, read back
 *   STRESS nn      -> Run nn shared memory round-trips
 *   STATUS         -> Check M4 core status
 *
 * Architecture:
 *   M7 (480 MHz): Main core running command loop, D1 domain
 *   M4 (240 MHz): Coprocessor handling IPC commands, D2 domain
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include <stdbool.h>
#include "stm32h745.h"

/* CDC Interface (memory-mapped) */
#define CDC_OUT     (*(volatile uint32_t *)0xE0000000)
#define CDC_IN      (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS  (*(volatile uint32_t *)0xE0000008)
#define CDC_RX_READY    0x01
#define CDC_TX_READY    0x02

/* Hardware Semaphores */
#define HSEM_BASE       0x58026400
#define HSEM            ((volatile uint32_t *)HSEM_BASE)
#define HSEM_RLR(n)     (*(volatile uint32_t *)(HSEM_BASE + (n) * 4))  /* Read Lock */
#define HSEM_R(n)       (*(volatile uint32_t *)(HSEM_BASE + 0x80 + (n) * 4))  /* Lock/Unlock */
#define HSEM_KEY        (*(volatile uint32_t *)(HSEM_BASE + 0x100))
#define HSEM_KEYR       (*(volatile uint32_t *)(HSEM_BASE + 0x104))

/* HSEM bits */
#define HSEM_LOCK       (1 << 31)
#define HSEM_COREID_M7  (0 << 8)
#define HSEM_COREID_M4  (1 << 8)
#define HSEM_PROCID     0xFF

/* Shared SRAM3 region for multicore communication */
#define SHARED_BASE     0x30040000  /* SRAM3 - shared between domains */
typedef struct {
    volatile uint32_t m4_ready;
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
 * HSEM Functions
 * ============================================================================ */

static bool hsem_try_lock(uint32_t sem_id, uint32_t core_id)
{
    if (sem_id >= 32) return false;

    /* 1-step lock: write LOCK bit with core ID and process ID */
    uint32_t lock_val = HSEM_LOCK | (core_id << 8) | 0x01;
    HSEM_R(sem_id) = lock_val;

    /* Read back to verify lock */
    uint32_t status = HSEM_R(sem_id);
    return (status & HSEM_LOCK) && ((status >> 8) & 0xF) == core_id;
}

static void hsem_unlock(uint32_t sem_id, uint32_t core_id)
{
    if (sem_id < 32) {
        /* Write without LOCK bit releases */
        HSEM_R(sem_id) = (core_id << 8) | 0x01;
    }
}

static bool hsem_is_locked(uint32_t sem_id)
{
    if (sem_id >= 32) return false;
    return (HSEM_RLR(sem_id) & HSEM_LOCK) != 0;
}

/* ============================================================================
 * M4 Core Code (placed in D2 domain)
 * ============================================================================ */

#ifdef CORE_M4
__attribute__((section(".m4_code")))
void m4_main(void)
{
    /* Signal ready */
    SHARED->m4_ready = 0xC0DE0004;  /* M4 ready signature */
    __asm__ volatile("dsb" ::: "memory");

    /* Main loop: wait for shared memory commands */
    while (1) {
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
#endif /* CORE_M4 */

/* ============================================================================
 * Command Handlers (M7 Core)
 * ============================================================================ */

static void cmd_cpuid(void)
{
    /* M7 core ID is 0, M4 is 1 */
#ifdef CORE_M4
    cdc_puts("01\n");  /* M4 */
#else
    cdc_puts("00\n");  /* M7 */
#endif
}

static void cmd_hsem(const char *args)
{
    while (*args == ' ') args++;

    uint32_t sem_id = parse_hex(args, 2);
    if (sem_id >= 32) {
        cdc_puts("ERROR: HSEM 0-31\n");
        return;
    }

    /* Try to lock from M7 (core ID = 0) */
    if (hsem_try_lock(sem_id, 0)) {
        cdc_puts("CLAIMED\n");
        hsem_unlock(sem_id, 0);
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

    /* Check if M4 is ready */
    if (SHARED->m4_ready != 0xC0DE0004) {
        cdc_puts("ERROR: M4 not ready\n");
        return;
    }

    /* Acquire semaphore for shared memory access */
    if (!hsem_try_lock(0, 0)) {
        cdc_puts("ERROR: HSEM busy\n");
        return;
    }

    /* Write value and ask M4 to increment */
    SHARED->shared_value = value;
    SHARED->command = CMD_INCREMENT;
    __asm__ volatile("dsb" ::: "memory");

    /* Release semaphore */
    hsem_unlock(0, 0);

    /* Wait for M4 to complete */
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

    /* Check if M4 is ready */
    if (SHARED->m4_ready != 0xC0DE0004) {
        cdc_puts("ERROR: M4 not ready\n");
        return;
    }

    uint32_t errors = 0;
    for (uint32_t i = 0; i < iterations; i++) {
        uint32_t value = i * 17;
        uint32_t expected = value + 1;

        /* Acquire semaphore */
        if (!hsem_try_lock(0, 0)) {
            errors++;
            continue;
        }

        /* Write command */
        SHARED->shared_value = value;
        SHARED->command = CMD_INCREMENT;
        __asm__ volatile("dsb" ::: "memory");

        /* Release semaphore */
        hsem_unlock(0, 0);

        /* Wait for completion */
        uint32_t timeout = 10000;
        while (SHARED->command != CMD_DONE && timeout > 0) {
            timeout--;
        }

        if (timeout == 0 || SHARED->shared_value != expected) {
            errors++;
        }
    }

    cdc_put_hex32(iterations);
    cdc_puts(" ");
    cdc_put_hex32(errors);
    cdc_puts("\n");
}

static void cmd_status(void)
{
    if (SHARED->m4_ready == 0xC0DE0004) {
        cdc_puts("READY\n");
    } else {
        cdc_put_hex32(SHARED->m4_ready);
        cdc_puts("\n");
    }
}

static void process_command(const char *cmd)
{
    if (strcmp(cmd, "PING") == 0) {
        cdc_puts("PONG\n");
    } else if (strcmp(cmd, "CPUID") == 0) {
        cmd_cpuid();
    } else if (strncmp(cmd, "HSEM ", 5) == 0) {
        cmd_hsem(cmd + 5);
    } else if (strncmp(cmd, "SHARED ", 7) == 0) {
        cmd_shared(cmd + 7);
    } else if (strncmp(cmd, "STRESS ", 7) == 0) {
        cmd_stress(cmd + 7);
    } else if (strcmp(cmd, "STATUS") == 0) {
        cmd_status();
    } else if (cmd[0] != '\0') {
        cdc_puts("ERROR: Unknown command\n");
    }
}

/* ============================================================================
 * Main (M7 Core)
 * ============================================================================ */

int main(void)
{
    char cmd_buffer[64];

    /* Initialize shared memory */
    SHARED->m4_ready = 0;
    SHARED->shared_value = 0;
    SHARED->command = CMD_NONE;
    __asm__ volatile("dsb" ::: "memory");

    /* M4 will be started by the emulator/test harness */

    /* Main command loop */
    while (1) {
        cdc_getline(cmd_buffer, sizeof(cmd_buffer));
        process_command(cmd_buffer);
    }

    return 0;
}

/* Reset handler for M7 */
void Reset_Handler(void)
{
    main();
    while (1);
}
