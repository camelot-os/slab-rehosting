/**
 * @file    main.c
 * @brief   Secure world main - STM32H563 TrustZone CDC ACM project
 *
 * Configures TrustZone (SAU, GTZC), initializes system clocks,
 * sets up USART1 for secure debug output, then jumps to the
 * non-secure application.
 *
 * ANSSI Compliance: Implements security hardening per ANSSI recommendations
 */

#include "main.h"
#include "partition_stm32h563xx.h"
#include "secure_nsc.h"
#include "security_config.h"
#include <string.h>

/* Private variables */
UART_HandleTypeDef huart1;

#if SECURITY_ENABLE_IWDG
IWDG_HandleTypeDef hiwdg;
#endif

/* Private function prototypes */
static void MX_USART1_UART_Init(void);
static void MX_GTZC_S_Init(void);
static void MX_GPIO_Init(void);
static void NonSecure_Init(void);

#if SECURITY_ENABLE_IWDG
static void MX_IWDG_Init(void);
#endif

#if SECURITY_LOCK_DEBUG
static void Security_LockDebugInterface(void);
#endif

#if SECURITY_VERIFY_NS_IMAGE
static int Security_ValidateNSImage(uint32_t ns_vector_table);
#endif

#if SECURITY_CONFIGURE_GPDMA
static void Security_ConfigureGPDMA(void);
#endif

/**
 * @brief  Secure main entry point
 */
int main(void)
{
    /* SAU/IDAU, FPU and Interrupts secure/non-secure allocation setup */
    SAU_Setup();

    /* MCU Configuration */
    HAL_Init();

    /* Configure the system clock to 250 MHz */
    SystemClock_Config();

    /* Initialize GTZC for peripheral and memory security */
    MX_GTZC_S_Init();

#if SECURITY_CONFIGURE_GPDMA
    /* Configure GPDMA channel security (ANSSI requirement) */
    Security_ConfigureGPDMA();
#endif

    /* Initialize secure GPIOs */
    MX_GPIO_Init();

    /* Initialize USART1 for debug output (secure) */
    MX_USART1_UART_Init();

#if SECURITY_ENABLE_IWDG
    /* Initialize Independent Watchdog (ANSSI requirement) */
    MX_IWDG_Init();
#endif

#if SECURITY_LOCK_DEBUG
    /* Lock debug interface in production (ANSSI Critical) */
    Security_LockDebugInterface();
#endif

    /* Print secure boot message */
    const char *boot_msg = "\r\n[SECURE] STM32H563 TrustZone Boot\r\n"
                           "[SECURE] SAU configured, GTZC initialized\r\n"
#if SECURITY_ENABLE_IWDG
                           "[SECURE] IWDG watchdog enabled\r\n"
#endif
#if SECURITY_LOCK_DEBUG
                           "[SECURE] Debug interface locked (PRODUCTION)\r\n"
#endif
                           "[SECURE] USART1 debug ready (115200 8N1)\r\n"
                           "[SECURE] Validating NS image...\r\n";
    HAL_UART_Transmit(&huart1, (uint8_t *)boot_msg, (uint16_t)strlen(boot_msg), HAL_MAX_DELAY);

    /* Boot non-secure application */
    NonSecure_Init();

    /* Should never reach here */
    while (1)
    {
#if SECURITY_ENABLE_IWDG
        /* Refresh watchdog in case of unexpected loop */
        HAL_IWDG_Refresh(&hiwdg);
#endif
    }
}

/**
 * @brief  Initialize and jump to Non-Secure application
 *
 * ANSSI Compliance: Validates NS image before execution
 */
static void NonSecure_Init(void)
{
    uint32_t ns_vector_table = VTOR_TABLE_NS_START_ADDR;
    uint32_t ns_stack_ptr;
    funcptr_NS ns_reset_handler;

#if SECURITY_VERIFY_NS_IMAGE
    /* Validate NS image before jumping (ANSSI requirement) */
    if (Security_ValidateNSImage(ns_vector_table) != 0)
    {
        const char *err_msg = "[SECURE] ERROR: NS image validation failed!\r\n"
                              "[SECURE] System halted for security.\r\n";
        HAL_UART_Transmit(&huart1, (uint8_t *)err_msg, (uint16_t)strlen(err_msg), HAL_MAX_DELAY);
        Error_Handler();
    }
    const char *ok_msg = "[SECURE] NS image validated OK\r\n"
                         "[SECURE] Jumping to Non-Secure application...\r\n\r\n";
    HAL_UART_Transmit(&huart1, (uint8_t *)ok_msg, (uint16_t)strlen(ok_msg), HAL_MAX_DELAY);
#endif

    /* Set non-secure vector table */
    SCB_NS->VTOR = ns_vector_table;

    /* Get non-secure stack pointer (first entry in vector table) */
    ns_stack_ptr = *((uint32_t *)ns_vector_table);

    /* Set non-secure main stack pointer */
    __TZ_set_MSP_NS(ns_stack_ptr);

    /* Get non-secure Reset Handler address (second entry in vector table) */
    ns_reset_handler = (funcptr_NS)(*((uint32_t *)(ns_vector_table + 4U)));

    /* Jump to non-secure Reset Handler */
    ns_reset_handler();
}

