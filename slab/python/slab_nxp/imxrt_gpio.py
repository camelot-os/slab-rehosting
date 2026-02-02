"""
i.MX RT GPIO Peripheral

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from .nxp_base import NXPPeripheral


class IMXRTGPIO(NXPPeripheral):
    """
    i.MX RT GPIO peripheral.

    Features:
    - 32 pins per port
    - Input/output control
    - Set/clear/toggle operations
    - Edge and level interrupts
    - IOMUX for pin multiplexing

    Memory Map:
        0x00: DR - Data register
        0x04: GDIR - Direction register
        0x08: PSR - Pad status register
        0x0C: ICR1 - Interrupt config 1 (pins 0-15)
        0x10: ICR2 - Interrupt config 2 (pins 16-31)
        0x14: IMR - Interrupt mask register
        0x18: ISR - Interrupt status register
        0x1C: EDGE_SEL - Edge select register
        0x84: DR_SET - Data register SET
        0x88: DR_CLEAR - Data register CLEAR
        0x8C: DR_TOGGLE - Data register TOGGLE
    """

    # Register offsets
    DR = 0x00
    GDIR = 0x04
    PSR = 0x08
    ICR1 = 0x0C
    ICR2 = 0x10
    IMR = 0x14
    ISR = 0x18
    EDGE_SEL = 0x1C
    DR_SET = 0x84
    DR_CLEAR = 0x88
    DR_TOGGLE = 0x8C

    # ICR values
    ICR_LOW_LEVEL = 0
    ICR_HIGH_LEVEL = 1
    ICR_RISING_EDGE = 2
    ICR_FALLING_EDGE = 3

    def __init__(self, port: int, base: int):
        super().__init__(f"GPIO{port}", base, 0x1000)
        self.port = port

        # Registers
        self.dr = 0
        self.gdir = 0
        self.icr1 = 0
        self.icr2 = 0
        self.imr = 0
        self.isr = 0
        self.edge_sel = 0

        # External input state
        self.external_input = 0

    def set_input(self, pin: int, value: bool):
        """Set external input on a pin."""
        old_psr = self._get_psr()
        if value:
            self.external_input |= (1 << pin)
        else:
            self.external_input &= ~(1 << pin)
        new_psr = self._get_psr()

        # Check for interrupts
        self._check_interrupt(pin, old_psr, new_psr)

    def get_output(self, pin: int) -> bool:
        """Get output state of pin."""
        return bool(self.dr & (1 << pin))

    def _get_psr(self) -> int:
        """Get pad status (combined outputs and inputs)."""
        # Outputs override inputs
        return (self.dr & self.gdir) | (self.external_input & ~self.gdir)

    def _check_interrupt(self, pin: int, old_val: int, new_val: int):
        """Check if pin transition should trigger interrupt."""
        if not (self.imr & (1 << pin)):
            return

        old_bit = bool(old_val & (1 << pin))
        new_bit = bool(new_val & (1 << pin))

        if old_bit == new_bit:
            return

        # Get ICR config for this pin
        if pin < 16:
            icr = (self.icr1 >> (pin * 2)) & 0x03
        else:
            icr = (self.icr2 >> ((pin - 16) * 2)) & 0x03

        # Check edge_sel override (any edge)
        if self.edge_sel & (1 << pin):
            if old_bit != new_bit:
                self.isr |= (1 << pin)
                self.trigger_irq(1)
            return

        trigger = False
        if icr == self.ICR_LOW_LEVEL:
            trigger = not new_bit
        elif icr == self.ICR_HIGH_LEVEL:
            trigger = new_bit
        elif icr == self.ICR_RISING_EDGE:
            trigger = not old_bit and new_bit
        elif icr == self.ICR_FALLING_EDGE:
            trigger = old_bit and not new_bit

        if trigger:
            self.isr |= (1 << pin)
            self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.DR:
            return self.dr
        elif offset == self.GDIR:
            return self.gdir
        elif offset == self.PSR:
            return self._get_psr()
        elif offset == self.ICR1:
            return self.icr1
        elif offset == self.ICR2:
            return self.icr2
        elif offset == self.IMR:
            return self.imr
        elif offset == self.ISR:
            return self.isr
        elif offset == self.EDGE_SEL:
            return self.edge_sel
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.DR:
            self.dr = value
        elif offset == self.GDIR:
            self.gdir = value
        elif offset == self.ICR1:
            self.icr1 = value
        elif offset == self.ICR2:
            self.icr2 = value
        elif offset == self.IMR:
            self.imr = value
        elif offset == self.ISR:
            # W1C
            self.isr &= ~value
        elif offset == self.EDGE_SEL:
            self.edge_sel = value
        elif offset == self.DR_SET:
            self.dr |= value
        elif offset == self.DR_CLEAR:
            self.dr &= ~value
        elif offset == self.DR_TOGGLE:
            self.dr ^= value
