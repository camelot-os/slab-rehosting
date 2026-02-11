/**
  * Interrupt handler prototypes for STM32U5A5 DMA + MPU Test
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
void GPDMA1_Channel0_IRQHandler(void);
void GPDMA1_Channel1_IRQHandler(void);

#ifdef __cplusplus
}
#endif

#endif /* __STM32U5xx_IT_H */
