/**
 * CMSIS System Source File for STM32F4xx
 *
 * Minimal implementation for MCUemu testing
 *
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "stm32f4xx.h"

/* Clock configuration */
uint32_t SystemCoreClock = 16000000;  /* Default HSI */

const uint8_t AHBPrescTable[16] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 6, 7, 8, 9};
const uint8_t APBPrescTable[8]  = {0, 0, 0, 0, 1, 2, 3, 4};

void SystemInit(void)
{
    /* FPU settings - enable CP10 and CP11 coprocessors */
#if (__FPU_PRESENT == 1) && (__FPU_USED == 1)
    SCB->CPACR |= ((3UL << 10*2) | (3UL << 11*2));
#endif

    /* Reset the RCC clock configuration to the default reset state */
    RCC->CR |= (uint32_t)0x00000001;  /* Set HSION bit */
    RCC->CFGR = 0x00000000;           /* Reset CFGR register */
    RCC->CR &= (uint32_t)0xFEF6FFFF;  /* Reset HSEON, CSSON and PLLON bits */
    RCC->PLLCFGR = 0x24003010;        /* Reset PLLCFGR register */
    RCC->CR &= (uint32_t)0xFFFBFFFF;  /* Reset HSEBYP bit */
    RCC->CIR = 0x00000000;            /* Disable all interrupts */

    /* Configure the Vector Table location */
    SCB->VTOR = FLASH_BASE;
}

void SystemCoreClockUpdate(void)
{
    uint32_t tmp = 0, pllvco = 0, pllp = 2, pllsource = 0, pllm = 2;

    /* Get SYSCLK source */
    tmp = RCC->CFGR & RCC_CFGR_SWS;

    switch (tmp)
    {
        case 0x00:  /* HSI used as system clock source */
            SystemCoreClock = HSI_VALUE;
            break;
        case 0x04:  /* HSE used as system clock source */
            SystemCoreClock = HSE_VALUE;
            break;
        case 0x08:  /* PLL used as system clock source */
            pllsource = (RCC->PLLCFGR & RCC_PLLCFGR_PLLSRC) >> 22;
            pllm = RCC->PLLCFGR & RCC_PLLCFGR_PLLM;

            if (pllsource != 0) {
                pllvco = (HSE_VALUE / pllm) * ((RCC->PLLCFGR & RCC_PLLCFGR_PLLN) >> 6);
            } else {
                pllvco = (HSI_VALUE / pllm) * ((RCC->PLLCFGR & RCC_PLLCFGR_PLLN) >> 6);
            }

            pllp = (((RCC->PLLCFGR & RCC_PLLCFGR_PLLP) >> 16) + 1) * 2;
            SystemCoreClock = pllvco / pllp;
            break;
        default:
            SystemCoreClock = HSI_VALUE;
            break;
    }

    /* Compute HCLK frequency */
    tmp = AHBPrescTable[((RCC->CFGR & RCC_CFGR_HPRE) >> 4)];
    SystemCoreClock >>= tmp;
}
