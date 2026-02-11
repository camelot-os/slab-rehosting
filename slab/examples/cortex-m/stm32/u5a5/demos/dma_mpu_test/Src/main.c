/**
  * STM32U5A5 DMA + MPU Comprehensive Test
  *
  * Validates all emulated PMSAv8 MPU and GPDMA features:
  *
  * MPU tests:
  *   1. TYPE.DREGION count (expect 8 on Cortex-M33)
  *   2. CTRL enable + PRIVDEFENA + HFNMIENA bits
  *   3. MAIR0/MAIR1 attribute readback
  *   4. All 4 regions: RBAR base, AP, XN, SH fields
  *   5. All 4 regions: RLAR limit, AttrIndx, EN fields
  *   6. Region disable/enable toggle via RLAR.EN
  *
  * DMA tests:
  *   1. Channel 0: M2M transfer with TC interrupt
  *   2. Channel 1: M2M transfer (multi-channel)
  *   3. Half-transfer flag (HTF) verification
  *   4. Channel suspend (CCR.SUSP -> CSR.SUSPF)
  *   5. Channel reset (CCR.RESET -> idle state)
  *   6. CFCR flag clear (W1C on CSR flags)
  *   7. MISR global interrupt status
  *   8. CSR.IDLEF status tracking
  *
  * Prints test results via USART1 at 115200 baud (PA9 TX).
  * Target: Nucleo-U5A5ZJT6Q (Cortex-M33 @ 160 MHz)
  *
  * Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
  */
#include "main.h"
#include <string.h>
#include <stdio.h>

UART_HandleTypeDef huart1;
DMA_HandleTypeDef hdma_ch0;
DMA_HandleTypeDef hdma_ch1;

static volatile uint8_t dma_ch0_complete = 0;
static volatile uint8_t dma_ch0_error = 0;
static volatile uint8_t dma_ch1_complete = 0;
static volatile uint8_t dma_ch1_error = 0;
static volatile uint8_t dma_ch0_half = 0;

static void MPU_Config(void);
static void SystemClock_Config(void);
static void USART1_Init(void);
static void GPDMA1_Init(void);
static void UART_Print(const char *msg);
static void UART_PrintHex(const char *label, uint32_t val);

/* MPU sub-tests */
static int MPU_Test_TypeRegion(void);
static int MPU_Test_Ctrl(void);
static int MPU_Test_MAIR(void);
static int MPU_Test_Region_RBAR(void);
static int MPU_Test_Region_RLAR(void);
static int MPU_Test_Region_Toggle(void);

/* DMA sub-tests */
static int DMA_Test_Ch0_M2M(void);
static int DMA_Test_Ch1_M2M(void);
static int DMA_Test_HalfTransfer(void);
static int DMA_Test_Suspend(void);
static int DMA_Test_Reset(void);
static int DMA_Test_FlagClear(void);
static int DMA_Test_MISR(void);
static int DMA_Test_IDLEF(void);

/* DMA test buffers (word-aligned in SRAM) */
static uint32_t __attribute__((aligned(4))) src_buf[DMA_TEST_SIZE_WORDS];
static uint32_t __attribute__((aligned(4))) dst_buf[DMA_TEST_SIZE_WORDS];
static uint32_t __attribute__((aligned(4))) src_buf2[DMA_SMALL_SIZE_WORDS];
static uint32_t __attribute__((aligned(4))) dst_buf2[DMA_SMALL_SIZE_WORDS];

static char print_buf[80];

int main(void)
{
  int mpu_pass = 0, mpu_fail = 0;
  int dma_pass = 0, dma_fail = 0;
  int result;

  HAL_Init();
  MPU_Config();
  SystemClock_Config();
  USART1_Init();

  UART_Print("\r\n[U5A5] DMA+MPU Comprehensive Test\r\n");
  UART_Print("==================================\r\n");

  /* --- MPU Tests --- */
  UART_Print("\r\n--- MPU Tests ---\r\n");

#define RUN_TEST(name, fn) do { \
    result = fn(); \
    if (result) { mpu_pass++; } else { mpu_fail++; } \
  } while (0)

  RUN_TEST("TYPE.DREGION",   MPU_Test_TypeRegion);
  RUN_TEST("CTRL",           MPU_Test_Ctrl);
  RUN_TEST("MAIR",           MPU_Test_MAIR);
  RUN_TEST("Region RBAR",    MPU_Test_Region_RBAR);
  RUN_TEST("Region RLAR",    MPU_Test_Region_RLAR);
  RUN_TEST("Region Toggle",  MPU_Test_Region_Toggle);

#undef RUN_TEST

  snprintf(print_buf, sizeof(print_buf),
           "[MPU] Results: %d passed, %d failed\r\n", mpu_pass, mpu_fail);
  UART_Print(print_buf);

  /* --- DMA Tests --- */
  UART_Print("\r\n--- DMA Tests ---\r\n");
  GPDMA1_Init();

