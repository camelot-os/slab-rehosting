/**
 * @file    main.h
 * @brief   Non-Secure world main header - STM32H563 TrustZone CDC ACM
 */

#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h5xx_hal.h"

/* USB pins (PA11=DM, PA12=DP on NUCLEO-H563ZI) */
#define USB_DM_PIN              GPIO_PIN_11
#define USB_DP_PIN              GPIO_PIN_12
#define USB_GPIO_PORT           GPIOA
#define USB_AF                  GPIO_AF10_USB

/* User button (PC13 on NUCLEO-H563ZI) */
#define USER_BUTTON_PIN         GPIO_PIN_13
#define USER_BUTTON_PORT        GPIOC

/* LED (PB7 yellow on NUCLEO-H563ZI for NS) */
#define LED_YELLOW_PIN          GPIO_PIN_7
#define LED_YELLOW_PORT         GPIOB

/* ThreadX memory pool sizes */
#define USBX_APP_MEM_POOL_SIZE  (32 * 1024)
#define TX_APP_STACK_SIZE       (1024)

/* Exported functions */
void Error_Handler(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
