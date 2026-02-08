/**
 * FreeRTOS Multi-Task Blinky Example
 *
 * This example demonstrates FreeRTOS task management on STM32F405.
 * It creates two tasks that blink different LEDs at different rates.
 *
 * Tasks:
 *   - Task1: Blinks LED on PA5 at 500ms
 *   - Task2: Blinks LED on PA6 at 200ms
 *
 * For MCUemu testing, the task execution and GPIO writes can be validated.
 *
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "FreeRTOS.h"
#include "task.h"
#include "semphr.h"
#include <stdint.h>

/* STM32F4 Register Definitions (minimal, no HAL) */
#define RCC_BASE        0x40023800
#define RCC_AHB1ENR     (*(volatile uint32_t *)(RCC_BASE + 0x30))

#define GPIOA_BASE      0x40020000
#define GPIOA_MODER     (*(volatile uint32_t *)(GPIOA_BASE + 0x00))
#define GPIOA_ODR       (*(volatile uint32_t *)(GPIOA_BASE + 0x14))
#define GPIOA_BSRR      (*(volatile uint32_t *)(GPIOA_BASE + 0x18))

/* LED Pins */
#define LED1_PIN        5   /* PA5 */
#define LED2_PIN        6   /* PA6 */

/* MCUemu test interface */
#define MCUEMU_TEST_BASE    0x4000F000
#define MCUEMU_TEST_STATUS  (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x00))
#define MCUEMU_TEST_DATA    (*(volatile uint32_t *)(MCUEMU_TEST_BASE + 0x04))

#define TEST_STATUS_RUNNING     0x01
#define TEST_STATUS_PASS        0x02
#define TEST_STATUS_FAIL        0x03

/* Task counters for testing */
static volatile uint32_t task1_count = 0;
static volatile uint32_t task2_count = 0;

/* Semaphore for test completion */
static SemaphoreHandle_t test_complete_sem;

/**
 * Task 1: Blink LED1 at 500ms rate
 */
static void Task1_LED(void *pvParameters)
{
    const uint32_t max_blinks = 5;
    (void)pvParameters;

    while (task1_count < max_blinks)
    {
        /* Toggle LED1 */
        GPIOA_ODR ^= (1 << LED1_PIN);
        task1_count++;

        /* Update test data */
        MCUEMU_TEST_DATA = (task1_count << 16) | task2_count;

        vTaskDelay(pdMS_TO_TICKS(500));
    }

    /* Signal completion */
    xSemaphoreGive(test_complete_sem);

    /* Delete self */
    vTaskDelete(NULL);
}

/**
 * Task 2: Blink LED2 at 200ms rate
 */
static void Task2_LED(void *pvParameters)
{
    const uint32_t max_blinks = 10;
    (void)pvParameters;

    while (task2_count < max_blinks)
    {
        /* Toggle LED2 */
        GPIOA_ODR ^= (1 << LED2_PIN);
        task2_count++;

        /* Update test data */
        MCUEMU_TEST_DATA = (task1_count << 16) | task2_count;

        vTaskDelay(pdMS_TO_TICKS(200));
    }

    /* Signal completion */
    xSemaphoreGive(test_complete_sem);

    /* Delete self */
    vTaskDelete(NULL);
}

/**
 * Monitor Task: Check for test completion
 */
static void TaskMonitor(void *pvParameters)
{
    (void)pvParameters;

    /* Wait for both tasks to complete */
    xSemaphoreTake(test_complete_sem, portMAX_DELAY);
    xSemaphoreTake(test_complete_sem, portMAX_DELAY);

    /* Check results */
    if (task1_count >= 5 && task2_count >= 10) {
        MCUEMU_TEST_STATUS = TEST_STATUS_PASS;
    } else {
        MCUEMU_TEST_STATUS = TEST_STATUS_FAIL;
    }

    /* Halt */
    while (1) {
        vTaskDelay(portMAX_DELAY);
    }
}

/**
 * Hardware initialization
 */
static void HW_Init(void)
{
    /* Enable GPIOA clock */
    RCC_AHB1ENR |= (1 << 0);

    /* Configure PA5, PA6 as output */
    GPIOA_MODER &= ~((3 << (LED1_PIN * 2)) | (3 << (LED2_PIN * 2)));
    GPIOA_MODER |= (1 << (LED1_PIN * 2)) | (1 << (LED2_PIN * 2));

    /* LEDs off */
    GPIOA_BSRR = (1 << (LED1_PIN + 16)) | (1 << (LED2_PIN + 16));
}

/**
 * Main entry point
 */
int main(void)
{
    /* Initialize hardware */
    HW_Init();

    /* Signal test start */
    MCUEMU_TEST_STATUS = TEST_STATUS_RUNNING;
    MCUEMU_TEST_DATA = 0;

    /* Create semaphore */
    test_complete_sem = xSemaphoreCreateCounting(2, 0);

    /* Create tasks */
    xTaskCreate(Task1_LED, "LED1", 128, NULL, 2, NULL);
    xTaskCreate(Task2_LED, "LED2", 128, NULL, 2, NULL);
    xTaskCreate(TaskMonitor, "Monitor", 128, NULL, 1, NULL);

    /* Start scheduler */
    vTaskStartScheduler();

    /* Should never reach here */
    while (1);

    return 0;
}

/* FreeRTOS hooks */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName)
{
    (void)xTask;
    (void)pcTaskName;
    MCUEMU_TEST_STATUS = TEST_STATUS_FAIL;
    while (1);
}

void vApplicationMallocFailedHook(void)
{
    MCUEMU_TEST_STATUS = TEST_STATUS_FAIL;
    while (1);
}
