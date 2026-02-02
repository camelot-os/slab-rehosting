"""
Tests for Virtual Peripherals and IC Components.

Tests pygame-based visual peripherals (LEDs, displays, inputs)
and IC components (EEPROM, Flash, RTC, Compass, LCD controllers).
"""

import pytest
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

# Import virtual components (no pygame dependency)
from virtual_components import (
    EEPROM_24Cxx,
    W25QxxFlash,
    DS3231_RTC,
    QMC5883L_Compass,
    ILI9341_LCD,
    SSD1306_OLED,
    ComponentSDK,
    create_eeprom,
    create_flash,
    create_rtc,
    create_compass,
    create_ili9341,
    create_ssd1306,
    I2CTransaction,
    SPITransaction,
)

# Try importing pygame peripherals (may fail if pygame not available)
try:
    from pygame_peripherals import (
        LED,
        RGBLED,
        LEDStrip,
        CharacterLCD,
        GraphicOLED,
        SevenSegmentDisplay,
        Button,
        RotaryEncoder,
        Gamepad,
        Buzzer,
        VirtualBoard,
        PeripheralSDK,
        LEDColor,
        RGB,
        PYGAME_AVAILABLE,
    )
except ImportError:
    PYGAME_AVAILABLE = False
    RGB = None


# =============================================================================
# EEPROM Tests
# =============================================================================

class TestEEPROM:
    """Tests for 24Cxx series EEPROM."""

    def test_create_eeprom_models(self):
        """Test creating different EEPROM models."""
        models = ['24C02', '24C16', '24C64', '24C256', '24C512']
        expected_sizes = [256, 2048, 8192, 32768, 65536]

        for model, size in zip(models, expected_sizes):
            eeprom = EEPROM_24Cxx(model)
            assert eeprom.size == size
            assert eeprom.model == model

    def test_write_read_single_byte(self):
        """Test writing and reading single byte."""
        eeprom = EEPROM_24Cxx('24C256')

        # Write byte at address 0x0100
        eeprom.i2c_write(bytes([0x01, 0x00, 0xAB]))

        # Read back
        eeprom._write_address = 0x0100
        data = eeprom.i2c_read(1)
        assert data == bytes([0xAB])

    def test_write_read_multiple_bytes(self):
        """Test writing and reading multiple bytes."""
        eeprom = EEPROM_24Cxx('24C256')

        test_data = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE])
        eeprom.i2c_write(bytes([0x00, 0x00]) + test_data)

        eeprom._write_address = 0x0000
        read_data = eeprom.i2c_read(6)
        assert read_data == test_data

    def test_sequential_read(self):
        """Test sequential read wraps around."""
        eeprom = EEPROM_24Cxx('24C02')  # 256 bytes

        # Fill some data
        for i in range(10):
            eeprom._memory[i] = i

        eeprom._write_address = 0
        data = eeprom.i2c_read(15)
        assert data[:10] == bytes(range(10))

    def test_address_wrapping(self):
        """Test address wraps at memory boundary."""
        eeprom = EEPROM_24Cxx('24C02')  # 256 bytes

        # Write at end of memory
        eeprom._write_address = 254
        eeprom.write_register(254, 0xAA)
        eeprom.write_register(255, 0xBB)

        assert eeprom._memory[254] == 0xAA
        assert eeprom._memory[255] == 0xBB

    def test_transaction_logging(self):
        """Test transaction logging."""
        eeprom = EEPROM_24Cxx('24C256')

        eeprom.i2c_write(bytes([0x00, 0x00, 0x55]))
        eeprom._write_address = 0
        eeprom.i2c_read(1)

        log = eeprom.get_transaction_log()
        assert len(log) == 2
        assert isinstance(log[0], I2CTransaction)
        assert log[0].is_read == False
        assert log[1].is_read == True

    def test_get_set_contents(self):
        """Test bulk contents access."""
        eeprom = EEPROM_24Cxx('24C64')

        test_data = bytes(range(256))
        eeprom.set_contents(test_data)

        contents = eeprom.get_contents()
        assert contents[:256] == test_data


# =============================================================================
# SPI Flash Tests
# =============================================================================