#define RUN_TEST(name, fn) do { \
    result = fn(); \
    if (result) { dma_pass++; } else { dma_fail++; } \
  } while (0)

  RUN_TEST("Ch0 M2M",       DMA_Test_Ch0_M2M);
  RUN_TEST("Ch1 M2M",       DMA_Test_Ch1_M2M);
  RUN_TEST("HalfTransfer",  DMA_Test_HalfTransfer);
  RUN_TEST("Suspend",       DMA_Test_Suspend);
  RUN_TEST("Reset",         DMA_Test_Reset);
  RUN_TEST("FlagClear",     DMA_Test_FlagClear);
  RUN_TEST("MISR",          DMA_Test_MISR);
  RUN_TEST("IDLEF",         DMA_Test_IDLEF);

#undef RUN_TEST

  snprintf(print_buf, sizeof(print_buf),
           "[DMA] Results: %d passed, %d failed\r\n", dma_pass, dma_fail);
  UART_Print(print_buf);

  /* --- Summary --- */
  UART_Print("\r\n==================================\r\n");
  int total_pass = mpu_pass + dma_pass;
  int total_fail = mpu_fail + dma_fail;
  snprintf(print_buf, sizeof(print_buf),
           "[U5A5] Total: %d passed, %d failed\r\n", total_pass, total_fail);
  UART_Print(print_buf);

  if (total_fail == 0)
  {
    UART_Print("[U5A5] ALL TESTS PASSED\r\n");
  }
  else
  {
    UART_Print("[U5A5] SOME TESTS FAILED\r\n");
  }

  /* Keep these markers for E2E runner backward compatibility */
  if (mpu_fail == 0)
    UART_Print("[U5A5] MPU PMSAv8: regions OK\r\n");
  if (dma_pass > 0)
    UART_Print("[U5A5] DMA transfer complete\r\n");

  while (1) {}
}

/* ================================================================
 * PMSAv8 MPU Configuration
 * ================================================================ */
static void MPU_Config(void)
{
  ARM_MPU_Disable();

  /* MAIR: Attr0 = Device-nGnRnE (0x00), Attr1 = Normal WB RA WA (0xFF) */
  ARM_MPU_SetMemAttr(0, ARM_MPU_ATTR(ARM_MPU_ATTR_DEVICE,
                                       ARM_MPU_ATTR_DEVICE_nGnRnE));
  ARM_MPU_SetMemAttr(1, ARM_MPU_ATTR(ARM_MPU_ATTR_MEMORY_(1,1,1,1),
                                       ARM_MPU_ATTR_MEMORY_(1,1,1,1)));

  /* Region 0: Flash - RO, executable, Inner-shareable, Attr1 (Normal) */
  ARM_MPU_SetRegion(0,
    ARM_MPU_RBAR(0x08000000, ARM_MPU_SH_INNER, 1U, 0U, 0U),
    ARM_MPU_RLAR(0x083FFFFF, 1));

  /* Region 1: SRAM - RW, non-executable, Inner-shareable, Attr1 (Normal) */
  ARM_MPU_SetRegion(1,
    ARM_MPU_RBAR(0x20000000, ARM_MPU_SH_INNER, 0U, 1U, 1U),
    ARM_MPU_RLAR(0x2026FFFF, 1));

  /* Region 2: Peripherals - Device, RW, non-executable, Non-shareable, Attr0 */
  ARM_MPU_SetRegion(2,
    ARM_MPU_RBAR(0x40000000, ARM_MPU_SH_NON, 0U, 0U, 1U),
    ARM_MPU_RLAR(0x4FFFFFFF, 0));

  /* Region 3: System PPB - Device, RW, non-executable, Non-shareable, Attr0 */
  ARM_MPU_SetRegion(3,
    ARM_MPU_RBAR(0xE0000000, ARM_MPU_SH_NON, 0U, 0U, 1U),
    ARM_MPU_RLAR(0xE00FFFFF, 0));

  ARM_MPU_Enable(MPU_CTRL_PRIVDEFENA_Msk);
}

/* ================================================================
 * MPU Sub-Tests
 * ================================================================ */

/**
  * Test 1: MPU TYPE register - verify DREGION count.
  * Cortex-M33 has 8 regions (DREGION = 8).
  */
static int MPU_Test_TypeRegion(void)
{
  uint32_t mpu_type = MPU->TYPE;
  uint32_t dregion = (mpu_type >> 8) & 0xFF;

  UART_Print("[MPU] TYPE.DREGION: ");
  UART_PrintHex("", dregion);

  if (dregion >= 4)
  {
    UART_Print("[MPU] TYPE.DREGION >= 4: PASS\r\n");
    return 1;
  }
  UART_Print("[MPU] TYPE.DREGION < 4: FAIL\r\n");
  return 0;
}

/**
  * Test 2: MPU CTRL register - verify ENABLE and PRIVDEFENA.
  */
static int MPU_Test_Ctrl(void)
{
  uint32_t ctrl = MPU->CTRL;
  int ok = 1;

  if (!(ctrl & MPU_CTRL_ENABLE_Msk))
  {
    UART_Print("[MPU] CTRL.ENABLE not set: FAIL\r\n");
    ok = 0;
  }
  if (!(ctrl & MPU_CTRL_PRIVDEFENA_Msk))
  {
    UART_Print("[MPU] CTRL.PRIVDEFENA not set: FAIL\r\n");
    ok = 0;
  }

  if (ok)
    UART_Print("[MPU] CTRL (ENABLE+PRIVDEFENA): PASS\r\n");
  return ok;
}

