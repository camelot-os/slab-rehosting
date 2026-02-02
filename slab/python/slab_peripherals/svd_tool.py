#!/usr/bin/env python3
"""
SVD Tool - Unified SVD peripheral code generator for MCUemu.

Generates Python peripheral implementations from CMSIS-SVD files:
- Individual peripheral classes with register definitions
- Complete PeripheralSet classes for MCU families

Usage:
    svd_tool.py list <svd_file>                    # List peripherals
    svd_tool.py peripheral <svd_file> RCC PWR      # Generate peripheral classes
    svd_tool.py peripheralset <svd_file> -o out.py # Generate PeripheralSet

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import argparse
import re
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from slab_cortex_m.svd_parser import SVDParser, SVDDevice, SVDPeripheral, SVDRegister


# =============================================================================
# Peripheral Type Detection
# =============================================================================

PERIPHERAL_TYPES = {
    # System
    r'^(SEC_)?RCC$': ('rcc', 'STM32RCCv4'),
    r'^(SEC_)?PWR$': ('pwr', 'STM32PWRv2'),
    r'^(SEC_)?FLASH$': ('flash', 'STM32FLASHv3'),
    # GPIO
    r'^(SEC_)?GPIO[A-K]$': ('gpio', 'STM32GPIOv2'),
    r'^(SEC_)?EXTI$': ('exti', 'STM32EXTI'),
    # Communication
    r'^(SEC_)?U?S?ART\d+$': ('usart', 'STM32USARTv2'),
    r'^(SEC_)?UART\d+$': ('usart', 'STM32USARTv2'),
    r'^(SEC_)?LPUART\d*$': ('lpuart', 'STM32LPUART'),
    r'^(SEC_)?SPI\d+$': ('spi', 'STM32SPIv2'),
    r'^(SEC_)?I2C\d+$': ('i2c', 'STM32I2Cv2'),
    # Timers
    r'^(SEC_)?TIM[18]$': ('timer_adv', 'STM32AdvancedTimer'),
    r'^(SEC_)?TIM[67]$': ('timer_basic', 'STM32BasicTimer'),
    r'^(SEC_)?TIM\d+$': ('timer', 'STM32GeneralTimer'),
    r'^(SEC_)?LPTIM\d*$': ('lptim', 'STM32LPTIM'),
    # Analog
    r'^(SEC_)?ADC\d*$': ('adc', 'STM32ADCv3'),
    r'^(SEC_)?DAC\d*$': ('dac', 'STM32DAC'),
    # DMA
    r'^(SEC_)?G?P?DMA\d*$': ('dma', 'STM32DMAv2'),
    # Misc
    r'^(SEC_)?IWDG$': ('iwdg', 'STM32IWDG'),
    r'^(SEC_)?WWDG$': ('wwdg', 'STM32WWDG'),
    r'^(SEC_)?RTC$': ('rtc', 'STM32RTC'),
    r'^(SEC_)?CRC$': ('crc', 'STM32CRC'),
    r'^(SEC_)?RNG$': ('rng', 'STM32RNG'),
    r'^(SEC_)?SYSCFG$': ('syscfg', 'STM32SYSCFG'),
    # TrustZone
    r'^(SEC_)?GTZC.*$': ('gtzc', 'STM32GTZC'),
    r'^(SEC_)?TAMP$': ('tamp', 'STM32TAMP'),
    # USB
    r'^(SEC_)?USB\w*$': ('usb', 'STM32USBDevice'),
}


@dataclass
class PeripheralInfo:
    """Peripheral metadata for code generation."""
    name: str
    base_address: int
    size: int
    periph_type: str
    class_name: str
    is_secure: bool = False


def detect_type(name: str) -> Tuple[str, str]:
    """Detect peripheral type and suggested class from name."""
    for pattern, (ptype, pclass) in PERIPHERAL_TYPES.items():
        if re.match(pattern, name, re.IGNORECASE):
            return ptype, pclass
    return 'generic', 'STM32Peripheral'


def extract_index(name: str) -> int:
    """Extract numeric index from peripheral name (e.g., I2C1 -> 1)."""
    match = re.search(r'\d+$', name)
    return int(match.group()) if match else 1


# =============================================================================
# Peripheral Class Generator
# =============================================================================

def to_python_name(name: str) -> str:
    """Convert register/field name to valid Python identifier."""
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if name and name[0].isdigit():
        name = '_' + name
    return name.upper()


def generate_peripheral_class(
    peripheral: SVDPeripheral,
    base_class: str = "STM32Peripheral",
    include_fields: bool = True,
) -> str:
    """Generate Python peripheral class from SVD peripheral definition."""
    lines = [
        f'class {peripheral.name}Peripheral({base_class}):',
        '    """',
        f'    {peripheral.description or peripheral.name} peripheral.',
        f'    Base: 0x{peripheral.base_address:08X}, Size: 0x{peripheral.size:X}',
        '    """',
        '',
        '    # Register offsets',
    ]

    # Register offset constants
    for reg in sorted(peripheral.registers, key=lambda r: r.address_offset):
        name = to_python_name(reg.name)
        desc = reg.description[:40] + '...' if reg.description and len(reg.description) > 40 else (reg.description or '')
        lines.append(f'    {name} = 0x{reg.address_offset:03X}  # {desc}')

    lines.append('')

    # Field bit masks (optional)
    if include_fields:
        for reg in sorted(peripheral.registers, key=lambda r: r.address_offset):
            if not reg.fields:
                continue
            reg_name = to_python_name(reg.name)
            lines.append(f'    # {reg.name} fields')
            for field in sorted(reg.fields, key=lambda f: f.bit_offset, reverse=True):
                field_name = to_python_name(field.name)
                if field.bit_width == 1:
                    lines.append(f'    {reg_name}_{field_name}_POS = {field.bit_offset}')
                    lines.append(f'    {reg_name}_{field_name} = (1 << {field.bit_offset})')
                else:
                    lines.append(f'    {reg_name}_{field_name}_POS = {field.bit_offset}')
                    lines.append(f'    {reg_name}_{field_name}_MSK = 0x{field.bit_mask:08X}')
            lines.append('')

    # Constructor
    lines.extend([
        f'    def __init__(self, base: int = 0x{peripheral.base_address:08X}):',
        f'        super().__init__("{peripheral.name}", base, 0x{peripheral.size:X})',
        '        self.regs = {}',
    ])

    # Initialize registers with reset values
    for reg in sorted(peripheral.registers, key=lambda r: r.address_offset):
        name = to_python_name(reg.name)
        lines.append(f'        self.regs[self.{name}] = 0x{reg.reset_value:08X}')

    lines.extend([
        '',
        '    def _read_reg(self, offset: int, size: int) -> int:',
        '        return self.regs.get(offset, 0)',
        '',
        '    def _write_reg(self, offset: int, size: int, value: int):',
        '        self.regs[offset] = value',
        '',
    ])

    return '\n'.join(lines)


