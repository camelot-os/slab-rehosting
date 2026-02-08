"""
LPC55S69 Peripheral Set

Features:
- Dual Cortex-M33 @ 150 MHz with TrustZone
- 640KB Flash, 320KB SRAM
- CASPER crypto accelerator
- PUF for secure key storage
- USB HS with PHY

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from .nxp_base import NXPPeripheralSet
from .lpc_flexcomm import LPCFlexComm, LPCFlexCommUSART, LPCFlexCommSPI, LPCFlexCommI2C
from .lpc_gpio import LPCGPIO, LPCPINT
from .lpc_ctimer import LPCCTimer
from .lpc_adc import LPCADC
from .lpc_crypto import LPCCASPER, LPCHASHCRYPT, LPCPUF


class LPC55S69PeripheralSet(NXPPeripheralSet):
    """
    LPC55S69 peripheral set.

    Memory Map:
        0x40000000 - SYSCON
        0x40001000 - IOCON
        0x40003000 - GINT0
        0x40004000 - PINT
        0x40006000 - INPUTMUX
        0x40008000 - CTIMER0
        0x40009000 - CTIMER1
        0x4000A000 - CTIMER2
        0x4000B000 - CTIMER3
        0x4000C000 - CTIMER4
        0x40020000 - UTICK
        0x40021000 - WWDT
        0x40022000 - MRT
        0x40034000 - RTC
        0x40035000 - OSTIMER
        0x40086000 - FLEXCOMM0 (USART/SPI/I2C)
        0x40087000 - FLEXCOMM1
        0x40088000 - FLEXCOMM2
        0x40089000 - FLEXCOMM3
        0x4008A000 - FLEXCOMM4
        0x40096000 - FLEXCOMM5
        0x40097000 - FLEXCOMM6
        0x40098000 - FLEXCOMM7
        0x4009F000 - FLEXCOMM8 (HS SPI)
        0x400A0000 - ADC0
        0x400A4000 - HASHCRYPT
        0x400A5000 - CASPER
        0x4003B000 - PUF
        0x40100000 - USB1
        0x50000000 - GPIO P0
        0x50001000 - GPIO P1
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__("LPC55S69", log)

        self._create_gpio()
        self._create_flexcomm()
        self._create_timers()
        self._create_analog()
        self._create_crypto()

    def _create_gpio(self):
        """Create GPIO peripherals."""
        self.gpio0 = LPCGPIO(port=0, base=0x50000000)
        self.gpio1 = LPCGPIO(port=1, base=0x50001000)
        self.pint = LPCPINT(base=0x40004000)

        self.add_peripheral(self.gpio0)
        self.add_peripheral(self.gpio1)
        self.add_peripheral(self.pint)

    def _create_flexcomm(self):
        """Create FlexComm peripherals."""
        # FlexComm instances can be configured as USART, SPI, or I2C
        flexcomm_bases = [
            0x40086000,  # FC0
            0x40087000,  # FC1
            0x40088000,  # FC2
            0x40089000,  # FC3
            0x4008A000,  # FC4
            0x40096000,  # FC5
            0x40097000,  # FC6
            0x40098000,  # FC7
            0x4009F000,  # FC8 (HS SPI only)
        ]

        for i, base in enumerate(flexcomm_bases):
            # Create base FlexComm
            fc = LPCFlexComm(index=i, base=base)
            setattr(self, f"flexcomm{i}", fc)
            self.add_peripheral(fc)

            # Create function-specific views
            usart = LPCFlexCommUSART(index=i, base=base)
            spi = LPCFlexCommSPI(index=i, base=base)
            i2c = LPCFlexCommI2C(index=i, base=base)

            setattr(self, f"usart{i}", usart)
            setattr(self, f"spi{i}", spi)
            setattr(self, f"i2c{i}", i2c)

            # Note: These share the same base, actual peripheral selection
            # depends on PSELID register in FlexComm

    def _create_timers(self):
        """Create timer peripherals."""
        ctimer_bases = [
            0x40008000,  # CTIMER0
            0x40009000,  # CTIMER1
            0x4000A000,  # CTIMER2
            0x4000B000,  # CTIMER3
            0x4000C000,  # CTIMER4
        ]

        for i, base in enumerate(ctimer_bases):
            ctimer = LPCCTimer(index=i, base=base)
            setattr(self, f"ctimer{i}", ctimer)
            self.add_peripheral(ctimer)

    def _create_analog(self):
        """Create analog peripherals."""
        self.adc0 = LPCADC(base=0x400A0000)
        self.add_peripheral(self.adc0)

    def _create_crypto(self):
        """Create crypto peripherals."""
        self.casper = LPCCASPER(base=0x400A5000)
        self.hashcrypt = LPCHASHCRYPT(base=0x400A4000)
        self.puf = LPCPUF(base=0x4003B000)

        self.add_peripheral(self.casper)
        self.add_peripheral(self.hashcrypt)
        self.add_peripheral(self.puf)
