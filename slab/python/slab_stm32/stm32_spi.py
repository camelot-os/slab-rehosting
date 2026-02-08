"""
STM32 SPI Peripheral Emulation

Implements:
- SPIv1 (F1/F4): Standard SPI
- SPIv2 (H7): SPI with FIFO

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from collections import deque
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32SPIv1(STM32Peripheral):
    """
    STM32F1/F4 SPI peripheral.

    Register Map:
        0x00: CR1    - Control register 1
        0x04: CR2    - Control register 2
        0x08: SR     - Status register
        0x0C: DR     - Data register
        0x10: CRCPR  - CRC polynomial
        0x14: RXCRCR - RX CRC register
        0x18: TXCRCR - TX CRC register
        0x1C: I2SCFGR - I2S configuration
        0x20: I2SPR  - I2S prescaler
    """

    # Register offsets
    CR1 = 0x00
    CR2 = 0x04
    SR = 0x08
    DR = 0x0C
    CRCPR = 0x10
    RXCRCR = 0x14
    TXCRCR = 0x18
    I2SCFGR = 0x1C
    I2SPR = 0x20

    # CR1 bits
    CR1_CPHA = 1 << 0      # Clock phase
    CR1_CPOL = 1 << 1      # Clock polarity
    CR1_MSTR = 1 << 2      # Master mode
    CR1_BR_MASK = 0x7 << 3  # Baud rate
    CR1_SPE = 1 << 6       # SPI enable
    CR1_LSBFIRST = 1 << 7  # LSB first
    CR1_SSI = 1 << 8       # Internal slave select
    CR1_SSM = 1 << 9       # Software slave management
    CR1_RXONLY = 1 << 10   # Receive only
    CR1_DFF = 1 << 11      # Data frame format (0=8bit, 1=16bit)
    CR1_CRCNEXT = 1 << 12  # CRC transfer next
    CR1_CRCEN = 1 << 13    # CRC enable
    CR1_BIDIOE = 1 << 14   # Bidirectional output enable
    CR1_BIDIMODE = 1 << 15 # Bidirectional mode

    # CR2 bits
    CR2_RXDMAEN = 1 << 0   # RX DMA enable
    CR2_TXDMAEN = 1 << 1   # TX DMA enable
    CR2_SSOE = 1 << 2      # SS output enable
    CR2_FRF = 1 << 4       # Frame format (TI mode)
    CR2_ERRIE = 1 << 5     # Error interrupt enable
    CR2_RXNEIE = 1 << 6    # RX not empty interrupt
    CR2_TXEIE = 1 << 7     # TX empty interrupt

    # SR bits
    SR_RXNE = 1 << 0       # RX not empty
    SR_TXE = 1 << 1        # TX empty
    SR_CHSIDE = 1 << 2     # Channel side (I2S)
    SR_UDR = 1 << 3        # Underrun (I2S)
    SR_CRCERR = 1 << 4     # CRC error
    SR_MODF = 1 << 5       # Mode fault
    SR_OVR = 1 << 6        # Overrun
    SR_BSY = 1 << 7        # Busy
    SR_FRE = 1 << 8        # Frame error (TI mode)

    # Base addresses (F4)
    SPI_BASES = {
        1: 0x40013000,  # SPI1 (APB2)
        2: 0x40003800,  # SPI2 (APB1)
        3: 0x40003C00,  # SPI3 (APB1)
        4: 0x40013400,  # SPI4 (APB2)
        5: 0x40015000,  # SPI5 (APB2)
        6: 0x40015400,  # SPI6 (APB2)
    }

    SPI_IRQS = {
        1: 35,  # SPI1
        2: 36,  # SPI2
        3: 51,  # SPI3
    }

    def __init__(self, index: int = 1, base: int = None):
        """
        Initialize SPI.

        Args:
            index: SPI number (1-6)
            base: Base address (auto-calculated if None)
        """
        if base is None:
            base = self.SPI_BASES.get(index, 0x40013000)

        irq = self.SPI_IRQS.get(index, 35)
        super().__init__(f"SPI{index}", base, 0x400, irq)
        self.index = index

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.sr = self.SR_TXE  # TX empty initially
        self.crcpr = 0x0007
        self.rxcrcr = 0
        self.txcrcr = 0
        self.i2scfgr = 0
        self.i2spr = 0x0002

        # Data registers
        self.tx_data = 0
        self.rx_data = 0

        # FIFOs (simulated)
        self.tx_fifo: deque = deque(maxlen=4)
        self.rx_fifo: deque = deque(maxlen=4)

        # External device callback
        self.on_transfer: Optional[Callable[[int], int]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.SR:
            return self._get_sr()
        elif offset == self.DR:
            return self._read_dr()
        elif offset == self.CRCPR:
            return self.crcpr
        elif offset == self.RXCRCR:
            return self.rxcrcr
        elif offset == self.TXCRCR:
            return self.txcrcr
        elif offset == self.I2SCFGR:
            return self.i2scfgr
        elif offset == self.I2SPR:
            return self.i2spr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            self.cr1 = value
            if value & self.CR1_SPE:
                self.log.debug(f"SPI enabled, BR={((value >> 3) & 7)}")
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.DR:
            self._write_dr(value)
        elif offset == self.CRCPR:
            self.crcpr = value
        elif offset == self.I2SCFGR:
            self.i2scfgr = value
        elif offset == self.I2SPR:
            self.i2spr = value

    def _get_sr(self) -> int:
        """Get status register with live flags."""
        sr = self.sr

        # RXNE: set if data available
        if self.rx_fifo:
            sr |= self.SR_RXNE
        else:
            sr &= ~self.SR_RXNE

        # TXE: set if TX buffer empty
        if len(self.tx_fifo) < 4:
            sr |= self.SR_TXE
        else:
            sr &= ~self.SR_TXE

        # BSY: clear when idle
        if not self.tx_fifo and not self.rx_fifo:
            sr &= ~self.SR_BSY

        return sr

    def _read_dr(self) -> int:
        """Read data register."""
        if self.rx_fifo:
            data = self.rx_fifo.popleft()
            if not self.rx_fifo:
                self.sr &= ~self.SR_RXNE
            return data
        return 0

    def _write_dr(self, value: int):
        """Write data register (start transfer)."""
        if not (self.cr1 & self.CR1_SPE):
            return

        # Get data width
        if self.cr1 & self.CR1_DFF:
            data = value & 0xFFFF  # 16-bit
        else:
            data = value & 0xFF   # 8-bit

        self.sr |= self.SR_BSY

        # Perform transfer
        if self.on_transfer:
            rx_data = self.on_transfer(data)
        else:
            rx_data = 0xFF  # Default: pull-up

        # Store received data
        if len(self.rx_fifo) < 4:
            self.rx_fifo.append(rx_data)
            self.sr |= self.SR_RXNE
        else:
            self.sr |= self.SR_OVR  # Overrun

        self.sr &= ~self.SR_BSY
        self._check_interrupt()

    def transfer(self, data: int) -> int:
        """Perform a single SPI transfer."""
        self._write_dr(data)
        if self.rx_fifo:
            return self.rx_fifo.popleft()
        return 0

    def _check_interrupt(self):
        """Check and trigger interrupt if enabled."""
        if (self.cr2 & self.CR2_RXNEIE) and (self._get_sr() & self.SR_RXNE):
            self.trigger_irq(1)
        if (self.cr2 & self.CR2_TXEIE) and (self._get_sr() & self.SR_TXE):
            self.trigger_irq(1)

    def _reset_registers(self):
        """Reset to default state."""
        self.cr1 = 0
        self.cr2 = 0
        self.sr = self.SR_TXE
        self.crcpr = 0x0007
        self.tx_fifo.clear()
        self.rx_fifo.clear()


class STM32SPIv2(STM32Peripheral):
    """
    STM32H7 SPI peripheral with FIFO.

    Extended features:
    - 16-deep FIFO
    - Hardware CRC
    - Variable data size (4-32 bits)
    - DMA circular mode
    """

    # Register offsets
    CR1 = 0x00
    CR2 = 0x04
    CFG1 = 0x08
    CFG2 = 0x0C
    IER = 0x10
    SR = 0x14
    IFCR = 0x18
    TXDR = 0x20
    RXDR = 0x30
    CRCPOLY = 0x40
    TXCRC = 0x44
    RXCRC = 0x48
    UDRDR = 0x4C
    I2SCFGR = 0x50

    # SR bits
    SR_RXP = 1 << 0       # RX packet available
    SR_TXP = 1 << 1       # TX packet space available
    SR_DXP = 1 << 2       # Duplex packet
    SR_EOT = 1 << 3       # End of transfer
    SR_TXTF = 1 << 4      # TX transfer filled
    SR_UDR = 1 << 5       # Underrun
    SR_OVR = 1 << 6       # Overrun
    SR_CRCE = 1 << 7      # CRC error
    SR_TIFRE = 1 << 8     # TI frame error
    SR_MODF = 1 << 9      # Mode fault
    SR_TSERF = 1 << 10    # Additional transfers reload
    SR_SUSP = 1 << 11     # Suspend
    SR_TXC = 1 << 12      # TX complete
    SR_RXPLVL = 0x3 << 13 # RX FIFO level
    SR_RXWNE = 1 << 15    # RX word not empty
    SR_CTSIZE = 0xFFFF << 16  # Transfers count

    SPI_BASES_H7 = {
        1: 0x40013000,
        2: 0x40003800,
        3: 0x40003C00,
        4: 0x40013400,
        5: 0x40015000,
        6: 0x58001400,
    }

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = self.SPI_BASES_H7.get(index, 0x40013000)

        super().__init__(f"SPI{index}", base, 0x400, 35)
        self.index = index

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.cfg1 = 0x00070007
        self.cfg2 = 0
        self.ier = 0
        self.sr = self.SR_TXP | self.SR_TXC
        self.crcpoly = 0x00000007
        self.txcrc = 0
        self.rxcrc = 0

        # FIFOs (16-deep)
        self.tx_fifo: deque = deque(maxlen=16)
        self.rx_fifo: deque = deque(maxlen=16)

        self.on_transfer: Optional[Callable[[int], int]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.CFG1:
            return self.cfg1
        elif offset == self.CFG2:
            return self.cfg2
        elif offset == self.IER:
            return self.ier
        elif offset == self.SR:
            return self._get_sr()
        elif offset == self.RXDR:
            return self._read_rxdr()
        elif offset == self.CRCPOLY:
            return self.crcpoly
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            self.cr1 = value
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.CFG1:
            self.cfg1 = value
        elif offset == self.CFG2:
            self.cfg2 = value
        elif offset == self.IER:
            self.ier = value
        elif offset == self.IFCR:
            # Clear flags
            self.sr &= ~(value & 0x0FF8)
        elif offset == self.TXDR:
            self._write_txdr(value)
        elif offset == self.CRCPOLY:
            self.crcpoly = value

    def _get_sr(self) -> int:
        sr = self.sr

        if self.rx_fifo:
            sr |= self.SR_RXP
        else:
            sr &= ~self.SR_RXP

        if len(self.tx_fifo) < 16:
            sr |= self.SR_TXP
        else:
            sr &= ~self.SR_TXP

        # FIFO level
        sr = (sr & ~(0x3 << 13)) | ((len(self.rx_fifo) & 3) << 13)

        return sr

    def _read_rxdr(self) -> int:
        if self.rx_fifo:
            return self.rx_fifo.popleft()
        return 0

    def _write_txdr(self, value: int):
        if not (self.cr1 & 1):  # SPE
            return

        data_size = (self.cfg1 & 0x1F) + 1  # DSIZE
        mask = (1 << data_size) - 1
        data = value & mask

        if self.on_transfer:
            rx = self.on_transfer(data)
        else:
            rx = mask

        if len(self.rx_fifo) < 16:
            self.rx_fifo.append(rx)
        else:
            self.sr |= self.SR_OVR

    def _reset_registers(self):
        self.cr1 = 0
        self.cr2 = 0
        self.cfg1 = 0x00070007
        self.cfg2 = 0
        self.sr = self.SR_TXP | self.SR_TXC
        self.tx_fifo.clear()
        self.rx_fifo.clear()