def generate_peripheral_module(
    device: SVDDevice,
    peripheral_names: List[str],
    base_class: str = "STM32Peripheral",
    include_fields: bool = True,
) -> str:
    """Generate Python module with peripheral classes and base class."""
    lines = [
        '"""',
        f'{device.name} Peripherals - Auto-generated from SVD',
        '',
        'Author: Mathieu Renard <mathieu.renard@twistedwires.io>',
        'Copyright (C) 2026 TwistedWires Security Lab',
        'SPDX-License-Identifier: Apache-2.0',
        '"""',
        '',
        'from typing import Tuple',
        '',
        '',
        f'class {base_class}:',
        '    """Base class for STM32 peripherals."""',
        '',
        '    def __init__(self, name: str, base: int, size: int):',
        '        self.name = name',
        '        self.base = base',
        '        self.size = size',
        '',
        '    def read(self, address: int, size: int) -> Tuple[int, int]:',
        '        offset = address - self.base',
        '        if 0 <= offset < self.size:',
        '            return self._read_reg(offset, size), 0',
        '        return 0, 1',
        '',
        '    def write(self, address: int, size: int, value: int) -> int:',
        '        offset = address - self.base',
        '        if 0 <= offset < self.size:',
        '            self._write_reg(offset, size, value)',
        '            return 0',
        '        return 1',
        '',
        '    def _read_reg(self, offset: int, size: int) -> int:',
        '        return 0',
        '',
        '    def _write_reg(self, offset: int, size: int, value: int):',
        '        pass',
        '',
        '',
    ]

    for name in peripheral_names:
        peripheral = device.get_peripheral(name)
        if peripheral:
            lines.append(generate_peripheral_class(peripheral, base_class, include_fields))
            lines.append('')

    return '\n'.join(lines)


