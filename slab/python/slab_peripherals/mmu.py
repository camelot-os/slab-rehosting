"""
Memory Management Unit (MMU) and DART Models

Implements:
- CortexAMMU: ARMv8-A MMU with page table walking (4KB/16KB/64KB granules)
- AppleDART: Apple Device Address Resolution Table (IOMMU for DMA isolation)

Both inherit from MemoryProtectionController and can be attached to the
SHM/TCP peripheral bridges in override mode.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import Optional, Callable, List, Dict, Tuple
from enum import IntEnum

from .mpu import MemoryProtectionController, ProtectionFault


# =============================================================================
# ARMv8-A MMU
# =============================================================================

class PageSize(IntEnum):
    """Supported page granules."""
    KB_4 = 4096
    KB_16 = 16384
    KB_64 = 65536


class MemoryType(IntEnum):
    """ARM memory types (MAIR encoding simplified)."""
    DEVICE_nGnRnE = 0x00  # Device, non-Gathering, non-Reordering, non-Early
    DEVICE_nGnRE = 0x04   # Device, non-Gathering, non-Reordering, Early
    NORMAL_NC = 0x44       # Normal, Non-Cacheable
    NORMAL_WT = 0xBB       # Normal, Write-Through
    NORMAL_WB = 0xFF       # Normal, Write-Back


@dataclass
class PageTableEntry:
    """
    ARMv8-A page table entry (simplified).

    Supports 4KB granule, 4-level page tables (48-bit VA).
    """
    valid: bool = False
    is_table: bool = False   # True = table descriptor, False = block/page
    is_page: bool = False    # True = final page entry

    # Output address (physical)
    output_address: int = 0

    # Attributes
    ap: int = 0        # Access Permission: 0=EL1 RW, 1=EL1/EL0 RW, 2=EL1 RO, 3=EL1/EL0 RO
    xn: bool = False   # Execute-Never (EL1)
    uxn: bool = False  # Unprivileged Execute-Never (EL0)
    af: bool = False   # Access Flag
    sh: int = 0        # Shareability: 0=Non, 2=Outer, 3=Inner
    ns: bool = False   # Non-Secure
    mem_type: int = MemoryType.NORMAL_WB

    # For table descriptors
    next_table_addr: int = 0

    @classmethod
    def from_descriptor(cls, desc: int, level: int, granule: int = 4096) -> 'PageTableEntry':
        """Parse a raw 64-bit descriptor."""
        entry = cls()
        entry.valid = bool(desc & 1)
        if not entry.valid:
            return entry

        if level < 3:
            entry.is_table = bool(desc & 2)
            if entry.is_table:
                entry.next_table_addr = desc & 0x0000FFFFFFFFF000
            else:
                # Block descriptor
                entry.is_page = True
                entry.output_address = desc & 0x0000FFFFFFFFF000
        else:
            # Level 3: page descriptor
            entry.is_page = bool(desc & 2)
            entry.output_address = desc & 0x0000FFFFFFFFF000

        # Parse attributes (common to block/page)
        if entry.is_page or (not entry.is_table and entry.valid):
            entry.af = bool(desc & (1 << 10))
            entry.ap = (desc >> 6) & 0x3
            entry.sh = (desc >> 8) & 0x3
            entry.ns = bool(desc & (1 << 5))
            entry.xn = bool(desc & (1 << 54))
            entry.uxn = bool(desc & (1 << 53))

        return entry

    def check_permission(self, is_write: bool, is_privileged: bool,
                         is_instruction: bool) -> bool:
        """Check access permission for this page."""
        if not self.valid or not self.af:
            return False

        # XN/UXN check
        if is_instruction:
            if is_privileged and self.xn:
                return False
            if not is_privileged and self.uxn:
                return False

        # AP field:
        # 0b00: EL1 RW, EL0 No Access
        # 0b01: EL1 RW, EL0 RW
        # 0b10: EL1 RO, EL0 No Access
        # 0b11: EL1 RO, EL0 RO
        if self.ap == 0:
            if not is_privileged:
                return False
        elif self.ap == 1:
            pass  # Full access
        elif self.ap == 2:
            if not is_privileged:
                return False
            if is_write:
                return False
        elif self.ap == 3:
            if is_write:
                return False

        return True


class CortexAMMU(MemoryProtectionController):
    """
    ARMv8-A MMU with multi-level page table walking.

    Supports:
    - 4KB granule, 4-level page tables (48-bit VA, 48-bit PA)
    - EL0/EL1 permission checking (AP, XN, UXN)
    - TLB caching for performance
    - Override mode for Python-side enforcement on peripheral bridge

    Usage:
        mmu = CortexAMMU()
        mmu.set_ttbr0(page_table_base_address)
        mmu.enable_override()

        # Load page tables from memory
        mmu.load_page_table(memory_read_callback)

        # Or manually add mappings
        mmu.add_mapping(va=0x40000000, pa=0x40000000, size=0x1000,
                       ap=1, xn=False)
    """

    def __init__(self, granule: int = PageSize.KB_4, va_bits: int = 48):
        super().__init__()
        self.granule = granule
        self.va_bits = va_bits
        self.enabled = False

        # Translation Table Base Registers
        self.ttbr0: int = 0  # User space
        self.ttbr1: int = 0  # Kernel space

        # Translation Control Register
        self.tcr_t0sz: int = 16  # VA size for TTBR0 = 64 - T0SZ
        self.tcr_t1sz: int = 16  # VA size for TTBR1 = 64 - T1SZ

        # Manual page table (flat list for software-managed mode)
        self._mappings: List[Dict] = []

        # TLB cache
        self._tlb: Dict[int, PageTableEntry] = {}
        self._tlb_max = 256
        self._tlb_hits = 0
        self._tlb_misses = 0

        # Memory read callback (for page table walking)
        self._mem_read: Optional[Callable[[int, int], bytes]] = None

        # Statistics
        self.access_checks = 0
        self.faults_generated = 0

    def reset(self):
        """Reset MMU state."""
        self.enabled = False
        self.ttbr0 = 0
        self.ttbr1 = 0
        self._mappings.clear()
        self._tlb.clear()
        self._tlb_hits = 0
        self._tlb_misses = 0
        self.access_checks = 0
        self.faults_generated = 0
        self._violation_count = 0
        self._violation_log.clear()

    def set_ttbr0(self, addr: int):
        """Set TTBR0_EL1 (user space page table base)."""
        self.ttbr0 = addr & 0x0000FFFFFFFFFFFF
        self._tlb.clear()

    def set_ttbr1(self, addr: int):
        """Set TTBR1_EL1 (kernel space page table base)."""
        self.ttbr1 = addr & 0x0000FFFFFFFFFFFF
        self._tlb.clear()

    def set_memory_reader(self, callback: Callable[[int, int], bytes]):
        """Set callback to read physical memory (for page table walks)."""
        self._mem_read = callback

    def add_mapping(self, va: int, pa: int, size: int,
                    ap: int = 1, xn: bool = False, uxn: bool = False,
                    ns: bool = False, device: bool = False):
        """
        Add a manual VA→PA mapping (software-managed mode).

        Use this when you don't have actual page tables to walk.
        """
        self._mappings.append({
            'va': va,
            'pa': pa,
            'size': size,
            'ap': ap,
            'xn': xn,
            'uxn': uxn,
            'ns': ns,
            'device': device,
        })
        self._tlb.clear()

    def remove_mapping(self, va: int):
        """Remove a manual mapping."""
        self._mappings = [m for m in self._mappings if m['va'] != va]
        self._tlb.clear()

    def translate_address(self, address: int, is_write: bool = False,
                          is_privileged: bool = True,
                          ns: bool = False) -> Tuple[int, bool]:
        """Translate VA to PA."""
        if not self.enabled:
            return (address, True)  # Identity mapping when disabled

        # Check TLB
        page_va = address & ~(self.granule - 1)
        if page_va in self._tlb:
            self._tlb_hits += 1
            entry = self._tlb[page_va]
            if entry.valid:
                offset = address & (self.granule - 1)
                return (entry.output_address | offset, True)
            return (0, False)

        self._tlb_misses += 1

        # Try manual mappings first
        for m in self._mappings:
            if m['va'] <= address < m['va'] + m['size']:
                offset = address - m['va']
                pa = m['pa'] + offset

                # Cache in TLB
                entry = PageTableEntry(
                    valid=True, is_page=True,
                    output_address=m['pa'] + (offset & ~(self.granule - 1)),
                    ap=m['ap'], xn=m['xn'], uxn=m['uxn'],
                    ns=m['ns'], af=True,
                )
                self._tlb[page_va] = entry
                return (pa, True)

        # Try page table walk
        if self._mem_read and self.ttbr0:
            entry = self._walk_page_table(address)
            self._tlb[page_va] = entry
            if entry.valid:
                offset = address & (self.granule - 1)
                return (entry.output_address | offset, True)

        return (0, False)

    def _walk_page_table(self, va: int) -> PageTableEntry:
        """
        Walk the page table for a virtual address.

        4KB granule, 4-level walk:
        - Level 0: bits [47:39] → 512 entries
        - Level 1: bits [38:30] → 512 entries (1GB blocks)
        - Level 2: bits [29:21] → 512 entries (2MB blocks)
        - Level 3: bits [20:12] → 512 entries (4KB pages)
        """
        if not self._mem_read:
            return PageTableEntry()

        table_addr = self.ttbr0

        for level in range(4):
            # Index bits for this level
            shift = 39 - (level * 9)
            index = (va >> shift) & 0x1FF

            # Read descriptor (8 bytes)
            desc_addr = table_addr + index * 8
            try:
                desc_bytes = self._mem_read(desc_addr, 8)
                desc = int.from_bytes(desc_bytes, 'little')
            except Exception:
                return PageTableEntry()

            entry = PageTableEntry.from_descriptor(desc, level, self.granule)
            if not entry.valid:
                return entry

            if entry.is_table and level < 3:
                # Follow table pointer
                table_addr = entry.next_table_addr
            else:
                # Block or page entry - done
                # Adjust output address for block size
                block_size = 1 << shift
                block_mask = block_size - 1
                entry.output_address = (entry.output_address & ~block_mask) | (va & block_mask)
                return entry

        return PageTableEntry()

    def check_access(self, address: int, size: int = 4,
                     is_write: bool = False, is_privileged: bool = True,
                     is_instruction: bool = False,
                     ns: bool = False, core_id: int = 0) -> bool:
        """Check if access is permitted by the MMU."""
        self.access_checks += 1

        if not self.enabled:
            return True

        # Translate address
        pa, valid = self.translate_address(address, is_write, is_privileged, ns)
        if not valid:
            self._generate_fault(address, size, is_write, is_privileged, is_instruction,
                                 "translation_fault")
            return False

        # Check permissions from TLB entry
        page_va = address & ~(self.granule - 1)
        entry = self._tlb.get(page_va)
        if entry and not entry.check_permission(is_write, is_privileged, is_instruction):
            self._generate_fault(address, size, is_write, is_privileged, is_instruction,
                                 "permission_fault")
            return False

        return True

    def _generate_fault(self, address: int, size: int, is_write: bool,
                        is_privileged: bool, is_instruction: bool,
                        details: str):
        """Generate a Data/Prefetch Abort."""
        self.faults_generated += 1
        self.record_violation(ProtectionFault(
            address=address, size=size, is_write=is_write,
            is_privileged=is_privileged, is_instruction=is_instruction,
            fault_type="MMU", details=details,
        ))

    def flush_tlb(self):
        """Flush entire TLB (TLBI ALL)."""
        self._tlb.clear()

    def flush_tlb_va(self, va: int):
        """Flush TLB entry for specific VA (TLBI VAE1)."""
        page_va = va & ~(self.granule - 1)
        self._tlb.pop(page_va, None)

    def get_stats(self) -> Dict:
        """Get MMU statistics."""
        return {
            'enabled': self.enabled,
            'ttbr0': f"0x{self.ttbr0:016X}",
            'ttbr1': f"0x{self.ttbr1:016X}",
            'mappings': len(self._mappings),
            'tlb_entries': len(self._tlb),
            'tlb_hits': self._tlb_hits,
            'tlb_misses': self._tlb_misses,
            'access_checks': self.access_checks,
            'faults': self.faults_generated,
        }


# =============================================================================
# APPLE DART (Device Address Resolution Table)
# =============================================================================

class DARTReg(IntEnum):
    """DART register offsets (Apple T8101/M1 style)."""
    PARAMS1 = 0x00
    PARAMS2 = 0x04
    TLB_OP = 0x20       # TLB operations
    TLB_OP_BUSY = 0x24
    ERROR_STATUS = 0x40
    ERROR_ADDR_LO = 0x50
    ERROR_ADDR_HI = 0x54
    CONFIG = 0x60       # DART configuration
    # Stream Command Registers (per-stream, stride 4)
    TCR_BASE = 0x100    # Translation Control (enable, bypass)
    # Translation Table Base (per-stream, per-level)
    TTBR_BASE = 0x200   # 4 levels * N streams


@dataclass
class DARTStream:
    """
    A DART stream (one per device/endpoint).

    Each stream has its own set of page tables and can be
    independently enabled/disabled.
    """
    index: int = 0
    enabled: bool = False
    bypass: bool = False  # Bypass = identity mapping

    # Translation table base addresses (up to 4 levels)
    ttbr: List[int] = field(default_factory=lambda: [0, 0, 0, 0])

    # Manual mappings (device VA → physical PA)
    mappings: List[Dict] = field(default_factory=list)


class AppleDART(MemoryProtectionController):
    """
    Apple DART (Device Address Resolution Table) - IOMMU.

    Used in Apple SoCs (A14+, M1+) to isolate DMA-capable devices.
    Each device has a "stream" with its own address translation tables.

    Key differences from CPU MMU:
    - Translates device/DMA addresses, not CPU virtual addresses
    - Per-stream (per-device) isolation
    - Simpler page tables (3-level, 16KB pages on M1)
    - No execute permission (devices don't fetch instructions)
    - Error reporting via DART error registers

    Usage:
        dart = AppleDART(num_streams=16)
        dart.enable_override()

        # Configure stream 0 (e.g., USB controller)
        dart.configure_stream(0, enabled=True)
        dart.add_stream_mapping(0, dva=0x0, pa=0x800000000, size=0x10000)

        # Check DMA access from device on stream 0
        allowed = dart.check_access(0x1000, is_write=True, core_id=0)  # core_id = stream
    """

    PAGE_SIZE = 16384  # 16KB pages (M1 DART)

    def __init__(self, num_streams: int = 16, page_size: int = 16384):
        super().__init__()
        self.num_streams = num_streams
        self.page_size = page_size
        self.enabled = False

        # Streams (one per device)
        self.streams: List[DARTStream] = [
            DARTStream(index=i) for i in range(num_streams)
        ]

        # Error state
        self._error_status: int = 0
        self._error_addr: int = 0
        self._error_stream: int = 0

        # Memory read callback (for page table walking)
        self._mem_read: Optional[Callable[[int, int], bytes]] = None

        # TLB per stream
        self._tlb: Dict[Tuple[int, int], int] = {}  # (stream, page_dva) → pa
        self._tlb_hits = 0
        self._tlb_misses = 0

        # Statistics
        self.access_checks = 0
        self.faults_generated = 0

    def reset(self):
        """Reset DART to power-on state."""
        self.enabled = False
        for s in self.streams:
            s.enabled = False
            s.bypass = False
            s.ttbr = [0, 0, 0, 0]
            s.mappings.clear()
        self._error_status = 0
        self._error_addr = 0
        self._tlb.clear()
        self._tlb_hits = 0
        self._tlb_misses = 0
        self.access_checks = 0
        self.faults_generated = 0
        self._violation_count = 0
        self._violation_log.clear()

    def set_memory_reader(self, callback: Callable[[int, int], bytes]):
        """Set callback to read physical memory (for page table walks)."""
        self._mem_read = callback

    def configure_stream(self, stream: int, enabled: bool = True,
                         bypass: bool = False):
        """Configure a DART stream."""
        if stream < self.num_streams:
            self.streams[stream].enabled = enabled
            self.streams[stream].bypass = bypass

    def set_stream_ttbr(self, stream: int, level: int, addr: int):
        """Set translation table base for a stream level."""
        if stream < self.num_streams and level < 4:
            self.streams[stream].ttbr[level] = addr
            # Invalidate TLB for this stream
            self._tlb = {k: v for k, v in self._tlb.items() if k[0] != stream}

    def add_stream_mapping(self, stream: int, dva: int, pa: int, size: int,
                           writable: bool = True):
        """
        Add a manual DVA→PA mapping for a stream.

        Args:
            stream: Stream index (device ID)
            dva: Device Virtual Address
            pa: Physical Address
            size: Mapping size in bytes
            writable: Allow writes
        """
        if stream < self.num_streams:
            self.streams[stream].mappings.append({
                'dva': dva,
                'pa': pa,
                'size': size,
                'writable': writable,
            })
            # Clear TLB for this stream
            self._tlb = {k: v for k, v in self._tlb.items() if k[0] != stream}

    def translate_address(self, address: int, is_write: bool = False,
                          is_privileged: bool = True,
                          ns: bool = False) -> Tuple[int, bool]:
        """
        Translate device virtual address to physical address.

        Note: For DART, core_id maps to stream index.
        This base version uses stream 0. Use translate_stream() for explicit stream.
        """
        return self.translate_stream(0, address)

    def translate_stream(self, stream: int, dva: int) -> Tuple[int, bool]:
        """Translate DVA to PA for a specific stream."""
        if stream >= self.num_streams:
            return (0, False)

        s = self.streams[stream]
        if not s.enabled:
            return (0, False)

        if s.bypass:
            return (dva, True)  # Identity mapping

        # Check TLB
        page_dva = dva & ~(self.page_size - 1)
        tlb_key = (stream, page_dva)
        if tlb_key in self._tlb:
            self._tlb_hits += 1
            pa_base = self._tlb[tlb_key]
            return (pa_base | (dva & (self.page_size - 1)), True)

        self._tlb_misses += 1

        # Check manual mappings
        for m in s.mappings:
            if m['dva'] <= dva < m['dva'] + m['size']:
                offset = dva - m['dva']
                pa = m['pa'] + offset
                # Cache in TLB
                self._tlb[tlb_key] = m['pa'] + (offset & ~(self.page_size - 1))
                return (pa, True)

        # Page table walk would go here (if _mem_read is set)
        if self._mem_read and s.ttbr[0]:
            pa = self._walk_dart_tables(s, dva)
            if pa is not None:
                self._tlb[tlb_key] = pa & ~(self.page_size - 1)
                return (pa, True)

        return (0, False)

    def _walk_dart_tables(self, stream: DARTStream, dva: int) -> Optional[int]:
        """
        Walk DART page tables (3-level, 16KB granule on M1).

        Level 0: bits [47:36] → 4096 entries
        Level 1: bits [35:25] → 2048 entries
        Level 2: bits [24:14] → 2048 entries → 16KB page
        """
        if not self._mem_read:
            return None

        table_addr = stream.ttbr[0]
        shifts = [36, 25, 14]  # Bit shifts for each level
        masks = [0xFFF, 0x7FF, 0x7FF]  # Index masks

        for level in range(3):
            index = (dva >> shifts[level]) & masks[level]
            desc_addr = table_addr + index * 8

            try:
                desc_bytes = self._mem_read(desc_addr, 8)
                desc = int.from_bytes(desc_bytes, 'little')
            except Exception:
                return None

            if not (desc & 1):  # Valid bit
                return None

            if level < 2:
                # Table descriptor - follow pointer
                table_addr = desc & 0x0000FFFFFFFC0000
            else:
                # Page descriptor
                pa_base = desc & 0x0000FFFFFFFC0000
                offset = dva & (self.page_size - 1)
                return pa_base | offset

        return None

    def check_access(self, address: int, size: int = 4,
                     is_write: bool = False, is_privileged: bool = True,
                     is_instruction: bool = False,
                     ns: bool = False, core_id: int = 0) -> bool:
        """
        Check if a DMA access is permitted.

        For DART, core_id is used as the stream index (device ID).
        """
        self.access_checks += 1

        if not self.enabled:
            return True

        stream = core_id  # Map core_id to stream for DART
        if stream >= self.num_streams:
            self._generate_fault(stream, address, size, is_write, "invalid_stream")
            return False

        s = self.streams[stream]
        if not s.enabled:
            self._generate_fault(stream, address, size, is_write, "stream_disabled")
            return False

        if s.bypass:
            return True  # Bypass mode, all accesses pass

        # Translate and check
        pa, valid = self.translate_stream(stream, address)
        if not valid:
            self._generate_fault(stream, address, size, is_write, "translation_fault")
            return False

        # Check write permission on manual mappings
        if is_write:
            for m in s.mappings:
                if m['dva'] <= address < m['dva'] + m['size']:
                    if not m.get('writable', True):
                        self._generate_fault(stream, address, size, is_write,
                                             "write_permission")
                        return False
                    break

        return True

    def _generate_fault(self, stream: int, address: int, size: int,
                        is_write: bool, details: str):
        """Generate a DART fault."""
        self.faults_generated += 1
        self._error_status = 1
        self._error_addr = address
        self._error_stream = stream

        self.record_violation(ProtectionFault(
            address=address, size=size, is_write=is_write,
            is_privileged=True, is_instruction=False,
            fault_type="DART",
            details=f"stream={stream} {details}",
        ))

    def flush_tlb(self, stream: Optional[int] = None):
        """Flush TLB entries (all or per-stream)."""
        if stream is not None:
            self._tlb = {k: v for k, v in self._tlb.items() if k[0] != stream}
        else:
            self._tlb.clear()

    # =========================================================================
    # Register Interface
    # =========================================================================

    def read_register(self, offset: int) -> int:
        """Read DART register."""
        if offset == DARTReg.PARAMS1:
            return self.num_streams
        elif offset == DARTReg.CONFIG:
            return 1 if self.enabled else 0
        elif offset == DARTReg.ERROR_STATUS:
            return self._error_status
        elif offset == DARTReg.ERROR_ADDR_LO:
            return self._error_addr & 0xFFFFFFFF
        elif offset == DARTReg.ERROR_ADDR_HI:
            return (self._error_addr >> 32) & 0xFFFFFFFF
        elif DARTReg.TCR_BASE <= offset < DARTReg.TCR_BASE + self.num_streams * 4:
            stream = (offset - DARTReg.TCR_BASE) // 4
            s = self.streams[stream]
            return (1 if s.enabled else 0) | (2 if s.bypass else 0)
        return 0

    def write_register(self, offset: int, value: int):
        """Write DART register."""
        if offset == DARTReg.CONFIG:
            self.enabled = bool(value & 1)
        elif offset == DARTReg.TLB_OP:
            # TLB invalidate operation
            if value & 1:
                stream = (value >> 8) & 0xFF
                self.flush_tlb(stream if stream < self.num_streams else None)
        elif offset == DARTReg.ERROR_STATUS:
            # W1C: write 1 to clear
            self._error_status &= ~value
        elif DARTReg.TCR_BASE <= offset < DARTReg.TCR_BASE + self.num_streams * 4:
            stream = (offset - DARTReg.TCR_BASE) // 4
            if stream < self.num_streams:
                self.streams[stream].enabled = bool(value & 1)
                self.streams[stream].bypass = bool(value & 2)
        elif DARTReg.TTBR_BASE <= offset < DARTReg.TTBR_BASE + self.num_streams * 16:
            # 4 levels per stream, 4 bytes each
            idx = (offset - DARTReg.TTBR_BASE) // 4
            stream = idx // 4
            level = idx % 4
            if stream < self.num_streams:
                self.streams[stream].ttbr[level] = value << 12  # Page-aligned

    def get_stats(self) -> Dict:
        """Get DART statistics."""
        active_streams = sum(1 for s in self.streams if s.enabled)
        return {
            'enabled': self.enabled,
            'num_streams': self.num_streams,
            'active_streams': active_streams,
            'tlb_entries': len(self._tlb),
            'tlb_hits': self._tlb_hits,
            'tlb_misses': self._tlb_misses,
            'access_checks': self.access_checks,
            'faults': self.faults_generated,
            'last_error_addr': f"0x{self._error_addr:016X}" if self._error_status else None,
        }
