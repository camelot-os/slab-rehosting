"""
NRF Base Peripheral Classes

Nordic peripherals have a unique architecture:
- Task/Event system (TASKS_xxx, EVENTS_xxx registers)
- EasyDMA for autonomous data transfers
- Shortcuts (automatic task triggers on events)
- PPI (Programmable Peripheral Interconnect)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Callable


STATUS_OK = 0
STATUS_ERROR = -1


class NRFPeripheral(ABC):
    """
    Base class for Nordic peripheral emulation.

    Nordic peripheral register layout:
        0x000-0x07C: TASKS (write 1 to trigger)
        0x080-0x0FC: SUBSCRIBE (for DPPI, nRF53)
        0x100-0x17C: EVENTS (read to check, write 0 to clear)
        0x180-0x1FC: PUBLISH (for DPPI, nRF53)
        0x200-0x2FC: SHORTS (automatic task on event)
        0x300-0x3FC: INTEN, INTENSET, INTENCLR
        0x400+:      Configuration registers
    """

    # Standard register offsets
    TASKS_BASE = 0x000
    SUBSCRIBE_BASE = 0x080  # nRF53 DPPI
    EVENTS_BASE = 0x100
    PUBLISH_BASE = 0x180    # nRF53 DPPI
    SHORTS = 0x200
    INTEN = 0x300
    INTENSET = 0x304
    INTENCLR = 0x308

    def __init__(self, name: str, base: int, size: int = 0x1000, irq: int = -1):
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq

        self.log = logging.getLogger(f"NRF.{name}")

        # Common state
        self.shorts = 0
        self.inten = 0
        self.events: Dict[int, int] = {}  # offset -> value

        # Generic register storage
        self.regs: Dict[int, int] = {}

        # Callbacks
        self.on_irq: Optional[Callable[[int], None]] = None

    def read(self, address: int, size: int) -> int:
        """Read from peripheral register."""
        offset = address - self.base
        if offset < 0 or offset >= self.size:
            return 0

        # Handle standard regions
        if self.EVENTS_BASE <= offset < self.EVENTS_BASE + 0x80:
            return self.events.get(offset, 0)
        elif offset == self.SHORTS:
            return self.shorts
        elif offset == self.INTEN:
            return self.inten
        elif offset == self.INTENSET:
            return self.inten
        elif offset == self.INTENCLR:
            return self.inten

        return self._read_reg(offset, size)

    def write(self, address: int, size: int, value: int):
        """Write to peripheral register."""
        offset = address - self.base
        if offset < 0 or offset >= self.size:
            return

        # Handle tasks (write 1 to trigger)
        if self.TASKS_BASE <= offset < self.TASKS_BASE + 0x80:
            if value == 1:
                self._handle_task(offset)
            return

        # Handle events (write 0 to clear)
        if self.EVENTS_BASE <= offset < self.EVENTS_BASE + 0x80:
            if value == 0:
                self.events[offset] = 0
            return

        # Handle standard registers
        if offset == self.SHORTS:
            self.shorts = value
        elif offset == self.INTENSET:
            self.inten |= value
        elif offset == self.INTENCLR:
            self.inten &= ~value
        else:
            self._write_reg(offset, size, value)

    @abstractmethod
    def _read_reg(self, offset: int, size: int) -> int:
        """Read peripheral-specific register."""
        pass

    @abstractmethod
    def _write_reg(self, offset: int, size: int, value: int):
        """Write peripheral-specific register."""
        pass

    def _handle_task(self, offset: int):
        """Handle task trigger. Override in subclass."""
        pass

    def set_event(self, event_offset: int):
        """Set an event and trigger interrupt if enabled."""
        self.events[event_offset] = 1

        # Calculate event index for interrupt check
        event_idx = (event_offset - self.EVENTS_BASE) // 4

        # Check if interrupt is enabled for this event
        if self.inten & (1 << event_idx):
            self.trigger_irq(1)

        # Check shortcuts
        self._check_shortcuts(event_offset)

    def _check_shortcuts(self, event_offset: int):
        """Check and execute shortcuts for this event."""
        # Override in subclass to handle specific shortcuts
        pass

    def trigger_irq(self, level: int):
        """Trigger interrupt to CPU."""
        if self.on_irq:
            self.on_irq(level)


class NRFPeripheralSet:
    """Collection of NRF peripherals for a specific device."""

    def __init__(self, device: str, log: logging.Logger = None):
        self.device = device
        self.log = log or logging.getLogger(f"NRF.{device}")
        self.peripherals: Dict[str, NRFPeripheral] = {}
        self._by_address: Dict[int, NRFPeripheral] = {}

    def add_peripheral(self, peripheral: NRFPeripheral):
        """Add a peripheral to the set."""
        self.peripherals[peripheral.name] = peripheral
        self._by_address[peripheral.base] = peripheral

    def get_by_address(self, address: int) -> Optional[NRFPeripheral]:
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
