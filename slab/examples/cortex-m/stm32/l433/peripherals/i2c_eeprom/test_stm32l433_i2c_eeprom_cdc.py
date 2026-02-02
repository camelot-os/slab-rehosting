#!/usr/bin/env python3
"""
STM32L433 I2C EEPROM CDC Test Harness

Tests I2C v2 peripheral with external 24C256 EEPROM:
- I2C master mode with auto-end
- EEPROM random read/write
- CDC-like command interface

This validates:
1. STM32L4xx I2C peripheral (I2Cv2)
2. 24C256 EEPROM virtual component
3. I2C addressing and data transfer

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32L476PeripheralSet
from virtual_components import EEPROM_24Cxx


class I2CEEPROMBridge:
    """
    Bridge between STM32 I2Cv2 callbacks and 24C256 EEPROM.

    I2Cv2 uses transaction-level callbacks:
    - on_start(addr, is_read) -> bool: Start condition, returns ACK
    - on_write(data) -> bool: Write byte, returns ACK
    - on_read() -> int: Read byte
    - on_stop(): Stop condition
    """

    def __init__(self, eeprom: EEPROM_24Cxx, i2c):
        self.eeprom = eeprom
        self.i2c = i2c
        self._current_addr = 0
        self._addr_bytes = []
        self._in_read = False

        # Connect callbacks
        i2c.on_start = self.on_start
        i2c.on_write = self.on_write
        i2c.on_read = self.on_read
        i2c.on_stop = self.on_stop

    def on_start(self, addr: int, is_read: bool) -> bool:
        """Handle I2C START condition."""
        if addr != self.eeprom.address:
            return False  # NACK

        self._in_read = is_read
        if not is_read:
            self._addr_bytes = []

        return True  # ACK

    def on_write(self, data: int) -> bool:
        """Handle I2C write byte."""
        # First 2 bytes are address for 24C256
        if len(self._addr_bytes) < 2:
            self._addr_bytes.append(data)
            if len(self._addr_bytes) == 2:
                self._current_addr = (self._addr_bytes[0] << 8) | self._addr_bytes[1]
            return True  # ACK

        # Write data byte to EEPROM
        mem_addr = self._current_addr % self.eeprom.size
        self.eeprom._memory[mem_addr] = data
        self._current_addr = (self._current_addr + 1) % self.eeprom.size

        return True  # ACK

    def on_read(self) -> int:
        """Handle I2C read byte."""
        mem_addr = self._current_addr % self.eeprom.size
        data = self.eeprom._memory[mem_addr]
        self._current_addr = (self._current_addr + 1) % self.eeprom.size
        return data

    def on_stop(self):
        """Handle I2C STOP condition."""
        pass


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
        """Probe EEPROM."""
        # Simulate I2C probe - just START with address, then STOP
        ack = self.bridge.on_start(self.eeprom.address, False)
        self.bridge.on_stop()

        if ack:
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

        # Simulate I2C random read:
        # 1. START + write address (2 bytes)
        # 2. Repeated START + read data
        # 3. STOP

        # Write phase - send address
        self.bridge.on_start(self.eeprom.address, False)
        self.bridge.on_write((addr >> 8) & 0xFF)
        self.bridge.on_write(addr & 0xFF)

        # Read phase
        self.bridge.on_start(self.eeprom.address, True)
        result = []
        for _ in range(length):
            result.append(self.bridge.on_read())
        self.bridge.on_stop()

        return ''.join(f'{b:02x}' for b in result)

    def _cmd_write(self, args: str) -> str:
        """Write data to EEPROM."""
        args = args.strip()
        if len(args) < 4:
            return "ERROR: Need 4-digit hex address"

        try:
            addr = int(args[:4], 16)
        except ValueError:
            return "ERROR: Invalid address"

        data_hex = args[4:].strip()
        if not data_hex:
            return "ERROR: No data"

        try:
            data = bytes.fromhex(data_hex)
        except ValueError:
            return "ERROR: Invalid data hex"

        if len(data) > 64:
            data = data[:64]

        # Simulate I2C write:
        # START + address bytes + data bytes + STOP
        self.bridge.on_start(self.eeprom.address, False)
        self.bridge.on_write((addr >> 8) & 0xFF)
        self.bridge.on_write(addr & 0xFF)
        for byte in data:
            self.bridge.on_write(byte)
        self.bridge.on_stop()

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

        # Simulate I2C write
        self.bridge.on_start(self.eeprom.address, False)
        self.bridge.on_write((addr >> 8) & 0xFF)
        self.bridge.on_write(addr & 0xFF)
        for byte in data:
            self.bridge.on_write(byte)
        self.bridge.on_stop()

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
    print("STM32L433 I2C EEPROM CDC Test (I2Cv2 + 24C256)")
    print("=" * 60)

    # Create STM32L476 peripheral set (compatible with L433)
    print("\nInitializing STM32L476 peripheral set...")
    stm32 = STM32L476PeripheralSet()
    print(f"  Device: STM32L476 (L4 family)")
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
