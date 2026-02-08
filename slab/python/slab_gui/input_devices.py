"""
SLAB GUI Input Device Emulation

Provides input device emulation for:
- Touch screen (mouse capture when over display)
- Keyboard (direct input or USB HID)
- Buttons and switches
- Rotary encoder

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List, Tuple
from enum import IntEnum, IntFlag
from dataclasses import dataclass
from .base import InputWidget, GUIBackend, _QT_AVAILABLE


class TouchEvent(IntEnum):
    """Touch event types."""
    PRESS = 0
    RELEASE = 1
    MOVE = 2


class KeyModifiers(IntFlag):
    """Keyboard modifiers."""
    NONE = 0
    SHIFT = 1 << 0
    CTRL = 1 << 1
    ALT = 1 << 2
    META = 1 << 3
    CAPSLOCK = 1 << 4
    NUMLOCK = 1 << 5


@dataclass
class TouchPoint:
    """Touch point data."""
    x: int
    y: int
    pressure: int = 255
    id: int = 0


@dataclass
class KeyEvent:
    """Keyboard event data."""
    key: int          # Key code
    char: str         # Character (if printable)
    pressed: bool     # True if key pressed, False if released
    modifiers: KeyModifiers = KeyModifiers.NONE


class TouchScreenWidget(InputWidget):
    """
    Touch screen input widget.

    Captures mouse events when cursor is over the display and converts
    them to touch events. Supports:
    - Single touch
    - Multi-touch (if Qt supports it)
    - Pressure (simulated from mouse buttons)

    Similar to VM mouse capture but automatic when over display.
    """

    def __init__(self, width: int = 320, height: int = 240,
                 grab_on_enter: bool = True,
                 backend: GUIBackend = None):
        super().__init__(backend)

        self.width = width
        self.height = height
        self.grab_on_enter = grab_on_enter

        # Touch state
        self._touch_points: List[TouchPoint] = []
        self._grabbed = False

        # Calibration (for resistive touch)
        self.cal_x_min = 0
        self.cal_x_max = width
        self.cal_y_min = 0
        self.cal_y_max = height
        self.invert_x = False
        self.invert_y = False
        self.swap_xy = False

        # Callbacks
        self.on_touch: Optional[Callable[[TouchEvent, TouchPoint], None]] = None
        self.on_touch_multi: Optional[Callable[[List[TouchPoint]], None]] = None

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt touch overlay widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtCore import Qt, QEvent
            from PySide6.QtGui import QCursor, QMouseEvent, QTouchEvent
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtCore import Qt, QEvent
            from PyQt6.QtGui import QCursor, QMouseEvent, QTouchEvent

        parent = self

        class QtTouchWidget(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)
                self.setMouseTracking(True)
                self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
                self._pressed = False

            def enterEvent(self, event):
                if parent.grab_on_enter:
                    parent._grabbed = True
                    self.setCursor(Qt.CursorShape.BlankCursor)

            def leaveEvent(self, event):
                if parent._grabbed:
                    parent._grabbed = False
                    self.unsetCursor()
                    # Release any active touch
                    if parent._touch_points:
                        for tp in parent._touch_points:
                            parent._emit_touch(TouchEvent.RELEASE, tp)
                        parent._touch_points.clear()

            def mousePressEvent(self, event):
                pos = event.position()
                tp = parent._map_touch(int(pos.x()), int(pos.y()))
                tp.pressure = 255
                parent._touch_points = [tp]
                parent._emit_touch(TouchEvent.PRESS, tp)
                self._pressed = True

            def mouseReleaseEvent(self, event):
                if parent._touch_points:
                    tp = parent._touch_points[0]
                    parent._emit_touch(TouchEvent.RELEASE, tp)
                    parent._touch_points.clear()
                self._pressed = False

            def mouseMoveEvent(self, event):
                if self._pressed and parent._touch_points:
                    pos = event.position()
                    tp = parent._map_touch(int(pos.x()), int(pos.y()))
                    tp.pressure = 255
                    parent._touch_points = [tp]
                    parent._emit_touch(TouchEvent.MOVE, tp)

            def event(self, event):
                """Handle touch events for multi-touch support."""
                if event.type() == QEvent.Type.TouchBegin:
                    touch_event = event
                    parent._handle_touch_event(touch_event)
                    return True
                elif event.type() == QEvent.Type.TouchUpdate:
                    touch_event = event
                    parent._handle_touch_event(touch_event)
                    return True
                elif event.type() == QEvent.Type.TouchEnd:
                    touch_event = event
                    parent._handle_touch_event(touch_event)
                    return True
                return super().event(event)

        self._native_widget = QtTouchWidget()

    def _map_touch(self, x: int, y: int) -> TouchPoint:
        """Map screen coordinates to touch coordinates with calibration."""
        # Apply calibration
        touch_x = int((x - self.cal_x_min) / (self.cal_x_max - self.cal_x_min) * self.width)
        touch_y = int((y - self.cal_y_min) / (self.cal_y_max - self.cal_y_min) * self.height)

        # Apply inversions
        if self.invert_x:
            touch_x = self.width - touch_x
        if self.invert_y:
            touch_y = self.height - touch_y

        # Apply swap
        if self.swap_xy:
            touch_x, touch_y = touch_y, touch_x

        # Clamp
        touch_x = max(0, min(self.width - 1, touch_x))
        touch_y = max(0, min(self.height - 1, touch_y))

        return TouchPoint(touch_x, touch_y)

    def _emit_touch(self, event_type: TouchEvent, point: TouchPoint):
        """Emit touch event."""
        if self.on_touch:
            self.on_touch(event_type, point)
        if self.on_change:
            self.on_change((event_type, point))

    def _handle_touch_event(self, event):
        """Handle Qt touch event for multi-touch."""
        try:
            from PySide6.QtCore import QEventPoint
        except ImportError:
            from PyQt6.QtCore import QEventPoint

        points = []
        for tp in event.points():
            pos = tp.position()
            mapped = self._map_touch(int(pos.x()), int(pos.y()))
            mapped.id = tp.id()
            mapped.pressure = int(tp.pressure() * 255)
            points.append(mapped)

        self._touch_points = points

        if self.on_touch_multi:
            self.on_touch_multi(points)

    def get_touch_points(self) -> List[TouchPoint]:
        """Get current touch points."""
        return self._touch_points.copy()

    def is_touched(self) -> bool:
        """Check if screen is being touched."""
        return len(self._touch_points) > 0

    def set_calibration(self, x_min: int, x_max: int, y_min: int, y_max: int):
        """Set touch calibration."""
        self.cal_x_min = x_min
        self.cal_x_max = x_max
        self.cal_y_min = y_min
        self.cal_y_max = y_max


class KeyboardWidget(InputWidget):
    """
    Keyboard input widget.

    Captures keyboard input and converts to key events.
    Can be used with:
    - Direct key codes (for MCU GPIO matrix)
    - USB HID key codes (for USB keyboard emulation)
    """

    # USB HID key codes (subset)
    HID_KEY_A = 0x04
    HID_KEY_Z = 0x1D
    HID_KEY_1 = 0x1E
    HID_KEY_0 = 0x27
    HID_KEY_ENTER = 0x28
    HID_KEY_ESCAPE = 0x29
    HID_KEY_BACKSPACE = 0x2A
    HID_KEY_TAB = 0x2B
    HID_KEY_SPACE = 0x2C
    HID_KEY_F1 = 0x3A
    HID_KEY_F12 = 0x45

    def __init__(self, capture_focus: bool = True,
                 emit_hid: bool = False,
                 backend: GUIBackend = None):
        super().__init__(backend)

        self.capture_focus = capture_focus
        self.emit_hid = emit_hid

        # Key state
        self._pressed_keys: set = set()
        self._modifiers = KeyModifiers.NONE

        # Callbacks
        self.on_key: Optional[Callable[[KeyEvent], None]] = None
        self.on_hid_report: Optional[Callable[[bytes], None]] = None

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt keyboard capture widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtCore import Qt

        parent = self

        class QtKeyboardWidget(QWidget):
            def __init__(self):
                super().__init__()
                self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                if parent.capture_focus:
                    self.setFocus()

            def keyPressEvent(self, event):
                parent._handle_key(event, True)

            def keyReleaseEvent(self, event):
                parent._handle_key(event, False)

        self._native_widget = QtKeyboardWidget()

    def _handle_key(self, event, pressed: bool):
        """Handle Qt key event."""
        try:
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtCore import Qt

        key = event.key()
        text = event.text()

        # Update modifiers
        mods = KeyModifiers.NONE
        qt_mods = event.modifiers()
        if qt_mods & Qt.KeyboardModifier.ShiftModifier:
            mods |= KeyModifiers.SHIFT
        if qt_mods & Qt.KeyboardModifier.ControlModifier:
            mods |= KeyModifiers.CTRL
        if qt_mods & Qt.KeyboardModifier.AltModifier:
            mods |= KeyModifiers.ALT
        if qt_mods & Qt.KeyboardModifier.MetaModifier:
            mods |= KeyModifiers.META

        self._modifiers = mods

        # Track pressed keys
        if pressed:
            self._pressed_keys.add(key)
        else:
            self._pressed_keys.discard(key)

        # Create key event
        key_event = KeyEvent(
            key=key,
            char=text if len(text) == 1 else '',
            pressed=pressed,
            modifiers=mods
        )

        # Emit callbacks
        if self.on_key:
            self.on_key(key_event)

        if self.emit_hid and self.on_hid_report:
            report = self._make_hid_report()
            self.on_hid_report(report)

        if self.on_change:
            self.on_change(key_event)

    def _qt_key_to_hid(self, qt_key: int) -> int:
        """Convert Qt key code to USB HID key code."""
        try:
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtCore import Qt

        # Letter keys A-Z
        if Qt.Key.Key_A <= qt_key <= Qt.Key.Key_Z:
            return self.HID_KEY_A + (qt_key - Qt.Key.Key_A)

        # Number keys 1-9, 0
        if Qt.Key.Key_1 <= qt_key <= Qt.Key.Key_9:
            return self.HID_KEY_1 + (qt_key - Qt.Key.Key_1)
        if qt_key == Qt.Key.Key_0:
            return self.HID_KEY_0

        # Special keys
        special = {
            Qt.Key.Key_Return: self.HID_KEY_ENTER,
            Qt.Key.Key_Enter: self.HID_KEY_ENTER,
            Qt.Key.Key_Escape: self.HID_KEY_ESCAPE,
            Qt.Key.Key_Backspace: self.HID_KEY_BACKSPACE,
            Qt.Key.Key_Tab: self.HID_KEY_TAB,
            Qt.Key.Key_Space: self.HID_KEY_SPACE,
        }

        return special.get(qt_key, 0)

    def _make_hid_report(self) -> bytes:
        """Create USB HID keyboard report."""
        # Standard HID keyboard report: [modifier, reserved, key1-6]
        modifier = 0
        if self._modifiers & KeyModifiers.CTRL:
            modifier |= 0x01
        if self._modifiers & KeyModifiers.SHIFT:
            modifier |= 0x02
        if self._modifiers & KeyModifiers.ALT:
            modifier |= 0x04
        if self._modifiers & KeyModifiers.META:
            modifier |= 0x08

        keys = []
        for qt_key in list(self._pressed_keys)[:6]:
            hid_key = self._qt_key_to_hid(qt_key)
            if hid_key:
                keys.append(hid_key)

        # Pad to 6 keys
        while len(keys) < 6:
            keys.append(0)

        return bytes([modifier, 0] + keys)

    def get_pressed_keys(self) -> set:
        """Get currently pressed keys."""
        return self._pressed_keys.copy()

    def get_modifiers(self) -> KeyModifiers:
        """Get current modifiers."""
        return self._modifiers


class ButtonWidget(InputWidget):
    """
    Simple button widget.

    Represents a physical button (momentary switch).
    """

    def __init__(self, label: str = "Button", size: int = 40,
                 backend: GUIBackend = None):
        super().__init__(backend)

        self.label = label
        self.size = size
        self._pressed = False

        # Callbacks
        self.on_press: Optional[Callable[[], None]] = None
        self.on_release: Optional[Callable[[], None]] = None

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt button widget."""
        try:
            from PySide6.QtWidgets import QPushButton
        except ImportError:
            from PyQt6.QtWidgets import QPushButton

        parent = self

        button = QPushButton(self.label)
        button.setFixedSize(self.size * 2, self.size)

        def on_pressed():
            parent._pressed = True
            if parent.on_press:
                parent.on_press()
            if parent.on_change:
                parent.on_change(True)

        def on_released():
            parent._pressed = False
            if parent.on_release:
                parent.on_release()
            if parent.on_change:
                parent.on_change(False)

        button.pressed.connect(on_pressed)
        button.released.connect(on_released)

        self._native_widget = button

    @property
    def pressed(self) -> bool:
        """Check if button is pressed."""
        return self._pressed


