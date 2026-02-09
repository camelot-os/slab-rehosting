"""
RP2040 Peripheral Emulation for SLAB

Implements the key RP2040 peripherals needed for LED blink and FreeRTOS:
- GPIO (IO_BANK0) - Pin control
- SIO - Single-cycle I/O with spinlocks and fast GPIO
- Clocks - Basic clock configuration
- Timer - 64-bit microsecond timer with alarms

References:
- RP2040 Datasheet (https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf)
- Pico SDK source code

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from enum import IntEnum

# Status codes
STATUS_OK = 0
STATUS_ERROR = 1
STATUS_SECURITY_FAULT = 2

# Import additional peripherals (lazy imports to avoid circular dependencies)
def _import_uart_spi_i2c():
    from .rp2040_uart_spi_i2c import RP2040UART, RP2040SPI, RP2040I2C
    return RP2040UART, RP2040SPI, RP2040I2C

def _import_adc_pwm_dma():
    from .rp2040_adc_pwm_dma import RP2040ADC, RP2040PWM, RP2040DMA
    return RP2040ADC, RP2040PWM, RP2040DMA

def _import_misc():
    from .rp2040_misc import (
        RP2040RTC, RP2040ROSC, RP2040SYSINFO, RP2040SYSCFG,
        RP2040VREG, RP2040TBMAN, RP2040BUSCTRL, RP2040XIP,
        RP2040SSI, RP2040IOQSPI, RP2040PADSQSPI, RP2040USB,
        # Bootrom-compatible peripherals (detailed implementations)
        RP2040RESETS, RP2040CLOCKS, RP2040WATCHDOG
    )
    return (RP2040RTC, RP2040ROSC, RP2040SYSINFO, RP2040SYSCFG,
            RP2040VREG, RP2040TBMAN, RP2040BUSCTRL, RP2040XIP,
            RP2040SSI, RP2040IOQSPI, RP2040PADSQSPI, RP2040USB,
            RP2040RESETS, RP2040CLOCKS, RP2040WATCHDOG)


class RP2040Peripheral(ABC):
    """Base class for RP2040 peripherals.

    Supports RP2040 bus-level atomic register aliases (Section 2.1.2):
    - base + 0x0000: Normal read/write
    - base + 0x1000: XOR on write (read returns normal value)
    - base + 0x2000: SET on write (OR bits)
    - base + 0x3000: CLR on write (AND NOT bits)

    Each peripheral occupies a 16KB window (4 x 4KB aliases).
    """

    def __init__(self, name: str, base: int, size: int, irq: int = -1):
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq
        self.regs: Dict[int, int] = {}
        self.log = logging.getLogger(f'RP2040.{name}')
        self.irq_callback: Optional[Callable[[int, int], None]] = None

    def contains(self, addr: int) -> bool:
        # Check all 4 atomic alias ranges
        for alias_offset in (0x0000, 0x1000, 0x2000, 0x3000):
            alias_base = self.base + alias_offset
            if alias_base <= addr < alias_base + self.size:
                return True
        return False

    def _resolve_alias(self, addr: int) -> Tuple[int, int]:
        """Resolve atomic alias, returning (register_offset, alias_type).

        alias_type: 0=normal, 1=XOR, 2=SET, 3=CLR
        """
        raw_offset = addr - self.base
        if raw_offset >= 0x1000:
            alias = raw_offset // 0x1000
            offset = raw_offset % 0x1000
        else:
            alias = 0
            offset = raw_offset
        return (offset, alias)

    def read(self, addr: int, size: int, secure: bool = True) -> Tuple[int, int]:
        offset, _alias = self._resolve_alias(addr)
        value = self._read_reg(offset, size)
        return (value, STATUS_OK)

    def write(self, addr: int, size: int, value: int, secure: bool = True) -> int:
        offset, alias = self._resolve_alias(addr)
        if alias == 0:
            self._write_reg(offset, size, value)
        elif alias == 1:  # XOR
            self._write_reg(offset, size, self._read_reg(offset, size) ^ value)
        elif alias == 2:  # SET
            self._write_reg(offset, size, self._read_reg(offset, size) | value)
        elif alias == 3:  # CLR
            self._write_reg(offset, size, self._read_reg(offset, size) & ~value)
        return STATUS_OK

    def _read_reg(self, offset: int, size: int) -> int:
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        self.regs[offset] = value

    def trigger_irq(self, level: int = 1):
        if self.irq >= 0 and self.irq_callback:
            self.irq_callback(self.irq, level)

    def reset(self):
        self.regs.clear()


# =============================================================================
# GPIO (IO_BANK0) - 0x40014000
# =============================================================================

class RP2040GPIO(RP2040Peripheral):
    """
    RP2040 GPIO bank (IO_BANK0).

    Memory map (per pin, 8 bytes each, GPIO0-29):
      0x000 + pin*8: GPIOx_STATUS (RO)
      0x004 + pin*8: GPIOx_CTRL

    Plus interrupt registers at 0x0F0-0x17C.

    This implementation focuses on basic GPIO control for LED blink.
    """

    # Register offsets (base per GPIO)
    GPIO_STATUS_OFFSET = 0x000  # +pin*8
    GPIO_CTRL_OFFSET = 0x004    # +pin*8

    # INTR registers (interrupt raw status)
    INTR0 = 0x0F0  # GPIO 0-7
    INTR1 = 0x0F4  # GPIO 8-15
    INTR2 = 0x0F8  # GPIO 16-23
    INTR3 = 0x0FC  # GPIO 24-29

    # PROC0_INTE (interrupt enable for processor 0)
    PROC0_INTE0 = 0x100
    PROC0_INTE1 = 0x104
    PROC0_INTE2 = 0x108
    PROC0_INTE3 = 0x10C

    # PROC0_INTF (interrupt force)
    PROC0_INTF0 = 0x110

    # PROC0_INTS (interrupt status after masking)
    PROC0_INTS0 = 0x120

    # CTRL register fields
    CTRL_FUNCSEL_MASK = 0x1F
    CTRL_OUTOVER_MASK = 0x300
    CTRL_OEOVER_MASK = 0x3000
    CTRL_INOVER_MASK = 0x30000
    CTRL_IRQOVER_MASK = 0x300000

    # Function select values
    FUNCSEL_SIO = 5  # SIO (software control)
    FUNCSEL_NULL = 31  # Null function

    def __init__(self, base: int = 0x40014000, size: int = 0x1000):
        super().__init__("IO_BANK0", base, size, irq=13)  # IO_IRQ_BANK0

        # Pin configuration (30 GPIOs)
        self.num_pins = 30
        self.pin_ctrl = [self.FUNCSEL_NULL] * self.num_pins  # Default: null function

        # Link to SIO for actual pin state
        self.sio: Optional['RP2040SIO'] = None

        # Pin state change callback (for virtual LED, etc.)
        self.on_pin_change: Optional[Callable[[int, int], None]] = None

    def _gpio_offset_to_pin(self, offset: int) -> Optional[int]:
        """Convert register offset to GPIO pin number."""
        if offset < 0x0F0:  # Before interrupt registers
            pin = offset // 8
            if pin < self.num_pins:
                return pin
        return None

    def _read_reg(self, offset: int, size: int) -> int:
        # Per-GPIO registers
        pin = self._gpio_offset_to_pin(offset)
        if pin is not None:
            reg_type = offset % 8
            if reg_type == 0:  # STATUS
                return self._get_gpio_status(pin)
            elif reg_type == 4:  # CTRL
                return self.pin_ctrl[pin]

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        # Per-GPIO registers
        pin = self._gpio_offset_to_pin(offset)
        if pin is not None:
            reg_type = offset % 8
            if reg_type == 4:  # CTRL
                self.pin_ctrl[pin] = value
                self.log.debug(f"GPIO{pin} CTRL = 0x{value:08X} (funcsel={value & 0x1F})")
                return

        self.regs[offset] = value

    def _get_gpio_status(self, pin: int) -> int:
        """Get GPIO status register (read-only)."""
        status = 0
        if self.sio:
            # Get output enable and output value from SIO
            oe = (self.sio.gpio_oe >> pin) & 1
            out = (self.sio.gpio_out >> pin) & 1
            pin_in = (self.sio.gpio_in >> pin) & 1

            status |= (out << 8)      # OUTFROMPERI
            status |= (out << 9)      # OUTTOPAD
            status |= (oe << 12)      # OEFROMPERI
            status |= (oe << 13)      # OETOPAD
            status |= (pin_in << 17)  # INFROMPAD

        return status

    def get_funcsel(self, pin: int) -> int:
        """Get function select for a pin."""
        if 0 <= pin < self.num_pins:
            return self.pin_ctrl[pin] & self.CTRL_FUNCSEL_MASK
        return self.FUNCSEL_NULL


# =============================================================================
# PADS_BANK0 - 0x4001C000
# =============================================================================

class RP2040Pads(RP2040Peripheral):
    """
    RP2040 Pad control (PADS_BANK0).

    Controls electrical characteristics of GPIO pads:
    - Output drive strength
    - Slew rate
    - Pull-up/pull-down
    - Schmitt trigger
    - Input enable
    """

    # Voltage select
    VOLTAGE_SELECT = 0x00

    # GPIO pad control (one register per GPIO, 0x04 + pin*4)
    GPIO_BASE = 0x04

    # Default pad configuration
    # Bits: [7] OD, [6] IE, [5:4] DRIVE, [3] PUE, [2] PDE, [1] SCHMITT, [0] SLEWFAST
    DEFAULT_PAD = 0x56  # IE=1, DRIVE=1, SCHMITT=1

    def __init__(self, base: int = 0x4001C000, size: int = 0x100):
        super().__init__("PADS_BANK0", base, size)

        # Initialize all pads to default
        for pin in range(30):
            self.regs[self.GPIO_BASE + pin * 4] = self.DEFAULT_PAD

    def _read_reg(self, offset: int, size: int) -> int:
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        self.regs[offset] = value


# =============================================================================
# SIO (Single-cycle I/O) - 0xD0000000
# =============================================================================

class RP2040SIO(RP2040Peripheral):
    """
    RP2040 Single-cycle I/O block.

    Provides:
    - Fast GPIO access (single cycle read/write)
    - Hardware spinlocks (32 locks for multicore sync)
    - Inter-core FIFOs
    - Hardware divider

    Memory map:
      0x000: CPUID
      0x004: GPIO_IN
      0x010: GPIO_OUT
      0x014: GPIO_OUT_SET
      0x018: GPIO_OUT_CLR
      0x01C: GPIO_OUT_XOR
      0x020: GPIO_OE
      0x024: GPIO_OE_SET
      0x028: GPIO_OE_CLR
      0x02C: GPIO_OE_XOR
      0x080: FIFO_ST (FIFO status)
      0x084: FIFO_WR
      0x088: FIFO_RD
      0x100: SPINLOCK0..31 (32 spinlocks)
    """

    # Register offsets
    CPUID = 0x000
    GPIO_IN = 0x004
    GPIO_HI_IN = 0x008

    GPIO_OUT = 0x010
    GPIO_OUT_SET = 0x014
    GPIO_OUT_CLR = 0x018
    GPIO_OUT_XOR = 0x01C

    GPIO_OE = 0x020
    GPIO_OE_SET = 0x024
    GPIO_OE_CLR = 0x028
    GPIO_OE_XOR = 0x02C

    GPIO_HI_OUT = 0x030
    GPIO_HI_OUT_SET = 0x034
    GPIO_HI_OUT_CLR = 0x038
    GPIO_HI_OUT_XOR = 0x03C

    GPIO_HI_OE = 0x040
    GPIO_HI_OE_SET = 0x044
    GPIO_HI_OE_CLR = 0x048
    GPIO_HI_OE_XOR = 0x04C

    # FIFO registers
    FIFO_ST = 0x050
    FIFO_WR = 0x054
    FIFO_RD = 0x058

    # Divider registers
    DIV_UDIVIDEND = 0x060
    DIV_UDIVISOR = 0x064
    DIV_SDIVIDEND = 0x068
    DIV_SDIVISOR = 0x06C
    DIV_QUOTIENT = 0x070
    DIV_REMAINDER = 0x074
    DIV_CSR = 0x078

    # Spinlocks (32 x 4 bytes = 128 bytes at 0x100)
    SPINLOCK_BASE = 0x100
    NUM_SPINLOCKS = 32

    def __init__(self, base: int = 0xD0000000, size: int = 0x200, cpuid: int = 0):
        super().__init__("SIO", base, size)

        self.cpuid = cpuid  # 0 or 1 for dual-core

        # GPIO state (directly accessible, single-cycle)
        self.gpio_in = 0       # Input state (external)
        self.gpio_out = 0      # Output state
        self.gpio_oe = 0       # Output enable

        # Spinlocks (shared between cores)
        self.spinlocks = [0] * self.NUM_SPINLOCKS

        # Inter-core FIFOs (8-word depth each)
        self.fifo_to_other: List[int] = []  # TX FIFO
        self.fifo_from_other: List[int] = []  # RX FIFO
        self.other_core: Optional['RP2040SIO'] = None

        # Divider state
        self.div_dividend = 0
        self.div_divisor = 1
        self.div_quotient = 0
        self.div_remainder = 0
        self.div_dirty = False

        # Pin change callback
        self.on_gpio_change: Optional[Callable[[int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CPUID:
            return self.cpuid

        elif offset == self.GPIO_IN:
            # Return combined input (external OR output for output pins)
            return self.gpio_in | (self.gpio_out & self.gpio_oe)

        elif offset == self.GPIO_OUT:
            return self.gpio_out

        elif offset == self.GPIO_OE:
            return self.gpio_oe

        elif offset == self.FIFO_ST:
            # [3] ROE (RX overflow error)
            # [2] WOF (TX overflow error)
            # [1] RDY (TX FIFO not full)
            # [0] VLD (RX FIFO not empty)
            status = 0
            if self.fifo_from_other:
                status |= 1  # VLD
            if len(self.fifo_to_other) < 8:
                status |= 2  # RDY
            return status

        elif offset == self.FIFO_RD:
            # Pop from RX FIFO
            if self.fifo_from_other:
                return self.fifo_from_other.pop(0)
            return 0

        elif offset == self.DIV_QUOTIENT:
            self._do_division()
            return self.div_quotient & 0xFFFFFFFF

        elif offset == self.DIV_REMAINDER:
            self._do_division()
            return self.div_remainder & 0xFFFFFFFF

        elif offset == self.DIV_CSR:
            # [1] DIRTY - calculation in progress
            # [0] READY - result available
            return 0 if self.div_dirty else 1

        # Spinlock read (attempt to claim)
        elif self.SPINLOCK_BASE <= offset < self.SPINLOCK_BASE + self.NUM_SPINLOCKS * 4:
            lock_num = (offset - self.SPINLOCK_BASE) // 4
            if self.spinlocks[lock_num] == 0:
                # Lock is free, claim it
                self.spinlocks[lock_num] = 1
                return 1  # Return non-zero = success
            return 0  # Already locked

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.GPIO_OUT:
            self.gpio_out = value & 0x3FFFFFFF  # 30 pins
            self._notify_gpio_change()

        elif offset == self.GPIO_OUT_SET:
            self.gpio_out |= (value & 0x3FFFFFFF)
            self._notify_gpio_change()

        elif offset == self.GPIO_OUT_CLR:
            self.gpio_out &= ~(value & 0x3FFFFFFF)
            self._notify_gpio_change()

        elif offset == self.GPIO_OUT_XOR:
            self.gpio_out ^= (value & 0x3FFFFFFF)
            self._notify_gpio_change()

        elif offset == self.GPIO_OE:
            self.gpio_oe = value & 0x3FFFFFFF
            self._notify_gpio_change()

        elif offset == self.GPIO_OE_SET:
            self.gpio_oe |= (value & 0x3FFFFFFF)
            self._notify_gpio_change()

        elif offset == self.GPIO_OE_CLR:
            self.gpio_oe &= ~(value & 0x3FFFFFFF)
            self._notify_gpio_change()

        elif offset == self.GPIO_OE_XOR:
            self.gpio_oe ^= (value & 0x3FFFFFFF)
            self._notify_gpio_change()

        elif offset == self.FIFO_WR:
            # Push to TX FIFO (goes to other core's RX)
            if self.other_core and len(self.fifo_to_other) < 8:
                self.fifo_to_other.append(value)
                self.other_core.fifo_from_other.append(value)

        elif offset == self.DIV_UDIVIDEND:
            self.div_dividend = value & 0xFFFFFFFF
            self.div_dirty = True

        elif offset == self.DIV_UDIVISOR:
            self.div_divisor = value & 0xFFFFFFFF
            self.div_dirty = True

        elif offset == self.DIV_SDIVIDEND:
            # Signed dividend
            if value & 0x80000000:
                self.div_dividend = value - 0x100000000
            else:
                self.div_dividend = value
            self.div_dirty = True

        elif offset == self.DIV_SDIVISOR:
            # Signed divisor
            if value & 0x80000000:
                self.div_divisor = value - 0x100000000
            else:
                self.div_divisor = value
            self.div_dirty = True

        # Spinlock write (release)
        elif self.SPINLOCK_BASE <= offset < self.SPINLOCK_BASE + self.NUM_SPINLOCKS * 4:
            lock_num = (offset - self.SPINLOCK_BASE) // 4
            self.spinlocks[lock_num] = 0  # Release lock

        else:
            self.regs[offset] = value

    def _do_division(self):
        """Perform pending division."""
        if self.div_dirty:
            if self.div_divisor != 0:
                self.div_quotient = self.div_dividend // self.div_divisor
                self.div_remainder = self.div_dividend % self.div_divisor
            else:
                self.div_quotient = 0xFFFFFFFF
                self.div_remainder = self.div_dividend
            self.div_dirty = False

    def _notify_gpio_change(self):
        """Notify listeners of GPIO state change."""
        if self.on_gpio_change:
            self.on_gpio_change(self.gpio_out, self.gpio_oe)

    def set_external_pin(self, pin: int, value: int):
        """Set external input pin state."""
        if value:
            self.gpio_in |= (1 << pin)
        else:
            self.gpio_in &= ~(1 << pin)


# =============================================================================
# TIMER - 0x40054000
# =============================================================================

class RP2040Timer(RP2040Peripheral):
    """
    RP2040 64-bit microsecond timer.

    Features:
    - 64-bit free-running counter at 1MHz
    - 4 alarm comparators with interrupt generation
    - Pause control for debugging

    Memory map:
      0x00: TIMEHW (write high word, triggers latch)
      0x04: TIMELW (write low word)
      0x08: TIMEHR (read high word, latched)
      0x0C: TIMELR (read low word, latches high)
      0x10: ALARM0
      0x14: ALARM1
      0x18: ALARM2
      0x1C: ALARM3
      0x20: ARMED
      0x24: TIMERAWH
      0x28: TIMERAWL
      0x2C: DBGPAUSE
      0x30: PAUSE
      0x34: INTR
      0x38: INTE
      0x3C: INTF
      0x40: INTS
    """

    # Register offsets
    TIMEHW = 0x00
    TIMELW = 0x04
    TIMEHR = 0x08
    TIMELR = 0x0C
    ALARM0 = 0x10
    ALARM1 = 0x14
    ALARM2 = 0x18
    ALARM3 = 0x1C
    ARMED = 0x20
    TIMERAWH = 0x24
    TIMERAWL = 0x28
    DBGPAUSE = 0x2C
    PAUSE = 0x30
    INTR = 0x34
    INTE = 0x38
    INTF = 0x3C
    INTS = 0x40

    def __init__(self, base: int = 0x40054000, size: int = 0x100):
        super().__init__("TIMER", base, size, irq=0)  # TIMER_IRQ_0

        # Timer state
        self.start_time = time.time()
        self.time_offset = 0  # For write adjustments

        # Alarm comparators
        self.alarms = [0, 0, 0, 0]
        self.armed = 0  # Bitmask of armed alarms

        # Interrupt state
        self.intr = 0   # Raw interrupt status
        self.inte = 0   # Interrupt enable
        self.intf = 0   # Interrupt force

        # Latched time for atomic read
        self.latched_high = 0

        # Pause control
        self.paused = False

    def _get_time_us(self) -> int:
        """Get current time in microseconds."""
        if self.paused:
            return self.time_offset
        elapsed = time.time() - self.start_time
        return int(elapsed * 1_000_000) + self.time_offset

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.TIMELR:
            # Reading TIMELR latches TIMEHR
            time_us = self._get_time_us()
            self.latched_high = (time_us >> 32) & 0xFFFFFFFF
            return time_us & 0xFFFFFFFF

        elif offset == self.TIMEHR:
            return self.latched_high

        elif offset == self.TIMERAWL:
            return self._get_time_us() & 0xFFFFFFFF

        elif offset == self.TIMERAWH:
            return (self._get_time_us() >> 32) & 0xFFFFFFFF

        elif offset == self.ALARM0:
            return self.alarms[0]
        elif offset == self.ALARM1:
            return self.alarms[1]
        elif offset == self.ALARM2:
            return self.alarms[2]
        elif offset == self.ALARM3:
            return self.alarms[3]

        elif offset == self.ARMED:
            return self.armed

        elif offset == self.INTR:
            return self._check_alarms()

        elif offset == self.INTE:
            return self.inte

        elif offset == self.INTF:
            return self.intf

        elif offset == self.INTS:
            return (self._check_alarms() | self.intf) & self.inte

        elif offset == self.PAUSE:
            return 1 if self.paused else 0

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.TIMEHW:
            # Write high word (pending)
            self.regs[self.TIMEHW] = value

        elif offset == self.TIMELW:
            # Write low word - commits time
            high = self.regs.get(self.TIMEHW, 0)
            new_time = (high << 32) | value
            current = self._get_time_us()
            self.time_offset += (new_time - current)

        elif offset == self.ALARM0:
            self.alarms[0] = value
            self.armed |= 1
        elif offset == self.ALARM1:
            self.alarms[1] = value
            self.armed |= 2
        elif offset == self.ALARM2:
            self.alarms[2] = value
            self.armed |= 4
        elif offset == self.ALARM3:
            self.alarms[3] = value
            self.armed |= 8

        elif offset == self.ARMED:
            # Write 1 to clear armed status
            self.armed &= ~value

        elif offset == self.INTR:
            # Write 1 to clear interrupt
            self.intr &= ~value

        elif offset == self.INTE:
            self.inte = value & 0xF

        elif offset == self.INTF:
            self.intf = value & 0xF

        elif offset == self.PAUSE:
            if value & 1:
                self.paused = True
                self.time_offset = self._get_time_us()
            else:
                self.paused = False
                self.start_time = time.time()

        else:
            self.regs[offset] = value

    def _check_alarms(self) -> int:
        """Check which alarms have fired."""
        current_low = self._get_time_us() & 0xFFFFFFFF
        fired = 0

        for i in range(4):
            if self.armed & (1 << i):
                # Compare only low 32 bits
                if current_low >= self.alarms[i]:
                    fired |= (1 << i)
                    self.armed &= ~(1 << i)  # Disarm

        self.intr |= fired
        return self.intr

    def tick(self):
        """Called periodically to check for alarm interrupts."""
        ints = (self._check_alarms() | self.intf) & self.inte
        if ints:
            for i in range(4):
                if ints & (1 << i):
                    self.trigger_irq(1)
                    break


# =============================================================================
# CLOCKS - 0x40008000
# =============================================================================

class RP2040Clocks(RP2040Peripheral):
    """
    RP2040 Clock controller.

    Simplified implementation that reports clocks as already configured.
    Real RP2040 has complex PLL and clock mux configuration.

    For LED blink and FreeRTOS, we just need clocks to appear "ready".
    """

    # Clock generator registers (0x00-0x78)
    CLK_GPOUT0_CTRL = 0x00
    CLK_GPOUT0_DIV = 0x04
    CLK_REF_CTRL = 0x30
    CLK_REF_DIV = 0x34
    CLK_SYS_CTRL = 0x3C
    CLK_SYS_DIV = 0x40
    CLK_PERI_CTRL = 0x48
    CLK_USB_CTRL = 0x54
    CLK_ADC_CTRL = 0x60
    CLK_RTC_CTRL = 0x6C

    # FC0 (Frequency counter)
    FC0_STATUS = 0x98

    def __init__(self, base: int = 0x40008000, size: int = 0x100):
        super().__init__("CLOCKS", base, size)

        # Default clock frequencies (in Hz)
        self.clk_sys = 125_000_000  # 125 MHz default
        self.clk_ref = 12_000_000   # 12 MHz from XOSC
        self.clk_peri = 125_000_000
        self.clk_usb = 48_000_000
        self.clk_adc = 48_000_000
        self.clk_rtc = 46875  # 46.875 kHz

        # Initialize clocks as enabled
        self.regs[self.CLK_SYS_CTRL] = 0x1  # Enable
        self.regs[self.CLK_REF_CTRL] = 0x1
        self.regs[self.CLK_PERI_CTRL] = 0x800  # Enable bit
        self.regs[self.CLK_USB_CTRL] = 0x800
        self.regs[self.CLK_ADC_CTRL] = 0x800

    def get_sys_freq(self) -> int:
        return self.clk_sys


# =============================================================================
# RESETS - 0x4000C000
# =============================================================================

class RP2040Resets(RP2040Peripheral):
    """
    RP2040 Reset controller.

    Controls peripheral reset states. Writing 1 asserts reset,
    writing 0 releases reset. RESET_DONE shows which peripherals
    are out of reset.
    """

    RESET = 0x00
    WDSEL = 0x04
    RESET_DONE = 0x08

    # Reset bits
    RESET_ADC = 1 << 0
    RESET_BUSCTRL = 1 << 1
    RESET_DMA = 1 << 2
    RESET_I2C0 = 1 << 3
    RESET_I2C1 = 1 << 4
    RESET_IO_BANK0 = 1 << 5
    RESET_IO_QSPI = 1 << 6
    RESET_JTAG = 1 << 7
    RESET_PADS_BANK0 = 1 << 8
    RESET_PADS_QSPI = 1 << 9
    RESET_PIO0 = 1 << 10
    RESET_PIO1 = 1 << 11
    RESET_PLL_SYS = 1 << 12
    RESET_PLL_USB = 1 << 13
    RESET_PWM = 1 << 14
    RESET_RTC = 1 << 15
    RESET_SPI0 = 1 << 16
    RESET_SPI1 = 1 << 17
    RESET_SYSCFG = 1 << 18
    RESET_SYSINFO = 1 << 19
    RESET_TBMAN = 1 << 20
    RESET_TIMER = 1 << 21
    RESET_UART0 = 1 << 22
    RESET_UART1 = 1 << 23
    RESET_USBCTRL = 1 << 24

    ALL_RESETS = 0x01FFFFFF

    def __init__(self, base: int = 0x4000C000, size: int = 0x100):
        super().__init__("RESETS", base, size)

        # Start with all peripherals in reset
        self.regs[self.RESET] = self.ALL_RESETS
        self.regs[self.RESET_DONE] = 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.RESET:
            self.regs[self.RESET] = value
            # Update RESET_DONE: peripherals not in reset are done
            self.regs[self.RESET_DONE] = ~value & self.ALL_RESETS
        else:
            self.regs[offset] = value


# =============================================================================
# XOSC - 0x40024000
# =============================================================================

class RP2040XOSC(RP2040Peripheral):
    """
    RP2040 Crystal Oscillator (XOSC).

    Simplified: Always reports stable 12MHz.
    """

    CTRL = 0x00
    STATUS = 0x04
    DORMANT = 0x08
    STARTUP = 0x0C
    COUNT = 0x1C

    # Status bits
    STATUS_STABLE = 1 << 31
    STATUS_ENABLED = 1 << 12

    def __init__(self, base: int = 0x40024000, size: int = 0x100):
        super().__init__("XOSC", base, size)

        # XOSC always appears stable
        self.regs[self.STATUS] = self.STATUS_STABLE | self.STATUS_ENABLED

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            # Auto-set stable when enabled
            if value & 0xFAB:  # Enable value
                self.regs[self.STATUS] |= self.STATUS_STABLE | self.STATUS_ENABLED
        self.regs[offset] = value


# =============================================================================
# PLL_SYS - 0x40028000, PLL_USB - 0x4002C000
# =============================================================================

class RP2040PLL(RP2040Peripheral):
    """
    RP2040 Phase-Locked Loop.

    Simplified: Always reports locked.
    """

    CS = 0x00
    PWR = 0x04
    FBDIV_INT = 0x08
    PRIM = 0x0C

    # CS bits
    CS_LOCK = 1 << 31

    def __init__(self, name: str, base: int, size: int = 0x100):
        super().__init__(name, base, size)

        # PLL always appears locked
        self.regs[self.CS] = self.CS_LOCK

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.PWR:
            # When VCO and main divider powered on, set lock
            if (value & 0x21) == 0:  # VCO and PD bits clear
                self.regs[self.CS] |= self.CS_LOCK
        self.regs[offset] = value


# =============================================================================
# WATCHDOG - 0x40058000
# =============================================================================

class RP2040Watchdog(RP2040Peripheral):
    """
    RP2040 Watchdog timer.

    Also provides TICK register used for timer/tick generation.
    """

    CTRL = 0x00
    LOAD = 0x04
    REASON = 0x08
    SCRATCH0 = 0x0C
    SCRATCH1 = 0x10
    SCRATCH2 = 0x14
    SCRATCH3 = 0x18
    SCRATCH4 = 0x1C
    SCRATCH5 = 0x20
    SCRATCH6 = 0x24
    SCRATCH7 = 0x28
    TICK = 0x2C

    def __init__(self, base: int = 0x40058000, size: int = 0x100):
        super().__init__("WATCHDOG", base, size)

        # TICK: [8:0] = cycles per tick, [9] = enable
        # Default: 12 cycles per tick (12MHz / 12 = 1MHz)
        self.regs[self.TICK] = (1 << 9) | 12  # Enable + 12 cycles


# =============================================================================
# PSM (Power-on State Machine) - 0x40010000
# =============================================================================

class RP2040PSM(RP2040Peripheral):
    """RP2040 Power-on State Machine - reports all power domains on."""

    FRCE_ON = 0x00
    FRCE_OFF = 0x04
    WDSEL = 0x08
    DONE = 0x0C

    ALL_DONE = 0x0001FFFF

    def __init__(self, base: int = 0x40010000, size: int = 0x100):
        super().__init__("PSM", base, size)
        self.regs[self.DONE] = self.ALL_DONE


# =============================================================================
# PIO (Programmable I/O) - 0x50200000 (PIO0), 0x50300000 (PIO1)
# =============================================================================

class RP2040PIO(RP2040Peripheral):
    """
    RP2040 PIO (Programmable I/O) block with full MMIO register interface.

    Each RP2040 has 2 PIO blocks, each with:
    - 32-word instruction memory
    - 4 state machines
    - 8 IRQ flags

    This class provides:
    1. Full MMIO register access (CTRL, FSTAT, TXF, RXF, SMx_*, etc.)
    2. Integration with PIOEmulator for instruction execution
    3. GPIO bidirectional connection

    Memory Map (per PIO block):
        0x000: CTRL          - Control register (enable SMs)
        0x004: FSTAT         - FIFO status
        0x008: FDEBUG        - FIFO debug
        0x00C: FLEVEL        - FIFO levels
        0x010-0x01C: TXF0-3  - TX FIFOs (write-only)
        0x020-0x02C: RXF0-3  - RX FIFOs (read-only)
        0x030: IRQ           - IRQ flags
        0x034: IRQ_FORCE     - Force IRQ
        0x038: INPUT_SYNC_BYPASS
        0x03C: DBG_PADOUT    - GPIO output state
        0x040: DBG_PADOE     - GPIO output enable
        0x044: DBG_CFGINFO   - Config info
        0x048-0x064: INSTR_MEM0-31
        0x0C8-0x0E4: SM0 registers
        0x0E8-0x104: SM1 registers
        0x108-0x124: SM2 registers
        0x128-0x144: SM3 registers
    """

    # Control registers
    CTRL = 0x000
    FSTAT = 0x004
    FDEBUG = 0x008
    FLEVEL = 0x00C

    # FIFO access
    TXF0 = 0x010
    TXF1 = 0x014
    TXF2 = 0x018
    TXF3 = 0x01C
    RXF0 = 0x020
    RXF1 = 0x024
    RXF2 = 0x028
    RXF3 = 0x02C

    # IRQ
    IRQ = 0x030
    IRQ_FORCE = 0x034

    # Debug
    INPUT_SYNC_BYPASS = 0x038
    DBG_PADOUT = 0x03C
    DBG_PADOE = 0x040
    DBG_CFGINFO = 0x044

    # Instruction memory (32 words)
    INSTR_MEM0 = 0x048  # Through INSTR_MEM31 at 0x0C4

    # Interrupt registers
    INTR = 0x128
    IRQ0_INTE = 0x12C
    IRQ0_INTF = 0x130
    IRQ0_INTS = 0x134
    IRQ1_INTE = 0x138
    IRQ1_INTF = 0x13C
    IRQ1_INTS = 0x140

    # State machine register offsets (relative to SM base)
    SM_CLKDIV = 0x00
    SM_EXECCTRL = 0x04
    SM_SHIFTCTRL = 0x08
    SM_ADDR = 0x0C
    SM_INSTR = 0x10
    SM_PINCTRL = 0x14

    # SM base addresses
    SM0_BASE = 0x0C8
    SM1_BASE = 0x0E8
    SM2_BASE = 0x108
    SM3_BASE = 0x128

    def __init__(self, index: int = 0, base: int = None, irq: int = 7):
        """
        Initialize PIO block.

        Args:
            index: PIO block index (0 or 1)
            base: Base address (auto-set if None)
            irq: IRQ number (7 for PIO0_IRQ_0, 9 for PIO1_IRQ_0)
        """
        if base is None:
            base = 0x50200000 if index == 0 else 0x50300000

        super().__init__(f"PIO{index}", base, 0x200, irq)
        self.index = index

        # Import PIO emulator
        try:
            from .peripherals import PIOEmulator, PIOStateMachine, PIOInstruction
        except ImportError:
            from peripherals import PIOEmulator, PIOStateMachine, PIOInstruction

        self.PIOInstruction = PIOInstruction

        # Create PIO emulator
        self.emu = PIOEmulator(index=index)

        # GPIO connection callbacks
        self.on_gpio_out: Optional[Callable[[int, int], None]] = None  # (pins, dirs)
        self.gpio_in: int = 0  # Input from external GPIO

        # IRQ callbacks
        self.irq0_inte = 0
        self.irq0_intf = 0
        self.irq1_inte = 0
        self.irq1_intf = 0

        # Wire PIO emulator GPIO callback
        self.emu.on_gpio_write = self._on_pio_gpio_write

        self.log.info(f"PIO{index} initialized at 0x{base:08X}")

    def _on_pio_gpio_write(self, pins: int, dirs: int):
        """Called when PIO writes to GPIO."""
        if self.on_gpio_out:
            self.on_gpio_out(pins, dirs)

    def set_gpio_input(self, pins: int):
        """Set GPIO input state (from external GPIO peripheral)."""
        self.gpio_in = pins
        self.emu.gpio_state = (self.emu.gpio_state & self.emu.gpio_dir) | (pins & ~self.emu.gpio_dir)

    def _get_sm_base(self, sm_index: int) -> int:
        """Get base offset for state machine registers."""
        return [self.SM0_BASE, self.SM1_BASE, self.SM2_BASE, self.SM3_BASE][sm_index]

    def _read_reg(self, offset: int, size: int) -> int:
        # CTRL - SM enable status
        if offset == self.CTRL:
            enable_bits = 0
            for i, sm in enumerate(self.emu.sm):
                if sm.enabled:
                    enable_bits |= (1 << i)
            return enable_bits

        # FSTAT - FIFO status
        elif offset == self.FSTAT:
            fstat = 0
            for i, sm in enumerate(self.emu.sm):
                if sm.rx_full():
                    fstat |= (1 << i)  # RXFULL
                if sm.rx_empty():
                    fstat |= (1 << (i + 8))  # RXEMPTY
                if sm.tx_full():
                    fstat |= (1 << (i + 16))  # TXFULL
                if sm.tx_empty():
                    fstat |= (1 << (i + 24))  # TXEMPTY
            return fstat

        # FDEBUG - FIFO debug
        elif offset == self.FDEBUG:
            return self.regs.get(offset, 0)

        # FLEVEL - FIFO levels
        elif offset == self.FLEVEL:
            flevel = 0
            for i, sm in enumerate(self.emu.sm):
                tx_level = len(sm.tx_fifo) & 0xF
                rx_level = len(sm.rx_fifo) & 0xF
                flevel |= (tx_level << (i * 8)) | (rx_level << (i * 8 + 4))
            return flevel

        # RXF0-3 - Read from RX FIFO
        elif self.RXF0 <= offset <= self.RXF3:
            sm_idx = (offset - self.RXF0) // 4
            sm = self.emu.sm[sm_idx]
            if sm.rx_fifo:
                return sm.rx_fifo.pop(0)
            return 0

        # IRQ - Raw IRQ flags
        elif offset == self.IRQ:
            return self.emu.irq_flags

        # DBG_PADOUT - GPIO output state
        elif offset == self.DBG_PADOUT:
            return self.emu.gpio_state

        # DBG_PADOE - GPIO output enable
        elif offset == self.DBG_PADOE:
            return self.emu.gpio_dir

        # DBG_CFGINFO
        elif offset == self.DBG_CFGINFO:
            # FIFO depth = 4, SM count = 4, IMEM size = 32
            return (4 << 16) | (4 << 8) | 32

        # Instruction memory
        elif self.INSTR_MEM0 <= offset < self.INSTR_MEM0 + 32 * 4:
            word_idx = (offset - self.INSTR_MEM0) // 4
            return self.emu.instructions[word_idx] if word_idx < 32 else 0

        # Interrupt status registers
        elif offset == self.INTR:
            return self.emu.irq_flags
        elif offset == self.IRQ0_INTE:
            return self.irq0_inte
        elif offset == self.IRQ0_INTF:
            return self.irq0_intf
        elif offset == self.IRQ0_INTS:
            return (self.emu.irq_flags | self.irq0_intf) & self.irq0_inte
        elif offset == self.IRQ1_INTE:
            return self.irq1_inte
        elif offset == self.IRQ1_INTF:
            return self.irq1_intf
        elif offset == self.IRQ1_INTS:
            return (self.emu.irq_flags | self.irq1_intf) & self.irq1_inte

        # State machine registers
        for sm_idx in range(4):
            sm_base = self._get_sm_base(sm_idx)
            if sm_base <= offset < sm_base + 0x18:
                return self._read_sm_reg(sm_idx, offset - sm_base)

        return self.regs.get(offset, 0)

    def _read_sm_reg(self, sm_idx: int, sm_offset: int) -> int:
        """Read state machine register."""
        sm = self.emu.sm[sm_idx]

        if sm_offset == self.SM_CLKDIV:
            return (sm.clkdiv_int << 16) | (sm.clkdiv_frac << 8)

        elif sm_offset == self.SM_EXECCTRL:
            return (
                (sm.wrap_top << 12) |
                (sm.wrap_bottom << 7) |
                (sm.side_set_pindirs << 4) |
                (sm.jmp_pin)
            )

        elif sm_offset == self.SM_SHIFTCTRL:
            return (
                (sm.pull_threshold << 25) |
                (sm.push_threshold << 20) |
                (int(sm.out_shiftdir) << 19) |
                (int(sm.in_shiftdir) << 18) |
                (int(sm.autopull) << 17) |
                (int(sm.autopush) << 16)
            )

        elif sm_offset == self.SM_ADDR:
            return sm.pc

        elif sm_offset == self.SM_INSTR:
            return self.emu.instructions[sm.pc]

        elif sm_offset == self.SM_PINCTRL:
            return (
                (sm.side_set_bits << 29) |
                (sm.set_count << 26) |
                (sm.out_count << 20) |
                (sm.in_base << 15) |
                (sm.side_set_base << 10) |
                (sm.set_base << 5) |
                (sm.out_base)
            )

        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        # CTRL - Enable/disable state machines
        if offset == self.CTRL:
            # Bits 3:0 = SM enable
            enable_mask = value & 0xF
            # Bits 11:8 = SM restart
            restart_mask = (value >> 8) & 0xF
            # Bits 7:4 = CLKDIV restart
            clkdiv_restart = (value >> 4) & 0xF

            for i in range(4):
                if enable_mask & (1 << i):
                    self.emu.sm[i].enabled = True
                else:
                    self.emu.sm[i].enabled = False

                if restart_mask & (1 << i):
                    self.emu.sm[i].reset()

            self.log.debug(f"CTRL write: enable={enable_mask:04b}")

        # TXF0-3 - Write to TX FIFO
        elif self.TXF0 <= offset <= self.TXF3:
            sm_idx = (offset - self.TXF0) // 4
            sm = self.emu.sm[sm_idx]
            if not sm.tx_full():
                sm.tx_fifo.append(value & 0xFFFFFFFF)

        # IRQ - Clear IRQ flags (write 1 to clear)
        elif offset == self.IRQ:
            self.emu.irq_flags &= ~value

        # IRQ_FORCE - Force IRQ flags
        elif offset == self.IRQ_FORCE:
            self.emu.irq_flags |= value

        # Instruction memory
        elif self.INSTR_MEM0 <= offset < self.INSTR_MEM0 + 32 * 4:
            word_idx = (offset - self.INSTR_MEM0) // 4
            if word_idx < 32:
                self.emu.instructions[word_idx] = value & 0xFFFF
                self.log.debug(f"INSTR[{word_idx}] = 0x{value:04X}")

        # Interrupt registers
        elif offset == self.IRQ0_INTE:
            self.irq0_inte = value
        elif offset == self.IRQ0_INTF:
            self.irq0_intf = value
        elif offset == self.IRQ1_INTE:
            self.irq1_inte = value
        elif offset == self.IRQ1_INTF:
            self.irq1_intf = value

        # State machine registers
        else:
            for sm_idx in range(4):
                sm_base = self._get_sm_base(sm_idx)
                if sm_base <= offset < sm_base + 0x18:
                    self._write_sm_reg(sm_idx, offset - sm_base, value)
                    return

        self.regs[offset] = value

    def _write_sm_reg(self, sm_idx: int, sm_offset: int, value: int):
        """Write state machine register."""
        sm = self.emu.sm[sm_idx]

        if sm_offset == self.SM_CLKDIV:
            sm.clkdiv_int = (value >> 16) & 0xFFFF
            sm.clkdiv_frac = (value >> 8) & 0xFF

        elif sm_offset == self.SM_EXECCTRL:
            sm.wrap_top = (value >> 12) & 0x1F
            sm.wrap_bottom = (value >> 7) & 0x1F
            sm.side_set_pindirs = bool(value & (1 << 4))
            sm.jmp_pin = value & 0x1F

            # Side-set optional and side-set bits are also in EXECCTRL
            sm.side_set_opt = bool(value & (1 << 30))
            # STATUS_SEL and STATUS_N also here

        elif sm_offset == self.SM_SHIFTCTRL:
            sm.pull_threshold = (value >> 25) & 0x1F
            sm.push_threshold = (value >> 20) & 0x1F
            sm.out_shiftdir = bool(value & (1 << 19))
            sm.in_shiftdir = bool(value & (1 << 18))
            sm.autopull = bool(value & (1 << 17))
            sm.autopush = bool(value & (1 << 16))

            # Fix 0 threshold = 32
            if sm.pull_threshold == 0:
                sm.pull_threshold = 32
            if sm.push_threshold == 0:
                sm.push_threshold = 32

        elif sm_offset == self.SM_INSTR:
            # Execute instruction immediately (used for debugging/setup)
            instr = self.PIOInstruction.decode(value & 0xFFFF, sm.side_set_bits, sm.side_set_opt)
            self.log.debug(f"SM{sm_idx} exec: {instr}")
            # Temporarily enable, execute one cycle
            was_enabled = sm.enabled
            sm.enabled = True
            self.emu.instructions[sm.pc] = value & 0xFFFF
            self.emu.step_sm(sm)
            sm.enabled = was_enabled

        elif sm_offset == self.SM_PINCTRL:
            sm.side_set_bits = (value >> 29) & 0x7
            sm.set_count = (value >> 26) & 0x7
            sm.out_count = (value >> 20) & 0x3F
            sm.in_base = (value >> 15) & 0x1F
            sm.side_set_base = (value >> 10) & 0x1F
            sm.set_base = (value >> 5) & 0x1F
            sm.out_base = value & 0x1F

            self.log.debug(f"SM{sm_idx} PINCTRL: out={sm.out_base}+{sm.out_count}, set={sm.set_base}+{sm.set_count}")

    def step(self) -> int:
        """Execute one PIO cycle for all enabled state machines."""
        cycles = self.emu.step()

        # Update external GPIO
        if self.on_gpio_out:
            self.on_gpio_out(self.emu.gpio_state, self.emu.gpio_dir)

        # Check for IRQ
        ints0 = (self.emu.irq_flags | self.irq0_intf) & self.irq0_inte
        if ints0:
            self.trigger_irq(1)

        return cycles

    def load_program(self, program: List[int], offset: int = 0):
        """Load PIO program into instruction memory."""
        self.emu.load_program(program, offset)

    def disassemble(self, start: int = 0, end: int = 32) -> List[str]:
        """Disassemble instruction memory."""
        return self.emu.disassemble(start, end)


# =============================================================================
# RP2040 PERIPHERAL SET
# =============================================================================

class RP2040PeripheralSet:
    """
    Complete set of RP2040 peripherals for LED blink, PIO, and FreeRTOS.

    Features:
    - Full GPIO (IO_BANK0, PADS, SIO)
    - PIO0 and PIO1 with instruction execution
    - Timer with alarms and interrupts
    - Clocks, Resets, XOSC, PLL
    - Bidirectional GPIO connection between PIO and SIO

    Usage:
        peripherals = RP2040PeripheralSet()
        peripherals.irq_callback = my_irq_handler

        # In server loop:
        peripheral = peripherals.find_peripheral(address)
        if peripheral:
            value, status = peripheral.read(address, size)

        # Run PIO (call periodically):
        peripherals.step_pio()
    """

    def __init__(self, cpuid: int = 0, chip: str = "RP2040", log: logging.Logger = None,
                 enable_all: bool = True):
        """
        Initialize RP2040 peripheral set.

        Args:
            cpuid: Core ID (0 or 1) for SIO
            chip: Chip name ("RP2040" or "RP2350")
            log: Optional logger instance
            enable_all: Enable all peripherals (default True)
        """
        self.log = log or logging.getLogger('RP2040')
        self.chip = chip
        self.irq_callback: Optional[Callable[[int, int], None]] = None

        # Create core peripherals
        # Use detailed implementations from rp2040_misc for bootrom compatibility
        # (CLOCKS has CLK_*_SELECTED, RESETS has RESET_DONE logic, WATCHDOG has TICK)
        try:
            from .rp2040_misc import (
                RP2040CLOCKS as _DetailedClocks,
                RP2040RESETS as _DetailedResets,
                RP2040WATCHDOG as _DetailedWatchdog,
            )
            _use_detailed = True
        except ImportError:
            _use_detailed = False

        self.gpio = RP2040GPIO()
        self.pads = RP2040Pads()
        self.sio = RP2040SIO(cpuid=cpuid)
        self.timer = RP2040Timer()
        self.clocks = _DetailedClocks() if _use_detailed else RP2040Clocks()
        self.resets = _DetailedResets() if _use_detailed else RP2040Resets()
        self.xosc = RP2040XOSC()
        self.pll_sys = RP2040PLL("PLL_SYS", 0x40028000)
        self.pll_usb = RP2040PLL("PLL_USB", 0x4002C000)
        self.watchdog = _DetailedWatchdog() if _use_detailed else RP2040Watchdog()
        self.psm = RP2040PSM()

        # Create PIO blocks
        self.pio0 = RP2040PIO(index=0, irq=7)   # PIO0_IRQ_0
        self.pio1 = RP2040PIO(index=1, irq=9)   # PIO1_IRQ_0

        # Link GPIO to SIO
        self.gpio.sio = self.sio

        # Wire PIO GPIO to SIO/GPIO bidirectionally
        self._setup_pio_gpio_connection()

        # Peripheral list for address lookup (internal use)
        self._peripherals: Dict[str, RP2040Peripheral] = {
            'GPIO': self.gpio,
            'PADS': self.pads,
            'SIO': self.sio,
            'TIMER': self.timer,
            'CLOCKS': self.clocks,
            'RESETS': self.resets,
            'XOSC': self.xosc,
            'PLL_SYS': self.pll_sys,
            'PLL_USB': self.pll_usb,
            'WATCHDOG': self.watchdog,
            'PSM': self.psm,
            'PIO0': self.pio0,
            'PIO1': self.pio1,
        }

        # Add additional peripherals if requested
        if enable_all:
            self._create_communication_peripherals()
            self._create_adc_pwm_dma_peripherals()
            self._create_misc_peripherals()

        # Peripheral list for address lookup
        self.peripherals: List[RP2040Peripheral] = list(self._peripherals.values())

        # Virtual LED state (GPIO25 on Pico)
        self.led_state = False
        self.on_led_change: Optional[Callable[[bool], None]] = None

        # Setup GPIO change callback
        self.sio.on_gpio_change = self._on_gpio_change

        periph_count = len(self._peripherals)
        self.log.info(f"{chip} peripherals initialized ({periph_count} peripherals)")

    def _create_communication_peripherals(self):
        """Create UART, SPI, I2C peripherals."""
        try:
            RP2040UART, RP2040SPI, RP2040I2C = _import_uart_spi_i2c()

            # UARTs
            self.uart0 = RP2040UART(index=0)  # 0x40034000
            self.uart1 = RP2040UART(index=1)  # 0x40038000
            self._peripherals['UART0'] = self.uart0
            self._peripherals['UART1'] = self.uart1

            # SPIs
            self.spi0 = RP2040SPI(index=0)  # 0x4003C000
            self.spi1 = RP2040SPI(index=1)  # 0x40040000
            self._peripherals['SPI0'] = self.spi0
            self._peripherals['SPI1'] = self.spi1

            # I2Cs
            self.i2c0 = RP2040I2C(index=0)  # 0x40044000
            self.i2c1 = RP2040I2C(index=1)  # 0x40048000
            self._peripherals['I2C0'] = self.i2c0
            self._peripherals['I2C1'] = self.i2c1

            self.log.debug("Communication peripherals created (UART, SPI, I2C)")

        except ImportError as e:
            self.log.warning(f"Could not import communication peripherals: {e}")

    def _create_adc_pwm_dma_peripherals(self):
        """Create ADC, PWM, DMA peripherals."""
        try:
            RP2040ADC, RP2040PWM, RP2040DMA = _import_adc_pwm_dma()

            # ADC
            self.adc = RP2040ADC()  # 0x4004C000
            self._peripherals['ADC'] = self.adc

            # PWM (8 slices)
            self.pwm = RP2040PWM()  # 0x40050000
            self._peripherals['PWM'] = self.pwm

            # DMA (12 channels)
            self.dma = RP2040DMA()  # 0x50000000
            self._peripherals['DMA'] = self.dma

            self.log.debug("ADC/PWM/DMA peripherals created")

        except ImportError as e:
            self.log.warning(f"Could not import ADC/PWM/DMA peripherals: {e}")

    def _create_misc_peripherals(self):
        """Create miscellaneous peripherals."""
        try:
            (RP2040RTC, RP2040ROSC, RP2040SYSINFO, RP2040SYSCFG,
             RP2040VREG, RP2040TBMAN, RP2040BUSCTRL, RP2040XIP,
             RP2040SSI, RP2040IOQSPI, RP2040PADSQSPI, RP2040USB,
             _RP2040RESETS, _RP2040CLOCKS, _RP2040WATCHDOG) = _import_misc()

            # RTC
            self.rtc = RP2040RTC()  # 0x4005C000
            self._peripherals['RTC'] = self.rtc

            # ROSC
            self.rosc = RP2040ROSC()  # 0x40060000
            self._peripherals['ROSC'] = self.rosc

            # SYSINFO
            self.sysinfo = RP2040SYSINFO()  # 0x40000000
            self._peripherals['SYSINFO'] = self.sysinfo

            # SYSCFG
            self.syscfg = RP2040SYSCFG()  # 0x40004000
            self._peripherals['SYSCFG'] = self.syscfg

            # VREG and Chip Reset
            self.vreg = RP2040VREG()  # 0x40064000
            self._peripherals['VREG'] = self.vreg

            # TBMAN (Testbench manager)
            self.tbman = RP2040TBMAN()  # 0x4006C000
            self._peripherals['TBMAN'] = self.tbman

            # BUSCTRL
            self.busctrl = RP2040BUSCTRL()  # 0x40030000
            self._peripherals['BUSCTRL'] = self.busctrl

            # XIP
            self.xip = RP2040XIP()  # 0x14000000
            self._peripherals['XIP'] = self.xip

            # SSI
            self.ssi = RP2040SSI()  # 0x18000000
            self._peripherals['SSI'] = self.ssi

            # IO_QSPI
            self.io_qspi = RP2040IOQSPI()  # 0x40018000
            self._peripherals['IO_QSPI'] = self.io_qspi

            # PADS_QSPI
            self.pads_qspi = RP2040PADSQSPI()  # 0x40020000
            self._peripherals['PADS_QSPI'] = self.pads_qspi

            # USB
            self.usb = RP2040USB()  # 0x50110000
            self._peripherals['USB'] = self.usb

            # USB DPRAM (endpoint buffers)
            from slab_rp2040.rp2040_misc import RP2040USBDPRAM
            self.usb_dpram = RP2040USBDPRAM()  # 0x50100000
            self._peripherals['USB_DPRAM'] = self.usb_dpram
            # Cross-link USB controller and DPRAM
            self.usb.dpram = self.usb_dpram
            self.usb_dpram._usb_ctrl = self.usb

            self.log.debug("Misc peripherals created")

        except ImportError as e:
            self.log.warning(f"Could not import misc peripherals: {e}")

    def _setup_pio_gpio_connection(self):
        """Wire PIO GPIO output to SIO and vice versa."""
        # When PIO writes to GPIO, update SIO input state
        def pio0_gpio_out(pins: int, dirs: int):
            self._merge_pio_gpio(0, pins, dirs)

        def pio1_gpio_out(pins: int, dirs: int):
            self._merge_pio_gpio(1, pins, dirs)

        self.pio0.on_gpio_out = pio0_gpio_out
        self.pio1.on_gpio_out = pio1_gpio_out

        # Track PIO GPIO state
        self._pio_gpio_out = [0, 0]  # PIO0, PIO1 output
        self._pio_gpio_oe = [0, 0]   # PIO0, PIO1 output enable

    def _merge_pio_gpio(self, pio_idx: int, pins: int, dirs: int):
        """Merge PIO GPIO output with SIO GPIO state."""
        self._pio_gpio_out[pio_idx] = pins
        self._pio_gpio_oe[pio_idx] = dirs

        # Merge: PIO output drives pins where PIO has output enabled
        # SIO sees the merged state
        merged_out = self.sio.gpio_out
        merged_oe = self.sio.gpio_oe

        for i in range(2):
            pio_out = self._pio_gpio_out[i]
            pio_oe = self._pio_gpio_oe[i]
            # Where PIO drives, use PIO value
            merged_out = (merged_out & ~pio_oe) | (pio_out & pio_oe)
            merged_oe |= pio_oe

        # Update SIO's view of GPIO (for reads)
        self.sio.gpio_in = merged_out

        # Also update GPIO peripheral status registers
        self._update_gpio_status(merged_out, merged_oe)

    def _update_gpio_status(self, gpio_out: int, gpio_oe: int):
        """Update GPIO status registers based on current state."""
        # This would update the GPIO STATUS registers (read-only)
        # to reflect current output state, OE, etc.
        pass  # GPIO STATUS is updated on read in RP2040GPIO

    def _sync_gpio_to_pio(self):
        """Sync SIO GPIO state to PIO inputs."""
        # Get current SIO output state
        gpio_state = self.sio.gpio_out

        # Also include external input (from PADS)
        # For now, just use SIO output as PIO input

        # PIO sees merged state
        merged = gpio_state
        for i in range(2):
            if self._pio_gpio_oe[i]:
                merged = (merged & ~self._pio_gpio_oe[i]) | (self._pio_gpio_out[i] & self._pio_gpio_oe[i])

        self.pio0.set_gpio_input(merged)
        self.pio1.set_gpio_input(merged)

    def find(self, addr: int) -> Optional[RP2040Peripheral]:
        """Find peripheral that contains the given address (legacy)."""
        return self.find_peripheral(addr)

    def find_peripheral(self, addr: int) -> Optional[RP2040Peripheral]:
        """Find peripheral that contains the given address."""
        for p in self.peripherals:
            if p.contains(addr):
                return p
        return None

    def setup_irq_callback(self, callback: Callable[[int, int], None]):
        """Set IRQ callback for all peripherals."""
        self.irq_callback = callback
        for p in self.peripherals:
            p.irq_callback = callback

    def _on_gpio_change(self, gpio_out: int, gpio_oe: int):
        """Called when GPIO state changes via SIO."""
        # Sync to PIO inputs
        self._sync_gpio_to_pio()

        # Check LED (GPIO25)
        led_pin = 25
        if gpio_oe & (1 << led_pin):
            new_state = bool(gpio_out & (1 << led_pin))
            if new_state != self.led_state:
                self.led_state = new_state
                self.log.info(f"LED {'ON' if new_state else 'OFF'}")
                if self.on_led_change:
                    self.on_led_change(new_state)

    def tick(self):
        """Periodic tick for timer interrupts."""
        self.timer.tick()

    def step_pio(self, cycles: int = 1) -> int:
        """
        Execute PIO cycles.

        Call this periodically to advance PIO state machines.
        Returns total cycles executed.
        """
        total = 0
        for _ in range(cycles):
            # Sync GPIO to PIO before stepping
            self._sync_gpio_to_pio()

            # Step both PIO blocks
            total += self.pio0.step()
            total += self.pio1.step()
        return total

    def load_pio_program(self, pio_index: int, program: List[int], offset: int = 0):
        """
        Load a PIO program into instruction memory.

        Args:
            pio_index: PIO block (0 or 1)
            program: List of 16-bit instruction words
            offset: Starting address in instruction memory
        """
        pio = self.pio0 if pio_index == 0 else self.pio1
        pio.load_program(program, offset)
        self.log.info(f"Loaded {len(program)} instructions to PIO{pio_index} at offset {offset}")

    def disassemble_pio(self, pio_index: int, start: int = 0, end: int = 32) -> List[str]:
        """Disassemble PIO instruction memory."""
        pio = self.pio0 if pio_index == 0 else self.pio1
        return pio.disassemble(start, end)


# =============================================================================
# RP2350 PERIPHERAL SET
# =============================================================================

def _import_rp2350_peripherals():
    """Lazy import RP2350-specific peripherals."""
    from .rp2350_peripherals import (
        RP2350SHA256, RP2350TRNG, RP2350OTP, RP2350OTPData,
        RP2350HSTX, RP2350HSTXFIFO, RP2350POWMAN, RP2350GlitchDetector,
        RP2350ACCESSCTRL, RP2350TICKS, RP2350QMI
    )
    return (RP2350SHA256, RP2350TRNG, RP2350OTP, RP2350OTPData,
            RP2350HSTX, RP2350HSTXFIFO, RP2350POWMAN, RP2350GlitchDetector,
            RP2350ACCESSCTRL, RP2350TICKS, RP2350QMI)


class RP2350PeripheralSet(RP2040PeripheralSet):
    """
    Complete set of RP2350 peripherals.

    Extends RP2040PeripheralSet with RP2350-specific features:
    - SHA256 hardware accelerator
    - True Random Number Generator (TRNG)
    - One-Time Programmable (OTP) memory
    - High-Speed TX (HSTX) interface
    - Power Manager (POWMAN)
    - Glitch/Fault Detector
    - Access Control (ACCESSCTRL)
    - TICKS (time reference)
    - QMI (QSPI memory interface)
    - Third PIO block (PIO2)
    - Extended GPIO (48 pins)

    RP2350 can run in ARM (Cortex-M33) or RISC-V (Hazard3) mode.
    """

    def __init__(self, cpuid: int = 0, arch: str = "ARM", log: logging.Logger = None):
        """
        Initialize RP2350 peripheral set.

        Args:
            cpuid: Core ID (0 or 1) for SIO
            arch: Architecture ("ARM" for Cortex-M33 or "RISCV" for Hazard3)
            log: Optional logger instance
        """
        self.arch = arch

        # Initialize base RP2040 peripherals
        super().__init__(cpuid=cpuid, chip="RP2350", log=log, enable_all=True)

        # Add RP2350-specific peripherals
        self._create_rp2350_peripherals()

        # Add third PIO block (RP2350 has 3 PIO blocks)
        self.pio2 = RP2040PIO(index=2, base=0x50400000, irq=11)
        self._peripherals['PIO2'] = self.pio2

        # Update peripheral list
        self.peripherals = list(self._peripherals.values())

        periph_count = len(self._peripherals)
        self.log.info(f"RP2350 ({arch}) peripherals initialized ({periph_count} peripherals)")

    def _create_rp2350_peripherals(self):
        """Create RP2350-specific peripherals."""
        try:
            (RP2350SHA256, RP2350TRNG, RP2350OTP, RP2350OTPData,
             RP2350HSTX, RP2350HSTXFIFO, RP2350POWMAN, RP2350GlitchDetector,
             RP2350ACCESSCTRL, RP2350TICKS, RP2350QMI) = _import_rp2350_peripherals()

            # SHA256 hardware accelerator
            self.sha256 = RP2350SHA256()  # 0x400F8000
            self._peripherals['SHA256'] = self.sha256

            # True Random Number Generator
            self.trng = RP2350TRNG()  # 0x400FC000
            self._peripherals['TRNG'] = self.trng

            # One-Time Programmable memory (registers)
            self.otp = RP2350OTP()  # 0x40120000
            self._peripherals['OTP'] = self.otp

            # OTP data view (raw read) - requires OTP reference
            self.otp_data = RP2350OTPData(otp=self.otp)  # 0x40130000
            self._peripherals['OTP_DATA'] = self.otp_data

            # High-Speed TX
            self.hstx = RP2350HSTX()  # 0x400C0000
            self._peripherals['HSTX'] = self.hstx

            # HSTX FIFO
            self.hstx_fifo = RP2350HSTXFIFO()  # 0x50600000
            self._peripherals['HSTX_FIFO'] = self.hstx_fifo

            # Power Manager
            self.powman = RP2350POWMAN()  # 0x40100000
            self._peripherals['POWMAN'] = self.powman

            # Glitch Detector
            self.glitch_detector = RP2350GlitchDetector()  # 0x40158000
            self._peripherals['GLITCH_DETECTOR'] = self.glitch_detector

            # Access Control
            self.accessctrl = RP2350ACCESSCTRL()  # 0x40154000
            self._peripherals['ACCESSCTRL'] = self.accessctrl

            # TICKS
            self.ticks = RP2350TICKS()  # 0x40108000
            self._peripherals['TICKS'] = self.ticks

            # QMI (QSPI memory interface)
            self.qmi = RP2350QMI()  # 0x400D0000
            self._peripherals['QMI'] = self.qmi

            self.log.debug("RP2350-specific peripherals created")

        except ImportError as e:
            self.log.warning(f"Could not import RP2350 peripherals: {e}")

    def step_pio(self, cycles: int = 1) -> int:
        """
        Execute PIO cycles (including PIO2 for RP2350).

        Call this periodically to advance PIO state machines.
        Returns total cycles executed.
        """
        total = 0
        for _ in range(cycles):
            # Sync GPIO to PIO before stepping
            self._sync_gpio_to_pio()

            # Step all three PIO blocks
            total += self.pio0.step()
            total += self.pio1.step()
            total += self.pio2.step()
        return total


# =============================================================================
# TEST / DEMO
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Create peripheral set
    peripherals = RP2040PeripheralSet()

    print("\n" + "=" * 60)
    print("  RP2040 Peripheral Emulation Test")
    print("=" * 60)

    # ==========================================================================
    # Test 1: LED Blink via SIO
    # ==========================================================================
    print("\n=== Test 1: LED Blink via SIO ===\n")

    # 1. Release IO_BANK0 and PADS from reset
    peripherals.resets.write(0x4000C000, 4, 0)  # Clear all resets

    # 2. Configure GPIO25 for SIO function
    gpio25_ctrl = 0x40014000 + 25 * 8 + 4
    peripherals.gpio.write(gpio25_ctrl, 4, 5)  # FUNCSEL = 5 (SIO)

    # 3. Set GPIO25 as output via SIO
    peripherals.sio.write(0xD0000000 + 0x24, 4, 1 << 25)  # GPIO_OE_SET

    # 4. Toggle LED
    for i in range(4):
        if i % 2 == 0:
            peripherals.sio.write(0xD0000000 + 0x14, 4, 1 << 25)  # GPIO_OUT_SET
        else:
            peripherals.sio.write(0xD0000000 + 0x18, 4, 1 << 25)  # GPIO_OUT_CLR

    # ==========================================================================
    # Test 2: LED Blink via PIO
    # ==========================================================================
    print("\n=== Test 2: LED Blink via PIO ===\n")

    # Import PIO programs
    try:
        from .peripherals import PIOPrograms
    except ImportError:
        from peripherals import PIOPrograms

    # Load blink program into PIO0
    blink_program = PIOPrograms.blink_led()
    peripherals.load_pio_program(0, blink_program)

    # Disassemble
    print("PIO0 Program:")
    for line in peripherals.disassemble_pio(0, 0, 2):
        print(f"  {line}")
    print()

    # Configure SM0 for LED (GPIO25)
    pio0 = peripherals.pio0.emu
    pio0.configure_sm(0,
        set_base=25,     # SET pins start at GPIO25
        set_count=1,     # 1 pin
        wrap_bottom=0,
        wrap_top=1,
    )

    # Enable SM0 via CTRL register
    peripherals.pio0.write(peripherals.pio0.base + RP2040PIO.CTRL, 4, 0x1)

    # Run a few cycles
    print("Running PIO (10 cycles):")
    for i in range(10):
        peripherals.step_pio()
        gpio = peripherals.pio0.emu.gpio_state
        led = "ON " if gpio & (1 << 25) else "OFF"
        print(f"  Cycle {i}: GPIO25 = {led}")

    # ==========================================================================
    # Test 3: PIO FIFO and TX
    # ==========================================================================
    print("\n=== Test 3: PIO FIFO Operations ===\n")

    # Simple program: pull from FIFO, output to pins
    tx_program = [
        0x80A0,  # pull block
        0x6008,  # out pins, 8
    ]
    peripherals.load_pio_program(0, tx_program)

    # Reconfigure SM0 for 8-bit output on GPIO0
    pio0.configure_sm(0,
        out_base=0,
        out_count=8,
        wrap_bottom=0,
        wrap_top=1,
        autopull=False,
    )

    # Reset SM0
    peripherals.pio0.write(peripherals.pio0.base + RP2040PIO.CTRL, 4, 0x101)  # Enable + restart

    # Push data to TX FIFO
    print("Pushing 0xAB to TX FIFO...")
    peripherals.pio0.write(peripherals.pio0.base + RP2040PIO.TXF0, 4, 0xAB)

    # Check FSTAT
    fstat = peripherals.pio0._read_reg(RP2040PIO.FSTAT, 4)
    print(f"FSTAT = 0x{fstat:08X}")
    print(f"  TX0 empty: {bool(fstat & (1 << 24))}")

    # Run PIO
    print("Running PIO...")
    peripherals.step_pio(5)

    # Check GPIO output
    gpio = peripherals.pio0.emu.gpio_state
    print(f"GPIO output = 0x{gpio:08X} (lower 8 bits = 0x{gpio & 0xFF:02X})")

    print("\n" + "=" * 60)
    print("  All Tests Complete!")
    print("=" * 60 + "\n")
