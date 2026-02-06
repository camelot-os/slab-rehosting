"""
Board Configuration

Defines the board-level configuration that ties together an MCU/SoC
peripheral set with external devices (LEDs, SPI flash, I2C EEPROM, etc.)
and wiring information.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path

log = logging.getLogger('Board')

# Try YAML support
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class ExternalDevice:
    """An external device wired to the board (LED, flash, EEPROM, etc.)."""
    type: str          # "LED", "W25Q128", "24C256", "ILI9341", etc.
    bus: str           # "GPIOA", "SPI1", "I2C1", etc.
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class USBConfig:
    """USB controller configuration."""
    type: str          # "dwc2_otg_fs", "dwc2_otg_hs", "nrf_usbd", etc.
    base: int = 0
    irq: int = -1


@dataclass
class BoardConfig:
    """Complete board configuration."""
    name: str                                    # "STM32F405_HelloBlink"
    mcu: str                                     # "STM32F405", "nRF52840", "RP2040"
    clock: int = 0                               # 0 = use SoC default
    external_devices: List[ExternalDevice] = field(default_factory=list)
    usb: Optional[USBConfig] = None
    qemu_cpu: str = ""                           # Override QEMU CPU type
    qemu_extra: Dict[str, str] = field(default_factory=dict)  # Extra QEMU -M props


# Known MCU -> (package, PeripheralSet class, default QEMU CPU, default clock)
MCU_REGISTRY: Dict[str, tuple] = {
    # STM32
    "STM32F030":  ("slab_stm32", "STM32F0xxPeripheralSet",  "cortex-m0",  48_000_000),
    "STM32F103":  ("slab_stm32", "STM32F103PeripheralSet",  "cortex-m3",  72_000_000),
    "STM32F405":  ("slab_stm32", "STM32F405PeripheralSet",  "cortex-m4", 168_000_000),
    "STM32F407":  ("slab_stm32", "STM32F407PeripheralSet",  "cortex-m4", 168_000_000),
    "STM32F439":  ("slab_stm32", "STM32F439PeripheralSet",  "cortex-m4", 180_000_000),
    "STM32L433":  ("slab_stm32", "STM32L4xxPeripheralSet",  "cortex-m4",  80_000_000),
    "STM32H563":  ("slab_stm32", "STM32H563PeripheralSet",  "cortex-m33", 250_000_000),
    "STM32H745":  ("slab_stm32", "STM32H7xxPeripheralSet",  "cortex-m7", 480_000_000),
    "STM32U585":  ("slab_stm32", "STM32U585PeripheralSet",  "cortex-m33", 160_000_000),
    "STM32WB55":  ("slab_stm32", "STM32WB55PeripheralSet",  "cortex-m4",  64_000_000),
    "STM32WB35":  ("slab_stm32", "STM32WB35PeripheralSet",  "cortex-m4",  64_000_000),
    # Nordic
    "nRF52840":   ("slab_nrf",   "NRF52840PeripheralSet",   "cortex-m4",  64_000_000),
    "nRF5340":    ("slab_nrf",   "NRF5340AppPeripheralSet",  "cortex-m33", 128_000_000),
    # NXP
    "LPC55S69":   ("slab_nxp",   "LPC55S69PeripheralSet",   "cortex-m33", 150_000_000),
    "IMXRT1060":  ("slab_nxp",   "IMXRT1060PeripheralSet",  "cortex-m7", 600_000_000),
    # Raspberry Pi
    "RP2040":     ("slab_rp2040", "RP2040PeripheralSet",    "cortex-m0", 125_000_000),
    "RP2350":     ("slab_rp2040", "RP2350PeripheralSet",    "cortex-m33", 150_000_000),
}


def load_board_config(path: str) -> BoardConfig:
    """Load board configuration from YAML or JSON file."""
    p = Path(path)
    text = p.read_text()

    if p.suffix in ('.yaml', '.yml'):
        if not HAS_YAML:
            raise ImportError("PyYAML required for .yaml board configs: pip install pyyaml")
        data = yaml.safe_load(text)
    elif p.suffix == '.json':
        data = json.loads(text)
    else:
        raise ValueError(f"Unsupported config format: {p.suffix}")

    # Parse external devices
    devices = []
    for d in data.get('external_devices', []):
        devices.append(ExternalDevice(
            type=d['type'],
            bus=d['bus'],
            params=d.get('params', {}),
        ))

    # Parse USB config
    usb = None
    if 'usb' in data:
        u = data['usb']
        usb = USBConfig(
            type=u['type'],
            base=int(str(u.get('base', 0)), 0),
            irq=u.get('irq', -1),
        )

    return BoardConfig(
        name=data['name'],
        mcu=data['mcu'],
        clock=data.get('clock', 0),
        external_devices=devices,
        usb=usb,
        qemu_cpu=data.get('qemu_cpu', ''),
        qemu_extra=data.get('qemu_extra', {}),
    )


def create_peripheral_set(config: BoardConfig):
    """Instantiate the MCU peripheral set from board config.

    Returns the peripheral set instance (STM32PeripheralSet, NRFPeripheralSet, etc.)
    """
    mcu = config.mcu
    if mcu not in MCU_REGISTRY:
        raise ValueError(
            f"Unknown MCU '{mcu}'. Available: {', '.join(sorted(MCU_REGISTRY))}")

    pkg_name, cls_name, default_cpu, default_clock = MCU_REGISTRY[mcu]

    # Import the package and class dynamically
    import importlib
    pkg = importlib.import_module(pkg_name)
    cls = getattr(pkg, cls_name)

    pset = cls()
    log.info(f"Created {mcu} peripheral set ({cls_name}) with "
             f"{len(pset.peripherals)} peripherals")
    return pset


def get_qemu_cpu(config: BoardConfig) -> str:
    """Get the QEMU CPU type for this board."""
    if config.qemu_cpu:
        return config.qemu_cpu
    mcu = config.mcu
    if mcu in MCU_REGISTRY:
        return MCU_REGISTRY[mcu][2]
    return "cortex-m4"


def get_default_clock(config: BoardConfig) -> int:
    """Get the default clock frequency for this board."""
    if config.clock > 0:
        return config.clock
    mcu = config.mcu
    if mcu in MCU_REGISTRY:
        return MCU_REGISTRY[mcu][3]
    return 168_000_000
