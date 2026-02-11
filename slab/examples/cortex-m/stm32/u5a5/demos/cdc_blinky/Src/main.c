/**
  * STM32U5A5 USB CDC Blinky - Native U5 HAL (DWC2 OTG HS)
  *
  * Demonstrates:
  * - PMSAv8 MPU configuration (Flash RO/exec, SRAM RW/noexec, Peripherals device)
  * - USB CDC ACM (VCP echo mode, sends "helloworld\n\r" on connect)
  * - USART1 output at 115200 baud on PA9 (TX) / PA10 (RX)
  * - LPUART1 output at 115200 baud on PA2 (TX) / PA3 (RX)
  * - Flash read/write demo (read UID, write/verify one page, erase)
  * - LED blink via TIM2: PC7 green (LD1), PB7 blue (LD2)
  *
  * System clock: 160 MHz from MSIS 4 MHz + PLL1 (N=80, M=1, R=1)
  * USB clock:    48 MHz from HSI48 (via CRS auto-calibration)
  *
  * Target: Nucleo-U5A5ZJT6Q (Cortex-M33 @ 160 MHz, TrustZone)
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "usb_device.h"
#include <string.h>

TIM_HandleTypeDef htim2;
UART_HandleTypeDef huart1;
UART_HandleTypeDef hlpuart1;

static void MPU_Config(void);
static void SystemClock_Config(void);
static void LED_Init(void);
static void TIM2_Init(void);
static void USART1_Init(void);
static void LPUART1_Init(void);
static void Flash_Demo(void);
static void UART_Print(UART_HandleTypeDef *huart, const char *msg);

volatile uint8_t usb_ready = 0;
volatile uint8_t hello_sent = 0;
static volatile uint8_t led_toggle = 0;

int main(void)
{
  HAL_Init();

  MPU_Config();

  SystemClock_Config();

  LED_Init();

  USART1_Init();

  LPUART1_Init();

  TIM2_Init();

  /* Print boot banner on both UARTs */
  UART_Print(&huart1,  "\r\n[U5A5] USART1: CDC Blinky starting...\r\n");
  UART_Print(&hlpuart1, "\r\n[U5A5] LPUART1: CDC Blinky starting...\r\n");

  UART_Print(&huart1,  "[U5A5] MPU: PMSAv8 configured (4 regions)\r\n");
  UART_Print(&hlpuart1, "[U5A5] MPU: PMSAv8 configured (4 regions)\r\n");

  /* Flash read/write demonstration */
  Flash_Demo();

  /* Initialize USB Device (HSI48 clock + CDC stack) */
  MX_USB_Device_Init();

  UART_Print(&huart1,  "[U5A5] USB CDC initialized, waiting for host...\r\n");
  UART_Print(&hlpuart1, "[U5A5] USB CDC initialized, waiting for host...\r\n");

  while (1)
  {
    if (usb_ready && !hello_sent)
    {
      usb_send_hello();
      hello_sent = 1;
      UART_Print(&huart1,  "[U5A5] USB host connected, hello sent.\r\n");
      UART_Print(&hlpuart1, "[U5A5] USB host connected, hello sent.\r\n");
    }
  }
}

/**
  * PMSAv8 MPU Configuration for STM32U5A5 (Cortex-M33)
  *
  * Memory map:
  *   Region 0: Flash  0x08000000 - 0x083FFFFF (4 MB)  - Normal cacheable, RO, exec
  *   Region 1: SRAM   0x20000000 - 0x2026FFFF (2.5 MB) - Normal cacheable, RW, noexec
  *   Region 2: Periph 0x40000000 - 0x4FFFFFFF (256 MB) - Device-nGnRnE, RW, noexec
  *   Region 3: System 0xE0000000 - 0xE00FFFFF (1 MB)   - Device-nGnRnE, RW, noexec
  *
  * MAIR attributes:
  *   Attr 0: Device-nGnRnE  (0x00) - strongly-ordered device memory
  *   Attr 1: Normal WB RA WA (0xFF) - write-back, read/write allocate, cacheable
  */
