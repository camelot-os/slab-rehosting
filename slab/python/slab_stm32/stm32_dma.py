"""
STM32 DMA Controller Emulation

Implements:
- DMAv1 (F1xx): Channel-based DMA
- DMAv2 (F4/L4/H7): Stream-based DMA
- BDMA (H7): Basic DMA for D3 domain
- MDMA (H7): Master DMA

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, Dict
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32DMAv1(STM32Peripheral):
    """
    STM32F1xx DMA controller (channel-based).

    7 channels per controller, each with:
    - CCRx: Configuration register
    - CNDTRx: Number of data
    - CPARx: Peripheral address
    - CMARx: Memory address
    """

    ISR = 0x00    # Interrupt status
    IFCR = 0x04   # Interrupt flag clear

    # Per-channel offsets (channel 1 starts at 0x08)
    CHANNEL_OFFSET = 0x08
    CHANNEL_SIZE = 0x14

    CCR = 0x00
    CNDTR = 0x04
    CPAR = 0x08
    CMAR = 0x0C

    # CCR bits
    CCR_EN = 1 << 0
    CCR_TCIE = 1 << 1
    CCR_HTIE = 1 << 2
    CCR_TEIE = 1 << 3
    CCR_DIR = 1 << 4
    CCR_CIRC = 1 << 5
    CCR_PINC = 1 << 6
    CCR_MINC = 1 << 7
    CCR_PSIZE = 0x3 << 8
    CCR_MSIZE = 0x3 << 10
    CCR_PL = 0x3 << 12
    CCR_MEM2MEM = 1 << 14

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = 0x40020000 if index == 1 else 0x40020400

        super().__init__(f"DMA{index}", base, 0x400)
        self.index = index
        self.num_channels = 7

        # Interrupt status
        self.isr = 0

        # Per-channel registers
        self.channels = []
        for ch in range(self.num_channels):
            self.channels.append({
                'ccr': 0,
                'cndtr': 0,
                'cpar': 0,
                'cmar': 0,
                'count': 0,
            })

        # Memory access callbacks
        self.mem_read: Optional[Callable[[int, int], int]] = None
        self.mem_write: Optional[Callable[[int, int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ISR:
            return self.isr
        elif offset == self.IFCR:
            return 0  # Write-only

        # Channel registers
        if offset >= self.CHANNEL_OFFSET:
            ch_offset = offset - self.CHANNEL_OFFSET
            ch_idx = ch_offset // self.CHANNEL_SIZE
            reg_offset = ch_offset % self.CHANNEL_SIZE

            if ch_idx < self.num_channels:
                ch = self.channels[ch_idx]
                if reg_offset == self.CCR:
                    return ch['ccr']
                elif reg_offset == self.CNDTR:
                    return ch['count']
                elif reg_offset == self.CPAR:
                    return ch['cpar']
                elif reg_offset == self.CMAR:
                    return ch['cmar']

        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.IFCR:
            self.isr &= ~value
            return

        if offset >= self.CHANNEL_OFFSET:
            ch_offset = offset - self.CHANNEL_OFFSET
            ch_idx = ch_offset // self.CHANNEL_SIZE
            reg_offset = ch_offset % self.CHANNEL_SIZE

            if ch_idx < self.num_channels:
                ch = self.channels[ch_idx]
                if reg_offset == self.CCR:
                    old_ccr = ch['ccr']
                    ch['ccr'] = value
                    if (value & self.CCR_EN) and not (old_ccr & self.CCR_EN):
                        self._start_transfer(ch_idx)
                elif reg_offset == self.CNDTR:
                    ch['cndtr'] = value
                    ch['count'] = value
                elif reg_offset == self.CPAR:
                    ch['cpar'] = value
                elif reg_offset == self.CMAR:
                    ch['cmar'] = value

    def _start_transfer(self, ch_idx: int):
        """Start DMA transfer."""
        ch = self.channels[ch_idx]
        self.log.debug(f"DMA{self.index} CH{ch_idx+1} start: P=0x{ch['cpar']:08X} M=0x{ch['cmar']:08X} N={ch['cndtr']}")

    def do_transfer(self, ch_idx: int) -> bool:
        """Perform one DMA transfer. Returns True if transfer complete."""
        ch = self.channels[ch_idx]
        if not (ch['ccr'] & self.CCR_EN) or ch['count'] == 0:
            return True

        # Get data sizes
        psize = 1 << ((ch['ccr'] >> 8) & 0x3)
        msize = 1 << ((ch['ccr'] >> 10) & 0x3)

        if ch['ccr'] & self.CCR_DIR:
            # Memory to peripheral
            if self.mem_read and self.mem_write:
                data = self.mem_read(ch['cmar'], msize)
                self.mem_write(ch['cpar'], psize, data)
        else:
            # Peripheral to memory
            if self.mem_read and self.mem_write:
                data = self.mem_read(ch['cpar'], psize)
                self.mem_write(ch['cmar'], msize, data)

        # Update addresses
        if ch['ccr'] & self.CCR_PINC:
            ch['cpar'] += psize
        if ch['ccr'] & self.CCR_MINC:
            ch['cmar'] += msize

        ch['count'] -= 1

        # Check complete
        if ch['count'] == 0:
            if ch['ccr'] & self.CCR_CIRC:
                ch['count'] = ch['cndtr']
                ch['cpar'] = self.channels[ch_idx]['cpar']
                ch['cmar'] = self.channels[ch_idx]['cmar']
            else:
                ch['ccr'] &= ~self.CCR_EN
                self.isr |= (1 << (ch_idx * 4 + 1))  # TCIF
                return True

        return False


class STM32DMAv2(STM32Peripheral):
    """
    STM32F4/L4/H7 DMA controller (stream-based).

    8 streams per controller, each with request mux.
    """

    LISR = 0x00   # Low interrupt status
    HISR = 0x04   # High interrupt status
    LIFCR = 0x08  # Low interrupt flag clear
    HIFCR = 0x0C  # High interrupt flag clear

    STREAM_BASE = 0x10
    STREAM_SIZE = 0x18

    SxCR = 0x00
    SxNDTR = 0x04
    SxPAR = 0x08
    SxM0AR = 0x0C
    SxM1AR = 0x10
    SxFCR = 0x14

    # CR bits
    CR_EN = 1 << 0
    CR_DMEIE = 1 << 1
    CR_TEIE = 1 << 2
    CR_HTIE = 1 << 3
    CR_TCIE = 1 << 4
    CR_PFCTRL = 1 << 5
    CR_DIR = 0x3 << 6
    CR_CIRC = 1 << 8
    CR_PINC = 1 << 9
    CR_MINC = 1 << 10
    CR_PSIZE = 0x3 << 11
    CR_MSIZE = 0x3 << 13
    CR_PINCOS = 1 << 15
    CR_PL = 0x3 << 16
    CR_DBM = 1 << 18
    CR_CT = 1 << 19
    CR_PBURST = 0x3 << 21
    CR_MBURST = 0x3 << 23
    CR_CHSEL = 0x7 << 25

    DMA_BASES = {
        1: 0x40026000,
        2: 0x40026400,
    }

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = self.DMA_BASES.get(index, 0x40026000)

        super().__init__(f"DMA{index}", base, 0x400)
        self.index = index
        self.num_streams = 8

        # Interrupt status
        self.lisr = 0
        self.hisr = 0

        # Per-stream registers
        self.streams = []
        for s in range(self.num_streams):
            self.streams.append({
                'cr': 0,
                'ndtr': 0,
                'par': 0,
                'm0ar': 0,
                'm1ar': 0,
                'fcr': 0x21,
                'count': 0,
            })

        self.mem_read: Optional[Callable[[int, int], int]] = None
        self.mem_write: Optional[Callable[[int, int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.LISR:
            return self.lisr
        elif offset == self.HISR:
            return self.hisr
        elif offset == self.LIFCR:
            return 0
        elif offset == self.HIFCR:
            return 0

        if offset >= self.STREAM_BASE:
            s_offset = offset - self.STREAM_BASE
            s_idx = s_offset // self.STREAM_SIZE
            reg_offset = s_offset % self.STREAM_SIZE

            if s_idx < self.num_streams:
                s = self.streams[s_idx]
                if reg_offset == self.SxCR:
                    return s['cr']
                elif reg_offset == self.SxNDTR:
                    return s['count']
                elif reg_offset == self.SxPAR:
                    return s['par']
                elif reg_offset == self.SxM0AR:
                    return s['m0ar']
                elif reg_offset == self.SxM1AR:
                    return s['m1ar']
                elif reg_offset == self.SxFCR:
                    return s['fcr']

        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.LIFCR:
            self.lisr &= ~value
            return
        elif offset == self.HIFCR:
            self.hisr &= ~value
            return

        if offset >= self.STREAM_BASE:
            s_offset = offset - self.STREAM_BASE
            s_idx = s_offset // self.STREAM_SIZE
            reg_offset = s_offset % self.STREAM_SIZE

            if s_idx < self.num_streams:
                s = self.streams[s_idx]
                if reg_offset == self.SxCR:
                    old_cr = s['cr']
                    s['cr'] = value
                    if (value & self.CR_EN) and not (old_cr & self.CR_EN):
                        self._start_transfer(s_idx)
                elif reg_offset == self.SxNDTR:
                    s['ndtr'] = value & 0xFFFF
                    s['count'] = value & 0xFFFF
                elif reg_offset == self.SxPAR:
                    s['par'] = value
                elif reg_offset == self.SxM0AR:
                    s['m0ar'] = value
                elif reg_offset == self.SxM1AR:
                    s['m1ar'] = value
                elif reg_offset == self.SxFCR:
                    s['fcr'] = value

    def _start_transfer(self, s_idx: int):
        s = self.streams[s_idx]
        self.log.debug(f"DMA{self.index} S{s_idx} start")

    def do_transfer(self, s_idx: int) -> bool:
        """Perform one DMA transfer."""
        s = self.streams[s_idx]
        if not (s['cr'] & self.CR_EN) or s['count'] == 0:
            return True

        psize = 1 << ((s['cr'] >> 11) & 0x3)
        msize = 1 << ((s['cr'] >> 13) & 0x3)
        direction = (s['cr'] >> 6) & 0x3

        # Use current memory pointer (for double buffer)
        if s['cr'] & self.CR_CT:
            m_addr = s['m1ar']
        else:
            m_addr = s['m0ar']

        if direction == 0:  # P2M
            if self.mem_read and self.mem_write:
                data = self.mem_read(s['par'], psize)
                self.mem_write(m_addr, msize, data)
        elif direction == 1:  # M2P
            if self.mem_read and self.mem_write:
                data = self.mem_read(m_addr, msize)
                self.mem_write(s['par'], psize, data)
        elif direction == 2:  # M2M
            if self.mem_read and self.mem_write:
                data = self.mem_read(s['par'], psize)
                self.mem_write(m_addr, msize, data)

        # Update addresses
        if s['cr'] & self.CR_PINC:
            s['par'] += psize
        if s['cr'] & self.CR_MINC:
            if s['cr'] & self.CR_CT:
                s['m1ar'] += msize
            else:
                s['m0ar'] += msize

        s['count'] -= 1

        if s['count'] == 0:
            # Set transfer complete
            if s_idx < 4:
                self.lisr |= (1 << (5 + s_idx * 6))
            else:
                self.hisr |= (1 << (5 + (s_idx - 4) * 6))

            if s['cr'] & self.CR_CIRC:
                s['count'] = s['ndtr']
            else:
                s['cr'] &= ~self.CR_EN
                return True

        return False


class STM32BDMA(STM32Peripheral):
    """STM32H7 Basic DMA for D3 domain."""

    def __init__(self, base: int = 0x58025400):
        super().__init__("BDMA", base, 0x400)
        self.num_channels = 8


class STM32MDMA(STM32Peripheral):
    """STM32H7 Master DMA."""

    def __init__(self, base: int = 0x52000000):
        super().__init__("MDMA", base, 0x400)
        self.num_channels = 16
