"""
Pygame-based Virtual Peripherals for SLAB.

Provides lightweight peripheral abstractions (LEDs, displays, inputs)
with state management suitable for testing and pygame-based visualization.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import colorsys
from enum import Enum

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


# ---------------------------------------------------------------------------
# Color utilities
# ---------------------------------------------------------------------------

class RGB:
    """RGB color with utility methods."""

    __slots__ = ('r', 'g', 'b')

    def __init__(self, r: int, g: int, b: int):
        self.r = r
        self.g = g
        self.b = b

    def to_tuple(self):
        return (self.r, self.g, self.b)

    def with_brightness(self, factor: float) -> 'RGB':
        return RGB(
            int(self.r * factor),
            int(self.g * factor),
            int(self.b * factor),
        )

    @classmethod
    def from_hex(cls, hex_str: str) -> 'RGB':
        h = hex_str.lstrip('#')
        return cls(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def __repr__(self):
        return f"RGB({self.r}, {self.g}, {self.b})"


class LEDColor(Enum):
    """Predefined LED colors."""
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)
    YELLOW = (255, 255, 0)
    WHITE = (255, 255, 255)
    ORANGE = (255, 165, 0)


# ---------------------------------------------------------------------------
# Output peripherals
# ---------------------------------------------------------------------------

class LED:
    """Single LED with on/off state and brightness."""

    def __init__(self, x: int = 0, y: int = 0, color=LEDColor.GREEN):
        self.x = x
        self.y = y
        self.led_color = color
        self.state = False
        self._brightness = 1.0

    @property
    def brightness(self) -> float:
        return self._brightness

    @brightness.setter
    def brightness(self, value: float):
        self._brightness = max(0.0, min(1.0, value))

    def on(self):
        self.state = True

    def off(self):
        self.state = False

    def toggle(self):
        self.state = not self.state


class RGBLED:
    """RGB LED with individual color channel control."""

    def __init__(self, x: int = 0, y: int = 0):
        self.x = x
        self.y = y
        self.color = RGB(0, 0, 0)

    def set_rgb(self, r: int, g: int, b: int):
        self.color = RGB(r, g, b)

    def set_hsv(self, h: float, s: float, v: float):
        r, g, b = colorsys.hsv_to_rgb(h / 360.0 if h > 1 else h, s, v)
        self.color = RGB(int(r * 255), int(g * 255), int(b * 255))


class LEDStrip:
    """Addressable LED strip (e.g., WS2812 / NeoPixel)."""

    def __init__(self, x: int = 0, y: int = 0, num_leds: int = 8):
        self.x = x
        self.y = y
        self._colors = [RGB(0, 0, 0) for _ in range(num_leds)]

    def set_pixel(self, index: int, color):
        if isinstance(color, tuple):
            self._colors[index] = RGB(*color)
        else:
            self._colors[index] = color

    def clear(self):
        for i in range(len(self._colors)):
            self._colors[i] = RGB(0, 0, 0)


class Buzzer:
    """Piezo buzzer stub."""

    def __init__(self, x: int = 0, y: int = 0):
        self.x = x
        self.y = y
        self.frequency = 0
        self.active = False

    def tone(self, frequency: int):
        self.frequency = frequency
        self.active = True

    def off(self):
        self.frequency = 0
        self.active = False


# ---------------------------------------------------------------------------
# Display peripherals
# ---------------------------------------------------------------------------

class CharacterLCD:
    """Character LCD display (e.g., HD44780)."""

    def __init__(self, x: int = 0, y: int = 0, cols: int = 16, rows: int = 2):
        self.x = x
        self.y = y
        self.cols = cols
        self.rows = rows
        self._buffer = [[' '] * cols for _ in range(rows)]
        self._cursor_row = 0
        self._cursor_col = 0

    def write(self, text: str):
        for ch in text:
            if self._cursor_col < self.cols:
                self._buffer[self._cursor_row][self._cursor_col] = ch
                self._cursor_col += 1

    def print(self, row: int, text: str):
        for i, ch in enumerate(text):
            if i < self.cols:
                self._buffer[row][i] = ch

    def clear(self):
        self._buffer = [[' '] * self.cols for _ in range(self.rows)]
        self._cursor_row = 0
        self._cursor_col = 0


class GraphicOLED:
    """Graphic OLED display (e.g., SSD1306)."""

    def __init__(self, x: int = 0, y: int = 0, width: int = 128, height: int = 64):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self._framebuffer = bytearray(width * height // 8)

    def set_pixel(self, px: int, py: int, on: bool = True):
        if 0 <= px < self.width and 0 <= py < self.height:
            byte_idx = (py // 8) * self.width + px
            bit = py % 8
            if on:
                self._framebuffer[byte_idx] |= (1 << bit)
            else:
                self._framebuffer[byte_idx] &= ~(1 << bit)

    def get_pixel(self, px: int, py: int) -> bool:
        if 0 <= px < self.width and 0 <= py < self.height:
            byte_idx = (py // 8) * self.width + px
            bit = py % 8
            return bool(self._framebuffer[byte_idx] & (1 << bit))
        return False

    def clear(self):
        self._framebuffer = bytearray(self.width * self.height // 8)

    def draw_line(self, x0: int, y0: int, x1: int, y1: int):
        """Bresenham's line algorithm."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            self.set_pixel(x0, y0, True)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy


