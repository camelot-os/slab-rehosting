/*
 * STM32L433 I2C EEPROM Test Firmware
 *
 * Tests I2C v2 peripheral with external 24C256 EEPROM:
 * - I2C master mode with auto-end
 * - EEPROM random read/write
 * - CDC ACM interface for test commands
 *
 * Commands via CDC:
 *   PING           -> PONG
 *   PROBE          -> OK if EEPROM responds
 *   READ xxxx nn   -> Read nn bytes from address
 *   WRITE xxxx dd  -> Write data to address
 *   FILL xxxx nn pp -> Fill nn bytes with pattern pp
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include <stdbool.h>
#include "stm32l4.h"

/* CDC Interface (memory-mapped) */
#define CDC_OUT     (*(volatile uint32_t *)0xE0000000)
#define CDC_IN      (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS  (*(volatile uint32_t *)0xE0000008)
#define CDC_RX_READY    0x01
#define CDC_TX_READY    0x02

/* EEPROM Configuration */
#define EEPROM_ADDR     0x50    /* 24C256 I2C address (7-bit) */

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

/* Initialize I2C1 */
static void i2c_init(void)
{
    /* Enable clocks */
    RCC->AHB2ENR |= RCC_AHB2ENR_GPIOBEN;
    RCC->APB1ENR1 |= RCC_APB1ENR1_I2C1EN;

    /* Configure GPIO:
     * PB6 - SCL (AF4)
     * PB7 - SDA (AF4)
     * Open-drain, pull-up
     */
    GPIOB->MODER &= ~((3 << 12) | (3 << 14));
    GPIOB->MODER |= (2 << 12) | (2 << 14);  /* Alternate function */

    GPIOB->OTYPER |= (1 << 6) | (1 << 7);   /* Open-drain */
    GPIOB->OSPEEDR |= (3 << 12) | (3 << 14); /* High speed */
    GPIOB->PUPDR &= ~((3 << 12) | (3 << 14));
    GPIOB->PUPDR |= (1 << 12) | (1 << 14);  /* Pull-up */

    /* Set AF4 for I2C1 */
    GPIOB->AFR[0] &= ~((0xF << 24) | (0xF << 28));
    GPIOB->AFR[0] |= (4 << 24) | (4 << 28);

    /* Disable I2C first */
    I2C1->CR1 = 0;

    /* Configure timing for 100kHz (assuming 80MHz clock)
     * PRESC=7, SCLDEL=9, SDADEL=0, SCLH=0xC7, SCLL=0xC3
     */
    I2C1->TIMINGR = (7 << 28) | (9 << 20) | (0 << 16) | (0xC7 << 8) | 0xC3;

    /* Enable I2C */
    I2C1->CR1 = I2C_CR1_PE;
}

/* I2C write to EEPROM */
static bool i2c_eeprom_write(uint16_t mem_addr, const uint8_t *data, uint8_t len)
{
    /* Wait if bus is busy */
    while (I2C1->ISR & I2C_ISR_BUSY);

    /* Configure transfer: address bytes + data, auto-end */
    uint32_t nbytes = 2 + len;  /* 2 address bytes + data */
    i2c_configure_transfer(I2C1, EEPROM_ADDR, nbytes, false, true);

    /* Send address high byte */
    i2c_wait_txis(I2C1);
    I2C1->TXDR = (mem_addr >> 8) & 0xFF;

    /* Send address low byte */
    i2c_wait_txis(I2C1);
    I2C1->TXDR = mem_addr & 0xFF;

    /* Send data bytes */
    for (uint8_t i = 0; i < len; i++) {
        i2c_wait_txis(I2C1);
        I2C1->TXDR = data[i];
    }

    /* Wait for stop */
    i2c_wait_stopf(I2C1);

    /* Check for NACK */
    if (I2C1->ISR & I2C_ISR_NACKF) {
        I2C1->ICR = I2C_ISR_NACKF;
        return false;
    }

    return true;
}

/* I2C read from EEPROM (random read) */
static bool i2c_eeprom_read(uint16_t mem_addr, uint8_t *data, uint8_t len)
{
    /* Wait if bus is busy */
    while (I2C1->ISR & I2C_ISR_BUSY);

    /* First: send address (2 bytes, no auto-end) */
    I2C1->CR2 = ((EEPROM_ADDR << 1) & I2C_CR2_SADD_Msk) |
                (2 << I2C_CR2_NBYTES_Pos) |  /* 2 address bytes */
                I2C_CR2_START;

    /* Send address high byte */
    i2c_wait_txis(I2C1);
    I2C1->TXDR = (mem_addr >> 8) & 0xFF;

    /* Send address low byte */
    i2c_wait_txis(I2C1);
    I2C1->TXDR = mem_addr & 0xFF;

    /* Wait for transfer complete */
    i2c_wait_tc(I2C1);

    /* Now: read data (repeated start) */
    I2C1->CR2 = ((EEPROM_ADDR << 1) & I2C_CR2_SADD_Msk) |
                ((uint32_t)len << I2C_CR2_NBYTES_Pos) |
                I2C_CR2_RD_WRN |
                I2C_CR2_AUTOEND |
                I2C_CR2_START;

    /* Read data bytes */
    for (uint8_t i = 0; i < len; i++) {
        i2c_wait_rxne(I2C1);
        data[i] = I2C1->RXDR;
    }

    /* Wait for stop */
    i2c_wait_stopf(I2C1);

    /* Check for NACK */
    if (I2C1->ISR & I2C_ISR_NACKF) {
        I2C1->ICR = I2C_ISR_NACKF;
        return false;
    }

    return true;
}

