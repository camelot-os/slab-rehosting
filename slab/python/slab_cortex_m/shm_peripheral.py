#!/usr/bin/env python3
"""
Shared Memory Peripheral Bridge

High-performance peripheral communication via POSIX shared memory.
Lower latency than TCP for local emulation.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import mmap
import struct
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable, List
from enum import IntEnum
from threading import Thread, Lock
import ctypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from slab_peripherals.bus_logger import log_unhandled as _log_unhandled
from slab_peripherals.mpu import MemoryProtectionController, CortexMPU, MPURegion, MPUCtrlBits
try:
    from slab_peripherals.pmp import RiscVPMP
    HAS_PMP = True
except ImportError:
    HAS_PMP = False
    RiscVPMP = None


# Try to import POSIX shared memory
try:
    from multiprocessing import shared_memory
    HAS_SHM = True
except ImportError:
    HAS_SHM = False


class ShmCommand(IntEnum):
    """Shared memory command codes."""
    NOP = 0
    READ8 = 1
    READ16 = 2
    READ32 = 3
    WRITE8 = 4
    WRITE16 = 5
    WRITE32 = 6
    IRQ_SET = 7
    IRQ_CLEAR = 8
    RESET = 9
    SYNC = 10
    # 64-bit bus width extensions (protocol v2)
    READ64 = 11
    WRITE64 = 12
    # MPU state sync from QEMU
    MPU_SYNC = 13
    # Snapshot and fault commands
    SNAPSHOT_SAVE = 15
    SNAPSHOT_RESTORE = 16
    FAULT_NOTIFY = 17


@dataclass
class BusAttributes:
    """
    Bus transaction attributes for privilege/security context.

    Tracks the CPU/core originating the access, security state,
    privilege level, and bus width for all slab machines.
    """
    core_id: int = 0           # CPU/core ID (0-255)
    ns: bool = False           # Non-Secure (TrustZone NS bit)
    privilege: int = 0         # 0=Unprivileged, 1=Privileged, 2=Hypervisor
    exception_level: int = 0   # ARMv8: EL0-EL3
    bus_width: int = 32        # 32 or 64 bit bus
    shareable: bool = False    # Memory shareability attribute
    cacheable: bool = True     # Memory cacheability attribute

    def pack(self) -> int:
        """Pack into 32-bit context word."""
        return (
            (self.core_id & 0xFF) |
            ((1 if self.ns else 0) << 8) |
            ((self.privilege & 0x03) << 9) |
            ((self.exception_level & 0x03) << 11) |
            ((1 if self.bus_width == 64 else 0) << 13) |
            ((1 if self.shareable else 0) << 14) |
            ((1 if self.cacheable else 0) << 15)
        )

    @classmethod
    def unpack(cls, word: int) -> 'BusAttributes':
        """Unpack from 32-bit context word."""
        return cls(
            core_id=word & 0xFF,
            ns=bool((word >> 8) & 1),
            privilege=(word >> 9) & 0x03,
            exception_level=(word >> 11) & 0x03,
            bus_width=64 if ((word >> 13) & 1) else 32,
            shareable=bool((word >> 14) & 1),
            cacheable=bool((word >> 15) & 1),
        )


@dataclass
class ShmHeader:
    """
    Shared memory region header.

    Protocol v1 Layout (backward compatible):
    [0:4]   - Magic (0x534C4142 = "SLAB")
    [4:8]   - Version (1)
    [8:12]  - Command (from QEMU)
    [12:16] - Status (from Python)
    [16:20] - Address (32-bit)
    [20:24] - Data (32-bit)
    [24:28] - Size
    [28:32] - Sequence number
    [32:36] - IRQ status
    [36:64] - Reserved
    [64:...]- Peripheral data region

    Protocol v2 Layout (64-bit + security context):
    [0:4]   - Magic (0x534C4142 = "SLAB")
    [4:8]   - Version (2)
    [8:12]  - Command (from QEMU)
    [12:16] - Status (from Python)
    [16:24] - Address (64-bit)
    [24:32] - Data (64-bit)
    [32:36] - Size
    [36:40] - Sequence number
    [40:44] - IRQ status
    [44:48] - Bus Attributes (core_id, NS, privilege, EL, bus_width)
    [48:64] - Reserved
    [64:...]- Peripheral data region
    """

    MAGIC = 0x534C4142  # "SLAB"
    VERSION = 2
    HEADER_SIZE = 64

    @staticmethod
    def pack(command: int, status: int, address: int, data: int,
             size: int, seq: int, irq: int,
             bus_attrs: Optional['BusAttributes'] = None,
             version: int = 2) -> bytes:
        """Pack header into bytes."""
        if version >= 2:
            # v2: 64-bit address/data + bus attributes
            # Layout: 4I(16) + 2Q(16) + 4I(16) + pad(16) = 64 bytes
            attrs_word = bus_attrs.pack() if bus_attrs else 0
            packed = struct.pack(
                '<IIIIQQIIII',
                ShmHeader.MAGIC,
                version,
                command,
                status,
                address,
                data,
                size,
                seq,
                irq,
                attrs_word,
            )
            return packed + b'\x00' * (64 - len(packed))
        else:
            # v1: 32-bit compatibility mode
            return struct.pack(
                '<IIIIIIIII',
                ShmHeader.MAGIC,
                1,
                command,
                status,
                address & 0xFFFFFFFF,
                data & 0xFFFFFFFF,
                size,
                seq,
                irq,
            ) + b'\x00' * 28

    @staticmethod
    def unpack(data: bytes) -> tuple:
        """
        Unpack header from bytes.

        Returns:
            (magic, version, command, status, address, value, size, seq, irq, bus_attrs)
        """
        magic, version = struct.unpack('<II', data[:8])

        if version >= 2 and len(data) >= 48:
            # v2: 64-bit fields
            _, _, command, status = struct.unpack('<IIII', data[:16])
            address, value = struct.unpack('<QQ', data[16:32])
            size, seq, irq, attrs_word = struct.unpack('<IIII', data[32:48])
            bus_attrs = BusAttributes.unpack(attrs_word)
            return magic, version, command, status, address, value, size, seq, irq, bus_attrs
        else:
            # v1: 32-bit compatibility
            magic, version, command, status, address, value, size, seq = \
                struct.unpack('<IIIIIIII', data[:32])
            irq = struct.unpack('<I', data[32:36])[0]
            # Extended v1: bus attributes at offset 40, PC at offset 44
            if len(data) >= 48:
                bus_attrs_word, pc = struct.unpack('<II', data[40:48])
                bus_attrs = BusAttributes.unpack(bus_attrs_word) if bus_attrs_word else BusAttributes()
            else:
                bus_attrs = BusAttributes()
                pc = 0
            return magic, version, command, status, address, value, size, seq, irq, bus_attrs


@dataclass
class ShmPeripheralBridge:
    """
    Shared memory peripheral bridge.

    Provides high-performance communication between QEMU and Python
    for peripheral emulation.
    """

    # Shared memory name
    shm_name: str = "/slab_peripheral"

    # Region size
    region_size: int = 1024 * 1024  # 1MB

    # Peripheral base addresses
    peripheral_map: Dict[int, 'PeripheralHandler'] = field(default_factory=dict)

    # Internal state
    _shm: Optional[shared_memory.SharedMemory] = None
    _mmap: Optional[mmap.mmap] = None
    _running: bool = False
    _thread: Optional[Thread] = None
    _lock: Lock = field(default_factory=Lock)

    # Memory protection controller (MPU/MMU/DART override mode)
    protection: Optional['MemoryProtectionController'] = None

    # ARMv8-M flag (Cortex-M23/M33/M55) -- used for PMSAv8 MPU format in SHM sync
    arch_v8m: bool = False

    # Fault handler (for crash detection and auto-snapshot)
    fault_handler: Optional[Any] = None  # FaultHandler instance

    # Current program counter (updated each transaction, for bootloop debugging)
    last_pc: int = 0

    # Statistics
    reads: int = 0
    writes: int = 0
    irqs: int = 0

    def __post_init__(self):
        if not HAS_SHM:
            raise RuntimeError("shared_memory not available")

    def create(self):
        """Create shared memory region."""
        try:
            # Try to create new
            self._shm = shared_memory.SharedMemory(
                name=self.shm_name,
                create=True,
                size=self.region_size
            )
        except FileExistsError:
            # Connect to existing
            self._shm = shared_memory.SharedMemory(
                name=self.shm_name,
                create=False
            )

        # Initialize header
        header = ShmHeader.pack(
            command=ShmCommand.NOP,
            status=0,
            address=0,
            data=0,
            size=0,
            seq=0,
            irq=0
        )
        # Assign bytes to shared memory buffer
        header_bytes = bytes(header) if not isinstance(header, bytes) else header
        for i, b in enumerate(header_bytes[:ShmHeader.HEADER_SIZE]):
            self._shm.buf[i] = b

    def connect(self):
        """Connect to existing shared memory region."""
        self._shm = shared_memory.SharedMemory(
            name=self.shm_name,
            create=False
        )

        # Verify magic
        magic = struct.unpack('<I', self._shm.buf[:4])[0]
        if magic != ShmHeader.MAGIC:
            raise ValueError(f"Invalid shared memory magic: {magic:#x}")

    def close(self):
        """Close shared memory connection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

        if self._shm:
            self._shm.close()
            # Don't unlink - let QEMU do that
            self._shm = None

    def register_peripheral(self, base_addr: int, handler: 'PeripheralHandler'):
        """Register a peripheral handler at base address."""
        self.peripheral_map[base_addr] = handler

    def start_handler(self):
        """Start the peripheral handler thread."""
        self._running = True
        self._thread = Thread(target=self._handler_loop, daemon=True)
        self._thread.start()

    def _handler_loop(self):
        """Main handler loop - polls shared memory for commands."""
        last_seq = 0

        while self._running:
            # Read header
            header_data = bytes(self._shm.buf[:ShmHeader.HEADER_SIZE])
            parsed = ShmHeader.unpack(header_data)
            magic, version, command, status, address, data, size, seq, irq, bus_attrs = parsed

            # Check for new command (sequence number changed)
            if seq != last_seq and command != ShmCommand.NOP:
                # Read PC from extended v1 header (offset 44)
                if len(header_data) >= 48:
                    self.last_pc = struct.unpack('<I', header_data[44:48])[0]

                # Sync protection state from C-side (piggyback on each transaction)
                if self.protection:
                    if isinstance(self.protection, CortexMPU):
                        self.sync_mpu_from_shm(self.protection)
                    elif isinstance(self.protection, RiscVPMP):
                        self.sync_pmp_from_shm(self.protection)

                result = self._handle_command(command, address, data, size, bus_attrs)

                # Write response (format depends on protocol version)
                with self._lock:
                    if version >= 2:
                        struct.pack_into('<I', self._shm.buf, 12, 1)  # Status = done
                        struct.pack_into('<Q', self._shm.buf, 24, result)  # 64-bit data
                    else:
                        struct.pack_into('<I', self._shm.buf, 12, 1)  # Status = done
                        struct.pack_into('<I', self._shm.buf, 20, result & 0xFFFFFFFF)

                last_seq = seq

                # Poll for fault notifications from QEMU plugin
                if self.fault_handler:
                    self.fault_handler.poll_shm_faults(self)
            else:
                # No new command - yield thread (sched_yield on Linux)
                # time.sleep(0.0001) takes ~160us on Linux due to timer granularity;
                # time.sleep(0) just yields the thread for lower latency
                time.sleep(0)

    def _handle_command(self, command: int, address: int, data: int,
                        size: int, bus_attrs: Optional[BusAttributes] = None) -> int:
        """Handle a command from QEMU with bus attributes."""
        # Protection controller override check (MPU/MMU/DART)
        if self.protection and self.protection.override_enabled:
            is_write = command in (ShmCommand.WRITE8, ShmCommand.WRITE16,
                                   ShmCommand.WRITE32, ShmCommand.WRITE64)
            access_sz = {ShmCommand.READ8: 1, ShmCommand.READ16: 2,
                         ShmCommand.READ32: 4, ShmCommand.READ64: 8,
                         ShmCommand.WRITE8: 1, ShmCommand.WRITE16: 2,
                         ShmCommand.WRITE32: 4, ShmCommand.WRITE64: 8}.get(command, 4)
            is_priv = bus_attrs.privilege >= 1 if bus_attrs else True
            ns = bus_attrs.ns if bus_attrs else False
            core = bus_attrs.core_id if bus_attrs else 0
            if not self.protection.check_access(
                address, size=access_sz, is_write=is_write,
                is_privileged=is_priv, ns=ns, core_id=core
            ):
                return 0xDEADC0DE  # Protection fault

        # Find peripheral for address
        handler = self._find_handler(address)

        if handler is None:
            is_write = command in (ShmCommand.WRITE8, ShmCommand.WRITE16,
                                   ShmCommand.WRITE32, ShmCommand.WRITE64)
            access_sz = {ShmCommand.READ8: 1, ShmCommand.READ16: 2,
                         ShmCommand.READ32: 4, ShmCommand.READ64: 8,
                         ShmCommand.WRITE8: 1, ShmCommand.WRITE16: 2,
                         ShmCommand.WRITE32: 4, ShmCommand.WRITE64: 8}.get(command, 4)
            _log_unhandled("SHM", "WRITE" if is_write else "READ",
                           address, value=data if is_write else None, size=access_sz)
            return 0xDEADBEEF  # Unmapped

        # Check access permissions
        if bus_attrs and not handler.check_access(bus_attrs):
            _log_unhandled("SHM-ACL", "DENIED", address, size=size)
            return 0xDEADC0DE  # Access denied

        if command == ShmCommand.READ8:
            self.reads += 1
            return handler.read(address, 1, bus_attrs) & 0xFF
        elif command == ShmCommand.READ16:
            self.reads += 1
            return handler.read(address, 2, bus_attrs) & 0xFFFF
        elif command == ShmCommand.READ32:
            self.reads += 1
            return handler.read(address, 4, bus_attrs) & 0xFFFFFFFF
        elif command == ShmCommand.READ64:
            self.reads += 1
            return handler.read(address, 8, bus_attrs) & 0xFFFFFFFFFFFFFFFF
        elif command == ShmCommand.WRITE8:
            self.writes += 1
            handler.write(address, data & 0xFF, 1, bus_attrs)
            return 0
        elif command == ShmCommand.WRITE16:
            self.writes += 1
            handler.write(address, data & 0xFFFF, 2, bus_attrs)
            return 0
        elif command == ShmCommand.WRITE32:
            self.writes += 1
            handler.write(address, data & 0xFFFFFFFF, 4, bus_attrs)
            return 0
        elif command == ShmCommand.WRITE64:
            self.writes += 1
            handler.write(address, data & 0xFFFFFFFFFFFFFFFF, 8, bus_attrs)
            return 0
        elif command == ShmCommand.RESET:
            handler.reset()
            return 0

        return 0

    def _find_handler(self, address: int) -> Optional['PeripheralHandler']:
        """Find peripheral handler for address."""
        for base, handler in self.peripheral_map.items():
            if base <= address < base + handler.size:
                return handler
        return None

    def set_irq(self, irq_num: int):
        """Set IRQ line (signal to QEMU).

        Uses a 3-word bitmap at header offsets 32/36/40 to cover IRQs 0-95.
        This matches the extended QEMU C-side check in slab_proxy_shm_transaction.
        """
        if irq_num >= 96:
            return
        word_idx = irq_num // 32
        bit_idx = irq_num % 32
        offset = 32 + word_idx * 4
        with self._lock:
            current = struct.unpack('<I', self._shm.buf[offset:offset + 4])[0]
            current |= (1 << bit_idx)
            struct.pack_into('<I', self._shm.buf, offset, current)
            self.irqs += 1

    def clear_irq(self, irq_num: int):
        """Clear IRQ line."""
        if irq_num >= 96:
            return
        word_idx = irq_num // 32
        bit_idx = irq_num % 32
        offset = 32 + word_idx * 4
        with self._lock:
            current = struct.unpack('<I', self._shm.buf[offset:offset + 4])[0]
            current &= ~(1 << bit_idx)
            struct.pack_into('<I', self._shm.buf, offset, current)

    def sync_mpu_from_shm(self, mpu: Optional['CortexMPU'] = None) -> Optional['CortexMPU']:
        """
        Read MPU state from SHM data region (written by QEMU C-side).

        The C-side slab_proxy_sync_mpu_state() writes the CPU's MPU
        registers into SHM at offset 64:
          [0:4]   MPU_CTRL
          [4:68]  8 regions × {RBAR(4), RASR/RLAR(4)}

        PMSAv7 (M3/M4/M7): RBAR + RASR pairs
        PMSAv8 (M23/M33/M55): RBAR + RLAR pairs

        The format is auto-detected from mpu.arch_v8m.

        Args:
            mpu: Existing CortexMPU to update, or None to create new.

        Returns:
            Updated CortexMPU instance.
        """
        if not self._shm:
            return mpu

        MPU_OFFSET = ShmHeader.HEADER_SIZE  # 64
        MPU_MAX_REGIONS = 8
        MPU_STATE_SIZE = 4 + MPU_MAX_REGIONS * 8  # 68 bytes

        # Read MPU state from SHM
        raw = bytes(self._shm.buf[MPU_OFFSET:MPU_OFFSET + MPU_STATE_SIZE])
        if len(raw) < MPU_STATE_SIZE:
            return mpu

        ctrl = struct.unpack('<I', raw[0:4])[0]

        if mpu is None:
            mpu = CortexMPU(num_regions=MPU_MAX_REGIONS, arch_v8m=self.arch_v8m)

        # Update control register state
        mpu.enabled = bool(ctrl & (1 << MPUCtrlBits.ENABLE))
        mpu.hfnmiena = bool(ctrl & (1 << MPUCtrlBits.HFNMIENA))
        mpu.privdefena = bool(ctrl & (1 << MPUCtrlBits.PRIVDEFENA))

        # Update regions from RBAR + RASR/RLAR pairs
        for i in range(min(MPU_MAX_REGIONS, mpu.num_regions)):
            offset = 4 + i * 8
            rbar, second = struct.unpack('<II', raw[offset:offset + 8])
            if mpu.arch_v8m:
                mpu.regions[i] = MPURegion.from_rbar_rlar(i, rbar, second)
            else:
                mpu.regions[i] = MPURegion.from_rasr(i, rbar, second)

        return mpu

    def sync_pmp_from_shm(self, pmp: Optional['RiscVPMP'] = None) -> Optional['RiscVPMP']:
        """
        Read RISC-V PMP state from SHM data region (written by C-side).

        The C-side slab_riscv_sync_pmp_state() writes the CPU's PMP
        registers into SHM at offset 64:
          [0:4]     num_entries (uint32_t)
          [4:8]     mseccfg (uint32_t)
          [8:136]   16 entries × {cfg(4), addr(4)}

        Args:
            pmp: Existing RiscVPMP to update, or None to create new.

        Returns:
            Updated RiscVPMP instance, or None if PMP module unavailable.
        """
        if not self._shm:
            return pmp

        PMP_OFFSET = ShmHeader.HEADER_SIZE  # 64
        PMP_MAX_ENTRIES = 16
        PMP_STATE_SIZE = 8 + PMP_MAX_ENTRIES * 8  # 136 bytes

        raw = bytes(self._shm.buf[PMP_OFFSET:PMP_OFFSET + PMP_STATE_SIZE])
        if len(raw) < 8:
            return pmp

        if pmp is None:
            pmp = RiscVPMP(num_entries=PMP_MAX_ENTRIES)

        pmp.load_from_shm_data(raw)
        return pmp


