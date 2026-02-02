/**
  * STM32F405 USB CDC Demo with LED Blink
  * Sends "helloworld\n\r" then echoes USB data, blinks PA13
  */
#ifndef __MAIN_H
#define __MAIN_H

#include "stm32f4xx_hal.h"
#include "usbd_def.h"
#include "usbd_core.h"
#include "usbd_desc.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"

/* LED on PA13 */
#define LED_PIN                 GPIO_PIN_13
#define LED_GPIO_PORT           GPIOA
#define LED_GPIO_CLK_ENABLE()   __HAL_RCC_GPIOA_CLK_ENABLE()

void Error_Handler(void);

#endif /* __MAIN_H */
