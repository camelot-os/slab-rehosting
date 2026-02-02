"""
SLAB NRF - Nordic Semiconductor Peripheral Emulation

Comprehensive peripheral emulation for Nordic nRF microcontrollers:
- nRF52840 (Cortex-M4F) - BLE 5.0, 802.15.4, USB
- nRF5340 (Cortex-M33) - Dual core, BLE 5.2, TrustZone

Nordic peripherals use EasyDMA for efficient data transfer without
CPU intervention. The peripheral architecture differs significantly
from ARM standard IP blocks.

References:
- nRF52840 Product Specification v1.7
- nRF5340 Product Specification v1.3
- Nordic SDK / nrfx drivers

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"

# Base classes
from .nrf_base import (
    NRFPeripheral,
    NRFPeripheralSet,
    STATUS_OK,
    STATUS_ERROR,
)

# GPIO
from .nrf_gpio import (
    NRFGPIO,
    NRFGPIOTE,
)

# Communication
from .nrf_uart import (
    NRFUARTE,       # EasyDMA UART
)

from .nrf_spi import (
    NRFSPIM,        # EasyDMA SPI Master
    NRFSPIS,        # EasyDMA SPI Slave
)

from .nrf_twi import (
    NRFTWIM,        # EasyDMA I2C Master
    NRFTWIS,        # EasyDMA I2C Slave
)

# Timers
from .nrf_timer import (
    NRFTIMER,       # General purpose timer
    NRFRTC,         # Real-time counter
)

# Analog
from .nrf_saadc import (
    NRFSAADC,       # Successive approximation ADC
)

# Memory/Flash
from .nrf_nvmc import (
    NRFNVMC,        # Non-volatile memory controller
)

from .nrf_qspi import (
    NRFQSPI,        # Quad SPI with EasyDMA
)

# Power/Clock
from .nrf_power import (
    NRFPOWER,       # Power management
    NRFCLOCK,       # Clock control
)

# Security
from .nrf_rng import (
    NRFRNG,         # Random number generator
)

from .nrf_crypto import (
    NRFECB,         # AES ECB
    NRFCCM,         # AES CCM
)

# Radio
from .nrf_radio import (
    NRFRADIO,       # 2.4GHz radio
)

# Peripheral sets
from .nrf52840 import (
    NRF52840PeripheralSet,
)

from .nrf5340 import (
    NRF5340AppPeripheralSet,
    NRF5340NetPeripheralSet,
)

__all__ = [
    # Version
    "__version__",
    "__author__",
    # Base
    "NRFPeripheral",
    "NRFPeripheralSet",
    "STATUS_OK",
    "STATUS_ERROR",
    # GPIO
    "NRFGPIO",
    "NRFGPIOTE",
    # UART
    "NRFUARTE",
    # SPI
    "NRFSPIM",
    "NRFSPIS",
    # I2C/TWI
    "NRFTWIM",
    "NRFTWIS",
    # Timers
    "NRFTIMER",
    "NRFRTC",
    # Analog
    "NRFSAADC",
    # Memory
    "NRFNVMC",
    "NRFQSPI",
    # Power/Clock
    "NRFPOWER",
    "NRFCLOCK",
    # Security
    "NRFRNG",
    "NRFECB",
    "NRFCCM",
    # Radio
    "NRFRADIO",
    # Peripheral sets
    "NRF52840PeripheralSet",
    "NRF5340AppPeripheralSet",
    "NRF5340NetPeripheralSet",
]
