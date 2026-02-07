/*
 * STM32L4 Minimal Register Definitions
 *
 * Bare-metal register definitions for STM32L4xx SoC peripherals.
 * Only includes registers and bit fields used by firmware examples.
 * STM32L4 uses I2C v2 peripheral (different from STM32F4 I2C v1).
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef STM32L4_H
#define STM32L4_H

#include <stdint.h>

/* ============================================================================
 * Base Addresses
 * ============================================================================ */

#define PERIPH_BASE         0x40000000UL
#define APB1PERIPH_BASE     (PERIPH_BASE + 0x00000000UL)
#define AHB1PERIPH_BASE     (PERIPH_BASE + 0x00020000UL)
#define AHB2PERIPH_BASE     (PERIPH_BASE + 0x08000000UL)

/* Peripheral base addresses */
#define I2C1_BASE           (APB1PERIPH_BASE + 0x5400UL)
#define RCC_BASE            (AHB1PERIPH_BASE + 0x1000UL)
#define GPIOB_BASE          (AHB2PERIPH_BASE + 0x0400UL)

/* ============================================================================
 * RCC - Reset and Clock Control (STM32L4)
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR;           /* 0x00 */
    volatile uint32_t ICSCR;        /* 0x04 */
    volatile uint32_t CFGR;         /* 0x08 */
    volatile uint32_t PLLCFGR;      /* 0x0C */
    volatile uint32_t PLLSAI1CFGR;  /* 0x10 */
    uint32_t RESERVED0;             /* 0x14 */
    volatile uint32_t CIER;         /* 0x18 */
    volatile uint32_t CIFR;         /* 0x1C */
    volatile uint32_t CICR;         /* 0x20 */
    uint32_t RESERVED1;             /* 0x24 */
    volatile uint32_t AHB1RSTR;     /* 0x28 */
    volatile uint32_t AHB2RSTR;     /* 0x2C */
    volatile uint32_t AHB3RSTR;     /* 0x30 */
    uint32_t RESERVED2;             /* 0x34 */
    volatile uint32_t APB1RSTR1;    /* 0x38 */
    volatile uint32_t APB1RSTR2;    /* 0x3C */
    volatile uint32_t APB2RSTR;     /* 0x40 */
    uint32_t RESERVED3;             /* 0x44 */
    volatile uint32_t AHB1ENR;      /* 0x48 */
    volatile uint32_t AHB2ENR;      /* 0x4C */
    volatile uint32_t AHB3ENR;      /* 0x50 */
    uint32_t RESERVED4;             /* 0x54 */
    volatile uint32_t APB1ENR1;     /* 0x58 */
    volatile uint32_t APB1ENR2;     /* 0x5C */
    volatile uint32_t APB2ENR;      /* 0x60 */
} RCC_TypeDef;

/* RCC AHB2ENR bit definitions */
#define RCC_AHB2ENR_GPIOAEN     (1UL << 0)
#define RCC_AHB2ENR_GPIOBEN     (1UL << 1)

/* RCC APB1ENR1 bit definitions */
#define RCC_APB1ENR1_I2C1EN     (1UL << 21)

/* ============================================================================
 * GPIO (STM32L4)
 * ============================================================================ */

typedef struct {
    volatile uint32_t MODER;        /* 0x00 - Mode register */
    volatile uint32_t OTYPER;       /* 0x04 - Output type register */
    volatile uint32_t OSPEEDR;      /* 0x08 - Output speed register */
    volatile uint32_t PUPDR;        /* 0x0C - Pull-up/pull-down register */
    volatile uint32_t IDR;          /* 0x10 - Input data register */
    volatile uint32_t ODR;          /* 0x14 - Output data register */
    volatile uint32_t BSRR;         /* 0x18 - Bit set/reset register */
    volatile uint32_t LCKR;         /* 0x1C - Lock register */
    volatile uint32_t AFR[2];       /* 0x20-0x24 - Alternate function [0]=low, [1]=high */
} GPIO_TypeDef;

