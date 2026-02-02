/*
 * STM32F439 DS3231 RTC Test Firmware
 *
 * Tests DS3231 I2C Real-Time Clock:
 * - Read/write time registers (BCD format)
 * - Read temperature sensor
 * - Status/control register access
 * - CDC ACM interface for test commands
 *
 * Commands via CDC:
 *   PING           -> PONG
 *   PROBE          -> Check if RTC responds
 *   TIME           -> Read current time (YYMMDD HHMMSS)
 *   SETTIME xxxx   -> Set time (YYMMDDHHMMSS hex)
 *   TEMP           -> Read temperature
 *   STATUS         -> Read status register
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "stm32f4.h"
#include "stm32f4_i2c.h"

/* DS3231 configuration */
#define DS3231_ADDR     0x68        /* 7-bit I2C address */

/* DS3231 Register addresses */
#define DS3231_REG_SECONDS  0x00
#define DS3231_REG_MINUTES  0x01
#define DS3231_REG_HOURS    0x02
#define DS3231_REG_DAY      0x03
#define DS3231_REG_DATE     0x04
#define DS3231_REG_MONTH    0x05
#define DS3231_REG_YEAR     0x06
#define DS3231_REG_CONTROL  0x0E
#define DS3231_REG_STATUS   0x0F
#define DS3231_REG_TEMP_MSB 0x11
#define DS3231_REG_TEMP_LSB 0x12

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

/* CDC send */
static void cdc_send(const char *str)
{
    while (*str) {
        CDC_OUT = *str++;
    }
}

static void cdc_send_hex8(uint8_t val)
{
    CDC_OUT = hex_chars[(val >> 4) & 0xF];
    CDC_OUT = hex_chars[val & 0xF];
}

/* Simple strcmp */
static int my_strcmp(const char *s1, const char *s2)
{
    while (*s1 && *s1 == *s2) { s1++; s2++; }
    return (unsigned char)*s1 - (unsigned char)*s2;
}

static int my_strncmp(const char *s1, const char *s2, int n)
{
    for (int i = 0; i < n; i++) {
        if (s1[i] != s2[i]) return s1[i] - s2[i];
        if (s1[i] == 0) return 0;
    }
    return 0;
}

/* DS3231: Read single register */
static int ds3231_read_reg(uint8_t reg, uint8_t *value)
{
    return i2c_write_read(I2C1, DS3231_ADDR, &reg, 1, value, 1);
}

/* DS3231: Write single register */
static int ds3231_write_reg(uint8_t reg, uint8_t value) __attribute__((unused));
static int ds3231_write_reg(uint8_t reg, uint8_t value)
{
    uint8_t buf[2] = {reg, value};
    return i2c_write(I2C1, DS3231_ADDR, buf, 2);
}

/* DS3231: Read multiple consecutive registers */
static int ds3231_read_regs(uint8_t start_reg, uint8_t *data, int len)
{
    return i2c_write_read(I2C1, DS3231_ADDR, &start_reg, 1, data, len);
}

/* DS3231: Write multiple consecutive registers */
static int ds3231_write_regs(uint8_t start_reg, const uint8_t *data, int len)
{
    uint8_t buf[16];
    if (len > 15) len = 15;
    buf[0] = start_reg;
    for (int i = 0; i < len; i++) {
        buf[1 + i] = data[i];
    }
    return i2c_write(I2C1, DS3231_ADDR, buf, len + 1);
}

/* Command: PROBE - Check if DS3231 responds */
static void cmd_probe(void)
{
    uint8_t data;
    int result = ds3231_read_reg(DS3231_REG_SECONDS, &data);

    if (result >= 0) {
        cdc_send("OK\n");
    } else {
        cdc_send("ERROR: No ACK\n");
    }
}

