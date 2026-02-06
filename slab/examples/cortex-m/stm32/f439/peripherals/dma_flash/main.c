/*
 * STM32F439 DMA + SPI Flash Test Firmware
 *
 * Tests DMA-driven SPI transfers to external W25Q128 Flash:
 * - DMA Memory-to-Peripheral (TX)
 * - DMA Peripheral-to-Memory (RX)
 * - CDC ACM interface for test commands
 *
 * Commands via CDC:
 *   PING           -> PONG
 *   JEDEC          -> Flash JEDEC ID (hex)
 *   ERASE xxxx     -> Erase 4KB sector at address
 *   WRITE xxxx dd  -> Write data to address (DMA)
 *   READ xxxx nn   -> Read nn bytes from address (DMA)
 *   DMA_STATUS     -> Show DMA transfer status
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include <stdbool.h>
#include "stm32f4.h"
#include "stm32f4_spi.h"

/* CDC Interface (memory-mapped) */
#define CDC_OUT     (*(volatile uint32_t *)0xE0000000)
#define CDC_IN      (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS  (*(volatile uint32_t *)0xE0000008)
#define CDC_RX_READY    0x01
#define CDC_TX_READY    0x02

/* SPI Flash Commands */
#define FLASH_CMD_WRITE_ENABLE   0x06
#define FLASH_CMD_WRITE_DISABLE  0x04
#define FLASH_CMD_READ_STATUS    0x05
#define FLASH_CMD_READ_DATA      0x03
#define FLASH_CMD_FAST_READ      0x0B
#define FLASH_CMD_PAGE_PROGRAM   0x02
#define FLASH_CMD_SECTOR_ERASE   0x20
#define FLASH_CMD_JEDEC_ID       0x9F

/* SPI Flash Status bits */
#define FLASH_STATUS_BUSY        0x01
#define FLASH_STATUS_WEL         0x02

/* DMA Buffers */
static uint8_t dma_tx_buffer[256 + 4];  /* Command + data */
static uint8_t dma_rx_buffer[256 + 4];  /* Response */

/* DMA Transfer state */
static volatile bool dma_tx_complete = false;
static volatile bool dma_rx_complete = false;

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

/* Configure DMA2 Stream 3 for SPI1 TX (Channel 3) */
static void dma_spi_tx_init(void)
{
    /* Reset DMA stream */
    DMA2->S[3].CR = 0;
    while (DMA2->S[3].CR & DMA_SxCR_EN);

    /* Clear interrupt flags */
    DMA2->LIFCR = (0x3F << 22);  /* Clear all flags for stream 3 */

    /* Configure stream:
     * - Channel 3 (SPI1_TX)
     * - Memory-to-peripheral
     * - Memory increment enable
     * - 8-bit transfers
     * - Transfer complete interrupt enable
     */
    DMA2->S[3].CR = (3 << 25) |    /* Channel 3 */
                 (1 << 6) |      /* Memory-to-peripheral */
                 (1 << 10) |     /* Memory increment */
                 (0 << 13) |     /* Peripheral size: 8-bit */
                 (0 << 11) |     /* Memory size: 8-bit */
                 (1 << 4);       /* Transfer complete interrupt */
}

/* Configure DMA2 Stream 0 for SPI1 RX (Channel 3) */
static void dma_spi_rx_init(void)
{
    /* Reset DMA stream */
    DMA2->S[0].CR = 0;
    while (DMA2->S[0].CR & DMA_SxCR_EN);

    /* Clear interrupt flags */
    DMA2->LIFCR = (0x3F << 0);  /* Clear all flags for stream 0 */

    /* Configure stream:
     * - Channel 3 (SPI1_RX)
     * - Peripheral-to-memory
     * - Memory increment enable
     * - 8-bit transfers
     * - Transfer complete interrupt enable
     */
    DMA2->S[0].CR = (3 << 25) |    /* Channel 3 */
                 (0 << 6) |      /* Peripheral-to-memory */
                 (1 << 10) |     /* Memory increment */
                 (0 << 13) |     /* Peripheral size: 8-bit */
                 (0 << 11) |     /* Memory size: 8-bit */
                 (1 << 4);       /* Transfer complete interrupt */
}