static void MPU_Config(void)
{
  /* Disable MPU before configuration */
  ARM_MPU_Disable();

  /* Configure memory attributes (MAIR0/MAIR1) */
  ARM_MPU_SetMemAttr(0, ARM_MPU_ATTR(ARM_MPU_ATTR_DEVICE,
                                       ARM_MPU_ATTR_DEVICE_nGnRnE));   /* Attr 0: Device */
  ARM_MPU_SetMemAttr(1, ARM_MPU_ATTR(ARM_MPU_ATTR_MEMORY_(1,1,1,1),
                                       ARM_MPU_ATTR_MEMORY_(1,1,1,1))); /* Attr 1: Normal WB */

  /* Region 0: Flash - 0x08000000 to 0x083FFFFF
   *   Normal cacheable (Attr 1), inner-shareable, read-only, executable
   *   RBAR: SH=inner(3), RO=1, NP=0 (priv only), XN=0 (executable) */
  ARM_MPU_SetRegion(0,
    ARM_MPU_RBAR(0x08000000, ARM_MPU_SH_INNER, 1U, 0U, 0U),
    ARM_MPU_RLAR(0x083FFFFF, 1));

  /* Region 1: SRAM - 0x20000000 to 0x2026FFFF
   *   Normal cacheable (Attr 1), inner-shareable, read-write, non-executable
   *   RBAR: SH=inner(3), RO=0, NP=1 (any priv), XN=1 (no exec) */
  ARM_MPU_SetRegion(1,
    ARM_MPU_RBAR(0x20000000, ARM_MPU_SH_INNER, 0U, 1U, 1U),
    ARM_MPU_RLAR(0x2026FFFF, 1));

  /* Region 2: Peripherals - 0x40000000 to 0x4FFFFFFF
   *   Device-nGnRnE (Attr 0), non-shareable, read-write, non-executable
   *   RBAR: SH=non(0), RO=0, NP=0 (priv only), XN=1 (no exec) */
  ARM_MPU_SetRegion(2,
    ARM_MPU_RBAR(0x40000000, ARM_MPU_SH_NON, 0U, 0U, 1U),
    ARM_MPU_RLAR(0x4FFFFFFF, 0));

  /* Region 3: System peripherals (PPB) - 0xE0000000 to 0xE00FFFFF
   *   Device-nGnRnE (Attr 0), non-shareable, read-write, non-executable
   *   RBAR: SH=non(0), RO=0, NP=0 (priv only), XN=1 (no exec) */
  ARM_MPU_SetRegion(3,
    ARM_MPU_RBAR(0xE0000000, ARM_MPU_SH_NON, 0U, 0U, 1U),
    ARM_MPU_RLAR(0xE00FFFFF, 0));

  /* Enable MPU with PRIVDEFENA (privileged default map for uncovered regions) */
  ARM_MPU_Enable(MPU_CTRL_PRIVDEFENA_Msk);
}

/**
  * System Clock Configuration
  *   MSIS (4 MHz) -> PLL1 (M=1, N=80, R=2) -> SYSCLK = 160 MHz
  *   PLL1Q = 2 -> PLL1Q output = 160 MHz (not used for USB, HSI48 used instead)
  *   HCLK = 160 MHz, APB1 = 160 MHz, APB2 = 160 MHz, APB3 = 160 MHz
  *
  * Note: For U5, MSIS replaces MSI. The PLL1 VCO = 4 MHz * 80 = 320 MHz.
  *       PLLR = 2 -> SYSCLK = 320/2 = 160 MHz.
  */
static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /* Configure voltage scaling for 160 MHz operation */
  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  /* Enable MSIS oscillator + configure PLL1 */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_MSI;
  RCC_OscInitStruct.MSIState = RCC_MSI_ON;
  RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_4;  /* MSIS = 4 MHz */
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
  RCC_OscInitStruct.PLL.PLLM = 1;
  RCC_OscInitStruct.PLL.PLLN = 80;
  RCC_OscInitStruct.PLL.PLLP = 2;
  RCC_OscInitStruct.PLL.PLLQ = 2;
  RCC_OscInitStruct.PLL.PLLR = 2;

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure bus clocks: SYSCLK = PLL1R, all dividers /1 */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2
                              | RCC_CLOCKTYPE_PCLK3;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;

  /* Flash latency for 160 MHz at VOS1: 4 wait states */
  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * Initialize LEDs: PC7 (green LD1), PB7 (blue LD2)
  */
static void LED_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  LED1_GPIO_CLK_ENABLE();
  LED2_GPIO_CLK_ENABLE();

  /* PC7 - Green LED */
  GPIO_InitStruct.Pin = LED1_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED1_GPIO_PORT, &GPIO_InitStruct);
  HAL_GPIO_WritePin(LED1_GPIO_PORT, LED1_PIN, GPIO_PIN_RESET);

  /* PB7 - Blue LED */
  GPIO_InitStruct.Pin = LED2_PIN;
  HAL_GPIO_Init(LED2_GPIO_PORT, &GPIO_InitStruct);
  HAL_GPIO_WritePin(LED2_GPIO_PORT, LED2_PIN, GPIO_PIN_RESET);
}

