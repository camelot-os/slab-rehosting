#!/usr/bin/env python3
"""
RTOS Examples Validation Script

Tests CubeMX HAL, FreeRTOS, and NuttX firmware rehosting with MCUemu.

Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: GPL-2.0-or-later
"""

import os
import sys
import time
import signal
import subprocess
from pathlib import Path

# Add Python packages to path
SLAB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SLAB_ROOT / "python"))

from slab_stm32 import STM32F439PeripheralSet
from slab_cortex_m.tcp_peripheral import TcpPeripheralBridge
from slab_cortex_m.shm_peripheral import ShmPeripheralBridge, HAS_SHM

# MCUemu test interface
MCUEMU_TEST_BASE = 0x4000F000
TEST_STATUS_RUNNING = 0x01
TEST_STATUS_PASS = 0x02
TEST_STATUS_FAIL = 0x03

# QEMU binary
QEMU_BIN = SLAB_ROOT / "qemu" / "build" / "qemu-system-arm"


class MCUemuTestInterface:
    """MCUemu test status interface peripheral."""

    def __init__(self, name="test_if"):
        self.name = name
        self.base = MCUEMU_TEST_BASE
        self.status = 0
        self.data = 0
        self.cmd = 0

    def read(self, addr: int, size: int):
        offset = addr - self.base
        if offset == 0x00:
            return self.status, None
        elif offset == 0x04:
            return self.data, None
        elif offset == 0x08:
            return self.cmd, None
        return 0, None

    def write(self, addr: int, size: int, value: int):
        offset = addr - self.base
        if offset == 0x00:
            self.status = value
        elif offset == 0x04:
            self.data = value
        elif offset == 0x08:
            self.cmd = value


def run_firmware_test(firmware_path: str, test_name: str, timeout_sec: float = 10.0,
                      use_shm: bool = False) -> bool:
    """
    Run a firmware binary on MCUemu and validate test status.

    Returns True if firmware reports TEST_STATUS_PASS.
    """
    if not QEMU_BIN.exists():
        print(f"  [SKIP] QEMU binary not found: {QEMU_BIN}")
        return None

    if not Path(firmware_path).exists():
        print(f"  [SKIP] Firmware not found: {firmware_path}")
        return None

    print(f"\n  Testing: {test_name}")
    print(f"    Firmware: {Path(firmware_path).name}")
    print(f"    Mode: {'SHM' if use_shm else 'TCP'}")

    # Create peripheral set
    peripherals = STM32F439PeripheralSet()
    test_if = MCUemuTestInterface()

    # Register test interface
    peripherals.add_peripheral(test_if)

    # Choose bridge mode
    port = 5556  # Use different port than default
    if use_shm and HAS_SHM:
        shm_path = f"/dev/shm/mcuemu_test_{os.getpid()}"
        bridge = ShmPeripheralBridge(peripherals, shm_path=shm_path)
        qemu_args = [
            str(QEMU_BIN),
            "-M", "slab-cortex-m",
            "-global", "slab-cortex-m.cpu-type=cortex-m4",
            "-global", "slab-cortex-m.flash-size=1048576",
            "-global", "slab-cortex-m.sram-size=131072",
            "-global", f"slab-cortex-m.shm-path={shm_path}",
            "-kernel", firmware_path,
            "-nographic",
        ]
    else:
        bridge = TcpPeripheralBridge(peripherals, port=port)
        qemu_args = [
            str(QEMU_BIN),
            "-M", "slab-cortex-m",
            "-global", "slab-cortex-m.cpu-type=cortex-m4",
            "-global", "slab-cortex-m.flash-size=1048576",
            "-global", "slab-cortex-m.sram-size=131072",
            "-global", f"slab-cortex-m.tcp-port={port}",
            "-kernel", firmware_path,
            "-nographic",
        ]

    # Start bridge
    bridge.start()
    time.sleep(0.2)

    # Start QEMU
    qemu_proc = subprocess.Popen(
        qemu_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    # Wait for test completion
    start_time = time.time()
    result = None
    last_status = 0
    last_data = 0

    try:
        while time.time() - start_time < timeout_sec:
            time.sleep(0.1)

            # Check status
            if test_if.status != last_status or test_if.data != last_data:
                last_status = test_if.status
                last_data = test_if.data
                print(f"    Status: {last_status:#x}  Data: {last_data:#x}")

            if test_if.status == TEST_STATUS_PASS:
                result = True
                break
            elif test_if.status == TEST_STATUS_FAIL:
                result = False
                break

        if result is None:
            print(f"    Timeout after {timeout_sec}s")
            result = False

    finally:
        # Cleanup
        try:
            os.killpg(os.getpgid(qemu_proc.pid), signal.SIGTERM)
        except Exception:
            pass
        bridge.stop()

    status_str = "PASS" if result else "FAIL"
    print(f"    Result: {status_str}")

    return result


def main():
    """Run all RTOS example tests."""
    print("=" * 60)
    print("MCUemu RTOS Examples Validation")
    print("=" * 60)

    examples_dir = SLAB_ROOT / "examples"
    results = {}

    # Test configurations
    tests = [
        {
            "name": "STM32CubeMX HAL Blinky",
            "firmware": examples_dir / "cubemx" / "blinky" / "build" / "blinky.bin",
            "timeout": 5.0,
        },
        {
            "name": "FreeRTOS Multi-Task Blinky",
            "firmware": examples_dir / "freertos" / "blinky_tasks" / "build" / "freertos_blinky.bin",
            "timeout": 15.0,  # FreeRTOS needs more time for tasks
        },
    ]

    # Test in TCP mode
    print("\n--- TCP Mode Tests ---")
    for test in tests:
        result = run_firmware_test(
            str(test["firmware"]),
            test["name"],
            timeout_sec=test["timeout"],
            use_shm=False,
        )
        results[f"{test['name']} (TCP)"] = result

    # Test in SHM mode if available
    if HAS_SHM:
        print("\n--- SHM Mode Tests ---")
        for test in tests:
            result = run_firmware_test(
                str(test["firmware"]),
                test["name"],
                timeout_sec=test["timeout"],
                use_shm=True,
            )
            results[f"{test['name']} (SHM)"] = result

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results.items():
        if result is None:
            status = "SKIP"
            skipped += 1
        elif result:
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"
            failed += 1
        print(f"  [{status}] {name}")

    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