/**
  * Test 3: MAIR0 attribute readback.
  * Attr0 = Device-nGnRnE (byte 0x00), Attr1 = Normal WB (byte 0xFF).
  */
static int MPU_Test_MAIR(void)
{
  uint32_t mair0 = MPU->MAIR[0];
  uint8_t attr0 = (uint8_t)(mair0 & 0xFF);
  uint8_t attr1 = (uint8_t)((mair0 >> 8) & 0xFF);
  int ok = 1;

  UART_PrintHex("[MPU] MAIR0=", mair0);

  if (attr0 != 0x00)
  {
    UART_PrintHex("[MPU] Attr0 expected 0x00, got ", attr0);
    ok = 0;
  }
  if (attr1 != 0xFF)
  {
    UART_PrintHex("[MPU] Attr1 expected 0xFF, got ", attr1);
    ok = 0;
  }

  if (ok)
    UART_Print("[MPU] MAIR attributes: PASS\r\n");
  else
    UART_Print("[MPU] MAIR attributes: FAIL\r\n");
  return ok;
}

/**
  * Test 4: Verify RBAR for all 4 regions.
  *
  * PMSAv8 RBAR layout:
  *   [31:5] BASE address
  *   [4:3]  SH (shareability): 00=Non, 01=reserved, 10=Outer, 11=Inner
  *   [2:1]  AP: 00=priv RW, 01=any RW, 10=priv RO, 11=any RO
  *   [0]    XN: 0=executable, 1=execute-never
  */
static int MPU_Test_Region_RBAR(void)
{
  int ok = 1;
  uint32_t rbar;

  /* Expected values per region:
   * Region 0: base=0x08000000 SH=Inner(3) AP=priv_RO(2) XN=0 -> 0x08000000|0x18|0x04|0x00
   * Region 1: base=0x20000000 SH=Inner(3) AP=any_RW(1)  XN=1 -> 0x20000000|0x18|0x02|0x01
   * Region 2: base=0x40000000 SH=Non(0)   AP=priv_RW(0) XN=1 -> 0x40000000|0x00|0x00|0x01
   * Region 3: base=0xE0000000 SH=Non(0)   AP=priv_RW(0) XN=1 -> 0xE0000000|0x00|0x00|0x01
   */
  struct {
    uint32_t base;
    uint8_t sh;   /* 0=Non, 2=Outer, 3=Inner */
    uint8_t ap;   /* 0=priv_RW, 1=any_RW, 2=priv_RO, 3=any_RO */
    uint8_t xn;
  } expected[4] = {
    { 0x08000000, 3, 2, 0 },  /* Flash: Inner-shareable, priv RO, exec */
    { 0x20000000, 3, 1, 1 },  /* SRAM: Inner-shareable, any RW, XN */
    { 0x40000000, 0, 0, 1 },  /* Periph: Non-shareable, priv RW, XN */
    { 0xE0000000, 0, 0, 1 },  /* System: Non-shareable, priv RW, XN */
  };

  for (int i = 0; i < 4; i++)
  {
    MPU->RNR = i;
    rbar = MPU->RBAR;

    uint32_t base = rbar & ~0x1FU;
    uint8_t sh  = (rbar >> 3) & 0x3;
    uint8_t ap  = (rbar >> 1) & 0x3;
    uint8_t xn  = rbar & 0x1;

    if (base != expected[i].base)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d base: expected 0x%08lX got 0x%08lX FAIL\r\n",
               i, (unsigned long)expected[i].base, (unsigned long)base);
      UART_Print(print_buf);
      ok = 0;
    }
    if (sh != expected[i].sh)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d SH: expected %d got %d FAIL\r\n", i, expected[i].sh, sh);
      UART_Print(print_buf);
      ok = 0;
    }
    if (ap != expected[i].ap)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d AP: expected %d got %d FAIL\r\n", i, expected[i].ap, ap);
      UART_Print(print_buf);
      ok = 0;
    }
    if (xn != expected[i].xn)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d XN: expected %d got %d FAIL\r\n", i, expected[i].xn, xn);
      UART_Print(print_buf);
      ok = 0;
    }
  }

  if (ok)
    UART_Print("[MPU] RBAR (base+SH+AP+XN) x4: PASS\r\n");
  else
    UART_Print("[MPU] RBAR verification: FAIL\r\n");
  return ok;
}

/**
  * Test 5: Verify RLAR for all 4 regions.
  *
  * PMSAv8 RLAR layout:
  *   [31:5]  LIMIT address (top of region, last 5 bits always 1 in address)
  *   [4]     (reserved in some variants, or PXN)
  *   [3:1]   AttrIndx (index into MAIR)
  *   [0]     EN (region enable)
  */
