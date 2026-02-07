/*
 * NRF52840 QSPI Flash Test Firmware
 *
 * Tests NRF52840 QSPI peripheral with external W25Q128 Flash:
 * - QSPI EasyDMA read/write operations
 * - Custom instruction interface for JEDEC ID, status register
 * - Sector erase via QSPI
 * - CDC ACM interface for test commands
 *
 * Commands via CDC:
 *   PING           -> PONG
 *   JEDEC          -> Read JEDEC ID via custom instruction
 *   STATUS         -> Read status register
 *   ERASE xxxx     -> Erase 4KB sector at address
 *   WRITE xxxx dd  -> Write data to flash
 *   READ xxxx nn   -> Read nn bytes from address
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "nrf52.h"

/* CDC Interface (memory-mapped) */
#define CDC_OUT     (*(volatile uint32_t *)0xE0000000)
#define CDC_IN      (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS  (*(volatile uint32_t *)0xE0000008)
#define CDC_RX_READY    0x01
#define CDC_TX_READY    0x02

/* Flash commands */
#define FLASH_CMD_READ_JEDEC    0x9F
#define FLASH_CMD_READ_STATUS   0x05
#define FLASH_CMD_WRITE_ENABLE  0x06
#define FLASH_CMD_SECTOR_ERASE  0x20
#define FLASH_CMD_PAGE_PROGRAM  0x02
#define FLASH_CMD_READ_DATA     0x03

/* Data buffers in RAM */
static uint8_t tx_buffer[256] __attribute__((aligned(4)));
static uint8_t rx_buffer[256] __attribute__((aligned(4)));

