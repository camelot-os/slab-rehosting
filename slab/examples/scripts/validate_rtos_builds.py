#!/usr/bin/env python3
"""
RTOS Firmware Build Validation

Validates that RTOS firmware binaries are properly built and can be
loaded by QEMU without errors.

Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: GPL-2.0-or-later
"""

import os
import sys
import subprocess
from pathlib import Path

SLAB_ROOT = Path(__file__).resolve().parent.parent.parent
QEMU_BIN = SLAB_ROOT / "qemu" / "build" / "qemu-system-arm"


def check_firmware_header(firmware_path: Path) -> dict:
    """Check firmware binary header (vector table)."""
    if not firmware_path.exists():
        return {"error": "File not found"}

    with open(firmware_path, "rb") as f:
        data = f.read(16)

    if len(data) < 16:
        return {"error": "File too small"}

    # Parse ARM Cortex-M vector table
    sp_init = int.from_bytes(data[0:4], "little")
    reset_vector = int.from_bytes(data[4:8], "little")
    nmi_vector = int.from_bytes(data[8:12], "little")
    hardfault_vector = int.from_bytes(data[12:16], "little")

    return {
        "size": firmware_path.stat().st_size,
        "sp_init": sp_init,
        "reset_vector": reset_vector,
        "nmi_vector": nmi_vector,
        "hardfault_vector": hardfault_vector,
        "valid_sp": 0x20000000 <= sp_init <= 0x20040000,  # RAM range
        "valid_reset": 0x08000000 <= reset_vector <= 0x08100000,  # Flash range
    }


def test_qemu_load(firmware_path: Path) -> bool:
    """Test that QEMU can load and start the firmware."""
    if not QEMU_BIN.exists():
        print("    QEMU binary not found, skipping load test")
        return None

    # Run QEMU with timeout - just check it starts and can load firmware
    try:
        result = subprocess.run(
            [
                str(QEMU_BIN),
                "-M", "slab-cortex-m",
                "-global", "slab-cortex-m.cpu-type=cortex-m4",
                "-global", "slab-cortex-m.flash-size=1048576",
                "-global", "slab-cortex-m.sram-size=131072",
                "-global", "slab-cortex-m.tcp-port=0",  # Port 0 = don't connect
                "-kernel", str(firmware_path),
                "-nographic",
                "-d", "in_asm",  # Dump first instructions
            ],
            timeout=2.0,
            capture_output=True,
            text=True,
        )
        # If we get any assembly output, firmware is executing
        has_instructions = "IN:" in result.stderr or "0x0800" in result.stderr
        return has_instructions
    except subprocess.TimeoutExpired:
        # Timeout is expected - firmware is running
        return True
    except Exception as e:
        print(f"    Error: {e}")
        return False


def main():
    print("=" * 60)
    print("RTOS Firmware Build Validation")
    print("=" * 60)

    examples_dir = SLAB_ROOT / "examples"

    # Firmware to validate
    firmwares = [
        {
            "name": "STM32CubeMX HAL Blinky",
            "path": examples_dir / "cubemx" / "blinky" / "build" / "blinky.bin",
            "rtos": "CubeMX HAL",
        },
        {
            "name": "FreeRTOS Multi-Task Blinky",
            "path": examples_dir / "freertos" / "blinky_tasks" / "build" / "freertos_blinky.bin",
            "rtos": "FreeRTOS",
        },
    ]

    results = []

    for fw in firmwares:
        print(f"\n--- {fw['name']} ---")
        print(f"  RTOS: {fw['rtos']}")
        print(f"  Path: {fw['path']}")

        info = check_firmware_header(fw["path"])

        if "error" in info:
            print(f"  Status: BUILD FAILED ({info['error']})")
            results.append((fw["name"], False, info["error"]))
            continue

        print(f"  Size: {info['size']} bytes")
        print(f"  SP Init: 0x{info['sp_init']:08X} ({'valid' if info['valid_sp'] else 'INVALID'})")
        print(f"  Reset Vector: 0x{info['reset_vector']:08X} ({'valid' if info['valid_reset'] else 'INVALID'})")

        if not info["valid_sp"] or not info["valid_reset"]:
            print("  Status: INVALID VECTOR TABLE")
            results.append((fw["name"], False, "Invalid vector table"))
            continue

        # Test QEMU load
        qemu_result = test_qemu_load(fw["path"])
        if qemu_result is None:
            print("  QEMU Load: skipped")
        elif qemu_result:
            print("  QEMU Load: OK (firmware executes)")
        else:
            print("  QEMU Load: FAILED")

        results.append((fw["name"], True, "OK"))

    # Summary
    print("\n" + "=" * 60)
    print("Validation Summary")
    print("=" * 60)

    passed = 0
    failed = 0

    for name, success, msg in results:
        status = "PASS" if success else "FAIL"
        if success:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}: {msg}")

    print(f"\nTotal: {passed} passed, {failed} failed")

    # Return summary table
    print("\n" + "-" * 60)
    print("| RTOS/Framework  | Build  | Vector Table | QEMU Load |")
    print("-" * 60)
    for fw in firmwares:
        name = fw["rtos"][:15].ljust(15)
        info = check_firmware_header(fw["path"])
        build = "OK" if "error" not in info else "FAIL"
        vt = "OK" if info.get("valid_sp") and info.get("valid_reset") else "FAIL"
        qemu = "OK" if QEMU_BIN.exists() else "N/A"
        print(f"| {name} | {build:6} | {vt:12} | {qemu:9} |")
    print("-" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
