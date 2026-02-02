"""
NRF52840 Peripheral Set

Features:
- Cortex-M4F @ 64 MHz
- 1MB Flash, 256KB RAM
- BLE 5.0, IEEE 802.15.4, Thread, Zigbee
- USB 2.0 Full Speed
- NFC-A tag

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional
from .nrf_base import NRFPeripheralSet
from .nrf_gpio import NRFGPIO, NRFGPIOTE
from .nrf_uart import NRFUARTE
from .nrf_spi import NRFSPIM
from .nrf_twi import NRFTWIM
from .nrf_timer import NRFTIMER, NRFRTC
from .nrf_saadc import NRFSAADC
from .nrf_nvmc import NRFNVMC
from .nrf_power import NRFPOWER, NRFCLOCK
from .nrf_rng import NRFRNG
from .nrf_crypto import NRFECB, NRFCCM
from .nrf_radio import NRFRADIO
from .nrf_qspi import NRFQSPI


class NRF52840PeripheralSet(NRFPeripheralSet):
    """
    NRF52840 peripheral set.

    Memory Map:
        0x40000000 - CLOCK/POWER
        0x40001000 - RADIO
        0x40002000 - UARTE0
        0x40003000 - SPIM0/TWIM0
        0x40004000 - SPIM1/TWIM1
        0x40005000 - NFCT
        0x40006000 - GPIOTE
        0x40007000 - SAADC
        0x40008000 - TIMER0
        0x40009000 - TIMER1
        0x4000A000 - TIMER2
        0x4000B000 - RTC0
        0x4000C000 - TEMP
        0x4000D000 - RNG
        0x4000E000 - ECB
        0x4000F000 - CCM/AAR
        0x40010000 - WDT
        0x40011000 - RTC1
        0x40012000 - QDEC
        0x40013000 - COMP/LPCOMP
        0x40014000 - EGU0/SWI0
        ...
        0x40019000 - EGU5/SWI5
        0x4001A000 - TIMER3
        0x4001B000 - TIMER4
        0x4001C000 - PWM0
        0x4001D000 - PDM
        0x4001E000 - NVMC
        0x4001F000 - ACL
        0x40020000 - PPI
        0x40021000 - MWU
        0x40022000 - PWM1
        0x40023000 - PWM2
        0x40024000 - RTC2
        0x40025000 - I2S
        0x40026000 - FPU
        0x40027000 - USBD
        0x40028000 - UARTE1
        0x40029000 - QSPI
        0x4002A000 - PWM3
        0x4002B000 - SPIM3
        0x50000000 - GPIO P0
        0x50000300 - GPIO P1
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__("NRF52840", log)

        self._create_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_security()
        self._create_radio()
        self._create_qspi()

    def _create_system(self):
        """Create system peripherals."""
        # POWER and CLOCK share base address
        self.power = NRFPOWER(base=0x40000000)
        self.clock = NRFCLOCK(base=0x40000000)
        self.add_peripheral(self.power)
        self.add_peripheral(self.clock)

        self.nvmc = NRFNVMC(base=0x4001E000)
        self.add_peripheral(self.nvmc)

    def _create_gpio(self):
        """Create GPIO peripherals."""
        self.gpio0 = NRFGPIO(port=0, base=0x50000000)
        self.gpio1 = NRFGPIO(port=1, base=0x50000300)
        self.gpiote = NRFGPIOTE(base=0x40006000)
        self.gpiote.gpio_ports = [self.gpio0, self.gpio1]

        self.add_peripheral(self.gpio0)
        self.add_peripheral(self.gpio1)
        self.add_peripheral(self.gpiote)

    def _create_communication(self):
        """Create communication peripherals."""
        # UARTE
        self.uarte0 = NRFUARTE(index=0, base=0x40002000)
        self.uarte1 = NRFUARTE(index=1, base=0x40028000)
        self.add_peripheral(self.uarte0)
        self.add_peripheral(self.uarte1)

        # SPIM (shares with TWIM)
        self.spim0 = NRFSPIM(index=0, base=0x40003000)
        self.spim1 = NRFSPIM(index=1, base=0x40004000)
        self.spim2 = NRFSPIM(index=2, base=0x40023000)
        self.spim3 = NRFSPIM(index=3, base=0x4002B000)
        self.add_peripheral(self.spim0)
        self.add_peripheral(self.spim1)
        self.add_peripheral(self.spim2)
        self.add_peripheral(self.spim3)

        # TWIM
        self.twim0 = NRFTWIM(index=0, base=0x40003000)
        self.twim1 = NRFTWIM(index=1, base=0x40004000)
        self.add_peripheral(self.twim0)
        self.add_peripheral(self.twim1)

    def _create_timers(self):
        """Create timer peripherals."""
        for i in range(5):
            timer = NRFTIMER(index=i)
            setattr(self, f"timer{i}", timer)
            self.add_peripheral(timer)

        for i in range(3):
            rtc = NRFRTC(index=i)
            setattr(self, f"rtc{i}", rtc)
            self.add_peripheral(rtc)

    def _create_analog(self):
        """Create analog peripherals."""
        self.saadc = NRFSAADC(base=0x40007000)
        self.add_peripheral(self.saadc)

    def _create_security(self):
        """Create security peripherals."""
        self.rng = NRFRNG(base=0x4000D000)
        self.ecb = NRFECB(base=0x4000E000)
        self.ccm = NRFCCM(base=0x4000F000)
        self.add_peripheral(self.rng)
        self.add_peripheral(self.ecb)
        self.add_peripheral(self.ccm)

    def _create_radio(self):
        """Create radio peripheral."""
        self.radio = NRFRADIO(base=0x40001000)
        self.add_peripheral(self.radio)

    def _create_qspi(self):
        """Create QSPI peripheral."""
        self.qspi = NRFQSPI(base=0x40029000)
        self.add_peripheral(self.qspi)
