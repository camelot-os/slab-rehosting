/**
 * @file    partition_stm32h563xx.h
 * @brief   CMSIS-CORE TrustZone partition configuration for STM32H563xx
 *
 * SAU (Security Attribution Unit) and interrupt target configuration
 * for secure/non-secure memory and peripheral partitioning.
 */

#ifndef PARTITION_STM32H563XX_H
#define PARTITION_STM32H563XX_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32h5xx.h"

/* ---- SAU Region Configuration ---- */

/* Number of SAU regions used */
#define SAU_INIT_REGION_COUNT   4U

/*
 * SAU Region 0: Non-Secure Flash
 * 0x08042000 - 0x081FFFFF (~1.75MB)
 */
#define SAU_INIT_REGION0_START  0x08042000UL
#define SAU_INIT_REGION0_END    0x081FFFFFUL
#define SAU_INIT_REGION0_NSC    0U  /* Non-Secure */

/*
 * SAU Region 1: Non-Secure Callable (NSC) Flash
 * 0x0C040000 - 0x0C041FFF (8KB)
 */
#define SAU_INIT_REGION1_START  0x0C040000UL
#define SAU_INIT_REGION1_END    0x0C041FFFUL
#define SAU_INIT_REGION1_NSC    1U  /* Non-Secure Callable */

/*
 * SAU Region 2: Non-Secure SRAM
 * 0x20020000 - 0x2009FFFF (512KB)
 */
#define SAU_INIT_REGION2_START  0x20020000UL
#define SAU_INIT_REGION2_END    0x2009FFFFUL
#define SAU_INIT_REGION2_NSC    0U  /* Non-Secure */

/*
 * SAU Region 3: Non-Secure Peripherals
 * 0x40000000 - 0x4FFFFFFF (peripheral address space)
 * Fine-grained control via GTZC TZSC
 */
#define SAU_INIT_REGION3_START  0x40000000UL
#define SAU_INIT_REGION3_END    0x4FFFFFFFUL
#define SAU_INIT_REGION3_NSC    0U  /* Non-Secure */

/* ---- Non-Secure Application Addresses ---- */
#define NS_FLASH_START          0x08042000UL
#define NS_SRAM_START           0x20020000UL

/* Non-secure vector table (start of NS flash) */
#define VTOR_TABLE_NS_START_ADDR  NS_FLASH_START

/* ---- Interrupt Target Configuration ---- */
/* NVIC ITNS (Interrupt Target Non-Secure) bits */
/* USB OTG FS interrupt -> Non-Secure */
#define NVIC_INIT_ITNS_USB_OTG_FS   1U

/* ---- FPU Configuration ---- */
/* FPU accessible from both Secure and Non-Secure */
#define FPU_S_NS_ACCESS         3U  /* Both S and NS can use FPU */

/* ---- SAU Initialization Function ---- */
static inline void SAU_Setup(void)
{
    /* Disable SAU before configuration */
    SAU->CTRL = 0U;

    /* Region 0: Non-Secure Flash */
    SAU->RNR  = 0U;
    SAU->RBAR = SAU_INIT_REGION0_START & SAU_RBAR_BADDR_Msk;
    SAU->RLAR = (SAU_INIT_REGION0_END & SAU_RLAR_LADDR_Msk)
                | ((SAU_INIT_REGION0_NSC << SAU_RLAR_NSC_Pos) & SAU_RLAR_NSC_Msk)
                | SAU_RLAR_ENABLE_Msk;

    /* Region 1: Non-Secure Callable (NSC) Flash */
    SAU->RNR  = 1U;
    SAU->RBAR = SAU_INIT_REGION1_START & SAU_RBAR_BADDR_Msk;
    SAU->RLAR = (SAU_INIT_REGION1_END & SAU_RLAR_LADDR_Msk)
                | ((SAU_INIT_REGION1_NSC << SAU_RLAR_NSC_Pos) & SAU_RLAR_NSC_Msk)
                | SAU_RLAR_ENABLE_Msk;

    /* Region 2: Non-Secure SRAM */
    SAU->RNR  = 2U;
    SAU->RBAR = SAU_INIT_REGION2_START & SAU_RBAR_BADDR_Msk;
    SAU->RLAR = (SAU_INIT_REGION2_END & SAU_RLAR_LADDR_Msk)
                | ((SAU_INIT_REGION2_NSC << SAU_RLAR_NSC_Pos) & SAU_RLAR_NSC_Msk)
                | SAU_RLAR_ENABLE_Msk;

    /* Region 3: Non-Secure Peripherals */
    SAU->RNR  = 3U;
    SAU->RBAR = SAU_INIT_REGION3_START & SAU_RBAR_BADDR_Msk;
    SAU->RLAR = (SAU_INIT_REGION3_END & SAU_RLAR_LADDR_Msk)
                | ((SAU_INIT_REGION3_NSC << SAU_RLAR_NSC_Pos) & SAU_RLAR_NSC_Msk)
                | SAU_RLAR_ENABLE_Msk;

    /* Enable SAU - all memory not covered by regions is Secure */
    SAU->CTRL = SAU_CTRL_ENABLE_Msk;

    /* Configure FPU access from Non-Secure */
    SCB->NSACR |= (SCB_NSACR_CP10_Msk | SCB_NSACR_CP11_Msk);
    FPU->FPCCR |= FPU_FPCCR_TS_Msk | FPU_FPCCR_CLRONRETS_Msk | FPU_FPCCR_CLRONRET_Msk;
}

#ifdef __cplusplus
}
#endif

#endif /* PARTITION_STM32H563XX_H */
