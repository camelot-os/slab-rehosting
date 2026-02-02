/**
 * @file    ux_user.h
 * @brief   USBX User Configuration
 */

#ifndef UX_USER_H
#define UX_USER_H

/* Device mode only */
#define UX_DEVICE_ONLY

/* Disable host mode */
#define UX_HOST_SIDE_ONLY

/* Maximum number of devices */
#define UX_MAX_DEVICES                      1

/* Maximum number of classes */
#define UX_MAX_SLAVE_CLASS_DRIVER           1

/* Maximum number of endpoints */
#define UX_MAX_DEVICE_ENDPOINTS             4

/* Maximum number of interfaces */
#define UX_MAX_DEVICE_INTERFACES            2

/* Thread stack size */
#define UX_THREAD_STACK_SIZE                1024

/* CDC ACM configuration */
#define UX_SLAVE_REQUEST_DATA_MAX_LENGTH    256

/* Disable unused features */
#define UX_DEVICE_CLASS_CDC_ACM_TRANSMISSION_DISABLE

#endif /* UX_USER_H */
