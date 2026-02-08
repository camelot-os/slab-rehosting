#!/usr/bin/env python3
"""
SVD Composer - Create Custom Device SVDs

A tool for creating new SVD files by:
1. Parsing SVD files from a directory
2. Picking peripherals from different devices
3. Combining them into a new custom device SVD
4. Generating SVDs from MMIO access logs

This enables:
- Custom device configurations for emulation
- Reverse engineering unknown devices from MMIO logs
- Building composite devices for security testing
- Creating minimal SVDs with only needed peripherals

Usage:
    # CLI usage
    python -m slab_peripherals.svd_composer scan /path/to/svd/files
    python -m slab_peripherals.svd_composer compose --output custom.svd
    python -m slab_peripherals.svd_composer from-log mmio.log --output inferred.svd

    # Python API
    from slab_peripherals.svd_composer import SVDComposer
    composer = SVDComposer()
    composer.scan_directory('/path/to/svd/files')
    composer.add_peripheral('STM32F405', 'GPIOA')
    composer.add_peripheral('STM32F407', 'USB_OTG_FS')
    composer.save('custom_device.svd')

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0 AND Apache-2.0
"""

import xml.etree.ElementTree as ET
from xml.dom import minidom
import os
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Tuple, Iterator, Set
from pathlib import Path
from collections import defaultdict
import argparse

logger = logging.getLogger(__name__)


# =============================================================================
# SVD Data Structures (simplified, self-contained)
# =============================================================================

@dataclass
class SVDField:
    """Register field definition."""
    name: str
    description: str = ""
    bit_offset: int = 0
    bit_width: int = 1
    access: str = "read-write"
    enumerated_values: Dict[str, int] = field(default_factory=dict)

    @property
    def bit_mask(self) -> int:
        return ((1 << self.bit_width) - 1) << self.bit_offset

    def to_xml(self, parent: ET.Element) -> ET.Element:
        """Convert to XML element."""
        elem = ET.SubElement(parent, "field")
        ET.SubElement(elem, "name").text = self.name
        if self.description:
            ET.SubElement(elem, "description").text = self.description
        ET.SubElement(elem, "bitOffset").text = str(self.bit_offset)
        ET.SubElement(elem, "bitWidth").text = str(self.bit_width)
        if self.access != "read-write":
            ET.SubElement(elem, "access").text = self.access
        return elem


@dataclass
class SVDRegister:
    """Register definition."""
    name: str
    description: str = ""
    address_offset: int = 0
    size: int = 32
    access: str = "read-write"
    reset_value: int = 0
    reset_mask: int = 0xFFFFFFFF
    fields: List[SVDField] = field(default_factory=list)
    dim: int = 0
    dim_increment: int = 0
    dim_index: str = ""

    def to_xml(self, parent: ET.Element) -> ET.Element:
        """Convert to XML element."""
        elem = ET.SubElement(parent, "register")
        ET.SubElement(elem, "name").text = self.name
        if self.description:
            ET.SubElement(elem, "description").text = self.description
        ET.SubElement(elem, "addressOffset").text = f"0x{self.address_offset:X}"
        ET.SubElement(elem, "size").text = str(self.size)
        ET.SubElement(elem, "access").text = self.access
        ET.SubElement(elem, "resetValue").text = f"0x{self.reset_value:08X}"

        if self.dim > 0:
            ET.SubElement(elem, "dim").text = str(self.dim)
            ET.SubElement(elem, "dimIncrement").text = f"0x{self.dim_increment:X}"
            if self.dim_index:
                ET.SubElement(elem, "dimIndex").text = self.dim_index

        if self.fields:
            fields_elem = ET.SubElement(elem, "fields")
            for f in self.fields:
                f.to_xml(fields_elem)

        return elem


@dataclass
class SVDInterrupt:
    """Interrupt definition."""
    name: str
    description: str = ""
    value: int = 0

    def to_xml(self, parent: ET.Element) -> ET.Element:
        """Convert to XML element."""
        elem = ET.SubElement(parent, "interrupt")
        ET.SubElement(elem, "name").text = self.name
        if self.description:
            ET.SubElement(elem, "description").text = self.description
        ET.SubElement(elem, "value").text = str(self.value)
        return elem


@dataclass
class SVDPeripheral:
    """Peripheral definition."""
    name: str
    description: str = ""
    base_address: int = 0
    size: int = 0x400
    group_name: str = ""
    registers: List[SVDRegister] = field(default_factory=list)
    interrupts: List[SVDInterrupt] = field(default_factory=list)
    derived_from: Optional[str] = None
    # Metadata for tracking origin
    source_device: str = ""
    source_file: str = ""

    def to_xml(self, parent: ET.Element) -> ET.Element:
        """Convert to XML element."""
        elem = ET.SubElement(parent, "peripheral")
        if self.derived_from:
            elem.set("derivedFrom", self.derived_from)

        ET.SubElement(elem, "name").text = self.name
        if self.description:
            ET.SubElement(elem, "description").text = self.description
        if self.group_name:
            ET.SubElement(elem, "groupName").text = self.group_name
        ET.SubElement(elem, "baseAddress").text = f"0x{self.base_address:08X}"

        # Address block
        addr_block = ET.SubElement(elem, "addressBlock")
        ET.SubElement(addr_block, "offset").text = "0x0"
        ET.SubElement(addr_block, "size").text = f"0x{self.size:X}"
        ET.SubElement(addr_block, "usage").text = "registers"

        # Interrupts
        for irq in self.interrupts:
            irq.to_xml(elem)

        # Registers (only if not derived)
        if self.registers and not self.derived_from:
            regs_elem = ET.SubElement(elem, "registers")
            for reg in self.registers:
                reg.to_xml(regs_elem)

        return elem


