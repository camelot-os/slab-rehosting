/*
 * STM32F4 SPI Register Bit Definitions
 *
 * Minimal SPI bit field definitions for STM32F4xx.
 * Only includes fields used by firmware examples.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef STM32F4_SPI_H
#define STM32F4_SPI_H

#include "stm32f4.h"

/* SPI CR1 bit definitions */
#define SPI_CR1_CPHA        (1UL << 0)
#define SPI_CR1_CPOL        (1UL << 1)
#define SPI_CR1_MSTR        (1UL << 2)
#define SPI_CR1_BR_DIV8     (2UL << 3)   /* Baud rate = fPCLK/8 */
#define SPI_CR1_SPE         (1UL << 6)
#define SPI_CR1_SSI         (1UL << 8)
#define SPI_CR1_SSM         (1UL << 9)

/* SPI CR2 bit definitions */
#define SPI_CR2_RXDMAEN     (1UL << 0)
#define SPI_CR2_TXDMAEN     (1UL << 1)

/* SPI SR bit definitions */
#define SPI_SR_RXNE         (1UL << 0)
#define SPI_SR_TXE          (1UL << 1)
#define SPI_SR_BSY          (1UL << 7)

#endif /* STM32F4_SPI_H */