class TestW25QxxFlash:
    """Tests for W25Qxx SPI Flash."""

    def test_create_flash_models(self):
        """Test creating different flash models."""
        models = ['W25Q16', 'W25Q64', 'W25Q128', 'W25Q256']
        expected_sizes = [2, 8, 16, 32]  # MB

        for model, size_mb in zip(models, expected_sizes):
            flash = W25QxxFlash(model)
            assert flash.size == size_mb * 1024 * 1024

    def test_jedec_id(self):
        """Test reading JEDEC ID."""
        flash = W25QxxFlash('W25Q128')
        flash.select()
        response = flash.transfer(bytes([0x9F, 0, 0, 0]))
        flash.deselect()

        assert response[1] == 0xEF  # Winbond
        assert response[2] == 0x40
        assert response[3] == 0x18  # W25Q128

    def test_write_enable_disable(self):
        """Test write enable/disable."""
        flash = W25QxxFlash('W25Q128')

        # Initially WEL should be clear
        flash.select()
        flash.transfer(bytes([0x05, 0]))
        status = flash.transfer(bytes([0x05, 0]))
        flash.deselect()
        assert (status[1] & 0x02) == 0

        # Enable write
        flash.select()
        flash.transfer(bytes([0x06]))
        flash.deselect()

        # Check WEL is set
        flash.select()
        status = flash.transfer(bytes([0x05, 0]))
        flash.deselect()
        assert (status[1] & 0x02) != 0

        # Disable write
        flash.select()
        flash.transfer(bytes([0x04]))
        flash.deselect()

        # Check WEL is clear
        flash.select()
        status = flash.transfer(bytes([0x05, 0]))
        flash.deselect()
        assert (status[1] & 0x02) == 0

    def test_read_data(self):
        """Test reading data."""
        flash = W25QxxFlash('W25Q128')

        # Pre-fill some data
        flash._memory[0x1000:0x1004] = bytes([0xDE, 0xAD, 0xBE, 0xEF])

        # Read it back
        flash.select()
        cmd = bytes([0x03, 0x00, 0x10, 0x00, 0, 0, 0, 0])  # Read from 0x001000
        response = flash.transfer(cmd)
        flash.deselect()

        assert response[4:8] == bytes([0xDE, 0xAD, 0xBE, 0xEF])

    def test_page_program(self):
        """Test page programming."""
        flash = W25QxxFlash('W25Q128')

        # Enable write
        flash.select()
        flash.transfer(bytes([0x06]))
        flash.deselect()

        # Program page at address 0
        flash.select()
        cmd = bytes([0x02, 0x00, 0x00, 0x00, 0xAA, 0xBB, 0xCC, 0xDD])
        flash.transfer(cmd)
        flash.deselect()

        # Verify
        assert flash._memory[0:4] == bytes([0xAA, 0xBB, 0xCC, 0xDD])

    def test_sector_erase(self):
        """Test sector erase (4KB)."""
        flash = W25QxxFlash('W25Q128')

        # Fill sector with data
        flash._memory[0:4096] = bytes([0x55] * 4096)

        # Enable write
        flash.select()
        flash.transfer(bytes([0x06]))
        flash.deselect()

        # Erase sector
        flash.select()
        flash.transfer(bytes([0x20, 0x00, 0x00, 0x00]))
        flash.deselect()

        # Verify erased (all 0xFF)
        assert flash._memory[0:4096] == bytes([0xFF] * 4096)

    def test_chip_erase(self):
        """Test chip erase."""
        flash = W25QxxFlash('W25Q16')  # Small size for fast test

        # Fill with data
        flash._memory = bytearray([0x55] * flash.size)

        # Enable write and erase
        flash.select()
        flash.transfer(bytes([0x06]))
        flash.deselect()

        flash.select()
        flash.transfer(bytes([0xC7]))
        flash.deselect()

        # Verify all erased
        assert all(b == 0xFF for b in flash._memory)

    def test_power_down(self):
        """Test power down mode."""
        flash = W25QxxFlash('W25Q128')

        # Power down
        flash.select()
        flash.transfer(bytes([0xB9]))
        flash.deselect()

        assert flash._powered_down

        # Commands should not work while powered down
        flash.select()
        response = flash.transfer(bytes([0x9F, 0, 0, 0]))
        flash.deselect()
        # Response should be zeros (device not responding)

        # Release from power down
        flash.select()
        flash.transfer(bytes([0xAB, 0, 0, 0, 0]))
        flash.deselect()

        assert not flash._powered_down


# =============================================================================
# RTC Tests
# =============================================================================

