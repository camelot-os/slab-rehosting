"""
LPC55xx CTimer Peripheral

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from .nxp_base import NXPPeripheral


class LPCCTimer(NXPPeripheral):
    """
    LPC55xx Standard Counter/Timer (CTIMER).

    Features:
    - 32-bit counter
    - 4 match registers with actions
    - 4 capture channels
    - PWM generation
    - External count input

    Memory Map:
        0x00: IR - Interrupt register
        0x04: TCR - Timer control
        0x08: TC - Timer counter
        0x0C: PR - Prescale register
        0x10: PC - Prescale counter
        0x14: MCR - Match control
        0x18: MR0 - Match register 0
        0x1C: MR1 - Match register 1
        0x20: MR2 - Match register 2
        0x24: MR3 - Match register 3
        0x28: CCR - Capture control
        0x2C: CR0 - Capture register 0
        0x30: CR1 - Capture register 1
        0x34: CR2 - Capture register 2
        0x38: CR3 - Capture register 3
        0x3C: EMR - External match
        0x70: CTCR - Count control
        0x74: PWMC - PWM control
        0x78: MSR0-3 - Match shadow registers
    """

    # Register offsets
    IR = 0x00
    TCR = 0x04
    TC = 0x08
    PR = 0x0C
    PC = 0x10
    MCR = 0x14
    MR0 = 0x18
    MR1 = 0x1C
    MR2 = 0x20
    MR3 = 0x24
    CCR = 0x28
    CR0 = 0x2C
    CR1 = 0x30
    CR2 = 0x34
    CR3 = 0x38
    EMR = 0x3C
    CTCR = 0x70
    PWMC = 0x74
    MSR0 = 0x78
    MSR1 = 0x7C
    MSR2 = 0x80
    MSR3 = 0x84

    # TCR bits
    TCR_CEN = (1 << 0)     # Counter enable
    TCR_CRST = (1 << 1)    # Counter reset

    # MCR bits per match channel
    MCR_INT = 0x01         # Interrupt on match
    MCR_RESET = 0x02       # Reset on match
    MCR_STOP = 0x04        # Stop on match

    # IR bits
    IR_MR0 = (1 << 0)
    IR_MR1 = (1 << 1)
    IR_MR2 = (1 << 2)
    IR_MR3 = (1 << 3)
    IR_CR0 = (1 << 4)
    IR_CR1 = (1 << 5)
    IR_CR2 = (1 << 6)
    IR_CR3 = (1 << 7)

    def __init__(self, index: int, base: int):
        super().__init__(f"CTIMER{index}", base, 0x1000)
        self.index = index

        # State
        self.ir = 0
        self.tcr = 0
        self.tc = 0
        self.pr = 0
        self.pc = 0
        self.mcr = 0
        self.mr = [0, 0, 0, 0]
        self.ccr = 0
        self.cr = [0, 0, 0, 0]
        self.emr = 0
        self.ctcr = 0
        self.pwmc = 0
        self.msr = [0, 0, 0, 0]

        # Cycle count for timing
        self.cycles = 0

    def tick(self, cycles: int = 1):
        """Advance timer by cycles."""
        if not (self.tcr & self.TCR_CEN):
            return

        for _ in range(cycles):
            self.pc += 1
            if self.pc > self.pr:
                self.pc = 0
                self._increment_counter()

    def _increment_counter(self):
        """Increment main counter and check matches."""
        self.tc = (self.tc + 1) & 0xFFFFFFFF

        # Check match registers
        for i in range(4):
            if self.tc == self.mr[i]:
                self._handle_match(i)

    def _handle_match(self, channel: int):
        """Handle match event on channel."""
        mcr_shift = channel * 3
        mcr_bits = (self.mcr >> mcr_shift) & 0x07

        if mcr_bits & self.MCR_INT:
            self.ir |= (1 << channel)
            self.trigger_irq(1)

        if mcr_bits & self.MCR_RESET:
            self.tc = 0

        if mcr_bits & self.MCR_STOP:
            self.tcr &= ~self.TCR_CEN

        # PWM mode - toggle external match
        if self.pwmc & (1 << channel):
            self.emr ^= (1 << channel)

    def capture(self, channel: int):
        """Capture current counter value."""
        if channel < 4:
            self.cr[channel] = self.tc
            # Check if capture interrupt enabled
            ccr_shift = channel * 3
            if self.ccr & (1 << ccr_shift):  # Rising edge
                self.ir |= (1 << (4 + channel))
                self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.IR:
            return self.ir
        elif offset == self.TCR:
            return self.tcr
        elif offset == self.TC:
            return self.tc
        elif offset == self.PR:
            return self.pr
        elif offset == self.PC:
            return self.pc
        elif offset == self.MCR:
            return self.mcr
        elif offset == self.MR0:
            return self.mr[0]
        elif offset == self.MR1:
            return self.mr[1]
        elif offset == self.MR2:
            return self.mr[2]
        elif offset == self.MR3:
            return self.mr[3]
        elif offset == self.CCR:
            return self.ccr
        elif offset == self.CR0:
            return self.cr[0]
        elif offset == self.CR1:
            return self.cr[1]
        elif offset == self.CR2:
            return self.cr[2]
        elif offset == self.CR3:
            return self.cr[3]
        elif offset == self.EMR:
            return self.emr
        elif offset == self.CTCR:
            return self.ctcr
        elif offset == self.PWMC:
            return self.pwmc
        elif offset == self.MSR0:
            return self.msr[0]
        elif offset == self.MSR1:
            return self.msr[1]
        elif offset == self.MSR2:
            return self.msr[2]
        elif offset == self.MSR3:
            return self.msr[3]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.IR:
            # Write 1 to clear
            self.ir &= ~value
        elif offset == self.TCR:
            if value & self.TCR_CRST:
                self.tc = 0
                self.pc = 0
            self.tcr = value & ~self.TCR_CRST
        elif offset == self.TC:
            self.tc = value & 0xFFFFFFFF
        elif offset == self.PR:
            self.pr = value & 0xFFFFFFFF
        elif offset == self.PC:
            self.pc = value & 0xFFFFFFFF
        elif offset == self.MCR:
            self.mcr = value & 0xFFFF
        elif offset == self.MR0:
            self.mr[0] = value & 0xFFFFFFFF
        elif offset == self.MR1:
            self.mr[1] = value & 0xFFFFFFFF
        elif offset == self.MR2:
            self.mr[2] = value & 0xFFFFFFFF
        elif offset == self.MR3:
            self.mr[3] = value & 0xFFFFFFFF
        elif offset == self.CCR:
            self.ccr = value & 0xFFF
        elif offset == self.EMR:
            self.emr = value & 0xFFF
        elif offset == self.CTCR:
            self.ctcr = value & 0x0F
        elif offset == self.PWMC:
            self.pwmc = value & 0x0F
        elif offset == self.MSR0:
            self.msr[0] = value & 0xFFFFFFFF
        elif offset == self.MSR1:
            self.msr[1] = value & 0xFFFFFFFF
        elif offset == self.MSR2:
            self.msr[2] = value & 0xFFFFFFFF
        elif offset == self.MSR3:
            self.msr[3] = value & 0xFFFFFFFF