/* Command: TIME - Read current time */
static void cmd_time(void)
{
    uint8_t time_data[7];

    if (ds3231_read_regs(DS3231_REG_SECONDS, time_data, 7) < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    /* Output: YYMMDD HHMMSS (BCD values as hex) */
    cdc_send_hex8(time_data[6]);  /* Year */
    cdc_send_hex8(time_data[5] & 0x1F);  /* Month (mask century bit) */
    cdc_send_hex8(time_data[4]);  /* Date */
    cdc_send(" ");
    cdc_send_hex8(time_data[2] & 0x3F);  /* Hours (mask 12/24 bits) */
    cdc_send_hex8(time_data[1]);  /* Minutes */
    cdc_send_hex8(time_data[0]);  /* Seconds */
    cdc_send("\n");
}

/* Command: SETTIME - Set time (YYMMDDHHMMSS) */
static void cmd_settime(const char *args)
{
    uint8_t time_bytes[6];

    /* Skip spaces */
    while (*args == ' ') args++;

    /* Parse 6 hex bytes: YY MM DD HH MM SS */
    if (hex_to_bytes(args, time_bytes, 6) < 6) {
        cdc_send("ERROR: Need YYMMDDHHMMSS\n");
        return;
    }

    /* Write to DS3231 registers (order: seconds, minutes, hours, day, date, month, year) */
    uint8_t regs[7];
    regs[0] = time_bytes[5];  /* Seconds */
    regs[1] = time_bytes[4];  /* Minutes */
    regs[2] = time_bytes[3];  /* Hours (24-hour mode) */
    regs[3] = 0x01;           /* Day of week (not used, set to 1) */
    regs[4] = time_bytes[2];  /* Date */
    regs[5] = time_bytes[1];  /* Month */
    regs[6] = time_bytes[0];  /* Year */

    if (ds3231_write_regs(DS3231_REG_SECONDS, regs, 7) < 0) {
        cdc_send("ERROR: Write failed\n");
        return;
    }

    cdc_send("OK\n");
}

/* Command: TEMP - Read temperature */
static void cmd_temp(void)
{
    uint8_t temp_data[2];

    if (ds3231_read_regs(DS3231_REG_TEMP_MSB, temp_data, 2) < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    /* Temperature format: MSB is signed integer part, LSB upper 2 bits are fractional (0.25C resolution) */
    cdc_send_hex8(temp_data[0]);
    cdc_send_hex8(temp_data[1]);
    cdc_send("\n");
}

/* Command: STATUS - Read status register */
static void cmd_status(void)
{
    uint8_t status;

    if (ds3231_read_reg(DS3231_REG_STATUS, &status) < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    cdc_send_hex8(status);
    cdc_send("\n");
}

/* Process command */
static void process_command(const char *cmd)
{
    if (my_strcmp(cmd, "PING") == 0) {
        cdc_send("PONG\n");
    } else if (my_strcmp(cmd, "PROBE") == 0) {
        cmd_probe();
    } else if (my_strcmp(cmd, "TIME") == 0) {
        cmd_time();
    } else if (my_strncmp(cmd, "SETTIME ", 8) == 0) {
        cmd_settime(cmd + 8);
    } else if (my_strcmp(cmd, "TEMP") == 0) {
        cmd_temp();
    } else if (my_strcmp(cmd, "STATUS") == 0) {
        cmd_status();
    } else if (cmd[0] != '\0') {
        cdc_send("ERROR: Unknown command\n");
    }
}

/* Read command line from CDC */
static int cdc_getline(char *buf, int maxlen)
{
    int i = 0;
    while (i < maxlen - 1) {
        /* Wait for char (in emulation, CDC_STATUS bit 0 indicates RX ready) */
        while (!(CDC_STATUS & 0x01));

        char c = CDC_IN & 0xFF;
        if (c == '\n' || c == '\r') break;
        buf[i++] = c;
    }
    buf[i] = '\0';
    return i;
}

int main(void)
{
    char cmd_buf[64];

    /* Initialize I2C1 at 100kHz */
    i2c_init(I2C1, 100000);

    /* Main loop */
    while (1) {
        cdc_getline(cmd_buf, sizeof(cmd_buf));
        process_command(cmd_buf);
    }

    return 0;
}

/* Reset handler */
void Reset_Handler(void)
{
    main();
    while (1);
}
