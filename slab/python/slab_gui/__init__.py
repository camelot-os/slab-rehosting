"""
SLAB GUI - Display and Input Mockups

Provides visual representations for:
- LCD/OLED displays (character and graphical)
- LEDs (single and arrays)
- 7-segment displays
- ADC/DAC sliders
- Buttons and switches
- Framebuffer display

Supports multiple backends:
- PySide6/PyQt6 (Qt)
- Pygame

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"

from .base import (
    GUIBackend,
    DisplayWidget,
    InputWidget,
)

from .led import (
    LEDWidget,
    LEDArrayWidget,
    RGBLEDWidget,
)

from .segment import (
    SevenSegmentWidget,
    SevenSegmentArrayWidget,
)

from .lcd import (
    CharacterLCDWidget,
    GraphicLCDWidget,
    OLEDWidget,
)

from .analog import (
    ADCSliderWidget,
    DACDisplayWidget,
    PotentiometerWidget,
)

from .framebuffer import (
    FramebufferWidget,
    FramebufferServer,
)

from .lcd_controllers import (
    LCDControllerBase,
    ILI9341Controller,
    ILI9488Controller,
    ST7735Controller,
    ST7789Controller,
    LCDControllerWidget,
    LCDFramebufferBridge,
    LCDCommand,
    create_lcd_widget,
)

from .input_devices import (
    TouchScreenWidget,
    KeyboardWidget,
    ButtonWidget,
    RotaryEncoderWidget,
    TouchEvent,
    TouchPoint,
    KeyEvent,
    KeyModifiers,
)

__all__ = [
    "__version__",
    "__author__",
    # Base
    "GUIBackend",
    "DisplayWidget",
    "InputWidget",
    # LED
    "LEDWidget",
    "LEDArrayWidget",
    "RGBLEDWidget",
    # 7-segment
    "SevenSegmentWidget",
    "SevenSegmentArrayWidget",
    # LCD
    "CharacterLCDWidget",
    "GraphicLCDWidget",
    "OLEDWidget",
    # Analog
    "ADCSliderWidget",
    "DACDisplayWidget",
    "PotentiometerWidget",
    # Framebuffer
    "FramebufferWidget",
    "FramebufferServer",
    # LCD Controllers
    "LCDControllerBase",
    "ILI9341Controller",
    "ILI9488Controller",
    "ST7735Controller",
    "ST7789Controller",
    "LCDControllerWidget",
    "LCDFramebufferBridge",
    "LCDCommand",
    "create_lcd_widget",
    # Input Devices
    "TouchScreenWidget",
    "KeyboardWidget",
    "ButtonWidget",
    "RotaryEncoderWidget",
    "TouchEvent",
    "TouchPoint",
    "KeyEvent",
    "KeyModifiers",
]
