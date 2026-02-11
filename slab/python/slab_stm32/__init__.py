"""
SLAB STM32 - STM32 Microcontroller Peripheral Emulation

Comprehensive peripheral emulation for STM32 microcontroller families:
- STM32F1xx (Cortex-M3) - F103 "Blue Pill"
- STM32F4xx (Cortex-M4F) - F405, F407, F429, F439
- STM32L4xx (Cortex-M4F) - L476 (low power)
- STM32H7xx (Cortex-M7) - H743, H753, H750
- STM32WBxx (Cortex-M4+M0+) - WB55 (BLE/802.15.4)
- STM32U5xx (Cortex-M33) - U5A5 (TrustZone)

All peripherals use standard STM32 IP blocks where possible, making
the code reusable across multiple device families.

References:
- STM32 Reference Manuals (RM0008, RM0090, RM0351, RM0433, RM0434, RM0456)
- STM32 Programming Manuals (PM0056, PM0214)
- STM32CubeMX / HAL drivers

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"

# Base classes
from .stm32_base import (
    STM32Peripheral,
    STATUS_OK,
    STATUS_ERROR,
)

# GPIO (different for F1 vs F2/F4/L4/H7)
from .stm32_gpio import (
    STM32GPIOv1,      # F1xx style (CRL/CRH)
    STM32GPIOv2,      # F2/F4/L4/H7 style (MODER/OTYPER/OSPEEDR)
    STM32EXTI,        # External interrupt controller
    # Aliases
    STM32F1GPIO,
    STM32F4GPIO,
)

# Communication peripherals
from .stm32_usart import (
    STM32USARTv1,     # F1/F4 style USART
    STM32USARTv2,     # L4/H7 style USART
    STM32LPUART,      # Low-power UART (L4/H7)
)

from .stm32_spi import (
    STM32SPIv1,       # F1/F4 style SPI
    STM32SPIv2,       # H7 style SPI (with FIFO)
)

from .stm32_i2c import (
    STM32I2Cv1,       # F1/F4 style I2C
    STM32I2Cv2,       # L4/H7 style I2C
)

# System peripherals
from .stm32_rcc import (
    STM32RCCv1,       # F1xx RCC
    STM32RCCv2,       # F4xx RCC
    STM32RCCv3,       # L4xx RCC
    STM32RCCv4,       # H7xx RCC
)

from .stm32_pwr import (
    STM32PWRv1,       # F1/F4 PWR
    STM32PWRv2,       # L4/U5 PWR
    STM32PWRv3,       # H7 PWR (with SMPS)
)

from .stm32_flash import (
    STM32FLASHv1,     # F1 Flash interface
    STM32FLASHv2,     # F4 Flash interface
    STM32FLASHv3,     # L4/H7 Flash interface
)

# Timers
from .stm32_timers import (
    STM32BasicTimer,  # TIM6/TIM7
    STM32GeneralTimer,  # TIM2/3/4/5
    STM32AdvancedTimer,  # TIM1/TIM8
    STM32LPTIM,       # Low-power timer
)

# ADC/DAC
from .stm32_adc import (
    STM32ADCv1,       # F1 ADC (12-bit)
    STM32ADCv2,       # F4 ADC (12-bit, triple)
    STM32ADCv3,       # L4/H7 ADC (16-bit)
)

from .stm32_dac import (
    STM32DAC,         # DAC peripheral
)

# DMA
from .stm32_dma import (
    STM32DMAv1,       # F1 DMA (channels)
    STM32DMAv2,       # F4/L4/H7 DMA (streams)
    STM32BDMA,        # H7 BDMA
    STM32MDMA,        # H7 MDMA
)

# Miscellaneous
from .stm32_misc import (
    STM32SYSCFG,      # System configuration
    STM32IWDG,        # Independent watchdog
    STM32WWDG,        # Window watchdog
    STM32RTC,         # Real-time clock
    STM32CRC,         # CRC calculator
    STM32RNG,         # Random number generator
    STM32DBG,         # Debug support
    STM32ICACHE,      # Instruction cache (H5)
)

# USB
from .stm32_usb_device import (
    STM32USBDevice,   # F1xx USB Device (not OTG)
)

# Peripheral sets by family
from .stm32f0xx import (
    STM32F042PeripheralSet,
    STM32F072PeripheralSet,
    STM32F0xxPeripheralSet,
    create_ledger_nano_s_mcu,
)

from .stm32f1xx import (
    STM32F103PeripheralSet,
    STM32F1xxPeripheralSet,
)

from .stm32f4xx import (
    STM32F405PeripheralSet,
    STM32F407PeripheralSet,
    STM32F411PeripheralSet,
    STM32F429PeripheralSet,
    STM32F439PeripheralSet,
    STM32F4xxPeripheralSet,
)

# F4 crypto peripherals
from .stm32_cryp import STM32F4CRYP
from .stm32_hash import STM32F4HASH

from .stm32l4xx import (
    STM32L476PeripheralSet,
    STM32L4xxPeripheralSet,
)

from .stm32h7xx import (
    STM32H743PeripheralSet,
    STM32H753PeripheralSet,
    STM32H750PeripheralSet,
    STM32H7xxPeripheralSet,
)

from .stm32h5xx import (
    STM32H5xxPeripheralSet,
    STM32H563PeripheralSet,
)

from .stm32wbxx import (
    STM32WB55PeripheralSet,
    STM32WB35PeripheralSet,
    STM32WBxxPeripheralSet,
    # WB-specific peripherals
    STM32IPCC,        # Inter-processor communication
    STM32HSEM,        # Hardware semaphore
    STM32PKA,         # Public key accelerator
    STM32AES,         # AES hardware accelerator
)

from .stm32u5xx import (
    STM32U5A5PeripheralSet,
    STM32U575PeripheralSet,
    STM32U585PeripheralSet,
    STM32U5xxPeripheralSet,
    # U5-specific peripherals (TrustZone)
    STM32GTZC,        # Global TrustZone controller
    STM32MPCBB,       # Memory protection block-based
    STM32TAMP,        # Tamper and backup
    STM32SAES,        # Secure AES
    STM32HASH,        # HASH processor
)

__all__ = [
    # Version
    "__version__",
    "__author__",
    # Base
    "STM32Peripheral",
    "STATUS_OK",
    "STATUS_ERROR",
    # GPIO
    "STM32GPIOv1",
    "STM32GPIOv2",
    "STM32F1GPIO",
    "STM32F4GPIO",
    "STM32EXTI",
    # USART
    "STM32USARTv1",
    "STM32USARTv2",
    "STM32LPUART",
    # SPI
    "STM32SPIv1",
    "STM32SPIv2",
    # I2C
    "STM32I2Cv1",
    "STM32I2Cv2",
    # RCC
    "STM32RCCv1",
    "STM32RCCv2",
    "STM32RCCv3",
    "STM32RCCv4",
    # PWR
    "STM32PWRv1",
    "STM32PWRv2",
    "STM32PWRv3",
    # Flash
    "STM32FLASHv1",
    "STM32FLASHv2",
    "STM32FLASHv3",
    # Timers
    "STM32BasicTimer",
    "STM32GeneralTimer",
    "STM32AdvancedTimer",
    "STM32LPTIM",
    # ADC/DAC
    "STM32ADCv1",
    "STM32ADCv2",
    "STM32ADCv3",
    "STM32DAC",
    # DMA
    "STM32DMAv1",
    "STM32DMAv2",
    "STM32BDMA",
    "STM32MDMA",
    # Misc
    "STM32SYSCFG",
    "STM32IWDG",
    "STM32WWDG",
    "STM32RTC",
    "STM32CRC",
    "STM32RNG",
    "STM32DBG",
    "STM32ICACHE",
    # USB
    "STM32USBDevice",
    # F0xx (Ledger Nano S MCU)
    "STM32F042PeripheralSet",
    "STM32F072PeripheralSet",
    "STM32F0xxPeripheralSet",
    "create_ledger_nano_s_mcu",
    # F1xx
    "STM32F103PeripheralSet",
    "STM32F1xxPeripheralSet",
    # F4xx
    "STM32F405PeripheralSet",
    "STM32F407PeripheralSet",
    "STM32F411PeripheralSet",
    "STM32F429PeripheralSet",
    "STM32F439PeripheralSet",
    "STM32F4xxPeripheralSet",
    "STM32F4CRYP",
    "STM32F4HASH",
    # L4xx
    "STM32L476PeripheralSet",
    "STM32L4xxPeripheralSet",
    # H7xx
    "STM32H743PeripheralSet",
    "STM32H753PeripheralSet",
    "STM32H750PeripheralSet",
    "STM32H7xxPeripheralSet",
    # H5xx (TrustZone)
    "STM32H5xxPeripheralSet",
    "STM32H563PeripheralSet",
    # WBxx (Wireless)
    "STM32WB55PeripheralSet",
    "STM32WB35PeripheralSet",
    "STM32WBxxPeripheralSet",
    "STM32IPCC",
    "STM32HSEM",
    "STM32PKA",
    "STM32AES",
    # U5xx (TrustZone)
    "STM32U5A5PeripheralSet",
    "STM32U575PeripheralSet",
    "STM32U585PeripheralSet",
    "STM32U5xxPeripheralSet",
    "STM32GTZC",
    "STM32MPCBB",
    "STM32TAMP",
    "STM32SAES",
    "STM32HASH",
]
