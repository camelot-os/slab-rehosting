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
 * @file    app_usbx_device.c
 * @brief   USBX Device application (TF-M project)
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 */

#include "app_usbx_device.h"
#include "ux_device_descriptors.h"
#include "ux_device_cdc_acm.h"
#include "main.h"
#include "ux_dcd_stm32.h"

extern PCD_HandleTypeDef hpcd_USB_DRD_FS;

static TX_THREAD ux_device_thread;
static UCHAR ux_device_thread_stack[USB_DEVICE_THREAD_STACK_SIZE];

static TX_THREAD cdc_acm_read_thread;
static TX_THREAD cdc_acm_write_thread;
static UCHAR cdc_acm_read_thread_stack[CDC_ACM_READ_THREAD_STACK_SIZE];
static UCHAR cdc_acm_write_thread_stack[CDC_ACM_WRITE_THREAD_STACK_SIZE];

static UX_SLAVE_CLASS_CDC_ACM_PARAMETER cdc_acm_parameter;

UINT MX_USBX_Device_Init(VOID *memory_ptr)
{
    UINT status;
    UCHAR *device_framework_fs;
    ULONG device_framework_fs_length;
    UCHAR *string_framework;
    ULONG string_framework_length;
    UCHAR *language_id_framework;
    ULONG language_id_framework_length;

    status = ux_system_initialize(memory_ptr, USBX_DEVICE_MEMORY_STACK_SIZE,
                                  UX_NULL, 0);
    if (status != UX_SUCCESS)
        return status;

    device_framework_fs = USBD_Get_Device_Framework_Speed(&device_framework_fs_length);
    string_framework = USBD_Get_String_Framework(&string_framework_length);
    language_id_framework = USBD_Get_Language_Id_Framework(&language_id_framework_length);

    status = ux_device_stack_initialize(NULL, 0,
                                        device_framework_fs, device_framework_fs_length,
                                        string_framework, string_framework_length,
                                        language_id_framework, language_id_framework_length,
                                        UX_NULL);
    if (status != UX_SUCCESS)
        return status;

    cdc_acm_parameter.ux_slave_class_cdc_acm_instance_activate = USBD_CDC_ACM_Activate;
    cdc_acm_parameter.ux_slave_class_cdc_acm_instance_deactivate = USBD_CDC_ACM_Deactivate;
    cdc_acm_parameter.ux_slave_class_cdc_acm_parameter_change = USBD_CDC_ACM_ParameterChange;

    status = ux_device_stack_class_register(_ux_system_slave_class_cdc_acm_name,
                                            ux_device_class_cdc_acm_entry,
                                            1, 0, &cdc_acm_parameter);
    if (status != UX_SUCCESS)
        return status;

    /* Device management thread */
    status = tx_thread_create(&ux_device_thread, "USBX Device",
                              USBX_Device_Thread_Entry, 0,
                              ux_device_thread_stack, USB_DEVICE_THREAD_STACK_SIZE,
                              10, 10, TX_NO_TIME_SLICE, TX_AUTO_START);
    if (status != TX_SUCCESS)
        return UX_ERROR;

    /* CDC read thread (command parser) */
    status = tx_thread_create(&cdc_acm_read_thread, "CDC Read",
                              CDC_ACM_Read_Thread_Entry, 0,
                              cdc_acm_read_thread_stack, CDC_ACM_READ_THREAD_STACK_SIZE,
                              15, 15, TX_NO_TIME_SLICE, TX_AUTO_START);
    if (status != TX_SUCCESS)
        return UX_ERROR;

    /* CDC write thread */
    status = tx_thread_create(&cdc_acm_write_thread, "CDC Write",
                              CDC_ACM_Write_Thread_Entry, 0,
                              cdc_acm_write_thread_stack, CDC_ACM_WRITE_THREAD_STACK_SIZE,
                              15, 15, TX_NO_TIME_SLICE, TX_AUTO_START);
    if (status != TX_SUCCESS)
        return UX_ERROR;

    return status;
}

void USBX_Device_Thread_Entry(ULONG thread_input)
{
    (void)thread_input;

    ux_dcd_stm32_initialize((ULONG)USB_DRD_FS, (ULONG)&hpcd_USB_DRD_FS);
    HAL_PCD_Start(&hpcd_USB_DRD_FS);

    while (1)
    {
        tx_thread_sleep(TX_TIMER_TICKS_PER_SECOND);
    }
}
