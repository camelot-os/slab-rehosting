/**
 * @file    ux_device_descriptors.h
 * @brief   USB device descriptor definitions
 */

#ifndef UX_DEVICE_DESCRIPTORS_H
#define UX_DEVICE_DESCRIPTORS_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ux_api.h"

/* USB Device descriptor parameters */
#define USBD_VID                        0x0483  /* STMicroelectronics */
#define USBD_PID                        0x5740  /* Virtual COM Port */
#define USBD_DEVICE_VER                 0x0200  /* 2.00 */
#define USBD_LANGID_STRING              0x0409  /* English (US) */
#define USBD_MANUFACTURER_STRING        "STMicroelectronics"
#define USBD_PRODUCT_STRING             "STM32H563 TZ CDC ACM"
#define USBD_SERIAL_NUMBER_STRING       "TZ_CDC_001"

/* USB Configuration */
#define USBD_MAX_NUM_CONFIGURATION      1
#define USBD_MAX_POWER                  100  /* 200 mA (unit = 2mA) */
#define USBD_SELF_POWERED               0

/* CDC ACM Endpoints */
#define CDC_ACM_EPOUT_ADDR              0x01
#define CDC_ACM_EPIN_ADDR               0x81
#define CDC_ACM_EPINT_ADDR              0x82

/* Endpoint sizes */
#define CDC_ACM_DATA_FS_MAX_PACKET_SIZE 64
#define CDC_ACM_CMD_PACKET_SIZE         8

/* USB Device framework sizes */
#define USBD_DEVICE_FRAMEWORK_FS_LENGTH     (18 + 9 + 8 + 9 + 5 + 5 + 4 + 5 + 7 + 9 + 7 + 7)
#define USBD_STRING_FRAMEWORK_LENGTH        256
#define USBD_LANGUAGE_ID_FRAMEWORK_LENGTH   2

/* Functions */
UCHAR *USBD_Get_Device_Framework_Speed(ULONG *length);
UCHAR *USBD_Get_String_Framework(ULONG *length);
UCHAR *USBD_Get_Language_Id_Framework(ULONG *length);

#ifdef __cplusplus
}
#endif

#endif /* UX_DEVICE_DESCRIPTORS_H */