class RotaryEncoderWidget(InputWidget):
    """
    Rotary encoder widget.

    Emulates a rotary encoder with:
    - Direction (CW/CCW)
    - Optional push button
    """

    def __init__(self, steps_per_rev: int = 24, has_button: bool = True,
                 backend: GUIBackend = None):
        super().__init__(backend)

        self.steps_per_rev = steps_per_rev
        self.has_button = has_button

        self._position = 0
        self._button_pressed = False

        # Callbacks
        self.on_rotate: Optional[Callable[[int], None]] = None  # Delta steps
        self.on_button: Optional[Callable[[bool], None]] = None

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt rotary encoder widget."""
        try:
            from PySide6.QtWidgets import QWidget, QDial, QPushButton, QVBoxLayout
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget, QDial, QPushButton, QVBoxLayout
            from PyQt6.QtCore import Qt

        parent = self

        container = QWidget()
        layout = QVBoxLayout(container)

        # Dial for rotation
        dial = QDial()
        dial.setMinimum(0)
        dial.setMaximum(self.steps_per_rev * 4)  # Allow multiple revolutions
        dial.setWrapping(True)
        dial.setNotchesVisible(True)
        dial.setFixedSize(80, 80)

        def on_dial_change(value):
            delta = value - parent._position
            # Handle wraparound
            if abs(delta) > self.steps_per_rev * 2:
                delta = -delta
            parent._position = value
            if parent.on_rotate:
                parent.on_rotate(delta)
            if parent.on_change:
                parent.on_change(('rotate', delta))

        dial.valueChanged.connect(on_dial_change)

        layout.addWidget(dial, alignment=Qt.AlignmentFlag.AlignCenter)

        # Button if present
        if self.has_button:
            button = QPushButton("Press")
            button.setFixedSize(60, 30)

            def on_pressed():
                parent._button_pressed = True
                if parent.on_button:
                    parent.on_button(True)

            def on_released():
                parent._button_pressed = False
                if parent.on_button:
                    parent.on_button(False)

            button.pressed.connect(on_pressed)
            button.released.connect(on_released)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignCenter)

        self._native_widget = container

    @property
    def position(self) -> int:
        """Get current position."""
        return self._position

    @property
    def button_pressed(self) -> bool:
        """Check if button is pressed."""
        return self._button_pressed
