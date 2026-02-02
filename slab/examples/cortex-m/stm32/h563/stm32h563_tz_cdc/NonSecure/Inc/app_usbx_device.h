/**
 * @file    app_usbx_device.h
 * @brief   USBX Device application header
 */

#ifndef APP_USBX_DEVICE_H
#define APP_USBX_DEVICE_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ux_api.h"
#include "ux_device_class_cdc_acm.h"

/* USBX memory pool size */
#define USBX_DEVICE_MEMORY_STACK_SIZE   (16 * 1024)

/* USB thread stack size */
#define USB_DEVICE_THREAD_STACK_SIZE    (1024)

/* CDC ACM thread stack sizes */
#define CDC_ACM_READ_THREAD_STACK_SIZE  (1024)
#define CDC_ACM_WRITE_THREAD_STACK_SIZE (1024)

/* Exported functions */
UINT MX_USBX_Device_Init(VOID *memory_ptr);
void USBX_Device_Thread_Entry(ULONG thread_input);

#ifdef __cplusplus
}
#endif

#endif /* APP_USBX_DEVICE_H */