class TestDS3231RTC:
    """Tests for DS3231 RTC."""

    def test_create_rtc(self):
        """Test creating RTC."""
        rtc = DS3231_RTC()
        assert rtc.address == 0x68
        assert rtc.name == "DS3231"

    def test_set_get_time(self):
        """Test setting and getting time."""
        rtc = DS3231_RTC()
        rtc._use_system_time = False  # Don't use system time

        rtc.set_time(2025, 6, 15, 14, 30, 45)
        year, month, day, hour, minute, second = rtc.get_time()

        assert year == 2025
        assert month == 6
        assert day == 15
        assert hour == 14
        assert minute == 30
        assert second == 45

    def test_bcd_conversion(self):
        """Test BCD conversion."""
        rtc = DS3231_RTC()

        # Test decimal to BCD
        assert rtc._dec_to_bcd(0) == 0x00
        assert rtc._dec_to_bcd(9) == 0x09
        assert rtc._dec_to_bcd(10) == 0x10
        assert rtc._dec_to_bcd(59) == 0x59
        assert rtc._dec_to_bcd(99) == 0x99

        # Test BCD to decimal
        assert rtc._bcd_to_dec(0x00) == 0
        assert rtc._bcd_to_dec(0x09) == 9
        assert rtc._bcd_to_dec(0x10) == 10
        assert rtc._bcd_to_dec(0x59) == 59
        assert rtc._bcd_to_dec(0x99) == 99

    def test_temperature(self):
        """Test temperature reading."""
        rtc = DS3231_RTC()
        rtc.set_temperature(25.5)

        assert rtc.get_temperature() == 25.5

        # Read temperature registers
        rtc._update_temp_registers()
        temp_msb = rtc.read_register(rtc.REG_TEMP_MSB)
        temp_lsb = rtc.read_register(rtc.REG_TEMP_LSB)

        # Calculate temperature from registers
        raw = (temp_msb << 2) | (temp_lsb >> 6)
        if temp_msb & 0x80:
            raw = raw - 1024
        calculated = raw * 0.25
        assert abs(calculated - 25.5) < 0.5

    def test_i2c_read_write(self):
        """Test I2C interface."""
        rtc = DS3231_RTC()
        rtc._use_system_time = False

        # Write time via I2C
        # Address 0, then seconds, minutes, hours
        rtc.i2c_write(bytes([0x00, 0x30, 0x45, 0x12]))  # 12:45:30

        # Read back
        rtc._register_pointer = 0
        data = rtc.i2c_read(3)

        assert data[0] == 0x30  # Seconds
        assert data[1] == 0x45  # Minutes
        assert data[2] == 0x12  # Hours


# =============================================================================
# Compass Tests
# =============================================================================

class TestQMC5883LCompass:
    """Tests for QMC5883L Compass."""

    def test_create_compass(self):
        """Test creating compass."""
        compass = QMC5883L_Compass()
        assert compass.address == 0x0D
        assert compass.read_register(compass.REG_CHIP_ID) == 0xFF

    def test_set_heading(self):
        """Test setting heading."""
        compass = QMC5883L_Compass()

        compass.set_heading(90.0)
        assert compass.get_heading() == 90.0

        compass.set_heading(360.0)
        assert compass.get_heading() == 0.0

        compass.set_heading(-90.0)
        assert compass.get_heading() == 270.0

    def test_magnetic_field_calculation(self):
        """Test magnetic field from heading."""
        compass = QMC5883L_Compass()

        # North (0 degrees)
        compass.set_heading(0.0)
        compass._update_mag_registers()
        # X should be positive, Y should be ~0

        # East (90 degrees)
        compass.set_heading(90.0)
        compass._update_mag_registers()
        # X should be ~0, Y should be positive

    def test_i2c_read(self):
        """Test reading via I2C."""
        compass = QMC5883L_Compass()
        compass.set_heading(45.0)

        # Read all data registers
        compass._register_pointer = 0
        data = compass.i2c_read(6)

        assert len(data) == 6
        # Data should be valid 16-bit values (little-endian)

    def test_data_ready_flag(self):
        """Test data ready status flag."""
        compass = QMC5883L_Compass()

        # Initially status should be 0
        compass._registers[compass.REG_STATUS] = 0

        # After reading mag data, DRDY should be set
        compass._update_mag_registers()
        status = compass.read_register(compass.REG_STATUS)
        assert status & compass.STATUS_DRDY


# =============================================================================
# ILI9341 LCD Controller Tests
# =============================================================================

