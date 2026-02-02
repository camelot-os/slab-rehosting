/*
 * SPI Flash Test Firmware with CDC-ACM Interface
 *
 * Tests W25Q128 SPI Flash via USB CDC commands.
 * Commands are received over CDC, flash operations performed,
 * and results returned.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "stm32f4.h"
#include "stm32f4_spi.h"

/* Flash commands (W25Q128) */
#define FLASH_CMD_WRITE_ENABLE      0x06
#define FLASH_CMD_WRITE_DISABLE     0x04
#define FLASH_CMD_READ_STATUS_1     0x05
#define FLASH_CMD_READ_DATA         0x03
#define FLASH_CMD_PAGE_PROGRAM      0x02
#define FLASH_CMD_SECTOR_ERASE      0x20
#define FLASH_CMD_JEDEC_ID          0x9F

/* Status register bits */
#define FLASH_SR_BUSY               0x01
#define FLASH_SR_WEL                0x02

/* CDC I/O addresses (emulation) */
#define CDC_OUT         (*(volatile uint32_t *)0xE0000000)
#define CDC_IN          (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS      (*(volatile uint32_t *)0xE0000008)

/* SPI CS control (directly connected in emulation) */
#define SPI_CS_LOW()    (*(volatile uint32_t *)0xE0000010) = 0
#define SPI_CS_HIGH()   (*(volatile uint32_t *)0xE0000010) = 1

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

/* SPI transfer single byte */
static uint8_t spi_xfer(uint8_t tx)
{
    while (!(SPI1->SR & SPI_SR_TXE));
    SPI1->DR = tx;
    while (!(SPI1->SR & SPI_SR_RXNE));
    return SPI1->DR;
}

/* Flash: Read JEDEC ID */
static void flash_read_jedec_id(uint8_t *id)
{
    SPI_CS_LOW();
    spi_xfer(FLASH_CMD_JEDEC_ID);
    id[0] = spi_xfer(0xFF);
    id[1] = spi_xfer(0xFF);
    id[2] = spi_xfer(0xFF);
    SPI_CS_HIGH();
}

/* Flash: Read status register */
static uint8_t flash_read_status(void)
{
    uint8_t status;
    SPI_CS_LOW();
    spi_xfer(FLASH_CMD_READ_STATUS_1);
    status = spi_xfer(0xFF);
    SPI_CS_HIGH();
    return status;
}

/* Flash: Wait ready */
static void flash_wait_ready(void)
{
    int timeout = 1000;
    while ((flash_read_status() & FLASH_SR_BUSY) && timeout--) {
        delay_ms(1);
    }
}

/* Flash: Write enable */
static void flash_write_enable(void)
{
    SPI_CS_LOW();
    spi_xfer(FLASH_CMD_WRITE_ENABLE);
    SPI_CS_HIGH();
}

/* Flash: Sector erase */
static void flash_sector_erase(uint32_t addr)
{
    flash_write_enable();
    SPI_CS_LOW();
    spi_xfer(FLASH_CMD_SECTOR_ERASE);
    spi_xfer((addr >> 16) & 0xFF);
    spi_xfer((addr >> 8) & 0xFF);
    spi_xfer(addr & 0xFF);
    SPI_CS_HIGH();
    flash_wait_ready();
}

/* Flash: Page program */
static void flash_page_program(uint32_t addr, const uint8_t *data, int len)
{
    flash_write_enable();
    SPI_CS_LOW();
    spi_xfer(FLASH_CMD_PAGE_PROGRAM);
    spi_xfer((addr >> 16) & 0xFF);
    spi_xfer((addr >> 8) & 0xFF);
    spi_xfer(addr & 0xFF);
    for (int i = 0; i < len; i++) {
        spi_xfer(data[i]);
    }
    SPI_CS_HIGH();
    flash_wait_ready();
}

/* Flash: Read data */
static void flash_read_data(uint32_t addr, uint8_t *data, int len)
{
    SPI_CS_LOW();
    spi_xfer(FLASH_CMD_READ_DATA);
    spi_xfer((addr >> 16) & 0xFF);
    spi_xfer((addr >> 8) & 0xFF);
    spi_xfer(addr & 0xFF);
    for (int i = 0; i < len; i++) {
        data[i] = spi_xfer(0xFF);
    }
    SPI_CS_HIGH();
}