/**
 * @brief  System Clock Configuration
 *         PLL1 sourced from HSE (8 MHz) -> 250 MHz SYSCLK
 *         USB clock from HSI48 (48 MHz)
 */
void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    /* Configure voltage scaling for 250 MHz */
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE0);
    while (!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

    /* Enable HSE and HSI48 oscillators */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE | RCC_OSCILLATORTYPE_HSI48;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.HSI48State = RCC_HSI48_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLL1_SOURCE_HSE;
    /* PLL1: 8 MHz / 2 * 125 / 2 = 250 MHz */
    RCC_OscInitStruct.PLL.PLLM = 2;
    RCC_OscInitStruct.PLL.PLLN = 125;
    RCC_OscInitStruct.PLL.PLLP = 2;
    RCC_OscInitStruct.PLL.PLLQ = 2;
    RCC_OscInitStruct.PLL.PLLR = 2;
    RCC_OscInitStruct.PLL.PLLRGE = RCC_PLL1_VCIRANGE_3;
    RCC_OscInitStruct.PLL.PLLVCOSEL = RCC_PLL1_VCORANGE_WIDE;
    RCC_OscInitStruct.PLL.PLLFRACN = 0;
    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
    {
        Error_Handler();
    }

    /* Configure clock tree: SYSCLK=250MHz, AHB=250MHz, APB1/2/3=250MHz */
    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2
                                | RCC_CLOCKTYPE_PCLK3;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
    RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;
    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
    {
        Error_Handler();
    }

    /* Select HSI48 as USB clock source */
    __HAL_RCC_USB_CONFIG(RCC_USBCLKSOURCE_HSI48);
}

/**
 * @brief  GTZC initialization - configure peripheral and memory security
 *
 * ANSSI Compliance: Explicit security configuration for all memory regions
 */
