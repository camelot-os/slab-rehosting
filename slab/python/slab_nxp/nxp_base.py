"""
NXP Base Peripheral Classes

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Callable


STATUS_OK = 0
STATUS_ERROR = -1


class NXPPeripheral(ABC):
    """Base class for NXP peripheral emulation."""

    def __init__(self, name: str, base: int, size: int = 0x1000, irq: int = -1):
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq

        self.log = logging.getLogger(f"NXP.{name}")
        self.regs: Dict[int, int] = {}

        # IRQ callback
        self.on_irq: Optional[Callable[[int], None]] = None

    def read(self, address: int, size: int) -> int:
        """Read from peripheral register."""
        offset = address - self.base
        if offset < 0 or offset >= self.size:
            return 0
        return self._read_reg(offset, size)

    def write(self, address: int, size: int, value: int):
        """Write to peripheral register."""
        offset = address - self.base
        if offset < 0 or offset >= self.size:
            return
        self._write_reg(offset, size, value)

    @abstractmethod
    def _read_reg(self, offset: int, size: int) -> int:
        """Read peripheral-specific register."""
        pass

    @abstractmethod
    def _write_reg(self, offset: int, size: int, value: int):
        """Write peripheral-specific register."""
        pass

    def trigger_irq(self, level: int):
        """Trigger interrupt to CPU."""
        if self.on_irq:
            self.on_irq(level)


class NXPPeripheralSet:
    """Collection of NXP peripherals for a specific device."""

    def __init__(self, device: str, log: logging.Logger = None):
        self.device = device
        self.log = log or logging.getLogger(f"NXP.{device}")
        self.peripherals: Dict[str, NXPPeripheral] = {}
        self._by_address: Dict[int, NXPPeripheral] = {}

    def add_peripheral(self, peripheral: NXPPeripheral):
        """Add a peripheral to the set."""
        self.peripherals[peripheral.name] = peripheral
        self._by_address[peripheral.base] = peripheral

    def get_by_address(self, address: int) -> Optional[NXPPeripheral]:
        """Find peripheral by address."""
        for base, periph in self._by_address.items():
            if base <= address < base + periph.size:
                return periph
        return None

    def read(self, address: int, size: int) -> int:
        """Read from any peripheral."""
        periph = self.get_by_address(address)
        if periph:
            return periph.read(address, size)
        return 0

    def write(self, address: int, size: int, value: int):
        """Write to any peripheral."""
        periph = self.get_by_address(address)
        if periph:
            periph.write(address, size, value)

    def list_peripherals(self) -> List[str]:
        """List all peripheral names."""
        return list(self.peripherals.keys())