/* String helpers */
static void cdc_putc(char c)
{
    while (!(CDC_STATUS & CDC_TX_READY));
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

static int cdc_getline(char *buf, int maxlen)
{
    int i = 0;
    while (i < maxlen - 1) {
        while (!(CDC_STATUS & CDC_RX_READY));
        char c = CDC_IN & 0xFF;
        if (c == '\n' || c == '\r') {
            break;
        }
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
    while (*a && *b && *a == *b) {
        a++;
        b++;
    }
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
 * QSPI Functions
 * ============================================================================ */

static void qspi_init(void)
{
    /* Configure QSPI pins (example: P0.17-22) */
    QSPI->PSEL_SCK = 17;
    QSPI->PSEL_CSN = 18;
    QSPI->PSEL_IO0 = 19;
    QSPI->PSEL_IO1 = 20;
    QSPI->PSEL_IO2 = 21;
    QSPI->PSEL_IO3 = 22;

    /* Configure interface: 24-bit address, fast read mode */
    QSPI->IFCONFIG0 = 0;  /* Default settings */
    QSPI->IFCONFIG1 = (0x40 << 0);  /* SCKFREQ = fPCLK/2 */

    /* Enable QSPI */
    QSPI->ENABLE = QSPI_ENABLE_ENABLED;

    /* Activate interface */
    QSPI->EVENTS_READY = 0;
    QSPI->TASKS_ACTIVATE = 1;
    while (!QSPI->EVENTS_READY);
}

static void qspi_custom_instruction(uint8_t opcode, int len, uint8_t *data_in, uint8_t *data_out)
{
    /* Setup CINSTRDAT for data bytes */
    QSPI->CINSTRDAT0 = 0;
    QSPI->CINSTRDAT1 = 0;

    if (data_in && len > 1) {
        uint32_t dat0 = 0;
        uint32_t dat1 = 0;
        for (int i = 0; i < len - 1 && i < 4; i++) {
            dat0 |= ((uint32_t)data_in[i]) << (i * 8);
        }
        for (int i = 4; i < len - 1 && i < 8; i++) {
            dat1 |= ((uint32_t)data_in[i]) << ((i - 4) * 8);
        }
        QSPI->CINSTRDAT0 = dat0;
        QSPI->CINSTRDAT1 = dat1;
    }

    /* Configure and execute custom instruction */
    QSPI->EVENTS_READY = 0;
    QSPI->CINSTRCONF = (opcode << QSPI_CINSTRCONF_OPCODE_POS) |
                       ((len + 1) << QSPI_CINSTRCONF_LENGTH_POS);  /* len includes opcode */

    /* Wait for completion */
    while (!QSPI->EVENTS_READY);

    /* Read response from CINSTRDAT */
    if (data_out && len > 0) {
        uint32_t dat0 = QSPI->CINSTRDAT0;
        uint32_t dat1 = QSPI->CINSTRDAT1;
        for (int i = 0; i < len && i < 4; i++) {
            data_out[i] = (dat0 >> (i * 8)) & 0xFF;
        }
        for (int i = 4; i < len && i < 8; i++) {
            data_out[i] = (dat1 >> ((i - 4) * 8)) & 0xFF;
        }
    }
}

static void qspi_read(uint32_t addr, uint8_t *data, uint32_t len)
{
    QSPI->READ_SRC = addr;
    QSPI->READ_DST = (uint32_t)data;
    QSPI->READ_CNT = len;

    QSPI->EVENTS_READY = 0;
    QSPI->TASKS_READSTART = 1;
    while (!QSPI->EVENTS_READY);
}

static void qspi_write(uint32_t addr, const uint8_t *data, uint32_t len)
{
    /* Write enable first */
    qspi_custom_instruction(FLASH_CMD_WRITE_ENABLE, 0, NULL, NULL);

    QSPI->WRITE_DST = addr;
    QSPI->WRITE_SRC = (uint32_t)data;
    QSPI->WRITE_CNT = len;

    QSPI->EVENTS_READY = 0;
    QSPI->TASKS_WRITESTART = 1;
    while (!QSPI->EVENTS_READY);
}

static void qspi_erase_sector(uint32_t addr)
{
    /* Write enable first */
    qspi_custom_instruction(FLASH_CMD_WRITE_ENABLE, 0, NULL, NULL);

    QSPI->ERASE_PTR = addr;
    QSPI->ERASE_LEN = QSPI_ERASE_LEN_4KB;

    QSPI->EVENTS_READY = 0;
    QSPI->TASKS_ERASESTART = 1;
    while (!QSPI->EVENTS_READY);
}

/* ============================================================================
 * Command Handlers
 * ============================================================================ */

static void cmd_ping(void)
{
    cdc_puts("PONG\n");
}

static void cmd_jedec(void)
{
    /* Read JEDEC ID using custom instruction */
    uint8_t jedec[3] = {0};
    qspi_custom_instruction(FLASH_CMD_READ_JEDEC, 3, NULL, jedec);

    cdc_put_hex8(jedec[0]);
    cdc_put_hex8(jedec[1]);
    cdc_put_hex8(jedec[2]);
    cdc_putc('\n');
}

static void cmd_status(void)
{
    uint8_t status = 0;
    qspi_custom_instruction(FLASH_CMD_READ_STATUS, 1, NULL, &status);

    cdc_put_hex8(status);
    cdc_putc('\n');
}

static void cmd_erase(const char *args)
{
    /* Skip leading spaces */
    while (*args == ' ') args++;

    if (!*args) {
        cdc_puts("ERROR: No address\n");
        return;
    }

    uint32_t addr = parse_hex(args, 4);
    qspi_erase_sector(addr);
    cdc_puts("OK\n");
}

static void cmd_write(const char *args)
{
    /* Skip leading spaces */
    while (*args == ' ') args++;

    if (!*args || !args[4]) {
        cdc_puts("ERROR: Need address and data\n");
        return;
    }

    uint32_t addr = parse_hex(args, 4);
    args += 4;

    /* Skip space between address and data */
    while (*args == ' ') args++;

    /* Parse hex data */
    int len = 0;
    while (*args && len < 256) {
        if (args[1]) {
            tx_buffer[len++] = parse_hex(args, 2);
            args += 2;
        } else {
            break;
        }
    }

    if (len == 0) {
        cdc_puts("ERROR: No data\n");
        return;
    }

    qspi_write(addr, tx_buffer, len);
    cdc_puts("OK\n");
}

static void cmd_read(const char *args)
{
    /* Skip leading spaces */
    while (*args == ' ') args++;

    if (!*args) {
        cdc_puts("ERROR: No address\n");
        return;
    }

    uint32_t addr = parse_hex(args, 4);
    args += 4;

    /* Skip space */
    while (*args == ' ') args++;

    uint32_t len = 16;  /* Default */
    if (*args) {
        len = parse_hex(args, 2);
    }

    if (len == 0) len = 16;
    if (len > 64) len = 64;

    qspi_read(addr, rx_buffer, len);

    for (uint32_t i = 0; i < len; i++) {
        cdc_put_hex8(rx_buffer[i]);
    }
    cdc_putc('\n');
}

static void process_command(const char *cmd)
{
    if (strcmp(cmd, "PING") == 0) {
        cmd_ping();
    } else if (strcmp(cmd, "JEDEC") == 0) {
        cmd_jedec();
    } else if (strcmp(cmd, "STATUS") == 0) {
        cmd_status();
    } else if (strncmp(cmd, "ERASE ", 6) == 0) {
        cmd_erase(cmd + 6);
    } else if (strncmp(cmd, "WRITE ", 6) == 0) {
        cmd_write(cmd + 6);
    } else if (strncmp(cmd, "READ ", 5) == 0) {
        cmd_read(cmd + 5);
    } else {
        cdc_puts("ERROR: Unknown command\n");
    }
}

int main(void)
{
    char cmd_buffer[256];

    /* Initialize QSPI */
    qspi_init();

    /* Main command loop */
    while (1) {
        cdc_getline(cmd_buffer, sizeof(cmd_buffer));
        process_command(cmd_buffer);
    }

    return 0;
}

/* Reset handler */
void Reset_Handler(void)
{
    main();
    while (1);
}

void Default_Handler(void)
{
    while (1);
}

__attribute__((section(".vectors")))
void (* const vectors[])(void) = {
    (void (*)(void))0x20040000,  /* Initial stack pointer (256KB SRAM) */
    Reset_Handler,
    Default_Handler,  /* NMI */
    Default_Handler,  /* HardFault */
    Default_Handler,  /* MemManage */
    Default_Handler,  /* BusFault */
    Default_Handler,  /* UsageFault */
    0, 0, 0, 0,       /* Reserved */
    Default_Handler,  /* SVCall */
    0, 0,              /* Reserved */
    Default_Handler,  /* PendSV */
    Default_Handler,  /* SysTick */
};