/* Start DMA TX transfer */
static void dma_spi_tx_start(const uint8_t *data, uint32_t len)
{
    dma_tx_complete = false;

    /* Disable stream first */
    DMA2->S[3].CR &= ~DMA_SxCR_EN;
    while (DMA2->S[3].CR & DMA_SxCR_EN);

    /* Clear flags */
    DMA2->LIFCR = (0x3F << 22);

    /* Set addresses and count */
    DMA2->S[3].PAR = (uint32_t)&SPI1->DR;
    DMA2->S[3].M0AR = (uint32_t)data;
    DMA2->S[3].NDTR = len;

    /* Enable DMA stream */
    DMA2->S[3].CR |= DMA_SxCR_EN;

    /* Enable SPI TX DMA */
    SPI1->CR2 |= SPI_CR2_TXDMAEN;
}

/* Start DMA RX transfer */
static void dma_spi_rx_start(uint8_t *data, uint32_t len)
{
    dma_rx_complete = false;

    /* Disable stream first */
    DMA2->S[0].CR &= ~DMA_SxCR_EN;
    while (DMA2->S[0].CR & DMA_SxCR_EN);

    /* Clear flags */
    DMA2->LIFCR = (0x3F << 0);

    /* Set addresses and count */
    DMA2->S[0].PAR = (uint32_t)&SPI1->DR;
    DMA2->S[0].M0AR = (uint32_t)data;
    DMA2->S[0].NDTR = len;

    /* Enable DMA stream */
    DMA2->S[0].CR |= DMA_SxCR_EN;

    /* Enable SPI RX DMA */
    SPI1->CR2 |= SPI_CR2_RXDMAEN;
}

/* Wait for DMA TX complete */
static void dma_spi_tx_wait(void)
{
    /* Poll for transfer complete */
    while (!(DMA2->LISR & (1 << 27)));  /* TCIF3 */

    /* Clear flag */
    DMA2->LIFCR = (1 << 27);

    /* Disable DMA */
    SPI1->CR2 &= ~SPI_CR2_TXDMAEN;

    dma_tx_complete = true;
}

/* Wait for DMA RX complete */
static void dma_spi_rx_wait(void)
{
    /* Poll for transfer complete */
    while (!(DMA2->LISR & (1 << 5)));  /* TCIF0 */

    /* Clear flag */
    DMA2->LIFCR = (1 << 5);

    /* Disable DMA */
    SPI1->CR2 &= ~SPI_CR2_RXDMAEN;

    dma_rx_complete = true;
}

/* SPI CS control */
static void spi_cs_low(void)
{
    GPIOA->BSRR = (1 << (4 + 16));  /* PA4 low */
}

static void spi_cs_high(void)
{
    GPIOA->BSRR = (1 << 4);  /* PA4 high */
}

/* Initialize SPI1 */
static void local_spi_init(void)
{
    /* Enable clocks */
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_DMA2EN;
    RCC->APB2ENR |= RCC_APB2ENR_SPI1EN;

    /* Configure GPIO:
     * PA4 - CS (output)
     * PA5 - SCK (AF5)
     * PA6 - MISO (AF5)
     * PA7 - MOSI (AF5)
     */
    GPIOA->MODER &= ~((3 << 8) | (3 << 10) | (3 << 12) | (3 << 14));
    GPIOA->MODER |= (1 << 8) | (2 << 10) | (2 << 12) | (2 << 14);

    /* Set alternate function 5 for SPI1 */
    GPIOA->AFRL &= ~(0xFFF << 20);
    GPIOA->AFRL |= (5 << 20) | (5 << 24) | (5 << 28);

    /* CS high initially */
    spi_cs_high();

    /* Configure SPI1:
     * - Master mode
     * - Clock polarity low, phase 1st edge
     * - 8-bit data
     * - Software CS
     * - Prescaler /4
     */
    SPI1->CR1 = SPI_CR1_MSTR |
                SPI_CR1_SSM |
                SPI_CR1_SSI |
                (1 << 3);  /* BR = /4 */

    /* Enable SPI */
    SPI1->CR1 |= SPI_CR1_SPE;

    /* Initialize DMA */
    dma_spi_tx_init();
    dma_spi_rx_init();
}

