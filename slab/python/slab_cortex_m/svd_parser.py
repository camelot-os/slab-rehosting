#!/usr/bin/env python3
"""
SVD (System View Description) Parser for MCUemu

Parses CMSIS-SVD XML files to extract peripheral, register, and field definitions.
This enables automatic peripheral configuration from vendor-provided SVD files.

Features:
- Parse SVD XML files (CMSIS-SVD 1.0, 1.1, 1.3)
- Extract device, CPU, and peripheral information
- Generate MCUemu YAML configurations
- Provide runtime register/field lookup for debugging
- Support register arrays and cluster derivation

Usage:
    # Parse SVD file
    from svd_parser import SVDParser
    parser = SVDParser()
    device = parser.parse('/path/to/device.svd')

    # Generate YAML config
    yaml_config = parser.generate_yaml_config(device)

    # Runtime lookup
    reg_info = device.get_register_info(0x40020000)  # Returns GPIO info

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import xml.etree.ElementTree as ET
import re
import yaml
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

log = logging.getLogger('SVD')


# =============================================================================
# SVD DATA STRUCTURES
# =============================================================================

@dataclass
class SVDField:
    """SVD register field definition."""
    name: str
    description: str
    bit_offset: int
    bit_width: int
    access: str = "read-write"
    enumerated_values: Dict[str, int] = field(default_factory=dict)

    @property
    def bit_mask(self) -> int:
        """Return the bit mask for this field."""
        return ((1 << self.bit_width) - 1) << self.bit_offset


@dataclass
class SVDRegister:
    """SVD register definition."""
    name: str
    description: str
    address_offset: int
    size: int = 32
    access: str = "read-write"
    reset_value: int = 0
    reset_mask: int = 0xFFFFFFFF
    fields: List[SVDField] = field(default_factory=list)
    dim: int = 0  # Array dimension
    dim_increment: int = 0  # Array element spacing

    def get_field(self, name: str) -> Optional[SVDField]:
        """Get field by name."""
        for f in self.fields:
            if f.name == name:
                return f
        return None


@dataclass
class SVDInterrupt:
    """SVD interrupt definition."""
    name: str
    description: str
    value: int


@dataclass
class SVDPeripheral:
    """SVD peripheral definition."""
    name: str
    description: str
    base_address: int
    size: int = 0x400
    group_name: str = ""
    registers: List[SVDRegister] = field(default_factory=list)
    interrupts: List[SVDInterrupt] = field(default_factory=list)
    derived_from: Optional[str] = None

    def get_register(self, offset: int) -> Optional[SVDRegister]:
        """Get register by offset."""
        for reg in self.registers:
            if reg.dim > 0:
                # Array register
                for i in range(reg.dim):
                    if reg.address_offset + (i * reg.dim_increment) == offset:
                        return reg
            elif reg.address_offset == offset:
                return reg
        return None

    def get_register_by_name(self, name: str) -> Optional[SVDRegister]:
        """Get register by name."""
        for reg in self.registers:
            if reg.name == name or name.startswith(reg.name):
                return reg
        return None


@dataclass
class SVDDevice:
    """SVD device definition."""
    name: str
    version: str
    description: str
    vendor: str = ""
    vendor_id: str = ""
    series: str = ""
    license_text: str = ""
    cpu_name: str = ""
    cpu_revision: str = ""
    cpu_endian: str = "little"
    cpu_mpu_present: bool = False
    cpu_fpu_present: bool = False
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

    def get_peripheral_at(self, address: int) -> Optional[SVDPeripheral]:
        """Get peripheral containing address."""
        for p in self.peripherals:
            if p.base_address <= address < p.base_address + p.size:
                return p
        return None

    def get_register_info(self, address: int) -> Optional[Tuple[SVDPeripheral, SVDRegister, int]]:
        """
        Get register information for an address.

        Returns:
            Tuple of (peripheral, register, array_index) or None if not found
        """
        periph = self.get_peripheral_at(address)
        if not periph:
            return None

        offset = address - periph.base_address
        for reg in periph.registers:
            if reg.dim > 0:
                # Array register
                for i in range(reg.dim):
                    if reg.address_offset + (i * reg.dim_increment) == offset:
                        return (periph, reg, i)
            elif reg.address_offset == offset:
                return (periph, reg, 0)
        return None

    def describe_address(self, address: int) -> str:
        """Get human-readable description of an address."""
        info = self.get_register_info(address)
        if not info:
            return f"Unknown address 0x{address:08X}"

        periph, reg, idx = info
        if reg.dim > 0:
            return f"{periph.name}->{reg.name}[{idx}] @ 0x{address:08X}"
        return f"{periph.name}->{reg.name} @ 0x{address:08X}"


# =============================================================================
# SVD PARSER
# =============================================================================

class SVDParser:
    """Parser for CMSIS-SVD XML files."""

    def __init__(self):
        self.device: Optional[SVDDevice] = None
        self._peripheral_map: Dict[str, SVDPeripheral] = {}

    def parse(self, svd_path: str) -> SVDDevice:
        """
        Parse an SVD file and return device information.

        Args:
            svd_path: Path to SVD XML file

        Returns:
            SVDDevice with parsed information
        """
        tree = ET.parse(svd_path)
        root = tree.getroot()

        # Parse device info
        device = self._parse_device(root)
        self.device = device
        return device

    def parse_string(self, svd_content: str) -> SVDDevice:
        """Parse SVD from XML string."""
        root = ET.fromstring(svd_content)
        device = self._parse_device(root)
        self.device = device
        return device

    def _parse_device(self, root: ET.Element) -> SVDDevice:
        """Parse device element."""
        device = SVDDevice(
            name=self._get_text(root, 'name', 'Unknown'),
            version=self._get_text(root, 'version', '1.0'),
            description=self._get_text(root, 'description', ''),
            vendor=self._get_text(root, 'vendor', ''),
            vendor_id=self._get_text(root, 'vendorID', ''),
            series=self._get_text(root, 'series', ''),
            license_text=self._get_text(root, 'licenseText', ''),
            address_unit_bits=int(self._get_text(root, 'addressUnitBits', '8')),
            width=int(self._get_text(root, 'width', '32')),
        )

        # Parse CPU info
        cpu = root.find('cpu')
        if cpu is not None:
            device.cpu_name = self._get_text(cpu, 'name', '')
            device.cpu_revision = self._get_text(cpu, 'revision', '')
            device.cpu_endian = self._get_text(cpu, 'endian', 'little')
            device.cpu_mpu_present = self._get_text(cpu, 'mpuPresent', '0') == '1'
            device.cpu_fpu_present = self._get_text(cpu, 'fpuPresent', '0') == '1'
            device.cpu_nvic_prio_bits = int(self._get_text(cpu, 'nvicPrioBits', '4'))

        # Parse peripherals
        peripherals_elem = root.find('peripherals')
        if peripherals_elem is not None:
            for periph_elem in peripherals_elem.findall('peripheral'):
                periph = self._parse_peripheral(periph_elem)
                device.peripherals.append(periph)
                self._peripheral_map[periph.name] = periph

        # Resolve derived peripherals
        self._resolve_derived_peripherals(device)

        return device

    def _parse_peripheral(self, elem: ET.Element) -> SVDPeripheral:
        """Parse peripheral element."""
        derived_from = elem.get('derivedFrom')

        periph = SVDPeripheral(
            name=self._get_text(elem, 'name', 'Unknown'),
            description=self._get_text(elem, 'description', ''),
            base_address=self._parse_int(self._get_text(elem, 'baseAddress', '0')),
            group_name=self._get_text(elem, 'groupName', ''),
            derived_from=derived_from,
        )

        # Parse size from addressBlock if available
        addr_block = elem.find('addressBlock')
        if addr_block is not None:
            size = self._get_text(addr_block, 'size', '0x400')
            periph.size = self._parse_int(size)

        # Parse registers
        registers_elem = elem.find('registers')
        if registers_elem is not None:
            for reg_elem in registers_elem.findall('register'):
                reg = self._parse_register(reg_elem)
                periph.registers.append(reg)

            # Also check for clusters
            for cluster_elem in registers_elem.findall('cluster'):
                cluster_regs = self._parse_cluster(cluster_elem)
                periph.registers.extend(cluster_regs)

        # Parse interrupts
        for int_elem in elem.findall('interrupt'):
            interrupt = SVDInterrupt(
                name=self._get_text(int_elem, 'name', ''),
                description=self._get_text(int_elem, 'description', ''),
                value=int(self._get_text(int_elem, 'value', '-1')),
            )
            periph.interrupts.append(interrupt)

        return periph

    def _parse_register(self, elem: ET.Element, base_offset: int = 0) -> SVDRegister:
        """Parse register element."""
        reg = SVDRegister(
            name=self._get_text(elem, 'name', 'Unknown'),
            description=self._get_text(elem, 'description', ''),
            address_offset=base_offset + self._parse_int(self._get_text(elem, 'addressOffset', '0')),
            size=self._parse_int(self._get_text(elem, 'size', '32')),
            access=self._get_text(elem, 'access', 'read-write'),
            reset_value=self._parse_int(self._get_text(elem, 'resetValue', '0')),
            reset_mask=self._parse_int(self._get_text(elem, 'resetMask', '0xFFFFFFFF')),
        )

        # Parse array dimensions
        dim_text = self._get_text(elem, 'dim', '')
        if dim_text:
            reg.dim = self._parse_int(dim_text)
            reg.dim_increment = self._parse_int(self._get_text(elem, 'dimIncrement', '4'))

        # Parse fields
        fields_elem = elem.find('fields')
        if fields_elem is not None:
            for field_elem in fields_elem.findall('field'):
                fld = self._parse_field(field_elem)
                reg.fields.append(fld)

        return reg

    def _parse_cluster(self, elem: ET.Element, base_offset: int = 0) -> List[SVDRegister]:
        """Parse cluster element (group of registers)."""
        registers = []
        cluster_offset = base_offset + self._parse_int(self._get_text(elem, 'addressOffset', '0'))

        for reg_elem in elem.findall('register'):
            reg = self._parse_register(reg_elem, cluster_offset)
            registers.append(reg)

        # Handle nested clusters
        for nested_cluster in elem.findall('cluster'):
            nested_regs = self._parse_cluster(nested_cluster, cluster_offset)
            registers.extend(nested_regs)

        return registers

    def _parse_field(self, elem: ET.Element) -> SVDField:
        """Parse field element."""
        # Handle both bitOffset/bitWidth and lsb/msb formats
        bit_offset = 0
        bit_width = 1

        lsb_text = self._get_text(elem, 'lsb', '')
        msb_text = self._get_text(elem, 'msb', '')
        bit_range = self._get_text(elem, 'bitRange', '')

        if bit_range:
            # Format: [MSB:LSB]
            match = re.match(r'\[(\d+):(\d+)\]', bit_range)
            if match:
                msb = int(match.group(1))
                lsb = int(match.group(2))
                bit_offset = lsb
                bit_width = msb - lsb + 1
        elif lsb_text and msb_text:
            lsb = int(lsb_text)
            msb = int(msb_text)
            bit_offset = lsb
            bit_width = msb - lsb + 1
        else:
            bit_offset = int(self._get_text(elem, 'bitOffset', '0'))
            bit_width = int(self._get_text(elem, 'bitWidth', '1'))

        fld = SVDField(
            name=self._get_text(elem, 'name', 'Unknown'),
            description=self._get_text(elem, 'description', ''),
            bit_offset=bit_offset,
            bit_width=bit_width,
            access=self._get_text(elem, 'access', 'read-write'),
        )

        # Parse enumerated values
        enum_elem = elem.find('enumeratedValues')
        if enum_elem is not None:
            for value_elem in enum_elem.findall('enumeratedValue'):
                name = self._get_text(value_elem, 'name', '')
                value = self._parse_int(self._get_text(value_elem, 'value', '0'))
                if name:
                    fld.enumerated_values[name] = value

        return fld

    def _resolve_derived_peripherals(self, device: SVDDevice):
        """Resolve derived peripheral definitions."""
        for periph in device.peripherals:
            if periph.derived_from and not periph.registers:
                base = self._peripheral_map.get(periph.derived_from)
                if base:
                    # Copy registers from base peripheral
                    periph.registers = [
                        SVDRegister(
                            name=r.name,
                            description=r.description,
                            address_offset=r.address_offset,
                            size=r.size,
                            access=r.access,
                            reset_value=r.reset_value,
                            reset_mask=r.reset_mask,
                            fields=r.fields.copy(),
                            dim=r.dim,
                            dim_increment=r.dim_increment,
                        )
                        for r in base.registers
                    ]
                    if not periph.size:
                        periph.size = base.size

    def _get_text(self, elem: ET.Element, tag: str, default: str = '') -> str:
        """Get text content of child element."""
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return default

    def _parse_int(self, text: str) -> int:
        """Parse integer from string (supports hex, binary, decimal)."""
        text = text.strip().lower()
        if not text:
            return 0
        if text.startswith('0x'):
            return int(text, 16)
        if text.startswith('0b'):
            return int(text, 2)
        if text.startswith('#'):
            # Binary with # prefix
            return int(text[1:], 2)
        return int(text)

    # =========================================================================
    # YAML GENERATION
    # =========================================================================

    def generate_yaml_config(self, device: SVDDevice, include_all: bool = False) -> str:
        """
        Generate MCUemu YAML configuration from SVD device.

        Args:
            device: Parsed SVD device
            include_all: If True, include all peripherals; otherwise only common ones

        Returns:
            YAML configuration string
        """
        # Determine peripheral types based on common patterns
        type_patterns = {
            r'^RCC': 'rcc',
            r'^PWR': 'pwr',
            r'^FLASH': 'flash',
            r'^GPIO[A-Z]?': 'gpio',
            r'^U?S?ART\d*': 'usart',
            r'^SPI\d*': 'spi',
            r'^I2C\d*': 'i2c',
            r'^TIM\d*': 'timer',
            r'^ADC\d*': 'adc',
            r'^DAC\d*': 'dac',
            r'^DMA\d*': 'dma',
            r'^USB': 'usb',
            r'^CAN\d*': 'can',
            r'^ETH': 'eth',
            r'^IWDG': 'iwdg',
            r'^WWDG': 'wwdg',
            r'^RTC': 'rtc',
            r'^EXTI': 'exti',
            r'^SYSCFG': 'syscfg',
            r'^NVIC': 'nvic',
            r'^SCB': 'scb',
        }

        def get_peripheral_type(name: str) -> str:
            for pattern, ptype in type_patterns.items():
                if re.match(pattern, name, re.IGNORECASE):
                    return ptype
            return 'generic'

        # Build configuration
        config = {
            'name': device.name,
            'machine': {
                'cpu_type': self._map_cpu_name(device.cpu_name),
                'flash_base': 0x08000000,
                'flash_size': 0x100000,
                'sram_base': 0x20000000,
                'sram_size': 0x20000,
                'periph_base': 0x40000000,
                'periph_size': 0x20000000,
                'num_irqs': 240,
                'tcp_port': 5000,
            },
            'peripherals': []
        }

        # Add peripherals
        for periph in device.peripherals:
            ptype = get_peripheral_type(periph.name)

            # Skip internal/system peripherals unless include_all
            if not include_all and ptype in ('nvic', 'scb'):
                continue

            entry = {
                'name': periph.name,
                'type': ptype,
                'base': f"0x{periph.base_address:08X}",
                'size': f"0x{periph.size:X}",
            }

            # Add IRQ if available
            if periph.interrupts:
                entry['irq'] = periph.interrupts[0].value

            config['peripherals'].append(entry)

        # Generate YAML with hex addresses
        return yaml.dump(config, default_flow_style=False, sort_keys=False)

    def _map_cpu_name(self, cpu_name: str) -> str:
        """Map SVD CPU name to QEMU CPU type."""
        cpu_name = cpu_name.lower()
        if 'cm0+' in cpu_name or 'cm0plus' in cpu_name:
            return 'cortex-m0'
        if 'cm0' in cpu_name:
            return 'cortex-m0'
        if 'cm3' in cpu_name:
            return 'cortex-m3'
        if 'cm4' in cpu_name:
            return 'cortex-m4'
        if 'cm7' in cpu_name:
            return 'cortex-m7'
        if 'cm23' in cpu_name:
            return 'cortex-m23'
        if 'cm33' in cpu_name:
            return 'cortex-m33'
        if 'cm55' in cpu_name:
            return 'cortex-m55'
        return 'cortex-m4'  # Default


# =============================================================================
# REGISTER DESCRIPTION HELPER
# =============================================================================

class SVDDebugHelper:
    """Helper for runtime debugging with SVD information."""

    def __init__(self, device: SVDDevice):
        self.device = device

    def describe_value(self, address: int, value: int) -> str:
        """
        Get human-readable description of a register value.

        Args:
            address: Register address
            value: Register value

        Returns:
            Formatted description string
        """
        info = self.device.get_register_info(address)
        if not info:
            return f"0x{address:08X} = 0x{value:08X}"

        periph, reg, idx = info
        lines = [f"{periph.name}->{reg.name} = 0x{value:08X}"]

        if reg.fields:
            lines.append("  Fields:")
            for field in sorted(reg.fields, key=lambda f: f.bit_offset, reverse=True):
                field_value = (value >> field.bit_offset) & ((1 << field.bit_width) - 1)
                if field.bit_width == 1:
                    lines.append(f"    [{field.bit_offset:2d}]    {field.name}: {field_value}")
                else:
                    msb = field.bit_offset + field.bit_width - 1
                    lines.append(f"    [{msb:2d}:{field.bit_offset:2d}] {field.name}: 0x{field_value:X}")

                # Show enumerated value name if available
                for name, enum_val in field.enumerated_values.items():
                    if enum_val == field_value:
                        lines[-1] += f" ({name})"
                        break

        return '\n'.join(lines)


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description='MCUemu SVD Parser - Parse CMSIS-SVD files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # Parse SVD and show device info
    python svd_parser.py /path/to/device.svd

    # Generate YAML configuration
    python svd_parser.py /path/to/device.svd --yaml

    # List all peripherals
    python svd_parser.py /path/to/device.svd --list-peripherals

    # Show register details for a peripheral
    python svd_parser.py /path/to/device.svd --peripheral GPIOA
'''
    )

    parser.add_argument('svd_file', help='Path to SVD file')
    parser.add_argument('--yaml', action='store_true',
                       help='Generate MCUemu YAML configuration')
    parser.add_argument('--yaml-all', action='store_true',
                       help='Include all peripherals in YAML')
    parser.add_argument('--list-peripherals', '-l', action='store_true',
                       help='List all peripherals')
    parser.add_argument('--peripheral', '-p', metavar='NAME',
                       help='Show details for specific peripheral')
    parser.add_argument('--address', '-a', metavar='ADDR',
                       help='Describe address (hex)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(name)s: %(message)s'
    )

    # Parse SVD file
    svd_parser = SVDParser()
    try:
        device = svd_parser.parse(args.svd_file)
    except Exception as e:
        log.error(f"Failed to parse SVD file: {e}")
        return 1

    # Generate YAML
    if args.yaml or args.yaml_all:
        yaml_config = svd_parser.generate_yaml_config(device, include_all=args.yaml_all)
        print(yaml_config)
        return 0

    # List peripherals
    if args.list_peripherals:
        print(f"Device: {device.name}")
        print(f"Vendor: {device.vendor}")
        print(f"CPU: {device.cpu_name}")
        print(f"\nPeripherals ({len(device.peripherals)}):")
        for p in sorted(device.peripherals, key=lambda x: x.base_address):
            irq_str = ""
            if p.interrupts:
                irqs = ", ".join(f"{i.name}={i.value}" for i in p.interrupts)
                irq_str = f" IRQ: {irqs}"
            print(f"  0x{p.base_address:08X} {p.name:12s} ({len(p.registers)} regs){irq_str}")
        return 0

    # Show peripheral details
    if args.peripheral:
        periph = device.get_peripheral(args.peripheral)
        if not periph:
            print(f"Peripheral not found: {args.peripheral}")
            return 1

        print(f"Peripheral: {periph.name}")
        print(f"Base: 0x{periph.base_address:08X}")
        print(f"Size: 0x{periph.size:X}")
        print(f"Description: {periph.description}")

        if periph.interrupts:
            print(f"\nInterrupts:")
            for irq in periph.interrupts:
                print(f"  {irq.name}: {irq.value}")

        print(f"\nRegisters ({len(periph.registers)}):")
        for reg in sorted(periph.registers, key=lambda r: r.address_offset):
            dim_str = f"[{reg.dim}]" if reg.dim > 0 else ""
            print(f"  +0x{reg.address_offset:03X} {reg.name}{dim_str:6s} {reg.access:12s} "
                  f"reset=0x{reg.reset_value:08X}")
            for field in sorted(reg.fields, key=lambda f: f.bit_offset, reverse=True):
                if field.bit_width == 1:
                    print(f"           [{field.bit_offset:2d}]    {field.name}")
                else:
                    msb = field.bit_offset + field.bit_width - 1
                    print(f"           [{msb:2d}:{field.bit_offset:2d}] {field.name}")
        return 0

    # Describe address
    if args.address:
        addr = int(args.address, 16) if args.address.startswith('0x') else int(args.address)
        print(device.describe_address(addr))
        return 0

    # Default: show device summary
    print(f"Device: {device.name}")
    print(f"Version: {device.version}")
    print(f"Vendor: {device.vendor}")
    print(f"Description: {device.description[:100]}...")
    print(f"\nCPU: {device.cpu_name} ({device.cpu_endian} endian)")
    print(f"NVIC Priority Bits: {device.cpu_nvic_prio_bits}")
    print(f"FPU: {'Yes' if device.cpu_fpu_present else 'No'}")
    print(f"MPU: {'Yes' if device.cpu_mpu_present else 'No'}")
    print(f"\nPeripherals: {len(device.peripherals)}")

    # Group by type
    groups: Dict[str, List[SVDPeripheral]] = {}
    for p in device.peripherals:
        group = p.group_name or 'Other'
        if group not in groups:
            groups[group] = []
        groups[group].append(p)

    for group, peripherals in sorted(groups.items()):
        print(f"  {group}: {len(peripherals)}")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
