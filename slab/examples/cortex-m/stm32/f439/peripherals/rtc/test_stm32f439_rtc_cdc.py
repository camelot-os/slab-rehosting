#!/usr/bin/env python3
"""
STM32F439 DS3231 RTC CDC Test Harness

Tests DS3231 I2C Real-Time Clock with STM32F439:
- Time read/write operations
- Temperature sensor read
- Status register access

This validates:
1. STM32 I2C peripheral (Python emulation)
2. DS3231 RTC virtual component
3. BCD time encoding/decoding

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet
from virtual_components import DS3231_RTC


class I2CRTCBridge:
    """
    Bridge between STM32 I2C callbacks and DS3231 RTC.

    Handles the I2C protocol:
    - START with address (write or read)
    - DATA bytes
    - STOP
    """

    def __init__(self, rtc: DS3231_RTC, i2c):
        self.rtc = rtc
        self.i2c = i2c
        self.is_read = False
        self.write_buffer = bytearray()
        self.current_reg = 0

        # Connect callbacks
        i2c.on_start = self.on_start
        i2c.on_write = self.on_write
        i2c.on_read = self.on_read
        i2c.on_stop = self.on_stop

    def on_start(self, addr: int, is_read: bool):
        """Handle START condition with address."""
        if addr == self.rtc.address:
            self.is_read = is_read
            if not is_read:
                # Write mode: reset buffer for new transaction
                self.write_buffer = bytearray()

    def on_write(self, data: int):
        """Handle write byte."""
        self.write_buffer.append(data)

        # First byte is register address
        if len(self.write_buffer) == 1:
            self.current_reg = data

    def on_read(self) -> int:
        """Handle read byte."""
        # Read from current register and auto-increment
        data = self.rtc.read_register(self.current_reg)
        self.current_reg = (self.current_reg + 1) % 19  # Wrap at register 0x12 (19 registers)
        return data

    def on_stop(self):
        """Handle STOP condition."""
        if not self.is_read and len(self.write_buffer) > 1:
            # Write data to RTC registers (first byte was address)
            reg = self.write_buffer[0]
            for i, byte in enumerate(self.write_buffer[1:]):
                self.rtc.write_register(reg + i, byte)


class CDCInterface:
    """Simulates CDC-ACM interface for RTC command processing."""

    def __init__(self, i2c, rtc: DS3231_RTC, bridge: I2CRTCBridge):
        self.i2c = i2c
        self.rtc = rtc
        self.bridge = bridge

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "PROBE":
            return self._cmd_probe()

        elif command == "TIME":
            return self._cmd_time()

        elif command == "SETTIME":
            return self._cmd_settime(args)

        elif command == "TEMP":
            return self._cmd_temp()

        elif command == "STATUS":
            return self._cmd_status()

        return "ERROR: Unknown command"

    def _i2c_write_read(self, addr: int, write_data: bytes, read_len: int) -> bytes:
        """Perform I2C write-then-read transaction."""
        # Write phase
        self.bridge.on_start(addr, False)
        for b in write_data:
            self.bridge.on_write(b)

        # Read phase (repeated start)
        self.bridge.on_start(addr, True)
        data = []
        for _ in range(read_len):
            data.append(self.bridge.on_read())
        self.bridge.on_stop()

        return bytes(data)

    def _i2c_write(self, addr: int, data: bytes) -> bool:
        """Perform I2C write transaction."""
        self.bridge.on_start(addr, False)
        for b in data:
            self.bridge.on_write(b)
        self.bridge.on_stop()
        return True

    def _cmd_probe(self) -> str:
        """Check if RTC responds."""
        data = self._i2c_write_read(self.rtc.address, bytes([0x00]), 1)
        return "OK"

    def _cmd_time(self) -> str:
        """Read current time."""
        # Read 7 registers starting from 0x00
        data = self._i2c_write_read(self.rtc.address, bytes([0x00]), 7)

        # Format: YYMMDD HHMMSS (BCD as hex)
        year = data[6]
        month = data[5] & 0x1F
        date = data[4]
        hours = data[2] & 0x3F
        minutes = data[1]
        seconds = data[0]

        return f"{year:02x}{month:02x}{date:02x} {hours:02x}{minutes:02x}{seconds:02x}"

    def _cmd_settime(self, args: str) -> str:
        """Set time (YYMMDDHHMMSS hex)."""
        args = args.strip()
        if len(args) < 12:
            return "ERROR: Need YYMMDDHHMMSS"

        try:
            time_bytes = bytes.fromhex(args[:12])
        except ValueError:
            return "ERROR: Invalid hex"

        # Order: seconds, minutes, hours, day, date, month, year
        regs = bytes([
            0x00,  # Start register
            time_bytes[5],  # Seconds
            time_bytes[4],  # Minutes
            time_bytes[3],  # Hours
            0x01,           # Day of week
            time_bytes[2],  # Date
            time_bytes[1],  # Month
            time_bytes[0],  # Year
        ])

        self._i2c_write(self.rtc.address, regs)
        return "OK"

    def _cmd_temp(self) -> str:
        """Read temperature."""
        data = self._i2c_write_read(self.rtc.address, bytes([0x11]), 2)
        return f"{data[0]:02x}{data[1]:02x}"

    def _cmd_status(self) -> str:
        """Read status register."""
        data = self._i2c_write_read(self.rtc.address, bytes([0x0F]), 1)
        return f"{data[0]:02x}"


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


def test_probe(cdc):
    """Test PROBE command."""
    print("\n=== Test: PROBE ===")
    response = cdc.send_command("PROBE")
    if response == "OK":
        print("  PASS: RTC detected")
        return True
    else:
        print(f"  FAIL: RTC not found: {response}")
        return False


def test_set_and_read_time(cdc, rtc):
    """Test setting and reading time."""
    print("\n=== Test: Set/Read Time ===")

    # Set time to 2025-06-15 14:30:45 (in BCD: 25 06 15 14 30 45)
    set_time = "250615143045"
    response = cdc.send_command(f"SETTIME {set_time}")
    if response != "OK":
        print(f"  FAIL: SETTIME failed: {response}")
        return False
    print(f"  Set time: {set_time}")

    # Read time back
    response = cdc.send_command("TIME")
    # Expected: "250615 143045"
    expected = "250615 143045"
    if response == expected:
        print(f"  PASS: Time read back correctly: {response}")
        return True
    else:
        print(f"  FAIL: Time mismatch")
        print(f"    Expected: {expected}")
        print(f"    Got: {response}")
        return False


def test_temperature(cdc, rtc):
    """Test temperature reading."""
    print("\n=== Test: Temperature ===")

    # Set a known temperature (25.25°C)
    rtc.set_temperature(25.25)

    response = cdc.send_command("TEMP")

    # Temperature format: MSB (signed integer) + LSB (upper 2 bits = fractional)
    # 25.25°C = 25 integer + 0.25 fraction
    # MSB = 0x19 (25 decimal), LSB = 0x40 (0.25 = 01 in upper 2 bits)
    expected = "1940"
    if response == expected:
        print(f"  PASS: Temperature = {response} (25.25°C)")
        return True
    else:
        print(f"  FAIL: Temperature mismatch")
        print(f"    Expected: {expected}")
        print(f"    Got: {response}")
        return False


def test_status(cdc, rtc):
    """Test status register read."""
    print("\n=== Test: Status Register ===")

    response = cdc.send_command("STATUS")

    # After reset, OSF bit (bit 7) may be set -> 0x08 or similar
    # We just verify we get a valid hex response
    if len(response) == 2:
        try:
            int(response, 16)
            print(f"  PASS: Status = 0x{response}")
            return True
        except ValueError:
            pass

    print(f"  FAIL: Invalid status response: {response}")
    return False


def test_time_persistence(cdc, rtc):
    """Test that time values persist correctly."""
    print("\n=== Test: Time Persistence ===")

    # Set different times and verify they're stored correctly
    test_times = [
        ("251231235959", "251231 235959"),  # End of year
        ("250101000000", "250101 000000"),  # Start of year
        ("251206121500", "251206 121500"),  # Random time
    ]

    for set_val, expected in test_times:
        response = cdc.send_command(f"SETTIME {set_val}")
        if response != "OK":
            print(f"  FAIL: SETTIME {set_val} failed")
            return False

        response = cdc.send_command("TIME")
        if response != expected:
            print(f"  FAIL: Time mismatch for {set_val}")
            print(f"    Expected: {expected}")
            print(f"    Got: {response}")
            return False

    print(f"  PASS: All time values persisted correctly")
    return True


def main():
    print("=" * 60)
    print("STM32F439 DS3231 RTC CDC Test")
    print("=" * 60)

    # Create STM32F439 peripheral set
    print("\nInitializing STM32F439 peripheral set...")
    stm32 = STM32F439PeripheralSet()
    print(f"  Device: STM32F439")
    print(f"  I2C1 base: 0x{stm32.i2c1.base:08X}")

    # Create DS3231 RTC
    print("\nCreating DS3231 RTC...")
    rtc = DS3231_RTC(address=0x68)
    rtc._use_system_time = False  # Don't sync to system time for testing
    print(f"  Address: 0x{rtc.address:02X}")

    # Create I2C-RTC bridge
    bridge = I2CRTCBridge(rtc, stm32.i2c1)

    # Create CDC interface
    cdc = CDCInterface(stm32.i2c1, rtc, bridge)

    # Run tests
    results = []

    results.append(("PING", test_ping(cdc)))
    results.append(("PROBE", test_probe(cdc)))
    results.append(("Set/Read Time", test_set_and_read_time(cdc, rtc)))
    results.append(("Temperature", test_temperature(cdc, rtc)))
    results.append(("Status Register", test_status(cdc, rtc)))
    results.append(("Time Persistence", test_time_persistence(cdc, rtc)))

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
