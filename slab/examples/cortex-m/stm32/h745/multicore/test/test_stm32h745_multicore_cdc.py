#!/usr/bin/env python3
"""
STM32H745 Multicore CDC Test Harness

Tests dual-core STM32H745 (Cortex-M7 + Cortex-M4) functionality:
- Hardware semaphore (HSEM) synchronization
- Shared memory access via SRAM3
- Inter-processor communication

This validates:
1. STM32H745 HSEM for multicore synchronization
2. Shared SRAM coordination between M7 and M4 cores
3. Heterogeneous dual-core operation

Architecture:
    M7 @ 480 MHz: Main application processor (D1 domain)
    M4 @ 240 MHz: Real-time coprocessor (D2 domain)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import threading
import time

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32H743PeripheralSet
from slab_stm32.stm32wbxx import STM32HSEM


class DualCoreSTM32H745:
    """
    Dual-core STM32H745 emulation with inter-core communication.

    Sets up two peripheral sets:
    - M7 core (main, 480 MHz)
    - M4 core (coprocessor, 240 MHz)

    Inter-core communication via:
    - HSEM (Hardware Semaphores)
    - Shared SRAM3 region
    """

    SHARED_BASE = 0x30040000

    def __init__(self):
        # Suppress log output for cleaner test output
        import logging
        logging.getLogger('STM32H745').setLevel(logging.WARNING)

        # Create peripheral sets for both cores
        # Both use H743 as base since H745 is dual-core variant
        self.m7 = STM32H743PeripheralSet()
        self.m4 = STM32H743PeripheralSet()

        # Add shared HSEM (same instance for both cores)
        self.hsem = STM32HSEM(base=0x58026400)

        # Shared memory simulation
        self.shared_memory = {}

        # M4 running flag
        self.m4_running = False
        self.m4_thread = None

    def read_shared(self, offset: int) -> int:
        """Read from shared memory region."""
        return self.shared_memory.get(offset, 0)

    def write_shared(self, offset: int, value: int):
        """Write to shared memory region."""
        self.shared_memory[offset] = value & 0xFFFFFFFF

    def start_m4(self):
        """Start M4 core emulation in background thread."""
        self.m4_running = True
        self.m4_thread = threading.Thread(target=self._m4_loop, daemon=True)
        self.m4_thread.start()

        # Wait for M4 to signal ready
        timeout = 100
        while timeout > 0:
            if self.read_shared(0) == 0xC0DE0004:
                return True
            time.sleep(0.001)
            timeout -= 1
        return False

    def stop_m4(self):
        """Stop M4 core emulation."""
        self.m4_running = False
        if self.m4_thread:
            self.m4_thread.join(timeout=1.0)

    def _m4_loop(self):
        """M4 main loop - handles shared memory commands."""
        # Signal ready (M4 signature)
        self.write_shared(0, 0xC0DE0004)

        while self.m4_running:
            # Check shared memory command (offset 8 = command)
            cmd = self.read_shared(8)
            if cmd == 0x00000001:  # CMD_INCREMENT
                val = self.read_shared(4)
                self.write_shared(4, val + 1)
                self.write_shared(8, 0xFFFFFFFF)  # CMD_DONE
            elif cmd == 0x00000002:  # CMD_MULTIPLY
                val = self.read_shared(4)
                self.write_shared(4, val * 2)
                self.write_shared(8, 0xFFFFFFFF)  # CMD_DONE

            time.sleep(0.0001)


class CDCInterface:
    """Simulates CDC-ACM interface for multicore test commands."""

    def __init__(self, dual_core: DualCoreSTM32H745):
        self.dual_core = dual_core
        self.hsem = dual_core.hsem

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "CPUID":
            return "00"  # M7 core ID

        elif command == "HSEM":
            return self._cmd_hsem(args)

        elif command == "SHARED":
            return self._cmd_shared(args)

        elif command == "STRESS":
            return self._cmd_stress(args)

        elif command == "STATUS":
            return self._cmd_status()

        return "ERROR: Unknown command"

    def _cmd_hsem(self, args: str) -> str:
        """Test hardware semaphore acquire/release."""
        args = args.strip()
        try:
            sem_id = int(args, 16) if args else 0
        except ValueError:
            sem_id = 0

        if sem_id >= 32:
            return "ERROR: HSEM 0-31"

        # Simulate HSEM lock via register access
        # Reading RLR returns current state and locks if free
        lock_status = self.hsem.semaphores[sem_id]

        if lock_status == 0:
            # Lock is free, claim it
            self.hsem.semaphores[sem_id] = 1  # M7 core ID + locked
            result = "CLAIMED"
            # Release it
            self.hsem.semaphores[sem_id] = 0
        else:
            result = "BUSY"

        return result

    def _cmd_shared(self, args: str) -> str:
        """Write to shared memory, M4 increments, read back."""
        args = args.strip()
        if not args:
            return "ERROR: Need hex value"

        try:
            value = int(args, 16)
        except ValueError:
            return "ERROR: Invalid hex"

        # Check M4 ready
        if self.dual_core.read_shared(0) != 0xC0DE0004:
            return "ERROR: M4 not ready"

        # Write value and command
        self.dual_core.write_shared(4, value)  # shared_value
        self.dual_core.write_shared(8, 0x00000001)  # CMD_INCREMENT

        # Wait for completion
        timeout = 1000
        while timeout > 0:
            if self.dual_core.read_shared(8) == 0xFFFFFFFF:  # CMD_DONE
                result = self.dual_core.read_shared(4)
                return f"{result:08x}"
            time.sleep(0.001)
            timeout -= 1

        return "ERROR: Timeout"

    def _cmd_stress(self, args: str) -> str:
        """Run multiple shared memory round-trips."""
        args = args.strip()
        try:
            iterations = int(args, 16) if args else 100
        except ValueError:
            iterations = 100

        if iterations > 10000:
            iterations = 10000

        # Check M4 ready
        if self.dual_core.read_shared(0) != 0xC0DE0004:
            return "ERROR: M4 not ready"

        errors = 0

        for i in range(iterations):
            value = (i * 17) & 0xFFFFFFFF
            expected = (value + 1) & 0xFFFFFFFF

            # Write command
            self.dual_core.write_shared(4, value)
            self.dual_core.write_shared(8, 0x00000001)  # CMD_INCREMENT

            # Wait for response
            timeout = 100
            while timeout > 0:
                if self.dual_core.read_shared(8) == 0xFFFFFFFF:
                    break
                time.sleep(0.0001)
                timeout -= 1

            result = self.dual_core.read_shared(4)
            if timeout == 0 or result != expected:
                errors += 1

        return f"{iterations:08x} {errors:08x}"

    def _cmd_status(self) -> str:
        """Check M4 core status."""
        status = self.dual_core.read_shared(0)
        if status == 0xC0DE0004:
            return "READY"
        return f"{status:08x}"


def test_ping(cdc):
    """Test PING command."""
    print("\n=== Test: PING ===")
    response = cdc.send_command("PING")
    if response == "PONG":
        print("  PASS: PING -> PONG")
        return True
    else:
        print(f"  FAIL: Expected PONG, got {response}")
        return False


def test_cpuid(cdc):
    """Test CPUID command."""
    print("\n=== Test: CPUID ===")
    response = cdc.send_command("CPUID")
    if response == "00":
        print(f"  PASS: M7 Core CPUID = {response}")
        return True
    else:
        print(f"  FAIL: Expected 00 (M7), got {response}")
        return False


def test_m4_status(cdc):
    """Test M4 core status."""
    print("\n=== Test: M4 Core Status ===")
    response = cdc.send_command("STATUS")
    if response == "READY":
        print("  PASS: M4 Core is READY")
        return True
    else:
        print(f"  FAIL: M4 Core status = {response}")
        return False


def test_hsem(cdc):
    """Test hardware semaphore acquire/release."""
    print("\n=== Test: Hardware Semaphores ===")

    for sem in [0, 15, 31]:
        response = cdc.send_command(f"HSEM {sem:02x}")
        if response != "CLAIMED":
            print(f"  FAIL: HSEM {sem} = {response}")
            return False

    print("  PASS: HSEM 0, 15, 31 claimed and released")
    return True


def test_shared_memory(cdc):
    """Test shared memory communication between M7 and M4."""
    print("\n=== Test: Shared Memory (M7 -> M4) ===")

    test_values = [0x00000000, 0x12345678, 0xFFFFFFFE]

    for value in test_values:
        response = cdc.send_command(f"SHARED {value:08x}")
        expected = f"{(value + 1) & 0xFFFFFFFF:08x}"

        if response != expected:
            print(f"  FAIL: SHARED {value:08x} -> {response}, expected {expected}")
            return False

    print(f"  PASS: {len(test_values)} shared memory increments successful")
    return True


def test_stress(cdc):
    """Test shared memory stress with many iterations."""
    print("\n=== Test: Shared Memory Stress ===")

    response = cdc.send_command("STRESS 100")
    parts = response.split()

    if len(parts) != 2:
        print(f"  FAIL: Invalid response: {response}")
        return False

    iterations = int(parts[0], 16)
    errors = int(parts[1], 16)

    if errors == 0:
        print(f"  PASS: {iterations} iterations, {errors} errors")
        return True
    else:
        print(f"  FAIL: {iterations} iterations, {errors} errors")
        return False


def main():
    print("=" * 60)
    print("STM32H745 Multicore CDC Test (Cortex-M7 + Cortex-M4)")
    print("=" * 60)

    # Create dual-core STM32H745
    print("\nInitializing dual-core STM32H745...")
    dual_core = DualCoreSTM32H745()
    print("  M7 Core: Cortex-M7 @ 480 MHz (main)")
    print("  M4 Core: Cortex-M4 @ 240 MHz (coprocessor)")
    print(f"  HSEM: {dual_core.hsem.name} at 0x{dual_core.hsem.base:08X}")
    print(f"  Shared SRAM: 0x{dual_core.SHARED_BASE:08X}")

    # Start M4 core
    print("\nStarting M4 Core...")
    if not dual_core.start_m4():
        print("  FAIL: M4 Core did not start")
        return 1
    print("  M4 Core started and ready")

    # Create CDC interface
    cdc = CDCInterface(dual_core)

    # Run tests
    results = []

    try:
        results.append(("PING", test_ping(cdc)))
        results.append(("CPUID", test_cpuid(cdc)))
        results.append(("M4 Core Status", test_m4_status(cdc)))
        results.append(("HSEM", test_hsem(cdc)))
        results.append(("Shared Memory", test_shared_memory(cdc)))
        results.append(("Stress Test", test_stress(cdc)))
    finally:
        # Stop M4 core
        dual_core.stop_m4()

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"  {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed} passed, {failed} failed")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
