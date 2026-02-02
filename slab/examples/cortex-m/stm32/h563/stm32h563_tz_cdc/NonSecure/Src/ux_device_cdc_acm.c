/**
 * @file    ux_device_cdc_acm.c
 * @brief   USB CDC ACM class implementation
 *
 * Handles CDC ACM activation, data transfer, and line coding.
 * Demonstrates echo-back functionality: data received from USB host
 * is echoed back, and also printed via secure UART for debug.
 */

#include "ux_device_cdc_acm.h"
#include "main.h"
#include "secure_nsc.h"
#include "tx_api.h"

/* CDC ACM instance (set when host activates the interface) */
static UX_SLAVE_CLASS_CDC_ACM *cdc_acm_instance = UX_NULL;

/* Activation event flag */
static TX_EVENT_FLAGS_GROUP cdc_acm_event_flags;
#define CDC_ACM_ACTIVATED_FLAG  (1UL << 0)

/* Data buffers */
static UCHAR cdc_rx_buffer[CDC_ACM_DATA_BUFFER_SIZE];
static UCHAR cdc_tx_buffer[CDC_ACM_DATA_BUFFER_SIZE];

/**
 * @brief  CDC ACM class activation callback
 *         Called when USB host sets configuration and activates CDC interface
 */
VOID USBD_CDC_ACM_Activate(VOID *instance)
{
    cdc_acm_instance = (UX_SLAVE_CLASS_CDC_ACM *)instance;

    /* Signal that CDC ACM is activated */
    tx_event_flags_set(&cdc_acm_event_flags, CDC_ACM_ACTIVATED_FLAG, TX_OR);

    const char *msg = "[NON-SECURE] CDC ACM: Host connected\r\n";
    SECURE_UART_Print(msg, strlen(msg));
}

/**
 * @brief  CDC ACM class deactivation callback
 *         Called when USB host deconfigures or disconnects
 */
VOID USBD_CDC_ACM_Deactivate(VOID *instance)
{
    (void)instance;
    cdc_acm_instance = UX_NULL;

    /* Clear activation flag */
    tx_event_flags_set(&cdc_acm_event_flags, ~CDC_ACM_ACTIVATED_FLAG, TX_AND);

    const char *msg = "[NON-SECURE] CDC ACM: Host disconnected\r\n";
    SECURE_UART_Print(msg, strlen(msg));
}

/**
 * @brief  CDC ACM line coding parameter change callback
 *         Called when host sends SET_LINE_CODING request
 */
VOID USBD_CDC_ACM_ParameterChange(VOID *instance)
{
    UX_SLAVE_CLASS_CDC_ACM *cdc_acm = (UX_SLAVE_CLASS_CDC_ACM *)instance;
    UX_SLAVE_CLASS_CDC_ACM_LINE_CODING_PARAMETER line_coding;
    ULONG ux_status;

    /* Get the new line coding parameters */
    ux_status = ux_device_class_cdc_acm_ioctl(cdc_acm,
                    UX_SLAVE_CLASS_CDC_ACM_IOCTL_GET_LINE_CODING,
                    &line_coding);

    if (ux_status == UX_SUCCESS)
    {
        char debug_msg[128];
        int len = snprintf(debug_msg, sizeof(debug_msg),
                          "[NON-SECURE] CDC ACM: Line coding changed - "
                          "Baud:%lu Data:%lu Stop:%lu Parity:%lu\r\n",
                          (unsigned long)line_coding.ux_slave_class_cdc_acm_parameter_baudrate,
                          (unsigned long)line_coding.ux_slave_class_cdc_acm_parameter_data_bit,
                          (unsigned long)line_coding.ux_slave_class_cdc_acm_parameter_stop_bit,
                          (unsigned long)line_coding.ux_slave_class_cdc_acm_parameter_parity);
        SECURE_UART_Print(debug_msg, (uint32_t)len);
    }
}

/**
 * @brief  CDC ACM Read Thread
 *         Reads data from USB host and echoes it back.
 *         Also sends received data to secure UART for debug.
 */
void CDC_ACM_Read_Thread_Entry(ULONG thread_input)
{
    ULONG actual_length;
    UINT status;
    ULONG actual_flags;

    (void)thread_input;

    /* Create event flags group */
    tx_event_flags_create(&cdc_acm_event_flags, "CDC ACM Events");

    while (1)
    {
        /* Wait for CDC ACM activation */
        tx_event_flags_get(&cdc_acm_event_flags, CDC_ACM_ACTIVATED_FLAG,
                          TX_OR, &actual_flags, TX_WAIT_FOREVER);

        if (cdc_acm_instance == UX_NULL)
        {
            tx_thread_sleep(10);
            continue;
        }

        /* Read data from USB host */
        status = ux_device_class_cdc_acm_read(cdc_acm_instance,
                                               cdc_rx_buffer,
                                               CDC_ACM_DATA_BUFFER_SIZE,
                                               &actual_length);

        if (status == UX_SUCCESS && actual_length > 0)
        {
            /* Echo received data back to host */
            ux_device_class_cdc_acm_write(cdc_acm_instance,
                                           cdc_rx_buffer,
                                           actual_length,
                                           &actual_length);

            /* Also print to secure UART for debug */
            char header[] = "[USB->UART] ";
            SECURE_UART_Print(header, sizeof(header) - 1);
            SECURE_UART_Print((const char *)cdc_rx_buffer, (uint32_t)actual_length);
            SECURE_UART_Print("\r\n", 2);
        }
    }
}

/**
 * @brief  CDC ACM Write Thread
 *         Periodically sends a status message to the USB host
 *         demonstrating NS->USB data flow.
 */
void CDC_ACM_Write_Thread_Entry(ULONG thread_input)
{
    ULONG actual_length;
    uint32_t counter = 0;
    ULONG actual_flags;

    (void)thread_input;

    while (1)
    {
        /* Wait for CDC ACM activation */
        tx_event_flags_get(&cdc_acm_event_flags, CDC_ACM_ACTIVATED_FLAG,
                          TX_OR, &actual_flags, TX_WAIT_FOREVER);

        if (cdc_acm_instance == UX_NULL)
        {
            tx_thread_sleep(10);
            continue;
        }

        /* Send periodic status message every 5 seconds */
        tx_thread_sleep(5 * TX_TIMER_TICKS_PER_SECOND);

        if (cdc_acm_instance != UX_NULL)
        {
            int len = snprintf((char *)cdc_tx_buffer, CDC_ACM_DATA_BUFFER_SIZE,
                              "[STM32H563-TZ] Heartbeat #%lu | Security: 0x%08lX\r\n",
                              (unsigned long)counter++,
                              (unsigned long)SECURE_GetSecurityStatus());

            ux_device_class_cdc_acm_write(cdc_acm_instance,
                                           cdc_tx_buffer,
                                           (ULONG)len,
                                           &actual_length);
        }
    }
}
