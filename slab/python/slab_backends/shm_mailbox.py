"""
SLAB Shared Memory Mailbox Interface

Provides Python interface to the SLAB mailbox-style SHM communication.

Supports:
- Legacy mode (simple request/response)
- Mailbox mode (separate secure/non-secure Tx/Rx channels)
- Ring buffer operations
- Framebuffer access

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import mmap
import struct
import time
from typing import Optional, Tuple, Callable
from dataclasses import dataclass
from enum import IntEnum, IntFlag


class ShmCommand(IntEnum):
    """SHM command types."""
    NOP = 0
    READ8 = 1
    READ16 = 2
    READ32 = 3
    READ64 = 4
    WRITE8 = 5
    WRITE16 = 6
    WRITE32 = 7
    WRITE64 = 8
    IRQ_SET = 9
    IRQ_CLEAR = 10
    RESET = 11
    FB_UPDATE = 12
    DMA_REQ = 13
    DMA_DONE = 14


class ShmFlags(IntFlag):
    """SHM capability flags."""
    HAS_RINGBUF = 1 << 0
    HAS_FRAMEBUF = 1 << 1
    HAS_DMA = 1 << 2
    HAS_MAILBOX = 1 << 3


@dataclass
class RingEntry:
    """Ring buffer entry."""
    cmd: int
    flags: int
    addr: int
    data: int
    size: int
    seq: int

    def pack(self) -> bytes:
        """Pack entry to bytes."""
        return struct.pack('<IIQQI4x', self.cmd, self.flags, self.addr,
                          self.data, self.size, self.seq)

    @classmethod
    def unpack(cls, data: bytes) -> 'RingEntry':
        """Unpack entry from bytes."""
        cmd, flags, addr, data_val, size, seq = struct.unpack('<IIQQI4x', data[:32])
        return cls(cmd, flags, addr, data_val, size, seq)


class SecurityContext:
    """CPU security context."""

    def __init__(self, raw: int = 0):
        self.raw = raw

    @property
    def cpu_id(self) -> int:
        """CPU/core ID."""
        return self.raw & 0xFF

    @property
    def is_secure(self) -> bool:
        """True if access from secure world."""
        return bool(self.raw & (1 << 8))

    @property
    def exception_level(self) -> int:
        """Exception level (0-3)."""
        return (self.raw >> 9) & 0x3

    @property
    def is_hypervisor(self) -> bool:
        """True if hypervisor context."""
        return bool(self.raw & (1 << 11))

    def __repr__(self):
        return (f"SecurityContext(cpu={self.cpu_id}, "
                f"secure={self.is_secure}, EL{self.exception_level}, "
                f"hyp={self.is_hypervisor})")


class SlabShmMailbox:
    """
    SLAB Shared Memory Mailbox Interface.

    Provides both legacy and mailbox-style communication with QEMU.
    """

    MAGIC = 0x534C4142  # "SLAB"
    VERSION_LEGACY = 1
    VERSION_MAILBOX = 2
    HEADER_SIZE = 256
    RING_ENTRY_SIZE = 32
    RING_DEFAULT_COUNT = 2048

    def __init__(self, shm_name: str):
        """
        Open shared memory mailbox.

        Args:
            shm_name: POSIX shared memory name (e.g., "/slab_periph_a")
        """
        self.shm_name = shm_name
        self.shm_fd = None
        self.shm = None
        self.size = 0
        self.flags = ShmFlags(0)
        self.version = 0

        # Mailbox ring offsets
        self.secure_tx_offset = 0
        self.secure_rx_offset = 0
        self.ns_tx_offset = 0
        self.ns_rx_offset = 0

        # Framebuffer info
        self.fb_offset = 0
        self.fb_size = 0
        self.fb_width = 0
        self.fb_height = 0
        self.fb_stride = 0
        self.fb_format = 0

        # DMA info
        self.dma_offset = 0
        self.dma_size = 0

        # Callbacks
        self.on_secure_request: Optional[Callable[[RingEntry], Optional[RingEntry]]] = None
        self.on_ns_request: Optional[Callable[[RingEntry], Optional[RingEntry]]] = None

        self._open()

    def _open(self):
        """Open and map shared memory."""
        import os
        import posix_ipc

        try:
            shm = posix_ipc.SharedMemory(self.shm_name)
            self.shm_fd = shm.fd

            # Get size
            stat = os.fstat(self.shm_fd)
            self.size = stat.st_size

            # Map it
            self.shm = mmap.mmap(self.shm_fd, self.size,
                                 mmap.MAP_SHARED,
                                 mmap.PROT_READ | mmap.PROT_WRITE)

            self._read_header()

        except ImportError:
            # Fallback without posix_ipc
            import ctypes
            rt = ctypes.CDLL('librt.so.1')
            self.shm_fd = rt.shm_open(self.shm_name.encode(), 2, 0o600)  # O_RDWR
            if self.shm_fd < 0:
                raise RuntimeError(f"Failed to open shm: {self.shm_name}")

            # Get size - assume 1MB if can't determine
            self.size = 1024 * 1024
            self.shm = mmap.mmap(self.shm_fd, self.size)
            self._read_header()

    def _read_header(self):
        """Read and parse SHM header."""
        self.shm.seek(0)
        header = self.shm.read(self.HEADER_SIZE)

        magic, version, total_size, flags = struct.unpack('<IIII', header[:16])

        if magic != self.MAGIC:
            raise RuntimeError(f"Invalid SHM magic: {magic:#x}")

        self.version = version
        self.flags = ShmFlags(flags)

        if flags & ShmFlags.HAS_MAILBOX:
            # Parse mailbox layout
            self.secure_tx_offset = struct.unpack('<I', header[112:116])[0]
            self.secure_rx_offset = struct.unpack('<I', header[116:120])[0]
            self.ns_tx_offset = struct.unpack('<I', header[120:124])[0]
            self.ns_rx_offset = struct.unpack('<I', header[124:128])[0]

        if flags & ShmFlags.HAS_FRAMEBUF:
            fb_data = struct.unpack('<IIIIIII', header[76:104])
            self.fb_offset = fb_data[0]
            self.fb_size = fb_data[1]
            self.fb_width = fb_data[2]
            self.fb_height = fb_data[3]
            self.fb_stride = fb_data[4]
            self.fb_format = fb_data[5]

        if flags & ShmFlags.HAS_DMA:
            self.dma_offset = struct.unpack('<I', header[104:108])[0]
            self.dma_size = struct.unpack('<I', header[108:112])[0]

    def close(self):
        """Close shared memory."""
        if self.shm:
            self.shm.close()
            self.shm = None
        if self.shm_fd is not None:
            import os
            os.close(self.shm_fd)
            self.shm_fd = None

    # =========================================================================
    # Legacy Mode Operations
    # =========================================================================

    def legacy_read(self, addr: int, size: int) -> int:
        """
        Legacy read operation (blocking).

        Args:
            addr: Address to read
            size: Size (1, 2, 4, or 8)

        Returns:
            Read value
        """
        cmd = {1: ShmCommand.READ8, 2: ShmCommand.READ16,
               4: ShmCommand.READ32, 8: ShmCommand.READ64}[size]

        # Write command
        self.shm.seek(16)  # cmd offset
        self.shm.write(struct.pack('<I', cmd))
        self.shm.write(struct.pack('<I', 0))  # status = 0 (pending)
        self.shm.write(struct.pack('<Q', addr))
        self.shm.write(struct.pack('<Q', 0))  # data
        self.shm.write(struct.pack('<I', size))

        # Wait for response
        timeout = 1.0
        start = time.time()
        while time.time() - start < timeout:
            self.shm.seek(20)  # status offset
            status = struct.unpack('<I', self.shm.read(4))[0]
            if status != 0:
                self.shm.seek(32)  # data offset
                return struct.unpack('<Q', self.shm.read(8))[0]
            time.sleep(0.0001)

        raise TimeoutError("Legacy read timed out")

    def legacy_write(self, addr: int, size: int, value: int):
        """
        Legacy write operation (blocking).

        Args:
            addr: Address to write
            size: Size (1, 2, 4, or 8)
            value: Value to write
        """
        cmd = {1: ShmCommand.WRITE8, 2: ShmCommand.WRITE16,
               4: ShmCommand.WRITE32, 8: ShmCommand.WRITE64}[size]

        self.shm.seek(16)
        self.shm.write(struct.pack('<I', cmd))
        self.shm.write(struct.pack('<I', 0))
        self.shm.write(struct.pack('<Q', addr))
        self.shm.write(struct.pack('<Q', value))
        self.shm.write(struct.pack('<I', size))

        # Wait for completion
        timeout = 1.0
        start = time.time()
        while time.time() - start < timeout:
            self.shm.seek(20)
            status = struct.unpack('<I', self.shm.read(4))[0]
            if status != 0:
                return
            time.sleep(0.0001)

        raise TimeoutError("Legacy write timed out")

    # =========================================================================
    # Mailbox Mode Operations
    # =========================================================================

    def _read_ring_entry(self, ring_offset: int, index: int) -> RingEntry:
        """Read entry from ring buffer."""
        offset = ring_offset + (index * self.RING_ENTRY_SIZE)
        self.shm.seek(offset)
        return RingEntry.unpack(self.shm.read(self.RING_ENTRY_SIZE))

    def _write_ring_entry(self, ring_offset: int, index: int, entry: RingEntry):
        """Write entry to ring buffer."""
        offset = ring_offset + (index * self.RING_ENTRY_SIZE)
        self.shm.seek(offset)
        self.shm.write(entry.pack())

    def process_mailbox(self) -> int:
        """
        Process pending mailbox requests.

        Returns:
            Number of requests processed
        """
        if not (self.flags & ShmFlags.HAS_MAILBOX):
            return 0

        processed = 0

        # Process secure TX (QEMU → Python)
        processed += self._process_tx_ring(
            self.secure_tx_offset, 128, 132,  # head/tail offsets
            self.secure_rx_offset, 136, 140,
            self.on_secure_request, is_secure=True
        )

        # Process non-secure TX (QEMU → Python)
        processed += self._process_tx_ring(
            self.ns_tx_offset, 144, 148,
            self.ns_rx_offset, 152, 156,
            self.on_ns_request, is_secure=False
        )

        return processed

    def _process_tx_ring(self, tx_offset: int, head_offset: int, tail_offset: int,
                         rx_offset: int, rx_head_offset: int, rx_tail_offset: int,
                         handler: Optional[Callable], is_secure: bool) -> int:
        """Process TX ring from QEMU."""
        processed = 0

        # Read head/tail
        self.shm.seek(head_offset)
        head = struct.unpack('<I', self.shm.read(4))[0]
        self.shm.seek(tail_offset)
        tail = struct.unpack('<I', self.shm.read(4))[0]

        while tail != head:
            entry = self._read_ring_entry(tx_offset, tail % self.RING_DEFAULT_COUNT)

            if handler:
                response = handler(entry)
                if response:
                    # Write response to RX ring
                    self.shm.seek(rx_tail_offset)
                    rx_tail = struct.unpack('<I', self.shm.read(4))[0]
                    self._write_ring_entry(rx_offset,
                                          rx_tail % self.RING_DEFAULT_COUNT,
                                          response)
                    # Update RX tail
                    self.shm.seek(rx_tail_offset)
                    self.shm.write(struct.pack('<I', (rx_tail + 1) % self.RING_DEFAULT_COUNT))

            # Update TX tail
            tail = (tail + 1) % self.RING_DEFAULT_COUNT
            self.shm.seek(tail_offset)
            self.shm.write(struct.pack('<I', tail))
            processed += 1

        return processed

    # =========================================================================
    # Framebuffer Operations
    # =========================================================================

    def get_framebuffer(self) -> Optional[memoryview]:
        """Get framebuffer memory view."""
        if not (self.flags & ShmFlags.HAS_FRAMEBUF) or self.fb_size == 0:
            return None
        return memoryview(self.shm)[self.fb_offset:self.fb_offset + self.fb_size]

    def set_framebuffer_config(self, width: int, height: int, stride: int, fmt: int):
        """Configure framebuffer dimensions."""
        self.fb_width = width
        self.fb_height = height
        self.fb_stride = stride
        self.fb_format = fmt

        # Write to header
        self.shm.seek(84)  # fb_width offset
        self.shm.write(struct.pack('<IIII', width, height, stride, fmt))

    def mark_framebuffer_dirty(self):
        """Mark framebuffer as dirty (needs update)."""
        self.shm.seek(100)  # fb_dirty offset
        self.shm.write(struct.pack('<I', 1))

    def clear_framebuffer_dirty(self):
        """Clear framebuffer dirty flag."""
        self.shm.seek(100)
        self.shm.write(struct.pack('<I', 0))

    def is_framebuffer_dirty(self) -> bool:
        """Check if framebuffer is dirty."""
        self.shm.seek(100)
        return struct.unpack('<I', self.shm.read(4))[0] != 0

    # =========================================================================
    # DMA Operations
    # =========================================================================

    def get_dma_buffer(self) -> Optional[memoryview]:
        """Get DMA buffer memory view."""
        if not (self.flags & ShmFlags.HAS_DMA) or self.dma_size == 0:
            return None
        return memoryview(self.shm)[self.dma_offset:self.dma_offset + self.dma_size]

    # =========================================================================
    # Context Manager
    # =========================================================================

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __repr__(self):
        return (f"SlabShmMailbox({self.shm_name}, version={self.version}, "
                f"size={self.size // (1024*1024)}MB, flags={self.flags})")
