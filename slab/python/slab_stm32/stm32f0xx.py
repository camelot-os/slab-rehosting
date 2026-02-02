"""
STM32F0xx Peripheral Sets

Supported devices:
- STM32F042 (Cortex-M0, 32KB Flash, 6KB SRAM) - Used in Ledger Nano S/S+
- STM32F072 (Cortex-M0, 128KB Flash, 16KB SRAM)
- STM32F091 (Cortex-M0, 256KB Flash, 32KB SRAM)

The F0 series uses Cortex-M0 core and has simpler peripherals than F1/F4.
Key differences from F1:
- GPIO uses MODER/OTYPER (like F4), not CRL/CRH
- Simpler RCC (no PLL multiplication flexibility)
- USB Device (not OTG) on some variants

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict

from .stm32_base import STM32PeripheralSet, STM32Peripheral
from .stm32_gpio import STM32GPIOv2, STM32EXTI
from .stm32_usart import STM32USARTv1
from .stm32_spi import STM32SPIv1
from .stm32_i2c import STM32I2Cv1
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer
from .stm32_adc import STM32ADCv1
from .stm32_dma import STM32DMAv1
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32DBG
from .stm32_usb_device import STM32USBDevice


class STM32F0xxRCC(STM32Peripheral):
    """
    STM32F0xx Reset and Clock Control.

    Simpler than F1/F4 RCC:
    - HSI (8 MHz internal)
    - HSE (external, typically 8 MHz)
    - PLL with limited factors
    - Max 48 MHz system clock
    """

    def __init__(self, base: int = 0x40021000):
        super().__init__("RCC", base, 0x400, irq=-1)

        # Default clock configuration
        self.hsi_freq = 8_000_000
        self.hse_freq = 8_000_000
        self.sysclk = self.hsi_freq
        self.hclk = self.sysclk
        self.pclk = self.sysclk

        self._reset_registers()

    def _reset_registers(self):
        """Reset RCC registers to default values."""
        self.regs = {
            0x00: 0x00000083,  # CR: HSI ON, HSI ready
            0x04: 0x00000000,  # CFGR: HSI as system clock
            0x08: 0x00000000,  # CIR: No interrupts
            0x0C: 0x00000000,  # APB2RSTR
            0x10: 0x00000000,  # APB1RSTR
            0x14: 0x00000014,  # AHBENR: SRAM, FLITF enabled
            0x18: 0x00000000,  # APB2ENR
            0x1C: 0x00000000,  # APB1ENR
            0x20: 0x00000000,  # BDCR
            0x24: 0x0C000000,  # CSR: LSIRDY, reset flags
            0x28: 0x00000000,  # AHBRSTR
            0x2C: 0x00000000,  # CFGR2
            0x30: 0x00000000,  # CFGR3
            0x34: 0x00000000,  # CR2
        }

    def _read_reg(self, offset: int, size: int) -> int:
        """Read RCC register."""
        if offset == 0x00:  # CR
            # Always report HSI ready
            return self.regs.get(offset, 0) | 0x02
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        """Write RCC register."""
        self.regs[offset] = value

        if offset == 0x04:  # CFGR
            # Update clock source status based on SW bits
            sw = value & 0x03
            self.regs[offset] = (value & ~0x0C) | (sw << 2)  # Set SWS = SW

            self.log.debug(f"RCC CFGR: SW={sw}")


class STM32F0xxFLASH(STM32Peripheral):
    """
    STM32F0xx Flash Interface.

    Simplified compared to F4:
    - Single bank
    - 1KB pages (F042) or 2KB pages (larger variants)
    - No dual-bank boot
    """

    def __init__(self, base: int = 0x40022000):
        super().__init__("FLASH", base, 0x400, irq=-1)
        self._reset_registers()

    def _reset_registers(self):
        self.regs = {
            0x00: 0x00000000,  # ACR: No latency, no prefetch
            0x04: 0x00000080,  # KEYR: Locked
            0x08: 0x00000000,  # OPTKEYR
            0x0C: 0x00000000,  # SR: No errors, not busy
            0x10: 0x00000080,  # CR: Locked
            0x14: 0x00000000,  # AR
            0x1C: 0x00FFFF00,  # OBR: Option bytes
            0x20: 0xFFFFFFFF,  # WRPR: Write protection
        }

    def _read_reg(self, offset: int, size: int) -> int:
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == 0x04:  # KEYR - Unlock sequence
            if value == 0x45670123:
                self._key1 = True
            elif value == 0xCDEF89AB and getattr(self, '_key1', False):
                self.regs[0x10] &= ~0x80  # Unlock CR
                self._key1 = False
        else:
            self.regs[offset] = value


class STM32F0xxPWR(STM32Peripheral):
    """STM32F0xx Power Control."""

    def __init__(self, base: int = 0x40007000):
        super().__init__("PWR", base, 0x400, irq=-1)
        self._reset_registers()

    def _reset_registers(self):
        self.regs = {
            0x00: 0x00000000,  # CR
            0x04: 0x00000000,  # CSR
        }


class STM32F0xxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32F0xx family.

    Memory Map:
        0x40000000 - APB1 (TIM2/3/6/7/14, RTC, WWDG, IWDG, SPI2, USART2-4, I2C1/2, USB, PWR, DAC, CEC)
        0x40010000 - APB2 (SYSCFG, EXTI, USART1/6/7/8, ADC, TIM1/15/16/17, SPI1, DBGMCU)
        0x40020000 - AHB1 (DMA, RCC, FLASH, CRC, TSC)
        0x48000000 - AHB2 (GPIO)
    """

    def __init__(self, device: str = "STM32F042", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "F0"
        self.cpu_type = "cortex-m0"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_misc()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32F0xxRCC(base=0x40021000)
        self.add_peripheral(self.rcc)

        self.pwr = STM32F0xxPWR(base=0x40007000)
        self.add_peripheral(self.pwr)

        self.flash = STM32F0xxFLASH(base=0x40022000)
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports (F0 uses GPIOv2 like F4, but at different base)."""
        # F0 GPIO is at 0x48000000 (AHB2), not 0x40020000
        gpio_bases = {
            'A': 0x48000000,
            'B': 0x48000400,
            'C': 0x48000800,
            'F': 0x48001400,  # F0 has limited GPIO
        }

        self.gpio = {}
        for port, base in gpio_bases.items():
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # EXTI
        self.exti = STM32EXTI(base=0x40010400)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals."""
        # USART1 (APB2)
        self.usart1 = STM32USARTv1(index=1, base=0x40013800)
        self.add_peripheral(self.usart1)

        # USART2 (APB1) - not on all F042 variants
        self.usart2 = STM32USARTv1(index=2, base=0x40004400)
        self.add_peripheral(self.usart2)

        # SPI1 (APB2)
        self.spi1 = STM32SPIv1(index=1, base=0x40013000)
        self.add_peripheral(self.spi1)

        # I2C1 (APB1)
        self.i2c1 = STM32I2Cv1(index=1, base=0x40005400)
        self.add_peripheral(self.i2c1)

    def _create_timers(self):
        """Create timer peripherals."""
        # TIM1 - Advanced timer (APB2)
        self.tim1 = STM32GeneralTimer(index=1, base=0x40012C00)
        self.add_peripheral(self.tim1)

        # TIM2 - General purpose (APB1) - 32-bit on F042
        self.tim2 = STM32GeneralTimer(index=2, base=0x40000000)
        self.add_peripheral(self.tim2)

        # TIM3 - General purpose (APB1)
        self.tim3 = STM32GeneralTimer(index=3, base=0x40000400)
        self.add_peripheral(self.tim3)

        # TIM14 - Basic (APB1)
        self.tim14 = STM32BasicTimer(index=14, base=0x40002000)
        self.add_peripheral(self.tim14)

        # TIM16, TIM17 - Basic (APB2)
        self.tim16 = STM32BasicTimer(index=16, base=0x40014400)
        self.tim17 = STM32BasicTimer(index=17, base=0x40014800)
        self.add_peripheral(self.tim16)
        self.add_peripheral(self.tim17)

    def _create_analog(self):
        """Create ADC peripheral."""
        # ADC (APB2) - Single ADC on F042
        self.adc = STM32ADCv1(index=1, base=0x40012400)
        self.add_peripheral(self.adc)

    def _create_dma(self):
        """Create DMA controller."""
        # DMA1 (AHB)
        self.dma1 = STM32DMAv1(index=1, base=0x40020000)
        self.add_peripheral(self.dma1)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        # SYSCFG (APB2)
        self.syscfg = STM32SYSCFG(base=0x40010000, family="F0")
        self.add_peripheral(self.syscfg)

        # Watchdogs
        self.iwdg = STM32IWDG(base=0x40003000)
        self.wwdg = STM32WWDG(base=0x40002C00, family="F0")
        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)

        # CRC (AHB)
        self.crc = STM32CRC(base=0x40023000, family="F0")
        self.add_peripheral(self.crc)

        # Debug
        self.dbg = STM32DBG(base=0x40015800, device="F042")
        self.add_peripheral(self.dbg)


