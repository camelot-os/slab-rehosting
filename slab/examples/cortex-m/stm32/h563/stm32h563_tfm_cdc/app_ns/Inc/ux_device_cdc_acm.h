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
 * @file    ux_device_cdc_acm.h
 * @brief   USB CDC ACM with PSA command parser
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#ifndef UX_DEVICE_CDC_ACM_H
#define UX_DEVICE_CDC_ACM_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ux_api.h"
#include "ux_device_class_cdc_acm.h"

#define CDC_ACM_CMD_BUFFER_SIZE     512
#define CDC_ACM_RESP_BUFFER_SIZE    1024

void CDC_ACM_Read_Thread_Entry(ULONG thread_input);
void CDC_ACM_Write_Thread_Entry(ULONG thread_input);

VOID USBD_CDC_ACM_Activate(VOID *cdc_acm_instance);
VOID USBD_CDC_ACM_Deactivate(VOID *cdc_acm_instance);
VOID USBD_CDC_ACM_ParameterChange(VOID *cdc_acm_instance);

#ifdef __cplusplus
}
#endif

#endif /* UX_DEVICE_CDC_ACM_H */
