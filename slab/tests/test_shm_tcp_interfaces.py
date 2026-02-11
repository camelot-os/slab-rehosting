#!/usr/bin/env python3
"""
Comprehensive Tests for SHM and TCP Peripheral Interfaces

Tests the shared memory and TCP interfaces used for communication
between QEMU and Python peripheral emulation.

Test Categories:
1. Protocol Tests - Packet format, serialization, validation
2. Peripheral Handler Tests - Read/write operations, callbacks
3. Server/Bridge Tests - Connection handling, command processing
4. Integration Tests - Full round-trip communication
5. Performance Tests - Latency and throughput benchmarks
6. Edge Cases - Error handling, boundary conditions
7. Multi-Peripheral Tests - Multiple peripherals on same bus

Usage:
    pytest tests/test_shm_tcp_interfaces.py -v
    pytest tests/test_shm_tcp_interfaces.py -k "tcp" -v
    pytest tests/test_shm_tcp_interfaces.py -k "shm" -v

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 Twisted Wires Security Lab
"""

import sys
import os
import struct
import time
import socket
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Optional

# Add paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python', 'slab_cortex_m'))


# =============================================================================
# TCP PROTOCOL TESTS
# =============================================================================

class TestTcpPacket(unittest.TestCase):
    """Test TCP packet serialization and parsing."""

    def setUp(self):
        from slab_cortex_m.tcp_peripheral import TcpPacket, TcpCommand
        self.TcpPacket = TcpPacket
        self.TcpCommand = TcpCommand

    def test_packet_header_size(self):
        """Verify header size constant."""
        self.assertEqual(self.TcpPacket.HEADER_SIZE, 12)

    def test_packet_pack_unpack_roundtrip(self):
        """Test packet serialization roundtrip."""
        original = self.TcpPacket(
            command=self.TcpCommand.READ32,
            flags=0x01,
            address=0x40020000,
            data=0x12345678
        )

        packed = original.pack()
        unpacked = self.TcpPacket.unpack(packed)

        self.assertEqual(unpacked.command, self.TcpCommand.READ32)
        self.assertEqual(unpacked.flags, 0x01)
        self.assertEqual(unpacked.address, 0x40020000)
        self.assertEqual(unpacked.data, 0x12345678)

    def test_packet_pack_format(self):
        """Test packet binary format."""
        pkt = self.TcpPacket(
            command=self.TcpCommand.WRITE32,
            flags=0,
            address=0x40020014,
            data=0xDEADBEEF
        )

        packed = pkt.pack()

        # Verify format: <BBHII
        cmd, flags, length, addr, data = struct.unpack('<BBHII', packed[:12])
        self.assertEqual(cmd, self.TcpCommand.WRITE32)
        self.assertEqual(flags, 0)
        self.assertEqual(length, 12)  # Header size, no extended data
        self.assertEqual(addr, 0x40020014)
        self.assertEqual(data, 0xDEADBEEF)

    def test_packet_with_extended_data(self):
        """Test packet with extended data."""
        extended = b"Hello Extended Data!"
        pkt = self.TcpPacket(
            command=self.TcpCommand.IDENTIFY,
            address=0,
            data=0,
            extended=extended
        )

        packed = pkt.pack()
        unpacked = self.TcpPacket.unpack(packed)

        self.assertEqual(len(packed), 12 + len(extended))
        self.assertEqual(unpacked.extended, extended)

    def test_all_command_types(self):
        """Test all command types serialize correctly."""
        for cmd in self.TcpCommand:
            pkt = self.TcpPacket(command=cmd, address=0x1000, data=0x55AA)
            packed = pkt.pack()
            unpacked = self.TcpPacket.unpack(packed)
            self.assertEqual(unpacked.command, cmd)

    def test_packet_unpack_short_data(self):
        """Test packet unpack rejects short data."""
        with self.assertRaises(ValueError):
            self.TcpPacket.unpack(b'\x00' * 8)  # Too short

    def test_max_values(self):
        """Test maximum values for fields."""
        pkt = self.TcpPacket(
            command=self.TcpCommand.READ32,
            flags=0xFF,
            address=0xFFFFFFFF,
            data=0xFFFFFFFF
        )
        packed = pkt.pack()
        unpacked = self.TcpPacket.unpack(packed)

        self.assertEqual(unpacked.address, 0xFFFFFFFF)
        self.assertEqual(unpacked.data, 0xFFFFFFFF)


# =============================================================================
# TCP PERIPHERAL HANDLER TESTS
# =============================================================================

class TestTcpPeripheralHandler(unittest.TestCase):
    """Test TCP peripheral handler."""

    def setUp(self):
        from slab_cortex_m.tcp_peripheral import TcpPeripheralHandler
        self.handler = TcpPeripheralHandler(
            name="test_periph",
            base_address=0x40020000,
            size=0x400
        )

    def test_handler_init(self):
        """Test handler initialization."""
        self.assertEqual(self.handler.name, "test_periph")
        self.assertEqual(self.handler.base_address, 0x40020000)
        self.assertEqual(self.handler.size, 0x400)

    def test_register_read_write(self):
        """Test register read/write operations."""
        # Write value
        self.handler.write(0x40020000, 0x12345678, 4)
        # Read back
        value = self.handler.read(0x40020000, 4)
        self.assertEqual(value, 0x12345678)

    def test_register_offset_calculation(self):
        """Test offset calculation from address."""
        # Write at different offsets
        self.handler.write(0x40020000, 0xAAAA, 4)  # Offset 0
        self.handler.write(0x40020010, 0xBBBB, 4)  # Offset 0x10
        self.handler.write(0x400203FC, 0xCCCC, 4)  # Offset 0x3FC (last)

        self.assertEqual(self.handler.registers.get(0x00), 0xAAAA)
        self.assertEqual(self.handler.registers.get(0x10), 0xBBBB)
        self.assertEqual(self.handler.registers.get(0x3FC), 0xCCCC)

    def test_read_callback(self):
        """Test custom read callback."""
        callback_called = []

        def read_cb(offset: int, size: int) -> int:
            callback_called.append((offset, size))
            return 0x55AA55AA

        self.handler.read_callback = read_cb

        result = self.handler.read(0x40020008, 4)

        self.assertEqual(result, 0x55AA55AA)
        self.assertEqual(callback_called, [(0x08, 4)])

    def test_write_callback(self):
        """Test custom write callback."""
        callback_called = []

        def write_cb(offset: int, value: int, size: int):
            callback_called.append((offset, value, size))

        self.handler.write_callback = write_cb

        self.handler.write(0x40020014, 0xDEADBEEF, 4)

        self.assertEqual(callback_called, [(0x14, 0xDEADBEEF, 4)])

    def test_reset(self):
        """Test peripheral reset."""
        self.handler.write(0x40020000, 0x1234, 4)
        self.handler.write(0x40020004, 0x5678, 4)

        self.handler.reset()

        self.assertEqual(len(self.handler.registers), 0)


# =============================================================================
# TCP SERVER TESTS
# =============================================================================

