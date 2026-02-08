/**
  * USB Device descriptor header for STM32WB55
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#ifndef __USBD_DESC_H
#define __USBD_DESC_H

#include "usbd_def.h"

/* Unique device ID register addresses (STM32WB55) */
#define DEVICE_ID1          (0x1FFF7590UL)
#define DEVICE_ID2          (0x1FFF7594UL)
#define DEVICE_ID3          (0x1FFF7598UL)

#define USB_SIZ_STRING_SERIAL       0x1A

extern USBD_DescriptorsTypeDef CDC_Desc;

#endif /* __USBD_DESC_H */
