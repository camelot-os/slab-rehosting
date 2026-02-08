#!/usr/bin/env python3
"""
RP2040 Bootrom Emulation - Detailed Analysis Test

Comprehensive logging of all peripheral interactions for analysis.
Generates a detailed report of the emulation capabilities.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import json
import logging
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

# Add python directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# Configure detailed logging
LOG_FORMAT = '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)-20s | %(message)s'
DATE_FORMAT = '%H:%M:%S'

# Create file handler for detailed log
log_file = Path(__file__).parent.parent / "results" / "rp2040_bootrom_test.log"
log_file.parent.mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.FileHandler(log_file, mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)

log = logging.getLogger('BootromTest')


@dataclass
class RegisterAccess:
    """Record of a register access."""
    timestamp: float
    peripheral: str
    address: int
    offset: int
    operation: str  # 'read' or 'write'
    value: int
    size: int


@dataclass
class PeripheralState:
    """Captured state of a peripheral."""
    name: str
    base: int
    registers: Dict[str, int] = field(default_factory=dict)
    status: str = "unknown"


@dataclass
class TestResult:
    """Result of a single test."""
    name: str
    passed: bool
    duration_ms: float
    details: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class TestReport:
    """Complete test report."""
    timestamp: str
    platform: str
    total_tests: int
    passed: int
    failed: int
    duration_ms: float
    tests: List[TestResult] = field(default_factory=list)
    peripheral_states: Dict[str, PeripheralState] = field(default_factory=dict)
    register_accesses: List[RegisterAccess] = field(default_factory=list)


class PeripheralLogger:
    """Wrapper to log all peripheral accesses."""

    def __init__(self, peripheral, tracker: List[RegisterAccess]):
        self._peripheral = peripheral
        self._tracker = tracker
        self._start_time = time.time()

    def read(self, addr: int, size: int) -> tuple:
        offset = addr - self._peripheral.base
        result = self._peripheral.read(addr, size)
        value = result[0] if isinstance(result, tuple) else result

        access = RegisterAccess(
            timestamp=time.time() - self._start_time,
            peripheral=self._peripheral.name,
            address=addr,
            offset=offset,
            operation='read',
            value=value,
            size=size
        )
        self._tracker.append(access)

        log.debug(f"[{self._peripheral.name}] READ  0x{addr:08x} (+0x{offset:03x}) = 0x{value:08x}")
        return result

    def write(self, addr: int, size: int, value: int) -> int:
        offset = addr - self._peripheral.base

        access = RegisterAccess(
            timestamp=time.time() - self._start_time,
            peripheral=self._peripheral.name,
            address=addr,
            offset=offset,
            operation='write',
            value=value,
            size=size
        )
        self._tracker.append(access)

        log.debug(f"[{self._peripheral.name}] WRITE 0x{addr:08x} (+0x{offset:03x}) = 0x{value:08x}")
        return self._peripheral.write(addr, size, value)

    def __getattr__(self, name):
        return getattr(self._peripheral, name)


class RP2040BootromAnalyzer:
    """Comprehensive analyzer for RP2040 bootrom emulation."""

    def __init__(self):
        self.report = TestReport(
            timestamp=datetime.now().isoformat(),
            platform="RP2040",
            total_tests=0,
            passed=0,
            failed=0,
            duration_ms=0
        )
        self.peripherals = {}
        self.start_time = None

    def setup_peripherals(self):
        """Initialize all peripherals with logging wrappers."""
        log.info("=" * 70)
        log.info("  INITIALIZING RP2040 PERIPHERALS")
        log.info("=" * 70)

        from slab_rp2040.rp2040_misc import (
            RP2040ROSC, RP2040XOSC, RP2040PLL, RP2040CLOCKS,
            RP2040RESETS, RP2040PSM, RP2040WATCHDOG, RP2040SYSINFO,
            RP2040SYSCFG, RP2040VREG, RP2040TBMAN, RP2040BUSCTRL,
            RP2040XIP, RP2040SSI, RP2040USB, RP2040RTC
        )

        # Create raw peripherals
        raw_peripherals = {
            'ROSC': RP2040ROSC(),
            'XOSC': RP2040XOSC(),
            'PLL_SYS': RP2040PLL("PLL_SYS", 0x40028000, 125000000),
            'PLL_USB': RP2040PLL("PLL_USB", 0x4002c000, 48000000),
            'CLOCKS': RP2040CLOCKS(),
            'RESETS': RP2040RESETS(),
            'PSM': RP2040PSM(),
            'WATCHDOG': RP2040WATCHDOG(),
            'SYSINFO': RP2040SYSINFO(),
            'SYSCFG': RP2040SYSCFG(),
            'VREG': RP2040VREG(),
            'TBMAN': RP2040TBMAN(),
            'BUSCTRL': RP2040BUSCTRL(),
            'XIP': RP2040XIP(),
            'SSI': RP2040SSI(),
            'USB': RP2040USB(),
            'RTC': RP2040RTC(),
        }

        # Wrap with logging
        for name, periph in raw_peripherals.items():
            self.peripherals[name] = PeripheralLogger(periph, self.report.register_accesses)
            log.info(f"  {name:12} @ 0x{periph.base:08x} (size: 0x{periph.size:x})")

        # Setup reset callbacks
        def on_reset(source):
            log.warning(f"SYSTEM RESET triggered by {source}")

        raw_peripherals['WATCHDOG'].on_system_reset = on_reset
        raw_peripherals['VREG'].on_system_reset = on_reset

        log.info(f"\nTotal peripherals initialized: {len(self.peripherals)}")
        return raw_peripherals

    def capture_peripheral_state(self, name: str, periph) -> PeripheralState:
        """Capture current state of a peripheral."""
        state = PeripheralState(name=name, base=periph.base)

        # Read key registers based on peripheral type
        register_maps = {
            'ROSC': {'CTRL': 0x00, 'STATUS': 0x18, 'DIV': 0x10},
            'XOSC': {'CTRL': 0x00, 'STATUS': 0x04, 'STARTUP': 0x0C},
            'PLL_SYS': {'CS': 0x00, 'PWR': 0x04, 'FBDIV': 0x08, 'PRIM': 0x0C},
            'PLL_USB': {'CS': 0x00, 'PWR': 0x04, 'FBDIV': 0x08, 'PRIM': 0x0C},
            'CLOCKS': {'REF_CTRL': 0x30, 'REF_SEL': 0x38, 'SYS_CTRL': 0x3C, 'SYS_SEL': 0x44},
            'RESETS': {'RESET': 0x00, 'WDSEL': 0x04, 'RESET_DONE': 0x08},
            'PSM': {'FRCE_ON': 0x00, 'FRCE_OFF': 0x04, 'DONE': 0x0C},
            'WATCHDOG': {'CTRL': 0x00, 'REASON': 0x08, 'TICK': 0x2C},
            'SYSINFO': {'CHIP_ID': 0x00, 'PLATFORM': 0x04},
            'VREG': {'VREG': 0x00, 'BOD': 0x04, 'CHIP_RESET': 0x08},
        }

        if name in register_maps:
            for reg_name, offset in register_maps[name].items():
                try:
                    val, _ = periph.read(periph.base + offset, 4)
                    state.registers[reg_name] = val
                except:
                    state.registers[reg_name] = 0

        return state

    def run_test(self, name: str, test_func) -> TestResult:
        """Run a single test with timing and error capture."""
        log.info("")
        log.info("-" * 70)
        log.info(f"  TEST: {name}")
        log.info("-" * 70)

        start = time.time()
        result = TestResult(name=name, passed=False, duration_ms=0)

        try:
            details = test_func()
            result.passed = True
            result.details = details if isinstance(details, dict) else {}
            log.info(f"  RESULT: PASSED")
        except AssertionError as e:
            result.errors.append(str(e))
            log.error(f"  RESULT: FAILED - {e}")
        except Exception as e:
            result.errors.append(f"{type(e).__name__}: {e}")
            log.error(f"  RESULT: ERROR - {type(e).__name__}: {e}")

        result.duration_ms = (time.time() - start) * 1000
        log.info(f"  Duration: {result.duration_ms:.2f} ms")

        return result

    def test_power_on_sequence(self) -> dict:
        """Test the power-on sequence (PSM)."""
        psm = self.peripherals['PSM']

        # Check all power domains are done
        done, _ = psm.read(0x40010000 + 0x0C, 4)

        domains = {
            'ROSC': bool(done & (1 << 0)),
            'XOSC': bool(done & (1 << 1)),
            'CLOCKS': bool(done & (1 << 2)),
            'RESETS': bool(done & (1 << 3)),
            'BUSFABRIC': bool(done & (1 << 4)),
            'ROM': bool(done & (1 << 5)),
            'SRAM0': bool(done & (1 << 6)),
            'SRAM1': bool(done & (1 << 7)),
            'SRAM2': bool(done & (1 << 8)),
            'SRAM3': bool(done & (1 << 9)),
            'SRAM4': bool(done & (1 << 10)),
            'SRAM5': bool(done & (1 << 11)),
            'XIP': bool(done & (1 << 12)),
            'VREG': bool(done & (1 << 13)),
            'SIO': bool(done & (1 << 14)),
            'PROC0': bool(done & (1 << 15)),
            'PROC1': bool(done & (1 << 16)),
        }

        for name, status in domains.items():
            log.info(f"    {name:12}: {'READY' if status else 'NOT READY'}")

        assert done == 0x1FFFF, f"Not all power domains ready: 0x{done:08x}"

        return {'psm_done': done, 'domains': domains}

    def test_clock_initialization(self) -> dict:
        """Test clock initialization sequence."""
        rosc = self.peripherals['ROSC']
        xosc = self.peripherals['XOSC']
        pll_sys = self.peripherals['PLL_SYS']
        pll_usb = self.peripherals['PLL_USB']
        clocks = self.peripherals['CLOCKS']

        results = {}

        # Step 1: Check ROSC is running
        log.info("  [1/6] Checking ROSC...")
        rosc_status, _ = rosc.read(0x40060000 + 0x18, 4)
        rosc_stable = bool(rosc_status & (1 << 31))
        rosc_enabled = bool(rosc_status & (1 << 12))
        log.info(f"        ROSC STATUS=0x{rosc_status:08x} STABLE={rosc_stable} ENABLED={rosc_enabled}")
        results['rosc'] = {'status': rosc_status, 'stable': rosc_stable}
        assert rosc_stable, "ROSC not stable"

        # Step 2: Enable XOSC
        log.info("  [2/6] Enabling XOSC...")
        xosc.write(0x40024000 + 0x0C, 4, 0xC4)  # STARTUP delay
        xosc.write(0x40024000 + 0x00, 4, 0xFABAA0)  # Enable with magic
        xosc_status, _ = xosc.read(0x40024000 + 0x04, 4)
        xosc_stable = bool(xosc_status & (1 << 31))
        log.info(f"        XOSC STATUS=0x{xosc_status:08x} STABLE={xosc_stable}")
        results['xosc'] = {'status': xosc_status, 'stable': xosc_stable}
        assert xosc_stable, "XOSC not stable"

        # Step 3: Configure PLL_SYS (125 MHz)
        log.info("  [3/6] Configuring PLL_SYS for 125 MHz...")
        log.info("        REFDIV=1, FBDIV=125, POSTDIV1=6, POSTDIV2=2")
        log.info("        Output = 12MHz * 125 / 6 / 2 = 125 MHz")
        pll_sys.write(0x40028000 + 0x08, 4, 125)  # FBDIV
        pll_sys.write(0x40028000 + 0x0C, 4, (6 << 16) | (2 << 12))  # PRIM
        pll_sys.write(0x40028000 + 0x04, 4, 0)  # Power on
        pll_cs, _ = pll_sys.read(0x40028000 + 0x00, 4)
        pll_locked = bool(pll_cs & (1 << 31))
        log.info(f"        PLL_SYS CS=0x{pll_cs:08x} LOCKED={pll_locked}")
        results['pll_sys'] = {'cs': pll_cs, 'locked': pll_locked, 'freq_mhz': 125}
        assert pll_locked, "PLL_SYS not locked"

        # Step 4: Configure PLL_USB (48 MHz)
        log.info("  [4/6] Configuring PLL_USB for 48 MHz...")
        log.info("        REFDIV=1, FBDIV=100, POSTDIV1=5, POSTDIV2=5")
        log.info("        Output = 12MHz * 100 / 5 / 5 = 48 MHz")
        pll_usb.write(0x4002c000 + 0x08, 4, 100)  # FBDIV
        pll_usb.write(0x4002c000 + 0x0C, 4, (5 << 16) | (5 << 12))  # PRIM
        pll_usb.write(0x4002c000 + 0x04, 4, 0)  # Power on
        pll_cs, _ = pll_usb.read(0x4002c000 + 0x00, 4)
        pll_locked = bool(pll_cs & (1 << 31))
        log.info(f"        PLL_USB CS=0x{pll_cs:08x} LOCKED={pll_locked}")
        results['pll_usb'] = {'cs': pll_cs, 'locked': pll_locked, 'freq_mhz': 48}
        assert pll_locked, "PLL_USB not locked"

        # Step 5: Switch CLK_REF to XOSC
        log.info("  [5/6] Switching CLK_REF to XOSC...")
        clocks.write(0x40008000 + 0x30, 4, 0x2)  # SRC=XOSC (2)
        ref_sel, _ = clocks.read(0x40008000 + 0x38, 4)
        log.info(f"        CLK_REF_SELECTED=0x{ref_sel:x}")
        results['clk_ref'] = {'selected': ref_sel}

        # Step 6: Switch CLK_SYS to PLL
        log.info("  [6/6] Switching CLK_SYS to PLL_SYS...")
        clocks.write(0x40008000 + 0x3C, 4, 0x1)  # SRC=AUX (PLL)
        sys_sel, _ = clocks.read(0x40008000 + 0x44, 4)
        log.info(f"        CLK_SYS_SELECTED=0x{sys_sel:x}")
        results['clk_sys'] = {'selected': sys_sel}

        return results

    def test_peripheral_reset_sequence(self) -> dict:
        """Test peripheral reset/unreset sequence."""
        resets = self.peripherals['RESETS']

        results = {}

        # Check initial state
        reset_reg, _ = resets.read(0x4000c000 + 0x00, 4)
        reset_done, _ = resets.read(0x4000c000 + 0x08, 4)
        log.info(f"  Initial: RESET=0x{reset_reg:08x} DONE=0x{reset_done:08x}")

        # Define peripheral groups
        peripheral_bits = {
            'ADC': 0, 'BUSCTRL': 1, 'DMA': 2, 'I2C0': 3, 'I2C1': 4,
            'IO_BANK0': 5, 'IO_QSPI': 6, 'JTAG': 7, 'PADS_BANK0': 8,
            'PADS_QSPI': 9, 'PIO0': 10, 'PIO1': 11, 'PLL_SYS': 12,
            'PLL_USB': 13, 'PWM': 14, 'RTC': 15, 'SPI0': 16, 'SPI1': 17,
            'SYSCFG': 18, 'SYSINFO': 19, 'TBMAN': 20, 'TIMER': 21,
            'UART0': 22, 'UART1': 23, 'USBCTRL': 24
        }

        # Release critical peripherals for bootrom
        critical = ['IO_BANK0', 'IO_QSPI', 'PADS_BANK0', 'PADS_QSPI',
                   'PLL_SYS', 'PLL_USB', 'USBCTRL']

        release_mask = 0
        for name in critical:
            release_mask |= (1 << peripheral_bits[name])

        log.info(f"  Releasing critical peripherals: {critical}")
        log.info(f"  Release mask: 0x{release_mask:08x}")

        new_reset = reset_reg & ~release_mask
        resets.write(0x4000c000 + 0x00, 4, new_reset)

        # Verify release
        reset_done, _ = resets.read(0x4000c000 + 0x08, 4)
        log.info(f"  After release: RESET_DONE=0x{reset_done:08x}")

        released = []
        still_reset = []
        for name, bit in peripheral_bits.items():
            if reset_done & (1 << bit):
                released.append(name)
            else:
                still_reset.append(name)

        log.info(f"  Released: {released}")
        log.info(f"  Still in reset: {still_reset}")

        results['released'] = released
        results['in_reset'] = still_reset
        results['reset_done'] = reset_done

        # Verify critical peripherals are released
        for name in critical:
            bit = peripheral_bits[name]
            assert reset_done & (1 << bit), f"{name} not released from reset"

        return results

    def test_timer_tick_setup(self) -> dict:
        """Test timer tick configuration."""
        watchdog = self.peripherals['WATCHDOG']

        results = {}

        # Read initial TICK state
        tick, _ = watchdog.read(0x40058000 + 0x2C, 4)
        log.info(f"  Initial TICK: 0x{tick:08x}")

        # Configure TICK for 1MHz from 12MHz XOSC
        # cycles = 12 (12MHz / 12 = 1MHz)
        log.info("  Configuring TICK: 12MHz / 12 = 1MHz")
        watchdog.write(0x40058000 + 0x2C, 4, (1 << 9) | 12)

        tick, _ = watchdog.read(0x40058000 + 0x2C, 4)
        running = bool(tick & (1 << 10))
        enabled = bool(tick & (1 << 9))
        cycles = tick & 0x1FF

        log.info(f"  TICK after config: 0x{tick:08x}")
        log.info(f"    RUNNING: {running}")
        log.info(f"    ENABLED: {enabled}")
        log.info(f"    CYCLES:  {cycles}")

        results['tick'] = tick
        results['running'] = running
        results['enabled'] = enabled
        results['cycles'] = cycles
        results['output_freq_mhz'] = 12 / cycles if cycles > 0 else 0

        assert enabled, "TICK not enabled"
        assert running, "TICK not running"
        assert cycles == 12, f"TICK cycles wrong: {cycles}"

        return results

    def test_chip_identification(self) -> dict:
        """Test chip identification registers."""
        sysinfo = self.peripherals['SYSINFO']
        tbman = self.peripherals['TBMAN']

        results = {}

        # Read CHIP_ID
        chip_id, _ = sysinfo.read(0x40000000 + 0x00, 4)
        platform, _ = sysinfo.read(0x40000000 + 0x04, 4)

        # Decode CHIP_ID
        revision = (chip_id >> 28) & 0xF
        part = (chip_id >> 12) & 0xFFFF
        manufacturer = (chip_id >> 1) & 0x7FF

        log.info(f"  CHIP_ID: 0x{chip_id:08x}")
        log.info(f"    Revision:     {revision}")
        log.info(f"    Part:         0x{part:04x} ({'RP2040' if part == 0x2040 else 'Unknown'})")
        log.info(f"    Manufacturer: 0x{manufacturer:03x} ({'Raspberry Pi' if manufacturer == 0x14D else 'Unknown'})")

        log.info(f"  PLATFORM: 0x{platform:08x}")
        log.info(f"    ASIC: {bool(platform & 2)}")
        log.info(f"    FPGA: {bool(platform & 1)}")

        # TBMAN platform
        tbman_platform, _ = tbman.read(0x4006c000 + 0x00, 4)
        log.info(f"  TBMAN PLATFORM: {tbman_platform}")

        results['chip_id'] = chip_id
        results['part'] = part
        results['manufacturer'] = manufacturer
        results['revision'] = revision
        results['platform'] = platform
        results['is_asic'] = bool(platform & 2)

        assert part == 0x2040, f"Wrong part number: 0x{part:04x}"

        return results

    def test_watchdog_scratch_registers(self) -> dict:
        """Test watchdog scratch registers (used for boot flags)."""
        watchdog = self.peripherals['WATCHDOG']

        results = {}

        # Write test patterns to all 8 scratch registers
        log.info("  Writing test patterns to SCRATCH0-7...")
        test_values = [0xDEADBEEF, 0xCAFEBABE, 0x12345678, 0x87654321,
                      0xAAAA5555, 0x5555AAAA, 0xFFFF0000, 0x0000FFFF]

        for i, val in enumerate(test_values):
            offset = 0x0C + i * 4
            watchdog.write(0x40058000 + offset, 4, val)

        # Read back and verify
        log.info("  Reading back scratch registers...")
        read_values = []
        for i in range(8):
            offset = 0x0C + i * 4
            val, _ = watchdog.read(0x40058000 + offset, 4)
            read_values.append(val)
            match = "OK" if val == test_values[i] else "MISMATCH"
            log.info(f"    SCRATCH{i}: wrote 0x{test_values[i]:08x}, read 0x{val:08x} [{match}]")

        results['test_values'] = test_values
        results['read_values'] = read_values
        results['all_match'] = read_values == test_values

        assert read_values == test_values, "Scratch register mismatch"

        return results

    def test_system_reset_mechanism(self) -> dict:
        """Test system reset trigger mechanism."""
        watchdog = self.peripherals['WATCHDOG']
        vreg = self.peripherals['VREG']

        results = {}
        reset_triggered = []

        def on_reset(source):
            reset_triggered.append(source)
            log.warning(f"  >>> RESET TRIGGERED by {source}")

        # Setup callbacks on raw peripherals
        watchdog._peripheral.on_system_reset = on_reset
        vreg._peripheral.on_system_reset = on_reset

        # Check reset reason register
        reason, _ = watchdog.read(0x40058000 + 0x08, 4)
        log.info(f"  Current reset REASON: 0x{reason:08x}")

        # Check VREG CHIP_RESET status
        chip_reset, _ = vreg.read(0x40064000 + 0x08, 4)
        log.info(f"  VREG CHIP_RESET: 0x{chip_reset:08x}")
        log.info(f"    HAD_POR: {bool(chip_reset & (1 << 24))}")
        log.info(f"    HAD_RUN: {bool(chip_reset & (1 << 20))}")
        log.info(f"    HAD_PSM: {bool(chip_reset & (1 << 16))}")

        # Test watchdog trigger (don't actually trigger in this test)
        log.info("  Watchdog TRIGGER bit is at CTRL[31]")
        log.info("  Writing CTRL with TRIGGER=1 would reset the system")

        results['reset_reason'] = reason
        results['chip_reset'] = chip_reset
        results['had_por'] = bool(chip_reset & (1 << 24))
        results['reset_mechanism'] = 'available'

        return results

    def test_usb_controller_init(self) -> dict:
        """Test USB controller initialization."""
        usb = self.peripherals['USB']

        results = {}

        # Read initial state
        main_ctrl, _ = usb.read(0x50110000 + 0x40, 4)
        sie_ctrl, _ = usb.read(0x50110000 + 0x4C, 4)
        sie_status, _ = usb.read(0x50110000 + 0x50, 4)

        log.info(f"  Initial USB state:")
        log.info(f"    MAIN_CTRL:  0x{main_ctrl:08x}")
        log.info(f"    SIE_CTRL:   0x{sie_ctrl:08x}")
        log.info(f"    SIE_STATUS: 0x{sie_status:08x}")

        # Enable USB controller
        log.info("  Enabling USB controller...")
        usb.write(0x50110000 + 0x40, 4, 1)  # CONTROLLER_EN

        main_ctrl, _ = usb.read(0x50110000 + 0x40, 4)
        log.info(f"    MAIN_CTRL after enable: 0x{main_ctrl:08x}")

        # Enable pull-up (device mode)
        log.info("  Enabling USB pull-up (device mode)...")
        usb.write(0x50110000 + 0x4C, 4, 1 << 16)  # PULLUP_EN

        sie_status, _ = usb.read(0x50110000 + 0x50, 4)
        connected = bool(sie_status & (1 << 16))
        log.info(f"    SIE_STATUS: 0x{sie_status:08x}")
        log.info(f"    CONNECTED: {connected}")

        results['main_ctrl'] = main_ctrl
        results['sie_status'] = sie_status
        results['connected'] = connected

        return results

    def run_all_tests(self):
        """Run all tests and generate report."""
        log.info("=" * 70)
        log.info("  RP2040 BOOTROM EMULATION - DETAILED ANALYSIS")
        log.info("=" * 70)
        log.info(f"  Timestamp: {self.report.timestamp}")
        log.info("")

        self.start_time = time.time()

        # Initialize peripherals
        raw_peripherals = self.setup_peripherals()

        # Define tests
        tests = [
            ("Power-On Sequence (PSM)", self.test_power_on_sequence),
            ("Clock Initialization", self.test_clock_initialization),
            ("Peripheral Reset Sequence", self.test_peripheral_reset_sequence),
            ("Timer Tick Setup", self.test_timer_tick_setup),
            ("Chip Identification", self.test_chip_identification),
            ("Watchdog Scratch Registers", self.test_watchdog_scratch_registers),
            ("System Reset Mechanism", self.test_system_reset_mechanism),
            ("USB Controller Init", self.test_usb_controller_init),
        ]

        # Run tests
        for name, test_func in tests:
            result = self.run_test(name, test_func)
            self.report.tests.append(result)
            self.report.total_tests += 1
            if result.passed:
                self.report.passed += 1
            else:
                self.report.failed += 1

        # Capture final peripheral states
        log.info("")
        log.info("=" * 70)
        log.info("  FINAL PERIPHERAL STATES")
        log.info("=" * 70)

        for name, periph in self.peripherals.items():
            state = self.capture_peripheral_state(name, periph._peripheral)
            self.report.peripheral_states[name] = state
            if state.registers:
                log.info(f"  {name}:")
                for reg, val in state.registers.items():
                    log.info(f"    {reg:15} = 0x{val:08x}")

        # Calculate total duration
        self.report.duration_ms = (time.time() - self.start_time) * 1000

        # Summary
        log.info("")
        log.info("=" * 70)
        log.info("  TEST SUMMARY")
        log.info("=" * 70)
        log.info(f"  Total tests:  {self.report.total_tests}")
        log.info(f"  Passed:       {self.report.passed}")
        log.info(f"  Failed:       {self.report.failed}")
        log.info(f"  Duration:     {self.report.duration_ms:.2f} ms")
        log.info(f"  Reg accesses: {len(self.report.register_accesses)}")
        log.info("")

        for test in self.report.tests:
            status = "PASS" if test.passed else "FAIL"
            log.info(f"  [{status}] {test.name} ({test.duration_ms:.2f} ms)")
            if test.errors:
                for err in test.errors:
                    log.info(f"         Error: {err}")

        log.info("=" * 70)

        return self.report

    def save_report(self, filepath: Path):
        """Save report to JSON file."""
        # Convert dataclasses to dicts
        report_dict = {
            'timestamp': self.report.timestamp,
            'platform': self.report.platform,
            'total_tests': self.report.total_tests,
            'passed': self.report.passed,
            'failed': self.report.failed,
            'duration_ms': self.report.duration_ms,
            'tests': [asdict(t) for t in self.report.tests],
            'peripheral_states': {
                name: asdict(state)
                for name, state in self.report.peripheral_states.items()
            },
            'register_access_count': len(self.report.register_accesses),
            'register_accesses': [
                {
                    'time_ms': a.timestamp * 1000,
                    'peripheral': a.peripheral,
                    'address': f"0x{a.address:08x}",
                    'offset': f"0x{a.offset:03x}",
                    'op': a.operation,
                    'value': f"0x{a.value:08x}",
                    'size': a.size
                }
                for a in self.report.register_accesses[:500]  # Limit to first 500
            ]
        }

        with open(filepath, 'w') as f:
            json.dump(report_dict, f, indent=2)

        log.info(f"Report saved to: {filepath}")


def main():
    """Main entry point."""
    print("\n" + "=" * 70)
    print("  RP2040 BOOTROM EMULATION - DETAILED ANALYSIS")
    print("=" * 70 + "\n")

    analyzer = RP2040BootromAnalyzer()
    report = analyzer.run_all_tests()

    # Save JSON report
    report_file = Path(__file__).parent.parent / "results" / "rp2040_bootrom_report.json"
    analyzer.save_report(report_file)

    # Print locations
    print(f"\nLog file:    {log_file}")
    print(f"Report file: {report_file}")

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
