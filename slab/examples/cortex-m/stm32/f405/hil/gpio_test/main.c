/*
 * STM32F405 GPIO HIL Test
 *
 * Bare-metal firmware that drives GPIOA output pins on real hardware
 * via HIL forwarding, then reads back the pin state and reports via
 * USART1 (emulated by SLAB).
 *
 * In HIL mode, GPIOA (0x40020000) is forwarded to real hardware via
 * pyOCD/SWD -- the GPIO register reads/writes hit the actual silicon.
 * All other peripherals (RCC, USART) are emulated by SLAB.
 *
 * Test sequence:
 *   1. Configure GPIOA pins 0-7 as outputs (on real hardware)
 *   2. Write 0xAA to ODR (alternating pattern)
 *   3. Read back IDR and verify
 *   4. Write 0x55 to ODR (inverted pattern)
 *   5. Read back IDR and verify
 *   6. Report PASS/FAIL over USART1
 *
 * USART1 output (115200 8N1 on PA9):
 *   "GPIO HIL Test\r\n"
 *   "MODER: xxxxxxxx\r\n"
 *   "ODR=0x000000AA IDR=0x000000AA\r\n"
 *   "ODR=0x00000055 IDR=0x00000055\r\n"
 *   "PASS\r\n" or "FAIL\r\n"
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2026 Twisted Wires Security Lab
 * SPDX-License-Identifier: Apache-2.0
 */

#include <stdint.h>
#include "stm32f4.h"

/* ------------------------------------------------------------------
 * USART1 minimal driver (emulated by SLAB)
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

    /* Enable GPIOA clock (AHB1) -- needed for USART TX pin */
    RCC->AHB1ENR |= (1UL << 0);

    /* 115200 baud @ 16 MHz HSI */
    USART1_BRR = 0x16D;

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

static void usart1_put_hex32(uint32_t val)
{
    static const char hex[] = "0123456789abcdef";
    usart1_puts("0x");
    for (int i = 28; i >= 0; i -= 4) {
        usart1_putc(hex[(val >> i) & 0xF]);
    }
}

/* ------------------------------------------------------------------
 * Main
 * ------------------------------------------------------------------ */

void Reset_Handler(void)
{
    int pass = 1;
    uint32_t idr_val;

    /* Enable GPIOA clock (AHB1 bit 0) */
    RCC->AHB1ENR |= (1UL << 0);

    /* Brief delay for clock to stabilize */
    for (volatile int i = 0; i < 100; i++);

    /* Init USART1 for output (emulated) */
    usart1_init();

    usart1_puts("GPIO HIL Test\r\n");

    /*
     * Configure GPIOA pins 0-7 as general-purpose output (push-pull).
     * MODER bits [15:0] = 0x5555 (each pin = 01 = output mode).
     * Preserve upper pins (8-15) for alternate functions (e.g. USART).
     */
    GPIOA->MODER &= ~0x0000FFFFUL;
    GPIOA->MODER |=  0x00005555UL;  /* PA0-PA7 = output */

    usart1_puts("MODER: ");
    usart1_put_hex32(GPIOA->MODER);
    usart1_puts("\r\n");

    /* Test pattern 1: 0xAA on PA0-PA7 */
    GPIOA->ODR = (GPIOA->ODR & ~0xFFUL) | 0xAAUL;

    /* Short delay for GPIO to settle */
    for (volatile int i = 0; i < 10; i++);

    idr_val = GPIOA->IDR;
    usart1_puts("ODR=");
    usart1_put_hex32(0xAA);
    usart1_puts(" IDR=");
    usart1_put_hex32(idr_val & 0xFF);
    usart1_puts("\r\n");

    if ((idr_val & 0xFF) != 0xAA) {
        pass = 0;
    }

    /* Test pattern 2: 0x55 on PA0-PA7 */
    GPIOA->ODR = (GPIOA->ODR & ~0xFFUL) | 0x55UL;

    for (volatile int i = 0; i < 10; i++);

    idr_val = GPIOA->IDR;
    usart1_puts("ODR=");
    usart1_put_hex32(0x55);
    usart1_puts(" IDR=");
    usart1_put_hex32(idr_val & 0xFF);
    usart1_puts("\r\n");

    if ((idr_val & 0xFF) != 0x55) {
        pass = 0;
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
