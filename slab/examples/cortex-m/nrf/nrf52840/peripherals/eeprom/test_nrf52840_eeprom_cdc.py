#!/usr/bin/env python3
"""
NRF52840 I2C EEPROM CDC Test Harness

Tests the I2C EEPROM firmware by simulating register-level access and
connecting a virtual 24C256 EEPROM to the NRF52840 TWIM peripheral.

This demonstrates end-to-end peripheral testing:
1. NRF52840 TWIM peripheral (Python emulation)
2. 24C256 EEPROM virtual component
3. CDC-like command interface

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_nrf import NRF52840PeripheralSet
from virtual_components import EEPROM_24Cxx


class TWIMEEPROMBridge:
    """
    Bridge between NRF TWIM callbacks and 24C256 EEPROM.

    NRF TWIM uses EasyDMA, so it processes entire transactions at once.
    The on_transfer callback receives:
    - addr: 7-bit I2C address
    - data: bytes written (for writes) or empty (for reads)
    - is_read: True for read operations

    Returns bytes for reads or empty bytes for writes.
    """

    def __init__(self, eeprom: EEPROM_24Cxx, twim):
        self.eeprom = eeprom
        self.twim = twim

        # Track the current address pointer for read operations
        self._current_addr = 0

        # Connect callback
        twim.on_transfer = self.on_transfer

    def on_transfer(self, addr: int, data: bytes, is_read: bool) -> bytes:
        """Handle TWIM transaction."""
        if addr != self.eeprom.address:
            return b''  # Not our device

        if is_read:
            # Read from current address
            result = bytearray()
            read_addr = self._current_addr
            # Read up to the requested amount (TWIM will limit via RXD_MAXCNT)
            for i in range(256):  # Max read
                result.append(self.eeprom._memory[read_addr % self.eeprom.size])
                read_addr = (read_addr + 1) % self.eeprom.size
            return bytes(result)

        else:
            # Write operation
            if len(data) >= 2:
                # First 2 bytes are address (for 24C256)
                self._current_addr = (data[0] << 8) | data[1]

                # If more data, write it to EEPROM
                if len(data) > 2:
                    write_data = data[2:]
                    start_addr = self._current_addr
                    for i, byte in enumerate(write_data):
                        addr = (start_addr + i) % self.eeprom.size
                        self.eeprom._memory[addr] = byte

            return b''


class CDCInterface:
    """Simulates CDC-ACM interface for EEPROM command processing."""

    def __init__(self, twim, eeprom: EEPROM_24Cxx, bridge: TWIMEEPROMBridge):
        self.twim = twim
        self.eeprom = eeprom
        self.bridge = bridge

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "PROBE":
            return self._cmd_probe()

        elif command == "READ":
            return self._cmd_read(args)

        elif command == "WRITE":
            return self._cmd_write(args)

        elif command == "FILL":
            return self._cmd_fill(args)

        return "ERROR: Unknown command"

    def _cmd_probe(self) -> str:
        """Check if EEPROM responds."""
        # Set address to 0 and read 1 byte
        self.bridge._current_addr = 0
        # Simulate a probe by reading 1 byte
        result = self.bridge.on_transfer(self.eeprom.address, bytes([0x00, 0x00]), False)
        result = self.bridge.on_transfer(self.eeprom.address, b'', True)
        if result:
            return "OK"
        return "ERROR: No response"

    def _cmd_read(self, args: str) -> str:
        """Read data from EEPROM."""
        args = args.strip()
        if len(args) < 4:
            return "ERROR: Need 4-digit hex address"

        try:
            addr = int(args[:4], 16)
        except ValueError:
            return "ERROR: Invalid address"

        # Parse length
        len_hex = args[4:].strip()
        if len_hex:
            try:
                length = int(len_hex[:2], 16)
            except ValueError:
                length = 16
        else:
            length = 16

        if length > 64:
            length = 64
        if length == 0:
            length = 16

        # Write address bytes (set EEPROM address pointer)
        addr_bytes = bytes([(addr >> 8) & 0xFF, addr & 0xFF])
        self.bridge.on_transfer(self.eeprom.address, addr_bytes, False)

        # Read data
        data = self.bridge.on_transfer(self.eeprom.address, b'', True)

        return ''.join(f'{b:02x}' for b in data[:length])

    def _cmd_write(self, args: str) -> str:
        """Write data to EEPROM."""
        args = args.strip()
        if len(args) < 4:
            return "ERROR: Need 4-digit hex address"

        try:
            addr = int(args[:4], 16)
        except ValueError:
            return "ERROR: Invalid address"

        # Parse data hex
        data_hex = args[4:].strip()
        if not data_hex:
            return "ERROR: No data"

        try:
            data = bytes.fromhex(data_hex)
        except ValueError:
            return "ERROR: Invalid data hex"

        if len(data) > 64:
            data = data[:64]

        # Build message: address + data
        write_data = bytes([(addr >> 8) & 0xFF, addr & 0xFF]) + data
        self.bridge.on_transfer(self.eeprom.address, write_data, False)

        return "OK"

    def _cmd_fill(self, args: str) -> str:
        """Fill EEPROM with pattern."""
        args = args.strip()
        if len(args) < 4:
            return "ERROR: Need 4-digit hex address"

        try:
            addr = int(args[:4], 16)
        except ValueError:
            return "ERROR: Invalid address"

        rest = args[4:].strip()

        if len(rest) < 2:
            return "ERROR: Need length"

        try:
            length = int(rest[:2], 16)
        except ValueError:
            return "ERROR: Invalid length"

        # Parse pattern
        pattern_hex = rest[2:].strip()
        if pattern_hex:
            try:
                pattern = int(pattern_hex[:2], 16)
            except ValueError:
                pattern = 0xFF
        else:
            pattern = 0xFF

        if length > 64:
            length = 64

        # Build fill data
        data = bytes([pattern] * length)
        write_data = bytes([(addr >> 8) & 0xFF, addr & 0xFF]) + data
        self.bridge.on_transfer(self.eeprom.address, write_data, False)

        return "OK"


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


def test_probe(cdc):
    """Test EEPROM probe."""
    print("\n=== Test: PROBE ===")
    response = cdc.send_command("PROBE")
    if response == "OK":
        print("  PASS: EEPROM detected")
        return True
    else:
        print(f"  FAIL: {response}")
        return False


def test_write_read(cdc, eeprom):
    """Test write and read."""
    print("\n=== Test: Write/Read ===")

    # Write test data
    test_data = "deadbeefcafebabe"
    print(f"  Writing data at 0x0000: {test_data}")
    response = cdc.send_command(f"WRITE 0000 {test_data}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Verify in EEPROM memory
    expected = bytes.fromhex(test_data)
    if eeprom._memory[0:8] != expected:
        print(f"  FAIL: EEPROM memory mismatch")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got: {eeprom._memory[0:8].hex()}")
        return False
    print("  Data written to EEPROM OK")

    # Read back via CDC
    print("  Reading data back...")
    response = cdc.send_command("READ 0000 08")
    if response != test_data:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {test_data}")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Read matches: {response}")
    return True


def test_write_at_offset(cdc, eeprom):
    """Test writing at non-zero offset."""
    print("\n=== Test: Write at Offset ===")

    # Write at 0x1000
    test_data = "0123456789abcdef"
    response = cdc.send_command(f"WRITE 1000 {test_data}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Read back
    response = cdc.send_command("READ 1000 08")
    if response != test_data:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {test_data}")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Data at offset 0x1000: {response}")
    return True


def test_fill(cdc, eeprom):
    """Test fill command."""
    print("\n=== Test: Fill ===")

    # Fill 16 bytes with 0xAA at 0x2000
    response = cdc.send_command("FILL 2000 10 aa")
    if response != "OK":
        print(f"  FAIL: Fill failed: {response}")
        return False

    # Read back
    response = cdc.send_command("READ 2000 10")
    expected = "aa" * 16
    if response != expected:
        print(f"  FAIL: Fill mismatch")
        print(f"    Expected: {expected}")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Filled 16 bytes with 0xAA")
    return True


def test_sequential_write(cdc, eeprom):
    """Test sequential write."""
    print("\n=== Test: Sequential Write ===")

    # Write incrementing pattern
    pattern = ''.join(f'{i:02x}' for i in range(16))
    response = cdc.send_command(f"WRITE 3000 {pattern}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Read back
    response = cdc.send_command("READ 3000 10")
    if response != pattern:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {pattern}")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Sequential pattern OK")
    return True


def test_large_read(cdc, eeprom):
    """Test reading larger block."""
    print("\n=== Test: Large Read ===")

    # Pre-fill EEPROM at 0x4000 with pattern
    for i in range(64):
        eeprom._memory[0x4000 + i] = i

    # Read 64 bytes
    response = cdc.send_command("READ 4000 40")
    expected = ''.join(f'{i:02x}' for i in range(64))

    if response == expected:
        print(f"  PASS: Large read (64 bytes) OK")
        return True
    else:
        print(f"  FAIL: Large read mismatch")
        print(f"    Expected first 16: {expected[:32]}")
        print(f"    Got: {response[:32]}")
        return False


def main():
    print("=" * 60)
    print("NRF52840 I2C EEPROM CDC Test (TWIM + 24C256)")
    print("=" * 60)

    # Create NRF52840 peripheral set
    print("\nInitializing NRF52840 peripheral set...")
    nrf = NRF52840PeripheralSet()
    print(f"  Device: {nrf.device}")
    print(f"  TWIM0 base: 0x{nrf.twim0.base:08X}")

    # Create 24C256 EEPROM
    print("\nCreating 24C256 EEPROM...")
    eeprom = EEPROM_24Cxx('24C256', address=0x50)
    print(f"  Model: {eeprom.model}")
    print(f"  Size: {eeprom.size // 1024} KB")
    print(f"  Address: 0x{eeprom.address:02X}")

    # Create bridge to connect TWIM to EEPROM
    bridge = TWIMEEPROMBridge(eeprom, nrf.twim0)

    # Create CDC interface
    cdc = CDCInterface(nrf.twim0, eeprom, bridge)

    # Run tests
    results = []

    results.append(("PING", test_ping(cdc)))
    results.append(("PROBE", test_probe(cdc)))
    results.append(("Write/Read", test_write_read(cdc, eeprom)))
    results.append(("Write at Offset", test_write_at_offset(cdc, eeprom)))
    results.append(("Fill", test_fill(cdc, eeprom)))
    results.append(("Sequential Write", test_sequential_write(cdc, eeprom)))
    results.append(("Large Read", test_large_read(cdc, eeprom)))

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
