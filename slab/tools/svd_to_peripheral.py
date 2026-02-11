#!/usr/bin/env python3
"""
SVD-to-Peripheral Skeleton Generator

Generates Python peripheral class skeletons from CMSIS-SVD XML files.
The generated code includes register offset constants, bitfield definitions,
and a stub read/write implementation ready to be filled in.

Usage:
    # Generate skeleton for a single peripheral
    python3 svd_to_peripheral.py STM32F405.svd SPI1

    # Generate skeletons for all peripherals
    python3 svd_to_peripheral.py STM32F405.svd --all --outdir stubs/

    # Generate MCUemu YAML config
    python3 svd_to_peripheral.py STM32F405.svd --yaml

    # List peripherals
    python3 svd_to_peripheral.py STM32F405.svd --list

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import argparse
import sys
import textwrap
from pathlib import Path

# Add slab/python to path for imports
SCRIPT_DIR = Path(__file__).parent.resolve()
SLAB_PYTHON = SCRIPT_DIR.parent / "python"
sys.path.insert(0, str(SLAB_PYTHON))

from slab_cortex_m.svd_parser import SVDParser, SVDPeripheral, SVDRegister, SVDField


def generate_skeleton(periph: SVDPeripheral, device_name: str = "") -> str:
    """Generate a Python class skeleton from an SVD peripheral definition.

    Args:
        periph: Parsed SVD peripheral.
        device_name: Device name for the module docstring.

    Returns:
        Python source code as a string.
    """
    class_name = _sanitize_class_name(periph.name)
    lines = []

    # Module docstring
    lines.append(f'"""')
    lines.append(f'{periph.name} Peripheral — {periph.description.strip()}')
    if device_name:
        lines.append(f'')
        lines.append(f'Generated from {device_name} SVD by svd_to_peripheral.py')
    lines.append(f'"""')
    lines.append(f'')
    lines.append(f'import logging')
    lines.append(f'')
    lines.append(f'log = logging.getLogger("{periph.name}")')
    lines.append(f'')
    lines.append(f'')

    # Class definition
    lines.append(f'class {class_name}:')
    lines.append(f'    """')
    lines.append(f'    {periph.name} peripheral at 0x{periph.base_address:08X}.')
    lines.append(f'    {periph.description.strip()}')
    lines.append(f'    """')
    lines.append(f'')

    # Register offset constants
    lines.append(f'    # Register offsets')
    for reg in periph.registers:
        desc = reg.description.strip().replace('\n', ' ')[:60] if reg.description else ""
        if reg.dim > 0:
            lines.append(f'    {reg.name}_BASE = 0x{reg.address_offset:04X}  # {desc} (array[{reg.dim}], step=0x{reg.dim_increment:X})')
        else:
            lines.append(f'    {reg.name} = 0x{reg.address_offset:04X}  # {desc}')
    lines.append(f'')

    # Bitfield constants (grouped by register)
    has_fields = any(reg.fields for reg in periph.registers)
    if has_fields:
        lines.append(f'    # Bitfield definitions')
        for reg in periph.registers:
            if not reg.fields:
                continue
            for fld in sorted(reg.fields, key=lambda f: f.bit_offset):
                prefix = f'{reg.name}_{fld.name}'
                if fld.bit_width == 1:
                    lines.append(f'    {prefix} = 1 << {fld.bit_offset}  # bit {fld.bit_offset}')
                else:
                    mask = ((1 << fld.bit_width) - 1) << fld.bit_offset
                    lines.append(f'    {prefix}_MASK = 0x{mask:08X}  # bits [{fld.bit_offset + fld.bit_width - 1}:{fld.bit_offset}]')
                    lines.append(f'    {prefix}_SHIFT = {fld.bit_offset}')
        lines.append(f'')

    # Constructor
    lines.append(f'    def __init__(self, base: int = 0x{periph.base_address:08X}, irq: int = -1):')
    lines.append(f'        self.name = "{periph.name}"')
    lines.append(f'        self.base = base')
    lines.append(f'        self.size = 0x{periph.size:X}')
    lines.append(f'        self.irq = irq')
    lines.append(f'        self.irq_callback = None')
    lines.append(f'        self.regs = {{}}')
    lines.append(f'        self._reset()')
    lines.append(f'')

    # Reset method
    lines.append(f'    def _reset(self):')
    lines.append(f'        """Reset all registers to their default values."""')
    for reg in periph.registers:
        if reg.dim > 0:
            for i in range(min(reg.dim, 8)):
                off = reg.address_offset + i * reg.dim_increment
                lines.append(f'        self.regs[0x{off:04X}] = 0x{reg.reset_value:08X}  # {reg.name}[{i}]')
            if reg.dim > 8:
                lines.append(f'        # ... {reg.dim - 8} more {reg.name} entries')
        else:
            lines.append(f'        self.regs[0x{reg.address_offset:04X}] = 0x{reg.reset_value:08X}  # {reg.name}')
    lines.append(f'')

    # contains method
    lines.append(f'    def contains(self, addr: int) -> bool:')
    lines.append(f'        """Check if address falls within this peripheral."""')
    lines.append(f'        return self.base <= addr < self.base + self.size')
    lines.append(f'')

    # read method
    lines.append(f'    def read(self, addr: int, size: int):')
    lines.append(f'        """Read a register. Returns (value, status)."""')
    lines.append(f'        offset = addr - self.base')
    lines.append(f'        value = self.regs.get(offset, 0)')
    lines.append(f'        # TODO: Add read side effects here')
    lines.append(f'        return (value, 0)')
    lines.append(f'')

    # write method
    lines.append(f'    def write(self, addr: int, size: int, value: int):')
    lines.append(f'        """Write a register. Returns status."""')
    lines.append(f'        offset = addr - self.base')
    lines.append(f'        self.regs[offset] = value & 0xFFFFFFFF')
    lines.append(f'        # TODO: Add write side effects here')
    lines.append(f'        return 0')
    lines.append(f'')

    # trigger_irq helper
    lines.append(f'    def trigger_irq(self, level: int = 1):')
    lines.append(f'        """Assert or deassert the peripheral IRQ."""')
    lines.append(f'        if self.irq_callback and self.irq >= 0:')
    lines.append(f'            self.irq_callback(self.irq, level)')
    lines.append(f'')

    return '\n'.join(lines)


