/*
 * I2C EEPROM Test Firmware with CDC-ACM Interface
 *
 * Tests 24C256 EEPROM via USB CDC commands.
 * Commands are received over CDC, EEPROM operations performed,
 * and results returned.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "stm32f4.h"
#include "stm32f4_i2c.h"

/* EEPROM configuration */
#define EEPROM_ADDR     0x50        /* 7-bit I2C address */
#define EEPROM_SIZE     32768       /* 24C256 = 32KB */
#define EEPROM_PAGE     64          /* Page size */

/* CDC I/O addresses (emulation) */
#define CDC_OUT         (*(volatile uint32_t *)0xE0000000)
#define CDC_IN          (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS      (*(volatile uint32_t *)0xE0000008)

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

static void bytes_to_hex(const uint8_t *in, int len, char *out)
{
    for (int i = 0; i < len; i++) {
        out[i*2] = hex_chars[(in[i] >> 4) & 0xF];
        out[i*2+1] = hex_chars[in[i] & 0xF];
    }
    out[len*2] = '\n';
    out[len*2+1] = '\0';
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
        for (i = 0; i < 4000; i++);
    }
}

/* EEPROM: Write data at 16-bit address */
static int eeprom_write(uint16_t addr, const uint8_t *data, int len)
{
    uint8_t buf[66];  /* 2 address bytes + 64 data bytes max */

    if (len > 64) len = 64;

    /* Build message: address MSB, address LSB, data */
    buf[0] = (addr >> 8) & 0xFF;
    buf[1] = addr & 0xFF;
    for (int i = 0; i < len; i++) {
        buf[2 + i] = data[i];
    }

    return i2c_write(I2C1, EEPROM_ADDR, buf, len + 2);
}

/* EEPROM: Read data at 16-bit address */
static int eeprom_read(uint16_t addr, uint8_t *data, int len)
{
    uint8_t addr_buf[2];

    addr_buf[0] = (addr >> 8) & 0xFF;
    addr_buf[1] = addr & 0xFF;

    return i2c_write_read(I2C1, EEPROM_ADDR, addr_buf, 2, data, len);
}

/* Command: PROBE - Check if EEPROM responds */
static void cmd_probe(void)
{
    /* Try to read a single byte from address 0 */
    uint8_t data;
    int result = eeprom_read(0x0000, &data, 1);

    if (result >= 0) {
        cdc_send("OK\n");
    } else {
        cdc_send("ERROR: No ACK\n");
    }
}

/* Command: READ <addr_hex> <len_hex> - Read data */
static void cmd_read(const char *args)
{
    uint8_t addr_bytes[2];
    uint8_t len_byte;
    uint8_t data[64];
    char result[136];
    uint16_t addr;
    int len;

    if (hex_to_bytes(args, addr_bytes, 2) < 2) {
        cdc_send("ERROR: Need 2-byte address\n");
        return;
    }

    addr = (addr_bytes[0] << 8) | addr_bytes[1];

    /* Skip address hex (4 chars) and space */
    const char *len_hex = args + 4;
    while (*len_hex == ' ') len_hex++;

    if (hex_to_bytes(len_hex, &len_byte, 1) < 1) {
        len = 16;  /* Default */
    } else {
        len = len_byte;
    }

    if (len > 64) len = 64;

    if (eeprom_read(addr, data, len) < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    bytes_to_hex(data, len, result);
    cdc_send(result);
}

/* Command: WRITE <addr_hex> <data_hex> - Write data */
static void cmd_write(const char *args)
{
    uint8_t addr_bytes[2];
    uint8_t data[64];
    uint16_t addr;
    int data_len;

    if (hex_to_bytes(args, addr_bytes, 2) < 2) {
        cdc_send("ERROR: Need 2-byte address\n");
        return;
    }

    addr = (addr_bytes[0] << 8) | addr_bytes[1];

    /* Skip address hex (4 chars) and space */
    const char *data_hex = args + 4;
    while (*data_hex == ' ') data_hex++;

    data_len = hex_to_bytes(data_hex, data, 64);
    if (data_len == 0) {
        cdc_send("ERROR: No data\n");
        return;
    }

    if (eeprom_write(addr, data, data_len) < 0) {
        cdc_send("ERROR: Write failed\n");
        return;
    }

    /* Wait for write cycle (max 5ms for page write) */
    delay_ms(10);

    cdc_send("OK\n");
}

/* Command: FILL <addr_hex> <len_hex> <pattern_hex> - Fill with pattern */
static void cmd_fill(const char *args)
{
    uint8_t addr_bytes[2];
    uint8_t len_byte;
    uint8_t pattern;
    uint8_t data[64];
    uint16_t addr;
    int len;

    if (hex_to_bytes(args, addr_bytes, 2) < 2) {
        cdc_send("ERROR: Need 2-byte address\n");
        return;
    }

    addr = (addr_bytes[0] << 8) | addr_bytes[1];

    /* Skip address hex (4 chars) and space */
    const char *rest = args + 4;
    while (*rest == ' ') rest++;

    if (hex_to_bytes(rest, &len_byte, 1) < 1) {
        cdc_send("ERROR: Need length\n");
        return;
    }
    len = len_byte;
    if (len > 64) len = 64;

    /* Skip length hex (2 chars) and space */
    rest += 2;
    while (*rest == ' ') rest++;

    if (hex_to_bytes(rest, &pattern, 1) < 1) {
        pattern = 0xFF;
    }

    /* Fill data buffer */
    for (int i = 0; i < len; i++) {
        data[i] = pattern;
    }

    if (eeprom_write(addr, data, len) < 0) {
        cdc_send("ERROR: Write failed\n");
        return;
    }

    delay_ms(10);
    cdc_send("OK\n");
}

/* Process command */
static void process_command(char *cmd)
{
    while (*cmd == ' ' || *cmd == '\t') cmd++;

    char *args = cmd;
    while (*args && *args != ' ' && *args != '\t') args++;
    if (*args) {
        *args++ = '\0';
        while (*args == ' ' || *args == '\t') args++;
    }

    if (my_strcmp(cmd, "PROBE") == 0) {
        cmd_probe();
    } else if (my_strcmp(cmd, "READ") == 0) {
        cmd_read(args);
    } else if (my_strcmp(cmd, "WRITE") == 0) {
        cmd_write(args);
    } else if (my_strcmp(cmd, "FILL") == 0) {
        cmd_fill(args);
    } else if (my_strcmp(cmd, "PING") == 0) {
        cdc_send("PONG\n");
    } else {
        cdc_send("ERROR: Unknown command\n");
    }
}

/* Enable I2C clock */
static void enable_i2c_clock(void)
{
    /* Enable I2C1 clock (APB1) */
    RCC->APB1ENR |= (1 << 21);  /* I2C1EN */
}

/* Main */
int main(void)
{
    enable_i2c_clock();
    i2c_init(I2C1, 100000);  /* 100kHz */

    cdc_send("I2C EEPROM Test Ready\n");

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

__attribute__((section(".vectors")))
void (* const vectors[])(void) = {
    (void (*)(void))0x20020000,
    Reset_Handler,
    Default_Handler,
    Default_Handler,
    Default_Handler,
    Default_Handler,
    Default_Handler,
    0, 0, 0, 0,
    Default_Handler,
    Default_Handler,
    0,
    Default_Handler,
    Default_Handler,
};