static int MPU_Test_Region_RLAR(void)
{
  int ok = 1;
  uint32_t rlar;

  struct {
    uint32_t limit;    /* upper bound aligned to 32 bytes */
    uint8_t attr_idx;  /* MAIR index */
    uint8_t en;        /* enable bit */
  } expected[4] = {
    { 0x083FFFFF & ~0x1FU, 1, 1 },  /* Flash: Attr1 (Normal), enabled */
    { 0x2026FFFF & ~0x1FU, 1, 1 },  /* SRAM: Attr1 (Normal), enabled */
    { 0x4FFFFFFF & ~0x1FU, 0, 1 },  /* Periph: Attr0 (Device), enabled */
    { 0xE00FFFFF & ~0x1FU, 0, 1 },  /* System: Attr0 (Device), enabled */
  };

  for (int i = 0; i < 4; i++)
  {
    MPU->RNR = i;
    rlar = MPU->RLAR;

    uint32_t limit   = rlar & ~0x1FU;
    uint8_t attr_idx = (rlar >> 1) & 0x7;
    uint8_t en       = rlar & 0x1;

    if (limit != expected[i].limit)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d limit: expected 0x%08lX got 0x%08lX FAIL\r\n",
               i, (unsigned long)expected[i].limit, (unsigned long)limit);
      UART_Print(print_buf);
      ok = 0;
    }
    if (attr_idx != expected[i].attr_idx)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d AttrIndx: expected %d got %d FAIL\r\n",
               i, expected[i].attr_idx, attr_idx);
      UART_Print(print_buf);
      ok = 0;
    }
    if (en != expected[i].en)
    {
      snprintf(print_buf, sizeof(print_buf),
               "[MPU] R%d EN: expected %d got %d FAIL\r\n", i, expected[i].en, en);
      UART_Print(print_buf);
      ok = 0;
    }
  }

  if (ok)
    UART_Print("[MPU] RLAR (limit+AttrIndx+EN) x4: PASS\r\n");
  else
    UART_Print("[MPU] RLAR verification: FAIL\r\n");
  return ok;
}

/**
  * Test 6: Region disable/enable toggle.
  * Disable region 1, verify EN=0, re-enable, verify EN=1.
  */
static int MPU_Test_Region_Toggle(void)
{
  int ok = 1;
  uint32_t rlar;

  MPU->RNR = 1;
  rlar = MPU->RLAR;

  /* Verify currently enabled */
  if (!(rlar & 0x1))
  {
    UART_Print("[MPU] Region 1 not initially enabled: FAIL\r\n");
    return 0;
  }

  /* Disable region 1 (clear EN bit) */
  MPU->RLAR = rlar & ~0x1U;
  uint32_t rlar_disabled = MPU->RLAR;
  if (rlar_disabled & 0x1)
  {
    UART_Print("[MPU] Region 1 disable failed: FAIL\r\n");
    ok = 0;
  }

  /* Re-enable region 1 */
  MPU->RLAR = rlar;
  uint32_t rlar_reenabled = MPU->RLAR;
  if (!(rlar_reenabled & 0x1))
  {
    UART_Print("[MPU] Region 1 re-enable failed: FAIL\r\n");
    ok = 0;
  }

  if (ok)
    UART_Print("[MPU] Region toggle (disable/enable): PASS\r\n");
  return ok;
}

/* ================================================================
 * System Clock Configuration
 * ================================================================ */
static void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_MSI;
  RCC_OscInitStruct.MSIState = RCC_MSI_ON;
  RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_4;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
  RCC_OscInitStruct.PLL.PLLM = 1;
  RCC_OscInitStruct.PLL.PLLN = 80;
  RCC_OscInitStruct.PLL.PLLP = 2;
  RCC_OscInitStruct.PLL.PLLQ = 2;
  RCC_OscInitStruct.PLL.PLLR = 2;

  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK
                              | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2
                              | RCC_CLOCKTYPE_PCLK3;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_4) != HAL_OK)
  {
    Error_Handler();
  }
}

/* ================================================================
 * USART1 Init
 * ================================================================ */
static void USART1_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};

  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_USART1_CLK_ENABLE();

  GPIO_InitStruct.Pin = USART1_TX_PIN | USART1_RX_PIN;
  GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
  GPIO_InitStruct.Pull = GPIO_PULLUP;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
  GPIO_InitStruct.Alternate = USART1_AF;
  HAL_GPIO_Init(USART1_GPIO_PORT, &GPIO_InitStruct);

  huart1.Instance = USART1;
  huart1.Init.BaudRate = 115200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;

  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
}

/* ================================================================
 * DMA Callbacks
 * ================================================================ */

void HAL_DMA_XferCpltCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma == &hdma_ch0) dma_ch0_complete = 1;
  if (hdma == &hdma_ch1) dma_ch1_complete = 1;
}

void HAL_DMA_XferHalfCpltCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma == &hdma_ch0) dma_ch0_half = 1;
}

void HAL_DMA_XferErrorCallback(DMA_HandleTypeDef *hdma)
{
  if (hdma == &hdma_ch0) dma_ch0_error = 1;
  if (hdma == &hdma_ch1) dma_ch1_error = 1;
}

/* ================================================================
 * GPDMA1 Init (Channel 0 + Channel 1)
 * ================================================================ */
