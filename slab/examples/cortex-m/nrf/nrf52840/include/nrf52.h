/*
 * NRF52840 Minimal Register Definitions
 *
 * Bare-metal register definitions for nRF52840 SoC peripherals.
 * Only includes registers and bit fields used by firmware examples.
 * Register offsets verified against nRF52840 Product Specification v1.7.
 *
 * Author: Mathieu Renard <mathieu.renard@twistedwires.io>
 * Copyright (C) 2025 Twisted Wires Security Lab
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#ifndef NRF52_H
#define NRF52_H

#include <stdint.h>

/* ============================================================================
 * Base Addresses
 * ============================================================================ */

#define CLOCK_BASE          0x40000000UL
#define TWIM0_BASE          0x40003000UL
#define SPIM3_BASE          0x4002F000UL
#define QSPI_BASE           0x40029000UL

/* ============================================================================
 * CLOCK
 * Offsets: TASKS_HFCLKSTART=0x000, EVENTS_HFCLKSTARTED=0x100
 * ============================================================================ */

typedef struct {
    volatile uint32_t TASKS_HFCLKSTART;     /* 0x000 */
    volatile uint32_t TASKS_HFCLKSTOP;      /* 0x004 */
    volatile uint32_t TASKS_LFCLKSTART;     /* 0x008 */
    volatile uint32_t TASKS_LFCLKSTOP;      /* 0x00C */
    uint32_t RESERVED0[60];                 /* 0x010-0x0FC (60 words) */
    volatile uint32_t EVENTS_HFCLKSTARTED;  /* 0x100 */
    volatile uint32_t EVENTS_LFCLKSTARTED;  /* 0x104 */
} NRF_CLOCK_TypeDef;

/* ============================================================================
 * TWIM - Two-Wire Interface Master with EasyDMA
 *
 * Key offsets from base:
 *   TASKS_STARTRX=0x000, TASKS_STARTTX=0x008, TASKS_STOP=0x014
 *   EVENTS_STOPPED=0x104, EVENTS_ERROR=0x124
 *   EVENTS_LASTRX=0x15C, EVENTS_LASTTX=0x160
 *   SHORTS=0x200, ERRORSRC=0x4C4, ENABLE=0x500
 *   PSEL.SCL=0x508, PSEL.SDA=0x50C, FREQUENCY=0x524
 *   RXD.PTR=0x534, RXD.MAXCNT=0x538, RXD.AMOUNT=0x53C, RXD.LIST=0x540
 *   TXD.PTR=0x544, TXD.MAXCNT=0x548, TXD.AMOUNT=0x54C, TXD.LIST=0x550
 *   ADDRESS=0x588
 * ============================================================================ */

typedef struct {
    volatile uint32_t TASKS_STARTRX;    /* 0x000 */
    uint32_t RESERVED0;                 /* 0x004 */
    volatile uint32_t TASKS_STARTTX;    /* 0x008 */
    uint32_t RESERVED1[2];              /* 0x00C-0x010 */
    volatile uint32_t TASKS_STOP;       /* 0x014 */
    uint32_t RESERVED2;                 /* 0x018 */
    volatile uint32_t TASKS_SUSPEND;    /* 0x01C */
    volatile uint32_t TASKS_RESUME;     /* 0x020 */
    uint32_t RESERVED3[56];             /* 0x024-0x100 */
    volatile uint32_t EVENTS_STOPPED;   /* 0x104 */
    uint32_t RESERVED4[7];              /* 0x108-0x120 */
    volatile uint32_t EVENTS_ERROR;     /* 0x124 */
    uint32_t RESERVED5[8];              /* 0x128-0x144 */
    volatile uint32_t EVENTS_SUSPENDED; /* 0x148 */
    volatile uint32_t EVENTS_RXSTARTED; /* 0x14C */
    volatile uint32_t EVENTS_TXSTARTED; /* 0x150 */
    uint32_t RESERVED6[2];              /* 0x154-0x158 */
    volatile uint32_t EVENTS_LASTRX;    /* 0x15C */
    volatile uint32_t EVENTS_LASTTX;    /* 0x160 */
    uint32_t RESERVED7[39];             /* 0x164-0x1FC */
    volatile uint32_t SHORTS;           /* 0x200 */
    uint32_t RESERVED8[63];             /* 0x204-0x2FC */
    volatile uint32_t INTEN;            /* 0x300 */
    volatile uint32_t INTENSET;         /* 0x304 */
    volatile uint32_t INTENCLR;         /* 0x308 */
    uint32_t RESERVED9[110];            /* 0x30C-0x4C0 */
    volatile uint32_t ERRORSRC;         /* 0x4C4 */
    uint32_t RESERVED10[14];            /* 0x4C8-0x4FC */
    volatile uint32_t ENABLE;           /* 0x500 */
    uint32_t RESERVED11;                /* 0x504 */
    volatile uint32_t PSEL_SCL;         /* 0x508 */
    volatile uint32_t PSEL_SDA;         /* 0x50C */
    uint32_t RESERVED12[5];             /* 0x510-0x520 */
    volatile uint32_t FREQUENCY;        /* 0x524 */
    uint32_t RESERVED13[3];             /* 0x528-0x530 */
    volatile uint32_t RXD_PTR;          /* 0x534 */
    volatile uint32_t RXD_MAXCNT;       /* 0x538 */
    volatile uint32_t RXD_AMOUNT;       /* 0x53C */
    volatile uint32_t RXD_LIST;         /* 0x540 */
    volatile uint32_t TXD_PTR;          /* 0x544 */
    volatile uint32_t TXD_MAXCNT;       /* 0x548 */
    volatile uint32_t TXD_AMOUNT;       /* 0x54C */
    volatile uint32_t TXD_LIST;         /* 0x550 */
    uint32_t RESERVED14[13];            /* 0x554-0x584 */
    volatile uint32_t ADDRESS;          /* 0x588 */
} NRF_TWIM_TypeDef;

