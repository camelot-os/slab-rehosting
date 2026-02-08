"""
i.MX RT LPUART Peripheral

Low-Power UART used in i.MX RT series.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List
from .nxp_base import NXPPeripheral


class IMXRTLpuart(NXPPeripheral):
    """
    i.MX RT Low-Power UART.

    Features:
    - Full-duplex async serial
    - Hardware flow control (RTS/CTS)
    - 9-bit data support
    - DMA support
    - IrDA mode
    - Lin break detect

    Memory Map:
        0x00: VERID - Version ID
        0x04: PARAM - Parameter
        0x08: GLOBAL - Global
        0x0C: PINCFG - Pin configuration
        0x10: BAUD - Baud rate
        0x14: STAT - Status
        0x18: CTRL - Control
        0x1C: DATA - Data
        0x20: MATCH - Match address
        0x24: MODIR - Modem IrDA
        0x28: FIFO - FIFO
        0x2C: WATER - Watermark
    """

    # Register offsets
    VERID = 0x00
    PARAM = 0x04
    GLOBAL = 0x08
    PINCFG = 0x0C
    BAUD = 0x10
    STAT = 0x14
    CTRL = 0x18
    DATA = 0x1C
    MATCH = 0x20
    MODIR = 0x24
    FIFO = 0x28
    WATER = 0x2C

    # STAT bits
    STAT_MA2F = (1 << 14)     # Match 2 flag
    STAT_MA1F = (1 << 15)     # Match 1 flag
    STAT_PF = (1 << 16)       # Parity error
    STAT_FE = (1 << 17)       # Framing error
    STAT_NF = (1 << 18)       # Noise flag
    STAT_OR = (1 << 19)       # Overrun
    STAT_IDLE = (1 << 20)     # Idle line
    STAT_RDRF = (1 << 21)     # Receive data register full
    STAT_TC = (1 << 22)       # Transmission complete
    STAT_TDRE = (1 << 23)     # Transmit data register empty
    STAT_RAF = (1 << 24)      # Receiver active
    STAT_LBKDE = (1 << 25)    # LIN break detect enable
    STAT_BRK13 = (1 << 26)    # Break 13
    STAT_RWUID = (1 << 27)    # Receive wakeup idle detect
    STAT_RXINV = (1 << 28)    # Receive data inversion
    STAT_MSBF = (1 << 29)     # MSB first
    STAT_RXEDGIF = (1 << 30)  # RX edge interrupt flag
    STAT_LBKDIF = (1 << 31)   # LIN break detect flag

    # CTRL bits
    CTRL_PT = (1 << 0)        # Parity type
    CTRL_PE = (1 << 1)        # Parity enable
    CTRL_ILT = (1 << 2)       # Idle line type
    CTRL_WAKE = (1 << 3)      # Wake
    CTRL_M = (1 << 4)         # 9-bit mode
    CTRL_RSRC = (1 << 5)      # Receiver source
    CTRL_DOZEEN = (1 << 6)    # Doze enable
    CTRL_LOOPS = (1 << 7)     # Loop mode
    CTRL_IDLECFG = (0x07 << 8)
    CTRL_M7 = (1 << 11)       # 7-bit mode
    CTRL_MA2IE = (1 << 14)    # Match 2 interrupt enable
    CTRL_MA1IE = (1 << 15)    # Match 1 interrupt enable
    CTRL_SBK = (1 << 16)      # Send break
    CTRL_RWU = (1 << 17)      # Receiver wakeup
    CTRL_RE = (1 << 18)       # Receiver enable
    CTRL_TE = (1 << 19)       # Transmitter enable
    CTRL_ILIE = (1 << 20)     # Idle line interrupt enable
    CTRL_RIE = (1 << 21)      # Receive interrupt enable
    CTRL_TCIE = (1 << 22)     # Transmission complete interrupt enable
    CTRL_TIE = (1 << 23)      # Transmit interrupt enable
    CTRL_PEIE = (1 << 24)     # Parity error interrupt enable
    CTRL_FEIE = (1 << 25)     # Framing error interrupt enable
    CTRL_NEIE = (1 << 26)     # Noise error interrupt enable
    CTRL_ORIE = (1 << 27)     # Overrun interrupt enable
    CTRL_TXINV = (1 << 28)    # Transmit data inversion
    CTRL_TXDIR = (1 << 29)    # TX pin direction
    CTRL_R9T8 = (1 << 30)     # Receive bit 9 / Transmit bit 8
    CTRL_R8T9 = (1 << 31)     # Receive bit 8 / Transmit bit 9

    # FIFO bits
    FIFO_RXFIFOSIZE = (0x07 << 0)
    FIFO_RXFE = (1 << 3)      # RX FIFO enable
    FIFO_TXFIFOSIZE = (0x07 << 4)
    FIFO_TXFE = (1 << 7)      # TX FIFO enable
    FIFO_RXUFE = (1 << 8)     # RX underflow enable
    FIFO_TXOFE = (1 << 9)     # TX overflow enable
    FIFO_RXIDEN = (0x07 << 10)
    FIFO_RXFLUSH = (1 << 14)  # RX FIFO flush
    FIFO_TXFLUSH = (1 << 15)  # TX FIFO flush
    FIFO_RXUF = (1 << 16)     # RX underflow
    FIFO_TXOF = (1 << 17)     # TX overflow
    FIFO_RXEMPT = (1 << 22)   # RX FIFO empty
    FIFO_TXEMPT = (1 << 23)   # TX FIFO empty

    def __init__(self, index: int, base: int):
        super().__init__(f"LPUART{index}", base, 0x1000)
        self.index = index

        # Control registers
        self.baud = 0x0F000004  # Default baud config
        self.stat = self.STAT_TDRE | self.STAT_TC
        self.ctrl = 0
        self.global_reg = 0
        self.pincfg = 0
        self.match = 0
        self.modir = 0
        self.fifo = (1 << 0) | (1 << 4)  # Default FIFO size 1
        self.water = 0

        # FIFO buffers
        self.tx_fifo: List[int] = []
        self.rx_fifo: List[int] = []
        self.fifo_depth = 4  # Can be 1, 4, 8, 16, 32, etc.

        # Callbacks
        self.on_tx: Optional[Callable[[int], None]] = None
        self.on_tx_bytes: Optional[Callable[[bytes], None]] = None

    def receive_byte(self, data: int):
        """Receive a byte into RX FIFO."""
        if not (self.ctrl & self.CTRL_RE):
            return

        if len(self.rx_fifo) < self.fifo_depth:
            self.rx_fifo.append(data & 0xFF)
            self._update_rx_flags()
        else:
            self.stat |= self.STAT_OR  # Overrun

    def receive_bytes(self, data: bytes):
        """Receive multiple bytes."""
        for b in data:
            self.receive_byte(b)

    def _update_rx_flags(self):
        """Update RX status flags."""
        if self.rx_fifo:
            self.stat |= self.STAT_RDRF
            self.fifo &= ~self.FIFO_RXEMPT
        else:
            self.stat &= ~self.STAT_RDRF
            self.fifo |= self.FIFO_RXEMPT

        # Check watermark for interrupt
        rx_water = self.water & 0xFF
        if len(self.rx_fifo) >= rx_water:
            if self.ctrl & self.CTRL_RIE:
                self.trigger_irq(1)

    def _update_tx_flags(self):
        """Update TX status flags."""
        tx_water = (self.water >> 16) & 0xFF
        if len(self.tx_fifo) <= tx_water:
            self.stat |= self.STAT_TDRE
            if self.ctrl & self.CTRL_TIE:
                self.trigger_irq(1)
        else:
            self.stat &= ~self.STAT_TDRE

        if not self.tx_fifo:
            self.stat |= self.STAT_TC
            self.fifo |= self.FIFO_TXEMPT
            if self.ctrl & self.CTRL_TCIE:
                self.trigger_irq(1)
        else:
            self.stat &= ~self.STAT_TC
            self.fifo &= ~self.FIFO_TXEMPT

    def _transmit_byte(self, data: int):
        """Transmit a byte."""
        if self.on_tx:
            self.on_tx(data & 0xFF)
        if self.on_tx_bytes:
            self.on_tx_bytes(bytes([data & 0xFF]))

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.VERID:
            return 0x04010003  # Version 4.1.0.3
        elif offset == self.PARAM:
            return (self.fifo_depth << 8) | self.fifo_depth
        elif offset == self.GLOBAL:
            return self.global_reg
        elif offset == self.PINCFG:
            return self.pincfg
        elif offset == self.BAUD:
            return self.baud
        elif offset == self.STAT:
            return self.stat
        elif offset == self.CTRL:
            return self.ctrl
        elif offset == self.DATA:
            if self.rx_fifo:
                data = self.rx_fifo.pop(0)
                self._update_rx_flags()
                return data
            return 0
        elif offset == self.MATCH:
            return self.match
        elif offset == self.MODIR:
            return self.modir
        elif offset == self.FIFO:
            # Include FIFO count
            return self.fifo | (len(self.rx_fifo) << 24) | (len(self.tx_fifo) << 24)
        elif offset == self.WATER:
            return self.water | (len(self.rx_fifo) << 24) | (len(self.tx_fifo) << 8)
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.GLOBAL:
            if value & 0x02:  # RST
                self._reset()
            self.global_reg = value & ~0x02
        elif offset == self.PINCFG:
            self.pincfg = value
        elif offset == self.BAUD:
            self.baud = value
        elif offset == self.STAT:
            # W1C for flags
            clear_mask = value & 0xC01FC000
            self.stat &= ~clear_mask
        elif offset == self.CTRL:
            self.ctrl = value
        elif offset == self.DATA:
            if self.ctrl & self.CTRL_TE:
                if len(self.tx_fifo) < self.fifo_depth:
                    self.tx_fifo.append(value & 0x3FF)
                    # Immediately transmit (instant in emulation)
                    while self.tx_fifo:
                        self._transmit_byte(self.tx_fifo.pop(0))
                    self._update_tx_flags()
                else:
                    self.fifo |= self.FIFO_TXOF
        elif offset == self.MATCH:
            self.match = value
        elif offset == self.MODIR:
            self.modir = value
        elif offset == self.FIFO:
            if value & self.FIFO_RXFLUSH:
                self.rx_fifo.clear()
                self._update_rx_flags()
            if value & self.FIFO_TXFLUSH:
                self.tx_fifo.clear()
                self._update_tx_flags()
            # W1C for error flags
            if value & self.FIFO_RXUF:
                self.fifo &= ~self.FIFO_RXUF
            if value & self.FIFO_TXOF:
                self.fifo &= ~self.FIFO_TXOF
            self.fifo = (self.fifo & 0x00FF00FF) | (value & 0xFF00FF00)
        elif offset == self.WATER:
            self.water = value & 0x00FF00FF

    def _reset(self):
        """Reset UART to defaults."""
        self.baud = 0x0F000004
        self.stat = self.STAT_TDRE | self.STAT_TC
        self.ctrl = 0
        self.pincfg = 0
        self.match = 0
        self.modir = 0
        self.fifo = (1 << 0) | (1 << 4) | self.FIFO_RXEMPT | self.FIFO_TXEMPT
        self.water = 0
        self.tx_fifo.clear()
        self.rx_fifo.clear()
