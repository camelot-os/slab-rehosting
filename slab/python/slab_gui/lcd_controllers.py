"""
SLAB GUI LCD Controller Emulation

Emulates popular LCD controllers used with MCUs:
- ILI9341 (320x240 TFT, SPI/Parallel)
- ILI9488 (480x320 TFT, SPI/Parallel)
- ST7735 (128x160 TFT, SPI)
- ST7789 (240x240/320x240 TFT, SPI)
- SSD1306 (128x64 OLED, I2C/SPI)

These controllers communicate via SPI/I2C and use command/data mode
controlled by the D/C (Data/Command) pin.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, Tuple
from enum import IntEnum
from dataclasses import dataclass
from .base import DisplayWidget, Color, GUIBackend, _QT_AVAILABLE
from .framebuffer import PixelFormat


class LCDCommand(IntEnum):
    """Common LCD controller commands."""
    NOP = 0x00
    SWRESET = 0x01
    SLPIN = 0x10
    SLPOUT = 0x11
    PTLON = 0x12
    NORON = 0x13
    INVOFF = 0x20
    INVON = 0x21
    DISPOFF = 0x28
    DISPON = 0x29
    CASET = 0x2A  # Column Address Set
    RASET = 0x2B  # Row Address Set (PASET)
    RAMWR = 0x2C  # Memory Write
    RAMRD = 0x2E  # Memory Read
    MADCTL = 0x36  # Memory Access Control
    COLMOD = 0x3A  # Interface Pixel Format


class MADCTLBits(IntEnum):
    """Memory Access Control bits."""
    MY = 0x80   # Row Address Order
    MX = 0x40   # Column Address Order
    MV = 0x20   # Row/Column Exchange
    ML = 0x10   # Vertical Refresh Order
    BGR = 0x08  # RGB-BGR Order
    MH = 0x04   # Horizontal Refresh Order


@dataclass
class LCDConfig:
    """LCD controller configuration."""
    width: int
    height: int
    pixel_format: PixelFormat = PixelFormat.RGB565
    rotation: int = 0
    inverted: bool = False
    bgr_order: bool = False


class LCDControllerBase:
    """
    Base class for LCD controller emulation.

    Implements the command/data interface used by SPI LCD displays.
    """

    def __init__(self, width: int, height: int, name: str = "LCD"):
        self.width = width
        self.height = height
        self.name = name

        # Display state
        self.display_on = False
        self.sleep_mode = True
        self.inverted = False
        self.pixel_format = PixelFormat.RGB565
        self.madctl = 0x00

        # Window position
        self.col_start = 0
        self.col_end = width - 1
        self.row_start = 0
        self.row_end = height - 1
        self.col_ptr = 0
        self.row_ptr = 0

        # Framebuffer
        self._bpp = 2  # RGB565 default
        self._buffer = bytearray(width * height * self._bpp)

        # Command state
        self._in_command = False
        self._current_cmd = 0
        self._cmd_params = bytearray()
        self._expected_params = 0

        # Callbacks
        self.on_update: Optional[Callable[[], None]] = None

    def reset(self):
        """Software reset."""
        self.display_on = False
        self.sleep_mode = True
        self.inverted = False
        self.madctl = 0x00
        self.col_start = 0
        self.col_end = self.width - 1
        self.row_start = 0
        self.row_end = self.height - 1
        self.col_ptr = 0
        self.row_ptr = 0
        self._buffer = bytearray(len(self._buffer))

    def command(self, cmd: int):
        """
        Receive command byte (D/C pin low).

        Args:
            cmd: Command byte
        """
        self._in_command = True
        self._current_cmd = cmd
        self._cmd_params = bytearray()

        # Determine expected parameters
        self._expected_params = self._get_param_count(cmd)

        if self._expected_params == 0:
            self._execute_command()

    def data(self, byte: int):
        """
        Receive data byte (D/C pin high).

        Args:
            byte: Data byte
        """
        if self._in_command:
            # Collecting command parameters
            self._cmd_params.append(byte)
            if len(self._cmd_params) >= self._expected_params:
                self._execute_command()
        else:
            # Direct framebuffer write (after RAMWR)
            self._write_pixel_byte(byte)

    def data_bytes(self, data: bytes):
        """
        Receive multiple data bytes.

        Args:
            data: Data bytes
        """
        for b in data:
            self.data(b)

    def _get_param_count(self, cmd: int) -> int:
        """Get number of parameters for command."""
        param_counts = {
            LCDCommand.CASET: 4,
            LCDCommand.RASET: 4,
            LCDCommand.MADCTL: 1,
            LCDCommand.COLMOD: 1,
        }
        return param_counts.get(cmd, 0)

    def _execute_command(self):
        """Execute the current command."""
        cmd = self._current_cmd
        params = self._cmd_params

        if cmd == LCDCommand.NOP:
            pass
        elif cmd == LCDCommand.SWRESET:
            self.reset()
        elif cmd == LCDCommand.SLPIN:
            self.sleep_mode = True
        elif cmd == LCDCommand.SLPOUT:
            self.sleep_mode = False
        elif cmd == LCDCommand.INVOFF:
            self.inverted = False
        elif cmd == LCDCommand.INVON:
            self.inverted = True
        elif cmd == LCDCommand.DISPOFF:
            self.display_on = False
        elif cmd == LCDCommand.DISPON:
            self.display_on = True
        elif cmd == LCDCommand.CASET and len(params) >= 4:
            self.col_start = (params[0] << 8) | params[1]
            self.col_end = (params[2] << 8) | params[3]
            self.col_ptr = self.col_start
        elif cmd == LCDCommand.RASET and len(params) >= 4:
            self.row_start = (params[0] << 8) | params[1]
            self.row_end = (params[2] << 8) | params[3]
            self.row_ptr = self.row_start
        elif cmd == LCDCommand.RAMWR:
            self._in_command = False  # Switch to data mode
            self.col_ptr = self.col_start
            self.row_ptr = self.row_start
        elif cmd == LCDCommand.MADCTL and len(params) >= 1:
            self.madctl = params[0]
        elif cmd == LCDCommand.COLMOD and len(params) >= 1:
            self._set_pixel_format(params[0])

        self._in_command = True

    def _set_pixel_format(self, colmod: int):
        """Set pixel format from COLMOD value."""
        fmt_bits = colmod & 0x07
        if fmt_bits == 0x05:  # 16-bit RGB565
            self.pixel_format = PixelFormat.RGB565
            self._bpp = 2
        elif fmt_bits == 0x06:  # 18-bit RGB666 (packed as 24-bit)
            self.pixel_format = PixelFormat.RGB888
            self._bpp = 3

    def _write_pixel_byte(self, byte: int):
        """Write a byte to framebuffer."""
        # This is called in sequence after RAMWR
        # For RGB565, we need 2 bytes per pixel
        x = self.col_ptr
        y = self.row_ptr

        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * self._bpp

            # Handle partial pixel writes for RGB565
            if not hasattr(self, '_pixel_buffer'):
                self._pixel_buffer = bytearray()

            self._pixel_buffer.append(byte)

            if len(self._pixel_buffer) >= self._bpp:
                # Write complete pixel
                for i, b in enumerate(self._pixel_buffer[:self._bpp]):
                    if offset + i < len(self._buffer):
                        self._buffer[offset + i] = b
                self._pixel_buffer = bytearray()

                # Advance to next pixel
                self._advance_pixel()

    def _advance_pixel(self):
        """Advance to next pixel position."""
        self.col_ptr += 1
        if self.col_ptr > self.col_end:
            self.col_ptr = self.col_start
            self.row_ptr += 1
            if self.row_ptr > self.row_end:
                self.row_ptr = self.row_start
                # Notify update complete
                if self.on_update:
                    self.on_update()

    def get_buffer(self) -> bytes:
        """Get framebuffer data."""
        return bytes(self._buffer)

    def get_pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        """Get pixel RGB value."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return (0, 0, 0)

        offset = (y * self.width + x) * self._bpp

        if self.pixel_format == PixelFormat.RGB565:
            lo = self._buffer[offset]
            hi = self._buffer[offset + 1]
            pixel = (hi << 8) | lo
            r = ((pixel >> 11) & 0x1F) << 3
            g = ((pixel >> 5) & 0x3F) << 2
            b = (pixel & 0x1F) << 3
        elif self.pixel_format == PixelFormat.RGB888:
            r = self._buffer[offset]
            g = self._buffer[offset + 1]
            b = self._buffer[offset + 2]
        else:
            r = g = b = 0

        # Handle BGR order
        if self.madctl & MADCTLBits.BGR:
            r, b = b, r

        return (r, g, b)