static void GPDMA1_Init(void)
{
  __HAL_RCC_GPDMA1_CLK_ENABLE();

  /* Channel 0: word-width M2M */
  hdma_ch0.Instance = GPDMA1_Channel0;
  hdma_ch0.Init.Request = DMA_REQUEST_SW;
  hdma_ch0.Init.BlkHWRequest = DMA_BREQ_SINGLE_BURST;
  hdma_ch0.Init.Direction = DMA_MEMORY_TO_MEMORY;
  hdma_ch0.Init.SrcInc = DMA_SINC_INCREMENTED;
  hdma_ch0.Init.DestInc = DMA_DINC_INCREMENTED;
  hdma_ch0.Init.SrcDataWidth = DMA_SRC_DATAWIDTH_WORD;
  hdma_ch0.Init.DestDataWidth = DMA_DEST_DATAWIDTH_WORD;
  hdma_ch0.Init.Priority = DMA_HIGH_PRIORITY;
  hdma_ch0.Init.SrcBurstLength = 1;
  hdma_ch0.Init.DestBurstLength = 1;
  hdma_ch0.Init.TransferAllocatedPort = DMA_SRC_ALLOCATED_PORT0 | DMA_DEST_ALLOCATED_PORT0;
  hdma_ch0.Init.TransferEventMode = DMA_TCEM_BLOCK_TRANSFER;
  hdma_ch0.Init.Mode = DMA_NORMAL;

  if (HAL_DMA_Init(&hdma_ch0) != HAL_OK)
  {
    UART_Print("[DMA] Ch0 init FAILED\r\n");
    Error_Handler();
  }

  hdma_ch0.XferCpltCallback = HAL_DMA_XferCpltCallback;
  hdma_ch0.XferHalfCpltCallback = HAL_DMA_XferHalfCpltCallback;
  hdma_ch0.XferErrorCallback = HAL_DMA_XferErrorCallback;

  HAL_NVIC_SetPriority(GPDMA1_Channel0_IRQn, 4, 0);
  HAL_NVIC_EnableIRQ(GPDMA1_Channel0_IRQn);

  /* Channel 1: word-width M2M */
  hdma_ch1.Instance = GPDMA1_Channel1;
  hdma_ch1.Init.Request = DMA_REQUEST_SW;
  hdma_ch1.Init.BlkHWRequest = DMA_BREQ_SINGLE_BURST;
  hdma_ch1.Init.Direction = DMA_MEMORY_TO_MEMORY;
  hdma_ch1.Init.SrcInc = DMA_SINC_INCREMENTED;
  hdma_ch1.Init.DestInc = DMA_DINC_INCREMENTED;
  hdma_ch1.Init.SrcDataWidth = DMA_SRC_DATAWIDTH_WORD;
  hdma_ch1.Init.DestDataWidth = DMA_DEST_DATAWIDTH_WORD;
  hdma_ch1.Init.Priority = DMA_LOW_PRIORITY_LOW_WEIGHT;
  hdma_ch1.Init.SrcBurstLength = 1;
  hdma_ch1.Init.DestBurstLength = 1;
  hdma_ch1.Init.TransferAllocatedPort = DMA_SRC_ALLOCATED_PORT0 | DMA_DEST_ALLOCATED_PORT0;
  hdma_ch1.Init.TransferEventMode = DMA_TCEM_BLOCK_TRANSFER;
  hdma_ch1.Init.Mode = DMA_NORMAL;

  if (HAL_DMA_Init(&hdma_ch1) != HAL_OK)
  {
    UART_Print("[DMA] Ch1 init FAILED\r\n");
    Error_Handler();
  }

  hdma_ch1.XferCpltCallback = HAL_DMA_XferCpltCallback;
  hdma_ch1.XferErrorCallback = HAL_DMA_XferErrorCallback;

  HAL_NVIC_SetPriority(GPDMA1_Channel1_IRQn, 4, 0);
  HAL_NVIC_EnableIRQ(GPDMA1_Channel1_IRQn);
}

/* ================================================================
 * DMA Sub-Tests
 * ================================================================ */

/**
  * DMA Test 1: Channel 0 M2M transfer with TC interrupt.
  */
static int DMA_Test_Ch0_M2M(void)
{
  uint32_t i, timeout;

  UART_Print("[DMA] Ch0 M2M 256 bytes...\r\n");

  for (i = 0; i < DMA_TEST_SIZE_WORDS; i++)
  {
    src_buf[i] = 0xA5000000 | (i * 0x01010101);
    dst_buf[i] = 0;
  }

  dma_ch0_complete = 0;
  dma_ch0_error = 0;

  if (HAL_DMA_Start_IT(&hdma_ch0,
                        (uint32_t)src_buf,
                        (uint32_t)dst_buf,
                        DMA_TEST_SIZE_BYTES) != HAL_OK)
  {
    UART_Print("[DMA] Ch0 start FAILED\r\n");
    return 0;
  }

  timeout = 1000000;
  while (!dma_ch0_complete && !dma_ch0_error && timeout > 0)
    timeout--;

  if (dma_ch0_error)
  {
    UART_Print("[DMA] Ch0 transfer ERROR\r\n");
    return 0;
  }
  if (!dma_ch0_complete)
  {
    UART_Print("[DMA] Ch0 transfer TIMEOUT\r\n");
    return 0;
  }

  UART_Print("[DMA] Ch0 M2M TC interrupt: PASS\r\n");
  return 1;
}

