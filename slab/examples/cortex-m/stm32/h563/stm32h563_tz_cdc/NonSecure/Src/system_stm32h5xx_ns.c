/**
 * @file    system_stm32h5xx_ns.c
 * @brief   CMSIS Cortex-M33 Non-Secure Device System Source File
 *
 * Note: Clock configuration is done by the Secure world before jumping here.
 * This file only sets the vector table for the non-secure application.
 */

#include "stm32h5xx.h"

/* Non-secure flash base for vector table */
#define VECT_TAB_NS_OFFSET  0x00000000UL

/* System clock frequency (set by Secure world, 250 MHz) */
uint32_t SystemCoreClock = 250000000UL;

const uint8_t AHBPrescTable[16] = {
    0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U,
    1U, 2U, 3U, 4U, 6U, 7U, 8U, 9U
};

const uint8_t APBPrescTable[8] = {
    0U, 0U, 0U, 0U, 1U, 2U, 3U, 4U
};

/**
 * @brief  Non-Secure system initialization
 *         Vector table is already set by Secure world via SCB_NS->VTOR
 */
void SystemInit(void)
{
    /* FPU settings: enable CP10 and CP11 full access */
#if (__FPU_PRESENT == 1) && (__FPU_USED == 1)
    SCB->CPACR |= ((3UL << 20U) | (3UL << 22U));
#endif

    /* Vector table relocation (non-secure base) */
    SCB->VTOR = FLASH_BASE_NS | VECT_TAB_NS_OFFSET;
}
