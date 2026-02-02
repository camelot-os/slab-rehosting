"""
STM32H7xx Peripheral Sets

Supported devices:
- STM32H743/753 (480 MHz, dual core option)
- STM32H750 (value line, 128KB flash)
- STM32H7A3/7B3 (280 MHz, USB HS PHY)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict
from .stm32_base import STM32PeripheralSet
from .stm32_gpio import STM32GPIOv2, STM32EXTI
from .stm32_usart import STM32USARTv2, STM32LPUART
from .stm32_spi import STM32SPIv2
from .stm32_i2c import STM32I2Cv2
from .stm32_rcc import STM32RCCv4
from .stm32_dma import STM32DMAv2, STM32BDMA, STM32MDMA
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer, STM32LPTIM
from .stm32_adc import STM32ADCv3
from .stm32_dac import STM32DAC
from .stm32_pwr import STM32PWRv3
from .stm32_flash import STM32FLASHv3
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32RNG, STM32DBG


class STM32H7xxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32H7xx family.

    Memory Map (D1 domain):
        0x40000000 - APB1 (TIM2-7/12-14, LPTIM1, SPI2/3, USART2/3, UART4-8, I2C1-3, CEC, DAC, MDIOS)
        0x40010000 - APB2 (TIM1/8/15-17, SPI1/4/5, USART1/6, SAI1-2, DFSDM)
        0x40020000 - AHB1 (DMA1/2, DMAMUX1, ADC1/2, USB OTG HS/FS)
        0x48020000 - AHB2 (DCMI, CRYP, HASH, RNG, SDMMC2)
        0x50000000 - AHB3 (MDMA, FMC, QUADSPI, SDMMC1)
        0x52000000 - MDMA

    Memory Map (D2 domain):
        0x40080000 - APB3 (LTDC, DSI)

    Memory Map (D3 domain):
        0x58000000 - APB4 (EXTI, SYSCFG, LPUART1, SPI6, I2C4, LPTIM2-5, DAC2, COMP)
        0x58020000 - AHB4 (GPIOA-K, RCC, PWR, CRC, BDMA, HSEM)
    """

    def __init__(self, device: str = "STM32H743", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "H7"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_misc()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32RCCv4(base=0x58024400)
        self.add_peripheral(self.rcc)

        self.pwr = STM32PWRv3(base=0x58024800)
        self.add_peripheral(self.pwr)

        self.flash = STM32FLASHv3(base=0x52002000, family="H7")
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports (in D3 AHB4)."""
        gpio_bases = {
            'A': 0x58020000,
            'B': 0x58020400,
            'C': 0x58020800,
            'D': 0x58020C00,
            'E': 0x58021000,
            'F': 0x58021400,
            'G': 0x58021800,
            'H': 0x58021C00,
            'I': 0x58022000,
            'J': 0x58022400,
            'K': 0x58022800,
        }

        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # EXTI in D3 APB4
        self.exti = STM32EXTI(base=0x58000000)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals."""
        # USARTs (v2 with FIFO)
        usart_config = [
            (1, 0x40011000),  # D2 APB2
            (2, 0x40004400),  # D2 APB1
            (3, 0x40004800),  # D2 APB1
            (6, 0x40011400),  # D2 APB2
        ]
        for idx, base in usart_config:
            name = f"usart{idx}"
            setattr(self, name, STM32USARTv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # UARTs
        uart_config = [
            (4, 0x40004C00),
            (5, 0x40005000),
            (7, 0x40007800),
            (8, 0x40007C00),
        ]
        for idx, base in uart_config:
            name = f"uart{idx}"
            setattr(self, name, STM32USARTv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # LPUART in D3
        self.lpuart1 = STM32LPUART(index=1, base=0x58000C00)
        self.add_peripheral(self.lpuart1)

        # SPI (v2 with 16-deep FIFO)
        spi_config = [
            (1, 0x40013000),  # D2 APB2
            (2, 0x40003800),  # D2 APB1
            (3, 0x40003C00),  # D2 APB1
            (4, 0x40013400),  # D2 APB2
            (5, 0x40015000),  # D2 APB2
            (6, 0x58001400),  # D3 APB4
        ]
        for idx, base in spi_config:
            name = f"spi{idx}"
            setattr(self, name, STM32SPIv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # I2C (v2)
        i2c_config = [
            (1, 0x40005400),  # D2 APB1
            (2, 0x40005800),  # D2 APB1
            (3, 0x40005C00),  # D2 APB1
            (4, 0x58001C00),  # D3 APB4
        ]
        for idx, base in i2c_config:
            name = f"i2c{idx}"
            setattr(self, name, STM32I2Cv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

    def _create_timers(self):
        """Create timer peripherals."""
        # Advanced timers
        self.tim1 = STM32AdvancedTimer(index=1, base=0x40010000)
        self.tim8 = STM32AdvancedTimer(index=8, base=0x40010400)
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

        # Low-power timers (LPTIM1-5)
        lptim_config = [
            (1, 0x40002400),  # D2 APB1
            (2, 0x58002400),  # D3 APB4
            (3, 0x58002800),  # D3 APB4
            (4, 0x58002C00),  # D3 APB4
            (5, 0x58003000),  # D3 APB4
        ]
        for idx, base in lptim_config:
            name = f"lptim{idx}"
            setattr(self, name, STM32LPTIM(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

    def _create_analog(self):
        """Create ADC and DAC peripherals."""
        # ADCv3 (16-bit)
        self.adc1 = STM32ADCv3(index=1, base=0x40022000)
        self.adc2 = STM32ADCv3(index=2, base=0x40022100)
        self.adc3 = STM32ADCv3(index=3, base=0x58026000)  # D3 domain
        self.add_peripheral(self.adc1)
        self.add_peripheral(self.adc2)
        self.add_peripheral(self.adc3)

        # DACs
        self.dac1 = STM32DAC(base=0x40007400)
        self.add_peripheral(self.dac1)

    def _create_dma(self):
        """Create DMA controllers (multiple types)."""
        # DMAv2 streams
        self.dma1 = STM32DMAv2(index=1, base=0x40020000)
        self.dma2 = STM32DMAv2(index=2, base=0x40020400)
        self.add_peripheral(self.dma1)
        self.add_peripheral(self.dma2)

        # BDMA (D3 domain)
        self.bdma = STM32BDMA(base=0x58025400)
        self.add_peripheral(self.bdma)

        # MDMA (master DMA)
        self.mdma = STM32MDMA(base=0x52000000)
        self.add_peripheral(self.mdma)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        self.syscfg = STM32SYSCFG(base=0x58000400, family="H7")
        self.iwdg = STM32IWDG(base=0x58004800)
        self.wwdg = STM32WWDG(base=0x50003000, family="H7")  # D1 APB3
        self.rtc = STM32RTC(base=0x58004000, num_backup=32)
        self.crc = STM32CRC(base=0x58024C00, family="H7")
        self.rng = STM32RNG(base=0x48021800, family="H7")
        self.dbg = STM32DBG(base=0x5C001000, device="H743")

        self.add_peripheral(self.syscfg)
        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)
        self.add_peripheral(self.rtc)
        self.add_peripheral(self.crc)
        self.add_peripheral(self.rng)
        self.add_peripheral(self.dbg)


class STM32H743PeripheralSet(STM32H7xxPeripheralSet):
    """
    STM32H743 peripheral set.

    Features:
    - 480 MHz (single core)
    - 2MB Flash
    - Ethernet
    - USB OTG FS + HS
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32H743", log=log)


class STM32H753PeripheralSet(STM32H7xxPeripheralSet):
    """
    STM32H753 peripheral set (H743 + crypto).

    Additional features:
    - CRYP (AES-GCM, AES-CCM)
    - HASH (SHA-256)
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32H753", log=log)
        self.dbg.idcode = STM32DBG.DEVICE_IDS["H753"]


class STM32H750PeripheralSet(STM32H7xxPeripheralSet):
    """
    STM32H750 peripheral set (value line).

    Features:
    - 480 MHz
    - 128KB internal flash
    - Execute from QSPI
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32H750", log=log)
        # Smaller internal flash
        self.flash.page_size = 128 * 1024


class STM32H7A3PeripheralSet(STM32H7xxPeripheralSet):
    """
    STM32H7A3 peripheral set.

    Features:
    - 280 MHz
    - USB HS with integrated PHY
    - No Ethernet
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32H7A3", log=log)
        # Different clock speed
        self.rcc.hsi_freq = 64_000_000
