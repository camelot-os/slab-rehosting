"""
STM32U5xx Peripheral Sets

Supported devices:
- STM32U5A5 (160 MHz, TrustZone, 4MB Flash)
- STM32U575/585 (160 MHz, TrustZone)
- STM32U535/545 (160 MHz, cost optimized)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Dict, List, Tuple, Callable
from .stm32_base import STM32PeripheralSet, STM32Peripheral
from .stm32_gpio import STM32GPIOv2, STM32EXTI

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from slab_peripherals.mpu import MemoryProtectionController, ProtectionFault
from .stm32_usart import STM32USARTv2, STM32LPUART
from .stm32_spi import STM32SPIv2
from .stm32_i2c import STM32I2Cv2
from .stm32_rcc import STM32RCCv5
from .stm32_dma import STM32GPDMA
from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer, STM32LPTIM
from .stm32_adc import STM32ADCv3
from .stm32_dac import STM32DAC
from .stm32_pwr import STM32PWRv2
from .stm32_flash import STM32FLASHv3
from .stm32_misc import STM32SYSCFG, STM32IWDG, STM32WWDG, STM32RTC, STM32CRC, STM32RNG, STM32DBG, STM32OTP


class STM32GTZC(STM32Peripheral):
    """
    STM32 Global TrustZone Controller.

    Components:
    - TZSC: TrustZone Security Controller (peripheral security)
    - TZIC: TrustZone Illegal Access Controller (monitoring)
    - MPCBB: Memory Protection Controller Block-Based (SRAM security)
    """

    # TZSC registers
    TZSC_CR = 0x00
    TZSC_SECCFGR1 = 0x10
    TZSC_SECCFGR2 = 0x14
    TZSC_SECCFGR3 = 0x18
    TZSC_PRIVCFGR1 = 0x20
    TZSC_PRIVCFGR2 = 0x24
    TZSC_PRIVCFGR3 = 0x28

    # TZIC registers (offset 0x400)
    TZIC_IER1 = 0x400
    TZIC_IER2 = 0x404
    TZIC_IER3 = 0x408
    TZIC_SR1 = 0x420
    TZIC_SR2 = 0x424
    TZIC_SR3 = 0x428
    TZIC_FCR1 = 0x440
    TZIC_FCR2 = 0x444
    TZIC_FCR3 = 0x448

    def __init__(self, base: int = 0x50032400):
        super().__init__("GTZC", base, 0x800)

        # TZSC state
        self.tzsc_cr = 0
        self.seccfgr = [0, 0, 0]
        self.privcfgr = [0, 0, 0]

        # TZIC state
        self.tzic_ier = [0, 0, 0]
        self.tzic_sr = [0, 0, 0]

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.TZSC_CR:
            return self.tzsc_cr
        elif self.TZSC_SECCFGR1 <= offset <= self.TZSC_SECCFGR3:
            idx = (offset - self.TZSC_SECCFGR1) // 4
            return self.seccfgr[idx]
        elif self.TZSC_PRIVCFGR1 <= offset <= self.TZSC_PRIVCFGR3:
            idx = (offset - self.TZSC_PRIVCFGR1) // 4
            return self.privcfgr[idx]
        elif self.TZIC_IER1 <= offset <= self.TZIC_IER3:
            idx = (offset - self.TZIC_IER1) // 4
            return self.tzic_ier[idx]
        elif self.TZIC_SR1 <= offset <= self.TZIC_SR3:
            idx = (offset - self.TZIC_SR1) // 4
            return self.tzic_sr[idx]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.TZSC_CR:
            self.tzsc_cr = value
        elif self.TZSC_SECCFGR1 <= offset <= self.TZSC_SECCFGR3:
            idx = (offset - self.TZSC_SECCFGR1) // 4
            self.seccfgr[idx] = value
        elif self.TZSC_PRIVCFGR1 <= offset <= self.TZSC_PRIVCFGR3:
            idx = (offset - self.TZSC_PRIVCFGR1) // 4
            self.privcfgr[idx] = value
        elif self.TZIC_IER1 <= offset <= self.TZIC_IER3:
            idx = (offset - self.TZIC_IER1) // 4
            self.tzic_ier[idx] = value
        elif self.TZIC_FCR1 <= offset <= self.TZIC_FCR3:
            idx = (offset - self.TZIC_FCR1) // 4
            self.tzic_sr[idx] &= ~value

    def is_peripheral_secure(self, periph_id: int) -> bool:
        """Check if peripheral is configured as secure."""
        reg_idx = periph_id // 32
        bit_pos = periph_id % 32
        if reg_idx < 3:
            return bool(self.seccfgr[reg_idx] & (1 << bit_pos))
        return False


class STM32MPCBB(STM32Peripheral):
    """
    STM32 Memory Protection Controller Block-Based.

    Configures security attributes for SRAM on a per-block basis.
    Each block is 512 bytes (U5).
    """

    CR = 0x00
    CFGLOCKR1 = 0x10
    SECCFGR0 = 0x100  # Security config for blocks 0-31
    PRIVCFGR0 = 0x200  # Privilege config for blocks 0-31

    def __init__(self, index: int = 1, base: int = 0x50032800):
        super().__init__(f"MPCBB{index}", base, 0x400)
        self.index = index

        self.cr = 0
        self.cfglockr1 = 0

        # Each register covers 32 blocks (512B each = 16KB per register)
        # U5 has up to 32 SECCFGR/PRIVCFGR registers = 512KB configurable
        self.seccfgr = [0] * 32
        self.privcfgr = [0] * 32

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.CFGLOCKR1:
            return self.cfglockr1
        elif self.SECCFGR0 <= offset < self.SECCFGR0 + 128:
            idx = (offset - self.SECCFGR0) // 4
            return self.seccfgr[idx] if idx < 32 else 0
        elif self.PRIVCFGR0 <= offset < self.PRIVCFGR0 + 128:
            idx = (offset - self.PRIVCFGR0) // 4
            return self.privcfgr[idx] if idx < 32 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.CFGLOCKR1:
            # Lock bits can only be set, not cleared
            self.cfglockr1 |= value
        elif self.SECCFGR0 <= offset < self.SECCFGR0 + 128:
            idx = (offset - self.SECCFGR0) // 4
            if idx < 32 and not (self.cfglockr1 & (1 << idx)):
                self.seccfgr[idx] = value
        elif self.PRIVCFGR0 <= offset < self.PRIVCFGR0 + 128:
            idx = (offset - self.PRIVCFGR0) // 4
            if idx < 32:
                self.privcfgr[idx] = value

    def is_block_secure(self, block: int) -> bool:
        """Check if SRAM block is secure."""
        reg_idx = block // 32
        bit_pos = block % 32
        if reg_idx < 32:
            return bool(self.seccfgr[reg_idx] & (1 << bit_pos))
        return False


class STM32GTZCProtection(MemoryProtectionController):
    """
    TrustZone access enforcement for STM32U5 using GTZC + MPCBB.

    Enforces:
    - NS access denied to TZSC-secure peripherals
    - NS access denied to MPCBB-secure SRAM blocks
    - Unprivileged access denied to PRIVCFGR-protected peripherals
    - Records violations in TZIC status registers

    STM32U5 address layout:
    - 0x40000000-0x4FFFFFFF: Non-Secure peripheral/memory space
    - 0x50000000-0x5FFFFFFF: Secure peripheral/memory space (aliases)
    - 0x20000000-0x200FFFFF: SRAM1 (NS)
    - 0x30000000-0x300FFFFF: SRAM1 (Secure alias)

    Peripheral ID mapping:
    - IDs 0-31:  SECCFGR1 (APB1 peripherals)
    - IDs 32-63: SECCFGR2 (APB2/AHB1 peripherals)
    - IDs 64-95: SECCFGR3 (AHB2/AHB3 peripherals)
    """

    # STM32U5 peripheral base → ID mapping (subset of key peripherals)
    PERIPH_ID_MAP = {
        0x40000000: 0,   # TIM2
        0x40000400: 1,   # TIM3
        0x40000800: 2,   # TIM4
        0x40000C00: 3,   # TIM5
        0x40001000: 4,   # TIM6
        0x40001400: 5,   # TIM7
        0x40002C00: 6,   # WWDG
        0x40003000: 7,   # IWDG
        0x40003800: 8,   # SPI2
        0x40004400: 9,   # USART2
        0x40004800: 10,  # USART3
        0x40004C00: 11,  # UART4
        0x40005000: 12,  # UART5
        0x40005400: 13,  # I2C1
        0x40005800: 14,  # I2C2
        0x40007C00: 15,  # LPTIM1
        0x40012C00: 32,  # TIM1
        0x40013000: 33,  # SPI1
        0x40013400: 34,  # TIM8
        0x40013800: 35,  # USART1
        0x40020000: 48,  # GPDMA1
        0x40022000: 49,  # FLASH
        0x40023000: 50,  # CRC
        0x42020000: 64,  # GPIOA
        0x42020400: 65,  # GPIOB
        0x42020800: 66,  # GPIOC
        0x42020C00: 67,  # GPIOD
        0x42021000: 68,  # GPIOE
        0x42028000: 72,  # ADC1
        0x420C0400: 76,  # SAES / HASH
        0x420C0800: 77,  # RNG
    }

    # SRAM regions for MPCBB mapping
    SRAM_REGIONS = [
        # (NS base, Secure base, size, MPCBB index)
        (0x20000000, 0x30000000, 0x40000, 0),   # SRAM1 (256KB)
        (0x20040000, 0x30040000, 0x10000, 1),   # SRAM2 (64KB)
        (0x20050000, 0x30050000, 0x80000, 2),   # SRAM3 (512KB)
    ]

    BLOCK_SIZE = 512  # Each MPCBB block is 512 bytes

    def __init__(self, gtzc: 'STM32GTZC',
                 mpcbb_list: Optional[List['STM32MPCBB']] = None):
        """
        Initialize GTZC protection controller.

        Args:
            gtzc: STM32GTZC instance (TZSC + TZIC)
            mpcbb_list: List of STM32MPCBB instances [SRAM1, SRAM2, SRAM3]
        """
        super().__init__()
        self.gtzc = gtzc
        self.mpcbb = mpcbb_list or []
        self.irq_callback: Optional[Callable[[], None]] = None

    def reset(self):
        """Reset protection state."""
        self._violation_count = 0
        self._violation_log.clear()

    def translate_address(self, address: int, is_write: bool = False,
                          is_privileged: bool = True,
                          ns: bool = False) -> Tuple[int, bool]:
        """
        Translate secure alias to NS address.

        Secure aliases are 0x10000000 above their NS counterparts:
        - 0x50000000 → 0x40000000 (peripherals)
        - 0x30000000 → 0x20000000 (SRAM)
        """
        if 0x50000000 <= address < 0x60000000:
            return (address - 0x10000000, True)
        elif 0x30000000 <= address < 0x30100000:
            return (address - 0x10000000, True)
        return (address, True)

    def check_access(self, address: int, size: int = 4,
                     is_write: bool = False, is_privileged: bool = True,
                     is_instruction: bool = False,
                     ns: bool = False, core_id: int = 0) -> bool:
        """
        Check if access is permitted by GTZC/MPCBB policy.

        Denies:
        - NS access to secure peripherals (TZSC SECCFGR)
        - NS access to secure SRAM blocks (MPCBB SECCFGR)
        - Unprivileged access to privilege-only peripherals (TZSC PRIVCFGR)
        - NS access via secure alias addresses (0x5xxxxxxx)
        """
        # Secure alias access from NS state is always denied
        if ns and (0x50000000 <= address < 0x60000000 or
                   0x30000000 <= address < 0x30100000):
            self._record_tzic_violation(address, is_write, "NS access to secure alias")
            return False

        # Check peripheral security (TZSC)
        periph_id = self._address_to_periph_id(address)
        if periph_id is not None:
            # Security check
            if ns and self.gtzc.is_peripheral_secure(periph_id):
                self._record_tzic_violation(
                    address, is_write,
                    f"NS access to secure peripheral ID {periph_id}")
                return False

            # Privilege check
            if not is_privileged and self._is_peripheral_privileged(periph_id):
                self._record_tzic_violation(
                    address, is_write,
                    f"Unprivileged access to privileged peripheral ID {periph_id}")
                return False

        # Check SRAM security (MPCBB)
        block_info = self._address_to_sram_block(address)
        if block_info is not None:
            mpcbb_idx, block_num = block_info
            if mpcbb_idx < len(self.mpcbb):
                if ns and self.mpcbb[mpcbb_idx].is_block_secure(block_num):
                    self._record_tzic_violation(
                        address, is_write,
                        f"NS access to secure SRAM block {block_num} (MPCBB{mpcbb_idx+1})")
                    return False

        return True

    def _address_to_periph_id(self, address: int) -> Optional[int]:
        """Map address to peripheral ID for TZSC lookup."""
        # Normalize secure alias to NS base
        if 0x50000000 <= address < 0x60000000:
            address -= 0x10000000

        # Find peripheral by base address (aligned to 0x400 boundary)
        periph_base = address & ~0x3FF
        return self.PERIPH_ID_MAP.get(periph_base)

    def _is_peripheral_privileged(self, periph_id: int) -> bool:
        """Check if peripheral requires privileged access (PRIVCFGR)."""
        reg_idx = periph_id // 32
        bit_pos = periph_id % 32
        if reg_idx < 3:
            return bool(self.gtzc.privcfgr[reg_idx] & (1 << bit_pos))
        return False

    def _address_to_sram_block(self, address: int) -> Optional[Tuple[int, int]]:
        """
        Map address to (MPCBB index, block number).

        Returns None if address is not in a configured SRAM region.
        """
        for ns_base, sec_base, region_size, mpcbb_idx in self.SRAM_REGIONS:
            # Check NS SRAM range
            if ns_base <= address < ns_base + region_size:
                block = (address - ns_base) // self.BLOCK_SIZE
                return (mpcbb_idx, block)
            # Check Secure SRAM range
            if sec_base <= address < sec_base + region_size:
                block = (address - sec_base) // self.BLOCK_SIZE
                return (mpcbb_idx, block)
        return None

    def _record_tzic_violation(self, address: int, is_write: bool, details: str):
        """Record a TZIC illegal access and update status registers."""
        fault = ProtectionFault(
            address=address,
            size=4,
            is_write=is_write,
            is_privileged=False,
            is_instruction=False,
            fault_type="GTZC",
            details=details,
        )
        self.record_violation(fault)

        # Update TZIC status register
        periph_id = self._address_to_periph_id(address)
        if periph_id is not None:
            reg_idx = periph_id // 32
            bit_pos = periph_id % 32
            if reg_idx < 3:
                self.gtzc.tzic_sr[reg_idx] |= (1 << bit_pos)

                # Generate interrupt if enabled
                if self.gtzc.tzic_ier[reg_idx] & (1 << bit_pos):
                    if self.irq_callback:
                        self.irq_callback()


class STM32TAMP(STM32Peripheral):
    """
    STM32 Tamper and Backup Registers.

    Features:
    - Active/passive tamper detection
    - Backup registers (secure/non-secure)
    - Monotonic counter
    - Boot hardware key storage
    """

    CR1 = 0x00
    CR2 = 0x04
    CR3 = 0x08
    FLTCR = 0x0C
    ATCR1 = 0x10  # Active tamper control 1
    ATSEEDR = 0x14  # Active tamper seed
    ATOR = 0x18  # Active tamper output
    ATCR2 = 0x1C  # Active tamper control 2
    SECCFGR = 0x20
    PRIVCFGR = 0x24
    IER = 0x2C
    SR = 0x30
    MISR = 0x34
    SMISR = 0x38  # Secure masked interrupt
    SCR = 0x3C
    COUNTR = 0x40  # Monotonic counter
    CFGR = 0x50
    BKPR = 0x100  # Backup registers start

    # CR1 bits
    CR1_TAMP1E = 1 << 0
    CR1_TAMP2E = 1 << 1
    CR1_TAMP3E = 1 << 2
    CR1_ITAMP3E = 1 << 18  # Internal tamper 3
    CR1_ITAMP4E = 1 << 19
    CR1_ITAMP5E = 1 << 20
    CR1_ITAMP6E = 1 << 21
    CR1_ITAMP7E = 1 << 22
    CR1_ITAMP8E = 1 << 23

    def __init__(self, base: int = 0x40003400):
        super().__init__("TAMP", base, 0x400)

        self.cr1 = 0
        self.cr2 = 0
        self.cr3 = 0
        self.fltcr = 0
        self.atcr1 = 0
        self.atcr2 = 0
        self.seccfgr = 0
        self.privcfgr = 0
        self.ier = 0
        self.sr = 0
        self.countr = 0
        self.cfgr = 0

        # Backup registers (32 on U5)
        self.bkpr = [0] * 32

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.CR3:
            return self.cr3
        elif offset == self.FLTCR:
            return self.fltcr
        elif offset == self.ATCR1:
            return self.atcr1
        elif offset == self.ATCR2:
            return self.atcr2
        elif offset == self.SECCFGR:
            return self.seccfgr
        elif offset == self.PRIVCFGR:
            return self.privcfgr
        elif offset == self.IER:
            return self.ier
        elif offset == self.SR:
            return self.sr
        elif offset == self.COUNTR:
            return self.countr
        elif offset == self.CFGR:
            return self.cfgr
        elif offset >= self.BKPR:
            idx = (offset - self.BKPR) // 4
            if idx < 32:
                return self.bkpr[idx]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            self.cr1 = value
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.CR3:
            self.cr3 = value
        elif offset == self.FLTCR:
            self.fltcr = value
        elif offset == self.ATCR1:
            self.atcr1 = value
        elif offset == self.ATCR2:
            self.atcr2 = value
        elif offset == self.SECCFGR:
            self.seccfgr = value
        elif offset == self.PRIVCFGR:
            self.privcfgr = value
        elif offset == self.IER:
            self.ier = value
        elif offset == self.SCR:
            # Status clear
            self.sr &= ~value
        elif offset == self.CFGR:
            self.cfgr = value
        elif offset >= self.BKPR:
            idx = (offset - self.BKPR) // 4
            if idx < 32:
                self.bkpr[idx] = value


class STM32SAES(STM32Peripheral):
    """
    STM32 Secure AES (SAES) Hardware Accelerator.

    Enhanced AES with:
    - Hardware key wrapping
    - Secure key storage
    - Side-channel attack protection
    """

    CR = 0x00
    SR = 0x04
    DINR = 0x08
    DOUTR = 0x0C
    KEYR0 = 0x10
    IVR0 = 0x20
    IER = 0x300
    ISR = 0x304
    ICR = 0x308

    # CR bits (same as AES + additional)
    CR_EN = 1 << 0
    CR_DATATYPE = 0x3 << 1
    CR_MODE = 0x3 << 3
    CR_CHMOD = 0x7 << 5
    CR_KEYSIZE = 0x3 << 18
    CR_KEYPROT = 1 << 26  # Key protection
    CR_KMOD = 0x3 << 24   # Key mode (normal, wrapped, shared)

    # SR bits
    SR_CCF = 1 << 0
    SR_RDERR = 1 << 1
    SR_WRERR = 1 << 2
    SR_BUSY = 1 << 3
    SR_KEYVALID = 1 << 7

    def __init__(self, base: int = 0x420C0400):
        super().__init__("SAES", base, 0x400)

        self.cr = 0
        self.sr = 0
        self.ier = 0
        self.isr = 0
        self.key = [0] * 8
        self.iv = [0] * 4

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self.sr
        elif offset == self.IER:
            return self.ier
        elif offset == self.ISR:
            return self.isr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
            if value & self.CR_EN:
                self.sr |= self.SR_KEYVALID
        elif offset == self.IER:
            self.ier = value
        elif offset == self.ICR:
            self.isr &= ~value
        elif self.KEYR0 <= offset < self.KEYR0 + 32:
            idx = (offset - self.KEYR0) // 4
            if idx < 8:
                self.key[idx] = value
        elif self.IVR0 <= offset < self.IVR0 + 16:
            idx = (offset - self.IVR0) // 4
            if idx < 4:
                self.iv[idx] = value


class STM32HASH(STM32Peripheral):
    """
    STM32 HASH Processor.

    Supports:
    - SHA-1, SHA-224, SHA-256, SHA-384, SHA-512 (U5)
    - HMAC
    - Multi-buffer DMA
    """

    CR = 0x00
    DIN = 0x04
    STR = 0x08
    HR0 = 0x0C  # Hash result registers
    IMR = 0x20
    SR = 0x24
    CSR0 = 0xF8  # Context save/restore

    # CR bits
    CR_INIT = 1 << 2
    CR_DMAE = 1 << 3
    CR_DATATYPE = 0x3 << 4
    CR_MODE = 1 << 6
    CR_ALGO = 0x3 << 7  # Extended on U5
    CR_NBW = 0xF << 8
    CR_DINNE = 1 << 12
    CR_MDMAT = 1 << 13
    CR_LKEY = 1 << 16
    CR_ALGO1 = 1 << 18  # U5 SHA-384/512

    # SR bits
    SR_DINIS = 1 << 0
    SR_DCIS = 1 << 1
    SR_DMAS = 1 << 2
    SR_BUSY = 1 << 3
    SR_NBWP = 0xF << 9
    SR_DINNE = 1 << 15
    SR_NBWE = 0xF << 16

    def __init__(self, base: int = 0x420C0400):
        super().__init__("HASH", base, 0x400)

        self.cr = 0
        self.str = 0
        self.sr = self.SR_DINIS
        self.imr = 0

        # Hash result (up to 512 bits for SHA-512)
        self.hr = [0] * 16

        # Input buffer
        self.din_buf = []

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.STR:
            return self.str
        elif offset == self.SR:
            return self.sr
        elif offset == self.IMR:
            return self.imr
        elif self.HR0 <= offset < self.HR0 + 64:
            idx = (offset - self.HR0) // 4
            return self.hr[idx] if idx < 16 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.DIN:
            self._write_din(value)
        elif offset == self.STR:
            self.str = value
            if value & 0x100:  # DCAL
                self._compute_hash()
        elif offset == self.IMR:
            self.imr = value

    def _write_cr(self, value: int):
        if value & self.CR_INIT:
            # Initialize hash
            self.din_buf = []
            self.hr = [0] * 16
            self.sr |= self.SR_DINIS
        self.cr = value & ~self.CR_INIT

    def _write_din(self, value: int):
        self.din_buf.append(value)
        self.sr &= ~self.SR_DINIS

    def _compute_hash(self):
        """Compute hash (simulated)."""
        # In real implementation, would compute actual hash
        # For emulation, produce deterministic output based on input
        import hashlib
        data = b''.join(v.to_bytes(4, 'little') for v in self.din_buf)
        algo = (self.cr >> 7) & 0x3

        if algo == 0:  # SHA-1
            h = hashlib.sha1(data).digest()
        elif algo == 1:  # MD5 (not on U5)
            h = hashlib.md5(data).digest()
        else:  # SHA-256
            h = hashlib.sha256(data).digest()

        # Store result
        for i in range(min(len(h) // 4, 16)):
            self.hr[i] = int.from_bytes(h[i*4:(i+1)*4], 'big')

        self.sr |= self.SR_DCIS
        self.din_buf = []


class STM32U5xxPeripheralSet(STM32PeripheralSet):
    """
    Base peripheral set for STM32U5xx family.

    Memory Map (Non-Secure):
        0x40000000 - APB1 (TIM2-7, RTC, WWDG, IWDG, SPI2/3, USART2-5, I2C1-4, LPTIM1-4)
        0x40010000 - APB2 (SYSCFG, COMP, TIM1/8/15-17, SPI1/4, USART1/6, SAI1/2)
        0x40020000 - AHB1 (GPDMA1, CORDIC, FMAC, FLASH, CRC, TSC, MDF1, RAMCFG)
        0x42020000 - AHB2 (GPIOA-I, ADC1/2, DAC1, DCMI, OTG_FS, AES, HASH, RNG, SAES, PKA, OTFDEC)
        0x44020000 - AHB3 (LPGPIO, PWR, RCC, ADC4, DAC2, LPDMA, ADF1, GTZC2)
        0x46000000 - APB3 (SPI3, LPUART1, I2C3, LPTIM3/4, VREFBUF, RTC, TAMP)
        0x50000000 - AHB2 EXT (FMC, OCTOSPI)

    Memory Map (Secure aliases at 0x50000000+):
        Similar layout with security attributes
    """

    def __init__(self, device: str = "STM32U5A5", log: logging.Logger = None):
        super().__init__(device, log)
        self.family = "U5"

        self._create_clock_system()
        self._create_gpio()
        self._create_communication()
        self._create_timers()
        self._create_analog()
        self._create_dma()
        self._create_usb()
        self._create_security()
        self._create_misc()

    def _create_clock_system(self):
        """Create RCC and related peripherals."""
        self.rcc = STM32RCCv5(base=0x46020C00)
        self.add_peripheral(self.rcc)

        self.pwr = STM32PWRv2(base=0x46020800, family="U5")
        self.add_peripheral(self.pwr)

        self.flash = STM32FLASHv3(base=0x40022000, family="U5")
        self.add_peripheral(self.flash)

    def _create_gpio(self):
        """Create GPIO ports."""
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

        self.exti = STM32EXTI(base=0x46022000)
        self.add_peripheral(self.exti)

    def _create_communication(self):
        """Create USART, SPI, I2C peripherals."""
        # USARTs
        usart_config = [
            (1, 0x40013800),
            (2, 0x40004400),
            (3, 0x40004800),
            (6, 0x40006400),
        ]
        for idx, base in usart_config:
            name = f"usart{idx}"
            setattr(self, name, STM32USARTv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # UARTs
        uart_config = [(4, 0x40004C00), (5, 0x40005000)]
        for idx, base in uart_config:
            name = f"uart{idx}"
            setattr(self, name, STM32USARTv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # LPUART
        self.lpuart1 = STM32LPUART(index=1, base=0x46002400)
        self.add_peripheral(self.lpuart1)

        # SPI
        spi_config = [
            (1, 0x40013000),
            (2, 0x40003800),
            (3, 0x46002000),
        ]
        for idx, base in spi_config:
            name = f"spi{idx}"
            setattr(self, name, STM32SPIv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

        # I2C
        i2c_config = [
            (1, 0x40005400),
            (2, 0x40005800),
            (3, 0x46002800),
            (4, 0x40008400),
        ]
        for idx, base in i2c_config:
            name = f"i2c{idx}"
            setattr(self, name, STM32I2Cv2(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

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
        lptim_config = [
            (1, 0x40007C00),
            (2, 0x40009400),
            (3, 0x46004800),
            (4, 0x46004C00),
        ]
        for idx, base in lptim_config:
            name = f"lptim{idx}"
            setattr(self, name, STM32LPTIM(index=idx, base=base))
            self.add_peripheral(getattr(self, name))

    def _create_analog(self):
        """Create ADC and DAC peripherals."""
        self.adc1 = STM32ADCv3(index=1, base=0x42028000)
        self.adc2 = STM32ADCv3(index=2, base=0x42028100)
        self.adc4 = STM32ADCv3(index=4, base=0x46021000)  # AHB3
        self.add_peripheral(self.adc1)
        self.add_peripheral(self.adc2)
        self.add_peripheral(self.adc4)

        self.dac1 = STM32DAC(base=0x46021800)
        self.add_peripheral(self.dac1)

    def _create_dma(self):
        """Create DMA controllers."""
        # GPDMA1: 16 channels, IRQ 29-36 (ch0-7) + 80-87 (ch8-15)
        self.gpdma1 = STM32GPDMA(name="GPDMA1", base=0x40020000, num_channels=16)
        self.add_peripheral(self.gpdma1)

        # LPDMA1: 4 channels, IRQ 114-117
        self.lpdma = STM32GPDMA(name="LPDMA1", base=0x46025000, num_channels=4)
        self.add_peripheral(self.lpdma)

    def _create_security(self):
        """Create TrustZone and crypto peripherals."""
        # GTZC (Global TrustZone Controller)
        self.gtzc1 = STM32GTZC(base=0x50032400)
        self.gtzc2 = STM32GTZC(base=0x56032400)  # Secure alias
        self.add_peripheral(self.gtzc1)
        self.add_peripheral(self.gtzc2)

        # MPCBB (Memory Protection for SRAM)
        self.mpcbb1 = STM32MPCBB(index=1, base=0x50032C00)  # SRAM1
        self.mpcbb2 = STM32MPCBB(index=2, base=0x50033000)  # SRAM2
        self.mpcbb3 = STM32MPCBB(index=3, base=0x50033400)  # SRAM3
        self.add_peripheral(self.mpcbb1)
        self.add_peripheral(self.mpcbb2)
        self.add_peripheral(self.mpcbb3)

        # GTZC Protection Controller (enforcement layer)
        self.gtzc_protection = STM32GTZCProtection(
            gtzc=self.gtzc1,
            mpcbb_list=[self.mpcbb1, self.mpcbb2, self.mpcbb3]
        )

        # Tamper
        self.tamp = STM32TAMP(base=0x46003400)
        self.add_peripheral(self.tamp)

        # Crypto
        self.saes = STM32SAES(base=0x420C0400)
        self.hash = STM32HASH(base=0x420C0400)  # Different offset in practice
        self.rng = STM32RNG(base=0x420C0800, family="U5")
        self.add_peripheral(self.saes)
        self.add_peripheral(self.hash)
        self.add_peripheral(self.rng)

    def _create_usb(self):
        """Create USB OTG HS peripheral (DWC2)."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        self.usb = USBCDCPeripheral(
            name="USB_OTG_HS", base=0x42040000, size=0x40000, irq=73)
        self.add_peripheral(self.usb)

    def _create_misc(self):
        """Create miscellaneous peripherals."""
        self.syscfg = STM32SYSCFG(base=0x46000400, family="U5")
        self.iwdg = STM32IWDG(base=0x40003000)
        self.wwdg = STM32WWDG(base=0x40002C00, family="U5")
        self.rtc = STM32RTC(base=0x46007800, num_backup=32)
        self.crc = STM32CRC(base=0x40023000, family="U5")
        self.dbg = STM32DBG(base=0xE0044000, device="U5A5")

        self.otp = STM32OTP(family="U5", flash_size_kb=4096)
        self.add_peripheral(self.syscfg)
        self.add_peripheral(self.iwdg)
        self.add_peripheral(self.wwdg)
        self.add_peripheral(self.rtc)
        self.add_peripheral(self.crc)
        self.add_peripheral(self.dbg)
        self.add_peripheral(self.otp)


class STM32U5A5PeripheralSet(STM32U5xxPeripheralSet):
    """
    STM32U5A5 peripheral set.

    Features:
    - 160 MHz Cortex-M33 with TrustZone
    - 4MB Flash, 2.5MB SRAM
    - USB OTG HS with PHY
    - OCTOSPI
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32U5A5", log=log)


class STM32U575PeripheralSet(STM32U5xxPeripheralSet):
    """
    STM32U575 peripheral set.

    Features:
    - 160 MHz Cortex-M33 with TrustZone
    - 2MB Flash, 786KB SRAM
    - USB OTG FS
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(device="STM32U575", log=log)


class STM32U585PeripheralSet(STM32U575PeripheralSet):
    """
    STM32U585 peripheral set (U575 + crypto).

    Additional features:
    - SAES
    - PKA
    - OTFDEC
    """

    def __init__(self, log: logging.Logger = None):
        super().__init__(log=log)
        self.device = "STM32U585"