/* ============================================================================
 * I2C v2 (STM32L4)
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR1;          /* 0x00 - Control register 1 */
    volatile uint32_t CR2;          /* 0x04 - Control register 2 */
    volatile uint32_t OAR1;         /* 0x08 - Own address 1 */
    volatile uint32_t OAR2;         /* 0x0C - Own address 2 */
    volatile uint32_t TIMINGR;      /* 0x10 - Timing register */
    volatile uint32_t TIMEOUTR;     /* 0x14 - Timeout register */
    volatile uint32_t ISR;          /* 0x18 - Interrupt and status register */
    volatile uint32_t ICR;          /* 0x1C - Interrupt clear register */
    volatile uint32_t PECR;         /* 0x20 - PEC register */
    volatile uint32_t RXDR;         /* 0x24 - Receive data register */
    volatile uint32_t TXDR;         /* 0x28 - Transmit data register */
} I2C_TypeDef;

/* I2C CR1 bit definitions */
#define I2C_CR1_PE              (1UL << 0)

/* I2C CR2 bit definitions */
#define I2C_CR2_SADD_Msk        (0x3FFUL << 0)
#define I2C_CR2_RD_WRN          (1UL << 10)
#define I2C_CR2_NBYTES_Pos      16
#define I2C_CR2_NBYTES_Msk      (0xFFUL << 16)
#define I2C_CR2_RELOAD          (1UL << 24)
#define I2C_CR2_AUTOEND         (1UL << 25)
#define I2C_CR2_START           (1UL << 13)
#define I2C_CR2_STOP            (1UL << 14)

/* I2C ISR bit definitions */
#define I2C_ISR_TXE             (1UL << 0)
#define I2C_ISR_TXIS            (1UL << 1)
#define I2C_ISR_RXNE            (1UL << 2)
#define I2C_ISR_NACKF           (1UL << 4)
#define I2C_ISR_STOPF           (1UL << 5)
#define I2C_ISR_TC              (1UL << 6)
#define I2C_ISR_BUSY            (1UL << 15)

/* ============================================================================
 * Peripheral Instances
 * ============================================================================ */

#define RCC     ((RCC_TypeDef *)RCC_BASE)
#define GPIOB   ((GPIO_TypeDef *)GPIOB_BASE)
#define I2C1    ((I2C_TypeDef *)I2C1_BASE)

/* ============================================================================
 * I2C v2 Helper Functions
 * ============================================================================ */

/* Configure I2C transfer parameters */
static inline void i2c_configure_transfer(I2C_TypeDef *i2c, uint8_t addr,
                                           uint32_t nbytes, int read,
                                           int autoend)
{
    uint32_t cr2 = 0;
    cr2 |= ((uint32_t)(addr << 1)) & I2C_CR2_SADD_Msk;
    cr2 |= (nbytes << I2C_CR2_NBYTES_Pos) & I2C_CR2_NBYTES_Msk;
    if (read) cr2 |= I2C_CR2_RD_WRN;
    if (autoend) cr2 |= I2C_CR2_AUTOEND;
    cr2 |= I2C_CR2_START;
    i2c->CR2 = cr2;
}

/* Wait for TXIS (TX interrupt status) */
static inline int i2c_wait_txis(I2C_TypeDef *i2c)
{
    volatile int timeout = 100000;
    while (!(i2c->ISR & I2C_ISR_TXIS) && timeout > 0) {
        if (i2c->ISR & I2C_ISR_NACKF) return -1;
        timeout--;
    }
    return timeout > 0 ? 0 : -1;
}

/* Wait for RXNE (RX not empty) */
static inline int i2c_wait_rxne(I2C_TypeDef *i2c)
{
    volatile int timeout = 100000;
    while (!(i2c->ISR & I2C_ISR_RXNE) && timeout > 0) timeout--;
    return timeout > 0 ? 0 : -1;
}

/* Wait for STOPF (stop flag) */
static inline int i2c_wait_stopf(I2C_TypeDef *i2c)
{
    volatile int timeout = 100000;
    while (!(i2c->ISR & I2C_ISR_STOPF) && timeout > 0) timeout--;
    if (timeout > 0) {
        i2c->ICR = I2C_ISR_STOPF;  /* Clear STOPF */
        return 0;
    }
    return -1;
}

/* Wait for TC (transfer complete) */
static inline int i2c_wait_tc(I2C_TypeDef *i2c)
{
    volatile int timeout = 100000;
    while (!(i2c->ISR & I2C_ISR_TC) && timeout > 0) {
        if (i2c->ISR & I2C_ISR_NACKF) return -1;
        timeout--;
    }
    return timeout > 0 ? 0 : -1;
}

#endif /* STM32L4_H */
