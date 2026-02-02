"""
STM32 FLASH Interface Emulation

Implements:
- FLASHv1: F1xx
- FLASHv2: F4xx
- FLASHv3: L4xx/H7xx/U5xx

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32FLASHv1(STM32Peripheral):
    """
    STM32F1xx Flash Interface.

    Register Map:
        0x00: ACR    - Access control
        0x04: KEYR   - Key register
        0x08: OPTKEYR - Option key
        0x0C: SR     - Status
        0x10: CR     - Control
        0x14: AR     - Address
        0x1C: OBR    - Option byte
        0x20: WRPR   - Write protection
    """

    ACR = 0x00
    KEYR = 0x04
    OPTKEYR = 0x08
    SR = 0x0C
    CR = 0x10
    AR = 0x14
    OBR = 0x1C
    WRPR = 0x20

    # ACR bits
    ACR_LATENCY = 0x7     # Latency
    ACR_HLFCYA = 1 << 3   # Half cycle access
    ACR_PRFTBE = 1 << 4   # Prefetch enable
    ACR_PRFTBS = 1 << 5   # Prefetch status

    # SR bits
    SR_BSY = 1 << 0       # Busy
    SR_PGERR = 1 << 2     # Programming error
    SR_WRPRTERR = 1 << 4  # Write protection error
    SR_EOP = 1 << 5       # End of operation

    # CR bits
    CR_PG = 1 << 0        # Programming
    CR_PER = 1 << 1       # Page erase
    CR_MER = 1 << 2       # Mass erase
    CR_OPTPG = 1 << 4     # Option byte programming
    CR_OPTER = 1 << 5     # Option byte erase
    CR_STRT = 1 << 6      # Start
    CR_LOCK = 1 << 7      # Lock
    CR_OPTWRE = 1 << 9    # Option byte write enable
    CR_ERRIE = 1 << 10    # Error interrupt enable
    CR_EOPIE = 1 << 12    # End of operation interrupt enable

    # Keys
    KEY1 = 0x45670123
    KEY2 = 0xCDEF89AB
    OPTKEY1 = 0x45670123
    OPTKEY2 = 0xCDEF89AB

    def __init__(self, base: int = 0x40022000):
        super().__init__("FLASH", base, 0x400)

        self.acr = 0
        self.sr = 0
        self.cr = self.CR_LOCK
        self.ar = 0
        self.obr = 0x03FFFFFC  # Default option bytes
        self.wrpr = 0xFFFFFFFF

        # Unlock sequence state
        self._key_state = 0
        self._optkey_state = 0

        # Flash memory simulation
        self.flash_data: Optional[bytearray] = None
        self.flash_size = 512 * 1024  # 512KB default
        self.page_size = 2048  # 2KB pages

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ACR:
            return self._get_acr()
        elif offset == self.SR:
            return self.sr
        elif offset == self.CR:
            return self.cr
        elif offset == self.OBR:
            return self.obr
        elif offset == self.WRPR:
            return self.wrpr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ACR:
            self.acr = value
        elif offset == self.KEYR:
            self._handle_key(value)
        elif offset == self.OPTKEYR:
            self._handle_optkey(value)
        elif offset == self.SR:
            # Write 1 to clear
            self.sr &= ~(value & (self.SR_PGERR | self.SR_WRPRTERR | self.SR_EOP))
        elif offset == self.CR:
            self._write_cr(value)
        elif offset == self.AR:
            self.ar = value

    def _get_acr(self) -> int:
        acr = self.acr
        # Prefetch status follows enable
        if acr & self.ACR_PRFTBE:
            acr |= self.ACR_PRFTBS
        return acr

    def _handle_key(self, value: int):
        if self._key_state == 0 and value == self.KEY1:
            self._key_state = 1
        elif self._key_state == 1 and value == self.KEY2:
            self.cr &= ~self.CR_LOCK
            self._key_state = 0
        else:
            self._key_state = 0

    def _handle_optkey(self, value: int):
        if self._optkey_state == 0 and value == self.OPTKEY1:
            self._optkey_state = 1
        elif self._optkey_state == 1 and value == self.OPTKEY2:
            self.cr |= self.CR_OPTWRE
            self._optkey_state = 0
        else:
            self._optkey_state = 0

    def _write_cr(self, value: int):
        if self.cr & self.CR_LOCK:
            return  # Locked

        self.cr = value

        if value & self.CR_STRT:
            if value & self.CR_PER:
                self._page_erase()
            elif value & self.CR_MER:
                self._mass_erase()
            self.cr &= ~self.CR_STRT
            self.sr |= self.SR_EOP

    def _page_erase(self):
        """Erase page at address in AR."""
        if self.flash_data is None:
            return
        page = self.ar // self.page_size
        start = page * self.page_size
        for i in range(self.page_size):
            if start + i < len(self.flash_data):
                self.flash_data[start + i] = 0xFF

    def _mass_erase(self):
        """Erase all flash."""
        if self.flash_data:
            for i in range(len(self.flash_data)):
                self.flash_data[i] = 0xFF


class STM32FLASHv2(STM32Peripheral):
    """
    STM32F4xx Flash Interface.

    Features:
    - Sector-based erase (variable sector sizes)
    - Dual bank support (F4x9)
    - Write size selection (x8, x16, x32, x64)
    """

    ACR = 0x00
    KEYR = 0x04
    OPTKEYR = 0x08
    SR = 0x0C
    CR = 0x10
    OPTCR = 0x14
    OPTCR1 = 0x18  # Dual bank only

    # ACR bits
    ACR_LATENCY = 0xF     # Latency (up to 15 wait states)
    ACR_PRFTEN = 1 << 8   # Prefetch enable
    ACR_ICEN = 1 << 9     # Instruction cache enable
    ACR_DCEN = 1 << 10    # Data cache enable
    ACR_ICRST = 1 << 11   # Instruction cache reset
    ACR_DCRST = 1 << 12   # Data cache reset

    # SR bits
    SR_EOP = 1 << 0       # End of operation
    SR_OPERR = 1 << 1     # Operation error
    SR_WRPERR = 1 << 4    # Write protection error
    SR_PGAERR = 1 << 5    # Programming alignment error
    SR_PGPERR = 1 << 6    # Programming parallelism error
    SR_PGSERR = 1 << 7    # Programming sequence error
    SR_BSY = 1 << 16      # Busy

    # CR bits
    CR_PG = 1 << 0        # Programming
    CR_SER = 1 << 1       # Sector erase
    CR_MER = 1 << 2       # Mass erase
    CR_SNB = 0xF << 3     # Sector number
    CR_PSIZE = 0x3 << 8   # Program size
    CR_MER1 = 1 << 15     # Mass erase bank 2
    CR_STRT = 1 << 16     # Start
    CR_EOPIE = 1 << 24    # End of operation interrupt
    CR_ERRIE = 1 << 25    # Error interrupt
    CR_LOCK = 1 << 31     # Lock

    KEY1 = 0x45670123
    KEY2 = 0xCDEF89AB
    OPTKEY1 = 0x08192A3B
    OPTKEY2 = 0x4C5D6E7F

    def __init__(self, base: int = 0x40023C00, dual_bank: bool = False):
        super().__init__("FLASH", base, 0x400)
        self.dual_bank = dual_bank

        self.acr = 0
        self.sr = 0
        self.cr = self.CR_LOCK
        self.optcr = 0x0FFFAAED  # Default option config
        self.optcr1 = 0x0FFF0000 if dual_bank else 0

        self._key_state = 0
        self._optkey_state = 0

        # Sector sizes for F4 (16KB x 4, 64KB x 1, 128KB x rest)
        self.sector_sizes = [
            16 * 1024,   # Sector 0
            16 * 1024,   # Sector 1
            16 * 1024,   # Sector 2
            16 * 1024,   # Sector 3
            64 * 1024,   # Sector 4
            128 * 1024,  # Sector 5
            128 * 1024,  # Sector 6
            128 * 1024,  # Sector 7
            # ... more for larger devices
        ]

        self.flash_data: Optional[bytearray] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ACR:
            return self.acr
        elif offset == self.SR:
            return self.sr
        elif offset == self.CR:
            return self.cr
        elif offset == self.OPTCR:
            return self.optcr
        elif offset == self.OPTCR1 and self.dual_bank:
            return self.optcr1
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ACR:
            self._write_acr(value)
        elif offset == self.KEYR:
            self._handle_key(value)
        elif offset == self.OPTKEYR:
            self._handle_optkey(value)
        elif offset == self.SR:
            # Write 1 to clear
            clear_mask = (self.SR_EOP | self.SR_OPERR | self.SR_WRPERR |
                         self.SR_PGAERR | self.SR_PGPERR | self.SR_PGSERR)
            self.sr &= ~(value & clear_mask)
        elif offset == self.CR:
            self._write_cr(value)
        elif offset == self.OPTCR:
            self._write_optcr(value)

    def _write_acr(self, value: int):
        # Cache reset bits are write-only
        if value & self.ACR_ICRST:
            pass  # Reset instruction cache
        if value & self.ACR_DCRST:
            pass  # Reset data cache
        self.acr = value & ~(self.ACR_ICRST | self.ACR_DCRST)

    def _handle_key(self, value: int):
        if self._key_state == 0 and value == self.KEY1:
            self._key_state = 1
        elif self._key_state == 1 and value == self.KEY2:
            self.cr &= ~self.CR_LOCK
            self._key_state = 0
        else:
            self._key_state = 0

    def _handle_optkey(self, value: int):
        if self._optkey_state == 0 and value == self.OPTKEY1:
            self._optkey_state = 1
        elif self._optkey_state == 1 and value == self.OPTKEY2:
            # Option unlock (OPTLOCK in OPTCR)
            self.optcr &= ~1
            self._optkey_state = 0
        else:
            self._optkey_state = 0

    def _write_cr(self, value: int):
        if self.cr & self.CR_LOCK:
            return

        self.cr = value

        if value & self.CR_STRT:
            if value & self.CR_SER:
                sector = (value >> 3) & 0xF
                self._sector_erase(sector)
            elif value & self.CR_MER:
                self._mass_erase(0)
            elif value & self.CR_MER1:
                self._mass_erase(1)
            self.cr &= ~self.CR_STRT
            self.sr |= self.SR_EOP

    def _write_optcr(self, value: int):
        if self.optcr & 1:  # OPTLOCK
            return
        self.optcr = value

    def _sector_erase(self, sector: int):
        """Erase sector."""
        if self.flash_data is None:
            return

        offset = sum(self.sector_sizes[:sector]) if sector < len(self.sector_sizes) else 0
        size = self.sector_sizes[sector] if sector < len(self.sector_sizes) else 0

        for i in range(size):
            if offset + i < len(self.flash_data):
                self.flash_data[offset + i] = 0xFF

    def _mass_erase(self, bank: int):
        """Mass erase bank."""
        if self.flash_data:
            for i in range(len(self.flash_data)):
                self.flash_data[i] = 0xFF


class STM32FLASHv3(STM32Peripheral):
    """
    STM32L4xx/H7xx/U5xx Flash Interface.

    Features:
    - Dual bank (optional)
    - 72-bit ECC
    - Fast programming mode (H7/U5)
    - TrustZone secure/non-secure areas (U5)
    """

    ACR = 0x00
    PDKEYR = 0x04   # Power-down key (L4)
    KEYR = 0x08
    OPTKEYR = 0x0C
    SR = 0x10
    CR = 0x14
    ECCR = 0x18
    OPTR = 0x20
    PCROP1SR = 0x24
    PCROP1ER = 0x28
    WRP1AR = 0x2C
    WRP1BR = 0x30

    # ACR bits
    ACR_LATENCY = 0xF
    ACR_PRFTEN = 1 << 8
    ACR_ICEN = 1 << 9
    ACR_DCEN = 1 << 10
    ACR_ICRST = 1 << 11
    ACR_DCRST = 1 << 12
    ACR_RUN_PD = 1 << 13  # L4: Flash power-down in run
    ACR_SLEEP_PD = 1 << 14

    # SR bits
    SR_EOP = 1 << 0
    SR_OPERR = 1 << 1
    SR_PROGERR = 1 << 3
    SR_WRPERR = 1 << 4
    SR_PGAERR = 1 << 5
    SR_SIZERR = 1 << 6
    SR_PGSERR = 1 << 7
    SR_MISERR = 1 << 8
    SR_FASTERR = 1 << 9
    SR_RDERR = 1 << 14
    SR_OPTVERR = 1 << 15
    SR_BSY = 1 << 16

    # CR bits
    CR_PG = 1 << 0
    CR_PER = 1 << 1
    CR_MER1 = 1 << 2
    CR_PNB = 0xFF << 3
    CR_BKER = 1 << 11
    CR_MER2 = 1 << 15
    CR_STRT = 1 << 16
    CR_OPTSTRT = 1 << 17
    CR_FSTPG = 1 << 18
    CR_EOPIE = 1 << 24
    CR_ERRIE = 1 << 25
    CR_RDERRIE = 1 << 26
    CR_OBL_LAUNCH = 1 << 27
    CR_OPTLOCK = 1 << 30
    CR_LOCK = 1 << 31

    KEY1 = 0x45670123
    KEY2 = 0xCDEF89AB
    OPTKEY1 = 0x08192A3B
    OPTKEY2 = 0x4C5D6E7F

    def __init__(self, base: int = 0x40022000, family: str = "L4"):
        super().__init__("FLASH", base, 0x400)
        self.family = family

        self.acr = 0
        self.sr = 0
        self.cr = self.CR_LOCK | self.CR_OPTLOCK
        self.eccr = 0
        self.optr = 0xFFEFF8AA  # Default options

        # Page/sector configuration
        if family == "L4":
            self.page_size = 2048
        elif family == "H7":
            self.page_size = 128 * 1024  # 128KB sectors
        else:  # U5
            self.page_size = 8192

        self._key_state = 0
        self._optkey_state = 0
        self.flash_data: Optional[bytearray] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ACR:
            return self.acr
        elif offset == self.SR:
            return self.sr
        elif offset == self.CR:
            return self.cr
        elif offset == self.ECCR:
            return self.eccr
        elif offset == self.OPTR:
            return self.optr
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ACR:
            self._write_acr(value)
        elif offset == self.KEYR:
            self._handle_key(value)
        elif offset == self.OPTKEYR:
            self._handle_optkey(value)
        elif offset == self.SR:
            # Write 1 to clear
            clear_mask = 0xC3FB
            self.sr &= ~(value & clear_mask)
        elif offset == self.CR:
            self._write_cr(value)
        elif offset == self.OPTR:
            if not (self.cr & self.CR_OPTLOCK):
                self.optr = value
        else:
            self.regs[offset] = value

    def _write_acr(self, value: int):
        self.acr = value & ~(self.ACR_ICRST | self.ACR_DCRST)

    def _handle_key(self, value: int):
        if self._key_state == 0 and value == self.KEY1:
            self._key_state = 1
        elif self._key_state == 1 and value == self.KEY2:
            self.cr &= ~self.CR_LOCK
            self._key_state = 0
        else:
            self._key_state = 0

    def _handle_optkey(self, value: int):
        if self._optkey_state == 0 and value == self.OPTKEY1:
            self._optkey_state = 1
        elif self._optkey_state == 1 and value == self.OPTKEY2:
            self.cr &= ~self.CR_OPTLOCK
            self._optkey_state = 0
        else:
            self._optkey_state = 0

    def _write_cr(self, value: int):
        if self.cr & self.CR_LOCK:
            # Only LOCK and OPTLOCK can be cleared
            if value & self.CR_LOCK:
                return
            return

        self.cr = value

        if value & self.CR_STRT:
            if value & self.CR_PER:
                page = (value >> 3) & 0xFF
                bank = 1 if (value & self.CR_BKER) else 0
                self._page_erase(page, bank)
            elif value & self.CR_MER1:
                self._mass_erase(0)
            elif value & self.CR_MER2:
                self._mass_erase(1)
            self.cr &= ~self.CR_STRT
            self.sr |= self.SR_EOP

    def _page_erase(self, page: int, bank: int):
        """Erase page in specified bank."""
        if self.flash_data is None:
            return

        offset = page * self.page_size
        if bank == 1:
            offset += len(self.flash_data) // 2

        for i in range(self.page_size):
            if offset + i < len(self.flash_data):
                self.flash_data[offset + i] = 0xFF

    def _mass_erase(self, bank: int):
        """Mass erase bank."""
        if self.flash_data is None:
            return

        if bank == 0:
            start, end = 0, len(self.flash_data) // 2
        else:
            start, end = len(self.flash_data) // 2, len(self.flash_data)

        for i in range(start, end):
            self.flash_data[i] = 0xFF
