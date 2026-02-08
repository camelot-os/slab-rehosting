/*
 * NRF52840 SPI Flash Test Firmware with CDC-ACM Interface
 *
 * Tests W25Q128 SPI Flash via USB CDC commands using NRF SPIM peripheral.
 * Commands are received over CDC, SPI operations performed,
 * and results returned.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "nrf52.h"

/* W25Q128 Flash commands */
#define FLASH_CMD_JEDEC_ID      0x9F
#define FLASH_CMD_READ_STATUS   0x05
#define FLASH_CMD_WRITE_ENABLE  0x06
#define FLASH_CMD_WRITE_DISABLE 0x04
#define FLASH_CMD_READ_DATA     0x03
#define FLASH_CMD_PAGE_PROGRAM  0x02
#define FLASH_CMD_SECTOR_ERASE  0x20

/* W25Q128 expected JEDEC ID */
#define W25Q128_MFR_ID          0xEF
#define W25Q128_MEMORY_TYPE     0x40
#define W25Q128_CAPACITY        0x18

/* CDC I/O addresses (emulation) */
#define CDC_OUT         (*(volatile uint32_t *)0xE0000000)
#define CDC_IN          (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS      (*(volatile uint32_t *)0xE0000008)

/* DMA buffers */
static uint8_t tx_buffer[260];  /* cmd + 3 addr + 256 data */
static uint8_t rx_buffer[260];

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

/* Initialize SPIM */
static void spim_init(void)
{
    /* Configure pins (using P0.23-26) */
    SPIM3->PSEL_SCK = 23;
    SPIM3->PSEL_MOSI = 24;
    SPIM3->PSEL_MISO = 25;
    SPIM3->PSEL_CSN = 26;

    /* Set frequency to 8MHz */
    SPIM3->FREQUENCY = SPIM_FREQUENCY_8M;

    /* Configure for Mode 0 (CPOL=0, CPHA=0), MSB first */
    SPIM3->CONFIG = SPIM_CONFIG_ORDER_MSBFIRST |
                    SPIM_CONFIG_CPHA_LEADING |
                    SPIM_CONFIG_CPOL_LOW;

    /* Over-read character */
    SPIM3->ORC = 0xFF;

    /* Enable SPIM */
    SPIM3->ENABLE = SPIM_ENABLE_ENABLED;
}

/* SPI transfer */
static int spi_transfer(const uint8_t *tx_data, int tx_len, uint8_t *rx_data, int rx_len)
{
    /* Set TX buffer */
    SPIM3->TXD_PTR = (uint32_t)tx_data;
    SPIM3->TXD_MAXCNT = tx_len;

    /* Set RX buffer */
    SPIM3->RXD_PTR = (uint32_t)rx_data;
    SPIM3->RXD_MAXCNT = rx_len;

    /* Clear events */
    SPIM3->EVENTS_END = 0;
    SPIM3->EVENTS_STARTED = 0;

    /* Start transfer */
    SPIM3->TASKS_START = 1;

    /* Wait for completion */
    volatile int timeout = 100000;
    while (!SPIM3->EVENTS_END && timeout > 0) {
        timeout--;
    }

    if (timeout == 0) {
        SPIM3->TASKS_STOP = 1;
        return -1;
    }

    return 0;
}

/* Read JEDEC ID */
static int flash_read_jedec_id(uint8_t *id)
{
    tx_buffer[0] = FLASH_CMD_JEDEC_ID;
    tx_buffer[1] = 0xFF;
    tx_buffer[2] = 0xFF;
    tx_buffer[3] = 0xFF;

    if (spi_transfer(tx_buffer, 4, rx_buffer, 4) < 0) {
        return -1;
    }

    id[0] = rx_buffer[1];  /* Manufacturer ID */
    id[1] = rx_buffer[2];  /* Memory Type */
    id[2] = rx_buffer[3];  /* Capacity */

    return 0;
}

/* Read status register */
static uint8_t flash_read_status(void)
{
    tx_buffer[0] = FLASH_CMD_READ_STATUS;
    tx_buffer[1] = 0xFF;

    spi_transfer(tx_buffer, 2, rx_buffer, 2);

    return rx_buffer[1];
}

/* Write enable */
static void flash_write_enable(void)
{
    tx_buffer[0] = FLASH_CMD_WRITE_ENABLE;
    spi_transfer(tx_buffer, 1, rx_buffer, 1);
}

/* Wait for flash ready */
static void flash_wait_ready(void)
{
    int timeout = 1000;
    while ((flash_read_status() & 0x01) && timeout > 0) {
        delay_ms(1);
        timeout--;
    }
}

/* Sector erase (4KB) */
static int flash_sector_erase(uint32_t addr)
{
    flash_write_enable();

    tx_buffer[0] = FLASH_CMD_SECTOR_ERASE;
    tx_buffer[1] = (addr >> 16) & 0xFF;
    tx_buffer[2] = (addr >> 8) & 0xFF;
    tx_buffer[3] = addr & 0xFF;

    if (spi_transfer(tx_buffer, 4, rx_buffer, 4) < 0) {
        return -1;
    }

    flash_wait_ready();
    return 0;
}

/* Page program (up to 256 bytes) */
static int flash_page_program(uint32_t addr, const uint8_t *data, int len)
{
    if (len > 256) len = 256;

    flash_write_enable();

    tx_buffer[0] = FLASH_CMD_PAGE_PROGRAM;
    tx_buffer[1] = (addr >> 16) & 0xFF;
    tx_buffer[2] = (addr >> 8) & 0xFF;
    tx_buffer[3] = addr & 0xFF;

    for (int i = 0; i < len; i++) {
        tx_buffer[4 + i] = data[i];
    }

    if (spi_transfer(tx_buffer, 4 + len, rx_buffer, 4 + len) < 0) {
        return -1;
    }

    flash_wait_ready();
    return 0;
}

