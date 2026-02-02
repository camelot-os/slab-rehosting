/*
 * ILI9341 LCD Test Firmware with CDC-ACM Interface
 *
 * Tests ILI9341 TFT LCD via USB CDC commands.
 * Commands are received over CDC, LCD operations performed,
 * and results returned.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "stm32f4.h"
#include "stm32f4_spi.h"

/* LCD configuration */
#define LCD_WIDTH       240
#define LCD_HEIGHT      320

/* ILI9341 commands */
#define LCD_CMD_NOP         0x00
#define LCD_CMD_SWRESET     0x01
#define LCD_CMD_SLEEP_OUT   0x11
#define LCD_CMD_DISPLAY_ON  0x29
#define LCD_CMD_DISPLAY_OFF 0x28
#define LCD_CMD_COLUMN_ADDR 0x2A
#define LCD_CMD_PAGE_ADDR   0x2B
#define LCD_CMD_MEMORY_WRITE 0x2C
#define LCD_CMD_MADCTL      0x36
#define LCD_CMD_PIXEL_FORMAT 0x3A
#define LCD_CMD_READ_ID     0x04

/* CDC I/O addresses (emulation) */
#define CDC_OUT         (*(volatile uint32_t *)0xE0000000)
#define CDC_IN          (*(volatile uint32_t *)0xE0000004)
#define CDC_STATUS      (*(volatile uint32_t *)0xE0000008)

/* SPI CS and D/C control */
#define LCD_CS_LOW()    (*(volatile uint32_t *)0xE0000010) = 0
#define LCD_CS_HIGH()   (*(volatile uint32_t *)0xE0000010) = 1
#define LCD_DC_LOW()    (*(volatile uint32_t *)0xE0000014) = 0
#define LCD_DC_HIGH()   (*(volatile uint32_t *)0xE0000014) = 1

/* RGB565 color macros */
#define RGB565(r, g, b) (((r & 0x1F) << 11) | ((g & 0x3F) << 5) | (b & 0x1F))
#define RGB565_RED      RGB565(31, 0, 0)
#define RGB565_GREEN    RGB565(0, 63, 0)
#define RGB565_BLUE     RGB565(0, 0, 31)
#define RGB565_WHITE    RGB565(31, 63, 31)
#define RGB565_BLACK    0x0000

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

/* LCD: Write command */
static void lcd_write_cmd(uint8_t cmd)
{
    LCD_DC_LOW();
    LCD_CS_LOW();
    spi_xfer(cmd);
    LCD_CS_HIGH();
}

/* LCD: Write data byte */
static void lcd_write_data(uint8_t data)
{
    LCD_DC_HIGH();
    LCD_CS_LOW();
    spi_xfer(data);
    LCD_CS_HIGH();
}

/* LCD: Write data buffer */
static void lcd_write_data_buf(const uint8_t *data, int len)
{
    LCD_DC_HIGH();
    LCD_CS_LOW();
    for (int i = 0; i < len; i++) {
        spi_xfer(data[i]);
    }
    LCD_CS_HIGH();
}

/* LCD: Initialize */
static void lcd_init(void)
{
    /* Software reset */
    lcd_write_cmd(LCD_CMD_SWRESET);
    delay_ms(150);

    /* Sleep out */
    lcd_write_cmd(LCD_CMD_SLEEP_OUT);
    delay_ms(50);

    /* Pixel format: RGB565 */
    lcd_write_cmd(LCD_CMD_PIXEL_FORMAT);
    lcd_write_data(0x55);

    /* Display ON */
    lcd_write_cmd(LCD_CMD_DISPLAY_ON);
    delay_ms(50);
}

/* LCD: Set window */
static void lcd_set_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1)
{
    uint8_t data[4];

    /* Column address */
    lcd_write_cmd(LCD_CMD_COLUMN_ADDR);
    data[0] = x0 >> 8;
    data[1] = x0 & 0xFF;
    data[2] = x1 >> 8;
    data[3] = x1 & 0xFF;
    lcd_write_data_buf(data, 4);

    /* Page address */
    lcd_write_cmd(LCD_CMD_PAGE_ADDR);
    data[0] = y0 >> 8;
    data[1] = y0 & 0xFF;
    data[2] = y1 >> 8;
    data[3] = y1 & 0xFF;
    lcd_write_data_buf(data, 4);
}

/* LCD: Fill rectangle */
static void lcd_fill_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t color)
{
    lcd_set_window(x, y, x + w - 1, y + h - 1);
    lcd_write_cmd(LCD_CMD_MEMORY_WRITE);

    uint8_t hi = color >> 8;
    uint8_t lo = color & 0xFF;

    LCD_DC_HIGH();
    LCD_CS_LOW();
    for (uint32_t i = 0; i < (uint32_t)w * h; i++) {
        spi_xfer(hi);
        spi_xfer(lo);
    }
    LCD_CS_HIGH();
}

/* LCD: Set pixel */
static void lcd_set_pixel(uint16_t x, uint16_t y, uint16_t color)
{
    lcd_set_window(x, y, x, y);
    lcd_write_cmd(LCD_CMD_MEMORY_WRITE);
    lcd_write_data(color >> 8);
    lcd_write_data(color & 0xFF);
}

/* LCD: Draw horizontal line */
static void lcd_draw_hline(uint16_t x, uint16_t y, uint16_t len, uint16_t color)
{
    lcd_fill_rect(x, y, len, 1, color);
}

