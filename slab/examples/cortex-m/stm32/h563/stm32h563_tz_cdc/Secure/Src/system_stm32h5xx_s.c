/**
 * @file    system_stm32h5xx_s.c
 * @brief   CMSIS Cortex-M33 Secure Device System Source File
 */

#include "stm32h5xx.h"

/* Vector table base offset - secure flash */
#define VECT_TAB_OFFSET  0x00000000UL

/* System clock frequency (updated by SystemClock_Config) */
uint32_t SystemCoreClock = 64000000UL;  /* HSI default at boot */

const uint8_t AHBPrescTable[16] = {
    0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U,
    1U, 2U, 3U, 4U, 6U, 7U, 8U, 9U
};

const uint8_t APBPrescTable[8] = {
    0U, 0U, 0U, 0U, 1U, 2U, 3U, 4U
};

/**
 * @brief  Setup the microcontroller system (called before main)
 */
void SystemInit(void)
{
    /* FPU settings: enable CP10 and CP11 full access */
#if (__FPU_PRESENT == 1) && (__FPU_USED == 1)
    SCB->CPACR |= ((3UL << 20U) | (3UL << 22U));  /* CP10 and CP11 Full Access */
#endif

    /* Set secure vector table */
    SCB->VTOR = FLASH_BASE_S | VECT_TAB_OFFSET;
}