/* Read data */
static int flash_read(uint32_t addr, uint8_t *data, int len)
{
    if (len > 256) len = 256;

    tx_buffer[0] = FLASH_CMD_READ_DATA;
    tx_buffer[1] = (addr >> 16) & 0xFF;
    tx_buffer[2] = (addr >> 8) & 0xFF;
    tx_buffer[3] = addr & 0xFF;

    /* Fill TX with dummy bytes for reading */
    for (int i = 0; i < len; i++) {
        tx_buffer[4 + i] = 0xFF;
    }

    if (spi_transfer(tx_buffer, 4 + len, rx_buffer, 4 + len) < 0) {
        return -1;
    }

    /* Data starts at byte 4 */
    for (int i = 0; i < len; i++) {
        data[i] = rx_buffer[4 + i];
    }

    return len;
}

/* Command: PING */
static void cmd_ping(void)
{
    cdc_send("PONG\n");
}

/* Command: JEDEC - Read JEDEC ID */
static void cmd_jedec(void)
{
    uint8_t id[3];

    if (flash_read_jedec_id(id) < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    /* Output as hex */
    for (int i = 0; i < 3; i++) {
        CDC_OUT = hex_chars[(id[i] >> 4) & 0xF];
        CDC_OUT = hex_chars[id[i] & 0xF];
    }
    cdc_send("\n");
}

/* Command: STATUS - Read status register */
static void cmd_status(void)
{
    uint8_t status = flash_read_status();
    CDC_OUT = hex_chars[(status >> 4) & 0xF];
    CDC_OUT = hex_chars[status & 0xF];
    cdc_send("\n");
}

/* Command: ERASE <addr_hex> - Erase 4KB sector */
static void cmd_erase(const char *args)
{
    if (args[0] == '\0') {
        cdc_send("ERROR: Need 6-digit hex address\n");
        return;
    }

    /* Parse address (6 hex digits) */
    uint32_t addr = 0;
    int i = 0;
    while (args[i] && i < 6) {
        int n = hex_to_nibble(args[i]);
        if (n < 0) {
            cdc_send("ERROR: Invalid address\n");
            return;
        }
        addr = (addr << 4) | n;
        i++;
    }

    if (flash_sector_erase(addr) < 0) {
        cdc_send("ERROR: Erase failed\n");
        return;
    }

    cdc_send("OK\n");
}

/* Command: WRITE <addr_hex> <data_hex> - Write data */
static void cmd_write(const char *args)
{
    if (args[0] == '\0') {
        cdc_send("ERROR: Need 6-digit hex address\n");
        return;
    }

    /* Parse address (6 hex digits) */
    uint32_t addr = 0;
    int i = 0;
    while (args[i] && args[i] != ' ' && i < 6) {
        int n = hex_to_nibble(args[i]);
        if (n < 0) {
            cdc_send("ERROR: Invalid address\n");
            return;
        }
        addr = (addr << 4) | n;
        i++;
    }

    /* Skip whitespace */
    while (args[i] == ' ') i++;

    /* Parse data */
    static uint8_t data[256];
    int data_len = hex_to_bytes(&args[i], data, 256);
    if (data_len == 0) {
        cdc_send("ERROR: No data\n");
        return;
    }

    if (flash_page_program(addr, data, data_len) < 0) {
        cdc_send("ERROR: Write failed\n");
        return;
    }

    cdc_send("OK\n");
}

/* Command: READ <addr_hex> <len_hex> - Read data */
static void cmd_read(const char *args)
{
    if (args[0] == '\0') {
        cdc_send("ERROR: Need 6-digit hex address\n");
        return;
    }

    /* Parse address (6 hex digits) */
    uint32_t addr = 0;
    int i = 0;
    while (args[i] && args[i] != ' ' && i < 6) {
        int n = hex_to_nibble(args[i]);
        if (n < 0) {
            cdc_send("ERROR: Invalid address\n");
            return;
        }
        addr = (addr << 4) | n;
        i++;
    }

    /* Skip whitespace */
    while (args[i] == ' ') i++;

    /* Parse length (2 hex digits, default 16) */
    int len = 16;
    if (args[i] && args[i + 1]) {
        int hi = hex_to_nibble(args[i]);
        int lo = hex_to_nibble(args[i + 1]);
        if (hi >= 0 && lo >= 0) {
            len = (hi << 4) | lo;
        }
    }
    if (len > 256) len = 256;
    if (len == 0) len = 16;

    static uint8_t data[256];
    int result = flash_read(addr, data, len);
    if (result < 0) {
        cdc_send("ERROR: Read failed\n");
        return;
    }

    /* Output as hex */
    for (int j = 0; j < result; j++) {
        CDC_OUT = hex_chars[(data[j] >> 4) & 0xF];
        CDC_OUT = hex_chars[data[j] & 0xF];
    }
    cdc_send("\n");
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
    } else if (my_strcmp(cmd, "JEDEC") == 0) {
        cmd_jedec();
    } else if (my_strcmp(cmd, "STATUS") == 0) {
        cmd_status();
    } else if (my_strcmp(cmd, "ERASE") == 0) {
        cmd_erase(args);
    } else if (my_strcmp(cmd, "WRITE") == 0) {
        cmd_write(args);
    } else if (my_strcmp(cmd, "READ") == 0) {
        cmd_read(args);
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

    /* Initialize SPIM */
    spim_init();

    cdc_send("NRF52840 Flash Test Ready\n");

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
