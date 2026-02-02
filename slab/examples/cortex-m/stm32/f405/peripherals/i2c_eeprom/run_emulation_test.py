#!/usr/bin/env python3
"""
I2C EEPROM Emulation Test - Full QEMU Integration

This test actually runs the compiled firmware in QEMU with the mcuemu machine,
connecting a virtual 24C256 EEPROM and communicating via CDC.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import socket
import struct
import subprocess
import time
import threading
import queue

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from virtual_components import EEPROM_24Cxx

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR))))
QEMU_BIN = os.path.join(PROJECT_DIR, 'qemu', 'build', 'qemu-system-arm')
FIRMWARE = os.path.join(SCRIPT_DIR, 'i2c_eeprom_test.bin')

# Protocol constants (from mcuemu_server.py)
CMD_READ = ord('R')
CMD_WRITE = ord('W')
STATUS_OK = 0

# Memory-mapped addresses for CDC and I2C
CDC_OUT = 0xE0000000
CDC_IN = 0xE0000004
CDC_STATUS = 0xE0000008

# I2C1 registers (STM32F4)
I2C1_BASE = 0x40005400
I2C1_CR1 = I2C1_BASE + 0x00
I2C1_CR2 = I2C1_BASE + 0x04
I2C1_DR = I2C1_BASE + 0x10
I2C1_SR1 = I2C1_BASE + 0x14
I2C1_SR2 = I2C1_BASE + 0x18


class PeripheralServer:
    """Handles peripheral emulation for QEMU."""

    def __init__(self, port: int = 5000):
        self.port = port
        self.running = False
        self.server_socket = None
        self.client_socket = None
        self.eeprom = EEPROM_24Cxx('24C256', address=0x50)

        # CDC buffers
        self.cdc_tx_queue = queue.Queue()  # From MCU to host
        self.cdc_rx_queue = queue.Queue()  # From host to MCU

        # I2C state
        self.i2c_state = 'IDLE'
        self.i2c_addr = 0
        self.i2c_is_read = False
        self.i2c_tx_buffer = bytearray()

    def start(self):
        """Start the server."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('localhost', self.port))
        self.server_socket.listen(1)
        self.running = True

        self.thread = threading.Thread(target=self._serve)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        """Stop the server."""
        self.running = False
        if self.client_socket:
            self.client_socket.close()
        if self.server_socket:
            self.server_socket.close()

    def _serve(self):
        """Server thread."""
        try:
            self.server_socket.settimeout(1.0)
            while self.running:
                try:
                    self.client_socket, addr = self.server_socket.accept()
                    print(f"  Client connected from {addr}")
                    self._handle_client()
                except socket.timeout:
                    continue
        except Exception as e:
            if self.running:
                print(f"  Server error: {e}")

    def _handle_client(self):
        """Handle client connection."""
        try:
            while self.running:
                # Read request: [cmd:1][addr:4][size:4][value:4 if write]
                header = self.client_socket.recv(9)
                if not header:
                    break

                cmd = header[0]
                addr = struct.unpack('<I', header[1:5])[0]
                size = struct.unpack('<I', header[5:9])[0]

                if cmd == CMD_WRITE:
                    value_data = self.client_socket.recv(4)
                    value = struct.unpack('<I', value_data)[0]
                    self._handle_write(addr, size, value)
                    response = struct.pack('<IB', 0, STATUS_OK)
                elif cmd == CMD_READ:
                    value = self._handle_read(addr, size)
                    response = struct.pack('<IB', value, STATUS_OK)
                else:
                    response = struct.pack('<IB', 0, 1)  # Error

                self.client_socket.send(response)
        except Exception as e:
            if self.running:
                print(f"  Client error: {e}")

    def _handle_read(self, addr: int, size: int) -> int:
        """Handle memory read."""
        # CDC registers
        if addr == CDC_STATUS:
            return 1 if not self.cdc_rx_queue.empty() else 0
        elif addr == CDC_IN:
            try:
                return self.cdc_rx_queue.get_nowait()
            except queue.Empty:
                return 0

        # I2C registers
        elif addr == I2C1_SR1:
            return self._get_i2c_sr1()
        elif addr == I2C1_SR2:
            return self._get_i2c_sr2()
        elif addr == I2C1_DR:
            return self._read_i2c_dr()

        return 0

    def _handle_write(self, addr: int, size: int, value: int):
        """Handle memory write."""
        # CDC output
        if addr == CDC_OUT:
            char = chr(value & 0xFF)
            self.cdc_tx_queue.put(char)
            return

        # I2C registers
        elif addr == I2C1_CR1:
            self._write_i2c_cr1(value)
        elif addr == I2C1_DR:
            self._write_i2c_dr(value)

    def _get_i2c_sr1(self) -> int:
        """Get I2C status register 1."""
        sr1 = 0
        if self.i2c_state == 'START':
            sr1 |= (1 << 0)  # SB - Start bit
        elif self.i2c_state == 'ADDR':
            sr1 |= (1 << 1)  # ADDR
        elif self.i2c_state == 'DATA':
            sr1 |= (1 << 7)  # TXE
            sr1 |= (1 << 2)  # BTF
            if self.i2c_is_read:
                sr1 |= (1 << 6)  # RXNE
        return sr1

    def _get_i2c_sr2(self) -> int:
        """Get I2C status register 2."""
        sr2 = 0
        if self.i2c_state != 'IDLE':
            sr2 |= (1 << 0)  # MSL - Master
            sr2 |= (1 << 1)  # BUSY
            if not self.i2c_is_read:
                sr2 |= (1 << 2)  # TRA - Transmitter
        return sr2

    def _write_i2c_cr1(self, value: int):
        """Write I2C control register 1."""
        # START condition
        if value & (1 << 8):
            self.i2c_state = 'START'
            self.i2c_tx_buffer = bytearray()

        # STOP condition
        if value & (1 << 9):
            if not self.i2c_is_read and len(self.i2c_tx_buffer) > 2:
                # Process EEPROM write
                self.eeprom.i2c_write(bytes(self.i2c_tx_buffer))
            self.i2c_state = 'IDLE'

    def _write_i2c_dr(self, value: int):
        """Write I2C data register."""
        data = value & 0xFF

        if self.i2c_state == 'START':
            # Address byte
            self.i2c_addr = data >> 1
            self.i2c_is_read = bool(data & 1)
            self.i2c_state = 'ADDR'

            if not self.i2c_is_read:
                self.i2c_tx_buffer = bytearray()

        elif self.i2c_state in ('ADDR', 'DATA'):
            self.i2c_state = 'DATA'
            if not self.i2c_is_read:
                self.i2c_tx_buffer.append(data)

                # Update EEPROM address pointer after 2 bytes
                if len(self.i2c_tx_buffer) == 2:
                    addr = (self.i2c_tx_buffer[0] << 8) | self.i2c_tx_buffer[1]
                    self.eeprom._write_address = addr

    def _read_i2c_dr(self) -> int:
        """Read I2C data register."""
        if self.i2c_is_read:
            data = self.eeprom.i2c_read(1)
            return data[0] if data else 0xFF
        return 0

    def send_cdc_command(self, cmd: str) -> str:
        """Send CDC command and get response."""
        # Send command
        for char in cmd + '\n':
            self.cdc_rx_queue.put(ord(char))

        # Wait for response
        response = []
        timeout = time.time() + 2.0

        while time.time() < timeout:
            try:
                char = self.cdc_tx_queue.get(timeout=0.1)
                if char == '\n':
                    break
                response.append(char)
            except queue.Empty:
                continue

        return ''.join(response)


