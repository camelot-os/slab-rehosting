"""
NRF UARTE - EasyDMA UART

Features:
- Autonomous DMA transfers
- Hardware flow control (RTS/CTS)
- Parity support
- Configurable baud rate

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable
from collections import deque
from .nrf_base import NRFPeripheral


class NRFUARTE(NRFPeripheral):
    """
    NRF UARTE (UART with EasyDMA).

    Register Map:
        0x000: TASKS_STARTRX
        0x004: TASKS_STOPRX
        0x008: TASKS_STARTTX
        0x00C: TASKS_STOPTX
        0x02C: TASKS_FLUSHRX
        0x100: EVENTS_CTS
        0x104: EVENTS_NCTS
        0x108: EVENTS_RXDRDY
        0x110: EVENTS_ENDRX
        0x118: EVENTS_TXDRDY
        0x120: EVENTS_ENDTX
        0x124: EVENTS_ERROR
        0x144: EVENTS_RXTO
        0x14C: EVENTS_RXSTARTED
        0x150: EVENTS_TXSTARTED
        0x158: EVENTS_TXSTOPPED
        0x200: SHORTS
        0x300: INTEN
        0x500: ERRORSRC
        0x504: ENABLE
        0x508: PSEL.RTS
        0x50C: PSEL.TXD
        0x510: PSEL.CTS
        0x514: PSEL.RXD
        0x524: BAUDRATE
        0x534: RXD.PTR
        0x538: RXD.MAXCNT
        0x53C: RXD.AMOUNT
        0x544: TXD.PTR
        0x548: TXD.MAXCNT
        0x54C: TXD.AMOUNT
        0x56C: CONFIG
    """

    # Tasks
    TASKS_STARTRX = 0x000
    TASKS_STOPRX = 0x004
    TASKS_STARTTX = 0x008
    TASKS_STOPTX = 0x00C
    TASKS_FLUSHRX = 0x02C

    # Events
    EVENTS_CTS = 0x100
    EVENTS_NCTS = 0x104
    EVENTS_RXDRDY = 0x108
    EVENTS_ENDRX = 0x110
    EVENTS_TXDRDY = 0x118
    EVENTS_ENDTX = 0x120
    EVENTS_ERROR = 0x124
    EVENTS_RXTO = 0x144
    EVENTS_RXSTARTED = 0x14C
    EVENTS_TXSTARTED = 0x150
    EVENTS_TXSTOPPED = 0x158

    # Registers
    ERRORSRC = 0x480
    ENABLE = 0x500
    PSEL_RTS = 0x508
    PSEL_TXD = 0x50C
    PSEL_CTS = 0x510
    PSEL_RXD = 0x514
    BAUDRATE = 0x524
    RXD_PTR = 0x534
    RXD_MAXCNT = 0x538
    RXD_AMOUNT = 0x53C
    TXD_PTR = 0x544
    TXD_MAXCNT = 0x548
    TXD_AMOUNT = 0x54C
    CONFIG = 0x56C

    # Standard baud rates (register values)
    BAUD_9600 = 0x00275000
    BAUD_115200 = 0x01D7E000
    BAUD_1M = 0x10000000

    UARTE_BASES = {
        0: 0x40002000,
        1: 0x40028000,  # nRF52840
    }

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = self.UARTE_BASES.get(index, 0x40002000)

        super().__init__(f"UARTE{index}", base, 0x1000, irq=2 + index)
        self.index = index

        self.errorsrc = 0
        self.enable = 0
        self.psel_rts = 0xFFFFFFFF  # Disconnected
        self.psel_txd = 0xFFFFFFFF
        self.psel_cts = 0xFFFFFFFF
        self.psel_rxd = 0xFFFFFFFF
        self.baudrate = self.BAUD_115200
        self.config = 0

        # DMA pointers
        self.rxd_ptr = 0
        self.rxd_maxcnt = 0
        self.rxd_amount = 0
        self.txd_ptr = 0
        self.txd_maxcnt = 0
        self.txd_amount = 0

        # State
        self.rx_active = False
        self.tx_active = False

        # Buffers
        self.rx_fifo: deque = deque(maxlen=256)

        # Memory access callbacks
        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None

        # TX output callback
        self.on_tx: Optional[Callable[[bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ERRORSRC:
            return self.errorsrc
        elif offset == self.ENABLE:
            return self.enable
        elif offset == self.PSEL_RTS:
            return self.psel_rts
        elif offset == self.PSEL_TXD:
            return self.psel_txd
        elif offset == self.PSEL_CTS:
            return self.psel_cts
        elif offset == self.PSEL_RXD:
            return self.psel_rxd
        elif offset == self.BAUDRATE:
            return self.baudrate
        elif offset == self.RXD_PTR:
            return self.rxd_ptr
        elif offset == self.RXD_MAXCNT:
            return self.rxd_maxcnt
        elif offset == self.RXD_AMOUNT:
            return self.rxd_amount
        elif offset == self.TXD_PTR:
            return self.txd_ptr
        elif offset == self.TXD_MAXCNT:
            return self.txd_maxcnt
        elif offset == self.TXD_AMOUNT:
            return self.txd_amount
        elif offset == self.CONFIG:
            return self.config
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ERRORSRC:
            self.errorsrc &= ~value  # Write 1 to clear
        elif offset == self.ENABLE:
            self.enable = value
        elif offset == self.PSEL_RTS:
            self.psel_rts = value
        elif offset == self.PSEL_TXD:
            self.psel_txd = value
        elif offset == self.PSEL_CTS:
            self.psel_cts = value
        elif offset == self.PSEL_RXD:
            self.psel_rxd = value
        elif offset == self.BAUDRATE:
            self.baudrate = value
        elif offset == self.RXD_PTR:
            self.rxd_ptr = value
        elif offset == self.RXD_MAXCNT:
            self.rxd_maxcnt = value
        elif offset == self.TXD_PTR:
            self.txd_ptr = value
        elif offset == self.TXD_MAXCNT:
            self.txd_maxcnt = value
        elif offset == self.CONFIG:
            self.config = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_STARTRX:
            self._start_rx()
        elif offset == self.TASKS_STOPRX:
            self._stop_rx()
        elif offset == self.TASKS_STARTTX:
            self._start_tx()
        elif offset == self.TASKS_STOPTX:
            self._stop_tx()
        elif offset == self.TASKS_FLUSHRX:
            self._flush_rx()

    def _start_rx(self):
        """Start RX DMA transfer."""
        if self.enable != 8:  # Not enabled
            return

        self.rx_active = True
        self.rxd_amount = 0
        self.set_event(self.EVENTS_RXSTARTED)

        # Process any buffered data
        self._process_rx_fifo()

    def _stop_rx(self):
        """Stop RX DMA transfer."""
        self.rx_active = False
        self.set_event(self.EVENTS_ENDRX)

    def _start_tx(self):
        """Start TX DMA transfer."""
        if self.enable != 8:
            return

        self.tx_active = True
        self.txd_amount = 0
        self.set_event(self.EVENTS_TXSTARTED)

        # Transfer data from memory
        if self.mem_read and self.txd_maxcnt > 0:
            data = self.mem_read(self.txd_ptr, self.txd_maxcnt)
            if data:
                self.txd_amount = len(data)
                if self.on_tx:
                    self.on_tx(data)

                # Per-byte TXDRDY events
                for _ in data:
                    self.set_event(self.EVENTS_TXDRDY)

        self.set_event(self.EVENTS_ENDTX)
        self.tx_active = False

    def _stop_tx(self):
        """Stop TX DMA transfer."""
        self.tx_active = False
        self.set_event(self.EVENTS_TXSTOPPED)

    def _flush_rx(self):
        """Flush RX FIFO."""
        self.rx_fifo.clear()

    def _process_rx_fifo(self):
        """Process buffered RX data to DMA buffer."""
        if not self.rx_active or not self.mem_write:
            return

        while self.rx_fifo and self.rxd_amount < self.rxd_maxcnt:
            byte = self.rx_fifo.popleft()
            self.mem_write(self.rxd_ptr + self.rxd_amount, bytes([byte]))
            self.rxd_amount += 1
            self.set_event(self.EVENTS_RXDRDY)

        if self.rxd_amount >= self.rxd_maxcnt:
            self.set_event(self.EVENTS_ENDRX)
            self.rx_active = False

    def receive_byte(self, byte: int):
        """Receive a byte from external source."""
        self.rx_fifo.append(byte & 0xFF)
        if self.rx_active:
            self._process_rx_fifo()

    def receive_data(self, data: bytes):
        """Receive data from external source."""
        for byte in data:
            self.receive_byte(byte)

    def transmit_byte(self, byte: int):
        """Transmit a single byte (convenience method for non-DMA use)."""
        if self.on_tx:
            self.on_tx(bytes([byte & 0xFF]))
        self.set_event(self.EVENTS_TXDRDY)

    def transmit_data(self, data: bytes):
        """Transmit data (convenience method for non-DMA use)."""
        if self.on_tx:
            self.on_tx(data)
        for _ in data:
            self.set_event(self.EVENTS_TXDRDY)
