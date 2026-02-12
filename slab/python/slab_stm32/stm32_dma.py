"""
STM32 DMA Controller Emulation

Implements:
- DMAv1 (F1xx/WBxx): Channel-based DMA with optional DMAMUX
- DMAv2 (F4/L4/H7): Stream-based DMA
- GPDMA (U5xx): General Purpose DMA with linked-list
- BDMA (H7): Basic DMA for D3 domain
- MDMA (H7): Master DMA

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
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


class STM32GPDMA(STM32Peripheral):
    """
    STM32U5 General Purpose DMA controller (GPDMA).

    Completely different architecture from DMAv1/v2:
    - 16 channels (GPDMA1) or 4 channels (LPDMA1)
    - Per-channel status/flag registers (no shared ISR)
    - Linked-list descriptor support
    - Separate source/destination address registers
    - Per-channel NVIC IRQ lines

    Register map (from stm32u5a5xx.h / RM0456):
    Global:
        0x00: SECCFGR   - Security configuration
        0x04: PRIVCFGR  - Privileged configuration
        0x08: RCFGLOCKR - Configuration lock
        0x0C: MISR      - Non-secure masked interrupt status
        0x10: SMISR     - Secure masked interrupt status

    Per-channel (base = 0x50 + ch * 0x80):
        +0x00: CLBAR  - Linked-list base address
        +0x0C: CFCR   - Flag clear (write-only, W1C)
        +0x10: CSR    - Status (read-only)
        +0x14: CCR    - Control
        +0x40: CTR1   - Transfer config 1 (src/dst width, increment, burst)
        +0x44: CTR2   - Transfer config 2 (REQSEL, SWREQ, DREQ, trigger)
        +0x48: CBR1   - Block config (BNDT byte count, BRC repeat)
        +0x4C: CSAR   - Source address
        +0x50: CDAR   - Destination address
        +0x54: CTR3   - Transfer config 3 (address offsets, 2D)
        +0x58: CBR2   - Block config 2 (repeat offsets, 2D)
        +0x7C: CLLR   - Linked-list register
    """

    # Global register offsets
    SECCFGR   = 0x00
    PRIVCFGR  = 0x04
    RCFGLOCKR = 0x08
    MISR      = 0x0C
    SMISR     = 0x10

    # Per-channel register offsets (from channel base)
    CH_BASE   = 0x50
    CH_STRIDE = 0x80

    CLBAR = 0x00
    CFCR  = 0x0C
    CSR   = 0x10
    CCR   = 0x14
    CTR1  = 0x40
    CTR2  = 0x44
    CBR1  = 0x48
    CSAR  = 0x4C
    CDAR  = 0x50
    CTR3  = 0x54
    CBR2  = 0x58
    CLLR  = 0x7C

    # CCR bits
    CCR_EN     = 1 << 0
    CCR_RESET  = 1 << 1
    CCR_SUSP   = 1 << 2
    CCR_TCIE   = 1 << 8
    CCR_HTIE   = 1 << 9
    CCR_DTEIE  = 1 << 10
    CCR_ULEIE  = 1 << 11
    CCR_USEIE  = 1 << 12
    CCR_SUSPIE = 1 << 13
    CCR_TOIE   = 1 << 14
    CCR_LSM    = 1 << 16
    CCR_LAP    = 1 << 17
    CCR_PRIO   = 0x3 << 22

    # CSR bits (read-only status)
    CSR_IDLEF = 1 << 0
    CSR_TCF   = 1 << 8
    CSR_HTF   = 1 << 9
    CSR_DTEF  = 1 << 10
    CSR_ULEF  = 1 << 11
    CSR_USEF  = 1 << 12
    CSR_SUSPF = 1 << 13
    CSR_TOF   = 1 << 14

    # CTR1 bits
    CTR1_SDW_LOG2 = 0x3 << 0    # Source data width (log2)
    CTR1_SINC     = 1 << 3      # Source increment
    CTR1_SBL_1    = 0x3F << 4   # Source burst length - 1
    CTR1_PAM      = 0x3 << 11   # Padding/alignment mode
    CTR1_SAP      = 1 << 14     # Source allocated port
    CTR1_DDW_LOG2 = 0x3 << 16   # Dest data width (log2)
    CTR1_DINC     = 1 << 19     # Dest increment
    CTR1_DBL_1    = 0x3F << 20  # Dest burst length - 1
    CTR1_DAP      = 1 << 30     # Dest allocated port

    # CTR2 bits
    CTR2_REQSEL  = 0x7F << 0    # Request selection
    CTR2_SWREQ   = 1 << 9      # Software request
    CTR2_DREQ    = 1 << 10     # Destination hardware request
    CTR2_BREQ    = 1 << 11     # Block hardware request
    CTR2_TRIGM   = 0x3 << 14   # Trigger mode
    CTR2_TRIGSEL = 0x3F << 16  # Trigger selection
    CTR2_TRIGPOL = 0x3 << 24   # Trigger polarity
    CTR2_TCEM    = 0x3 << 30   # Transfer complete event mode

    # CBR1 bits
    CBR1_BNDT  = 0xFFFF << 0   # Block number of data bytes
    CBR1_BRC   = 0x7FF << 16   # Block repeat counter

    # CLLR bits
    CLLR_LA  = 0x3FFF << 2     # Next linked-list address
    CLLR_ULL = 1 << 16         # Update CLLR from memory
    CLLR_UB2 = 1 << 25         # Update CBR2
    CLLR_UT3 = 1 << 26         # Update CTR3
    CLLR_UDA = 1 << 27         # Update CDAR
    CLLR_USA = 1 << 28         # Update CSAR
    CLLR_UB1 = 1 << 29         # Update CBR1
    CLLR_UT2 = 1 << 30         # Update CTR2
    CLLR_UT1 = 1 << 31         # Update CTR1

    # NVIC IRQ numbers per channel (STM32U5A5)
    GPDMA_IRQS = [29, 30, 31, 32, 33, 34, 35, 36,
                  80, 81, 82, 83, 84, 85, 86, 87]
    LPDMA_IRQS = [114, 115, 116, 117]

    def __init__(self, name: str = "GPDMA1", base: int = 0x40020000,
                 num_channels: int = 16):
        # Total register space: global (0x14) + channels (num_ch * 0x80 from 0x50)
        total_size = self.CH_BASE + num_channels * self.CH_STRIDE
        super().__init__(name, base, total_size)
        self.num_channels = num_channels

        # Global registers
        self.seccfgr = 0
        self.privcfgr = 0
        self.rcfglockr = 0

        # Per-channel state
        self.channels = []
        for _ in range(num_channels):
            self.channels.append({
                'clbar': 0,
                'csr': self.CSR_IDLEF,  # Idle at reset
                'ccr': 0,
                'ctr1': 0,
                'ctr2': 0,
                'cbr1': 0,
                'csar': 0,
                'cdar': 0,
                'ctr3': 0,
                'cbr2': 0,
                'cllr': 0,
                # Working state
                'bndt_remaining': 0,
                'src_addr': 0,
                'dst_addr': 0,
            })

        # IRQ map (set from peripheral set based on GPDMA vs LPDMA)
        if 'LP' in name:
            self._irqs = self.LPDMA_IRQS[:num_channels]
        else:
            self._irqs = self.GPDMA_IRQS[:num_channels]

        # Memory access callbacks (set by peripheral set / board)
        self.mem_read: Optional[Callable[[int, int], int]] = None
        self.mem_write: Optional[Callable[[int, int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        # Global registers
        if offset == self.SECCFGR:
            return self.seccfgr
        elif offset == self.PRIVCFGR:
            return self.privcfgr
        elif offset == self.RCFGLOCKR:
            return self.rcfglockr
        elif offset == self.MISR:
            return self._compute_misr()
        elif offset == self.SMISR:
            return 0  # Secure mirror -- not modeled

        # Per-channel registers
        ch_idx, ch_off = self._decode_channel(offset)
        if ch_idx is None or ch_idx >= self.num_channels:
            return 0
        ch = self.channels[ch_idx]

        if ch_off == self.CLBAR:
            return ch['clbar']
        elif ch_off == self.CFCR:
            return 0  # Write-only
        elif ch_off == self.CSR:
            return ch['csr']
        elif ch_off == self.CCR:
            return ch['ccr']
        elif ch_off == self.CTR1:
            return ch['ctr1']
        elif ch_off == self.CTR2:
            return ch['ctr2']
        elif ch_off == self.CBR1:
            return ch['cbr1']
        elif ch_off == self.CSAR:
            return ch['csar']
        elif ch_off == self.CDAR:
            return ch['cdar']
        elif ch_off == self.CTR3:
            return ch['ctr3']
        elif ch_off == self.CBR2:
            return ch['cbr2']
        elif ch_off == self.CLLR:
            return ch['cllr']
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        # Global registers
        if offset == self.SECCFGR:
            self.seccfgr = value
            return
        elif offset == self.PRIVCFGR:
            self.privcfgr = value
            return
        elif offset == self.RCFGLOCKR:
            self.rcfglockr = value
            return

        # Per-channel registers
        ch_idx, ch_off = self._decode_channel(offset)
        if ch_idx is None or ch_idx >= self.num_channels:
            return
        ch = self.channels[ch_idx]

        if ch_off == self.CFCR:
            # Write-1-to-clear status flags (bits 8-14 mirror CSR)
            ch['csr'] &= ~(value & 0x7F00)
            # Re-assert IDLEF if channel not enabled
            if not (ch['ccr'] & self.CCR_EN):
                ch['csr'] |= self.CSR_IDLEF
            self._update_irq(ch_idx)
            return
        elif ch_off == self.CCR:
            self._write_ccr(ch_idx, value)
            return
        elif ch_off == self.CTR1:
            ch['ctr1'] = value
        elif ch_off == self.CTR2:
            ch['ctr2'] = value
        elif ch_off == self.CBR1:
            ch['cbr1'] = value
        elif ch_off == self.CSAR:
            ch['csar'] = value
        elif ch_off == self.CDAR:
            ch['cdar'] = value
        elif ch_off == self.CTR3:
            ch['ctr3'] = value
        elif ch_off == self.CBR2:
            ch['cbr2'] = value
        elif ch_off == self.CLLR:
            ch['cllr'] = value
        elif ch_off == self.CLBAR:
            ch['clbar'] = value & 0xFFFF0000  # Upper 16 bits only

    def _decode_channel(self, offset: int):
        """Decode absolute offset into (channel_index, register_offset)."""
        if offset < self.CH_BASE:
            return None, None
        rel = offset - self.CH_BASE
        ch_idx = rel // self.CH_STRIDE
        ch_off = rel % self.CH_STRIDE
        return ch_idx, ch_off

    def _write_ccr(self, ch_idx: int, value: int):
        """Handle CCR write with EN/RESET/SUSP side effects."""
        ch = self.channels[ch_idx]
        old_ccr = ch['ccr']

        # RESET bit -- reset channel to idle
        if value & self.CCR_RESET:
            ch['ccr'] = 0
            ch['csr'] = self.CSR_IDLEF
            ch['ctr1'] = 0
            ch['ctr2'] = 0
            ch['cbr1'] = 0
            ch['csar'] = 0
            ch['cdar'] = 0
            ch['ctr3'] = 0
            ch['cbr2'] = 0
            ch['cllr'] = 0
            ch['clbar'] = 0
            ch['bndt_remaining'] = 0
            self._update_irq(ch_idx)
            return

        # SUSP bit -- suspend channel
        if (value & self.CCR_SUSP) and not (old_ccr & self.CCR_SUSP):
            ch['csr'] |= self.CSR_SUSPF
            ch['csr'] |= self.CSR_IDLEF
            # Clear EN on suspend
            value &= ~self.CCR_EN

        ch['ccr'] = value

        # EN 0->1 transition -- start transfer
        if (value & self.CCR_EN) and not (old_ccr & self.CCR_EN):
            self._start_transfer(ch_idx)

    def _start_transfer(self, ch_idx: int):
        """Initiate a DMA transfer on the given channel."""
        ch = self.channels[ch_idx]

        # Snapshot working addresses and count
        ch['src_addr'] = ch['csar']
        ch['dst_addr'] = ch['cdar']
        ch['bndt_remaining'] = ch['cbr1'] & 0xFFFF  # BNDT field

        # Clear IDLEF -- channel is active
        ch['csr'] &= ~self.CSR_IDLEF

        self.log.debug(
            f"{self.name} CH{ch_idx} start: "
            f"SRC=0x{ch['csar']:08X} DST=0x{ch['cdar']:08X} "
            f"BNDT={ch['bndt_remaining']}"
        )

        # For software-triggered (SWREQ) or emulation, complete immediately
        if ch['ctr2'] & self.CTR2_SWREQ:
            self._complete_transfer(ch_idx)
        else:
            # Hardware request -- transfer completes when peripheral triggers
            # For emulation: complete immediately (peripheral model will
            # have already prepared source data)
            self._complete_transfer(ch_idx)

    def _complete_transfer(self, ch_idx: int):
        """Mark transfer as complete, set flags, fire IRQ."""
        ch = self.channels[ch_idx]

        # Set transfer complete flag
        ch['csr'] |= self.CSR_TCF

        # Half transfer flag (set for completeness)
        ch['csr'] |= self.CSR_HTF

        # Disable channel
        ch['ccr'] &= ~self.CCR_EN
        ch['csr'] |= self.CSR_IDLEF

        # Zero remaining count
        ch['bndt_remaining'] = 0

        self._update_irq(ch_idx)

    def _update_irq(self, ch_idx: int):
        """Assert/deassert per-channel IRQ based on enabled flags."""
        ch = self.channels[ch_idx]
        ccr = ch['ccr']
        csr = ch['csr']

        # Check each interrupt enable against its status flag
        pending = False
        if (ccr & self.CCR_TCIE) and (csr & self.CSR_TCF):
            pending = True
        if (ccr & self.CCR_HTIE) and (csr & self.CSR_HTF):
            pending = True
        if (ccr & self.CCR_DTEIE) and (csr & self.CSR_DTEF):
            pending = True
        if (ccr & self.CCR_ULEIE) and (csr & self.CSR_ULEF):
            pending = True
        if (ccr & self.CCR_USEIE) and (csr & self.CSR_USEF):
            pending = True
        if (ccr & self.CCR_SUSPIE) and (csr & self.CSR_SUSPF):
            pending = True
        if (ccr & self.CCR_TOIE) and (csr & self.CSR_TOF):
            pending = True

        if ch_idx < len(self._irqs) and self.irq_callback:
            self.irq_callback(self._irqs[ch_idx], 1 if pending else 0)

    def _compute_misr(self) -> int:
        """Compute MISR: bit N set if channel N has any pending interrupt."""
        misr = 0
        for i, ch in enumerate(self.channels):
            ccr = ch['ccr']
            csr = ch['csr']
            if ((ccr & self.CCR_TCIE) and (csr & self.CSR_TCF)) or \
               ((ccr & self.CCR_HTIE) and (csr & self.CSR_HTF)) or \
               ((ccr & self.CCR_DTEIE) and (csr & self.CSR_DTEF)) or \
               ((ccr & self.CCR_ULEIE) and (csr & self.CSR_ULEF)) or \
               ((ccr & self.CCR_USEIE) and (csr & self.CSR_USEF)) or \
               ((ccr & self.CCR_SUSPIE) and (csr & self.CSR_SUSPF)) or \
               ((ccr & self.CCR_TOIE) and (csr & self.CSR_TOF)):
                misr |= (1 << i)
        return misr

    def do_transfer(self, ch_idx: int) -> bool:
        """
        Perform one data beat on the given channel.

        Called externally when a peripheral DMA request fires.
        Returns True when the block transfer is complete.
        """
        ch = self.channels[ch_idx]
        if not (ch['ccr'] & self.CCR_EN) or ch['bndt_remaining'] == 0:
            return True

        # Source/dest data widths
        src_width = 1 << (ch['ctr1'] & 0x3)         # SDW_LOG2
        dst_width = 1 << ((ch['ctr1'] >> 16) & 0x3)  # DDW_LOG2
        xfer_width = min(src_width, dst_width)

        # Read source
        if self.mem_read:
            data = self.mem_read(ch['src_addr'], xfer_width)
        else:
            data = 0

        # Write destination
        if self.mem_write:
            self.mem_write(ch['dst_addr'], xfer_width, data)

        # Increment addresses
        if ch['ctr1'] & self.CTR1_SINC:
            ch['src_addr'] += src_width
        if ch['ctr1'] & self.CTR1_DINC:
            ch['dst_addr'] += dst_width

        ch['bndt_remaining'] -= xfer_width

        # Check block complete
        if ch['bndt_remaining'] <= 0:
            ch['bndt_remaining'] = 0
            self._complete_transfer(ch_idx)
            return True

        # Half transfer check
        initial_bndt = ch['cbr1'] & 0xFFFF
        if initial_bndt > 0 and ch['bndt_remaining'] <= initial_bndt // 2:
            if not (ch['csr'] & self.CSR_HTF):
                ch['csr'] |= self.CSR_HTF
                self._update_irq(ch_idx)

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