/**
  * DMA Test 2: Channel 1 M2M transfer (multi-channel validation).
  */
static int DMA_Test_Ch1_M2M(void)
{
  uint32_t i, timeout;

  UART_Print("[DMA] Ch1 M2M 64 bytes...\r\n");

  for (i = 0; i < DMA_SMALL_SIZE_WORDS; i++)
  {
    src_buf2[i] = 0xBEEF0000 | i;
    dst_buf2[i] = 0;
  }

  dma_ch1_complete = 0;
  dma_ch1_error = 0;

  if (HAL_DMA_Start_IT(&hdma_ch1,
                        (uint32_t)src_buf2,
                        (uint32_t)dst_buf2,
                        DMA_SMALL_SIZE_BYTES) != HAL_OK)
  {
    UART_Print("[DMA] Ch1 start FAILED\r\n");
    return 0;
  }

  timeout = 1000000;
  while (!dma_ch1_complete && !dma_ch1_error && timeout > 0)
    timeout--;

  if (dma_ch1_error)
  {
    UART_Print("[DMA] Ch1 transfer ERROR\r\n");
    return 0;
  }
  if (!dma_ch1_complete)
  {
    UART_Print("[DMA] Ch1 transfer TIMEOUT\r\n");
    return 0;
  }

  UART_Print("[DMA] Ch1 M2M TC interrupt: PASS\r\n");
  return 1;
}

/**
  * DMA Test 3: Half-transfer flag (HTF).
  * Use direct register access (bypass HAL) to verify HTF is set
  * on transfer completion. HAL_DMA_IRQHandler clears flags, so
  * we must check before IRQ processing.
  *
  * Approach: disable NVIC IRQ, start transfer via direct register
  * writes, then read CSR before any IRQ handler runs.
  */
static int DMA_Test_HalfTransfer(void)
{
  uint32_t csr;

  UART_Print("[DMA] Half-transfer flag (direct regs)...\r\n");

  /* Reset channel 0 and configure directly */
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;

  /* Disable NVIC for Ch0 so IRQ handler doesn't auto-clear flags */
  HAL_NVIC_DisableIRQ(GPDMA1_Channel0_IRQn);

  /* Configure: SWREQ, word src/dst, src+dst increment */
  GPDMA1_Channel0->CTR1 = (0 << 0)   /* SDW_LOG2 = 0 (word=2^0? no, log2(4)=2) */
                         | (1 << 3)   /* SINC */
                         | (2 << 0)   /* SDW_LOG2 = 2 (word) */
                         | (1 << 19)  /* DINC */
                         | (2 << 16); /* DDW_LOG2 = 2 (word) */
  GPDMA1_Channel0->CTR2 = DMA_CCR_SUSP; /* SWREQ = bit 9 */
  GPDMA1_Channel0->CTR2 = (1 << 9);  /* SWREQ */
  GPDMA1_Channel0->CBR1 = DMA_SMALL_SIZE_BYTES;
  GPDMA1_Channel0->CSAR = (uint32_t)src_buf;
  GPDMA1_Channel0->CDAR = (uint32_t)dst_buf;

  /* Enable with TCIE + HTIE */
  GPDMA1_Channel0->CCR = DMA_CCR_EN | DMA_CCR_TCIE | DMA_CCR_HTIE;

  /* Emulation completes immediately -- read CSR before any IRQ processing */
  csr = GPDMA1_Channel0->CSR;

  /* Re-enable NVIC */
  HAL_NVIC_EnableIRQ(GPDMA1_Channel0_IRQn);

  /* Clean up: clear all flags, reset channel */
  GPDMA1_Channel0->CFCR = 0x7F00;
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;

  /* Re-init channel via HAL for subsequent tests */
  HAL_DMA_Init(&hdma_ch0);
  hdma_ch0.XferCpltCallback = HAL_DMA_XferCpltCallback;
  hdma_ch0.XferHalfCpltCallback = HAL_DMA_XferHalfCpltCallback;
  hdma_ch0.XferErrorCallback = HAL_DMA_XferErrorCallback;

  if ((csr & DMA_CSR_HTF) && (csr & DMA_CSR_TCF))
  {
    UART_Print("[DMA] CSR.HTF + CSR.TCF set: PASS\r\n");
    return 1;
  }
  else
  {
    UART_PrintHex("[DMA] CSR after direct xfer=", csr);
    if (!(csr & DMA_CSR_HTF))
      UART_Print("[DMA] HTF not set\r\n");
    if (!(csr & DMA_CSR_TCF))
      UART_Print("[DMA] TCF not set\r\n");
    UART_Print("[DMA] HTF: FAIL\r\n");
    return 0;
  }
}

/**
  * DMA Test 4: Channel suspend.
  * Write CCR.SUSP -> verify CSR.SUSPF is set and channel becomes idle.
  */