/* TWIM FREQUENCY values */
#define TWIM_FREQUENCY_100K     0x01980000UL
#define TWIM_FREQUENCY_250K     0x04000000UL
#define TWIM_FREQUENCY_400K     0x06680000UL

/* TWIM ENABLE values */
#define TWIM_ENABLE_DISABLED    0x00
#define TWIM_ENABLE_ENABLED     0x06

/* TWIM SHORTS bit definitions */
#define TWIM_SHORTS_LASTTX_STARTRX  (1UL << 7)
#define TWIM_SHORTS_LASTTX_SUSPEND  (1UL << 8)
#define TWIM_SHORTS_LASTTX_STOP     (1UL << 9)
#define TWIM_SHORTS_LASTRX_STARTTX  (1UL << 10)
#define TWIM_SHORTS_LASTRX_STOP     (1UL << 12)

/* ============================================================================
 * SPIM - SPI Master with EasyDMA
 *
 * Key offsets from base:
 *   TASKS_START=0x010, TASKS_STOP=0x014
 *   EVENTS_STOPPED=0x104, EVENTS_END=0x118, EVENTS_STARTED=0x14C
 *   ENABLE=0x500
 *   PSEL.SCK=0x508, PSEL.MOSI=0x50C, PSEL.MISO=0x510, PSEL.CSN=0x514
 *   FREQUENCY=0x524
 *   RXD.PTR=0x534, RXD.MAXCNT=0x538
 *   TXD.PTR=0x544, TXD.MAXCNT=0x548
 *   CONFIG=0x554, ORC=0x5C0
 * ============================================================================ */