@dataclass
class PeripheralHandler:
    """Base class for peripheral handlers."""

    name: str = "generic"
    base_address: int = 0
    size: int = 0x1000

    # Register storage
    registers: Dict[int, int] = field(default_factory=dict)

    # Callbacks (legacy 32-bit)
    read_callback: Optional[Callable[[int, int], int]] = None
    write_callback: Optional[Callable[[int, int, int], None]] = None

    # Extended callbacks with bus attributes
    read_callback_ext: Optional[Callable[[int, int, 'BusAttributes'], int]] = None
    write_callback_ext: Optional[Callable[[int, int, int, 'BusAttributes'], None]] = None

    def read(self, address: int, size: int,
             bus_attrs: Optional['BusAttributes'] = None) -> int:
        """Read from peripheral with optional bus attributes."""
        offset = address - self.base_address

        if self.read_callback_ext and bus_attrs:
            return self.read_callback_ext(offset, size, bus_attrs)
        elif self.read_callback:
            return self.read_callback(offset, size)

        return self.registers.get(offset, 0)

    def write(self, address: int, value: int, size: int,
              bus_attrs: Optional['BusAttributes'] = None):
        """Write to peripheral with optional bus attributes."""
        offset = address - self.base_address

        if self.write_callback_ext and bus_attrs:
            self.write_callback_ext(offset, value, size, bus_attrs)
        elif self.write_callback:
            self.write_callback(offset, value, size)
        else:
            self.registers[offset] = value

    def check_access(self, bus_attrs: Optional['BusAttributes'] = None) -> bool:
        """
        Check if access is permitted given bus attributes.

        Override in subclass for TrustZone/privilege enforcement.
        Returns True if access is allowed.
        """
        return True

    def reset(self):
        """Reset peripheral to default state."""
        self.registers.clear()


@dataclass
class ShmPeripheralServer:
    """
    Server that exposes multiple peripherals via shared memory.

    Usage:
        server = ShmPeripheralServer()
        server.add_peripheral(GPIOPeripheral(base=0x40020000))
        server.add_peripheral(UARTPeripheral(base=0x40011000))
        server.start()
    """

    shm_name: str = "/slab_peripheral"
    bridge: Optional[ShmPeripheralBridge] = None

    def __post_init__(self):
        self.bridge = ShmPeripheralBridge(shm_name=self.shm_name)

    def add_peripheral(self, peripheral: PeripheralHandler):
        """Add a peripheral to the server."""
        self.bridge.register_peripheral(peripheral.base_address, peripheral)

    def start(self):
        """Start the peripheral server."""
        self.bridge.create()
        self.bridge.start_handler()
        print(f"Shared memory peripheral server started: {self.shm_name}")

    def stop(self):
        """Stop the peripheral server."""
        self.bridge.close()

    def get_stats(self) -> Dict[str, int]:
        """Get server statistics."""
        return {
            "reads": self.bridge.reads,
            "writes": self.bridge.writes,
            "irqs": self.bridge.irqs,
        }
