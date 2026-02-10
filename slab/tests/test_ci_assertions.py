"""
Unit tests for CI runner bus-level assertions.

Tests the 4 new assertion checkers:
- spi_transactions
- i2c_transactions
- uart_contains
- usb_setup

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import time
import pytest

from slab_cortex_m.ci_runner import (
    check_spi_transactions,
    check_i2c_transactions,
    check_uart_contains,
    check_usb_setup,
)
from slab_cortex_m.virtual_components import (
    SPITransaction,
    I2CTransaction,
    W25QxxFlash,
    EEPROM_24Cxx,
)


class FakeBoard:
    """Minimal board mock for assertion tests."""

    def __init__(self):
        self.bus_devices = {}
        self.uart_output = bytearray()
        self.usb_transactions = []

        class FakeAdapter:
            peripherals = []
        self.adapter = FakeAdapter()


# =============================================================================
# SPI Transaction Assertions
# =============================================================================

class TestSPITransactions:

    def test_pass_min_count(self):
        board = FakeBoard()
        flash = W25QxxFlash(model='W25Q128')
        # Generate transactions via packet-level transfer
        flash.select()
        flash.transfer(bytes([0x9F, 0, 0, 0]))  # JEDEC ID
        flash.deselect()
        flash.select()
        flash.transfer(bytes([0x05, 0]))  # Read SR1
        flash.deselect()
        flash.select()
        flash.transfer(bytes([0x03, 0, 0, 0, 0, 0]))  # Read Data
        flash.deselect()
        board.bus_devices['SPI1'] = [flash]

        result = check_spi_transactions(board, {'bus': 'SPI1', 'min_count': 3})
        assert result.passed
        assert 'count=3' in result.detail

    def test_fail_min_count(self):
        board = FakeBoard()
        flash = W25QxxFlash(model='W25Q128')
        flash.select()
        flash.transfer(bytes([0x9F, 0, 0, 0]))
        flash.deselect()
        board.bus_devices['SPI1'] = [flash]

        result = check_spi_transactions(board, {'bus': 'SPI1', 'min_count': 5})
        assert not result.passed

    def test_pass_contains_mosi(self):
        board = FakeBoard()
        flash = W25QxxFlash(model='W25Q128')
        flash.select()
        flash.transfer(bytes([0x9F, 0, 0, 0]))  # JEDEC ID cmd=0x9F
        flash.deselect()
        board.bus_devices['SPI1'] = [flash]

        result = check_spi_transactions(board, {
            'bus': 'SPI1', 'min_count': 1, 'contains_mosi': '9F'})
        assert result.passed

    def test_fail_contains_mosi(self):
        board = FakeBoard()
        flash = W25QxxFlash(model='W25Q128')
        flash.select()
        flash.transfer(bytes([0x05, 0]))  # Read SR1
        flash.deselect()
        board.bus_devices['SPI1'] = [flash]

        result = check_spi_transactions(board, {
            'bus': 'SPI1', 'min_count': 1, 'contains_mosi': '9F'})
        assert not result.passed

    def test_empty_bus(self):
        board = FakeBoard()
        result = check_spi_transactions(board, {'bus': 'SPI1', 'min_count': 1})
        assert not result.passed

    def test_wrong_bus_name(self):
        board = FakeBoard()
        flash = W25QxxFlash(model='W25Q128')
        flash.select()
        flash.transfer(bytes([0x9F, 0, 0, 0]))
        flash.deselect()
        board.bus_devices['SPI2'] = [flash]

        result = check_spi_transactions(board, {'bus': 'SPI1', 'min_count': 1})
        assert not result.passed


# =============================================================================
# I2C Transaction Assertions
# =============================================================================

class TestI2CTransactions:

    def test_pass_min_count(self):
        board = FakeBoard()
        eeprom = EEPROM_24Cxx(model='24C256', address=0x50)
        eeprom.i2c_start(0xA0, False)
        eeprom.i2c_write(bytes([0x00, 0x00, 0xDE, 0xAD]))
        eeprom._write_address = 0
        eeprom.i2c_start(0xA1, True)
        eeprom.i2c_read(2)
        board.bus_devices['I2C1'] = [eeprom]

        result = check_i2c_transactions(board, {'bus': 'I2C1', 'min_count': 2})
        assert result.passed

    def test_fail_min_count(self):
        board = FakeBoard()
        eeprom = EEPROM_24Cxx(model='24C256', address=0x50)
        eeprom.i2c_write(bytes([0x00, 0x00, 0xDE]))
        board.bus_devices['I2C1'] = [eeprom]

        result = check_i2c_transactions(board, {'bus': 'I2C1', 'min_count': 5})
        assert not result.passed

    def test_filter_by_address(self):
        board = FakeBoard()
        eeprom = EEPROM_24Cxx(model='24C256', address=0x50)
        eeprom.i2c_write(bytes([0x00, 0x00, 0xAA]))
        board.bus_devices['I2C1'] = [eeprom]

        # Filter by correct address
        result = check_i2c_transactions(board, {
            'bus': 'I2C1', 'min_count': 1, 'address': 0x50})
        assert result.passed

        # Filter by wrong address
        result = check_i2c_transactions(board, {
            'bus': 'I2C1', 'min_count': 1, 'address': 0x68})
        assert not result.passed

    def test_contains_data(self):
        board = FakeBoard()
        eeprom = EEPROM_24Cxx(model='24C256', address=0x50)
        eeprom.i2c_write(bytes([0x00, 0x42, 0xBE, 0xEF]))
        board.bus_devices['I2C1'] = [eeprom]

        result = check_i2c_transactions(board, {
            'bus': 'I2C1', 'min_count': 1, 'contains_data': '00 42'})
        assert result.passed

        result = check_i2c_transactions(board, {
            'bus': 'I2C1', 'min_count': 1, 'contains_data': 'FF FF'})
        assert not result.passed


# =============================================================================
# UART Contains Assertions
# =============================================================================

class TestUARTContains:

    def test_pass_text(self):
        board = FakeBoard()
        board.uart_output = bytearray(b'Hello World!\r\n')
        result = check_uart_contains(board, {'text': 'Hello'})
        assert result.passed

    def test_fail_text(self):
        board = FakeBoard()
        board.uart_output = bytearray(b'Goodbye World!\r\n')
        result = check_uart_contains(board, {'text': 'Hello'})
        assert not result.passed

    def test_pass_regex(self):
        board = FakeBoard()
        board.uart_output = bytearray(b'Temperature: 25.3C\r\n')
        result = check_uart_contains(board, {'regex': r'Temperature: \d+\.\d+C'})
        assert result.passed

    def test_fail_regex(self):
        board = FakeBoard()
        board.uart_output = bytearray(b'Temperature: unknown\r\n')
        result = check_uart_contains(board, {'regex': r'Temperature: \d+\.\d+C'})
        assert not result.passed

    def test_empty_output(self):
        board = FakeBoard()
        result = check_uart_contains(board, {'text': 'Hello'})
        assert not result.passed

    def test_no_params(self):
        board = FakeBoard()
        result = check_uart_contains(board, {})
        assert not result.passed
        assert 'no' in result.detail

    def test_binary_safe(self):
        board = FakeBoard()
        board.uart_output = bytearray(b'\x00\x01Hello\xff\xfe')
        result = check_uart_contains(board, {'text': 'Hello'})
        assert result.passed


# =============================================================================
# USB SETUP Assertions
# =============================================================================

class TestUSBSetup:

    def _make_device_descriptor(self, vid=0x0483, pid=0x5740):
        """Build a minimal 18-byte USB device descriptor."""
        import struct
        return struct.pack('<BBHBBBBHHHBBBB',
            18,     # bLength
            0x01,   # bDescriptorType = DEVICE
            0x0200, # bcdUSB
            0x02,   # bDeviceClass = CDC
            0x02,   # bDeviceSubClass
            0x00,   # bDeviceProtocol
            64,     # bMaxPacketSize0
            vid,    # idVendor
            pid,    # idProduct
            0x0200, # bcdDevice
            1,      # iManufacturer
            2,      # iProduct
            3,      # iSerialNumber
            1,      # bNumConfigurations
        )

    def test_pass_min_count(self):
        board = FakeBoard()
        board.usb_transactions = [
            {'endpoint': 0, 'direction': 0, 'setup': b'\x80\x06\x00\x01\x00\x00\x12\x00',
             'data': b'\x80\x06\x00\x01\x00\x00\x12\x00', 'timestamp': time.time()},
        ]
        result = check_usb_setup(board, {'min_count': 1})
        assert result.passed

    def test_fail_min_count(self):
        board = FakeBoard()
        board.usb_transactions = []
        result = check_usb_setup(board, {'min_count': 1})
        assert not result.passed

    def test_pass_vid_pid(self):
        board = FakeBoard()
        desc = self._make_device_descriptor(vid=0x0483, pid=0x5740)
        board.usb_transactions = [
            {'endpoint': 0, 'direction': 0, 'setup': b'\x80\x06\x00\x01\x00\x00\x12\x00',
             'data': b'\x80\x06\x00\x01\x00\x00\x12\x00', 'timestamp': time.time()},
            {'endpoint': 0, 'direction': 1, 'data': desc, 'timestamp': time.time()},
        ]
        result = check_usb_setup(board, {
            'min_count': 1, 'vid': 0x0483, 'pid': 0x5740})
        assert result.passed

    def test_fail_vid_pid(self):
        board = FakeBoard()
        desc = self._make_device_descriptor(vid=0x0483, pid=0x5740)
        board.usb_transactions = [
            {'endpoint': 0, 'direction': 0, 'setup': b'\x80\x06\x00\x01\x00\x00\x12\x00',
             'data': b'\x80\x06\x00\x01\x00\x00\x12\x00', 'timestamp': time.time()},
            {'endpoint': 0, 'direction': 1, 'data': desc, 'timestamp': time.time()},
        ]
        result = check_usb_setup(board, {
            'min_count': 1, 'vid': 0x2E8A, 'pid': 0x0003})
        assert not result.passed

    def test_usb_from_peripheral(self):
        """Test fallback to peripheral.usb_transactions when board has none."""
        board = FakeBoard()

        class FakeUSBPeripheral:
            usb_transactions = [
                {'endpoint': 0, 'direction': 0,
                 'setup': b'\x80\x06\x00\x01\x00\x00\x12\x00',
                 'data': b'\x80\x06\x00\x01\x00\x00\x12\x00',
                 'timestamp': time.time()},
            ]

        board.adapter.peripherals = [FakeUSBPeripheral()]
        result = check_usb_setup(board, {'min_count': 1})
        assert result.passed
