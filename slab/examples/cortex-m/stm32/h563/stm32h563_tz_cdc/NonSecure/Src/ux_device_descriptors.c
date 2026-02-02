/**
 * @file    ux_device_descriptors.c
 * @brief   USB Device Descriptors for CDC ACM
 *
 * Contains the device framework (device + configuration + interface +
 * endpoint descriptors) and string descriptors for the CDC ACM device.
 */

#include "ux_device_descriptors.h"
#include <string.h>

/* USB Device Descriptor + Configuration Descriptor (Full-Speed) */
static UCHAR USBD_DeviceFrameworkFS[] =
{
    /* ---- Device Descriptor (18 bytes) ---- */
    0x12,                           /* bLength */
    0x01,                           /* bDescriptorType: Device */
    0x00, 0x02,                     /* bcdUSB: 2.00 */
    0x02,                           /* bDeviceClass: CDC */
    0x02,                           /* bDeviceSubClass: ACM */
    0x00,                           /* bDeviceProtocol */
    0x40,                           /* bMaxPacketSize0: 64 bytes */
    0x83, 0x04,                     /* idVendor: 0x0483 (ST) */
    0x40, 0x57,                     /* idProduct: 0x5740 (VCP) */
    0x00, 0x02,                     /* bcdDevice: 2.00 */
    0x01,                           /* iManufacturer: String Index 1 */
    0x02,                           /* iProduct: String Index 2 */
    0x03,                           /* iSerialNumber: String Index 3 */
    USBD_MAX_NUM_CONFIGURATION,     /* bNumConfigurations */

    /* ---- Configuration Descriptor (9 bytes) ---- */
    0x09,                           /* bLength */
    0x02,                           /* bDescriptorType: Configuration */
    0x43, 0x00,                     /* wTotalLength: 67 bytes */
    0x02,                           /* bNumInterfaces: 2 (CDC Control + Data) */
    0x01,                           /* bConfigurationValue */
    0x00,                           /* iConfiguration */
    0x80 | (USBD_SELF_POWERED << 6),/* bmAttributes: Bus powered */
    USBD_MAX_POWER,                 /* bMaxPower: 200 mA */

    /* ---- Interface Association Descriptor (8 bytes) ---- */
    0x08,                           /* bLength */
    0x0B,                           /* bDescriptorType: IAD */
    0x00,                           /* bFirstInterface: 0 */
    0x02,                           /* bInterfaceCount: 2 */
    0x02,                           /* bFunctionClass: CDC */
    0x02,                           /* bFunctionSubClass: ACM */
    0x01,                           /* bFunctionProtocol: AT Commands */
    0x00,                           /* iFunction */

    /* ---- CDC Control Interface (Interface 0) ---- */
    0x09,                           /* bLength */
    0x04,                           /* bDescriptorType: Interface */
    0x00,                           /* bInterfaceNumber: 0 */
    0x00,                           /* bAlternateSetting */
    0x01,                           /* bNumEndpoints: 1 (Interrupt IN) */
    0x02,                           /* bInterfaceClass: CDC */
    0x02,                           /* bInterfaceSubClass: ACM */
    0x01,                           /* bInterfaceProtocol: AT Commands */
    0x00,                           /* iInterface */

    /* ---- CDC Header Functional Descriptor (5 bytes) ---- */
    0x05,                           /* bLength */
    0x24,                           /* bDescriptorType: CS_INTERFACE */
    0x00,                           /* bDescriptorSubtype: Header */
    0x10, 0x01,                     /* bcdCDC: 1.10 */

    /* ---- CDC Call Management Functional Descriptor (5 bytes) ---- */
    0x05,                           /* bLength */
    0x24,                           /* bDescriptorType: CS_INTERFACE */
    0x01,                           /* bDescriptorSubtype: Call Management */
    0x00,                           /* bmCapabilities */
    0x01,                           /* bDataInterface: 1 */

    /* ---- CDC ACM Functional Descriptor (4 bytes) ---- */
    0x04,                           /* bLength */
    0x24,                           /* bDescriptorType: CS_INTERFACE */
    0x02,                           /* bDescriptorSubtype: ACM */
    0x02,                           /* bmCapabilities: Line Coding + Serial State */

    /* ---- CDC Union Functional Descriptor (5 bytes) ---- */
    0x05,                           /* bLength */
    0x24,                           /* bDescriptorType: CS_INTERFACE */
    0x06,                           /* bDescriptorSubtype: Union */
    0x00,                           /* bControlInterface: 0 */
    0x01,                           /* bSubordinateInterface0: 1 */

    /* ---- Interrupt IN Endpoint (Interface 0) ---- */
    0x07,                           /* bLength */
    0x05,                           /* bDescriptorType: Endpoint */
    CDC_ACM_EPINT_ADDR,             /* bEndpointAddress: EP2 IN */
    0x03,                           /* bmAttributes: Interrupt */
    0x08, 0x00,                     /* wMaxPacketSize: 8 */
    0x10,                           /* bInterval: 16 ms */

    /* ---- CDC Data Interface (Interface 1) ---- */
    0x09,                           /* bLength */
    0x04,                           /* bDescriptorType: Interface */
    0x01,                           /* bInterfaceNumber: 1 */
    0x00,                           /* bAlternateSetting */
    0x02,                           /* bNumEndpoints: 2 (Bulk IN + OUT) */
    0x0A,                           /* bInterfaceClass: CDC Data */
    0x00,                           /* bInterfaceSubClass */
    0x00,                           /* bInterfaceProtocol */
    0x00,                           /* iInterface */

    /* ---- Bulk OUT Endpoint ---- */
    0x07,                           /* bLength */
    0x05,                           /* bDescriptorType: Endpoint */
    CDC_ACM_EPOUT_ADDR,             /* bEndpointAddress: EP1 OUT */
    0x02,                           /* bmAttributes: Bulk */
    0x40, 0x00,                     /* wMaxPacketSize: 64 */
    0x00,                           /* bInterval */

    /* ---- Bulk IN Endpoint ---- */
    0x07,                           /* bLength */
    0x05,                           /* bDescriptorType: Endpoint */
    CDC_ACM_EPIN_ADDR,              /* bEndpointAddress: EP1 IN */
    0x02,                           /* bmAttributes: Bulk */
    0x40, 0x00,                     /* wMaxPacketSize: 64 */
    0x00,                           /* bInterval */
};

