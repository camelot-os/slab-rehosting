#!/usr/bin/env python3
"""
Test Record/Replay Mode for HIL Peripherals

This test validates the record/replay functionality by:
1. Creating a flash peripheral with test data
2. Recording all accesses during firmware execution
3. Replaying the same execution without the original peripheral
4. Verifying identical results

SPDX-License-Identifier: Apache-2.0 OR Apache-2.0
Copyright (C) 2025 Twisted Wires Security Lab
"""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from slab_cortex_m.replay_peripheral import (
    RecordReplayPeripheral,
    AccessRecord,
    create_recorded_flash,
    create_replay_flash,
)


class MockFlashPeripheral:
    """Mock flash peripheral with predictable data."""

    def __init__(self, name: str, base: int, size: int):
        self.name = name
        self.base = base
        self.size = size
        self.irq = -1
        # Fill with pattern: address XOR 0xDEADBEEF
        self._data = {}
        for offset in range(0, min(size, 0x1000), 4):
            addr = base + offset
            self._data[addr] = (addr ^ 0xDEADBEEF) & 0xFFFFFFFF

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    def read(self, addr: int, size: int, secure: bool = False):
        if addr in self._data:
            return (self._data[addr], 0)
        return (0xFFFFFFFF, 0)  # Unprogrammed flash

    def write(self, addr: int, size: int, value: int, secure: bool = False):
        self._data[addr] = value
        return (0, 0)


class TestAccessRecord(unittest.TestCase):
    """Test AccessRecord serialization."""

    def test_to_dict(self):
        record = AccessRecord(
            is_write=False,
            address=0x08000000,
            size=4,
            value=0xDEADBEEF,
            pc=0x08001234,
            sequence=1
        )
        d = record.to_dict()
        self.assertEqual(d['address'], 0x08000000)
        self.assertEqual(d['value'], 0xDEADBEEF)

    def test_from_dict(self):
        d = {
            'is_write': True,
            'address': 0x40020000,
            'size': 4,
            'value': 0x12345678,
            'pc': 0,
            'timestamp': 0.0,
            'sequence': 5
        }
        record = AccessRecord.from_dict(d)
        self.assertTrue(record.is_write)
        self.assertEqual(record.address, 0x40020000)

    def test_key_generation(self):
        read_record = AccessRecord(False, 0x08000000, 4, 0xDEAD, 0, 0.0, 0)
        write_record = AccessRecord(True, 0x08000000, 4, 0xBEEF, 0, 0.0, 0)

        # Keys should be different for read vs write
        self.assertNotEqual(read_record.key(), write_record.key())
        self.assertTrue(read_record.key().startswith('R:'))
        self.assertTrue(write_record.key().startswith('W:'))


class TestRecordMode(unittest.TestCase):
    """Test recording peripheral accesses."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.record_file = os.path.join(self.temp_dir, "test_trace.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_reads(self):
        """Test that reads are recorded correctly."""
        flash = MockFlashPeripheral("FLASH", 0x08000000, 0x10000)
        recorded = RecordReplayPeripheral(flash, record_file=self.record_file)

        # Perform some reads
        result1 = recorded.read(0x08000000, 4)
        result2 = recorded.read(0x08000004, 4)
        result3 = recorded.read(0x08000008, 4)

        recorded.close()

        # Verify file was created
        self.assertTrue(os.path.exists(self.record_file))

        # Verify content
        with open(self.record_file, 'r') as f:
            lines = f.readlines()

        self.assertEqual(len(lines), 3)

        # Parse first record
        record = json.loads(lines[0])
        self.assertFalse(record['is_write'])
        self.assertEqual(record['address'], 0x08000000)

    def test_record_writes(self):
        """Test that writes are recorded correctly."""
        flash = MockFlashPeripheral("FLASH", 0x08000000, 0x10000)
        recorded = RecordReplayPeripheral(flash, record_file=self.record_file)

        # Perform write
        recorded.write(0x08000100, 4, 0xCAFEBABE)

        recorded.close()

        with open(self.record_file, 'r') as f:
            record = json.loads(f.readline())

        self.assertTrue(record['is_write'])
        self.assertEqual(record['value'], 0xCAFEBABE)


class TestReplayMode(unittest.TestCase):
    """Test replaying peripheral accesses."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.record_file = os.path.join(self.temp_dir, "test_trace.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_replay_reads(self):
        """Test that replayed reads return recorded values."""
        # First, record some accesses
        flash = MockFlashPeripheral("FLASH", 0x08000000, 0x10000)
        recorded = RecordReplayPeripheral(flash, record_file=self.record_file)

        original_values = []
        for offset in range(0, 0x20, 4):
            result = recorded.read(0x08000000 + offset, 4)
            original_values.append(result[0])

        recorded.close()

        # Now replay without the original peripheral
        replay = RecordReplayPeripheral.replay_only(
            "FLASH", 0x08000000, 0x10000,
            replay_file=self.record_file
        )

        # Read same addresses - should get same values
        replay_values = []
        for offset in range(0, 0x20, 4):
            result = replay.read(0x08000000 + offset, 4)
            replay_values.append(result[0])

        self.assertEqual(original_values, replay_values)

        # Check stats
        stats = replay.get_stats()
        self.assertEqual(stats['replay_hits'], 8)
        self.assertEqual(stats['replay_misses'], 0)

    def test_replay_repeated_reads(self):
        """Test that repeated reads to same address work correctly."""
        flash = MockFlashPeripheral("FLASH", 0x08000000, 0x10000)
        recorded = RecordReplayPeripheral(flash, record_file=self.record_file)

        # Read same address multiple times (common for polling)
        for _ in range(5):
            recorded.read(0x08000000, 4)

        recorded.close()

        # Replay
        replay = RecordReplayPeripheral.replay_only(
            "FLASH", 0x08000000, 0x10000,
            replay_file=self.record_file
        )

        for _ in range(5):
            result = replay.read(0x08000000, 4)
            self.assertIsNotNone(result[0])


