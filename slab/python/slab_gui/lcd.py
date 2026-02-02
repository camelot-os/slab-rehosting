"""
SLAB GUI LCD and OLED Display Widgets

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, List
from .base import DisplayWidget, Color, GUIBackend, _QT_AVAILABLE


class CharacterLCDWidget(DisplayWidget):
    """
    Character LCD display (e.g., HD44780 compatible).

    Common sizes: 16x2, 20x4
    """

    def __init__(self, cols: int = 16, rows: int = 2,
                 char_width: int = 12, char_height: int = 18,
                 fg_color: Color = None, bg_color: Color = None,
                 backend: GUIBackend = None):
        self.cols = cols
        self.rows = rows
        self.char_width = char_width
        self.char_height = char_height
        self.fg_color = fg_color or Color(0, 80, 0)  # Dark green LCD
        self.bg_color = bg_color or Color(120, 180, 120)  # Light green

        margin = 10
        width = cols * char_width + 2 * margin
        height = rows * char_height + 2 * margin

        super().__init__(width, height, backend)

        # Character buffer
        self._buffer = [[' ' for _ in range(cols)] for _ in range(rows)]
        self._cursor_row = 0
        self._cursor_col = 0
        self._cursor_visible = True
        self._display_on = True

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt character LCD widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtGui import QPainter, QFont, QColor, QPen
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtGui import QPainter, QFont, QColor, QPen
            from PyQt6.QtCore import Qt

        parent = self

        class QtCharLCD(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)
                self.font = QFont("Courier New", parent.char_height - 4)
                self.font.setStyleHint(QFont.StyleHint.Monospace)

            def paintEvent(self, event):
                painter = QPainter(self)

                # Background
                bg = parent.bg_color
                painter.fillRect(0, 0, parent.width, parent.height, QColor(bg.r, bg.g, bg.b))

                # Border
                painter.setPen(QPen(QColor(60, 60, 60), 3))
                painter.drawRect(1, 1, parent.width - 2, parent.height - 2)

                if not parent._display_on:
                    return

                # Draw characters
                fg = parent.fg_color
                painter.setPen(QColor(fg.r, fg.g, fg.b))
                painter.setFont(self.font)

                margin = 10
                for row in range(parent.rows):
                    for col in range(parent.cols):
                        x = margin + col * parent.char_width
                        y = margin + (row + 1) * parent.char_height - 4
                        char = parent._buffer[row][col]
                        painter.drawText(x, y, char)

                # Cursor
                if parent._cursor_visible:
                    cx = margin + parent._cursor_col * parent.char_width
                    cy = margin + parent._cursor_row * parent.char_height
                    painter.fillRect(
                        cx, cy + parent.char_height - 3,
                        parent.char_width - 2, 2,
                        QColor(fg.r, fg.g, fg.b)
                    )

        self._native_widget = QtCharLCD()

    def write(self, text: str):
        """Write text at cursor position."""
        for char in text:
            if char == '\n':
                self._cursor_row += 1
                self._cursor_col = 0
            elif char == '\r':
                self._cursor_col = 0
            else:
                if self._cursor_col < self.cols and self._cursor_row < self.rows:
                    self._buffer[self._cursor_row][self._cursor_col] = char
                    self._cursor_col += 1
                    if self._cursor_col >= self.cols:
                        self._cursor_col = 0
                        self._cursor_row += 1
        self.update()

    def set_cursor(self, row: int, col: int):
        """Set cursor position."""
        self._cursor_row = max(0, min(self.rows - 1, row))
        self._cursor_col = max(0, min(self.cols - 1, col))
        self.update()

    def set_text(self, row: int, text: str):
        """Set entire row text."""
        if 0 <= row < self.rows:
            text = text.ljust(self.cols)[:self.cols]
            self._buffer[row] = list(text)
        self.update()

    def display_on(self, on: bool):
        """Turn display on/off."""
        self._display_on = on
        self.update()

    def cursor_visible(self, visible: bool):
        """Show/hide cursor."""
        self._cursor_visible = visible
        self.update()

    def update(self):
        if self._native_widget:
            self._native_widget.update()

    def clear(self, color: Color = None):
        """Clear display."""
        self._buffer = [[' ' for _ in range(self.cols)] for _ in range(self.rows)]
        self._cursor_row = 0
        self._cursor_col = 0
        self.update()


class GraphicLCDWidget(DisplayWidget):
    """
    Graphic LCD display (e.g., 128x64 monochrome).
    """

    def __init__(self, width: int = 128, height: int = 64,
                 fg_color: Color = None, bg_color: Color = None,
                 scale: int = 2, backend: GUIBackend = None):
        self.lcd_width = width
        self.lcd_height = height
        self.scale = scale
        self.fg_color = fg_color or Color(0, 0, 0)
        self.bg_color = bg_color or Color(170, 180, 170)

        super().__init__(width * scale + 20, height * scale + 20, backend)

        # Pixel buffer (1 bit per pixel, packed into bytes)
        self._buffer = bytearray((width * height + 7) // 8)

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt graphic LCD widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtGui import QPainter, QColor, QPen, QImage
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtGui import QPainter, QColor, QPen, QImage

        parent = self

        class QtGraphicLCD(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)

            def paintEvent(self, event):
                painter = QPainter(self)

                # Background
                bg = parent.bg_color
                painter.fillRect(0, 0, parent.width, parent.height, QColor(bg.r, bg.g, bg.b))

                # Border
                painter.setPen(QPen(QColor(60, 60, 60), 3))
                painter.drawRect(1, 1, parent.width - 2, parent.height - 2)

                # Draw pixels
                fg = parent.fg_color
                margin = 10
                scale = parent.scale

                for y in range(parent.lcd_height):
                    for x in range(parent.lcd_width):
                        bit_idx = y * parent.lcd_width + x
                        byte_idx = bit_idx // 8
                        bit_pos = 7 - (bit_idx % 8)

                        if parent._buffer[byte_idx] & (1 << bit_pos):
                            painter.fillRect(
                                margin + x * scale,
                                margin + y * scale,
                                scale, scale,
                                QColor(fg.r, fg.g, fg.b)
                            )

        self._native_widget = QtGraphicLCD()

    def set_pixel(self, x: int, y: int, on: bool = True):
        """Set a pixel."""
        if 0 <= x < self.lcd_width and 0 <= y < self.lcd_height:
            bit_idx = y * self.lcd_width + x
            byte_idx = bit_idx // 8
            bit_pos = 7 - (bit_idx % 8)

            if on:
                self._buffer[byte_idx] |= (1 << bit_pos)
            else:
                self._buffer[byte_idx] &= ~(1 << bit_pos)

    def get_pixel(self, x: int, y: int) -> bool:
        """Get a pixel."""
        if 0 <= x < self.lcd_width and 0 <= y < self.lcd_height:
            bit_idx = y * self.lcd_width + x
            byte_idx = bit_idx // 8
            bit_pos = 7 - (bit_idx % 8)
            return bool(self._buffer[byte_idx] & (1 << bit_pos))
        return False

    def set_buffer(self, data: bytes):
        """Set entire buffer."""
        self._buffer = bytearray(data[:len(self._buffer)])
        self.update()

    def draw_line(self, x0: int, y0: int, x1: int, y1: int, on: bool = True):
        """Draw a line using Bresenham's algorithm."""
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            self.set_pixel(x0, y0, on)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def draw_rect(self, x: int, y: int, w: int, h: int, on: bool = True, fill: bool = False):
        """Draw rectangle."""
        if fill:
            for py in range(y, y + h):
                for px in range(x, x + w):
                    self.set_pixel(px, py, on)
        else:
            self.draw_line(x, y, x + w - 1, y, on)
            self.draw_line(x + w - 1, y, x + w - 1, y + h - 1, on)
            self.draw_line(x + w - 1, y + h - 1, x, y + h - 1, on)
            self.draw_line(x, y + h - 1, x, y, on)

    def update(self):
        if self._native_widget:
            self._native_widget.update()

    def clear(self, color: Color = None):
        """Clear display."""
        self._buffer = bytearray(len(self._buffer))
        self.update()


class OLEDWidget(GraphicLCDWidget):
    """
    OLED display (e.g., SSD1306 128x64).

    Same as graphic LCD but with OLED colors (white on black).
    """

    def __init__(self, width: int = 128, height: int = 64,
                 scale: int = 2, backend: GUIBackend = None):
        super().__init__(
            width, height,
            fg_color=Color(200, 200, 255),  # Bluish white
            bg_color=Color(0, 0, 0),        # Black
            scale=scale,
            backend=backend
        )
