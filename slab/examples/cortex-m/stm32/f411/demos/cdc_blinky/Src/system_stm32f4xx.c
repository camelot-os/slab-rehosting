/**
  * System initialization for STM32F411
  *
  * Based on STM32CubeF4 CMSIS template.
  * Configures FPU, sets VTOR, initializes SystemCoreClock.
  *
  * Copyright (c) 2017 STMicroelectronics. (original template)
  * Copyright (C) 2026 Twisted Wires Security Lab. (adaptation)
  */
#include "stm32f4xx.h"

#if !defined(HSE_VALUE)
#define HSE_VALUE    (25000000UL)
#endif

#if !defined(HSI_VALUE)
#define HSI_VALUE    (16000000UL)
#endif

/******************************************************************************/
/*  Global variables                                                          */
/******************************************************************************/

/* System Core Clock initial value (HSI 16MHz at reset) */
uint32_t SystemCoreClock = 16000000UL;

const uint8_t AHBPrescTable[16] = {
  0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U,
  1U, 2U, 3U, 4U, 6U, 7U, 8U, 9U
};

const uint8_t APBPrescTable[8] = {
  0U, 0U, 0U, 0U, 1U, 2U, 3U, 4U
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
  uint32_t tmp, pllvco, pllp, pllsource, pllm;

  /* Get SYSCLK source */
  tmp = RCC->CFGR & RCC_CFGR_SWS;

  switch (tmp)
  {
    case 0x00U:  /* HSI used as system clock source */
      SystemCoreClock = HSI_VALUE;
      break;

    case 0x04U:  /* HSE used as system clock source */
      SystemCoreClock = HSE_VALUE;
      break;

    case 0x08U:  /* PLL used as system clock source */
      pllsource = (RCC->PLLCFGR & RCC_PLLCFGR_PLLSRC) >> RCC_PLLCFGR_PLLSRC_Pos;
      pllm = RCC->PLLCFGR & RCC_PLLCFGR_PLLM;

      if (pllsource != 0)
      {
        /* HSE used as PLL clock source */
        pllvco = (HSE_VALUE / pllm) * ((RCC->PLLCFGR & RCC_PLLCFGR_PLLN) >> RCC_PLLCFGR_PLLN_Pos);
      }
      else
      {
        /* HSI used as PLL clock source */
        pllvco = (HSI_VALUE / pllm) * ((RCC->PLLCFGR & RCC_PLLCFGR_PLLN) >> RCC_PLLCFGR_PLLN_Pos);
      }

      pllp = (((RCC->PLLCFGR & RCC_PLLCFGR_PLLP) >> RCC_PLLCFGR_PLLP_Pos) + 1U) * 2U;
      SystemCoreClock = pllvco / pllp;
      break;

    default:
      SystemCoreClock = HSI_VALUE;
      break;
  }

  /* Compute HCLK frequency */
  tmp = AHBPrescTable[((RCC->CFGR & RCC_CFGR_HPRE) >> RCC_CFGR_HPRE_Pos)];
  SystemCoreClock >>= tmp;
}
