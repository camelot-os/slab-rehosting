/**
  * USB Device initialization for STM32U5A5
  *
  * - Configures HSI48 (48 MHz) as USB clock source via CRS
  * - Initializes USB Device core + CDC class
  * - Provides usb_send_hello() for initial "helloworld" message
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include "usbd_core.h"
#include "usbd_desc.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"
#include "usb_device.h"

USBD_HandleTypeDef USBD_Device;

/**
  * Configure USB 48 MHz clock from HSI48 + CRS
  *
  * HSI48 is the internal 48 MHz RC oscillator. CRS (Clock Recovery System)
  * auto-calibrates HSI48 against USB SOF frames for precise 48 MHz.
  */
void USBD_Clock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
  RCC_CRSInitTypeDef RCC_CRSInitStruct = {0};

  /* Enable HSI48 oscillator */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI48;
  RCC_OscInitStruct.HSI48State = RCC_HSI48_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Select HSI48 as ICLK source (USB uses ICLK on U5 series) */
  PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_ICLK;
  PeriphClkInitStruct.IclkClockSelection = RCC_ICLK_CLKSOURCE_HSI48;
  if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure CRS (Clock Recovery System) for HSI48 auto-calibration
   * against USB SOF (1 kHz) */
  __HAL_RCC_CRS_CLK_ENABLE();

  RCC_CRSInitStruct.Prescaler = RCC_CRS_SYNC_DIV1;
  RCC_CRSInitStruct.Source = RCC_CRS_SYNC_SOURCE_USB;
  RCC_CRSInitStruct.Polarity = RCC_CRS_SYNC_POLARITY_RISING;
  RCC_CRSInitStruct.ReloadValue = __HAL_RCC_CRS_RELOADVALUE_CALCULATE(48000000, 1000);
  RCC_CRSInitStruct.ErrorLimitValue = 34;
  RCC_CRSInitStruct.HSI48CalibrationValue = 32;
  HAL_RCCEx_CRSConfig(&RCC_CRSInitStruct);
}

/**
  * Initialize USB Device stack (CDC class)
  */
void MX_USB_Device_Init(void)
{
  USBD_Clock_Config();

  USBD_Init(&USBD_Device, &CDC_Desc, DEVICE_FS);
  USBD_RegisterClass(&USBD_Device, &USBD_CDC);
  USBD_CDC_RegisterInterface(&USBD_Device, &USBD_Interface_fops_FS);
  USBD_Start(&USBD_Device);
}

/**
  * Send "helloworld\n\r" over USB CDC
  */
void usb_send_hello(void)
{
  static uint8_t msg[] = "helloworld\n\r";
  CDC_Transmit_FS(msg, sizeof(msg) - 1);
}
