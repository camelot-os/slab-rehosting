/*
 * Copyright 2024-2026 Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * @file    main.c
 * @brief   Non-Secure main - STM32H563 TF-M CDC ACM
 * @author  Mathieu Renard <mathieu.renard@twistedwires.io>
 *
 * ============================================================================
 *                      TF-M NON-SECURE APPLICATION
 * ============================================================================
 *
 * This file is the entry point for the Non-Secure (NS) world application.
 * Before this code runs, the following has already happened:
 *
 * 1. MCUboot (BL2) verified and launched TF-M secure firmware
 * 2. TF-M initialized:
 *    - Security Attribution Unit (SAU) - defines S/NS regions
 *    - GTZC (Global TrustZone Controller) - protects peripherals
 *    - Secure services (Crypto, Storage, Attestation)
 * 3. TF-M jumped to this NS code via the NS Reset Handler
 *
 * ARCHITECTURE:
 *
 *  +------------------------------------------+
 *  |        NON-SECURE WORLD (this code)      |
 *  |  +------------------------------------+  |
 *  |  |  ThreadX RTOS + USBX USB Stack    |  |
 *  |  +------------------------------------+  |
 *  |  |  PSA Crypto Demo Application       |  |
 *  |  +------------------------------------+  |
 *  |               |                          |
 *  |          PSA API calls                   |
 *  |               v                          |
 *  +------------------------------------------+
 *  |        SECURE WORLD (TF-M)              |
 *  |  +------------------------------------+  |
 *  |  |  Crypto | Storage | Attestation   |  |
 *  |  +------------------------------------+  |
 *  +------------------------------------------+
 *
 * PSA API SECURITY MODEL:
 * - NS code cannot directly access secure memory or peripherals
 * - All crypto operations are delegated to TF-M via PSA APIs
 * - Keys never leave the secure world - only handles are used in NS
 *
 * @see https://tf-m-user-guide.trustedfirmware.org/
 * @see https://arm-software.github.io/psa-api/
 */

#include "main.h"
#include "app_usbx_device.h"
#include "psa_crypto_app.h"
#include "tx_api.h"
#include <string.h>
#include <stdio.h>

/* ============================================================================
 *                         THREADX CONFIGURATION
 * ============================================================================
 * ThreadX is an RTOS that manages threads, memory, and timers.
 * For TrustZone, we use TX_SINGLE_MODE_NON_SECURE to run entirely in NS.
 */

/* ThreadX byte pool for dynamic memory allocation */
static TX_BYTE_POOL tx_app_byte_pool;
static UCHAR tx_byte_pool_buffer[USBX_APP_MEM_POOL_SIZE];

/* USB PCD (Peripheral Controller Driver) handle
 * This is required by USBX to interface with the STM32 USB hardware */
PCD_HandleTypeDef hpcd_USB_DRD_FS;

/* Private function prototypes */
static void MX_GPIO_Init(void);
static void MX_USB_PCD_Init(void);

/* ============================================================================
 *                            MAIN ENTRY POINT
 * ============================================================================
 */

/**
 * @brief  Non-Secure main entry point
 *
 * BOOT SEQUENCE:
 * 1. MCUboot verifies TF-M image signature
 * 2. TF-M secure firmware initializes TrustZone:
 *    - SAU regions (what memory is secure vs non-secure)
 *    - GTZC MPCBB (SRAM block security)
 *    - GTZC TZSC (peripheral security)
 * 3. TF-M initializes secure services (Crypto, Storage, Attestation)
 * 4. TF-M jumps to NS Reset_Handler
 * 5. NS startup code runs, then calls main() (we are here)
 *
 * IMPORTANT: The STM32H5 clocks are configured by TF-M secure firmware.
 * NS code inherits the clock configuration.
 */
int main(void)
{
    /* Initialize HAL library (systick, NVIC priority grouping)
     * Note: Clock init is done by TF-M, we just need HAL basics */
    HAL_Init();

    /* =====================================================================
     * PSA CRYPTO INITIALIZATION
     * =====================================================================
     * This establishes connection to TF-M's crypto partition.
     * All subsequent psa_* calls will cross the S/NS boundary via
     * secure veneers (NSC - Non-Secure Callable functions).
     *
     * Under the hood:
     * 1. psa_crypto_init() is called
     * 2. This invokes tfm_crypto_init() veneer function
     * 3. TF-M routes the call to the Crypto Secure Partition
     * 4. The partition initializes the crypto library (mbed TLS)
     */
    if (app_psa_init() != 0)
    {
        Error_Handler();
    }

    /* Initialize GPIO (LEDs for status indication) */
    MX_GPIO_Init();

    /* Initialize USB peripheral (CDC Virtual COM Port) */
    MX_USB_PCD_Init();

    /* =====================================================================
     * ENTER THREADX KERNEL
     * =====================================================================
     * tx_kernel_enter() never returns. It:
     * 1. Calls tx_application_define() to create threads/resources
     * 2. Starts the scheduler
     * 3. Begins executing the highest priority ready thread
     */
    tx_kernel_enter();

    /* Should never reach here */
    while (1) {}
}

/* ============================================================================
 *                    THREADX APPLICATION DEFINITION
 * ============================================================================
 */

/**
 * @brief  ThreadX application initialization callback
 *
 * This function is called by tx_kernel_enter() BEFORE the scheduler starts.
 * Use this to create all OS objects (threads, queues, semaphores, etc.)
 *
 * MEMORY MODEL:
 * ThreadX uses byte pools for dynamic memory allocation. We create one pool
 * from a static buffer, then allocate from it for USBX stack memory.
 *
 * @param first_unused_memory  Pointer to first unused RAM (from linker)
 *                             We don't use this; we use our own static buffer
 */
