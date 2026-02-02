/**
 * @file    stm32h5xx_hal_conf.h
 * @brief   HAL configuration for NS world (TF-M project)
 */

#ifndef STM32H5XX_HAL_CONF_H
#define STM32H5XX_HAL_CONF_H

#ifdef __cplusplus
extern "C" {
#endif

#define HAL_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_ICACHE_MODULE_ENABLED
#define HAL_PCD_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED

#if !defined(HSE_VALUE)
#define HSE_VALUE               8000000UL
#endif
#if !defined(HSE_STARTUP_TIMEOUT)
#define HSE_STARTUP_TIMEOUT     100UL
#endif
#if !defined(HSI_VALUE)
#define HSI_VALUE               64000000UL
#endif
#if !defined(HSI48_VALUE)
#define HSI48_VALUE             48000000UL
#endif
#if !defined(LSE_VALUE)
#define LSE_VALUE               32768UL
#endif
#if !defined(LSE_STARTUP_TIMEOUT)
#define LSE_STARTUP_TIMEOUT     5000UL
#endif
#if !defined(LSI_VALUE)
#define LSI_VALUE               32000UL
#endif
#if !defined(CSI_VALUE)
#define CSI_VALUE               4000000UL
#endif

#define EXTERNAL_CLOCK_VALUE    12288000UL
#define VDD_VALUE               3300UL
#define TICK_INT_PRIORITY       0x0FUL
#define USE_RTOS                0U
#define PREFETCH_ENABLE         1U
#define LSI_STARTUP_TIME        130UL

#ifdef HAL_RCC_MODULE_ENABLED
#include "stm32h5xx_hal_rcc.h"
#endif
#ifdef HAL_GPIO_MODULE_ENABLED
#include "stm32h5xx_hal_gpio.h"
#endif
#ifdef HAL_DMA_MODULE_ENABLED
#include "stm32h5xx_hal_dma.h"
#endif
#ifdef HAL_CORTEX_MODULE_ENABLED
#include "stm32h5xx_hal_cortex.h"
#endif
#ifdef HAL_FLASH_MODULE_ENABLED
#include "stm32h5xx_hal_flash.h"
#endif
#ifdef HAL_ICACHE_MODULE_ENABLED
#include "stm32h5xx_hal_icache.h"
#endif
#ifdef HAL_PCD_MODULE_ENABLED
#include "stm32h5xx_hal_pcd.h"
#endif
#ifdef HAL_PWR_MODULE_ENABLED
#include "stm32h5xx_hal_pwr.h"
#endif

#ifdef USE_FULL_ASSERT
#define assert_param(expr) ((expr) ? (void)0U : assert_failed((uint8_t *)__FILE__, __LINE__))
void assert_failed(uint8_t *file, uint32_t line);
#else
#define assert_param(expr) ((void)0U)
#endif

#ifdef __cplusplus
}
#endif

#endif /* STM32H5XX_HAL_CONF_H */
