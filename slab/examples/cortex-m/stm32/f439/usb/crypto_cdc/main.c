/*
 * STM32F439 Crypto Test Firmware
 *
 * Tests CRYP (AES) and HASH (SHA-256) peripherals via USB CDC.
 * Commands are received over CDC, crypto operations performed,
 * and results returned.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>
#include "stm32f4.h"
#include "stm32f4_crypto.h"

/* Simple strcmp for bare-metal (no libc) */
static int my_strcmp(const char *s1, const char *s2)
{
    while (*s1 && *s1 == *s2) {
        s1++;
        s2++;
    }
    return (unsigned char)*s1 - (unsigned char)*s2;
}

/* CDC buffer (reserved for future use) */
#define CDC_BUF_SIZE 256

/* Hex conversion helpers */
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

/* CDC I/O over USART1 (0x40011000) - proxied to Python server */
#define CDC_USART_BASE   0x40011000
#define CDC_USART_SR     (*(volatile uint32_t *)(CDC_USART_BASE + 0x00))
#define CDC_USART_DR     (*(volatile uint32_t *)(CDC_USART_BASE + 0x04))
#define CDC_USART_BRR    (*(volatile uint32_t *)(CDC_USART_BASE + 0x08))
#define CDC_USART_CR1    (*(volatile uint32_t *)(CDC_USART_BASE + 0x0C))

#define USART_SR_RXNE    (1 << 5)   /* RX not empty */
#define USART_SR_TXE     (1 << 7)   /* TX empty (always ready) */

/* Send response over CDC (via USART1 registers) */
static void cdc_send(const char *str)
{
    while (*str) {
        CDC_USART_DR = *str++;
    }
}

/* AES-128-ECB encryption */
static void cmd_aes128_ecb_enc(const char *args)
{
    uint8_t key[16], data[16], out[16];
    char result[64];

    /* Parse key (16 bytes) and data (16 bytes) from hex */
    if (hex_to_bytes(args, key, 16) != 16 ||
        hex_to_bytes(args + 32, data, 16) != 16) {
        cdc_send("ERROR: Invalid input\n");
        return;
    }

    /* Configure CRYP for AES-128 ECB encrypt */
    cryp_aes_init(CRYP_KEYSIZE_128, CRYP_ALGOMODE_AES_ECB, 1);
    cryp_set_key_128(key);
    cryp_enable();

    /* Process block */
    cryp_process_block(data, out);

    cryp_disable();

    /* Return result */
    bytes_to_hex(out, 16, result);
    cdc_send(result);
}

/* AES-128-ECB decryption */
static void cmd_aes128_ecb_dec(const char *args)
{
    uint8_t key[16], data[16], out[16];
    char result[64];

    if (hex_to_bytes(args, key, 16) != 16 ||
        hex_to_bytes(args + 32, data, 16) != 16) {
        cdc_send("ERROR: Invalid input\n");
        return;
    }

    cryp_aes_init(CRYP_KEYSIZE_128, CRYP_ALGOMODE_AES_ECB, 0);
    cryp_set_key_128(key);
    cryp_enable();

    cryp_process_block(data, out);

    cryp_disable();

    bytes_to_hex(out, 16, result);
    cdc_send(result);
}

/* SHA-256 hash */
static void cmd_sha256(const char *args)
{
    uint8_t data[128];
    uint8_t digest[32];
    char result[80];
    int len;

    len = hex_to_bytes(args, data, sizeof(data));
    if (len < 0) {
        cdc_send("ERROR: Invalid input\n");
        return;
    }

    /* Initialize HASH for SHA-256 */
    hash_init(HASH_CR_ALGO_SHA256);

    /* Push data word by word */
    int i;
    for (i = 0; i + 4 <= len; i += 4) {
        uint32_t word = (data[i] << 24) | (data[i+1] << 16) |
                        (data[i+2] << 8) | data[i+3];
        hash_write_data(word);
    }

    /* Handle remaining bytes */
    if (i < len) {
        uint32_t word = 0;
        int remaining = len - i;
        for (int j = 0; j < remaining; j++) {
            word |= data[i + j] << (24 - j * 8);
        }
        hash_write_data(word);
    }

    /* Finalize */
    int remaining_bits = (len % 4) * 8;
    hash_finalize(remaining_bits);

    /* Read result */
    hash_read_sha256(digest);

    bytes_to_hex(digest, 32, result);
    cdc_send(result);
}

