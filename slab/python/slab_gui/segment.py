"""
SLAB GUI 7-Segment Display Widgets

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, List
from .base import DisplayWidget, Color, GUIBackend, _QT_AVAILABLE


# 7-segment patterns for digits 0-9 and A-F
# Segments: DP G F E D C B A (bit 7 to 0)
SEGMENT_PATTERNS = {
    '0': 0x3F, '1': 0x06, '2': 0x5B, '3': 0x4F,
    '4': 0x66, '5': 0x6D, '6': 0x7D, '7': 0x07,
    '8': 0x7F, '9': 0x6F, 'A': 0x77, 'B': 0x7C,
    'C': 0x39, 'D': 0x5E, 'E': 0x79, 'F': 0x71,
    'a': 0x77, 'b': 0x7C, 'c': 0x58, 'd': 0x5E,
    'e': 0x79, 'f': 0x71, '-': 0x40, '_': 0x08,
    ' ': 0x00, 'H': 0x76, 'L': 0x38, 'P': 0x73,
    'U': 0x3E, 'o': 0x5C, 'n': 0x54, 'r': 0x50,
}


class SevenSegmentWidget(DisplayWidget):
    """Single 7-segment display digit."""

    def __init__(self, color: Color = None, width: int = 40, height: int = 60,
                 backend: GUIBackend = None):
        super().__init__(width, height, backend)
        self.segment_color = color or Color.RED
        self._segments = 0  # 8-bit: DP G F E D C B A
        self._dp = False

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt 7-segment widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtGui import QPainter, QBrush, QPen, QColor, QPolygon
            from PySide6.QtCore import QPoint
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtGui import QPainter, QBrush, QPen, QColor, QPolygon
            from PyQt6.QtCore import QPoint

        parent = self

        class Qt7Seg(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)

            def _draw_segment(self, painter, points, lit):
                c = parent.segment_color
                if lit:
                    color = QColor(c.r, c.g, c.b)
                else:
                    color = QColor(c.r // 8, c.g // 8, c.b // 8)
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color.darker(120), 1))
                polygon = QPolygon([QPoint(int(x), int(y)) for x, y in points])
                painter.drawPolygon(polygon)

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                # Background
                painter.fillRect(0, 0, parent.width, parent.height, QColor(20, 20, 20))

                w, h = parent.width, parent.height
                sw = w * 0.15  # segment width
                sl = w * 0.6   # segment length
                m = w * 0.1    # margin

                # Calculate segment positions
                # Horizontal segments (a, g, d)
                def h_seg(cx, cy):
                    return [
                        (cx - sl/2, cy),
                        (cx - sl/2 + sw/2, cy - sw/2),
                        (cx + sl/2 - sw/2, cy - sw/2),
                        (cx + sl/2, cy),
                        (cx + sl/2 - sw/2, cy + sw/2),
                        (cx - sl/2 + sw/2, cy + sw/2),
                    ]

                # Vertical segments (b, c, e, f)
                def v_seg(cx, cy):
                    return [
                        (cx, cy - sl/2),
                        (cx + sw/2, cy - sl/2 + sw/2),
                        (cx + sw/2, cy + sl/2 - sw/2),
                        (cx, cy + sl/2),
                        (cx - sw/2, cy + sl/2 - sw/2),
                        (cx - sw/2, cy - sl/2 + sw/2),
                    ]

                cx = w / 2
                top_y = m + sw/2
                mid_y = h / 2
                bot_y = h - m - sw/2
                left_x = m + sw/2
                right_x = w - m - sw/2

                segs = parent._segments

                # a - top
                self._draw_segment(painter, h_seg(cx, top_y), segs & 0x01)
                # b - top right
                self._draw_segment(painter, v_seg(right_x, (top_y + mid_y) / 2), segs & 0x02)
                # c - bottom right
                self._draw_segment(painter, v_seg(right_x, (mid_y + bot_y) / 2), segs & 0x04)
                # d - bottom
                self._draw_segment(painter, h_seg(cx, bot_y), segs & 0x08)
                # e - bottom left
                self._draw_segment(painter, v_seg(left_x, (mid_y + bot_y) / 2), segs & 0x10)
                # f - top left
                self._draw_segment(painter, v_seg(left_x, (top_y + mid_y) / 2), segs & 0x20)
                # g - middle
                self._draw_segment(painter, h_seg(cx, mid_y), segs & 0x40)

                # DP - decimal point
                c = parent.segment_color
                dp_color = QColor(c.r, c.g, c.b) if (segs & 0x80) or parent._dp else QColor(c.r // 8, c.g // 8, c.b // 8)
                painter.setBrush(QBrush(dp_color))
                painter.setPen(QPen(dp_color, 1))
                dp_radius = sw / 2
                painter.drawEllipse(
                    int(w - m - dp_radius), int(h - m - dp_radius),
                    int(dp_radius * 2), int(dp_radius * 2)
                )

        self._native_widget = Qt7Seg()

    @property
    def segments(self) -> int:
        return self._segments

    @segments.setter
    def segments(self, value: int):
        self._segments = value & 0xFF
        self.update()

    def set_digit(self, digit: str):
        """Set display to show a digit or character."""
        self._segments = SEGMENT_PATTERNS.get(digit, 0)
        self.update()

    def set_decimal_point(self, on: bool):
        """Set decimal point state."""
        self._dp = on
        self.update()

    def update(self):
        if self._native_widget:
            self._native_widget.update()

    def clear(self, color: Color = None):
        self._segments = 0
        self._dp = False
        self.update()


class SevenSegmentArrayWidget(DisplayWidget):
    """Array of 7-segment displays."""

    def __init__(self, digits: int = 4, color: Color = None,
                 digit_width: int = 35, digit_height: int = 55,
                 backend: GUIBackend = None):
        self.num_digits = digits
        self.digit_width = digit_width
        self.digit_height = digit_height

        width = digits * (digit_width + 5) + 5
        height = digit_height + 10

        super().__init__(width, height, backend)

        self.displays = [
            SevenSegmentWidget(color, digit_width, digit_height, backend)
            for _ in range(digits)
        ]

        self._create_native()

    def _create_native(self):
        """Create native container widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt container."""
        try:
            from PySide6.QtWidgets import QWidget, QHBoxLayout
            from PySide6.QtGui import QPalette, QColor
        except ImportError:
            from PyQt6.QtWidgets import QWidget, QHBoxLayout
            from PyQt6.QtGui import QPalette, QColor

        container = QWidget()
        container.setFixedSize(self.width, self.height)
        palette = container.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(20, 20, 20))
        container.setAutoFillBackground(True)
        container.setPalette(palette)

        layout = QHBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        for display in self.displays:
            if display._native_widget:
                layout.addWidget(display._native_widget)

        self._native_widget = container

    def set_number(self, value: int, leading_zeros: bool = False):
        """Set display to show a number."""
        if value < 0:
            # Handle negative
            fmt = f"-{{:0{self.num_digits - 1}d}}" if leading_zeros else f"-{{:{self.num_digits - 1}d}}"
            text = fmt.format(abs(value))
        else:
            fmt = f"{{:0{self.num_digits}d}}" if leading_zeros else f"{{:{self.num_digits}d}}"
            text = fmt.format(value)

        self.set_text(text[-self.num_digits:])

    def set_hex(self, value: int):
        """Set display to show hex value."""
        fmt = f"{{:0{self.num_digits}X}}"
        self.set_text(fmt.format(value)[-self.num_digits:])

    def set_text(self, text: str):
        """Set display to show text."""
        text = text.ljust(self.num_digits)[:self.num_digits]
        for i, char in enumerate(text):
            self.displays[i].set_digit(char)

    def set_segments(self, index: int, value: int):
        """Set raw segments for a specific digit."""
        if 0 <= index < self.num_digits:
            self.displays[index].segments = value

    def update(self):
        for display in self.displays:
            display.update()

    def clear(self, color: Color = None):
        for display in self.displays:
            display.clear()