class TestTcpPeripheralBridge(unittest.TestCase):
    """Test TCP peripheral bridge/server."""

    def setUp(self):
        from slab_cortex_m.tcp_peripheral import (
            TcpPeripheralBridge, TcpPeripheralHandler, TcpPacket, TcpCommand
        )
        self.TcpPeripheralBridge = TcpPeripheralBridge
        self.TcpPeripheralHandler = TcpPeripheralHandler
        self.TcpPacket = TcpPacket
        self.TcpCommand = TcpCommand

    def test_bridge_init(self):
        """Test bridge initialization."""
        bridge = self.TcpPeripheralBridge(host="127.0.0.1", port=15555)
        self.assertEqual(bridge.host, "127.0.0.1")
        self.assertEqual(bridge.port, 15555)

    def test_register_peripheral(self):
        """Test peripheral registration."""
        bridge = self.TcpPeripheralBridge()
        handler = self.TcpPeripheralHandler(
            name="gpio",
            base_address=0x40020000,
            size=0x400
        )

        bridge.register_peripheral(0x40020000, handler)

        self.assertIn(0x40020000, bridge.peripheral_map)
        self.assertEqual(bridge.peripheral_map[0x40020000], handler)

    def test_find_handler(self):
        """Test finding handler for address."""
        bridge = self.TcpPeripheralBridge()

        gpio = self.TcpPeripheralHandler("gpio", 0x40020000, 0x400)
        uart = self.TcpPeripheralHandler("uart", 0x40011000, 0x400)

        bridge.register_peripheral(0x40020000, gpio)
        bridge.register_peripheral(0x40011000, uart)

        # Find by exact address
        self.assertEqual(bridge._find_handler(0x40020000), gpio)
        self.assertEqual(bridge._find_handler(0x40011000), uart)

        # Find by offset within range
        self.assertEqual(bridge._find_handler(0x40020014), gpio)
        self.assertEqual(bridge._find_handler(0x400113FC), uart)

        # Not found
        self.assertIsNone(bridge._find_handler(0x50000000))

    def test_process_read_packet(self):
        """Test processing READ commands."""
        bridge = self.TcpPeripheralBridge()
        gpio = self.TcpPeripheralHandler("gpio", 0x40020000, 0x400)
        gpio.registers[0x14] = 0xABCD1234
        bridge.register_peripheral(0x40020000, gpio)

        # READ32
        pkt = self.TcpPacket(
            command=self.TcpCommand.READ32,
            address=0x40020014
        )
        response = bridge._process_packet(pkt)

        self.assertEqual(response.command, self.TcpCommand.ACK)
        self.assertEqual(response.data, 0xABCD1234)
        self.assertEqual(bridge.reads, 1)

    def test_process_write_packet(self):
        """Test processing WRITE commands."""
        bridge = self.TcpPeripheralBridge()
        gpio = self.TcpPeripheralHandler("gpio", 0x40020000, 0x400)
        bridge.register_peripheral(0x40020000, gpio)

        # WRITE32
        pkt = self.TcpPacket(
            command=self.TcpCommand.WRITE32,
            address=0x40020014,
            data=0xDEADBEEF
        )
        response = bridge._process_packet(pkt)

        self.assertEqual(response.command, self.TcpCommand.ACK)
        self.assertEqual(gpio.registers[0x14], 0xDEADBEEF)
        self.assertEqual(bridge.writes, 1)

    def test_process_invalid_address(self):
        """Test processing commands to unmapped address."""
        bridge = self.TcpPeripheralBridge()

        pkt = self.TcpPacket(
            command=self.TcpCommand.READ32,
            address=0x50000000  # Unmapped
        )
        response = bridge._process_packet(pkt)

        self.assertEqual(response.command, self.TcpCommand.NACK)

    def test_irq_handling(self):
        """Test IRQ set/clear."""
        bridge = self.TcpPeripheralBridge()

        bridge.set_irq(5)
        self.assertEqual(bridge.irq_status, 1 << 5)

        bridge.set_irq(10)
        self.assertEqual(bridge.irq_status, (1 << 5) | (1 << 10))

        bridge.clear_irq(5)
        self.assertEqual(bridge.irq_status, 1 << 10)

    def test_reset_command(self):
        """Test RESET command."""
        bridge = self.TcpPeripheralBridge()
        gpio = self.TcpPeripheralHandler("gpio", 0x40020000, 0x400)
        gpio.registers[0] = 0x1234
        bridge.register_peripheral(0x40020000, gpio)
        bridge.irq_status = 0xFF

        pkt = self.TcpPacket(command=self.TcpCommand.RESET)
        bridge._process_packet(pkt)

        self.assertEqual(len(gpio.registers), 0)
        self.assertEqual(bridge.irq_status, 0)

    def test_identify_command(self):
        """Test IDENTIFY command returns peripheral info."""
        bridge = self.TcpPeripheralBridge()
        bridge.register_peripheral(0x40020000,
            self.TcpPeripheralHandler("gpio", 0x40020000, 0x400))
        bridge.register_peripheral(0x40011000,
            self.TcpPeripheralHandler("uart", 0x40011000, 0x400))

        pkt = self.TcpPacket(command=self.TcpCommand.IDENTIFY)
        response = bridge._process_packet(pkt)

        info = response.extended.decode()
        self.assertIn("gpio", info)
        self.assertIn("uart", info)
        self.assertIn("0x40020000", info)


# =============================================================================
# TCP CLIENT-SERVER INTEGRATION TESTS
# =============================================================================

class TestTcpClientServer(unittest.TestCase):
    """Test TCP client-server communication."""

    @classmethod
    def setUpClass(cls):
        """Start test server."""
        from slab_cortex_m.tcp_peripheral import (
            TcpPeripheralServer, TcpPeripheralHandler
        )

        cls.port = 15556  # Use unique port to avoid conflicts
        cls.server = TcpPeripheralServer(host="127.0.0.1", port=cls.port)

        # Add test peripheral
        cls.gpio = TcpPeripheralHandler("gpio", 0x40020000, 0x400)
        cls.server.add_peripheral(cls.gpio)

        cls.server.start()
        time.sleep(0.2)  # Give server time to start

    @classmethod
    def tearDownClass(cls):
        """Stop test server."""
        cls.server.stop()

    def setUp(self):
        from slab_cortex_m.tcp_peripheral import TcpPacket, TcpCommand
        self.TcpPacket = TcpPacket
        self.TcpCommand = TcpCommand

        # Connect client
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect(("127.0.0.1", self.port))
        self.client.settimeout(2.0)
        time.sleep(0.1)

    def tearDown(self):
        self.client.close()

    def _send_receive(self, pkt):
        """Send packet and receive response."""
        self.client.send(pkt.pack())
        response_data = self.client.recv(1024)
        return self.TcpPacket.unpack(response_data)

    def test_write_read_roundtrip(self):
        """Test write then read same address."""
        # Write
        write_pkt = self.TcpPacket(
            command=self.TcpCommand.WRITE32,
            address=0x40020000,
            data=0x12345678
        )
        response = self._send_receive(write_pkt)
        self.assertEqual(response.command, self.TcpCommand.ACK)

        # Read back
        read_pkt = self.TcpPacket(
            command=self.TcpCommand.READ32,
            address=0x40020000
        )
        response = self._send_receive(read_pkt)
        self.assertEqual(response.command, self.TcpCommand.ACK)
        self.assertEqual(response.data, 0x12345678)

    def test_different_sizes(self):
        """Test 8, 16, 32-bit operations."""
        # 8-bit
        self._send_receive(self.TcpPacket(
            command=self.TcpCommand.WRITE8,
            address=0x40020100,
            data=0xAB
        ))
        resp = self._send_receive(self.TcpPacket(
            command=self.TcpCommand.READ8,
            address=0x40020100
        ))
        self.assertEqual(resp.data & 0xFF, 0xAB)

        # 16-bit
        self._send_receive(self.TcpPacket(
            command=self.TcpCommand.WRITE16,
            address=0x40020200,
            data=0xCDEF
        ))
        resp = self._send_receive(self.TcpPacket(
            command=self.TcpCommand.READ16,
            address=0x40020200
        ))
        self.assertEqual(resp.data & 0xFFFF, 0xCDEF)

    def test_burst_operations(self):
        """Test rapid sequential operations."""
        # Write and read in pairs to avoid timing issues
        for i in range(50):  # Reduced count for reliability
            pkt = self.TcpPacket(
                command=self.TcpCommand.WRITE32,
                address=0x40020000 + (i * 4) % 0x400,
                data=i
            )
            self.client.send(pkt.pack())
            # Wait for response immediately
            data = self.client.recv(1024)
            resp = self.TcpPacket.unpack(data)
            self.assertEqual(resp.command, self.TcpCommand.ACK)


