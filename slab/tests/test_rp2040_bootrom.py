#!/usr/bin/env python3
"""
RP2040 Bootrom Emulation Test

Tests the ability to emulate the RP2040 bootrom using the SLAB framework.
The bootrom performs:
1. Clock initialization (XOSC, PLLs)
2. Peripheral reset sequence
3. Flash boot or USB boot mode selection

This test verifies the peripheral implementations needed for bootrom execution.

References:
- RP2040 Bootrom: https://github.com/raspberrypi/pico-bootrom-rp2040
- RP2040 Datasheet: https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import struct
import logging
import argparse
from pathlib import Path

# Add python directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger('RP2040BootromTest')


def test_peripheral_imports():
    """Test that all bootrom-required peripherals can be imported."""
    log.info("Testing peripheral imports...")

    from slab_rp2040 import (
        RP2040XOSC_Bootrom,
        RP2040PLL_Bootrom,
        RP2040RESETS_Bootrom,
        RP2040CLOCKS_Bootrom,
        RP2040PSM_Bootrom,
        RP2040WATCHDOG_Bootrom,
        RP2040ROSC,
        RP2040SSI,
        RP2040XIP,
        RP2040USB,
        RP2040SYSINFO,
    )

    log.info("All bootrom peripherals imported successfully")
    return True


def test_xosc():
    """Test XOSC (Crystal Oscillator) peripheral."""
    log.info("Testing XOSC peripheral...")

    from slab_rp2040.rp2040_misc import RP2040XOSC

    xosc = RP2040XOSC()

    # Test initial state (disabled)
    status, _ = xosc.read(0x40024000 + 0x04, 4)  # STATUS
    log.info(f"Initial XOSC STATUS: 0x{status:08x}")

    # Enable XOSC with magic value
    xosc.write(0x40024000 + 0x00, 4, 0xFAB << 12 | 0xAA0)  # CTRL = enable

    # Check status - should be stable
    status, _ = xosc.read(0x40024000 + 0x04, 4)
    stable = bool(status & (1 << 31))
    enabled = bool(status & (1 << 12))

    log.info(f"XOSC STATUS after enable: 0x{status:08x}")
    log.info(f"  STABLE: {stable}, ENABLED: {enabled}")

    assert stable, "XOSC should report stable after enable"
    assert enabled, "XOSC should report enabled"

    log.info("XOSC test passed")
    return True


def test_pll():
    """Test PLL (Phase-Locked Loop) peripheral."""
    log.info("Testing PLL peripheral...")

    from slab_rp2040.rp2040_misc import RP2040PLL

    # Test PLL_SYS
    pll_sys = RP2040PLL("PLL_SYS", 0x40028000)

    # Initial state - powered down
    cs, _ = pll_sys.read(0x40028000 + 0x00, 4)
    pwr, _ = pll_sys.read(0x40028000 + 0x04, 4)
    log.info(f"Initial PLL_SYS CS: 0x{cs:08x}, PWR: 0x{pwr:08x}")

    # Configure PLL: REFDIV=1, FBDIV=125, POSTDIV1=6, POSTDIV2=2
    # Output = (12MHz / 1) * 125 / 6 / 2 = 125MHz
    pll_sys.write(0x40028000 + 0x00, 4, 1)  # CS: REFDIV=1
    pll_sys.write(0x40028000 + 0x08, 4, 125)  # FBDIV_INT
    pll_sys.write(0x40028000 + 0x0C, 4, (6 << 16) | (2 << 12))  # PRIM

    # Power on VCO
    pll_sys.write(0x40028000 + 0x04, 4, 0x00)  # Clear PD bits

    # Check lock status
    cs, _ = pll_sys.read(0x40028000 + 0x00, 4)
    locked = bool(cs & (1 << 31))

    log.info(f"PLL_SYS CS after config: 0x{cs:08x}")
    log.info(f"  LOCKED: {locked}")

    assert locked, "PLL should report locked after configuration"

    log.info("PLL test passed")
    return True


def test_resets():
    """Test RESETS controller peripheral."""
    log.info("Testing RESETS peripheral...")

    from slab_rp2040.rp2040_misc import RP2040RESETS

    resets = RP2040RESETS()

    # Initial state - all in reset
    reset_reg, _ = resets.read(0x4000c000 + 0x00, 4)
    reset_done, _ = resets.read(0x4000c000 + 0x08, 4)

    log.info(f"Initial RESET: 0x{reset_reg:08x}")
    log.info(f"Initial RESET_DONE: 0x{reset_done:08x}")

    assert reset_reg == 0x1FFFFFF, "All peripherals should start in reset"
    assert reset_done == 0, "No peripherals should be out of reset initially"

    # Release IO_BANK0 and PADS from reset (needed for GPIO)
    RESET_IO_BANK0 = 1 << 5
    RESET_PADS_BANK0 = 1 << 8

    resets.write(0x4000c000 + 0x00, 4, reset_reg & ~(RESET_IO_BANK0 | RESET_PADS_BANK0))

    reset_done, _ = resets.read(0x4000c000 + 0x08, 4)
    log.info(f"RESET_DONE after release: 0x{reset_done:08x}")

    assert reset_done & RESET_IO_BANK0, "IO_BANK0 should be out of reset"
    assert reset_done & RESET_PADS_BANK0, "PADS_BANK0 should be out of reset"

    log.info("RESETS test passed")
    return True


def test_clocks():
    """Test CLOCKS controller peripheral."""
    log.info("Testing CLOCKS peripheral...")

    from slab_rp2040.rp2040_misc import RP2040CLOCKS

    clocks = RP2040CLOCKS()

    # Check initial clock selections
    clk_ref_sel, _ = clocks.read(0x40008000 + 0x38, 4)  # CLK_REF_SELECTED
    clk_sys_sel, _ = clocks.read(0x40008000 + 0x44, 4)  # CLK_SYS_SELECTED

    log.info(f"CLK_REF_SELECTED: 0x{clk_ref_sel:x}")
    log.info(f"CLK_SYS_SELECTED: 0x{clk_sys_sel:x}")

    # Switch CLK_REF to XOSC (source 2)
    clocks.write(0x40008000 + 0x30, 4, 0x2)  # CLK_REF_CTRL

    clk_ref_sel, _ = clocks.read(0x40008000 + 0x38, 4)
    log.info(f"CLK_REF_SELECTED after switch: 0x{clk_ref_sel:x}")

    # FC0 - frequency counter should report done
    fc0_status, _ = clocks.read(0x40008000 + 0x98, 4)
    log.info(f"FC0_STATUS: 0x{fc0_status:08x}")

    log.info("CLOCKS test passed")
    return True


def test_watchdog():
    """Test WATCHDOG peripheral."""
    log.info("Testing WATCHDOG peripheral...")

    from slab_rp2040.rp2040_misc import RP2040WATCHDOG

    watchdog = RP2040WATCHDOG()

    # Test TICK register (used for timer tick)
    tick, _ = watchdog.read(0x40058000 + 0x2C, 4)
    log.info(f"Initial TICK: 0x{tick:08x}")

    # Enable TICK with 12 cycles (12MHz / 12 = 1MHz)
    watchdog.write(0x40058000 + 0x2C, 4, (1 << 9) | 12)

    tick, _ = watchdog.read(0x40058000 + 0x2C, 4)
    running = bool(tick & (1 << 10))
    enabled = bool(tick & (1 << 9))
    cycles = tick & 0x1FF

    log.info(f"TICK after config: 0x{tick:08x}")
    log.info(f"  RUNNING: {running}, ENABLED: {enabled}, CYCLES: {cycles}")

    assert enabled, "TICK should be enabled"
    assert running, "TICK should be running"
    assert cycles == 12, "TICK cycles should be 12"

    # Test scratch registers (used by bootrom for boot flags)
    for i in range(8):
        offset = 0x0C + i * 4
        watchdog.write(0x40058000 + offset, 4, 0xDEADBEE0 + i)

    for i in range(8):
        offset = 0x0C + i * 4
        val, _ = watchdog.read(0x40058000 + offset, 4)
        assert val == 0xDEADBEE0 + i, f"SCRATCH{i} mismatch"

    log.info("WATCHDOG test passed")
    return True


def test_psm():
    """Test PSM (Power-on State Machine) peripheral."""
    log.info("Testing PSM peripheral...")

    from slab_rp2040.rp2040_misc import RP2040PSM

    psm = RP2040PSM()

    # Check DONE register - all power domains should be done
    done, _ = psm.read(0x40010000 + 0x0C, 4)
    log.info(f"PSM DONE: 0x{done:08x}")

    # Should have all domains powered
    assert done == 0x1FFFF, "All power domains should be done"

    log.info("PSM test passed")
    return True


def test_bootrom_init_sequence():
    """
    Test the bootrom initialization sequence.

    The RP2040 bootrom performs these steps:
    1. Wait for ROSC to stabilize
    2. Configure XOSC
    3. Configure PLLs
    4. Switch clocks to PLL
    5. Release peripherals from reset
    6. Check boot mode (flash or USB)
    """
    log.info("Testing bootrom initialization sequence...")

    from slab_rp2040.rp2040_misc import (
        RP2040ROSC, RP2040XOSC, RP2040PLL, RP2040CLOCKS,
        RP2040RESETS, RP2040PSM, RP2040WATCHDOG, RP2040SYSINFO
    )

    # Create all peripherals
    rosc = RP2040ROSC()
    xosc = RP2040XOSC()
    pll_sys = RP2040PLL("PLL_SYS", 0x40028000, 125000000)
    pll_usb = RP2040PLL("PLL_USB", 0x4002c000, 48000000)
    clocks = RP2040CLOCKS()
    resets = RP2040RESETS()
    psm = RP2040PSM()
    watchdog = RP2040WATCHDOG()
    sysinfo = RP2040SYSINFO()

    # Step 1: Check PSM DONE
    done, _ = psm.read(0x40010000 + 0x0C, 4)
    assert done != 0, "PSM should report power domains done"
    log.info("Step 1: PSM DONE = 0x{:08x}".format(done))

    # Step 2: Check ROSC status
    rosc_status, _ = rosc.read(0x40060000 + 0x18, 4)  # STATUS
    rosc_stable = bool(rosc_status & (1 << 31))
    assert rosc_stable, "ROSC should be stable"
    log.info("Step 2: ROSC STABLE = {}".format(rosc_stable))

    # Step 3: Enable XOSC
    xosc.write(0x40024000 + 0x00, 4, 0xFABAA0)  # Enable
    xosc_status, _ = xosc.read(0x40024000 + 0x04, 4)
    xosc_stable = bool(xosc_status & (1 << 31))
    assert xosc_stable, "XOSC should be stable"
    log.info("Step 3: XOSC STABLE = {}".format(xosc_stable))

    # Step 4: Switch CLK_REF to XOSC
    clocks.write(0x40008000 + 0x30, 4, 0x2)  # SRC=XOSC
    ref_sel, _ = clocks.read(0x40008000 + 0x38, 4)
    log.info("Step 4: CLK_REF_SELECTED = 0x{:x}".format(ref_sel))

    # Step 5: Release PLLs from reset
    reset_val, _ = resets.read(0x4000c000 + 0x00, 4)
    RESET_PLL_SYS = 1 << 12
    RESET_PLL_USB = 1 << 13
    resets.write(0x4000c000 + 0x00, 4, reset_val & ~(RESET_PLL_SYS | RESET_PLL_USB))
    log.info("Step 5: Released PLLs from reset")

    # Step 6: Configure PLL_SYS
    pll_sys.write(0x40028000 + 0x00, 4, 1)  # REFDIV=1
    pll_sys.write(0x40028000 + 0x08, 4, 125)  # FBDIV=125
    pll_sys.write(0x40028000 + 0x0C, 4, (6 << 16) | (2 << 12))  # POSTDIV
    pll_sys.write(0x40028000 + 0x04, 4, 0)  # Power on

    pll_cs, _ = pll_sys.read(0x40028000 + 0x00, 4)
    pll_locked = bool(pll_cs & (1 << 31))
    assert pll_locked, "PLL_SYS should be locked"
    log.info("Step 6: PLL_SYS LOCKED = {}".format(pll_locked))

    # Step 7: Configure PLL_USB (48MHz for USB)
    pll_usb.write(0x4002c000 + 0x00, 4, 1)  # REFDIV=1
    pll_usb.write(0x4002c000 + 0x08, 4, 100)  # FBDIV=100 (12*100/25=48MHz)
    pll_usb.write(0x4002c000 + 0x0C, 4, (5 << 16) | (5 << 12))  # POSTDIV
    pll_usb.write(0x4002c000 + 0x04, 4, 0)  # Power on

    pll_cs, _ = pll_usb.read(0x4002c000 + 0x00, 4)
    pll_locked = bool(pll_cs & (1 << 31))
    assert pll_locked, "PLL_USB should be locked"
    log.info("Step 7: PLL_USB LOCKED = {}".format(pll_locked))

    # Step 8: Switch CLK_SYS to PLL
    clocks.write(0x40008000 + 0x3C, 4, 0x1)  # AUXSRC=PLL, SRC=AUX
    sys_sel, _ = clocks.read(0x40008000 + 0x44, 4)
    log.info("Step 8: CLK_SYS_SELECTED = 0x{:x}".format(sys_sel))

    # Step 9: Enable TICK for 1MHz timebase
    watchdog.write(0x40058000 + 0x2C, 4, (1 << 9) | 12)  # Enable, 12 cycles
    tick, _ = watchdog.read(0x40058000 + 0x2C, 4)
    tick_running = bool(tick & (1 << 10))
    log.info("Step 9: TICK RUNNING = {}".format(tick_running))

    # Step 10: Release IO peripherals from reset
    reset_val, _ = resets.read(0x4000c000 + 0x00, 4)
    IO_RESETS = (1 << 5) | (1 << 6) | (1 << 8) | (1 << 9)  # IO_BANK0, IO_QSPI, PADS
    resets.write(0x4000c000 + 0x00, 4, reset_val & ~IO_RESETS)

    reset_done, _ = resets.read(0x4000c000 + 0x08, 4)
    log.info("Step 10: RESET_DONE = 0x{:08x}".format(reset_done))

    # Step 11: Check CHIP_ID
    chip_id, _ = sysinfo.read(0x40000000 + 0x00, 4)
    log.info("Step 11: CHIP_ID = 0x{:08x}".format(chip_id))

    log.info("Bootrom initialization sequence completed successfully!")
    return True


def main():
    """Run all bootrom emulation tests."""
    parser = argparse.ArgumentParser(description="RP2040 Bootrom Emulation Test")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--bootrom", type=str, help="Path to bootrom binary (optional)")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 60)
    print("  RP2040 Bootrom Emulation Test")
    print("=" * 60)

    tests = [
        ("Peripheral imports", test_peripheral_imports),
        ("XOSC peripheral", test_xosc),
        ("PLL peripheral", test_pll),
        ("RESETS peripheral", test_resets),
        ("CLOCKS peripheral", test_clocks),
        ("WATCHDOG peripheral", test_watchdog),
        ("PSM peripheral", test_psm),
        ("Bootrom init sequence", test_bootrom_init_sequence),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            if test_func():
                passed += 1
                print(f"  PASSED")
            else:
                failed += 1
                print(f"  FAILED")
        except Exception as e:
            failed += 1
            log.error(f"Test failed with exception: {e}")
            print(f"  FAILED: {e}")

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