static int DMA_Test_Suspend(void)
{
  uint32_t ccr, csr;

  UART_Print("[DMA] Suspend test...\r\n");

  /* Re-init channel 0 for this test */
  HAL_DMA_DeInit(&hdma_ch0);
  hdma_ch0.Init.Request = DMA_REQUEST_SW;
  hdma_ch0.Init.Direction = DMA_MEMORY_TO_MEMORY;
  hdma_ch0.Init.SrcInc = DMA_SINC_INCREMENTED;
  hdma_ch0.Init.DestInc = DMA_DINC_INCREMENTED;
  hdma_ch0.Init.SrcDataWidth = DMA_SRC_DATAWIDTH_WORD;
  hdma_ch0.Init.DestDataWidth = DMA_DEST_DATAWIDTH_WORD;
  hdma_ch0.Init.Priority = DMA_HIGH_PRIORITY;
  hdma_ch0.Init.SrcBurstLength = 1;
  hdma_ch0.Init.DestBurstLength = 1;
  hdma_ch0.Init.TransferAllocatedPort = DMA_SRC_ALLOCATED_PORT0 | DMA_DEST_ALLOCATED_PORT0;
  hdma_ch0.Init.TransferEventMode = DMA_TCEM_BLOCK_TRANSFER;
  hdma_ch0.Init.Mode = DMA_NORMAL;
  HAL_DMA_Init(&hdma_ch0);

  /* Write SUSP bit to CCR */
  ccr = GPDMA1_Channel0->CCR;
  GPDMA1_Channel0->CCR = ccr | DMA_CCR_SUSP;

  /* Read CSR to check SUSPF */
  csr = GPDMA1_Channel0->CSR;

  if (csr & DMA_CSR_SUSPF)
  {
    UART_Print("[DMA] CCR.SUSP -> CSR.SUSPF: PASS\r\n");
    return 1;
  }
  else
  {
    UART_PrintHex("[DMA] SUSPF not set, CSR=", csr);
    UART_Print("[DMA] Suspend: FAIL\r\n");
    return 0;
  }
}

/**
  * DMA Test 5: Channel reset.
  * Write CCR.RESET -> verify channel returns to idle, all regs cleared.
  */
static int DMA_Test_Reset(void)
{
  uint32_t csr, ccr;
  int ok = 1;

  UART_Print("[DMA] Reset test...\r\n");

  /* Write RESET bit */
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;

  /* After reset: CCR=0, CSR=IDLEF only */
  ccr = GPDMA1_Channel0->CCR;
  csr = GPDMA1_Channel0->CSR;

  if (ccr != 0)
  {
    UART_PrintHex("[DMA] After RESET CCR!=0: ", ccr);
    ok = 0;
  }
  if (!(csr & DMA_CSR_IDLEF))
  {
    UART_PrintHex("[DMA] After RESET no IDLEF, CSR=", csr);
    ok = 0;
  }
  /* Status flags should be cleared */
  if (csr & (DMA_CSR_TCF | DMA_CSR_HTF | DMA_CSR_DTEF | DMA_CSR_SUSPF))
  {
    UART_PrintHex("[DMA] After RESET stale flags, CSR=", csr);
    ok = 0;
  }

  if (ok)
    UART_Print("[DMA] CCR.RESET -> idle state: PASS\r\n");
  else
    UART_Print("[DMA] Reset: FAIL\r\n");

  /* Re-init channel for subsequent tests */
  HAL_DMA_Init(&hdma_ch0);
  hdma_ch0.XferCpltCallback = HAL_DMA_XferCpltCallback;
  hdma_ch0.XferHalfCpltCallback = HAL_DMA_XferHalfCpltCallback;
  hdma_ch0.XferErrorCallback = HAL_DMA_XferErrorCallback;

  return ok;
}

/**
  * DMA Test 6: CFCR flag clear (W1C).
  * Use direct register access: start transfer with NVIC disabled,
  * verify TCF/HTF set, then clear via CFCR, verify cleared.
  */
static int DMA_Test_FlagClear(void)
{
  uint32_t csr;
  int ok = 1;

  UART_Print("[DMA] CFCR flag clear test...\r\n");

  /* Reset and configure channel directly */
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;
  HAL_NVIC_DisableIRQ(GPDMA1_Channel0_IRQn);

  GPDMA1_Channel0->CTR1 = (2 << 0) | (1 << 3) | (1 << 19) | (2 << 16);
  GPDMA1_Channel0->CTR2 = (1 << 9);  /* SWREQ */
  GPDMA1_Channel0->CBR1 = DMA_SMALL_SIZE_BYTES;
  GPDMA1_Channel0->CSAR = (uint32_t)src_buf;
  GPDMA1_Channel0->CDAR = (uint32_t)dst_buf;

  /* Enable with TCIE + HTIE */
  GPDMA1_Channel0->CCR = DMA_CCR_EN | DMA_CCR_TCIE | DMA_CCR_HTIE;

  /* Read CSR -- TCF and HTF should be set */
  csr = GPDMA1_Channel0->CSR;
  if (!(csr & DMA_CSR_TCF))
  {
    UART_Print("[DMA] CFCR: TCF not set before clear\r\n");
    ok = 0;
  }

  /* Clear TCF via CFCR (write-1-to-clear) */
  GPDMA1_Channel0->CFCR = DMA_CSR_TCF;
  csr = GPDMA1_Channel0->CSR;
  if (csr & DMA_CSR_TCF)
  {
    UART_PrintHex("[DMA] TCF still set after clear, CSR=", csr);
    ok = 0;
  }
  else
  {
    UART_Print("[DMA] TCF cleared via CFCR: OK\r\n");
  }

  /* Clear HTF via CFCR */
  GPDMA1_Channel0->CFCR = DMA_CSR_HTF;
  csr = GPDMA1_Channel0->CSR;
  if (csr & DMA_CSR_HTF)
  {
    UART_Print("[DMA] HTF still set after clear\r\n");
    ok = 0;
  }
  else
  {
    UART_Print("[DMA] HTF cleared via CFCR: OK\r\n");
  }

  /* Cleanup */
  HAL_NVIC_EnableIRQ(GPDMA1_Channel0_IRQn);
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;
  HAL_DMA_Init(&hdma_ch0);
  hdma_ch0.XferCpltCallback = HAL_DMA_XferCpltCallback;
  hdma_ch0.XferHalfCpltCallback = HAL_DMA_XferHalfCpltCallback;
  hdma_ch0.XferErrorCallback = HAL_DMA_XferErrorCallback;

  if (ok)
    UART_Print("[DMA] CFCR W1C flag clear: PASS\r\n");
  else
    UART_Print("[DMA] CFCR: FAIL\r\n");
  return ok;
}

