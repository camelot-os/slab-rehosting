"""
Slab RP2040/RP2350 - Raspberry Pi Pico Support for Slab Security Analysis Framework

This package provides timing models, peripheral emulation, and security analysis
tools for the RP2040 and RP2350 microcontrollers (Raspberry Pi Pico / Pico 2).

Key Features:
- Dual Cortex-M0+/M33 or Hazard3 RISC-V timing model
- PIO (Programmable I/O) emulation
- Full GPIO, SIO, Timer, Clocks peripheral support
- USB bootloader mass storage emulation
- USBIP integration for host connectivity
- Support for both ARM and RISC-V architectures (RP2350)

References:
- RP2040 Datasheet: https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf
- RP2350 Datasheet: https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf
- SVD: /svd/data/RaspberryPi/rp2040.svd, rp2350.svd

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.2.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"

try:
    from .timing import (
        RP2040Timing,
        CortexM0PlusTiming,
        RP2040MemoryTiming,
    )
except ImportError:
    pass

from .peripherals import (
    PIOEmulator,
    PIOStateMachine,
    PIOInstruction,
)

from .rp2040_peripherals import (
    RP2040Peripheral,
    RP2040GPIO,
    RP2040Pads,
    RP2040SIO,
    RP2040Timer,
    RP2040Clocks,
    RP2040Resets,
    RP2040XOSC,
    RP2040PLL,
    RP2040Watchdog,
    RP2040PSM,
    RP2040PIO,
    RP2040PeripheralSet,
    RP2350PeripheralSet,
)

# Communication peripherals - IP block names (reusable)
from .rp2040_uart_spi_i2c import (
    PL011UART,       # ARM PrimeCell UART
    PrimeCellSSP,    # ARM PrimeCell SPI/SSI
    SynopsysDWI2C,   # Synopsys DesignWare I2C
    # Backward-compatible aliases
    RP2040UART,
    RP2040SPI,
    RP2040I2C,
)

# ADC, PWM, DMA
from .rp2040_adc_pwm_dma import (
    RP2040ADC,
    RP2040PWM,
    RP2040DMA,
)

# Miscellaneous peripherals
from .rp2040_misc import (
    RP2040RTC,
    RP2040ROSC,
    RP2040SYSINFO,
    RP2040SYSCFG,
    RP2040VREG,
    RP2040TBMAN,
    RP2040BUSCTRL,
    RP2040XIP,
    RP2040SSI,
    RP2040IOQSPI,
    RP2040PADSQSPI,
    RP2040USB,
    # Bootrom-compatible peripherals (detailed implementations)
    RP2040XOSC as RP2040XOSC_Bootrom,
    RP2040PLL as RP2040PLL_Bootrom,
    RP2040RESETS as RP2040RESETS_Bootrom,
    RP2040CLOCKS as RP2040CLOCKS_Bootrom,
    RP2040PSM as RP2040PSM_Bootrom,
    RP2040WATCHDOG as RP2040WATCHDOG_Bootrom,
)

# RP2350-specific peripherals
from .rp2350_peripherals import (
    RP2350SHA256,
    RP2350TRNG,
    RP2350OTP,
    RP2350OTPData,
    RP2350HSTX,
    RP2350HSTXFIFO,
    RP2350POWMAN,
    RP2350GlitchDetector,
    RP2350ACCESSCTRL,
    RP2350TICKS,
    RP2350QMI,
)

from .rp2040_usb_boot import (
    RP2040BootromUSB,
    RP2040BootromFAT,
    UF2Block,
    create_rp2040_bootloader,
    create_rp2350_bootloader,
    create_uf2_file,
)

from .rp2040_server import (
    RP2040Server,
    RP2040USBIPServer,
    RP2040_CONFIG,
    RP2350_ARM_CONFIG,
    RP2350_RISCV_CONFIG,
)

try:
    from .rp2350_timing import (
        RP2350Timing,
        CortexM33Timing,
        Hazard3Timing,
        RP2350MemoryTiming,
    )
except ImportError:
    pass

try:
    from .security import (
        TrustZoneModel,
        SAURegion,
        SAURegionType,
        SecureBootChain,
        OTPModel,
        BootStage,
        SecurityState,
    )
except ImportError:
    pass

__all__ = [
    "__version__",
    "__author__",
    # Timing
    "RP2040Timing",
    "CortexM0PlusTiming",
    "RP2040MemoryTiming",
    # PIO
    "PIOEmulator",
    "PIOStateMachine",
    "PIOInstruction",
    # Core Peripherals
    "RP2040Peripheral",
    "RP2040GPIO",
    "RP2040Pads",
    "RP2040SIO",
    "RP2040Timer",
    "RP2040Clocks",
    "RP2040Resets",
    "RP2040XOSC",
    "RP2040PLL",
    "RP2040Watchdog",
    "RP2040PSM",
    "RP2040PIO",
    "RP2040PeripheralSet",
    "RP2350PeripheralSet",
    # Communication - IP Blocks (reusable)
    "PL011UART",
    "PrimeCellSSP",
    "SynopsysDWI2C",
    # Communication - RP2040 aliases
    "RP2040UART",
    "RP2040SPI",
    "RP2040I2C",
    # ADC/PWM/DMA
    "RP2040ADC",
    "RP2040PWM",
    "RP2040DMA",
    # Misc Peripherals
    "RP2040RTC",
    "RP2040ROSC",
    "RP2040SYSINFO",
    "RP2040SYSCFG",
    "RP2040VREG",
    "RP2040TBMAN",
    "RP2040BUSCTRL",
    "RP2040XIP",
    "RP2040SSI",
    "RP2040IOQSPI",
    "RP2040PADSQSPI",
    "RP2040USB",
    # Bootrom-compatible peripherals
    "RP2040XOSC_Bootrom",
    "RP2040PLL_Bootrom",
    "RP2040RESETS_Bootrom",
    "RP2040CLOCKS_Bootrom",
    "RP2040PSM_Bootrom",
    "RP2040WATCHDOG_Bootrom",
    # RP2350-Specific
    "RP2350SHA256",
    "RP2350TRNG",
    "RP2350OTP",
    "RP2350OTPData",
    "RP2350HSTX",
    "RP2350HSTXFIFO",
    "RP2350POWMAN",
    "RP2350GlitchDetector",
    "RP2350ACCESSCTRL",
    "RP2350TICKS",
    "RP2350QMI",
    # USB Bootloader
    "RP2040BootromUSB",
    "RP2040BootromFAT",
    "UF2Block",
    "create_rp2040_bootloader",
    "create_rp2350_bootloader",
    "create_uf2_file",
    # Server
    "RP2040Server",
    "RP2040USBIPServer",
    "RP2040_CONFIG",
    "RP2350_ARM_CONFIG",
    "RP2350_RISCV_CONFIG",
    # RP2350 Timing
    "RP2350Timing",
    "CortexM33Timing",
    "Hazard3Timing",
    "RP2350MemoryTiming",
    # RP2350 Security
    "TrustZoneModel",
    "SAURegion",
    "SAURegionType",
    "SecureBootChain",
    "OTPModel",
    "BootStage",
    "SecurityState",
]