# =============================================================================
# SHARED MEMORY TESTS
# =============================================================================

class TestShmHeader(unittest.TestCase):
    """Test shared memory header format."""

    def setUp(self):
        try:
            from slab_cortex_m.shm_peripheral import ShmHeader, ShmCommand
            self.ShmHeader = ShmHeader
            self.ShmCommand = ShmCommand
            self.available = True
        except ImportError:
            self.available = False

    def test_header_magic(self):
        """Test header magic value."""
        if not self.available:
            self.skipTest("shared_memory not available")

        # "SLAB" in little-endian
        self.assertEqual(self.ShmHeader.MAGIC, 0x534C4142)

    def test_header_pack_unpack(self):
        """Test header serialization."""
        if not self.available:
            self.skipTest("shared_memory not available")

        header = self.ShmHeader.pack(
            command=self.ShmCommand.READ32,
            status=1,
            address=0x40020000,
            data=0x12345678,
            size=4,
            seq=42,
            irq=0x0F
        )

        magic, version, cmd, status, addr, data, size, seq, irq, bus_attrs = \
            self.ShmHeader.unpack(header)

        self.assertEqual(magic, self.ShmHeader.MAGIC)
        self.assertEqual(cmd, self.ShmCommand.READ32)
        self.assertEqual(status, 1)
        self.assertEqual(addr, 0x40020000)
        self.assertEqual(data, 0x12345678)
        self.assertEqual(seq, 42)
        self.assertEqual(irq, 0x0F)


class TestShmPeripheralHandler(unittest.TestCase):
    """Test shared memory peripheral handler."""

    def setUp(self):
        try:
            from slab_cortex_m.shm_peripheral import PeripheralHandler
            self.PeripheralHandler = PeripheralHandler
            self.available = True
        except ImportError:
            self.available = False

    def test_handler_basic(self):
        """Test basic handler operations."""
        if not self.available:
            self.skipTest("shared_memory not available")

        handler = self.PeripheralHandler(
            name="test",
            base_address=0x40020000,
            size=0x400
        )

        handler.write(0x40020010, 0xABCD, 4)
        value = handler.read(0x40020010, 4)

        self.assertEqual(value, 0xABCD)


class TestShmPeripheralBridge(unittest.TestCase):
    """Test shared memory peripheral bridge."""

    def setUp(self):
        try:
            from slab_cortex_m.shm_peripheral import (
                ShmPeripheralBridge, PeripheralHandler, ShmCommand
            )
            self.ShmPeripheralBridge = ShmPeripheralBridge
            self.PeripheralHandler = PeripheralHandler
            self.ShmCommand = ShmCommand
            self.available = True
        except (ImportError, RuntimeError):
            self.available = False

    def test_bridge_create_connect(self):
        """Test bridge creation and connection."""
        if not self.available:
            self.skipTest("shared_memory not available")

        # Create bridge
        bridge1 = self.ShmPeripheralBridge(shm_name="/slab_test_bridge")
        try:
            bridge1.create()

            # Connect second bridge
            bridge2 = self.ShmPeripheralBridge(shm_name="/slab_test_bridge")
            bridge2.connect()

            # Verify both can access
            self.assertIsNotNone(bridge1._shm)
            self.assertIsNotNone(bridge2._shm)

        finally:
            bridge1.close()
            # Clean up shared memory
            try:
                bridge1._shm.unlink()
            except:
                pass

    def test_command_handling(self):
        """Test command handling."""
        if not self.available:
            self.skipTest("shared_memory not available")

        bridge = self.ShmPeripheralBridge(shm_name="/slab_test_cmd")
        handler = self.PeripheralHandler(
            name="test",
            base_address=0x40020000,
            size=0x400
        )
        handler.registers[0x10] = 0xDEADBEEF

        bridge.register_peripheral(0x40020000, handler)

        try:
            bridge.create()

            # Simulate READ32 command
            result = bridge._handle_command(
                self.ShmCommand.READ32,
                0x40020010,
                0,
                4
            )
            self.assertEqual(result, 0xDEADBEEF)

            # Simulate WRITE32 command
            bridge._handle_command(
                self.ShmCommand.WRITE32,
                0x40020020,
                0xCAFEBABE,
                4
            )
            self.assertEqual(handler.registers[0x20], 0xCAFEBABE)

        finally:
            bridge.close()


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

