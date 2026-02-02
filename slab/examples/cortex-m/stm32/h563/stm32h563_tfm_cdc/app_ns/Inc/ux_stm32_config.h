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
 * @file    ux_stm32_config.h
 * @brief   USBX STM32 DCD configuration for TF-M project
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * ANSSI Security: This file configures the USB device controller
 * for secure operation in the non-secure world.
 */

#ifndef UX_STM32_CONFIG_H
#define UX_STM32_CONFIG_H

/* Include STM32 HAL for PCD type definitions */
#include "stm32h5xx_hal.h"

/* USB device controller configuration */
#define UX_DCD_STM32_MAX_ED              8
#define UX_DCD_STM32_FIFO_SIZE           1024

/* ANSSI: Use FS (Full-Speed) mode only - more predictable behavior */
#define UX_DCD_STM32_USE_FS

#endif /* UX_STM32_CONFIG_H */
