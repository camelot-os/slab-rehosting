"""
MMIO Trace Logger with Register Name Resolution

Captures every peripheral read/write during firmware emulation,
resolving raw addresses to human-readable peripheral and register names.
Useful for:
  - End-to-end testing proof (deterministic trace output)
  - Reverse engineering firmware initialization sequences
  - CI regression testing (trace diffs)

Output formats:
  - Text: Slab MMIO log format (compatible with svd_composer.py)
  - JSON Lines: Compatible with replay_peripheral.py
  - CSV: For spreadsheet analysis

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class MMIOTrace:
    """A single MMIO access record."""
    sequence: int
    timestamp: float          # Relative to tracer start (seconds)
    is_write: bool
    address: int
    size: int
    value: int
    peripheral_name: str      # "SPI1", "GPIOA", "UNMAPPED"
    register_name: str        # "CR1", "REG_0x04"
    bitfields: str = ""       # "SPE|MSTR" or ""
    pc: int = 0               # Program counter (0 = not available)


@dataclass
class SpinLoopInfo:
    """Detected spin loop (repeated register polling)."""
    peripheral: str
    register: str
    address: int
    start_seq: int
    end_seq: int
    count: int                # Number of repeated reads
    value: int                # Last read value


class RegisterNameResolver:
    """
    Resolves peripheral register offsets to human-readable names.

    Uses class introspection to extract register offset constants and
    bit-field definitions from peripheral classes. Works with STM32,
    NRF, and RP2040 peripheral implementations without requiring SVD files.

    Register offsets are class-level uppercase integer constants.
    Bit-fields follow the pattern {REGISTER}_{FIELD} = mask.
    """

    def __init__(self):
        self._offset_cache: Dict[type, Dict[int, str]] = {}
        self._bitfield_cache: Dict[type, Dict[str, List[Tuple[str, int]]]] = {}
        self._size_cache: Dict[type, int] = {}

    def resolve(self, peripheral, offset: int) -> str:
        """Return register name like 'CR1' or 'REG_0x04'."""
        cls = type(peripheral)
        if cls not in self._offset_cache:
            self._build_cache(cls, peripheral)
        return self._offset_cache[cls].get(offset, f"REG_0x{offset:03X}")

    def resolve_bitfields(self, peripheral, reg_name: str, value: int) -> str:
        """Return active bit-fields like 'SPE|MSTR'.

        Only includes single-bit flags that are set in value.
        Multi-bit masks (e.g., BR_MASK) are excluded to avoid noise.
        """
        cls = type(peripheral)
        if cls not in self._bitfield_cache:
            self._build_cache(cls, peripheral)

        fields = self._bitfield_cache[cls].get(reg_name, [])
        active = []
        for field_name, mask in fields:
            # Only include single-bit flags
            if mask & (mask - 1) == 0 and mask != 0:  # Power of 2
                if value & mask:
                    active.append(field_name)
        return '|'.join(active)

    def _build_cache(self, cls, peripheral):
        """Walk MRO and collect register offsets and bit-field constants."""
        offsets: Dict[int, str] = {}
        bitfields: Dict[str, List[Tuple[str, int]]] = {}
        psize = getattr(peripheral, 'size', 0x1000)
        self._size_cache[cls] = psize

        # Collect all uppercase integer attributes from the class hierarchy
        reg_names: Set[str] = set()
        all_attrs: Dict[str, int] = {}

        for klass in cls.__mro__:
            for attr_name, attr_value in vars(klass).items():
                if (attr_name.startswith('_') or not attr_name[0].isupper()
                        or not isinstance(attr_value, int)):
                    continue
                if attr_name in all_attrs:
                    continue  # First in MRO wins
                all_attrs[attr_name] = attr_value

        # Separate register offsets from bit-field masks.
        # Register offsets: within [0, psize) and name is a "root" token
        # (no underscore, or starts with known prefixes like TASKS_, EVENTS_)
        # Bit-fields: name matches REGNAME_FIELDNAME where REGNAME is a register
        #
        # Strategy: first pass collects candidate registers, second pass
        # identifies bit-fields by checking if prefix matches a register.

        nrf_prefixes = ('TASKS_', 'EVENTS_', 'SUBSCRIBE_', 'PUBLISH_')

        # First pass: identify register offsets
        for name, val in all_attrs.items():
            if val < 0 or val >= psize:
                continue
            # Skip names ending in _MASK, _Msk, _Pos (bit-field helpers)
            if name.endswith(('_MASK', '_Msk', '_Pos')):
                continue

            # Is this a register offset or a bit-field?
            # Registers: no underscore, or NRF-style with prefix
            if '_' not in name:
                # Simple register: CR1, SR, DR, SHORTS, INTEN, etc.
                offsets[val] = name
                reg_names.add(name)
            elif any(name.startswith(p) for p in nrf_prefixes):
                # NRF task/event register: TASKS_START, EVENTS_COMPARE, etc.
                offsets[val] = name
                reg_names.add(name)
            elif name.endswith('_BASE'):
                # Array base: TASKS_CAPTURE_BASE, CC_BASE, etc.
                offsets[val] = name
                reg_names.add(name)
            # Otherwise it might be a bit-field -- defer to second pass

        # Second pass: identify bit-fields (PREFIX matches a register name)
        for name, val in all_attrs.items():
            if '_' not in name:
                continue
            # Find the register prefix
            parts = name.split('_', 1)
            if len(parts) != 2:
                continue
            prefix, suffix = parts
            if prefix in reg_names:
                if prefix not in bitfields:
                    bitfields[prefix] = []
                bitfields[prefix].append((suffix, val))

        self._offset_cache[cls] = offsets
        self._bitfield_cache[cls] = bitfields


class MMIOTracer:
    """
    Captures all MMIO accesses with register name resolution.

    Attach to a BasePeripheralServer via server.tracer = MMIOTracer().
    The server's handle_client() loop will call trace_read/trace_write
    after each peripheral access.
    """

    def __init__(self):
        self._traces: List[MMIOTrace] = []
        self._resolver = RegisterNameResolver()
        self._start_time: float = 0.0
        self._sequence: int = 0
        self._started: bool = False

    @property
    def traces(self) -> List[MMIOTrace]:
        """Access collected traces."""
        return self._traces

    @property
    def count(self) -> int:
        """Number of traces collected."""
        return len(self._traces)

    def reset(self):
        """Clear all traces and restart."""
        self._traces.clear()
        self._sequence = 0
        self._started = False

    def trace_read(self, address: int, size: int, value: int,
                   peripheral=None, pc: int = 0):
        """Record a read access."""
        self._record(False, address, size, value, peripheral, pc=pc)

    def trace_write(self, address: int, size: int, value: int,
                    peripheral=None, pc: int = 0):
        """Record a write access."""
        self._record(True, address, size, value, peripheral, pc=pc)

    @staticmethod
    def _resolve_peripheral(peripheral, address: int):
        """Drill through Board/adapter proxies to find actual peripheral.

        Board.find_peripheral() returns the Board itself (for protocol
        compatibility), but we need the underlying STM32/NRF peripheral
        object for register name resolution.
        """
        # Board -> adapter -> find_peripheral
        adapter = getattr(peripheral, 'adapter', None)
        if adapter is not None:
            actual = adapter.find_peripheral(address)
            if actual is not None:
                return actual
        # PeripheralSetAdapter -> find_peripheral
        if hasattr(peripheral, 'find_peripheral') and not hasattr(peripheral, 'adapter'):
            actual = peripheral.find_peripheral(address)
            if actual is not None:
                return actual
        return peripheral

    def _record(self, is_write: bool, address: int, size: int,
                value: int, peripheral, pc: int = 0):
        """Create and store a trace record."""
        if not self._started:
            self._start_time = time.monotonic()
            self._started = True

        ts = time.monotonic() - self._start_time
        self._sequence += 1

        if peripheral is not None:
            # If peripheral is a Board/adapter proxy, drill down to actual peripheral
            actual = self._resolve_peripheral(peripheral, address)
            pname = getattr(actual, 'name', 'UNKNOWN')
            base = getattr(actual, 'base', 0)
            offset = address - base
            reg_name = self._resolver.resolve(actual, offset)
            # Strip compound prefix for bit-field lookup
            bf_key = reg_name.split('_BASE')[0] if reg_name.endswith('_BASE') else reg_name
            bitfields = self._resolver.resolve_bitfields(
                actual, bf_key, value) if is_write else ""
        else:
            pname = "UNMAPPED"
            reg_name = f"0x{address:08X}"
            bitfields = ""

        trace = MMIOTrace(
            sequence=self._sequence,
            timestamp=round(ts, 6),
            is_write=is_write,
            address=address,
            size=size,
            value=value,
            peripheral_name=pname,
            register_name=reg_name,
            bitfields=bitfields,
            pc=pc,
        )
        self._traces.append(trace)

    # -------------------------------------------------------------------------
    # Export formats
    # -------------------------------------------------------------------------

    def export_text(self, path: str):
        """Export in Slab MMIO log format (compatible with svd_composer.py).

        Format: [seq] R/W 0xADDR size 0xVALUE  PERIPH->REG [bitfields] @PC
        """
        with open(path, 'w') as f:
            for t in self._traces:
                rw = 'W' if t.is_write else 'R'
                bf = f"  [{t.bitfields}]" if t.bitfields else ""
                pc = f"  @0x{t.pc:08X}" if t.pc else ""
                f.write(
                    f"{t.sequence:08d} {rw} 0x{t.address:08X} {t.size} "
                    f"0x{t.value:08X}  {t.peripheral_name}->{t.register_name}"
                    f"{bf}{pc}\n"
                )

    def export_json(self, path: str):
        """Export as JSON Lines (compatible with replay_peripheral.py)."""
        with open(path, 'w') as f:
            for t in self._traces:
                record = {
                    'seq': t.sequence,
                    'ts': t.timestamp,
                    'rw': 'W' if t.is_write else 'R',
                    'addr': f"0x{t.address:08X}",
                    'size': t.size,
                    'value': f"0x{t.value:08X}",
                    'periph': t.peripheral_name,
                    'reg': t.register_name,
                }
                if t.bitfields:
                    record['bits'] = t.bitfields
                if t.pc:
                    record['pc'] = f"0x{t.pc:08X}"
                f.write(json.dumps(record) + '\n')

    def export_csv(self, path: str):
        """Export as CSV for spreadsheet analysis."""
        with open(path, 'w') as f:
            f.write("sequence,timestamp,rw,address,size,value,"
                    "peripheral,register,bitfields,pc\n")
            for t in self._traces:
                rw = 'W' if t.is_write else 'R'
                pc = f"0x{t.pc:08X}" if t.pc else ""
                f.write(
                    f"{t.sequence},{t.timestamp:.6f},{rw},"
                    f"0x{t.address:08X},{t.size},0x{t.value:08X},"
                    f"{t.peripheral_name},{t.register_name},"
                    f"{t.bitfields},{pc}\n"
                )

    # -------------------------------------------------------------------------
    # Analysis helpers
    # -------------------------------------------------------------------------

    def get_init_sequence(self, max_unique_writes: int = 200) -> List[MMIOTrace]:
        """Extract peripheral initialization phase.

        Returns traces up to the point where the firmware starts
        repeating register patterns (i.e., enters its main loop).
        Heuristic: stop after seeing max_unique_writes unique
        (peripheral, register, value) write combinations.
        """
        seen = set()
        result = []
        repeat_count = 0

        for t in self._traces:
            if t.is_write:
                key = (t.peripheral_name, t.register_name, t.value)
                if key in seen:
                    repeat_count += 1
                    if repeat_count > 10:
                        break
                else:
                    seen.add(key)
                    repeat_count = 0

            result.append(t)
            if len(seen) >= max_unique_writes:
                break

        return result

    def get_peripheral_summary(self) -> Dict[str, Dict[str, int]]:
        """Per-peripheral read/write counts and most-accessed registers.

        Returns: {
            "SPI1": {"reads": 42, "writes": 18, "top_reg": "DR"},
            ...
        }
        """
        summary: Dict[str, Dict[str, int]] = {}
        reg_counts: Dict[str, Dict[str, int]] = {}

        for t in self._traces:
            pname = t.peripheral_name
            if pname not in summary:
                summary[pname] = {'reads': 0, 'writes': 0, 'top_reg': ''}
                reg_counts[pname] = {}

            if t.is_write:
                summary[pname]['writes'] += 1
            else:
                summary[pname]['reads'] += 1

            reg_counts[pname][t.register_name] = (
                reg_counts[pname].get(t.register_name, 0) + 1)

        # Find top register per peripheral
        for pname in summary:
            if reg_counts[pname]:
                top = max(reg_counts[pname], key=reg_counts[pname].get)
                summary[pname]['top_reg'] = top

        return summary

    def get_register_access_table(self) -> List[Dict]:
        """Generate a table of unique register accesses with counts.

        Returns list of dicts with: peripheral, register, reads, writes,
        last_value.
        """
        table: Dict[str, Dict] = {}

        for t in self._traces:
            key = f"{t.peripheral_name}.{t.register_name}"
            if key not in table:
                table[key] = {
                    'peripheral': t.peripheral_name,
                    'register': t.register_name,
                    'reads': 0,
                    'writes': 0,
                    'last_value': 0,
                }
            if t.is_write:
                table[key]['writes'] += 1
            else:
                table[key]['reads'] += 1
            table[key]['last_value'] = t.value

        return sorted(table.values(),
                      key=lambda r: (r['peripheral'], r['register']))

    def detect_spin_loops(self, min_repeats: int = 5) -> List[SpinLoopInfo]:
        """Detect spin loops: firmware polling a register repeatedly.

        Identifies consecutive reads from the same address returning
        the same value (typical of busy-wait loops on status registers).
        Useful for detecting stuck peripheral initialization.

        Args:
            min_repeats: Minimum consecutive identical reads to flag.

        Returns:
            List of SpinLoopInfo for each detected spin loop.
        """
        loops = []
        if not self._traces:
            return loops

        run_start = 0
        run_count = 1
        prev = self._traces[0]

        for i in range(1, len(self._traces)):
            t = self._traces[i]
            # Same address, same value, both reads
            if (not t.is_write and not prev.is_write
                    and t.address == prev.address
                    and t.value == prev.value):
                run_count += 1
            else:
                if run_count >= min_repeats:
                    p = self._traces[run_start]
                    loops.append(SpinLoopInfo(
                        peripheral=p.peripheral_name,
                        register=p.register_name,
                        address=p.address,
                        start_seq=p.sequence,
                        end_seq=self._traces[i - 1].sequence,
                        count=run_count,
                        value=p.value,
                    ))
                run_start = i
                run_count = 1
            prev = t

        # Check final run
        if run_count >= min_repeats:
            p = self._traces[run_start]
            loops.append(SpinLoopInfo(
                peripheral=p.peripheral_name,
                register=p.register_name,
                address=p.address,
                start_seq=p.sequence,
                end_seq=self._traces[-1].sequence,
                count=run_count,
                value=p.value,
            ))

        return loops
