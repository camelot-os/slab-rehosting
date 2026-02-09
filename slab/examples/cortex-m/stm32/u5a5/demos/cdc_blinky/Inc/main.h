/**
  * Main header for STM32U5A5 CDC Blinky
  *
  * USB CDC ACM + USART1 + LPUART1 + Flash demo + LED blink.
  * Uses native U5 HAL for all peripherals (RCC, GPIO, TIM, PCD, UART, FLASH).
  * USB OTG HS with DWC2 controller at 0x42040000.
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32u5xx_hal.h"

/*
 * Nucleo-U5A5ZJT6Q LED mapping:
 *   LD1 (Green) = PC7
 *   LD2 (Blue)  = PB7
 */
#define LED1_PIN                GPIO_PIN_7
#define LED1_GPIO_PORT          GPIOC
#define LED1_GPIO_CLK_ENABLE()  __HAL_RCC_GPIOC_CLK_ENABLE()

#define LED2_PIN                GPIO_PIN_7
#define LED2_GPIO_PORT          GPIOB
#define LED2_GPIO_CLK_ENABLE()  __HAL_RCC_GPIOB_CLK_ENABLE()

/* USART1: PA9 (TX), PA10 (RX) */
#define USART1_TX_PIN           GPIO_PIN_9
#define USART1_RX_PIN           GPIO_PIN_10
#define USART1_GPIO_PORT        GPIOA
#define USART1_AF               GPIO_AF7_USART1

/* LPUART1: PA2 (TX), PA3 (RX) */
#define LPUART1_TX_PIN          GPIO_PIN_2
#define LPUART1_RX_PIN          GPIO_PIN_3
#define LPUART1_GPIO_PORT       GPIOA
#define LPUART1_AF              GPIO_AF8_LPUART1

/* STM32U5A5 Unique Device ID at 0x0BFA0700 (96-bit) */
#define U5_UID_BASE             0x0BFA0700UL

/* Flash demo page address (near end of 4MB flash, page at 0x083FE000) */
#define FLASH_DEMO_ADDR         0x083FE000UL
#define FLASH_DEMO_PAGE         511U
#define FLASH_DEMO_BANK         FLASH_BANK_2

void Error_Handler(void);

extern volatile uint8_t usb_ready;
extern volatile uint8_t hello_sent;

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
