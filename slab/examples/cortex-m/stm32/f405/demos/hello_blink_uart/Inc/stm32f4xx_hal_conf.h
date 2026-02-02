/**
  * STM32F4xx HAL configuration
  */
#ifndef __STM32F4xx_HAL_CONF_H
#define __STM32F4xx_HAL_CONF_H

/* Oscillator values */
#define HSE_VALUE    ((uint32_t)8000000U)
#define HSE_STARTUP_TIMEOUT    ((uint32_t)100U)
#define HSI_VALUE    ((uint32_t)16000000U)
#define LSI_VALUE    ((uint32_t)32000U)
#define LSE_VALUE    ((uint32_t)32768U)
#define LSE_STARTUP_TIMEOUT    ((uint32_t)5000U)
#define EXTERNAL_CLOCK_VALUE    ((uint32_t)12288000U)

/* System tick frequency */
#define VDD_VALUE                    ((uint32_t)3300U)
#define TICK_INT_PRIORITY            ((uint32_t)0U)
#define USE_RTOS                     0U
#define PREFETCH_ENABLE              1U
#define INSTRUCTION_CACHE_ENABLE     1U
#define DATA_CACHE_ENABLE            1U

/* Module selection */
#define HAL_MODULE_ENABLED
#define HAL_GPIO_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_TIM_MODULE_ENABLED
#define HAL_UART_MODULE_ENABLED
#define HAL_DMA_MODULE_ENABLED

/* Includes */
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
#ifdef HAL_UART_MODULE_ENABLED
  #include "stm32f4xx_hal_uart.h"
#endif

/* Assert configuration */
#define assert_param(expr) ((void)0U)

#endif /* __STM32F4xx_HAL_CONF_H */
