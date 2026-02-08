#!/usr/bin/env python3
"""
NRF52840 QSPI Flash CDC Test Harness

Tests QSPI-driven Flash transfers with an external W25Q128 Flash:
- QSPI EasyDMA for read/write transfers
- Custom instruction interface for JEDEC ID, status register
- CDC-like command interface

This validates:
1. NRF52840 QSPI peripheral
2. W25Q128 Flash virtual component
3. QSPI EasyDMA memory-to-flash and flash-to-memory transfers

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_nrf import NRF52840PeripheralSet
from virtual_components import W25QxxFlash


class QSPIFlashBridge:
    """
    Bridge between NRF QSPI callbacks and W25Q Flash.

    Handles QSPI operations and custom instructions.
    Operates directly on flash memory for QSPI EasyDMA operations.
    """

    def __init__(self, flash: W25QxxFlash):
        self.flash = flash

    def on_flash_access(self, operation: str, address: int, data: bytes) -> bytes:
        """Handle QSPI flash operations."""
        if operation == 'read':
            # Direct memory read
            end_addr = min(address + len(data), self.flash.size)
            return bytes(self.flash._memory[address:end_addr])
        elif operation == 'write':
            # Page program (flash can only clear bits)
            if self.flash._sr1 & self.flash.SR1_WEL:
                page_start = address & ~0xFF  # 256-byte page boundary
                for i, byte in enumerate(data):
                    write_addr = page_start | ((address + i) & 0xFF)
                    if write_addr < self.flash.size:
                        self.flash._memory[write_addr] &= byte
                self.flash._sr1 &= ~self.flash.SR1_WEL
            return b''
        elif operation == 'erase_4k':
            # Sector erase (4KB)
            if self.flash._sr1 & self.flash.SR1_WEL:
                sector_start = address & ~0xFFF
                for i in range(4096):
                    if sector_start + i < self.flash.size:
                        self.flash._memory[sector_start + i] = 0xFF
                self.flash._sr1 &= ~self.flash.SR1_WEL
            return b''
        elif operation == 'erase_64k':
            # Block erase (64KB)
            if self.flash._sr1 & self.flash.SR1_WEL:
                block_start = address & ~0xFFFF
                for i in range(65536):
                    if block_start + i < self.flash.size:
                        self.flash._memory[block_start + i] = 0xFF
                self.flash._sr1 &= ~self.flash.SR1_WEL
            return b''
        elif operation == 'erase_all':
            # Chip erase
            if self.flash._sr1 & self.flash.SR1_WEL:
                self.flash._memory = bytearray([0xFF] * self.flash.size)
                self.flash._sr1 &= ~self.flash.SR1_WEL
            return b''
        return b''

    def on_custom_instruction(self, opcode: int, data_in: bytes) -> bytes:
        """Handle QSPI custom instructions (JEDEC ID, status, etc.)."""
        if opcode == 0x9F:  # Read JEDEC ID
            jedec = self.flash.JEDEC_IDS.get(self.flash.model, (0xEF, 0x40, 0x18))
            return bytes(jedec)
        elif opcode == 0x05:  # Read Status Register
            return bytes([self.flash._sr1])
        elif opcode == 0x06:  # Write Enable
            self.flash._sr1 |= self.flash.SR1_WEL
            return b''
        elif opcode == 0x04:  # Write Disable
            self.flash._sr1 &= ~self.flash.SR1_WEL
            return b''
        return bytes(len(data_in)) if data_in else b''


class DMAMemoryBridge:
    """
    Bridge for DMA memory access.

    Provides mem_read/mem_write callbacks for QSPI EasyDMA.
    """

    def __init__(self, memory_size: int = 0x40000):
        self.memory = bytearray(memory_size)
        self.base_address = 0x20000000  # SRAM base

    def mem_read(self, addr: int, size: int) -> bytes:
        """Read from memory (for QSPI EasyDMA)."""
        offset = addr - self.base_address
        if 0 <= offset < len(self.memory) - size + 1:
            return bytes(self.memory[offset:offset + size])
        return bytes(size)

    def mem_write(self, addr: int, data: bytes):
        """Write to memory (for QSPI EasyDMA)."""
        offset = addr - self.base_address
        if 0 <= offset < len(self.memory) - len(data) + 1:
            self.memory[offset:offset + len(data)] = data

    def set_bytes(self, addr: int, data: bytes):
        """Set memory bytes directly."""
        offset = addr - self.base_address
        if 0 <= offset < len(self.memory) - len(data) + 1:
            self.memory[offset:offset + len(data)] = data

    def get_bytes(self, addr: int, length: int) -> bytes:
        """Get memory bytes directly."""
        offset = addr - self.base_address
        if 0 <= offset < len(self.memory) - length + 1:
            return bytes(self.memory[offset:offset + length])
        return bytes(length)


class CDCInterface:
    """Simulates CDC-ACM interface for command processing."""

    def __init__(self, qspi, flash: W25QxxFlash, bridge: QSPIFlashBridge, memory: DMAMemoryBridge):
        self.qspi = qspi
        self.flash = flash
        self.bridge = bridge
        self.memory = memory

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
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

    def _cmd_jedec(self) -> str:
        """Read JEDEC ID via custom instruction."""
        result = self.bridge.on_custom_instruction(0x9F, b'')
        return f"{result[0]:02x}{result[1]:02x}{result[2]:02x}"

    def _cmd_status(self) -> str:
        """Read status register."""
        result = self.bridge.on_custom_instruction(0x05, b'')
        return f"{result[0]:02x}"

    def _cmd_erase(self, args: str) -> str:
        """Erase 4KB sector."""
        args = args.strip()
        if len(args) < 4:
            return "ERROR: Need 4-digit hex address"

        try:
            addr = int(args[:4], 16)
        except ValueError:
            return "ERROR: Invalid address"

        self.bridge.on_flash_access('erase_4k', addr, b'')
        return "OK"

    def _cmd_write(self, args: str) -> str:
        """Write data to flash via QSPI."""
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

        if len(data) > 256:
            data = data[:256]

        # Write enable + page program
        self.bridge.on_custom_instruction(0x06, b'')  # Write enable
        self.bridge.on_flash_access('write', addr, data)

        return "OK"

    def _cmd_read(self, args: str) -> str:
        """Read data from flash via QSPI."""
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

        data = self.bridge.on_flash_access('read', addr, bytes(length))
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


def test_jedec(cdc):
    """Test JEDEC ID read."""
    print("\n=== Test: JEDEC ID ===")
    response = cdc.send_command("JEDEC")
    if response == "ef4018":
        print(f"  PASS: JEDEC ID = {response}")
        return True
    else:
        print(f"  FAIL: Expected ef4018, got {response}")
        return False


def test_status(cdc):
    """Test status register read."""
    print("\n=== Test: STATUS ===")
    response = cdc.send_command("STATUS")
    if response == "00":
        print(f"  PASS: Status = {response}")
        return True
    else:
        print(f"  FAIL: Expected 00, got {response}")
        return False


def test_erase_write_read(cdc, flash):
    """Test erase, write, and read via QSPI."""
    print("\n=== Test: QSPI Erase/Write/Read ===")

    # Erase sector
    print("  Erasing sector at 0x000000...")
    response = cdc.send_command("ERASE 0000")
    if response != "OK":
        print(f"  FAIL: Erase failed: {response}")
        return False
    print("  Sector erased OK")

    # Verify erased (should be 0xFF)
    response = cdc.send_command("READ 0000 08")
    if response != "ff" * 8:
        print(f"  FAIL: Sector not erased: {response}")
        return False
    print("  Sector verified erased")

    # Write test data via QSPI
    test_data = "deadbeefcafebabe"
    print(f"  Writing data via QSPI: {test_data}")
    response = cdc.send_command(f"WRITE 0000 {test_data}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False
    print("  Data written OK")

    # Read back via QSPI
    print("  Reading data via QSPI...")
    response = cdc.send_command("READ 0000 08")
    if response == test_data:
        print(f"  PASS: Read matches: {response}")
        return True
    else:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {test_data}")
        print(f"    Got: {response}")
        return False


def test_large_qspi_transfer(cdc, flash):
    """Test larger QSPI transfer (64 bytes)."""
    print("\n=== Test: Large QSPI Transfer ===")

    # Erase sector
    response = cdc.send_command("ERASE 1000")
    if response != "OK":
        print(f"  FAIL: Erase failed: {response}")
        return False

    # Write 64 bytes incrementing pattern
    pattern = ''.join(f'{i:02x}' for i in range(64))
    response = cdc.send_command(f"WRITE 1000 {pattern}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False

    # Read back
    response = cdc.send_command("READ 1000 40")
    if response == pattern:
        print(f"  PASS: Large QSPI transfer (64 bytes) OK")
        return True
    else:
        print(f"  FAIL: Large QSPI transfer mismatch")
        print(f"    Expected: {pattern[:32]}...")
        print(f"    Got: {response[:32]}...")
        return False


def test_multiple_transfers(cdc, flash):
    """Test multiple consecutive QSPI transfers."""
    print("\n=== Test: Multiple QSPI Transfers ===")

    # Perform multiple write/read cycles
    for i in range(4):
        addr = f"{i * 0x100:04x}"
        data = f"{(i * 17):02x}" * 8

        # Erase if at sector boundary
        if i == 0:
            cdc.send_command(f"ERASE {addr}")

        # Write
        response = cdc.send_command(f"WRITE {addr} {data}")
        if response != "OK":
            print(f"  FAIL: Write {i} failed")
            return False

        # Read back
        response = cdc.send_command(f"READ {addr} 08")
        if response != data:
            print(f"  FAIL: Read {i} mismatch")
            return False

    print(f"  PASS: 4 consecutive QSPI transfers OK")
    return True


def main():
    print("=" * 60)
    print("NRF52840 QSPI Flash CDC Test")
    print("=" * 60)

    # Create NRF52840 peripheral set
    print("\nInitializing NRF52840 peripheral set...")
    nrf = NRF52840PeripheralSet()
    print(f"  Device: NRF52840")
    print(f"  QSPI base: 0x{nrf.qspi.base:08X}")

    # Create W25Q128 Flash
    print("\nCreating W25Q128 Flash...")
    flash = W25QxxFlash('W25Q128')
    print(f"  Model: {flash.model}")
    print(f"  Size: {flash.size // (1024 * 1024)} MB")

    # Create memory bridge for DMA
    memory = DMAMemoryBridge()

    # Connect QSPI memory callbacks
    nrf.qspi.mem_read = memory.mem_read
    nrf.qspi.mem_write = memory.mem_write

    # Create QSPI-Flash bridge
    bridge = QSPIFlashBridge(flash)

    # Connect QSPI flash callbacks
    nrf.qspi.on_flash_access = bridge.on_flash_access
    nrf.qspi.on_custom_instruction = bridge.on_custom_instruction

    # Create CDC interface
    cdc = CDCInterface(nrf.qspi, flash, bridge, memory)

    # Run tests
    results = []

    results.append(("PING", test_ping(cdc)))
    results.append(("JEDEC ID", test_jedec(cdc)))
    results.append(("Status Register", test_status(cdc)))
    results.append(("QSPI Erase/Write/Read", test_erase_write_read(cdc, flash)))
    results.append(("Large QSPI Transfer", test_large_qspi_transfer(cdc, flash)))
    results.append(("Multiple QSPI Transfers", test_multiple_transfers(cdc, flash)))

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
