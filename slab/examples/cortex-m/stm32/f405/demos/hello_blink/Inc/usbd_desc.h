/**
  * USB Device descriptor header
  */
#ifndef __USBD_DESC_H
#define __USBD_DESC_H

#include "usbd_def.h"

/* Unique device ID register addresses (for serial number) */
#define DEVICE_ID1          (0x1FFF7A10)
#define DEVICE_ID2          (0x1FFF7A14)
#define DEVICE_ID3          (0x1FFF7A18)

#define USB_SIZ_STRING_SERIAL       0x1A

extern USBD_DescriptorsTypeDef VCP_Desc;

#endif /* __USBD_DESC_H */
