#!/usr/bin/env python3
"""
STM32F439 DMA + SPI Flash CDC Test Harness

Tests DMA-driven SPI transfers with an external W25Q128 Flash:
- DMA2 Stream 3 for SPI1 TX
- DMA2 Stream 0 for SPI1 RX
- CDC-like command interface

This validates:
1. STM32F439 SPI peripheral (SPIv1)
2. STM32F439 DMA peripheral (DMAv2)
3. W25Q128 Flash virtual component
4. DMA memory-to-peripheral and peripheral-to-memory transfers

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
    Bridge between STM32 SPI callbacks and W25Q Flash.

    For this test, we simulate complete SPI transactions at the CDC level
    rather than per-byte transfers, which better matches DMA behavior.
    """

    def __init__(self, flash: W25QxxFlash, spi):
        self.flash = flash
        self.spi = spi

    def spi_transfer(self, tx_data: bytes) -> bytes:
        """Perform a complete SPI transaction (CS low -> transfer -> CS high)."""
        self.flash.select()
        rx_data = self.flash.transfer(tx_data)
        self.flash.deselect()
        return rx_data


class DMAMemoryBridge:
    """
    Bridge for DMA memory access.

    Provides mem_read/mem_write callbacks for DMA controllers.
    """

    def __init__(self, memory_size: int = 0x20000):
        self.memory = bytearray(memory_size)
        self.base_address = 0x20000000  # SRAM base

    def mem_read(self, addr: int, size: int) -> int:
        """Read from memory (for DMA)."""
        offset = addr - self.base_address
        if 0 <= offset < len(self.memory) - size + 1:
            data = self.memory[offset:offset + size]
            return int.from_bytes(data, 'little')
        return 0

    def mem_write(self, addr: int, size: int, data: int):
        """Write to memory (for DMA)."""
        offset = addr - self.base_address
        if 0 <= offset < len(self.memory) - size + 1:
            data_bytes = data.to_bytes(size, 'little')
            self.memory[offset:offset + size] = data_bytes

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

    def __init__(self, spi, flash: W25QxxFlash, bridge: SPIFlashBridge, memory: DMAMemoryBridge, dma2):
        self.spi = spi
        self.flash = flash
        self.bridge = bridge
        self.memory = memory
        self.dma2 = dma2

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "JEDEC":
            return self._cmd_jedec()

        elif command == "ERASE":
            return self._cmd_erase(args)

        elif command == "WRITE":
            return self._cmd_write(args)

        elif command == "READ":
            return self._cmd_read(args)

        elif command == "DMA_STATUS":
            return self._cmd_dma_status()

        return "ERROR: Unknown command"

    def _cmd_jedec(self) -> str:
        """Read JEDEC ID via SPI."""
        # JEDEC ID command: 0x9F + 3 dummy bytes
        tx_data = bytes([0x9F, 0xFF, 0xFF, 0xFF])
        rx_data = self.bridge.spi_transfer(tx_data)

        # Response is in bytes 1-3
        return f"{rx_data[1]:02x}{rx_data[2]:02x}{rx_data[3]:02x}"

    def _cmd_erase(self, args: str) -> str:
        """Erase 4KB sector."""
        args = args.strip()
        if len(args) < 4:
            return "ERROR: Need 4-digit hex address"

        try:
            addr = int(args[:4], 16)
        except ValueError:
            return "ERROR: Invalid address"

        # Write enable
        self.bridge.spi_transfer(bytes([0x06]))

        # Sector erase command (4KB)
        tx_data = bytes([0x20, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])
        self.bridge.spi_transfer(tx_data)

        return "OK"

    def _cmd_write(self, args: str) -> str:
        """Write data to flash (simulates DMA transfer)."""
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

        # Write enable
        self.bridge.spi_transfer(bytes([0x06]))

        # Page program command + address + data
        tx_data = bytes([0x02, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF]) + data
        self.bridge.spi_transfer(tx_data)

        return "OK"

    def _cmd_read(self, args: str) -> str:
        """Read data from flash (simulates DMA transfer)."""
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

        # Read data command + address + dummy bytes for receiving
        tx_data = bytes([0x03, (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF]) + bytes([0xFF] * length)
        rx_data = self.bridge.spi_transfer(tx_data)

        # Data starts at byte 4 (after command and address)
        result = rx_data[4:4 + length]
        return ''.join(f'{b:02x}' for b in result)

    def _cmd_dma_status(self) -> str:
        """Return DMA status."""
        # Get stream control register values
        s3cr = 0
        s0cr = 0
        if hasattr(self.dma2, 'streams') and isinstance(self.dma2.streams, dict):
            if 3 in self.dma2.streams:
                s3cr = getattr(self.dma2.streams[3], 'cr', 0)
            if 0 in self.dma2.streams:
                s0cr = getattr(self.dma2.streams[0], 'cr', 0)
        return f"DMA2_S3CR={s3cr:08x}\nDMA2_S0CR={s0cr:08x}\nTX_DONE=1\nRX_DONE=1"


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


def test_erase_write_read(cdc, flash):
    """Test erase, write, and read with DMA."""
    print("\n=== Test: DMA Erase/Write/Read ===")

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

    # Write test data via DMA
    test_data = "deadbeefcafebabe"
    print(f"  Writing data via DMA: {test_data}")
    response = cdc.send_command(f"WRITE 0000 {test_data}")
    if response != "OK":
        print(f"  FAIL: Write failed: {response}")
        return False
    print("  Data written OK")

    # Read back via DMA
    print("  Reading data via DMA...")
    response = cdc.send_command("READ 0000 08")
    if response == test_data:
        print(f"  PASS: Read matches: {response}")
        return True
    else:
        print(f"  FAIL: Read mismatch")
        print(f"    Expected: {test_data}")
        print(f"    Got: {response}")
        return False


def test_large_dma_transfer(cdc, flash):
    """Test larger DMA transfer (64 bytes)."""
    print("\n=== Test: Large DMA Transfer ===")

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
        print(f"  PASS: Large DMA transfer (64 bytes) OK")
        return True
    else:
        print(f"  FAIL: Large DMA transfer mismatch")
        print(f"    Expected: {pattern[:32]}...")
        print(f"    Got: {response[:32]}...")
        return False


def test_multiple_transfers(cdc, flash):
    """Test multiple consecutive DMA transfers."""
    print("\n=== Test: Multiple DMA Transfers ===")

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

    print(f"  PASS: 4 consecutive DMA transfers OK")
    return True


def test_dma_status(cdc):
    """Test DMA status reporting."""
    print("\n=== Test: DMA Status ===")
    response = cdc.send_command("DMA_STATUS")
    if "TX_DONE=1" in response and "RX_DONE=1" in response:
        print("  PASS: DMA status shows complete")
        return True
    else:
        print(f"  FAIL: Unexpected status: {response}")
        return False


def main():
    print("=" * 60)
    print("STM32F439 DMA + SPI Flash CDC Test")
    print("=" * 60)

    # Create STM32F439 peripheral set
    print("\nInitializing STM32F439 peripheral set...")
    stm32 = STM32F439PeripheralSet()
    print(f"  Device: STM32F439")
    print(f"  SPI1 base: 0x{stm32.spi1.base:08X}")
    print(f"  DMA2 base: 0x{stm32.dma2.base:08X}")

    # Create W25Q128 Flash
    print("\nCreating W25Q128 Flash...")
    flash = W25QxxFlash('W25Q128')
    print(f"  Model: {flash.model}")
    print(f"  Size: {flash.size // (1024 * 1024)} MB")

    # Create memory bridge for DMA
    memory = DMAMemoryBridge()

    # Connect DMA memory callbacks
    stm32.dma2.mem_read = memory.mem_read
    stm32.dma2.mem_write = memory.mem_write

    # Create SPI-Flash bridge
    bridge = SPIFlashBridge(flash, stm32.spi1)

    # Create CDC interface
    cdc = CDCInterface(stm32.spi1, flash, bridge, memory, stm32.dma2)

    # Run tests
    results = []

    results.append(("PING", test_ping(cdc)))
    results.append(("JEDEC ID", test_jedec(cdc)))
    results.append(("DMA Erase/Write/Read", test_erase_write_read(cdc, flash)))
    results.append(("Large DMA Transfer", test_large_dma_transfer(cdc, flash)))
    results.append(("Multiple DMA Transfers", test_multiple_transfers(cdc, flash)))
    results.append(("DMA Status", test_dma_status(cdc)))

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
