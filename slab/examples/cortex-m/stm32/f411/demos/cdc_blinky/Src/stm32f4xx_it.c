/**
  * Interrupt handlers for STM32F411 CDC Blinky
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "stm32f4xx_it.h"

extern PCD_HandleTypeDef hpcd;
extern UART_HandleTypeDef huart2;

/* Cortex-M4 Processor Exceptions */

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

void OTG_FS_IRQHandler(void)
{
  HAL_PCD_IRQHandler(&hpcd);
}

void USART2_IRQHandler(void)
{
  HAL_UART_IRQHandler(&huart2);
}
