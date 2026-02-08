#!/usr/bin/env python3
"""
Dual MCU SPI Communication Test for MCUemu

Test Scenario: IoT Gateway with Sensor Co-processor
====================================================

Architecture:
    [STM32F4 - Main Controller]  <---SPI--->  [nRF52840 - Sensor Hub]
           (SPI Master)                            (SPI Slave)

The STM32F4 acts as the main application processor running the IoT gateway.
The nRF52840 acts as a sensor co-processor that:
- Collects data from sensors (temperature, humidity, battery)
- Manages BLE communication (simulated)
- Responds to commands from the main controller

Protocol:
=========
Master sends command byte, slave responds with data.

Commands (Master -> Slave):
    0x01: GET_STATUS       - Returns status byte
    0x02: GET_TEMPERATURE  - Returns temperature (2 bytes, little-endian, 0.1°C)
    0x03: GET_HUMIDITY     - Returns humidity (1 byte, %)
    0x04: GET_BATTERY      - Returns battery level (1 byte, %)
    0x05: SET_LED          - Set LED state (next byte: 0=off, 1=on)
    0x06: GET_DEVICE_ID    - Returns 4-byte device ID
    0x10: ECHO             - Echo next byte back

Response format:
    First byte after command: ACK (0xAA) or NACK (0x55)
    Following bytes: data (depends on command)

Usage:
    python3 test_dual_mcu_spi.py

Author: Twisted Wires Security Lab
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import sys
import os
from dataclasses import dataclass
from typing import List, Tuple
from enum import IntEnum

# Add parent directory for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from spi_bridge import (
    SPIBridge, SPIMasterPeripheral, SPISlavePeripheral, STM32_SPI
)


# =============================================================================
# PROTOCOL DEFINITIONS
# =============================================================================

class SensorCommand(IntEnum):
    """Commands from master to slave."""
    GET_STATUS = 0x01
    GET_TEMPERATURE = 0x02
    GET_HUMIDITY = 0x03
    GET_BATTERY = 0x04
    SET_LED = 0x05
    GET_DEVICE_ID = 0x06
    ECHO = 0x10
    INVALID = 0xFF


class SensorStatus(IntEnum):
    """Status flags for sensor hub."""
    READY = 0x01
    BLE_CONNECTED = 0x02
    SENSORS_OK = 0x04
    LOW_BATTERY = 0x08
    LED_ON = 0x10


ACK = 0xAA
NACK = 0x55


# =============================================================================
# SENSOR HUB FIRMWARE SIMULATION (nRF52840 - Slave)
# =============================================================================

class SensorHubFirmware:
    """
    Simulated firmware for the nRF52840 sensor hub.

    This represents the slave MCU's behavior - processing commands
    from the master and providing sensor data responses.
    """

    def __init__(self):
        # Sensor data (simulated)
        self.temperature = 235  # 23.5°C in 0.1°C units
        self.humidity = 65      # 65%
        self.battery = 87       # 87%
        self.device_id = [0x12, 0x34, 0x56, 0x78]

        # State
        self.led_state = False
        self.status = SensorStatus.READY | SensorStatus.SENSORS_OK

        # Protocol state machine
        self.state = 'IDLE'
        self.current_cmd = 0
        self.response_queue: List[int] = []
        self.bytes_to_receive = 0
        self.received_data: List[int] = []

    def process_byte(self, rx_byte: int) -> int:
        """
        Process a byte received from master and return response.

        This implements the slave's protocol state machine.
        """
        if self.state == 'IDLE':
            # Expecting command byte
            return self._handle_command(rx_byte)

        elif self.state == 'RECEIVING':
            # Receiving additional data for command
            self.received_data.append(rx_byte)
            self.bytes_to_receive -= 1

            if self.bytes_to_receive == 0:
                # All data received, execute command
                self._execute_command()
                self.state = 'RESPONDING'

            return self._get_response()

        elif self.state == 'RESPONDING':
            # Sending response bytes
            return self._get_response()

        return 0x00

    def _handle_command(self, cmd: int) -> int:
        """Handle incoming command byte."""
        self.current_cmd = cmd
        self.received_data = []

        if cmd == SensorCommand.GET_STATUS:
            self.response_queue = [ACK, self.status]
            self.state = 'RESPONDING'

        elif cmd == SensorCommand.GET_TEMPERATURE:
            temp_lo = self.temperature & 0xFF
            temp_hi = (self.temperature >> 8) & 0xFF
            self.response_queue = [ACK, temp_lo, temp_hi]
            self.state = 'RESPONDING'

        elif cmd == SensorCommand.GET_HUMIDITY:
            self.response_queue = [ACK, self.humidity]
            self.state = 'RESPONDING'

        elif cmd == SensorCommand.GET_BATTERY:
            self.response_queue = [ACK, self.battery]
            self.state = 'RESPONDING'

        elif cmd == SensorCommand.SET_LED:
            # Need 1 more byte for LED state
            self.bytes_to_receive = 1
            self.state = 'RECEIVING'
            self.response_queue = []

        elif cmd == SensorCommand.GET_DEVICE_ID:
            self.response_queue = [ACK] + self.device_id
            self.state = 'RESPONDING'

        elif cmd == SensorCommand.ECHO:
            # Need 1 byte to echo back
            self.bytes_to_receive = 1
            self.state = 'RECEIVING'
            self.response_queue = []

        else:
            # Unknown command
            self.response_queue = [NACK]
            self.state = 'RESPONDING'

        return self._get_response()

    def _execute_command(self):
        """Execute command after receiving all data."""
        if self.current_cmd == SensorCommand.SET_LED:
            self.led_state = self.received_data[0] != 0
            if self.led_state:
                self.status |= SensorStatus.LED_ON
            else:
                self.status &= ~SensorStatus.LED_ON
            self.response_queue = [ACK]

        elif self.current_cmd == SensorCommand.ECHO:
            self.response_queue = [ACK, self.received_data[0]]

    def _get_response(self) -> int:
        """Get next response byte."""
        if self.response_queue:
            response = self.response_queue.pop(0)
            if not self.response_queue:
                self.state = 'IDLE'
            return response
        return 0x00


# =============================================================================
# MAIN CONTROLLER FIRMWARE SIMULATION (STM32F4 - Master)
# =============================================================================

class MainControllerFirmware:
    """
    Simulated firmware for the STM32F4 main controller.

    This represents the master MCU's behavior - sending commands
    to the sensor hub and processing responses.
    """

    def __init__(self, spi: SPIMasterPeripheral):
        self.spi = spi

    def spi_transfer(self, tx_byte: int) -> int:
        """Perform single-byte SPI transfer."""
        # Enable SPI if not already
        if not (self.spi.cr1 & STM32_SPI.CR1_SPE):
            self.spi.write(STM32_SPI.CR1, 4, STM32_SPI.CR1_SPE | STM32_SPI.CR1_MSTR)

        # Write to DR (triggers transfer via bridge)
        self.spi.write(STM32_SPI.DR, 4, tx_byte)

        # Wait for RXNE (simulated - immediate in our case)
        while not (self.spi.sr & STM32_SPI.SR_RXNE):
            pass

        # Read response
        return self.spi.read(STM32_SPI.DR, 4)

    def spi_transfer_multi(self, tx_bytes: List[int]) -> List[int]:
        """Perform multi-byte SPI transfer."""
        return [self.spi_transfer(b) for b in tx_bytes]

    def get_status(self) -> Tuple[bool, int]:
        """Get sensor hub status."""
        # Send command
        self.spi_transfer(SensorCommand.GET_STATUS)
        # Get ACK
        ack = self.spi_transfer(0x00)
        if ack != ACK:
            return (False, 0)
        # Get status
        status = self.spi_transfer(0x00)
        return (True, status)

    def get_temperature(self) -> Tuple[bool, float]:
        """Get temperature in Celsius."""
        self.spi_transfer(SensorCommand.GET_TEMPERATURE)
        ack = self.spi_transfer(0x00)
        if ack != ACK:
            return (False, 0.0)
        temp_lo = self.spi_transfer(0x00)
        temp_hi = self.spi_transfer(0x00)
        temp_raw = temp_lo | (temp_hi << 8)
        return (True, temp_raw / 10.0)

    def get_humidity(self) -> Tuple[bool, int]:
        """Get humidity percentage."""
        self.spi_transfer(SensorCommand.GET_HUMIDITY)
        ack = self.spi_transfer(0x00)
        if ack != ACK:
            return (False, 0)
        humidity = self.spi_transfer(0x00)
        return (True, humidity)

    def get_battery(self) -> Tuple[bool, int]:
        """Get battery percentage."""
        self.spi_transfer(SensorCommand.GET_BATTERY)
        ack = self.spi_transfer(0x00)
        if ack != ACK:
            return (False, 0)
        battery = self.spi_transfer(0x00)
        return (True, battery)

    def set_led(self, state: bool) -> bool:
        """Set LED state."""
        self.spi_transfer(SensorCommand.SET_LED)
        self.spi_transfer(0x01 if state else 0x00)
        ack = self.spi_transfer(0x00)
        return ack == ACK

    def get_device_id(self) -> Tuple[bool, List[int]]:
        """Get 4-byte device ID."""
        self.spi_transfer(SensorCommand.GET_DEVICE_ID)
        ack = self.spi_transfer(0x00)
        if ack != ACK:
            return (False, [])
        device_id = [self.spi_transfer(0x00) for _ in range(4)]
        return (True, device_id)

    def echo(self, value: int) -> Tuple[bool, int]:
        """Echo test."""
        self.spi_transfer(SensorCommand.ECHO)
        self.spi_transfer(value)
        ack = self.spi_transfer(0x00)
        if ack != ACK:
            return (False, 0)
        echoed = self.spi_transfer(0x00)
        return (True, echoed)


# =============================================================================
# TEST CASES
# =============================================================================

def create_test_environment():
    """Create the dual-MCU test environment."""
    # Create SPI peripherals
    master_spi = SPIMasterPeripheral("STM32_SPI1", 0x40013000)
    slave_spi = SPISlavePeripheral("NRF_SPIS", 0x40003000)

    # Create bridge
    bridge = SPIBridge()
    bridge.connect(master_spi, slave_spi)

    # Create firmware instances
    sensor_hub = SensorHubFirmware()
    main_controller = MainControllerFirmware(master_spi)

    # Connect slave to sensor hub firmware
    slave_spi.on_receive = sensor_hub.process_byte
    slave_spi.dr_tx = 0x00  # Initial response

    return master_spi, slave_spi, bridge, sensor_hub, main_controller


def test_get_status():
    """Test GET_STATUS command."""
    print("\n=== Test: GET_STATUS ===")

    _, _, bridge, sensor_hub, main_ctrl = create_test_environment()

    success, status = main_ctrl.get_status()
    assert success, "GET_STATUS should succeed"

    print(f"Status: 0x{status:02X}")
    print(f"  READY: {bool(status & SensorStatus.READY)}")
    print(f"  SENSORS_OK: {bool(status & SensorStatus.SENSORS_OK)}")
    print(f"  LED_ON: {bool(status & SensorStatus.LED_ON)}")

    expected = SensorStatus.READY | SensorStatus.SENSORS_OK
    assert status == expected, f"Expected status 0x{expected:02X}, got 0x{status:02X}"

    print(f"Transactions: {len(bridge.transactions)}")
    print("PASS: GET_STATUS")
    return True


def test_get_temperature():
    """Test GET_TEMPERATURE command."""
    print("\n=== Test: GET_TEMPERATURE ===")

    _, _, bridge, sensor_hub, main_ctrl = create_test_environment()

    success, temp = main_ctrl.get_temperature()
    assert success, "GET_TEMPERATURE should succeed"

    print(f"Temperature: {temp}°C")
    assert temp == 23.5, f"Expected 23.5°C, got {temp}°C"

    print("PASS: GET_TEMPERATURE")
    return True


def test_get_humidity():
    """Test GET_HUMIDITY command."""
    print("\n=== Test: GET_HUMIDITY ===")

    _, _, _, sensor_hub, main_ctrl = create_test_environment()

    success, humidity = main_ctrl.get_humidity()
    assert success, "GET_HUMIDITY should succeed"

    print(f"Humidity: {humidity}%")
    assert humidity == 65, f"Expected 65%, got {humidity}%"

    print("PASS: GET_HUMIDITY")
    return True


def test_get_battery():
    """Test GET_BATTERY command."""
    print("\n=== Test: GET_BATTERY ===")

    _, _, _, sensor_hub, main_ctrl = create_test_environment()

    success, battery = main_ctrl.get_battery()
    assert success, "GET_BATTERY should succeed"

    print(f"Battery: {battery}%")
    assert battery == 87, f"Expected 87%, got {battery}%"

    print("PASS: GET_BATTERY")
    return True


def test_set_led():
    """Test SET_LED command."""
    print("\n=== Test: SET_LED ===")

    _, _, _, sensor_hub, main_ctrl = create_test_environment()

    # Turn LED on
    success = main_ctrl.set_led(True)
    assert success, "SET_LED(True) should succeed"
    print("LED turned ON")

    # Verify via status
    success, status = main_ctrl.get_status()
    assert success, "GET_STATUS should succeed"
    assert status & SensorStatus.LED_ON, "LED should be ON in status"
    print(f"Status confirms LED ON: 0x{status:02X}")

    # Turn LED off
    success = main_ctrl.set_led(False)
    assert success, "SET_LED(False) should succeed"
    print("LED turned OFF")

    # Verify via status
    success, status = main_ctrl.get_status()
    assert success, "GET_STATUS should succeed"
    assert not (status & SensorStatus.LED_ON), "LED should be OFF in status"
    print(f"Status confirms LED OFF: 0x{status:02X}")

    print("PASS: SET_LED")
    return True


def test_get_device_id():
    """Test GET_DEVICE_ID command."""
    print("\n=== Test: GET_DEVICE_ID ===")

    _, _, _, sensor_hub, main_ctrl = create_test_environment()

    success, device_id = main_ctrl.get_device_id()
    assert success, "GET_DEVICE_ID should succeed"

    id_str = ':'.join(f'{b:02X}' for b in device_id)
    print(f"Device ID: {id_str}")

    expected_id = [0x12, 0x34, 0x56, 0x78]
    assert device_id == expected_id, f"Expected {expected_id}, got {device_id}"

    print("PASS: GET_DEVICE_ID")
    return True


def test_echo():
    """Test ECHO command."""
    print("\n=== Test: ECHO ===")

    _, _, _, sensor_hub, main_ctrl = create_test_environment()

    test_values = [0x00, 0x55, 0xAA, 0xFF, 0x42]
    for value in test_values:
        success, echoed = main_ctrl.echo(value)
        assert success, f"ECHO(0x{value:02X}) should succeed"
        assert echoed == value, f"Expected 0x{value:02X}, got 0x{echoed:02X}"
        print(f"  Echo 0x{value:02X} -> 0x{echoed:02X} ✓")

    print("PASS: ECHO")
    return True


def test_invalid_command():
    """Test handling of invalid command."""
    print("\n=== Test: Invalid Command ===")

    master_spi, _, bridge, sensor_hub, main_ctrl = create_test_environment()

    # Send invalid command directly
    main_ctrl.spi_transfer(SensorCommand.INVALID)
    response = main_ctrl.spi_transfer(0x00)

    print(f"Invalid command response: 0x{response:02X}")
    assert response == NACK, f"Expected NACK (0x{NACK:02X}), got 0x{response:02X}"

    print("PASS: Invalid Command")
    return True


def test_full_sensor_query_sequence():
    """Test a full sensor query sequence (realistic use case)."""
    print("\n=== Test: Full Sensor Query Sequence ===")
    print("Scenario: IoT gateway querying sensor hub for all data")

    _, _, bridge, sensor_hub, main_ctrl = create_test_environment()

    # Simulate typical IoT gateway behavior
    print("\n1. Query sensor hub status...")
    success, status = main_ctrl.get_status()
    assert success
    print(f"   Status: 0x{status:02X} (Ready: {bool(status & SensorStatus.READY)})")

    print("\n2. Read all sensor values...")
    success, temp = main_ctrl.get_temperature()
    assert success
    print(f"   Temperature: {temp}°C")

    success, humidity = main_ctrl.get_humidity()
    assert success
    print(f"   Humidity: {humidity}%")

    success, battery = main_ctrl.get_battery()
    assert success
    print(f"   Battery: {battery}%")

    print("\n3. Get device identification...")
    success, device_id = main_ctrl.get_device_id()
    assert success
    print(f"   Device ID: {':'.join(f'{b:02X}' for b in device_id)}")

    print("\n4. Toggle activity LED...")
    success = main_ctrl.set_led(True)
    assert success
    print("   LED ON")

    # Simulate some work
    print("   ... processing data ...")

    success = main_ctrl.set_led(False)
    assert success
    print("   LED OFF")

    print("\n5. Verify communication integrity with echo test...")
    for test_val in [0x00, 0xFF]:
        success, echoed = main_ctrl.echo(test_val)
        assert success and echoed == test_val
    print("   Echo test passed")

    # Summary
    print(f"\n=== Communication Summary ===")
    print(f"Total SPI transactions: {len(bridge.transactions)}")

    # Count bytes transferred
    total_mosi = sum(t.master_tx for t in bridge.transactions)
    total_miso = sum(t.slave_tx for t in bridge.transactions)
    print(f"Total bytes MOSI: {len(bridge.transactions)}")
    print(f"Total bytes MISO: {len(bridge.transactions)}")

    print("\nPASS: Full Sensor Query Sequence")
    return True


def test_transaction_log():
    """Test that transaction logging works correctly."""
    print("\n=== Test: Transaction Logging ===")

    _, _, bridge, sensor_hub, main_ctrl = create_test_environment()

    # Clear any existing transactions
    bridge.clear_log()
    assert len(bridge.transactions) == 0

    # Do a simple echo
    main_ctrl.echo(0x42)

    # Check transaction log
    print(f"Transactions recorded: {len(bridge.transactions)}")
    for i, txn in enumerate(bridge.transactions):
        print(f"  [{i}] MOSI: 0x{txn.master_tx:02X} -> MISO: 0x{txn.slave_tx:02X}")

    # ECHO command: CMD, VALUE, dummy for ACK, dummy for echo
    assert len(bridge.transactions) == 4, f"Expected 4 transactions, got {len(bridge.transactions)}"

    print("PASS: Transaction Logging")
    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all dual-MCU SPI tests."""
    print("=" * 70)
    print("MCUemu Dual-MCU SPI Communication Test")
    print("=" * 70)
    print("\nTest Scenario: IoT Gateway with Sensor Co-processor")
    print("  MCU1 (STM32F4): Main Controller, SPI Master")
    print("  MCU2 (nRF52840): Sensor Hub, SPI Slave")
    print("=" * 70)

    tests = [
        test_get_status,
        test_get_temperature,
        test_get_humidity,
        test_get_battery,
        test_set_led,
        test_get_device_id,
        test_echo,
        test_invalid_command,
        test_transaction_log,
        test_full_sensor_query_sequence,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except AssertionError as e:
            print(f"FAIL: {e}")
            results.append(False)
        except Exception as e:
            print(f"ERROR: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    # Summary
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("All Dual-MCU SPI tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
