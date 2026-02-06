"""
Board Builder

Factory that takes a BoardConfig and produces an assembled board:
peripheral set (adapted) + external devices (wired).

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional

from slab_cortex_m.board import (
    BoardConfig, ExternalDevice, create_peripheral_set,
    get_qemu_cpu, get_default_clock,
)
from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

log = logging.getLogger('BoardBuilder')


class Board:
    """An assembled board: adapted peripheral set + external devices."""

    def __init__(self, config: BoardConfig, adapter: PeripheralSetAdapter):
        self.config = config
        self.adapter = adapter
        self.external_devices = []
        self.name = config.name
        self.qemu_cpu = get_qemu_cpu(config)
        self.clock = get_default_clock(config)

    def find_peripheral(self, addr: int):
        return self.adapter.find_peripheral(addr)

    def read(self, addr: int, size: int, secure: bool = True):
        return self.adapter.read(addr, size, secure)

    def write(self, addr: int, size: int, value: int, secure: bool = True):
        return self.adapter.write(addr, size, value, secure)

    def contains(self, addr: int) -> bool:
        return self.adapter.contains(addr)

    @property
    def irq_callback(self):
        return self.adapter.irq_callback

    @irq_callback.setter
    def irq_callback(self, cb):
        self.adapter.irq_callback = cb


def _create_external_device(device_cfg: ExternalDevice):
    """Create a virtual external device from config."""
    dtype = device_cfg.type.upper()

    if dtype == 'LED':
        # LED is observation-only, no device object needed
        log.info(f"LED on {device_cfg.bus} pin {device_cfg.params.get('pin', 0)}")
        return None

    elif dtype in ('W25Q128', 'W25Q64', 'W25Q32', 'W25Q16'):
        from slab_cortex_m.virtual_components import W25QxxFlash
        flash = W25QxxFlash(model=dtype)
        log.info(f"Created {dtype} flash on {device_cfg.bus}")
        return flash

    elif dtype in ('24C256', '24C512', '24C64', '24C32'):
        from slab_cortex_m.virtual_components import EEPROM_24Cxx
        eeprom = EEPROM_24Cxx(
            model=dtype,
            address=device_cfg.params.get('address', 0x50),
        )
        log.info(f"Created {dtype} EEPROM on {device_cfg.bus} "
                 f"@ 0x{eeprom.address:02X}")
        return eeprom

    else:
        log.warning(f"Unknown external device type: {device_cfg.type}")
        return None


def _wire_device(board: Board, device_cfg: ExternalDevice, device):
    """Wire an external device to the appropriate bus peripheral."""
    if device is None:
        return

    bus_name = device_cfg.bus
    # Find the bus peripheral in the adapted set
    for p in board.adapter.peripherals:
        if hasattr(p, 'name') and p.name == bus_name:
            dtype = device_cfg.type.upper()

            if dtype.startswith('W25Q'):
                # SPI flash: wire transfer callback
                if hasattr(p, 'transfer_callback'):
                    p.transfer_callback = device.transfer
                    log.info(f"Wired {dtype} to {bus_name}.transfer_callback")
                elif hasattr(p, 'set_slave_device'):
                    p.set_slave_device(device)
                    log.info(f"Wired {dtype} to {bus_name} as slave")

            elif dtype.startswith('24C'):
                # I2C EEPROM: add to I2C bus
                if hasattr(p, 'add_slave'):
                    p.add_slave(device)
                    log.info(f"Wired {dtype} to {bus_name} bus")
                elif hasattr(p, 'slave_devices'):
                    p.slave_devices.append(device)
                    log.info(f"Added {dtype} to {bus_name}.slave_devices")

            return

    log.warning(f"Bus peripheral '{bus_name}' not found for {device_cfg.type}")


def build_board(config: BoardConfig) -> Board:
    """Build a complete board from configuration.

    1. Create MCU peripheral set
    2. Wrap in PeripheralSetAdapter
    3. Create and wire external devices
    """
    # Create peripheral set
    pset = create_peripheral_set(config)

    # Wrap in adapter
    adapter = PeripheralSetAdapter(pset)
    board = Board(config, adapter)

    # Create and wire external devices
    for dev_cfg in config.external_devices:
        device = _create_external_device(dev_cfg)
        if device:
            board.external_devices.append(device)
            _wire_device(board, dev_cfg, device)

    log.info(f"Board '{config.name}' ready: {len(adapter.peripherals)} peripherals, "
             f"{len(board.external_devices)} external devices")

    return board
