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
 * @file    ux_device_descriptors.c
 * @brief   USB Device Descriptors for TF-M CDC ACM project
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#include "ux_device_descriptors.h"
#include <string.h>

static UCHAR USBD_DeviceFrameworkFS[] =
{
    /* Device Descriptor */
    0x12, 0x01, 0x00, 0x02,
    0x02, 0x02, 0x00, 0x40,
    0x83, 0x04,  /* idVendor: 0x0483 (ST) */
    0x41, 0x57,  /* idProduct: 0x5741 (TF-M VCP) */
    0x00, 0x02,  /* bcdDevice: 2.00 */
    0x01, 0x02, 0x03,
    0x01,  /* bNumConfigurations */

    /* Configuration Descriptor (67 bytes total) */
    0x09, 0x02, 0x43, 0x00, 0x02, 0x01, 0x00,
    0x80, 0x64,  /* bmAttributes, MaxPower=100mA */

    /* IAD */
    0x08, 0x0B, 0x00, 0x02, 0x02, 0x02, 0x01, 0x00,

    /* CDC Control Interface */
    0x09, 0x04, 0x00, 0x00, 0x01, 0x02, 0x02, 0x01, 0x00,

    /* CDC Header */
    0x05, 0x24, 0x00, 0x10, 0x01,

    /* CDC Call Management */
    0x05, 0x24, 0x01, 0x00, 0x01,

    /* CDC ACM */
    0x04, 0x24, 0x02, 0x02,

    /* CDC Union */
    0x05, 0x24, 0x06, 0x00, 0x01,

    /* Interrupt IN Endpoint */
    0x07, 0x05, 0x82, 0x03,  /* EP2 IN, Interrupt */
    0x08, 0x00, 0x10,  /* wMaxPacketSize=8, bInterval=16 */

    /* CDC Data Interface */
    0x09, 0x04, 0x01, 0x00, 0x02, 0x0A, 0x00, 0x00, 0x00,

    /* Bulk OUT */
    0x07, 0x05, 0x01, 0x02,  /* EP1 OUT, Bulk */
    0x40, 0x00, 0x00,  /* wMaxPacketSize=64 */

    /* Bulk IN */
    0x07, 0x05, 0x81, 0x02,  /* EP1 IN, Bulk */
    0x40, 0x00, 0x00,  /* wMaxPacketSize=64 */
};

#define STRING_FRAMEWORK_SIZE 256
static UCHAR USBD_StringFramework[STRING_FRAMEWORK_SIZE];

static UCHAR USBD_LanguageIdFramework[] = {
    0x09, 0x04  /* English (US): 0x0409 */
};

/**
 * @brief  Maximum single string length (ANSSI security: prevents buffer overflow)
 */
#define MAX_USB_STRING_LENGTH  64U

/**
 * @brief  Add string to framework with bounds checking
 *
 * ANSSI Security: Added bounds checking to prevent buffer overflow
 */
static ULONG add_string(UCHAR *fw, ULONG off, UCHAR idx, const char *s)
{
    ULONG len;
    ULONG required_size;

    /* Null pointer check */
    if ((fw == NULL) || (s == NULL))
    {
        return off;
    }

    len = (ULONG)strlen(s);

    /* Limit string length */
    if (len > MAX_USB_STRING_LENGTH)
    {
        len = MAX_USB_STRING_LENGTH;
    }

    /* Calculate required size and check bounds */
    required_size = off + 4UL + len;
    if (required_size > STRING_FRAMEWORK_SIZE)
    {
        return off;  /* Buffer overflow protection */
    }

    fw[off++] = 0x09;  /* LANGID low byte (English US: 0x0409) */
    fw[off++] = 0x04;  /* LANGID high byte */
    fw[off++] = idx;
    fw[off++] = (UCHAR)len;
    memcpy(&fw[off], s, len);
    return off + len;
}

UCHAR *USBD_Get_Device_Framework_Speed(ULONG *length)
{
    *length = sizeof(USBD_DeviceFrameworkFS);
    return USBD_DeviceFrameworkFS;
}

UCHAR *USBD_Get_String_Framework(ULONG *length)
{
    ULONG off = 0;
    off = add_string(USBD_StringFramework, off, 1, USBD_MANUFACTURER_STRING);
    off = add_string(USBD_StringFramework, off, 2, USBD_PRODUCT_STRING);
    off = add_string(USBD_StringFramework, off, 3, USBD_SERIAL_NUMBER_STRING);
    *length = off;
    return USBD_StringFramework;
}

UCHAR *USBD_Get_Language_Id_Framework(ULONG *length)
{
    *length = sizeof(USBD_LanguageIdFramework);
    return USBD_LanguageIdFramework;
}
