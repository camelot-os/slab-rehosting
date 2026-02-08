#!/usr/bin/env python3
"""
SPI Flash Emulation Test

Tests the STM32 SPI peripheral with a virtual W25Q128 Flash.
This validates the Python peripheral implementation matches what firmware would see.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet
from slab_stm32.stm32_spi import STM32SPIv1


class VirtualW25Q128:
    """
    Simple W25Q128 SPI Flash emulation for testing.

    Supports:
    - 0x9F: JEDEC ID
    - 0x05: Read Status Register 1
    - 0x06: Write Enable
    - 0x04: Write Disable
    - 0x03: Read Data
    - 0x02: Page Program
    - 0x20: Sector Erase (4KB)
    """

    # Commands
    CMD_WRITE_ENABLE = 0x06
    CMD_WRITE_DISABLE = 0x04
    CMD_READ_STATUS_1 = 0x05
    CMD_READ_DATA = 0x03
    CMD_PAGE_PROGRAM = 0x02
    CMD_SECTOR_ERASE = 0x20
    CMD_JEDEC_ID = 0x9F

    # Status bits
    SR_BUSY = 0x01
    SR_WEL = 0x02

    # W25Q128 JEDEC ID
    JEDEC_ID = [0xEF, 0x40, 0x18]

    def __init__(self, size=16 * 1024 * 1024):  # 16MB
        self.size = size
        self.memory = bytearray([0xFF] * size)
        self.status = 0
        self.cs_active = False
        self.cmd_buffer = bytearray()
        self.response_buffer = bytearray()
        self.response_idx = 0

    def select(self):
        """Chip select asserted (CS low)."""
        self.cs_active = True
        self.cmd_buffer.clear()
        self.response_buffer.clear()
        self.response_idx = 0

    def deselect(self):
        """Chip select deasserted (CS high)."""
        if self.cs_active:
            self._process_command()
        self.cs_active = False

    def transfer(self, tx_byte):
        """
        Handle SPI byte transfer.
        Returns the MISO byte for this clock cycle.
        """
        if not self.cs_active:
            return 0xFF

        self.cmd_buffer.append(tx_byte)

        # Generate response based on command
        if len(self.cmd_buffer) == 1:
            cmd = self.cmd_buffer[0]
            if cmd == self.CMD_JEDEC_ID:
                self.response_buffer = bytearray([0xFF] + self.JEDEC_ID)
            elif cmd == self.CMD_READ_STATUS_1:
                self.response_buffer = bytearray([0xFF, self.status])
            elif cmd == self.CMD_WRITE_ENABLE:
                self.status |= self.SR_WEL
                self.response_buffer = bytearray([0xFF])
            elif cmd == self.CMD_WRITE_DISABLE:
                self.status &= ~self.SR_WEL
                self.response_buffer = bytearray([0xFF])
            else:
                self.response_buffer = bytearray([0xFF])

        # For read data command, fill response as we receive address
        if len(self.cmd_buffer) == 4 and self.cmd_buffer[0] == self.CMD_READ_DATA:
            addr = (self.cmd_buffer[1] << 16) | (self.cmd_buffer[2] << 8) | self.cmd_buffer[3]
            # Extend response buffer for reads
            self.response_buffer = bytearray([0xFF] * 4)  # Dummy for cmd + addr

        # For ongoing reads
        if len(self.cmd_buffer) > 4 and self.cmd_buffer[0] == self.CMD_READ_DATA:
            addr = (self.cmd_buffer[1] << 16) | (self.cmd_buffer[2] << 8) | self.cmd_buffer[3]
            offset = len(self.cmd_buffer) - 5
            read_addr = addr + offset
            if read_addr < self.size:
                return self.memory[read_addr]
            return 0xFF

        # Return response byte
        if self.response_idx < len(self.response_buffer):
            resp = self.response_buffer[self.response_idx]
            self.response_idx += 1
            return resp

        return 0xFF

    def _process_command(self):
        """Process complete command when CS goes high."""
        if len(self.cmd_buffer) < 1:
            return

        cmd = self.cmd_buffer[0]

        if cmd == self.CMD_PAGE_PROGRAM and self.status & self.SR_WEL:
            if len(self.cmd_buffer) > 4:
                addr = (self.cmd_buffer[1] << 16) | (self.cmd_buffer[2] << 8) | self.cmd_buffer[3]
                data = self.cmd_buffer[4:]
                # Page program: can only change 1->0
                page_start = addr & ~0xFF
                for i, byte in enumerate(data):
                    write_addr = page_start | ((addr + i) & 0xFF)
                    if write_addr < self.size:
                        self.memory[write_addr] &= byte
                self.status &= ~self.SR_WEL

        elif cmd == self.CMD_SECTOR_ERASE and self.status & self.SR_WEL:
            if len(self.cmd_buffer) >= 4:
                addr = (self.cmd_buffer[1] << 16) | (self.cmd_buffer[2] << 8) | self.cmd_buffer[3]
                sector_start = addr & ~0xFFF
                for i in range(4096):
                    if sector_start + i < self.size:
                        self.memory[sector_start + i] = 0xFF
                self.status &= ~self.SR_WEL

    def get_contents(self, start=0, length=None):
        """Get memory contents."""
        if length is None:
            length = min(256, self.size - start)
        return bytes(self.memory[start:start + length])


def test_spi_flash_jedec_id():
    """Test JEDEC ID read via SPI."""
    print("\n=== Test: SPI Flash JEDEC ID ===")

    stm32 = STM32F439PeripheralSet()
    spi = stm32.spi1

    flash = VirtualW25Q128()

    def on_transfer(tx_data):
        return flash.transfer(tx_data)

    spi.on_transfer = on_transfer

    # Enable SPI
    spi.write(spi.base + spi.CR1, 4,
              STM32SPIv1.CR1_MSTR | STM32SPIv1.CR1_SSM | STM32SPIv1.CR1_SSI | STM32SPIv1.CR1_SPE)

    # Select flash (simulated)
    flash.select()

    # Send JEDEC ID command and read 3 bytes
    jedec_id = []

    # Write command, get dummy response
    spi.write(spi.base + spi.DR, 4, 0x9F)
    val, _ = spi.read(spi.base + spi.DR, 4)

    # Read 3 ID bytes
    for i in range(3):
        spi.write(spi.base + spi.DR, 4, 0xFF)
        val, _ = spi.read(spi.base + spi.DR, 4)
        jedec_id.append(val & 0xFF)

    flash.deselect()

    expected = [0xEF, 0x40, 0x18]
    if jedec_id == expected:
        print(f"  PASS: JEDEC ID correct")
        print(f"    Got: {[hex(b) for b in jedec_id]}")
        return True
    else:
        print(f"  FAIL: JEDEC ID mismatch")
        print(f"    Expected: {[hex(b) for b in expected]}")
        print(f"    Got: {[hex(b) for b in jedec_id]}")
        return False


def test_spi_flash_erase():
    """Test sector erase."""
    print("\n=== Test: SPI Flash Sector Erase ===")

    stm32 = STM32F439PeripheralSet()
    spi = stm32.spi1

    flash = VirtualW25Q128()

    # Pre-populate with non-FF data
    for i in range(256):
        flash.memory[i] = i

    spi.on_transfer = lambda tx: flash.transfer(tx)
    spi.write(spi.base + spi.CR1, 4,
              STM32SPIv1.CR1_MSTR | STM32SPIv1.CR1_SSM | STM32SPIv1.CR1_SSI | STM32SPIv1.CR1_SPE)

    # Write enable
    flash.select()
    spi.write(spi.base + spi.DR, 4, 0x06)
    spi.read(spi.base + spi.DR, 4)
    flash.deselect()

    # Sector erase at address 0
    flash.select()
    for byte in [0x20, 0x00, 0x00, 0x00]:
        spi.write(spi.base + spi.DR, 4, byte)
        spi.read(spi.base + spi.DR, 4)
    flash.deselect()

    # Verify erased (all 0xFF)
    contents = flash.get_contents(0, 256)
    all_ff = all(b == 0xFF for b in contents)

    if all_ff:
        print(f"  PASS: Sector erased to 0xFF")
        return True
    else:
        print(f"  FAIL: Sector not properly erased")
        return False


def test_spi_flash_program():
    """Test page program."""
    print("\n=== Test: SPI Flash Page Program ===")

    stm32 = STM32F439PeripheralSet()
    spi = stm32.spi1

    flash = VirtualW25Q128()
    spi.on_transfer = lambda tx: flash.transfer(tx)
    spi.write(spi.base + spi.CR1, 4,
              STM32SPIv1.CR1_MSTR | STM32SPIv1.CR1_SSM | STM32SPIv1.CR1_SSI | STM32SPIv1.CR1_SPE)

    test_data = bytes([i for i in range(64)])

    # Write enable
    flash.select()
    spi.write(spi.base + spi.DR, 4, 0x06)
    spi.read(spi.base + spi.DR, 4)
    flash.deselect()

    # Page program at address 0x1000
    flash.select()
    for byte in [0x02, 0x00, 0x10, 0x00]:  # Command + address
        spi.write(spi.base + spi.DR, 4, byte)
        spi.read(spi.base + spi.DR, 4)
    for byte in test_data:
        spi.write(spi.base + spi.DR, 4, byte)
        spi.read(spi.base + spi.DR, 4)
    flash.deselect()

    # Verify
    contents = flash.get_contents(0x1000, 64)

    if contents == test_data:
        print(f"  PASS: Page program successful")
        print(f"    Wrote 64 bytes at 0x1000")
        return True
    else:
        print(f"  FAIL: Page program mismatch")
        return False


def test_spi_flash_read():
    """Test data read."""
    print("\n=== Test: SPI Flash Read ===")

    stm32 = STM32F439PeripheralSet()
    spi = stm32.spi1

    flash = VirtualW25Q128()

    # Pre-populate
    test_pattern = bytes([0xAA, 0x55, 0x12, 0x34])
    flash.memory[0x2000:0x2004] = test_pattern

    spi.on_transfer = lambda tx: flash.transfer(tx)
    spi.write(spi.base + spi.CR1, 4,
              STM32SPIv1.CR1_MSTR | STM32SPIv1.CR1_SSM | STM32SPIv1.CR1_SSI | STM32SPIv1.CR1_SPE)

    # Read data command
    flash.select()
    for byte in [0x03, 0x00, 0x20, 0x00]:  # Command + address
        spi.write(spi.base + spi.DR, 4, byte)
        spi.read(spi.base + spi.DR, 4)

    read_data = []
    for _ in range(4):
        spi.write(spi.base + spi.DR, 4, 0xFF)
        val, _ = spi.read(spi.base + spi.DR, 4)
        read_data.append(val & 0xFF)
    flash.deselect()

    if bytes(read_data) == test_pattern:
        print(f"  PASS: Read successful")
        print(f"    Expected: {list(test_pattern)}")
        print(f"    Got: {read_data}")
        return True
    else:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {list(test_pattern)}")
        print(f"    Got: {read_data}")
        return False


def test_peripheral_address():
    """Verify SPI1 is at correct address."""
    print("\n=== Test: SPI1 Address ===")

    stm32 = STM32F439PeripheralSet()

    if stm32.spi1.base == 0x40013000:
        print(f"  PASS: SPI1 at 0x{stm32.spi1.base:08X}")
        return True
    else:
        print(f"  FAIL: SPI1 at 0x{stm32.spi1.base:08X}, expected 0x40013000")
        return False


def main():
    print("=" * 60)
    print("SPI Flash Peripheral Emulation Test")
    print("=" * 60)

    results = []

    results.append(("SPI1 Address", test_peripheral_address()))
    results.append(("JEDEC ID", test_spi_flash_jedec_id()))
    results.append(("Sector Erase", test_spi_flash_erase()))
    results.append(("Page Program", test_spi_flash_program()))
    results.append(("Data Read", test_spi_flash_read()))

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
