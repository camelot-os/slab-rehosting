/*
 * NRF52840 I2C EEPROM Test Firmware with CDC-ACM Interface
 *
 * Tests 24C256 EEPROM via USB CDC commands using NRF TWIM peripheral.
 * Commands are received over CDC, I2C operations performed,
 * and results returned.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "nrf52.h"

/* EEPROM configuration */
#define EEPROM_ADDR         0x50    /* 24C256 I2C address */
#define EEPROM_PAGE_SIZE    64      /* Page size for 24C256 */

/* CDC I/O addresses (emulation) */
#define CDC_OUT         (*(volatile uint32_t *)0xE0000000)
#define CDC_IN          (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS      (*(volatile uint32_t *)0xE0000008)

/* DMA buffers */
static uint8_t tx_buffer[68];   /* 2 addr bytes + 64 data max */
static uint8_t rx_buffer[64];

/* Hex conversion */
static const char hex_chars[] = "0123456789abcdef";

static int hex_to_nibble(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int hex_to_bytes(const char *hex, uint8_t *out, int max_len)
{
    int i = 0;
    while (hex[0] && hex[1] && i < max_len) {
        int hi = hex_to_nibble(hex[0]);
        int lo = hex_to_nibble(hex[1]);
        if (hi < 0 || lo < 0) break;
        out[i++] = (hi << 4) | lo;
        hex += 2;
    }
    return i;
}

/* CDC send */
static void cdc_send(const char *str)
{
    while (*str) {
        CDC_OUT = *str++;
    }
}

/* Simple strcmp */
static int my_strcmp(const char *s1, const char *s2)
{
    while (*s1 && *s1 == *s2) { s1++; s2++; }
    return (unsigned char)*s1 - (unsigned char)*s2;
}

/* Simple delay */
static void delay_ms(int ms)
{
    volatile int i;
    for (int j = 0; j < ms; j++) {
        for (i = 0; i < 16000; i++);  /* ~64MHz clock */
    }
}

/* Initialize TWIM */
static void twim_init(void)
{
    /* Configure pins (using P0.26 for SCL, P0.27 for SDA) */
    TWIM0->PSEL_SCL = 26;
    TWIM0->PSEL_SDA = 27;

    /* Set frequency to 400kHz */
    TWIM0->FREQUENCY = TWIM_FREQUENCY_400K;

    /* Enable TWIM */
    TWIM0->ENABLE = TWIM_ENABLE_ENABLED;
}

/* Wait for event with timeout */
static int wait_event(volatile uint32_t *event, int timeout_ms)
{
    volatile int timeout = timeout_ms * 1000;
    while (!*event && timeout > 0) {
        timeout--;
    }
    if (*event) {
        *event = 0;  /* Clear event */
        return 0;
    }
    return -1;  /* Timeout */
}

/* I2C write: address bytes + data */
static int i2c_write(uint8_t addr, const uint8_t *data, int len)
{
    /* Set device address */
    TWIM0->ADDRESS = addr;

    /* Set TX buffer */
    TWIM0->TXD_PTR = (uint32_t)data;
    TWIM0->TXD_MAXCNT = len;

    /* No RX */
    TWIM0->RXD_MAXCNT = 0;

    /* Clear events */
    TWIM0->EVENTS_STOPPED = 0;
    TWIM0->EVENTS_ERROR = 0;
    TWIM0->EVENTS_LASTTX = 0;

    /* Configure shortcut: LASTTX -> STOP */
    TWIM0->SHORTS = TWIM_SHORTS_LASTTX_STOP;

    /* Start TX */
    TWIM0->TASKS_STARTTX = 1;

    /* Wait for completion */
    if (wait_event(&TWIM0->EVENTS_STOPPED, 100) < 0) {
        TWIM0->TASKS_STOP = 1;
        return -1;
    }

    /* Check for errors */
    if (TWIM0->ERRORSRC) {
        uint32_t err = TWIM0->ERRORSRC;
        TWIM0->ERRORSRC = err;  /* Clear errors */
        return -2;
    }

    return 0;
}

/* I2C write-then-read (for setting address then reading) */
static int i2c_write_read(uint8_t addr, const uint8_t *tx_data, int tx_len,
                           uint8_t *rx_data, int rx_len)
{
    /* Set device address */
    TWIM0->ADDRESS = addr;

    /* Set TX buffer (address bytes) */
    TWIM0->TXD_PTR = (uint32_t)tx_data;
    TWIM0->TXD_MAXCNT = tx_len;

    /* Set RX buffer */
    TWIM0->RXD_PTR = (uint32_t)rx_data;
    TWIM0->RXD_MAXCNT = rx_len;

    /* Clear events */
    TWIM0->EVENTS_STOPPED = 0;
    TWIM0->EVENTS_ERROR = 0;
    TWIM0->EVENTS_LASTTX = 0;
    TWIM0->EVENTS_LASTRX = 0;

    /* Configure shortcuts: LASTTX -> STARTRX -> LASTRX -> STOP */
    TWIM0->SHORTS = TWIM_SHORTS_LASTTX_STARTRX | TWIM_SHORTS_LASTRX_STOP;

    /* Start TX */
    TWIM0->TASKS_STARTTX = 1;

    /* Wait for completion */
    if (wait_event(&TWIM0->EVENTS_STOPPED, 100) < 0) {
        TWIM0->TASKS_STOP = 1;
        return -1;
    }

    /* Check for errors */
    if (TWIM0->ERRORSRC) {
        uint32_t err = TWIM0->ERRORSRC;
        TWIM0->ERRORSRC = err;
        return -2;
    }

    return TWIM0->RXD_AMOUNT;
}

/* Command: PING */
static void cmd_ping(void)
{
    cdc_send("PONG\n");
}

/* Command: PROBE - Check if EEPROM responds */
static void cmd_probe(void)
{
    /* Try to read 1 byte from address 0 */
    tx_buffer[0] = 0x00;  /* High address byte */
    tx_buffer[1] = 0x00;  /* Low address byte */

    int result = i2c_write_read(EEPROM_ADDR, tx_buffer, 2, rx_buffer, 1);
    if (result >= 0) {
        cdc_send("OK\n");
    } else {
        cdc_send("ERROR: No response\n");
    }
}

/* Command: READ <addr_hex> <len_hex> */
static void cmd_read(const char *args)
{
    if (args[0] == '\0' || args[1] == '\0' || args[2] == '\0' || args[3] == '\0') {
        cdc_send("ERROR: Need 4-digit hex address\n");
        return;
    }

    /* Parse address (4 hex digits) */
    uint16_t addr = 0;
    for (int i = 0; i < 4; i++) {
        int n = hex_to_nibble(args[i]);
        if (n < 0) {
            cdc_send("ERROR: Invalid address\n");
            return;
        }
        addr = (addr << 4) | n;
    }

    /* Parse length (2 hex digits, default 16) */
    int len = 16;
    const char *len_arg = &args[4];
    while (*len_arg == ' ') len_arg++;
    if (len_arg[0] && len_arg[1]) {
        int hi = hex_to_nibble(len_arg[0]);
        int lo = hex_to_nibble(len_arg[1]);
        if (hi >= 0 && lo >= 0) {
            len = (hi << 4) | lo;
        }
    }
    if (len > 64) len = 64;
    if (len == 0) len = 16;

    /* Set EEPROM address */
    tx_buffer[0] = (addr >> 8) & 0xFF;
    tx_buffer[1] = addr & 0xFF;

    /* Read data */
    int result = i2c_write_read(EEPROM_ADDR, tx_buffer, 2, rx_buffer, len);
    if (result < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    /* Output as hex */
    for (int i = 0; i < result; i++) {
        CDC_OUT = hex_chars[(rx_buffer[i] >> 4) & 0xF];
        CDC_OUT = hex_chars[rx_buffer[i] & 0xF];
    }
    cdc_send("\n");
}

/* Command: WRITE <addr_hex> <data_hex> */
static void cmd_write(const char *args)
{
    if (args[0] == '\0' || args[1] == '\0' || args[2] == '\0' || args[3] == '\0') {
        cdc_send("ERROR: Need 4-digit hex address\n");
        return;
    }

    /* Parse address */
    uint16_t addr = 0;
    for (int i = 0; i < 4; i++) {
        int n = hex_to_nibble(args[i]);
        if (n < 0) {
            cdc_send("ERROR: Invalid address\n");
            return;
        }
        addr = (addr << 4) | n;
    }

    /* Parse data */
    const char *data_arg = &args[4];
    while (*data_arg == ' ') data_arg++;

    int data_len = hex_to_bytes(data_arg, &tx_buffer[2], 64);
    if (data_len == 0) {
        cdc_send("ERROR: No data\n");
        return;
    }

    /* Set address bytes */
    tx_buffer[0] = (addr >> 8) & 0xFF;
    tx_buffer[1] = addr & 0xFF;

    /* Write to EEPROM */
    int result = i2c_write(EEPROM_ADDR, tx_buffer, 2 + data_len);
    if (result < 0) {
        cdc_send("ERROR: Write failed\n");
        return;
    }

    /* Wait for write cycle */
    delay_ms(10);

    cdc_send("OK\n");
}

/* Command: FILL <addr_hex> <len_hex> <pattern_hex> */
static void cmd_fill(const char *args)
{
    if (args[0] == '\0' || args[1] == '\0' || args[2] == '\0' || args[3] == '\0') {
        cdc_send("ERROR: Need 4-digit hex address\n");
        return;
    }

    /* Parse address */
    uint16_t addr = 0;
    for (int i = 0; i < 4; i++) {
        int n = hex_to_nibble(args[i]);
        if (n < 0) {
            cdc_send("ERROR: Invalid address\n");
            return;
        }
        addr = (addr << 4) | n;
    }

    /* Parse length */
    const char *rest = &args[4];
    while (*rest == ' ') rest++;
    if (!rest[0] || !rest[1]) {
        cdc_send("ERROR: Need length\n");
        return;
    }

    int hi = hex_to_nibble(rest[0]);
    int lo = hex_to_nibble(rest[1]);
    if (hi < 0 || lo < 0) {
        cdc_send("ERROR: Invalid length\n");
        return;
    }
    int len = (hi << 4) | lo;
    if (len > 64) len = 64;

    /* Parse pattern */
    rest = &rest[2];
    while (*rest == ' ') rest++;
    uint8_t pattern = 0xFF;
    if (rest[0] && rest[1]) {
        hi = hex_to_nibble(rest[0]);
        lo = hex_to_nibble(rest[1]);
        if (hi >= 0 && lo >= 0) {
            pattern = (hi << 4) | lo;
        }
    }

    /* Set address bytes */
    tx_buffer[0] = (addr >> 8) & 0xFF;
    tx_buffer[1] = addr & 0xFF;

    /* Fill data */
    for (int i = 0; i < len; i++) {
        tx_buffer[2 + i] = pattern;
    }

    /* Write to EEPROM */
    int result = i2c_write(EEPROM_ADDR, tx_buffer, 2 + len);
    if (result < 0) {
        cdc_send("ERROR: Write failed\n");
        return;
    }

    delay_ms(10);
    cdc_send("OK\n");
}

/* Process command */
static void process_command(char *cmd)
{
    /* Skip leading whitespace */
    while (*cmd == ' ' || *cmd == '\t') cmd++;

    /* Find command end */
    char *args = cmd;
    while (*args && *args != ' ' && *args != '\t') args++;
    if (*args) {
        *args++ = '\0';
        while (*args == ' ' || *args == '\t') args++;
    }

    if (my_strcmp(cmd, "PING") == 0) {
        cmd_ping();
    } else if (my_strcmp(cmd, "PROBE") == 0) {
        cmd_probe();
    } else if (my_strcmp(cmd, "READ") == 0) {
        cmd_read(args);
    } else if (my_strcmp(cmd, "WRITE") == 0) {
        cmd_write(args);
    } else if (my_strcmp(cmd, "FILL") == 0) {
        cmd_fill(args);
    } else {
        cdc_send("ERROR: Unknown command\n");
    }
}

/* Main */
int main(void)
{
    /* Start HFCLK for accurate timing */
    CLOCK->TASKS_HFCLKSTART = 1;
    while (!CLOCK->EVENTS_HFCLKSTARTED);

    /* Initialize TWIM */
    twim_init();

    cdc_send("NRF52840 EEPROM Test Ready\n");

    while (1) {
        if (CDC_STATUS & 1) {
            char cmd[256];
            uint32_t len = 0;

            while (len < sizeof(cmd) - 1) {
                uint32_t c = CDC_IN;
                if (c == '\n' || c == '\r') break;
                cmd[len++] = c;
            }
            cmd[len] = '\0';

            if (len > 0) {
                process_command(cmd);
            }
        }
    }

    return 0;
}

/* Startup */
void Reset_Handler(void)
{
    main();
    while (1);
}

void Default_Handler(void)
{
    while (1);
}

__attribute__((section(".isr_vector")))
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
    Default_Handler,  /* Debug */
    0,                /* Reserved */
    Default_Handler,  /* PendSV */
    Default_Handler,  /* SysTick */
};
