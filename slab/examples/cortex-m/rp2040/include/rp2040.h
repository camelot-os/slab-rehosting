/*
 * RP2040 Minimal Register Definitions
 *
 * Bare-metal register definitions for RP2040 SoC peripherals.
 * Only includes registers and bit fields used by firmware examples.
 * I2C controller is based on the Synopsys DesignWare I2C.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 TwistedWires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef RP2040_H
#define RP2040_H

#include <stdint.h>

/* ============================================================================
 * Base Addresses
 * ============================================================================ */

#define I2C0_BASE           0x40044000UL
#define I2C1_BASE           0x40048000UL
#define RESETS_BASE         0x4000C000UL

/* ============================================================================
 * RESETS - Subsystem Reset Control
 * ============================================================================ */

typedef struct {
    volatile uint32_t RESET;            /* 0x00 - Reset control */
    volatile uint32_t WDSEL;            /* 0x04 - Watchdog select */
    volatile uint32_t RESET_DONE;       /* 0x08 - Reset done status */
} RESETS_TypeDef;

/* RESETS bit definitions */
#define RESETS_I2C0         (1UL << 3)
#define RESETS_I2C1         (1UL << 4)

/* ============================================================================
 * I2C - Synopsys DesignWare I2C Controller
 * ============================================================================ */

typedef struct {
    volatile uint32_t CON;              /* 0x00 - Control register */
    volatile uint32_t TAR;              /* 0x04 - Target address */
    volatile uint32_t SAR;              /* 0x08 - Slave address */
    uint32_t RESERVED0;                 /* 0x0C */
    volatile uint32_t DATA_CMD;         /* 0x10 - Data/command register */
    volatile uint32_t SS_SCL_HCNT;      /* 0x14 - Standard speed SCL high count */
    volatile uint32_t SS_SCL_LCNT;      /* 0x18 - Standard speed SCL low count */
    volatile uint32_t FS_SCL_HCNT;      /* 0x1C - Fast speed SCL high count */
    volatile uint32_t FS_SCL_LCNT;      /* 0x20 - Fast speed SCL low count */
    uint32_t RESERVED1[2];              /* 0x24-0x28 */
    volatile uint32_t INTR_STAT;        /* 0x2C - Interrupt status */
    volatile uint32_t INTR_MASK;        /* 0x30 - Interrupt mask */
    volatile uint32_t RAW_INTR_STAT;    /* 0x34 - Raw interrupt status */
    volatile uint32_t RX_TL;            /* 0x38 - Receive FIFO threshold */
    volatile uint32_t TX_TL;            /* 0x3C - Transmit FIFO threshold */
    volatile uint32_t CLR_INTR;         /* 0x40 - Clear combined interrupt */
    volatile uint32_t CLR_RX_UNDER;     /* 0x44 */
    volatile uint32_t CLR_RX_OVER;      /* 0x48 */
    volatile uint32_t CLR_TX_OVER;      /* 0x4C */
    volatile uint32_t CLR_RD_REQ;       /* 0x50 */
    volatile uint32_t CLR_TX_ABRT;      /* 0x54 - Clear TX abort */
    volatile uint32_t CLR_RX_DONE;      /* 0x58 */
    volatile uint32_t CLR_ACTIVITY;     /* 0x5C */
    volatile uint32_t CLR_STOP_DET;     /* 0x60 */
    volatile uint32_t CLR_START_DET;    /* 0x64 */
    volatile uint32_t CLR_GEN_CALL;     /* 0x68 */
    volatile uint32_t ENABLE;           /* 0x6C - Enable register */
    volatile uint32_t STATUS;           /* 0x70 - Status register */
    volatile uint32_t TXFLR;            /* 0x74 - TX FIFO level */
    volatile uint32_t RXFLR;            /* 0x78 - RX FIFO level */
    volatile uint32_t SDA_HOLD;         /* 0x7C - SDA hold time */
    volatile uint32_t TX_ABRT_SOURCE;   /* 0x80 */
} I2C_TypeDef;

/* I2C CON register bit definitions */
#define I2C_CON_MASTER_MODE     (1UL << 0)
#define I2C_CON_SPEED_Pos       1
#define I2C_CON_SPEED_STD       (1UL << 1)   /* Standard mode (100kHz) */
#define I2C_CON_SPEED_FAST      (2UL << 1)   /* Fast mode (400kHz) */
#define I2C_CON_10BITADDR_SLAVE (1UL << 3)
#define I2C_CON_10BITADDR_MASTER (1UL << 4)
#define I2C_CON_RESTART_EN      (1UL << 5)
#define I2C_CON_SLAVE_DISABLE   (1UL << 6)
#define I2C_CON_STOP_DET_IFADDR (1UL << 7)
#define I2C_CON_TX_EMPTY_CTRL   (1UL << 8)

/* I2C ENABLE register */
#define I2C_ENABLE_ENABLE       (1UL << 0)

/* I2C STATUS register bit definitions */
#define I2C_STATUS_ACTIVITY     (1UL << 0)
#define I2C_STATUS_TFNF         (1UL << 1)   /* TX FIFO not full */
#define I2C_STATUS_TFE          (1UL << 2)   /* TX FIFO empty */
#define I2C_STATUS_RFNE         (1UL << 3)   /* RX FIFO not empty */
#define I2C_STATUS_RFF          (1UL << 4)   /* RX FIFO full */

/* I2C DATA_CMD register bit definitions */
#define I2C_DATA_CMD_DAT_Msk    (0xFFUL << 0)
#define I2C_DATA_CMD_CMD_READ   (1UL << 8)   /* 1=read, 0=write */
#define I2C_DATA_CMD_STOP       (1UL << 9)
#define I2C_DATA_CMD_RESTART    (1UL << 10)

/* I2C RAW_INTR_STAT bit definitions */
#define I2C_INT_RX_UNDER       (1UL << 0)
#define I2C_INT_RX_OVER        (1UL << 1)
#define I2C_INT_RX_FULL        (1UL << 2)
#define I2C_INT_TX_OVER        (1UL << 3)
#define I2C_INT_TX_EMPTY       (1UL << 4)
#define I2C_INT_RD_REQ         (1UL << 5)
#define I2C_INT_TX_ABRT        (1UL << 6)
#define I2C_INT_ACTIVITY       (1UL << 8)
#define I2C_INT_STOP_DET       (1UL << 9)
#define I2C_INT_START_DET      (1UL << 10)

/* ============================================================================
 * Peripheral Instances
 * ============================================================================ */

#define RESETS  ((RESETS_TypeDef *)RESETS_BASE)
#define I2C0    ((I2C_TypeDef *)I2C0_BASE)
#define I2C1    ((I2C_TypeDef *)I2C1_BASE)

#endif /* RP2040_H */