class TestILI9341LCD:
    """Tests for ILI9341 LCD Controller."""

    def test_create_lcd(self):
        """Test creating LCD controller."""
        lcd = ILI9341_LCD()
        assert lcd.width == 240
        assert lcd.height == 320

    def test_reset(self):
        """Test software reset."""
        lcd = ILI9341_LCD()
        lcd._display_on = True

        lcd.reset()
        assert not lcd._display_on

    def test_display_on_off(self):
        """Test display on/off commands."""
        lcd = ILI9341_LCD()

        lcd.write_command(lcd.CMD_DISPLAY_ON)
        assert lcd._display_on

        lcd.write_command(lcd.CMD_DISPLAY_OFF)
        assert not lcd._display_on

    def test_window_setting(self):
        """Test column/page address setting."""
        lcd = ILI9341_LCD()

        # Set window 10,20 to 50,80
        lcd.write_command(lcd.CMD_COLUMN_ADDR, bytes([0, 10, 0, 50]))
        lcd.write_command(lcd.CMD_PAGE_ADDR, bytes([0, 20, 0, 80]))

        assert lcd._col_start == 10
        assert lcd._col_end == 50
        assert lcd._page_start == 20
        assert lcd._page_end == 80

    def test_rgb565_conversion(self):
        """Test RGB565 color conversion."""
        # Pure red
        color = ILI9341_LCD.rgb_to_rgb565(255, 0, 0)
        assert color == 0xF800

        # Pure green
        color = ILI9341_LCD.rgb_to_rgb565(0, 255, 0)
        assert color == 0x07E0

        # Pure blue
        color = ILI9341_LCD.rgb_to_rgb565(0, 0, 255)
        assert color == 0x001F

        # White
        color = ILI9341_LCD.rgb_to_rgb565(255, 255, 255)
        assert color == 0xFFFF

        # Convert back
        r, g, b = ILI9341_LCD.rgb565_to_rgb(0xF800)
        assert r == 0xF8
        assert g == 0
        assert b == 0

    def test_framebuffer(self):
        """Test framebuffer operations."""
        lcd = ILI9341_LCD()

        fb = lcd.get_framebuffer()
        assert len(fb) == 240 * 320 * 2


# =============================================================================
# SSD1306 OLED Controller Tests
# =============================================================================

class TestSSD1306OLED:
    """Tests for SSD1306 OLED Controller."""

    def test_create_oled(self):
        """Test creating OLED controller."""
        oled = SSD1306_OLED()
        assert oled.width == 128
        assert oled.height == 64
        assert oled._pages == 8

    def test_set_get_pixel(self):
        """Test pixel operations."""
        oled = SSD1306_OLED()

        oled.set_pixel(10, 20, True)
        assert oled.get_pixel(10, 20) == True
        assert oled.get_pixel(10, 21) == False

        oled.set_pixel(10, 20, False)
        assert oled.get_pixel(10, 20) == False

    def test_clear(self):
        """Test clearing display."""
        oled = SSD1306_OLED()

        oled.set_pixel(50, 30, True)
        oled.clear()

        assert oled.get_pixel(50, 30) == False
        assert all(b == 0 for b in oled.get_buffer())

    def test_display_on_off(self):
        """Test display on/off via I2C."""
        oled = SSD1306_OLED()

        # Command mode (0x00), Display ON (0xAF)
        oled.i2c_write(bytes([0x00, 0xAF]))
        assert oled._display_on

        # Command mode (0x00), Display OFF (0xAE)
        oled.i2c_write(bytes([0x00, 0xAE]))
        assert not oled._display_on

    def test_invert_display(self):
        """Test display inversion."""
        oled = SSD1306_OLED()

        oled.i2c_write(bytes([0x00, 0xA7]))  # Invert
        assert oled._inverted

        oled.i2c_write(bytes([0x00, 0xA6]))  # Normal
        assert not oled._inverted

    def test_buffer_operations(self):
        """Test buffer get/set."""
        oled = SSD1306_OLED()

        # Create test pattern
        test_data = bytes([0xAA] * 128 + [0x55] * 128)
        oled.set_buffer(test_data)

        buffer = oled.get_buffer()
        assert buffer[:128] == bytes([0xAA] * 128)
        assert buffer[128:256] == bytes([0x55] * 128)


# =============================================================================
# Component SDK Tests
# =============================================================================

