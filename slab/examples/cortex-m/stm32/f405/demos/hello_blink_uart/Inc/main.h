/**
  * STM32F405 UART Demo with LED Blink
  * Sends "helloworld\r\n" then echoes UART data, blinks PA13
  *
  * For MCUemu proxy benchmarking (no USB OTG dependencies)
  */
#ifndef __MAIN_H
#define __MAIN_H

#include "stm32f4xx_hal.h"

/* LED on PA13 */
#define LED_PIN                 GPIO_PIN_13
#define LED_GPIO_PORT           GPIOA
#define LED_GPIO_CLK_ENABLE()   __HAL_RCC_GPIOA_CLK_ENABLE()

/* USART2: PA2 (TX), PA3 (RX) */
#define USART_TX_PIN            GPIO_PIN_2
#define USART_RX_PIN            GPIO_PIN_3
#define USART_GPIO_PORT         GPIOA
#define USART_GPIO_CLK_ENABLE() __HAL_RCC_GPIOA_CLK_ENABLE()

/* MCUemu test interface */
#define MCUEMU_TEST_BASE        0x4000F000
#define MCUEMU_TEST_STATUS      (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x00))
#define MCUEMU_TEST_DATA        (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x04))
#define TEST_STATUS_RUNNING     0x01
#define TEST_STATUS_PASS        0x02
#define TEST_STATUS_FAIL        0x03

void Error_Handler(void);

#endif /* __MAIN_H */
