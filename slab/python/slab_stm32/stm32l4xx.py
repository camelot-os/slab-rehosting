"""
STM32L4xx Peripheral Sets

Supported devices:
- STM32L476 (80 MHz, low power)
- STM32L4R5/S5 (120 MHz, larger flash)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict
from .stm32_base import STM32PeripheralSet
from .stm32_gpio import STM32GPIOv2, STM32EXTI
from .stm32_usart import STM32USARTv2, STM32LPUART
from .stm32_spi import STM32SPIv1
from .stm32_i2c import STM32I2Cv2
from .stm32_rcc import STM32RCCv3
from .stm32_dma import STM32DMAv1
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer, STM32LPTIM
from .stm32_adc import STM32ADCv3
from .stm32_dac import STM32DAC
from .stm32_pwr import STM32PWRv2
from .stm32_flash import STM32FLASHv3
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32RNG, STM32DBG


class STM32L4xxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32L4xx family.

    Memory Map:
        0x40000000 - APB1 (TIM2-7, RTC, WWDG, IWDG, SPI2/3, USART2-5, I2C1-3, CAN1, PWR, DAC, LPTIM)
        0x40010000 - APB2 (SYSCFG, COMP, EXTI, FIREWALL, TIM1/8/15-17, SPI1, USART1, SAI1)
        0x40020000 - AHB1 (DMA1/2, RCC, FLASH, CRC, TSC)
        0x48000000 - AHB2 (GPIOA-H, OTGFS, ADC, RNG, AES)
        0xA0000000 - FMC/QUADSPI
    """

    def __init__(self, device: str = "STM32L476", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "L4"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_misc()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32RCCv3(base=0x40021000)
        self.add_peripheral(self.rcc)

        self.pwr = STM32PWRv2(base=0x40007000, family="L4")
        self.add_peripheral(self.pwr)

        self.flash = STM32FLASHv3(base=0x40022000, family="L4")
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports (GPIOv2, located in AHB2)."""
        gpio_bases = {
            'A': 0x48000000,
            'B': 0x48000400,
            'C': 0x48000800,
            'D': 0x48000C00,
            'E': 0x48001000,
            'F': 0x48001400,
            'G': 0x48001800,
            'H': 0x48001C00,
        }

        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # EXTI
        self.exti = STM32EXTI(base=0x40010400)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals (v2 variants)."""
        # USARTs (v2 with FIFO)
        self.usart1 = STM32USARTv2(index=1, base=0x40013800)
        self.usart2 = STM32USARTv2(index=2, base=0x40004400)
        self.usart3 = STM32USARTv2(index=3, base=0x40004800)
        self.add_peripheral(self.usart1)
        self.add_peripheral(self.usart2)
        self.add_peripheral(self.usart3)

        # LPUART
        self.lpuart1 = STM32LPUART(index=1, base=0x40008000)
        self.add_peripheral(self.lpuart1)

        # SPI
        self.spi1 = STM32SPIv1(index=1, base=0x40013000)
        self.spi2 = STM32SPIv1(index=2, base=0x40003800)
        self.spi3 = STM32SPIv1(index=3, base=0x40003C00)
        self.add_peripheral(self.spi1)
        self.add_peripheral(self.spi2)
        self.add_peripheral(self.spi3)

        # I2C (v2)
        self.i2c1 = STM32I2Cv2(index=1, base=0x40005400)
        self.i2c2 = STM32I2Cv2(index=2, base=0x40005800)
        self.i2c3 = STM32I2Cv2(index=3, base=0x40005C00)
        self.add_peripheral(self.i2c1)
        self.add_peripheral(self.i2c2)
        self.add_peripheral(self.i2c3)

    def _create_timers(self):
        """Create timer peripherals."""
        # Advanced timers
        self.tim1 = STM32AdvancedTimer(index=1, base=0x40012C00)
        self.tim8 = STM32AdvancedTimer(index=8, base=0x40013400)
        self.add_peripheral(self.tim1)
        self.add_peripheral(self.tim8)

        # General purpose timers
        self.tim2 = STM32GeneralTimer(index=2, base=0x40000000, is_32bit=True)
        self.tim3 = STM32GeneralTimer(index=3, base=0x40000400)
        self.tim4 = STM32GeneralTimer(index=4, base=0x40000800)
        self.tim5 = STM32GeneralTimer(index=5, base=0x40000C00, is_32bit=True)
        self.add_peripheral(self.tim2)
        self.add_peripheral(self.tim3)
        self.add_peripheral(self.tim4)
        self.add_peripheral(self.tim5)

        # Basic timers
        self.tim6 = STM32BasicTimer(index=6, base=0x40001000)
        self.tim7 = STM32BasicTimer(index=7, base=0x40001400)
        self.add_peripheral(self.tim6)
        self.add_peripheral(self.tim7)

        # Low-power timers
        self.lptim1 = STM32LPTIM(index=1, base=0x40007C00)
        self.lptim2 = STM32LPTIM(index=2, base=0x40009400)
        self.add_peripheral(self.lptim1)
        self.add_peripheral(self.lptim2)

    def _create_analog(self):
        """Create ADC and DAC peripherals."""
        # ADCv3 (16-bit capable)
        self.adc1 = STM32ADCv3(index=1, base=0x50040000)
        self.adc2 = STM32ADCv3(index=2, base=0x50040100)
        self.adc3 = STM32ADCv3(index=3, base=0x50040200)
        self.add_peripheral(self.adc1)
        self.add_peripheral(self.adc2)
        self.add_peripheral(self.adc3)

        # DAC
        self.dac1 = STM32DAC(base=0x40007400)
        self.add_peripheral(self.dac1)

    def _create_dma(self):
        """Create DMA controllers (channel-based like F1)."""
        self.dma1 = STM32DMAv1(index=1, base=0x40020000)
        self.dma2 = STM32DMAv1(index=2, base=0x40020400)
        self.add_peripheral(self.dma1)
        self.add_peripheral(self.dma2)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        self.syscfg = STM32SYSCFG(base=0x40010000, family="L4")
        self.iwdg = STM32IWDG(base=0x40003000)
        self.wwdg = STM32WWDG(base=0x40002C00, family="L4")
        self.rtc = STM32RTC(base=0x40002800, num_backup=32)
        self.crc = STM32CRC(base=0x40023000, family="L4")
        self.rng = STM32RNG(base=0x50060800, family="L4")
        self.dbg = STM32DBG(base=0xE0042000, device="L476")

        self.add_peripheral(self.syscfg)
        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)
        self.add_peripheral(self.rtc)
        self.add_peripheral(self.crc)
        self.add_peripheral(self.rng)
        self.add_peripheral(self.dbg)


class STM32L476PeripheralSet(STM32L4xxPeripheralSet):
    """
    STM32L476 peripheral set.

    Features:
    - 80 MHz
    - Ultra-low-power
    - USB OTG FS
    - LCD controller
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32L476", log=log)


class STM32L4R5PeripheralSet(STM32L4xxPeripheralSet):
    """
    STM32L4R5 peripheral set.

    Features:
    - 120 MHz
    - 2MB Flash
    - OCTOSPI
    - Higher performance ADC
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32L4R5", log=log)
        # Higher clock
        self.rcc.sysclk = 120_000_000
