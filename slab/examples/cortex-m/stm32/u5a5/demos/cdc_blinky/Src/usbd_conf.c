/**
  * USB Device BSP for STM32U5A5 (DWC2 OTG HS)
  *
  * PCD handle uses USB_OTG_HS instance (0x42040000).
  * Endpoint FIFOs are configured for CDC ACM operation.
  *
  * Based on STM32CubeU5 CDC_Standalone template.
  * Copyright (c) 2021-2023 STMicroelectronics. (original template)
  * Copyright (C) 2026 Twisted Wires Security Lab. (adaptation)
  */
#include "main.h"
#include "stm32u5xx.h"
#include "stm32u5xx_hal.h"
#include "usbd_def.h"
#include "usbd_core.h"
#include "usbd_cdc.h"

PCD_HandleTypeDef hpcd;

static USBD_StatusTypeDef USBD_Get_USB_Status(HAL_StatusTypeDef hal_status);

/*******************************************************************************
                       LL Driver Callbacks (PCD -> USB Device Library)
*******************************************************************************/

void HAL_PCD_MspInit(PCD_HandleTypeDef *pcdHandle)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  if (pcdHandle->Instance == USB_OTG_HS)
  {
    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* PA11 = USB_DM, PA12 = USB_DP */
    GPIO_InitStruct.Pin = GPIO_PIN_11 | GPIO_PIN_12;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF10_USB;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    /* Enable USB OTG HS clock */
    __HAL_RCC_USB_OTG_HS_CLK_ENABLE();

    /* Enable USB power (VDDUSB) */
    HAL_PWREx_EnableVddUSB();

    HAL_NVIC_SetPriority(OTG_HS_IRQn, 6, 0);
    HAL_NVIC_EnableIRQ(OTG_HS_IRQn);
  }
}

void HAL_PCD_MspDeInit(PCD_HandleTypeDef *pcdHandle)
{
  if (pcdHandle->Instance == USB_OTG_HS)
  {
    __HAL_RCC_USB_OTG_HS_CLK_DISABLE();
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_11 | GPIO_PIN_12);
    HAL_NVIC_DisableIRQ(OTG_HS_IRQn);
  }
}

void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_LL_SetupStage((USBD_HandleTypeDef *)hpcd->pData,
                      (uint8_t *)hpcd->Setup);
}

void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
  USBD_LL_DataOutStage((USBD_HandleTypeDef *)hpcd->pData,
                        epnum, hpcd->OUT_ep[epnum].xfer_buff);
}

void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
  USBD_LL_DataInStage((USBD_HandleTypeDef *)hpcd->pData,
                       epnum, hpcd->IN_ep[epnum].xfer_buff);
}

