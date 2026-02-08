"""
i.MX RT Timer Peripherals - GPT and PIT

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable
from .nxp_base import NXPPeripheral


class IMXRTGPT(NXPPeripheral):
    """
    i.MX RT General Purpose Timer.

    Features:
    - 32-bit counter
    - 3 output compare channels
    - 2 input capture channels
    - 12-bit prescaler
    - Free-run or restart modes

    Memory Map:
        0x00: CR - Control register
        0x04: PR - Prescaler
        0x08: SR - Status register
        0x0C: IR - Interrupt register
        0x10: OCR1 - Output compare 1
        0x14: OCR2 - Output compare 2
        0x18: OCR3 - Output compare 3
        0x1C: ICR1 - Input capture 1
        0x20: ICR2 - Input capture 2
        0x24: CNT - Counter value
    """

    # Register offsets
    CR = 0x00
    PR = 0x04
    SR = 0x08
    IR = 0x0C
    OCR1 = 0x10
    OCR2 = 0x14
    OCR3 = 0x18
    ICR1 = 0x1C
    ICR2 = 0x20
    CNT = 0x24

    # CR bits
    CR_EN = (1 << 0)           # Timer enable
    CR_ENMOD = (1 << 1)        # Enable mode (reset on enable)
    CR_DBGEN = (1 << 2)        # Debug enable
    CR_WAITEN = (1 << 3)       # Wait enable
    CR_DOZEEN = (1 << 4)       # Doze enable
    CR_STOPEN = (1 << 5)       # Stop enable
    CR_CLKSRC_MASK = (0x07 << 6)
    CR_FRR = (1 << 9)          # Free-run/restart
    CR_EN_24M = (1 << 10)      # 24MHz oscillator enable
    CR_SWR = (1 << 15)         # Software reset
    CR_IM1_MASK = (0x03 << 16)
    CR_IM2_MASK = (0x03 << 18)
    CR_OM1_MASK = (0x07 << 20)
    CR_OM2_MASK = (0x07 << 23)
    CR_OM3_MASK = (0x07 << 26)
    CR_FO1 = (1 << 29)         # Force output compare 1
    CR_FO2 = (1 << 30)         # Force output compare 2
    CR_FO3 = (1 << 31)         # Force output compare 3

    # SR bits
    SR_OF1 = (1 << 0)          # Output compare 1 flag
    SR_OF2 = (1 << 1)          # Output compare 2 flag
    SR_OF3 = (1 << 2)          # Output compare 3 flag
    SR_IF1 = (1 << 3)          # Input capture 1 flag
    SR_IF2 = (1 << 4)          # Input capture 2 flag
    SR_ROV = (1 << 5)          # Rollover flag

    # IR bits (same positions as SR)
    IR_OF1IE = (1 << 0)
    IR_OF2IE = (1 << 1)
    IR_OF3IE = (1 << 2)
    IR_IF1IE = (1 << 3)
    IR_IF2IE = (1 << 4)
    IR_ROVIE = (1 << 5)

    def __init__(self, index: int, base: int):
        super().__init__(f"GPT{index}", base, 0x1000)
        self.index = index

        # Registers
        self.cr = 0
        self.pr = 0
        self.sr = 0
        self.ir = 0
        self.ocr = [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]
        self.icr = [0, 0]
        self.cnt = 0

        # Internal state
        self._prescale_counter = 0

    def tick(self, cycles: int = 1):
        """Advance timer by cycles."""
        if not (self.cr & self.CR_EN):
            return

        for _ in range(cycles):
            self._prescale_counter += 1
            if self._prescale_counter > (self.pr & 0xFFF):
                self._prescale_counter = 0
                self._increment_counter()

    def _increment_counter(self):
        """Increment main counter and check compare."""
        self.cnt = (self.cnt + 1) & 0xFFFFFFFF

        # Check rollover
        if self.cnt == 0:
            self.sr |= self.SR_ROV
            if self.ir & self.IR_ROVIE:
                self.trigger_irq(1)

        # Check output compares
        for i in range(3):
            if self.cnt == self.ocr[i]:
                self.sr |= (self.SR_OF1 << i)
                if self.ir & (self.IR_OF1IE << i):
                    self.trigger_irq(1)

                # Restart mode?
                if i == 0 and not (self.cr & self.CR_FRR):
                    self.cnt = 0

    def capture(self, channel: int):
        """Capture counter value on input channel."""
        if channel < 2:
            self.icr[channel] = self.cnt
            self.sr |= (self.SR_IF1 << channel)
            if self.ir & (self.IR_IF1IE << channel):
                self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.PR:
            return self.pr
        elif offset == self.SR:
            return self.sr
        elif offset == self.IR:
            return self.ir
        elif offset == self.OCR1:
            return self.ocr[0]
        elif offset == self.OCR2:
            return self.ocr[1]
        elif offset == self.OCR3:
            return self.ocr[2]
        elif offset == self.ICR1:
            return self.icr[0]
        elif offset == self.ICR2:
            return self.icr[1]
        elif offset == self.CNT:
            return self.cnt
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            if value & self.CR_SWR:
                self._reset()
                return
            if (value & self.CR_EN) and (value & self.CR_ENMOD):
                self.cnt = 0
            self.cr = value & ~self.CR_SWR
        elif offset == self.PR:
            self.pr = value & 0xFFF
        elif offset == self.SR:
            # W1C
            self.sr &= ~(value & 0x3F)
        elif offset == self.IR:
            self.ir = value & 0x3F
        elif offset == self.OCR1:
            self.ocr[0] = value
        elif offset == self.OCR2:
            self.ocr[1] = value
        elif offset == self.OCR3:
            self.ocr[2] = value

    def _reset(self):
        """Reset timer."""
        self.cr = 0
        self.pr = 0
        self.sr = 0
        self.ir = 0
        self.ocr = [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]
        self.icr = [0, 0]
        self.cnt = 0
        self._prescale_counter = 0


class IMXRTPIT(NXPPeripheral):
    """
    i.MX RT Periodic Interrupt Timer.

    Features:
    - 4 independent 32-bit timer channels
    - Can chain timers for 64-bit operation
    - Periodic or one-shot modes
    - DMA support

    Memory Map:
        0x00: MCR - Module control
        0x0C: LTMR64H - Lifetime timer high
        0x10: LTMR64L - Lifetime timer low
        Per channel (N = 0-3), offset = 0x100 + N*0x10:
        0x100: LDVAL - Load value
        0x104: CVAL - Current value
        0x108: TCTRL - Timer control
        0x10C: TFLG - Timer flag
    """

    MCR = 0x00
    LTMR64H = 0x0C
    LTMR64L = 0x10
    CHAN_BASE = 0x100
    CHAN_SIZE = 0x10

    # MCR bits
    MCR_FRZ = (1 << 0)         # Freeze
    MCR_MDIS = (1 << 1)        # Module disable

    # TCTRL bits
    TCTRL_TEN = (1 << 0)       # Timer enable
    TCTRL_TIE = (1 << 1)       # Interrupt enable
    TCTRL_CHN = (1 << 2)       # Chain mode

    # TFLG bits
    TFLG_TIF = (1 << 0)        # Timer interrupt flag

    def __init__(self, base: int = 0x40084000):
        super().__init__("PIT", base, 0x1000)

        # Module control
        self.mcr = self.MCR_MDIS

        # 4 timer channels
        self.ldval = [0, 0, 0, 0]
        self.cval = [0, 0, 0, 0]
        self.tctrl = [0, 0, 0, 0]
        self.tflg = [0, 0, 0, 0]

        # Lifetime counter
        self.lifetime = 0

    def tick(self, cycles: int = 1):
        """Advance timers by cycles."""
        if self.mcr & self.MCR_MDIS:
            return

        for _ in range(cycles):
            self.lifetime += 1
            self._tick_channels()

    def _tick_channels(self):
        """Tick all enabled channels."""
        for ch in range(4):
            if not (self.tctrl[ch] & self.TCTRL_TEN):
                continue

            # Chain mode - only count when previous timer reaches 0
            if (self.tctrl[ch] & self.TCTRL_CHN) and ch > 0:
                if self.cval[ch - 1] != 0:
                    continue

            if self.cval[ch] > 0:
                self.cval[ch] -= 1
            else:
                # Timeout
                self.cval[ch] = self.ldval[ch]
                self.tflg[ch] |= self.TFLG_TIF

                if self.tctrl[ch] & self.TCTRL_TIE:
                    self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.MCR:
            return self.mcr
        elif offset == self.LTMR64H:
            return (self.lifetime >> 32) & 0xFFFFFFFF
        elif offset == self.LTMR64L:
            return self.lifetime & 0xFFFFFFFF
        elif offset >= self.CHAN_BASE:
            ch = (offset - self.CHAN_BASE) // self.CHAN_SIZE
            reg = (offset - self.CHAN_BASE) % self.CHAN_SIZE
            if ch < 4:
                if reg == 0x00:
                    return self.ldval[ch]
                elif reg == 0x04:
                    return self.cval[ch]
                elif reg == 0x08:
                    return self.tctrl[ch]
                elif reg == 0x0C:
                    return self.tflg[ch]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.MCR:
            self.mcr = value & 0x03
        elif offset >= self.CHAN_BASE:
            ch = (offset - self.CHAN_BASE) // self.CHAN_SIZE
            reg = (offset - self.CHAN_BASE) % self.CHAN_SIZE
            if ch < 4:
                if reg == 0x00:
                    self.ldval[ch] = value
                    self.cval[ch] = value
                elif reg == 0x08:
                    self.tctrl[ch] = value & 0x07
                elif reg == 0x0C:
                    # W1C
                    self.tflg[ch] &= ~(value & 0x01)
