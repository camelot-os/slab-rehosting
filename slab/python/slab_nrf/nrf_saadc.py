"""
NRF SAADC - Successive Approximation ADC

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List
from .nrf_base import NRFPeripheral


class NRFSAADC(NRFPeripheral):
    """NRF SAADC (12-14 bit resolution, 8 channels)."""

    TASKS_START = 0x000
    TASKS_SAMPLE = 0x004
    TASKS_STOP = 0x008
    TASKS_CALIBRATEOFFSET = 0x00C

    EVENTS_STARTED = 0x100
    EVENTS_END = 0x104
    EVENTS_DONE = 0x108
    EVENTS_RESULTDONE = 0x10C
    EVENTS_CALIBRATEDONE = 0x110
    EVENTS_STOPPED = 0x114
    EVENTS_CH_BASE = 0x118  # LIMITH/LIMITL per channel

    ENABLE = 0x500
    CH_BASE = 0x510  # Channel config (PSELP, PSELN, CONFIG, LIMIT)
    RESOLUTION = 0x5F0
    OVERSAMPLE = 0x5F4
    SAMPLERATE = 0x5F8
    RESULT_PTR = 0x62C
    RESULT_MAXCNT = 0x630
    RESULT_AMOUNT = 0x634

    def __init__(self, base: int = 0x40007000):
        super().__init__("SAADC", base, 0x1000, irq=7)

        self.enable = 0
        self.resolution = 2  # 0=8bit, 1=10bit, 2=12bit, 3=14bit
        self.oversample = 0
        self.samplerate = 0
        self.result_ptr = 0
        self.result_maxcnt = 0
        self.result_amount = 0
        self.ch_config = [{'pselp': 0, 'pseln': 0, 'config': 0, 'limit': 0} for _ in range(8)]

        self.channel_values: List[int] = [2048] * 8
        self.mem_write: Optional[Callable[[int, bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ENABLE:
            return self.enable
        elif offset == self.RESOLUTION:
            return self.resolution
        elif offset == self.RESULT_PTR:
            return self.result_ptr
        elif offset == self.RESULT_MAXCNT:
            return self.result_maxcnt
        elif offset == self.RESULT_AMOUNT:
            return self.result_amount
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ENABLE:
            self.enable = value
        elif offset == self.RESOLUTION:
            self.resolution = value & 0x3
        elif offset == self.RESULT_PTR:
            self.result_ptr = value
        elif offset == self.RESULT_MAXCNT:
            self.result_maxcnt = value
        else:
            self.regs[offset] = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_START:
            self.set_event(self.EVENTS_STARTED)
        elif offset == self.TASKS_SAMPLE:
            self._do_sample()
        elif offset == self.TASKS_STOP:
            self.set_event(self.EVENTS_STOPPED)
        elif offset == self.TASKS_CALIBRATEOFFSET:
            self.set_event(self.EVENTS_CALIBRATEDONE)

    def _do_sample(self):
        """Perform ADC sampling."""
        if self.enable != 1:
            return

        results = []
        for ch in range(8):
            pselp = self.regs.get(self.CH_BASE + ch * 16, 0)
            if pselp != 0:  # Channel enabled
                value = self.channel_values[ch]
                # Apply resolution
                shifts = [4, 2, 0, 0]
                value = value >> shifts[self.resolution]
                results.append(value)

        if self.mem_write and results:
            data = b''.join(v.to_bytes(2, 'little') for v in results[:self.result_maxcnt])
            self.mem_write(self.result_ptr, data)
            self.result_amount = len(results)

        self.set_event(self.EVENTS_DONE)
        self.set_event(self.EVENTS_RESULTDONE)
        self.set_event(self.EVENTS_END)

    def set_channel_value(self, ch: int, value: int):
        if 0 <= ch < 8:
            self.channel_values[ch] = value & 0x3FFF