# =============================================================================
# PeripheralSet Generator
# =============================================================================

def generate_peripheral_set(device: SVDDevice, class_name: str, family: str) -> str:
    """Generate Python PeripheralSet class from SVD device."""

    # Extract and classify peripherals
    peripherals = []
    for p in device.peripherals:
        ptype, pclass = detect_type(p.name)
        peripherals.append(PeripheralInfo(
            name=p.name,
            base_address=p.base_address,
            size=p.size,
            periph_type=ptype,
            class_name=pclass,
            is_secure=p.name.startswith('SEC_'),
        ))

    # Group by type (non-secure only)
    gpio = [p for p in peripherals if p.periph_type == 'gpio' and not p.is_secure]
    usart = [p for p in peripherals if p.periph_type == 'usart' and not p.is_secure]
    spi = [p for p in peripherals if p.periph_type == 'spi' and not p.is_secure]
    i2c = [p for p in peripherals if p.periph_type == 'i2c' and not p.is_secure]
    timers = [p for p in peripherals if p.periph_type.startswith('timer') and not p.is_secure]
    gtzc = [p for p in peripherals if p.periph_type == 'gtzc' and not p.is_secure]

    rcc = next((p for p in peripherals if p.periph_type == 'rcc' and not p.is_secure), None)
    pwr = next((p for p in peripherals if p.periph_type == 'pwr' and not p.is_secure), None)
    flash = next((p for p in peripherals if p.periph_type == 'flash' and not p.is_secure), None)

    # Build imports
    imports = ['STM32PeripheralSet', 'STM32Peripheral']
    if gpio: imports.extend(['STM32GPIOv2', 'STM32EXTI'])
    if rcc: imports.append('STM32RCCv4')
    if pwr: imports.append('STM32PWRv2')
    if flash: imports.append('STM32FLASHv3')
    if usart: imports.append('STM32USARTv2')
    if spi: imports.append('STM32SPIv2')
    if i2c: imports.append('STM32I2Cv2')
    if timers: imports.extend(['STM32BasicTimer', 'STM32GeneralTimer', 'STM32AdvancedTimer', 'STM32LPTIM'])
    if gtzc: imports.extend(['STM32GTZC', 'STM32MPCBB'])

    misc_classes = []
    for p in peripherals:
        if p.class_name in ('STM32IWDG', 'STM32WWDG', 'STM32RTC', 'STM32CRC', 'STM32RNG') and not p.is_secure:
            if p.class_name not in misc_classes:
                misc_classes.append(p.class_name)

    # Generate code
    lines = [
        '"""',
        f'{device.name} Peripheral Set - Auto-generated from SVD',
        '',
        'Author: Mathieu Renard <mathieu.renard@twistedwires.io>',
        'Copyright (C) 2026 TwistedWires Security Lab',
        'SPDX-License-Identifier: Apache-2.0',
        '"""',
        '',
        'import logging',
        'from typing import Optional, Dict',
        'from .stm32_base import STM32PeripheralSet, STM32Peripheral',
    ]

    # Add specific imports
    if 'STM32GPIOv2' in imports:
        lines.append('from .stm32_gpio import STM32GPIOv2, STM32EXTI')
    if 'STM32USARTv2' in imports:
        lines.append('from .stm32_usart import STM32USARTv2, STM32LPUART')
    if 'STM32SPIv2' in imports:
        lines.append('from .stm32_spi import STM32SPIv2')
    if 'STM32I2Cv2' in imports:
        lines.append('from .stm32_i2c import STM32I2Cv2')
    if 'STM32RCCv4' in imports:
        lines.append('from .stm32_rcc import STM32RCCv4')
    if 'STM32PWRv2' in imports:
        lines.append('from .stm32_pwr import STM32PWRv2')
    if 'STM32FLASHv3' in imports:
        lines.append('from .stm32_flash import STM32FLASHv3')
    if 'STM32BasicTimer' in imports:
        lines.append('from .stm32_timers import STM32BasicTimer, STM32GeneralTimer, STM32AdvancedTimer, STM32LPTIM')
    if 'STM32GTZC' in imports:
        lines.append('from .stm32u5xx import STM32GTZC, STM32MPCBB')
    if misc_classes:
        lines.append(f"from .stm32_misc import {', '.join(sorted(misc_classes))}")

    # Class definition
    lines.extend([
        '',
        '',
        f'class {class_name}(STM32PeripheralSet):',
        f'    """Peripheral set for {device.name}."""',
        '',
        f'    def __init__(self, device: str = "{device.name}", log: logging.Logger = None):',
        '        super().__init__(device, log)',
        f'        self.family = "{family}"',
        '',
        '        self._create_clock_system()',
        '        self._create_gpio()',
        '        self._create_communication()',
        '        self._create_timers()',
        '        self._create_misc()',
    ])

    if gtzc:
        lines.append('        self._create_trustzone()')

    # Clock system
    lines.extend(['', '    def _create_clock_system(self):'])
    if rcc:
        lines.append(f'        self.rcc = STM32RCCv4(base=0x{rcc.base_address:08X})')
        lines.append('        self.add_peripheral(self.rcc)')
    if pwr:
        lines.append(f'        self.pwr = STM32PWRv2(base=0x{pwr.base_address:08X}, family="{family}")')
        lines.append('        self.add_peripheral(self.pwr)')
    if flash:
        lines.append(f'        self.flash = STM32FLASHv3(base=0x{flash.base_address:08X})')
        lines.append('        self.add_peripheral(self.flash)')

    # GPIO
    lines.extend(['', '    def _create_gpio(self):'])
    if gpio:
        lines.append('        gpio_bases = {')
        for p in sorted(gpio, key=lambda x: x.name):
            port = p.name.replace('GPIO', '')
            lines.append(f"            '{port}': 0x{p.base_address:08X},")
        lines.extend([
            '        }',
            '        self.gpio = {}',
            '        for port, base in gpio_bases.items():',
            '            self.gpio[port] = STM32GPIOv2(port=port, base=base)',
            '            self.add_peripheral(self.gpio[port])',
            '        self.exti = STM32EXTI(base=0x40013C00)',
            '        self.add_peripheral(self.exti)',
        ])
    else:
        lines.append('        pass  # No GPIO')

    # Communication
    lines.extend(['', '    def _create_communication(self):'])
    if usart:
        lines.append('        usart_cfg = [')
        for p in sorted(usart, key=lambda x: x.base_address):
            lines.append(f'            ({extract_index(p.name)}, 0x{p.base_address:08X}),')
        lines.extend([
            '        ]',
            '        for idx, base in usart_cfg:',
            '            setattr(self, f"usart{idx}", STM32USARTv2(index=idx, base=base))',
            '            self.add_peripheral(getattr(self, f"usart{idx}"))',
        ])
    if spi:
        lines.append('        spi_cfg = [')
        for p in sorted(spi, key=lambda x: x.base_address):
            lines.append(f'            ({extract_index(p.name)}, 0x{p.base_address:08X}),')
        lines.extend([
            '        ]',
            '        for idx, base in spi_cfg:',
            '            setattr(self, f"spi{idx}", STM32SPIv2(index=idx, base=base))',
            '            self.add_peripheral(getattr(self, f"spi{idx}"))',
        ])
    if i2c:
        lines.append('        i2c_cfg = [')
        for p in sorted(i2c, key=lambda x: x.base_address):
            lines.append(f'            ({extract_index(p.name)}, 0x{p.base_address:08X}),')
        lines.extend([
            '        ]',
            '        for idx, base in i2c_cfg:',
            '            setattr(self, f"i2c{idx}", STM32I2Cv2(index=idx, base=base))',
            '            self.add_peripheral(getattr(self, f"i2c{idx}"))',
        ])
    if not (usart or spi or i2c):
        lines.append('        pass  # No communication peripherals')

    # Timers
    lines.extend(['', '    def _create_timers(self):'])
    if timers:
        for p in sorted(timers, key=lambda x: x.base_address):
            idx = extract_index(p.name)
            if idx in (1, 8):
                tcls = 'STM32AdvancedTimer'
            elif idx in (6, 7):
                tcls = 'STM32BasicTimer'
            else:
                tcls = 'STM32GeneralTimer'
            extra = ', is_32bit=True' if idx in (2, 5) else ''
            lines.append(f'        self.tim{idx} = {tcls}(index={idx}, base=0x{p.base_address:08X}{extra})')
            lines.append(f'        self.add_peripheral(self.tim{idx})')
    else:
        lines.append('        pass  # No timers')

    # Misc
    lines.extend(['', '    def _create_misc(self):'])
    misc_found = False
    for p in peripherals:
        if p.is_secure:
            continue
        if p.class_name in ('STM32IWDG', 'STM32WWDG', 'STM32RTC', 'STM32CRC', 'STM32RNG'):
            lines.append(f'        self.{p.name.lower()} = {p.class_name}(base=0x{p.base_address:08X})')
            lines.append(f'        self.add_peripheral(self.{p.name.lower()})')
            misc_found = True
    if not misc_found:
        lines.append('        pass  # No misc peripherals')

    # TrustZone
    if gtzc:
        lines.extend(['', '    def _create_trustzone(self):'])
        for p in gtzc:
            if 'TZSC' in p.name:
                lines.append(f'        self.gtzc = STM32GTZC(base=0x{p.base_address:08X})')
                lines.append('        self.add_peripheral(self.gtzc)')
            elif 'MPCBB' in p.name:
                idx = extract_index(p.name)
                lines.append(f'        self.mpcbb{idx} = STM32MPCBB(index={idx}, base=0x{p.base_address:08X})')
                lines.append(f'        self.add_peripheral(self.mpcbb{idx})')

    # Alias
    lines.extend([
        '',
        '',
        f'# Alias',
        f'{device.name}PeripheralSet = {class_name}',
        '',
    ])

    return '\n'.join(lines)


