#!/usr/bin/env python3
"""
Firmware Emulation Integration Test

Tests CubeMX and FreeRTOS firmware with full peripheral emulation.
Monitors GPIO accesses to validate peripheral interactions.

Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: GPL-2.0-or-later
"""

import os
import sys
import time
import signal
import subprocess
import threading
from pathlib import Path

SLAB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SLAB_ROOT / "python"))

from slab_stm32 import STM32F439PeripheralSet
from slab_cortex_m.tcp_peripheral import TcpPeripheralBridge

QEMU_BIN = SLAB_ROOT / "qemu" / "build" / "qemu-system-arm"


class GPIOMonitor:
    """Monitor GPIO accesses."""

    def __init__(self):
        self.writes = []
        self.reads = []
        self.lock = threading.Lock()

    def record_write(self, addr, value):
        with self.lock:
            self.writes.append((time.time(), addr, value))

    def record_read(self, addr, value):
        with self.lock:
            self.reads.append((time.time(), addr, value))

    def get_summary(self):
        with self.lock:
            return {
                "total_writes": len(self.writes),
                "total_reads": len(self.reads),
                "unique_addrs": len(set(w[1] for w in self.writes)),
            }


def run_emulation_test(firmware_path: str, name: str, timeout: float = 5.0) -> dict:
    """Run firmware with full peripheral emulation."""
    print(f"\n=== {name} ===")
    print(f"  Firmware: {Path(firmware_path).name}")

    if not Path(firmware_path).exists():
        print("  Status: SKIP (firmware not found)")
        return {"status": "skip", "reason": "firmware not found"}

    if not QEMU_BIN.exists():
        print("  Status: SKIP (QEMU not found)")
        return {"status": "skip", "reason": "QEMU not found"}

    # Create peripheral set
    peripherals = STM32F439PeripheralSet()
    gpio_monitor = GPIOMonitor()

    # Wrap GPIO port A write method to monitor accesses (LED on PA5)
    gpioa = peripherals.gpio['A']
    original_gpio_write = gpioa.write

    def monitored_write(addr, size, value):
        gpio_monitor.record_write(addr, value)
        return original_gpio_write(addr, size, value)

    gpioa.write = monitored_write

    # Start TCP bridge
    port = 5557
    bridge = TcpPeripheralBridge(peripherals, port=port)
    bridge.start_server()
    time.sleep(0.3)

    # Start QEMU
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

    print(f"  Starting QEMU on port {port}...")
    qemu_proc = subprocess.Popen(
        qemu_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    result = {"status": "unknown"}

    try:
        # Wait for emulation
        start_time = time.time()
        last_print = 0

        while time.time() - start_time < timeout:
            time.sleep(0.1)

            # Print progress every second
            elapsed = int(time.time() - start_time)
            if elapsed > last_print:
                last_print = elapsed
                summary = gpio_monitor.get_summary()
                print(f"  [{elapsed}s] GPIO writes: {summary['total_writes']}, "
                      f"reads: {summary['total_reads']}")

            # Check if QEMU is still running
            if qemu_proc.poll() is not None:
                print("  QEMU exited unexpectedly")
                break

        # Get final summary
        summary = gpio_monitor.get_summary()
        result["gpio_writes"] = summary["total_writes"]
        result["gpio_reads"] = summary["total_reads"]
        result["unique_addrs"] = summary["unique_addrs"]

        # Determine status
        if summary["total_writes"] > 0:
            result["status"] = "pass"
            print(f"  Status: PASS")
            print(f"  GPIO writes: {summary['total_writes']}")
            print(f"  GPIO reads: {summary['total_reads']}")
            print(f"  Unique addresses: {summary['unique_addrs']}")
        else:
            result["status"] = "fail"
            result["reason"] = "No GPIO activity detected"
            print(f"  Status: FAIL (no GPIO activity)")

    except Exception as e:
        result["status"] = "error"
        result["reason"] = str(e)
        print(f"  Status: ERROR ({e})")

    finally:
        # Cleanup
        try:
            os.killpg(os.getpgid(qemu_proc.pid), signal.SIGTERM)
            qemu_proc.wait(timeout=2)
        except Exception:
            try:
                qemu_proc.kill()
            except Exception:
                pass
        bridge.stop_server()

    return result


def main():
    print("=" * 60)
    print("MCUemu RTOS Firmware Emulation Test")
    print("=" * 60)

    examples_dir = SLAB_ROOT / "examples"

    tests = [
        {
            "name": "STM32CubeMX HAL Blinky",
            "firmware": examples_dir / "cubemx" / "blinky" / "build" / "blinky.bin",
            "timeout": 5.0,
        },
        {
            "name": "FreeRTOS Multi-Task Blinky",
            "firmware": examples_dir / "freertos" / "blinky_tasks" / "build" / "freertos_blinky.bin",
            "timeout": 8.0,
        },
    ]

    results = []
    for test in tests:
        result = run_emulation_test(
            str(test["firmware"]),
            test["name"],
            timeout=test["timeout"],
        )
        results.append((test["name"], result))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        status = result["status"].upper()
        if result["status"] == "pass":
            passed += 1
            gpio_info = f"(GPIO: {result.get('gpio_writes', 0)} writes)"
            print(f"  [PASS] {name} {gpio_info}")
        elif result["status"] == "skip":
            skipped += 1
            print(f"  [SKIP] {name}: {result.get('reason', 'unknown')}")
        else:
            failed += 1
            print(f"  [FAIL] {name}: {result.get('reason', 'unknown')}")

    print(f"\nTotal: {passed} passed, {failed} failed, {skipped} skipped")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
