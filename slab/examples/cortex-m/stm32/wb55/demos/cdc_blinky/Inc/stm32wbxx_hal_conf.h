/**
  * STM32WBxx HAL configuration for CDC Blinky
  *
  * Enables: RCC, GPIO, TIM, CORTEX, DMA, FLASH, PWR, PCD, EXTI
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __STM32WBxx_HAL_CONF_H
#define __STM32WBxx_HAL_CONF_H

#ifdef __cplusplus
extern "C" {
#endif

/* Module selection */
#define HAL_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_EXTI_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_PCD_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED

#define USE_HAL_PCD_REGISTER_CALLBACKS    0U

/* Oscillator Values */
#if !defined(HSE_VALUE)
  #define HSE_VALUE    (32000000UL)
#endif

#if !defined(HSE_STARTUP_TIMEOUT)
  #define HSE_STARTUP_TIMEOUT    (100U)
#endif

#if !defined(MSI_VALUE)
  #define MSI_VALUE    (4000000UL)
#endif

#if !defined(HSI_VALUE)
  #define HSI_VALUE    (16000000UL)
#endif

#if !defined(HSI48_VALUE)
  #define HSI48_VALUE  (48000000UL)
#endif

#if !defined(LSI_VALUE)
  #define LSI_VALUE    (32000U)
#endif

#if !defined(LSE_VALUE)
  #define LSE_VALUE    (32768U)
#endif

#if !defined(LSE_STARTUP_TIMEOUT)
  #define LSE_STARTUP_TIMEOUT    (5000U)
#endif

#if !defined(EXTERNAL_SAI1_CLOCK_VALUE)
  #define EXTERNAL_SAI1_CLOCK_VALUE    (48000U)
#endif

/* System Configuration */
#define VDD_VALUE                    (3300U)
#define TICK_INT_PRIORITY            (0x0FU)
#define USE_RTOS                     0U
#define PREFETCH_ENABLE              1U
#define INSTRUCTION_CACHE_ENABLE     1U
#define DATA_CACHE_ENABLE            1U

/* Module headers */
#ifdef HAL_RCC_MODULE_ENABLED
  #include "stm32wbxx_hal_rcc.h"
  #include "stm32wbxx_hal_rcc_ex.h"
#endif
#ifdef HAL_GPIO_MODULE_ENABLED
  #include "stm32wbxx_hal_gpio.h"
  #include "stm32wbxx_hal_gpio_ex.h"
#endif
#ifdef HAL_DMA_MODULE_ENABLED
  #include "stm32wbxx_hal_dma.h"
  #include "stm32wbxx_hal_dma_ex.h"
#endif
#ifdef HAL_CORTEX_MODULE_ENABLED
  #include "stm32wbxx_hal_cortex.h"
#endif
#ifdef HAL_EXTI_MODULE_ENABLED
  #include "stm32wbxx_hal_exti.h"
#endif
#ifdef HAL_FLASH_MODULE_ENABLED
  #include "stm32wbxx_hal_flash.h"
  #include "stm32wbxx_hal_flash_ex.h"
#endif
#ifdef HAL_PCD_MODULE_ENABLED
  #include "stm32wbxx_hal_pcd.h"
  #include "stm32wbxx_hal_pcd_ex.h"
#endif
#ifdef HAL_PWR_MODULE_ENABLED
  #include "stm32wbxx_hal_pwr.h"
  #include "stm32wbxx_hal_pwr_ex.h"
#endif
#ifdef HAL_TIM_MODULE_ENABLED
  #include "stm32wbxx_hal_tim.h"
  #include "stm32wbxx_hal_tim_ex.h"
#endif

/* Assert Configuration */
#define assert_param(expr) ((void)0U)

#ifdef __cplusplus
}
#endif

#endif /* __STM32WBxx_HAL_CONF_H */