class ILI9341Controller(LCDControllerBase):
    """
    ILI9341 LCD Controller (320x240 TFT).

    Common display controller for 2.4" and 2.8" TFT displays.
    Supports SPI and 8/16-bit parallel interface.
    """

    # ILI9341 specific commands
    CMD_PWCTR1 = 0xC0
    CMD_PWCTR2 = 0xC1
    CMD_VMCTR1 = 0xC5
    CMD_VMCTR2 = 0xC7
    CMD_FRMCTR1 = 0xB1

    def __init__(self):
        super().__init__(320, 240, "ILI9341")


class ILI9488Controller(LCDControllerBase):
    """
    ILI9488 LCD Controller (480x320 TFT).

    3.5" TFT display controller with higher resolution.
    """

    def __init__(self):
        super().__init__(480, 320, "ILI9488")
        self._bpp = 3  # ILI9488 typically uses 18-bit color
        self.pixel_format = PixelFormat.RGB888
        self._buffer = bytearray(self.width * self.height * self._bpp)


class ST7735Controller(LCDControllerBase):
    """
    ST7735 LCD Controller (128x160 TFT).

    Small 1.8" TFT display, common in hobby projects.
    """

    def __init__(self, width: int = 128, height: int = 160):
        super().__init__(width, height, "ST7735")


