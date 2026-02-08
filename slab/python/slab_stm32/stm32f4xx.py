"""
STM32F4xx Peripheral Sets

Supported devices:
- STM32F405/407 (168 MHz, USB OTG FS/HS, Ethernet)
- STM32F429/439 (180 MHz, LCD-TFT, FMC, dual bank flash)
- STM32F446 (180 MHz, dual I2S)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict
from .stm32_base import STM32PeripheralSet
from .stm32_gpio import STM32GPIOv2, STM32EXTI
from .stm32_usart import STM32USARTv1
from .stm32_spi import STM32SPIv1
from .stm32_i2c import STM32I2Cv1
from .stm32_rcc import STM32RCCv2
from .stm32_dma import STM32DMAv2
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer
from .stm32_adc import STM32ADCv2
from .stm32_dac import STM32DAC
from .stm32_pwr import STM32PWRv1
from .stm32_flash import STM32FLASHv2
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32RNG, STM32DBG
from .stm32_cryp import STM32F4CRYP
from .stm32_hash import STM32F4HASH


class STM32F4xxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32F4xx family.

    Memory Map:
        0x40000000 - APB1 (TIM2-7/12-14, RTC, WWDG, IWDG, I2S, SPI2/3, USART2-5, I2C1-3, CAN1/2, PWR, DAC)
        0x40010000 - APB2 (TIM1/8-11, USART1/6, ADC1-3, SDIO, SPI1/4, SYSCFG, EXTI)
        0x40020000 - AHB1 (GPIOA-K, CRC, RCC, FLASH, DMA1/2, Ethernet, USB OTG HS)
        0x50000000 - AHB2 (USB OTG FS, DCMI, RNG, HASH, CRYP)
        0xA0000000 - AHB3 (FSMC/FMC)
    """

    def __init__(self, device: str = "STM32F407", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "F4"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_misc()
        self._create_usb()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32RCCv2(base=0x40023800)
        self.add_peripheral(self.rcc)

        self.pwr = STM32PWRv1(base=0x40007000, family="F4")
        self.add_peripheral(self.pwr)

        self.flash = STM32FLASHv2(base=0x40023C00, dual_bank=False)
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports (GPIOv2 with MODER)."""
        gpio_bases = {
            'A': 0x40020000,
            'B': 0x40020400,
            'C': 0x40020800,
            'D': 0x40020C00,
            'E': 0x40021000,
            'F': 0x40021400,
            'G': 0x40021800,
            'H': 0x40021C00,
            'I': 0x40022000,
        }

        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # EXTI
        self.exti = STM32EXTI(base=0x40013C00)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals."""
        # USARTs
        usart_config = [
            (1, 0x40011000),  # APB2
            (2, 0x40004400),  # APB1
            (3, 0x40004800),  # APB1
            (4, 0x40004C00),  # APB1 (UART)
            (5, 0x40005000),  # APB1 (UART)
            (6, 0x40011400),  # APB2
        ]

        for idx, base in usart_config:
            name = f"usart{idx}"
            setattr(self, name, STM32USARTv1(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # SPI
        spi_config = [
            (1, 0x40013000),  # APB2
            (2, 0x40003800),  # APB1
            (3, 0x40003C00),  # APB1
        ]

        for idx, base in spi_config:
            name = f"spi{idx}"
            setattr(self, name, STM32SPIv1(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # I2C
        i2c_config = [
            (1, 0x40005400),
            (2, 0x40005800),
            (3, 0x40005C00),
        ]

        for idx, base in i2c_config:
            name = f"i2c{idx}"
            setattr(self, name, STM32I2Cv1(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

    def _create_timers(self):
        """Create timer peripherals."""
        # Advanced timers
        self.tim1 = STM32AdvancedTimer(index=1, base=0x40010000)
        self.tim8 = STM32AdvancedTimer(index=8, base=0x40010400)
        self.add_peripheral(self.tim1)
        self.add_peripheral(self.tim8)

        # General purpose timers (32-bit: TIM2, TIM5)
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

    def _create_analog(self):
        """Create ADC and DAC peripherals."""
        # Triple ADC
        self.adc1 = STM32ADCv2(index=1, base=0x40012000)
        self.adc2 = STM32ADCv2(index=2, base=0x40012100)
        self.adc3 = STM32ADCv2(index=3, base=0x40012200)
        self.add_peripheral(self.adc1)
        self.add_peripheral(self.adc2)
        self.add_peripheral(self.adc3)

        # DAC
        self.dac = STM32DAC(base=0x40007400)
        self.add_peripheral(self.dac)

    def _create_dma(self):
        """Create DMA controllers."""
        self.dma1 = STM32DMAv2(index=1, base=0x40026000)
        self.dma2 = STM32DMAv2(index=2, base=0x40026400)
        self.add_peripheral(self.dma1)
        self.add_peripheral(self.dma2)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        self.syscfg = STM32SYSCFG(base=0x40013800, family="F4")
        self.iwdg = STM32IWDG(base=0x40003000)
        self.wwdg = STM32WWDG(base=0x40002C00, family="F4")
        self.rtc = STM32RTC(base=0x40002800, num_backup=20)
        self.crc = STM32CRC(base=0x40023000, family="F4")
        self.rng = STM32RNG(base=0x50060800, family="F4")
        self.dbg = STM32DBG(base=0xE0042000, device="F407")

        self.add_peripheral(self.syscfg)
        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)
        self.add_peripheral(self.rtc)
        self.add_peripheral(self.crc)
        self.add_peripheral(self.rng)
        self.add_peripheral(self.dbg)

    def _create_usb(self):
        """Create USB OTG FS peripheral (DWC2)."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        self.usb = USBCDCPeripheral(
            name="USB_OTG_FS", base=0x50000000, size=0x40000, irq=67)
        self.add_peripheral(self.usb)


class STM32F405PeripheralSet(STM32F4xxPeripheralSet):
    """
    STM32F405 peripheral set.

    Features:
    - 168 MHz
    - USB OTG FS + HS
    - No Ethernet
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32F405", log=log)
        self.dbg.idcode = STM32DBG.DEVICE_IDS["F405"]


class STM32F407PeripheralSet(STM32F4xxPeripheralSet):
    """
    STM32F407 peripheral set.

    Features:
    - 168 MHz
    - USB OTG FS + HS
    - Ethernet MAC
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32F407", log=log)


class STM32F429PeripheralSet(STM32F4xxPeripheralSet):
    """
    STM32F429 peripheral set.

    Features:
    - 180 MHz
    - LCD-TFT controller
    - FMC (flexible memory controller)
    - Dual bank flash
    - SDRAM support
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32F429", log=log)

        # Update for dual bank flash
        self.flash = STM32FLASHv2(base=0x40023C00, dual_bank=True)

        # Additional GPIO ports
        for port, base in [('J', 0x40022400), ('K', 0x40022800)]:
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        self.dbg.idcode = STM32DBG.DEVICE_IDS["F429"]


class STM32F439PeripheralSet(STM32F429PeripheralSet):
    """
    STM32F439 peripheral set (F429 + crypto).

    Additional features:
    - CRYP (AES, DES, TDES)
    - HASH (MD5, SHA-1, SHA-224, SHA-256)
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(log=log)
        self.device = "STM32F439"
        self.dbg.idcode = STM32DBG.DEVICE_IDS["F439"]

        # Add crypto peripherals
        self._create_crypto()

    def _create_crypto(self):
        """Create cryptographic peripherals."""
        # CRYP at 0x50060000 (AES, DES, TDES)
        self.cryp = STM32F4CRYP(base=0x50060000)
        self.add_peripheral(self.cryp)

        # HASH at 0x50060400 (MD5, SHA-1, SHA-224, SHA-256)
        self.hash = STM32F4HASH(base=0x50060400)
        self.add_peripheral(self.hash)


class STM32F446PeripheralSet(STM32F4xxPeripheralSet):
    """
    STM32F446 peripheral set.

    Features:
    - 180 MHz
    - Dual I2S (full duplex)
    - SPDIFRX
    - No Ethernet
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32F446", log=log)

        # SPI4
        self.spi4 = STM32SPIv1(index=4, base=0x40013400)
        self.add_peripheral(self.spi4)
