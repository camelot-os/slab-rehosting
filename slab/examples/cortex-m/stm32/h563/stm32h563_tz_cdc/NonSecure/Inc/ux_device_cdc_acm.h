/**
 * @file    ux_device_cdc_acm.h
 * @brief   USB CDC ACM class handler header
 */

#ifndef UX_DEVICE_CDC_ACM_H
#define UX_DEVICE_CDC_ACM_H

#ifdef __cplusplus
extern "C" {
#endif

#include "ux_api.h"
#include "ux_device_class_cdc_acm.h"

/* CDC ACM buffer sizes */
#define CDC_ACM_DATA_BUFFER_SIZE    512

/* CDC ACM thread entry points */
void CDC_ACM_Read_Thread_Entry(ULONG thread_input);
void CDC_ACM_Write_Thread_Entry(ULONG thread_input);

/* CDC ACM class callbacks */
VOID USBD_CDC_ACM_Activate(VOID *cdc_acm_instance);
VOID USBD_CDC_ACM_Deactivate(VOID *cdc_acm_instance);
VOID USBD_CDC_ACM_ParameterChange(VOID *cdc_acm_instance);

#ifdef __cplusplus
}
#endif

#endif /* UX_DEVICE_CDC_ACM_H */