/* Command: JEDEC - Read JEDEC ID */
static void cmd_jedec(void)
{
    uint8_t id[3];
    char result[16];

    flash_read_jedec_id(id);
    bytes_to_hex(id, 3, result);
    cdc_send(result);
}

/* Command: ERASE <addr_hex> - Erase 4KB sector */
static void cmd_erase(const char *args)
{
    uint8_t addr_bytes[4];
    uint32_t addr;

    if (hex_to_bytes(args, addr_bytes, 3) < 3) {
        cdc_send("ERROR: Need 3-byte address\n");
        return;
    }

    addr = (addr_bytes[0] << 16) | (addr_bytes[1] << 8) | addr_bytes[2];
    flash_sector_erase(addr);
    cdc_send("OK\n");
}

/* Command: WRITE <addr_hex> <data_hex> - Program page */
static void cmd_write(const char *args)
{
    uint8_t addr_bytes[4];
    uint8_t data[256];
    uint32_t addr;
    int data_len;

    if (hex_to_bytes(args, addr_bytes, 3) < 3) {
        cdc_send("ERROR: Need 3-byte address\n");
        return;
    }

    addr = (addr_bytes[0] << 16) | (addr_bytes[1] << 8) | addr_bytes[2];

    /* Skip address hex (6 chars) and space */
    const char *data_hex = args + 6;
    while (*data_hex == ' ') data_hex++;

    data_len = hex_to_bytes(data_hex, data, 256);
    if (data_len == 0) {
        cdc_send("ERROR: No data\n");
        return;
    }

    flash_page_program(addr, data, data_len);
    cdc_send("OK\n");
}

/* Command: READ <addr_hex> <len_hex> - Read data */
static void cmd_read(const char *args)
{
    uint8_t addr_bytes[4];
    uint8_t len_byte;
    uint8_t data[256];
    char result[520];
    uint32_t addr;
    int len;

    if (hex_to_bytes(args, addr_bytes, 3) < 3) {
        cdc_send("ERROR: Need 3-byte address\n");
        return;
    }

    addr = (addr_bytes[0] << 16) | (addr_bytes[1] << 8) | addr_bytes[2];

    /* Skip address hex (6 chars) and space */
    const char *len_hex = args + 6;
    while (*len_hex == ' ') len_hex++;

    if (hex_to_bytes(len_hex, &len_byte, 1) < 1) {
        len = 16;  /* Default */
    } else {
        len = len_byte;
    }

    if (len > 256) len = 256;

    flash_read_data(addr, data, len);
    bytes_to_hex(data, len, result);
    cdc_send(result);
}

/* Command: STATUS - Read status register */
static void cmd_status(void)
{
    uint8_t status = flash_read_status();
    char result[8];
    bytes_to_hex(&status, 1, result);
    cdc_send(result);
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

    if (my_strcmp(cmd, "JEDEC") == 0) {
        cmd_jedec();
    } else if (my_strcmp(cmd, "ERASE") == 0) {
        cmd_erase(args);
    } else if (my_strcmp(cmd, "WRITE") == 0) {
        cmd_write(args);
    } else if (my_strcmp(cmd, "READ") == 0) {
        cmd_read(args);
    } else if (my_strcmp(cmd, "STATUS") == 0) {
        cmd_status();
    } else if (my_strcmp(cmd, "PING") == 0) {
        cdc_send("PONG\n");
    } else {
        cdc_send("ERROR: Unknown command\n");
    }
}

/* Enable SPI clock */
static void enable_spi_clock(void)
{
    RCC->APB2ENR |= (1 << 12);  /* SPI1EN */
}

/* Initialize SPI */
static void spi_init_master(void)
{
    /* Master mode, software SS, 8-bit, CPOL=0, CPHA=0 */
    SPI1->CR1 = SPI_CR1_MSTR | SPI_CR1_SSM | SPI_CR1_SSI | SPI_CR1_BR_DIV8;
    SPI1->CR1 |= SPI_CR1_SPE;
}

/* Main */
int main(void)
{
    enable_spi_clock();
    spi_init_master();
    SPI_CS_HIGH();

    cdc_send("SPI Flash Test Ready\n");

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
