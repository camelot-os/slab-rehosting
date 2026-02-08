"""
SLAB GUI LED Widgets

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, List, Tuple
from .base import DisplayWidget, Color, GUIBackend, _QT_AVAILABLE, _PYGAME_AVAILABLE


class LEDWidget(DisplayWidget):
    """Single LED widget."""

    def __init__(self, color: Color = None, size: int = 20,
                 backend: GUIBackend = None):
        super().__init__(size, size, backend)
        self.led_color = color or Color.RED
        self._on = False

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()
        elif self.backend == GUIBackend.PYGAME and _PYGAME_AVAILABLE:
            self._create_pygame()

    def _create_qt(self):
        """Create Qt LED widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtCore import Qt
            from PySide6.QtGui import QPainter, QBrush, QPen, QColor, QRadialGradient
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QPainter, QBrush, QPen, QColor, QRadialGradient

        parent = self

        class QtLED(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                # Draw LED
                if parent._on:
                    # Lit LED with glow effect
                    c = parent.led_color
                    gradient = QRadialGradient(
                        parent.width / 2, parent.height / 2,
                        parent.width / 2
                    )
                    gradient.setColorAt(0, QColor(255, 255, 255, 200))
                    gradient.setColorAt(0.3, QColor(c.r, c.g, c.b, 255))
                    gradient.setColorAt(1, QColor(c.r // 2, c.g // 2, c.b // 2, 255))
                    painter.setBrush(QBrush(gradient))
                else:
                    # Off LED - darker
                    c = parent.led_color
                    painter.setBrush(QBrush(QColor(c.r // 4, c.g // 4, c.b // 4)))

                painter.setPen(QPen(QColor(40, 40, 40), 2))
                margin = 2
                painter.drawEllipse(
                    margin, margin,
                    parent.width - 2 * margin,
                    parent.height - 2 * margin
                )

        self._native_widget = QtLED()

    def _create_pygame(self):
        """Create Pygame LED surface."""
        pass  # Handled in render()

    @property
    def on(self) -> bool:
        return self._on

    @on.setter
    def on(self, value: bool):
        self._on = bool(value)
        self.update()

    def toggle(self):
        """Toggle LED state."""
        self._on = not self._on
        self.update()

    def update(self):
        """Update the LED display."""
        if self._native_widget:
            self._native_widget.update()

    def clear(self, color: Color = None):
        """Turn off LED."""
        self._on = False
        self.update()

    def render_pygame(self, surface, x: int, y: int):
        """Render to Pygame surface at position."""
        if not _PYGAME_AVAILABLE:
            return

        import pygame

        center = (x + self.width // 2, y + self.height // 2)
        radius = min(self.width, self.height) // 2 - 2

        if self._on:
            c = self.led_color.to_rgb()
            # Glow effect
            for r in range(radius + 5, radius - 1, -1):
                alpha = int(255 * (1 - (r - radius) / 6))
                glow_surface = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surface, (*c, alpha), (r, r), r)
                surface.blit(glow_surface, (center[0] - r, center[1] - r))
            pygame.draw.circle(surface, c, center, radius)
        else:
            c = tuple(v // 4 for v in self.led_color.to_rgb())
            pygame.draw.circle(surface, c, center, radius)

        # Border
        pygame.draw.circle(surface, (40, 40, 40), center, radius, 2)


class LEDArrayWidget(DisplayWidget):
    """Array of LEDs (e.g., LED bar graph)."""

    def __init__(self, count: int = 8, colors: List[Color] = None,
                 orientation: str = "horizontal", led_size: int = 15,
                 backend: GUIBackend = None):
        self.count = count
        self.orientation = orientation
        self.led_size = led_size

        if orientation == "horizontal":
            width = count * (led_size + 2) + 2
            height = led_size + 4
        else:
            width = led_size + 4
            height = count * (led_size + 2) + 2

        super().__init__(width, height, backend)

        # Default: green/yellow/red bar graph
        if colors is None:
            colors = []
            for i in range(count):
                ratio = i / count
                if ratio < 0.6:
                    colors.append(Color.GREEN)
                elif ratio < 0.8:
                    colors.append(Color.YELLOW)
                else:
                    colors.append(Color.RED)

        self.leds = [LEDWidget(c, led_size, backend) for c in colors]
        self._value = 0  # 0 to count

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, val: int):
        self._value = max(0, min(self.count, val))
        for i, led in enumerate(self.leds):
            led.on = i < self._value
        self.update()

    def set_binary(self, bits: int):
        """Set LEDs from binary value."""
        for i, led in enumerate(self.leds):
            led.on = bool(bits & (1 << i))
        self.update()

    def update(self):
        """Update display."""
        for led in self.leds:
            led.update()

    def clear(self, color: Color = None):
        """Turn off all LEDs."""
        for led in self.leds:
            led.on = False
        self.update()


class RGBLEDWidget(DisplayWidget):
    """RGB LED widget."""

    def __init__(self, size: int = 25, backend: GUIBackend = None):
        super().__init__(size, size, backend)
        self._r = 0
        self._g = 0
        self._b = 0

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt RGB LED widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtGui import QPainter, QBrush, QPen, QColor, QRadialGradient
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtGui import QPainter, QBrush, QPen, QColor, QRadialGradient

        parent = self

        class QtRGBLED(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)

            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)

                r, g, b = parent._r, parent._g, parent._b
                brightness = max(r, g, b)

                if brightness > 0:
                    gradient = QRadialGradient(
                        parent.width / 2, parent.height / 2,
                        parent.width / 2
                    )
                    gradient.setColorAt(0, QColor(255, 255, 255, brightness))
                    gradient.setColorAt(0.3, QColor(r, g, b, 255))
                    gradient.setColorAt(1, QColor(r // 2, g // 2, b // 2, 255))
                    painter.setBrush(QBrush(gradient))
                else:
                    painter.setBrush(QBrush(QColor(30, 30, 30)))

                painter.setPen(QPen(QColor(40, 40, 40), 2))
                margin = 2
                painter.drawEllipse(
                    margin, margin,
                    parent.width - 2 * margin,
                    parent.height - 2 * margin
                )

        self._native_widget = QtRGBLED()

    def set_color(self, r: int, g: int, b: int):
        """Set RGB color (0-255 each)."""
        self._r = max(0, min(255, r))
        self._g = max(0, min(255, g))
        self._b = max(0, min(255, b))
        self.update()

    def set_color_object(self, color: Color):
        """Set color from Color object."""
        self.set_color(color.r, color.g, color.b)

    @property
    def color(self) -> Tuple[int, int, int]:
        return (self._r, self._g, self._b)

    def update(self):
        if self._native_widget:
            self._native_widget.update()

    def clear(self, color: Color = None):
        self._r = self._g = self._b = 0
        self.update()