void tx_application_define(void *first_unused_memory)
{
    UINT status;
    VOID *memory_ptr;

    /* Suppress unused parameter warning (we use static buffer instead) */
    (void)first_unused_memory;

    /* Create ThreadX byte pool for dynamic memory allocation
     * This pool is used by USBX for:
     * - USB device controller structures
     * - CDC ACM class instance
     * - Transfer buffers
     */
    status = tx_byte_pool_create(&tx_app_byte_pool, "TX App Pool",
                                 tx_byte_pool_buffer, USBX_APP_MEM_POOL_SIZE);
    if (status != TX_SUCCESS)
    {
        Error_Handler();
    }

    /* Allocate memory for USBX device stack */
    status = tx_byte_allocate(&tx_app_byte_pool, &memory_ptr,
                              USBX_DEVICE_MEMORY_STACK_SIZE, TX_NO_WAIT);
    if (status != TX_SUCCESS)
    {
        Error_Handler();
    }

    /* Initialize USBX device stack with CDC ACM class
     * This creates the USB device thread and registers the CDC class */
    status = MX_USBX_Device_Init(memory_ptr);
    if (status != UX_SUCCESS)
    {
        Error_Handler();
    }
}

/* ============================================================================
 *                      PERIPHERAL INITIALIZATION
 * ============================================================================
 */

/**
 * @brief  Initialize GPIO for LED status indication
 *
 * TRUSTZONE NOTE:
 * GPIO peripherals are assigned to NS world by TF-M via GTZC TZSC.
 * We can only access GPIOs that TF-M has configured as non-secure.
 * Attempting to access secure GPIOs would trigger a secure fault.
 */
static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Enable GPIO clocks for ports we need */
    __HAL_RCC_GPIOA_CLK_ENABLE();  /* USB pins */
    __HAL_RCC_GPIOB_CLK_ENABLE();  /* LED pins */

    /* Configure LED as push-pull output
     * LED is used to indicate:
     * - OFF: Normal operation
     * - ON: Error condition (see Error_Handler)
     */
    GPIO_InitStruct.Pin = LED_YELLOW_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_YELLOW_PORT, &GPIO_InitStruct);
    HAL_GPIO_WritePin(LED_YELLOW_PORT, LED_YELLOW_PIN, GPIO_PIN_RESET);
}

/**
 * @brief  Initialize USB peripheral in device mode
 *
 * The STM32H563 has a USB Full-Speed (12 Mbps) peripheral with:
 * - 8 bidirectional endpoints
 * - Embedded PHY (no external components needed)
 * - Dual-Role Device (DRD) capability (we use Device mode only)
 *
 * SECURITY CONSIDERATION:
 * USB is a complex attack surface. We use USBX which has been
 * designed with security in mind. The CDC ACM class is simple
 * and well-tested.
 */
static void MX_USB_PCD_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Enable USB peripheral clock */
    __HAL_RCC_USB_CLK_ENABLE();

    /* Configure USB D- and D+ pins as alternate function */
    GPIO_InitStruct.Pin = USB_DM_PIN | USB_DP_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    GPIO_InitStruct.Alternate = USB_AF;
    HAL_GPIO_Init(USB_GPIO_PORT, &GPIO_InitStruct);

    /* Configure USB PCD (Peripheral Controller Driver) */
    hpcd_USB_DRD_FS.Instance = USB_DRD_FS;
    hpcd_USB_DRD_FS.Init.dev_endpoints = 8;      /* Max endpoints supported */
    hpcd_USB_DRD_FS.Init.speed = PCD_SPEED_FULL; /* 12 Mbps Full-Speed */
    hpcd_USB_DRD_FS.Init.phy_itface = PCD_PHY_EMBEDDED;
    hpcd_USB_DRD_FS.Init.Sof_enable = DISABLE;
    hpcd_USB_DRD_FS.Init.low_power_enable = DISABLE;
    hpcd_USB_DRD_FS.Init.lpm_enable = DISABLE;
    hpcd_USB_DRD_FS.Init.battery_charging_enable = DISABLE;

    if (HAL_PCD_Init(&hpcd_USB_DRD_FS) != HAL_OK)
    {
        Error_Handler();
    }

    /* Configure USB interrupt priority
     * Priority 6 is below ThreadX kernel priority (typically 0-4)
     * This ensures USB doesn't starve critical system operations
     *
     * ANSSI: Interrupt priorities should be carefully designed
     * to prevent priority inversion and DoS scenarios
     */
    HAL_NVIC_SetPriority(USB_DRD_FS_IRQn, 6, 0);
    HAL_NVIC_EnableIRQ(USB_DRD_FS_IRQn);
}

/* ============================================================================
 *                          ERROR HANDLING
 * ============================================================================
 */

/**
 * @brief  Fatal error handler
 *
 * Called when an unrecoverable error occurs. Actions:
 * 1. Disable all interrupts (prevent further processing)
 * 2. Turn on LED to indicate error
 * 3. Loop forever (requires manual reset)
 *
 * PRODUCTION CONSIDERATION:
 * In production, consider:
 * - Logging the error to persistent storage
 * - Triggering a watchdog reset after a delay
 * - Not exposing detailed error info (ANSSI recommendation)
 */
void Error_Handler(void)
{
    /* Disable interrupts to prevent further processing */
    __disable_irq();

    /* Visual error indication */
    HAL_GPIO_WritePin(LED_YELLOW_PORT, LED_YELLOW_PIN, GPIO_PIN_SET);

    /* Infinite loop - requires manual reset */
    while (1) {}
}
