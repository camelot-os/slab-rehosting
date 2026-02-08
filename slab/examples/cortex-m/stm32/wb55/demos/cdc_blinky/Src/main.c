/**
  * STM32WB55 USB CDC Blinky - Native WB55 HAL
  *
  * - Configures system clock to 64 MHz (MSI + PLL)
  * - Initializes 3 LEDs on PB0 (green), PB1 (red), PB5 (blue)
  * - Initializes USB CDC (VCP) with echo mode
  * - Sends "helloworld\n\r" once USB host configures the device
  * - Blinks LEDs via TIM2 interrupt (250ms period)
  *
  * Target: STM32WB55 (Cortex-M4 @ 64 MHz, USB FS)
  *
  * Copyright (C) 2026 TwistedWires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "usb_device.h"

TIM_HandleTypeDef htim2;

static void SystemClock_Config(void);
static void LED_Init(void);
static void TIM2_Init(void);

volatile uint8_t usb_ready = 0;
volatile uint8_t hello_sent = 0;
static volatile uint8_t led_phase = 0;

int main(void)
{
  HAL_Init();

  SystemClock_Config();

  LED_Init();

  TIM2_Init();

  /* Initialize USB Device (HSI48 clock + CDC stack) */
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
  * System Clock Configuration
  *   MSI (4 MHz, range 6) -> PLL (N=32, M=1, R=2) -> SYSCLK = 64 MHz
  *   HCLK = 64 MHz, APB1 = 64 MHz, APB2 = 64 MHz
  *   HCLK2 (CPU2) = 32 MHz, HCLK4 (AHB shared) = 64 MHz
  */
static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /* Configure voltage scaling */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /* MSI + PLL configuration */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_MSI;
  RCC_OscInitStruct.MSIState = RCC_MSI_ON;
  RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_6;  /* 4 MHz */
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
  RCC_OscInitStruct.PLL.PLLM = RCC_PLLM_DIV1;
  RCC_OscInitStruct.PLL.PLLN = 32;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV5;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV4;

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure bus clocks */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK4 | RCC_CLOCKTYPE_HCLK2
                              | RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.AHBCLK2Divider = RCC_SYSCLK_DIV2;
  RCC_ClkInitStruct.AHBCLK4Divider = RCC_SYSCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK)
  {
    Error_Handler();
  }

  /* Enable MSI Auto calibration */
  HAL_RCCEx_EnableMSIPLLMode();
}

/**
  * Initialize 3 LEDs on PB0 (green), PB1 (red), PB5 (blue)
  */
static void LED_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  LED_GPIO_CLK_ENABLE();

  GPIO_InitStruct.Pin = LED1_PIN | LED2_PIN | LED3_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);

  HAL_GPIO_WritePin(LED_GPIO_PORT, LED1_PIN | LED2_PIN | LED3_PIN, GPIO_PIN_RESET);
}

/**
  * Initialize TIM2 for LED blink (250ms period, rotating pattern)
  */
static void TIM2_Init(void)
{
  __HAL_RCC_TIM2_CLK_ENABLE();

  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 6400 - 1;          /* 64 MHz / 6400 = 10 kHz */
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 2500 - 1;             /* 10 kHz / 2500 = 4 Hz (250ms) */
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
  * TIM2 period elapsed callback - rotating LED pattern
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    HAL_GPIO_WritePin(LED_GPIO_PORT, LED1_PIN | LED2_PIN | LED3_PIN, GPIO_PIN_RESET);

    switch (led_phase)
    {
      case 0:
        HAL_GPIO_WritePin(LED_GPIO_PORT, LED1_PIN, GPIO_PIN_SET);  /* Blue */
        break;
      case 1:
        HAL_GPIO_WritePin(LED_GPIO_PORT, LED2_PIN, GPIO_PIN_SET);  /* Green */
        break;
      case 2:
        HAL_GPIO_WritePin(LED_GPIO_PORT, LED3_PIN, GPIO_PIN_SET);  /* Red */
        break;
      default:
        break;
    }

    led_phase = (led_phase + 1) & 3;
  }
}

void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
