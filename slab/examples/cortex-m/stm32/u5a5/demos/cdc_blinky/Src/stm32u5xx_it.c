/**
  * Interrupt handlers for STM32U5A5 CDC Blinky
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "stm32u5xx_it.h"

extern PCD_HandleTypeDef hpcd;
extern TIM_HandleTypeDef htim2;
extern UART_HandleTypeDef huart1;
extern UART_HandleTypeDef hlpuart1;

/* Cortex-M33 Processor Exceptions */

void NMI_Handler(void)
{
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

void SecureFault_Handler(void)
{
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

/* Peripheral Interrupt Handlers */

void OTG_HS_IRQHandler(void)
{
  HAL_PCD_IRQHandler(&hpcd);
}

void TIM2_IRQHandler(void)
{
  HAL_TIM_IRQHandler(&htim2);
}

void USART1_IRQHandler(void)
{
  HAL_UART_IRQHandler(&huart1);
}

void LPUART1_IRQHandler(void)
{
  HAL_UART_IRQHandler(&hlpuart1);
}