/* Probe EEPROM */
static bool i2c_eeprom_probe(void)
{
    /* Wait if bus is busy */
    while (I2C1->ISR & I2C_ISR_BUSY);

    /* Send just the address, 0 data bytes */
    I2C1->CR2 = ((EEPROM_ADDR << 1) & I2C_CR2_SADD_Msk) |
                I2C_CR2_AUTOEND |
                I2C_CR2_START;

    /* Wait for stop */
    i2c_wait_stopf(I2C1);

    /* Check for NACK */
    if (I2C1->ISR & I2C_ISR_NACKF) {
        I2C1->ICR = I2C_ISR_NACKF;
        return false;
    }

    return true;
}

/* Command handlers */
static void cmd_ping(void)
{
    cdc_puts("PONG\n");
}

static void cmd_probe(void)
{
    if (i2c_eeprom_probe()) {
        cdc_puts("OK\n");
    } else {
        cdc_puts("ERROR: No response\n");
    }
}

static void cmd_read(const char *args)
{
    args = args;
    while (*args == ' ') args++;

    if (!args[0] || !args[1] || !args[2] || !args[3]) {
        cdc_puts("ERROR: Need 4-digit hex address\n");
        return;
    }

    uint16_t addr = parse_hex(args, 4);
    const char *len_str = args + 4;
    while (*len_str == ' ') len_str++;

    uint8_t len = 16;  /* Default */
    if (*len_str) {
        len = parse_hex(len_str, 2);
    }

    if (len == 0) len = 16;
    if (len > 64) len = 64;

    uint8_t data[64];
    if (i2c_eeprom_read(addr, data, len)) {
        for (uint8_t i = 0; i < len; i++) {
            cdc_put_hex8(data[i]);
        }
        cdc_putc('\n');
    } else {
        cdc_puts("ERROR: Read failed\n");
    }
}

static void cmd_write(const char *args)
{
    args = args;
    while (*args == ' ') args++;

    if (!args[0] || !args[1] || !args[2] || !args[3]) {
        cdc_puts("ERROR: Need 4-digit hex address\n");
        return;
    }

    uint16_t addr = parse_hex(args, 4);
    const char *data_str = args + 4;
    while (*data_str == ' ') data_str++;

    /* Parse hex data */
    uint8_t data[64];
    uint8_t len = 0;
    while (*data_str && len < 64) {
        if (data_str[1]) {
            data[len++] = parse_hex(data_str, 2);
            data_str += 2;
        } else {
            break;
        }
    }

    if (len == 0) {
        cdc_puts("ERROR: No data\n");
        return;
    }

    if (i2c_eeprom_write(addr, data, len)) {
        cdc_puts("OK\n");
    } else {
        cdc_puts("ERROR: Write failed\n");
    }
}

static void cmd_fill(const char *args)
{
    args = args;
    while (*args == ' ') args++;

    if (!args[0] || !args[1] || !args[2] || !args[3]) {
        cdc_puts("ERROR: Need 4-digit hex address\n");
        return;
    }

    uint16_t addr = parse_hex(args, 4);
    const char *rest = args + 4;
    while (*rest == ' ') rest++;

    if (!rest[0] || !rest[1]) {
        cdc_puts("ERROR: Need length\n");
        return;
    }

    uint8_t len = parse_hex(rest, 2);
    rest += 2;
    while (*rest == ' ') rest++;

    uint8_t pattern = 0xFF;
    if (*rest) {
        pattern = parse_hex(rest, 2);
    }

    if (len == 0) len = 16;
    if (len > 64) len = 64;

    uint8_t data[64];
    for (uint8_t i = 0; i < len; i++) {
        data[i] = pattern;
    }

    if (i2c_eeprom_write(addr, data, len)) {
        cdc_puts("OK\n");
    } else {
        cdc_puts("ERROR: Fill failed\n");
    }
}

static void process_command(const char *cmd)
{
    if (strcmp(cmd, "PING") == 0) {
        cmd_ping();
    } else if (strcmp(cmd, "PROBE") == 0) {
        cmd_probe();
    } else if (strncmp(cmd, "READ ", 5) == 0) {
        cmd_read(cmd + 5);
    } else if (strncmp(cmd, "WRITE ", 6) == 0) {
        cmd_write(cmd + 6);
    } else if (strncmp(cmd, "FILL ", 5) == 0) {
        cmd_fill(cmd + 5);
    } else {
        cdc_puts("ERROR: Unknown command\n");
    }
}

int main(void)
{
    char cmd_buffer[128];

    /* Initialize I2C */
    i2c_init();

    /* Main command loop */
    while (1) {
        cdc_getline(cmd_buffer, sizeof(cmd_buffer));
        process_command(cmd_buffer);
    }

    return 0;
}

/* Default handler for unused interrupts */
void Default_Handler(void) { while (1); }

/* Reset handler */
void Reset_Handler(void)
{
    main();
    while (1);
}

/* Vector table - must be placed at flash start */
__attribute__((section(".vectors")))
void (* const vectors[])(void) = {
    (void (*)(void))0x20010000,  /* Initial SP (64KB SRAM) */
    Reset_Handler,               /* Reset */
    Default_Handler,             /* NMI */
    Default_Handler,             /* HardFault */
    Default_Handler,             /* MemManage */
    Default_Handler,             /* BusFault */
    Default_Handler,             /* UsageFault */
    0, 0, 0, 0,                 /* Reserved */
    Default_Handler,             /* SVCall */
    Default_Handler,             /* Debug */
    0,                           /* Reserved */
    Default_Handler,             /* PendSV */
    Default_Handler,             /* SysTick */
};