class TestRecordReplayIntegration(unittest.TestCase):
    """Integration tests for record/replay with realistic scenarios."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.record_file = os.path.join(self.temp_dir, "flash_trace.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_firmware_boot_sequence(self):
        """
        Simulate a firmware boot sequence that reads from flash.

        This mimics an MCU bootloader that:
        1. Reads vector table (SP, Reset handler)
        2. Reads some configuration from flash
        3. Copies code to RAM
        """
        # Create flash with realistic data
        flash = MockFlashPeripheral("FLASH", 0x08000000, 0x100000)
        # Set up vector table
        flash._data[0x08000000] = 0x20020000  # Initial SP
        flash._data[0x08000004] = 0x08000101  # Reset handler
        flash._data[0x08000008] = 0x08000201  # NMI handler
        # Configuration area
        flash._data[0x08001000] = 0x12345678  # Magic
        flash._data[0x08001004] = 0x00000100  # Code size

        # Record boot sequence
        recorded = RecordReplayPeripheral(flash, record_file=self.record_file)

        # Simulate boot
        boot_reads = []

        # Read vector table
        sp = recorded.read(0x08000000, 4)[0]
        reset = recorded.read(0x08000004, 4)[0]
        boot_reads.extend([sp, reset])

        # Read config
        magic = recorded.read(0x08001000, 4)[0]
        code_size = recorded.read(0x08001004, 4)[0]
        boot_reads.extend([magic, code_size])

        # Read code (simulated copy to RAM)
        for offset in range(0, code_size, 4):
            val = recorded.read(0x08002000 + offset, 4)[0]
            boot_reads.append(val)

        recorded.close()

        # Now replay the exact same boot sequence
        replay = RecordReplayPeripheral.replay_only(
            "FLASH", 0x08000000, 0x100000,
            replay_file=self.record_file
        )

        replay_reads = []

        # Same sequence
        sp = replay.read(0x08000000, 4)[0]
        reset = replay.read(0x08000004, 4)[0]
        replay_reads.extend([sp, reset])

        magic = replay.read(0x08001000, 4)[0]
        code_size = replay.read(0x08001004, 4)[0]
        replay_reads.extend([magic, code_size])

        for offset in range(0, code_size, 4):
            val = replay.read(0x08002000 + offset, 4)[0]
            replay_reads.append(val)

        # Verify identical behavior
        self.assertEqual(boot_reads, replay_reads)

        # Verify specific values
        self.assertEqual(sp, 0x20020000)
        self.assertEqual(reset, 0x08000101)
        self.assertEqual(magic, 0x12345678)

        print(f"\n✓ Boot sequence replay successful!")
        print(f"  Reads: {len(replay_reads)}")
        print(f"  Stats: {replay.get_stats()}")

    def test_spi_flash_read_sequence(self):
        """
        Simulate SPI flash read sequence.

        This mimics reading from external SPI flash where each
        access goes through SPI peripheral registers.
        """
        # Mock SPI peripheral that reads from "external" flash
        class MockSPIFlash:
            def __init__(self):
                self.name = "SPI_FLASH"
                self.base = 0x40013000
                self.size = 0x400
                self.irq = -1
                # Simulated external flash content
                self._flash_data = bytes([i & 0xFF for i in range(256)])
                self._read_ptr = 0
                self._dr_value = 0

            def contains(self, addr):
                return self.base <= addr < self.base + self.size

            def read(self, addr, size, secure=False):
                offset = addr - self.base
                if offset == 0x0C:  # SPI_DR
                    # Return next byte from "flash"
                    if self._read_ptr < len(self._flash_data):
                        val = self._flash_data[self._read_ptr]
                        self._read_ptr += 1
                        return (val, 0)
                    return (0xFF, 0)
                elif offset == 0x08:  # SPI_SR - status
                    return (0x03, 0)  # TXE | RXNE
                return (0, 0)

            def write(self, addr, size, value, secure=False):
                offset = addr - self.base
                if offset == 0x0C:  # SPI_DR - send command
                    if value == 0x03:  # READ command
                        self._read_ptr = 0
                return (0, 0)

        spi = MockSPIFlash()
        recorded = RecordReplayPeripheral(spi, record_file=self.record_file)

        # Simulate reading 16 bytes from SPI flash
        original_data = []

        # Send READ command
        recorded.write(0x4001300C, 4, 0x03)

        # Read 16 bytes
        for _ in range(16):
            # Check status
            status = recorded.read(0x40013008, 4)[0]
            # Read data
            data = recorded.read(0x4001300C, 4)[0]
            original_data.append(data)

        recorded.close()

        # Replay
        replay = RecordReplayPeripheral.replay_only(
            "SPI_FLASH", 0x40013000, 0x400,
            replay_file=self.record_file
        )

        replay_data = []

        # Same sequence
        replay.write(0x4001300C, 4, 0x03)

        for _ in range(16):
            status = replay.read(0x40013008, 4)[0]
            data = replay.read(0x4001300C, 4)[0]
            replay_data.append(data)

        self.assertEqual(original_data, replay_data)
        self.assertEqual(original_data, list(range(16)))

        print(f"\n✓ SPI flash replay successful!")
        print(f"  Data: {replay_data}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
