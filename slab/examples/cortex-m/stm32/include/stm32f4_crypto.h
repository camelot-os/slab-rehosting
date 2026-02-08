/*
 * STM32F4 CRYP and HASH Peripheral Definitions
 *
 * Minimal register definitions and helper functions for the
 * STM32F4xx hardware crypto (CRYP) and hash (HASH) accelerators.
 * Only includes registers and operations used by firmware examples.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef STM32F4_CRYPTO_H
#define STM32F4_CRYPTO_H

#include <stdint.h>
#include "stm32f4.h"

/* ============================================================================
 * CRYP - Cryptographic Processor
 * Base: 0x50060000
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR;           /* 0x00 - Control register */
    volatile uint32_t SR;           /* 0x04 - Status register */
    volatile uint32_t DIN;          /* 0x08 - Data input register */
    volatile uint32_t DOUT;         /* 0x0C - Data output register */
    volatile uint32_t DMACR;        /* 0x10 - DMA control register */
    volatile uint32_t IMSCR;        /* 0x14 - Interrupt mask set/clear */
    volatile uint32_t RISR;         /* 0x18 - Raw interrupt status */
    volatile uint32_t MISR;         /* 0x1C - Masked interrupt status */
    volatile uint32_t K0LR;         /* 0x20 - Key 0 left */
    volatile uint32_t K0RR;         /* 0x24 - Key 0 right */
    volatile uint32_t K1LR;         /* 0x28 - Key 1 left */
    volatile uint32_t K1RR;         /* 0x2C - Key 1 right */
    volatile uint32_t K2LR;         /* 0x30 - Key 2 left */
    volatile uint32_t K2RR;         /* 0x34 - Key 2 right */
    volatile uint32_t K3LR;         /* 0x38 - Key 3 left */
    volatile uint32_t K3RR;         /* 0x3C - Key 3 right */
    volatile uint32_t IV0LR;        /* 0x40 - Init vector 0 left */
    volatile uint32_t IV0RR;        /* 0x44 - Init vector 0 right */
    volatile uint32_t IV1LR;        /* 0x48 - Init vector 1 left */
    volatile uint32_t IV1RR;        /* 0x4C - Init vector 1 right */
} CRYP_TypeDef;

#define CRYP    ((CRYP_TypeDef *)CRYP_BASE)

/* CRYP CR bit definitions */
#define CRYP_CR_ALGODIR         (1UL << 2)      /* 0=encrypt, 1=decrypt */
#define CRYP_CR_ALGOMODE_Pos    3
#define CRYP_CR_ALGOMODE_Msk    (7UL << 3)
#define CRYP_CR_DATATYPE_Pos    6
#define CRYP_CR_KEYSIZE_Pos     8
#define CRYP_CR_KEYSIZE_Msk     (3UL << 8)
#define CRYP_CR_CRYPEN          (1UL << 15)      /* Crypto enable */

/* CRYP SR bit definitions */
#define CRYP_SR_IFEM            (1UL << 0)       /* Input FIFO empty */
#define CRYP_SR_IFNF            (1UL << 1)       /* Input FIFO not full */
#define CRYP_SR_OFNE            (1UL << 2)       /* Output FIFO not empty */
#define CRYP_SR_BUSY            (1UL << 4)       /* Busy */

/* Algorithm mode constants */
#define CRYP_ALGOMODE_TDES_ECB  0x00
#define CRYP_ALGOMODE_TDES_CBC  0x01
#define CRYP_ALGOMODE_DES_ECB   0x02
#define CRYP_ALGOMODE_DES_CBC   0x03
#define CRYP_ALGOMODE_AES_ECB   0x04
#define CRYP_ALGOMODE_AES_CBC   0x05
#define CRYP_ALGOMODE_AES_CTR   0x06

/* Key size constants */
#define CRYP_KEYSIZE_128        0x00
#define CRYP_KEYSIZE_192        0x01
#define CRYP_KEYSIZE_256        0x02

/* ============================================================================
 * HASH - Hash Processor
 * Base: 0x50060400
 * ============================================================================ */

typedef struct {
    volatile uint32_t CR;           /* 0x00 - Control register */
    volatile uint32_t DIN;          /* 0x04 - Data input register */
    volatile uint32_t STR;          /* 0x08 - Start register */
    volatile uint32_t HR[5];        /* 0x0C-0x1C - Digest registers (SHA-1/MD5) */
    volatile uint32_t IMR;          /* 0x20 - Interrupt enable */
    volatile uint32_t SR;           /* 0x24 - Status register */
    uint32_t RESERVED[52];          /* 0x28-0xF4 */
    volatile uint32_t CSR[54];      /* 0xF8-0x1CC - Context swap */
    uint32_t RESERVED2[80];         /* padding to 0x310 */
    volatile uint32_t HR_LONG[8];   /* 0x310-0x32C - SHA-256 digest */
} HASH_TypeDef;

#define HASH    ((HASH_TypeDef *)HASH_BASE)