/* SPI transfer with DMA */
static void spi_dma_transfer(const uint8_t *tx, uint8_t *rx, uint32_t len)
{
    spi_cs_low();

    /* Start both TX and RX DMA */
    dma_spi_rx_start(rx, len);
    dma_spi_tx_start(tx, len);

    /* Wait for completion */
    dma_spi_tx_wait();
    dma_spi_rx_wait();

    /* Wait for SPI not busy */
    while (SPI1->SR & SPI_SR_BSY);

    spi_cs_high();
}

/* Read Flash JEDEC ID */
static void flash_read_jedec_id(uint8_t *id)
{
    dma_tx_buffer[0] = FLASH_CMD_JEDEC_ID;
    dma_tx_buffer[1] = 0xFF;
    dma_tx_buffer[2] = 0xFF;
    dma_tx_buffer[3] = 0xFF;

    spi_dma_transfer(dma_tx_buffer, dma_rx_buffer, 4);

    id[0] = dma_rx_buffer[1];
    id[1] = dma_rx_buffer[2];
    id[2] = dma_rx_buffer[3];
}

/* Read Flash status register */
static uint8_t flash_read_status(void)
{
    dma_tx_buffer[0] = FLASH_CMD_READ_STATUS;
    dma_tx_buffer[1] = 0xFF;

    spi_dma_transfer(dma_tx_buffer, dma_rx_buffer, 2);

    return dma_rx_buffer[1];
}

/* Wait for Flash not busy */
static void flash_wait_ready(void)
{
    while (flash_read_status() & FLASH_STATUS_BUSY);
}

/* Write enable */
static void flash_write_enable(void)
{
    dma_tx_buffer[0] = FLASH_CMD_WRITE_ENABLE;
    spi_dma_transfer(dma_tx_buffer, dma_rx_buffer, 1);
}

/* Erase 4KB sector */
static void flash_sector_erase(uint32_t addr)
{
    flash_write_enable();

    dma_tx_buffer[0] = FLASH_CMD_SECTOR_ERASE;
    dma_tx_buffer[1] = (addr >> 16) & 0xFF;
    dma_tx_buffer[2] = (addr >> 8) & 0xFF;
    dma_tx_buffer[3] = addr & 0xFF;

    spi_dma_transfer(dma_tx_buffer, dma_rx_buffer, 4);

    flash_wait_ready();
}

/* Page program (up to 256 bytes) */
static void flash_page_program(uint32_t addr, const uint8_t *data, uint32_t len)
{
    if (len > 256) len = 256;

    flash_write_enable();

    dma_tx_buffer[0] = FLASH_CMD_PAGE_PROGRAM;
    dma_tx_buffer[1] = (addr >> 16) & 0xFF;
    dma_tx_buffer[2] = (addr >> 8) & 0xFF;
    dma_tx_buffer[3] = addr & 0xFF;

    for (uint32_t i = 0; i < len; i++) {
        dma_tx_buffer[4 + i] = data[i];
    }

    spi_dma_transfer(dma_tx_buffer, dma_rx_buffer, 4 + len);

    flash_wait_ready();
}

/* Read data */
static void flash_read_data(uint32_t addr, uint8_t *data, uint32_t len)
{
    if (len > 256) len = 256;

    dma_tx_buffer[0] = FLASH_CMD_READ_DATA;
    dma_tx_buffer[1] = (addr >> 16) & 0xFF;
    dma_tx_buffer[2] = (addr >> 8) & 0xFF;
    dma_tx_buffer[3] = addr & 0xFF;

    /* Fill dummy bytes */
    for (uint32_t i = 0; i < len; i++) {
        dma_tx_buffer[4 + i] = 0xFF;
    }

    spi_dma_transfer(dma_tx_buffer, dma_rx_buffer, 4 + len);

    for (uint32_t i = 0; i < len; i++) {
        data[i] = dma_rx_buffer[4 + i];
    }
}

