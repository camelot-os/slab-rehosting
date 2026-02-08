"""
SLAB GUI Analog Input/Output Widgets

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable
from .base import InputWidget, DisplayWidget, Color, GUIBackend, _QT_AVAILABLE


class ADCSliderWidget(InputWidget):
    """
    ADC input slider widget.

    Simulates analog input from potentiometer, sensor, etc.
    """

    def __init__(self, min_value: int = 0, max_value: int = 4095,
                 width: int = 200, height: int = 50,
                 orientation: str = "horizontal",
                 label: str = "ADC",
                 backend: GUIBackend = None):
        super().__init__(backend)

        self._min_value = min_value
        self._max_value = max_value
        self.width = width
        self.height = height
        self.orientation = orientation
        self.label = label

        self._value = min_value

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt slider widget."""
        try:
            from PySide6.QtWidgets import QWidget, QSlider, QLabel, QVBoxLayout, QHBoxLayout
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget, QSlider, QLabel, QVBoxLayout, QHBoxLayout
            from PyQt6.QtCore import Qt

        parent = self

        container = QWidget()

        # Create slider
        if self.orientation == "horizontal":
            slider = QSlider(Qt.Orientation.Horizontal)
            layout = QVBoxLayout(container)
        else:
            slider = QSlider(Qt.Orientation.Vertical)
            layout = QHBoxLayout(container)

        slider.setMinimum(self._min_value)
        slider.setMaximum(self._max_value)
        slider.setValue(self._value)

        # Labels
        name_label = QLabel(self.label)
        self._value_label = QLabel(str(self._value))

        def on_slider_change(value):
            parent._value = value
            self._value_label.setText(str(value))
            if parent.on_change:
                parent.on_change(value)

        slider.valueChanged.connect(on_slider_change)

        layout.addWidget(name_label)
        layout.addWidget(slider)
        layout.addWidget(self._value_label)

        self._native_widget = container
        self._slider = slider

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, val: int):
        self._value = max(self._min_value, min(self._max_value, val))
        if hasattr(self, '_slider'):
            self._slider.setValue(self._value)
        self.update()

    def set_voltage(self, voltage: float, vref: float = 3.3):
        """Set value from voltage."""
        if vref > 0:
            ratio = voltage / vref
            self.value = int(ratio * self._max_value)

    def get_voltage(self, vref: float = 3.3) -> float:
        """Get voltage value."""
        return (self._value / self._max_value) * vref

    def update(self):
        if hasattr(self, '_value_label'):
            self._value_label.setText(str(self._value))


class DACDisplayWidget(DisplayWidget):
    """
    DAC output display widget.

    Shows current DAC output value as progress bar and voltage.
    """

    def __init__(self, min_value: int = 0, max_value: int = 4095,
                 width: int = 200, height: int = 50,
                 label: str = "DAC",
                 vref: float = 3.3,
                 backend: GUIBackend = None):
        super().__init__(width, height, backend)

        self.min_value = min_value
        self.max_value = max_value
        self.label = label
        self.vref = vref

        self._value = min_value

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt DAC display widget."""
        try:
            from PySide6.QtWidgets import QWidget, QProgressBar, QLabel, QVBoxLayout
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget, QProgressBar, QLabel, QVBoxLayout
            from PyQt6.QtCore import Qt

        parent = self

        container = QWidget()
        layout = QVBoxLayout(container)

        # Label
        name_label = QLabel(self.label)

        # Progress bar
        progress = QProgressBar()
        progress.setMinimum(self.min_value)
        progress.setMaximum(self.max_value)
        progress.setValue(self._value)
        progress.setTextVisible(False)

        # Value label
        voltage = (self._value / self.max_value) * self.vref
        self._value_label = QLabel(f"{self._value} ({voltage:.3f}V)")

        layout.addWidget(name_label)
        layout.addWidget(progress)
        layout.addWidget(self._value_label)

        self._native_widget = container
        self._progress = progress

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, val: int):
        self._value = max(self.min_value, min(self.max_value, val))
        self.update()

    def set_voltage(self, voltage: float):
        """Set value from voltage."""
        if self.vref > 0:
            ratio = voltage / self.vref
            self.value = int(ratio * self.max_value)

    def get_voltage(self) -> float:
        """Get voltage value."""
        return (self._value / self.max_value) * self.vref

    def update(self):
        if hasattr(self, '_progress'):
            self._progress.setValue(self._value)
        if hasattr(self, '_value_label'):
            voltage = (self._value / self.max_value) * self.vref
            self._value_label.setText(f"{self._value} ({voltage:.3f}V)")

    def clear(self, color: Color = None):
        self._value = self.min_value
        self.update()


class PotentiometerWidget(InputWidget):
    """
    Rotary potentiometer widget.

    Visual dial for analog input.
    """

    def __init__(self, min_value: int = 0, max_value: int = 4095,
                 size: int = 80,
                 label: str = "POT",
                 backend: GUIBackend = None):
        super().__init__(backend)

        self._min_value = min_value
        self._max_value = max_value
        self.size = size
        self.label = label

        self._value = min_value
        self._angle = 0  # -135 to +135 degrees

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt potentiometer widget."""
        try:
            from PySide6.QtWidgets import QWidget, QDial, QLabel, QVBoxLayout
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget, QDial, QLabel, QVBoxLayout
            from PyQt6.QtCore import Qt

        parent = self

        container = QWidget()
        layout = QVBoxLayout(container)

        # Label
        name_label = QLabel(self.label)
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Dial
        dial = QDial()
        dial.setMinimum(self._min_value)
        dial.setMaximum(self._max_value)
        dial.setValue(self._value)
        dial.setFixedSize(self.size, self.size)
        dial.setNotchesVisible(True)

        # Value label
        self._value_label = QLabel(str(self._value))
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def on_dial_change(value):
            parent._value = value
            self._value_label.setText(str(value))
            if parent.on_change:
                parent.on_change(value)

        dial.valueChanged.connect(on_dial_change)

        layout.addWidget(name_label)
        layout.addWidget(dial, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._value_label)

        self._native_widget = container
        self._dial = dial

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, val: int):
        self._value = max(self._min_value, min(self._max_value, val))
        if hasattr(self, '_dial'):
            self._dial.setValue(self._value)
        self.update()

    def update(self):
        if hasattr(self, '_value_label'):
            self._value_label.setText(str(self._value))