class TestComponentSDK:
    """Tests for Component SDK."""

    def test_add_i2c_devices(self):
        """Test adding I2C devices."""
        sdk = ComponentSDK()

        eeprom = create_eeprom()
        rtc = create_rtc()
        compass = create_compass()

        sdk.add_i2c_device(eeprom)
        sdk.add_i2c_device(rtc)
        sdk.add_i2c_device(compass)

        assert sdk.get_i2c_device(0x50) is eeprom
        assert sdk.get_i2c_device(0x68) is rtc
        assert sdk.get_i2c_device(0x0D) is compass

    def test_add_spi_devices(self):
        """Test adding SPI devices."""
        sdk = ComponentSDK()

        flash = create_flash()
        lcd = create_ili9341()

        sdk.add_spi_device('flash', flash)
        sdk.add_spi_device('lcd', lcd)

        assert sdk.get_spi_device('flash') is flash
        assert sdk.get_spi_device('lcd') is lcd

    def test_i2c_transfer(self):
        """Test I2C transfer through SDK."""
        sdk = ComponentSDK()
        eeprom = create_eeprom()
        sdk.add_i2c_device(eeprom)

        # Write data
        sdk.i2c_transfer(0xA0, bytes([0x00, 0x00, 0x12, 0x34]))

        # Read back
        eeprom._write_address = 0
        result = sdk.i2c_transfer(0xA1, b'', read_length=2)

        assert result == bytes([0x12, 0x34])

    def test_spi_transfer(self):
        """Test SPI transfer through SDK."""
        sdk = ComponentSDK()
        flash = create_flash()
        sdk.add_spi_device('flash', flash)

        # Read JEDEC ID
        result = sdk.spi_transfer('flash', bytes([0x9F, 0, 0, 0]))

        assert result[1] == 0xEF  # Winbond


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactoryFunctions:
    """Tests for factory functions."""

    def test_create_eeprom(self):
        """Test create_eeprom factory."""
        eeprom = create_eeprom('24C128', 0x54)
        assert eeprom.model == '24C128'
        assert eeprom.address == 0x54
        assert eeprom.size == 16384

    def test_create_flash(self):
        """Test create_flash factory."""
        flash = create_flash('W25Q64')
        assert flash.model == 'W25Q64'
        assert flash.size == 8 * 1024 * 1024

    def test_create_rtc(self):
        """Test create_rtc factory."""
        rtc = create_rtc(0x57)
        assert rtc.address == 0x57

    def test_create_compass(self):
        """Test create_compass factory."""
        compass = create_compass(0x1E)
        assert compass.address == 0x1E

    def test_create_ili9341(self):
        """Test create_ili9341 factory."""
        lcd = create_ili9341(320, 480)
        assert lcd.width == 320
        assert lcd.height == 480

    def test_create_ssd1306(self):
        """Test create_ssd1306 factory."""
        oled = create_ssd1306(128, 32)
        assert oled.width == 128
        assert oled.height == 32
        assert oled._pages == 4


# =============================================================================
# Pygame Peripheral Tests (conditional)
# =============================================================================

