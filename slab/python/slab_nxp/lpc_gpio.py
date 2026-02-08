"""
LPC55xx GPIO and Pin Interrupt Peripherals

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from .nxp_base import NXPPeripheral


class LPCGPIO(NXPPeripheral):
    """
    LPC55xx GPIO peripheral.

    Features:
    - 2 ports (P0, P1) with up to 32 pins each
    - Byte, halfword, and word access
    - Set, clear, toggle operations
    - Direction control per pin

    Memory Map (per port):
        0x0000-0x001F: B[n] - Byte pin registers
        0x1000-0x103F: W[n] - Word pin registers
        0x2080: DIR - Direction
        0x2084: MASK - Mask
        0x2088: PIN - Port pins
        0x208C: MPIN - Masked port
        0x2090: SET - Set output
        0x2094: CLR - Clear output
        0x2098: NOT - Toggle output
        0x209C: DIRSET - Direction set
        0x20A0: DIRCLR - Direction clear
        0x20A4: DIRNOT - Direction toggle
    """

    # Register offsets (relative to port base)
    B_BASE = 0x0000      # Byte pin registers [0-31]
    W_BASE = 0x1000      # Word pin registers [0-31]
    DIR = 0x2080
    MASK = 0x2084
    PIN = 0x2088
    MPIN = 0x208C
    SET = 0x2090
    CLR = 0x2094
    NOT = 0x2098
    DIRSET = 0x209C
    DIRCLR = 0x20A0
    DIRNOT = 0x20A4

    def __init__(self, port: int, base: int):
        super().__init__(f"GPIO{port}", base, 0x2100)
        self.port = port

        # State
        self.direction = 0      # 0=input, 1=output
        self.output = 0         # Output latch
        self.input = 0          # External input (set by external code)
        self.mask = 0xFFFFFFFF  # Pin mask

    def set_input(self, pin: int, value: bool):
        """Set external input on pin (for simulation)."""
        if value:
            self.input |= (1 << pin)
        else:
            self.input &= ~(1 << pin)

    def get_output(self, pin: int) -> bool:
        """Get output state of pin."""
        return bool(self.output & (1 << pin))

    def _get_pin_state(self) -> int:
        """Get combined pin state (outputs drive inputs where direction=1)."""
        # Where direction=1 (output), use output value
        # Where direction=0 (input), use input value
        return (self.output & self.direction) | (self.input & ~self.direction)

    def _read_reg(self, offset: int, size: int) -> int:
        # Byte pin registers
        if self.B_BASE <= offset < self.B_BASE + 32:
            pin = offset - self.B_BASE
            return 1 if (self._get_pin_state() & (1 << pin)) else 0

        # Word pin registers
        if self.W_BASE <= offset < self.W_BASE + 128:
            pin = (offset - self.W_BASE) // 4
            return 0xFFFFFFFF if (self._get_pin_state() & (1 << pin)) else 0

        if offset == self.DIR:
            return self.direction
        elif offset == self.MASK:
            return self.mask
        elif offset == self.PIN:
            return self._get_pin_state()
        elif offset == self.MPIN:
            return self._get_pin_state() & ~self.mask
        elif offset == self.SET:
            return self.output
        elif offset == self.CLR:
            return 0
        elif offset == self.NOT:
            return 0
        elif offset == self.DIRSET:
            return self.direction
        elif offset == self.DIRCLR:
            return 0
        elif offset == self.DIRNOT:
            return 0

        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        # Byte pin registers
        if self.B_BASE <= offset < self.B_BASE + 32:
            pin = offset - self.B_BASE
            if self.direction & (1 << pin):  # Only if output
                if value & 1:
                    self.output |= (1 << pin)
                else:
                    self.output &= ~(1 << pin)
            return

        # Word pin registers
        if self.W_BASE <= offset < self.W_BASE + 128:
            pin = (offset - self.W_BASE) // 4
            if self.direction & (1 << pin):
                if value:
                    self.output |= (1 << pin)
                else:
                    self.output &= ~(1 << pin)
            return

        if offset == self.DIR:
            self.direction = value & 0xFFFFFFFF
        elif offset == self.MASK:
            self.mask = value & 0xFFFFFFFF
        elif offset == self.PIN:
            # Write to output bits where direction=1
            self.output = (self.output & ~self.direction) | (value & self.direction)
        elif offset == self.MPIN:
            # Masked write
            active_mask = ~self.mask & self.direction
            self.output = (self.output & ~active_mask) | (value & active_mask)
        elif offset == self.SET:
            self.output |= (value & self.direction)
        elif offset == self.CLR:
            self.output &= ~(value & self.direction)
        elif offset == self.NOT:
            self.output ^= (value & self.direction)
        elif offset == self.DIRSET:
            self.direction |= value
        elif offset == self.DIRCLR:
            self.direction &= ~value
        elif offset == self.DIRNOT:
            self.direction ^= value


class LPCPINT(NXPPeripheral):
    """
    LPC55xx Pin Interrupt peripheral.

    Features:
    - 8 pin interrupt channels
    - Edge and level detection
    - Pattern match engine
    - Programmable slice outputs

    Memory Map:
        0x00: ISEL - Interrupt select (edge/level)
        0x04: IENR - Enable rising edge/level
        0x08: SIENR - Set IENR bits
        0x0C: CIENR - Clear IENR bits
        0x10: IENF - Enable falling edge
        0x14: SIENF - Set IENF bits
        0x18: CIENF - Clear IENF bits
        0x1C: RISE - Rising edge detect
        0x20: FALL - Falling edge detect
        0x24: IST - Interrupt status
        0x28: PMCTRL - Pattern match control
        0x2C: PMSRC - Pattern match source
        0x30: PMCFG - Pattern match config
    """

    ISEL = 0x00
    IENR = 0x04
    SIENR = 0x08
    CIENR = 0x0C
    IENF = 0x10
    SIENF = 0x14
    CIENF = 0x18
    RISE = 0x1C
    FALL = 0x20
    IST = 0x24
    PMCTRL = 0x28
    PMSRC = 0x2C
    PMCFG = 0x30

    def __init__(self, base: int = 0x40004000):
        super().__init__("PINT", base, 0x1000)

        # State
        self.isel = 0       # 0=edge, 1=level
        self.ienr = 0       # Rising edge/high level enable
        self.ienf = 0       # Falling edge enable
        self.rise = 0       # Rising edge detected
        self.fall = 0       # Falling edge detected
        self.ist = 0        # Interrupt status
        self.pmctrl = 0
        self.pmsrc = 0
        self.pmcfg = 0

        # Previous pin state for edge detection
        self.prev_state = 0

    def update_pin(self, channel: int, state: bool):
        """Update pin state and detect edges."""
        if channel >= 8:
            return

        mask = 1 << channel
        prev = bool(self.prev_state & mask)

        if state and not prev:
            # Rising edge
            self.rise |= mask
            if self.ienr & mask:
                if self.isel & mask:
                    # Level mode - set while high
                    self.ist |= mask
                else:
                    # Edge mode - set on edge
                    self.ist |= mask
        elif not state and prev:
            # Falling edge
            self.fall |= mask
            if self.ienf & mask:
                self.ist |= mask
            if self.isel & mask:
                # Level mode - clear when low
                self.ist &= ~mask

        if state:
            self.prev_state |= mask
        else:
            self.prev_state &= ~mask

        # Check for interrupt
        if self.ist:
            self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ISEL:
            return self.isel
        elif offset == self.IENR:
            return self.ienr
        elif offset == self.IENF:
            return self.ienf
        elif offset == self.RISE:
            return self.rise
        elif offset == self.FALL:
            return self.fall
        elif offset == self.IST:
            return self.ist
        elif offset == self.PMCTRL:
            return self.pmctrl
        elif offset == self.PMSRC:
            return self.pmsrc
        elif offset == self.PMCFG:
            return self.pmcfg
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ISEL:
            self.isel = value & 0xFF
        elif offset == self.IENR:
            self.ienr = value & 0xFF
        elif offset == self.SIENR:
            self.ienr |= (value & 0xFF)
        elif offset == self.CIENR:
            self.ienr &= ~(value & 0xFF)
        elif offset == self.IENF:
            self.ienf = value & 0xFF
        elif offset == self.SIENF:
            self.ienf |= (value & 0xFF)
        elif offset == self.CIENF:
            self.ienf &= ~(value & 0xFF)
        elif offset == self.RISE:
            # Write 1 to clear
            self.rise &= ~(value & 0xFF)
        elif offset == self.FALL:
            # Write 1 to clear
            self.fall &= ~(value & 0xFF)
        elif offset == self.IST:
            # Write 1 to clear
            self.ist &= ~(value & 0xFF)
        elif offset == self.PMCTRL:
            self.pmctrl = value
        elif offset == self.PMSRC:
            self.pmsrc = value
        elif offset == self.PMCFG:
            self.pmcfg = value
