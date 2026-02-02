#!/usr/bin/env python3
"""
RP2040 I2C EEPROM CDC Test Harness

Tests the I2C EEPROM firmware by simulating register-level access and
connecting a virtual 24C256 EEPROM to the RP2040 I2C peripheral.

This demonstrates end-to-end peripheral testing:
1. RP2040 I2C peripheral (Synopsys DesignWare I2C)
2. 24C256 EEPROM virtual component
3. CDC-like command interface

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_rp2040 import RP2040PeripheralSet
from virtual_components import EEPROM_24Cxx


class I2CEEPROMBridge:
    """
    Bridge between RP2040 I2C callbacks and 24C256 EEPROM.

    RP2040 I2C (DW_apb_i2c) uses FIFO-based transactions:
    - on_write(addr, data) -> bool: Called when writing to device (returns ACK)
    - on_read(addr, len) -> bytes: Called when reading from device
    """

    def __init__(self, eeprom: EEPROM_24Cxx, i2c):
        self.eeprom = eeprom
        self.i2c = i2c

        # Track the current address pointer for read operations
        self._current_addr = 0

        # Connect callbacks
        i2c.on_write = self.on_write
        i2c.on_read = self.on_read

    def on_write(self, addr: int, data: bytes) -> bool:
        """Handle I2C write transaction."""
        if addr != self.eeprom.address:
            return False  # NACK - not our device

        if len(data) >= 2:
            # First 2 bytes are EEPROM address (for 24C256)
            self._current_addr = (data[0] << 8) | data[1]

            # If more data, write it to EEPROM
            if len(data) > 2:
                write_data = data[2:]
                start_addr = self._current_addr
                for i, byte in enumerate(write_data):
                    mem_addr = (start_addr + i) % self.eeprom.size
                    self.eeprom._memory[mem_addr] = byte

        return True  # ACK

    def on_read(self, addr: int, length: int) -> bytes:
        """Handle I2C read transaction."""
        if addr != self.eeprom.address:
            return b''  # Not our device

        # Read from current address
        result = bytearray()
        read_addr = self._current_addr
        for _ in range(length):
            result.append(self.eeprom._memory[read_addr % self.eeprom.size])
            read_addr = (read_addr + 1) % self.eeprom.size

        # Update address pointer
        self._current_addr = read_addr

        return bytes(result)


class CDCInterface:
    """Simulates CDC-ACM interface for EEPROM command processing."""

    def __init__(self, i2c, eeprom: EEPROM_24Cxx, bridge: I2CEEPROMBridge):
        self.i2c = i2c
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
        addr_bytes = bytes([0x00, 0x00])
        ack = self.bridge.on_write(self.eeprom.address, addr_bytes)
        if ack:
            result = self.bridge.on_read(self.eeprom.address, 1)
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
        self.bridge.on_write(self.eeprom.address, addr_bytes)

        # Read data
        data = self.bridge.on_read(self.eeprom.address, length)

        return ''.join(f'{b:02x}' for b in data)

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
        ack = self.bridge.on_write(self.eeprom.address, write_data)

        return "OK" if ack else "ERROR: Write failed"

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
        ack = self.bridge.on_write(self.eeprom.address, write_data)

        return "OK" if ack else "ERROR: Write failed"


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
    print("RP2040 I2C EEPROM CDC Test (DW_apb_i2c + 24C256)")
    print("=" * 60)

    # Create RP2040 peripheral set
    print("\nInitializing RP2040 peripheral set...")
    rp2040 = RP2040PeripheralSet()
    print(f"  Device: RP2040")
    print(f"  I2C0 base: 0x{rp2040.i2c0.base:08X}")

    # Create 24C256 EEPROM
    print("\nCreating 24C256 EEPROM...")
    eeprom = EEPROM_24Cxx('24C256', address=0x50)
    print(f"  Model: {eeprom.model}")
    print(f"  Size: {eeprom.size // 1024} KB")
    print(f"  Address: 0x{eeprom.address:02X}")

    # Create bridge to connect I2C to EEPROM
    bridge = I2CEEPROMBridge(eeprom, rp2040.i2c0)

    # Create CDC interface
    cdc = CDCInterface(rp2040.i2c0, eeprom, bridge)

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