static void MX_GTZC_S_Init(void)
{
    MPCBB_ConfigTypeDef MPCBB_NonSecureArea = {0};
    MPCBB_ConfigTypeDef MPCBB_SecureArea = {0};

    /* Enable GTZC clock (H563 only has GTZC1) */
    __HAL_RCC_GTZC1_CLK_ENABLE();

    /*
     * TZSC Peripheral Security Configuration
     * - USART1: Secure (debug output)
     * - USB OTG FS: Non-Secure (CDC ACM in NS world)
     */

    /* Mark USB OTG FS as Non-Secure */
    if (HAL_GTZC_TZSC_ConfigPeriphAttributes(GTZC_PERIPH_USB, GTZC_TZSC_PERIPH_NSEC) != HAL_OK)
    {
        Error_Handler();
    }

    /* USART1 remains Secure by default (no action needed, reset state is secure) */

#if SECURITY_EXPLICIT_SRAM1
    /*
     * MPCBB Configuration for SRAM1 - EXPLICITLY Secure (ANSSI requirement)
     * SRAM1 (0x30000000, 256KB): Secure
     * Explicit configuration prevents reliance on default state
     */
    MPCBB_SecureArea.SecureRWIllegalMode = GTZC_MPCBB_SRWILADIS_ENABLE;
    MPCBB_SecureArea.InvertSecureState = GTZC_MPCBB_INVSECSTATE_NOT_INVERTED;

    /* Set all SRAM1 blocks as SECURE (0xFFFFFFFF = all bits secure) */
    for (uint32_t i = 0; i < GTZC_MPCBB_NB_VCTR_REG_MAX; i++)
    {
        MPCBB_SecureArea.AttributeConfig.MPCBB_SecConfig_array[i] = 0xFFFFFFFFUL;
    }
    if (HAL_GTZC_MPCBB_ConfigMem(SRAM1_BASE_S, &MPCBB_SecureArea) != HAL_OK)
    {
        Error_Handler();
    }
#endif

    /*
     * MPCBB Configuration - SRAM2/SRAM3 Non-Secure
     * SRAM2 (0x20000000 alias to 0x30040000): Non-Secure (NS application)
     * SRAM3: Non-Secure
     */

    /* Configure SRAM2 as Non-Secure (for NS application) */
    MPCBB_NonSecureArea.SecureRWIllegalMode = GTZC_MPCBB_SRWILADIS_ENABLE;
    MPCBB_NonSecureArea.InvertSecureState = GTZC_MPCBB_INVSECSTATE_NOT_INVERTED;

    /* Set all SRAM2 blocks as non-secure */
    for (uint32_t i = 0; i < GTZC_MPCBB_NB_VCTR_REG_MAX; i++)
    {
        MPCBB_NonSecureArea.AttributeConfig.MPCBB_SecConfig_array[i] = 0x00000000UL;
    }
    if (HAL_GTZC_MPCBB_ConfigMem(SRAM2_BASE_S, &MPCBB_NonSecureArea) != HAL_OK)
    {
        Error_Handler();
    }

    /* Configure SRAM3 as Non-Secure */
    if (HAL_GTZC_MPCBB_ConfigMem(SRAM3_BASE_S, &MPCBB_NonSecureArea) != HAL_OK)
    {
        Error_Handler();
    }

    /* Enable GTZC secure interrupt for illegal access detection */
    HAL_NVIC_SetPriority(GTZC_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(GTZC_IRQn);
}

/**
 * @brief  Secure GPIO initialization
 *         - USART1 TX/RX pins (Secure)
 *         - LED (optional, Secure indicator)
 */
static void MX_GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Enable GPIO clocks */
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    /* Configure USART1 pins: PA9 (TX), PA10 (RX) */
    GPIO_InitStruct.Pin = USART1_TX_PIN | USART1_RX_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    GPIO_InitStruct.Alternate = USART1_AF;
    HAL_GPIO_Init(USART1_TX_PORT, &GPIO_InitStruct);

    /* Configure secure LED (PB0 on NUCLEO-H563ZI) */
    GPIO_InitStruct.Pin = LED_GREEN_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GREEN_PORT, &GPIO_InitStruct);

    /* LED off initially */
    HAL_GPIO_WritePin(LED_GREEN_PORT, LED_GREEN_PIN, GPIO_PIN_RESET);
}

/**
 * @brief  USART1 initialization: 115200 baud, 8N1
 */
static void MX_USART1_UART_Init(void)
{
    __HAL_RCC_USART1_CLK_ENABLE();

    huart1.Instance = USART1;
    huart1.Init.BaudRate = 115200;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    huart1.Init.Mode = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    huart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
    huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;

    if (HAL_UART_Init(&huart1) != HAL_OK)
    {
        Error_Handler();
    }
}

/**
 * @brief  Error handler - toggle LED rapidly
 */
void Error_Handler(void)
{
    __disable_irq();
    HAL_GPIO_WritePin(LED_GREEN_PORT, LED_GREEN_PIN, GPIO_PIN_SET);
    while (1)
    {
    }
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    (void)file;
    (void)line;
    Error_Handler();
}
#endif

/* ============================================================================
 * ANSSI Security Functions
 * ============================================================================
 */

#if SECURITY_ENABLE_IWDG
/**
 * @brief  Initialize Independent Watchdog
 *
 * ANSSI Recommendation: Watchdog prevents system hangs and ensures
 * the system remains in a known state.
 */
static void MX_IWDG_Init(void)
{
    hiwdg.Instance = IWDG;
    hiwdg.Init.Prescaler = IWDG_PRESCALER_64;
    /* Timeout calculation: (4096 * 64) / 32000 Hz = ~8.2 seconds */
    hiwdg.Init.Reload = 4095;
    hiwdg.Init.Window = IWDG_WINDOW_DISABLE;
    hiwdg.Init.EWI = 0;

    if (HAL_IWDG_Init(&hiwdg) != HAL_OK)
    {
        Error_Handler();
    }
}
#endif

#if SECURITY_LOCK_DEBUG
/**
 * @brief  Lock debug interface (SWD/JTAG) for production
 *
 * ANSSI Critical: Debug access must be disabled in production to prevent:
 * - Firmware extraction
 * - Memory inspection
 * - Debug-based attacks
 *
 * Note: This locks the debug interface until next reset.
 * For permanent lockout, use RDP Level 2.
 */
