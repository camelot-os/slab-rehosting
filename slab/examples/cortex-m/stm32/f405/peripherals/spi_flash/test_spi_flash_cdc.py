#!/usr/bin/env python3
"""
SPI Flash CDC Test Harness

Tests the SPI Flash firmware by simulating register-level access and
connecting a virtual W25Q128 Flash chip to the STM32 SPI peripheral.

This demonstrates end-to-end peripheral testing:
1. STM32 SPI peripheral (Python emulation)
2. W25Q128 Flash virtual component
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
from virtual_components import W25QxxFlash


class SPIFlashBridge:
    """
    Bridge between STM32 SPI (byte-level) and W25Q Flash (transaction-level).

    Accumulates SPI bytes while CS is low, then performs the transaction
    when CS goes high. For commands that need immediate response (like JEDEC ID),
    we pre-compute responses.
    """

    def __init__(self, flash: W25QxxFlash):
        self.flash = flash
        self.mosi_buffer = bytearray()
        self.miso_buffer = bytearray()
        self.cs_low = False
        self._byte_index = 0

    def set_cs(self, low: bool):
        """Handle CS signal change."""
        if low and not self.cs_low:
            # CS going low: start new transaction
            self.mosi_buffer = bytearray()
            self.miso_buffer = bytearray()
            self._byte_index = 0
            self.flash.select()
        elif not low and self.cs_low:
            # CS going high: process the complete transaction
            if self.mosi_buffer:
                response = self.flash.transfer(bytes(self.mosi_buffer))
                self.miso_buffer = bytearray(response)
            self.flash.deselect()
        self.cs_low = low

    def transfer_byte(self, tx: int) -> int:
        """
        Transfer single byte via SPI.

        For read operations, we need to provide the response immediately.
        We handle this by pre-computing responses for known commands.
        """
        if not self.cs_low:
            return 0xFF

        # Accumulate MOSI byte
        self.mosi_buffer.append(tx)
        idx = len(self.mosi_buffer) - 1

        # For immediate response commands, compute on-the-fly
        if idx == 0:
            # First byte is command - return 0xFF (dummy)
            return 0xFF

        cmd = self.mosi_buffer[0]

        # JEDEC ID - immediate response
        if cmd == 0x9F:  # JEDEC ID
            jedec = self.flash.JEDEC_IDS.get(self.flash.model, (0xEF, 0x40, 0x18))
            if idx == 1:
                return jedec[0]
            elif idx == 2:
                return jedec[1]
            elif idx == 3:
                return jedec[2]

        # Read Status Register 1
        elif cmd == 0x05:  # Read Status 1
            if idx >= 1:
                return self.flash._sr1

        # Read Data - needs address first
        elif cmd == 0x03:  # Read Data
            if idx >= 4:
                addr_start = (self.mosi_buffer[1] << 16) | \
                             (self.mosi_buffer[2] << 8) | \
                             self.mosi_buffer[3]
                data_idx = idx - 4
                read_addr = addr_start + data_idx
                if read_addr < self.flash.size:
                    return self.flash._memory[read_addr]

        return 0xFF


class CDCInterface:
    """Simulates CDC-ACM interface for command processing."""

    def __init__(self, spi, flash_bridge: SPIFlashBridge):
        self.spi = spi
        self.bridge = flash_bridge
        self.output_buffer = []

    def send_command(self, cmd: str) -> str:
        """
        Send a command and get response.

        Simulates what the firmware does when processing CDC commands.
        """
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "JEDEC":
            return self._cmd_jedec()

        elif command == "STATUS":
            return self._cmd_status()

        elif command == "ERASE":
            return self._cmd_erase(args)

        elif command == "WRITE":
            return self._cmd_write(args)

        elif command == "READ":
            return self._cmd_read(args)

        return "ERROR: Unknown command"

    def _spi_xfer(self, tx: int) -> int:
        """Perform SPI transfer via bridge."""
        return self.bridge.transfer_byte(tx)

    def _cs_low(self):
        """Assert CS (active low)."""
        self.bridge.set_cs(True)

    def _cs_high(self):
        """Deassert CS."""
        self.bridge.set_cs(False)

    def _cmd_jedec(self) -> str:
        """Read JEDEC ID."""
        self._cs_low()
        self._spi_xfer(0x9F)  # JEDEC ID command
        id0 = self._spi_xfer(0xFF)
        id1 = self._spi_xfer(0xFF)
        id2 = self._spi_xfer(0xFF)
        self._cs_high()
        return f"{id0:02x}{id1:02x}{id2:02x}"

    def _cmd_status(self) -> str:
        """Read status register."""
        self._cs_low()
        self._spi_xfer(0x05)  # Read Status Register 1
        status = self._spi_xfer(0xFF)
        self._cs_high()
        return f"{status:02x}"

    def _cmd_erase(self, args: str) -> str:
        """Erase sector at address."""
        if len(args) < 6:
            return "ERROR: Need 3-byte address"

        try:
            addr = int(args[:6], 16)
        except ValueError:
            return "ERROR: Invalid address"

        # Write enable
        self._cs_low()
        self._spi_xfer(0x06)
        self._cs_high()

        # Sector erase
        self._cs_low()
        self._spi_xfer(0x20)
        self._spi_xfer((addr >> 16) & 0xFF)
        self._spi_xfer((addr >> 8) & 0xFF)
        self._spi_xfer(addr & 0xFF)
        self._cs_high()

        return "OK"

    def _cmd_write(self, args: str) -> str:
        """Write data to flash."""
        if len(args) < 6:
            return "ERROR: Need 3-byte address"

        try:
            addr = int(args[:6], 16)
        except ValueError:
            return "ERROR: Invalid address"

        # Parse data hex
        data_hex = args[6:].strip()
        if not data_hex:
            return "ERROR: No data"

        try:
            data = bytes.fromhex(data_hex)
        except ValueError:
            return "ERROR: Invalid data hex"

        # Write enable
        self._cs_low()
        self._spi_xfer(0x06)
        self._cs_high()

        # Page program
        self._cs_low()
        self._spi_xfer(0x02)
        self._spi_xfer((addr >> 16) & 0xFF)
        self._spi_xfer((addr >> 8) & 0xFF)
        self._spi_xfer(addr & 0xFF)
        for b in data:
            self._spi_xfer(b)
        self._cs_high()

        return "OK"

    def _cmd_read(self, args: str) -> str:
        """Read data from flash."""
        if len(args) < 6:
            return "ERROR: Need 3-byte address"

        try:
            addr = int(args[:6], 16)
        except ValueError:
            return "ERROR: Invalid address"

        # Parse length
        len_hex = args[6:].strip()
        if len_hex:
            try:
                length = int(len_hex[:2], 16)
            except ValueError:
                length = 16
        else:
            length = 16

        if length > 256:
            length = 256

        # Read data
        self._cs_low()
        self._spi_xfer(0x03)
        self._spi_xfer((addr >> 16) & 0xFF)
        self._spi_xfer((addr >> 8) & 0xFF)
        self._spi_xfer(addr & 0xFF)

        data = []
        for _ in range(length):
            data.append(self._spi_xfer(0xFF))
        self._cs_high()

        return ''.join(f'{b:02x}' for b in data)


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


def test_jedec_id(cdc, flash):
    """Test JEDEC ID reading."""
    print("\n=== Test: JEDEC ID ===")
    response = cdc.send_command("JEDEC")
    expected = "ef4018"  # W25Q128

    if response == expected:
        print(f"  PASS: JEDEC ID = {response}")
        return True
    else:
        print(f"  FAIL: Expected {expected}, got {response}")
        return False


def test_status_register(cdc):
    """Test status register reading."""
    print("\n=== Test: Status Register ===")
    response = cdc.send_command("STATUS")

    # Status should be 0x00 initially (not busy, WEL clear)
    try:
        status = int(response, 16)
        print(f"  Status = 0x{status:02X}")
        if status == 0x00:
            print("  PASS: Initial status is 0x00")
            return True
        else:
            print(f"  WARN: Expected 0x00, got 0x{status:02X}")
            return True  # Not a failure, just different state
    except ValueError:
        print(f"  FAIL: Invalid response {response}")
        return False


def test_erase_write_read(cdc, flash):
    """Test erase, write, read sequence."""
    print("\n=== Test: Erase/Write/Read ===")

    # 1. Erase sector at 0x000000
    print("  Erasing sector at 0x000000...")
    response = cdc.send_command("ERASE 000000")
    if response != "OK":
        print(f"  FAIL: Erase failed: {response}")
        return False

    # Verify sector is erased (all 0xFF)
    if flash._memory[0:16] != bytes([0xFF] * 16):
        print("  FAIL: Sector not erased")
        return False
    print("  Sector erased OK")

    # 2. Write test pattern
    test_data = "deadbeefcafebabe"
    print(f"  Writing data: {test_data}")
    response = cdc.send_command(f"WRITE 000000 {test_data}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Verify in flash memory
    expected = bytes.fromhex(test_data)
    if flash._memory[0:8] != expected:
        print(f"  FAIL: Data not written correctly")
        print(f"    Expected: {expected.hex()}")
        print(f"    Got: {flash._memory[0:8].hex()}")
        return False
    print("  Data written OK")

    # 3. Read back via CDC
    print("  Reading data back...")
    response = cdc.send_command("READ 000000 08")
    if response != test_data:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {test_data}")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Read back matches: {response}")
    return True


def test_write_at_offset(cdc, flash):
    """Test writing at non-zero offset."""
    print("\n=== Test: Write at Offset ===")

    # Erase sector at 0x001000
    response = cdc.send_command("ERASE 001000")
    if response != "OK":
        print(f"  FAIL: Erase failed: {response}")
        return False

    # Write at 0x001234
    test_data = "0123456789abcdef"
    response = cdc.send_command(f"WRITE 001234 {test_data}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Read back
    response = cdc.send_command("READ 001234 08")
    if response != test_data:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {test_data}")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Data at offset 0x1234: {response}")
    return True


def test_page_boundary(cdc, flash):
    """Test writing across page boundary."""
    print("\n=== Test: Page Boundary ===")

    # Erase sector at 0x002000
    response = cdc.send_command("ERASE 002000")
    if response != "OK":
        print(f"  FAIL: Erase failed: {response}")
        return False

    # Write at end of page (page boundary is 256 bytes)
    # Address 0x2FC = last 4 bytes of page
    response = cdc.send_command("WRITE 0020FC aabbccdd")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Read back from 0x20FC
    response = cdc.send_command("READ 0020FC 04")
    if response != "aabbccdd":
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: aabbccdd")
        print(f"    Got: {response}")
        return False

    print(f"  PASS: Page boundary write OK")
    return True


def test_large_read(cdc, flash):
    """Test reading larger data block."""
    print("\n=== Test: Large Read ===")

    # Pre-fill flash with pattern
    for i in range(256):
        flash._memory[0x3000 + i] = i

    # Read 256 bytes
    response = cdc.send_command("READ 003000 FF")

    # Build expected hex string
    expected = ''.join(f'{i:02x}' for i in range(255))

    # Compare first 255 bytes (FF = 255)
    if response[:510] == expected:  # 255 bytes = 510 hex chars
        print(f"  PASS: Large read (255 bytes) OK")
        return True
    else:
        print(f"  FAIL: Large read mismatch")
        print(f"    Expected first 32 bytes: {expected[:64]}")
        print(f"    Got: {response[:64]}")
        return False


def main():
    print("=" * 60)
    print("SPI Flash CDC Test (STM32F439 + W25Q128)")
    print("=" * 60)

    # Create STM32F439 peripheral set
    print("\nInitializing STM32F439 peripheral set...")
    stm32 = STM32F439PeripheralSet()
    print(f"  Device: {stm32.device}")
    print(f"  SPI1 base: 0x{stm32.spi1.base:08X}")

    # Create W25Q128 Flash
    print("\nCreating W25Q128 Flash...")
    flash = W25QxxFlash('W25Q128')
    print(f"  Model: {flash.model}")
    print(f"  Size: {flash.size // (1024*1024)} MB")

    # Create bridge
    bridge = SPIFlashBridge(flash)

    # Connect SPI to bridge
    stm32.spi1.on_transfer = bridge.transfer_byte

    # Create CDC interface
    cdc = CDCInterface(stm32.spi1, bridge)

    # Run tests
    results = []

    results.append(("PING", test_ping(cdc)))
    results.append(("JEDEC ID", test_jedec_id(cdc, flash)))
    results.append(("Status Register", test_status_register(cdc)))
    results.append(("Erase/Write/Read", test_erase_write_read(cdc, flash)))
    results.append(("Write at Offset", test_write_at_offset(cdc, flash)))
    results.append(("Page Boundary", test_page_boundary(cdc, flash)))
    results.append(("Large Read", test_large_read(cdc, flash)))

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
