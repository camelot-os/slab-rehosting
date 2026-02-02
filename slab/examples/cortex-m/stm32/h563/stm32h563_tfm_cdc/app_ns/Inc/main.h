/*
 * Copyright 2024-2026 Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * @file    main.h
 * @brief   Non-Secure main header - STM32H563 TF-M CDC ACM
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h5xx_hal.h"

/* USB pins */
#define USB_DM_PIN              GPIO_PIN_11
#define USB_DP_PIN              GPIO_PIN_12
#define USB_GPIO_PORT           GPIOA
#define USB_AF                  GPIO_AF10_USB

/* LED (PB7 yellow on NUCLEO-H563ZI) */
#define LED_YELLOW_PIN          GPIO_PIN_7
#define LED_YELLOW_PORT         GPIOB

/* ThreadX / USBX memory */
#define USBX_APP_MEM_POOL_SIZE  (48 * 1024)  /* Larger for crypto buffers */

void Error_Handler(void);

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