def _sanitize_class_name(name: str) -> str:
    """Convert peripheral name to a valid Python class name."""
    # Remove trailing digits for generic naming
    clean = name.replace('-', '_').replace(' ', '_')
    # Capitalize properly
    if clean.isupper():
        return clean
    return clean


def list_peripherals(device):
    """Print a summary table of all peripherals in the device."""
    print(f"Device: {device.name} — {device.description.strip()}")
    if device.cpu_name:
        print(f"CPU: {device.cpu_name}")
    print(f"")
    print(f"{'Name':<16} {'Base':>12} {'Size':>8} {'IRQs':<20} Description")
    print(f"{'─'*16} {'─'*12} {'─'*8} {'─'*20} {'─'*40}")
    for p in device.peripherals:
        irqs = ", ".join(f"{i.name}({i.value})" for i in p.interrupts[:3])
        desc = p.description.strip().replace('\n', ' ')[:40]
        print(f"{p.name:<16} 0x{p.base_address:08X} 0x{p.size:04X}   {irqs:<20} {desc}")
    print(f"\nTotal: {len(device.peripherals)} peripherals")


def main():
    parser = argparse.ArgumentParser(
        description='Generate peripheral class skeletons from CMSIS-SVD files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          %(prog)s STM32F405.svd SPI1              # Single peripheral skeleton
          %(prog)s STM32F405.svd --all              # All peripherals to stdout
          %(prog)s STM32F405.svd --all --outdir .   # One file per peripheral
          %(prog)s STM32F405.svd --yaml             # MCUemu YAML config
          %(prog)s STM32F405.svd --list             # List all peripherals
        """))
    parser.add_argument('svd', type=Path, help='Path to SVD file')
    parser.add_argument('peripheral', nargs='?', default=None,
                        help='Peripheral name to generate (e.g., SPI1, RCC)')
    parser.add_argument('--all', action='store_true',
                        help='Generate skeletons for all peripherals')
    parser.add_argument('--outdir', type=Path, default=None,
                        help='Output directory (one file per peripheral)')
    parser.add_argument('--yaml', action='store_true',
                        help='Generate MCUemu YAML config instead of Python')
    parser.add_argument('--yaml-all', action='store_true',
                        help='Include all peripherals in YAML (including NVIC/SCB)')
    parser.add_argument('--list', action='store_true',
                        help='List all peripherals in the SVD file')
    args = parser.parse_args()

    if not args.svd.exists():
        print(f"Error: SVD file not found: {args.svd}", file=sys.stderr)
        sys.exit(1)

    # Parse SVD
    svd_parser = SVDParser()
    device = svd_parser.parse(str(args.svd))

    if args.list:
        list_peripherals(device)
        return

    if args.yaml or args.yaml_all:
        yaml_str = svd_parser.generate_yaml_config(device, include_all=args.yaml_all)
        print(yaml_str)
        return

    if args.peripheral:
        # Single peripheral
        periph = device.get_peripheral(args.peripheral)
        if not periph:
            print(f"Error: Peripheral '{args.peripheral}' not found.", file=sys.stderr)
            print(f"Available: {', '.join(p.name for p in device.peripherals)}", file=sys.stderr)
            sys.exit(1)
        code = generate_skeleton(periph, device.name)
        print(code)

    elif args.all:
        if args.outdir:
            # One file per peripheral
            args.outdir.mkdir(parents=True, exist_ok=True)
            for periph in device.peripherals:
                code = generate_skeleton(periph, device.name)
                filename = f"{periph.name.lower()}.py"
                outpath = args.outdir / filename
                outpath.write_text(code)
                print(f"  {outpath}")
            print(f"\nGenerated {len(device.peripherals)} files in {args.outdir}/")
        else:
            # All to stdout, separated
            for i, periph in enumerate(device.peripherals):
                if i > 0:
                    print(f"\n{'#' * 78}\n")
                code = generate_skeleton(periph, device.name)
                print(code)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