typedef struct {
    uint32_t RESERVED0[4];              /* 0x000-0x00C */
    volatile uint32_t TASKS_START;      /* 0x010 */
    volatile uint32_t TASKS_STOP;       /* 0x014 */
    uint32_t RESERVED1;                 /* 0x018 */
    volatile uint32_t TASKS_SUSPEND;    /* 0x01C */
    volatile uint32_t TASKS_RESUME;     /* 0x020 */
    uint32_t RESERVED2[56];             /* 0x024-0x100 */
    volatile uint32_t EVENTS_STOPPED;   /* 0x104 */
    uint32_t RESERVED3[2];              /* 0x108-0x10C */
    volatile uint32_t EVENTS_ENDRX;     /* 0x110 */
    uint32_t RESERVED4;                 /* 0x114 */
    volatile uint32_t EVENTS_END;       /* 0x118 */
    uint32_t RESERVED5;                 /* 0x11C */
    volatile uint32_t EVENTS_ENDTX;     /* 0x120 */
    uint32_t RESERVED6[10];             /* 0x124-0x148 */
    volatile uint32_t EVENTS_STARTED;   /* 0x14C */
    uint32_t RESERVED7[44];             /* 0x150-0x1FC */
    volatile uint32_t SHORTS;           /* 0x200 */
    uint32_t RESERVED8[63];             /* 0x204-0x2FC */
    volatile uint32_t INTEN;            /* 0x300 */
    volatile uint32_t INTENSET;         /* 0x304 */
    volatile uint32_t INTENCLR;         /* 0x308 */
    uint32_t RESERVED9[61];             /* 0x30C-0x3FC */
    volatile uint32_t STALLSTAT;        /* 0x400 */
    uint32_t RESERVED10[63];            /* 0x404-0x4FC */
    volatile uint32_t ENABLE;           /* 0x500 */
    uint32_t RESERVED11;                /* 0x504 */
    volatile uint32_t PSEL_SCK;         /* 0x508 */
    volatile uint32_t PSEL_MOSI;        /* 0x50C */
    volatile uint32_t PSEL_MISO;        /* 0x510 */
    volatile uint32_t PSEL_CSN;         /* 0x514 */
    uint32_t RESERVED12[3];             /* 0x518-0x520 */
    volatile uint32_t FREQUENCY;        /* 0x524 */
    uint32_t RESERVED13[3];             /* 0x528-0x530 */
    volatile uint32_t RXD_PTR;          /* 0x534 */
    volatile uint32_t RXD_MAXCNT;       /* 0x538 */
    volatile uint32_t RXD_AMOUNT;       /* 0x53C */
    volatile uint32_t RXD_LIST;         /* 0x540 */
    volatile uint32_t TXD_PTR;          /* 0x544 */
    volatile uint32_t TXD_MAXCNT;       /* 0x548 */
    volatile uint32_t TXD_AMOUNT;       /* 0x54C */
    volatile uint32_t TXD_LIST;         /* 0x550 */
    volatile uint32_t CONFIG;           /* 0x554 */
    uint32_t RESERVED14[2];             /* 0x558-0x55C */
    volatile uint32_t IFTIMING_RXDELAY; /* 0x560 */
    volatile uint32_t IFTIMING_CSNDUR;  /* 0x564 */
    volatile uint32_t CSNPOL;           /* 0x568 */
    volatile uint32_t PSELDCX;          /* 0x56C */
    volatile uint32_t DCXCNT;           /* 0x570 */
    uint32_t RESERVED15[19];            /* 0x574-0x5BC */
    volatile uint32_t ORC;              /* 0x5C0 */
} NRF_SPIM_TypeDef;

/* SPIM FREQUENCY values */
#define SPIM_FREQUENCY_125K     0x02000000UL
#define SPIM_FREQUENCY_250K     0x04000000UL
#define SPIM_FREQUENCY_500K     0x08000000UL
#define SPIM_FREQUENCY_1M       0x10000000UL
#define SPIM_FREQUENCY_2M       0x20000000UL
#define SPIM_FREQUENCY_4M       0x40000000UL
#define SPIM_FREQUENCY_8M       0x80000000UL

/* SPIM ENABLE values */
#define SPIM_ENABLE_DISABLED    0x00
#define SPIM_ENABLE_ENABLED     0x07

/* SPIM CONFIG bit definitions */
#define SPIM_CONFIG_ORDER_MSBFIRST  (0UL << 0)
#define SPIM_CONFIG_ORDER_LSBFIRST  (1UL << 0)
#define SPIM_CONFIG_CPHA_LEADING    (0UL << 1)
#define SPIM_CONFIG_CPHA_TRAILING   (1UL << 1)
#define SPIM_CONFIG_CPOL_LOW        (0UL << 2)
#define SPIM_CONFIG_CPOL_HIGH       (1UL << 2)

/* ============================================================================
 * QSPI - Quad SPI Interface
 *
 * Key offsets from base:
 *   TASKS_ACTIVATE=0x000, TASKS_READSTART=0x004, TASKS_WRITESTART=0x008
 *   TASKS_ERASESTART=0x00C, EVENTS_READY=0x100, ENABLE=0x500
 *   READ.SRC=0x508, WRITE.DST=0x518, ERASE.PTR=0x528
 *   PSEL.SCK=0x540, IFCONFIG0=0x564, IFCONFIG1=0x620
 *   CINSTRCONF=0x654, CINSTRDAT0=0x658, CINSTRDAT1=0x65C
 * ============================================================================ */

