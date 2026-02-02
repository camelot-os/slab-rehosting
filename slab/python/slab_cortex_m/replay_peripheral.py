"""
Record/Replay Peripheral Wrapper

Provides record and replay capabilities for any peripheral.
Inspired by Avatar2's forwarding mechanism.

- Record mode: captures all peripheral responses to a JSON Lines file
- Replay mode: replays responses from file without actual peripheral

SPDX-License-Identifier: Apache-2.0 OR Apache-2.0
Copyright (C) 2025 Twisted Wires Security Lab
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, asdict
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class AccessRecord:
    """Record of a single peripheral access."""
    is_write: bool
    address: int
    size: int
    value: int  # Value written (for writes) or returned (for reads)
    pc: int = 0
    timestamp: float = 0.0
    sequence: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'AccessRecord':
        return cls(**d)

    def key(self) -> str:
        """Generate lookup key for replay matching."""
        return f"{'W' if self.is_write else 'R'}:{self.address:08x}:{self.size}:{self.value if self.is_write else 0}"


class RecordReplayPeripheral:
    """
    Wrapper that adds record/replay capability to any peripheral.

    Usage:
        # Record mode - capture to file
        flash = SPIFlash("FLASH", 0x08000000, 0x100000)
        recorded_flash = RecordReplayPeripheral(flash, record_file="flash_trace.jsonl")

        # Replay mode - playback from file
        replay_flash = RecordReplayPeripheral.replay_only(
            name="FLASH", base=0x08000000, size=0x100000,
            replay_file="flash_trace.jsonl"
        )
    """

    def __init__(self, peripheral, record_file: Optional[str] = None,
                 replay_file: Optional[str] = None):
        """
        Wrap a peripheral with record/replay capability.

        Args:
            peripheral: The actual peripheral to wrap
            record_file: Path to write access records (record mode)
            replay_file: Path to read access records (replay mode)
        """
        self._peripheral = peripheral
        self.name = peripheral.name
        self.base = peripheral.base
        self.size = peripheral.size
        self.irq = getattr(peripheral, 'irq', -1)

        self._record_file = record_file
        self._replay_file = replay_file
        self._sequence = 0

        # Record mode
        self._recording = record_file is not None
        self._record_handle = None

        # Replay mode
        self._replaying = replay_file is not None
        self._replay_data: Dict[str, List[AccessRecord]] = {}
        self._replay_index: Dict[str, int] = {}

        # Statistics
        self.stats = {
            'reads': 0,
            'writes': 0,
            'replay_hits': 0,
            'replay_misses': 0,
        }

        if self._recording:
            self._open_record_file()

        if self._replaying:
            self._load_replay_file()

    @classmethod
    def replay_only(cls, name: str, base: int, size: int,
                    replay_file: str, irq: int = -1) -> 'RecordReplayPeripheral':
        """
        Create a replay-only peripheral without a backing peripheral.

        This is useful when the original hardware is not available.
        """
        # Create a dummy peripheral
        class DummyPeripheral:
            def __init__(self, name, base, size, irq):
                self.name = name
                self.base = base
                self.size = size
                self.irq = irq

            def contains(self, addr):
                return self.base <= addr < self.base + self.size

            def read(self, addr, size, secure=False):
                raise RuntimeError("Replay miss - no backing peripheral")

            def write(self, addr, size, value, secure=False):
                raise RuntimeError("Replay miss - no backing peripheral")

        dummy = DummyPeripheral(name, base, size, irq)
        return cls(dummy, replay_file=replay_file)

    def _open_record_file(self):
        """Open file for recording."""
        self._record_handle = open(self._record_file, 'w')
        logger.info(f"Recording peripheral accesses to {self._record_file}")

    def _load_replay_file(self):
        """Load replay data from file."""
        path = Path(self._replay_file)
        if not path.exists():
            raise FileNotFoundError(f"Replay file not found: {self._replay_file}")

        with open(path, 'r') as f:
            for line in f:
                if line.strip():
                    record = AccessRecord.from_dict(json.loads(line))
                    key = record.key()
                    if key not in self._replay_data:
                        self._replay_data[key] = []
                    self._replay_data[key].append(record)

        # Initialize replay indices
        for key in self._replay_data:
            self._replay_index[key] = 0

        total = sum(len(v) for v in self._replay_data.values())
        logger.info(f"Loaded {total} records from {self._replay_file}")

    def _record_access(self, record: AccessRecord):
        """Write access record to file."""
        if self._record_handle:
            self._record_handle.write(json.dumps(record.to_dict()) + '\n')
            self._record_handle.flush()

    def _get_replay_value(self, is_write: bool, addr: int, size: int,
                          write_value: int = 0) -> Optional[int]:
        """
        Get replay value for an access.

        Returns None if no matching record found.
        """
        key = f"{'W' if is_write else 'R'}:{addr:08x}:{size}:{write_value if is_write else 0}"

        if key not in self._replay_data:
            return None

        records = self._replay_data[key]
        idx = self._replay_index.get(key, 0)

        if idx >= len(records):
            # Wrap around for repeated accesses
            idx = 0

        record = records[idx]
        self._replay_index[key] = idx + 1
        self.stats['replay_hits'] += 1

        return record.value

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    def read(self, addr: int, size: int, secure: bool = False) -> Tuple[int, int]:
        """Read with record/replay support."""
        self.stats['reads'] += 1
        self._sequence += 1

        # Try replay first
        if self._replaying:
            replay_value = self._get_replay_value(False, addr, size)
            if replay_value is not None:
                logger.debug(f"Replay read 0x{addr:08X} = 0x{replay_value:08X}")
                return (replay_value, 0)
            else:
                self.stats['replay_misses'] += 1
                logger.warning(f"Replay miss for read 0x{addr:08X}")

        # Fall through to actual peripheral
        result = self._peripheral.read(addr, size, secure)
        if isinstance(result, tuple):
            value = result[0]
        else:
            value = result

        # Record if enabled
        if self._recording:
            import time
            record = AccessRecord(
                is_write=False,
                address=addr,
                size=size,
                value=value,
                sequence=self._sequence,
                timestamp=time.time()
            )
            self._record_access(record)

        return (value, 0) if not isinstance(result, tuple) else result

    def write(self, addr: int, size: int, value: int, secure: bool = False) -> Tuple[int, int]:
        """Write with record/replay support."""
        self.stats['writes'] += 1
        self._sequence += 1

        # Record if enabled
        if self._recording:
            import time
            record = AccessRecord(
                is_write=True,
                address=addr,
                size=size,
                value=value,
                sequence=self._sequence,
                timestamp=time.time()
            )
            self._record_access(record)

        # For replay mode, just acknowledge writes (they don't return data)
        if self._replaying:
            logger.debug(f"Replay write 0x{addr:08X} = 0x{value:08X}")
            return (0, 0)

        # Fall through to actual peripheral
        result = self._peripheral.write(addr, size, value, secure)
        return result if isinstance(result, tuple) else (0, 0)

    def close(self):
        """Close record file if open."""
        if self._record_handle:
            self._record_handle.close()
            self._record_handle = None
            logger.info(f"Closed recording: {self.stats}")

    def get_stats(self) -> dict:
        """Get access statistics."""
        return self.stats.copy()

    def __del__(self):
        self.close()


# Convenience function for quick testing
def create_recorded_flash(base: int = 0x08000000, size: int = 0x100000,
                          record_file: str = "flash_trace.jsonl") -> RecordReplayPeripheral:
    """Create a recorded flash peripheral for testing."""
    from slab_cortex_m.stm32_peripherals import Flash
    flash = Flash("FLASH", base, size)
    return RecordReplayPeripheral(flash, record_file=record_file)


def create_replay_flash(base: int = 0x08000000, size: int = 0x100000,
                        replay_file: str = "flash_trace.jsonl") -> RecordReplayPeripheral:
    """Create a replay-only flash peripheral."""
    return RecordReplayPeripheral.replay_only("FLASH", base, size, replay_file)