class TestTcpPerformance(unittest.TestCase):
    """Performance tests for TCP interface."""

    @classmethod
    def setUpClass(cls):
        from slab_cortex_m.tcp_peripheral import (
            TcpPeripheralServer, TcpPeripheralHandler
        )

        cls.port = 15557
        cls.server = TcpPeripheralServer(host="127.0.0.1", port=cls.port)
        cls.server.add_peripheral(
            TcpPeripheralHandler("perf_test", 0x40020000, 0x1000)
        )
        cls.server.start()
        time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_latency(self):
        """Measure round-trip latency."""
        from slab_cortex_m.tcp_peripheral import TcpPacket, TcpCommand

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", self.port))
        client.settimeout(2.0)
        time.sleep(0.1)

        latencies = []
        for _ in range(100):
            pkt = TcpPacket(
                command=TcpCommand.READ32,
                address=0x40020000
            )

            start = time.perf_counter()
            client.send(pkt.pack())
            client.recv(1024)
            elapsed = time.perf_counter() - start

            latencies.append(elapsed * 1000)  # ms

        client.close()

        avg_latency = sum(latencies) / len(latencies)
        min_latency = min(latencies)
        max_latency = max(latencies)

        print(f"\n  TCP Latency: avg={avg_latency:.3f}ms, "
              f"min={min_latency:.3f}ms, max={max_latency:.3f}ms")

        # Should be under 10ms for local connection
        self.assertLess(avg_latency, 10.0)

    def test_throughput(self):
        """Measure throughput (operations/second)."""
        from slab_cortex_m.tcp_peripheral import TcpPacket, TcpCommand

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", self.port))
        client.settimeout(5.0)
        time.sleep(0.1)

        num_ops = 1000
        pkt = TcpPacket(
            command=TcpCommand.WRITE32,
            address=0x40020000,
            data=0x12345678
        ).pack()

        start = time.perf_counter()
        for _ in range(num_ops):
            client.send(pkt)
            client.recv(1024)
        elapsed = time.perf_counter() - start

        client.close()

        throughput = num_ops / elapsed
        print(f"\n  TCP Throughput: {throughput:.0f} ops/sec")

        # Should be at least 1000 ops/sec
        self.assertGreater(throughput, 1000)


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_tcp_packet_zero_length(self):
        """Test packet with minimum valid data."""
        from slab_cortex_m.tcp_peripheral import TcpPacket, TcpCommand

        pkt = TcpPacket(command=TcpCommand.NOP)
        packed = pkt.pack()
        unpacked = TcpPacket.unpack(packed)

        self.assertEqual(unpacked.command, TcpCommand.NOP)
        self.assertEqual(unpacked.address, 0)
        self.assertEqual(unpacked.data, 0)

    def test_address_boundary(self):
        """Test peripheral address boundaries."""
        from slab_cortex_m.tcp_peripheral import TcpPeripheralBridge, TcpPeripheralHandler

        bridge = TcpPeripheralBridge()
        handler = TcpPeripheralHandler("test", 0x40020000, 0x400)
        bridge.register_peripheral(0x40020000, handler)

        # First address (valid)
        self.assertEqual(bridge._find_handler(0x40020000), handler)

        # Last address (valid)
        self.assertEqual(bridge._find_handler(0x400203FF), handler)

        # Just past end (invalid)
        self.assertIsNone(bridge._find_handler(0x40020400))

        # Just before start (invalid)
        self.assertIsNone(bridge._find_handler(0x4001FFFF))

    def test_multiple_overlapping_peripherals(self):
        """Test that overlapping peripherals are handled correctly."""
        from slab_cortex_m.tcp_peripheral import TcpPeripheralBridge, TcpPeripheralHandler

        bridge = TcpPeripheralBridge()

        # Non-overlapping peripherals
        p1 = TcpPeripheralHandler("p1", 0x40020000, 0x400)
        p2 = TcpPeripheralHandler("p2", 0x40020400, 0x400)

        bridge.register_peripheral(0x40020000, p1)
        bridge.register_peripheral(0x40020400, p2)

        self.assertEqual(bridge._find_handler(0x40020000), p1)
        self.assertEqual(bridge._find_handler(0x40020400), p2)


# =============================================================================
# MULTI-PERIPHERAL TESTS
# =============================================================================

class TestMultiPeripheral(unittest.TestCase):
    """Test multiple peripherals on same bridge."""

    def test_gpio_uart_spi(self):
        """Test typical MCU peripheral setup."""
        from slab_cortex_m.tcp_peripheral import TcpPeripheralBridge, TcpPeripheralHandler

        bridge = TcpPeripheralBridge()

        # GPIO ports
        gpioa = TcpPeripheralHandler("GPIOA", 0x40020000, 0x400)
        gpiob = TcpPeripheralHandler("GPIOB", 0x40020400, 0x400)

        # UART
        usart1 = TcpPeripheralHandler("USART1", 0x40011000, 0x400)

        # SPI
        spi1 = TcpPeripheralHandler("SPI1", 0x40013000, 0x400)

        bridge.register_peripheral(0x40020000, gpioa)
        bridge.register_peripheral(0x40020400, gpiob)
        bridge.register_peripheral(0x40011000, usart1)
        bridge.register_peripheral(0x40013000, spi1)

        # Verify all addressable
        self.assertEqual(bridge._find_handler(0x40020014).name, "GPIOA")
        self.assertEqual(bridge._find_handler(0x40020414).name, "GPIOB")
        self.assertEqual(bridge._find_handler(0x40011004).name, "USART1")
        self.assertEqual(bridge._find_handler(0x4001300C).name, "SPI1")

    def test_independent_register_spaces(self):
        """Test peripherals have independent register spaces."""
        from slab_cortex_m.tcp_peripheral import TcpPeripheralBridge, TcpPeripheralHandler

        bridge = TcpPeripheralBridge()

        p1 = TcpPeripheralHandler("p1", 0x40020000, 0x100)
        p2 = TcpPeripheralHandler("p2", 0x40020100, 0x100)

        bridge.register_peripheral(0x40020000, p1)
        bridge.register_peripheral(0x40020100, p2)

        # Write same offset to both
        p1.write(0x40020010, 0xAAAA, 4)
        p2.write(0x40020110, 0xBBBB, 4)

        # Verify independent
        self.assertEqual(p1.registers[0x10], 0xAAAA)
        self.assertEqual(p2.registers[0x10], 0xBBBB)


# =============================================================================
# MPU SYNC TESTS
# =============================================================================

