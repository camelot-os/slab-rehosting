#!/usr/bin/env python3
"""
SPI LCD CDC Test Harness

Tests the ILI9341 LCD firmware by simulating register-level access and
connecting a virtual ILI9341 display to the STM32 SPI peripheral.

This demonstrates end-to-end peripheral testing:
1. STM32 SPI peripheral (Python emulation)
2. ILI9341 LCD virtual component
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
from virtual_components import ILI9341_LCD


# RGB565 color macros
def RGB565(r, g, b):
    """Create RGB565 color from 5-bit R, 6-bit G, 5-bit B."""
    return ((r & 0x1F) << 11) | ((g & 0x3F) << 5) | (b & 0x1F)


RGB565_RED = RGB565(31, 0, 0)
RGB565_GREEN = RGB565(0, 63, 0)
RGB565_BLUE = RGB565(0, 0, 31)
RGB565_WHITE = RGB565(31, 63, 31)
RGB565_BLACK = 0x0000


class SPILCDBridge:
    """
    Bridge between STM32 SPI (byte-level) and ILI9341 LCD.

    Handles:
    - CS control
    - D/C (Data/Command) mode
    - Byte accumulation for commands and data
    - Command parameter handling (for COLUMN_ADDR, PAGE_ADDR, etc.)
    """

    # Commands that expect parameter data (not pixel data)
    PARAM_COMMANDS = {
        0x2A: 4,  # COLUMN_ADDR: 4 bytes
        0x2B: 4,  # PAGE_ADDR: 4 bytes
        0x36: 1,  # MADCTL: 1 byte
        0x3A: 1,  # PIXEL_FORMAT: 1 byte
    }

    def __init__(self, lcd: ILI9341_LCD):
        self.lcd = lcd
        self.cs_low = False
        self.dc_high = False  # False = Command, True = Data
        self.mosi_buffer = bytearray()
        self._byte_index = 0
        self._current_cmd = 0
        self._expected_params = 0
        self._param_buffer = bytearray()

    def set_cs(self, low: bool):
        """Handle CS signal change."""
        if low and not self.cs_low:
            # CS going low: start transaction
            self.mosi_buffer = bytearray()
            self._byte_index = 0
            self.lcd.select()
        elif not low and self.cs_low:
            # CS going high: process accumulated data
            if self.mosi_buffer:
                if not self.dc_high:
                    # Command mode - first byte is command
                    if len(self.mosi_buffer) > 0:
                        cmd = self.mosi_buffer[0]
                        self._current_cmd = cmd
                        # Check if this command expects parameters
                        if cmd in self.PARAM_COMMANDS:
                            self._expected_params = self.PARAM_COMMANDS[cmd]
                            self._param_buffer = bytearray()
                        else:
                            self._expected_params = 0
                        # Process command (with any inline data if present)
                        data = bytes(self.mosi_buffer[1:])
                        self.lcd.write_command(cmd, data)
                else:
                    # Data mode
                    if self._expected_params > 0:
                        # Command expecting parameters - collect them
                        self._param_buffer.extend(self.mosi_buffer)
                        if len(self._param_buffer) >= self._expected_params:
                            # We have all params, update the command
                            self._apply_command_params()
                    else:
                        # Pixel data for memory write
                        if self._current_cmd == 0x2C:  # Memory Write
                            self.lcd.write_data(bytes(self.mosi_buffer))
            self.lcd.deselect()
        self.cs_low = low

    def _apply_command_params(self):
        """Apply collected parameters to the current command."""
        cmd = self._current_cmd
        data = bytes(self._param_buffer[:self._expected_params])

        if cmd == 0x2A and len(data) >= 4:  # COLUMN_ADDR
            self.lcd._col_start = (data[0] << 8) | data[1]
            self.lcd._col_end = (data[2] << 8) | data[3]
        elif cmd == 0x2B and len(data) >= 4:  # PAGE_ADDR
            self.lcd._page_start = (data[0] << 8) | data[1]
            self.lcd._page_end = (data[2] << 8) | data[3]
        elif cmd == 0x36 and len(data) >= 1:  # MADCTL
            self.lcd._madctl = data[0]
        elif cmd == 0x3A and len(data) >= 1:  # PIXEL_FORMAT
            self.lcd._pixel_format = data[0]

        self._expected_params = 0
        self._param_buffer = bytearray()

    def set_dc(self, high: bool):
        """Handle D/C signal change."""
        if high != self.dc_high:
            self.dc_high = high
            if high:
                self.lcd.set_data_mode()
            else:
                self.lcd.set_command_mode()

    def transfer_byte(self, tx: int) -> int:
        """Transfer single byte via SPI."""
        if not self.cs_low:
            return 0xFF

        self.mosi_buffer.append(tx)
        return 0xFF


class CDCInterface:
    """Simulates CDC-ACM interface for LCD command processing."""

    def __init__(self, spi, lcd: ILI9341_LCD, bridge: SPILCDBridge):
        self.spi = spi
        self.lcd = lcd
        self.bridge = bridge

    def send_command(self, cmd: str) -> str:
        """Send a command and get response."""
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if command == "PING":
            return "PONG"

        elif command == "INIT":
            return self._cmd_init()

        elif command == "CLEAR":
            return self._cmd_clear(args)

        elif command == "FILL":
            return self._cmd_fill(args)

        elif command == "PIXEL":
            return self._cmd_pixel(args)

        elif command == "HLINE":
            return self._cmd_hline(args)

        elif command == "VLINE":
            return self._cmd_vline(args)

        elif command == "PATTERN":
            return self._cmd_pattern()

        return "ERROR: Unknown command"

    def _spi_cmd(self, cmd: int):
        """Send LCD command."""
        self.bridge.set_dc(False)  # Command mode
        self.bridge.set_cs(True)
        self.bridge.transfer_byte(cmd)
        self.bridge.set_cs(False)

    def _spi_data(self, data: bytes):
        """Send LCD data."""
        self.bridge.set_dc(True)  # Data mode
        self.bridge.set_cs(True)
        for b in data:
            self.bridge.transfer_byte(b)
        self.bridge.set_cs(False)

    def _lcd_set_window(self, x0: int, y0: int, x1: int, y1: int):
        """Set LCD window."""
        # Column address
        self._spi_cmd(0x2A)
        self._spi_data(bytes([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF]))

        # Page address
        self._spi_cmd(0x2B)
        self._spi_data(bytes([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF]))

    def _lcd_fill_rect(self, x: int, y: int, w: int, h: int, color: int):
        """Fill rectangle with color."""
        self._lcd_set_window(x, y, x + w - 1, y + h - 1)
        self._spi_cmd(0x2C)  # Memory write

        hi = (color >> 8) & 0xFF
        lo = color & 0xFF
        pixel_data = bytes([hi, lo]) * (w * h)
        self._spi_data(pixel_data)

    def _cmd_init(self) -> str:
        """Initialize LCD."""
        # Software reset
        self._spi_cmd(0x01)

        # Sleep out
        self._spi_cmd(0x11)

        # Pixel format: RGB565
        self._spi_cmd(0x3A)
        self._spi_data(bytes([0x55]))

        # Display ON
        self._spi_cmd(0x29)

        return "OK"

    def _cmd_clear(self, args: str) -> str:
        """Clear screen with color."""
        color = RGB565_BLACK
        if args:
            try:
                color = int(args[:4], 16)
            except ValueError:
                pass

        self._lcd_fill_rect(0, 0, 240, 320, color)
        return "OK"

    def _cmd_fill(self, args: str) -> str:
        """Fill rectangle."""
        try:
            params = bytes.fromhex(args.replace(' ', ''))
        except ValueError:
            return "ERROR: Invalid hex"

        if len(params) < 10:
            return "ERROR: Need x(2), y(2), w(2), h(2), color(2)"

        x = (params[0] << 8) | params[1]
        y = (params[2] << 8) | params[3]
        w = (params[4] << 8) | params[5]
        h = (params[6] << 8) | params[7]
        color = (params[8] << 8) | params[9]

        if x >= 240 or y >= 320:
            return "ERROR: Out of bounds"

        if x + w > 240:
            w = 240 - x
        if y + h > 320:
            h = 320 - y

        self._lcd_fill_rect(x, y, w, h, color)
        return "OK"

    def _cmd_pixel(self, args: str) -> str:
        """Set single pixel."""
        try:
            params = bytes.fromhex(args.replace(' ', ''))
        except ValueError:
            return "ERROR: Invalid hex"

        if len(params) < 6:
            return "ERROR: Need x(2), y(2), color(2)"

        x = (params[0] << 8) | params[1]
        y = (params[2] << 8) | params[3]
        color = (params[4] << 8) | params[5]

        if x >= 240 or y >= 320:
            return "ERROR: Out of bounds"

        self._lcd_fill_rect(x, y, 1, 1, color)
        return "OK"

    def _cmd_hline(self, args: str) -> str:
        """Draw horizontal line."""
        try:
            params = bytes.fromhex(args.replace(' ', ''))
        except ValueError:
            return "ERROR: Invalid hex"

        if len(params) < 8:
            return "ERROR: Need x(2), y(2), len(2), color(2)"

        x = (params[0] << 8) | params[1]
        y = (params[2] << 8) | params[3]
        length = (params[4] << 8) | params[5]
        color = (params[6] << 8) | params[7]

        if x >= 240 or y >= 320:
            return "ERROR: Out of bounds"

        if x + length > 240:
            length = 240 - x

        self._lcd_fill_rect(x, y, length, 1, color)
        return "OK"

    def _cmd_vline(self, args: str) -> str:
        """Draw vertical line."""
        try:
            params = bytes.fromhex(args.replace(' ', ''))
        except ValueError:
            return "ERROR: Invalid hex"

        if len(params) < 8:
            return "ERROR: Need x(2), y(2), len(2), color(2)"

        x = (params[0] << 8) | params[1]
        y = (params[2] << 8) | params[3]
        length = (params[4] << 8) | params[5]
        color = (params[6] << 8) | params[7]

        if x >= 240 or y >= 320:
            return "ERROR: Out of bounds"

        if y + length > 320:
            length = 320 - y

        self._lcd_fill_rect(x, y, 1, length, color)
        return "OK"

    def _cmd_pattern(self) -> str:
        """Draw test pattern."""
        self._lcd_fill_rect(0, 0, 60, 320, RGB565_RED)
        self._lcd_fill_rect(60, 0, 60, 320, RGB565_GREEN)
        self._lcd_fill_rect(120, 0, 60, 320, RGB565_BLUE)
        self._lcd_fill_rect(180, 0, 60, 320, RGB565_WHITE)
        return "OK"


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


def test_init(cdc, lcd):
    """Test LCD initialization."""
    print("\n=== Test: INIT ===")
    response = cdc.send_command("INIT")
    if response == "OK":
        if lcd._display_on and not lcd._sleep:
            print("  PASS: LCD initialized (display on, awake)")
            return True
        else:
            print(f"  FAIL: Display state incorrect")
            print(f"    display_on={lcd._display_on}, sleep={lcd._sleep}")
            return False
    else:
        print(f"  FAIL: {response}")
        return False


def test_clear(cdc, lcd):
    """Test screen clear."""
    print("\n=== Test: CLEAR ===")

    # Clear to red
    response = cdc.send_command(f"CLEAR {RGB565_RED:04x}")
    if response != "OK":
        print(f"  FAIL: {response}")
        return False

    # Check framebuffer - first pixel should be red
    fb = lcd.get_framebuffer()
    expected_hi = (RGB565_RED >> 8) & 0xFF
    expected_lo = RGB565_RED & 0xFF

    if fb[0] == expected_hi and fb[1] == expected_lo:
        print(f"  PASS: Screen cleared to red (0x{RGB565_RED:04X})")
        return True
    else:
        print(f"  FAIL: Pixel mismatch")
        print(f"    Expected: {expected_hi:02X}{expected_lo:02X}")
        print(f"    Got: {fb[0]:02X}{fb[1]:02X}")
        return False


def test_fill(cdc, lcd):
    """Test fill rectangle."""
    print("\n=== Test: FILL ===")

    # Clear first
    cdc.send_command("CLEAR 0000")

    # Fill 10x10 rectangle at (20, 30) with green
    x, y, w, h = 20, 30, 10, 10
    color = RGB565_GREEN
    args = f"{x:04x}{y:04x}{w:04x}{h:04x}{color:04x}"
    response = cdc.send_command(f"FILL {args}")

    if response != "OK":
        print(f"  FAIL: {response}")
        return False

    # Check pixel at (20, 30)
    pixel = lcd.get_pixel(20, 30)
    if pixel == color:
        print(f"  PASS: Rectangle filled at (20,30) with green")
        return True
    else:
        print(f"  FAIL: Pixel mismatch at (20,30)")
        print(f"    Expected: 0x{color:04X}")
        print(f"    Got: 0x{pixel:04X}")
        return False


def test_pixel(cdc, lcd):
    """Test single pixel."""
    print("\n=== Test: PIXEL ===")

    # Clear first
    cdc.send_command("CLEAR 0000")

    # Set pixel at (100, 150) to blue
    x, y = 100, 150
    color = RGB565_BLUE
    args = f"{x:04x}{y:04x}{color:04x}"
    response = cdc.send_command(f"PIXEL {args}")

    if response != "OK":
        print(f"  FAIL: {response}")
        return False

    # Check pixel
    pixel = lcd.get_pixel(100, 150)
    if pixel == color:
        print(f"  PASS: Pixel set at (100,150) to blue")
        return True
    else:
        print(f"  FAIL: Pixel mismatch")
        print(f"    Expected: 0x{color:04X}")
        print(f"    Got: 0x{pixel:04X}")
        return False


def test_hline(cdc, lcd):
    """Test horizontal line."""
    print("\n=== Test: HLINE ===")

    # Clear first
    cdc.send_command("CLEAR 0000")

    # Draw horizontal line at y=50, from x=10 to x=110, white
    x, y, length = 10, 50, 100
    color = RGB565_WHITE
    args = f"{x:04x}{y:04x}{length:04x}{color:04x}"
    response = cdc.send_command(f"HLINE {args}")

    if response != "OK":
        print(f"  FAIL: {response}")
        return False

    # Check start and end pixels
    start_pixel = lcd.get_pixel(10, 50)
    end_pixel = lcd.get_pixel(109, 50)
    outside_pixel = lcd.get_pixel(110, 50)

    if start_pixel == color and end_pixel == color and outside_pixel == 0:
        print(f"  PASS: Horizontal line drawn from (10,50) to (109,50)")
        return True
    else:
        print(f"  FAIL: Line pixels incorrect")
        print(f"    Start (10,50): 0x{start_pixel:04X} (expected 0x{color:04X})")
        print(f"    End (109,50): 0x{end_pixel:04X} (expected 0x{color:04X})")
        print(f"    Outside (110,50): 0x{outside_pixel:04X} (expected 0x0000)")
        return False


def test_vline(cdc, lcd):
    """Test vertical line."""
    print("\n=== Test: VLINE ===")

    # Clear first
    cdc.send_command("CLEAR 0000")

    # Draw vertical line at x=120, from y=20 to y=120, red
    x, y, length = 120, 20, 100
    color = RGB565_RED
    args = f"{x:04x}{y:04x}{length:04x}{color:04x}"
    response = cdc.send_command(f"VLINE {args}")

    if response != "OK":
        print(f"  FAIL: {response}")
        return False

    # Check start and end pixels
    start_pixel = lcd.get_pixel(120, 20)
    end_pixel = lcd.get_pixel(120, 119)
    outside_pixel = lcd.get_pixel(120, 120)

    if start_pixel == color and end_pixel == color and outside_pixel == 0:
        print(f"  PASS: Vertical line drawn from (120,20) to (120,119)")
        return True
    else:
        print(f"  FAIL: Line pixels incorrect")
        print(f"    Start (120,20): 0x{start_pixel:04X} (expected 0x{color:04X})")
        print(f"    End (120,119): 0x{end_pixel:04X} (expected 0x{color:04X})")
        print(f"    Outside (120,120): 0x{outside_pixel:04X} (expected 0x0000)")
        return False


def test_pattern(cdc, lcd):
    """Test pattern command."""
    print("\n=== Test: PATTERN ===")

    response = cdc.send_command("PATTERN")
    if response != "OK":
        print(f"  FAIL: {response}")
        return False

    # Check colors in each stripe
    red_pixel = lcd.get_pixel(30, 160)  # Center of red stripe
    green_pixel = lcd.get_pixel(90, 160)  # Center of green stripe
    blue_pixel = lcd.get_pixel(150, 160)  # Center of blue stripe
    white_pixel = lcd.get_pixel(210, 160)  # Center of white stripe

    passed = True
    if red_pixel == RGB565_RED:
        print(f"  Red stripe OK (0x{red_pixel:04X})")
    else:
        print(f"  FAIL: Red stripe wrong (0x{red_pixel:04X})")
        passed = False

    if green_pixel == RGB565_GREEN:
        print(f"  Green stripe OK (0x{green_pixel:04X})")
    else:
        print(f"  FAIL: Green stripe wrong (0x{green_pixel:04X})")
        passed = False

    if blue_pixel == RGB565_BLUE:
        print(f"  Blue stripe OK (0x{blue_pixel:04X})")
    else:
        print(f"  FAIL: Blue stripe wrong (0x{blue_pixel:04X})")
        passed = False

    if white_pixel == RGB565_WHITE:
        print(f"  White stripe OK (0x{white_pixel:04X})")
    else:
        print(f"  FAIL: White stripe wrong (0x{white_pixel:04X})")
        passed = False

    if passed:
        print("  PASS: All stripes correct")
    return passed


def main():
    print("=" * 60)
    print("SPI LCD CDC Test (STM32F439 + ILI9341)")
    print("=" * 60)

    # Create STM32F439 peripheral set
    print("\nInitializing STM32F439 peripheral set...")
    stm32 = STM32F439PeripheralSet()
    print(f"  Device: {stm32.device}")
    print(f"  SPI1 base: 0x{stm32.spi1.base:08X}")

    # Create ILI9341 LCD
    print("\nCreating ILI9341 LCD...")
    lcd = ILI9341_LCD(240, 320)
    print(f"  Size: {lcd.width}x{lcd.height}")
    print(f"  Framebuffer: {len(lcd.get_framebuffer())} bytes")

    # Create bridge
    bridge = SPILCDBridge(lcd)

    # Connect SPI to bridge
    stm32.spi1.on_transfer = bridge.transfer_byte

    # Create CDC interface
    cdc = CDCInterface(stm32.spi1, lcd, bridge)

    # Run tests
    results = []

    results.append(("PING", test_ping(cdc)))
    results.append(("INIT", test_init(cdc, lcd)))
    results.append(("CLEAR", test_clear(cdc, lcd)))
    results.append(("FILL", test_fill(cdc, lcd)))
    results.append(("PIXEL", test_pixel(cdc, lcd)))
    results.append(("HLINE", test_hline(cdc, lcd)))
    results.append(("VLINE", test_vline(cdc, lcd)))
    results.append(("PATTERN", test_pattern(cdc, lcd)))

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