/**
  * Initialize TIM2 for LED blink (500ms period, alternating green/blue)
  *
  * Timer clock = 160 MHz (APB1 = HCLK = 160 MHz, timer multiplier x1)
  * PSC = 16000-1 -> timer tick = 160 MHz / 16000 = 10 kHz
  * ARR = 5000-1  -> overflow = 10 kHz / 5000 = 2 Hz (500ms)
  */
static void TIM2_Init(void)
{
  __HAL_RCC_TIM2_CLK_ENABLE();

  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 16000 - 1;
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 5000 - 1;
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }

  HAL_NVIC_SetPriority(TIM2_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(TIM2_IRQn);

  HAL_TIM_Base_Start_IT(&htim2);
}

/**
  * Initialize USART1: 115200 baud, 8N1
  * TX = PA9 (AF7), RX = PA10 (AF7)
  */
static void USART1_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_USART1_CLK_ENABLE();

  /* PA9 (TX) and PA10 (RX) as AF7 */
  GPIO_InitStruct.Pin = USART1_TX_PIN | USART1_RX_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  GPIO_InitStruct.Alternate = USART1_AF;
  HAL_GPIO_Init(USART1_GPIO_PORT, &GPIO_InitStruct);

  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;

  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }

  HAL_NVIC_SetPriority(USART1_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(USART1_IRQn);
}

/**
  * Initialize LPUART1: 115200 baud, 8N1
  * TX = PA2 (AF8), RX = PA3 (AF8)
  *
  * LPUART1 is on APB3 (clocked from PCLK3 = 160 MHz).
  */
static void LPUART1_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_LPUART1_CLK_ENABLE();

  /* PA2 (TX) and PA3 (RX) as AF8 */
  GPIO_InitStruct.Pin = LPUART1_TX_PIN | LPUART1_RX_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  GPIO_InitStruct.Alternate = LPUART1_AF;
  HAL_GPIO_Init(LPUART1_GPIO_PORT, &GPIO_InitStruct);

  hlpuart1.Instance = LPUART1;
  hlpuart1.Init.BaudRate = 115200;
  hlpuart1.Init.WordLength = UART_WORDLENGTH_8B;
  hlpuart1.Init.StopBits = UART_STOPBITS_1;
  hlpuart1.Init.Parity = UART_PARITY_NONE;
  hlpuart1.Init.Mode = UART_MODE_TX_RX;
  hlpuart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  hlpuart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  hlpuart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;

  if (HAL_UART_Init(&hlpuart1) != HAL_OK)
  {
    Error_Handler();
  }

  HAL_NVIC_SetPriority(LPUART1_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(LPUART1_IRQn);
}

/**
  * Flash read/write demonstration:
  *   1. Read 96-bit Unique Device ID from 0x0BFA0700
  *   2. Erase one page near end of flash (page 511, bank 2)
  *   3. Write a test pattern (32 bytes / 4 quadwords)
  *   4. Read back and verify
  *   5. Erase the page to leave flash clean
  *
  * Note: STM32U5 flash writes must be 128-bit (quadword) aligned.
  */
