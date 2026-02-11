/**
  * USB Device initialization for STM32F411
  *
  * - PLL Q output provides 48 MHz USB clock (configured in SystemClock_Config)
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
  * Note: On STM32F411, the USB 48 MHz clock comes from PLLQ output,
  * which was already configured in SystemClock_Config() (PLLQ = 4,
  * giving 192 MHz / 4 = 48 MHz). No separate clock configuration needed.
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
