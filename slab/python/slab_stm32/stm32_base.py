"""
STM32 Peripheral Base Classes

Provides the base class for all STM32 peripheral emulation.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from abc import ABC
from typing import Dict, Optional, Callable, Tuple

# Status codes
STATUS_OK = 0
STATUS_ERROR = 1


class STM32Peripheral(ABC):
    """
    Base class for STM32 peripherals.

    Features:
    - Standard read/write interface with atomic set/clear support
    - IRQ callback mechanism
    - Register storage
    - Debug logging

    STM32 peripherals typically have three additional address regions
    for atomic bit operations:
    - Base + 0x0000: Normal read/write
    - Base + 0x0400: Bit set (write 1 to set bits)  [Some peripherals]
    - Base + 0x0800: Bit clear (write 1 to clear bits) [Some peripherals]
    """

    def __init__(self, name: str, base: int, size: int = 0x400, irq: int = -1):
        """
        Initialize STM32 peripheral.

        Args:
            name: Peripheral name (e.g., "GPIOA", "USART1")
            base: Base address
            size: Register region size (default 0x400 = 1KB)
            irq: IRQ number (-1 if no IRQ)
        """
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq
        self.regs: Dict[int, int] = {}
        self.log = logging.getLogger(f'STM32.{name}')
        self.irq_callback: Optional[Callable[[int, int], None]] = None

    def contains(self, addr: int) -> bool:
        """Check if address is within this peripheral's range."""
        return self.base <= addr < self.base + self.size

    def read(self, addr: int, size: int) -> Tuple[int, int]:
        """
        Read from peripheral.

        Args:
            addr: Absolute address
            size: Read size in bytes (1, 2, or 4)

        Returns:
            Tuple of (value, status)
        """
        offset = addr - self.base
        value = self._read_reg(offset, size)
        return (value, STATUS_OK)

    def write(self, addr: int, size: int, value: int) -> int:
        """
        Write to peripheral.

        Args:
            addr: Absolute address
            size: Write size in bytes (1, 2, or 4)
            value: Value to write

        Returns:
            Status code
        """
        offset = addr - self.base
        self._write_reg(offset, size, value)
        return STATUS_OK

    def _read_reg(self, offset: int, size: int) -> int:
        """Read from register offset. Override in subclasses."""
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        """Write to register offset. Override in subclasses."""
        self.regs[offset] = value

    def trigger_irq(self, level: int = 1):
        """Trigger interrupt."""
        if self.irq >= 0 and self.irq_callback:
            self.irq_callback(self.irq, level)

    def reset(self):
        """Reset peripheral to default state."""
        self.regs.clear()
        self._reset_registers()

    def _reset_registers(self):
        """Reset registers to default values. Override in subclasses."""
        pass


class STM32PeripheralSet:
    """
    Base class for STM32 peripheral sets.

    Manages a collection of peripherals for a specific STM32 device.
    """

    def __init__(self, name: str, cpu_freq: int = 8_000_000):
        """
        Initialize peripheral set.

        Args:
            name: Device name (e.g., "STM32F103", "STM32F405")
            cpu_freq: CPU frequency in Hz
        """
        self.name = name
        self.cpu_freq = cpu_freq
        self.log = logging.getLogger(f'STM32.{name}')
        self._peripherals: Dict[str, STM32Peripheral] = {}
        self.peripherals: list = []
        self.irq_callback: Optional[Callable[[int, int], None]] = None

    def add_peripheral(self, peripheral: STM32Peripheral):
        """Add a peripheral to the set."""
        self._peripherals[peripheral.name] = peripheral
        self.peripherals.append(peripheral)
        peripheral.irq_callback = self.irq_callback

    def find_peripheral(self, addr: int) -> Optional[STM32Peripheral]:
        """Find peripheral that contains the given address.

        Handles TrustZone secure aliases: addresses in 0x50000000-0x5FFFFFFF
        are mapped to 0x40000000-0x4FFFFFFF (non-secure peripheral region).
        """
        # First try the original address
        for p in self.peripherals:
            if p.contains(addr):
                return p

        # Try secure alias mapping (0x5xxxxxxx -> 0x4xxxxxxx)
        if 0x50000000 <= addr < 0x60000000:
            ns_addr = addr - 0x10000000
            for p in self.peripherals:
                if p.contains(ns_addr):
                    return p

        return None

    def _to_nonsecure(self, addr: int) -> int:
        """Convert secure alias to non-secure address if needed."""
        if 0x50000000 <= addr < 0x60000000:
            return addr - 0x10000000
        return addr

    def read(self, addr: int, size: int) -> Tuple[int, int]:
        """Read from peripheral address."""
        p = self.find_peripheral(addr)
        if p:
            # Only de-alias if peripheral doesn't directly contain the address
            # (i.e., it was found via the 0x5x->0x4x secure alias mapping)
            if not p.contains(addr):
                addr = self._to_nonsecure(addr)
            return p.read(addr, size)
        self.log.debug(f"Read from unmapped address 0x{addr:08X}")
        return (0, STATUS_OK)

    def write(self, addr: int, size: int, value: int) -> int:
        """Write to peripheral address."""
        p = self.find_peripheral(addr)
        if p:
            # Only de-alias if peripheral doesn't directly contain the address
            if not p.contains(addr):
                addr = self._to_nonsecure(addr)
            return p.write(addr, size, value)
        self.log.debug(f"Write to unmapped address 0x{addr:08X} = 0x{value:X}")
        return STATUS_OK

    def setup_irq_callback(self, callback: Callable[[int, int], None]):
        """Set IRQ callback for all peripherals."""
        self.irq_callback = callback
        for p in self.peripherals:
            p.irq_callback = callback

    def reset(self):
        """Reset all peripherals."""
        for p in self.peripherals:
            p.reset()

    def list_peripherals(self) -> list:
        """List all peripheral names."""
        return list(self._peripherals.keys())

    def __getattr__(self, name: str):
        """Allow accessing peripherals by name."""
        if name.startswith('_') or name in ('peripherals', 'log', 'name', 'cpu_freq'):
            raise AttributeError(name)
        if name in self._peripherals:
            return self._peripherals[name]
        raise AttributeError(f"No peripheral named '{name}'")
