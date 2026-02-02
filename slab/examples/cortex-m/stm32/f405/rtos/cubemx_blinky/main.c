/**
 * STM32F405 Blinky Example using HAL
 *
 * This example demonstrates GPIO control using STM32 HAL library.
 * It blinks an LED on PA5 (typical for Nucleo boards).
 *
 * For MCUemu testing, the GPIO writes are captured by the peripheral
 * server and can be validated.
 *
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "stm32f4xx_hal.h"

/* LED Pin Definition */
#define LED_PIN         GPIO_PIN_5
#define LED_GPIO_PORT   GPIOA

/* MCUemu test interface */
#define MCUEMU_TEST_BASE    0x4000F000
#define MCUEMU_TEST_STATUS  (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x00))
#define MCUEMU_TEST_DATA    (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x04))
#define MCUEMU_TEST_CMD     (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x08))

#define TEST_STATUS_RUNNING     0x01
#define TEST_STATUS_PASS        0x02
#define TEST_STATUS_FAIL        0x03

/* System Clock Configuration */
static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

    /* Configure the main internal regulator output voltage */
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    /* Initialize HSE Oscillator */
    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    RCC_OscInitStruct.HSEState = RCC_HSE_ON;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
    RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    RCC_OscInitStruct.PLL.PLLM = 8;
    RCC_OscInitStruct.PLL.PLLN = 336;
    RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
    RCC_OscInitStruct.PLL.PLLQ = 7;
    HAL_RCC_OscConfig(&RCC_OscInitStruct);

    /* Initialize CPU, AHB and APB clocks */
    RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                                | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;
    RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;
    HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5);
}

/* GPIO Initialization */
static void GPIO_Init(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    /* Enable GPIOA clock */
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* Configure LED pin as output */
    GPIO_InitStruct.Pin = LED_PIN;
    GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(LED_GPIO_PORT, &GPIO_InitStruct);

    /* Start with LED off */
    HAL_GPIO_WritePin(LED_GPIO_PORT, LED_PIN, GPIO_PIN_RESET);
}

int main(void)
{
    uint32_t toggle_count = 0;
    const uint32_t max_toggles = 10;  /* For testing */

    /* Initialize HAL */
    HAL_Init();

    /* Configure system clock */
    SystemClock_Config();

    /* Initialize GPIO */
    GPIO_Init();

    /* Signal test start */
    MCUEMU_TEST_STATUS = TEST_STATUS_RUNNING;
    MCUEMU_TEST_DATA = 0;

    /* Main loop - blink LED */
    while (toggle_count < max_toggles)
    {
        /* Toggle LED */
        HAL_GPIO_TogglePin(LED_GPIO_PORT, LED_PIN);
        toggle_count++;

        /* Record toggle count for test validation */
        MCUEMU_TEST_DATA = toggle_count;

        /* Delay (simplified for emulation) */
        for (volatile int i = 0; i < 100000; i++);
    }

    /* Test complete */
    if (toggle_count == max_toggles) {
        MCUEMU_TEST_STATUS = TEST_STATUS_PASS;
    } else {
        MCUEMU_TEST_STATUS = TEST_STATUS_FAIL;
    }

    /* Infinite loop */
    while (1) {
        __WFI();
    }

    return 0;
}

/* HAL requires this for timing */
void SysTick_Handler(void)
{
    HAL_IncTick();
}

/* Error handler */
void Error_Handler(void)
{
    MCUEMU_TEST_STATUS = TEST_STATUS_FAIL;
    while (1) {
        __WFI();
    }
}
