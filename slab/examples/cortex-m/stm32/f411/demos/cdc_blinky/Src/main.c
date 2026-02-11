/**
  * STM32F411 BlackPill USB CDC Blinky - Native F4 HAL (DWC2 OTG FS)
  *
  * Demonstrates:
  * - USB CDC ACM (VCP echo mode, sends "helloworld\n\r" on connect)
  * - USART2 output at 115200 baud on PA2 (TX) / PA3 (RX)
  * - LED blink on PC13 (active low, BlackPill onboard LED)
  *
  * System clock: 96 MHz from HSI 16 MHz + PLL (M=16, N=192, P=2)
  * USB clock:    48 MHz from PLLQ (192 / 4 = 48 MHz)
  *
  * Target: WeAct BlackPill V2.0 (STM32F411CEU6, Cortex-M4 @ 96 MHz)
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "usb_device.h"
#include <string.h>

UART_HandleTypeDef huart2;

static void SystemClock_Config(void);
static void LED_Init(void);
static void USART2_Init(void);
static void UART_Print(UART_HandleTypeDef *huart, const char *msg);

volatile uint8_t usb_ready = 0;
volatile uint8_t hello_sent = 0;

int main(void)
{
  HAL_Init();

  SystemClock_Config();

  LED_Init();

  USART2_Init();

  /* Print boot banner */
  UART_Print(&huart2, "\r\n[F411] USART2: CDC Blinky starting...\r\n");

  /* Initialize USB Device (PLL Q provides 48 MHz + CDC stack) */
  MX_USB_Device_Init();

  UART_Print(&huart2, "[F411] USB CDC initialized, waiting for host...\r\n");

  while (1)
  {
    if (usb_ready && !hello_sent)
    {
      usb_send_hello();
      hello_sent = 1;
      UART_Print(&huart2, "[F411] USB host connected, hello sent.\r\n");
    }

    /* Simple LED toggle (PC13 active low) */
    HAL_GPIO_TogglePin(LED_GPIO_PORT, LED_PIN);
    HAL_Delay(500);
  }
}

/**
  * System Clock Configuration
  *   HSI (16 MHz) -> PLL (M=16, N=192, P=2) -> SYSCLK = 96 MHz
  *   PLLQ = 4 -> 48 MHz for USB OTG FS
  *   HCLK = 96 MHz, APB1 = 48 MHz (div2), APB2 = 96 MHz (div1)
  *
  * Flash latency: 3 wait states at 96 MHz (2.7V-3.6V)
  */
static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /* Enable Power Control clock and set voltage scaling for high freq */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /* Configure HSI + PLL */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 16;   /* VCO input = 16 MHz / 16 = 1 MHz */
  RCC_OscInitStruct.PLL.PLLN = 192;   /* VCO output = 1 MHz * 192 = 192 MHz */
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;  /* SYSCLK = 192 / 2 = 96 MHz */
  RCC_OscInitStruct.PLL.PLLQ = 4;     /* USB CLK = 192 / 4 = 48 MHz */

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure bus clocks: SYSCLK = PLL, AHB = /1, APB1 = /2, APB2 = /1 */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;   /* APB1 = 48 MHz */
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;   /* APB2 = 96 MHz */

  /* Flash latency for 96 MHz at VOS1 (2.7V-3.6V): 3 wait states */
  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * Initialize LED: PC13 (active low on BlackPill)
  */
static void LED_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  LED_GPIO_CLK_ENABLE();

  /* PC13 - User LED (active low) */
  GPIO_InitStruct.Pin = LED_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);
  HAL_GPIO_WritePin(LED_GPIO_PORT, LED_PIN, GPIO_PIN_SET);  /* LED off (active low) */
}

/**
  * Initialize USART2: 115200 baud, 8N1
  * TX = PA2 (AF7), RX = PA3 (AF7)
  */
static void USART2_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_USART2_CLK_ENABLE();

  /* PA2 (TX) and PA3 (RX) as AF7 */
  GPIO_InitStruct.Pin = USART2_TX_PIN | USART2_RX_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  GPIO_InitStruct.Alternate = USART2_AF;
  HAL_GPIO_Init(USART2_GPIO_PORT, &GPIO_InitStruct);

  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;

  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }

  HAL_NVIC_SetPriority(USART2_IRQn, 6, 0);
  HAL_NVIC_EnableIRQ(USART2_IRQn);
}

/**
  * Blocking UART print helper (polling mode)
  */
static void UART_Print(UART_HandleTypeDef *huart, const char *msg)
{
  HAL_UART_Transmit(huart, (const uint8_t *)msg, (uint16_t)strlen(msg), 100);
}

void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
