"""
NRF SPIM/SPIS - EasyDMA SPI

Features:
- Autonomous DMA transfers
- Master (SPIM) and Slave (SPIS) modes
- Configurable frequency up to 32MHz
- Hardware CS control
- RX/TX list mode for scatter-gather

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from .nrf_base import NRFPeripheral


class NRFSPIM(NRFPeripheral):
    """
    NRF SPIM (SPI Master with EasyDMA).

    Register Map:
        0x010: TASKS_START
        0x014: TASKS_STOP
        0x01C: TASKS_SUSPEND
        0x020: TASKS_RESUME
        0x104: EVENTS_STOPPED
        0x110: EVENTS_ENDRX
        0x118: EVENTS_END
        0x120: EVENTS_ENDTX
        0x14C: EVENTS_STARTED
        0x200: SHORTS
        0x300: INTEN
        0x400: STALLSTAT
        0x500: ENABLE
        0x508: PSEL.SCK
        0x50C: PSEL.MOSI
        0x510: PSEL.MISO
        0x514: PSEL.CSN (nRF52840)
        0x524: FREQUENCY
        0x534: RXD.PTR
        0x538: RXD.MAXCNT
        0x53C: RXD.AMOUNT
        0x540: RXD.LIST
        0x544: TXD.PTR
        0x548: TXD.MAXCNT
        0x54C: TXD.AMOUNT
        0x550: TXD.LIST
        0x554: CONFIG
        0x5C0: IFTIMING.RXDELAY (nRF52840)
        0x5C4: IFTIMING.CSNDUR (nRF52840)
        0x5C8: CSNPOL (nRF52840)
        0x5CC: PSELDCX (nRF52840)
        0x5D0: DCXCNT (nRF52840)
        0x5E0: ORC
    """

    # Tasks
    TASKS_START = 0x010
    TASKS_STOP = 0x014
    TASKS_SUSPEND = 0x01C
    TASKS_RESUME = 0x020

    # Events
    EVENTS_STOPPED = 0x104
    EVENTS_ENDRX = 0x110
    EVENTS_END = 0x118
    EVENTS_ENDTX = 0x120
    EVENTS_STARTED = 0x14C

    # Registers
    ENABLE = 0x500
    PSEL_SCK = 0x508
    PSEL_MOSI = 0x50C
    PSEL_MISO = 0x510
    PSEL_CSN = 0x514
    FREQUENCY = 0x524
    RXD_PTR = 0x534
    RXD_MAXCNT = 0x538
    RXD_AMOUNT = 0x53C
    RXD_LIST = 0x540
    TXD_PTR = 0x544
    TXD_MAXCNT = 0x548
    TXD_AMOUNT = 0x54C
    TXD_LIST = 0x550
    CONFIG = 0x554
    ORC = 0x5C0  # Over-read character

    # Frequency values
    FREQ_125K = 0x02000000
    FREQ_250K = 0x04000000
    FREQ_500K = 0x08000000
    FREQ_1M = 0x10000000
    FREQ_2M = 0x20000000
    FREQ_4M = 0x40000000
    FREQ_8M = 0x80000000

    SPIM_BASES = {
        0: 0x40003000,
        1: 0x40004000,
        2: 0x40023000,
        3: 0x4002F000,  # nRF52840
    }

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = self.SPIM_BASES.get(index, 0x40003000)

        super().__init__(f"SPIM{index}", base, 0x1000, irq=3 + index)
        self.index = index

        self.enable = 0
        self.psel_sck = 0xFFFFFFFF
        self.psel_mosi = 0xFFFFFFFF
        self.psel_miso = 0xFFFFFFFF
        self.psel_csn = 0xFFFFFFFF
        self.frequency = self.FREQ_4M
        self.config = 0
        self.orc = 0

        # DMA pointers
        self.rxd_ptr = 0
        self.rxd_maxcnt = 0
        self.rxd_amount = 0
        self.rxd_list = 0
        self.txd_ptr = 0
        self.txd_maxcnt = 0
        self.txd_amount = 0
        self.txd_list = 0

        # State
        self.active = False

        # Memory callbacks
        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None

        # SPI transfer callback
        self.on_transfer: Optional[Callable[[bytes], bytes]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ENABLE:
            return self.enable
        elif offset == self.PSEL_SCK:
            return self.psel_sck
        elif offset == self.PSEL_MOSI:
            return self.psel_mosi
        elif offset == self.PSEL_MISO:
            return self.psel_miso
        elif offset == self.PSEL_CSN:
            return self.psel_csn
        elif offset == self.FREQUENCY:
            return self.frequency
        elif offset == self.RXD_PTR:
            return self.rxd_ptr
        elif offset == self.RXD_MAXCNT:
            return self.rxd_maxcnt
        elif offset == self.RXD_AMOUNT:
            return self.rxd_amount
        elif offset == self.RXD_LIST:
            return self.rxd_list
        elif offset == self.TXD_PTR:
            return self.txd_ptr
        elif offset == self.TXD_MAXCNT:
            return self.txd_maxcnt
        elif offset == self.TXD_AMOUNT:
            return self.txd_amount
        elif offset == self.TXD_LIST:
            return self.txd_list
        elif offset == self.CONFIG:
            return self.config
        elif offset == self.ORC:
            return self.orc
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ENABLE:
            self.enable = value
        elif offset == self.PSEL_SCK:
            self.psel_sck = value
        elif offset == self.PSEL_MOSI:
            self.psel_mosi = value
        elif offset == self.PSEL_MISO:
            self.psel_miso = value
        elif offset == self.PSEL_CSN:
            self.psel_csn = value
        elif offset == self.FREQUENCY:
            self.frequency = value
        elif offset == self.RXD_PTR:
            self.rxd_ptr = value
        elif offset == self.RXD_MAXCNT:
            self.rxd_maxcnt = value
        elif offset == self.RXD_LIST:
            self.rxd_list = value
        elif offset == self.TXD_PTR:
            self.txd_ptr = value
        elif offset == self.TXD_MAXCNT:
            self.txd_maxcnt = value
        elif offset == self.TXD_LIST:
            self.txd_list = value
        elif offset == self.CONFIG:
            self.config = value
        elif offset == self.ORC:
            self.orc = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_START:
            self._start_transfer()
        elif offset == self.TASKS_STOP:
            self._stop_transfer()
        elif offset == self.TASKS_SUSPEND:
            self.active = False
        elif offset == self.TASKS_RESUME:
            self.active = True

    def _start_transfer(self):
        """Start SPI transfer."""
        if self.enable != 7:  # SPIM not enabled
            return

        self.active = True
        self.set_event(self.EVENTS_STARTED)

        # Determine transfer length
        tx_len = self.txd_maxcnt
        rx_len = self.rxd_maxcnt
        xfer_len = max(tx_len, rx_len)

        # Read TX data from memory
        tx_data = bytes([self.orc] * xfer_len)
        if self.mem_read and tx_len > 0:
            tx_data = self.mem_read(self.txd_ptr, tx_len)
            if len(tx_data) < xfer_len:
                tx_data += bytes([self.orc] * (xfer_len - len(tx_data)))

        # Perform transfer
        if self.on_transfer:
            rx_data = self.on_transfer(tx_data)
        else:
            rx_data = bytes([0xFF] * xfer_len)

        # Write RX data to memory
        if self.mem_write and rx_len > 0:
            self.mem_write(self.rxd_ptr, rx_data[:rx_len])

        self.txd_amount = tx_len
        self.rxd_amount = rx_len

        self.set_event(self.EVENTS_ENDTX)
        self.set_event(self.EVENTS_ENDRX)
        self.set_event(self.EVENTS_END)

        self.active = False

    def _stop_transfer(self):
        """Stop SPI transfer."""
        self.active = False
        self.set_event(self.EVENTS_STOPPED)


class NRFSPIS(NRFPeripheral):
    """
    NRF SPIS (SPI Slave with EasyDMA).

    Similar to SPIM but responds to external master.
    """

    TASKS_ACQUIRE = 0x024
    TASKS_RELEASE = 0x028
    EVENTS_END = 0x104
    EVENTS_ENDRX = 0x110
    EVENTS_ACQUIRED = 0x128

    ENABLE = 0x500
    PSEL_SCK = 0x508
    PSEL_MISO = 0x50C
    PSEL_MOSI = 0x510
    PSEL_CSN = 0x514
    RXD_PTR = 0x534
    RXD_MAXCNT = 0x538
    RXD_AMOUNT = 0x53C
    TXD_PTR = 0x544
    TXD_MAXCNT = 0x548
    TXD_AMOUNT = 0x54C
    CONFIG = 0x554
    DEF = 0x55C
    ORC = 0x5C0

    def __init__(self, index: int = 0, base: int = 0x40003000):
        super().__init__(f"SPIS{index}", base, 0x1000, irq=3 + index)
        self.index = index

        self.enable = 0
        self.config = 0
        self.def_char = 0
        self.orc = 0

        self.rxd_ptr = 0
        self.rxd_maxcnt = 0
        self.rxd_amount = 0
        self.txd_ptr = 0
        self.txd_maxcnt = 0
        self.txd_amount = 0

        self.semaphore = 0  # 0=free, 1=CPU, 2=SPIS

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ENABLE:
            return self.enable
        elif offset == self.RXD_AMOUNT:
            return self.rxd_amount
        elif offset == self.TXD_AMOUNT:
            return self.txd_amount
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        self.regs[offset] = value
        if offset == self.ENABLE:
            self.enable = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_ACQUIRE:
            self.semaphore = 1  # CPU owns
            self.set_event(self.EVENTS_ACQUIRED)
        elif offset == self.TASKS_RELEASE:
            self.semaphore = 2  # SPIS owns