class ST7789Controller(LCDControllerBase):
    """
    ST7789 LCD Controller (240x240 or 240x320 TFT).

    Popular IPS display controller with good viewing angles.
    """

    def __init__(self, width: int = 240, height: int = 240):
        super().__init__(width, height, "ST7789")


class LCDControllerWidget(DisplayWidget):
    """
    GUI Widget for LCD Controller displays.

    Wraps an LCD controller and provides Qt/Pygame rendering.
    """

    def __init__(self, controller: LCDControllerBase,
                 scale: int = 2, backend: GUIBackend = None):
        self.controller = controller
        self.scale = scale

        super().__init__(
            controller.width * scale,
            controller.height * scale,
            backend
        )

        # Connect controller update to widget refresh
        self.controller.on_update = self._on_controller_update

        self._create_native()

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt widget for LCD display."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtGui import QPainter, QImage, QColor
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtGui import QPainter, QImage, QColor
            from PyQt6.QtCore import Qt

        parent = self

        class QtLCDWidget(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)
                self._image = None

            def paintEvent(self, event):
                painter = QPainter(self)

                # Draw border
                painter.setPen(QColor(60, 60, 60))
                painter.drawRect(0, 0, parent.width - 1, parent.height - 1)

                if not parent.controller.display_on:
                    painter.fillRect(1, 1, parent.width - 2, parent.height - 2,
                                    QColor(20, 20, 20))
                    return

                if self._image:
                    scaled = self._image.scaled(
                        parent.width, parent.height,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation
                    )
                    painter.drawImage(0, 0, scaled)

            def update_image(self):
                """Update image from controller buffer."""
                ctrl = parent.controller
                data = ctrl.get_buffer()

                if ctrl.pixel_format == PixelFormat.RGB565:
                    # Convert RGB565 to RGB888 for Qt
                    rgb_data = bytearray(ctrl.width * ctrl.height * 3)
                    for i in range(0, len(data), 2):
                        if i + 1 < len(data):
                            pixel = data[i] | (data[i + 1] << 8)
                            r = ((pixel >> 11) & 0x1F) << 3
                            g = ((pixel >> 5) & 0x3F) << 2
                            b = (pixel & 0x1F) << 3
                            idx = (i // 2) * 3
                            rgb_data[idx] = r
                            rgb_data[idx + 1] = g
                            rgb_data[idx + 2] = b
                    self._image = QImage(
                        bytes(rgb_data), ctrl.width, ctrl.height,
                        ctrl.width * 3, QImage.Format.Format_RGB888
                    )
                elif ctrl.pixel_format == PixelFormat.RGB888:
                    self._image = QImage(
                        data, ctrl.width, ctrl.height,
                        ctrl.width * 3, QImage.Format.Format_RGB888
                    )

                self.update()

        self._native_widget = QtLCDWidget()

    def _on_controller_update(self):
        """Called when controller buffer is updated."""
        if hasattr(self._native_widget, 'update_image'):
            self._native_widget.update_image()

    def update(self):
        """Update display."""
        if self._native_widget:
            if hasattr(self._native_widget, 'update_image'):
                self._native_widget.update_image()
            else:
                self._native_widget.update()

    def clear(self, color: Color = None):
        """Clear display."""
        self.controller.reset()
        self.update()


class LCDFramebufferBridge:
    """
    Bridge between LCD controller and FramebufferWidget.

    Connects LCD controller output to a FramebufferWidget for display,
    allowing the same framebuffer to be used for different LCD controllers
    or to share framebuffer with SHM for remote display.
    """

    def __init__(self, controller: LCDControllerBase,
                 framebuffer: 'FramebufferWidget' = None):
        """
        Create bridge between LCD controller and framebuffer.

        Args:
            controller: LCD controller to bridge
            framebuffer: FramebufferWidget to display on (created if None)
        """
        from .framebuffer import FramebufferWidget

        self.controller = controller

        # Create or use provided framebuffer
        if framebuffer is None:
            self.framebuffer = FramebufferWidget(
                fb_width=controller.width,
                fb_height=controller.height,
                pixel_format=controller.pixel_format
            )
            self._owns_framebuffer = True
        else:
            self.framebuffer = framebuffer
            self._owns_framebuffer = False

        # Connect controller update to framebuffer
        controller.on_update = self._sync_buffer

    def _sync_buffer(self):
        """Sync controller buffer to framebuffer."""
        data = self.controller.get_buffer()
        self.framebuffer.set_buffer(data)

    def get_widget(self):
        """Get the framebuffer widget for display."""
        return self.framebuffer._native_widget

    @property
    def widget(self):
        """Alias for get_widget."""
        return self.get_widget()


# Factory function
def create_lcd_widget(controller_type: str, scale: int = 2,
                      backend: GUIBackend = None, **kwargs) -> LCDControllerWidget:
    """
    Create LCD controller widget.

    Args:
        controller_type: Controller type ("ILI9341", "ILI9488", "ST7735", "ST7789")
        scale: Display scale factor
        backend: GUI backend

    Returns:
        LCDControllerWidget instance
    """
    controllers = {
        'ILI9341': ILI9341Controller,
        'ILI9488': ILI9488Controller,
        'ST7735': lambda: ST7735Controller(**kwargs),
        'ST7789': lambda: ST7789Controller(**kwargs),
    }

    if controller_type not in controllers:
        raise ValueError(f"Unknown controller type: {controller_type}")

    ctor = controllers[controller_type]
    if callable(ctor) and not isinstance(ctor, type):
        controller = ctor()
    else:
        controller = ctor()

    return LCDControllerWidget(controller, scale, backend)
