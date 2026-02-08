"""
STM32F1xx Peripheral Sets

Supported devices:
- STM32F103 (medium/high density)
- STM32F105/107 (connectivity line)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict
from .stm32_base import STM32PeripheralSet
from .stm32_gpio import STM32GPIOv1, STM32EXTI
from .stm32_usart import STM32USARTv1
from .stm32_spi import STM32SPIv1
from .stm32_i2c import STM32I2Cv1
from .stm32_rcc import STM32RCCv1
from .stm32_dma import STM32DMAv1
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer
from .stm32_adc import STM32ADCv1
from .stm32_dac import STM32DAC
from .stm32_pwr import STM32PWRv1
from .stm32_flash import STM32FLASHv1
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32DBG
from .stm32_usb_device import STM32USBDevice


class STM32F1xxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32F1xx family.

    Memory Map (typical):
        0x40000000 - APB1 (TIM2-7, RTC, WWDG, IWDG, SPI2/3, USART2-5, I2C1/2, USB, CAN, BKP, PWR, DAC)
        0x40010000 - APB2 (AFIO, EXTI, GPIOA-G, ADC1-3, TIM1/8, SPI1, USART1)
        0x40018000 - APB2 continued (TIM9-14 for XL devices)
        0x40020000 - AHB (DMA1/2, RCC, FLASH, CRC, FSMC, SDIO)
    """

    def __init__(self, device: str = "STM32F103", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "F1"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_misc()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32RCCv1(base=0x40021000)
        self.add_peripheral(self.rcc)

        self.pwr = STM32PWRv1(base=0x40007000, family="F1")
        self.add_peripheral(self.pwr)

        self.flash = STM32FLASHv1(base=0x40022000)
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports (GPIOv1 with CRL/CRH)."""
        gpio_bases = {
            'A': 0x40010800,
            'B': 0x40010C00,
            'C': 0x40011000,
            'D': 0x40011400,
            'E': 0x40011800,
        }

        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv1(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # EXTI
        self.exti = STM32EXTI(base=0x40010400)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals."""
        # USARTs
        self.usart1 = STM32USARTv1(index=1, base=0x40013800)
        self.usart2 = STM32USARTv1(index=2, base=0x40004400)
        self.usart3 = STM32USARTv1(index=3, base=0x40004800)
        self.add_peripheral(self.usart1)
        self.add_peripheral(self.usart2)
        self.add_peripheral(self.usart3)

        # SPI
        self.spi1 = STM32SPIv1(index=1, base=0x40013000)
        self.spi2 = STM32SPIv1(index=2, base=0x40003800)
        self.add_peripheral(self.spi1)
        self.add_peripheral(self.spi2)

        # I2C
        self.i2c1 = STM32I2Cv1(index=1, base=0x40005400)
        self.i2c2 = STM32I2Cv1(index=2, base=0x40005800)
        self.add_peripheral(self.i2c1)
        self.add_peripheral(self.i2c2)

    def _create_timers(self):
        """Create timer peripherals."""
        # Advanced timer
        self.tim1 = STM32AdvancedTimer(index=1, base=0x40012C00)
        self.add_peripheral(self.tim1)

        # General purpose timers
        self.tim2 = STM32GeneralTimer(index=2, base=0x40000000)
        self.tim3 = STM32GeneralTimer(index=3, base=0x40000400)
        self.tim4 = STM32GeneralTimer(index=4, base=0x40000800)
        self.add_peripheral(self.tim2)
        self.add_peripheral(self.tim3)
        self.add_peripheral(self.tim4)

        # Basic timers (not on all F1 devices)
        self.tim6 = STM32BasicTimer(index=6, base=0x40001000)
        self.tim7 = STM32BasicTimer(index=7, base=0x40001400)
        self.add_peripheral(self.tim6)
        self.add_peripheral(self.tim7)

    def _create_analog(self):
        """Create ADC and DAC peripherals."""
        self.adc1 = STM32ADCv1(index=1, base=0x40012400)
        self.adc2 = STM32ADCv1(index=2, base=0x40012800)
        self.add_peripheral(self.adc1)
        self.add_peripheral(self.adc2)

        self.dac = STM32DAC(base=0x40007400)
        self.add_peripheral(self.dac)

    def _create_dma(self):
        """Create DMA controllers."""
        self.dma1 = STM32DMAv1(index=1, base=0x40020000)
        self.add_peripheral(self.dma1)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        # AFIO (similar to SYSCFG)
        self.afio = STM32SYSCFG(base=0x40010000, family="F1")
        self.afio.name = "AFIO"
        self.add_peripheral(self.afio)

        self.iwdg = STM32IWDG(base=0x40003000)
        self.wwdg = STM32WWDG(base=0x40002C00, family="F1")
        self.rtc = STM32RTC(base=0x40002800, num_backup=10)
        self.crc = STM32CRC(base=0x40023000, family="F1")
        self.dbg = STM32DBG(base=0xE0042000, device="F103")

        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)
        self.add_peripheral(self.rtc)
        self.add_peripheral(self.crc)
        self.add_peripheral(self.dbg)


class STM32F103PeripheralSet(STM32F1xxPeripheralSet):
    """
    STM32F103 (medium/high density) peripheral set.

    Specific features:
    - Up to 72 MHz
    - USB device (no OTG)
    - CAN (high density)
    """

    def __init__(self, density: str = "HD", log: logging.Logger = None):
        self.density = density
        super().__init__(device=f"STM32F103{density}", log=log)

        # USB Device (all F103 variants have USB)
        self._add_usb()

        if density == "HD":
            self._add_high_density_peripherals()

    def _add_usb(self):
        """Add USB Device peripheral."""
        # USB low-priority IRQ = 20, high-priority = 19
        self.usb = STM32USBDevice(base=0x40005C00, irq=20)
        self.add_peripheral(self.usb)

    def _add_high_density_peripherals(self):
        """Add peripherals specific to high-density devices."""
        # Additional GPIO ports
        for port, base in [('F', 0x40011C00), ('G', 0x40012000)]:
            self.gpio[port] = STM32GPIOv1(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # TIM5 (32-bit on some)
        self.tim5 = STM32GeneralTimer(index=5, base=0x40000C00)
        self.add_peripheral(self.tim5)

        # TIM8
        self.tim8 = STM32AdvancedTimer(index=8, base=0x40013400)
        self.add_peripheral(self.tim8)

        # DMA2
        self.dma2 = STM32DMAv1(index=2, base=0x40020400)
        self.add_peripheral(self.dma2)

        # ADC3
        self.adc3 = STM32ADCv1(index=3, base=0x40013C00)
        self.add_peripheral(self.adc3)

        # SPI3
        self.spi3 = STM32SPIv1(index=3, base=0x40003C00)
        self.add_peripheral(self.spi3)


class STM32F105PeripheralSet(STM32F1xxPeripheralSet):
    """
    STM32F105/107 (connectivity line) peripheral set.

    Specific features:
    - USB OTG FS
    - Ethernet (F107)
    - Two CAN controllers
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32F105", log=log)
        # Connectivity line has different clocking
        self.rcc.hse_freq = 25_000_000  # Often 25MHz for Ethernet
