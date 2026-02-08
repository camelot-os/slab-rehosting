"""
Cortex-M Memory Protection Unit (MPU) Model

Implements both ARMv7-M and ARMv8-M MPU variants:
- ARMv7-M: 8 regions, subregion disable, TEX/SCB attributes
- ARMv8-M: 8-16 regions, limit-based, MAIR attributes

Also provides memory aliasing support (STM32 SYSCFG.MEMRMP).

Registers (at 0xE000ED90):
- MPU_TYPE  (0xE000ED90): Type register (read-only)
- MPU_CTRL  (0xE000ED94): Control register
- MPU_RNR   (0xE000ED98): Region Number Register
- MPU_RBAR  (0xE000ED9C): Region Base Address Register
- MPU_RASR  (0xE000EDA0): Region Attribute and Size Register (v7-M)
- MPU_RLAR  (0xE000EDA0): Region Limit Address Register (v8-M)
- MPU_RBAR_A1-A3 (0xE000EDA4-0xE000EDBC): Alias registers

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict, Tuple
from enum import IntEnum

from .bus_logger import log_unhandled as _log_unhandled


# =============================================================================
# MEMORY PROTECTION CONTROLLER (Abstract Base)
# =============================================================================

@dataclass
class ProtectionFault:
    """Describes a memory protection violation."""
    address: int
    size: int
    is_write: bool
    is_privileged: bool
    is_instruction: bool
    fault_type: str = ""  # "MPU", "MMU", "DART", "SAU"
    details: str = ""


class MemoryProtectionController(ABC):
    """
    Abstract base for memory protection enforcement.

    Subclasses:
    - CortexMPU: ARMv7-M/v8-M MPU (flat regions, privilege-based)
    - CortexAMMU: ARMv7-A/v8-A MMU (page tables, virtual→physical)
    - AppleDART: Apple Device Address Resolution Table (DMA isolation)

    The bridge calls check_access() before dispatching to peripherals.
    Override mode: when enabled, the Python-side controller overrides
    any QEMU-side protection, allowing policy injection from Python.
    """

    def __init__(self):
        self.override_enabled: bool = False  # Override mode
        self.log_violations: bool = True
        self.fault_callback: Optional[Callable[[ProtectionFault], None]] = None
        self._violation_count: int = 0
        self._violation_log: List[ProtectionFault] = []

    @abstractmethod
    def check_access(self, address: int, size: int = 4,
                     is_write: bool = False, is_privileged: bool = True,
                     is_instruction: bool = False,
                     ns: bool = False, core_id: int = 0) -> bool:
        """
        Check if a memory access is permitted.

        Args:
            address: Target address
            size: Access size in bytes
            is_write: Write access
            is_privileged: Privileged mode
            is_instruction: Instruction fetch
            ns: Non-Secure access (TrustZone)
            core_id: Originating CPU core

        Returns:
            True if access is permitted.
        """
        ...

    @abstractmethod
    def translate_address(self, address: int, is_write: bool = False,
                          is_privileged: bool = True,
                          ns: bool = False) -> Tuple[int, bool]:
        """
        Translate virtual/device address to physical address.

        Returns:
            Tuple of (physical_address, valid).
            If translation fails, returns (0, False).
        """
        ...

    @abstractmethod
    def reset(self):
        """Reset protection controller to power-on state."""
        ...

    def enable_override(self):
        """Enable override mode - Python enforces protection policy."""
        self.override_enabled = True

    def disable_override(self):
        """Disable override mode - defer to QEMU-side protection."""
        self.override_enabled = False

    def record_violation(self, fault: ProtectionFault):
        """Record a protection violation."""
        self._violation_count += 1
        self._violation_log.append(fault)
        if len(self._violation_log) > 100:
            self._violation_log = self._violation_log[-50:]

        if self.log_violations:
            _log_unhandled(
                f"PROT-{fault.fault_type}",
                "WRITE" if fault.is_write else "READ",
                fault.address, size=fault.size
            )

        if self.fault_callback:
            self.fault_callback(fault)

    def get_violation_stats(self) -> Dict:
        """Get violation statistics."""
        return {
            'total_violations': self._violation_count,
            'recent': [
                {'addr': f"0x{f.address:08X}", 'type': f.fault_type,
                 'write': f.is_write, 'details': f.details}
                for f in self._violation_log[-10:]
            ],
        }


# =============================================================================
# MPU CONSTANTS
# =============================================================================

class MPUReg(IntEnum):
    """MPU register offsets from 0xE000ED90."""
    TYPE = 0x00   # MPU_TYPE
    CTRL = 0x04   # MPU_CTRL
    RNR = 0x08    # MPU_RNR
    RBAR = 0x0C   # MPU_RBAR
    RASR = 0x10   # MPU_RASR (v7-M) / MPU_RLAR (v8-M)
    # Alias registers for bulk programming
    RBAR_A1 = 0x14
    RASR_A1 = 0x18
    RBAR_A2 = 0x1C
    RASR_A2 = 0x20
    RBAR_A3 = 0x24
    RASR_A3 = 0x28


class MPUCtrlBits(IntEnum):
    """MPU_CTRL register bits."""
    ENABLE = 0       # MPU enable
    HFNMIENA = 1     # MPU enabled during HardFault/NMI
    PRIVDEFENA = 2   # Enable default memory map for privileged access


class AccessPermission(IntEnum):
    """ARMv7-M MPU access permissions (AP field)."""
    NO_ACCESS = 0b000      # All accesses fault
    PRIV_RW = 0b001        # Privileged RW, Unprivileged No Access
    PRIV_RW_UNPRIV_RO = 0b010  # Privileged RW, Unprivileged RO
    FULL_RW = 0b011        # Full access
    RESERVED = 0b100       # Reserved
    PRIV_RO = 0b101        # Privileged RO, Unprivileged No Access
    RO = 0b110             # Read-only for all
    RO_RO = 0b111          # Read-only for all (alias)


class MemFaultType(IntEnum):
    """Memory fault types."""
    IACCVIOL = 0   # Instruction access violation
    DACCVIOL = 1   # Data access violation
    MUNSTKERR = 3  # MemManage fault on unstacking
    MSTKERR = 4    # MemManage fault on stacking
    MLSPERR = 5    # MemManage fault during FP lazy state


# =============================================================================
# MPU REGION
# =============================================================================

@dataclass
class MPURegion:
    """
    MPU region configuration.

    ARMv7-M style: base + size (power-of-2, minimum 32 bytes)
    ARMv8-M style: base + limit (32-byte aligned)
    """
    index: int = 0
    enabled: bool = False

    # ARMv7-M: base address (aligned to size)
    base: int = 0

    # ARMv7-M: region size as power-of-2 encoding (4 = 32 bytes, 31 = 4GB)
    size_exp: int = 0  # actual size = 2^(size_exp + 1)

    # ARMv8-M: limit address (inclusive)
    limit: int = 0

    # Access permissions
    ap: int = AccessPermission.NO_ACCESS
    xn: bool = False  # Execute Never

    # Memory attributes
    tex: int = 0       # Type Extension
    shareable: bool = False
    cacheable: bool = False
    bufferable: bool = False

    # Subregion disable (ARMv7-M only, 8 subregions)
    srd: int = 0  # Bit mask: 1 = subregion disabled

    @property
    def size(self) -> int:
        """Get region size in bytes."""
        if self.size_exp < 4:
            return 0  # Minimum is 32 bytes (exp=4)
        return 1 << (self.size_exp + 1)

    @property
    def end(self) -> int:
        """Get region end address (exclusive)."""
        return self.base + self.size

    def contains(self, address: int) -> bool:
        """Check if address is in this region (considering subregions)."""
        if not self.enabled:
            return False

        if address < self.base or address >= self.end:
            return False

        # Check subregion disable
        if self.srd and self.size >= 256:  # SRD only for regions >= 256 bytes
            subregion_size = self.size // 8
            subregion_idx = (address - self.base) // subregion_size
            if self.srd & (1 << subregion_idx):
                return False

        return True

    def check_permission(self, is_write: bool, is_privileged: bool,
                         is_instruction: bool) -> bool:
        """
        Check if access is permitted.

        Returns True if access is allowed, False if it should fault.
        """
        # Execute Never check
        if is_instruction and self.xn:
            return False

        # AP field permission check
        if self.ap == AccessPermission.NO_ACCESS:
            return False
        elif self.ap == AccessPermission.PRIV_RW:
            return is_privileged
        elif self.ap == AccessPermission.PRIV_RW_UNPRIV_RO:
            if is_write:
                return is_privileged
            return True
        elif self.ap == AccessPermission.FULL_RW:
            return True
        elif self.ap == AccessPermission.PRIV_RO:
            if is_write:
                return False
            return is_privileged
        elif self.ap in (AccessPermission.RO, AccessPermission.RO_RO):
            return not is_write

        return False

    def to_rasr(self) -> int:
        """Encode as ARMv7-M RASR register value."""
        rasr = 0
        if self.enabled:
            rasr |= 1  # ENABLE
        rasr |= (self.size_exp & 0x1F) << 1  # SIZE
        rasr |= (self.srd & 0xFF) << 8       # SRD
        rasr |= (1 if self.bufferable else 0) << 16  # B
        rasr |= (1 if self.cacheable else 0) << 17   # C
        rasr |= (1 if self.shareable else 0) << 18   # S
        rasr |= (self.tex & 0x07) << 19      # TEX
        rasr |= (self.ap & 0x07) << 24       # AP
        rasr |= (1 if self.xn else 0) << 28  # XN
        return rasr

    @classmethod
    def from_rasr(cls, index: int, base: int, rasr: int) -> 'MPURegion':
        """Decode from ARMv7-M RBAR + RASR register values."""
        return cls(
            index=index,
            enabled=bool(rasr & 1),
            base=base & 0xFFFFFFE0,  # 32-byte aligned
            size_exp=(rasr >> 1) & 0x1F,
            srd=(rasr >> 8) & 0xFF,
            bufferable=bool((rasr >> 16) & 1),
            cacheable=bool((rasr >> 17) & 1),
            shareable=bool((rasr >> 18) & 1),
            tex=(rasr >> 19) & 0x07,
            ap=(rasr >> 24) & 0x07,
            xn=bool((rasr >> 28) & 1),
        )


# =============================================================================
# MEMORY ALIAS MODEL
# =============================================================================

@dataclass
class MemoryAlias:
    """
    A memory alias/remap entry.

    Maps accesses from [alias_base, alias_base+size) to
    [target_base, target_base+size).
    """
    alias_base: int
    target_base: int
    size: int
    name: str = ""

    def translate(self, address: int) -> Optional[int]:
        """Translate aliased address to target. Returns None if not in range."""
        if self.alias_base <= address < self.alias_base + self.size:
            offset = address - self.alias_base
            return self.target_base + offset
        return None


class MemoryAliasController:
    """
    Manages memory aliases for STM32-style boot remapping.

    STM32 SYSCFG.MEMRMP modes:
    - 0b00: Flash at 0x00000000
    - 0b01: System memory at 0x00000000
    - 0b11: SRAM at 0x00000000
    """

    def __init__(self):
        self._aliases: List[MemoryAlias] = []
        self._remap_mode: int = 0  # SYSCFG.MEMRMP MEM_MODE bits

    def add_alias(self, alias: MemoryAlias):
        """Add a memory alias."""
        self._aliases.append(alias)

    def clear_aliases(self):
        """Remove all aliases."""
        self._aliases.clear()

    def set_remap_mode(self, mode: int):
        """
        Set STM32 memory remap mode (SYSCFG.MEMRMP MEM_MODE).

        This reconfigures what is mapped at 0x00000000.
        """
        self._remap_mode = mode & 0x07
        self._update_boot_alias()

    def _update_boot_alias(self):
        """Update the boot alias based on remap mode."""
        # Remove existing boot alias
        self._aliases = [a for a in self._aliases if a.name != "boot_remap"]

        # STM32F4 remap modes
        if self._remap_mode == 0b00:
            # Flash mapped at 0x00000000
            self._aliases.append(MemoryAlias(
                alias_base=0x00000000, target_base=0x08000000,
                size=0x00100000, name="boot_remap"
            ))
        elif self._remap_mode == 0b01:
            # System memory (bootrom) at 0x00000000
            self._aliases.append(MemoryAlias(
                alias_base=0x00000000, target_base=0x1FFF0000,
                size=0x00010000, name="boot_remap"
            ))
        elif self._remap_mode == 0b11:
            # SRAM at 0x00000000
            self._aliases.append(MemoryAlias(
                alias_base=0x00000000, target_base=0x20000000,
                size=0x00020000, name="boot_remap"
            ))

    def translate(self, address: int) -> int:
        """
        Translate address through aliases.

        Returns the physical address after alias resolution.
        If no alias matches, returns the original address.
        """
        for alias in self._aliases:
            target = alias.translate(address)
            if target is not None:
                return target
        return address

    @property
    def remap_mode(self) -> int:
        return self._remap_mode


# =============================================================================
# MPU CONTROLLER
# =============================================================================

class CortexMPU(MemoryProtectionController):
    """
    Cortex-M Memory Protection Unit.

    Implements the ARMv7-M MPU with:
    - 8 configurable regions (higher index = higher priority)
    - Subregion disable
    - Background region (default memory map) for privileged access
    - MemManage fault generation on violations
    - Memory aliasing support
    - Override mode for Python-side enforcement

    Usage:
        mpu = CortexMPU(num_regions=8)

        # Configure a region
        mpu.write_register(MPUReg.RNR, 0)           # Select region 0
        mpu.write_register(MPUReg.RBAR, 0x20000000) # Base = SRAM
        mpu.write_register(MPUReg.RASR, 0x0300001F) # Full RW, 4GB

        # Enable MPU + override mode
        mpu.write_register(MPUReg.CTRL, 0x05)  # ENABLE + PRIVDEFENA
        mpu.enable_override()  # Enforce on peripheral bridge

        # Check access
        allowed = mpu.check_access(0x20001000, is_write=True, is_privileged=True)
    """

    MPU_BASE = 0xE000ED90

    def __init__(self, num_regions: int = 8, arch_v8m: bool = False):
        """
        Initialize MPU.

        Args:
            num_regions: Number of MPU regions (4, 8, or 16)
            arch_v8m: Use ARMv8-M style (limit-based) instead of v7-M
        """
        super().__init__()
        self.num_regions = num_regions
        self.arch_v8m = arch_v8m

        # Regions (higher index = higher priority)
        self.regions: List[MPURegion] = [
            MPURegion(index=i) for i in range(num_regions)
        ]

        # Control register state
        self.enabled = False
        self.hfnmiena = False
        self.privdefena = False  # Background region for privileged

        # Currently selected region
        self._rnr = 0

        # Memory aliases
        self.aliases = MemoryAliasController()

        # Statistics
        self.access_checks = 0
        self.faults_generated = 0
        self._fault_log: List[Dict] = []

    def reset(self):
        """Reset MPU to power-on state."""
        self.enabled = False
        self.hfnmiena = False
        self.privdefena = False
        self._rnr = 0
        for r in self.regions:
            r.enabled = False
            r.base = 0
            r.size_exp = 0
            r.ap = AccessPermission.NO_ACCESS
            r.xn = False
            r.srd = 0
        self._fault_log.clear()
        self.access_checks = 0
        self.faults_generated = 0
        self._violation_count = 0
        self._violation_log.clear()

    def translate_address(self, address: int, is_write: bool = False,
                          is_privileged: bool = True,
                          ns: bool = False) -> Tuple[int, bool]:
        """MPU is flat-mapped; translate only through aliases."""
        phys = self.aliases.translate(address)
        return (phys, True)

    # =========================================================================
    # Register Access
    # =========================================================================

    def read_register(self, offset: int) -> int:
        """Read MPU register (offset from MPU_BASE)."""
        if offset == MPUReg.TYPE:
            # MPU_TYPE: DREGION = num_regions, IREGION = 0, SEPARATE = 0
            return (self.num_regions << 8)

        elif offset == MPUReg.CTRL:
            val = 0
            if self.enabled:
                val |= (1 << MPUCtrlBits.ENABLE)
            if self.hfnmiena:
                val |= (1 << MPUCtrlBits.HFNMIENA)
            if self.privdefena:
                val |= (1 << MPUCtrlBits.PRIVDEFENA)
            return val

        elif offset == MPUReg.RNR:
            return self._rnr

        elif offset == MPUReg.RBAR:
            if self._rnr < self.num_regions:
                r = self.regions[self._rnr]
                return r.base | (1 << 4) | (self._rnr & 0x0F)  # VALID + REGION
            return 0

        elif offset == MPUReg.RASR:
            if self._rnr < self.num_regions:
                return self.regions[self._rnr].to_rasr()
            return 0

        # Alias registers
        elif offset in (MPUReg.RBAR_A1, MPUReg.RBAR_A2, MPUReg.RBAR_A3):
            alias_idx = (offset - MPUReg.RBAR_A1) // 8 + 1
            region_idx = (self._rnr + alias_idx) % self.num_regions
            r = self.regions[region_idx]
            return r.base | (1 << 4) | (region_idx & 0x0F)

        elif offset in (MPUReg.RASR_A1, MPUReg.RASR_A2, MPUReg.RASR_A3):
            alias_idx = (offset - MPUReg.RASR_A1) // 8 + 1
            region_idx = (self._rnr + alias_idx) % self.num_regions
            return self.regions[region_idx].to_rasr()

        return 0

    def write_register(self, offset: int, value: int):
        """Write MPU register (offset from MPU_BASE)."""
        if offset == MPUReg.CTRL:
            self.enabled = bool(value & (1 << MPUCtrlBits.ENABLE))
            self.hfnmiena = bool(value & (1 << MPUCtrlBits.HFNMIENA))
            self.privdefena = bool(value & (1 << MPUCtrlBits.PRIVDEFENA))

        elif offset == MPUReg.RNR:
            self._rnr = value & 0xFF
            if self._rnr >= self.num_regions:
                self._rnr = 0

        elif offset == MPUReg.RBAR:
            # RBAR write: if VALID bit set, update REGION field too
            if value & (1 << 4):  # VALID bit
                self._rnr = value & 0x0F
            if self._rnr < self.num_regions:
                self.regions[self._rnr].base = value & 0xFFFFFFE0

        elif offset == MPUReg.RASR:
            if self._rnr < self.num_regions:
                r = self.regions[self._rnr]
                r.enabled = bool(value & 1)
                r.size_exp = (value >> 1) & 0x1F
                r.srd = (value >> 8) & 0xFF
                r.bufferable = bool((value >> 16) & 1)
                r.cacheable = bool((value >> 17) & 1)
                r.shareable = bool((value >> 18) & 1)
                r.tex = (value >> 19) & 0x07
                r.ap = (value >> 24) & 0x07
                r.xn = bool((value >> 28) & 1)

        # Alias registers for bulk programming
        elif offset in (MPUReg.RBAR_A1, MPUReg.RBAR_A2, MPUReg.RBAR_A3):
            alias_idx = (offset - MPUReg.RBAR_A1) // 8 + 1
            if value & (1 << 4):  # VALID
                region_idx = value & 0x0F
            else:
                region_idx = (self._rnr + alias_idx) % self.num_regions
            if region_idx < self.num_regions:
                self.regions[region_idx].base = value & 0xFFFFFFE0

        elif offset in (MPUReg.RASR_A1, MPUReg.RASR_A2, MPUReg.RASR_A3):
            alias_idx = (offset - MPUReg.RASR_A1) // 8 + 1
            region_idx = (self._rnr + alias_idx) % self.num_regions
            if region_idx < self.num_regions:
                r = self.regions[region_idx]
                r.enabled = bool(value & 1)
                r.size_exp = (value >> 1) & 0x1F
                r.srd = (value >> 8) & 0xFF
                r.bufferable = bool((value >> 16) & 1)
                r.cacheable = bool((value >> 17) & 1)
                r.shareable = bool((value >> 18) & 1)
                r.tex = (value >> 19) & 0x07
                r.ap = (value >> 24) & 0x07
                r.xn = bool((value >> 28) & 1)

    # =========================================================================
    # Access Checking
    # =========================================================================

    def check_access(self, address: int, size: int = 4,
                     is_write: bool = False, is_privileged: bool = True,
                     is_instruction: bool = False,
                     ns: bool = False, core_id: int = 0) -> bool:
        """
        Check if a memory access is permitted by the MPU.

        Args:
            address: Access address
            size: Access size in bytes
            is_write: True for write, False for read
            is_privileged: True for privileged mode
            is_instruction: True for instruction fetch
            ns: Non-Secure access (unused for basic MPU)
            core_id: Originating core (unused for basic MPU)

        Returns:
            True if access is permitted, False if it should fault.
        """
        self.access_checks += 1

        if not self.enabled:
            return True  # MPU disabled, all accesses allowed

        # Resolve aliases first
        phys_address = self.aliases.translate(address)

        # Find matching region (highest index wins)
        matched_region = None
        for region in reversed(self.regions):
            if region.contains(phys_address):
                matched_region = region
                break

        if matched_region is None:
            # No region matched
            if self.privdefena and is_privileged:
                # Background region allows privileged access to default map
                return True
            # Fault: no matching region
            self._generate_fault(address, size, is_write, is_privileged, is_instruction)
            return False

        # Check permissions on matched region
        if not matched_region.check_permission(is_write, is_privileged, is_instruction):
            self._generate_fault(address, size, is_write, is_privileged, is_instruction)
            return False

        return True

    def _generate_fault(self, address: int, size: int,
                        is_write: bool, is_privileged: bool,
                        is_instruction: bool):
        """Generate a MemManage fault."""
        self.faults_generated += 1
        fault_type = MemFaultType.IACCVIOL if is_instruction else MemFaultType.DACCVIOL

        self._fault_log.append({
            'address': address,
            'type': fault_type.name,
            'count': self.faults_generated,
        })

        # Record via base class
        self.record_violation(ProtectionFault(
            address=address, size=size, is_write=is_write,
            is_privileged=is_privileged, is_instruction=is_instruction,
            fault_type="MPU", details=fault_type.name,
        ))

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def configure_region(self, index: int, base: int, size_exp: int,
                         ap: int = AccessPermission.FULL_RW,
                         xn: bool = False, enabled: bool = True):
        """
        Configure an MPU region directly.

        Args:
            index: Region index (0 to num_regions-1)
            base: Base address (must be aligned to region size)
            size_exp: Size exponent (4=32B, 5=64B, ..., 31=4GB)
            ap: Access permission
            xn: Execute Never
            enabled: Region enabled
        """
        if index >= self.num_regions:
            return
        r = self.regions[index]
        r.base = base & 0xFFFFFFE0
        r.size_exp = size_exp
        r.ap = ap
        r.xn = xn
        r.enabled = enabled

    def get_region_for_address(self, address: int) -> Optional[MPURegion]:
        """Find the highest-priority region containing address."""
        for region in reversed(self.regions):
            if region.contains(address):
                return region
        return None

    def get_stats(self) -> dict:
        """Get MPU statistics."""
        active_regions = sum(1 for r in self.regions if r.enabled)
        return {
            'enabled': self.enabled,
            'privdefena': self.privdefena,
            'num_regions': self.num_regions,
            'active_regions': active_regions,
            'access_checks': self.access_checks,
            'faults_generated': self.faults_generated,
            'recent_faults': self._fault_log[-10:],
        }

    def dump_regions(self) -> List[Dict]:
        """Dump all configured regions for debugging."""
        result = []
        for r in self.regions:
            if r.enabled:
                result.append({
                    'index': r.index,
                    'base': f"0x{r.base:08X}",
                    'size': f"0x{r.size:X}" if r.size else "0",
                    'end': f"0x{r.end:08X}" if r.size else "N/A",
                    'ap': AccessPermission(r.ap).name,
                    'xn': r.xn,
                    'srd': f"0b{r.srd:08b}" if r.srd else "none",
                    'cacheable': r.cacheable,
                    'bufferable': r.bufferable,
                    'shareable': r.shareable,
                })
        return result