@dataclass
class SVDDevice:
    """Device definition."""
    name: str = "CustomDevice"
    version: str = "1.0"
    description: str = "Custom device created with SVD Composer"
    vendor: str = "Twisted Wires"
    vendor_id: str = "TW"
    series: str = ""
    license_text: str = "SPDX-License-Identifier: Apache-2.0"
    cpu_name: str = "CM4"
    cpu_revision: str = "r0p1"
    cpu_endian: str = "little"
    cpu_mpu_present: bool = True
    cpu_fpu_present: bool = True
    cpu_nvic_prio_bits: int = 4
    address_unit_bits: int = 8
    width: int = 32
    peripherals: List[SVDPeripheral] = field(default_factory=list)

    def get_peripheral(self, name: str) -> Optional[SVDPeripheral]:
        """Get peripheral by name."""
        for p in self.peripherals:
            if p.name == name:
                return p
        return None

    def to_xml(self) -> ET.Element:
        """Convert to XML element."""
        root = ET.Element("device")
        root.set("schemaVersion", "1.3")
        root.set("xmlns:xs", "http://www.w3.org/2001/XMLSchema-instance")

        ET.SubElement(root, "vendor").text = self.vendor
        ET.SubElement(root, "vendorID").text = self.vendor_id
        ET.SubElement(root, "name").text = self.name
        if self.series:
            ET.SubElement(root, "series").text = self.series
        ET.SubElement(root, "version").text = self.version
        ET.SubElement(root, "description").text = self.description
        if self.license_text:
            ET.SubElement(root, "licenseText").text = self.license_text

        # CPU element
        cpu = ET.SubElement(root, "cpu")
        ET.SubElement(cpu, "name").text = self.cpu_name
        ET.SubElement(cpu, "revision").text = self.cpu_revision
        ET.SubElement(cpu, "endian").text = self.cpu_endian
        ET.SubElement(cpu, "mpuPresent").text = str(self.cpu_mpu_present).lower()
        ET.SubElement(cpu, "fpuPresent").text = str(self.cpu_fpu_present).lower()
        ET.SubElement(cpu, "nvicPrioBits").text = str(self.cpu_nvic_prio_bits)
        ET.SubElement(cpu, "vendorSystickConfig").text = "false"

        ET.SubElement(root, "addressUnitBits").text = str(self.address_unit_bits)
        ET.SubElement(root, "width").text = str(self.width)

        # Peripherals
        if self.peripherals:
            periphs = ET.SubElement(root, "peripherals")
            for p in self.peripherals:
                p.to_xml(periphs)

        return root

    def to_svd(self, pretty: bool = True) -> str:
        """Convert to SVD XML string."""
        root = self.to_xml()
        if pretty:
            xml_str = ET.tostring(root, encoding='unicode')
            dom = minidom.parseString(xml_str)
            return dom.toprettyxml(indent="  ")
        return ET.tostring(root, encoding='unicode')


# =============================================================================
# SVD Parser (Minimal, Self-contained)
# =============================================================================