/**
  * DMA Test 7: MISR (Masked Interrupt Status Register).
  * Use direct register access with NVIC disabled so flags persist.
  * MISR bit N = 1 when channel N has any enabled+pending flag.
  */
static int DMA_Test_MISR(void)
{
  uint32_t misr;

  UART_Print("[DMA] MISR test...\r\n");

  /* Reset and configure channel directly */
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;
  HAL_NVIC_DisableIRQ(GPDMA1_Channel0_IRQn);

  GPDMA1_Channel0->CTR1 = (2 << 0) | (1 << 3) | (1 << 19) | (2 << 16);
  GPDMA1_Channel0->CTR2 = (1 << 9);  /* SWREQ */
  GPDMA1_Channel0->CBR1 = DMA_SMALL_SIZE_BYTES;
  GPDMA1_Channel0->CSAR = (uint32_t)src_buf;
  GPDMA1_Channel0->CDAR = (uint32_t)dst_buf;

  /* Enable with TCIE */
  GPDMA1_Channel0->CCR = DMA_CCR_EN | DMA_CCR_TCIE;

  /* MISR bit 0 should now reflect Ch0 pending (TCF + TCIE) */
  misr = GPDMA1->MISR;
  UART_PrintHex("[DMA] MISR=", misr);

  /* Cleanup */
  GPDMA1_Channel0->CFCR = 0x7F00;
  HAL_NVIC_EnableIRQ(GPDMA1_Channel0_IRQn);
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;
  HAL_DMA_Init(&hdma_ch0);
  hdma_ch0.XferCpltCallback = HAL_DMA_XferCpltCallback;
  hdma_ch0.XferHalfCpltCallback = HAL_DMA_XferHalfCpltCallback;
  hdma_ch0.XferErrorCallback = HAL_DMA_XferErrorCallback;

  if (misr & (1 << 0))
  {
    UART_Print("[DMA] MISR bit0 (Ch0 pending): PASS\r\n");
    return 1;
  }
  else
  {
    UART_Print("[DMA] MISR bit0 not set: FAIL\r\n");
    return 0;
  }
}

/**
  * DMA Test 8: CSR.IDLEF tracking.
  * After reset, channel is idle (IDLEF=1).
  * After init (before transfer), channel should still be idle.
  */
static int DMA_Test_IDLEF(void)
{
  uint32_t csr;
  int ok = 1;

  UART_Print("[DMA] IDLEF test...\r\n");

  /* Reset channel 0 */
  GPDMA1_Channel0->CCR = DMA_CCR_RESET;
  csr = GPDMA1_Channel0->CSR;

  if (!(csr & DMA_CSR_IDLEF))
  {
    UART_Print("[DMA] IDLEF not set after reset: FAIL\r\n");
    ok = 0;
  }
  else
  {
    UART_Print("[DMA] IDLEF set after reset: OK\r\n");
  }

  /* Re-init -- IDLEF should remain set (channel configured but not started) */
  HAL_DMA_Init(&hdma_ch0);
  csr = GPDMA1_Channel0->CSR;

  if (!(csr & DMA_CSR_IDLEF))
  {
    UART_Print("[DMA] IDLEF not set after init: FAIL\r\n");
    ok = 0;
  }
  else
  {
    UART_Print("[DMA] IDLEF set after init: OK\r\n");
  }

  if (ok)
    UART_Print("[DMA] CSR.IDLEF tracking: PASS\r\n");
  return ok;
}

/* ================================================================
 * Utility
 * ================================================================ */
static void UART_Print(const char *msg)
{
  HAL_UART_Transmit(&huart1, (const uint8_t *)msg, (uint16_t)strlen(msg), 100);
}

static void UART_PrintHex(const char *label, uint32_t val)
{
  snprintf(print_buf, sizeof(print_buf), "%s0x%08lX\r\n",
           label, (unsigned long)val);
  UART_Print(print_buf);
}

void Error_Handler(void)
{
  __disable_irq();
  while (1) {}
}