/* String Framework */
static UCHAR USBD_StringFramework[USBD_STRING_FRAMEWORK_LENGTH];

/* Language ID Framework */
static UCHAR USBD_LanguageIdFramework[] =
{
    0x09, 0x04                      /* English (US) 0x0409 */
};

/**
 * @brief  Maximum single string length (prevents buffer overflow)
 */
#define USBD_MAX_STRING_LENGTH  64U

/**
 * @brief  Helper: add a string to the USBX string framework
 *
 * ANSSI Security: Added bounds checking to prevent buffer overflow
 *
 * @param  framework: Target buffer for string framework
 * @param  offset: Current offset in buffer
 * @param  string_index: USB string index
 * @param  str: Source string (null-terminated)
 * @param  max_framework_size: Maximum size of framework buffer
 * @retval New offset after string addition, or original offset on error
 */
static ULONG USBD_String_Add(UCHAR *framework, ULONG offset,
                              UCHAR string_index, const char *str)
{
    ULONG len;
    ULONG required_size;

    /* Null pointer check */
    if ((framework == NULL) || (str == NULL))
    {
        return offset;  /* Return unchanged offset on error */
    }

    len = (ULONG)strlen(str);

    /* Bounds check: limit string length to prevent truncation issues */
    if (len > USBD_MAX_STRING_LENGTH)
    {
        len = USBD_MAX_STRING_LENGTH;
    }

    /* Calculate required buffer size: 4 bytes header + string data */
    required_size = offset + 4UL + len;

    /* Bounds check: ensure we don't overflow the framework buffer */
    if (required_size > USBD_STRING_FRAMEWORK_LENGTH)
    {
        return offset;  /* Return unchanged offset on buffer overflow */
    }

    /* Language ID: English (US) = 0x0409 */
    framework[offset++] = 0x09;
    framework[offset++] = 0x04;

    /* String index */
    framework[offset++] = string_index;

    /* String length */
    framework[offset++] = (UCHAR)len;

    /* String data */
    memcpy(&framework[offset], str, len);
    offset += len;

    return offset;
}

/**
 * @brief  Get Full-Speed device framework
 */
UCHAR *USBD_Get_Device_Framework_Speed(ULONG *length)
{
    *length = sizeof(USBD_DeviceFrameworkFS);
    return USBD_DeviceFrameworkFS;
}

/**
 * @brief  Get String framework
 */
UCHAR *USBD_Get_String_Framework(ULONG *length)
{
    ULONG offset = 0;

    offset = USBD_String_Add(USBD_StringFramework, offset, 1, USBD_MANUFACTURER_STRING);
    offset = USBD_String_Add(USBD_StringFramework, offset, 2, USBD_PRODUCT_STRING);
    offset = USBD_String_Add(USBD_StringFramework, offset, 3, USBD_SERIAL_NUMBER_STRING);

    *length = offset;
    return USBD_StringFramework;
}

/**
 * @brief  Get Language ID framework
 */
UCHAR *USBD_Get_Language_Id_Framework(ULONG *length)
{
    *length = sizeof(USBD_LanguageIdFramework);
    return USBD_LanguageIdFramework;
}