# =============================================================================
# CLI Commands
# =============================================================================

def cmd_list(args):
    """List peripherals in SVD file."""
    parser = SVDParser()
    device = parser.parse(args.svd_file)

    print(f"Device: {device.name}")
    print(f"Peripherals: {len(device.peripherals)}")
    print("-" * 60)

    for p in sorted(device.peripherals, key=lambda x: x.base_address):
        ptype, _ = detect_type(p.name)
        sec = "[S]" if p.name.startswith('SEC_') else "   "
        print(f"  0x{p.base_address:08X} {sec} {p.name:20s} {ptype:12s} ({len(p.registers)} regs)")

    return 0


def cmd_peripheral(args):
    """Generate peripheral class(es)."""
    parser = SVDParser()
    device = parser.parse(args.svd_file)

    # Get peripheral names
    names = args.names
    if args.pattern:
        pattern = re.compile(args.pattern, re.IGNORECASE)
        names = [p.name for p in device.peripherals if pattern.match(p.name)]

    if not names:
        print("Error: No peripherals specified", file=sys.stderr)
        return 1

    print(f"Generating {len(names)} peripheral(s)...", file=sys.stderr)

    if args.standalone:
        code = generate_peripheral_module(device, names, args.base, not args.no_fields)
    else:
        code_parts = []
        for name in names:
            peripheral = device.get_peripheral(name)
            if peripheral:
                code_parts.append(generate_peripheral_class(peripheral, args.base, not args.no_fields))
            else:
                print(f"Warning: Peripheral '{name}' not found", file=sys.stderr)
        code = '\n\n'.join(code_parts)

    if args.output:
        Path(args.output).write_text(code)
        print(f"Generated: {args.output}", file=sys.stderr)
    else:
        print(code)

    return 0


