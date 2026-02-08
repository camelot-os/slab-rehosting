"""
STM32 GPIO and EXTI Peripheral Emulation

Implements two GPIO architectures:
- GPIOv1 (F1xx): CRL/CRH based configuration
- GPIOv2 (F2/F4/L4/H7): MODER/OTYPER/OSPEEDR/PUPDR based

References:
- RM0008 (STM32F1xx Reference Manual)
- RM0090 (STM32F4xx Reference Manual)
- RM0351 (STM32L4xx Reference Manual)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Dict, Optional, Callable, List
from .stm32_base import STM32Peripheral, STATUS_OK


# =============================================================================
# GPIOv1 - STM32F1xx Style (CRL/CRH)
# =============================================================================

class STM32GPIOv1(STM32Peripheral):
    """
    STM32F1xx GPIO peripheral.

    Uses CRL/CRH for pin configuration (4 bits per pin):
    - MODE[1:0]: Input/Output mode
    - CNF[1:0]: Configuration

    Register Map:
        0x00: CRL   - Configuration low (pins 0-7)
        0x04: CRH   - Configuration high (pins 8-15)
        0x08: IDR   - Input data register
        0x0C: ODR   - Output data register
        0x10: BSRR  - Bit set/reset register
        0x14: BRR   - Bit reset register
        0x18: LCKR  - Configuration lock register
    """

    # Register offsets
    CRL = 0x00
    CRH = 0x04
    IDR = 0x08
    ODR = 0x0C
    BSRR = 0x10
    BRR = 0x14
    LCKR = 0x18

    # MODE bits (per pin)
    MODE_INPUT = 0b00
    MODE_OUTPUT_10MHZ = 0b01
    MODE_OUTPUT_2MHZ = 0b10
    MODE_OUTPUT_50MHZ = 0b11

    # CNF bits for input mode
    CNF_INPUT_ANALOG = 0b00
    CNF_INPUT_FLOATING = 0b01
    CNF_INPUT_PUPD = 0b10

    # CNF bits for output mode
    CNF_OUTPUT_PP = 0b00
    CNF_OUTPUT_OD = 0b01
    CNF_AF_PP = 0b10
    CNF_AF_OD = 0b11

    # Base addresses for GPIOA-G
    GPIO_BASES = {
        'A': 0x40010800,
        'B': 0x40010C00,
        'C': 0x40011000,
        'D': 0x40011400,
        'E': 0x40011800,
        'F': 0x40011C00,
        'G': 0x40012000,
    }

    def __init__(self, port: str = 'A', base: int = None):
        """
        Initialize GPIO port.

        Args:
            port: Port letter (A-G)
            base: Base address (auto-calculated if None)
        """
        if base is None:
            base = self.GPIO_BASES.get(port.upper(), 0x40010800)

        super().__init__(f"GPIO{port.upper()}", base, 0x400)
        self.port = port.upper()

        # Pin state
        self.odr = 0x0000      # Output data register
        self.idr = 0x0000      # Input data register (external input)
        self.crl = 0x44444444  # Default: floating input
        self.crh = 0x44444444
        self.lckr = 0x00000000
        self.locked = False

        # Callbacks for pin changes
        self.on_pin_change: Optional[Callable[[int, int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CRL:
            return self.crl
        elif offset == self.CRH:
            return self.crh
        elif offset == self.IDR:
            # Return merged input: external OR output for output pins
            return self._get_idr()
        elif offset == self.ODR:
            return self.odr
        elif offset == self.LCKR:
            return self.lckr | (0x10000 if self.locked else 0)
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CRL:
            if not self.locked:
                self.crl = value
                self.log.debug(f"CRL = 0x{value:08X}")
        elif offset == self.CRH:
            if not self.locked:
                self.crh = value
                self.log.debug(f"CRH = 0x{value:08X}")
        elif offset == self.ODR:
            old_odr = self.odr
            self.odr = value & 0xFFFF
            self._notify_change(old_odr)
        elif offset == self.BSRR:
            old_odr = self.odr
            # High 16 bits: reset, Low 16 bits: set
            self.odr &= ~((value >> 16) & 0xFFFF)
            self.odr |= (value & 0xFFFF)
            self._notify_change(old_odr)
        elif offset == self.BRR:
            old_odr = self.odr
            self.odr &= ~(value & 0xFFFF)
            self._notify_change(old_odr)
        elif offset == self.LCKR:
            self._handle_lock(value)

    def _get_idr(self) -> int:
        """Get input data register value."""
        result = 0
        for pin in range(16):
            if self._is_output(pin):
                result |= ((self.odr >> pin) & 1) << pin
            else:
                result |= ((self.idr >> pin) & 1) << pin
        return result

    def _is_output(self, pin: int) -> bool:
        """Check if pin is configured as output."""
        if pin < 8:
            mode = (self.crl >> (pin * 4)) & 0x3
        else:
            mode = (self.crh >> ((pin - 8) * 4)) & 0x3
        return mode != self.MODE_INPUT

    def _handle_lock(self, value: int):
        """Handle LCKR write sequence."""
        # Lock sequence: Write LCKK=1, Write LCKK=0, Write LCKK=1, Read LCKK
        if value & 0x10000:
            self.lckr = value & 0xFFFF
        else:
            if self.lckr == (value & 0xFFFF):
                self.locked = True

    def _notify_change(self, old_odr: int):
        """Notify pin change callback."""
        if self.on_pin_change and old_odr != self.odr:
            changed = old_odr ^ self.odr
            for pin in range(16):
                if changed & (1 << pin):
                    new_val = (self.odr >> pin) & 1
                    self.on_pin_change(pin, new_val, self._is_output(pin))

    def set_input_pin(self, pin: int, value: int):
        """Set external input pin state."""
        if value:
            self.idr |= (1 << pin)
        else:
            self.idr &= ~(1 << pin)

    def get_output_pin(self, pin: int) -> int:
        """Get output pin state."""
        return (self.odr >> pin) & 1

    def _reset_registers(self):
        """Reset to default state."""
        self.odr = 0x0000
        self.crl = 0x44444444
        self.crh = 0x44444444
        self.lckr = 0x00000000
        self.locked = False


# =============================================================================
# GPIOv2 - STM32F2/F4/L4/H7 Style (MODER/OTYPER/OSPEEDR/PUPDR)
# =============================================================================

class STM32GPIOv2(STM32Peripheral):
    """
    STM32F2/F4/L4/H7 GPIO peripheral.

    Uses MODER/OTYPER/OSPEEDR/PUPDR for pin configuration.

    Register Map:
        0x00: MODER   - Mode register (2 bits per pin)
        0x04: OTYPER  - Output type (1 bit per pin)
        0x08: OSPEEDR - Output speed (2 bits per pin)
        0x0C: PUPDR   - Pull-up/pull-down (2 bits per pin)
        0x10: IDR     - Input data register
        0x14: ODR     - Output data register
        0x18: BSRR    - Bit set/reset register
        0x1C: LCKR    - Configuration lock
        0x20: AFRL    - Alternate function low (pins 0-7)
        0x24: AFRH    - Alternate function high (pins 8-15)
        0x28: BRR     - Bit reset register (some devices)
    """

    # Register offsets
    MODER = 0x00
    OTYPER = 0x04
    OSPEEDR = 0x08
    PUPDR = 0x0C
    IDR = 0x10
    ODR = 0x14
    BSRR = 0x18
    LCKR = 0x1C
    AFRL = 0x20
    AFRH = 0x24
    BRR = 0x28

    # MODER values (2 bits per pin)
    MODE_INPUT = 0b00
    MODE_OUTPUT = 0b01
    MODE_AF = 0b10
    MODE_ANALOG = 0b11

    # OTYPER values
    OTYPE_PUSHPULL = 0
    OTYPE_OPENDRAIN = 1

    # OSPEEDR values
    OSPEED_LOW = 0b00
    OSPEED_MEDIUM = 0b01
    OSPEED_HIGH = 0b10
    OSPEED_VERYHIGH = 0b11

    # PUPDR values
    PUPD_NONE = 0b00
    PUPD_PULLUP = 0b01
    PUPD_PULLDOWN = 0b10

    # Base addresses for F4xx GPIOA-K
    GPIO_BASES_F4 = {
        'A': 0x40020000,
        'B': 0x40020400,
        'C': 0x40020800,
        'D': 0x40020C00,
        'E': 0x40021000,
        'F': 0x40021400,
        'G': 0x40021800,
        'H': 0x40021C00,
        'I': 0x40022000,
        'J': 0x40022400,
        'K': 0x40022800,
    }

    # Base addresses for H7xx GPIOA-K
    GPIO_BASES_H7 = {
        'A': 0x58020000,
        'B': 0x58020400,
        'C': 0x58020800,
        'D': 0x58020C00,
        'E': 0x58021000,
        'F': 0x58021400,
        'G': 0x58021800,
        'H': 0x58021C00,
        'I': 0x58022000,
        'J': 0x58022400,
        'K': 0x58022800,
    }

    def __init__(self, port: str = 'A', base: int = None, family: str = "F4"):
        """
        Initialize GPIO port.

        Args:
            port: Port letter (A-K)
            base: Base address (auto-calculated if None)
            family: Device family ("F4", "L4", "H7")
        """
        if base is None:
            if family == "H7":
                base = self.GPIO_BASES_H7.get(port.upper(), 0x58020000)
            else:
                base = self.GPIO_BASES_F4.get(port.upper(), 0x40020000)

        super().__init__(f"GPIO{port.upper()}", base, 0x400)
        self.port = port.upper()
        self.family = family

        # Registers
        self.moder = 0xFFFFFFFF if port == 'A' else 0x00000000  # GPIOA has analog by default
        self.otyper = 0x00000000
        self.ospeedr = 0x00000000
        self.pupdr = 0x00000000
        self.odr = 0x00000000
        self.idr = 0x00000000
        self.afrl = 0x00000000
        self.afrh = 0x00000000
        self.lckr = 0x00000000
        self.locked = False

        # Default values vary by port
        self._set_port_defaults()

        # Callbacks
        self.on_pin_change: Optional[Callable[[int, int, int], None]] = None

    def _set_port_defaults(self):
        """Set port-specific default values per family."""
        if self.family == "H5":
            self._set_port_defaults_h5()
        else:
            self._set_port_defaults_f4()

    def _set_port_defaults_f4(self):
        """F4/L4 GPIO reset values (RM0090/RM0351)."""
        if self.port == 'A':
            # PA13/14/15 are debug pins (JTAG/SWD)
            self.moder = 0xA8000000  # PA13-15 AF, others input
            self.pupdr = 0x64000000  # PA13 pull-up, PA14/15 pull-down
            self.ospeedr = 0x0C000000  # PA13 very high speed
        elif self.port == 'B':
            # PB3/4 are debug pins
            self.moder = 0x00000280  # PB3/4 AF
            self.pupdr = 0x00000100  # PB4 pull-up

    def _set_port_defaults_h5(self):
        """H5 GPIO reset values (RM0481).
        H5 defaults unassigned pins to analog mode (0b11)."""
        if self.port == 'A':
            # PA13/14/15 = AF (SWD), rest analog
            self.moder = 0xABFFFFFF
            self.pupdr = 0x64000000  # PA13 pull-up, PA14/15 pull-down
            self.ospeedr = 0x0C000000  # PA13 very high speed
        elif self.port == 'B':
            # PB3 = AF (SWO), rest analog
            self.moder = 0xFFFFFEBF  # PB3 AF (bits 7:6=10), rest analog
            self.pupdr = 0x00000000
        else:
            # All other ports: all pins analog
            self.moder = 0xFFFFFFFF

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.MODER:
            return self.moder
        elif offset == self.OTYPER:
            return self.otyper
        elif offset == self.OSPEEDR:
            return self.ospeedr
        elif offset == self.PUPDR:
            return self.pupdr
        elif offset == self.IDR:
            return self._get_idr()
        elif offset == self.ODR:
            return self.odr
        elif offset == self.AFRL:
            return self.afrl
        elif offset == self.AFRH:
            return self.afrh
        elif offset == self.LCKR:
            return self.lckr | (0x10000 if self.locked else 0)
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.MODER:
            if not self.locked:
                self.moder = value
                self.log.debug(f"MODER = 0x{value:08X}")
        elif offset == self.OTYPER:
            if not self.locked:
                self.otyper = value & 0xFFFF
        elif offset == self.OSPEEDR:
            if not self.locked:
                self.ospeedr = value
        elif offset == self.PUPDR:
            if not self.locked:
                self.pupdr = value
        elif offset == self.ODR:
            old_odr = self.odr
            self.odr = value & 0xFFFF
            self._notify_change(old_odr)
        elif offset == self.BSRR:
            old_odr = self.odr
            # High 16 bits: reset, Low 16 bits: set
            self.odr &= ~((value >> 16) & 0xFFFF)
            self.odr |= (value & 0xFFFF)
            self._notify_change(old_odr)
        elif offset == self.BRR:
            old_odr = self.odr
            self.odr &= ~(value & 0xFFFF)
            self._notify_change(old_odr)
        elif offset == self.AFRL:
            if not self.locked:
                self.afrl = value
        elif offset == self.AFRH:
            if not self.locked:
                self.afrh = value
        elif offset == self.LCKR:
            self._handle_lock(value)

    def _get_idr(self) -> int:
        """Get input data register value."""
        result = 0
        for pin in range(16):
            mode = (self.moder >> (pin * 2)) & 0x3
            if mode == self.MODE_OUTPUT:
                result |= ((self.odr >> pin) & 1) << pin
            else:
                result |= ((self.idr >> pin) & 1) << pin
        return result

    def get_pin_mode(self, pin: int) -> int:
        """Get pin mode (0=input, 1=output, 2=AF, 3=analog)."""
        return (self.moder >> (pin * 2)) & 0x3

    def get_pin_af(self, pin: int) -> int:
        """Get alternate function number for pin."""
        if pin < 8:
            return (self.afrl >> (pin * 4)) & 0xF
        else:
            return (self.afrh >> ((pin - 8) * 4)) & 0xF

    def _handle_lock(self, value: int):
        """Handle LCKR write sequence."""
        if value & 0x10000:
            self.lckr = value & 0xFFFF
        else:
            if self.lckr == (value & 0xFFFF):
                self.locked = True

    def _notify_change(self, old_odr: int):
        """Notify pin change callback."""
        if self.on_pin_change and old_odr != self.odr:
            changed = old_odr ^ self.odr
            for pin in range(16):
                if changed & (1 << pin):
                    new_val = (self.odr >> pin) & 1
                    mode = self.get_pin_mode(pin)
                    self.on_pin_change(pin, new_val, mode == self.MODE_OUTPUT)

    def set_input_pin(self, pin: int, value: int):
        """Set external input pin state."""
        if value:
            self.idr |= (1 << pin)
        else:
            self.idr &= ~(1 << pin)

    def get_output_pin(self, pin: int) -> int:
        """Get output pin state."""
        return (self.odr >> pin) & 1

    # Convenience methods for easier use
    def set_mode(self, pin: int, mode: int):
        """Set pin mode (0=input, 1=output, 2=AF, 3=analog)."""
        mask = ~(0x3 << (pin * 2))
        self.moder = (self.moder & mask) | ((mode & 0x3) << (pin * 2))

    def set_output(self, pin: int, value: bool):
        """Set output pin high or low."""
        old_odr = self.odr
        if value:
            self.odr |= (1 << pin)
        else:
            self.odr &= ~(1 << pin)
        self._notify_change(old_odr)

    def get_output(self, pin: int) -> bool:
        """Get output pin state as boolean."""
        return bool((self.odr >> pin) & 1)

    def _reset_registers(self):
        """Reset to default state."""
        self.odr = 0x00000000
        self.otyper = 0x00000000
        self.ospeedr = 0x00000000
        self.lckr = 0x00000000
        self.locked = False
        self._set_port_defaults()


# =============================================================================
# EXTI - External Interrupt Controller
# =============================================================================

class STM32EXTI(STM32Peripheral):
    """
    STM32 External Interrupt/Event Controller.

    Handles GPIO interrupts and other external events.

    Register Map (F4/L4):
        0x00: IMR    - Interrupt mask register
        0x04: EMR    - Event mask register
        0x08: RTSR   - Rising trigger selection
        0x0C: FTSR   - Falling trigger selection
        0x10: SWIER  - Software interrupt event register
        0x14: PR     - Pending register
    """

    # Register offsets (F2/F4/L4)
    IMR = 0x00
    EMR = 0x04
    RTSR = 0x08
    FTSR = 0x0C
    SWIER = 0x10
    PR = 0x14

    # H7 has different register layout (IMR1/IMR2/IMR3, etc.)
    # For H7:
    IMR1 = 0x80
    EMR1 = 0x84
    RTSR1 = 0x00
    FTSR1 = 0x04
    SWIER1 = 0x08
    PR1 = 0x88

    # EXTI lines 0-15 are connected to GPIO
    # Lines 16-22 are internal (PVD, RTC, USB, etc.)

    def __init__(self, base: int = 0x40013C00, family: str = "F4"):
        """
        Initialize EXTI controller.

        Args:
            base: Base address
            family: Device family ("F1", "F4", "L4", "H7")
        """
        super().__init__("EXTI", base, 0x400)
        self.family = family

        # Registers
        self.imr = 0x00000000
        self.emr = 0x00000000
        self.rtsr = 0x00000000
        self.ftsr = 0x00000000
        self.swier = 0x00000000
        self.pr = 0x00000000

        # GPIO connection
        self.gpio_ports: Dict[str, STM32GPIOv1 | STM32GPIOv2] = {}

        # Previous GPIO state for edge detection
        self._prev_gpio = [0] * 16

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.IMR:
            return self.imr
        elif offset == self.EMR:
            return self.emr
        elif offset == self.RTSR:
            return self.rtsr
        elif offset == self.FTSR:
            return self.ftsr
        elif offset == self.SWIER:
            return self.swier
        elif offset == self.PR:
            return self.pr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.IMR:
            self.imr = value
        elif offset == self.EMR:
            self.emr = value
        elif offset == self.RTSR:
            self.rtsr = value
        elif offset == self.FTSR:
            self.ftsr = value
        elif offset == self.SWIER:
            # Software trigger - sets pending bits
            for line in range(23):
                if value & (1 << line):
                    if self.imr & (1 << line):
                        self.pr |= (1 << line)
                        self._trigger_interrupt(line)
            self.swier = 0  # Auto-cleared
        elif offset == self.PR:
            # Write 1 to clear pending bits
            self.pr &= ~value

    def check_gpio_edge(self, line: int, new_value: int):
        """
        Check for edge on GPIO line and trigger interrupt if enabled.

        Args:
            line: EXTI line (0-15)
            new_value: New GPIO value (0 or 1)
        """
        if line >= 16:
            return

        old_value = self._prev_gpio[line]
        self._prev_gpio[line] = new_value

        triggered = False

        # Check rising edge
        if (self.rtsr & (1 << line)) and old_value == 0 and new_value == 1:
            triggered = True

        # Check falling edge
        if (self.ftsr & (1 << line)) and old_value == 1 and new_value == 0:
            triggered = True

        if triggered and (self.imr & (1 << line)):
            self.pr |= (1 << line)
            self._trigger_interrupt(line)

    def _trigger_interrupt(self, line: int):
        """Trigger EXTI interrupt."""
        # EXTI0-4 have individual IRQs
        # EXTI5-9 share EXTI9_5_IRQn
        # EXTI10-15 share EXTI15_10_IRQn
        if line <= 4:
            irq = 6 + line  # EXTI0_IRQn = 6
        elif line <= 9:
            irq = 23  # EXTI9_5_IRQn
        else:
            irq = 40  # EXTI15_10_IRQn

        self.irq = irq
        self.trigger_irq(1)

    def _reset_registers(self):
        """Reset to default state."""
        self.imr = 0x00000000
        self.emr = 0x00000000
        self.rtsr = 0x00000000
        self.ftsr = 0x00000000
        self.swier = 0x00000000
        self.pr = 0x00000000
        self._prev_gpio = [0] * 16


# =============================================================================
# ALIASES
# =============================================================================

# Backward-compatible aliases
STM32F1GPIO = STM32GPIOv1
STM32F4GPIO = STM32GPIOv2
