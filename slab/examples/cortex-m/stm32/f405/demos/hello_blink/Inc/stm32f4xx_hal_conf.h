/**
  * HAL configuration for STM32F405 USB CDC Demo
  */
#ifndef __STM32F4xx_HAL_CONF_H
#define __STM32F4xx_HAL_CONF_H

#ifdef __cplusplus
 extern "C" {
#endif

/* Module Selection */
#define HAL_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_PCD_MODULE_ENABLED

/* HSE/HSI Configuration - adjust HSE_VALUE for your crystal */
#if !defined (HSE_VALUE)
  #define HSE_VALUE    (8000000U)  /* 8 MHz crystal - change if different */
#endif

#if !defined (HSE_STARTUP_TIMEOUT)
  #define HSE_STARTUP_TIMEOUT    (100U)
#endif

#if !defined (HSI_VALUE)
  #define HSI_VALUE    (16000000U)
#endif

#if !defined (LSI_VALUE)
 #define LSI_VALUE  (32000U)
#endif

#if !defined (LSE_VALUE)
 #define LSE_VALUE  (32768U)
#endif

#if !defined (LSE_STARTUP_TIMEOUT)
  #define LSE_STARTUP_TIMEOUT    (5000U)
#endif

#if !defined (EXTERNAL_CLOCK_VALUE)
  #define EXTERNAL_CLOCK_VALUE    (12288000U)
#endif

/* System Configuration */
#define  VDD_VALUE                    (3300U)
#define  TICK_INT_PRIORITY            (0x0FU)
#define  USE_RTOS                     0
#define  PREFETCH_ENABLE              1
#define  INSTRUCTION_CACHE_ENABLE     1
#define  DATA_CACHE_ENABLE            1U

#define  USE_HAL_PCD_REGISTER_CALLBACKS         0U
#define  USE_HAL_TIM_REGISTER_CALLBACKS         0U

/* Include HAL modules */
#ifdef HAL_RCC_MODULE_ENABLED
  #include "stm32f4xx_hal_rcc.h"
#endif

#ifdef HAL_GPIO_MODULE_ENABLED
  #include "stm32f4xx_hal_gpio.h"
#endif

#ifdef HAL_DMA_MODULE_ENABLED
  #include "stm32f4xx_hal_dma.h"
#endif

#ifdef HAL_CORTEX_MODULE_ENABLED
  #include "stm32f4xx_hal_cortex.h"
#endif

#ifdef HAL_FLASH_MODULE_ENABLED
  #include "stm32f4xx_hal_flash.h"
#endif

#ifdef HAL_PWR_MODULE_ENABLED
 #include "stm32f4xx_hal_pwr.h"
#endif

#ifdef HAL_TIM_MODULE_ENABLED
 #include "stm32f4xx_hal_tim.h"
#endif

#ifdef HAL_PCD_MODULE_ENABLED
 #include "stm32f4xx_hal_pcd.h"
#endif

/* Assert Configuration */
#define assert_param(expr) ((void)0U)

#ifdef __cplusplus
}
#endif

#endif /* __STM32F4xx_HAL_CONF_H */