def cmd_peripheralset(args):
    """Generate PeripheralSet class."""
    parser = SVDParser()
    device = parser.parse(args.svd_file)

    # Determine class name and family
    class_name = args.class_name or f'{device.name}PeripheralSet'

    if args.family:
        family = args.family
    elif 'H5' in device.name:
        family = 'H5'
    elif 'H7' in device.name:
        family = 'H7'
    elif 'F4' in device.name:
        family = 'F4'
    elif 'U5' in device.name:
        family = 'U5'
    elif 'L4' in device.name:
        family = 'L4'
    else:
        family = device.name[:2]

    code = generate_peripheral_set(device, class_name, family)

    if args.output:
        Path(args.output).write_text(code)
        print(f"Generated: {args.output}", file=sys.stderr)
    else:
        print(code)

    return 0


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        prog='svd_tool',
        description='SVD peripheral code generator for MCUemu',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # List all peripherals in SVD file
    svd_tool.py list STM32H563.svd

    # Generate RCC peripheral class
    svd_tool.py peripheral STM32H563.svd RCC

    # Generate multiple peripherals with fields
    svd_tool.py peripheral STM32H563.svd RCC PWR FLASH -o system.py

    # Generate all GPIO peripherals (pattern match)
    svd_tool.py peripheral STM32H563.svd --pattern "GPIO.*" --standalone

    # Generate complete PeripheralSet
    svd_tool.py peripheralset STM32H563.svd -o stm32h5xx.py
