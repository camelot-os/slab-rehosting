/*
 * STM32F4 I2C Helper Functions
 *
 * Minimal I2C master driver for STM32F4xx (I2C v1 peripheral).
 * Provides blocking write and write-read operations.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef STM32F4_I2C_H
#define STM32F4_I2C_H

#include <stdint.h>
#include "stm32f4.h"

/* I2C CR1 bit definitions */
#define I2C_CR1_PE          (1UL << 0)
#define I2C_CR1_START       (1UL << 8)
#define I2C_CR1_STOP        (1UL << 9)
#define I2C_CR1_ACK         (1UL << 10)
#define I2C_CR1_SWRST       (1UL << 15)

/* I2C CR2 bit definitions */
#define I2C_CR2_FREQ_Msk    (0x3FUL << 0)

/* I2C SR1 bit definitions */
#define I2C_SR1_SB          (1UL << 0)
#define I2C_SR1_ADDR        (1UL << 1)
#define I2C_SR1_BTF         (1UL << 2)
#define I2C_SR1_RXNE        (1UL << 6)
#define I2C_SR1_TXE         (1UL << 7)
#define I2C_SR1_AF          (1UL << 10)

/* I2C SR2 bit definitions */
#define I2C_SR2_BUSY        (1UL << 1)

/* Initialize I2C peripheral in master mode */
static inline void i2c_init(I2C_TypeDef *i2c, uint32_t speed)
{
    /* Reset I2C */
    i2c->CR1 = I2C_CR1_SWRST;
    i2c->CR1 = 0;

    /* Set peripheral clock frequency (assume 16MHz APB1) */
    i2c->CR2 = 16;

    /* Set clock control register for standard/fast mode */
    if (speed <= 100000) {
        /* Standard mode: Thigh = Tlow = CCR * Tpclk1 */
        i2c->CCR = 80;     /* 16MHz / (2 * 100kHz) = 80 */
        i2c->TRISE = 17;   /* (1000ns / 62.5ns) + 1 = 17 */
    } else {
        /* Fast mode: CCR for 400kHz */
        i2c->CCR = (1 << 15) | 14;  /* Fast mode, CCR=14 */
        i2c->TRISE = 6;
    }

    /* Enable I2C */
    i2c->CR1 = I2C_CR1_PE;
}

/* Wait for flag with timeout */
static inline int i2c_wait_flag(volatile uint32_t *reg, uint32_t flag, int set)
{
    volatile int timeout = 100000;
    if (set) {
        while (!(*reg & flag) && timeout > 0) timeout--;
    } else {
        while ((*reg & flag) && timeout > 0) timeout--;
    }
    return timeout > 0 ? 0 : -1;
}

/* I2C master write */
static inline int i2c_write(I2C_TypeDef *i2c, uint8_t addr, const uint8_t *data, int len)
{
    /* Generate START */
    i2c->CR1 |= I2C_CR1_START;
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_SB, 1) < 0) return -1;

    /* Send address (write) */
    i2c->DR = (addr << 1) | 0;
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_ADDR, 1) < 0) return -1;
    (void)i2c->SR2;  /* Clear ADDR flag */

    /* Send data */
    for (int i = 0; i < len; i++) {
        if (i2c_wait_flag(&i2c->SR1, I2C_SR1_TXE, 1) < 0) return -1;
        i2c->DR = data[i];
    }

    /* Wait for last byte transfer */
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_BTF, 1) < 0) return -1;

    /* Generate STOP */
    i2c->CR1 |= I2C_CR1_STOP;

    return 0;
}

/* I2C master write then read (repeated start) */
static inline int i2c_write_read(I2C_TypeDef *i2c, uint8_t addr,
                                  const uint8_t *tx_data, int tx_len,
                                  uint8_t *rx_data, int rx_len)
{
    /* Generate START */
    i2c->CR1 |= I2C_CR1_START;
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_SB, 1) < 0) return -1;

    /* Send address (write) */
    i2c->DR = (addr << 1) | 0;
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_ADDR, 1) < 0) return -1;
    (void)i2c->SR2;

    /* Send TX data */
    for (int i = 0; i < tx_len; i++) {
        if (i2c_wait_flag(&i2c->SR1, I2C_SR1_TXE, 1) < 0) return -1;
        i2c->DR = tx_data[i];
    }
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_BTF, 1) < 0) return -1;

    /* Repeated START */
    i2c->CR1 |= I2C_CR1_START;
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_SB, 1) < 0) return -1;

    /* Send address (read) */
    i2c->DR = (addr << 1) | 1;
    if (i2c_wait_flag(&i2c->SR1, I2C_SR1_ADDR, 1) < 0) return -1;

    if (rx_len > 1) {
        i2c->CR1 |= I2C_CR1_ACK;
    } else {
        i2c->CR1 &= ~I2C_CR1_ACK;
    }
    (void)i2c->SR2;

    /* Read data */
    for (int i = 0; i < rx_len; i++) {
        if (i == rx_len - 1) {
            i2c->CR1 &= ~I2C_CR1_ACK;
            i2c->CR1 |= I2C_CR1_STOP;
        }
        if (i2c_wait_flag(&i2c->SR1, I2C_SR1_RXNE, 1) < 0) return -1;
        rx_data[i] = i2c->DR;
    }

    return rx_len;
}

#endif /* STM32F4_I2C_H */