/* HASH CR bit definitions */
#define HASH_CR_INIT            (1UL << 2)
#define HASH_CR_DMAE            (1UL << 3)
#define HASH_CR_DATATYPE_Pos    4
#define HASH_CR_MODE            (1UL << 6)       /* 0=hash, 1=HMAC */
#define HASH_CR_ALGO_Pos        7
#define HASH_CR_ALGO_0          (1UL << 7)
#define HASH_CR_ALGO_1          (1UL << 18)
#define HASH_CR_NBW_Pos         8

/* HASH STR bit definitions */
#define HASH_STR_NBLW_Pos       0
#define HASH_STR_DCAL           (1UL << 8)       /* Digest calculation */

/* HASH SR bit definitions */
#define HASH_SR_DINIS           (1UL << 0)       /* Data input interrupt status */
#define HASH_SR_DCIS            (1UL << 1)       /* Digest calculation complete */
#define HASH_SR_BUSY            (1UL << 3)

/* Algorithm selection */
#define HASH_CR_ALGO_SHA1       0x00
#define HASH_CR_ALGO_MD5        HASH_CR_ALGO_0
#define HASH_CR_ALGO_SHA256     HASH_CR_ALGO_1

/* ============================================================================
 * CRYP Helper Functions
 * ============================================================================ */

static inline void cryp_aes_init(uint32_t keysize, uint32_t algomode, int encrypt)
{
    uint32_t cr = 0;
    cr |= (keysize << CRYP_CR_KEYSIZE_Pos);
    cr |= (algomode << CRYP_CR_ALGOMODE_Pos);
    cr |= (0x02 << CRYP_CR_DATATYPE_Pos);  /* 8-bit data type (byte swap) */
    if (!encrypt) {
        cr |= CRYP_CR_ALGODIR;
    }
    CRYP->CR = cr;
}

static inline void cryp_set_key_128(const uint8_t *key)
{
    CRYP->K2LR = ((uint32_t)key[0] << 24) | ((uint32_t)key[1] << 16) |
                  ((uint32_t)key[2] << 8) | key[3];
    CRYP->K2RR = ((uint32_t)key[4] << 24) | ((uint32_t)key[5] << 16) |
                  ((uint32_t)key[6] << 8) | key[7];
    CRYP->K3LR = ((uint32_t)key[8] << 24) | ((uint32_t)key[9] << 16) |
                  ((uint32_t)key[10] << 8) | key[11];
    CRYP->K3RR = ((uint32_t)key[12] << 24) | ((uint32_t)key[13] << 16) |
                  ((uint32_t)key[14] << 8) | key[15];
}

static inline void cryp_enable(void)
{
    CRYP->CR |= CRYP_CR_CRYPEN;
}

static inline void cryp_disable(void)
{
    CRYP->CR &= ~CRYP_CR_CRYPEN;
}

static inline void cryp_process_block(const uint8_t *in, uint8_t *out)
{
    /* Wait for input FIFO not full, then write 4 words (16 bytes) */
    for (int i = 0; i < 4; i++) {
        while (!(CRYP->SR & CRYP_SR_IFNF));
        CRYP->DIN = ((uint32_t)in[i*4] << 24) | ((uint32_t)in[i*4+1] << 16) |
                     ((uint32_t)in[i*4+2] << 8) | in[i*4+3];
    }

    /* Wait for output FIFO not empty, then read 4 words */
    for (int i = 0; i < 4; i++) {
        while (!(CRYP->SR & CRYP_SR_OFNE));
        uint32_t word = CRYP->DOUT;
        out[i*4]   = (word >> 24) & 0xFF;
        out[i*4+1] = (word >> 16) & 0xFF;
        out[i*4+2] = (word >> 8) & 0xFF;
        out[i*4+3] = word & 0xFF;
    }
}

/* ============================================================================
 * HASH Helper Functions
 * ============================================================================ */

static inline void hash_init(uint32_t algo)
{
    HASH->CR = HASH_CR_INIT | algo | (0x02 << HASH_CR_DATATYPE_Pos);
}

static inline void hash_write_data(uint32_t word)
{
    HASH->DIN = word;
}

static inline void hash_finalize(int remaining_bits)
{
    HASH->STR = (remaining_bits & 0x1F) << HASH_STR_NBLW_Pos;
    HASH->STR |= HASH_STR_DCAL;

    /* Wait for digest calculation to complete */
    while (HASH->SR & HASH_SR_BUSY);
}

static inline void hash_read_sha256(uint8_t *digest)
{
    for (int i = 0; i < 8; i++) {
        uint32_t word = HASH->HR_LONG[i];
        digest[i*4]   = (word >> 24) & 0xFF;
        digest[i*4+1] = (word >> 16) & 0xFF;
        digest[i*4+2] = (word >> 8) & 0xFF;
        digest[i*4+3] = word & 0xFF;
    }
}

static inline void hash_read_md5(uint8_t *digest)
{
    for (int i = 0; i < 4; i++) {
        uint32_t word = HASH->HR[i];
        digest[i*4]   = (word >> 24) & 0xFF;
        digest[i*4+1] = (word >> 16) & 0xFF;
        digest[i*4+2] = (word >> 8) & 0xFF;
        digest[i*4+3] = word & 0xFF;
    }
}

#endif /* STM32F4_CRYPTO_H */
