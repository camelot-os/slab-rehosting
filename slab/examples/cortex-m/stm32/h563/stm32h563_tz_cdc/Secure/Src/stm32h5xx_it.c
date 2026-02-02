/**
 * @file    stm32h5xx_it.c
 * @brief   Secure world interrupt handlers
 */

#include "main.h"
#include "stm32h5xx_it.h"
#include <string.h>

extern UART_HandleTypeDef huart1;

void NMI_Handler(void)
{
    while (1) {}
}

void HardFault_Handler(void)
{
    while (1) {}
}

void MemManage_Handler(void)
{
    while (1) {}
}

void BusFault_Handler(void)
{
    while (1) {}
}

void UsageFault_Handler(void)
{
    while (1) {}
}

/**
 * @brief  SecureFault handler - triggered by illegal NS access to secure memory
 */
void SecureFault_Handler(void)
{
    const char *msg = "[SECURE] *** SecureFault: Illegal access detected! ***\r\n";
    HAL_UART_Transmit(&huart1, (uint8_t *)msg, (uint16_t)strlen(msg), 100);

    /* Turn on LED to indicate fault */
    HAL_GPIO_WritePin(LED_GREEN_PORT, LED_GREEN_PIN, GPIO_PIN_SET);

    while (1) {}
}

void SVC_Handler(void)
{
}

void DebugMon_Handler(void)
{
}

void PendSV_Handler(void)
{
}

void SysTick_Handler(void)
{
    HAL_IncTick();
}

/**
 * @brief  GTZC interrupt handler - illegal access via GTZC controller
 */
void GTZC_IRQHandler(void)
{
    const char *msg = "[SECURE] GTZC: Illegal peripheral/memory access!\r\n";
    HAL_UART_Transmit(&huart1, (uint8_t *)msg, (uint16_t)strlen(msg), 100);

    HAL_GPIO_WritePin(LED_GREEN_PORT, LED_GREEN_PIN, GPIO_PIN_SET);

    /* Clear GTZC flags */
    HAL_GTZC_IRQHandler();
}
