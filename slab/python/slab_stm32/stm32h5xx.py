"""
STM32H563 Peripheral Set - Auto-generated from SVD

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict
from .stm32_base import STM32PeripheralSet, STM32Peripheral
from .stm32_gpio import STM32GPIOv2, STM32EXTI
from .stm32_usart import STM32USARTv2, STM32LPUART
from .stm32_spi import STM32SPIv2
from .stm32_i2c import STM32I2Cv2
from .stm32_rcc import STM32RCCv4
from .stm32_pwr import STM32PWRv2
from .stm32_flash import STM32FLASHv3
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer, STM32LPTIM
from .stm32u5xx import STM32GTZC, STM32MPCBB
from .stm32_misc import STM32CRC, STM32IWDG, STM32RNG, STM32RTC, STM32WWDG, STM32ICACHE, STM32SYSCFG


class STM32GPDMA(STM32Peripheral):
    """
    STM32H5 GPDMA (General Purpose DMA) stub.

    GPDMA1: 0x40020000 (16 channels)
    GPDMA2: 0x40021000 (16 channels)

    This is a minimal stub that accepts all writes and returns
    sensible values for reads to allow HAL initialization to proceed.
    """

    # Global registers
    SECCFGR = 0x00   # Secure configuration
    PRIVCFGR = 0x04  # Privilege configuration
    RCFGLOCKR = 0x08 # Configuration lock
    MISR = 0x0C      # Masked interrupt status
    SMISR = 0x10     # Secure masked interrupt status

    # Channel registers start at 0x050 (channel 0)
    # Each channel is 0x80 bytes
    CHANNEL_BASE = 0x050
    CHANNEL_SIZE = 0x080

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = 0x40020000 if index == 1 else 0x40021000
        super().__init__(f"GPDMA{index}", base, size=0x1000)
        self.index = index
        self.num_channels = 16

    def _read_reg(self, offset: int, size: int) -> int:
        # Return stored value or default
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        # Accept all writes
        self.regs[offset] = value


class STM32H5xxPeripheralSet(STM32PeripheralSet):
    """Peripheral set for STM32H563."""

    def __init__(self, device: str = "STM32H563", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "H5"

        self._create_clock_system()
        self._create_dma()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_misc()
        self._create_trustzone()

    def _create_clock_system(self):
        self.rcc = STM32RCCv4(base=0x44020C00)
        self.add_peripheral(self.rcc)
        self.pwr = STM32PWRv2(base=0x44020800, family="H5")
        self.add_peripheral(self.pwr)
        self.flash = STM32FLASHv3(base=0x40022000, family="H5")
        self.add_peripheral(self.flash)

    def _create_dma(self):
        """Create GPDMA controllers for H5."""
        self.gpdma1 = STM32GPDMA(index=1, base=0x40020000)
        self.add_peripheral(self.gpdma1)
        self.gpdma2 = STM32GPDMA(index=2, base=0x40021000)
        self.add_peripheral(self.gpdma2)

    def _create_gpio(self):
        gpio_bases = {
            'A': 0x42020000,
            'B': 0x42020400,
            'C': 0x42020800,
            'D': 0x42020C00,
            'E': 0x42021000,
            'F': 0x42021400,
            'G': 0x42021800,
            'H': 0x42021C00,
            'I': 0x42022000,
        }
        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv2(port=port, base=base, family="H5")
            self.add_peripheral(self.gpio[port])
        self.exti = STM32EXTI(base=0x44022000)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        usart_cfg = [
            (2, 0x40004400),
            (3, 0x40004800),
            (4, 0x40004C00),
            (5, 0x40005000),
            (6, 0x40006400),
            (10, 0x40006800),
            (11, 0x40006C00),
            (7, 0x40007800),
            (8, 0x40007C00),
            (9, 0x40008000),
            (12, 0x40008400),
            (1, 0x40013800),
        ]
        for idx, base in usart_cfg:
            setattr(self, f"usart{idx}", STM32USARTv2(index=idx, base=base))
            self.add_peripheral(getattr(self, f"usart{idx}"))
        spi_cfg = [
            (2, 0x40003800),
            (3, 0x40003C00),
            (1, 0x40013000),
            (4, 0x40014C00),
            (6, 0x40015000),
            (5, 0x44002000),
        ]
        for idx, base in spi_cfg:
            setattr(self, f"spi{idx}", STM32SPIv2(index=idx, base=base))
            self.add_peripheral(getattr(self, f"spi{idx}"))
        i2c_cfg = [
            (1, 0x40005400),
            (2, 0x40005800),
            (3, 0x44002800),
            (4, 0x44002C00),
        ]
        for idx, base in i2c_cfg:
            setattr(self, f"i2c{idx}", STM32I2Cv2(index=idx, base=base))
            self.add_peripheral(getattr(self, f"i2c{idx}"))

    def _create_timers(self):
        self.tim2 = STM32GeneralTimer(index=2, base=0x40000000, is_32bit=True)
        self.add_peripheral(self.tim2)
        self.tim3 = STM32GeneralTimer(index=3, base=0x40000400)
        self.add_peripheral(self.tim3)
        self.tim4 = STM32GeneralTimer(index=4, base=0x40000800)
        self.add_peripheral(self.tim4)
        self.tim5 = STM32GeneralTimer(index=5, base=0x40000C00, is_32bit=True)
        self.add_peripheral(self.tim5)
        self.tim6 = STM32BasicTimer(index=6, base=0x40001000)
        self.add_peripheral(self.tim6)
        self.tim7 = STM32BasicTimer(index=7, base=0x40001400)
        self.add_peripheral(self.tim7)
        self.tim12 = STM32GeneralTimer(index=12, base=0x40001800)
        self.add_peripheral(self.tim12)
        self.tim13 = STM32GeneralTimer(index=13, base=0x40001C00)
        self.add_peripheral(self.tim13)
        self.tim14 = STM32GeneralTimer(index=14, base=0x40002000)
        self.add_peripheral(self.tim14)
        self.tim1 = STM32AdvancedTimer(index=1, base=0x40012C00)
        self.add_peripheral(self.tim1)
        self.tim8 = STM32AdvancedTimer(index=8, base=0x40013400)
        self.add_peripheral(self.tim8)
        self.tim15 = STM32GeneralTimer(index=15, base=0x40014000)
        self.add_peripheral(self.tim15)
        self.tim16 = STM32GeneralTimer(index=16, base=0x40014400)
        self.add_peripheral(self.tim16)
        self.tim17 = STM32GeneralTimer(index=17, base=0x40014800)
        self.add_peripheral(self.tim17)

    def _create_misc(self):
        self.crc = STM32CRC(base=0x40023000)
        self.add_peripheral(self.crc)
        self.iwdg = STM32IWDG(base=0x40003000)
        self.add_peripheral(self.iwdg)
        self.rtc = STM32RTC(base=0x44007800)
        self.add_peripheral(self.rtc)
        self.rng = STM32RNG(base=0x420C0800)
        self.add_peripheral(self.rng)
        self.wwdg = STM32WWDG(base=0x40002C00)
        self.add_peripheral(self.wwdg)
        # ICACHE - HAL_Init() enables this during startup
        self.icache = STM32ICACHE(base=0x40030400)
        self.add_peripheral(self.icache)
        # SYSCFG - System configuration controller
        self.syscfg = STM32SYSCFG(base=0x44000400, family="H5")
        self.add_peripheral(self.syscfg)

    def _create_trustzone(self):
        self.mpcbb1 = STM32MPCBB(index=1, base=0x40032C00)
        self.add_peripheral(self.mpcbb1)
        self.mpcbb2 = STM32MPCBB(index=2, base=0x40033000)
        self.add_peripheral(self.mpcbb2)
        self.mpcbb3 = STM32MPCBB(index=3, base=0x40033400)
        self.add_peripheral(self.mpcbb3)
        self.gtzc = STM32GTZC(base=0x40032400)
        self.add_peripheral(self.gtzc)


# Alias
STM32H563PeripheralSet = STM32H5xxPeripheralSet
