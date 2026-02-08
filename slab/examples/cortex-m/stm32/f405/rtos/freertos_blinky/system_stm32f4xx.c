/**
 * System Source File for FreeRTOS MCUemu Example
 *
 * Minimal implementation for MCUemu testing
 *
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <stdint.h>

/* Clock configuration */
uint32_t SystemCoreClock = 168000000;  /* 168 MHz for STM32F405 */

void SystemInit(void)
{
    /* Enable FPU (CP10 and CP11 coprocessors) */
    *((volatile uint32_t *)0xE000ED88) |= ((3UL << 10*2) | (3UL << 11*2));

    /* Reset RCC configuration */
    *((volatile uint32_t *)0x40023800) |= 0x00000001;  /* RCC_CR: Set HSION */
    *((volatile uint32_t *)0x40023808) = 0x00000000;   /* RCC_CFGR: Reset */

    /* Configure Vector Table location to flash */
    *((volatile uint32_t *)0xE000ED08) = 0x08000000;   /* SCB_VTOR */
}

void SystemCoreClockUpdate(void)
{
    SystemCoreClock = 168000000;
}

/* Required for FreeRTOS port */
void __libc_init_array(void)
{
    /* Minimal implementation - no static constructors */
}