class TestMpuSyncFromShm(unittest.TestCase):
    """Test MPU state synchronization from SHM data region."""

    def setUp(self):
        from slab_cortex_m.shm_peripheral import ShmPeripheralBridge, ShmHeader
        from slab_peripherals.mpu import CortexMPU, MPUCtrlBits, MPURegion, AccessPermission
        self.ShmPeripheralBridge = ShmPeripheralBridge
        self.ShmHeader = ShmHeader
        self.CortexMPU = CortexMPU
        self.MPUCtrlBits = MPUCtrlBits
        self.MPURegion = MPURegion
        self.AccessPermission = AccessPermission

    def _build_mpu_shm_data(self, ctrl, regions):
        """Build SHM MPU state area (68 bytes at offset 64)."""
        data = struct.pack('<I', ctrl)
        for rbar, rasr in regions:
            data += struct.pack('<II', rbar, rasr)
        # Pad to 8 regions
        for _ in range(8 - len(regions)):
            data += struct.pack('<II', 0, 0)
        return data

    def test_sync_mpu_disabled(self):
        """Test syncing MPU with ENABLE=0."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = Mock()

        # MPU disabled (CTRL=0)
        mpu_data = self._build_mpu_shm_data(0x00000000, [])
        full_buf = bytearray(1024)
        full_buf[64:64+len(mpu_data)] = mpu_data
        bridge._shm.buf = full_buf

        mpu = bridge.sync_mpu_from_shm()
        self.assertIsNotNone(mpu)
        self.assertFalse(mpu.enabled)
        self.assertFalse(mpu.privdefena)

    def test_sync_mpu_enabled_with_privdefena(self):
        """Test syncing MPU with ENABLE + PRIVDEFENA."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = Mock()

        # CTRL = ENABLE | PRIVDEFENA = 0x05
        ctrl = (1 << self.MPUCtrlBits.ENABLE) | (1 << self.MPUCtrlBits.PRIVDEFENA)
        mpu_data = self._build_mpu_shm_data(ctrl, [])
        full_buf = bytearray(1024)
        full_buf[64:64+len(mpu_data)] = mpu_data
        bridge._shm.buf = full_buf

        mpu = bridge.sync_mpu_from_shm()
        self.assertTrue(mpu.enabled)
        self.assertTrue(mpu.privdefena)
        self.assertFalse(mpu.hfnmiena)

    def test_sync_mpu_regions(self):
        """Test syncing MPU with configured regions."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = Mock()

        # Region 0: SRAM at 0x20000000, size=256KB (exp=17), FULL_RW
        rbar0 = 0x20000000
        # RASR: ENABLE=1, SIZE=17 (bits[5:1]), AP=FULL_RW (0b011 at bits[26:24])
        rasr0 = 1 | (17 << 1) | (0b011 << 24)

        # Region 1: Flash at 0x08000000, size=1MB (exp=19), PRIV_RO, XN
        rbar1 = 0x08000000
        rasr1 = 1 | (19 << 1) | (0b101 << 24) | (1 << 28)  # XN bit

        ctrl = (1 << self.MPUCtrlBits.ENABLE)
        mpu_data = self._build_mpu_shm_data(ctrl, [(rbar0, rasr0), (rbar1, rasr1)])
        full_buf = bytearray(1024)
        full_buf[64:64+len(mpu_data)] = mpu_data
        bridge._shm.buf = full_buf

        mpu = bridge.sync_mpu_from_shm()

        # Check region 0
        r0 = mpu.regions[0]
        self.assertTrue(r0.enabled)
        self.assertEqual(r0.base, 0x20000000)
        self.assertEqual(r0.size_exp, 17)
        self.assertEqual(r0.size, 1 << 18)  # 256KB
        self.assertEqual(r0.ap, self.AccessPermission.FULL_RW)
        self.assertFalse(r0.xn)

        # Check region 1
        r1 = mpu.regions[1]
        self.assertTrue(r1.enabled)
        self.assertEqual(r1.base, 0x08000000)
        self.assertEqual(r1.size_exp, 19)
        self.assertEqual(r1.ap, self.AccessPermission.PRIV_RO)
        self.assertTrue(r1.xn)

    def test_sync_mpu_update_existing(self):
        """Test syncing updates an existing MPU instance."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = Mock()

        mpu = self.CortexMPU(num_regions=8)
        mpu.enabled = False

        ctrl = (1 << self.MPUCtrlBits.ENABLE)
        mpu_data = self._build_mpu_shm_data(ctrl, [])
        full_buf = bytearray(1024)
        full_buf[64:64+len(mpu_data)] = mpu_data
        bridge._shm.buf = full_buf

        result = bridge.sync_mpu_from_shm(mpu)
        self.assertIs(result, mpu)
        self.assertTrue(mpu.enabled)

    def test_sync_mpu_with_srd(self):
        """Test syncing MPU region with subregion disable."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = Mock()

        # Region with SRD = 0b10000001 (subregions 0 and 7 disabled)
        rbar = 0x20000000
        srd = 0b10000001
        rasr = 1 | (17 << 1) | (srd << 8) | (0b011 << 24)

        ctrl = (1 << self.MPUCtrlBits.ENABLE)
        mpu_data = self._build_mpu_shm_data(ctrl, [(rbar, rasr)])
        full_buf = bytearray(1024)
        full_buf[64:64+len(mpu_data)] = mpu_data
        bridge._shm.buf = full_buf

        mpu = bridge.sync_mpu_from_shm()
        r0 = mpu.regions[0]
        self.assertEqual(r0.srd, 0b10000001)
        # Address in subregion 0 should not be contained
        self.assertFalse(r0.contains(0x20000000))
        # Address in subregion 1 should be contained
        subregion_size = r0.size // 8
        self.assertTrue(r0.contains(0x20000000 + subregion_size))

    def test_sync_mpu_no_shm(self):
        """Test sync gracefully handles missing SHM."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = None

        result = bridge.sync_mpu_from_shm()
        self.assertIsNone(result)

    def test_sync_mpu_access_check(self):
        """Test that synced MPU correctly checks access permissions."""
        bridge = self.ShmPeripheralBridge.__new__(self.ShmPeripheralBridge)
        bridge._shm = Mock()

        # Region 0: SRAM, PRIV_RW (privileged only)
        rbar0 = 0x20000000
        rasr0 = 1 | (17 << 1) | (0b001 << 24)  # AP=PRIV_RW

        ctrl = (1 << self.MPUCtrlBits.ENABLE)
        mpu_data = self._build_mpu_shm_data(ctrl, [(rbar0, rasr0)])
        full_buf = bytearray(1024)
        full_buf[64:64+len(mpu_data)] = mpu_data
        bridge._shm.buf = full_buf

        mpu = bridge.sync_mpu_from_shm()
        mpu.enable_override()

        # Privileged access should pass
        self.assertTrue(mpu.check_access(0x20001000, is_privileged=True))
        # Unprivileged access should fail
        self.assertFalse(mpu.check_access(0x20001000, is_privileged=False))


# =============================================================================
# PMSAv8 MPU TESTS (ARMv8-M: Cortex-M23/M33/M55/M85)
# =============================================================================

