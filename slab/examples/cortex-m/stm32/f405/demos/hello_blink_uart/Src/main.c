/**
  * STM32F405 UART Demo
  * - Sends "helloworld\r\n" on startup
  * - UART echo mode (echoes received data)
  * - Blinks LED on PA13
  *
  * For MCUemu proxy benchmarking (no USB OTG dependencies)
  */
#include "main.h"

UART_HandleTypeDef huart2;
TIM_HandleTypeDef htim2;

static void SystemClock_Config(void);
static void LED_Init(void);
static void TIM2_Init(void);
static void USART2_Init(void);

volatile uint32_t led_toggle_count = 0;
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

  /* Initialize USART2 */
  USART2_Init();

  /* Mark test as running */
  MCUEMU_TEST_STATUS = TEST_STATUS_RUNNING;

  /* Send hello message */
  const char *msg = "helloworld\r\n";
  HAL_UART_Transmit(&huart2, (uint8_t*)msg, 12, HAL_MAX_DELAY);
  hello_sent = 1;

  /* Main loop - UART echo */
  uint8_t rx_byte;
  while (1)
  {
    /* Echo any received data */
    if (HAL_UART_Receive(&huart2, &rx_byte, 1, 10) == HAL_OK)
    {
      HAL_UART_Transmit(&huart2, &rx_byte, 1, HAL_MAX_DELAY);
    }

    /* Check if test should complete (10 LED toggles) */
    if (led_toggle_count >= 10)
    {
      MCUEMU_TEST_STATUS = TEST_STATUS_PASS;
      MCUEMU_TEST_DATA = led_toggle_count;
      break;
    }
  }

  /* Idle loop */
  while (1)
  {
    __WFI();
  }
}

/**
  * @brief  System Clock Configuration
  *         System Clock source = PLL (HSE)
  *         SYSCLK = 168 MHz
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
  RCC_OscInitStruct.PLL.PLLQ = 7;      /* 336/7 = 48 MHz (unused) */

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
  * @brief Initialize USART2 (115200 8N1)
  */
static void USART2_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  /* Enable clocks */
  __HAL_RCC_USART2_CLK_ENABLE();
  USART_GPIO_CLK_ENABLE();

  /* Configure PA2 (TX) and PA3 (RX) as alternate function */
  GPIO_InitStruct.Pin = USART_TX_PIN | USART_RX_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  GPIO_InitStruct.Alternate = GPIO_AF7_USART2;
  HAL_GPIO_Init(USART_GPIO_PORT, &GPIO_InitStruct);

  /* Configure USART2 */
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
}

/**
  * @brief TIM2 period elapsed callback - toggle LED
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  if (htim->Instance == TIM2)
  {
    HAL_GPIO_TogglePin(LED_GPIO_PORT, LED_PIN);
    led_toggle_count++;
  }
}

/**
  * @brief Error handler
  */
void Error_Handler(void)
{
  MCUEMU_TEST_STATUS = TEST_STATUS_FAIL;
  __disable_irq();
  while (1)
  {
  }
}