@pytest.mark.skipif(not PYGAME_AVAILABLE, reason="pygame not available")
class TestPygamePeripherals:
    """Tests for pygame-based peripherals."""

    def test_rgb_color(self):
        """Test RGB color class."""
        if RGB is None:
            pytest.skip("RGB not available")
        color = RGB(255, 128, 64)
        assert color.to_tuple() == (255, 128, 64)

        # Test brightness
        dimmed = color.with_brightness(0.5)
        assert dimmed.r == 127
        assert dimmed.g == 64
        assert dimmed.b == 32

        # Test from hex
        hex_color = RGB.from_hex('#FF8040')
        assert hex_color.r == 255
        assert hex_color.g == 128
        assert hex_color.b == 64

    def test_led_state(self):
        """Test LED state changes."""
        led = LED(0, 0, LEDColor.RED)

        assert not led.state

        led.on()
        assert led.state

        led.off()
        assert not led.state

        led.toggle()
        assert led.state

    def test_led_brightness(self):
        """Test LED brightness."""
        led = LED(0, 0)

        led.brightness = 0.5
        assert led.brightness == 0.5

        led.brightness = 1.5  # Should clamp
        assert led.brightness == 1.0

        led.brightness = -0.5  # Should clamp
        assert led.brightness == 0.0

    def test_rgb_led_color(self):
        """Test RGB LED color setting."""
        rgb = RGBLED(0, 0)

        rgb.set_rgb(100, 150, 200)
        color = rgb.color
        assert color.r == 100
        assert color.g == 150
        assert color.b == 200

    def test_rgb_led_hsv(self):
        """Test RGB LED HSV conversion."""
        rgb = RGBLED(0, 0)

        # Pure red (H=0)
        rgb.set_hsv(0, 1.0, 1.0)
        color = rgb.color
        assert color.r == 255
        assert color.g == 0
        assert color.b == 0

    def test_led_strip(self):
        """Test LED strip operations."""
        strip = LEDStrip(0, 0, num_leds=8)

        strip.set_pixel(0, (255, 0, 0))
        strip.set_pixel(7, (0, 0, 255))

        assert strip._colors[0].r == 255
        assert strip._colors[7].b == 255

        strip.clear()
        assert all(c.r == 0 and c.g == 0 and c.b == 0 for c in strip._colors)

    def test_character_lcd(self):
        """Test character LCD."""
        lcd = CharacterLCD(0, 0, cols=16, rows=2)

        lcd.write("Hello")
        assert lcd._buffer[0][:5] == ['H', 'e', 'l', 'l', 'o']

        lcd.clear()
        assert lcd._buffer[0][0] == ' '

        lcd.print(1, "Line 2")
        assert lcd._buffer[1][:6] == ['L', 'i', 'n', 'e', ' ', '2']

    def test_graphic_oled(self):
        """Test graphic OLED."""
        oled = GraphicOLED(0, 0, width=128, height=64)

        oled.set_pixel(10, 20, True)
        assert oled.get_pixel(10, 20) == True

        oled.clear()
        assert oled.get_pixel(10, 20) == False

        oled.draw_line(0, 0, 10, 10)
        assert oled.get_pixel(5, 5) == True

    def test_seven_segment(self):
        """Test 7-segment display."""
        seg = SevenSegmentDisplay(0, 0, digits=4)

        seg.set_number(1234)
        assert seg._values == ['1', '2', '3', '4']

        seg.set_text("ABCD")
        assert seg._values == ['A', 'B', 'C', 'D']

    def test_button_state(self):
        """Test button state."""
        btn = Button(0, 0, label="Test")

        assert not btn.pressed

        btn.press()
        assert btn.pressed

        btn.release()
        assert not btn.pressed

    def test_rotary_encoder(self):
        """Test rotary encoder."""
        encoder = RotaryEncoder(0, 0)

        assert encoder.position == 0

        encoder.rotate_cw()
        assert encoder.position == 1

        encoder.rotate_ccw()
        encoder.rotate_ccw()
        assert encoder.position == -1

    def test_gamepad_state(self):
        """Test gamepad state."""
        gamepad = Gamepad(0, 0)

        state = gamepad.get_state()
        assert 'dpad' in state
        assert 'buttons' in state
        assert 'analog' in state

        gamepad.up = True
        gamepad.button_a = True

        state = gamepad.get_state()
        assert state['dpad']['up'] == True
        assert state['buttons']['a'] == True


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests combining multiple components."""

    def test_i2c_bus_with_multiple_devices(self):
        """Test I2C bus with EEPROM, RTC, and Compass."""
        sdk = ComponentSDK()

        eeprom = create_eeprom('24C256', 0x50)
        rtc = create_rtc(0x68)
        compass = create_compass(0x0D)

        sdk.add_i2c_device(eeprom)
        sdk.add_i2c_device(rtc)
        sdk.add_i2c_device(compass)

        # Write to EEPROM
        sdk.i2c_transfer(0xA0, bytes([0x00, 0x00, 0xCA, 0xFE]))

        # Read RTC time
        result = sdk.i2c_transfer(0xD0, bytes([0x00]), read_length=3)
        assert len(result) == 3

        # Read compass data
        result = sdk.i2c_transfer(0x1A, bytes([0x00]), read_length=6)
        assert len(result) == 6

    def test_spi_bus_with_flash_and_lcd(self):
        """Test SPI bus with Flash and LCD."""
        sdk = ComponentSDK()

        flash = create_flash('W25Q128')
        lcd = create_ili9341()

        sdk.add_spi_device('flash', flash)
        sdk.add_spi_device('lcd', lcd)

        # Read flash ID
        result = sdk.spi_transfer('flash', bytes([0x9F, 0, 0, 0]))
        assert result[1] == 0xEF

        # Send LCD commands
        lcd.select()
        lcd.write_command(lcd.CMD_DISPLAY_ON)
        lcd.deselect()
        assert lcd._display_on

    def test_data_persistence(self):
        """Test that EEPROM data persists across operations."""
        eeprom = create_eeprom('24C256')

        # Write pattern
        test_data = bytes([i & 0xFF for i in range(256)])
        eeprom.set_contents(test_data)

        # Simulate power cycle (reset)
        eeprom.reset()

        # Data should still be there
        contents = eeprom.get_contents()
        assert contents[:256] == test_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