/* LCD: Draw vertical line */
static void lcd_draw_vline(uint16_t x, uint16_t y, uint16_t len, uint16_t color)
{
    lcd_fill_rect(x, y, 1, len, color);
}

/* Command: INIT - Initialize LCD */
static void cmd_init(void)
{
    lcd_init();
    cdc_send("OK\n");
}

/* Command: CLEAR <color_hex> - Clear screen */
static void cmd_clear(const char *args)
{
    uint8_t color_bytes[2];
    uint16_t color = RGB565_BLACK;

    if (hex_to_bytes(args, color_bytes, 2) == 2) {
        color = (color_bytes[0] << 8) | color_bytes[1];
    }

    lcd_fill_rect(0, 0, LCD_WIDTH, LCD_HEIGHT, color);
    cdc_send("OK\n");
}

/* Command: FILL <x> <y> <w> <h> <color> - Fill rectangle */
static void cmd_fill(const char *args)
{
    uint8_t params[10];
    if (hex_to_bytes(args, params, 10) < 10) {
        cdc_send("ERROR: Need x(2), y(2), w(2), h(2), color(2)\n");
        return;
    }

    uint16_t x = (params[0] << 8) | params[1];
    uint16_t y = (params[2] << 8) | params[3];
    uint16_t w = (params[4] << 8) | params[5];
    uint16_t h = (params[6] << 8) | params[7];
    uint16_t color = (params[8] << 8) | params[9];

    if (x >= LCD_WIDTH || y >= LCD_HEIGHT) {
        cdc_send("ERROR: Out of bounds\n");
        return;
    }

    if (x + w > LCD_WIDTH) w = LCD_WIDTH - x;
    if (y + h > LCD_HEIGHT) h = LCD_HEIGHT - y;

    lcd_fill_rect(x, y, w, h, color);
    cdc_send("OK\n");
}

/* Command: PIXEL <x> <y> <color> - Set pixel */
static void cmd_pixel(const char *args)
{
    uint8_t params[6];
    if (hex_to_bytes(args, params, 6) < 6) {
        cdc_send("ERROR: Need x(2), y(2), color(2)\n");
        return;
    }

    uint16_t x = (params[0] << 8) | params[1];
    uint16_t y = (params[2] << 8) | params[3];
    uint16_t color = (params[4] << 8) | params[5];

    if (x >= LCD_WIDTH || y >= LCD_HEIGHT) {
        cdc_send("ERROR: Out of bounds\n");
        return;
    }

    lcd_set_pixel(x, y, color);
    cdc_send("OK\n");
}

/* Command: HLINE <x> <y> <len> <color> - Draw horizontal line */
static void cmd_hline(const char *args)
{
    uint8_t params[8];
    if (hex_to_bytes(args, params, 8) < 8) {
        cdc_send("ERROR: Need x(2), y(2), len(2), color(2)\n");
        return;
    }

    uint16_t x = (params[0] << 8) | params[1];
    uint16_t y = (params[2] << 8) | params[3];
    uint16_t len = (params[4] << 8) | params[5];
    uint16_t color = (params[6] << 8) | params[7];

    if (x >= LCD_WIDTH || y >= LCD_HEIGHT) {
        cdc_send("ERROR: Out of bounds\n");
        return;
    }

    if (x + len > LCD_WIDTH) len = LCD_WIDTH - x;

    lcd_draw_hline(x, y, len, color);
    cdc_send("OK\n");
}

/* Command: VLINE <x> <y> <len> <color> - Draw vertical line */
static void cmd_vline(const char *args)
{
    uint8_t params[8];
    if (hex_to_bytes(args, params, 8) < 8) {
        cdc_send("ERROR: Need x(2), y(2), len(2), color(2)\n");
        return;
    }

    uint16_t x = (params[0] << 8) | params[1];
    uint16_t y = (params[2] << 8) | params[3];
    uint16_t len = (params[4] << 8) | params[5];
    uint16_t color = (params[6] << 8) | params[7];

    if (x >= LCD_WIDTH || y >= LCD_HEIGHT) {
        cdc_send("ERROR: Out of bounds\n");
        return;
    }

    if (y + len > LCD_HEIGHT) len = LCD_HEIGHT - y;

    lcd_draw_vline(x, y, len, color);
    cdc_send("OK\n");
}

/* Command: PATTERN - Draw test pattern */
static void cmd_pattern(void)
{
    /* Fill with bars */
    lcd_fill_rect(0, 0, 60, 320, RGB565_RED);
    lcd_fill_rect(60, 0, 60, 320, RGB565_GREEN);
    lcd_fill_rect(120, 0, 60, 320, RGB565_BLUE);
    lcd_fill_rect(180, 0, 60, 320, RGB565_WHITE);
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

    if (my_strcmp(cmd, "INIT") == 0) {
        cmd_init();
    } else if (my_strcmp(cmd, "CLEAR") == 0) {
        cmd_clear(args);
    } else if (my_strcmp(cmd, "FILL") == 0) {
        cmd_fill(args);
    } else if (my_strcmp(cmd, "PIXEL") == 0) {
        cmd_pixel(args);
    } else if (my_strcmp(cmd, "HLINE") == 0) {
        cmd_hline(args);
    } else if (my_strcmp(cmd, "VLINE") == 0) {
        cmd_vline(args);
    } else if (my_strcmp(cmd, "PATTERN") == 0) {
        cmd_pattern();
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
    LCD_CS_HIGH();

    cdc_send("ILI9341 LCD Test Ready\n");

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
