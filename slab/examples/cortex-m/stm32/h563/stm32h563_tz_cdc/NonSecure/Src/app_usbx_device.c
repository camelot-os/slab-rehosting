/**
 * @file    app_usbx_device.c
 * @brief   USBX Device application - initializes USB stack and CDC ACM class
 */

#include "app_usbx_device.h"
#include "ux_device_descriptors.h"
#include "ux_device_cdc_acm.h"
#include "main.h"
#include "secure_nsc.h"
#include "ux_dcd_stm32.h"

/* External USB PCD handle */
extern PCD_HandleTypeDef hpcd_USB_DRD_FS;

/* USBX device thread */
static TX_THREAD ux_device_thread;
static UCHAR ux_device_thread_stack[USB_DEVICE_THREAD_STACK_SIZE];

/* CDC ACM threads */
static TX_THREAD cdc_acm_read_thread;
static TX_THREAD cdc_acm_write_thread;
static UCHAR cdc_acm_read_thread_stack[CDC_ACM_READ_THREAD_STACK_SIZE];
static UCHAR cdc_acm_write_thread_stack[CDC_ACM_WRITE_THREAD_STACK_SIZE];

/* CDC ACM class parameters */
static UX_SLAVE_CLASS_CDC_ACM_PARAMETER cdc_acm_parameter;

/**
 * @brief  Initialize USBX Device stack
 * @param  memory_ptr: pointer to allocated memory for USBX
 * @retval UX_SUCCESS on success
 */
UINT MX_USBX_Device_Init(VOID *memory_ptr)
{
    UINT status;
    UCHAR *device_framework_fs;
    ULONG device_framework_fs_length;
    UCHAR *string_framework;
    ULONG string_framework_length;
    UCHAR *language_id_framework;
    ULONG language_id_framework_length;

    /* Initialize USBX memory */
    status = ux_system_initialize(memory_ptr, USBX_DEVICE_MEMORY_STACK_SIZE,
                                  UX_NULL, 0);
    if (status != UX_SUCCESS)
    {
        return status;
    }

    /* Get device framework */
    device_framework_fs = USBD_Get_Device_Framework_Speed(&device_framework_fs_length);
    string_framework = USBD_Get_String_Framework(&string_framework_length);
    language_id_framework = USBD_Get_Language_Id_Framework(&language_id_framework_length);

    /* Initialize USBX Device stack (Full-Speed only) */
    status = ux_device_stack_initialize(NULL, 0,
                                        device_framework_fs, device_framework_fs_length,
                                        string_framework, string_framework_length,
                                        language_id_framework, language_id_framework_length,
                                        UX_NULL);
    if (status != UX_SUCCESS)
    {
        return status;
    }

    /* Configure CDC ACM class parameters */
    cdc_acm_parameter.ux_slave_class_cdc_acm_instance_activate = USBD_CDC_ACM_Activate;
    cdc_acm_parameter.ux_slave_class_cdc_acm_instance_deactivate = USBD_CDC_ACM_Deactivate;
    cdc_acm_parameter.ux_slave_class_cdc_acm_parameter_change = USBD_CDC_ACM_ParameterChange;

    /* Register CDC ACM class */
    status = ux_device_stack_class_register(_ux_system_slave_class_cdc_acm_name,
                                            ux_device_class_cdc_acm_entry,
                                            1, 0, &cdc_acm_parameter);
    if (status != UX_SUCCESS)
    {
        return status;
    }

    /* Create USB device management thread */
    status = tx_thread_create(&ux_device_thread, "USBX Device Thread",
                              USBX_Device_Thread_Entry, 0,
                              ux_device_thread_stack, USB_DEVICE_THREAD_STACK_SIZE,
                              10, 10, TX_NO_TIME_SLICE, TX_AUTO_START);
    if (status != TX_SUCCESS)
    {
        return UX_ERROR;
    }

    /* Create CDC ACM read thread */
    status = tx_thread_create(&cdc_acm_read_thread, "CDC ACM Read Thread",
                              CDC_ACM_Read_Thread_Entry, 0,
                              cdc_acm_read_thread_stack, CDC_ACM_READ_THREAD_STACK_SIZE,
                              15, 15, TX_NO_TIME_SLICE, TX_AUTO_START);
    if (status != TX_SUCCESS)
    {
        return UX_ERROR;
    }

    /* Create CDC ACM write thread */
    status = tx_thread_create(&cdc_acm_write_thread, "CDC ACM Write Thread",
                              CDC_ACM_Write_Thread_Entry, 0,
                              cdc_acm_write_thread_stack, CDC_ACM_WRITE_THREAD_STACK_SIZE,
                              15, 15, TX_NO_TIME_SLICE, TX_AUTO_START);
    if (status != TX_SUCCESS)
    {
        return UX_ERROR;
    }

    return status;
}

/**
 * @brief  USBX Device thread - connects USB controller to USBX stack
 */
void USBX_Device_Thread_Entry(ULONG thread_input)
{
    (void)thread_input;

    /* Register the STM32 USB DCD driver with USBX */
    ux_dcd_stm32_initialize((ULONG)USB_DRD_FS, (ULONG)&hpcd_USB_DRD_FS);

    /* Start USB device */
    HAL_PCD_Start(&hpcd_USB_DRD_FS);

    const char *msg = "[NON-SECURE] USB CDC ACM device started\r\n";
    SECURE_UART_Print(msg, strlen(msg));

    /* Thread stays alive - USB events handled in interrupts */
    while (1)
    {
        tx_thread_sleep(TX_TIMER_TICKS_PER_SECOND);

        /* Toggle LED to show NS world is alive */
        HAL_GPIO_TogglePin(LED_YELLOW_PORT, LED_YELLOW_PIN);
    }
}