void HAL_PCD_SOFCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_LL_SOF((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_ResetCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_SpeedTypeDef speed = USBD_SPEED_FULL;

  if (hpcd->Init.speed != PCD_SPEED_FULL)
  {
    Error_Handler();
  }

  USBD_LL_SetSpeed((USBD_HandleTypeDef *)hpcd->pData, speed);
  USBD_LL_Reset((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_SuspendCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_LL_Suspend((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_ResumeCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_LL_Resume((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_ISOOUTIncompleteCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
  USBD_LL_IsoOUTIncomplete((USBD_HandleTypeDef *)hpcd->pData, epnum);
}

void HAL_PCD_ISOINIncompleteCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
  USBD_LL_IsoINIncomplete((USBD_HandleTypeDef *)hpcd->pData, epnum);
}

void HAL_PCD_ConnectCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_LL_DevConnected((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_DisconnectCallback(PCD_HandleTypeDef *hpcd)
{
  USBD_LL_DevDisconnected((USBD_HandleTypeDef *)hpcd->pData);
}

/*******************************************************************************
                       LL Driver Interface (USB Device Library --> PCD)
*******************************************************************************/

USBD_StatusTypeDef USBD_LL_Init(USBD_HandleTypeDef *pdev)
{
  hpcd.pData = pdev;
  pdev->pData = &hpcd;

  hpcd.Instance = USB_OTG_HS;
  hpcd.Init.dev_endpoints = 6;
  hpcd.Init.use_dedicated_ep1 = 0;
  hpcd.Init.dma_enable = 0;
  hpcd.Init.low_power_enable = 0;
  hpcd.Init.phy_itface = PCD_PHY_EMBEDDED;
  hpcd.Init.Sof_enable = DISABLE;
  hpcd.Init.speed = PCD_SPEED_FULL;
  hpcd.Init.vbus_sensing_enable = 0;
  hpcd.Init.lpm_enable = DISABLE;
  hpcd.Init.battery_charging_enable = DISABLE;

  if (HAL_PCD_Init(&hpcd) != HAL_OK)
  {
    Error_Handler();
  }

  /* Configure RX/TX FIFOs for DWC2 OTG HS */
  HAL_PCDEx_SetRxFiFo(&hpcd, 0x80);
  HAL_PCDEx_SetTxFiFo(&hpcd, 0, 0x40);
  HAL_PCDEx_SetTxFiFo(&hpcd, 1, 0x80);

  return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_DeInit(USBD_HandleTypeDef *pdev)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_DeInit(pdev->pData);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_Start(USBD_HandleTypeDef *pdev)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_Start(pdev->pData);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_Stop(USBD_HandleTypeDef *pdev)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_Stop(pdev->pData);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_OpenEP(USBD_HandleTypeDef *pdev,
                                   uint8_t ep_addr, uint8_t ep_type,
                                   uint16_t ep_mps)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_Open(pdev->pData, ep_addr,
                                                  ep_mps, ep_type);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_CloseEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_Close(pdev->pData, ep_addr);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_FlushEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_Flush(pdev->pData, ep_addr);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_StallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_SetStall(pdev->pData, ep_addr);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_ClearStallEP(USBD_HandleTypeDef *pdev,
                                         uint8_t ep_addr)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_ClrStall(pdev->pData, ep_addr);
  return USBD_Get_USB_Status(hal_status);
}

uint8_t USBD_LL_IsStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
  PCD_HandleTypeDef *hpcd = (PCD_HandleTypeDef *)pdev->pData;

  if ((ep_addr & 0x80) == 0x80)
  {
    return hpcd->IN_ep[ep_addr & 0x7F].is_stall;
  }
  else
  {
    return hpcd->OUT_ep[ep_addr & 0x7F].is_stall;
  }
}

USBD_StatusTypeDef USBD_LL_SetUSBAddress(USBD_HandleTypeDef *pdev,
                                          uint8_t dev_addr)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_SetAddress(pdev->pData, dev_addr);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_Transmit(USBD_HandleTypeDef *pdev,
                                     uint8_t ep_addr,
                                     uint8_t *pbuf, uint32_t size)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_Transmit(pdev->pData, ep_addr,
                                                      pbuf, size);
  return USBD_Get_USB_Status(hal_status);
}

USBD_StatusTypeDef USBD_LL_PrepareReceive(USBD_HandleTypeDef *pdev,
                                           uint8_t ep_addr,
                                           uint8_t *pbuf, uint32_t size)
{
  HAL_StatusTypeDef hal_status = HAL_PCD_EP_Receive(pdev->pData, ep_addr,
                                                     pbuf, size);
  return USBD_Get_USB_Status(hal_status);
}

uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
  return HAL_PCD_EP_GetRxCount((PCD_HandleTypeDef *)pdev->pData, ep_addr);
}

void USBD_LL_Delay(uint32_t Delay)
{
  HAL_Delay(Delay);
}

void *USBD_static_malloc(uint32_t size)
{
  UNUSED(size);
  static uint32_t mem[(sizeof(USBD_CDC_HandleTypeDef) / 4) + 1];
  return mem;
}

void USBD_static_free(void *p)
{
  UNUSED(p);
}

static USBD_StatusTypeDef USBD_Get_USB_Status(HAL_StatusTypeDef hal_status)
{
  switch (hal_status)
  {
    case HAL_OK:      return USBD_OK;
    case HAL_BUSY:    return USBD_BUSY;
    case HAL_ERROR:
    case HAL_TIMEOUT:
    default:          return USBD_FAIL;
  }
}
