"""
RP2350-Specific Peripherals

Implements peripherals unique to RP2350:
- SHA256 - Hardware SHA-256 accelerator
- TRNG - True Random Number Generator
- OTP - One-Time Programmable memory
- HSTX - High-Speed TX interface
- POWMAN - Power Manager
- GLITCH_DETECTOR - Glitch/fault detection
- PIO2 - Third PIO block
- ACCESSCTRL - Security access control
- QMI - QSPI Memory Interface

References:
- RP2350 Datasheet

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
import hashlib
import secrets
from typing import Dict, List, Optional, Callable, Tuple

try:
    from .rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR
except ImportError:
    from rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR


# =============================================================================
# SHA256 - 0x400F8000
# =============================================================================

class RP2350SHA256(RP2040Peripheral):
    """
    RP2350 SHA-256 Hardware Accelerator.

    Provides hardware-accelerated SHA-256 hashing.

    Register Map:
        0x00: CSR       - Control/status
        0x04: WDATA     - Write data (32-bit words)
        0x08: SUM0-SUM7 - Hash result (8 x 32-bit)
    """

    CSR = 0x00
    WDATA = 0x04
    SUM0 = 0x08
    SUM1 = 0x0C
    SUM2 = 0x10
    SUM3 = 0x14
    SUM4 = 0x18
    SUM5 = 0x1C
    SUM6 = 0x20
    SUM7 = 0x24

    # CSR bits
    CSR_SUM_VLD = 1 << 24
    CSR_WDATA_RDY = 1 << 16
    CSR_ERR_WDATA_NOT_RDY = 1 << 10
    CSR_DMA_SIZE_MASK = 0x3 << 8
    CSR_BSWAP = 1 << 4
    CSR_START = 1 << 1
    CSR_EN = 1 << 0

    def __init__(self, base: int = 0x400F8000):
        super().__init__("SHA256", base, 0x100)

        self.csr = 0
        self.data_buffer = bytearray()
        self.hash_result = bytes(32)

        # Use Python's hashlib for actual computation
        self.hasher: Optional[hashlib._Hash] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CSR:
            csr = self.csr
            # Always ready to accept data when enabled
            if self.csr & self.CSR_EN:
                csr |= self.CSR_WDATA_RDY
            # Result valid after computation
            if len(self.hash_result) == 32 and not self.hasher:
                csr |= self.CSR_SUM_VLD
            return csr

        elif self.SUM0 <= offset <= self.SUM7:
            idx = (offset - self.SUM0) // 4
            if idx < 8 and len(self.hash_result) >= (idx + 1) * 4:
                return int.from_bytes(self.hash_result[idx*4:(idx+1)*4], 'big')
            return 0

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CSR:
            self.csr = value & 0xFFFF

            if value & self.CSR_START:
                # Start new hash
                self.hasher = hashlib.sha256()
                self.data_buffer.clear()
                self.log.debug("SHA256 started")

            if not (value & self.CSR_EN):
                # Finalize when disabled
                if self.hasher:
                    if self.data_buffer:
                        self.hasher.update(bytes(self.data_buffer))
                    self.hash_result = self.hasher.digest()
                    self.hasher = None
                    self.log.debug(f"SHA256 result: {self.hash_result.hex()}")

        elif offset == self.WDATA:
            if self.hasher:
                # Add 32-bit word to buffer
                if self.csr & self.CSR_BSWAP:
                    data = value.to_bytes(4, 'little')
                else:
                    data = value.to_bytes(4, 'big')
                self.data_buffer.extend(data)

                # Process in 64-byte blocks
                while len(self.data_buffer) >= 64:
                    self.hasher.update(bytes(self.data_buffer[:64]))
                    self.data_buffer = self.data_buffer[64:]

        else:
            self.regs[offset] = value

    def compute_hash(self, data: bytes) -> bytes:
        """Convenience method to compute SHA-256 hash."""
        return hashlib.sha256(data).digest()


# =============================================================================
# TRNG - 0x400F0000
# =============================================================================

class RP2350TRNG(RP2040Peripheral):
    """
    RP2350 True Random Number Generator.

    ARM TrustZone RNG providing cryptographically secure random numbers.

    Register Map:
        0x000-0x0FC: RNG_IMR/ISR/ICR (interrupt)
        0x100: TRNG_CONFIG
        0x104: TRNG_VALID
        0x108-0x11C: EHR_DATA0-5 (entropy)
        0x120: RND_SOURCE_ENABLE
        ...
    """

    # Key registers
    TRNG_CONFIG = 0x100
    TRNG_VALID = 0x104
    EHR_DATA0 = 0x108
    EHR_DATA1 = 0x10C
    EHR_DATA2 = 0x110
    EHR_DATA3 = 0x114
    EHR_DATA4 = 0x118
    EHR_DATA5 = 0x11C
    RND_SOURCE_ENABLE = 0x120
    SAMPLE_CNT1 = 0x124
    AUTOCORR_STATISTIC = 0x128
    TRNG_SW_RESET = 0x140

    def __init__(self, base: int = 0x400F0000):
        super().__init__("TRNG", base, 0x200)

        self.enabled = False
        self.valid = True  # Always have entropy available

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.TRNG_VALID:
            return 1 if self.valid else 0

        elif self.EHR_DATA0 <= offset <= self.EHR_DATA5:
            # Return cryptographically secure random bytes
            return secrets.randbits(32)

        elif offset == self.RND_SOURCE_ENABLE:
            return 1 if self.enabled else 0

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.RND_SOURCE_ENABLE:
            self.enabled = bool(value & 1)

        elif offset == self.TRNG_SW_RESET:
            if value & 1:
                self.enabled = False

        else:
            self.regs[offset] = value

    def get_random_bytes(self, count: int) -> bytes:
        """Get random bytes."""
        return secrets.token_bytes(count)


# =============================================================================
# OTP - 0x40120000
# =============================================================================

class RP2350OTP(RP2040Peripheral):
    """
    RP2350 OTP (One-Time Programmable) Memory.

    8KB of OTP storage for:
    - Boot keys
    - Security configuration
    - Device serial number
    - Calibration data

    Register Map:
        0x000: SW_LOCK0-63    - Software write lock
        0x100: SBPI_INSTR     - OTP programming instruction
        0x104: SBPI_WDATA0-3  - Write data
        0x114: SBPI_RDATA0-3  - Read data
        0x124: SBPI_STATUS    - Status
        ...
    """

    SW_LOCK0 = 0x000  # Through SW_LOCK63 at 0x0FC
    SBPI_INSTR = 0x100
    SBPI_WDATA0 = 0x104
    SBPI_RDATA0 = 0x114
    SBPI_STATUS = 0x124
    USR_WDATA0 = 0x128
    USR_RDATA0 = 0x138
    DBG_WDATA0 = 0x148
    DBG_RDATA0 = 0x158

    # OTP size
    OTP_SIZE = 8192  # 8KB

    def __init__(self, base: int = 0x40120000):
        super().__init__("OTP", base, 0x200)

        # OTP storage (simulated - not actually one-time)
        self.otp_data = bytearray(self.OTP_SIZE)

        # Lock bits (64 regions of 128 bytes each)
        self.locks = [0] * 64

        # Pre-populate some OTP data
        self._init_otp_data()

    def _init_otp_data(self):
        """Initialize OTP with default values."""
        # Device ID at offset 0
        self.otp_data[0:4] = b'RP23'

        # Serial number
        self.otp_data[0x10:0x18] = secrets.token_bytes(8)

    def _read_reg(self, offset: int, size: int) -> int:
        if self.SW_LOCK0 <= offset < self.SW_LOCK0 + 64 * 4:
            idx = (offset - self.SW_LOCK0) // 4
            return self.locks[idx]

        elif offset == self.SBPI_STATUS:
            return 0  # Not busy

        elif self.SBPI_RDATA0 <= offset < self.SBPI_RDATA0 + 16:
            # Return OTP data
            idx = (offset - self.SBPI_RDATA0) // 4
            return int.from_bytes(self.otp_data[idx*4:(idx+1)*4], 'little')

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if self.SW_LOCK0 <= offset < self.SW_LOCK0 + 64 * 4:
            idx = (offset - self.SW_LOCK0) // 4
            # Locks can only be set, not cleared
            self.locks[idx] |= value

        else:
            self.regs[offset] = value

    def read_otp(self, offset: int, size: int) -> bytes:
        """Read OTP data."""
        if offset + size <= self.OTP_SIZE:
            return bytes(self.otp_data[offset:offset + size])
        return bytes(size)


# =============================================================================
# OTP_DATA - 0x40130000
# =============================================================================

class RP2350OTPData(RP2040Peripheral):
    """
    RP2350 OTP Data - Direct read access to OTP memory.

    This is a memory-mapped view of the OTP contents.
    """

    def __init__(self, otp: RP2350OTP, base: int = 0x40130000):
        super().__init__("OTP_DATA", base, 0x2000)
        self.otp = otp

    def _read_reg(self, offset: int, size: int) -> int:
        if offset < self.otp.OTP_SIZE:
            data = self.otp.otp_data[offset:offset + size]
            return int.from_bytes(data.ljust(4, b'\x00'), 'little')
        return 0


# =============================================================================
# HSTX_CTRL - 0x400C0000
# =============================================================================

class RP2350HSTX(RP2040Peripheral):
    """
    RP2350 High-Speed TX Interface.

    High-speed serial output for driving displays, etc.

    Register Map:
        0x00: CSR          - Control/status
        0x04: BIT0-7       - Bit pattern registers
        0x24: EXPAND_SHIFT - Expansion shift
        0x28: EXPAND_TMDS  - TMDS expansion
    """

    CSR = 0x00
    BIT0 = 0x04
    BIT1 = 0x08
    BIT2 = 0x0C
    BIT3 = 0x10
    BIT4 = 0x14
    BIT5 = 0x18
    BIT6 = 0x1C
    BIT7 = 0x20
    EXPAND_SHIFT = 0x24
    EXPAND_TMDS = 0x28

    # CSR bits
    CSR_COUPLED_SEL_MASK = 0x3 << 24
    CSR_COUPLED_MODE = 1 << 20
    CSR_EXPAND_EN = 1 << 12
    CSR_N_MASK = 0x7 << 8
    CSR_SHIFT_MASK = 0x1F << 0

    def __init__(self, base: int = 0x400C0000):
        super().__init__("HSTX", base, 0x100)


# =============================================================================
# HSTX_FIFO - 0x50600000
# =============================================================================

class RP2350HSTXFIFO(RP2040Peripheral):
    """
    RP2350 HSTX FIFO - Data FIFO for HSTX output.

    Register Map:
        0x00: STAT  - FIFO status
        0x04: FIFO  - FIFO write
    """

    STAT = 0x00
    FIFO = 0x04

    def __init__(self, base: int = 0x50600000):
        super().__init__("HSTX_FIFO", base, 0x100)

        self.fifo: List[int] = []
        self.fifo_size = 8

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.STAT:
            # Level in bits 7:0, full in bit 10, empty in bit 11
            stat = len(self.fifo)
            if len(self.fifo) >= self.fifo_size:
                stat |= (1 << 10)
            if not self.fifo:
                stat |= (1 << 11)
            return stat
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.FIFO:
            if len(self.fifo) < self.fifo_size:
                self.fifo.append(value)
        else:
            self.regs[offset] = value


# =============================================================================
# POWMAN - 0x40100000
# =============================================================================

class RP2350POWMAN(RP2040Peripheral):
    """
    RP2350 Power Manager.

    Replaces VREG_AND_CHIP_RESET with more comprehensive power management.

    Register Map:
        0x00: BADPASSWD        - Bad password detection
        0x04: VREG_CTRL        - Voltage regulator control
        0x08: VREG_STS         - Voltage regulator status
        0x0C: VREG_LP_ENTRY    - Low power entry
        0x10: VREG_LP_EXIT     - Low power exit
        0x14: BOD_CTRL         - Brown-out detector
        0x18: BOD_LP_ENTRY
        0x1C: BOD_LP_EXIT
        0x20: LPOSC            - Low-power oscillator
        0x24: CHIP_RESET       - Chip reset control
        0x28: WDSEL            - Watchdog select
        0x2C: TIMER            - Power timer
        ...
    """

    BADPASSWD = 0x00
    VREG_CTRL = 0x04
    VREG_STS = 0x08
    VREG_LP_ENTRY = 0x0C
    VREG_LP_EXIT = 0x10
    BOD_CTRL = 0x14
    BOD_LP_ENTRY = 0x18
    BOD_LP_EXIT = 0x1C
    LPOSC = 0x20
    CHIP_RESET = 0x24
    WDSEL = 0x28
    TIMER = 0x2C
    STATE = 0x30

    def __init__(self, base: int = 0x40100000):
        super().__init__("POWMAN", base, 0x100)

        # Default: VREG at 1.1V, enabled, OK
        self.regs[self.VREG_CTRL] = 0x000B0001  # 1.1V, enabled
        self.regs[self.VREG_STS] = 0x00010000   # VREG OK
        self.regs[self.BOD_CTRL] = 0x00000091   # BOD enabled


# =============================================================================
# GLITCH_DETECTOR - 0x40158000
# =============================================================================

class RP2350GlitchDetector(RP2040Peripheral):
    """
    RP2350 Glitch Detector.

    Hardware protection against voltage/clock glitch attacks.

    Register Map:
        0x00: ARM            - Arm the detector
        0x04: DISARM         - Disarm the detector
        0x08: SENSITIVITY    - Sensitivity setting
        0x0C: LOCK           - Lock configuration
        0x10: TRIG_STATUS    - Trigger status
        0x14: TRIG_FORCE     - Force trigger (testing)
    """

    ARM = 0x00
    DISARM = 0x04
    SENSITIVITY = 0x08
    LOCK = 0x0C
    TRIG_STATUS = 0x10
    TRIG_FORCE = 0x14

    def __init__(self, base: int = 0x40158000):
        super().__init__("GLITCH_DET", base, 0x100)

        self.armed = False
        self.sensitivity = 0
        self.locked = False
        self.triggered = False

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ARM:
            return 1 if self.armed else 0
        elif offset == self.SENSITIVITY:
            return self.sensitivity
        elif offset == self.LOCK:
            return 1 if self.locked else 0
        elif offset == self.TRIG_STATUS:
            return 1 if self.triggered else 0
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ARM:
            if not self.locked:
                self.armed = True
        elif offset == self.DISARM:
            if not self.locked:
                self.armed = False
        elif offset == self.SENSITIVITY:
            if not self.locked:
                self.sensitivity = value & 0xFF
        elif offset == self.LOCK:
            self.locked = True  # Can only be set, not cleared
        elif offset == self.TRIG_FORCE:
            if value & 1:
                self.triggered = True
        elif offset == self.TRIG_STATUS:
            # Write 1 to clear
            if value & 1:
                self.triggered = False


# =============================================================================
# ACCESSCTRL - 0x40060000
# =============================================================================

class RP2350ACCESSCTRL(RP2040Peripheral):
    """
    RP2350 Access Control.

    Hardware access control for security domain assignment.
    Controls which bus masters can access which peripherals.

    Register Map:
        0x00: LOCK              - Lock configuration
        0x04: FORCE_CORE_NS     - Force core non-secure
        0x08: CFGRESET          - Config reset
        0x0C-0xE8: Peripheral access control registers
    """

    LOCK = 0x00
    FORCE_CORE_NS = 0x04
    CFGRESET = 0x08

    def __init__(self, base: int = 0x40060000):
        super().__init__("ACCESSCTRL", base, 0x100)

        self.locked = False

        # Default: all peripherals accessible from all domains
        for offset in range(0x0C, 0xEC, 4):
            self.regs[offset] = 0xFFFFFFFF

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.LOCK:
            self.locked = True
        elif not self.locked:
            self.regs[offset] = value


# =============================================================================
# TICKS - 0x40108000
# =============================================================================

class RP2350TICKS(RP2040Peripheral):
    """
    RP2350 Ticks - Time reference block.

    Provides tick generators for various timebases.

    Register Map:
        0x00: PROC0_CTRL    - Processor 0 tick control
        0x04: PROC0_CYCLES  - Cycles per tick
        0x08: PROC0_COUNT   - Current count
        ...
        (similar for PROC1, TIMER0, TIMER1, WATCHDOG, RISCV)
    """

    PROC0_CTRL = 0x00
    PROC0_CYCLES = 0x04
    PROC0_COUNT = 0x08
    PROC1_CTRL = 0x0C
    PROC1_CYCLES = 0x10
    PROC1_COUNT = 0x14
    TIMER0_CTRL = 0x18
    TIMER0_CYCLES = 0x1C
    TIMER0_COUNT = 0x20
    TIMER1_CTRL = 0x24
    TIMER1_CYCLES = 0x28
    TIMER1_COUNT = 0x2C
    WATCHDOG_CTRL = 0x30
    WATCHDOG_CYCLES = 0x34
    WATCHDOG_COUNT = 0x38
    RISCV_CTRL = 0x3C
    RISCV_CYCLES = 0x40
    RISCV_COUNT = 0x44

    def __init__(self, base: int = 0x40108000):
        super().__init__("TICKS", base, 0x100)

        # Default: 1 cycle per tick
        for offset in [self.PROC0_CYCLES, self.PROC1_CYCLES,
                      self.TIMER0_CYCLES, self.TIMER1_CYCLES,
                      self.WATCHDOG_CYCLES, self.RISCV_CYCLES]:
            self.regs[offset] = 1


# =============================================================================
# QMI - 0x400D0000
# =============================================================================

class RP2350QMI(RP2040Peripheral):
    """
    RP2350 QSPI Memory Interface.

    Replaces XIP_SSI with more advanced QSPI/PSRAM controller.

    Register Map:
        0x00: DIRECT_CSR    - Direct mode control/status
        0x04: DIRECT_TX     - Direct mode TX
        0x08: DIRECT_RX     - Direct mode RX
        0x0C: M0_TIMING     - Memory 0 timing
        0x10: M0_RFMT       - Memory 0 read format
        0x14: M0_RCMD       - Memory 0 read command
        0x18: M0_WFMT       - Memory 0 write format
        0x1C: M0_WCMD       - Memory 0 write command
        0x20: M1_TIMING     - Memory 1 timing
        ...
        0x38: ATRANS0       - Address translation 0
        ...
    """

    DIRECT_CSR = 0x00
    DIRECT_TX = 0x04
    DIRECT_RX = 0x08
    M0_TIMING = 0x0C
    M0_RFMT = 0x10
    M0_RCMD = 0x14
    M0_WFMT = 0x18
    M0_WCMD = 0x1C
    M1_TIMING = 0x20
    M1_RFMT = 0x24
    M1_RCMD = 0x28
    M1_WFMT = 0x2C
    M1_WCMD = 0x30
    ATRANS0 = 0x38

    def __init__(self, base: int = 0x400D0000):
        super().__init__("QMI", base, 0x100)

        # Default timing for 133MHz operation
        self.regs[self.M0_TIMING] = 0x40000004
        self.regs[self.M1_TIMING] = 0x40000004


# =============================================================================
# RP2350 BOOTROM PERIPHERALS
# These peripherals have different base addresses than RP2040
# =============================================================================


# =============================================================================
# RP2350_SYSINFO - 0x40000000
# =============================================================================

class RP2350SYSINFO(RP2040Peripheral):
    """
    RP2350 System Information.

    Register Map:
        0x00: CHIP_ID    - Chip identifier
        0x04: PACKAGE_SEL - Package selection
        0x08: PLATFORM   - Platform (ASIC/FPGA)
        0x0C: GITREF_RP2350 - Git reference
    """

    CHIP_ID = 0x00
    PACKAGE_SEL = 0x04
    PLATFORM = 0x08
    GITREF = 0x0C

    # RP2350 CHIP_ID: Part=0x2350, Manufacturer=0x14D (Raspberry Pi)
    # Format: [31:28]=Rev, [27:12]=Part, [11:1]=Manufacturer, [0]=1
    DEFAULT_CHIP_ID = (0 << 28) | (0x2350 << 12) | (0x14D << 1) | 1

    def __init__(self, base: int = 0x40000000):
        super().__init__("RP2350_SYSINFO", base, 0x100)

        self.regs[self.CHIP_ID] = self.DEFAULT_CHIP_ID
        self.regs[self.PACKAGE_SEL] = 0x00000000
        self.regs[self.PLATFORM] = 0x00000002  # ASIC=1, FPGA=0


# =============================================================================
# RP2350_ROSC - 0x400E4000 (Ring Oscillator)
# =============================================================================

class RP2350ROSC(RP2040Peripheral):
    """
    RP2350 Ring Oscillator (LPOSC in POWMAN).

    The RP2350 integrates the ring oscillator into the power manager.
    This provides a basic oscillator for low-power operation.
    """

    CTRL = 0x00
    FREQA = 0x04
    FREQB = 0x08
    RANDOM = 0x0C
    DORMANT = 0x10
    STATUS = 0x14

    # Status bits
    STATUS_STABLE = 1 << 31
    STATUS_ENABLED = 1 << 12

    def __init__(self, base: int = 0x400E4000):
        super().__init__("RP2350_ROSC", base, 0x100)

        # Default: enabled and stable
        self.regs[self.CTRL] = 0x00000AA0  # Enable
        self.regs[self.STATUS] = self.STATUS_STABLE | self.STATUS_ENABLED

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.RANDOM:
            # Return random bits from ring oscillator
            import secrets
            return secrets.randbits(32)
        return self.regs.get(offset, 0)


# =============================================================================
# RP2350_XOSC - 0x40048000 (Crystal Oscillator)
# =============================================================================

class RP2350XOSC(RP2040Peripheral):
    """
    RP2350 Crystal Oscillator.

    Similar to RP2040 but with different enable sequence.

    Register Map:
        0x00: CTRL    - Control (enable/disable)
        0x04: STATUS  - Status (stable/badwrite)
        0x08: DORMANT - Dormant control
        0x0C: STARTUP - Startup delay
        0x10: COUNT   - Counter value
    """

    CTRL = 0x00
    STATUS = 0x04
    DORMANT = 0x08
    STARTUP = 0x0C
    COUNT = 0x10

    # Status bits
    STATUS_STABLE = 1 << 31
    STATUS_BADWRITE = 1 << 24
    STATUS_ENABLED = 1 << 12

    # Enable magic value
    ENABLE_MAGIC = 0xFAB

    def __init__(self, base: int = 0x40048000):
        super().__init__("RP2350_XOSC", base, 0x100)

        self.enabled = False
        self.startup_delay = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.STATUS:
            status = 0
            if self.enabled:
                status |= self.STATUS_STABLE | self.STATUS_ENABLED
            return status
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self.regs[offset] = value
            enable_bits = (value >> 12) & 0xFFF
            if enable_bits == self.ENABLE_MAGIC:
                self.enabled = True
                self.log.debug("XOSC enabled")
            elif enable_bits == 0xD1E:
                self.enabled = False
                self.log.debug("XOSC disabled")
        elif offset == self.STARTUP:
            self.startup_delay = value & 0x3FFF
            self.regs[offset] = value
        else:
            self.regs[offset] = value


# =============================================================================
# RP2350_PLL - 0x40050000 (PLL_SYS), 0x40058000 (PLL_USB)
# =============================================================================

class RP2350PLL(RP2040Peripheral):
    """
    RP2350 Phase-Locked Loop.

    Similar to RP2040 PLL but can achieve higher frequencies (150MHz sys).

    Register Map:
        0x00: CS      - Control/status
        0x04: PWR     - Power control
        0x08: FBDIV   - Feedback divisor
        0x0C: PRIM    - Post dividers
        0x10: INTR    - Interrupt
        0x14: INTE    - Interrupt enable
        0x18: INTF    - Interrupt force
        0x1C: INTS    - Interrupt status
    """

    CS = 0x00
    PWR = 0x04
    FBDIV = 0x08
    PRIM = 0x0C
    INTR = 0x10
    INTE = 0x14
    INTF = 0x18
    INTS = 0x1C

    # CS bits
    CS_LOCK = 1 << 31
    CS_BYPASS = 1 << 8
    CS_REFDIV_MASK = 0x3F

    # PWR bits
    PWR_VCOPD = 1 << 5
    PWR_POSTDIVPD = 1 << 3
    PWR_DSMPD = 1 << 2
    PWR_PD = 1 << 0

    def __init__(self, name: str, base: int, target_freq: int = 150000000):
        super().__init__(name, base, 0x100)

        self.target_freq = target_freq

        # Default: powered down
        self.regs[self.CS] = 0x00000001  # REFDIV=1
        self.regs[self.PWR] = 0x0000002D  # All powered down
        self.regs[self.FBDIV] = 0x00000000
        self.regs[self.PRIM] = 0x00077000  # POSTDIV1=7, POSTDIV2=7

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CS:
            cs = self.regs.get(self.CS, 0)
            # Report LOCK if VCO is powered on and FBDIV is set
            pwr = self.regs.get(self.PWR, 0x2D)
            fbdiv = self.regs.get(self.FBDIV, 0)
            if not (pwr & self.PWR_VCOPD) and fbdiv > 0:
                cs |= self.CS_LOCK
            return cs
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        self.regs[offset] = value

        if offset == self.PWR:
            if not (value & self.PWR_VCOPD):
                self.log.debug(f"{self.name} VCO powered on")


# =============================================================================
# RP2350_CLOCKS - 0x40010000
# =============================================================================

class RP2350CLOCKS(RP2040Peripheral):
    """
    RP2350 Clock Controller.

    Manages all clock generators and distribution.
    Higher frequencies than RP2040 (150MHz vs 133MHz).

    Register Map:
        0x00-0x7C: Clock generators (CLK_GPOUT0-3, CLK_REF, CLK_SYS, etc.)
        0x80-0x8C: Clock resus
        0x90-0xA0: FC0 (frequency counter)
        0xA4-0xAC: Wake enable
        0xB0-0xB8: Sleep enable
        0xBC-0xC4: Enabled status
        0xC8-0xCC: Interrupt control
    """

    # Clock generator offsets (each clock gen is 12 bytes)
    CLK_GPOUT0_CTRL = 0x00
    CLK_GPOUT0_DIV = 0x04
    CLK_GPOUT0_SELECTED = 0x08
    CLK_REF_CTRL = 0x30
    CLK_REF_DIV = 0x34
    CLK_REF_SELECTED = 0x38
    CLK_SYS_CTRL = 0x3C
    CLK_SYS_DIV = 0x40
    CLK_SYS_SELECTED = 0x44
    CLK_PERI_CTRL = 0x48
    CLK_PERI_DIV = 0x4C
    CLK_PERI_SELECTED = 0x50
    CLK_HSTX_CTRL = 0x54
    CLK_HSTX_DIV = 0x58
    CLK_HSTX_SELECTED = 0x5C
    CLK_USB_CTRL = 0x60
    CLK_USB_DIV = 0x64
    CLK_USB_SELECTED = 0x68
    CLK_ADC_CTRL = 0x6C
    CLK_ADC_DIV = 0x70
    CLK_ADC_SELECTED = 0x74

    # RESUS
    CLK_SYS_RESUS_CTRL = 0x80
    CLK_SYS_RESUS_STATUS = 0x84

    def __init__(self, base: int = 0x40010000):
        super().__init__("RP2350_CLOCKS", base, 0x100)

        # Default: clocks sourced from ring oscillator
        self.regs[self.CLK_REF_CTRL] = 0x00000000
        self.regs[self.CLK_REF_DIV] = 0x00000100  # Divide by 1
        self.regs[self.CLK_SYS_CTRL] = 0x00000000
        self.regs[self.CLK_SYS_DIV] = 0x00000100

    def _read_reg(self, offset: int, size: int) -> int:
        # SELECTED registers reflect the source based on CTRL
        if offset == self.CLK_REF_SELECTED:
            ctrl = self.regs.get(self.CLK_REF_CTRL, 0)
            src = ctrl & 0x3
            return 1 << (src + 1)
        elif offset == self.CLK_SYS_SELECTED:
            ctrl = self.regs.get(self.CLK_SYS_CTRL, 0)
            src = ctrl & 0x1
            return 1 << (src + 1)
        elif offset == self.CLK_USB_SELECTED:
            return 0x2  # PLL_USB
        elif offset == self.CLK_ADC_SELECTED:
            return 0x2  # PLL_USB

        return self.regs.get(offset, 0)


# =============================================================================
# RP2350_RESETS - 0x40020000
# =============================================================================

class RP2350RESETS(RP2040Peripheral):
    """
    RP2350 Reset Controller.

    Controls peripheral reset states. More peripherals than RP2040.

    Register Map:
        0x00: RESET       - Reset control (write 1 to reset)
        0x04: WDSEL       - Watchdog select
        0x08: RESET_DONE  - Reset done status
    """

    RESET = 0x00
    WDSEL = 0x04
    RESET_DONE = 0x08

    # RP2350 has more reset bits than RP2040
    ALL_RESETS = 0x1FFFFFFF  # 29 bits

    # Peripheral bit assignments (based on RP2350 datasheet)
    RESET_ADC = 1 << 0
    RESET_BUSCTRL = 1 << 1
    RESET_DMA = 1 << 2
    RESET_HSTX = 1 << 3
    RESET_I2C0 = 1 << 4
    RESET_I2C1 = 1 << 5
    RESET_IO_BANK0 = 1 << 6
    RESET_IO_QSPI = 1 << 7
    RESET_JTAG = 1 << 8
    RESET_PADS_BANK0 = 1 << 9
    RESET_PADS_QSPI = 1 << 10
    RESET_PIO0 = 1 << 11
    RESET_PIO1 = 1 << 12
    RESET_PIO2 = 1 << 13
    RESET_PLL_SYS = 1 << 14
    RESET_PLL_USB = 1 << 15
    RESET_PWM = 1 << 16
    RESET_SHA256 = 1 << 17
    RESET_SPI0 = 1 << 18
    RESET_SPI1 = 1 << 19
    RESET_SYSCFG = 1 << 20
    RESET_SYSINFO = 1 << 21
    RESET_TBMAN = 1 << 22
    RESET_TIMER0 = 1 << 23
    RESET_TIMER1 = 1 << 24
    RESET_TRNG = 1 << 25
    RESET_UART0 = 1 << 26
    RESET_UART1 = 1 << 27
    RESET_USBCTRL = 1 << 28

    def __init__(self, base: int = 0x40020000):
        super().__init__("RP2350_RESETS", base, 0x100)

        # Default: all peripherals in reset
        self.regs[self.RESET] = self.ALL_RESETS
        self.regs[self.WDSEL] = 0x00000000
        self.regs[self.RESET_DONE] = 0x00000000

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.RESET_DONE:
            # RESET_DONE is inverse of RESET (released peripherals report done)
            reset = self.regs.get(self.RESET, self.ALL_RESETS)
            return (~reset) & self.ALL_RESETS
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.RESET:
            old_reset = self.regs.get(self.RESET, self.ALL_RESETS)
            self.regs[self.RESET] = value & self.ALL_RESETS
            released = old_reset & ~value
            if released:
                self.log.debug(f"Released from reset: 0x{released:08x}")
        else:
            self.regs[offset] = value


# =============================================================================
# RP2350_PSM - 0x40018000 (Power-on State Machine)
# =============================================================================

class RP2350PSM(RP2040Peripheral):
    """
    RP2350 Power-on State Machine.

    Controls the power-up sequence of the chip.

    Register Map:
        0x00: FRCE_ON   - Force power on
        0x04: FRCE_OFF  - Force power off
        0x08: WDSEL     - Watchdog select
        0x0C: DONE      - Power-up done
    """

    FRCE_ON = 0x00
    FRCE_OFF = 0x04
    WDSEL = 0x08
    DONE = 0x0C

    # Power domains (more than RP2040)
    # Bits match the sequence order
    ALL_DONE = 0x0003FFFF  # 18 domains

    def __init__(self, base: int = 0x40018000):
        super().__init__("RP2350_PSM", base, 0x100)

        # Default: all domains powered up
        self.regs[self.DONE] = self.ALL_DONE

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.DONE:
            # All domains ready
            return self.ALL_DONE
        return self.regs.get(offset, 0)


# =============================================================================
# RP2350_WATCHDOG - 0x400D8000
# =============================================================================

class RP2350WATCHDOG(RP2040Peripheral):
    """
    RP2350 Watchdog Timer.

    Similar to RP2040 but at different address.

    Register Map:
        0x00: CTRL       - Control
        0x04: LOAD       - Load value
        0x08: REASON     - Reset reason
        0x0C: SCRATCH0-7 - Scratch registers (0x0C-0x28)
        0x2C: TICK       - Tick configuration
    """

    CTRL = 0x00
    LOAD = 0x04
    REASON = 0x08
    SCRATCH0 = 0x0C
    SCRATCH1 = 0x10
    SCRATCH2 = 0x14
    SCRATCH3 = 0x18
    SCRATCH4 = 0x1C
    SCRATCH5 = 0x20
    SCRATCH6 = 0x24
    SCRATCH7 = 0x28
    TICK = 0x2C

    # CTRL bits
    CTRL_TRIGGER = 1 << 31
    CTRL_ENABLE = 1 << 30
    CTRL_PAUSE_DBG1 = 1 << 26
    CTRL_PAUSE_DBG0 = 1 << 25
    CTRL_PAUSE_JTAG = 1 << 24
    CTRL_TIME_MASK = 0x00FFFFFF

    # TICK bits
    TICK_RUNNING = 1 << 10
    TICK_ENABLE = 1 << 9
    TICK_CYCLES_MASK = 0x1FF

    def __init__(self, base: int = 0x400D8000):
        super().__init__("RP2350_WATCHDOG", base, 0x100)

        # Default control value
        self.regs[self.CTRL] = 0x07000000  # TIME=max, not enabled
        self.regs[self.REASON] = 0x00000000

        # Optional callback for system reset
        self.on_system_reset: Optional[Callable[[str], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.TICK:
            tick = self.regs.get(self.TICK, 0)
            # If enabled, also report running
            if tick & self.TICK_ENABLE:
                tick |= self.TICK_RUNNING
            return tick
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self.regs[self.CTRL] = value
            if value & self.CTRL_TRIGGER:
                self.log.warning("WATCHDOG TRIGGERED - System reset!")
                if self.on_system_reset:
                    self.on_system_reset("WATCHDOG_TRIGGER")
        elif offset == self.TICK:
            self.regs[self.TICK] = value
            if value & self.TICK_ENABLE:
                cycles = value & self.TICK_CYCLES_MASK
                self.log.debug(f"TICK enabled, cycles={cycles}")
        else:
            self.regs[offset] = value


# =============================================================================
# RP2350_USB - 0x50110000
# =============================================================================

class RP2350USB(RP2040Peripheral):
    """
    RP2350 USB Controller.

    Same as RP2040 USB controller.

    Register Map:
        0x00-0x3C: Device address, endpoint config
        0x40: MAIN_CTRL
        0x44: SOF_WR/RD
        0x48: SIE_CTRL
        0x4C: SIE_STATUS
        0x50-...: Interrupt, buffer control
    """

    ADDR_ENDP = 0x00
    MAIN_CTRL = 0x40
    SOF_WR = 0x44
    SOF_RD = 0x48
    SIE_CTRL = 0x4C
    SIE_STATUS = 0x50
    INT_EP_CTRL = 0x54
    BUFF_STATUS = 0x58
    BUFF_CPU_SHOULD_HANDLE = 0x5C

    # MAIN_CTRL bits
    MAIN_CTRL_SIM_TIMING = 1 << 31
    MAIN_CTRL_HOST_NDEVICE = 1 << 1
    MAIN_CTRL_CONTROLLER_EN = 1 << 0

    # SIE_STATUS bits
    SIE_STATUS_SPEED = 0x3 << 8
    SIE_STATUS_CONNECTED = 1 << 16

    def __init__(self, base: int = 0x50110000):
        super().__init__("RP2350_USB", base, 0x200)

        self.regs[self.SIE_STATUS] = 0x00000300  # Full-speed

    def _write_reg(self, offset: int, size: int, value: int):
        self.regs[offset] = value

        if offset == self.MAIN_CTRL:
            if value & self.MAIN_CTRL_CONTROLLER_EN:
                self.log.debug("USB controller enabled")

        elif offset == self.SIE_CTRL:
            # Simulate connection when pull-up enabled
            if value & (1 << 16):  # PULLUP_EN
                self.regs[self.SIE_STATUS] |= self.SIE_STATUS_CONNECTED


# =============================================================================
# RP2350 BOOTRAM - 0x400E0000
# =============================================================================

class RP2350BOOTRAM(RP2040Peripheral):
    """
    RP2350 Boot RAM - Secure boot scratch memory.

    256 bytes of RAM used during secure boot process.
    """

    def __init__(self, base: int = 0x400E0000):
        super().__init__("RP2350_BOOTRAM", base, 0x100)

        self.ram = bytearray(256)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset < len(self.ram):
            return int.from_bytes(self.ram[offset:offset + size], 'little')
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset < len(self.ram):
            self.ram[offset:offset + size] = value.to_bytes(size, 'little')
