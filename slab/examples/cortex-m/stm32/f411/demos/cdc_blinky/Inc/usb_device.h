/**
  * USB Device initialization header
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __USB_DEVICE_H
#define __USB_DEVICE_H

#ifdef __cplusplus
extern "C" {
#endif

void MX_USB_Device_Init(void);
void usb_send_hello(void);

#ifdef __cplusplus
}
#endif

#endif /* __USB_DEVICE_H */
