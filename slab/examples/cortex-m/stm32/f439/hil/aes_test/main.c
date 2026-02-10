/*
 * STM32F439 AES-128 ECB HIL Test
 *
 * Bare-metal firmware that performs AES-128 ECB encryption using the
 * hardware CRYP accelerator, then outputs the ciphertext over USART1.
 *
 * In HIL mode, the CRYP peripheral (0x50060000) is forwarded to real
 * hardware via pyOCD/SWD -- the AES computation runs on actual silicon.
 * All other peripherals (RCC, GPIO, USART) are emulated by SLAB.
 *
 * NIST AES-128 ECB Test Vector (FIPS 197 Appendix B):
 *   Key:       2b7e151628aed2a6abf7158809cf4f3c
 *   Plaintext: 3243f6a8885a308d313198a2e0370734
 *   Expected:  3925841d02dc09fbdc118597196a0b32
 *
 * USART1 output (115200 8N1 on PA9):
 *   "AES-128 ECB HIL Test\r\n"
 *   "Key: 2b7e151628aed2a6abf7158809cf4f3c\r\n"
 *   "PT:  3243f6a8885a308d313198a2e0370734\r\n"
 *   "CT:  3925841d02dc09fbdc118597196a0b32\r\n"  (if CRYP works)
 *   "PASS\r\n" or "FAIL\r\n"
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2026 Twisted Wires Security Lab
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdint.h>
#include "stm32f4.h"
#include "stm32f4_crypto.h"

/* NIST test vector (FIPS 197 Appendix B) */
static const uint8_t aes_key[16] = {
    0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
    0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c
};

static const uint8_t plaintext[16] = {
    0x32, 0x43, 0xf6, 0xa8, 0x88, 0x5a, 0x30, 0x8d,
    0x31, 0x31, 0x98, 0xa2, 0xe0, 0x37, 0x07, 0x34
};

static const uint8_t expected_ct[16] = {
    0x39, 0x25, 0x84, 0x1d, 0x02, 0xdc, 0x09, 0xfb,
    0xdc, 0x11, 0x85, 0x97, 0x19, 0x6a, 0x0b, 0x32
};

/* ------------------------------------------------------------------
 * USART1 minimal driver (PA9=TX, emulated by SLAB)
 * ------------------------------------------------------------------ */

#define USART1_BASE  0x40011000
#define USART1_SR    (*(volatile uint32_t *)(USART1_BASE + 0x00))
#define USART1_DR    (*(volatile uint32_t *)(USART1_BASE + 0x04))
#define USART1_BRR   (*(volatile uint32_t *)(USART1_BASE + 0x08))
#define USART1_CR1   (*(volatile uint32_t *)(USART1_BASE + 0x0C))

static void usart1_init(void)
{
    /* Enable USART1 clock (APB2) */
    RCC->APB2ENR |= (1UL << 4);

    /* Enable GPIOA clock (AHB1) */
    RCC->AHB1ENR |= (1UL << 0);

    /* Configure PA9 as USART1 TX (AF7) */
    GPIOA->MODER  &= ~(3UL << 18);
    GPIOA->MODER  |=  (2UL << 18);  /* AF mode */
    GPIOA->AFRH   &= ~(0xFUL << 4);
    GPIOA->AFRH   |=  (7UL << 4);   /* AF7 */

    /* 115200 baud at 168 MHz APB2 (assuming HSI, approximate) */
    USART1_BRR = 0x16D;  /* ~115200 @ 16 MHz HSI */

    /* Enable USART + TX */
    USART1_CR1 = (1UL << 13) | (1UL << 3);  /* UE | TE */
}

static void usart1_putc(char c)
{
    while (!(USART1_SR & (1UL << 7)));  /* Wait for TXE */
    USART1_DR = c;
}

static void usart1_puts(const char *s)
{
    while (*s) usart1_putc(*s++);
}

static void usart1_put_hex(const uint8_t *data, int len)
{
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < len; i++) {
        usart1_putc(hex[data[i] >> 4]);
        usart1_putc(hex[data[i] & 0x0F]);
    }
}

/* ------------------------------------------------------------------
 * Main
 * ------------------------------------------------------------------ */

void Reset_Handler(void)
{
    uint8_t ciphertext[16];
    int pass = 1;

    /* Enable CRYP clock (AHB2) */
    RCC->AHB2ENR |= RCC_AHB2ENR_CRYPEN;

    /* Brief delay for clock to stabilize */
    for (volatile int i = 0; i < 100; i++);

    /* Init USART1 for output */
    usart1_init();

    usart1_puts("AES-128 ECB HIL Test\r\n");
    usart1_puts("Key: ");
    usart1_put_hex(aes_key, 16);
    usart1_puts("\r\n");
    usart1_puts("PT:  ");
    usart1_put_hex(plaintext, 16);
    usart1_puts("\r\n");

    /* Configure CRYP for AES-128 ECB encrypt */
    cryp_aes_init(CRYP_KEYSIZE_128, CRYP_ALGOMODE_AES_ECB, 1);
    cryp_set_key_128(aes_key);
    cryp_enable();

    /* Encrypt one block */
    cryp_process_block(plaintext, ciphertext);

    cryp_disable();

    /* Output result */
    usart1_puts("CT:  ");
    usart1_put_hex(ciphertext, 16);
    usart1_puts("\r\n");

    /* Verify against expected */
    for (int i = 0; i < 16; i++) {
        if (ciphertext[i] != expected_ct[i]) {
            pass = 0;
            break;
        }
    }

    usart1_puts(pass ? "PASS\r\n" : "FAIL\r\n");

    /* Halt */
    while (1) __asm__("wfi");
}

/* Vector table */
extern uint32_t _estack;

__attribute__((section(".vectors"), used))
void *vector_table[] = {
    &_estack,
    (void *)Reset_Handler,
};
