#!/usr/bin/env python3
"""
MCUemu Test Peripheral Server

This server emulates peripherals for the MCUemu test firmware.
It implements the binary protocol to communicate with QEMU.

Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import socket
import struct
import threading
import time
import sys
import argparse
from dataclasses import dataclass
from typing import Dict, Callable, Optional
from enum import IntEnum


class TestStatus(IntEnum):
    RUNNING = 0
    PASS = 1
    FAIL = 2


@dataclass
class TestResult:
    status: TestStatus = TestStatus.RUNNING
    test_id: int = 0
    data: int = 0
    error: int = 0


class MCUemuTestServer:
    """Test peripheral server for MCUemu"""

    # Peripheral base addresses (must match mcuemu.h)
    GPIO_BASE = 0x40000000
    UART_BASE = 0x40001000
    TIMER_BASE = 0x40002000
    RESULT_BASE = 0x4000F000

    # UART status bits
    UART_SR_TXE = 1 << 0
    UART_SR_RXNE = 1 << 1
    UART_SR_TC = 1 << 2

    def __init__(self, port: int = 5000, verbose: bool = False):
        self.port = port
        self.verbose = verbose
        self.running = False
        self.server_socket = None
        self.client_socket = None

        # Register storage (simulated peripheral registers)
        self.registers: Dict[int, int] = {}

        # Test result
        self.test_result = TestResult()

        # UART buffers
        self.uart_rx_buffer: list = []
        self.uart_tx_buffer: list = []

        # Timer state
        self.timer_enabled = False
        self.timer_counter = 0
        self.timer_reload = 0xFFFFFFFF

        # IRQ injection queue
        self.pending_irqs: list = []

        # Callbacks for special register handling
        self.read_handlers: Dict[int, Callable] = {}
        self.write_handlers: Dict[int, Callable] = {}

        self._setup_handlers()

    def _setup_handlers(self):
        """Setup special register handlers"""
        # UART handlers
        self.read_handlers[self.UART_BASE + 0x00] = self._uart_read_dr
        self.read_handlers[self.UART_BASE + 0x04] = self._uart_read_sr
        self.write_handlers[self.UART_BASE + 0x00] = self._uart_write_dr

        # Timer handlers
        self.read_handlers[self.TIMER_BASE + 0x00] = self._timer_read_cnt
        self.write_handlers[self.TIMER_BASE + 0x08] = self._timer_write_cr

        # Test result handlers
        self.write_handlers[self.RESULT_BASE + 0x00] = self._result_write_status
        self.write_handlers[self.RESULT_BASE + 0x04] = self._result_write_test_id
        self.write_handlers[self.RESULT_BASE + 0x08] = self._result_write_data
        self.write_handlers[self.RESULT_BASE + 0x0C] = self._result_write_error

        # GPIO special handler (IRQ injection trigger)
        self.write_handlers[self.GPIO_BASE + 0x0C] = self._gpio_write_ctrl

    def _uart_read_dr(self, addr: int, size: int) -> int:
        """Read UART data register"""
        if self.uart_rx_buffer:
            return self.uart_rx_buffer.pop(0)
        return 0

    def _uart_read_sr(self, addr: int, size: int) -> int:
        """Read UART status register"""
        status = self.UART_SR_TXE | self.UART_SR_TC  # Always ready to transmit
        if self.uart_rx_buffer:
            status |= self.UART_SR_RXNE
        return status

    def _uart_write_dr(self, addr: int, size: int, value: int):
        """Write UART data register"""
        char = value & 0xFF
        self.uart_tx_buffer.append(char)
        # Echo back to RX for echo test
        self.uart_rx_buffer.append(char)
        if self.verbose:
            print(f"UART TX: {chr(char) if 32 <= char < 127 else f'0x{char:02X}'}")

    def _timer_read_cnt(self, addr: int, size: int) -> int:
        """Read timer counter"""
        if self.timer_enabled:
            self.timer_counter = (self.timer_counter - 1) & 0xFFFFFFFF
        return self.timer_counter

    def _timer_write_cr(self, addr: int, size: int, value: int):
        """Write timer control register"""
        self.timer_enabled = bool(value & 0x01)
        if self.timer_enabled:
            self.timer_counter = self.timer_reload
            if self.verbose:
                print("Timer enabled")

    def _gpio_write_ctrl(self, addr: int, size: int, value: int):
        """GPIO control register - used to trigger IRQ injection"""
        if value == 0xFF:
            # Request to inject EXTI1 interrupt
            self.pending_irqs.append(1)
            if self.verbose:
                print("IRQ injection requested: EXTI1")

    def _result_write_status(self, addr: int, size: int, value: int):
        """Write test result status"""
        self.test_result.status = TestStatus(value)
        if self.verbose:
            status_str = {0: "RUNNING", 1: "PASS", 2: "FAIL"}.get(value, "UNKNOWN")
            print(f"Test status: {status_str}")
        if value in (TestStatus.PASS, TestStatus.FAIL):
            self._print_result()

    def _result_write_test_id(self, addr: int, size: int, value: int):
        """Write test ID"""
        self.test_result.test_id = value
        if self.verbose:
            print(f"Test ID: 0x{value:04X}")

    def _result_write_data(self, addr: int, size: int, value: int):
        """Write test data"""
        self.test_result.data = value
        if self.verbose:
            print(f"Test data: 0x{value:08X}")

    def _result_write_error(self, addr: int, size: int, value: int):
        """Write test error code"""
        self.test_result.error = value
        if self.verbose:
            print(f"Test error: {value}")

    def _print_result(self):
        """Print test result summary"""
        status = "PASS" if self.test_result.status == TestStatus.PASS else "FAIL"
        print(f"\n{'='*60}")
        print(f"TEST RESULT: {status}")
        print(f"Test ID:     0x{self.test_result.test_id:04X}")
        print(f"Data:        0x{self.test_result.data:08X}")
        if self.test_result.status == TestStatus.FAIL:
            print(f"Error code:  {self.test_result.error}")
        print(f"{'='*60}\n")

    def read_register(self, addr: int, size: int) -> int:
        """Read a register value"""
        # Check for special handler
        if addr in self.read_handlers:
            return self.read_handlers[addr](addr, size)

        # Return cached value or 0
        return self.registers.get(addr, 0)

    def write_register(self, addr: int, size: int, value: int):
        """Write a register value"""
        # Store in cache
        self.registers[addr] = value

        # Check for special handler
        if addr in self.write_handlers:
            self.write_handlers[addr](addr, size, value)

    def handle_client(self, client_socket: socket.socket):
        """Handle client connection"""
        self.client_socket = client_socket
        client_socket.settimeout(0.1)

        while self.running:
            try:
                # Read request header
                data = client_socket.recv(1)
                if not data:
                    break

                req_type = data[0]

                if req_type == ord('R'):  # Read
                    # Read address (4 bytes), size (4 bytes), security (1 byte)
                    addr_data = client_socket.recv(9)
                    if len(addr_data) < 9:
                        break
                    addr, size = struct.unpack('<II', addr_data[:8])
                    secure = addr_data[8]

                    value = self.read_register(addr, size)

                    if self.verbose:
                        sec_str = "[S]" if secure else ""
                        print(f"READ  0x{addr:08X} [{size}]{sec_str} = 0x{value:08X}")

                    # Send response: value (4 bytes) + status (1 byte)
                    resp = struct.pack('<IB', value, 0)
                    client_socket.send(resp)

                elif req_type == ord('W'):  # Write
                    # Read address (4), size (4), value (4), security (1)
                    write_data = client_socket.recv(13)
                    if len(write_data) < 13:
                        break
                    addr, size, value = struct.unpack('<III', write_data[:12])
                    secure = write_data[12]

                    self.write_register(addr, size, value)

                    if self.verbose:
                        sec_str = "[S]" if secure else ""
                        print(f"WRITE 0x{addr:08X} [{size}]{sec_str} = 0x{value:08X}")

                    # Send response: value echo (4 bytes) + status (1 byte)
                    resp = struct.pack('<IB', value, 0)
                    client_socket.send(resp)

                elif req_type in (ord('S'), ord('T')):  # Secure read/write
                    # Same as R/W but with security attribute
                    # For testing, treat same as normal access
                    if req_type == ord('S'):
                        addr_data = client_socket.recv(8)
                        if len(addr_data) < 8:
                            break
                        addr, size = struct.unpack('<II', addr_data)
                        value = self.read_register(addr, size)
                        resp = struct.pack('<IB', value, 0)
                        client_socket.send(resp)
                    else:
                        write_data = client_socket.recv(12)
                        if len(write_data) < 12:
                            break
                        addr, size, value = struct.unpack('<III', write_data)
                        self.write_register(addr, size, value)
                        resp = struct.pack('<IB', value, 0)
                        client_socket.send(resp)

            except socket.timeout:
                continue
            except Exception as e:
                if self.verbose:
                    print(f"Error: {e}")
                break

        client_socket.close()
        self.client_socket = None

    def start(self):
        """Start the server"""
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.server_socket.bind(('127.0.0.1', self.port))
        self.server_socket.listen(1)
        self.server_socket.settimeout(1.0)

        print(f"MCUemu Test Server listening on port {self.port}")

        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"Client connected from {addr}")
                self.handle_client(client_socket)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Server error: {e}")
                break

        self.server_socket.close()

    def stop(self):
        """Stop the server"""
        self.running = False

    def get_result(self) -> TestResult:
        """Get test result"""
        return self.test_result

    def reset(self):
        """Reset server state"""
        self.registers.clear()
        self.test_result = TestResult()
        self.uart_rx_buffer.clear()
        self.uart_tx_buffer.clear()
        self.timer_enabled = False
        self.timer_counter = 0


def main():
    parser = argparse.ArgumentParser(description='MCUemu Test Peripheral Server')
    parser.add_argument('-p', '--port', type=int, default=5000,
                        help='TCP port (default: 5000)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    parser.add_argument('-t', '--timeout', type=float, default=30.0,
                        help='Test timeout in seconds (default: 30)')
    args = parser.parse_args()

    server = MCUemuTestServer(port=args.port, verbose=args.verbose)

    # Run server in a thread with timeout
    server_thread = threading.Thread(target=server.start, daemon=True)
    server_thread.start()

    try:
        start_time = time.time()
        while time.time() - start_time < args.timeout:
            time.sleep(0.1)
            result = server.get_result()
            if result.status != TestStatus.RUNNING:
                break
    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        server.stop()

    # Return exit code based on test result
    result = server.get_result()
    if result.status == TestStatus.PASS:
        sys.exit(0)
    elif result.status == TestStatus.FAIL:
        sys.exit(1)
    else:
        print("Test did not complete")
        sys.exit(2)


if __name__ == '__main__':
    main()