/* Command handlers */
static void cmd_ping(void)
{
    cdc_puts("PONG\n");
}

static void cmd_jedec(void)
{
    uint8_t id[3];
    flash_read_jedec_id(id);
    cdc_put_hex8(id[0]);
    cdc_put_hex8(id[1]);
    cdc_put_hex8(id[2]);
    cdc_putc('\n');
}

static void cmd_erase(const char *args)
{
    uint32_t addr = parse_hex(args, 4);
    flash_sector_erase(addr);
    cdc_puts("OK\n");
}

static void cmd_write(const char *args)
{
    uint32_t addr = parse_hex(args, 4);
    const char *data_str = args + 4;
    while (*data_str == ' ') data_str++;

    /* Parse hex data */
    uint8_t data[256];
    int len = 0;
    while (*data_str && len < 256) {
        if (data_str[1]) {
            data[len++] = parse_hex(data_str, 2);
            data_str += 2;
        } else {
            break;
        }
    }

    if (len > 0) {
        flash_page_program(addr, data, len);
        cdc_puts("OK\n");
    } else {
        cdc_puts("ERROR: No data\n");
    }
}

static void cmd_read(const char *args)
{
    uint32_t addr = parse_hex(args, 4);
    const char *len_str = args + 4;
    while (*len_str == ' ') len_str++;
    uint32_t len = parse_hex(len_str, 2);

    if (len == 0) len = 16;
    if (len > 64) len = 64;

    uint8_t data[64];
    flash_read_data(addr, data, len);

    for (uint32_t i = 0; i < len; i++) {
        cdc_put_hex8(data[i]);
    }
    cdc_putc('\n');
}

static void cmd_dma_status(void)
{
    cdc_puts("DMA2_S3CR=");
    cdc_put_hex8((DMA2->S[3].CR >> 24) & 0xFF);
    cdc_put_hex8((DMA2->S[3].CR >> 16) & 0xFF);
    cdc_put_hex8((DMA2->S[3].CR >> 8) & 0xFF);
    cdc_put_hex8(DMA2->S[3].CR & 0xFF);
    cdc_puts("\nDMA2_S0CR=");
    cdc_put_hex8((DMA2->S[0].CR >> 24) & 0xFF);
    cdc_put_hex8((DMA2->S[0].CR >> 16) & 0xFF);
    cdc_put_hex8((DMA2->S[0].CR >> 8) & 0xFF);
    cdc_put_hex8(DMA2->S[0].CR & 0xFF);
    cdc_puts("\nTX_DONE=");
    cdc_putc(dma_tx_complete ? '1' : '0');
    cdc_puts("\nRX_DONE=");
    cdc_putc(dma_rx_complete ? '1' : '0');
    cdc_putc('\n');
}

static void process_command(const char *cmd)
{
    if (strcmp(cmd, "PING") == 0) {
        cmd_ping();
    } else if (strcmp(cmd, "JEDEC") == 0) {
        cmd_jedec();
    } else if (strncmp(cmd, "ERASE ", 6) == 0) {
        cmd_erase(cmd + 6);
    } else if (strncmp(cmd, "WRITE ", 6) == 0) {
        cmd_write(cmd + 6);
    } else if (strncmp(cmd, "READ ", 5) == 0) {
        cmd_read(cmd + 5);
    } else if (strcmp(cmd, "DMA_STATUS") == 0) {
        cmd_dma_status();
    } else {
        cdc_puts("ERROR: Unknown command\n");
    }
}

int main(void)
{
    char cmd_buffer[128];

    /* Initialize SPI with DMA */
    local_spi_init();

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
    (void (*)(void))0x20030000,  /* Initial SP (192KB SRAM) */
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