class SVDParser:
    """Parse SVD XML files."""

    def parse(self, path: str) -> SVDDevice:
        """Parse an SVD file and return device definition."""
        tree = ET.parse(path)
        root = tree.getroot()

        device = SVDDevice(
            name=self._get_text(root, "name", "Unknown"),
            version=self._get_text(root, "version", "1.0"),
            description=self._get_text(root, "description", ""),
            vendor=self._get_text(root, "vendor", ""),
            vendor_id=self._get_text(root, "vendorID", ""),
            series=self._get_text(root, "series", ""),
        )

        # Parse CPU info
        cpu_elem = root.find("cpu")
        if cpu_elem is not None:
            device.cpu_name = self._get_text(cpu_elem, "name", "CM4")
            device.cpu_revision = self._get_text(cpu_elem, "revision", "r0p1")
            device.cpu_endian = self._get_text(cpu_elem, "endian", "little")
            device.cpu_mpu_present = self._get_text(cpu_elem, "mpuPresent", "false") == "true"
            device.cpu_fpu_present = self._get_text(cpu_elem, "fpuPresent", "false") == "true"
            device.cpu_nvic_prio_bits = int(self._get_text(cpu_elem, "nvicPrioBits", "4"))

        # Parse peripherals
        peripherals_elem = root.find("peripherals")
        if peripherals_elem is not None:
            peripheral_dict = {}  # For derivation lookup

            for p_elem in peripherals_elem.findall("peripheral"):
                peripheral = self._parse_peripheral(p_elem, path)

                # Handle derivation
                derived_from = p_elem.get("derivedFrom")
                if derived_from and derived_from in peripheral_dict:
                    base = peripheral_dict[derived_from]
                    if not peripheral.registers:
                        peripheral.registers = base.registers.copy()
                    if not peripheral.interrupts:
                        peripheral.interrupts = base.interrupts.copy()
                    if not peripheral.group_name:
                        peripheral.group_name = base.group_name

                peripheral_dict[peripheral.name] = peripheral
                device.peripherals.append(peripheral)

        return device

    def _parse_peripheral(self, elem: ET.Element, source_file: str) -> SVDPeripheral:
        """Parse peripheral element."""
        peripheral = SVDPeripheral(
            name=self._get_text(elem, "name", "Unknown"),
            description=self._get_text(elem, "description", ""),
            base_address=self._parse_int(self._get_text(elem, "baseAddress", "0")),
            group_name=self._get_text(elem, "groupName", ""),
            derived_from=elem.get("derivedFrom"),
            source_file=source_file,
        )

        # Parse address block for size
        addr_block = elem.find("addressBlock")
        if addr_block is not None:
            peripheral.size = self._parse_int(self._get_text(addr_block, "size", "0x400"))

        # Parse interrupts
        for irq_elem in elem.findall("interrupt"):
            peripheral.interrupts.append(SVDInterrupt(
                name=self._get_text(irq_elem, "name", ""),
                description=self._get_text(irq_elem, "description", ""),
                value=int(self._get_text(irq_elem, "value", "0")),
            ))

        # Parse registers
        regs_elem = elem.find("registers")
        if regs_elem is not None:
            for reg_elem in regs_elem.findall("register"):
                peripheral.registers.append(self._parse_register(reg_elem))

            # Also handle clusters
            for cluster_elem in regs_elem.findall("cluster"):
                peripheral.registers.extend(self._parse_cluster(cluster_elem))

        return peripheral

    def _parse_register(self, elem: ET.Element) -> SVDRegister:
        """Parse register element."""
        reg = SVDRegister(
            name=self._get_text(elem, "name", "Unknown"),
            description=self._get_text(elem, "description", ""),
            address_offset=self._parse_int(self._get_text(elem, "addressOffset", "0")),
            size=self._parse_int(self._get_text(elem, "size", "32")),
            access=self._get_text(elem, "access", "read-write"),
            reset_value=self._parse_int(self._get_text(elem, "resetValue", "0")),
            reset_mask=self._parse_int(self._get_text(elem, "resetMask", "0xFFFFFFFF")),
        )

        # Array/dim support
        dim_text = self._get_text(elem, "dim", "")
        if dim_text:
            reg.dim = self._parse_int(dim_text)
            reg.dim_increment = self._parse_int(self._get_text(elem, "dimIncrement", "4"))
            reg.dim_index = self._get_text(elem, "dimIndex", "")

        # Parse fields
        fields_elem = elem.find("fields")
        if fields_elem is not None:
            for field_elem in fields_elem.findall("field"):
                reg.fields.append(self._parse_field(field_elem))

        return reg

    def _parse_cluster(self, elem: ET.Element, base_offset: int = 0) -> List[SVDRegister]:
        """Parse cluster element (group of registers)."""
        registers = []
        cluster_offset = self._parse_int(self._get_text(elem, "addressOffset", "0"))

        for reg_elem in elem.findall("register"):
            reg = self._parse_register(reg_elem)
            reg.address_offset += cluster_offset + base_offset
            registers.append(reg)

        return registers

    def _parse_field(self, elem: ET.Element) -> SVDField:
        """Parse field element."""
        # Handle bitRange format [MSB:LSB]
        bit_range = self._get_text(elem, "bitRange", "")
        if bit_range:
            match = re.match(r'\[(\d+):(\d+)\]', bit_range)
            if match:
                msb, lsb = int(match.group(1)), int(match.group(2))
                bit_offset = lsb
                bit_width = msb - lsb + 1
            else:
                bit_offset = 0
                bit_width = 1
        else:
            bit_offset = int(self._get_text(elem, "bitOffset", "0"))
            bit_width = int(self._get_text(elem, "bitWidth", "1"))

        field = SVDField(
            name=self._get_text(elem, "name", "Unknown"),
            description=self._get_text(elem, "description", ""),
            bit_offset=bit_offset,
            bit_width=bit_width,
            access=self._get_text(elem, "access", "read-write"),
        )

        # Parse enumerated values
        enum_elem = elem.find("enumeratedValues")
        if enum_elem is not None:
            for ev in enum_elem.findall("enumeratedValue"):
                name = self._get_text(ev, "name", "")
                value = self._parse_int(self._get_text(ev, "value", "0"))
                if name:
                    field.enumerated_values[name] = value

        return field

    def _get_text(self, elem: ET.Element, tag: str, default: str = "") -> str:
        """Get text content of child element."""
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return default

    def _parse_int(self, value: str) -> int:
        """Parse integer from string (hex or decimal)."""
        value = value.strip().lower()
        if not value:
            return 0
        if value.startswith("0x") or value.startswith("#"):
            return int(value.replace("#", "0x"), 16)
        return int(value)


# =============================================================================
# MMIO Log Parser - Infer SVD from Access Patterns
# =============================================================================

@dataclass
class MMIOAccess:
    """Single MMIO access record."""
    address: int
    size: int  # 1, 2, or 4 bytes
    access_type: str  # 'read' or 'write'
    value: int
    pc: int = 0
    cycle: int = 0


