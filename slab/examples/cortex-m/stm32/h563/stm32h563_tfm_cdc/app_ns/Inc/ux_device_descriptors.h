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
 * @file    ux_device_descriptors.h
 * @brief   USB device descriptors (TF-M CDC ACM project)
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#ifndef UX_DEVICE_DESCRIPTORS_H
#define UX_DEVICE_DESCRIPTORS_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ux_api.h"

#define USBD_VID                        0x0483
#define USBD_PID                        0x5741  /* Different PID for TF-M variant */
#define USBD_DEVICE_VER                 0x0200
#define USBD_LANGID_STRING              0x0409
#define USBD_MANUFACTURER_STRING        "STMicroelectronics"
#define USBD_PRODUCT_STRING             "STM32H563 TF-M PSA CDC"
#define USBD_SERIAL_NUMBER_STRING       "TFM_CDC_001"

#define USBD_MAX_NUM_CONFIGURATION      1
#define USBD_MAX_POWER                  100
#define USBD_SELF_POWERED               0

#define CDC_ACM_EPOUT_ADDR              0x01
#define CDC_ACM_EPIN_ADDR               0x81
#define CDC_ACM_EPINT_ADDR              0x82

#define CDC_ACM_DATA_FS_MAX_PACKET_SIZE 64
#define CDC_ACM_CMD_PACKET_SIZE         8

UCHAR *USBD_Get_Device_Framework_Speed(ULONG *length);
UCHAR *USBD_Get_String_Framework(ULONG *length);
UCHAR *USBD_Get_Language_Id_Framework(ULONG *length);

#ifdef __cplusplus
}
#endif

#endif /* UX_DEVICE_DESCRIPTORS_H */
