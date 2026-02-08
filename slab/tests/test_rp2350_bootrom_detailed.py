#!/usr/bin/env python3
"""
RP2350 Bootrom Emulation - Detailed Analysis Test

Comprehensive logging of all peripheral interactions for analysis.
Generates a detailed report of the emulation capabilities.

Tests the RP2350-specific bootrom peripherals including:
- Clock system (ROSC, XOSC, PLLs at 150MHz)
- Reset controller (29 reset bits)
- Power-on state machine (18 domains)
- Security peripherals (TRNG, SHA256, OTP)
- TrustZone configuration

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
log_file = Path(__file__).parent.parent / "results" / "rp2350_bootrom_test.log"
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


class RP2350BootromAnalyzer:
    """Comprehensive analyzer for RP2350 bootrom emulation."""

    def __init__(self):
        self.report = TestReport(
            timestamp=datetime.now().isoformat(),
            platform="RP2350",
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
        log.info("  INITIALIZING RP2350 PERIPHERALS")
        log.info("=" * 70)

        from slab_rp2040.rp2350_peripherals import (
            RP2350SYSINFO, RP2350ROSC, RP2350XOSC, RP2350PLL, RP2350CLOCKS,
            RP2350RESETS, RP2350PSM, RP2350WATCHDOG, RP2350USB, RP2350BOOTRAM,
            RP2350SHA256, RP2350TRNG, RP2350OTP, RP2350OTPData, RP2350POWMAN,
            RP2350GlitchDetector, RP2350ACCESSCTRL, RP2350TICKS, RP2350QMI
        )

        # Create raw peripherals
        otp = RP2350OTP()
        raw_peripherals = {
            'SYSINFO': RP2350SYSINFO(),
            'ROSC': RP2350ROSC(),
            'XOSC': RP2350XOSC(),
            'PLL_SYS': RP2350PLL("PLL_SYS", 0x40050000, 150000000),
            'PLL_USB': RP2350PLL("PLL_USB", 0x40058000, 48000000),
            'CLOCKS': RP2350CLOCKS(),
            'RESETS': RP2350RESETS(),
            'PSM': RP2350PSM(),
            'WATCHDOG': RP2350WATCHDOG(),
            'USB': RP2350USB(),
            'BOOTRAM': RP2350BOOTRAM(),
            'SHA256': RP2350SHA256(),
            'TRNG': RP2350TRNG(),
            'OTP': otp,
            'OTP_DATA': RP2350OTPData(otp),
            'POWMAN': RP2350POWMAN(),
            'GLITCH_DET': RP2350GlitchDetector(),
            'ACCESSCTRL': RP2350ACCESSCTRL(),
            'TICKS': RP2350TICKS(),
            'QMI': RP2350QMI(),
        }

        # Wrap with logging
        for name, periph in raw_peripherals.items():
            self.peripherals[name] = PeripheralLogger(periph, self.report.register_accesses)
            log.info(f"  {name:12} @ 0x{periph.base:08x} (size: 0x{periph.size:x})")

        # Setup reset callbacks
        def on_reset(source):
            log.warning(f"SYSTEM RESET triggered by {source}")

        raw_peripherals['WATCHDOG'].on_system_reset = on_reset

        log.info(f"\nTotal peripherals initialized: {len(self.peripherals)}")
        return raw_peripherals

    def capture_peripheral_state(self, name: str, periph) -> PeripheralState:
        """Capture current state of a peripheral."""
        state = PeripheralState(name=name, base=periph.base)

        # Read key registers based on peripheral type
        register_maps = {
            'ROSC': {'CTRL': 0x00, 'STATUS': 0x14},
            'XOSC': {'CTRL': 0x00, 'STATUS': 0x04, 'STARTUP': 0x0C},
            'PLL_SYS': {'CS': 0x00, 'PWR': 0x04, 'FBDIV': 0x08, 'PRIM': 0x0C},
            'PLL_USB': {'CS': 0x00, 'PWR': 0x04, 'FBDIV': 0x08, 'PRIM': 0x0C},
            'CLOCKS': {'REF_CTRL': 0x30, 'REF_SEL': 0x38, 'SYS_CTRL': 0x3C, 'SYS_SEL': 0x44},
            'RESETS': {'RESET': 0x00, 'WDSEL': 0x04, 'RESET_DONE': 0x08},
            'PSM': {'FRCE_ON': 0x00, 'FRCE_OFF': 0x04, 'DONE': 0x0C},
            'WATCHDOG': {'CTRL': 0x00, 'REASON': 0x08, 'TICK': 0x2C},
            'SYSINFO': {'CHIP_ID': 0x00, 'PLATFORM': 0x08},
            'POWMAN': {'VREG_CTRL': 0x04, 'VREG_STS': 0x08, 'CHIP_RESET': 0x24},
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
        done, _ = psm.read(0x40018000 + 0x0C, 4)

        # RP2350 has 18 power domains
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
            'BOOTRAM': bool(done & (1 << 17)),
        }

        for name, status in domains.items():
            log.info(f"    {name:12}: {'READY' if status else 'NOT READY'}")

        assert done == 0x3FFFF, f"Not all power domains ready: 0x{done:08x}"

        return {'psm_done': done, 'domains': domains}

    def test_clock_initialization(self) -> dict:
        """Test clock initialization sequence for 150MHz."""
        rosc = self.peripherals['ROSC']
        xosc = self.peripherals['XOSC']
        pll_sys = self.peripherals['PLL_SYS']
        pll_usb = self.peripherals['PLL_USB']
        clocks = self.peripherals['CLOCKS']

        results = {}

        # Step 1: Check ROSC is running
        log.info("  [1/6] Checking ROSC...")
        rosc_status, _ = rosc.read(0x400E4000 + 0x14, 4)
        rosc_stable = bool(rosc_status & (1 << 31))
        rosc_enabled = bool(rosc_status & (1 << 12))
        log.info(f"        ROSC STATUS=0x{rosc_status:08x} STABLE={rosc_stable} ENABLED={rosc_enabled}")
        results['rosc'] = {'status': rosc_status, 'stable': rosc_stable}
        assert rosc_stable, "ROSC not stable"

        # Step 2: Enable XOSC
        log.info("  [2/6] Enabling XOSC...")
        xosc.write(0x40048000 + 0x0C, 4, 0xC4)  # STARTUP delay
        xosc.write(0x40048000 + 0x00, 4, 0xFABAA0)  # Enable with magic
        xosc_status, _ = xosc.read(0x40048000 + 0x04, 4)
        xosc_stable = bool(xosc_status & (1 << 31))
        log.info(f"        XOSC STATUS=0x{xosc_status:08x} STABLE={xosc_stable}")
        results['xosc'] = {'status': xosc_status, 'stable': xosc_stable}
        assert xosc_stable, "XOSC not stable"

        # Step 3: Configure PLL_SYS (150 MHz for RP2350)
        log.info("  [3/6] Configuring PLL_SYS for 150 MHz...")
        log.info("        REFDIV=1, FBDIV=125, POSTDIV1=5, POSTDIV2=2")
        log.info("        Output = 12MHz * 125 / 5 / 2 = 150 MHz")
        pll_sys.write(0x40050000 + 0x08, 4, 125)  # FBDIV
        pll_sys.write(0x40050000 + 0x0C, 4, (5 << 16) | (2 << 12))  # PRIM
        pll_sys.write(0x40050000 + 0x04, 4, 0)  # Power on (clear PD bits)
        pll_cs, _ = pll_sys.read(0x40050000 + 0x00, 4)
        pll_locked = bool(pll_cs & (1 << 31))
        log.info(f"        PLL_SYS CS=0x{pll_cs:08x} LOCKED={pll_locked}")
        results['pll_sys'] = {'cs': pll_cs, 'locked': pll_locked, 'freq_mhz': 150}
        assert pll_locked, "PLL_SYS not locked"

        # Step 4: Configure PLL_USB (48 MHz)
        log.info("  [4/6] Configuring PLL_USB for 48 MHz...")
        log.info("        REFDIV=1, FBDIV=100, POSTDIV1=5, POSTDIV2=5")
        log.info("        Output = 12MHz * 100 / 5 / 5 = 48 MHz")
        pll_usb.write(0x40058000 + 0x08, 4, 100)  # FBDIV
        pll_usb.write(0x40058000 + 0x0C, 4, (5 << 16) | (5 << 12))  # PRIM
        pll_usb.write(0x40058000 + 0x04, 4, 0)  # Power on
        pll_cs, _ = pll_usb.read(0x40058000 + 0x00, 4)
        pll_locked = bool(pll_cs & (1 << 31))
        log.info(f"        PLL_USB CS=0x{pll_cs:08x} LOCKED={pll_locked}")
        results['pll_usb'] = {'cs': pll_cs, 'locked': pll_locked, 'freq_mhz': 48}
        assert pll_locked, "PLL_USB not locked"

        # Step 5: Switch CLK_REF to XOSC
        log.info("  [5/6] Switching CLK_REF to XOSC...")
        clocks.write(0x40010000 + 0x30, 4, 0x2)  # SRC=XOSC (2)
        ref_sel, _ = clocks.read(0x40010000 + 0x38, 4)
        log.info(f"        CLK_REF_SELECTED=0x{ref_sel:x}")
        results['clk_ref'] = {'selected': ref_sel}

        # Step 6: Switch CLK_SYS to PLL
        log.info("  [6/6] Switching CLK_SYS to PLL_SYS...")
        clocks.write(0x40010000 + 0x3C, 4, 0x1)  # SRC=AUX (PLL)
        sys_sel, _ = clocks.read(0x40010000 + 0x44, 4)
        log.info(f"        CLK_SYS_SELECTED=0x{sys_sel:x}")
        results['clk_sys'] = {'selected': sys_sel}

        return results

    def test_peripheral_reset_sequence(self) -> dict:
        """Test peripheral reset/unreset sequence."""
        resets = self.peripherals['RESETS']

        results = {}

        # Check initial state
        reset_reg, _ = resets.read(0x40020000 + 0x00, 4)
        reset_done, _ = resets.read(0x40020000 + 0x08, 4)
        log.info(f"  Initial: RESET=0x{reset_reg:08x} DONE=0x{reset_done:08x}")

        # Define peripheral groups (RP2350 has 29 reset bits)
        peripheral_bits = {
            'ADC': 0, 'BUSCTRL': 1, 'DMA': 2, 'HSTX': 3, 'I2C0': 4, 'I2C1': 5,
            'IO_BANK0': 6, 'IO_QSPI': 7, 'JTAG': 8, 'PADS_BANK0': 9,
            'PADS_QSPI': 10, 'PIO0': 11, 'PIO1': 12, 'PIO2': 13,
            'PLL_SYS': 14, 'PLL_USB': 15, 'PWM': 16, 'SHA256': 17,
            'SPI0': 18, 'SPI1': 19, 'SYSCFG': 20, 'SYSINFO': 21,
            'TBMAN': 22, 'TIMER0': 23, 'TIMER1': 24, 'TRNG': 25,
            'UART0': 26, 'UART1': 27, 'USBCTRL': 28
        }

        # Release critical peripherals for bootrom
        critical = ['IO_BANK0', 'IO_QSPI', 'PADS_BANK0', 'PADS_QSPI',
                   'PLL_SYS', 'PLL_USB', 'USBCTRL', 'SHA256', 'TRNG']

        release_mask = 0
        for name in critical:
            release_mask |= (1 << peripheral_bits[name])

        log.info(f"  Releasing critical peripherals: {critical}")
        log.info(f"  Release mask: 0x{release_mask:08x}")

        new_reset = reset_reg & ~release_mask
        resets.write(0x40020000 + 0x00, 4, new_reset)

        # Verify release
        reset_done, _ = resets.read(0x40020000 + 0x08, 4)
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

    def test_chip_identification(self) -> dict:
        """Test chip identification registers."""
        sysinfo = self.peripherals['SYSINFO']

        results = {}

        # Read CHIP_ID
        chip_id, _ = sysinfo.read(0x40000000 + 0x00, 4)
        platform, _ = sysinfo.read(0x40000000 + 0x08, 4)

        # Decode CHIP_ID
        revision = (chip_id >> 28) & 0xF
        part = (chip_id >> 12) & 0xFFFF
        manufacturer = (chip_id >> 1) & 0x7FF

        log.info(f"  CHIP_ID: 0x{chip_id:08x}")
        log.info(f"    Revision:     {revision}")
        log.info(f"    Part:         0x{part:04x} ({'RP2350' if part == 0x2350 else 'Unknown'})")
        log.info(f"    Manufacturer: 0x{manufacturer:03x} ({'Raspberry Pi' if manufacturer == 0x14D else 'Unknown'})")

        log.info(f"  PLATFORM: 0x{platform:08x}")
        log.info(f"    ASIC: {bool(platform & 2)}")
        log.info(f"    FPGA: {bool(platform & 1)}")

        results['chip_id'] = chip_id
        results['part'] = part
        results['manufacturer'] = manufacturer
        results['revision'] = revision
        results['platform'] = platform
        results['is_asic'] = bool(platform & 2)

        assert part == 0x2350, f"Wrong part number: 0x{part:04x}"

        return results

    def test_security_peripherals(self) -> dict:
        """Test RP2350 security peripherals (SHA256, TRNG, OTP)."""
        sha256 = self.peripherals['SHA256']
        trng = self.peripherals['TRNG']
        otp = self.peripherals['OTP']

        results = {}

        # Test TRNG
        log.info("  Testing TRNG...")
        trng.write(0x400F0000 + 0x120, 4, 1)  # Enable RND_SOURCE
        trng_valid, _ = trng.read(0x400F0000 + 0x104, 4)
        log.info(f"    TRNG_VALID: {trng_valid}")

        random_word, _ = trng.read(0x400F0000 + 0x108, 4)  # EHR_DATA0
        log.info(f"    Random word: 0x{random_word:08x}")
        results['trng'] = {'valid': trng_valid, 'random_sample': random_word}
        assert trng_valid == 1, "TRNG not valid"

        # Test SHA256
        log.info("  Testing SHA256...")
        sha256.write(0x400F8000 + 0x00, 4, 0x03)  # EN | START
        csr, _ = sha256.read(0x400F8000 + 0x00, 4)
        wdata_rdy = bool(csr & (1 << 16))
        log.info(f"    SHA256 CSR: 0x{csr:08x}")
        log.info(f"    WDATA_RDY: {wdata_rdy}")
        results['sha256'] = {'csr': csr, 'ready': wdata_rdy}

        # Test OTP read
        log.info("  Testing OTP...")
        otp_status, _ = otp.read(0x40120000 + 0x124, 4)  # SBPI_STATUS
        log.info(f"    OTP SBPI_STATUS: 0x{otp_status:08x}")
        results['otp'] = {'status': otp_status}

        return results

    def test_trustzone_accessctrl(self) -> dict:
        """Test TrustZone access control configuration."""
        accessctrl = self.peripherals['ACCESSCTRL']

        results = {}

        # Read LOCK status
        lock, _ = accessctrl.read(0x40060000 + 0x00, 4)
        log.info(f"  ACCESSCTRL LOCK: {lock}")

        # Check that peripherals are accessible by default
        # First peripheral access control register at 0x0C
        periph_access, _ = accessctrl.read(0x40060000 + 0x0C, 4)
        log.info(f"  First peripheral access: 0x{periph_access:08x}")
        log.info(f"    All domains accessible: {periph_access == 0xFFFFFFFF}")

        results['locked'] = lock
        results['default_access'] = periph_access
        results['open_access'] = periph_access == 0xFFFFFFFF

        return results

    def test_glitch_detector(self) -> dict:
        """Test glitch detector peripheral."""
        glitch_det = self.peripherals['GLITCH_DET']

        results = {}

        # Check initial state
        arm_status, _ = glitch_det.read(0x40158000 + 0x00, 4)
        log.info(f"  Initial ARM status: {arm_status}")

        trig_status, _ = glitch_det.read(0x40158000 + 0x10, 4)
        log.info(f"  Trigger status: {trig_status}")

        # Arm the detector
        log.info("  Arming glitch detector...")
        glitch_det.write(0x40158000 + 0x00, 4, 1)

        arm_status, _ = glitch_det.read(0x40158000 + 0x00, 4)
        log.info(f"  Armed: {arm_status}")

        results['armed'] = arm_status
        results['triggered'] = trig_status

        return results

    def test_timer_tick_setup(self) -> dict:
        """Test timer tick configuration."""
        ticks = self.peripherals['TICKS']
        watchdog = self.peripherals['WATCHDOG']

        results = {}

        # Configure TICKS peripheral (new in RP2350)
        log.info("  Configuring TICKS peripheral...")

        # Set PROC0 cycles
        ticks.write(0x40108000 + 0x04, 4, 1)  # PROC0_CYCLES = 1
        proc0_cycles, _ = ticks.read(0x40108000 + 0x04, 4)
        log.info(f"    PROC0_CYCLES: {proc0_cycles}")

        # Configure WATCHDOG TICK (similar to RP2040)
        log.info("  Configuring WATCHDOG TICK...")
        tick, _ = watchdog.read(0x400D8000 + 0x2C, 4)
        log.info(f"  Initial TICK: 0x{tick:08x}")

        # Configure TICK for 1MHz from 12MHz XOSC
        watchdog.write(0x400D8000 + 0x2C, 4, (1 << 9) | 12)

        tick, _ = watchdog.read(0x400D8000 + 0x2C, 4)
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

    def test_qmi_interface(self) -> dict:
        """Test QMI (QSPI Memory Interface) initialization."""
        qmi = self.peripherals['QMI']

        results = {}

        # Read timing configuration
        m0_timing, _ = qmi.read(0x400D0000 + 0x0C, 4)
        m1_timing, _ = qmi.read(0x400D0000 + 0x20, 4)

        log.info(f"  QMI M0_TIMING: 0x{m0_timing:08x}")
        log.info(f"  QMI M1_TIMING: 0x{m1_timing:08x}")

        # Check direct mode CSR
        direct_csr, _ = qmi.read(0x400D0000 + 0x00, 4)
        log.info(f"  QMI DIRECT_CSR: 0x{direct_csr:08x}")

        results['m0_timing'] = m0_timing
        results['m1_timing'] = m1_timing
        results['direct_csr'] = direct_csr

        return results

    def run_all_tests(self):
        """Run all tests and generate report."""
        log.info("=" * 70)
        log.info("  RP2350 BOOTROM EMULATION - DETAILED ANALYSIS")
        log.info("=" * 70)
        log.info(f"  Timestamp: {self.report.timestamp}")
        log.info("")

        self.start_time = time.time()

        # Initialize peripherals
        raw_peripherals = self.setup_peripherals()

        # Define tests
        tests = [
            ("Power-On Sequence (PSM)", self.test_power_on_sequence),
            ("Clock Initialization (150MHz)", self.test_clock_initialization),
            ("Peripheral Reset Sequence", self.test_peripheral_reset_sequence),
            ("Chip Identification (RP2350)", self.test_chip_identification),
            ("Security Peripherals (SHA256/TRNG/OTP)", self.test_security_peripherals),
            ("TrustZone Access Control", self.test_trustzone_accessctrl),
            ("Glitch Detector", self.test_glitch_detector),
            ("Timer Tick Setup", self.test_timer_tick_setup),
            ("USB Controller Init", self.test_usb_controller_init),
            ("QMI Interface", self.test_qmi_interface),
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
    print("  RP2350 BOOTROM EMULATION - DETAILED ANALYSIS")
    print("=" * 70 + "\n")

    analyzer = RP2350BootromAnalyzer()
    report = analyzer.run_all_tests()

    # Save JSON report
    report_file = Path(__file__).parent.parent / "results" / "rp2350_bootrom_report.json"
    analyzer.save_report(report_file)

    # Print locations
    print(f"\nLog file:    {log_file}")
    print(f"Report file: {report_file}")

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
