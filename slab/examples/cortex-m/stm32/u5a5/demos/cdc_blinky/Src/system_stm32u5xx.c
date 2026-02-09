/**
  * System initialization for STM32U5A5
  *
  * Based on STM32CubeU5 CMSIS template.
  * Configures FPU, sets VTOR, resets RCC to MSIS 4MHz default.
  *
  * Copyright (c) 2021-2023 STMicroelectronics. (original template)
  * Copyright (C) 2026 Twisted Wires Security Lab. (adaptation)
  */
#include "stm32u5xx.h"

#if !defined(HSE_VALUE)
#define HSE_VALUE    (16000000UL)
#endif

#if !defined(MSI_VALUE)
#define MSI_VALUE    (4000000UL)
#endif

#if !defined(HSI_VALUE)
#define HSI_VALUE    (16000000UL)
#endif

#if !defined(LSI_VALUE)
#define LSI_VALUE    (32000UL)
#endif

#if !defined(LSE_VALUE)
#define LSE_VALUE    (32768U)
#endif

/******************************************************************************/
/*  Global variables                                                          */
/******************************************************************************/

/* System Core Clock initial value (MSIS 4MHz) */
uint32_t SystemCoreClock = 4000000UL;

const uint8_t AHBPrescTable[16] = {
  0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U,
  1U, 2U, 3U, 4U, 6U, 7U, 8U, 9U
};

const uint8_t APBPrescTable[8] = {
  0U, 0U, 0U, 0U, 1U, 2U, 3U, 4U
};

const uint32_t MSIRangeTable[16] = {
     48000000UL,  24000000UL,  16000000UL,  12000000UL,
      4000000UL,   2000000UL,   1330000UL,   1000000UL,
      3072000UL,   1536000UL,   1024000UL,    768000UL,
       400000UL,    200000UL,    133000UL,    100000UL
};

/******************************************************************************/
/*  SystemInit                                                                */
/******************************************************************************/
void SystemInit(void)
{
#if (__FPU_PRESENT == 1) && (__FPU_USED == 1)
  /* Enable CP10 and CP11 (FPU) full access */
  SCB->CPACR |= ((3UL << (10UL * 2UL)) | (3UL << (11UL * 2UL)));
#endif

  /* Set VTOR to flash base */
  SCB->VTOR = FLASH_BASE;
}

/******************************************************************************/
/*  SystemCoreClockUpdate                                                     */
/******************************************************************************/
void SystemCoreClockUpdate(void)
{
  uint32_t pllr, pllsource, pllm, tmp, msirange, pllvco;

  /* Get MSIS range */
  if ((RCC->ICSCR1 & RCC_ICSCR1_MSIRGSEL) != 0U)
  {
    msirange = MSIRangeTable[(RCC->ICSCR1 & RCC_ICSCR1_MSISRANGE) >> RCC_ICSCR1_MSISRANGE_Pos];
  }
  else
  {
    msirange = MSIRangeTable[(RCC->CSR & RCC_CSR_MSISSRANGE) >> RCC_CSR_MSISSRANGE_Pos];
  }

  switch (RCC->CFGR1 & RCC_CFGR1_SWS)
  {
    case 0x00U:  /* MSIS used as system clock source */
      SystemCoreClock = msirange;
      break;

    case 0x04U:  /* HSI used as system clock source */
      SystemCoreClock = HSI_VALUE;
      break;

    case 0x08U:  /* HSE used as system clock source */
      SystemCoreClock = HSE_VALUE;
      break;

    case 0x0CU:  /* PLL1 used as system clock source */
      pllsource = (RCC->PLL1CFGR & RCC_PLL1CFGR_PLL1SRC);
      pllm = ((RCC->PLL1CFGR & RCC_PLL1CFGR_PLL1M) >> RCC_PLL1CFGR_PLL1M_Pos) + 1U;

      switch (pllsource)
      {
        case 0x01U:  /* MSI */
          pllvco = msirange / pllm;
          break;
        case 0x02U:  /* HSI */
          pllvco = HSI_VALUE / pllm;
          break;
        case 0x03U:  /* HSE */
          pllvco = HSE_VALUE / pllm;
          break;
        default:
          pllvco = msirange / pllm;
          break;
      }

      pllvco = pllvco * ((RCC->PLL1DIVR & RCC_PLL1DIVR_PLL1N) + 1U);
      pllr = ((RCC->PLL1DIVR & RCC_PLL1DIVR_PLL1R) >> RCC_PLL1DIVR_PLL1R_Pos) + 1U;
      SystemCoreClock = pllvco / pllr;
      break;

    default:
      SystemCoreClock = msirange;
      break;
  }

  /* Compute HCLK frequency */
  tmp = AHBPrescTable[((RCC->CFGR2 & RCC_CFGR2_HPRE) >> RCC_CFGR2_HPRE_Pos)];
  SystemCoreClock >>= tmp;
}
