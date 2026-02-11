/**
  * Main header for STM32U5A5 DMA + MPU Test
  *
  * Tests GPDMA1 memory-to-memory transfer and PMSAv8 MPU configuration.
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32u5xx_hal.h"

/* USART1: PA9 (TX), PA10 (RX) */
#define USART1_TX_PIN           GPIO_PIN_9
#define USART1_RX_PIN           GPIO_PIN_10
#define USART1_GPIO_PORT        GPIOA
#define USART1_AF               GPIO_AF7_USART1

/* DMA test buffer size (words) */
#define DMA_TEST_SIZE_WORDS     64
#define DMA_TEST_SIZE_BYTES     (DMA_TEST_SIZE_WORDS * 4)

/* DMA small buffer for channel 1 test */
#define DMA_SMALL_SIZE_WORDS    16
#define DMA_SMALL_SIZE_BYTES    (DMA_SMALL_SIZE_WORDS * 4)

void Error_Handler(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
