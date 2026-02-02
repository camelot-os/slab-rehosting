/**
 * @file    ux_stm32_config.h
 * @brief   USBX STM32 DCD Configuration
 */

#ifndef UX_STM32_CONFIG_H
#define UX_STM32_CONFIG_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h5xx_hal.h"

/* USB Device Controller Configuration */
#define UX_DCD_STM32_MAX_ED                 8
#define UX_DCD_STM32_ENDPOINT_BUFFER_SIZE   512

/* Define USB peripheral base address */
#define USB_BASE_ADDR                       USB_DRD_FS_BASE

#ifdef __cplusplus
}
#endif

#endif /* UX_STM32_CONFIG_H */
