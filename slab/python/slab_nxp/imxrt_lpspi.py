"""
i.MX RT LPSPI Peripheral

Low-Power SPI used in i.MX RT series.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List
from .nxp_base import NXPPeripheral


class IMXRTLpspi(NXPPeripheral):
    """
    i.MX RT Low-Power SPI.

    Features:
    - 4 chip selects
    - Word size 8-32 bits
    - FIFO with configurable watermarks
    - DMA support
    - Master and slave modes

    Memory Map:
        0x00: VERID - Version ID
        0x04: PARAM - Parameter
        0x10: CR - Control
        0x14: SR - Status
        0x18: IER - Interrupt enable
        0x1C: DER - DMA enable
        0x20: CFGR0 - Configuration 0
        0x24: CFGR1 - Configuration 1
        0x40: DMR0 - Data match 0
        0x44: DMR1 - Data match 1
        0x60: CCR - Clock configuration
        0x70: FCR - FIFO control
        0x74: FSR - FIFO status
        0x78: TCR - Transmit command
        0x7C: TDR - Transmit data
        0x84: RSR - Receive status
        0x88: RDR - Receive data
    """

    # Register offsets
    VERID = 0x00
    PARAM = 0x04
    CR = 0x10
    SR = 0x14
    IER = 0x18
    DER = 0x1C
    CFGR0 = 0x20
    CFGR1 = 0x24
    DMR0 = 0x40
    DMR1 = 0x44
    CCR = 0x60
    FCR = 0x70
    FSR = 0x74
    TCR = 0x78
    TDR = 0x7C
    RSR = 0x84
    RDR = 0x88

    # CR bits
    CR_MEN = (1 << 0)         # Module enable
    CR_RST = (1 << 1)         # Software reset
    CR_DOZEN = (1 << 2)       # Doze enable
    CR_DBGEN = (1 << 3)       # Debug enable
    CR_RTF = (1 << 8)         # Reset transmit FIFO
    CR_RRF = (1 << 9)         # Reset receive FIFO

    # SR bits
    SR_TDF = (1 << 0)         # Transmit data flag
    SR_RDF = (1 << 1)         # Receive data flag
    SR_WCF = (1 << 8)         # Word complete flag
    SR_FCF = (1 << 9)         # Frame complete flag
    SR_TCF = (1 << 10)        # Transfer complete flag
    SR_TEF = (1 << 11)        # Transmit error flag
    SR_REF = (1 << 12)        # Receive error flag
    SR_DMF = (1 << 13)        # Data match flag
    SR_MBF = (1 << 24)        # Module busy flag

    # TCR bits
    TCR_FRAMESZ_MASK = 0x0FFF
    TCR_WIDTH_MASK = (0x03 << 16)
    TCR_TXMSK = (1 << 18)
    TCR_RXMSK = (1 << 19)
    TCR_CONTC = (1 << 20)
    TCR_CONT = (1 << 21)
    TCR_BYSW = (1 << 22)
    TCR_LSBF = (1 << 23)
    TCR_PCS_MASK = (0x03 << 24)
    TCR_PRESCALE_MASK = (0x07 << 27)
    TCR_CPHA = (1 << 30)
    TCR_CPOL = (1 << 31)

    def __init__(self, index: int, base: int):
        super().__init__(f"LPSPI{index}", base, 0x1000)
        self.index = index

        # Control registers
        self.cr = 0
        self.sr = self.SR_TDF
        self.ier = 0
        self.der = 0
        self.cfgr0 = 0
        self.cfgr1 = 0
        self.dmr0 = 0
        self.dmr1 = 0
        self.ccr = 0
        self.fcr = 0
        self.tcr = 0

        # FIFO
        self.tx_fifo: List[int] = []
        self.rx_fifo: List[int] = []
        self.fifo_depth = 16

        # Callbacks
        self.on_transfer: Optional[Callable[[int, int], int]] = None
        # on_transfer(data, frame_size) -> response

    def _do_transfer(self, data: int) -> int:
        """Perform SPI transfer."""
        frame_size = (self.tcr & self.TCR_FRAMESZ_MASK) + 1
        if self.on_transfer:
            return self.on_transfer(data, frame_size)
        return 0xFFFFFFFF  # Default: pull-up

    def _update_status(self):
        """Update status register."""
        # TX flag
        tx_water = self.fcr & 0x03
        if len(self.tx_fifo) <= tx_water:
            self.sr |= self.SR_TDF
        else:
            self.sr &= ~self.SR_TDF

        # RX flag
        rx_water = (self.fcr >> 16) & 0x03
        if len(self.rx_fifo) > rx_water:
            self.sr |= self.SR_RDF
        else:
            self.sr &= ~self.SR_RDF

        # Check for interrupts
        if (self.sr & self.ier) & 0x3F03:
            self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.VERID:
            return 0x01010004  # Version 1.1.0.4
        elif offset == self.PARAM:
            return (self.fifo_depth << 8) | self.fifo_depth
        elif offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self.sr
        elif offset == self.IER:
            return self.ier
        elif offset == self.DER:
            return self.der
        elif offset == self.CFGR0:
            return self.cfgr0
        elif offset == self.CFGR1:
            return self.cfgr1
        elif offset == self.DMR0:
            return self.dmr0
        elif offset == self.DMR1:
            return self.dmr1
        elif offset == self.CCR:
            return self.ccr
        elif offset == self.FCR:
            return self.fcr
        elif offset == self.FSR:
            return (len(self.rx_fifo) << 16) | len(self.tx_fifo)
        elif offset == self.TCR:
            return self.tcr
        elif offset == self.RSR:
            return 0 if self.rx_fifo else (1 << 1)  # SOF
        elif offset == self.RDR:
            if self.rx_fifo:
                data = self.rx_fifo.pop(0)
                self._update_status()
                return data
            return 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            if value & self.CR_RST:
                self._reset()
                return
            if value & self.CR_RTF:
                self.tx_fifo.clear()
            if value & self.CR_RRF:
                self.rx_fifo.clear()
            self.cr = value & ~(self.CR_RST | self.CR_RTF | self.CR_RRF)
            self._update_status()
        elif offset == self.SR:
            # W1C for flags
            self.sr &= ~(value & 0x3F00)
        elif offset == self.IER:
            self.ier = value
        elif offset == self.DER:
            self.der = value
        elif offset == self.CFGR0:
            self.cfgr0 = value
        elif offset == self.CFGR1:
            self.cfgr1 = value
        elif offset == self.DMR0:
            self.dmr0 = value
        elif offset == self.DMR1:
            self.dmr1 = value
        elif offset == self.CCR:
            self.ccr = value
        elif offset == self.FCR:
            self.fcr = value
        elif offset == self.TCR:
            self.tcr = value
        elif offset == self.TDR:
            if self.cr & self.CR_MEN:
                if len(self.tx_fifo) < self.fifo_depth:
                    self.tx_fifo.append(value)
                    # Process immediately in emulation
                    while self.tx_fifo:
                        tx_data = self.tx_fifo.pop(0)
                        rx_data = self._do_transfer(tx_data)
                        if not (self.tcr & self.TCR_RXMSK):
                            if len(self.rx_fifo) < self.fifo_depth:
                                self.rx_fifo.append(rx_data)
                            else:
                                self.sr |= self.SR_REF
                    self.sr |= self.SR_TCF | self.SR_FCF | self.SR_WCF
                    self._update_status()
                else:
                    self.sr |= self.SR_TEF

    def _reset(self):
        """Reset SPI to defaults."""
        self.cr = 0
        self.sr = self.SR_TDF
        self.ier = 0
        self.der = 0
        self.cfgr0 = 0
        self.cfgr1 = 0
        self.dmr0 = 0
        self.dmr1 = 0
        self.ccr = 0
        self.fcr = 0
        self.tcr = 0
        self.tx_fifo.clear()
        self.rx_fifo.clear()
