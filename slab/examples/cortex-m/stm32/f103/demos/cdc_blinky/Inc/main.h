/**
  * Main header for STM32F103 BluePill CDC Blinky
  *
  * Uses native F1 HAL for all peripherals (RCC, GPIO, PCD).
  * USB CDC uses F103 PMA-based USB FS peripheral.
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f1xx_hal.h"

/*
 * BluePill LED mapping:
 *   LED (Green) = PC13 (active LOW)
 */
#define LED_PIN                 GPIO_PIN_13
#define LED_GPIO_PORT           GPIOC
#define LED_GPIO_CLK_ENABLE()   __HAL_RCC_GPIOC_CLK_ENABLE()

void Error_Handler(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
