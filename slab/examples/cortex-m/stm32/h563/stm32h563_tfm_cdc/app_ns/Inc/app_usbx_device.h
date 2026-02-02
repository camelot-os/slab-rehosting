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
 * @file    app_usbx_device.h
 * @brief   USBX Device application header (TF-M project)
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#ifndef APP_USBX_DEVICE_H
#define APP_USBX_DEVICE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ux_api.h"
#include "ux_device_class_cdc_acm.h"

#define USBX_DEVICE_MEMORY_STACK_SIZE   (16 * 1024)
#define USB_DEVICE_THREAD_STACK_SIZE    (1024)
#define CDC_ACM_READ_THREAD_STACK_SIZE  (2048)  /* Larger for crypto ops */
#define CDC_ACM_WRITE_THREAD_STACK_SIZE (1024)

UINT MX_USBX_Device_Init(VOID *memory_ptr);
void USBX_Device_Thread_Entry(ULONG thread_input);

#ifdef __cplusplus
}
#endif

#endif /* APP_USBX_DEVICE_H */
