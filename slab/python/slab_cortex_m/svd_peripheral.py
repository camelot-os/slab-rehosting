"""
SVD Auto-Stub Peripheral Set

Generates a complete peripheral set at runtime from an SVD file.
Each peripheral returns SVD reset values for reads and logs writes.
No hand-coded Python peripheral implementation needed.

This enables quick-start emulation of any Cortex-M MCU with just an SVD file:

    from slab_cortex_m.svd_peripheral import SVDStubPeripheralSet
    ps = SVDStubPeripheralSet.from_svd("STM32F407.svd")
    # All peripherals are immediately available with correct reset values

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Dict, List, Optional, Tuple, Callable, Any
from pathlib import Path

from slab_cortex_m.svd_parser import SVDParser, SVDDevice, SVDPeripheral, SVDRegister

log = logging.getLogger('SVDStub')

STATUS_OK = 0


class SVDStubPeripheral:
    """
    Auto-generated peripheral stub from SVD definition.

    Reads return reset values (or last written value).
    Writes store values. All accesses are optionally logged.
    Special status-register behaviors (RCC ready bits, etc.) are
    auto-detected via heuristics.
    """

    def __init__(self, svd_periph: SVDPeripheral, auto_ready: bool = True):
        self.name = svd_periph.name
        self.base = svd_periph.base_address
        self.size = svd_periph.size or 0x400
        self.irq = svd_periph.interrupts[0].value if svd_periph.interrupts else -1
        self.irq_callback: Optional[Callable] = None

        # Register storage: offset -> current value
        self.regs: Dict[int, int] = {}

        # SVD metadata for each offset
        self._svd_regs: Dict[int, SVDRegister] = {}

        # Ready-bit auto-set rules: (offset, mask) pairs
        # When firmware writes to a control reg, the ready bit is auto-set
        self._ready_rules: List[Tuple[int, int, int, int]] = []

        # Populate from SVD
        self._init_from_svd(svd_periph, auto_ready)

        self.log = logging.getLogger(f'SVD.{self.name}')

    def _init_from_svd(self, svd_periph: SVDPeripheral, auto_ready: bool):
        """Initialize register map from SVD definition."""
        for reg in svd_periph.registers:
            if reg.dim > 0:
                # Array register: expand all elements
                for i in range(reg.dim):
                    offset = reg.address_offset + (i * reg.dim_increment)
                    self.regs[offset] = reg.reset_value
                    self._svd_regs[offset] = reg
            else:
                self.regs[reg.address_offset] = reg.reset_value
                self._svd_regs[reg.address_offset] = reg

        if auto_ready:
            self._detect_ready_bits(svd_periph)

    def _detect_ready_bits(self, svd_periph: SVDPeripheral):
        """
        Auto-detect ready/status bits that should mirror enable bits.

        Common patterns:
        - RCC: HSION -> HSIRDY, PLLON -> PLLRDY, etc.
        - PWR: VOS -> VOSRDY
        - FLASH: any write -> BSY cleared
        - Generic: *EN -> *RDY, *ON -> *RDY
        """
        for reg in svd_periph.registers:
            if reg.dim > 0:
                continue
            for field in reg.fields:
                fname = field.name.upper()
                # Pattern: xxxON -> xxxRDY (same register)
                if fname.endswith('ON'):
                    prefix = fname[:-2]
                    rdy_field = None
                    for f2 in reg.fields:
                        if f2.name.upper() == prefix + 'RDY':
                            rdy_field = f2
                            break
                    if rdy_field:
                        # When enable bit is set, auto-set ready bit
                        self._ready_rules.append((
                            reg.address_offset, field.bit_mask,
                            reg.address_offset, rdy_field.bit_mask,
                        ))

                # Pattern: xxxEN -> xxxRDY (same register)
                if fname.endswith('EN') and not fname.endswith('DIEN') \
                        and not fname.endswith('TIEN'):
                    prefix = fname[:-2]
                    for f2 in reg.fields:
                        f2name = f2.name.upper()
                        if f2name == prefix + 'RDY' or f2name == prefix + 'F':
                            self._ready_rules.append((
                                reg.address_offset, field.bit_mask,
                                reg.address_offset, f2.bit_mask,
                            ))
                            break

        # Cross-register patterns: CR -> SR ready bits
        cr_reg = None
        sr_reg = None
        for reg in svd_periph.registers:
            rname = reg.name.upper()
            if rname in ('CR', 'CR1', 'CTL', 'CTL0'):
                cr_reg = reg
            elif rname in ('SR', 'SR1', 'ISR', 'STAT', 'STAT0'):
                sr_reg = reg

        if cr_reg and sr_reg and cr_reg.address_offset != sr_reg.address_offset:
            for cf in cr_reg.fields:
                cfname = cf.name.upper()
                if cfname.endswith('EN') or cfname.endswith('ON'):
                    prefix = cfname[:-2] if cfname.endswith('ON') else cfname[:-2]
                    for sf in sr_reg.fields:
                        sfname = sf.name.upper()
                        if sfname == prefix + 'RDY' or sfname == prefix + 'F':
                            self._ready_rules.append((
                                cr_reg.address_offset, cf.bit_mask,
                                sr_reg.address_offset, sf.bit_mask,
                            ))
                            break

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    def read(self, addr: int, size: int) -> Tuple[int, int]:
        offset = addr - self.base
        value = self.regs.get(offset, 0)
        # Mask to requested size
        if size == 1:
            value &= 0xFF
        elif size == 2:
            value &= 0xFFFF
        return (value, STATUS_OK)

    def write(self, addr: int, size: int, value: int) -> int:
        offset = addr - self.base
        svd_reg = self._svd_regs.get(offset)

        # Respect read-only registers
        if svd_reg and svd_reg.access == 'read-only':
            return STATUS_OK

        # Store value
        if size == 1:
            old = self.regs.get(offset, 0)
            self.regs[offset] = (old & ~0xFF) | (value & 0xFF)
        elif size == 2:
            old = self.regs.get(offset, 0)
            self.regs[offset] = (old & ~0xFFFF) | (value & 0xFFFF)
        else:
            self.regs[offset] = value & 0xFFFFFFFF

        # Apply ready-bit rules
        for src_off, src_mask, dst_off, dst_mask in self._ready_rules:
            if offset == src_off:
                if self.regs.get(src_off, 0) & src_mask:
                    # Enable bit set -> set ready bit
                    self.regs[dst_off] = self.regs.get(dst_off, 0) | dst_mask
                else:
                    # Enable bit cleared -> clear ready bit
                    self.regs[dst_off] = self.regs.get(dst_off, 0) & ~dst_mask

        return STATUS_OK

    def trigger_irq(self, level: int = 1):
        if self.irq >= 0 and self.irq_callback:
            self.irq_callback(self.irq, level)

    def reset(self):
        """Reset all registers to SVD reset values."""
        for offset, reg in self._svd_regs.items():
            self.regs[offset] = reg.reset_value


class SVDStubPeripheralSet:
    """
    Complete peripheral set auto-generated from SVD.

    Drop-in replacement for hand-coded peripheral sets like
    STM32F405PeripheralSet. Uses SVD register definitions for
    reset values and access attributes.
    """

    def __init__(self, device: SVDDevice, auto_ready: bool = True):
        self.name = device.name
        self.device = device
        self.peripherals: List[SVDStubPeripheral] = []
        self._by_name: Dict[str, SVDStubPeripheral] = {}
        self.irq_callback: Optional[Callable] = None

        # Create stub peripherals for each SVD peripheral
        for svd_p in device.peripherals:
            # Skip internal ARM peripherals (NVIC, SCB, etc.)
            if svd_p.base_address >= 0xE0000000:
                continue
            stub = SVDStubPeripheral(svd_p, auto_ready=auto_ready)
            self.peripherals.append(stub)
            self._by_name[stub.name] = stub

        log.info(f"Created SVD stub set '{self.name}' with "
                 f"{len(self.peripherals)} peripherals")

    @classmethod
    def from_svd(cls, svd_path: str, auto_ready: bool = True) -> 'SVDStubPeripheralSet':
        """Create peripheral set from an SVD file path."""
        parser = SVDParser()
        device = parser.parse(svd_path)
        return cls(device, auto_ready=auto_ready)

    def find_peripheral(self, addr: int) -> Optional[SVDStubPeripheral]:
        for p in self.peripherals:
            if p.contains(addr):
                return p
        return None

    def read(self, addr: int, size: int) -> Tuple[int, int]:
        p = self.find_peripheral(addr)
        if p:
            return p.read(addr, size)
        return (0, STATUS_OK)

    def write(self, addr: int, size: int, value: int) -> int:
        p = self.find_peripheral(addr)
        if p:
            return p.write(addr, size, value)
        return STATUS_OK

    def setup_irq_callback(self, callback: Callable):
        self.irq_callback = callback
        for p in self.peripherals:
            p.irq_callback = callback

    def get_peripheral(self, name: str) -> Optional[SVDStubPeripheral]:
        return self._by_name.get(name)

    def reset(self):
        for p in self.peripherals:
            p.reset()

    def get_memory_info(self) -> Dict[str, Any]:
        """
        Extract memory layout from SVD device info.

        Returns dict with flash_base, flash_size, sram_base, sram_size,
        cpu_type, periph_base, periph_size.
        """
        info = {
            'cpu_type': _map_svd_cpu(self.device.cpu_name),
            'flash_base': 0x08000000,
            'flash_size': 0x100000,
            'sram_base': 0x20000000,
            'sram_size': 0x20000,
            'periph_base': 0x40000000,
            'periph_size': 0x20000000,
        }

        # Detect memory layout from peripheral addresses
        min_periph = 0xFFFFFFFF
        max_periph = 0
        for p in self.peripherals:
            if p.base < 0xE0000000:  # Skip ARM internal
                min_periph = min(min_periph, p.base)
                max_periph = max(max_periph, p.base + p.size)

        if min_periph < 0xFFFFFFFF:
            info['periph_base'] = min_periph & 0xF0000000  # Align to 256MB
            info['periph_size'] = max_periph - info['periph_base']
            # Round up to power of 2
            size = info['periph_size']
            power = 1
            while power < size:
                power <<= 1
            info['periph_size'] = power

        # Detect flash base from vendor conventions
        device_name = self.device.name.upper()
        if 'NRF' in device_name or 'NRF' in self.device.vendor.upper():
            info['flash_base'] = 0x00000000
            info['flash_size'] = 0x100000
            info['sram_base'] = 0x20000000
            info['sram_size'] = 0x40000
        elif 'RP20' in device_name:
            info['flash_base'] = 0x10000000
            info['flash_size'] = 0x200000
            info['sram_base'] = 0x20000000
            info['sram_size'] = 0x42000
        elif 'LPC' in device_name or 'IMXRT' in device_name:
            info['flash_base'] = 0x00000000
            info['flash_size'] = 0x80000
            info['sram_base'] = 0x20000000
            info['sram_size'] = 0x20000
        # STM32 defaults (0x08000000) are already set

        return info


def _map_svd_cpu(cpu_name: str) -> str:
    """Map SVD CPU name to QEMU cpu-type property."""
    cpu = cpu_name.lower().replace(' ', '')
    # Check longer matches first to avoid cm3 matching cm33
    if 'cm85' in cpu:
        return 'cortex-m85'
    if 'cm55' in cpu:
        return 'cortex-m55'
    if 'cm33' in cpu:
        return 'cortex-m33'
    if 'cm23' in cpu:
        return 'cortex-m23'
    if 'cm0+' in cpu or 'cm0plus' in cpu:
        return 'cortex-m0'  # QEMU has no M0+
    if 'cm7' in cpu:
        return 'cortex-m7'
    if 'cm4' in cpu:
        return 'cortex-m4'
    if 'cm3' in cpu:
        return 'cortex-m3'
    if 'cm0' in cpu:
        return 'cortex-m0'
    return 'cortex-m4'