def run_qemu_test():
    """Run the full QEMU emulation test."""
    print("=" * 60)
    print("I2C EEPROM QEMU Emulation Test")
    print("=" * 60)

    # Check prerequisites
    if not os.path.exists(QEMU_BIN):
        print(f"ERROR: QEMU not found at {QEMU_BIN}")
        return 1

    if not os.path.exists(FIRMWARE):
        print(f"ERROR: Firmware not found at {FIRMWARE}")
        print("Build it with: make")
        return 1

    print(f"\n  QEMU: {QEMU_BIN}")
    print(f"  Firmware: {FIRMWARE}")

    # Start peripheral server
    print("\nStarting peripheral server...")
    server = PeripheralServer(port=5555)
    server.start()
    time.sleep(0.5)

    # Start QEMU
    print("Starting QEMU...")
    qemu_cmd = [
        QEMU_BIN,
        '-M', 'mcuemu',
        '-cpu', 'cortex-m4',
        '-kernel', FIRMWARE,
        '-global', 'mcuemu.tcp-port=5555',
        '-nographic',
        '-serial', 'null',
    ]

    try:
        qemu_proc = subprocess.Popen(
            qemu_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Wait for QEMU to connect
        time.sleep(1.0)

        # Wait for firmware ready message
        print("\nWaiting for firmware...")
        timeout = time.time() + 5.0
        ready = False
        while time.time() < timeout:
            try:
                char = server.cdc_tx_queue.get(timeout=0.1)
                sys.stdout.write(char)
                sys.stdout.flush()
                if char == '\n':
                    ready = True
                    break
            except queue.Empty:
                continue

        if not ready:
            print("\nERROR: Firmware did not respond")
            qemu_proc.terminate()
            server.stop()
            return 1

        print("\n\n=== Running Tests ===")

        # Test PING
        print("\nTest: PING")
        response = server.send_cdc_command("PING")
        if response == "PONG":
            print(f"  PASS: {response}")
        else:
            print(f"  FAIL: Expected PONG, got '{response}'")

        # Test WRITE/READ
        print("\nTest: WRITE/READ")
        response = server.send_cdc_command("WRITE 0000 deadbeef")
        if response == "OK":
            print(f"  Write: {response}")
        else:
            print(f"  Write FAIL: {response}")

        response = server.send_cdc_command("READ 0000 04")
        if response == "deadbeef":
            print(f"  Read: {response}")
            print("  PASS")
        else:
            print(f"  Read FAIL: Expected 'deadbeef', got '{response}'")

        # Verify EEPROM contents
        print("\nVerifying EEPROM memory...")
        contents = server.eeprom._memory[0:4]
        expected = bytes.fromhex("deadbeef")
        if contents == expected:
            print(f"  PASS: EEPROM contains {contents.hex()}")
        else:
            print(f"  FAIL: EEPROM contains {contents.hex()}, expected {expected.hex()}")

        print("\n=== Test Complete ===")

    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    finally:
        # Cleanup
        try:
            qemu_proc.terminate()
            qemu_proc.wait(timeout=2)
        except:
            qemu_proc.kill()
        server.stop()

    return 0


if __name__ == "__main__":
    sys.exit(run_qemu_test())
