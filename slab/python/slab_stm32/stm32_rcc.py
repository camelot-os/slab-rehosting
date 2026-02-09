"""
STM32 RCC (Reset and Clock Control) Peripheral Emulation

Implements clock controllers for different STM32 families:
- RCCv1: F1xx
- RCCv2: F4xx
- RCCv3: L4xx
- RCCv4: H7xx

References:
- RM0008 (F1xx), RM0090 (F4xx), RM0351 (L4xx), RM0433 (H7xx)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32RCCBase(STM32Peripheral):
    """Base class for STM32 RCC peripherals."""

    def __init__(self, name: str, base: int, size: int = 0x400):
        super().__init__(name, base, size)
        self.hsi_freq = 8_000_000   # Internal RC oscillator
        self.hse_freq = 8_000_000   # External crystal
        self.lsi_freq = 32_000      # Low-speed internal
        self.lse_freq = 32_768      # Low-speed external
        self.sysclk = self.hsi_freq
        self.hclk = self.hsi_freq
        self.pclk1 = self.hsi_freq
        self.pclk2 = self.hsi_freq

    def get_sysclk(self) -> int:
        return self.sysclk

    def get_hclk(self) -> int:
        return self.hclk

    def get_pclk1(self) -> int:
        return self.pclk1

    def get_pclk2(self) -> int:
        return self.pclk2


class STM32RCCv1(STM32RCCBase):
    """
    STM32F1xx RCC.

    Register Map:
        0x00: CR       - Clock control
        0x04: CFGR     - Clock configuration
        0x08: CIR      - Clock interrupt
        0x0C: APB2RSTR - APB2 peripheral reset
        0x10: APB1RSTR - APB1 peripheral reset
        0x14: AHBENR   - AHB peripheral enable
        0x18: APB2ENR  - APB2 peripheral enable
        0x1C: APB1ENR  - APB1 peripheral enable
        0x20: BDCR     - Backup domain control
        0x24: CSR      - Control/status
    """

    CR = 0x00
    CFGR = 0x04
    CIR = 0x08
    APB2RSTR = 0x0C
    APB1RSTR = 0x10
    AHBENR = 0x14
    APB2ENR = 0x18
    APB1ENR = 0x1C
    BDCR = 0x20
    CSR = 0x24

    # CR bits
    CR_HSION = 1 << 0
    CR_HSIRDY = 1 << 1
    CR_HSEON = 1 << 16
    CR_HSERDY = 1 << 17
    CR_PLLON = 1 << 24
    CR_PLLRDY = 1 << 25

    def __init__(self, base: int = 0x40021000):
        super().__init__("RCC", base)

        # Registers
        self.cr = self.CR_HSIRDY | self.CR_HSION  # HSI on and ready
        self.cfgr = 0
        self.cir = 0
        self.apb2rstr = 0
        self.apb1rstr = 0
        self.ahbenr = 0
        self.apb2enr = 0
        self.apb1enr = 0
        self.bdcr = 0
        self.csr = 0x0C000000  # LSIRDY set

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self._get_cr()
        elif offset == self.CFGR:
            return self.cfgr
        elif offset == self.CIR:
            return self.cir
        elif offset == self.APB2RSTR:
            return self.apb2rstr
        elif offset == self.APB1RSTR:
            return self.apb1rstr
        elif offset == self.AHBENR:
            return self.ahbenr
        elif offset == self.APB2ENR:
            return self.apb2enr
        elif offset == self.APB1ENR:
            return self.apb1enr
        elif offset == self.BDCR:
            return self.bdcr
        elif offset == self.CSR:
            return self.csr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.CFGR:
            self.cfgr = value
            self._update_clocks()
        elif offset == self.CIR:
            self.cir &= ~(value & 0x009F0000)  # Clear interrupt flags
        elif offset == self.APB2RSTR:
            self.apb2rstr = value
        elif offset == self.APB1RSTR:
            self.apb1rstr = value
        elif offset == self.AHBENR:
            self.ahbenr = value
        elif offset == self.APB2ENR:
            self.apb2enr = value
        elif offset == self.APB1ENR:
            self.apb1enr = value
        elif offset == self.BDCR:
            self.bdcr = value
        elif offset == self.CSR:
            if value & (1 << 24):  # RMVF - clear reset flags
                self.csr &= 0x00FFFFFF

    def _get_cr(self) -> int:
        cr = self.cr
        # Auto-set ready flags
        if cr & self.CR_HSION:
            cr |= self.CR_HSIRDY
        if cr & self.CR_HSEON:
            cr |= self.CR_HSERDY
        if cr & self.CR_PLLON:
            cr |= self.CR_PLLRDY
        return cr

    def _update_clocks(self):
        """Update clock frequencies based on CFGR."""
        # SW - System clock switch
        sw = self.cfgr & 0x3
        if sw == 0:
            self.sysclk = self.hsi_freq
        elif sw == 1:
            self.sysclk = self.hse_freq
        elif sw == 2:
            # PLL
            pllmul = ((self.cfgr >> 18) & 0xF) + 2
            if pllmul > 16:
                pllmul = 16
            pllsrc = (self.cfgr >> 16) & 1
            if pllsrc == 0:
                self.sysclk = (self.hsi_freq // 2) * pllmul
            else:
                self.sysclk = self.hse_freq * pllmul

        # Update SWS
        self.cfgr = (self.cfgr & ~0x0C) | (sw << 2)

        # AHB prescaler
        hpre = (self.cfgr >> 4) & 0xF
        if hpre < 8:
            self.hclk = self.sysclk
        else:
            self.hclk = self.sysclk >> (hpre - 7)

        # APB1 prescaler
        ppre1 = (self.cfgr >> 8) & 0x7
        if ppre1 < 4:
            self.pclk1 = self.hclk
        else:
            self.pclk1 = self.hclk >> (ppre1 - 3)

        # APB2 prescaler
        ppre2 = (self.cfgr >> 11) & 0x7
        if ppre2 < 4:
            self.pclk2 = self.hclk
        else:
            self.pclk2 = self.hclk >> (ppre2 - 3)


class STM32RCCv2(STM32RCCBase):
    """
    STM32F4xx RCC.

    Additional features:
    - PLL with VCO configuration (PLLM, PLLN, PLLP, PLLQ)
    - More peripheral enables (AHB1/2/3, APB1/2)
    """

    CR = 0x00
    PLLCFGR = 0x04
    CFGR = 0x08
    CIR = 0x0C
    AHB1RSTR = 0x10
    AHB2RSTR = 0x14
    AHB3RSTR = 0x18
    APB1RSTR = 0x20
    APB2RSTR = 0x24
    AHB1ENR = 0x30
    AHB2ENR = 0x34
    AHB3ENR = 0x38
    APB1ENR = 0x40
    APB2ENR = 0x44
    AHB1LPENR = 0x50
    AHB2LPENR = 0x54
    AHB3LPENR = 0x58
    APB1LPENR = 0x60
    APB2LPENR = 0x64
    BDCR = 0x70
    CSR = 0x74
    SSCGR = 0x80
    PLLI2SCFGR = 0x84

    # CR bits
    CR_HSION = 1 << 0
    CR_HSIRDY = 1 << 1
    CR_HSEON = 1 << 16
    CR_HSERDY = 1 << 17
    CR_PLLON = 1 << 24
    CR_PLLRDY = 1 << 25
    CR_PLLI2SON = 1 << 26
    CR_PLLI2SRDY = 1 << 27

    def __init__(self, base: int = 0x40023800):
        super().__init__("RCC", base)
        self.hsi_freq = 16_000_000  # F4 has 16MHz HSI

        # Registers
        self.cr = self.CR_HSIRDY | self.CR_HSION
        self.pllcfgr = 0x24003010  # Default PLL config
        self.cfgr = 0
        self.cir = 0
        self.ahb1rstr = 0
        self.ahb2rstr = 0
        self.ahb3rstr = 0
        self.apb1rstr = 0
        self.apb2rstr = 0
        self.ahb1enr = 0
        self.ahb2enr = 0
        self.ahb3enr = 0
        self.apb1enr = 0
        self.apb2enr = 0
        self.bdcr = 0
        self.csr = 0x0E000000

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self._get_cr()
        elif offset == self.PLLCFGR:
            return self.pllcfgr
        elif offset == self.CFGR:
            return self.cfgr
        elif offset == self.CIR:
            return self.cir
        elif offset == self.AHB1RSTR:
            return self.ahb1rstr
        elif offset == self.AHB2RSTR:
            return self.ahb2rstr
        elif offset == self.AHB3RSTR:
            return self.ahb3rstr
        elif offset == self.APB1RSTR:
            return self.apb1rstr
        elif offset == self.APB2RSTR:
            return self.apb2rstr
        elif offset == self.AHB1ENR:
            return self.ahb1enr
        elif offset == self.AHB2ENR:
            return self.ahb2enr
        elif offset == self.AHB3ENR:
            return self.ahb3enr
        elif offset == self.APB1ENR:
            return self.apb1enr
        elif offset == self.APB2ENR:
            return self.apb2enr
        elif offset == self.BDCR:
            return self.bdcr
        elif offset == self.CSR:
            return self.csr
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.PLLCFGR:
            self.pllcfgr = value
        elif offset == self.CFGR:
            self.cfgr = value
            self._update_clocks()
        elif offset == self.AHB1ENR:
            self.ahb1enr = value
        elif offset == self.AHB2ENR:
            self.ahb2enr = value
        elif offset == self.AHB3ENR:
            self.ahb3enr = value
        elif offset == self.APB1ENR:
            self.apb1enr = value
        elif offset == self.APB2ENR:
            self.apb2enr = value
        elif offset == self.BDCR:
            self.bdcr = value
        elif offset == self.CSR:
            if value & (1 << 24):
                self.csr &= 0x00FFFFFF
        else:
            self.regs[offset] = value

    def _get_cr(self) -> int:
        cr = self.cr
        if cr & self.CR_HSION:
            cr |= self.CR_HSIRDY
        if cr & self.CR_HSEON:
            cr |= self.CR_HSERDY
        if cr & self.CR_PLLON:
            cr |= self.CR_PLLRDY
        if cr & self.CR_PLLI2SON:
            cr |= self.CR_PLLI2SRDY
        return cr

    def _update_clocks(self):
        """Update clock frequencies based on PLL and CFGR."""
        sw = self.cfgr & 0x3

        if sw == 0:
            self.sysclk = self.hsi_freq
        elif sw == 1:
            self.sysclk = self.hse_freq
        elif sw == 2:
            # PLL calculation
            pllm = self.pllcfgr & 0x3F
            plln = (self.pllcfgr >> 6) & 0x1FF
            pllp = ((self.pllcfgr >> 16) & 0x3) * 2 + 2
            pllsrc = (self.pllcfgr >> 22) & 1

            if pllsrc == 0:
                vco_in = self.hsi_freq // pllm
            else:
                vco_in = self.hse_freq // pllm

            vco_out = vco_in * plln
            self.sysclk = vco_out // pllp

        self.cfgr = (self.cfgr & ~0x0C) | (sw << 2)

        # Prescalers
        hpre = (self.cfgr >> 4) & 0xF
        if hpre < 8:
            self.hclk = self.sysclk
        else:
            self.hclk = self.sysclk >> (hpre - 7)

        ppre1 = (self.cfgr >> 10) & 0x7
        if ppre1 < 4:
            self.pclk1 = self.hclk
        else:
            self.pclk1 = self.hclk >> (ppre1 - 3)

        ppre2 = (self.cfgr >> 13) & 0x7
        if ppre2 < 4:
            self.pclk2 = self.hclk
        else:
            self.pclk2 = self.hclk >> (ppre2 - 3)


class STM32RCCv3(STM32RCCBase):
    """
    STM32L4xx/WBxx RCC.

    Register layout per RM0434 (WB55) / RM0351 (L4xx).
    Used for L4xx, U5xx, and WBxx families which share similar RCC architecture.

    Auto-ready logic: when firmware enables a clock (MSION, HSION, PLLON etc.),
    the corresponding RDY bit is returned immediately on read.
    """

    # Register offsets
    CR = 0x00
    ICSCR = 0x04
    CFGR = 0x08
    PLLCFGR = 0x0C
    PLLSAI1CFGR = 0x10
    CIER = 0x18
    CIFR = 0x1C
    CICR = 0x20
    AHB1RSTR = 0x28
    AHB2RSTR = 0x2C
    AHB3RSTR = 0x30
    APB1RSTR1 = 0x38
    APB1RSTR2 = 0x3C
    APB2RSTR = 0x40
    AHB1ENR = 0x48
    AHB2ENR = 0x4C
    AHB3ENR = 0x50
    APB1ENR1 = 0x58
    APB1ENR2 = 0x5C
    APB2ENR = 0x60
    CCIPR = 0x88
    BDCR = 0x90
    CSR = 0x94
    CRRCR = 0x98
    HSECR = 0x9C
    EXTCFGR = 0x108

    # CR bits
    CR_MSION = 1 << 0
    CR_MSIRDY = 1 << 1
    CR_HSION = 1 << 8
    CR_HSIRDY = 1 << 10
    CR_HSIKERDY = 1 << 12
    CR_HSEON = 1 << 16
    CR_HSERDY = 1 << 17
    CR_PLLON = 1 << 24
    CR_PLLRDY = 1 << 25
    CR_PLLSAI1ON = 1 << 26
    CR_PLLSAI1RDY = 1 << 27

    # CRRCR bits
    CRRCR_HSI48ON = 1 << 0
    CRRCR_HSI48RDY = 1 << 1

    # CSR bits
    CSR_LSION = 1 << 0
    CSR_LSIRDY = 1 << 1

    # BDCR bits
    BDCR_LSEON = 1 << 0
    BDCR_LSERDY = 1 << 1

    def __init__(self, base: int = 0x40021000):
        super().__init__("RCC", base)
        self.msi_freq = 4_000_000   # MSI default 4MHz (range 6)
        self.hsi_freq = 16_000_000

        # CR: MSI on and ready, MSIRANGE=0110 (4MHz) -- RM0434 reset=0x00000061
        self.cr = 0x00000063
        self.icscr = 0x00400000
        self.cfgr = 0x00070000       # RM0434: MCOSEL=111 at reset
        self.pllcfgr = 0x22041000    # RM0434: default PLL config
        self.pllsai1cfgr = 0x22041000
        self.cier = 0
        self.cifr = 0
        self.ahb1enr = 0
        self.ahb2enr = 0
        self.ahb3enr = 0
        self.apb1enr1 = 0
        self.apb1enr2 = 0
        self.apb2enr = 0
        self.ccipr = 0
        self.bdcr = 0
        self.csr = self.CSR_LSION | self.CSR_LSIRDY
        self.crrcr = 0
        self.hsecr = 0
        self.extcfgr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self._get_cr()
        elif offset == self.ICSCR:
            return self.icscr
        elif offset == self.CFGR:
            return self._get_cfgr()
        elif offset == self.PLLCFGR:
            return self.pllcfgr
        elif offset == self.PLLSAI1CFGR:
            return self.pllsai1cfgr
        elif offset == self.CIER:
            return self.cier
        elif offset == self.CIFR:
            return self.cifr
        elif offset == self.AHB1ENR:
            return self.ahb1enr
        elif offset == self.AHB2ENR:
            return self.ahb2enr
        elif offset == self.AHB3ENR:
            return self.ahb3enr
        elif offset == self.APB1ENR1:
            return self.apb1enr1
        elif offset == self.APB1ENR2:
            return self.apb1enr2
        elif offset == self.APB2ENR:
            return self.apb2enr
        elif offset == self.CCIPR:
            return self.ccipr
        elif offset == self.BDCR:
            return self._get_bdcr()
        elif offset == self.CSR:
            return self._get_csr()
        elif offset == self.CRRCR:
            return self._get_crrcr()
        elif offset == self.HSECR:
            return self.hsecr
        elif offset == self.EXTCFGR:
            return self._get_extcfgr()
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.ICSCR:
            self.icscr = value
        elif offset == self.CFGR:
            self.cfgr = value
            self._update_clocks()
        elif offset == self.PLLCFGR:
            self.pllcfgr = value
        elif offset == self.PLLSAI1CFGR:
            self.pllsai1cfgr = value
        elif offset == self.CIER:
            self.cier = value
        elif offset == self.CICR:
            self.cifr &= ~value  # Clear interrupt flags
        elif offset == self.AHB1ENR:
            self.ahb1enr = value
        elif offset == self.AHB2ENR:
            self.ahb2enr = value
        elif offset == self.AHB3ENR:
            self.ahb3enr = value
        elif offset == self.APB1ENR1:
            self.apb1enr1 = value
        elif offset == self.APB1ENR2:
            self.apb1enr2 = value
        elif offset == self.APB2ENR:
            self.apb2enr = value
        elif offset == self.CCIPR:
            self.ccipr = value
        elif offset == self.BDCR:
            self.bdcr = value
        elif offset == self.CSR:
            if value & (1 << 23):  # RMVF - clear reset flags
                self.csr &= 0x00FFFFFF
            else:
                self.csr = value
        elif offset == self.CRRCR:
            self.crrcr = value
        elif offset == self.HSECR:
            self.hsecr = value
        elif offset == self.EXTCFGR:
            self.extcfgr = value
        else:
            self.regs[offset] = value

    def _get_cr(self) -> int:
        """Read CR with auto-ready bits."""
        cr = self.cr
        if cr & self.CR_MSION:
            cr |= self.CR_MSIRDY
        if cr & self.CR_HSION:
            cr |= self.CR_HSIRDY | self.CR_HSIKERDY
        if cr & self.CR_HSEON:
            cr |= self.CR_HSERDY
        if cr & self.CR_PLLON:
            cr |= self.CR_PLLRDY
        if cr & self.CR_PLLSAI1ON:
            cr |= self.CR_PLLSAI1RDY
        return cr

    def _get_cfgr(self) -> int:
        """Read CFGR with prescaler-ready flags.

        Per RM0434: HPREF (bit 16), PPRE1F (bit 17), PPRE2F (bit 18) are
        read-only status bits indicating prescaler change has taken effect.
        In emulation, prescaler changes are instant so these are always set.
        """
        cfgr = self.cfgr
        # Always set prescaler-ready flags (instant in emulation)
        cfgr |= (1 << 16) | (1 << 17) | (1 << 18)
        return cfgr

    def _get_bdcr(self) -> int:
        """Read BDCR with LSE auto-ready."""
        bdcr = self.bdcr
        if bdcr & self.BDCR_LSEON:
            bdcr |= self.BDCR_LSERDY
        return bdcr

    def _get_csr(self) -> int:
        """Read CSR with LSI auto-ready."""
        csr = self.csr
        if csr & self.CSR_LSION:
            csr |= self.CSR_LSIRDY
        return csr

    def _get_crrcr(self) -> int:
        """Read CRRCR with HSI48 auto-ready."""
        crrcr = self.crrcr
        if crrcr & self.CRRCR_HSI48ON:
            crrcr |= self.CRRCR_HSI48RDY
        return crrcr

    def _get_extcfgr(self) -> int:
        """Read EXTCFGR with prescaler ready flags.

        Per CMSIS stm32wb35xx.h / stm32wb55xx.h:
          SHDHPRE[3:0]  = bits [3:0]   (Shared AHB prescaler)
          C2HPRE[3:0]   = bits [7:4]   (CPU2 AHB prescaler)
          SHDHPREF       = bit 16       (Shared prescaler applied, read-only)
          C2HPREF        = bit 17       (CPU2 prescaler applied, read-only)
          RFCSS          = bit 20       (RF clock source selection)
        """
        val = self.extcfgr
        # Always set prescaler-ready flags (instant in emulation)
        val |= (1 << 16) | (1 << 17)
        return val

    def _update_clocks(self):
        """Update clock frequencies and SWS based on CFGR."""
        sw = self.cfgr & 0x3

        if sw == 0:
            self.sysclk = self.msi_freq
        elif sw == 1:
            self.sysclk = self.hsi_freq
        elif sw == 2:
            self.sysclk = self.hse_freq
        elif sw == 3:
            # PLL: VCO = (src / PLLM) * PLLN, SYSCLK = VCO / PLLR
            pllm = ((self.pllcfgr >> 4) & 0x7) + 1
            plln = (self.pllcfgr >> 8) & 0x7F
            pllr = (((self.pllcfgr >> 25) & 0x3) + 1) * 2
            pllsrc = self.pllcfgr & 0x3
            if pllsrc == 1:
                vco_in = self.msi_freq // pllm
            elif pllsrc == 2:
                vco_in = self.hsi_freq // pllm
            elif pllsrc == 3:
                vco_in = self.hse_freq // pllm
            else:
                vco_in = 0
            if vco_in > 0 and plln > 0 and pllr > 0:
                self.sysclk = (vco_in * plln) // pllr

        # Auto-update SWS to match SW
        self.cfgr = (self.cfgr & ~0x0C) | (sw << 2)

        # AHB prescaler
        hpre = (self.cfgr >> 4) & 0xF
        if hpre < 8:
            self.hclk = self.sysclk
        else:
            self.hclk = self.sysclk >> (hpre - 7)

        # APB1 prescaler
        ppre1 = (self.cfgr >> 8) & 0x7
        if ppre1 < 4:
            self.pclk1 = self.hclk
        else:
            self.pclk1 = self.hclk >> (ppre1 - 3)

        # APB2 prescaler
        ppre2 = (self.cfgr >> 11) & 0x7
        if ppre2 < 4:
            self.pclk2 = self.hclk
        else:
            self.pclk2 = self.hclk >> (ppre2 - 3)


class STM32RCCv4(STM32RCCBase):
    """
    STM32H5xx RCC - Complex clock tree for H5 family.

    Register layout from STM32H563 reference manual (RM0481).
    Base address: 0x44020C00 (non-secure) / 0x54020C00 (secure alias)
    """

    # Register offsets (H5)
    CR = 0x00           # Clock control
    HSICFGR = 0x10      # HSI calibration
    CRRCR = 0x14        # Clock recovery RC
    CSICFGR = 0x18      # CSI calibration
    CFGR1 = 0x1C        # Clock config 1 (SW/SWS)
    CFGR2 = 0x20        # Clock config 2 (prescalers)
    PLL1CFGR = 0x28     # PLL1 configuration
    PLL2CFGR = 0x2C     # PLL2 configuration
    PLL3CFGR = 0x30     # PLL3 configuration
    PLL1DIVR = 0x34     # PLL1 dividers
    PLL1FRACR = 0x38    # PLL1 fractional
    PLL2DIVR = 0x3C     # PLL2 dividers
    PLL2FRACR = 0x40    # PLL2 fractional
    PLL3DIVR = 0x44     # PLL3 dividers
    PLL3FRACR = 0x48    # PLL3 fractional
    CIER = 0x50         # Clock interrupt enable
    CIFR = 0x54         # Clock interrupt flag
    CICR = 0x58         # Clock interrupt clear
    AHB1ENR = 0x88      # AHB1 clock enable
    AHB2ENR = 0x8C      # AHB2 clock enable
    AHB4ENR = 0x94      # AHB4 clock enable (GPIO clocks)
    APB1LENR = 0x9C     # APB1 low clock enable
    APB1HENR = 0xA0     # APB1 high clock enable
    APB2ENR = 0xA4      # APB2 clock enable
    APB3ENR = 0xA8      # APB3 clock enable
    CCIPR4 = 0xE4       # Clock source for SysTick, other peripherals
    CCIPR5 = 0xE8       # Additional clock config
    BDCR = 0xF0         # Backup domain control (LSE) -- RM0481
    CSR = 0xF4          # Clock status register (LSI) -- RM0481

    # CR bits (from STM32H563 SVD)
    CR_HSION = 1 << 0       # HSI enable
    CR_HSIRDY = 1 << 1      # HSI ready
    CR_HSIKERON = 1 << 2    # HSI keep on in stop
    CR_HSIDIV = 0x3 << 3    # HSI divider (2 bits)
    CR_HSIDIVF = 1 << 5     # HSI divider flag
    CR_CSION = 1 << 8       # CSI enable
    CR_CSIRDY = 1 << 9      # CSI ready
    CR_CSIKERON = 1 << 10   # CSI keep on in stop
    CR_HSI48ON = 1 << 12    # HSI48 enable
    CR_HSI48RDY = 1 << 13   # HSI48 ready
    CR_HSEON = 1 << 16      # HSE enable
    CR_HSERDY = 1 << 17     # HSE ready
    CR_HSEBYP = 1 << 18     # HSE bypass
    CR_HSECSSON = 1 << 19   # HSE CSS enable
    CR_HSEEXT = 1 << 20     # HSE external
    CR_PLL1ON = 1 << 24     # PLL1 enable
    CR_PLL1RDY = 1 << 25    # PLL1 ready
    CR_PLL2ON = 1 << 26     # PLL2 enable
    CR_PLL2RDY = 1 << 27    # PLL2 ready
    CR_PLL3ON = 1 << 28     # PLL3 enable
    CR_PLL3RDY = 1 << 29    # PLL3 ready

    # CFGR1 bits
    CFGR1_SW_MASK = 0x7     # System clock switch (3 bits)
    CFGR1_SWS_SHIFT = 3     # System clock switch status position
    CFGR1_SWS_MASK = 0x7 << 3

    # Clock sources
    CLK_HSI = 0
    CLK_CSI = 1
    CLK_HSE = 2
    CLK_PLL1 = 3

    # BDCR bits (LSE control)
    BDCR_LSEON = 1 << 0     # LSE enable
    BDCR_LSERDY = 1 << 1    # LSE ready
    BDCR_LSEBYP = 1 << 2    # LSE bypass

    # CSR bits (LSI control)
    CSR_LSION = 1 << 0      # LSI enable
    CSR_LSIRDY = 1 << 1     # LSI ready

    def __init__(self, base: int = 0x44020C00):
        super().__init__("RCC", base, 0x400)
        self.hsi_freq = 64_000_000  # H5 has 64MHz HSI
        self._read_counts = {}  # Track read counts for polling detection
        self._poll_threshold = 5  # Auto-ready after N polls
        self._reset_registers()

    def _reset_registers(self):
        """Initialize RCC with default values.

        Start with minimal clocks (HSI only). The auto-ready logic in
        _write_reg will set ready bits when firmware enables clocks.
        """
        # CR: Only HSI on and ready initially (default boot state)
        # Other clocks will be enabled by firmware and auto-ready
        self.regs[self.CR] = (
            self.CR_HSION | self.CR_HSIRDY | self.CR_HSIDIVF |
            self.CR_HSI48ON | self.CR_HSI48RDY  # HSI48 often used
        )

        # CFGR1: HSI as system clock initially (SW=0, SWS=0)
        self.regs[self.CFGR1] = 0x00000000

        # CFGR2: Default prescalers
        self.regs[self.CFGR2] = 0x00000000

        # PLL configs - unconfigured initially
        self.regs[self.PLL1CFGR] = 0x00000000
        self.regs[self.PLL2CFGR] = 0x00000000
        self.regs[self.PLL3CFGR] = 0x00000000

        # PLL dividers - set sensible defaults
        self.regs[self.PLL1DIVR] = 0x01010280  # N=129, P=2, Q=2, R=2
        self.regs[self.PLL2DIVR] = 0x01010280
        self.regs[self.PLL3DIVR] = 0x01010280

        # Enable registers (all disabled by default)
        self.regs[self.AHB1ENR] = 0
        self.regs[self.AHB2ENR] = 0
        self.regs[self.AHB4ENR] = 0
        self.regs[self.APB1LENR] = 0
        self.regs[self.APB1HENR] = 0
        self.regs[self.APB2ENR] = 0
        self.regs[self.APB3ENR] = 0

        # Clock source configuration (CCIPR4 contains SYSTICKSEL)
        self.regs[self.CCIPR4] = 0
        self.regs[self.CCIPR5] = 0

        # BDCR: LSE initially off
        self.regs[self.BDCR] = 0

        # CSR: LSI on and ready (often needed early)
        self.regs[self.CSR] = self.CSR_LSION | self.CSR_LSIRDY

    def _read_reg(self, offset: int, size: int) -> int:
        """Read RCC register with polling detection and auto-ready.

        Based on Z3 bootloop solver analysis: when firmware polls a status
        register repeatedly, auto-set the expected ready bits to break
        the polling loop.
        """
        # Track read counts for polling detection
        self._read_counts[offset] = self._read_counts.get(offset, 0) + 1
        count = self._read_counts[offset]

        value = self.regs.get(offset, 0)

        # Auto-ready logic when polling detected
        if count >= self._poll_threshold:
            if offset == self.CR:
                # Set all ready bits for enabled clocks (Z3 pattern)
                if value & self.CR_HSION:
                    value |= self.CR_HSIRDY | self.CR_HSIDIVF
                if value & self.CR_CSION:
                    value |= self.CR_CSIRDY
                if value & self.CR_HSI48ON:
                    value |= self.CR_HSI48RDY
                if value & self.CR_HSEON:
                    value |= self.CR_HSERDY
                if value & self.CR_PLL1ON:
                    value |= self.CR_PLL1RDY
                if value & self.CR_PLL2ON:
                    value |= self.CR_PLL2RDY
                if value & self.CR_PLL3ON:
                    value |= self.CR_PLL3RDY
                self.regs[self.CR] = value

            elif offset == self.CFGR1:
                # SWS must match SW (Z3 pattern)
                sw = value & self.CFGR1_SW_MASK
                value = (value & ~self.CFGR1_SWS_MASK) | (sw << self.CFGR1_SWS_SHIFT)
                self.regs[self.CFGR1] = value

            elif offset == self.CFGR2:
                # Set prescaler ready bit (Z3 solved to 0x00000002)
                value |= (1 << 1)
                self.regs[self.CFGR2] = value

            elif offset == self.CSR:
                # LSI ready (Z3 pattern)
                if value & self.CSR_LSION:
                    value |= self.CSR_LSIRDY
                self.regs[self.CSR] = value

            elif offset == self.BDCR:
                # LSE ready
                if value & self.BDCR_LSEON:
                    value |= self.BDCR_LSERDY
                self.regs[self.BDCR] = value

            # Reset count after auto-ready applied
            if count == self._poll_threshold:
                self.log.debug(f"RCC polling detected @ 0x{offset:02X}, auto-ready applied")

        self.log.debug(f"RCC read offset 0x{offset:02X} = 0x{value:08X}")
        return value

    def _write_reg(self, offset: int, size: int, value: int):
        self.log.debug(f"RCC write offset 0x{offset:02X} = 0x{value:08X}")

        if offset == self.CR:
            # Auto-set RDY bits when ON bits are set (instant clock ready)
            if value & self.CR_HSION:
                value |= self.CR_HSIRDY | self.CR_HSIDIVF
            if value & self.CR_CSION:
                value |= self.CR_CSIRDY
            if value & self.CR_HSI48ON:
                value |= self.CR_HSI48RDY
            if value & self.CR_HSEON:
                value |= self.CR_HSERDY
            if value & self.CR_PLL1ON:
                value |= self.CR_PLL1RDY
            if value & self.CR_PLL2ON:
                value |= self.CR_PLL2RDY
            if value & self.CR_PLL3ON:
                value |= self.CR_PLL3RDY
            self.log.debug(f"RCC CR after ready bits: 0x{value:08X}")

        elif offset == self.CFGR1:
            # Auto-update SWS to match SW (instant clock switch)
            sw = value & self.CFGR1_SW_MASK
            value = (value & ~self.CFGR1_SWS_MASK) | (sw << self.CFGR1_SWS_SHIFT)
            self.log.debug(f"RCC CFGR1 SW={sw}, SWS updated: 0x{value:08X}")

        elif offset == self.BDCR:
            # Auto-set LSERDY when LSEON is set
            if value & self.BDCR_LSEON:
                value |= self.BDCR_LSERDY

        elif offset == self.CSR:
            # Auto-set LSIRDY when LSION is set
            if value & self.CSR_LSION:
                value |= self.CSR_LSIRDY

        self.regs[offset] = value


class STM32RCCv5(STM32RCCBase):
    """
    STM32U5xx RCC (RM0456).

    Register layout uses CFGR1/CFGR2/CFGR3 and PLL1-PLL3,
    similar to H5 but with MSIS/MSIK oscillators instead of CSI.
    All registers stored in self.regs dict; only critical offsets
    have auto-ready logic.
    """

    # Register offsets
    CR = 0x00
    ICSCR1 = 0x08
    ICSCR2 = 0x0C
    ICSCR3 = 0x10
    CRRCR = 0x18
    CFGR1 = 0x1C
    CFGR2 = 0x20
    CFGR3 = 0x24
    PLL1CFGR = 0x28
    PLL2CFGR = 0x2C
    PLL3CFGR = 0x30
    PLL1DIVR = 0x34
    PLL1FRACR = 0x38
    PLL2DIVR = 0x3C
    PLL2FRACR = 0x40
    PLL3DIVR = 0x44
    PLL3FRACR = 0x48
    CIER = 0x50
    CIFR = 0x54
    CICR = 0x58
    AHB1ENR = 0x88
    AHB2ENR1 = 0x8C
    AHB2ENR2 = 0x90
    AHB3ENR = 0x94
    APB1ENR1 = 0x9C
    APB1ENR2 = 0xA0
    APB2ENR = 0xA4
    APB3ENR = 0xA8
    CCIPR1 = 0xE0
    CCIPR2 = 0xE4
    CCIPR3 = 0xE8
    BDCR = 0xF0
    CSR = 0xF4

    # CR bits (RM0456 RCC_CR)
    CR_MSISON = 1 << 0
    CR_MSIKERON = 1 << 1
    CR_MSISRDY = 1 << 2
    CR_MSIKON = 1 << 3
    CR_MSIPLLMODE = 1 << 4
    CR_MSIPLLFAST = 1 << 5
    CR_MSIKRDY = 1 << 7
    CR_HSION = 1 << 8
    CR_HSIKERON = 1 << 9
    CR_HSIRDY = 1 << 10
    CR_HSI48ON = 1 << 12
    CR_HSI48RDY = 1 << 13
    CR_SHSION = 1 << 14
    CR_SHSIRDY = 1 << 15
    CR_HSEON = 1 << 16
    CR_HSERDY = 1 << 17
    CR_PLL1ON = 1 << 24
    CR_PLL1RDY = 1 << 25
    CR_PLL2ON = 1 << 26
    CR_PLL2RDY = 1 << 27
    CR_PLL3ON = 1 << 28
    CR_PLL3RDY = 1 << 29

    # CFGR1 bits (SW 2-bit, SWS at bits 3:2)
    CFGR1_SW_MASK = 0x3
    CFGR1_SWS_SHIFT = 2
    CFGR1_SWS_MASK = 0x3 << 2

    # CFGR2 prescaler ready flags
    CFGR2_HPREF = 1 << 16
    CFGR2_PPRE1F = 1 << 17
    CFGR2_PPRE2F = 1 << 18

    # BDCR bits
    BDCR_LSEON = 1 << 0
    BDCR_LSERDY = 1 << 1

    # CSR bits
    CSR_LSION = 1 << 0
    CSR_LSIRDY = 1 << 1

    def __init__(self, base: int = 0x46020C00):
        super().__init__("RCC", base, 0x400)
        self.hsi_freq = 16_000_000
        self.msi_freq = 4_000_000
        self._init_regs()

    def _init_regs(self):
        """Initialize with reset defaults."""
        # CR: MSIS on and ready at reset (RM0456 reset value = 0x00000035)
        self.regs[self.CR] = (
            self.CR_MSISON | self.CR_MSISRDY |
            self.CR_MSIKON | self.CR_MSIKRDY |
            self.CR_MSIPLLMODE | self.CR_MSIPLLFAST
        )
        self.regs[self.ICSCR1] = 0x44000000  # MSIRANGE=4 (4MHz)
        self.regs[self.CFGR1] = 0
        self.regs[self.CFGR2] = 0
        self.regs[self.CFGR3] = 0
        self.regs[self.BDCR] = 0
        self.regs[self.CSR] = self.CSR_LSION | self.CSR_LSIRDY

    def _read_reg(self, offset: int, size: int) -> int:
        value = self.regs.get(offset, 0)

        if offset == self.CR:
            value = self._apply_cr_ready(value)
        elif offset == self.CFGR2:
            # Auto-set prescaler ready flags (instant)
            value |= self.CFGR2_HPREF | self.CFGR2_PPRE1F | self.CFGR2_PPRE2F
        elif offset == self.BDCR:
            if value & self.BDCR_LSEON:
                value |= self.BDCR_LSERDY
        elif offset == self.CSR:
            if value & self.CSR_LSION:
                value |= self.CSR_LSIRDY

        return value

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            value = self._apply_cr_ready(value)
        elif offset == self.CFGR1:
            # Auto-update SWS to match SW (instant clock switch)
            sw = value & self.CFGR1_SW_MASK
            value = (value & ~self.CFGR1_SWS_MASK) | (sw << self.CFGR1_SWS_SHIFT)
        elif offset == self.BDCR:
            if value & self.BDCR_LSEON:
                value |= self.BDCR_LSERDY
        elif offset == self.CSR:
            if value & self.CSR_LSION:
                value |= self.CSR_LSIRDY

        self.regs[offset] = value

    def _apply_cr_ready(self, cr: int) -> int:
        """Auto-set ready bits for enabled oscillators."""
        if cr & self.CR_MSISON:
            cr |= self.CR_MSISRDY
        if cr & self.CR_MSIKON:
            cr |= self.CR_MSIKRDY
        if cr & self.CR_HSION:
            cr |= self.CR_HSIRDY
        if cr & self.CR_HSI48ON:
            cr |= self.CR_HSI48RDY
        if cr & self.CR_SHSION:
            cr |= self.CR_SHSIRDY
        if cr & self.CR_HSEON:
            cr |= self.CR_HSERDY
        if cr & self.CR_PLL1ON:
            cr |= self.CR_PLL1RDY
        if cr & self.CR_PLL2ON:
            cr |= self.CR_PLL2RDY
        if cr & self.CR_PLL3ON:
            cr |= self.CR_PLL3RDY
        return cr