static void Flash_Demo(void)
{
  uint32_t uid[3];
  char buf[80];
  uint32_t read_back[8];
  FLASH_EraseInitTypeDef erase_init;
  uint32_t page_error = 0;
  HAL_StatusTypeDef status;
  uint32_t i;

  /* Step 1: Read Unique Device ID */
  uid[0] = *(volatile uint32_t *)(U5_UID_BASE + 0x00);
  uid[1] = *(volatile uint32_t *)(U5_UID_BASE + 0x04);
  uid[2] = *(volatile uint32_t *)(U5_UID_BASE + 0x08);

  /* Format UID string manually (no snprintf dependency) */
  {
    static const char hex[] = "0123456789ABCDEF";
    const char *prefix = "[U5A5] UID: ";
    uint32_t idx = 0;
    uint32_t w, nibble;

    while (*prefix)
      buf[idx++] = *prefix++;

    for (w = 0; w < 3; w++)
    {
      for (nibble = 0; nibble < 8; nibble++)
      {
        buf[idx++] = hex[(uid[w] >> (28 - nibble * 4)) & 0xF];
      }
      if (w < 2)
        buf[idx++] = '-';
    }
    buf[idx++] = '\r';
    buf[idx++] = '\n';
    buf[idx] = '\0';
  }

  UART_Print(&huart1, buf);
  UART_Print(&hlpuart1, buf);

  /* Step 2: Unlock flash and erase target page */
  HAL_FLASH_Unlock();

  erase_init.TypeErase = FLASH_TYPEERASE_PAGES;
  erase_init.Banks = FLASH_DEMO_BANK;
  erase_init.Page = FLASH_DEMO_PAGE;
  erase_init.NbPages = 1;

  status = HAL_FLASHEx_Erase(&erase_init, &page_error);
  if (status != HAL_OK)
  {
    UART_Print(&huart1,  "[U5A5] Flash erase FAILED\r\n");
    UART_Print(&hlpuart1, "[U5A5] Flash erase FAILED\r\n");
    HAL_FLASH_Lock();
    return;
  }

  UART_Print(&huart1,  "[U5A5] Flash page erased OK\r\n");
  UART_Print(&hlpuart1, "[U5A5] Flash page erased OK\r\n");

  /* Step 3: Write test pattern (4 quadwords = 64 bytes)
   * STM32U5 requires 128-bit (quadword) aligned writes.
   * HAL_FLASH_Program with FLASH_TYPEPROGRAM_QUADWORD writes 16 bytes at a time.
   */
  {
    /* 4 quadwords of test data (each 16 bytes = 4 uint32_t) */
    static const uint32_t test_data[16] = {
      0xDEADBEEF, 0xCAFEBABE, 0x12345678, 0x9ABCDEF0,
      0xA5A5A5A5, 0x5A5A5A5A, 0xFF00FF00, 0x00FF00FF,
      0x01020304, 0x05060708, 0x090A0B0C, 0x0D0E0F10,
      0xFEDCBA98, 0x76543210, 0xAAAA5555, 0x5555AAAA
    };

    for (i = 0; i < 4; i++)
    {
      status = HAL_FLASH_Program(FLASH_TYPEPROGRAM_QUADWORD,
                                  FLASH_DEMO_ADDR + (i * 16),
                                  (uint32_t)&test_data[i * 4]);
      if (status != HAL_OK)
      {
        UART_Print(&huart1,  "[U5A5] Flash write FAILED\r\n");
        UART_Print(&hlpuart1, "[U5A5] Flash write FAILED\r\n");
        HAL_FLASH_Lock();
        return;
      }
    }
  }

  UART_Print(&huart1,  "[U5A5] Flash write OK (64 bytes)\r\n");
  UART_Print(&hlpuart1, "[U5A5] Flash write OK (64 bytes)\r\n");

  /* Step 4: Verify written data */
  memcpy(read_back, (void *)FLASH_DEMO_ADDR, sizeof(read_back));

  if (read_back[0] == 0xDEADBEEF && read_back[1] == 0xCAFEBABE &&
      read_back[2] == 0x12345678 && read_back[3] == 0x9ABCDEF0)
  {
    UART_Print(&huart1,  "[U5A5] Flash verify OK\r\n");
    UART_Print(&hlpuart1, "[U5A5] Flash verify OK\r\n");
  }
  else
  {
    UART_Print(&huart1,  "[U5A5] Flash verify FAILED\r\n");
    UART_Print(&hlpuart1, "[U5A5] Flash verify FAILED\r\n");
  }

  /* Step 5: Erase page again to leave flash clean */
  HAL_FLASHEx_Erase(&erase_init, &page_error);

  HAL_FLASH_Lock();

  UART_Print(&huart1,  "[U5A5] Flash demo complete\r\n");
  UART_Print(&hlpuart1, "[U5A5] Flash demo complete\r\n");
}

/**
  * Blocking UART print helper (polling mode)
  */
static void UART_Print(UART_HandleTypeDef *huart, const char *msg)
{
  HAL_UART_Transmit(huart, (const uint8_t *)msg, (uint16_t)strlen(msg), 100);
}

/**
  * TIM2 period elapsed callback - alternating LED pattern
  * Toggles green and blue LEDs alternately every 500ms.
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    if (led_toggle)
    {
      HAL_GPIO_WritePin(LED1_GPIO_PORT, LED1_PIN, GPIO_PIN_SET);    /* Green ON */
      HAL_GPIO_WritePin(LED2_GPIO_PORT, LED2_PIN, GPIO_PIN_RESET);  /* Blue OFF */
    }
    else
    {
      HAL_GPIO_WritePin(LED1_GPIO_PORT, LED1_PIN, GPIO_PIN_RESET);  /* Green OFF */
      HAL_GPIO_WritePin(LED2_GPIO_PORT, LED2_PIN, GPIO_PIN_SET);    /* Blue ON */
    }

    led_toggle ^= 1;
  }
}

void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
