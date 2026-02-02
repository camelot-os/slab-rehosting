/**
 * @file    main.h
 * @brief   Secure world main header - STM32H563 TrustZone CDC ACM project
 */

#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h5xx_hal.h"

/* Non-secure function pointer type for jumping to NS */
#if defined(__ARM_FEATURE_CMSE) && (__ARM_FEATURE_CMSE == 3U)
typedef void (*funcptr_NS)(void) __attribute__((cmse_nonsecure_call));
#else
typedef void (*funcptr_NS)(void);
#endif

/* Exported defines */
#define USART1_TX_PIN           GPIO_PIN_9
#define USART1_TX_PORT          GPIOA
#define USART1_RX_PIN           GPIO_PIN_10
#define USART1_RX_PORT          GPIOA
#define USART1_AF               GPIO_AF7_USART1

#define LED_GREEN_PIN           GPIO_PIN_0
#define LED_GREEN_PORT          GPIOB

/* Exported functions */
void Error_Handler(void);
void SystemClock_Config(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
