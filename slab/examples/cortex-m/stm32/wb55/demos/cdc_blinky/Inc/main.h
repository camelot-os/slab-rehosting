/**
  * Main header for STM32WB55 CDC Blinky
  *
  * Uses native WB55 HAL for all peripherals (RCC, GPIO, TIM, PCD).
  * USB CDC uses WB55 PMA-based USB FS peripheral.
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32wbxx_hal.h"

/*
 * WB55 Nucleo LED mapping:
 *   LED1 (Blue)  = PB5
 *   LED2 (Green) = PB0
 *   LED3 (Red)   = PB1
 */
#define LED1_PIN                GPIO_PIN_5
#define LED2_PIN                GPIO_PIN_0
#define LED3_PIN                GPIO_PIN_1
#define LED_GPIO_PORT           GPIOB
#define LED_GPIO_CLK_ENABLE()   __HAL_RCC_GPIOB_CLK_ENABLE()

void Error_Handler(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