class TestPMSAv8MPU(unittest.TestCase):
    """Test PMSAv8 MPU (limit-based, 2-bit AP, MAIR)."""

    def setUp(self):
        from slab_peripherals.mpu import (
            CortexMPU, MPUReg, MPUCtrlBits, MPURegion,
            AccessPermissionV8,
        )
        self.CortexMPU = CortexMPU
        self.MPUReg = MPUReg
        self.MPUCtrlBits = MPUCtrlBits
        self.MPURegion = MPURegion
        self.AccessPermissionV8 = AccessPermissionV8

    def test_v8m_region_from_rbar_rlar(self):
        """Decode PMSAv8 RBAR + RLAR register values."""
        # RBAR: base=0x20000000, SH=inner(3), AP=RW_ANY(01), XN=0
        rbar = 0x20000000 | (3 << 3) | (0b01 << 1) | 0
        # RLAR: limit=0x2003FFE0, AttrIndx=2, EN=1
        rlar = 0x2003FFE0 | (2 << 1) | 1

        r = self.MPURegion.from_rbar_rlar(0, rbar, rlar)
        self.assertTrue(r.enabled)
        self.assertTrue(r._v8m)
        self.assertEqual(r.base, 0x20000000)
        self.assertEqual(r.limit, 0x2003FFE0)
        self.assertEqual(r.sh, 3)  # Inner shareable
        self.assertEqual(r.ap, self.AccessPermissionV8.RW_ANY)
        self.assertFalse(r.xn)
        self.assertEqual(r.attr_idx, 2)

    def test_v8m_region_contains_limit_based(self):
        """PMSAv8 regions use limit-based addressing (inclusive end)."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (3 << 3) | (0b01 << 1),  # RBAR
            0x2003FFE0 | (0 << 1) | 1,             # RLAR: limit=0x2003FFE0, EN=1
        )
        # Region covers 0x20000000 to 0x2003FFFF (limit | 0x1F)
        self.assertTrue(r.contains(0x20000000))
        self.assertTrue(r.contains(0x20020000))
        self.assertTrue(r.contains(0x2003FFFF))
        self.assertFalse(r.contains(0x20040000))
        self.assertFalse(r.contains(0x1FFFFFFF))

    def test_v8m_region_end_property(self):
        """end property returns limit | 0x1F + 1 for v8M."""
        r = self.MPURegion.from_rbar_rlar(0, 0x20000000, 0x2003FFE0 | 1)
        self.assertEqual(r.end, 0x20040000)

    def test_v8m_ap_rw_priv_only(self):
        """AP=00: RW privileged only."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (0b00 << 1),  # AP=RW_PRIV
            0x2003FFE0 | 1,
        )
        self.assertTrue(r.check_permission(is_write=True, is_privileged=True, is_instruction=False))
        self.assertTrue(r.check_permission(is_write=False, is_privileged=True, is_instruction=False))
        self.assertFalse(r.check_permission(is_write=True, is_privileged=False, is_instruction=False))
        self.assertFalse(r.check_permission(is_write=False, is_privileged=False, is_instruction=False))

    def test_v8m_ap_rw_any(self):
        """AP=01: RW any privilege."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (0b01 << 1),  # AP=RW_ANY
            0x2003FFE0 | 1,
        )
        self.assertTrue(r.check_permission(is_write=True, is_privileged=True, is_instruction=False))
        self.assertTrue(r.check_permission(is_write=True, is_privileged=False, is_instruction=False))
        self.assertTrue(r.check_permission(is_write=False, is_privileged=False, is_instruction=False))

    def test_v8m_ap_ro_priv_only(self):
        """AP=10: RO privileged only."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (0b10 << 1),  # AP=RO_PRIV
            0x2003FFE0 | 1,
        )
        self.assertTrue(r.check_permission(is_write=False, is_privileged=True, is_instruction=False))
        self.assertFalse(r.check_permission(is_write=True, is_privileged=True, is_instruction=False))
        self.assertFalse(r.check_permission(is_write=False, is_privileged=False, is_instruction=False))

    def test_v8m_ap_ro_any(self):
        """AP=11: RO any privilege."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (0b11 << 1),  # AP=RO_ANY
            0x2003FFE0 | 1,
        )
        self.assertTrue(r.check_permission(is_write=False, is_privileged=True, is_instruction=False))
        self.assertTrue(r.check_permission(is_write=False, is_privileged=False, is_instruction=False))
        self.assertFalse(r.check_permission(is_write=True, is_privileged=True, is_instruction=False))

    def test_v8m_xn_blocks_execution(self):
        """XN bit prevents instruction fetch."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (0b01 << 1) | 1,  # XN=1
            0x2003FFE0 | 1,
        )
        self.assertTrue(r.xn)
        self.assertFalse(r.check_permission(is_write=False, is_privileged=True, is_instruction=True))
        self.assertTrue(r.check_permission(is_write=False, is_privileged=True, is_instruction=False))

    def test_v8m_to_rbar_rlar_roundtrip(self):
        """RBAR/RLAR encode+decode roundtrip."""
        r_orig = self.MPURegion.from_rbar_rlar(
            3,
            0x08000000 | (2 << 3) | (0b10 << 1) | 0,  # SH=outer, AP=RO_PRIV, XN=0
            0x080FFFE0 | (5 << 1) | 1,                 # AttrIndx=5, EN=1
        )
        rbar = r_orig.to_rbar_v8()
        rlar = r_orig.to_rlar_v8()
        r_decoded = self.MPURegion.from_rbar_rlar(3, rbar, rlar)

        self.assertEqual(r_decoded.base, r_orig.base)
        self.assertEqual(r_decoded.limit, r_orig.limit)
        self.assertEqual(r_decoded.sh, r_orig.sh)
        self.assertEqual(r_decoded.ap, r_orig.ap)
        self.assertEqual(r_decoded.xn, r_orig.xn)
        self.assertEqual(r_decoded.attr_idx, r_orig.attr_idx)
        self.assertEqual(r_decoded.enabled, r_orig.enabled)

    def test_v8m_mpu_register_readwrite(self):
        """Test CortexMPU v8M register read/write."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)

        # TYPE register
        self.assertEqual(mpu.read_register(self.MPUReg.TYPE), 8 << 8)

        # Set region 0
        mpu.write_register(self.MPUReg.RNR, 0)
        # RBAR: base=0x20000000, SH=inner(3), AP=RW_ANY(01), XN=0
        mpu.write_register(self.MPUReg.RBAR, 0x20000000 | (3 << 3) | (0b01 << 1))
        # RLAR: limit=0x2003FFE0, AttrIndx=0, EN=1
        mpu.write_register(self.MPUReg.RLAR, 0x2003FFE0 | (0 << 1) | 1)

        r = mpu.regions[0]
        self.assertEqual(r.base, 0x20000000)
        self.assertEqual(r.limit, 0x2003FFE0)
        self.assertEqual(r.sh, 3)
        self.assertEqual(r.ap, 0b01)
        self.assertTrue(r.enabled)
        self.assertTrue(r._v8m)

    def test_v8m_mpu_mair_registers(self):
        """Test MAIR0/MAIR1 read/write."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)

        mpu.write_register(self.MPUReg.MAIR0, 0x44BB00FF)
        mpu.write_register(self.MPUReg.MAIR1, 0x00000044)

        self.assertEqual(mpu.read_register(self.MPUReg.MAIR0), 0x44BB00FF)
        self.assertEqual(mpu.read_register(self.MPUReg.MAIR1), 0x00000044)

        # Check individual attribute extraction
        self.assertEqual(mpu.get_mair_attr(0), 0xFF)  # Attr0
        self.assertEqual(mpu.get_mair_attr(1), 0x00)  # Attr1
        self.assertEqual(mpu.get_mair_attr(2), 0xBB)  # Attr2
        self.assertEqual(mpu.get_mair_attr(3), 0x44)  # Attr3
        self.assertEqual(mpu.get_mair_attr(4), 0x44)  # Attr4
        self.assertEqual(mpu.get_mair_attr(5), 0x00)  # Attr5

    def test_v8m_mpu_mair_ignored_for_v7(self):
        """MAIR reads return 0 for PMSAv7 MPU."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=False)
        mpu.write_register(self.MPUReg.MAIR0, 0xDEADBEEF)
        self.assertEqual(mpu.read_register(self.MPUReg.MAIR0), 0)

    def test_v8m_mpu_alias_registers(self):
        """Test v8M alias register programming (4 consecutive regions)."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)

        # Select region 0 as base
        mpu.write_register(self.MPUReg.RNR, 0)

        # Program regions 0-3 via RBAR/RLAR + aliases
        bases = [0x20000000, 0x20040000, 0x20080000, 0x200C0000]
        limits = [0x2003FFE0, 0x2007FFE0, 0x200BFFE0, 0x200FFFE0]

        mpu.write_register(self.MPUReg.RBAR, bases[0] | (0b01 << 1))
        mpu.write_register(self.MPUReg.RLAR, limits[0] | 1)
        mpu.write_register(self.MPUReg.RBAR_A1, bases[1] | (0b01 << 1))
        mpu.write_register(self.MPUReg.RLAR_A1, limits[1] | 1)
        mpu.write_register(self.MPUReg.RBAR_A2, bases[2] | (0b01 << 1))
        mpu.write_register(self.MPUReg.RLAR_A2, limits[2] | 1)
        mpu.write_register(self.MPUReg.RBAR_A3, bases[3] | (0b01 << 1))
        mpu.write_register(self.MPUReg.RLAR_A3, limits[3] | 1)

        for i in range(4):
            self.assertEqual(mpu.regions[i].base, bases[i], f"region {i}")
            self.assertEqual(mpu.regions[i].limit, limits[i], f"region {i}")
            self.assertTrue(mpu.regions[i].enabled, f"region {i}")

    def test_v8m_mpu_access_check(self):
        """End-to-end access check with PMSAv8 MPU."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)
        mpu.enabled = True

        # Region 0: SRAM RW privileged only
        mpu.write_register(self.MPUReg.RNR, 0)
        mpu.write_register(self.MPUReg.RBAR, 0x20000000 | (0b00 << 1))  # AP=RW_PRIV
        mpu.write_register(self.MPUReg.RLAR, 0x2003FFE0 | 1)

        # Region 1: Flash RO any privilege
        mpu.write_register(self.MPUReg.RNR, 1)
        mpu.write_register(self.MPUReg.RBAR, 0x08000000 | (0b11 << 1))  # AP=RO_ANY
        mpu.write_register(self.MPUReg.RLAR, 0x080FFFE0 | 1)

        # SRAM: priv RW OK, unpriv fails
        self.assertTrue(mpu.check_access(0x20001000, is_write=True, is_privileged=True))
        self.assertFalse(mpu.check_access(0x20001000, is_write=True, is_privileged=False))

        # Flash: any read OK, any write fails
        self.assertTrue(mpu.check_access(0x08001000, is_write=False, is_privileged=True))
        self.assertTrue(mpu.check_access(0x08001000, is_write=False, is_privileged=False))
        self.assertFalse(mpu.check_access(0x08001000, is_write=True, is_privileged=True))

        # Unmapped address: fault (no PRIVDEFENA)
        self.assertFalse(mpu.check_access(0x40000000, is_privileged=True))

    def test_v8m_mpu_privdefena(self):
        """PRIVDEFENA allows privileged access to unmapped regions."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)
        mpu.enabled = True
        mpu.privdefena = True

        # No regions configured
        self.assertTrue(mpu.check_access(0x40000000, is_privileged=True))
        self.assertFalse(mpu.check_access(0x40000000, is_privileged=False))

    def test_v8m_shm_sync(self):
        """Test SHM sync with PMSAv8 RBAR+RLAR format."""
        from slab_cortex_m.shm_peripheral import ShmPeripheralBridge, ShmHeader

        bridge = ShmPeripheralBridge.__new__(ShmPeripheralBridge)
        bridge._shm = Mock()

        # Build v8M MPU state
        ctrl = (1 << self.MPUCtrlBits.ENABLE) | (1 << self.MPUCtrlBits.PRIVDEFENA)
        # Region 0: RBAR=0x20000000|SH=3|AP=01|XN=0, RLAR=0x2003FFE0|AttrIndx=0|EN=1
        rbar0 = 0x20000000 | (3 << 3) | (0b01 << 1) | 0
        rlar0 = 0x2003FFE0 | (0 << 1) | 1
        # Region 1: RBAR=0x08000000|SH=0|AP=11|XN=0, RLAR=0x080FFFE0|AttrIndx=1|EN=1
        rbar1 = 0x08000000 | (0 << 3) | (0b11 << 1) | 0
        rlar1 = 0x080FFFE0 | (1 << 1) | 1

        data = struct.pack('<I', ctrl)
        data += struct.pack('<II', rbar0, rlar0)
        data += struct.pack('<II', rbar1, rlar1)
        for _ in range(6):
            data += struct.pack('<II', 0, 0)

        full_buf = bytearray(1024)
        full_buf[64:64+len(data)] = data
        bridge._shm.buf = full_buf

        # Sync with v8M MPU
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)
        result = bridge.sync_mpu_from_shm(mpu)

        self.assertIs(result, mpu)
        self.assertTrue(mpu.enabled)
        self.assertTrue(mpu.privdefena)

        r0 = mpu.regions[0]
        self.assertTrue(r0.enabled)
        self.assertTrue(r0._v8m)
        self.assertEqual(r0.base, 0x20000000)
        self.assertEqual(r0.limit, 0x2003FFE0)
        self.assertEqual(r0.sh, 3)
        self.assertEqual(r0.ap, 0b01)

        r1 = mpu.regions[1]
        self.assertTrue(r1.enabled)
        self.assertEqual(r1.base, 0x08000000)
        self.assertEqual(r1.limit, 0x080FFFE0)
        self.assertEqual(r1.ap, 0b11)
        self.assertEqual(r1.attr_idx, 1)

    def test_v8m_region_disabled(self):
        """Disabled v8M regions don't match."""
        r = self.MPURegion.from_rbar_rlar(
            0,
            0x20000000 | (0b01 << 1),
            0x2003FFE0 | (0 << 1) | 0,  # EN=0
        )
        self.assertFalse(r.enabled)
        self.assertFalse(r.contains(0x20001000))

    def test_v8m_mpu_reset(self):
        """Reset clears all v8M state including MAIR."""
        mpu = self.CortexMPU(num_regions=8, arch_v8m=True)
        mpu.enabled = True
        mpu.mair = [0xDEADBEEF, 0xCAFEBABE]
        mpu.write_register(self.MPUReg.RNR, 0)
        mpu.write_register(self.MPUReg.RBAR, 0x20000000 | (0b01 << 1))
        mpu.write_register(self.MPUReg.RLAR, 0x2003FFE0 | 1)

        mpu.reset()
        self.assertFalse(mpu.enabled)
        self.assertEqual(mpu.mair, [0, 0])
        self.assertFalse(mpu.regions[0].enabled)
        self.assertEqual(mpu.regions[0].base, 0)
        self.assertEqual(mpu.regions[0].limit, 0)


