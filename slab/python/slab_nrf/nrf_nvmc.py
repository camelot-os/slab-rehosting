"""
NRF NVMC - Non-Volatile Memory Controller

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional
from .nrf_base import NRFPeripheral


class NRFNVMC(NRFPeripheral):
    """NRF Non-Volatile Memory Controller (Flash programming)."""

    READY = 0x400
    READYNEXT = 0x408
    CONFIG = 0x504
    ERASEALL = 0x50C
    ERASEPAGEPARTIALCFG = 0x51C
    ICACHECNF = 0x540

    CONFIG_WEN = 1  # Write enable
    CONFIG_EEN = 2  # Erase enable

    def __init__(self, base: int = 0x4001E000):
        super().__init__("NVMC", base, 0x1000)

        self.config = 0
        self.icachecnf = 0
        self.flash_data: Optional[bytearray] = None
        self.page_size = 4096

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.READY:
            return 1  # Always ready
        elif offset == self.READYNEXT:
            return 1
        elif offset == self.CONFIG:
            return self.config
        elif offset == self.ICACHECNF:
            return self.icachecnf
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CONFIG:
            self.config = value & 0x3
        elif offset == self.ERASEALL:
            if value == 1 and (self.config & self.CONFIG_EEN):
                self._erase_all()
        elif offset == self.ICACHECNF:
            self.icachecnf = value

    def _erase_all(self):
        if self.flash_data:
            for i in range(len(self.flash_data)):
                self.flash_data[i] = 0xFF

    def erase_page(self, address: int):
        """Erase 4KB page."""
        if self.flash_data and (self.config & self.CONFIG_EEN):
            page_start = (address // self.page_size) * self.page_size
            for i in range(self.page_size):
                if page_start + i < len(self.flash_data):
                    self.flash_data[page_start + i] = 0xFF

    def write_word(self, address: int, value: int):
        """Write 32-bit word to flash."""
        if self.flash_data and (self.config & self.CONFIG_WEN):
            if address + 4 <= len(self.flash_data):
                for i in range(4):
                    self.flash_data[address + i] &= (value >> (i * 8)) & 0xFF
