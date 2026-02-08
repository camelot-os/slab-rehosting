"""
NRF RNG - True Random Number Generator

Uses secrets module for cryptographically secure random numbers.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import secrets
from .nrf_base import NRFPeripheral


class NRFRNG(NRFPeripheral):
    """NRF True Random Number Generator."""

    TASKS_START = 0x000
    TASKS_STOP = 0x004
    EVENTS_VALRDY = 0x100

    CONFIG = 0x504
    VALUE = 0x508

    def __init__(self, base: int = 0x4000D000):
        super().__init__("RNG", base, 0x1000, irq=13)

        self.config = 0  # Bias correction enable
        self.running = False
        self._value = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CONFIG:
            return self.config
        elif offset == self.VALUE:
            return self._value
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CONFIG:
            self.config = value & 1

    def _handle_task(self, offset: int):
        if offset == self.TASKS_START:
            self.running = True
            self._generate_value()
        elif offset == self.TASKS_STOP:
            self.running = False

    def _generate_value(self):
        """Generate new random value using secrets module."""
        self._value = secrets.randbelow(256)
        self.set_event(self.EVENTS_VALRDY)

    def tick(self):
        """Generate values continuously when running."""
        if self.running:
            self._generate_value()

    # Convenience method
    def get_random_byte(self) -> int:
        """Get a single random byte (convenience method)."""
        self._generate_value()
        return self._value
