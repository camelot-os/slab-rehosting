"""
STM32 DAC Peripheral Emulation

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable
from .stm32_base import STM32Peripheral


class STM32DAC(STM32Peripheral):
    """
    STM32 DAC peripheral.

    Register Map:
        0x00: CR      - Control register
        0x04: SWTRIGR - Software trigger
        0x08: DHR12R1 - Channel 1 12-bit right-aligned
        0x0C: DHR12L1 - Channel 1 12-bit left-aligned
        0x10: DHR8R1  - Channel 1 8-bit
        0x14: DHR12R2 - Channel 2 12-bit right-aligned
        0x18: DHR12L2 - Channel 2 12-bit left-aligned
        0x1C: DHR8R2  - Channel 2 8-bit
        0x20: DHR12RD - Dual 12-bit right-aligned
        0x24: DHR12LD - Dual 12-bit left-aligned
        0x28: DHR8RD  - Dual 8-bit
        0x2C: DOR1    - Channel 1 output
        0x30: DOR2    - Channel 2 output
        0x34: SR      - Status register
    """

    CR = 0x00
    SWTRIGR = 0x04
    DHR12R1 = 0x08
    DHR12L1 = 0x0C
    DHR8R1 = 0x10
    DHR12R2 = 0x14
    DHR12L2 = 0x18
    DHR8R2 = 0x1C
    DHR12RD = 0x20
    DHR12LD = 0x24
    DHR8RD = 0x28
    DOR1 = 0x2C
    DOR2 = 0x30
    SR = 0x34

    # CR bits per channel
    CR_EN1 = 1 << 0
    CR_TEN1 = 1 << 2
    CR_TSEL1 = 0x7 << 3
    CR_WAVE1 = 0x3 << 6
    CR_MAMP1 = 0xF << 8
    CR_DMAEN1 = 1 << 12
    CR_DMAUDRIE1 = 1 << 13

    CR_EN2 = 1 << 16
    CR_TEN2 = 1 << 18
    CR_TSEL2 = 0x7 << 19
    CR_WAVE2 = 0x3 << 22
    CR_MAMP2 = 0xF << 24
    CR_DMAEN2 = 1 << 28
    CR_DMAUDRIE2 = 1 << 29

    def __init__(self, base: int = 0x40007400):
        super().__init__("DAC", base, 0x400, 54)

        self.cr = 0
        self.dhr12r = [0, 0]
        self.dhr12l = [0, 0]
        self.dhr8r = [0, 0]
        self.dor = [0, 0]
        self.sr = 0

        # Output callbacks
        self.on_output: Optional[Callable[[int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.DHR12R1:
            return self.dhr12r[0]
        elif offset == self.DHR12R2:
            return self.dhr12r[1]
        elif offset == self.DHR12L1:
            return self.dhr12l[0]
        elif offset == self.DHR12L2:
            return self.dhr12l[1]
        elif offset == self.DHR8R1:
            return self.dhr8r[0]
        elif offset == self.DHR8R2:
            return self.dhr8r[1]
        elif offset == self.DOR1:
            return self.dor[0]
        elif offset == self.DOR2:
            return self.dor[1]
        elif offset == self.SR:
            return self.sr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.SWTRIGR:
            if value & 1:
                self._trigger_channel(0)
            if value & 2:
                self._trigger_channel(1)
        elif offset == self.DHR12R1:
            self.dhr12r[0] = value & 0xFFF
            self._update_output(0)
        elif offset == self.DHR12R2:
            self.dhr12r[1] = value & 0xFFF
            self._update_output(1)
        elif offset == self.DHR12L1:
            self.dhr12l[0] = (value >> 4) & 0xFFF
            self._update_output(0)
        elif offset == self.DHR12L2:
            self.dhr12l[1] = (value >> 4) & 0xFFF
            self._update_output(1)
        elif offset == self.DHR8R1:
            self.dhr8r[0] = value & 0xFF
            self._update_output(0)
        elif offset == self.DHR8R2:
            self.dhr8r[1] = value & 0xFF
            self._update_output(1)
        elif offset == self.DHR12RD:
            self.dhr12r[0] = value & 0xFFF
            self.dhr12r[1] = (value >> 16) & 0xFFF
            self._update_output(0)
            self._update_output(1)

    def _trigger_channel(self, ch: int):
        """Software trigger channel."""
        self._update_output(ch)

    def _update_output(self, ch: int):
        """Update DAC output."""
        en_bit = self.CR_EN1 if ch == 0 else self.CR_EN2

        if self.cr & en_bit:
            # Use 12-bit right-aligned value
            self.dor[ch] = self.dhr12r[ch]

            if self.on_output:
                self.on_output(ch, self.dor[ch])
