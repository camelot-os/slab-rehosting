#!/usr/bin/env python3
"""
I2C EEPROM Emulation Test

Tests the STM32 I2C peripheral with a virtual 24C256 EEPROM.
This validates the Python peripheral implementation matches what firmware would see.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet
from slab_stm32.stm32_i2c import STM32I2Cv1


class VirtualEEPROM:
    """Simple 24C256 EEPROM emulation for testing."""

    def __init__(self, address=0x50, size=32768):
        self.address = address
        self.size = size
        self.memory = bytearray(size)
        self.write_buffer = bytearray()
        self.read_addr = 0
        self.in_transaction = False
        self.is_read = False

    def on_start(self, addr, is_read):
        """Handle I2C START condition."""
        if addr == self.address:
            self.in_transaction = True
            self.is_read = is_read
            self.write_buffer.clear()

    def on_write(self, data):
        """Handle I2C write byte."""
        if self.in_transaction and not self.is_read:
            self.write_buffer.append(data)

    def on_read(self):
        """Handle I2C read byte."""
        if self.in_transaction and self.is_read:
            if self.read_addr < self.size:
                data = self.memory[self.read_addr]
                self.read_addr = (self.read_addr + 1) % self.size
                return data
        return 0xFF

    def on_stop(self):
        """Handle I2C STOP condition."""
        if self.in_transaction and not self.is_read:
            # Process write buffer: first 2 bytes are address
            if len(self.write_buffer) >= 2:
                addr = (self.write_buffer[0] << 8) | self.write_buffer[1]
                self.read_addr = addr  # Set for subsequent reads
                # Write remaining bytes to memory
                for i, byte in enumerate(self.write_buffer[2:]):
                    mem_addr = (addr + i) % self.size
                    self.memory[mem_addr] = byte
        self.in_transaction = False

    def get_contents(self, start=0, length=None):
        """Get memory contents."""
        if length is None:
            length = self.size - start
        return bytes(self.memory[start:start + length])


def test_i2c_eeprom_basic():
    """Test basic I2C EEPROM write and read via register access."""
    print("\n=== Test: Basic I2C EEPROM Write/Read ===")

    # Create STM32 with I2C1
    stm32 = STM32F439PeripheralSet()
    i2c = stm32.i2c1

    # Create virtual EEPROM and connect
    eeprom = VirtualEEPROM(address=0x50)
    i2c.on_start = eeprom.on_start
    i2c.on_write = eeprom.on_write
    i2c.on_read = eeprom.on_read
    i2c.on_stop = eeprom.on_stop

    # Enable I2C peripheral
    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE)

    # Simulate writing 4 bytes at address 0x0000
    test_data = [0xDE, 0xAD, 0xBE, 0xEF]

    # Generate START
    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_START)

    # Send address (write mode)
    i2c.write(i2c.base + i2c.DR, 4, 0x50 << 1)  # Address + write bit

    # Send EEPROM address (2 bytes) + data
    for byte in [0x00, 0x00] + test_data:
        i2c.write(i2c.base + i2c.DR, 4, byte)

    # Generate STOP
    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_STOP)

    # Verify EEPROM contents
    contents = eeprom.get_contents(0, 4)
    expected = bytes(test_data)

    if contents == expected:
        print(f"  PASS: EEPROM write successful")
        print(f"    Written: {test_data}")
        print(f"    In EEPROM: {list(contents)}")
        return True
    else:
        print(f"  FAIL: EEPROM mismatch")
        print(f"    Expected: {list(expected)}")
        print(f"    Got: {list(contents)}")
        return False


def test_eeprom_sequential_write():
    """Test sequential write to EEPROM."""
    print("\n=== Test: Sequential EEPROM Write ===")

    stm32 = STM32F439PeripheralSet()
    i2c = stm32.i2c1

    eeprom = VirtualEEPROM(address=0x50)
    i2c.on_start = eeprom.on_start
    i2c.on_write = eeprom.on_write
    i2c.on_read = eeprom.on_read
    i2c.on_stop = eeprom.on_stop

    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE)

    # Write 16 bytes at address 0x0100
    test_data = [i + 0x10 for i in range(16)]

    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_START)
    i2c.write(i2c.base + i2c.DR, 4, 0x50 << 1)

    for byte in [0x01, 0x00] + test_data:  # Address 0x0100
        i2c.write(i2c.base + i2c.DR, 4, byte)

    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_STOP)

    contents = eeprom.get_contents(0x0100, 16)
    expected = bytes(test_data)

    if contents == expected:
        print(f"  PASS: Sequential write successful")
        print(f"    Written 16 bytes at 0x0100")
        return True
    else:
        print(f"  FAIL: Sequential write mismatch")
        return False


def test_eeprom_read():
    """Test reading from EEPROM."""
    print("\n=== Test: EEPROM Read ===")

    stm32 = STM32F439PeripheralSet()
    i2c = stm32.i2c1

    eeprom = VirtualEEPROM(address=0x50)
    i2c.on_start = eeprom.on_start
    i2c.on_write = eeprom.on_write
    i2c.on_read = eeprom.on_read
    i2c.on_stop = eeprom.on_stop

    # Pre-populate EEPROM
    test_pattern = bytes([0x11, 0x22, 0x33, 0x44])
    eeprom.memory[0x0200:0x0204] = test_pattern

    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE)

    # Write address to EEPROM (set pointer)
    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_START)
    i2c.write(i2c.base + i2c.DR, 4, 0x50 << 1)  # Write mode
    i2c.write(i2c.base + i2c.DR, 4, 0x02)  # Address high
    i2c.write(i2c.base + i2c.DR, 4, 0x00)  # Address low
    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_STOP)

    # Now read 4 bytes
    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_START)
    i2c.write(i2c.base + i2c.DR, 4, (0x50 << 1) | 1)  # Read mode

    read_data = []
    for _ in range(4):
        # Trigger read by accessing DR
        val, _ = i2c.read(i2c.base + i2c.DR, 4)
        # Actually get data via callback
        byte = eeprom.on_read()
        read_data.append(byte)

    i2c.write(i2c.base + i2c.CR1, 4, STM32I2Cv1.CR1_PE | STM32I2Cv1.CR1_STOP)

    if bytes(read_data) == test_pattern:
        print(f"  PASS: Read successful")
        print(f"    Expected: {list(test_pattern)}")
        print(f"    Read: {read_data}")
        return True
    else:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {list(test_pattern)}")
        print(f"    Got: {read_data}")
        return False


def test_peripheral_address():
    """Verify I2C1 is at correct address."""
    print("\n=== Test: I2C1 Address ===")

    stm32 = STM32F439PeripheralSet()

    if stm32.i2c1.base == 0x40005400:
        print(f"  PASS: I2C1 at 0x{stm32.i2c1.base:08X}")
        return True
    else:
        print(f"  FAIL: I2C1 at 0x{stm32.i2c1.base:08X}, expected 0x40005400")
        return False


def main():
    print("=" * 60)
    print("I2C EEPROM Peripheral Emulation Test")
    print("=" * 60)

    results = []

    results.append(("I2C1 Address", test_peripheral_address()))
    results.append(("Basic Write", test_i2c_eeprom_basic()))
    results.append(("Sequential Write", test_eeprom_sequential_write()))
    results.append(("Read", test_eeprom_read()))

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