'''
    )

    subparsers = parser.add_subparsers(dest='command', help='Command')

    # list command
    p_list = subparsers.add_parser('list', help='List peripherals in SVD file')
    p_list.add_argument('svd_file', help='SVD file path')

    # peripheral command
    p_periph = subparsers.add_parser('peripheral', help='Generate peripheral class(es)')
    p_periph.add_argument('svd_file', help='SVD file path')
    p_periph.add_argument('names', nargs='*', help='Peripheral name(s)')
    p_periph.add_argument('--pattern', '-p', help='Regex pattern to match names')
    p_periph.add_argument('--output', '-o', help='Output file')
    p_periph.add_argument('--base', '-b', default='STM32Peripheral', help='Base class')
    p_periph.add_argument('--no-fields', action='store_true', help='Skip field definitions')
    p_periph.add_argument('--standalone', '-s', action='store_true', help='Include base class')

    # peripheralset command
    p_set = subparsers.add_parser('peripheralset', help='Generate PeripheralSet class')
    p_set.add_argument('svd_file', help='SVD file path')
    p_set.add_argument('--output', '-o', help='Output file')
    p_set.add_argument('--class-name', '-c', help='Class name')
    p_set.add_argument('--family', '-f', help='MCU family (H5, F4, etc.)')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Validate SVD file
    if not Path(args.svd_file).exists():
        print(f"Error: SVD file not found: {args.svd_file}", file=sys.stderr)
        return 1

    # Dispatch
    commands = {
        'list': cmd_list,
        'peripheral': cmd_peripheral,
        'peripheralset': cmd_peripheralset,
    }

    return commands[args.command](args)


if __name__ == '__main__':
    sys.exit(main())
