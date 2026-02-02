"""
SLAB GUI Base Classes

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Optional, Callable, Tuple
import logging


class GUIBackend(Enum):
    """Available GUI backends."""
    QT = auto()
    PYGAME = auto()
    TERMINAL = auto()  # Text-only fallback


# Try to detect available backends
_AVAILABLE_BACKENDS = []

try:
    from PySide6 import QtWidgets, QtCore, QtGui
    _AVAILABLE_BACKENDS.append(GUIBackend.QT)
    _QT_AVAILABLE = True
except ImportError:
    try:
        from PyQt6 import QtWidgets, QtCore, QtGui
        _AVAILABLE_BACKENDS.append(GUIBackend.QT)
        _QT_AVAILABLE = True
    except ImportError:
        _QT_AVAILABLE = False

try:
    import pygame
    _AVAILABLE_BACKENDS.append(GUIBackend.PYGAME)
    _PYGAME_AVAILABLE = True
except ImportError:
    _PYGAME_AVAILABLE = False

_AVAILABLE_BACKENDS.append(GUIBackend.TERMINAL)


def get_available_backends():
    """Get list of available GUI backends."""
    return _AVAILABLE_BACKENDS.copy()


def get_best_backend() -> GUIBackend:
    """Get the best available backend."""
    if GUIBackend.QT in _AVAILABLE_BACKENDS:
        return GUIBackend.QT
    if GUIBackend.PYGAME in _AVAILABLE_BACKENDS:
        return GUIBackend.PYGAME
    return GUIBackend.TERMINAL


class Color:
    """Simple color class."""

    def __init__(self, r: int, g: int, b: int, a: int = 255):
        self.r = max(0, min(255, r))
        self.g = max(0, min(255, g))
        self.b = max(0, min(255, b))
        self.a = max(0, min(255, a))

    @classmethod
    def from_hex(cls, hex_str: str) -> 'Color':
        """Create color from hex string (#RRGGBB or #RRGGBBAA)."""
        hex_str = hex_str.lstrip('#')
        if len(hex_str) == 6:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            return cls(r, g, b)
        elif len(hex_str) == 8:
            r = int(hex_str[0:2], 16)
            g = int(hex_str[2:4], 16)
            b = int(hex_str[4:6], 16)
            a = int(hex_str[6:8], 16)
            return cls(r, g, b, a)
        raise ValueError(f"Invalid hex color: {hex_str}")

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)

    def to_rgb(self) -> Tuple[int, int, int]:
        return (self.r, self.g, self.b)

    # Predefined colors
    BLACK = None
    WHITE = None
    RED = None
    GREEN = None
    BLUE = None
    YELLOW = None
    CYAN = None
    MAGENTA = None
    ORANGE = None
    GRAY = None


# Initialize predefined colors
Color.BLACK = Color(0, 0, 0)
Color.WHITE = Color(255, 255, 255)
Color.RED = Color(255, 0, 0)
Color.GREEN = Color(0, 255, 0)
Color.BLUE = Color(0, 0, 255)
Color.YELLOW = Color(255, 255, 0)
Color.CYAN = Color(0, 255, 255)
Color.MAGENTA = Color(255, 0, 255)
Color.ORANGE = Color(255, 165, 0)
Color.GRAY = Color(128, 128, 128)


class DisplayWidget(ABC):
    """Base class for display widgets."""

    def __init__(self, width: int, height: int, backend: GUIBackend = None):
        self.width = width
        self.height = height
        self.backend = backend or get_best_backend()
        self.log = logging.getLogger(self.__class__.__name__)

        self._visible = False
        self._native_widget = None

    @abstractmethod
    def update(self):
        """Update the display."""
        pass

    @abstractmethod
    def clear(self, color: Color = None):
        """Clear the display."""
        pass

    def show(self):
        """Show the widget."""
        self._visible = True

    def hide(self):
        """Hide the widget."""
        self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible


class InputWidget(ABC):
    """Base class for input widgets."""

    def __init__(self, backend: GUIBackend = None):
        self.backend = backend or get_best_backend()
        self.log = logging.getLogger(self.__class__.__name__)

        self._value = 0
        self._min_value = 0
        self._max_value = 1
        self._native_widget = None

        # Callbacks
        self.on_change: Optional[Callable[[int], None]] = None

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, val: int):
        old_val = self._value
        self._value = max(self._min_value, min(self._max_value, val))
        if self._value != old_val and self.on_change:
            self.on_change(self._value)

    @abstractmethod
    def update(self):
        """Update the widget display."""
        pass
