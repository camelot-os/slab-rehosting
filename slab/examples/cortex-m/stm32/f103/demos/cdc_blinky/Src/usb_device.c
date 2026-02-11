/**
  * USB Device initialization for STM32F103
  *
  * - USB clock is derived from PLL: 72 MHz / 1.5 = 48 MHz
  *   (configured via RCC_CFGR USBPRE bit, handled by HAL RCC)
  * - Initializes USB Device core + CDC class
  * - Provides usb_send_hello() for initial "helloworld" message
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "usbd_core.h"
#include "usbd_desc.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"
#include "usb_device.h"

USBD_HandleTypeDef USBD_Device;

/**
  * Initialize USB Device stack (CDC class)
  *
  * On F103 the USB 48 MHz clock comes from PLL/1.5 (72/1.5=48).
  * No separate HSI48 or CRS needed -- much simpler than WB55.
  */
void MX_USB_Device_Init(void)
{
  USBD_Init(&USBD_Device, &CDC_Desc, DEVICE_FS);
  USBD_RegisterClass(&USBD_Device, &USBD_CDC);
  USBD_CDC_RegisterInterface(&USBD_Device, &USBD_Interface_fops_FS);
  USBD_Start(&USBD_Device);
}

/**
  * Send "helloworld\n\r" over USB CDC
  */
void usb_send_hello(void)
{
  static uint8_t msg[] = "helloworld\n\r";
  CDC_Transmit_FS(msg, sizeof(msg) - 1);
}