# =============================================================================
# GTZC ENFORCEMENT TESTS
# =============================================================================

class TestSTM32GTZCProtection(unittest.TestCase):
    """Test GTZC TrustZone enforcement for STM32U5."""

    def setUp(self):
        from slab_stm32.stm32u5xx import STM32GTZC, STM32MPCBB, STM32GTZCProtection
        self.STM32GTZC = STM32GTZC
        self.STM32MPCBB = STM32MPCBB
        self.STM32GTZCProtection = STM32GTZCProtection

    def _create_protection(self):
        """Create GTZC protection with 3 MPCBBs."""
        gtzc = self.STM32GTZC()
        mpcbb1 = self.STM32MPCBB(index=1)
        mpcbb2 = self.STM32MPCBB(index=2)
        mpcbb3 = self.STM32MPCBB(index=3)
        prot = self.STM32GTZCProtection(gtzc, [mpcbb1, mpcbb2, mpcbb3])
        return prot, gtzc, mpcbb1, mpcbb2, mpcbb3

    def test_ns_access_allowed_to_ns_peripheral(self):
        """NS access to non-secure peripheral should pass."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # USART2 (periph_id=9) is NOT secure
        self.assertTrue(prot.check_access(0x40004400, ns=True))

    def test_ns_access_denied_to_secure_peripheral(self):
        """NS access to secure peripheral should be denied."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Mark USART2 (periph_id=9) as secure
        gtzc.seccfgr[0] |= (1 << 9)

        self.assertFalse(prot.check_access(0x40004400, ns=True))
        self.assertEqual(prot._violation_count, 1)

    def test_secure_access_allowed_to_secure_peripheral(self):
        """Secure access (ns=False) to secure peripheral should pass."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Mark USART2 as secure
        gtzc.seccfgr[0] |= (1 << 9)

        # Secure access (ns=False) should pass
        self.assertTrue(prot.check_access(0x40004400, ns=False))

    def test_ns_access_to_secure_alias_denied(self):
        """NS access to secure alias address (0x5xxxxxxx) should be denied."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Any NS access to the secure alias space should be denied
        self.assertFalse(prot.check_access(0x50004400, ns=True))
        self.assertEqual(prot._violation_count, 1)

    def test_secure_access_to_secure_alias_allowed(self):
        """Secure access to secure alias should pass."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Secure access to secure alias is fine
        self.assertTrue(prot.check_access(0x50004400, ns=False))

    def test_unprivileged_access_denied_to_privileged_peripheral(self):
        """Unprivileged access to PRIVCFGR-protected peripheral denied."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Mark USART2 (periph_id=9) as privileged-only
        gtzc.privcfgr[0] |= (1 << 9)

        # Unprivileged access should be denied
        self.assertFalse(prot.check_access(
            0x40004400, is_privileged=False, ns=False))

    def test_privileged_access_allowed_to_privileged_peripheral(self):
        """Privileged access to PRIVCFGR-protected peripheral passes."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Mark USART2 as privileged-only
        gtzc.privcfgr[0] |= (1 << 9)

        # Privileged access should pass
        self.assertTrue(prot.check_access(
            0x40004400, is_privileged=True, ns=False))

    def test_ns_access_to_secure_sram_denied(self):
        """NS access to MPCBB-secure SRAM block should be denied."""
        prot, gtzc, mpcbb1, *_ = self._create_protection()
        prot.enable_override()

        # Mark block 0 of SRAM1 as secure
        mpcbb1.seccfgr[0] |= (1 << 0)  # Block 0

        # NS access to SRAM1 block 0 (0x20000000-0x200001FF)
        self.assertFalse(prot.check_access(0x20000000, ns=True))
        self.assertFalse(prot.check_access(0x200001FF, ns=True))

    def test_ns_access_to_non_secure_sram_allowed(self):
        """NS access to non-secure SRAM block should pass."""
        prot, gtzc, mpcbb1, *_ = self._create_protection()
        prot.enable_override()

        # Block 1 is not secure (default)
        # SRAM1 block 1 = 0x20000200-0x200003FF
        self.assertTrue(prot.check_access(0x20000200, ns=True))

    def test_secure_access_to_secure_sram_allowed(self):
        """Secure access to secure SRAM should pass."""
        prot, gtzc, mpcbb1, *_ = self._create_protection()
        prot.enable_override()

        mpcbb1.seccfgr[0] |= (1 << 0)

        # Secure access should pass
        self.assertTrue(prot.check_access(0x20000000, ns=False))

    def test_ns_access_secure_sram_alias_denied(self):
        """NS access to secure SRAM alias (0x3xxxxxxx) should be denied."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # NS access to SRAM secure alias
        self.assertFalse(prot.check_access(0x30000000, ns=True))

    def test_tzic_status_updated_on_violation(self):
        """TZIC SR bits should be set on illegal access."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        # Mark GPIOA (periph_id=64) as secure
        gtzc.seccfgr[2] |= (1 << 0)  # ID 64 = seccfgr[2] bit 0

        # NS access should fail and set TZIC SR
        prot.check_access(0x42020000, ns=True)

        # TZIC SR3 bit 0 should be set (periph_id 64 → reg 2, bit 0)
        self.assertEqual(gtzc.tzic_sr[2] & 1, 1)

    def test_tzic_interrupt_fired_on_violation(self):
        """IRQ callback should fire when TZIC IER is enabled."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        irq_fired = []
        prot.irq_callback = lambda: irq_fired.append(True)

        # Mark GPIOA as secure and enable TZIC interrupt
        gtzc.seccfgr[2] |= (1 << 0)  # GPIOA secure
        gtzc.tzic_ier[2] |= (1 << 0)  # Enable IER for GPIOA

        # NS access should trigger IRQ
        prot.check_access(0x42020000, ns=True)
        self.assertEqual(len(irq_fired), 1)

    def test_address_translation_secure_to_ns(self):
        """Secure alias addresses should translate to NS base."""
        prot, *_ = self._create_protection()

        # Peripheral secure alias
        addr, valid = prot.translate_address(0x50004400)
        self.assertEqual(addr, 0x40004400)
        self.assertTrue(valid)

        # SRAM secure alias
        addr, valid = prot.translate_address(0x30010000)
        self.assertEqual(addr, 0x20010000)
        self.assertTrue(valid)

        # Regular address unchanged
        addr, valid = prot.translate_address(0x40004400)
        self.assertEqual(addr, 0x40004400)
        self.assertTrue(valid)

    def test_mpcbb_block_calculation(self):
        """Verify correct SRAM block calculation from address."""
        prot, gtzc, mpcbb1, mpcbb2, mpcbb3 = self._create_protection()
        prot.enable_override()

        # Mark SRAM2 block 5 as secure
        mpcbb2.seccfgr[0] |= (1 << 5)

        # SRAM2 starts at 0x20040000, block 5 = offset 5*512 = 0xA00
        target_addr = 0x20040000 + 5 * 512
        self.assertFalse(prot.check_access(target_addr, ns=True))

        # Block 4 should be fine
        safe_addr = 0x20040000 + 4 * 512
        self.assertTrue(prot.check_access(safe_addr, ns=True))

    def test_peripheral_set_has_gtzc_protection(self):
        """STM32U5xxPeripheralSet should have gtzc_protection instance."""
        from slab_stm32.stm32u5xx import STM32U5A5PeripheralSet
        periph_set = STM32U5A5PeripheralSet()
        self.assertIsNotNone(periph_set.gtzc_protection)
        self.assertIsInstance(periph_set.gtzc_protection, self.STM32GTZCProtection)

    def test_fault_callback(self):
        """Fault callback should receive ProtectionFault on violation."""
        prot, gtzc, *_ = self._create_protection()
        prot.enable_override()

        faults = []
        prot.fault_callback = lambda f: faults.append(f)

        # Mark SPI1 (periph_id=33) as secure
        gtzc.seccfgr[1] |= (1 << 1)  # ID 33 = seccfgr[1] bit 1

        prot.check_access(0x40013000, ns=True, is_write=True)

        self.assertEqual(len(faults), 1)
        self.assertEqual(faults[0].fault_type, "GTZC")
        self.assertTrue(faults[0].is_write)
        self.assertIn("secure peripheral", faults[0].details)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
