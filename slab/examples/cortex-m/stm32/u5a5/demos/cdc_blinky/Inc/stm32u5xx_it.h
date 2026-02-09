/**
  * Interrupt handlers header for STM32U5A5 CDC Blinky
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __STM32U5xx_IT_H
#define __STM32U5xx_IT_H

#ifdef __cplusplus
extern "C" {
#endif

void NMI_Handler(void);
void HardFault_Handler(void);
void MemManage_Handler(void);
void BusFault_Handler(void);
void UsageFault_Handler(void);
void SecureFault_Handler(void);
void SVC_Handler(void);
void DebugMon_Handler(void);
void PendSV_Handler(void);
void SysTick_Handler(void);
void TIM2_IRQHandler(void);
void OTG_HS_IRQHandler(void);
void USART1_IRQHandler(void);
void LPUART1_IRQHandler(void);

#ifdef __cplusplus
}
#endif

#endif /* __STM32U5xx_IT_H */
