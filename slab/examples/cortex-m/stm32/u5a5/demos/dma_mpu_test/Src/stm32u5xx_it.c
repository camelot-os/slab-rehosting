/**
  * Interrupt handlers for STM32U5A5 DMA + MPU Test
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "stm32u5xx_it.h"

extern DMA_HandleTypeDef hdma_ch0;

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

/* GPDMA1 Channel 0 interrupt handler */
void GPDMA1_Channel0_IRQHandler(void)
{
  HAL_DMA_IRQHandler(&hdma_ch0);
}
