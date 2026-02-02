"""
SLAB GUI Framebuffer Display Widget

Displays raw framebuffer data from emulated GPU or display controller.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import threading
import mmap
import socket
import struct
from typing import Optional, Callable
from enum import Enum, auto
from .base import DisplayWidget, Color, GUIBackend, _QT_AVAILABLE


class PixelFormat(Enum):
    """Framebuffer pixel formats."""
    RGB565 = auto()     # 16-bit: 5-6-5
    RGB888 = auto()     # 24-bit: 8-8-8
    RGBA8888 = auto()   # 32-bit: 8-8-8-8
    BGRA8888 = auto()   # 32-bit: 8-8-8-8 (BGR)
    MONO = auto()       # 1-bit monochrome
    GRAY8 = auto()      # 8-bit grayscale


class FramebufferWidget(DisplayWidget):
    """
    Framebuffer display widget.

    Displays raw pixel data from memory buffer.
    Can connect to shared memory or receive updates via callback.
    """

    def __init__(self, fb_width: int = 320, fb_height: int = 240,
                 pixel_format: PixelFormat = PixelFormat.RGB565,
                 scale: int = 1,
                 backend: GUIBackend = None):
        self.fb_width = fb_width
        self.fb_height = fb_height
        self.pixel_format = pixel_format
        self.scale = scale

        super().__init__(fb_width * scale, fb_height * scale, backend)

        # Calculate bytes per pixel
        self._bpp = self._get_bpp(pixel_format)
        self._stride = fb_width * self._bpp

        # Framebuffer data
        self._buffer = bytearray(fb_width * fb_height * self._bpp)

        self._create_native()

    def _get_bpp(self, fmt: PixelFormat) -> int:
        """Get bytes per pixel for format."""
        bpp_map = {
            PixelFormat.RGB565: 2,
            PixelFormat.RGB888: 3,
            PixelFormat.RGBA8888: 4,
            PixelFormat.BGRA8888: 4,
            PixelFormat.MONO: 1,  # Packed, but treat as 1 for simplicity
            PixelFormat.GRAY8: 1,
        }
        return bpp_map.get(fmt, 2)

    def _create_native(self):
        """Create native widget."""
        if self.backend == GUIBackend.QT and _QT_AVAILABLE:
            self._create_qt()

    def _create_qt(self):
        """Create Qt framebuffer widget."""
        try:
            from PySide6.QtWidgets import QWidget
            from PySide6.QtGui import QPainter, QImage, QColor
            from PySide6.QtCore import Qt
        except ImportError:
            from PyQt6.QtWidgets import QWidget
            from PyQt6.QtGui import QPainter, QImage, QColor
            from PyQt6.QtCore import Qt

        parent = self

        class QtFramebuffer(QWidget):
            def __init__(self):
                super().__init__()
                self.setFixedSize(parent.width, parent.height)
                self._image = None

            def paintEvent(self, event):
                painter = QPainter(self)

                if self._image:
                    if parent.scale > 1:
                        scaled = self._image.scaled(
                            parent.width, parent.height,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.FastTransformation
                        )
                        painter.drawImage(0, 0, scaled)
                    else:
                        painter.drawImage(0, 0, self._image)
                else:
                    painter.fillRect(0, 0, parent.width, parent.height, QColor(0, 0, 0))

            def update_image(self, data: bytes):
                """Update image from buffer data."""
                if parent.pixel_format == PixelFormat.RGB565:
                    # Convert RGB565 to RGB888
                    rgb_data = bytearray(parent.fb_width * parent.fb_height * 3)
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
                        bytes(rgb_data), parent.fb_width, parent.fb_height,
                        parent.fb_width * 3, QImage.Format.Format_RGB888
                    )
                elif parent.pixel_format == PixelFormat.RGB888:
                    self._image = QImage(
                        data, parent.fb_width, parent.fb_height,
                        parent.fb_width * 3, QImage.Format.Format_RGB888
                    )
                elif parent.pixel_format == PixelFormat.RGBA8888:
                    self._image = QImage(
                        data, parent.fb_width, parent.fb_height,
                        parent.fb_width * 4, QImage.Format.Format_RGBA8888
                    )
                elif parent.pixel_format == PixelFormat.BGRA8888:
                    self._image = QImage(
                        data, parent.fb_width, parent.fb_height,
                        parent.fb_width * 4, QImage.Format.Format_ARGB32
                    )
                elif parent.pixel_format == PixelFormat.GRAY8:
                    self._image = QImage(
                        data, parent.fb_width, parent.fb_height,
                        parent.fb_width, QImage.Format.Format_Grayscale8
                    )

                self.update()

        self._native_widget = QtFramebuffer()

    def set_buffer(self, data: bytes):
        """Set framebuffer data."""
        self._buffer = bytearray(data[:len(self._buffer)])
        if hasattr(self._native_widget, 'update_image'):
            self._native_widget.update_image(bytes(self._buffer))
        self.update()

    def set_pixel(self, x: int, y: int, color: Color):
        """Set a single pixel."""
        if 0 <= x < self.fb_width and 0 <= y < self.fb_height:
            offset = (y * self.fb_width + x) * self._bpp

            if self.pixel_format == PixelFormat.RGB565:
                pixel = ((color.r >> 3) << 11) | ((color.g >> 2) << 5) | (color.b >> 3)
                self._buffer[offset] = pixel & 0xFF
                self._buffer[offset + 1] = (pixel >> 8) & 0xFF
            elif self.pixel_format == PixelFormat.RGB888:
                self._buffer[offset] = color.r
                self._buffer[offset + 1] = color.g
                self._buffer[offset + 2] = color.b
            elif self.pixel_format == PixelFormat.RGBA8888:
                self._buffer[offset] = color.r
                self._buffer[offset + 1] = color.g
                self._buffer[offset + 2] = color.b
                self._buffer[offset + 3] = color.a
            elif self.pixel_format == PixelFormat.GRAY8:
                gray = (color.r + color.g + color.b) // 3
                self._buffer[offset] = gray

    def update(self):
        if self._native_widget:
            self._native_widget.update()

    def clear(self, color: Color = None):
        """Clear framebuffer."""
        if color is None:
            self._buffer = bytearray(len(self._buffer))
        else:
            # Fill with color
            for y in range(self.fb_height):
                for x in range(self.fb_width):
                    self.set_pixel(x, y, color)

        if hasattr(self._native_widget, 'update_image'):
            self._native_widget.update_image(bytes(self._buffer))
        self.update()


class FramebufferServer:
    """
    Server for receiving framebuffer updates from emulator.

    Can receive via:
    - Shared memory (mmap)
    - TCP socket
    """

    def __init__(self, widget: FramebufferWidget,
                 mode: str = "tcp",
                 host: str = "127.0.0.1",
                 port: int = 9000,
                 shm_path: str = None):
        self.widget = widget
        self.mode = mode
        self.host = host
        self.port = port
        self.shm_path = shm_path

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._mmap: Optional[mmap.mmap] = None

    def start(self):
        """Start the server."""
        self._running = True

        if self.mode == "tcp":
            self._start_tcp()
        elif self.mode == "shm":
            self._start_shm()

    def stop(self):
        """Stop the server."""
        self._running = False
        if self._socket:
            self._socket.close()
        if self._mmap:
            self._mmap.close()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _start_tcp(self):
        """Start TCP server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen(1)

        self._thread = threading.Thread(target=self._tcp_loop, daemon=True)
        self._thread.start()

    def _tcp_loop(self):
        """TCP receive loop."""
        while self._running:
            try:
                self._socket.settimeout(1.0)
                client, addr = self._socket.accept()

                while self._running:
                    # Receive frame size header
                    header = client.recv(4)
                    if len(header) < 4:
                        break

                    size = struct.unpack('<I', header)[0]
                    if size > len(self.widget._buffer):
                        break

                    # Receive frame data
                    data = b''
                    while len(data) < size:
                        chunk = client.recv(min(4096, size - len(data)))
                        if not chunk:
                            break
                        data += chunk

                    if len(data) == size:
                        self.widget.set_buffer(data)

            except socket.timeout:
                continue
            except Exception:
                break

    def _start_shm(self):
        """Start shared memory monitor."""
        if not self.shm_path:
            return

        self._thread = threading.Thread(target=self._shm_loop, daemon=True)
        self._thread.start()

    def _shm_loop(self):
        """Shared memory monitor loop."""
        try:
            with open(self.shm_path, 'r+b') as f:
                self._mmap = mmap.mmap(f.fileno(), len(self.widget._buffer))

                while self._running:
                    # Read from shared memory
                    self._mmap.seek(0)
                    data = self._mmap.read(len(self.widget._buffer))
                    self.widget.set_buffer(data)

                    # Simple polling interval
                    import time
                    time.sleep(1/60)  # 60 FPS

        except Exception:
            pass
