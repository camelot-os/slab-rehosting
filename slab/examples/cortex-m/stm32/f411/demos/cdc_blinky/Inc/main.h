/**
  * Main header for STM32F411 BlackPill CDC Blinky
  *
  * USB CDC ACM + USART2 debug + LED blink on PC13.
  * Uses native F4 HAL for all peripherals (RCC, GPIO, PCD, UART).
  * USB OTG FS with DWC2 controller at 0x50000000.
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"

/*
 * WeAct BlackPill V2.0 (STM32F411CEU6) LED mapping:
 *   User LED = PC13 (active low)
 */
#define LED_PIN                 GPIO_PIN_13
#define LED_GPIO_PORT           GPIOC
#define LED_GPIO_CLK_ENABLE()   __HAL_RCC_GPIOC_CLK_ENABLE()

/* USART2: PA2 (TX), PA3 (RX) - debug output */
#define USART2_TX_PIN           GPIO_PIN_2
#define USART2_RX_PIN           GPIO_PIN_3
#define USART2_GPIO_PORT        GPIOA
#define USART2_AF               GPIO_AF7_USART2

/* STM32F411 Unique Device ID at 0x1FFF7A10 (96-bit) */
#define F4_UID_BASE             0x1FFF7A10UL

void Error_Handler(void);

extern volatile uint8_t usb_ready;
extern volatile uint8_t hello_sent;

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
