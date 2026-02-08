/*
 * STM32F4 Minimal Register Definitions
 *
 * Bare-metal register definitions for STM32F4xx SoC peripherals.
 * Only includes registers and bit fields used by firmware examples.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef STM32F4_H
#define STM32F4_H

#include <stdint.h>

/* ============================================================================
 * Base Addresses
 * ============================================================================ */

#define PERIPH_BASE         0x40000000UL
#define APB1PERIPH_BASE     (PERIPH_BASE + 0x00000000UL)
#define APB2PERIPH_BASE     (PERIPH_BASE + 0x00010000UL)
#define AHB1PERIPH_BASE     (PERIPH_BASE + 0x00020000UL)
#define AHB2PERIPH_BASE     (PERIPH_BASE + 0x10000000UL)

/* Peripheral base addresses */
#define I2C1_BASE           (APB1PERIPH_BASE + 0x5400UL)
#define SPI1_BASE           (APB2PERIPH_BASE + 0x3000UL)
#define RCC_BASE            (AHB1PERIPH_BASE + 0x3800UL)
#define GPIOA_BASE          (AHB1PERIPH_BASE + 0x0000UL)
#define DMA2_BASE           (AHB1PERIPH_BASE + 0x6400UL)
#define CRYP_BASE           (AHB2PERIPH_BASE + 0x00060000UL)
#define HASH_BASE           (AHB2PERIPH_BASE + 0x00060400UL)

/* ============================================================================
 * RCC - Reset and Clock Control
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR;           /* 0x00 */
    volatile uint32_t PLLCFGR;      /* 0x04 */
    volatile uint32_t CFGR;         /* 0x08 */
    volatile uint32_t CIR;          /* 0x0C */
    volatile uint32_t AHB1RSTR;     /* 0x10 */
    volatile uint32_t AHB2RSTR;     /* 0x14 */
    volatile uint32_t AHB3RSTR;     /* 0x18 */
    uint32_t RESERVED0;             /* 0x1C */
    volatile uint32_t APB1RSTR;     /* 0x20 */
    volatile uint32_t APB2RSTR;     /* 0x24 */
    uint32_t RESERVED1[2];          /* 0x28-0x2C */
    volatile uint32_t AHB1ENR;      /* 0x30 */
    volatile uint32_t AHB2ENR;      /* 0x34 */
    volatile uint32_t AHB3ENR;      /* 0x38 */
    uint32_t RESERVED2;             /* 0x3C */
    volatile uint32_t APB1ENR;      /* 0x40 */
    volatile uint32_t APB2ENR;      /* 0x44 */
} RCC_TypeDef;

/* RCC AHB1ENR bit definitions */
#define RCC_AHB1ENR_GPIOAEN     (1UL << 0)
#define RCC_AHB1ENR_DMA2EN      (1UL << 22)

/* RCC AHB2ENR bit definitions */
#define RCC_AHB2ENR_CRYPEN      (1UL << 4)
#define RCC_AHB2ENR_HASHEN      (1UL << 5)

/* RCC APB2ENR bit definitions */
#define RCC_APB2ENR_SPI1EN      (1UL << 12)

/* ============================================================================
 * GPIO
 * ============================================================================ */

typedef struct {
    volatile uint32_t MODER;        /* 0x00 */
    volatile uint32_t OTYPER;       /* 0x04 */
    volatile uint32_t OSPEEDR;      /* 0x08 */
    volatile uint32_t PUPDR;        /* 0x0C */
    volatile uint32_t IDR;          /* 0x10 */
    volatile uint32_t ODR;          /* 0x14 */
    volatile uint32_t BSRR;         /* 0x18 */
    volatile uint32_t LCKR;         /* 0x1C */
    volatile uint32_t AFRL;         /* 0x20 */
    volatile uint32_t AFRH;         /* 0x24 */
} GPIO_TypeDef;

/* ============================================================================
 * SPI
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR1;          /* 0x00 */
    volatile uint32_t CR2;          /* 0x04 */
    volatile uint32_t SR;           /* 0x08 */
    volatile uint32_t DR;           /* 0x0C */
} SPI_TypeDef;

/* ============================================================================
 * I2C (STM32F4 I2C v1)
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR1;          /* 0x00 */
    volatile uint32_t CR2;          /* 0x04 */
    volatile uint32_t OAR1;         /* 0x08 */
    volatile uint32_t OAR2;         /* 0x0C */
    volatile uint32_t DR;           /* 0x10 */
    volatile uint32_t SR1;          /* 0x14 */
    volatile uint32_t SR2;          /* 0x18 */
    volatile uint32_t CCR;          /* 0x1C */
    volatile uint32_t TRISE;        /* 0x20 */
} I2C_TypeDef;

/* ============================================================================
 * DMA
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR;           /* 0x00 - Stream configuration */
    volatile uint32_t NDTR;         /* 0x04 - Number of data */
    volatile uint32_t PAR;          /* 0x08 - Peripheral address */
    volatile uint32_t M0AR;         /* 0x0C - Memory 0 address */
    volatile uint32_t M1AR;         /* 0x10 - Memory 1 address */
    volatile uint32_t FCR;          /* 0x14 - FIFO control */
} DMA_Stream_TypeDef;

typedef struct {
    volatile uint32_t LISR;         /* 0x00 - Low interrupt status */
    volatile uint32_t HISR;         /* 0x04 - High interrupt status */
    volatile uint32_t LIFCR;        /* 0x08 - Low interrupt flag clear */
    volatile uint32_t HIFCR;        /* 0x0C - High interrupt flag clear */
    DMA_Stream_TypeDef S[8];        /* 0x10 - Streams 0-7 */
} DMA_TypeDef;

/* DMA Stream CR bit definitions */
#define DMA_SxCR_EN             (1UL << 0)

/* ============================================================================
 * Peripheral Instances
 * ============================================================================ */

#define RCC     ((RCC_TypeDef *)RCC_BASE)
#define GPIOA   ((GPIO_TypeDef *)GPIOA_BASE)
#define SPI1    ((SPI_TypeDef *)SPI1_BASE)
#define I2C1    ((I2C_TypeDef *)I2C1_BASE)
#define DMA2    ((DMA_TypeDef *)DMA2_BASE)

#endif /* STM32F4_H */
