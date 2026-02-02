/**
  * Interrupt handlers for STM32F405 USB CDC Demo
  */
#include "main.h"
#include "stm32f4xx_it.h"

extern PCD_HandleTypeDef hpcd;
extern TIM_HandleTypeDef htim2;

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

/**
  * @brief USB OTG FS interrupt handler
  */
void OTG_FS_IRQHandler(void)
{
  HAL_PCD_IRQHandler(&hpcd);
}

/**
  * @brief TIM2 interrupt handler
  */
void TIM2_IRQHandler(void)
{
  HAL_TIM_IRQHandler(&htim2);
}
