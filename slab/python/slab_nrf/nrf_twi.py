"""
NRF TWIM/TWIS - EasyDMA I2C (Two-Wire Interface)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable
from .nrf_base import NRFPeripheral


class NRFTWIM(NRFPeripheral):
    """NRF TWIM (I2C Master with EasyDMA)."""

    TASKS_STARTRX = 0x000
    TASKS_STARTTX = 0x008
    TASKS_STOP = 0x014
    TASKS_SUSPEND = 0x01C
    TASKS_RESUME = 0x020

    EVENTS_STOPPED = 0x104
    EVENTS_ERROR = 0x124
    EVENTS_SUSPENDED = 0x148
    EVENTS_RXSTARTED = 0x14C
    EVENTS_TXSTARTED = 0x150
    EVENTS_LASTRX = 0x15C
    EVENTS_LASTTX = 0x160

    ENABLE = 0x500
    PSEL_SCL = 0x508
    PSEL_SDA = 0x50C
    FREQUENCY = 0x524
    RXD_PTR = 0x534
    RXD_MAXCNT = 0x538
    RXD_AMOUNT = 0x53C
    TXD_PTR = 0x544
    TXD_MAXCNT = 0x548
    TXD_AMOUNT = 0x54C
    ADDRESS = 0x588
    ERRORSRC = 0x4C4

    FREQ_100K = 0x01980000
    FREQ_250K = 0x04000000
    FREQ_400K = 0x06400000

    TWIM_BASES = {0: 0x40003000, 1: 0x40004000}

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = self.TWIM_BASES.get(index, 0x40003000)
        super().__init__(f"TWIM{index}", base, 0x1000, irq=3 + index)

        self.enable = 0
        self.frequency = self.FREQ_100K
        self.address = 0
        self.errorsrc = 0
        self.rxd_ptr = 0
        self.rxd_maxcnt = 0
        self.rxd_amount = 0
        self.txd_ptr = 0
        self.txd_maxcnt = 0
        self.txd_amount = 0

        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None
        self.on_transfer: Optional[Callable[[int, bytes, bool], bytes]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.ENABLE: self.enable,
            self.FREQUENCY: self.frequency,
            self.ADDRESS: self.address,
            self.ERRORSRC: self.errorsrc,
            self.RXD_PTR: self.rxd_ptr,
            self.RXD_MAXCNT: self.rxd_maxcnt,
            self.RXD_AMOUNT: self.rxd_amount,
            self.TXD_PTR: self.txd_ptr,
            self.TXD_MAXCNT: self.txd_maxcnt,
            self.TXD_AMOUNT: self.txd_amount,
        }
        return regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ENABLE:
            self.enable = value
        elif offset == self.FREQUENCY:
            self.frequency = value
        elif offset == self.ADDRESS:
            self.address = value & 0x7F
        elif offset == self.ERRORSRC:
            self.errorsrc &= ~value
        elif offset == self.RXD_PTR:
            self.rxd_ptr = value
        elif offset == self.RXD_MAXCNT:
            self.rxd_maxcnt = value
        elif offset == self.TXD_PTR:
            self.txd_ptr = value
        elif offset == self.TXD_MAXCNT:
            self.txd_maxcnt = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_STARTTX:
            self._start_tx()
        elif offset == self.TASKS_STARTRX:
            self._start_rx()
        elif offset == self.TASKS_STOP:
            self.set_event(self.EVENTS_STOPPED)

    def _start_tx(self):
        if self.enable != 6:
            return
        self.set_event(self.EVENTS_TXSTARTED)
        if self.mem_read and self.txd_maxcnt > 0:
            data = self.mem_read(self.txd_ptr, self.txd_maxcnt)
            if self.on_transfer:
                self.on_transfer(self.address, data, False)
            self.txd_amount = len(data)
        self.set_event(self.EVENTS_LASTTX)

    def _start_rx(self):
        if self.enable != 6:
            return
        self.set_event(self.EVENTS_RXSTARTED)
        if self.on_transfer:
            rx_data = self.on_transfer(self.address, b'', True)
            if self.mem_write and rx_data:
                self.mem_write(self.rxd_ptr, rx_data[:self.rxd_maxcnt])
                self.rxd_amount = min(len(rx_data), self.rxd_maxcnt)
        self.set_event(self.EVENTS_LASTRX)


class NRFTWIS(NRFPeripheral):
    """NRF TWIS (I2C Slave with EasyDMA)."""

    TASKS_STOP = 0x014
    TASKS_SUSPEND = 0x01C
    TASKS_RESUME = 0x020
    TASKS_PREPARERX = 0x030
    TASKS_PREPARETX = 0x034

    EVENTS_STOPPED = 0x104
    EVENTS_ERROR = 0x124
    EVENTS_RXSTARTED = 0x14C
    EVENTS_TXSTARTED = 0x150
    EVENTS_WRITE = 0x164
    EVENTS_READ = 0x168

    ENABLE = 0x500
    PSEL_SCL = 0x508
    PSEL_SDA = 0x50C
    ADDRESS0 = 0x588
    ADDRESS1 = 0x58C
    CONFIG = 0x594

    def __init__(self, index: int = 0, base: int = 0x40003000):
        super().__init__(f"TWIS{index}", base, 0x1000, irq=3 + index)
        self.enable = 0
        self.address0 = 0
        self.address1 = 0
        self.config = 0

    def _read_reg(self, offset: int, size: int) -> int:
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        self.regs[offset] = value

    def _handle_task(self, offset: int):
        pass
