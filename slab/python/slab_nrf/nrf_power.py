"""
NRF POWER and CLOCK Peripherals

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from .nrf_base import NRFPeripheral


class NRFPOWER(NRFPeripheral):
    """NRF Power Management Unit."""

    TASKS_CONSTLAT = 0x078
    TASKS_LOWPWR = 0x07C
    EVENTS_POFWARN = 0x108
    EVENTS_SLEEPENTER = 0x114
    EVENTS_SLEEPEXIT = 0x118
    EVENTS_USBDETECTED = 0x11C
    EVENTS_USBREMOVED = 0x120
    EVENTS_USBPWRRDY = 0x124

    RESETREAS = 0x400
    RAMSTATUS = 0x428
    USBREGSTATUS = 0x438
    SYSTEMOFF = 0x500
    POFCON = 0x510
    GPREGRET = 0x51C
    GPREGRET2 = 0x520
    DCDCEN = 0x578
    DCDCEN0 = 0x578
    MAINREGSTATUS = 0x640

    RAM_BASE = 0x900  # RAM power control

    def __init__(self, base: int = 0x40000000):
        super().__init__("POWER", base, 0x1000, irq=0)

        self.resetreas = 0x01  # Power-on reset
        self.pofcon = 0
        self.gpregret = 0
        self.gpregret2 = 0
        self.dcdcen = 0
        self.mainregstatus = 1  # Main regulator
        self.usbregstatus = 0

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.RESETREAS: self.resetreas,
            self.RAMSTATUS: 0xFFFF,  # All RAM retained
            self.USBREGSTATUS: self.usbregstatus,
            self.POFCON: self.pofcon,
            self.GPREGRET: self.gpregret,
            self.GPREGRET2: self.gpregret2,
            self.DCDCEN: self.dcdcen,
            self.MAINREGSTATUS: self.mainregstatus,
        }
        return regs.get(offset, self.regs.get(offset, 0))

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.RESETREAS:
            self.resetreas &= ~value
        elif offset == self.SYSTEMOFF:
            pass  # System off - no action in emulator
        elif offset == self.POFCON:
            self.pofcon = value
        elif offset == self.GPREGRET:
            self.gpregret = value & 0xFF
        elif offset == self.GPREGRET2:
            self.gpregret2 = value & 0xFF
        elif offset == self.DCDCEN:
            self.dcdcen = value & 1
        else:
            self.regs[offset] = value


class NRFCLOCK(NRFPeripheral):
    """NRF Clock Control."""

    TASKS_HFCLKSTART = 0x000
    TASKS_HFCLKSTOP = 0x004
    TASKS_LFCLKSTART = 0x008
    TASKS_LFCLKSTOP = 0x00C
    TASKS_CAL = 0x010
    TASKS_CTSTART = 0x014
    TASKS_CTSTOP = 0x018

    EVENTS_HFCLKSTARTED = 0x100
    EVENTS_LFCLKSTARTED = 0x104
    EVENTS_DONE = 0x10C
    EVENTS_CTTO = 0x110

    HFCLKRUN = 0x408
    HFCLKSTAT = 0x40C
    LFCLKRUN = 0x414
    LFCLKSTAT = 0x418
    LFCLKSRCCOPY = 0x41C
    LFCLKSRC = 0x518
    HFXODEBOUNCE = 0x528
    CTIV = 0x538
    TRACECONFIG = 0x55C

    def __init__(self, base: int = 0x40000000):
        super().__init__("CLOCK", base, 0x1000, irq=0)

        self.hfclkrun = 0
        self.hfclkstat = 0
        self.lfclkrun = 0
        self.lfclkstat = 0
        self.lfclksrc = 0  # 0=RC, 1=XTAL, 2=Synth

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.HFCLKRUN: self.hfclkrun,
            self.HFCLKSTAT: self.hfclkstat,
            self.LFCLKRUN: self.lfclkrun,
            self.LFCLKSTAT: self.lfclkstat,
            self.LFCLKSRC: self.lfclksrc,
        }
        return regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.LFCLKSRC:
            self.lfclksrc = value & 0x3

    def _handle_task(self, offset: int):
        if offset == self.TASKS_HFCLKSTART:
            self.hfclkrun = 1
            self.hfclkstat = 0x10001  # Running from XTAL
            self.set_event(self.EVENTS_HFCLKSTARTED)
        elif offset == self.TASKS_HFCLKSTOP:
            self.hfclkrun = 0
            self.hfclkstat = 0
        elif offset == self.TASKS_LFCLKSTART:
            self.lfclkrun = 1
            self.lfclkstat = (self.lfclksrc << 16) | 1  # Running
            self.set_event(self.EVENTS_LFCLKSTARTED)
        elif offset == self.TASKS_LFCLKSTOP:
            self.lfclkrun = 0
            self.lfclkstat = 0
        elif offset == self.TASKS_CAL:
            self.set_event(self.EVENTS_DONE)
