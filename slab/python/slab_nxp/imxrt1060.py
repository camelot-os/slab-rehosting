"""
i.MX RT1060 Peripheral Set

Features:
- Cortex-M7 @ 600 MHz
- 1MB on-chip SRAM
- FlexRAM (TCM/OCRAM configurable)
- LCD controller
- Camera interface
- Ethernet MAC
- USB OTG HS x2

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from .nxp_base import NXPPeripheralSet
from .imxrt_lpuart import IMXRTLpuart
from .imxrt_lpspi import IMXRTLpspi
from .imxrt_lpi2c import IMXRTLpi2c
from .imxrt_gpio import IMXRTGPIO
from .imxrt_gpt import IMXRTGPT, IMXRTPIT
from .imxrt_adc import IMXRTADC


class IMXRT1060PeripheralSet(NXPPeripheralSet):
    """
    i.MX RT1060 peripheral set.

    Memory Map:
        0x40000000 - AIPS-1 (configuration)
        0x40080000 - LPUART1
        0x40084000 - LPUART2
        0x40088000 - LPUART3
        0x4008C000 - LPUART4
        0x40090000 - LPUART5
        0x40094000 - LPUART6
        0x40098000 - LPUART7
        0x4009C000 - LPUART8
        0x40034000 - LPSPI1
        0x40038000 - LPSPI2
        0x4003C000 - LPSPI3
        0x40040000 - LPSPI4
        0x403F0000 - LPI2C1
        0x403F4000 - LPI2C2
        0x403F8000 - LPI2C3
        0x403FC000 - LPI2C4
        0x401C4000 - GPIO1
        0x401C8000 - GPIO2
        0x401CC000 - GPIO3
        0x401D0000 - GPIO4
        0x400C0000 - GPIO5
        0x42000000 - GPIO6-9 (fast)
        0x400EC000 - GPT1
        0x400F0000 - GPT2
        0x40084000 - PIT
        0x400C8000 - ADC1
        0x400CC000 - ADC2
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__("IMXRT1060", log)

        self._create_uart()
        self._create_spi()
        self._create_i2c()
        self._create_gpio()
        self._create_timers()
        self._create_analog()

    def _create_uart(self):
        """Create LPUART peripherals."""
        uart_bases = [
            0x40080000,  # LPUART1
            0x40084000,  # LPUART2
            0x40088000,  # LPUART3
            0x4008C000,  # LPUART4
            0x40090000,  # LPUART5
            0x40094000,  # LPUART6
            0x40098000,  # LPUART7
            0x4009C000,  # LPUART8
        ]

        for i, base in enumerate(uart_bases):
            uart = IMXRTLpuart(index=i + 1, base=base)
            setattr(self, f"lpuart{i + 1}", uart)
            self.add_peripheral(uart)

    def _create_spi(self):
        """Create LPSPI peripherals."""
        spi_bases = [
            0x40034000,  # LPSPI1
            0x40038000,  # LPSPI2
            0x4003C000,  # LPSPI3
            0x40040000,  # LPSPI4
        ]

        for i, base in enumerate(spi_bases):
            spi = IMXRTLpspi(index=i + 1, base=base)
            setattr(self, f"lpspi{i + 1}", spi)
            self.add_peripheral(spi)

    def _create_i2c(self):
        """Create LPI2C peripherals."""
        i2c_bases = [
            0x403F0000,  # LPI2C1
            0x403F4000,  # LPI2C2
            0x403F8000,  # LPI2C3
            0x403FC000,  # LPI2C4
        ]

        for i, base in enumerate(i2c_bases):
            i2c = IMXRTLpi2c(index=i + 1, base=base)
            setattr(self, f"lpi2c{i + 1}", i2c)
            self.add_peripheral(i2c)

    def _create_gpio(self):
        """Create GPIO peripherals."""
        # Standard GPIO ports
        gpio_bases = [
            0x401C4000,  # GPIO1
            0x401C8000,  # GPIO2
            0x401CC000,  # GPIO3
            0x401D0000,  # GPIO4
            0x400C0000,  # GPIO5
        ]

        for i, base in enumerate(gpio_bases):
            gpio = IMXRTGPIO(port=i + 1, base=base)
            setattr(self, f"gpio{i + 1}", gpio)
            self.add_peripheral(gpio)

        # Fast GPIO (GPIO6-9 at 0x42000000)
        fast_gpio_bases = [
            0x42000000,  # GPIO6
            0x42004000,  # GPIO7
            0x42008000,  # GPIO8
            0x4200C000,  # GPIO9
        ]

        for i, base in enumerate(fast_gpio_bases):
            gpio = IMXRTGPIO(port=i + 6, base=base)
            setattr(self, f"gpio{i + 6}", gpio)
            self.add_peripheral(gpio)

    def _create_timers(self):
        """Create timer peripherals."""
        # GPT timers
        self.gpt1 = IMXRTGPT(index=1, base=0x400EC000)
        self.gpt2 = IMXRTGPT(index=2, base=0x400F0000)
        self.add_peripheral(self.gpt1)
        self.add_peripheral(self.gpt2)

        # PIT
        self.pit = IMXRTPIT(base=0x40084000)
        self.add_peripheral(self.pit)

    def _create_analog(self):
        """Create analog peripherals."""
        self.adc1 = IMXRTADC(index=1, base=0x400C8000)
        self.adc2 = IMXRTADC(index=2, base=0x400CC000)
        self.add_peripheral(self.adc1)
        self.add_peripheral(self.adc2)
