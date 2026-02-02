/**
  * STM32F405 USB CDC Demo
  * - Sends "helloworld\n\r" on startup
  * - USB CDC echo mode (echoes received data)
  * - Blinks LED on PA13
  */
#include "main.h"

USBD_HandleTypeDef USBD_Device;
TIM_HandleTypeDef htim2;

static void SystemClock_Config(void);
static void LED_Init(void);
static void TIM2_Init(void);

volatile uint8_t usb_ready = 0;
volatile uint8_t hello_sent = 0;

int main(void)
{
  /* HAL initialization */
  HAL_Init();

  /* Configure system clock to 168 MHz using HSE */
  SystemClock_Config();

  /* Initialize LED on PA13 */
  LED_Init();

  /* Initialize Timer for LED blink */
  TIM2_Init();

  /* Initialize USB Device Library */
  USBD_Init(&USBD_Device, &VCP_Desc, 0);

  /* Register CDC Class */
  USBD_RegisterClass(&USBD_Device, USBD_CDC_CLASS);

  /* Register CDC Interface */
  USBD_CDC_RegisterInterface(&USBD_Device, &USBD_CDC_fops);

  /* Start USB Device */
  USBD_Start(&USBD_Device);

  /* Main loop */
  while (1)
  {
    /* Send "helloworld" once when USB is ready */
    if (usb_ready && !hello_sent)
    {
      const char *msg = "helloworld\n\r";
      CDC_Transmit((uint8_t*)msg, 12);
      hello_sent = 1;
    }
  }
}

/**
  * @brief  System Clock Configuration
  *         System Clock source = PLL (HSE)
  *         SYSCLK = 168 MHz
  *         HCLK = 168 MHz
  *         AHB Prescaler = 1
  *         APB1 Prescaler = 4
  *         APB2 Prescaler = 2
  *         HSE = 8 MHz (adjust PLLM for your crystal)
  *         PLL_M = 8, PLL_N = 336, PLL_P = 2, PLL_Q = 7
  *         USB OTG FS requires 48 MHz (336/7 = 48)
  */
static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /* Enable Power Control clock */
  __HAL_RCC_PWR_CLK_ENABLE();

  /* Voltage scaling for maximum performance */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

  /* Configure HSE and PLL */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 8;      /* HSE/8 = 1 MHz */
  RCC_OscInitStruct.PLL.PLLN = 336;    /* 1 MHz * 336 = 336 MHz VCO */
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;  /* 336/2 = 168 MHz SYSCLK */
  RCC_OscInitStruct.PLL.PLLQ = 7;      /* 336/7 = 48 MHz USB clock */

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure clocks */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK |
                                RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;  /* APB1 = 42 MHz */
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;  /* APB2 = 84 MHz */

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }

  /* Enable Flash prefetch */
  __HAL_FLASH_PREFETCH_BUFFER_ENABLE();
}

/**
  * @brief Initialize LED on PA13
  */
static void LED_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  LED_GPIO_CLK_ENABLE();

  /* Configure PA13 as output push-pull */
  GPIO_InitStruct.Pin = LED_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);

  /* Turn LED off initially */
  HAL_GPIO_WritePin(LED_GPIO_PORT, LED_PIN, GPIO_PIN_RESET);
}

/**
  * @brief Initialize TIM2 for LED blink (500ms period)
  */
static void TIM2_Init(void)
{
  __HAL_RCC_TIM2_CLK_ENABLE();

  /* TIM2 is on APB1 (42 MHz, timer runs at 84 MHz due to x2 multiplier) */
  htim2.Instance = TIM2;
  htim2.Init.Prescaler = 8400 - 1;     /* 84 MHz / 8400 = 10 kHz */
  htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim2.Init.Period = 5000 - 1;        /* 10 kHz / 5000 = 2 Hz (500ms) */
  htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;

  if (HAL_TIM_Base_Init(&htim2) != HAL_OK)
  {
    Error_Handler();
  }

  /* Enable TIM2 interrupt */
  HAL_NVIC_SetPriority(TIM2_IRQn, 5, 0);
  HAL_NVIC_EnableIRQ(TIM2_IRQn);

  /* Start timer with interrupt */
  HAL_TIM_Base_Start_IT(&htim2);
}

/**
  * @brief TIM2 period elapsed callback - toggle LED
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    HAL_GPIO_TogglePin(LED_GPIO_PORT, LED_PIN);
  }
}

/**
  * @brief Error handler
  */
void Error_Handler(void)
{
  __disable_irq();
  while (1)
  {
  }
}