@dataclass
class InferredRegister:
    """Register inferred from MMIO accesses."""
    offset: int
    size: int = 32
    read_count: int = 0
    write_count: int = 0
    values_seen: Set[int] = field(default_factory=set)
    pcs_seen: Set[int] = field(default_factory=set)

    @property
    def access_type(self) -> str:
        if self.read_count > 0 and self.write_count > 0:
            return "read-write"
        elif self.read_count > 0:
            return "read-only"
        elif self.write_count > 0:
            return "write-only"
        return "read-write"

    @property
    def likely_name(self) -> str:
        """Generate likely register name from offset."""
        return f"REG_{self.offset:03X}"


class MMIOLogParser:
    """
    Parse MMIO access logs and infer peripheral structure.

    Supports multiple log formats:
    - Slab emulator MMIO trace format
    - QEMU mtrace format
    - Custom JSON/CSV formats
    """

    def __init__(self):
        self.accesses: List[MMIOAccess] = []
        self.inferred_peripherals: Dict[int, Dict[int, InferredRegister]] = defaultdict(dict)

    def parse_log(self, path: str, format: str = "auto") -> int:
        """
        Parse MMIO log file.

        Args:
            path: Path to log file
            format: Log format ('auto', 'slab', 'qemu', 'json', 'csv')

        Returns:
            Number of accesses parsed
        """
        if format == "auto":
            format = self._detect_format(path)

        if format == "json":
            return self._parse_json(path)
        elif format == "csv":
            return self._parse_csv(path)
        elif format == "qemu":
            return self._parse_qemu(path)
        else:  # slab or default
            return self._parse_slab(path)

    def _detect_format(self, path: str) -> str:
        """Detect log format from file content."""
        with open(path, 'r') as f:
            first_line = f.readline().strip()

        if first_line.startswith('{') or first_line.startswith('['):
            return "json"
        elif ',' in first_line and ('address' in first_line.lower() or 'read' in first_line.lower()):
            return "csv"
        elif 'mtrace' in first_line.lower():
            return "qemu"
        return "slab"

    def _parse_slab(self, path: str) -> int:
        """
        Parse Slab emulator MMIO trace format.

        Format: [cycle] R/W addr size value [pc]
        Example: 1234 W 0x40020000 4 0x00000001 0x08001234
        """
        count = 0
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.split()
                if len(parts) < 5:
                    continue

                try:
                    cycle = int(parts[0])
                    access_type = 'write' if parts[1].upper() == 'W' else 'read'
                    address = int(parts[2], 0)
                    size = int(parts[3])
                    value = int(parts[4], 0)
                    pc = int(parts[5], 0) if len(parts) > 5 else 0

                    self.accesses.append(MMIOAccess(
                        address=address,
                        size=size,
                        access_type=access_type,
                        value=value,
                        pc=pc,
                        cycle=cycle,
                    ))
                    count += 1
                except (ValueError, IndexError):
                    continue

        return count

    def _parse_json(self, path: str) -> int:
        """Parse JSON format log."""
        with open(path, 'r') as f:
            data = json.load(f)

        if isinstance(data, dict) and 'accesses' in data:
            data = data['accesses']

        count = 0
        for entry in data:
            try:
                self.accesses.append(MMIOAccess(
                    address=entry.get('address', entry.get('addr', 0)),
                    size=entry.get('size', 4),
                    access_type=entry.get('type', entry.get('access_type', 'read')),
                    value=entry.get('value', entry.get('data', 0)),
                    pc=entry.get('pc', 0),
                    cycle=entry.get('cycle', entry.get('timestamp', 0)),
                ))
                count += 1
            except (KeyError, TypeError):
                continue

        return count

    def _parse_csv(self, path: str) -> int:
        """Parse CSV format log."""
        import csv
        count = 0

        with open(path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    self.accesses.append(MMIOAccess(
                        address=int(row.get('address', row.get('addr', '0')), 0),
                        size=int(row.get('size', '4')),
                        access_type=row.get('type', row.get('access', 'read')),
                        value=int(row.get('value', row.get('data', '0')), 0),
                        pc=int(row.get('pc', '0'), 0),
                        cycle=int(row.get('cycle', row.get('timestamp', '0'))),
                    ))
                    count += 1
                except (ValueError, KeyError):
                    continue

        return count

    def _parse_qemu(self, path: str) -> int:
        """Parse QEMU mtrace format."""
        count = 0
        # QEMU mtrace: cpu_physical_memory_rw: 0x40020000 <- 0x00000001 (4)
        pattern = re.compile(
            r'(read|write|rw).*?'
            r'(0x[0-9a-fA-F]+)\s*'
            r'(<-|->)\s*'
            r'(0x[0-9a-fA-F]+)\s*'
            r'\((\d+)\)'
        )

        with open(path, 'r') as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    access_type = 'write' if '<-' in match.group(3) else 'read'
                    self.accesses.append(MMIOAccess(
                        address=int(match.group(2), 16),
                        size=int(match.group(5)),
                        access_type=access_type,
                        value=int(match.group(4), 16),
                    ))
                    count += 1

        return count

    def analyze(self, peripheral_alignment: int = 0x400) -> Dict[int, Dict[int, InferredRegister]]:
        """
        Analyze accesses and infer peripheral/register structure.

        Args:
            peripheral_alignment: Assumed peripheral base alignment

        Returns:
            Dict mapping peripheral base -> register offset -> InferredRegister
        """
        self.inferred_peripherals.clear()

        for access in self.accesses:
            # Determine peripheral base (aligned)
            base = (access.address // peripheral_alignment) * peripheral_alignment
            offset = access.address - base

            if offset not in self.inferred_peripherals[base]:
                self.inferred_peripherals[base][offset] = InferredRegister(
                    offset=offset,
                    size=access.size * 8,
                )

            reg = self.inferred_peripherals[base][offset]
            if access.access_type == 'read':
                reg.read_count += 1
            else:
                reg.write_count += 1
            reg.values_seen.add(access.value)
            if access.pc:
                reg.pcs_seen.add(access.pc)

        return self.inferred_peripherals

    def generate_svd_peripheral(
        self,
        base_address: int,
        name: Optional[str] = None
    ) -> SVDPeripheral:
        """Generate SVD peripheral from inferred registers."""
        if base_address not in self.inferred_peripherals:
            self.analyze()

        regs = self.inferred_peripherals.get(base_address, {})
        if not name:
            name = f"PERIPH_{base_address:08X}"

        peripheral = SVDPeripheral(
            name=name,
            description=f"Peripheral inferred from MMIO log at 0x{base_address:08X}",
            base_address=base_address,
            size=max((r.offset + 4 for r in regs.values()), default=0x100),
        )

        for offset, inferred in sorted(regs.items()):
            reg = SVDRegister(
                name=inferred.likely_name,
                description=f"Inferred from {inferred.read_count}R/{inferred.write_count}W accesses",
                address_offset=offset,
                size=inferred.size if inferred.size in [8, 16, 32] else 32,
                access=inferred.access_type,
            )

            # Try to infer fields from value patterns
            if len(inferred.values_seen) > 1:
                # Identify likely bit fields
                all_values = list(inferred.values_seen)
                bit_activity = 0
                for v in all_values:
                    bit_activity |= v

                # Create fields for active bit ranges
                current_field_start = None
                for bit in range(32):
                    bit_active = (bit_activity >> bit) & 1
                    if bit_active and current_field_start is None:
                        current_field_start = bit
                    elif not bit_active and current_field_start is not None:
                        width = bit - current_field_start
                        if width > 0:
                            reg.fields.append(SVDField(
                                name=f"FIELD_{current_field_start}",
                                bit_offset=current_field_start,
                                bit_width=width,
                            ))
                        current_field_start = None

                if current_field_start is not None:
                    reg.fields.append(SVDField(
                        name=f"FIELD_{current_field_start}",
                        bit_offset=current_field_start,
                        bit_width=32 - current_field_start,
                    ))

            peripheral.registers.append(reg)

        return peripheral


# =============================================================================
# SVD Composer - Main Tool
# =============================================================================

@dataclass
class PeripheralEntry:
    """Entry in peripheral catalog."""
    name: str
    device_name: str
    device_file: str
    base_address: int
    group_name: str
    description: str
    register_count: int
    interrupt_count: int


class SVDComposer:
    """
    Create custom SVD files by combining peripherals from multiple sources.

    Usage:
        composer = SVDComposer()
        composer.scan_directory('/path/to/svd/files')
        composer.list_devices()
        composer.list_peripherals('STM32F405')
        composer.add_peripheral('STM32F405', 'GPIOA')
        composer.add_peripheral('STM32F407', 'USB_OTG_FS', new_base=0x50000000)
        composer.save('custom_device.svd')
    """

    def __init__(self):
        self.parser = SVDParser()
        self.mmio_parser = MMIOLogParser()

        # Catalog of all parsed devices and peripherals
        self.devices: Dict[str, SVDDevice] = {}
        self.peripheral_catalog: Dict[str, List[PeripheralEntry]] = defaultdict(list)

        # The device being composed
        self.target_device = SVDDevice()
        self._used_names: Set[str] = set()
        self._used_addresses: Set[int] = set()

    def scan_directory(
        self,
        path: str,
        recursive: bool = True,
        pattern: str = "*.svd"
    ) -> int:
        """
        Scan directory for SVD files and build peripheral catalog.

        Args:
            path: Directory path
            recursive: Scan subdirectories
            pattern: File pattern to match

        Returns:
            Number of devices parsed
        """
        import glob

        if recursive:
            search_pattern = os.path.join(path, "**", pattern)
            files = glob.glob(search_pattern, recursive=True)
        else:
            search_pattern = os.path.join(path, pattern)
            files = glob.glob(search_pattern)

        count = 0
        for svd_file in files:
            try:
                device = self.parser.parse(svd_file)
                device_key = device.name or Path(svd_file).stem

                # Store device
                self.devices[device_key] = device

                # Build peripheral catalog
                for peripheral in device.peripherals:
                    entry = PeripheralEntry(
                        name=peripheral.name,
                        device_name=device_key,
                        device_file=svd_file,
                        base_address=peripheral.base_address,
                        group_name=peripheral.group_name,
                        description=peripheral.description[:100] if peripheral.description else "",
                        register_count=len(peripheral.registers),
                        interrupt_count=len(peripheral.interrupts),
                    )
                    self.peripheral_catalog[device_key].append(entry)

                count += 1
                logger.info(f"Parsed {device_key}: {len(device.peripherals)} peripherals")

            except Exception as e:
                logger.warning(f"Failed to parse {svd_file}: {e}")

        return count

    def scan_file(self, path: str) -> str:
        """
        Scan single SVD file.

        Returns:
            Device name/key
        """
        device = self.parser.parse(path)
        device_key = device.name or Path(path).stem

        self.devices[device_key] = device

        for peripheral in device.peripherals:
            entry = PeripheralEntry(
                name=peripheral.name,
                device_name=device_key,
                device_file=path,
                base_address=peripheral.base_address,
                group_name=peripheral.group_name,
                description=peripheral.description[:100] if peripheral.description else "",
                register_count=len(peripheral.registers),
                interrupt_count=len(peripheral.interrupts),
            )
            self.peripheral_catalog[device_key].append(entry)

        return device_key

    def list_devices(self) -> List[str]:
        """List all parsed devices."""
        return list(self.devices.keys())

    def list_peripherals(
        self,
        device: Optional[str] = None,
        group: Optional[str] = None
    ) -> List[PeripheralEntry]:
        """
        List peripherals, optionally filtered by device or group.

        Args:
            device: Filter by device name
            group: Filter by group name (e.g., 'GPIO', 'USART')

        Returns:
            List of peripheral entries
        """
        results = []

        devices_to_check = [device] if device else self.peripheral_catalog.keys()

        for dev_name in devices_to_check:
            for entry in self.peripheral_catalog.get(dev_name, []):
                if group and group.lower() not in entry.group_name.lower():
                    continue
                results.append(entry)

        return results

    def search_peripherals(self, query: str) -> List[PeripheralEntry]:
        """
        Search peripherals by name, group, or description.

        Args:
            query: Search string (case-insensitive)

        Returns:
            Matching peripheral entries
        """
        query = query.lower()
        results = []

        for entries in self.peripheral_catalog.values():
            for entry in entries:
                if (query in entry.name.lower() or
                    query in entry.group_name.lower() or
                    query in entry.description.lower()):
                    results.append(entry)

        return results

    def add_peripheral(
        self,
        device: str,
        peripheral_name: str,
        new_name: Optional[str] = None,
        new_base: Optional[int] = None,
        derive_from: Optional[str] = None
    ) -> bool:
        """
        Add peripheral from source device to target.

        Args:
            device: Source device name
            peripheral_name: Peripheral name in source
            new_name: New name in target (optional)
            new_base: New base address (optional)
            derive_from: Derive from existing peripheral in target

        Returns:
            True if added successfully
        """
        if device not in self.devices:
            logger.error(f"Device '{device}' not found")
            return False

        source_device = self.devices[device]
        source_peripheral = source_device.get_peripheral(peripheral_name)

        if not source_peripheral:
            logger.error(f"Peripheral '{peripheral_name}' not found in {device}")
            return False

        # Create copy for target
        target_name = new_name or peripheral_name
        target_base = new_base if new_base is not None else source_peripheral.base_address

        # Check for conflicts
        if target_name in self._used_names:
            logger.error(f"Peripheral name '{target_name}' already used")
            return False

        if target_base in self._used_addresses:
            logger.warning(f"Base address 0x{target_base:08X} already used")

        # Create new peripheral
        new_peripheral = SVDPeripheral(
            name=target_name,
            description=source_peripheral.description,
            base_address=target_base,
            size=source_peripheral.size,
            group_name=source_peripheral.group_name,
            registers=source_peripheral.registers.copy() if not derive_from else [],
            interrupts=source_peripheral.interrupts.copy(),
            derived_from=derive_from,
            source_device=device,
            source_file=self.devices[device].name,
        )

        self.target_device.peripherals.append(new_peripheral)
        self._used_names.add(target_name)
        self._used_addresses.add(target_base)

        logger.info(f"Added {target_name} from {device} at 0x{target_base:08X}")
        return True

    def add_peripheral_group(
        self,
        device: str,
        group: str,
        base_offset: int = 0
    ) -> int:
        """
        Add all peripherals from a group (e.g., all GPIOs).

        Args:
            device: Source device name
            group: Group name (e.g., 'GPIO')
            base_offset: Offset to add to all base addresses

        Returns:
            Number of peripherals added
        """
        if device not in self.devices:
            logger.error(f"Device '{device}' not found")
            return 0

        count = 0
        for peripheral in self.devices[device].peripherals:
            if group.lower() in peripheral.group_name.lower():
                new_base = peripheral.base_address + base_offset if base_offset else None
                if self.add_peripheral(device, peripheral.name, new_base=new_base):
                    count += 1

        return count

    def add_from_mmio_log(
        self,
        log_path: str,
        peripheral_alignment: int = 0x400,
        name_prefix: str = "INFERRED"
    ) -> int:
        """
        Add peripherals inferred from MMIO access log.

        Args:
            log_path: Path to MMIO log file
            peripheral_alignment: Peripheral base alignment
            name_prefix: Prefix for generated peripheral names

        Returns:
            Number of peripherals added
        """
        self.mmio_parser.parse_log(log_path)
        self.mmio_parser.analyze(peripheral_alignment)

        count = 0
        for base_address in sorted(self.mmio_parser.inferred_peripherals.keys()):
            name = f"{name_prefix}_{base_address:08X}"
            peripheral = self.mmio_parser.generate_svd_peripheral(base_address, name)

            if len(peripheral.registers) > 0:
                self.target_device.peripherals.append(peripheral)
                self._used_names.add(name)
                self._used_addresses.add(base_address)
                count += 1
                logger.info(f"Added inferred peripheral {name} with {len(peripheral.registers)} registers")

        return count

    def set_device_info(
        self,
        name: str = None,
        vendor: str = None,
        description: str = None,
        cpu_name: str = None,
        **kwargs
    ):
        """Set target device metadata."""
        if name:
            self.target_device.name = name
        if vendor:
            self.target_device.vendor = vendor
        if description:
            self.target_device.description = description
        if cpu_name:
            self.target_device.cpu_name = cpu_name

        for key, value in kwargs.items():
            if hasattr(self.target_device, key):
                setattr(self.target_device, key, value)

    def remove_peripheral(self, name: str) -> bool:
        """Remove peripheral from target by name."""
        for i, p in enumerate(self.target_device.peripherals):
            if p.name == name:
                self.target_device.peripherals.pop(i)
                self._used_names.discard(name)
                self._used_addresses.discard(p.base_address)
                return True
        return False

    def clear(self):
        """Clear target device (start fresh)."""
        self.target_device = SVDDevice()
        self._used_names.clear()
        self._used_addresses.clear()

    def save(self, path: str, pretty: bool = True):
        """
        Save composed device to SVD file.

        Args:
            path: Output file path
            pretty: Pretty-print XML
        """
        svd_content = self.target_device.to_svd(pretty=pretty)

        with open(path, 'w') as f:
            f.write(svd_content)

        logger.info(f"Saved SVD to {path} ({len(self.target_device.peripherals)} peripherals)")

    def to_svd(self, pretty: bool = True) -> str:
        """Get SVD XML as string."""
        return self.target_device.to_svd(pretty=pretty)

    def describe(self) -> str:
        """Get human-readable description of current state."""
        lines = [
            "SVD Composer Status",
            "=" * 40,
            "",
            f"Source Devices: {len(self.devices)}",
        ]

        for name in sorted(self.devices.keys())[:10]:
            p_count = len(self.devices[name].peripherals)
            lines.append(f"  - {name}: {p_count} peripherals")

        if len(self.devices) > 10:
            lines.append(f"  ... and {len(self.devices) - 10} more")

        lines.extend([
            "",
            f"Target Device: {self.target_device.name}",
            f"  Peripherals: {len(self.target_device.peripherals)}",
        ])

        for p in self.target_device.peripherals[:10]:
            source = f" (from {p.source_device})" if p.source_device else ""
            lines.append(f"    - {p.name} @ 0x{p.base_address:08X}{source}")

        if len(self.target_device.peripherals) > 10:
            lines.append(f"    ... and {len(self.target_device.peripherals) - 10} more")

        return "\n".join(lines)

    def describe_for_llm(self) -> str:
        """Get LLM-friendly description for automated composition."""
        return self.describe()


# =============================================================================
# Interactive Browser
# =============================================================================

class InteractiveBrowser:
    """Interactive SVD browser for terminal use."""

    def __init__(self, composer: SVDComposer):
        self.composer = composer

    def run(self):
        """Run interactive session."""
        print("\nSVD Composer Interactive Browser")
        print("=" * 40)
        print("Commands: devices, peripherals <device>, search <query>,")
        print("          add <device> <peripheral>, remove <name>,")
        print("          info, save <path>, quit")
        print()

        while True:
            try:
                cmd = input("svd> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting.")
                break

            if not cmd:
                continue

            parts = cmd.split()
            command = parts[0].lower()

            if command in ('quit', 'exit', 'q'):
                break

            elif command == 'devices':
                for name in self.composer.list_devices():
                    device = self.composer.devices[name]
                    print(f"  {name}: {len(device.peripherals)} peripherals")

            elif command == 'peripherals' and len(parts) > 1:
                device = parts[1]
                for entry in self.composer.list_peripherals(device):
                    print(f"  {entry.name} @ 0x{entry.base_address:08X} ({entry.group_name})")

            elif command == 'search' and len(parts) > 1:
                query = ' '.join(parts[1:])
                results = self.composer.search_peripherals(query)
                for entry in results[:20]:
                    print(f"  {entry.device_name}/{entry.name} @ 0x{entry.base_address:08X}")

            elif command == 'add' and len(parts) >= 3:
                device = parts[1]
                peripheral = parts[2]
                new_base = int(parts[3], 0) if len(parts) > 3 else None
                if self.composer.add_peripheral(device, peripheral, new_base=new_base):
                    print(f"  Added {peripheral}")
                else:
                    print(f"  Failed to add {peripheral}")

            elif command == 'remove' and len(parts) > 1:
                name = parts[1]
                if self.composer.remove_peripheral(name):
                    print(f"  Removed {name}")
                else:
                    print(f"  {name} not found")

            elif command == 'info':
                print(self.composer.describe())

            elif command == 'save' and len(parts) > 1:
                path = parts[1]
                self.composer.save(path)
                print(f"  Saved to {path}")

            elif command == 'name' and len(parts) > 1:
                self.composer.set_device_info(name=' '.join(parts[1:]))
                print(f"  Device name set to: {self.composer.target_device.name}")

            else:
                print("  Unknown command. Type 'quit' to exit.")


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="SVD Composer - Create custom device SVDs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan SVD directory and list devices
    python -m slab_peripherals.svd_composer scan /path/to/svds

    # Interactive mode
    python -m slab_peripherals.svd_composer interactive /path/to/svds

    # Create SVD from MMIO log
    python -m slab_peripherals.svd_composer from-log mmio.log -o inferred.svd

    # Compose from command line
    python -m slab_peripherals.svd_composer compose \\
        --source /path/to/svds \\
        --add STM32F405:GPIOA \\
        --add STM32F407:USB_OTG_FS:0x50000000 \\
        --name MyDevice \\
        --output custom.svd
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Scan command
    scan_parser = subparsers.add_parser('scan', help='Scan SVD directory')
    scan_parser.add_argument('path', help='Directory to scan')
    scan_parser.add_argument('--recursive', '-r', action='store_true', default=True,
                             help='Scan recursively (default: True)')

    # List command
    list_parser = subparsers.add_parser('list', help='List peripherals')
    list_parser.add_argument('path', help='SVD directory or file')
    list_parser.add_argument('--device', '-d', help='Filter by device')
    list_parser.add_argument('--group', '-g', help='Filter by group')

    # Interactive command
    interactive_parser = subparsers.add_parser('interactive', help='Interactive browser')
    interactive_parser.add_argument('path', help='SVD directory to scan')

    # From-log command
    log_parser = subparsers.add_parser('from-log', help='Create SVD from MMIO log')
    log_parser.add_argument('log', help='MMIO log file')
    log_parser.add_argument('--output', '-o', required=True, help='Output SVD file')
    log_parser.add_argument('--format', '-f', choices=['auto', 'slab', 'qemu', 'json', 'csv'],
                            default='auto', help='Log format')
    log_parser.add_argument('--name', '-n', default='InferredDevice', help='Device name')
    log_parser.add_argument('--alignment', '-a', type=lambda x: int(x, 0), default=0x400,
                            help='Peripheral alignment (default: 0x400)')

    # Compose command
    compose_parser = subparsers.add_parser('compose', help='Compose new SVD')
    compose_parser.add_argument('--source', '-s', required=True, help='Source SVD directory')
    compose_parser.add_argument('--add', '-a', action='append', default=[],
                                help='Add peripheral (DEVICE:PERIPHERAL[:NEWBASE])')
    compose_parser.add_argument('--name', '-n', default='CustomDevice', help='Device name')
    compose_parser.add_argument('--vendor', '-v', default='Custom', help='Vendor name')
    compose_parser.add_argument('--output', '-o', required=True, help='Output SVD file')
    compose_parser.add_argument('--log', help='Also include peripherals from MMIO log')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    composer = SVDComposer()

    if args.command == 'scan':
        count = composer.scan_directory(args.path, recursive=args.recursive)
        print(f"Scanned {count} devices:")
        for name in sorted(composer.devices.keys()):
            device = composer.devices[name]
            print(f"  {name}: {len(device.peripherals)} peripherals")

    elif args.command == 'list':
        if os.path.isfile(args.path):
            composer.scan_file(args.path)
        else:
            composer.scan_directory(args.path)

        entries = composer.list_peripherals(device=args.device, group=args.group)
        for entry in entries:
            print(f"{entry.device_name:20s} {entry.name:20s} 0x{entry.base_address:08X} "
                  f"{entry.group_name:15s} {entry.register_count:3d} regs")

    elif args.command == 'interactive':
        composer.scan_directory(args.path)
        browser = InteractiveBrowser(composer)
        browser.run()

    elif args.command == 'from-log':
        composer.mmio_parser.parse_log(args.log, format=args.format)
        count = composer.add_from_mmio_log(args.log, peripheral_alignment=args.alignment)
        composer.set_device_info(name=args.name)
        composer.save(args.output)
        print(f"Created SVD with {count} inferred peripherals: {args.output}")

    elif args.command == 'compose':
        # Scan sources
        composer.scan_directory(args.source)

        # Set device info
        composer.set_device_info(name=args.name, vendor=args.vendor)

        # Add peripherals
        for spec in args.add:
            parts = spec.split(':')
            if len(parts) < 2:
                print(f"Invalid spec: {spec} (expected DEVICE:PERIPHERAL[:NEWBASE])")
                continue

            device = parts[0]
            peripheral = parts[1]
            new_base = int(parts[2], 0) if len(parts) > 2 else None

            if not composer.add_peripheral(device, peripheral, new_base=new_base):
                print(f"Warning: Could not add {device}:{peripheral}")

        # Add from log if specified
        if args.log:
            composer.add_from_mmio_log(args.log)

        # Save
        composer.save(args.output)
        print(f"Created SVD: {args.output}")
        print(composer.describe())

    return 0


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    exit(main())