typedef struct {
    volatile uint32_t TASKS_ACTIVATE;       /* 0x000 */
    volatile uint32_t TASKS_READSTART;      /* 0x004 */
    volatile uint32_t TASKS_WRITESTART;     /* 0x008 */
    volatile uint32_t TASKS_ERASESTART;     /* 0x00C */
    volatile uint32_t TASKS_DEACTIVATE;     /* 0x010 */
    uint32_t RESERVED0[59];                 /* 0x014-0x0FC */
    volatile uint32_t EVENTS_READY;         /* 0x100 */
    uint32_t RESERVED1[127];                /* 0x104-0x2FC */
    volatile uint32_t INTEN;                /* 0x300 */
    volatile uint32_t INTENSET;             /* 0x304 */
    volatile uint32_t INTENCLR;             /* 0x308 */
    uint32_t RESERVED2[125];                /* 0x30C-0x4FC */
    volatile uint32_t ENABLE;               /* 0x500 */
    uint32_t RESERVED3;                     /* 0x504 */
    volatile uint32_t READ_SRC;             /* 0x508 */
    volatile uint32_t READ_DST;             /* 0x50C */
    volatile uint32_t READ_CNT;             /* 0x510 */
    uint32_t RESERVED4;                     /* 0x514 */
    volatile uint32_t WRITE_DST;            /* 0x518 */
    volatile uint32_t WRITE_SRC;            /* 0x51C */
    volatile uint32_t WRITE_CNT;            /* 0x520 */
    uint32_t RESERVED5;                     /* 0x524 */
    volatile uint32_t ERASE_PTR;            /* 0x528 */
    volatile uint32_t ERASE_LEN;            /* 0x52C */
    uint32_t RESERVED6[4];                  /* 0x530-0x53C */
    volatile uint32_t PSEL_SCK;             /* 0x540 */
    volatile uint32_t PSEL_CSN;             /* 0x544 */
    uint32_t RESERVED7;                     /* 0x548 */
    volatile uint32_t PSEL_IO0;             /* 0x54C */
    volatile uint32_t PSEL_IO1;             /* 0x550 */
    volatile uint32_t PSEL_IO2;             /* 0x554 */
    volatile uint32_t PSEL_IO3;             /* 0x558 */
    uint32_t RESERVED8;                     /* 0x55C */
    volatile uint32_t XIPOFFSET;            /* 0x560 */
    volatile uint32_t IFCONFIG0;            /* 0x564 */
    uint32_t RESERVED9[46];                 /* 0x568-0x61C */
    volatile uint32_t IFCONFIG1;            /* 0x620 */
    volatile uint32_t STATUS;               /* 0x624 */
    uint32_t RESERVED10[3];                 /* 0x628-0x630 */
    volatile uint32_t DPMDUR;               /* 0x634 */
    uint32_t RESERVED11[3];                 /* 0x638-0x640 */
    volatile uint32_t ADDRCONF;             /* 0x644 */
    uint32_t RESERVED12[3];                 /* 0x648-0x650 */
    volatile uint32_t CINSTRCONF;           /* 0x654 */
    volatile uint32_t CINSTRDAT0;           /* 0x658 */
    volatile uint32_t CINSTRDAT1;           /* 0x65C */
    volatile uint32_t IFTIMING;             /* 0x660 */
} NRF_QSPI_TypeDef;

/* QSPI ENABLE values */
#define QSPI_ENABLE_DISABLED    0x00
#define QSPI_ENABLE_ENABLED     0x01

/* QSPI CINSTRCONF bit positions */
#define QSPI_CINSTRCONF_OPCODE_POS      0
#define QSPI_CINSTRCONF_LENGTH_POS      8

/* QSPI ERASE_LEN values */
#define QSPI_ERASE_LEN_4KB     0x00
#define QSPI_ERASE_LEN_64KB    0x01
#define QSPI_ERASE_LEN_ALL     0x02

/* ============================================================================
 * Peripheral Instances
 * ============================================================================ */

#define CLOCK   ((NRF_CLOCK_TypeDef *)CLOCK_BASE)
#define TWIM0   ((NRF_TWIM_TypeDef *)TWIM0_BASE)
#define SPIM3   ((NRF_SPIM_TypeDef *)SPIM3_BASE)
#define QSPI    ((NRF_QSPI_TypeDef *)QSPI_BASE)

#endif /* NRF52_H */
