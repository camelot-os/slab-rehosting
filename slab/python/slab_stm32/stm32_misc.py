"""
STM32 Miscellaneous Peripherals

Includes:
- SYSCFG: System configuration
- IWDG: Independent watchdog
- WWDG: Window watchdog
- RTC: Real-time clock
- CRC: CRC calculation unit
- RNG: Random number generator
- DBG: Debug support

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
import time
import struct
from typing import Optional, Callable
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32SYSCFG(STM32Peripheral):
    """
    STM32 System Configuration Controller.

    Functions:
    - Memory remap
    - EXTI line source selection
    - I/O compensation cell control
    """

    MEMRMP = 0x00      # Memory remap (F4) / CFGR1 (L4)
    PMC = 0x04         # Peripheral mode config (F4)
    EXTICR1 = 0x08
    EXTICR2 = 0x0C
    EXTICR3 = 0x10
    EXTICR4 = 0x14
    CMPCR = 0x20       # Compensation cell control (F4)
    CFGR2 = 0x18       # L4/H7

    def __init__(self, base: int = 0x40013800, family: str = "F4"):
        super().__init__("SYSCFG", base, 0x400)
        self.family = family

        self.memrmp = 0
        self.pmc = 0
        self.exticr = [0, 0, 0, 0]
        self.cmpcr = 0
        self.cfgr2 = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.MEMRMP:
            return self.memrmp
        elif offset == self.PMC:
            return self.pmc
        elif offset == self.EXTICR1:
            return self.exticr[0]
        elif offset == self.EXTICR2:
            return self.exticr[1]
        elif offset == self.EXTICR3:
            return self.exticr[2]
        elif offset == self.EXTICR4:
            return self.exticr[3]
        elif offset == self.CMPCR:
            # READY bit always set
            return self.cmpcr | (1 << 8)
        elif offset == self.CFGR2:
            return self.cfgr2
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.MEMRMP:
            self.memrmp = value
        elif offset == self.PMC:
            self.pmc = value
        elif offset == self.EXTICR1:
            self.exticr[0] = value
        elif offset == self.EXTICR2:
            self.exticr[1] = value
        elif offset == self.EXTICR3:
            self.exticr[2] = value
        elif offset == self.EXTICR4:
            self.exticr[3] = value
        elif offset == self.CFGR2:
            self.cfgr2 = value

    def get_exti_source(self, line: int) -> int:
        """Get GPIO port for EXTI line (0-15)."""
        if line < 16:
            reg_idx = line // 4
            bit_pos = (line % 4) * 4
            return (self.exticr[reg_idx] >> bit_pos) & 0xF
        return 0


class STM32IWDG(STM32Peripheral):
    """
    STM32 Independent Watchdog.

    Features:
    - 12-bit down counter
    - LSI clock (~32kHz)
    - Configurable prescaler (4 to 256)
    """

    KR = 0x00    # Key register
    PR = 0x04    # Prescaler
    RLR = 0x08   # Reload
    SR = 0x0C    # Status
    WINR = 0x10  # Window (L4/H7)

    # Key values
    KEY_RELOAD = 0xAAAA
    KEY_ENABLE = 0xCCCC
    KEY_UNLOCK = 0x5555

    # SR bits
    SR_PVU = 1 << 0   # Prescaler update
    SR_RVU = 1 << 1   # Reload update
    SR_WVU = 1 << 2   # Window update

    def __init__(self, base: int = 0x40003000):
        super().__init__("IWDG", base, 0x400)

        self.pr = 0
        self.rlr = 0xFFF
        self.sr = 0
        self.winr = 0xFFF
        self.enabled = False
        self.counter = 0xFFF

        self._unlocked = False

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.PR:
            return self.pr
        elif offset == self.RLR:
            return self.rlr
        elif offset == self.SR:
            # Return current SR and clear update flags (simulating instant completion)
            # On real hardware, PVU/RVU/WVU clear after ~5-6 LSI cycles (~200us)
            sr_val = self.sr
            self.sr = 0  # Clear all update flags
            return sr_val
        elif offset == self.WINR:
            return self.winr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.KR:
            self._handle_key(value)
        elif offset == self.PR and self._unlocked:
            self.pr = value & 0x7
            self.sr |= self.SR_PVU
        elif offset == self.RLR and self._unlocked:
            self.rlr = value & 0xFFF
            self.sr |= self.SR_RVU
        elif offset == self.WINR and self._unlocked:
            self.winr = value & 0xFFF
            self.sr |= self.SR_WVU

    def _handle_key(self, value: int):
        if value == self.KEY_ENABLE:
            self.enabled = True
            self.counter = self.rlr
            self._unlocked = False
        elif value == self.KEY_RELOAD:
            self.counter = self.rlr
        elif value == self.KEY_UNLOCK:
            self._unlocked = True

    def tick(self) -> bool:
        """Process IWDG tick. Returns True if reset triggered."""
        if not self.enabled:
            return False

        # Clear update flags
        self.sr = 0

        if self.counter > 0:
            self.counter -= 1
        else:
            return True  # Watchdog reset!

        return False


class STM32WWDG(STM32Peripheral):
    """
    STM32 Window Watchdog.

    Features:
    - 7-bit down counter
    - Configurable window
    - Early wakeup interrupt
    """

    CR = 0x00    # Control
    CFR = 0x04   # Configuration
    SR = 0x08    # Status

    # CR bits
    CR_T = 0x7F       # Counter
    CR_WDGA = 1 << 7  # Activation

    # CFR bits
    CFR_W = 0x7F      # Window
    CFR_WDGTB = 0x3 << 7   # Timer base (F4) / 0x7 << 11 (L4/H7)
    CFR_EWI = 1 << 9  # Early wakeup interrupt

    # SR bits
    SR_EWIF = 1 << 0  # Early wakeup interrupt flag

    def __init__(self, base: int = 0x40002C00, family: str = "F4"):
        super().__init__("WWDG", base, 0x400, irq=0)  # IRQ varies by device
        self.family = family

        self.cr = 0x7F
        self.cfr = 0x7F
        self.sr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.CFR:
            return self.cfr
        elif offset == self.SR:
            return self.sr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.CFR:
            self.cfr = value
        elif offset == self.SR:
            self.sr &= ~value  # Write 0 to clear

    def tick(self) -> bool:
        """Process WWDG tick. Returns True if reset triggered."""
        if not (self.cr & self.CR_WDGA):
            return False

        t = self.cr & self.CR_T
        if t == 0x40:
            return True  # Reset

        # Early wakeup interrupt
        if t == 0x40 and (self.cfr & self.CFR_EWI):
            self.sr |= self.SR_EWIF
            self.trigger_irq(1)

        self.cr = (self.cr & ~self.CR_T) | ((t - 1) & self.CR_T)
        return False


class STM32RTC(STM32Peripheral):
    """
    STM32 Real-Time Clock.

    Features:
    - Calendar (BCD format)
    - Alarms (2 alarms on most devices)
    - Wakeup timer
    - Timestamp
    - Backup registers
    """

    TR = 0x00       # Time
    DR = 0x04       # Date
    CR = 0x08       # Control
    ISR = 0x0C      # Initialization/status
    PRER = 0x10     # Prescaler
    WUTR = 0x14     # Wakeup timer
    ALRMAR = 0x1C   # Alarm A
    ALRMBR = 0x20   # Alarm B
    WPR = 0x24      # Write protection
    SSR = 0x28      # Sub second
    SHIFTR = 0x2C   # Shift control
    TSTR = 0x30     # Timestamp time
    TSDR = 0x34     # Timestamp date
    TSSSR = 0x38    # Timestamp sub second
    CALR = 0x3C     # Calibration
    TAMPCR = 0x40   # Tamper config (or TAFCR on F4)
    ALRMASSR = 0x44 # Alarm A sub second
    ALRMBSSR = 0x48 # Alarm B sub second
    OR = 0x4C       # Option (some families)
    BKP0R = 0x50    # Backup register 0

    # CR bits
    CR_WUCKSEL = 0x7
    CR_TSEDGE = 1 << 3
    CR_REFCKON = 1 << 4
    CR_BYPSHAD = 1 << 5
    CR_FMT = 1 << 6
    CR_ALRAE = 1 << 8
    CR_ALRBE = 1 << 9
    CR_WUTE = 1 << 10
    CR_TSE = 1 << 11
    CR_ALRAIE = 1 << 12
    CR_ALRBIE = 1 << 13
    CR_WUTIE = 1 << 14
    CR_TSIE = 1 << 15
    CR_ADD1H = 1 << 16
    CR_SUB1H = 1 << 17
    CR_BKP = 1 << 18
    CR_COSEL = 1 << 19
    CR_POL = 1 << 20
    CR_OSEL = 0x3 << 21
    CR_COE = 1 << 23

    # ISR bits
    ISR_ALRAWF = 1 << 0
    ISR_ALRBWF = 1 << 1
    ISR_WUTWF = 1 << 2
    ISR_SHPF = 1 << 3
    ISR_INITS = 1 << 4
    ISR_RSF = 1 << 5
    ISR_INITF = 1 << 6
    ISR_INIT = 1 << 7
    ISR_ALRAF = 1 << 8
    ISR_ALRBF = 1 << 9
    ISR_WUTF = 1 << 10
    ISR_TSF = 1 << 11
    ISR_TSOVF = 1 << 12
    ISR_TAMP1F = 1 << 13
    ISR_TAMP2F = 1 << 14
    ISR_TAMP3F = 1 << 15
    ISR_RECALPF = 1 << 16

    # Write protection keys
    WP_KEY1 = 0xCA
    WP_KEY2 = 0x53

    def __init__(self, base: int = 0x40002800, num_backup: int = 20):
        super().__init__("RTC", base, 0x400, irq=41)  # RTC Alarm IRQ
        self.num_backup = num_backup

        # Time/date in BCD
        self.tr = 0
        self.dr = 0x00002101  # Jan 1, Monday
        self.cr = 0
        self.isr = self.ISR_INITS | self.ISR_RSF
        self.prer = 0x007F00FF  # Default async/sync prescaler
        self.wutr = 0xFFFF
        self.alrmar = 0
        self.alrmbr = 0
        self.ssr = 0

        # Backup registers
        self.bkp = [0] * num_backup

        # Write protection state
        self._wp_state = 0
        self._write_enabled = False

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.TR:
            return self.tr
        elif offset == self.DR:
            return self.dr
        elif offset == self.CR:
            return self.cr
        elif offset == self.ISR:
            return self.isr
        elif offset == self.PRER:
            return self.prer
        elif offset == self.WUTR:
            return self.wutr
        elif offset == self.ALRMAR:
            return self.alrmar
        elif offset == self.ALRMBR:
            return self.alrmbr
        elif offset == self.SSR:
            return self.ssr
        elif offset >= self.BKP0R:
            idx = (offset - self.BKP0R) // 4
            if idx < self.num_backup:
                return self.bkp[idx]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.WPR:
            self._handle_wp(value)
            return

        if not self._write_enabled and offset not in [self.ISR]:
            return  # Write protected

        if offset == self.TR:
            if self.isr & self.ISR_INITF:
                self.tr = value
        elif offset == self.DR:
            if self.isr & self.ISR_INITF:
                self.dr = value
        elif offset == self.CR:
            self.cr = value
        elif offset == self.ISR:
            self._write_isr(value)
        elif offset == self.PRER:
            if self.isr & self.ISR_INITF:
                self.prer = value
        elif offset == self.WUTR:
            self.wutr = value
        elif offset == self.ALRMAR:
            self.alrmar = value
        elif offset == self.ALRMBR:
            self.alrmbr = value
        elif offset >= self.BKP0R:
            idx = (offset - self.BKP0R) // 4
            if idx < self.num_backup:
                self.bkp[idx] = value

    def _handle_wp(self, value: int):
        if self._wp_state == 0 and value == self.WP_KEY1:
            self._wp_state = 1
        elif self._wp_state == 1 and value == self.WP_KEY2:
            self._write_enabled = True
            self._wp_state = 0
        else:
            self._write_enabled = False
            self._wp_state = 0

    def _write_isr(self, value: int):
        # INIT bit handling
        if value & self.ISR_INIT:
            self.isr |= self.ISR_INIT | self.ISR_INITF
            self.isr |= self.ISR_ALRAWF | self.ISR_ALRBWF | self.ISR_WUTWF
        else:
            self.isr &= ~(self.ISR_INIT | self.ISR_INITF)

        # Clear flags (write 0)
        clear_mask = (self.ISR_ALRAF | self.ISR_ALRBF | self.ISR_WUTF |
                     self.ISR_TSF | self.ISR_TSOVF |
                     self.ISR_TAMP1F | self.ISR_TAMP2F | self.ISR_TAMP3F)
        self.isr &= ~(~value & clear_mask)


class STM32CRC(STM32Peripheral):
    """
    STM32 CRC Calculation Unit.

    Features:
    - CRC-32 (Ethernet polynomial)
    - Configurable polynomial (L4/H7)
    - Configurable input/output bit reversal
    """

    DR = 0x00    # Data register
    IDR = 0x04   # Independent data (8-bit)
    CR = 0x08    # Control
    INIT = 0x10  # Initial value (L4/H7)
    POL = 0x14   # Polynomial (L4/H7)

    # CR bits
    CR_RESET = 1 << 0
    CR_POLYSIZE = 0x3 << 3  # L4/H7
    CR_REV_IN = 0x3 << 5    # L4/H7
    CR_REV_OUT = 1 << 7     # L4/H7

    # CRC-32 polynomial (Ethernet)
    CRC32_POLY = 0x04C11DB7

    def __init__(self, base: int = 0x40023000, family: str = "F4"):
        super().__init__("CRC", base, 0x400)
        self.family = family

        self.dr = 0xFFFFFFFF
        self.idr = 0
        self.cr = 0
        self.init = 0xFFFFFFFF
        self.pol = self.CRC32_POLY

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.DR:
            return self.dr
        elif offset == self.IDR:
            return self.idr
        elif offset == self.CR:
            return self.cr & ~self.CR_RESET  # RESET always reads 0
        elif offset == self.INIT:
            return self.init
        elif offset == self.POL:
            return self.pol
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.DR:
            self._compute_crc(value, size)
        elif offset == self.IDR:
            self.idr = value & 0xFF
        elif offset == self.CR:
            self.cr = value
            if value & self.CR_RESET:
                self.dr = self.init
        elif offset == self.INIT:
            self.init = value
        elif offset == self.POL:
            self.pol = value

    def _compute_crc(self, data: int, size: int):
        """Compute CRC over input data."""
        # Reverse input if configured
        if self.family in ["L4", "H7", "U5"]:
            rev_in = (self.cr >> 5) & 0x3
            if rev_in == 1:  # By byte
                data = self._reverse_bytes(data, size)
            elif rev_in == 2:  # By half-word
                data = self._reverse_halfwords(data, size)
            elif rev_in == 3:  # By word
                data = self._reverse_bits(data, 32)

        # CRC calculation
        for i in range(size * 8):
            if (self.dr ^ data) & 0x80000000:
                self.dr = ((self.dr << 1) ^ self.pol) & 0xFFFFFFFF
            else:
                self.dr = (self.dr << 1) & 0xFFFFFFFF
            data = (data << 1) & 0xFFFFFFFF

        # Reverse output if configured
        if self.family in ["L4", "H7", "U5"] and (self.cr & self.CR_REV_OUT):
            self.dr = self._reverse_bits(self.dr, 32)

    def _reverse_bits(self, value: int, bits: int) -> int:
        result = 0
        for i in range(bits):
            if value & (1 << i):
                result |= 1 << (bits - 1 - i)
        return result

    def _reverse_bytes(self, value: int, size: int) -> int:
        result = 0
        for i in range(size):
            byte = (value >> (i * 8)) & 0xFF
            result |= self._reverse_bits(byte, 8) << (i * 8)
        return result

    def _reverse_halfwords(self, value: int, size: int) -> int:
        result = 0
        for i in range(size // 2):
            hw = (value >> (i * 16)) & 0xFFFF
            result |= self._reverse_bits(hw, 16) << (i * 16)
        return result


class STM32RNG(STM32Peripheral):
    """
    STM32 Random Number Generator.

    Features:
    - True random number generator (TRNG)
    - Continuous health tests
    - Seed error detection
    """

    CR = 0x00    # Control
    SR = 0x04    # Status
    DR = 0x08    # Data
    HTCR = 0x10  # Health test (H7/U5)

    # CR bits
    CR_RNGEN = 1 << 2     # RNG enable
    CR_IE = 1 << 3        # Interrupt enable
    CR_CED = 1 << 5       # Clock error detection disable
    CR_ARDIS = 1 << 7     # Auto reset disable (H7)
    CR_RNG_CONFIG3 = 0xF << 8   # H7/U5
    CR_NISTC = 1 << 12    # NIST compliance (H7/U5)
    CR_RNG_CONFIG2 = 0x7 << 13  # H7/U5
    CR_CLKDIV = 0xF << 16 # Clock divider (H7/U5)
    CR_RNG_CONFIG1 = 0x3F << 20 # H7/U5
    CR_CONDRST = 1 << 30  # Conditioning reset (H7/U5)

    # SR bits
    SR_DRDY = 1 << 0      # Data ready
    SR_CECS = 1 << 1      # Clock error current
    SR_SECS = 1 << 2      # Seed error current
    SR_CEIS = 1 << 5      # Clock error interrupt
    SR_SEIS = 1 << 6      # Seed error interrupt

    def __init__(self, base: int = 0x50060800, family: str = "F4"):
        super().__init__("RNG", base, 0x400, irq=80)
        self.family = family

        self.cr = 0
        self.sr = 0
        self._data_ready = False

        # Simulated entropy source
        import random
        self._rng = random.Random()

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self._get_sr()
        elif offset == self.DR:
            return self._get_dr()
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
            if value & self.CR_RNGEN:
                self._data_ready = True
        elif offset == self.SR:
            # Clear error flags (write 0)
            self.sr &= value | ~(self.SR_CEIS | self.SR_SEIS)

    def _get_sr(self) -> int:
        sr = self.sr
        if self.cr & self.CR_RNGEN:
            sr |= self.SR_DRDY
        return sr

    def _get_dr(self) -> int:
        if not (self.cr & self.CR_RNGEN):
            return 0

        # Return random 32-bit value
        return self._rng.getrandbits(32)


class STM32ICACHE(STM32Peripheral):
    """
    STM32H5 Instruction Cache Controller.

    The ICACHE provides instruction caching for improved performance.
    HAL_Init() typically enables ICACHE during startup.

    Register Map:
        0x00: CR    - Control register
        0x04: SR    - Status register
        0x08: IER   - Interrupt enable register
        0x0C: FCR   - Flag clear register
        0x10: HMONR - Hit monitor register
        0x14: MMONR - Miss monitor register
        0x20: CRR0  - Cache region 0 configuration
        ...
    """

    CR = 0x00      # Control
    SR = 0x04      # Status
    IER = 0x08     # Interrupt enable
    FCR = 0x0C     # Flag clear
    HMONR = 0x10   # Hit monitor
    MMONR = 0x14   # Miss monitor
    CRR0 = 0x20    # Region 0
    CRR1 = 0x24    # Region 1
    CRR2 = 0x28    # Region 2
    CRR3 = 0x2C    # Region 3

    # CR bits
    CR_EN = 1 << 0        # Cache enable
    CR_CACHEINV = 1 << 1  # Cache invalidation request
    CR_WAYSEL = 1 << 2    # Way selection (direct mapped)
    CR_HITMEN = 1 << 16   # Hit monitor enable
    CR_MISSMEN = 1 << 17  # Miss monitor enable
    CR_HITMRST = 1 << 18  # Hit monitor reset
    CR_MISSMRST = 1 << 19 # Miss monitor reset

    # SR bits
    SR_BUSYF = 1 << 0     # Busy flag
    SR_BSYENDF = 1 << 1   # Busy end flag (invalidation complete)
    SR_ERRF = 1 << 2      # Error flag

    def __init__(self, base: int = 0x40030000):
        super().__init__("ICACHE", base, 0x400)

        # Registers - initialized to "cache ready" state
        self.cr = 0  # Cache disabled by default
        self.sr = self.SR_BSYENDF  # Not busy, operation complete
        self.ier = 0
        self.hmonr = 0
        self.mmonr = 0
        self.crr = [0, 0, 0, 0]

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.SR:
            return self._get_sr()
        elif offset == self.IER:
            return self.ier
        elif offset == self.HMONR:
            return self.hmonr
        elif offset == self.MMONR:
            return self.mmonr
        elif offset == self.CRR0:
            return self.crr[0]
        elif offset == self.CRR1:
            return self.crr[1]
        elif offset == self.CRR2:
            return self.crr[2]
        elif offset == self.CRR3:
            return self.crr[3]
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.IER:
            self.ier = value
        elif offset == self.FCR:
            # Flag clear - write 1 to clear
            if value & self.SR_BSYENDF:
                self.sr &= ~self.SR_BSYENDF
            if value & self.SR_ERRF:
                self.sr &= ~self.SR_ERRF
        elif offset == self.CRR0:
            self.crr[0] = value
        elif offset == self.CRR1:
            self.crr[1] = value
        elif offset == self.CRR2:
            self.crr[2] = value
        elif offset == self.CRR3:
            self.crr[3] = value

    def _write_cr(self, value: int):
        old_cr = self.cr
        self.cr = value

        # Handle cache invalidation request
        if value & self.CR_CACHEINV:
            # Instant invalidation complete
            self.cr &= ~self.CR_CACHEINV  # Clear request bit
            self.sr |= self.SR_BSYENDF    # Set completion flag
            self.sr &= ~self.SR_BUSYF     # Not busy

        # Handle monitor resets
        if value & self.CR_HITMRST:
            self.hmonr = 0
            self.cr &= ~self.CR_HITMRST
        if value & self.CR_MISSMRST:
            self.mmonr = 0
            self.cr &= ~self.CR_MISSMRST

    def _get_sr(self) -> int:
        # Cache is never busy in emulation (instant operations)
        return self.sr & ~self.SR_BUSYF


class STM32DBG(STM32Peripheral):
    """
    STM32 Debug Support.

    Features:
    - Device ID (IDCODE)
    - Debug freeze for peripherals
    """

    IDCODE = 0x00   # Device ID
    CR = 0x04       # Control
    APB1FZR1 = 0x08 # APB1 freeze 1 (L4/H7)
    APB1FZR2 = 0x0C # APB1 freeze 2
    APB2FZR = 0x10  # APB2 freeze

    # Device IDs
    DEVICE_IDS = {
        "F103": 0x10016414,
        "F405": 0x10016413,
        "F407": 0x10016413,
        "F429": 0x10016419,
        "F439": 0x10016419,
        "L476": 0x10016415,
        "H743": 0x10016450,
        "H753": 0x10016450,
        "WB55": 0x10016495,
        "U5A5": 0x10016482,
    }

    def __init__(self, base: int = 0xE0042000, device: str = "F407"):
        super().__init__("DBG", base, 0x400)
        self.device = device

        self.idcode = self.DEVICE_IDS.get(device, 0x10016413)
        self.cr = 0
        self.apb1fzr1 = 0
        self.apb1fzr2 = 0
        self.apb2fzr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.IDCODE:
            return self.idcode
        elif offset == self.CR:
            return self.cr
        elif offset == self.APB1FZR1:
            return self.apb1fzr1
        elif offset == self.APB1FZR2:
            return self.apb1fzr2
        elif offset == self.APB2FZR:
            return self.apb2fzr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self.cr = value
        elif offset == self.APB1FZR1:
            self.apb1fzr1 = value
        elif offset == self.APB1FZR2:
            self.apb1fzr2 = value
        elif offset == self.APB2FZR:
            self.apb2fzr = value
