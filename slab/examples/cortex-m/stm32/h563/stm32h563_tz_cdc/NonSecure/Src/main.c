/**
 * @file    main.c
 * @brief   Non-Secure world main - STM32H563 TrustZone CDC ACM
 *
 * This runs after the Secure world has configured TrustZone and
 * jumped here. Initializes USB CDC ACM and ThreadX RTOS.
 */

#include "main.h"
#include "app_usbx_device.h"
#include "secure_nsc.h"
#include "tx_api.h"

/* ThreadX byte pool for memory allocation */
static TX_BYTE_POOL tx_app_byte_pool;
static UCHAR tx_byte_pool_buffer[USBX_APP_MEM_POOL_SIZE];

/* Private function prototypes */
static void MX_GPIO_Init(void);
static void MX_USB_PCD_Init(void);

/* USB PCD handle */
PCD_HandleTypeDef hpcd_USB_DRD_FS;

/**
 * @brief  Non-Secure main entry point
 */
int main(void)
{
    /* HAL initialization (non-secure) */
    HAL_Init();

    /* Note: System clock already configured by Secure world */

    /* Initialize non-secure GPIOs */
    MX_GPIO_Init();

    /* Print via secure UART (NSC call) */
    const char *msg = "[NON-SECURE] Application started\r\n";
    SECURE_UART_Print(msg, strlen(msg));

    /* Initialize USB peripheral */
    MX_USB_PCD_Init();

    /* Enter ThreadX kernel */
    tx_kernel_enter();

    /* Should never reach here */
    while (1)
    {
    }
}

/**
 * @brief  ThreadX application define - called by tx_kernel_enter()
 */
void tx_application_define(void *first_unused_memory)
{
    UINT status;
    VOID *memory_ptr;

    (void)first_unused_memory;

    /* Create a byte memory pool for USBX */
    status = tx_byte_pool_create(&tx_app_byte_pool, "TX App Pool",
                                 tx_byte_pool_buffer, USBX_APP_MEM_POOL_SIZE);
    if (status != TX_SUCCESS)
    {
        Error_Handler();
    }

    /* Allocate memory for USBX */
    status = tx_byte_allocate(&tx_app_byte_pool, &memory_ptr,
                              USBX_DEVICE_MEMORY_STACK_SIZE, TX_NO_WAIT);
    if (status != TX_SUCCESS)
    {
        Error_Handler();
    }

    /* Initialize USBX Device stack */
    status = MX_USBX_Device_Init(memory_ptr);
    if (status != UX_SUCCESS)
    {
        Error_Handler();
    }
}

/**
 * @brief  GPIO initialization for Non-Secure world
 */
static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Enable GPIO clocks */
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();

    /* Configure LED (PB7 yellow) */
    GPIO_InitStruct.Pin = LED_YELLOW_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_YELLOW_PORT, &GPIO_InitStruct);

    /* Configure User Button (PC13) */
    GPIO_InitStruct.Pin = USER_BUTTON_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(USER_BUTTON_PORT, &GPIO_InitStruct);

    /* LED off initially */
    HAL_GPIO_WritePin(LED_YELLOW_PORT, LED_YELLOW_PIN, GPIO_PIN_RESET);
}

/**
 * @brief  USB OTG FS peripheral initialization
 */
static void MX_USB_PCD_Init(void)
{
    /* Enable USB clock */
    __HAL_RCC_USB_CLK_ENABLE();

    /* Configure USB GPIO: PA11 (DM), PA12 (DP) */
    GPIO_InitTypeDef GPIO_InitStruct = {0};
    GPIO_InitStruct.Pin = USB_DM_PIN | USB_DP_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    GPIO_InitStruct.Alternate = USB_AF;
    HAL_GPIO_Init(USB_GPIO_PORT, &GPIO_InitStruct);

    /* Configure USB PCD */
    hpcd_USB_DRD_FS.Instance = USB_DRD_FS;
    hpcd_USB_DRD_FS.Init.dev_endpoints = 8;
    hpcd_USB_DRD_FS.Init.speed = PCD_SPEED_FULL;
    hpcd_USB_DRD_FS.Init.phy_itface = PCD_PHY_EMBEDDED;
    hpcd_USB_DRD_FS.Init.Sof_enable = DISABLE;
    hpcd_USB_DRD_FS.Init.low_power_enable = DISABLE;
    hpcd_USB_DRD_FS.Init.lpm_enable = DISABLE;
    hpcd_USB_DRD_FS.Init.battery_charging_enable = DISABLE;

    if (HAL_PCD_Init(&hpcd_USB_DRD_FS) != HAL_OK)
    {
        Error_Handler();
    }

    /* Enable USB interrupt */
    HAL_NVIC_SetPriority(USB_DRD_FS_IRQn, 6, 0);
    HAL_NVIC_EnableIRQ(USB_DRD_FS_IRQn);
}

/**
 * @brief  Error handler
 */
void Error_Handler(void)
{
    const char *msg = "[NON-SECURE] Error_Handler called!\r\n";
    SECURE_UART_Print(msg, strlen(msg));

    __disable_irq();
    HAL_GPIO_WritePin(LED_YELLOW_PORT, LED_YELLOW_PIN, GPIO_PIN_SET);
    while (1)
    {
    }
}

/**
 * @brief  HAL tick handler override for ThreadX
 */
void HAL_InitTick_Callback(void)
{
    /* ThreadX manages the tick via its own timer */
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    (void)file;
    (void)line;
    Error_Handler();
}
#endif