/* MD5 hash */
static void cmd_md5(const char *args)
{
    uint8_t data[128];
    uint8_t digest[16];
    char result[48];
    int len;

    len = hex_to_bytes(args, data, sizeof(data));
    if (len < 0) {
        cdc_send("ERROR: Invalid input\n");
        return;
    }

    hash_init(HASH_CR_ALGO_MD5);

    int i;
    for (i = 0; i + 4 <= len; i += 4) {
        uint32_t word = (data[i] << 24) | (data[i+1] << 16) |
                        (data[i+2] << 8) | data[i+3];
        hash_write_data(word);
    }

    if (i < len) {
        uint32_t word = 0;
        int remaining = len - i;
        for (int j = 0; j < remaining; j++) {
            word |= data[i + j] << (24 - j * 8);
        }
        hash_write_data(word);
    }

    int remaining_bits = (len % 4) * 8;
    hash_finalize(remaining_bits);

    hash_read_md5(digest);

    bytes_to_hex(digest, 16, result);
    cdc_send(result);
}

/* Process incoming command */
static void process_command(char *cmd)
{
    /* Skip leading whitespace */
    while (*cmd == ' ' || *cmd == '\t') cmd++;

    /* Find command and arguments */
    char *args = cmd;
    while (*args && *args != ' ' && *args != '\t') args++;
    if (*args) {
        *args++ = '\0';
        while (*args == ' ' || *args == '\t') args++;
    }

    /* Dispatch command */
    if (my_strcmp(cmd, "AES128_ECB_ENC") == 0) {
        cmd_aes128_ecb_enc(args);
    } else if (my_strcmp(cmd, "AES128_ECB_DEC") == 0) {
        cmd_aes128_ecb_dec(args);
    } else if (my_strcmp(cmd, "SHA256") == 0) {
        cmd_sha256(args);
    } else if (my_strcmp(cmd, "MD5") == 0) {
        cmd_md5(args);
    } else if (my_strcmp(cmd, "PING") == 0) {
        cdc_send("PONG\n");
    } else {
        cdc_send("ERROR: Unknown command\n");
    }
}

/* Enable crypto clocks */
static void enable_crypto_clocks(void)
{
    /* Enable CRYP and HASH clocks (AHB2) */
    RCC->AHB2ENR |= RCC_AHB2ENR_CRYPEN | RCC_AHB2ENR_HASHEN;
}

/* Main */
int main(void)
{
    /* Basic system init */
    enable_crypto_clocks();

    /* Send ready message */
    cdc_send("STM32F439 Crypto Ready\n");

    /* Main loop: poll USART1 for commands */
    while (1) {
        /* Check if USART has received data (RXNE flag) */
        if (CDC_USART_SR & USART_SR_RXNE) {
            uint32_t len = 0;
            char cmd[256];

            /* Read line from USART DR */
            while (len < sizeof(cmd) - 1) {
                /* Wait for next character */
                while (!(CDC_USART_SR & USART_SR_RXNE)) {}
                uint32_t c = CDC_USART_DR;
                if (c == '\n' || c == '\r') break;
                cmd[len++] = (char)c;
            }
            cmd[len] = '\0';

            if (len > 0) {
                process_command(cmd);
            }
        }
    }

    return 0;
}

/* Minimal startup code for Cortex-M4 */
void Reset_Handler(void)
{
    main();
    while (1);
}

void Default_Handler(void)
{
    while (1);
}

/* Vector table */
__attribute__((section(".vectors")))
void (* const vectors[])(void) = {
    (void (*)(void))0x20020000,  /* Initial SP (128KB SRAM) */
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
    /* IRQs... */
};
