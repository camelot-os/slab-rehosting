/**
  * USB CDC Interface - Echo Mode
  * Sends "helloworld\n\r" then echoes received data
  */
#include "main.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"

#define APP_RX_DATA_SIZE  512
#define APP_TX_DATA_SIZE  512

/* Line coding structure */
USBD_CDC_LineCodingTypeDef LineCoding = {
  115200,   /* baud rate */
  0x00,     /* stop bits: 1 */
  0x00,     /* parity: none */
  0x08      /* data bits: 8 */
};

uint8_t UserRxBuffer[APP_RX_DATA_SIZE];
uint8_t UserTxBuffer[APP_TX_DATA_SIZE];

extern USBD_HandleTypeDef USBD_Device;
extern volatile uint8_t usb_ready;

/* Function prototypes */
static int8_t CDC_Init(void);
static int8_t CDC_DeInit(void);
static int8_t CDC_Control(uint8_t cmd, uint8_t *pbuf, uint16_t length);
static int8_t CDC_Receive(uint8_t *pbuf, uint32_t *Len);
static int8_t CDC_TransmitCplt(uint8_t *pbuf, uint32_t *Len, uint8_t epnum);

USBD_CDC_ItfTypeDef USBD_Interface_fops_FS = {
  CDC_Init,
  CDC_DeInit,
  CDC_Control,
  CDC_Receive,
  CDC_TransmitCplt
};

/**
  * @brief  CDC interface initialization
  */
static int8_t CDC_Init(void)
{
  USBD_CDC_SetTxBuffer(&USBD_Device, UserTxBuffer, 0);
  USBD_CDC_SetRxBuffer(&USBD_Device, UserRxBuffer);
  usb_ready = 1;
  return USBD_OK;
}

/**
  * @brief  CDC interface de-initialization
  */
static int8_t CDC_DeInit(void)
{
  usb_ready = 0;
  return USBD_OK;
}

/**
  * @brief  Handle CDC class requests
  */
static int8_t CDC_Control(uint8_t cmd, uint8_t *pbuf, uint16_t length)
{
  (void)length;

  switch (cmd)
  {
    case CDC_SEND_ENCAPSULATED_COMMAND:
      break;

    case CDC_GET_ENCAPSULATED_RESPONSE:
      break;

    case CDC_SET_COMM_FEATURE:
      break;

    case CDC_GET_COMM_FEATURE:
      break;

    case CDC_CLEAR_COMM_FEATURE:
      break;

    case CDC_SET_LINE_CODING:
      LineCoding.bitrate    = (uint32_t)(pbuf[0] | (pbuf[1] << 8) |
                              (pbuf[2] << 16) | (pbuf[3] << 24));
      LineCoding.format     = pbuf[4];
      LineCoding.paritytype = pbuf[5];
      LineCoding.datatype   = pbuf[6];
      break;

    case CDC_GET_LINE_CODING:
      pbuf[0] = (uint8_t)(LineCoding.bitrate);
      pbuf[1] = (uint8_t)(LineCoding.bitrate >> 8);
      pbuf[2] = (uint8_t)(LineCoding.bitrate >> 16);
      pbuf[3] = (uint8_t)(LineCoding.bitrate >> 24);
      pbuf[4] = LineCoding.format;
      pbuf[5] = LineCoding.paritytype;
      pbuf[6] = LineCoding.datatype;
      break;

    case CDC_SET_CONTROL_LINE_STATE:
      break;

    case CDC_SEND_BREAK:
      break;

    default:
      break;
  }

  return USBD_OK;
}

/**
  * @brief  Data received over USB - ECHO it back
  */
static int8_t CDC_Receive(uint8_t *Buf, uint32_t *Len)
{
  /* Echo received data back */
  USBD_CDC_SetTxBuffer(&USBD_Device, Buf, (uint16_t)*Len);
  USBD_CDC_TransmitPacket(&USBD_Device);

  /* Prepare for next reception */
  USBD_CDC_SetRxBuffer(&USBD_Device, UserRxBuffer);
  USBD_CDC_ReceivePacket(&USBD_Device);

  return USBD_OK;
}

/**
  * @brief  Transmit complete callback
  */
static int8_t CDC_TransmitCplt(uint8_t *pbuf, uint32_t *Len, uint8_t epnum)
{
  (void)pbuf;
  (void)Len;
  (void)epnum;
  return USBD_OK;
}

/**
  * @brief  CDC Transmit function (public API)
  */
uint8_t CDC_Transmit_FS(uint8_t *Buf, uint16_t Len)
{
  USBD_CDC_HandleTypeDef *hcdc;

  if (USBD_Device.pClassData == NULL)
  {
    return USBD_FAIL;
  }

  hcdc = (USBD_CDC_HandleTypeDef*)USBD_Device.pClassData;

  if (hcdc->TxState != 0)
  {
    return USBD_BUSY;
  }

  USBD_CDC_SetTxBuffer(&USBD_Device, Buf, Len);
  return USBD_CDC_TransmitPacket(&USBD_Device);
}
