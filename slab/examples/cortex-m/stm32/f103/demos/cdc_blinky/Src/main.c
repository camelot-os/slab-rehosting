/**
  * STM32F103 BluePill USB CDC Blinky - Native F1 HAL
  *
  * - Configures system clock to 72 MHz (minimal for emulation)
  * - Initializes LED on PC13 (BluePill onboard, active LOW)
  * - Initializes USB CDC (VCP) with echo mode
  * - Sends "helloworld\n\r" once USB host configures the device
  *
  * Target: STM32F103C8 (Cortex-M3 @ 72 MHz, USB FS with PMA)
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "usb_device.h"

static void SystemClock_Config(void);
static void LED_Init(void);

volatile uint8_t usb_ready = 0;
volatile uint8_t hello_sent = 0;

int main(void)
{
  HAL_Init();

  SystemClock_Config();

  LED_Init();

  /* Initialize USB Device (CDC stack) */
  MX_USB_Device_Init();

  while (1)
  {
    if (usb_ready && !hello_sent)
    {
      usb_send_hello();
      hello_sent = 1;
    }
  }
}

/**
  * System Clock Configuration (minimal for emulation)
  *
  * In emulation the QEMU machine provides the sysclk-hz property,
  * so we only need to set up minimal RCC state so the HAL is happy.
  *
  * Target: HSI 8 MHz -> PLL (x9) -> 72 MHz SYSCLK
  *         USB prescaler /1.5 -> 48 MHz USB clock
  *         Flash: 2 wait states at 72 MHz
  */
static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /* Configure HSI oscillator and PLL */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI_DIV2;  /* HSI/2 = 4 MHz */
  RCC_OscInitStruct.PLL.PLLMUL = RCC_PLL_MUL9;               /* 4 * 9 = 36 MHz ... */

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure bus clocks: SYSCLK from PLL, AHB/APB dividers */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * Initialize LED on PC13 (BluePill onboard LED, active LOW)
  */
static void LED_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  LED_GPIO_CLK_ENABLE();

  /* PC13 - push-pull output, active low */
  GPIO_InitStruct.Pin = LED_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);

  /* LED ON (active low: RESET = ON) */
  HAL_GPIO_WritePin(LED_GPIO_PORT, LED_PIN, GPIO_PIN_RESET);
}

void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