class STM32F042PeripheralSet(STM32F0xxPeripheralSet):
    """
    STM32F042 peripheral set.

    Specifications:
    - Cortex-M0 @ 48 MHz
    - 32 KB Flash
    - 6 KB SRAM
    - USB Device (Crystal-less)
    - CAN (on some variants)

    Used in:
    - Ledger Nano S (MCU)
    - Ledger Nano S Plus (MCU)
    """

    # IRQ numbers for STM32F042
    USB_IRQ = 31

    def __init__(self, variant: str = "K6", log: logging.Logger = None):
        """
        Initialize STM32F042 peripheral set.

        Args:
            variant: Package variant (K6 = LQFP32, G6 = LQFP28, etc.)
            log: Logger instance
        """
        self.variant = variant
        super().__init__(device=f"STM32F042{variant}", log=log)

        # Add USB Device (crystal-less capable)
        self._add_usb()

    def _add_usb(self):
        """Add USB Device peripheral."""
        # USB registers at 0x40005C00, PMA at 0x40006000
        self.usb = STM32USBDevice(base=0x40005C00, irq=self.USB_IRQ)
        self.add_peripheral(self.usb)
        self.log.info("USB Device peripheral added (crystal-less)")


class STM32F072PeripheralSet(STM32F0xxPeripheralSet):
    """
    STM32F072 peripheral set.

    Specifications:
    - Cortex-M0 @ 48 MHz
    - 128 KB Flash
    - 16 KB SRAM
    - USB Device
    - CAN
    - DAC
    - More GPIO
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32F072", log=log)

        # Additional GPIO ports
        for port, base in [('D', 0x48000C00), ('E', 0x48001000)]:
            self.gpio[port] = STM32GPIOv2(port=port, base=base)
            self.add_peripheral(self.gpio[port])

        # USB
        self.usb = STM32USBDevice(base=0x40005C00, irq=31)
        self.add_peripheral(self.usb)

        # Additional I2C
        self.i2c2 = STM32I2Cv1(index=2, base=0x40005800)
        self.add_peripheral(self.i2c2)

        # SPI2
        self.spi2 = STM32SPIv1(index=2, base=0x40003800)
        self.add_peripheral(self.spi2)


# Convenience function for Ledger Nano S emulation
def create_ledger_nano_s_mcu(log: logging.Logger = None) -> STM32F042PeripheralSet:
    """
    Create peripheral set configured for Ledger Nano S MCU.

    The Ledger Nano S uses:
    - STM32F042K6 as MCU (this function)
    - ST31H320 as Secure Element (separate emulation needed)

    Communication between MCU and SE uses SEPROXYHAL protocol over UART.
    """
    ps = STM32F042PeripheralSet(variant="K6", log=log)

    # Configure for Ledger use case:
    # - USART for SE communication (SEPROXYHAL)
    # - USB for host communication
    # - I2C for OLED display
    # - GPIO for buttons

    return ps
