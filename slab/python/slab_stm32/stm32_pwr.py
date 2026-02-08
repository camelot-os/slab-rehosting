"""
STM32 PWR (Power Control) Peripheral Emulation

Implements:
- PWRv1: F1xx/F4xx
- PWRv2: L4xx/H7xx/U5xx

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32PWRv1(STM32Peripheral):
    """
    STM32F1xx/F4xx Power Control.

    Register Map:
        0x00: CR   - Power control
        0x04: CSR  - Power control/status
    """

    CR = 0x00
    CSR = 0x04

    # CR bits
    CR_LPDS = 1 << 0      # Low-power deepsleep
    CR_PDDS = 1 << 1      # Power down deepsleep
    CR_CWUF = 1 << 2      # Clear wakeup flag
    CR_CSBF = 1 << 3      # Clear standby flag
    CR_PVDE = 1 << 4      # PVD enable
    CR_PLS = 0x7 << 5     # PVD level selection
    CR_DBP = 1 << 8       # Disable backup domain write protection

    # F4-specific CR bits
    CR_FPDS = 1 << 9      # Flash power down in Stop
    CR_LPUDS = 1 << 10    # Low-power regulator in Stop under-drive
    CR_MRUDS = 1 << 11    # Main regulator in Stop under-drive
    CR_ADCDC1 = 1 << 13   # ADC DC1
    CR_VOS = 0x3 << 14    # Regulator voltage scaling
    CR_ODEN = 1 << 16     # Overdrive enable
    CR_ODSWEN = 1 << 17   # Overdrive switching enable

    # CSR bits
    CSR_WUF = 1 << 0      # Wakeup flag
    CSR_SBF = 1 << 1      # Standby flag
    CSR_PVDO = 1 << 2     # PVD output
    CSR_BRR = 1 << 3      # Backup regulator ready
    CSR_EWUP = 1 << 8     # Enable wakeup pin

    # F4-specific CSR bits
    CSR_BRE = 1 << 9      # Backup regulator enable
    CSR_VOSRDY = 1 << 14  # VOS ready
    CSR_ODRDY = 1 << 16   # Overdrive ready
    CSR_ODSWRDY = 1 << 17 # Overdrive switching ready

    def __init__(self, base: int = 0x40007000, family: str = "F4"):
        super().__init__("PWR", base, 0x400)
        self.family = family

        self.cr = 0
        self.csr = 0

        if family == "F4":
            self.cr |= (0x3 << 14)  # VOS default scale 1
            self.csr |= self.CSR_VOSRDY

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.CSR:
            return self._get_csr()
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            self._write_cr(value)
        elif offset == self.CSR:
            self._write_csr(value)

    def _write_cr(self, value: int):
        # Clear flags
        if value & self.CR_CWUF:
            self.csr &= ~self.CSR_WUF
        if value & self.CR_CSBF:
            self.csr &= ~self.CSR_SBF

        self.cr = value & ~(self.CR_CWUF | self.CR_CSBF)

        # Overdrive handling (F4)
        if self.family == "F4":
            if value & self.CR_ODEN:
                self.csr |= self.CSR_ODRDY
            if value & self.CR_ODSWEN:
                self.csr |= self.CSR_ODSWRDY

    def _write_csr(self, value: int):
        # Only some bits writable
        writable = self.CSR_EWUP
        if self.family == "F4":
            writable |= self.CSR_BRE

        self.csr = (self.csr & ~writable) | (value & writable)

        # Backup regulator ready follows enable
        if self.family == "F4" and (value & self.CSR_BRE):
            self.csr |= self.CSR_BRR

    def _get_csr(self) -> int:
        csr = self.csr
        # VOS always ready in emulation
        if self.family == "F4":
            csr |= self.CSR_VOSRDY
        return csr


class STM32PWRv2(STM32Peripheral):
    """
    STM32L4xx/H7xx/U5xx Power Control.

    New features:
    - Multiple voltage ranges
    - SMPS (H7)
    - Low-power run mode
    """

    CR1 = 0x00
    CR2 = 0x04
    CR3 = 0x08
    CR4 = 0x0C
    SR1 = 0x10
    SR2 = 0x14
    SCR = 0x18
    PUCRA = 0x20
    PDCRA = 0x24

    # CR1 bits
    CR1_LPMS = 0x7 << 0   # Low-power mode selection
    CR1_DBP = 1 << 8      # Disable backup domain write protection
    CR1_VOS = 0x3 << 9    # Voltage scaling
    CR1_LPR = 1 << 14     # Low-power run

    # CR2 bits (L4)
    CR2_PVDE = 1 << 0
    CR2_PLS = 0x7 << 1
    CR2_PVME1 = 1 << 4
    CR2_PVME2 = 1 << 5
    CR2_PVME3 = 1 << 6
    CR2_PVME4 = 1 << 7

    # SR1 bits
    SR1_WUF1 = 1 << 0
    SR1_WUF2 = 1 << 1
    SR1_WUF3 = 1 << 2
    SR1_WUF4 = 1 << 3
    SR1_WUF5 = 1 << 4
    SR1_SBF = 1 << 8
    SR1_WUFI = 1 << 15

    # SR2 bits
    SR2_REGLPS = 1 << 8   # Low-power regulator started
    SR2_REGLPF = 1 << 9   # Low-power regulator flag
    SR2_VOSF = 1 << 10    # Voltage scaling flag
    SR2_PVDO = 1 << 11    # PVD output

    # H5-specific register offsets
    H5_PMCR = 0x00    # Power mode control
    H5_PMSR = 0x04    # Power mode status
    H5_VOSCR = 0x10   # Voltage scaling control
    H5_VOSSR = 0x14   # Voltage scaling status
    H5_BDCR = 0x20    # Backup domain control
    H5_DBPCR = 0x24   # Disable backup protection control
    H5_BDSR = 0x28    # Backup domain status
    H5_SCCR = 0x30    # Supply configuration control
    H5_VMCR = 0x34    # Voltage monitor control
    H5_VMSR = 0x3C    # Voltage monitor status

    # H5 VOSSR bits
    H5_VOSSR_VOSRDY = 1 << 3      # VOS ready
    H5_VOSSR_ACTVOSRDY = 1 << 13  # Active VOS ready
    H5_VOSSR_ACTVOS = 0x3 << 14   # Active VOS level

    def __init__(self, base: int = 0x40007000, family: str = "L4"):
        super().__init__("PWR", base, 0x400)
        self.family = family

        if family == "H5":
            # H5-specific registers
            self.pmcr = 0x0000000C   # Default from SVD
            self.pmsr = 0x00000000
            self.voscr = 0x00000000
            # VOSSR reset value from SVD: VOSRDY=1 (bit 3)
            # Add ACTVOSRDY (bit 13) and default VOS level
            self.vossr = 0x00000008  # VOSRDY=1 (matches SVD reset value)
            self.bdcr = 0
            self.dbpcr = 0
            self.bdsr = 0
            self.sccr = 0
            self.vmcr = 0
            self.vmsr = 0
        else:
            # L4/H7 registers
            self.cr1 = 0x0200  # VOS = Range 1
            self.cr2 = 0
            self.cr3 = 0
            self.cr4 = 0
            self.sr1 = 0
            self.sr2 = 0

        # Pull-up/down control
        self.pucr = [0] * 8  # A-H
        self.pdcr = [0] * 8

    def _read_reg(self, offset: int, size: int) -> int:
        if self.family == "H5":
            return self._read_reg_h5(offset, size)

        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.CR3:
            return self.cr3
        elif offset == self.CR4:
            return self.cr4
        elif offset == self.SR1:
            return self.sr1
        elif offset == self.SR2:
            return self._get_sr2()
        elif offset == self.SCR:
            return 0  # Write-only
        elif offset >= self.PUCRA:
            return self._read_pucr_pdcr(offset)
        return 0

    def _read_reg_h5(self, offset: int, size: int) -> int:
        """Read H5-specific PWR registers."""
        self.log.debug(f"PWR H5 read offset 0x{offset:02X}")
        if offset == self.H5_PMCR:
            return self.pmcr
        elif offset == self.H5_PMSR:
            return self.pmsr
        elif offset == self.H5_VOSCR:
            return self.voscr
        elif offset == self.H5_VOSSR:
            return self.vossr
        elif offset == self.H5_BDCR:
            return self.bdcr
        elif offset == self.H5_DBPCR:
            return self.dbpcr
        elif offset == self.H5_BDSR:
            return self.bdsr
        elif offset == self.H5_SCCR:
            return self.sccr
        elif offset == self.H5_VMCR:
            return self.vmcr
        elif offset == self.H5_VMSR:
            return self.vmsr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if self.family == "H5":
            return self._write_reg_h5(offset, size, value)

        if offset == self.CR1:
            self.cr1 = value
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.CR3:
            self.cr3 = value
        elif offset == self.CR4:
            self.cr4 = value
        elif offset == self.SCR:
            # Status clear register
            self.sr1 &= ~(value & 0x1F)  # Clear WUFx
            if value & (1 << 8):
                self.sr1 &= ~self.SR1_SBF
        elif offset >= self.PUCRA:
            self._write_pucr_pdcr(offset, value)

    def _write_reg_h5(self, offset: int, size: int, value: int):
        """Write H5-specific PWR registers."""
        if offset == self.H5_PMCR:
            self.pmcr = value
        elif offset == self.H5_VOSCR:
            # Auto-set ready bit in VOSCR (bit 3 = VOSRDY like in VOSSR)
            # Some HAL versions check VOSCR for the ready bit
            self.voscr = value | (1 << 3)  # Set bit 3 (same as VOSRDY position)
            # Auto-set VOSSR ready bits when VOSCR is written
            vos = (value >> 4) & 0x3
            self.vossr = self.H5_VOSSR_VOSRDY | self.H5_VOSSR_ACTVOSRDY | (vos << 14)
        elif offset == self.H5_BDCR:
            self.bdcr = value
        elif offset == self.H5_DBPCR:
            self.dbpcr = value
        elif offset == self.H5_SCCR:
            self.sccr = value
        elif offset == self.H5_VMCR:
            self.vmcr = value

    def _get_sr2(self) -> int:
        sr2 = self.sr2
        # VOSF cleared when VOS transition complete
        sr2 &= ~self.SR2_VOSF
        return sr2

    def _read_pucr_pdcr(self, offset: int) -> int:
        idx = (offset - self.PUCRA) // 8
        is_pdcr = ((offset - self.PUCRA) % 8) >= 4
        if idx < 8:
            return self.pdcr[idx] if is_pdcr else self.pucr[idx]
        return 0

    def _write_pucr_pdcr(self, offset: int, value: int):
        idx = (offset - self.PUCRA) // 8
        is_pdcr = ((offset - self.PUCRA) % 8) >= 4
        if idx < 8:
            if is_pdcr:
                self.pdcr[idx] = value
            else:
                self.pucr[idx] = value


class STM32PWRv3(STM32Peripheral):
    """
    STM32H7xx Power Control with SMPS.

    Features:
    - D1/D2/D3 domain control
    - SMPS regulator
    - VOS0-VOS3 voltage scaling
    """

    CR1 = 0x00
    CSR1 = 0x04
    CR2 = 0x08
    CR3 = 0x0C
    CPUCR = 0x10
    D3CR = 0x18
    WKUPCR = 0x20
    WKUPFR = 0x24
    WKUPEPR = 0x28

    # CR1 bits
    CR1_LPDS = 1 << 0
    CR1_PVDE = 1 << 4
    CR1_PLS = 0x7 << 5
    CR1_DBP = 1 << 8
    CR1_FLPS = 1 << 9
    CR1_SVOS = 0x3 << 14
    CR1_AVDEN = 1 << 16
    CR1_ALS = 0x3 << 17

    # CSR1 bits
    CSR1_PVDO = 1 << 4
    CSR1_ACTVOSRDY = 1 << 13
    CSR1_ACTVOS = 0x3 << 14
    CSR1_AVDO = 1 << 16

    # D3CR bits
    D3CR_VOSRDY = 1 << 13
    D3CR_VOS = 0x3 << 14

    def __init__(self, base: int = 0x58024800):
        super().__init__("PWR", base, 0x400)

        self.cr1 = 0xF000C000  # SVOS, PLS defaults
        self.csr1 = 0
        self.cr2 = 0
        self.cr3 = 0x06  # USB regulator, LDO enabled
        self.cpucr = 0
        self.d3cr = 0x4000  # VOS3

        self.wkupcr = 0
        self.wkupfr = 0
        self.wkupepr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CSR1:
            return self._get_csr1()
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.CR3:
            return self.cr3
        elif offset == self.CPUCR:
            return self.cpucr
        elif offset == self.D3CR:
            return self._get_d3cr()
        elif offset == self.WKUPCR:
            return self.wkupcr
        elif offset == self.WKUPFR:
            return self.wkupfr
        elif offset == self.WKUPEPR:
            return self.wkupepr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            self.cr1 = value
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.CR3:
            self.cr3 = value
        elif offset == self.CPUCR:
            self.cpucr = value
        elif offset == self.D3CR:
            self.d3cr = value
        elif offset == self.WKUPCR:
            # Clear wakeup flags
            self.wkupfr &= ~(value & 0x3F)
        elif offset == self.WKUPEPR:
            self.wkupepr = value

    def _get_csr1(self) -> int:
        csr1 = self.csr1
        # ACTVOS reflects current VOS
        vos = (self.d3cr >> 14) & 0x3
        csr1 |= (vos << 14) | self.CSR1_ACTVOSRDY
        return csr1

    def _get_d3cr(self) -> int:
        # VOSRDY always set in emulation
        return self.d3cr | self.D3CR_VOSRDY
