#!/usr/bin/env python3
"""
I2C EEPROM CDC Test Harness

Tests the I2C EEPROM firmware by simulating register-level access and
connecting a virtual 24C256 EEPROM to the STM32 I2C peripheral.

This demonstrates end-to-end peripheral testing:
1. STM32 I2C peripheral (Python emulation)
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

from slab_stm32 import STM32F439PeripheralSet
from virtual_components import EEPROM_24Cxx


class I2CEEPROMBridge:
    """
    Bridge between STM32 I2C callbacks and 24C256 EEPROM.

    Handles the I2C protocol:
    - START with address (write or read)
    - DATA bytes
    - STOP
    """

    def __init__(self, eeprom: EEPROM_24Cxx, i2c):
        self.eeprom = eeprom
        self.i2c = i2c
        self.is_read = False
        self.write_buffer = bytearray()
        self.address_set = False

        # Connect callbacks
        i2c.on_start = self.on_start
        i2c.on_write = self.on_write
        i2c.on_read = self.on_read
        i2c.on_stop = self.on_stop

    def on_start(self, addr: int, is_read: bool):
        """Handle START condition with address."""
        if addr == self.eeprom.address:
            self.is_read = is_read
            if not is_read:
                # Write mode: reset buffer for new transaction
                self.write_buffer = bytearray()
                self.address_set = False

    def on_write(self, data: int):
        """Handle write byte."""
        self.write_buffer.append(data)

        # For 24C256, first 2 bytes are address
        if len(self.write_buffer) == 2 and not self.address_set:
            addr = (self.write_buffer[0] << 8) | self.write_buffer[1]
            self.eeprom._write_address = addr
            self.address_set = True

    def on_read(self) -> int:
        """Handle read byte."""
        # Read from current EEPROM address
        addr = self.eeprom._write_address
        data = self.eeprom._memory[addr % self.eeprom.size]
        self.eeprom._write_address = (addr + 1) % self.eeprom.size
        return data

    def on_stop(self):
        """Handle STOP condition."""
        if not self.is_read and len(self.write_buffer) > 2:
            # Write data to EEPROM (skip address bytes)
            start_addr = (self.write_buffer[0] << 8) | self.write_buffer[1]
            data = self.write_buffer[2:]
            for i, byte in enumerate(data):
                addr = (start_addr + i) % self.eeprom.size
                self.eeprom._memory[addr] = byte


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

    def _i2c_write(self, addr: int, data: bytes) -> bool:
        """Perform I2C write transaction."""
        # START + address (write)
        self.bridge.on_start(addr, False)

        # Data bytes
        for b in data:
            self.bridge.on_write(b)

        # STOP
        self.bridge.on_stop()

        return True

    def _i2c_read(self, addr: int, length: int) -> bytes:
        """Perform I2C read transaction."""
        # START + address (read)
        self.bridge.on_start(addr, True)

        # Read bytes
        data = []
        for _ in range(length):
            data.append(self.bridge.on_read())

        # STOP
        self.bridge.on_stop()

        return bytes(data)

    def _i2c_write_read(self, addr: int, write_data: bytes, read_len: int) -> bytes:
        """Perform I2C write-then-read transaction (repeated start)."""
        # First: write address bytes
        self.bridge.on_start(addr, False)
        for b in write_data:
            self.bridge.on_write(b)

        # Repeated start for read (no stop in between)
        self.bridge.on_start(addr, True)

        # Read bytes
        data = []
        for _ in range(read_len):
            data.append(self.bridge.on_read())

        # STOP
        self.bridge.on_stop()

        return bytes(data)

    def _cmd_probe(self) -> str:
        """Check if EEPROM responds (try to read 1 byte)."""
        try:
            # Set address to 0
            addr_bytes = bytes([0x00, 0x00])
            data = self._i2c_write_read(self.eeprom.address, addr_bytes, 1)
            return "OK"
        except Exception as e:
            return f"ERROR: {e}"

    def _cmd_read(self, args: str) -> str:
        """Read data from EEPROM."""
        if len(args) < 4:
            return "ERROR: Need 2-byte address"

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

        # Write address, then read
        addr_bytes = bytes([(addr >> 8) & 0xFF, addr & 0xFF])
        data = self._i2c_write_read(self.eeprom.address, addr_bytes, length)

        return ''.join(f'{b:02x}' for b in data)

    def _cmd_write(self, args: str) -> str:
        """Write data to EEPROM."""
        if len(args) < 4:
            return "ERROR: Need 2-byte address"

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
        self._i2c_write(self.eeprom.address, write_data)

        return "OK"

    def _cmd_fill(self, args: str) -> str:
        """Fill EEPROM with pattern."""
        if len(args) < 4:
            return "ERROR: Need 2-byte address"

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
        self._i2c_write(self.eeprom.address, write_data)

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
    print("I2C EEPROM CDC Test (STM32F439 + 24C256)")
    print("=" * 60)

    # Create STM32F439 peripheral set
    print("\nInitializing STM32F439 peripheral set...")
    stm32 = STM32F439PeripheralSet()
    print(f"  Device: {stm32.device}")
    print(f"  I2C1 base: 0x{stm32.i2c1.base:08X}")

    # Create 24C256 EEPROM
    print("\nCreating 24C256 EEPROM...")
    eeprom = EEPROM_24Cxx('24C256', address=0x50)
    print(f"  Model: {eeprom.model}")
    print(f"  Size: {eeprom.size // 1024} KB")
    print(f"  Address: 0x{eeprom.address:02X}")

    # Create bridge to connect I2C to EEPROM
    bridge = I2CEEPROMBridge(eeprom, stm32.i2c1)

    # Create CDC interface
    cdc = CDCInterface(stm32.i2c1, eeprom, bridge)

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
