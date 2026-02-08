"""
Bus Access Logger for SLAB Peripherals

Provides configurable logging for:
  1. Unhandled memory accesses (red) - addresses with no peripheral handler
  2. Uninitialized memory reads (yellow) - reads before any write

Enable unhandled access logging via:
  - Environment variable: SLAB_LOG_UNHANDLED=1
  - Command line: --log-unhandled [logfile]
  - Programmatically: bus_logger.enable()

Enable uninitialized memory tracking via:
  - Environment variable: SLAB_LOG_UNINIT=1
  - Command line: --log-uninit
  - Programmatically: tracker = UninitializedMemoryTracker(...); tracker.enable()

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
from typing import Optional, TextIO

# ANSI color codes
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Module-level configuration
_enabled: bool = False
_log_file: Optional[TextIO] = None
_access_count: int = 0
_max_log_per_address: int = 10  # Suppress after N accesses to same address
_seen_addresses: dict = {}


def enable(log_file: Optional[str] = None):
    """Enable unhandled access logging."""
    global _enabled, _log_file
    _enabled = True
    if log_file:
        _log_file = open(log_file, 'a')


def disable():
    """Disable unhandled access logging."""
    global _enabled, _log_file
    _enabled = False
    if _log_file:
        _log_file.close()
        _log_file = None


def is_enabled() -> bool:
    """Check if logging is enabled."""
    return _enabled


def reset_stats():
    """Reset access counters."""
    global _access_count, _seen_addresses
    _access_count = 0
    _seen_addresses.clear()


def get_stats() -> dict:
    """Get unhandled access statistics."""
    return {
        'total_unhandled': _access_count,
        'unique_addresses': len(_seen_addresses),
        'top_offenders': sorted(
            _seen_addresses.items(), key=lambda x: x[1], reverse=True
        )[:10],
    }


def log_unhandled(source: str, access_type: str, address: int,
                  value: Optional[int] = None, size: int = 4):
    """
    Log an unhandled memory access in red.

    Args:
        source: Peripheral/module name (e.g. "DWC2", "SHM", "TCP")
        access_type: "READ" or "WRITE"
        address: Memory address or register offset
        value: Write value (for WRITE accesses)
        size: Access size in bytes (1, 2, 4, 8)
    """
    global _access_count
    if not _enabled:
        return

    _access_count += 1

    # Suppress repeated accesses to same address
    key = (source, address)
    count = _seen_addresses.get(key, 0) + 1
    _seen_addresses[key] = count
    if count > _max_log_per_address:
        if count == _max_log_per_address + 1:
            msg = (f"{RED}[{source}] Suppressing further unhandled access logs "
                   f"for 0x{address:08X} (>{_max_log_per_address} hits){RESET}")
            print(msg, file=sys.stderr)
            if _log_file:
                _log_file.write(msg.replace(RED, '').replace(RESET, '') + '\n')
        return

    # Format the address based on size
    addr_fmt = f"0x{address:08X}" if address <= 0xFFFFFFFF else f"0x{address:016X}"

    if access_type == "WRITE" and value is not None:
        val_width = size * 2
        msg = (f"{RED}[{source}] Unhandled {access_type}{size*8}: "
               f"addr={addr_fmt} val=0x{value:0{val_width}X}{RESET}")
    else:
        msg = (f"{RED}[{source}] Unhandled {access_type}{size*8}: "
               f"addr={addr_fmt}{RESET}")

    print(msg, file=sys.stderr)
    if _log_file:
        # Strip ANSI codes for file output
        _log_file.write(msg.replace(RED, '').replace(RESET, '') + '\n')
        _log_file.flush()


# =========================================================================
# Uninitialized Memory Tracker
# =========================================================================

class UninitializedMemoryTracker:
    """
    Tracks reads from memory locations that have never been written.

    Uses a shadow bitmap (1 bit per byte) to record which addresses
    have been written. Reads from unwritten locations are logged in yellow.

    Enable via:
      - Environment variable: SLAB_LOG_UNINIT=1
      - Programmatically: tracker.enable()

    Usage:
        tracker = UninitializedMemoryTracker("SRAM", base=0x20000000, size=0x20000)
        tracker.record_write(0x20000100, 4)  # Mark 4 bytes as initialized
        tracker.check_read(0x20000100, 4)    # OK - no warning
        tracker.check_read(0x20000200, 4)    # WARNING - uninit read
    """

    def __init__(self, region_name: str, base: int = 0, size: int = 0,
                 log_reads: bool = True):
        """
        Initialize tracker for a memory region.

        Args:
            region_name: Name for log messages (e.g. "SRAM", "RAM", "STACK")
            base: Base address of the memory region
            size: Size in bytes of the memory region
            log_reads: Whether to log uninitialized reads (default True)
        """
        self.region_name = region_name
        self.base = base
        self.size = size
        self.log_reads = log_reads
        self._enabled = False

        # Shadow bitmap: 1 bit per byte, packed into bytearray
        # Each byte in _written covers 8 bytes of tracked memory
        self._written = bytearray((size + 7) // 8) if size > 0 else bytearray()

        # Statistics
        self.uninit_read_count = 0
        self.total_reads = 0
        self.total_writes = 0
        self._uninit_addresses: dict = {}  # addr -> count
        self._max_log_per_address = 5

        # Auto-enable from environment
        if os.environ.get('SLAB_LOG_UNINIT', '').strip() in ('1', 'true', 'yes'):
            self._enabled = True
        elif '--log-uninit' in sys.argv:
            self._enabled = True

    def enable(self):
        """Enable uninitialized access tracking."""
        self._enabled = True

    def disable(self):
        """Disable uninitialized access tracking."""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def resize(self, base: int, size: int):
        """Resize/relocate the tracked region (resets all state)."""
        self.base = base
        self.size = size
        self._written = bytearray((size + 7) // 8)
        self.reset_stats()

    def reset(self):
        """Reset all bytes to uninitialized state."""
        self._written = bytearray(len(self._written))

    def reset_stats(self):
        """Reset statistics only."""
        self.uninit_read_count = 0
        self.total_reads = 0
        self.total_writes = 0
        self._uninit_addresses.clear()

    def _offset(self, address: int) -> int:
        """Convert absolute address to offset within region."""
        return address - self.base

    def _in_range(self, address: int, size: int) -> bool:
        """Check if access is within tracked region."""
        offset = self._offset(address)
        return 0 <= offset and offset + size <= self.size

    def _mark_written(self, offset: int, size: int):
        """Mark bytes as written in shadow bitmap."""
        for i in range(size):
            byte_idx = (offset + i) >> 3
            bit_idx = (offset + i) & 7
            if byte_idx < len(self._written):
                self._written[byte_idx] |= (1 << bit_idx)

    def _is_written(self, offset: int) -> bool:
        """Check if a single byte has been written."""
        byte_idx = offset >> 3
        bit_idx = offset & 7
        if byte_idx < len(self._written):
            return bool(self._written[byte_idx] & (1 << bit_idx))
        return False

    def record_write(self, address: int, size: int):
        """
        Record a write, marking bytes as initialized.

        Call this on every memory write to the tracked region.
        """
        if not self._in_range(address, size):
            return
        self.total_writes += 1
        offset = self._offset(address)
        self._mark_written(offset, size)

    def check_read(self, address: int, size: int) -> bool:
        """
        Check a read for uninitialized bytes.

        Returns True if all bytes were previously written (safe).
        Returns False and logs if any byte is uninitialized.
        """
        if not self._in_range(address, size):
            return True  # Out of range, not our concern
        self.total_reads += 1

        if not self._enabled:
            return True

        offset = self._offset(address)

        # Check each byte in the access
        uninit_bytes = []
        for i in range(size):
            if not self._is_written(offset + i):
                uninit_bytes.append(offset + i)

        if not uninit_bytes:
            return True

        # Found uninitialized read
        self.uninit_read_count += 1

        if not self.log_reads:
            return False

        # Suppress repeated logging
        count = self._uninit_addresses.get(address, 0) + 1
        self._uninit_addresses[address] = count
        if count > self._max_log_per_address:
            if count == self._max_log_per_address + 1:
                msg = (f"{YELLOW}[{self.region_name}] Suppressing further uninit "
                       f"read logs for 0x{address:08X}{RESET}")
                print(msg, file=sys.stderr)
            return False

        addr_fmt = f"0x{address:08X}" if address <= 0xFFFFFFFF else f"0x{address:016X}"
        n_uninit = len(uninit_bytes)
        msg = (f"{YELLOW}[{self.region_name}] Uninitialized READ{size*8}: "
               f"addr={addr_fmt} ({n_uninit}/{size} bytes uninit){RESET}")
        print(msg, file=sys.stderr)
        if _log_file:
            _log_file.write(msg.replace(YELLOW, '').replace(RESET, '') + '\n')
            _log_file.flush()

        return False

    def mark_region_initialized(self, address: int, size: int):
        """
        Mark an entire region as initialized (e.g. after DMA fill, memset).
        """
        if not self._in_range(address, size):
            return
        offset = self._offset(address)
        self._mark_written(offset, size)

    def get_stats(self) -> dict:
        """Get uninitialized access statistics."""
        # Count total initialized bytes
        init_count = 0
        for byte_val in self._written:
            init_count += bin(byte_val).count('1')

        return {
            'region': self.region_name,
            'base': f"0x{self.base:08X}",
            'size': self.size,
            'total_reads': self.total_reads,
            'total_writes': self.total_writes,
            'uninit_reads': self.uninit_read_count,
            'bytes_initialized': init_count,
            'bytes_total': self.size,
            'coverage_pct': (init_count / self.size * 100) if self.size else 0,
            'top_uninit_reads': sorted(
                self._uninit_addresses.items(), key=lambda x: x[1], reverse=True
            )[:10],
        }


# Auto-enable from environment variable or command-line args
if os.environ.get('SLAB_LOG_UNHANDLED', '').strip() in ('1', 'true', 'yes'):
    enable()
elif '--log-unhandled' in sys.argv:
    enable()
    # Check for optional log file argument
    try:
        idx = sys.argv.index('--log-unhandled')
        if idx + 1 < len(sys.argv) and not sys.argv[idx + 1].startswith('-'):
            enable(sys.argv[idx + 1])
    except (ValueError, IndexError):
        pass
