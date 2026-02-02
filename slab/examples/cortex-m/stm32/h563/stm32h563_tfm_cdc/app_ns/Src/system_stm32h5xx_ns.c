/**
 * @file    system_stm32h5xx_ns.c
 * @brief   CMSIS Non-Secure system init (TF-M project)
 *         Clock config done by TF-M secure side.
 */

#include "stm32h5xx.h"

uint32_t SystemCoreClock = 250000000UL;

const uint8_t AHBPrescTable[16] = {
    0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U,
    1U, 2U, 3U, 4U, 6U, 7U, 8U, 9U
};

const uint8_t APBPrescTable[8] = {
    0U, 0U, 0U, 0U, 1U, 2U, 3U, 4U
};

void SystemInit(void)
{
#if (__FPU_PRESENT == 1) && (__FPU_USED == 1)
    SCB->CPACR |= ((3UL << 20U) | (3UL << 22U));
#endif
    SCB->VTOR = FLASH_BASE_NS;
}
