#!/usr/bin/env python3
"""
RP2040 Multicore CDC Test Harness

Tests dual-core RP2040 functionality:
- Inter-core FIFO communication
- Spinlock synchronization
- Shared memory access
- Dual-core peripheral set simulation

This validates:
1. RP2040 SIO FIFO for inter-core messaging
2. Spinlock acquire/release
3. Shared SRAM coordination between cores

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import threading
import time

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_rp2040 import RP2040PeripheralSet


class DualCoreRP2040:
    """
    Dual-core RP2040 emulation with inter-core communication.

    Sets up two peripheral sets (one per core) with linked SIO FIFOs.
    """

    SHARED_BASE = 0x20040000

    def __init__(self):
        # Suppress log output for cleaner test output
        import logging
        logging.getLogger('RP2040').setLevel(logging.WARNING)

        # Create peripheral sets for both cores
        self.core0 = RP2040PeripheralSet(cpuid=0, chip="RP2040")
        self.core1 = RP2040PeripheralSet(cpuid=1, chip="RP2040")

        # Link the SIO FIFOs between cores
        self.core0.sio.other_core = self.core1.sio
        self.core1.sio.other_core = self.core0.sio

        # Shared memory simulation (simple dict-based)
        self.shared_memory = {}

        # Core 1 running flag
        self.core1_running = False
        self.core1_thread = None

    def read_shared(self, offset: int) -> int:
        """Read from shared memory region."""
        return self.shared_memory.get(offset, 0)

    def write_shared(self, offset: int, value: int):
        """Write to shared memory region."""
        self.shared_memory[offset] = value & 0xFFFFFFFF

    def start_core1(self):
        """Start Core 1 emulation in background thread."""
        self.core1_running = True
        self.core1_thread = threading.Thread(target=self._core1_loop, daemon=True)
        self.core1_thread.start()

        # Wait for Core 1 to signal ready
        timeout = 100
        while timeout > 0:
            if self.read_shared(0) == 0xC0DE0001:
                return True
            time.sleep(0.001)
            timeout -= 1
        return False

    def stop_core1(self):
        """Stop Core 1 emulation."""
        self.core1_running = False
        if self.core1_thread:
            self.core1_thread.join(timeout=1.0)

    def _core1_loop(self):
        """Core 1 main loop - handles FIFO messages and shared memory commands."""
        sio = self.core1.sio

        # Signal ready
        self.write_shared(0, 0xC0DE0001)

        while self.core1_running:
            # Check for FIFO data
            if sio.fifo_from_other:
                value = sio.fifo_from_other.pop(0)
                # Process: add 0x1000 to the value
                response = (value + 0x1000) & 0xFFFFFFFF
                # Send response back
                if sio.other_core:
                    sio.other_core.fifo_from_other.append(response)

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

    def __init__(self, dual_core: DualCoreRP2040):
        self.dual_core = dual_core
        self.sio = dual_core.core0.sio

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "CPUID":
            return f"{self.sio.cpuid:02x}"

        elif command == "FIFO":
            return self._cmd_fifo(args)

        elif command == "SPINLOCK":
            return self._cmd_spinlock(args)

        elif command == "SHARED":
            return self._cmd_shared(args)

        elif command == "STRESS":
            return self._cmd_stress(args)

        elif command == "STATUS":
            return self._cmd_status()

        return "ERROR: Unknown command"

    def _cmd_fifo(self, args: str) -> str:
        """Send value via FIFO to Core 1, get response."""
        args = args.strip()
        if not args:
            return "ERROR: Need hex value"

        try:
            value = int(args, 16)
        except ValueError:
            return "ERROR: Invalid hex"

        # Check Core 1 ready
        if self.dual_core.read_shared(0) != 0xC0DE0001:
            return "ERROR: Core1 not ready"

        # Send to Core 1 via FIFO
        sio = self.dual_core.core0.sio
        if sio.other_core:
            sio.other_core.fifo_from_other.append(value)

        # Wait for response
        timeout = 1000
        while timeout > 0:
            if sio.fifo_from_other:
                response = sio.fifo_from_other.pop(0)
                return f"{response:08x}"
            time.sleep(0.001)
            timeout -= 1

        return "ERROR: FIFO pop timeout"

    def _cmd_spinlock(self, args: str) -> str:
        """Test spinlock acquire/release."""
        args = args.strip()
        try:
            lock_num = int(args, 16) if args else 0
        except ValueError:
            lock_num = 0

        if lock_num >= 32:
            return "ERROR: Lock 0-31"

        sio = self.sio
        # Try to claim (read returns non-zero if claimed)
        if sio.spinlocks[lock_num] == 0:
            sio.spinlocks[lock_num] = 1
            result = "CLAIMED"
            # Release
            sio.spinlocks[lock_num] = 0
        else:
            result = "BUSY"

        return result

    def _cmd_shared(self, args: str) -> str:
        """Write to shared memory, Core 1 increments, read back."""
        args = args.strip()
        if not args:
            return "ERROR: Need hex value"

        try:
            value = int(args, 16)
        except ValueError:
            return "ERROR: Invalid hex"

        # Check Core 1 ready
        if self.dual_core.read_shared(0) != 0xC0DE0001:
            return "ERROR: Core1 not ready"

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
        """Run multiple FIFO round-trips."""
        args = args.strip()
        try:
            iterations = int(args, 16) if args else 100
        except ValueError:
            iterations = 100

        if iterations > 10000:
            iterations = 10000

        # Check Core 1 ready
        if self.dual_core.read_shared(0) != 0xC0DE0001:
            return "ERROR: Core1 not ready"

        errors = 0
        sio = self.dual_core.core0.sio

        for i in range(iterations):
            value = (i * 17) & 0xFFFFFFFF
            expected = (value + 0x1000) & 0xFFFFFFFF

            # Send
            if sio.other_core:
                sio.other_core.fifo_from_other.append(value)

            # Wait for response
            timeout = 100
            response = None
            while timeout > 0:
                if sio.fifo_from_other:
                    response = sio.fifo_from_other.pop(0)
                    break
                time.sleep(0.0001)
                timeout -= 1

            if response is None or response != expected:
                errors += 1

        return f"{iterations:08x} {errors:08x}"

    def _cmd_status(self) -> str:
        """Check Core 1 status."""
        status = self.dual_core.read_shared(0)
        if status == 0xC0DE0001:
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
        print(f"  PASS: Core 0 CPUID = {response}")
        return True
    else:
        print(f"  FAIL: Expected 00, got {response}")
        return False


def test_core1_status(cdc):
    """Test Core 1 status."""
    print("\n=== Test: Core 1 Status ===")
    response = cdc.send_command("STATUS")
    if response == "READY":
        print("  PASS: Core 1 is READY")
        return True
    else:
        print(f"  FAIL: Core 1 status = {response}")
        return False


def test_fifo_communication(cdc):
    """Test inter-core FIFO communication."""
    print("\n=== Test: Inter-Core FIFO ===")

    # Send value, expect value + 0x1000 back
    test_values = [0x00000000, 0x12345678, 0xDEADBEEF, 0x00001234]

    for value in test_values:
        response = cdc.send_command(f"FIFO {value:08x}")
        expected = f"{(value + 0x1000) & 0xFFFFFFFF:08x}"

        if response != expected:
            print(f"  FAIL: FIFO {value:08x} -> {response}, expected {expected}")
            return False

    print(f"  PASS: {len(test_values)} FIFO round-trips successful")
    return True


def test_spinlock(cdc):
    """Test spinlock acquire/release."""
    print("\n=== Test: Spinlock ===")

    for lock in [0, 15, 31]:
        response = cdc.send_command(f"SPINLOCK {lock:02x}")
        if response != "CLAIMED":
            print(f"  FAIL: Spinlock {lock} = {response}")
            return False

    print("  PASS: Spinlocks 0, 15, 31 claimed and released")
    return True


def test_shared_memory(cdc):
    """Test shared memory communication."""
    print("\n=== Test: Shared Memory ===")

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
    """Test FIFO stress with many iterations."""
    print("\n=== Test: FIFO Stress ===")

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
    print("RP2040 Multicore CDC Test")
    print("=" * 60)

    # Create dual-core RP2040
    print("\nInitializing dual-core RP2040...")
    dual_core = DualCoreRP2040()
    print(f"  Core 0: CPUID = {dual_core.core0.sio.cpuid}")
    print(f"  Core 1: CPUID = {dual_core.core1.sio.cpuid}")
    print(f"  FIFO linked: {dual_core.core0.sio.other_core is not None}")

    # Start Core 1
    print("\nStarting Core 1...")
    if not dual_core.start_core1():
        print("  FAIL: Core 1 did not start")
        return 1
    print("  Core 1 started and ready")

    # Create CDC interface
    cdc = CDCInterface(dual_core)

    # Run tests
    results = []

    try:
        results.append(("PING", test_ping(cdc)))
        results.append(("CPUID", test_cpuid(cdc)))
        results.append(("Core 1 Status", test_core1_status(cdc)))
        results.append(("FIFO Communication", test_fifo_communication(cdc)))
        results.append(("Spinlock", test_spinlock(cdc)))
        results.append(("Shared Memory", test_shared_memory(cdc)))
        results.append(("FIFO Stress", test_stress(cdc)))
    finally:
        # Stop Core 1
        dual_core.stop_core1()

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
