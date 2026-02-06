"""
Peripheral Adapters

Thin wrappers that normalize the different peripheral interfaces
(STM32, NRF, NXP, RP2040) to a common interface expected by
BasePeripheralServer.

The server protocol expects:
  - read(addr, size, secure) -> (value, status)
  - write(addr, size, value, secure) -> status
  - contains(addr) -> bool
  - irq_callback: Callable[[irq_num, level], None]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List

from slab_cortex_m.base_server import STATUS_OK

log = logging.getLogger('Adapter')


class PeripheralSetAdapter:
    """Wraps any PeripheralSet to provide a uniform interface for the server.

    Handles the differences between STM32/RP2040 (return tuples) and
    NRF/NXP (return raw values) peripheral sets.
    """

    def __init__(self, peripheral_set, family: str = "auto"):
        self.pset = peripheral_set
        self.family = family if family != "auto" else self._detect_family()
        self._irq_callback: Optional[Callable] = None
        self._setup_irq_forwarding()

    def _detect_family(self) -> str:
        """Detect the peripheral family from the class hierarchy."""
        cls_name = type(self.pset).__name__
        if 'STM32' in cls_name:
            return 'stm32'
        elif 'NRF' in cls_name or 'nRF' in cls_name:
            return 'nrf'
        elif 'NXP' in cls_name or 'LPC' in cls_name or 'IMXRT' in cls_name:
            return 'nxp'
        elif 'RP20' in cls_name:
            return 'rp2040'
        return 'unknown'

    def _setup_irq_forwarding(self):
        """Wire IRQ callbacks from the peripheral set to our unified callback."""
        if self.family in ('stm32', 'rp2040'):
            # These use irq_callback(irq_num, level) -- same as server protocol
            if hasattr(self.pset, 'setup_irq_callback'):
                self.pset.setup_irq_callback(self._forward_irq)
            else:
                # Set on each peripheral directly
                for p in self._get_peripherals():
                    if hasattr(p, 'irq_callback'):
                        p.irq_callback = self._forward_irq
        elif self.family in ('nrf', 'nxp'):
            # These use on_irq(level) -- need to wrap with irq number
            for p in self._get_peripherals():
                if hasattr(p, 'on_irq') and hasattr(p, 'irq') and p.irq >= 0:
                    # Capture irq number in closure
                    irq_num = p.irq
                    p.on_irq = lambda level, n=irq_num: self._forward_irq(n, level)

    def _forward_irq(self, irq_num: int, level: int):
        """Forward IRQ to server callback."""
        if self._irq_callback:
            self._irq_callback(irq_num, level)

    @property
    def irq_callback(self):
        return self._irq_callback

    @irq_callback.setter
    def irq_callback(self, cb):
        self._irq_callback = cb

    def _get_peripherals(self) -> list:
        """Get the list of peripherals from the peripheral set."""
        pset = self.pset
        if hasattr(pset, 'peripherals'):
            p = pset.peripherals
            if isinstance(p, dict):
                return list(p.values())
            return list(p)
        return []

    def find_peripheral(self, addr: int):
        """Find peripheral containing address. Returns the adapted set itself
        since reads/writes go through the PeripheralSet level."""
        pset = self.pset
        if hasattr(pset, 'find_peripheral'):
            return pset.find_peripheral(addr)
        elif hasattr(pset, 'get_by_address'):
            return pset.get_by_address(addr)
        # Fallback: check each peripheral
        for p in self._get_peripherals():
            if hasattr(p, 'contains') and p.contains(addr):
                return p
        return None

    def read(self, addr: int, size: int, secure: bool = True):
        """Read with normalized return: (value, status)."""
        periph = self.find_peripheral(addr)
        if periph is None:
            return (0, STATUS_OK)

        if self.family in ('stm32',):
            # STM32 PeripheralSet.read() returns (value, status)
            return self.pset.read(addr, size)
        elif self.family in ('rp2040',):
            # RP2040 peripheral.read() returns (value, status)
            return periph.read(addr, size, secure)
        elif self.family in ('nrf', 'nxp'):
            # NRF/NXP return raw int
            try:
                value = self.pset.read(addr, size)
                return (value if isinstance(value, int) else 0, STATUS_OK)
            except Exception:
                return (0, STATUS_OK)
        else:
            # Unknown: try tuple first, fall back to int
            result = periph.read(addr, size)
            if isinstance(result, tuple):
                return result
            return (result, STATUS_OK)

    def write(self, addr: int, size: int, value: int, secure: bool = True):
        """Write with normalized return: status."""
        periph = self.find_peripheral(addr)
        if periph is None:
            return STATUS_OK

        if self.family in ('stm32',):
            return self.pset.write(addr, size, value)
        elif self.family in ('rp2040',):
            return periph.write(addr, size, value, secure)
        elif self.family in ('nrf', 'nxp'):
            try:
                self.pset.write(addr, size, value)
            except Exception:
                pass
            return STATUS_OK
        else:
            result = periph.write(addr, size, value)
            return result if isinstance(result, int) else STATUS_OK

    def contains(self, addr: int) -> bool:
        """Check if any peripheral handles this address."""
        return self.find_peripheral(addr) is not None

    @property
    def peripherals(self):
        """Access underlying peripherals list."""
        return self._get_peripherals()

    @property
    def name(self) -> str:
        """Name of the underlying peripheral set."""
        return getattr(self.pset, 'name', type(self.pset).__name__)
