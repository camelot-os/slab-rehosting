/**
 * @file    stm32h5xx_it.c
 * @brief   Non-Secure world interrupt handlers
 *
 * Note: ThreadX provides SysTick_Handler, HardFault_Handler,
 *       UsageFault_Handler, and PendSV_Handler
 */

#include "main.h"
#include "stm32h5xx_it.h"

extern PCD_HandleTypeDef hpcd_USB_DRD_FS;

void NMI_Handler(void)
{
    while (1) {}
}

/* HardFault_Handler provided by ThreadX */

void MemManage_Handler(void)
{
    while (1) {}
}

void BusFault_Handler(void)
{
    while (1) {}
}

/* UsageFault_Handler provided by ThreadX */

void SVC_Handler(void)
{
}

void DebugMon_Handler(void)
{
}

/* PendSV_Handler provided by ThreadX */

/* SysTick_Handler provided by ThreadX */

/**
 * @brief  USB DRD FS interrupt handler
 */
void USB_DRD_FS_IRQHandler(void)
{
    HAL_PCD_IRQHandler(&hpcd_USB_DRD_FS);
}