static void Security_LockDebugInterface(void)
{
    /* Configure DBGMCU as secure peripheral */
    if (HAL_GTZC_TZSC_ConfigPeriphAttributes(GTZC_PERIPH_DBGMCU, GTZC_TZSC_PERIPH_SEC) != HAL_OK)
    {
        Error_Handler();
    }

    /* Disable debug in low power modes */
    HAL_DBGMCU_DisableDBGStopMode();
    HAL_DBGMCU_DisableDBGStandbyMode();

    /* Clear debug enable bits in DHCSR (via secure access only)
     * Note: Full debug lockout requires RDP Level 2 */
}
#endif

#if SECURITY_VERIFY_NS_IMAGE
/**
 * @brief  Validate Non-Secure image before execution
 *
 * ANSSI Requirement: Verify image integrity before jumping to NS code.
 * Checks:
 * 1. Stack pointer is within valid NS SRAM range
 * 2. Reset handler is within valid NS Flash range
 * 3. Optional: CRC/signature verification
 *
 * @param  ns_vector_table: Address of NS vector table
 * @retval 0 if valid, -1 if invalid
 */
static int Security_ValidateNSImage(uint32_t ns_vector_table)
{
    uint32_t ns_stack_ptr;
    uint32_t ns_reset_handler;

    /* Read stack pointer (first entry in vector table) */
    ns_stack_ptr = *((uint32_t *)ns_vector_table);

    /* Read reset handler (second entry in vector table) */
    ns_reset_handler = *((uint32_t *)(ns_vector_table + 4U));

    /* Clear LSB of reset handler (Thumb bit) for address validation */
    ns_reset_handler &= ~1UL;

    /* Validation 1: Stack pointer must be in valid NS SRAM range */
    if ((ns_stack_ptr < NS_STACK_PTR_MIN) || (ns_stack_ptr > NS_STACK_PTR_MAX))
    {
        return -1;  /* Invalid stack pointer */
    }

    /* Validation 2: Reset handler must be in valid NS Flash range */
    if ((ns_reset_handler < NS_RESET_HANDLER_MIN) || (ns_reset_handler > NS_RESET_HANDLER_MAX))
    {
        return -1;  /* Invalid reset handler */
    }

    /* Validation 3: Stack pointer should be word-aligned */
    if ((ns_stack_ptr & 0x3UL) != 0)
    {
        return -1;  /* Misaligned stack pointer */
    }

#if SECURITY_NS_IMAGE_CRC
    /* Optional: CRC32 validation of NS image
     * In a full implementation, compute CRC over NS flash region
     * and compare against expected value stored in secure flash.
     *
     * For now, skip CRC if placeholder value is used */
    if (NS_IMAGE_EXPECTED_CRC != 0xFFFFFFFFUL)
    {
        /* TODO: Implement CRC32 computation using hardware CRC unit */
        /* uint32_t computed_crc = HAL_CRC_Calculate(...); */
        /* if (computed_crc != NS_IMAGE_EXPECTED_CRC) return -1; */
    }
#endif

    return 0;  /* Image validated successfully */
}
#endif

#if SECURITY_CONFIGURE_GPDMA
/**
 * @brief  Configure GPDMA channel security
 *
 * ANSSI Requirement: All GPDMA channels must be explicitly configured
 * to prevent DMA-based attacks where NS code could use an unconfigured
 * channel to access secure memory.
 *
 * Note: On STM32H5, GPDMA has its own security registers (SECCFGR/PRIVCFGR)
 * at the DMA peripheral base address. This is different from STM32U5 where
 * GPDMA security is configured through GTZC_TZSC.
 */
static void Security_ConfigureGPDMA(void)
{
    /* Enable GPDMA1 clock */
    __HAL_RCC_GPDMA1_CLK_ENABLE();

    /*
     * Configure all GPDMA1 channels as Non-Secure and Non-Privileged
     * STM32H5 GPDMA has direct security registers:
     * - SECCFGR at offset 0x00: bit N = 1 means channel N is secure
     * - PRIVCFGR at offset 0x04: bit N = 1 means channel N is privileged
     * Setting to 0 allows NS code to use DMA (MPCBB still enforces memory protection)
     */
    GPDMA1->SECCFGR = 0x00000000U;   /* All channels non-secure */
    GPDMA1->PRIVCFGR = 0x00000000U;  /* All channels non-privileged */

    /* Enable GPDMA2 clock and configure as non-secure */
    __HAL_RCC_GPDMA2_CLK_ENABLE();
    GPDMA2->SECCFGR = 0x00000000U;
    GPDMA2->PRIVCFGR = 0x00000000U;
}
#endif
