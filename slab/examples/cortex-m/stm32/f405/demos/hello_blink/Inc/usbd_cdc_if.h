/**
  * USB CDC interface header
  */
#ifndef __USBD_CDC_IF_H
#define __USBD_CDC_IF_H

#include "usbd_cdc.h"

/* CDC Polling interval in ms */
#define CDC_POLLING_INTERVAL             5

extern USBD_CDC_ItfTypeDef USBD_CDC_fops;

/* Public functions */
uint8_t CDC_Transmit(uint8_t* Buf, uint16_t Len);

#endif /* __USBD_CDC_IF_H */