class SevenSegmentDisplay:
    """Multi-digit 7-segment display."""

    def __init__(self, x: int = 0, y: int = 0, digits: int = 4):
        self.x = x
        self.y = y
        self.digits = digits
        self._values = [' '] * digits

    def set_number(self, n: int):
        s = str(n)
        self._values = list(s[-self.digits:].rjust(self.digits))

    def set_text(self, text: str):
        self._values = list(text[:self.digits].ljust(self.digits))


# ---------------------------------------------------------------------------
# Input peripherals
# ---------------------------------------------------------------------------

class Button:
    """Momentary push button."""

    def __init__(self, x: int = 0, y: int = 0, label: str = ""):
        self.x = x
        self.y = y
        self.label = label
        self.pressed = False

    def press(self):
        self.pressed = True

    def release(self):
        self.pressed = False


class RotaryEncoder:
    """Incremental rotary encoder."""

    def __init__(self, x: int = 0, y: int = 0):
        self.x = x
        self.y = y
        self.position = 0

    def rotate_cw(self):
        self.position += 1

    def rotate_ccw(self):
        self.position -= 1


class Gamepad:
    """Game controller with dpad, buttons, and analog sticks."""

    def __init__(self, x: int = 0, y: int = 0):
        self.x = x
        self.y = y
        # D-pad
        self.up = False
        self.down = False
        self.left = False
        self.right = False
        # Buttons
        self.button_a = False
        self.button_b = False
        self.button_x = False
        self.button_y = False
        # Analog
        self.analog_x = 0.0
        self.analog_y = 0.0

    def get_state(self) -> dict:
        return {
            'dpad': {
                'up': self.up,
                'down': self.down,
                'left': self.left,
                'right': self.right,
            },
            'buttons': {
                'a': self.button_a,
                'b': self.button_b,
                'x': self.button_x,
                'y': self.button_y,
            },
            'analog': {
                'x': self.analog_x,
                'y': self.analog_y,
            },
        }


# ---------------------------------------------------------------------------
# Board / SDK stubs
# ---------------------------------------------------------------------------

class VirtualBoard:
    """Container for a collection of virtual peripherals."""

    def __init__(self, name: str = "board"):
        self.name = name
        self.peripherals = []

    def add(self, peripheral):
        self.peripherals.append(peripheral)


class PeripheralSDK:
    """SDK for managing pygame-based peripherals."""

    def __init__(self):
        self.board = VirtualBoard()

    def add_peripheral(self, peripheral):
        self.board.add(peripheral)
