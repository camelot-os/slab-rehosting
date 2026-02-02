"""
NRF TIMER and RTC Peripherals

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable
from .nrf_base import NRFPeripheral


class NRFTIMER(NRFPeripheral):
    """NRF General Purpose Timer (32-bit, up to 6 CC registers)."""

    TASKS_START = 0x000
    TASKS_STOP = 0x004
    TASKS_COUNT = 0x008
    TASKS_CLEAR = 0x00C
    TASKS_SHUTDOWN = 0x010
    TASKS_CAPTURE_BASE = 0x040  # [0-5]

    EVENTS_COMPARE_BASE = 0x140  # [0-5]

    MODE = 0x504
    BITMODE = 0x508
    PRESCALER = 0x510
    CC_BASE = 0x540  # [0-5]

    TIMER_BASES = {
        0: 0x40008000,
        1: 0x40009000,
        2: 0x4000A000,
        3: 0x4001A000,
        4: 0x4001B000,
    }

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = self.TIMER_BASES.get(index, 0x40008000)
        super().__init__(f"TIMER{index}", base, 0x1000, irq=8 + index)

        self.mode = 0  # 0=timer, 1=counter, 2=low-power counter
        self.bitmode = 0  # 0=16bit, 1=8bit, 2=24bit, 3=32bit
        self.prescaler = 0
        self.cc = [0] * 6
        self.counter = 0
        self.running = False

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.MODE:
            return self.mode
        elif offset == self.BITMODE:
            return self.bitmode
        elif offset == self.PRESCALER:
            return self.prescaler
        elif self.CC_BASE <= offset < self.CC_BASE + 24:
            idx = (offset - self.CC_BASE) // 4
            return self.cc[idx] if idx < 6 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.MODE:
            self.mode = value & 0x3
        elif offset == self.BITMODE:
            self.bitmode = value & 0x3
        elif offset == self.PRESCALER:
            self.prescaler = value & 0xF
        elif self.CC_BASE <= offset < self.CC_BASE + 24:
            idx = (offset - self.CC_BASE) // 4
            if idx < 6:
                self.cc[idx] = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_START:
            self.running = True
        elif offset == self.TASKS_STOP:
            self.running = False
        elif offset == self.TASKS_CLEAR:
            self.counter = 0
        elif self.TASKS_CAPTURE_BASE <= offset < self.TASKS_CAPTURE_BASE + 24:
            idx = (offset - self.TASKS_CAPTURE_BASE) // 4
            if idx < 6:
                self.cc[idx] = self._get_counter()

    def _get_counter(self) -> int:
        masks = [0xFFFF, 0xFF, 0xFFFFFF, 0xFFFFFFFF]
        return self.counter & masks[self.bitmode]

    def tick(self):
        """Advance timer by one tick."""
        if not self.running or self.mode != 0:
            return

        self.counter += 1
        counter = self._get_counter()

        for i in range(6):
            if counter == self.cc[i]:
                self.set_event(self.EVENTS_COMPARE_BASE + i * 4)


class NRFRTC(NRFPeripheral):
    """NRF Real-Time Counter (24-bit, low power)."""

    TASKS_START = 0x000
    TASKS_STOP = 0x004
    TASKS_CLEAR = 0x008
    TASKS_TRIGOVRFLW = 0x00C

    EVENTS_TICK = 0x100
    EVENTS_OVRFLW = 0x104
    EVENTS_COMPARE_BASE = 0x140  # [0-3]

    PRESCALER = 0x508
    COUNTER = 0x504
    CC_BASE = 0x540  # [0-3]
    EVTEN = 0x340
    EVTENSET = 0x344
    EVTENCLR = 0x348

    RTC_BASES = {0: 0x4000B000, 1: 0x40011000, 2: 0x40024000}

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = self.RTC_BASES.get(index, 0x4000B000)
        super().__init__(f"RTC{index}", base, 0x1000, irq=11 + index)

        self.prescaler = 0
        self.counter = 0
        self.cc = [0] * 4
        self.evten = 0
        self.running = False
        self._prescaler_counter = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.PRESCALER:
            return self.prescaler
        elif offset == self.COUNTER:
            return self.counter & 0xFFFFFF
        elif offset == self.EVTEN:
            return self.evten
        elif self.CC_BASE <= offset < self.CC_BASE + 16:
            idx = (offset - self.CC_BASE) // 4
            return self.cc[idx] if idx < 4 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.PRESCALER:
            self.prescaler = value & 0xFFF
        elif offset == self.EVTENSET:
            self.evten |= value
        elif offset == self.EVTENCLR:
            self.evten &= ~value
        elif self.CC_BASE <= offset < self.CC_BASE + 16:
            idx = (offset - self.CC_BASE) // 4
            if idx < 4:
                self.cc[idx] = value & 0xFFFFFF

    def _handle_task(self, offset: int):
        if offset == self.TASKS_START:
            self.running = True
        elif offset == self.TASKS_STOP:
            self.running = False
        elif offset == self.TASKS_CLEAR:
            self.counter = 0
        elif offset == self.TASKS_TRIGOVRFLW:
            self.counter = 0xFFFFF0

    def tick_lfclk(self):
        """Called at 32.768 kHz LFCLK rate."""
        if not self.running:
            return

        self._prescaler_counter += 1
        if self._prescaler_counter > self.prescaler:
            self._prescaler_counter = 0
            self.counter = (self.counter + 1) & 0xFFFFFF
            self.set_event(self.EVENTS_TICK)

            if self.counter == 0:
                self.set_event(self.EVENTS_OVRFLW)

            for i in range(4):
                if self.counter == self.cc[i]:
                    self.set_event(self.EVENTS_COMPARE_BASE + i * 4)
