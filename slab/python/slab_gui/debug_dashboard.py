"""
SLAB Professional Debug Dashboard

A professional-grade debug interface for MCU emulation with:
- Start/Reset/Stop emulator controls
- Interactive console with input fields (UART & USB CDC)
- Logic analyzer with zoom/pan controls
- LED status display
- Real-time signal capture
- Sigrok-compatible export (VCD, .sr)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import time
import zipfile
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable, Any
from enum import Enum
from collections import deque

try:
    import pygame
    from pygame import gfxdraw
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


# =============================================================================
# Color Theme (Dark Professional)
# =============================================================================

class Theme:
    """Professional dark color theme."""
    BG_PRIMARY = (18, 18, 24)
    BG_SECONDARY = (28, 28, 38)
    BG_TERTIARY = (38, 38, 50)
    BG_INPUT = (22, 22, 32)

    BORDER = (55, 55, 70)
    BORDER_FOCUS = (80, 140, 200)

    TEXT_PRIMARY = (220, 220, 230)
    TEXT_SECONDARY = (150, 150, 165)
    TEXT_DIM = (90, 90, 100)

    ACCENT_GREEN = (100, 220, 130)
    ACCENT_BLUE = (80, 160, 240)
    ACCENT_RED = (220, 80, 90)
    ACCENT_YELLOW = (240, 200, 80)
    ACCENT_CYAN = (80, 200, 220)
    ACCENT_MAGENTA = (180, 100, 220)

    BUTTON_START = (50, 140, 60)
    BUTTON_START_HOVER = (70, 180, 80)
    BUTTON_STOP = (180, 60, 60)
    BUTTON_STOP_HOVER = (220, 80, 80)
    BUTTON_RESET = (180, 160, 60)
    BUTTON_RESET_HOVER = (220, 200, 80)

    SCROLLBAR = (50, 50, 65)
    SCROLLBAR_THUMB = (80, 80, 100)


# =============================================================================
# Signal Capture Engine
# =============================================================================

class SignalType(Enum):
    DIGITAL = "digital"
    UART_TX = "uart_tx"
    UART_RX = "uart_rx"
    SPI = "spi"
    I2C = "i2c"


@dataclass
class SignalTransition:
    timestamp: float
    value: int


@dataclass
class SignalChannel:
    name: str
    signal_type: SignalType = SignalType.DIGITAL
    color: Tuple[int, int, int] = (100, 255, 100)
    transitions: List[SignalTransition] = field(default_factory=list)
    current_value: int = 0

    def add_transition(self, timestamp: float, value: int):
        if value != self.current_value:
            self.transitions.append(SignalTransition(timestamp, value))
            self.current_value = value

    def get_value_at(self, timestamp: float) -> int:
        value = 0
        for t in self.transitions:
            if t.timestamp <= timestamp:
                value = t.value
            else:
                break
        return value

    def clear(self):
        self.transitions.clear()
        self.current_value = 0


class SignalCapture:
    """Thread-safe signal capture engine."""

    def __init__(self, sample_rate: int = 1000000):
        self.sample_rate = sample_rate
        self.channels: Dict[str, SignalChannel] = {}
        self.start_time: Optional[float] = None
        self.lock = threading.Lock()
        self._running = False

    def add_channel(self, name: str, signal_type: SignalType = SignalType.DIGITAL,
                    color: Tuple[int, int, int] = None) -> SignalChannel:
        if color is None:
            colors = [
                Theme.ACCENT_GREEN, Theme.ACCENT_YELLOW, Theme.ACCENT_CYAN,
                Theme.ACCENT_MAGENTA, Theme.ACCENT_BLUE, Theme.ACCENT_RED,
            ]
            color = colors[len(self.channels) % len(colors)]
        channel = SignalChannel(name=name, signal_type=signal_type, color=color)
        self.channels[name] = channel
        return channel

    def start(self):
        with self.lock:
            self.start_time = time.time()
            self._running = True
            for ch in self.channels.values():
                ch.clear()

    def stop(self):
        with self.lock:
            self._running = False

    def record(self, channel_name: str, value: int):
        with self.lock:
            if not self._running or self.start_time is None:
                return
            channel = self.channels.get(channel_name)
            if channel:
                timestamp = time.time() - self.start_time
                channel.add_transition(timestamp, value)

    def get_duration(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def export_vcd(self, filename: str) -> str:
        lines = []
        lines.append("$date")
        lines.append(f"   {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("$end")
        lines.append("$version SLAB Logic Analyzer 2.0 $end")
        lines.append("$timescale 1ns $end")
        lines.append("$scope module capture $end")

        var_ids = {}
        var_id = ord('!')
        for name, channel in self.channels.items():
            var_ids[name] = chr(var_id)
            lines.append(f"$var wire 1 {chr(var_id)} {name} $end")
            var_id += 1

        lines.append("$upscope $end")
        lines.append("$enddefinitions $end")
        lines.append("#0")
        for name in self.channels:
            lines.append(f"b0 {var_ids[name]}")

        all_transitions = []
        for name, channel in self.channels.items():
            for t in channel.transitions:
                all_transitions.append((t.timestamp, name, t.value))
        all_transitions.sort(key=lambda x: x[0])

        for timestamp, name, value in all_transitions:
            ns = int(timestamp * 1e9)
            lines.append(f"#{ns}")
            lines.append(f"b{value} {var_ids[name]}")

        vcd_content = "\n".join(lines)
        if filename:
            with open(filename, 'w') as f:
                f.write(vcd_content)
        return vcd_content

    def export_sigrok(self, filename: str):
        duration = self.get_duration()
        if duration == 0:
            return

        export_rate = 1000000
        total_samples = min(int(duration * export_rate), 1000000)  # Cap at 1M samples
        num_channels = len(self.channels)
        bytes_per_sample = (num_channels + 7) // 8

        logic_data = bytearray()
        channel_list = list(self.channels.values())

        for sample_idx in range(total_samples):
            timestamp = sample_idx / export_rate
            byte_val = 0
            for ch_idx, channel in enumerate(channel_list):
                if channel.get_value_at(timestamp):
                    byte_val |= (1 << (ch_idx % 8))
                if (ch_idx + 1) % 8 == 0 or ch_idx == num_channels - 1:
                    logic_data.append(byte_val)
                    byte_val = 0

        metadata = [
            "[global]", "sigrok version=0.5.0", "",
            "[device 1]", "capturefile=logic-1",
            f"total probes={num_channels}",
            f"samplerate={export_rate} Hz",
            f"unitsize={bytes_per_sample}", "",
        ]
        for idx, channel in enumerate(channel_list):
            metadata.append(f"probe{idx + 1}={channel.name}")

        with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("metadata", "\n".join(metadata))
            zf.writestr("logic-1-1", bytes(logic_data))


# =============================================================================
# Input Field Widget
# =============================================================================

class InputField:
    """Text input field with cursor and selection."""

    def __init__(self, x: int, y: int, width: int, height: int = 22):
        self.rect = pygame.Rect(x, y, width, height) if PYGAME_AVAILABLE else None
        self.text = ""
        self.cursor_pos = 0
        self.focused = False
        self.placeholder = "Type here..."

        self.font = None
        self.bg_color = Theme.BG_INPUT
        self.text_color = Theme.TEXT_PRIMARY
        self.placeholder_color = Theme.TEXT_DIM
        self.cursor_color = Theme.ACCENT_BLUE
        self.cursor_blink = 0

        # Callback when Enter is pressed
        self.on_submit: Optional[Callable[[str], None]] = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 18)

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE or not self.rect:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN:
            self.focused = self.rect.collidepoint(event.pos)
            if self.focused:
                self.cursor_pos = len(self.text)
            return self.focused

        if not self.focused:
            return False

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                if self.text and self.on_submit:
                    self.on_submit(self.text)
                    self.text = ""
                    self.cursor_pos = 0
                return True
            elif event.key == pygame.K_BACKSPACE:
                if self.cursor_pos > 0:
                    self.text = self.text[:self.cursor_pos-1] + self.text[self.cursor_pos:]
                    self.cursor_pos -= 1
                return True
            elif event.key == pygame.K_DELETE:
                if self.cursor_pos < len(self.text):
                    self.text = self.text[:self.cursor_pos] + self.text[self.cursor_pos+1:]
                return True
            elif event.key == pygame.K_LEFT:
                self.cursor_pos = max(0, self.cursor_pos - 1)
                return True
            elif event.key == pygame.K_RIGHT:
                self.cursor_pos = min(len(self.text), self.cursor_pos + 1)
                return True
            elif event.key == pygame.K_HOME:
                self.cursor_pos = 0
                return True
            elif event.key == pygame.K_END:
                self.cursor_pos = len(self.text)
                return True
            elif event.unicode and event.unicode.isprintable():
                self.text = self.text[:self.cursor_pos] + event.unicode + self.text[self.cursor_pos:]
                self.cursor_pos += 1
                return True

        return False

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE or not self.rect:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, self.bg_color, self.rect, border_radius=3)

        # Border
        border_color = Theme.BORDER_FOCUS if self.focused else Theme.BORDER
        pygame.draw.rect(surface, border_color, self.rect, 1, border_radius=3)

        # Text or placeholder
        if self.text:
            text_surf = self.font.render(self.text, True, self.text_color)
        else:
            text_surf = self.font.render(self.placeholder, True, self.placeholder_color)

        # Clip text to field width
        text_x = self.rect.x + 5
        text_y = self.rect.centery - text_surf.get_height() // 2
        surface.blit(text_surf, (text_x, text_y), area=pygame.Rect(0, 0, self.rect.width - 10, text_surf.get_height()))

        # Cursor
        if self.focused:
            self.cursor_blink = (self.cursor_blink + 1) % 60
            if self.cursor_blink < 30:
                cursor_text = self.text[:self.cursor_pos]
                cursor_x = text_x + self.font.size(cursor_text)[0]
                pygame.draw.line(surface, self.cursor_color,
                               (cursor_x, self.rect.y + 4),
                               (cursor_x, self.rect.bottom - 4), 2)


# =============================================================================
# Console Widget with Input
# =============================================================================

class ConsoleWidget:
    """Interactive console with output display and input field."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 title: str = "Console", color: Tuple[int, int, int] = Theme.ACCENT_GREEN):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.title = title
        self.color = color

        self.lines: deque = deque(maxlen=200)
        self.line_buffer = bytearray()
        self.scroll_offset = 0
        self.auto_scroll = True

        self.font = None
        self.title_font = None
        self.line_height = 15

        # Input field at bottom
        input_height = 24
        self.input = InputField(x + 2, y + height - input_height - 2, width - 4, input_height)
        self.input.placeholder = f"Send to {title}..."

        # Callback for input
        self.on_input: Optional[Callable[[str], None]] = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 15)
            self.title_font = pygame.font.Font(None, 18)
            self.input.on_submit = self._on_input_submit

    def _on_input_submit(self, text: str):
        self.add_line(f"> {text}")
        if self.on_input:
            self.on_input(text)

    def add_byte(self, byte: int):
        self.line_buffer.append(byte)
        if byte == 0x0A:
            line = self.line_buffer.decode('utf-8', errors='replace').strip()
            if line:
                self.add_line(line)
            self.line_buffer.clear()

    def add_line(self, line: str):
        # Timestamp prefix
        ts = time.strftime("%H:%M:%S")
        self.lines.append(f"[{ts}] {line}")
        if self.auto_scroll:
            self.scroll_offset = 0

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if self.input.handle_event(event):
            return True

        if event.type == pygame.MOUSEWHEEL:
            # Check if mouse is over this console
            if PYGAME_AVAILABLE:
                mx, my = pygame.mouse.get_pos()
                if self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height:
                    self.scroll_offset = max(0, self.scroll_offset - event.y * 2)
                    self.auto_scroll = (self.scroll_offset == 0)
                    return True

        return False

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        # Title bar
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y, self.width, 22), border_radius=4)
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y + 10, self.width, 12))

        # Title
        title_surf = self.title_font.render(self.title, True, self.color)
        surface.blit(title_surf, (self.x + 8, self.y + 4))

        # Content area
        content_y = self.y + 25
        content_height = self.height - 52  # Leave room for input
        max_lines = content_height // self.line_height

        # Draw lines
        visible_lines = list(self.lines)
        if self.scroll_offset > 0:
            visible_lines = visible_lines[:-self.scroll_offset] if self.scroll_offset < len(visible_lines) else []
        visible_lines = visible_lines[-max_lines:]

        for idx, line in enumerate(visible_lines):
            line_y = content_y + idx * self.line_height
            # Truncate
            max_chars = (self.width - 16) // 7
            display_line = line[:max_chars]
            text_surf = self.font.render(display_line, True, Theme.TEXT_SECONDARY)
            surface.blit(text_surf, (self.x + 8, line_y))

        # Scroll indicator
        if len(self.lines) > max_lines:
            scroll_x = self.x + self.width - 8
            scroll_height = content_height
            thumb_height = max(20, scroll_height * max_lines // len(self.lines))
            thumb_pos = scroll_height - thumb_height - (self.scroll_offset * (scroll_height - thumb_height) // max(1, len(self.lines) - max_lines))

            pygame.draw.rect(surface, Theme.SCROLLBAR,
                           (scroll_x, content_y, 4, scroll_height), border_radius=2)
            pygame.draw.rect(surface, Theme.SCROLLBAR_THUMB,
                           (scroll_x, content_y + thumb_pos, 4, thumb_height), border_radius=2)

        # Draw input field
        self.input.draw(surface)

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)


# =============================================================================
# Logic Analyzer with Zoom Controls
# =============================================================================

class LogicAnalyzerPro:
    """Professional logic analyzer with zoom controls."""

    # Zoom levels in seconds per screen width
    ZOOM_LEVELS = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0]

    def __init__(self, x: int, y: int, width: int, height: int, capture: SignalCapture):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.capture = capture

        self.zoom_index = 6  # 1.0s default
        self.time_offset = 0.0
        self.auto_scroll = True
        self.channel_height = 28
        self.label_width = 70

        self.font = None
        self.small_font = None

        # Drag state
        self.dragging = False
        self.drag_start_x = 0
        self.drag_start_offset = 0.0

    @property
    def time_scale(self) -> float:
        return self.ZOOM_LEVELS[self.zoom_index]

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 16)
            self.small_font = pygame.font.Font(None, 14)

    def zoom_in(self):
        if self.zoom_index > 0:
            self.zoom_index -= 1

    def zoom_out(self):
        if self.zoom_index < len(self.ZOOM_LEVELS) - 1:
            self.zoom_index += 1

    def scroll_left(self):
        self.auto_scroll = False
        self.time_offset = max(0, self.time_offset - self.time_scale / 4)

    def scroll_right(self):
        self.auto_scroll = False
        self.time_offset += self.time_scale / 4

    def toggle_auto_scroll(self):
        self.auto_scroll = not self.auto_scroll

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE:
            return False

        waveform_x = self.x + self.label_width
        waveform_width = self.width - self.label_width

        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:  # Left click
                mx, my = event.pos
                if waveform_x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height:
                    self.dragging = True
                    self.drag_start_x = mx
                    self.drag_start_offset = self.time_offset
                    self.auto_scroll = False
                    return True
            elif event.button == 4:  # Scroll up = zoom in
                self.zoom_in()
                return True
            elif event.button == 5:  # Scroll down = zoom out
                self.zoom_out()
                return True

        elif event.type == pygame.MOUSEBUTTONUP:
            if event.button == 1:
                self.dragging = False

        elif event.type == pygame.MOUSEMOTION:
            if self.dragging:
                dx = event.pos[0] - self.drag_start_x
                time_delta = (dx / waveform_width) * self.time_scale
                self.time_offset = max(0, self.drag_start_offset - time_delta)
                return True

        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height:
                if event.y > 0:
                    self.zoom_in()
                else:
                    self.zoom_out()
                return True

        return False

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        # Auto-scroll
        if self.auto_scroll:
            duration = self.capture.get_duration()
            if duration > self.time_scale:
                self.time_offset = duration - self.time_scale

        waveform_x = self.x + self.label_width
        waveform_width = self.width - self.label_width - 5

        # Label background
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y, self.label_width, self.height), border_radius=4)
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x + 6, self.y, self.label_width - 6, self.height))

        # Draw channels
        for idx, (name, channel) in enumerate(self.capture.channels.items()):
            y_base = self.y + 8 + idx * self.channel_height + self.channel_height // 2

            if y_base > self.y + self.height - 10:
                break

            # Label
            label = self.font.render(name[:8], True, channel.color)
            surface.blit(label, (self.x + 4, y_base - 6))

            # Waveform
            self._draw_waveform(surface, channel, waveform_x, y_base,
                              waveform_width, self.channel_height - 6)

            # Separator
            sep_y = self.y + 8 + (idx + 1) * self.channel_height
            pygame.draw.line(surface, Theme.BG_TERTIARY,
                           (self.x, sep_y), (self.x + self.width, sep_y))

        # Time grid
        self._draw_time_grid(surface, waveform_x, waveform_width)

        # Zoom indicator
        zoom_text = f"{self.time_scale * 1000:.0f}ms/div"
        if self.time_scale < 0.1:
            zoom_text = f"{self.time_scale * 1000:.1f}ms/div"
        zoom_surf = self.small_font.render(zoom_text, True, Theme.TEXT_SECONDARY)
        surface.blit(zoom_surf, (self.x + self.width - 65, self.y + 4))

        # Auto-scroll indicator
        if self.auto_scroll:
            auto_surf = self.small_font.render("AUTO", True, Theme.ACCENT_GREEN)
            surface.blit(auto_surf, (self.x + self.width - 120, self.y + 4))

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)

    def _draw_waveform(self, surface, channel, x, y_center, width, height):
        half_h = height // 2

        if not channel.transitions:
            y = y_center - half_h if channel.current_value else y_center + half_h
            pygame.draw.line(surface, channel.color, (x, y), (x + width, y), 2)
            return

        points = []
        start_value = channel.get_value_at(self.time_offset)
        prev_y = y_center - half_h if start_value else y_center + half_h
        points.append((x, prev_y))

        for t in channel.transitions:
            if t.timestamp < self.time_offset:
                continue
            if t.timestamp > self.time_offset + self.time_scale:
                break

            rel_time = t.timestamp - self.time_offset
            px = x + int((rel_time / self.time_scale) * width)

            points.append((px, prev_y))
            new_y = y_center - half_h if t.value else y_center + half_h
            points.append((px, new_y))
            prev_y = new_y

        points.append((x + width, prev_y))

        if len(points) >= 2:
            pygame.draw.lines(surface, channel.color, False, points, 2)

    def _draw_time_grid(self, surface, x, width):
        num_divs = 10
        for i in range(1, num_divs):
            gx = x + (width * i) // num_divs
            pygame.draw.line(surface, Theme.BG_TERTIARY,
                           (gx, self.y), (gx, self.y + self.height))

        # Time labels
        for i in range(0, num_divs + 1, 2):
            gx = x + (width * i) // num_divs
            time_val = self.time_offset + (self.time_scale * i / num_divs)
            if time_val < 1.0:
                time_label = f"{time_val * 1000:.0f}ms"
            else:
                time_label = f"{time_val:.1f}s"
            label_surf = self.small_font.render(time_label, True, Theme.TEXT_DIM)
            surface.blit(label_surf, (gx - 15, self.y + self.height - 12))


# =============================================================================
# LED Status Widget
# =============================================================================

class LEDStatusPro:
    """Professional LED status display."""

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.leds: Dict[str, Tuple[str, Tuple[int, int, int], bool]] = {}
        self.font = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 14)

    def add_led(self, name: str, color: Tuple[int, int, int] = Theme.ACCENT_GREEN):
        self.leds[name] = (name, color, False)

    def set_led(self, name: str, state: bool):
        if name in self.leds:
            led_name, color, _ = self.leds[name]
            self.leds[name] = (led_name, color, state)

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        # Title
        title = self.font.render("GPIO LEDs", True, Theme.TEXT_PRIMARY)
        surface.blit(title, (self.x + 5, self.y + 4))

        # LEDs in a grid
        led_size = 16  # Increased from 10 for better visibility
        cols = max(1, (self.width - 10) // 70)
        start_y = self.y + 22

        for idx, (name, (_, color, state)) in enumerate(self.leds.items()):
            row = idx // cols
            col = idx % cols

            lx = self.x + 8 + col * 70
            ly = start_y + row * 22

            if ly + led_size > self.y + self.height:
                break

            center = (lx + led_size // 2, ly + led_size // 2)

            if state:
                # Glow
                for r in range(led_size, led_size // 2, -1):
                    alpha = int(60 * (1 - (r - led_size // 2) / (led_size // 2)))
                    glow_surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                    pygame.draw.circle(glow_surf, (*color, alpha), (r, r), r)
                    surface.blit(glow_surf, (center[0] - r, center[1] - r))
                pygame.draw.circle(surface, color, center, led_size // 2)
            else:
                dark = tuple(c // 6 for c in color)
                pygame.draw.circle(surface, dark, center, led_size // 2)

            pygame.draw.circle(surface, Theme.BORDER, center, led_size // 2, 1)

            # Label
            label = self.font.render(name[:5], True, Theme.TEXT_DIM)
            surface.blit(label, (lx + led_size + 3, ly))

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)


# =============================================================================
# Control Panel
# =============================================================================

class ControlPanel:
    """Emulator control panel with Start/Reset/Stop buttons."""

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

        self.running = False
        self.ops_count = 0
        self.elapsed_time = 0.0

        self.on_start: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_reset: Optional[Callable[[], None]] = None

        self.font = None
        self.buttons: Dict[str, dict] = {}
        self._buttons_init = False

    def _init_buttons(self):
        if not PYGAME_AVAILABLE or self._buttons_init:
            return
        self._buttons_init = True

        btn_w, btn_h = 65, 26
        btn_y = self.y + 24
        gap = 8

        self.buttons = {
            'start': {
                'rect': pygame.Rect(self.x + 8, btn_y, btn_w, btn_h),
                'text': "Start",
                'colors': (Theme.BUTTON_START, Theme.BUTTON_START_HOVER),
                'enabled': True, 'hover': False,
            },
            'stop': {
                'rect': pygame.Rect(self.x + 8 + btn_w + gap, btn_y, btn_w, btn_h),
                'text': "Stop",
                'colors': (Theme.BUTTON_STOP, Theme.BUTTON_STOP_HOVER),
                'enabled': False, 'hover': False,
            },
            'reset': {
                'rect': pygame.Rect(self.x + 8 + 2 * (btn_w + gap), btn_y, btn_w, btn_h),
                'text': "Reset",
                'colors': (Theme.BUTTON_RESET, Theme.BUTTON_RESET_HOVER),
                'enabled': True, 'hover': False,
            },
        }

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 16)
            self._init_buttons()

    def set_running(self, running: bool):
        self.running = running
        if 'start' in self.buttons:
            self.buttons['start']['enabled'] = not running
            self.buttons['stop']['enabled'] = running

    def update_stats(self, ops: int, elapsed: float):
        self.ops_count = ops
        self.elapsed_time = elapsed

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE:
            return False

        self._init_buttons()

        if event.type == pygame.MOUSEMOTION:
            for btn in self.buttons.values():
                btn['hover'] = btn['rect'].collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for name, btn in self.buttons.items():
                if btn['enabled'] and btn['rect'].collidepoint(event.pos):
                    if name == 'start' and self.on_start:
                        self.set_running(True)
                        self.on_start()
                    elif name == 'stop' and self.on_stop:
                        self.set_running(False)
                        self.on_stop()
                    elif name == 'reset' and self.on_reset:
                        self.on_reset()
                    return True

        return False

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        # Title
        title = self.font.render("Emulator Control", True, Theme.TEXT_PRIMARY)
        surface.blit(title, (self.x + 8, self.y + 5))

        # Buttons
        for name, btn in self.buttons.items():
            base, hover = btn['colors']
            if not btn['enabled']:
                color = tuple(c // 3 for c in base)
                text_color = Theme.TEXT_DIM
            elif btn['hover']:
                color = hover
                text_color = Theme.TEXT_PRIMARY
            else:
                color = base
                text_color = Theme.TEXT_PRIMARY

            pygame.draw.rect(surface, color, btn['rect'], border_radius=4)
            pygame.draw.rect(surface, Theme.BORDER, btn['rect'], 1, border_radius=4)

            text = self.font.render(btn['text'], True, text_color)
            text_rect = text.get_rect(center=btn['rect'].center)
            surface.blit(text, text_rect)

        # Status
        status_y = self.y + 58
        status_color = Theme.ACCENT_GREEN if self.running else Theme.ACCENT_RED
        pygame.draw.circle(surface, status_color, (self.x + 15, status_y + 4), 5)

        status_text = "Running" if self.running else "Stopped"
        status_surf = self.font.render(status_text, True, status_color)
        surface.blit(status_surf, (self.x + 25, status_y - 2))

        # Stats
        ops_text = f"Ops: {self.ops_count:,}"
        time_text = f"Time: {self.elapsed_time:.1f}s"
        ops_surf = self.font.render(ops_text, True, Theme.TEXT_SECONDARY)
        time_surf = self.font.render(time_text, True, Theme.TEXT_SECONDARY)
        surface.blit(ops_surf, (self.x + 100, status_y - 2))
        surface.blit(time_surf, (self.x + 190, status_y - 2))

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)


# =============================================================================
# Main Debug Dashboard
# =============================================================================

class DebugDashboardPro:
    """
    Professional Debug Dashboard.

    Layout:
    +------------------------------------------+
    | Control Panel              | LED Status  |
    +------------------------------------------+
    | Logic Analyzer (waveforms with zoom)     |
    +------------------------------------------+
    | UART Console       | USB CDC Console     |
    | [input field]      | [input field]       |
    +------------------------------------------+
    """

    def __init__(self, width: int = 900, height: int = 700,
                 title: str = "MCUemu Debug Dashboard",
                 show_controls: bool = True):
        self.width = width
        self.height = height
        self.title = title
        self.show_controls = show_controls

        self.screen = None
        self.clock = None
        self.running = False

        # Create capture engine
        self.capture = SignalCapture()

        # Create widgets
        self._create_widgets()

        # External callbacks
        self.on_start: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_reset: Optional[Callable[[], None]] = None
        self.on_uart_input: Optional[Callable[[str], None]] = None
        self.on_cdc_input: Optional[Callable[[str], None]] = None

    def _create_widgets(self):
        m = 5  # Margin

        # Top row layout depends on show_controls
        top_h = 80
        if self.show_controls:
            ctrl_w = self.width * 2 // 3 - m
            led_w = self.width - ctrl_w - 3 * m
            self.control = ControlPanel(m, m, ctrl_w, top_h)
            self.led_status = LEDStatusPro(ctrl_w + 2 * m, m, led_w, top_h)
        else:
            # No control panel - LED status takes full width
            self.control = None
            self.led_status = LEDStatusPro(m, m, self.width - 2 * m, top_h)

        # Logic analyzer
        la_y = top_h + 2 * m
        la_h = 180
        self.logic_analyzer = LogicAnalyzerPro(m, la_y, self.width - 2 * m, la_h, self.capture)

        # Consoles
        console_y = la_y + la_h + m
        console_h = self.height - console_y - m
        console_w = (self.width - 3 * m) // 2

        self.uart_console = ConsoleWidget(m, console_y, console_w, console_h,
                                          "UART Console", Theme.ACCENT_GREEN)
        self.cdc_console = ConsoleWidget(console_w + 2 * m, console_y, console_w, console_h,
                                         "USB CDC Console", Theme.ACCENT_BLUE)

    def init_pygame(self) -> bool:
        if not PYGAME_AVAILABLE:
            return False

        pygame.init()
        pygame.display.set_caption(self.title)
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.clock = pygame.time.Clock()
        self.running = True

        # Wire callbacks
        if self.control:
            self.control.on_start = self._on_start
            self.control.on_stop = self._on_stop
            self.control.on_reset = self._on_reset
        self.uart_console.on_input = self._on_uart_input
        self.cdc_console.on_input = self._on_cdc_input

        return True

    def _on_start(self):
        self.capture.start()
        if self.on_start:
            self.on_start()

    def _on_stop(self):
        self.capture.stop()
        if self.on_stop:
            self.on_stop()

    def _on_reset(self):
        self.capture.stop()
        for ch in self.capture.channels.values():
            ch.clear()
        self.uart_console.lines.clear()
        self.cdc_console.lines.clear()
        if self.on_reset:
            self.on_reset()

    def _on_uart_input(self, text: str):
        if self.on_uart_input:
            self.on_uart_input(text)

    def _on_cdc_input(self, text: str):
        if self.on_cdc_input:
            self.on_cdc_input(text)

    # Public API
    def add_led(self, name: str, color: Tuple[int, int, int] = Theme.ACCENT_GREEN):
        self.led_status.add_led(name, color)

    def set_led(self, name: str, state: bool):
        self.led_status.set_led(name, state)
        if name in self.capture.channels:
            self.capture.record(name, 1 if state else 0)

    def add_signal(self, name: str, signal_type: SignalType = SignalType.DIGITAL,
                   color: Tuple[int, int, int] = None):
        return self.capture.add_channel(name, signal_type, color)

    def record_signal(self, name: str, value: int):
        self.capture.record(name, value)

    def add_uart_line(self, line: str):
        self.uart_console.add_line(line)

    def add_cdc_line(self, line: str):
        self.cdc_console.add_line(line)

    def update_stats(self, ops: int, elapsed: float):
        if self.control:
            self.control.update_stats(ops, elapsed)

    def handle_events(self) -> bool:
        if not PYGAME_AVAILABLE:
            return True

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            # Route to widgets
            if self.control and self.control.handle_event(event):
                continue
            if self.logic_analyzer.handle_event(event):
                continue
            if self.uart_console.handle_event(event):
                continue
            if self.cdc_console.handle_event(event):
                continue

            # Global keys
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                elif event.key == pygame.K_SPACE and self.control:
                    if self.control.running:
                        self._on_stop()
                        self.control.set_running(False)
                    else:
                        self._on_start()
                        self.control.set_running(True)
                elif event.key == pygame.K_r and self.control and not self.uart_console.input.focused and not self.cdc_console.input.focused:
                    self._on_reset()
                elif event.key == pygame.K_e and not self.uart_console.input.focused and not self.cdc_console.input.focused:
                    self.export_capture("/tmp/slab_capture")
                elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
                    self.logic_analyzer.zoom_in()
                elif event.key == pygame.K_MINUS:
                    self.logic_analyzer.zoom_out()
                elif event.key == pygame.K_LEFT:
                    self.logic_analyzer.scroll_left()
                elif event.key == pygame.K_RIGHT:
                    self.logic_analyzer.scroll_right()
                elif event.key == pygame.K_a and not self.uart_console.input.focused and not self.cdc_console.input.focused:
                    self.logic_analyzer.toggle_auto_scroll()

        return True

    def draw(self):
        if not self.screen:
            return

        self.screen.fill(Theme.BG_PRIMARY)

        if self.control:
            self.control.draw(self.screen)
        self.led_status.draw(self.screen)
        self.logic_analyzer.draw(self.screen)
        self.uart_console.draw(self.screen)
        self.cdc_console.draw(self.screen)

        # Help bar
        font = pygame.font.Font(None, 13)
        help_text = "Space=Start/Stop  R=Reset  E=Export  +/-/Wheel=Zoom  Drag/Arrows=Pan  A=AutoScroll"
        help_surf = font.render(help_text, True, Theme.TEXT_DIM)
        self.screen.blit(help_surf, (5, self.height - 14))

        pygame.display.flip()

    def export_capture(self, basename: str):
        self.capture.export_vcd(f"{basename}.vcd")
        self.capture.export_sigrok(f"{basename}.sr")
        self.add_uart_line(f"[Export] Saved to {basename}.vcd/.sr")

    def run_loop(self, tick_callback: Optional[Callable[[], None]] = None, fps: int = 30):
        while self.running:
            if not self.handle_events():
                break
            if tick_callback:
                tick_callback()
            self.draw()
            self.clock.tick(fps)

        self.export_capture("/tmp/final_capture")

    def close(self):
        self.running = False
        if PYGAME_AVAILABLE:
            pygame.quit()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    'Theme',
    'SignalType',
    'SignalTransition',
    'SignalChannel',
    'SignalCapture',
    'InputField',
    'ConsoleWidget',
    'LogicAnalyzerPro',
    'LEDStatusPro',
    'ControlPanel',
    'DebugDashboardPro',
    'PYGAME_AVAILABLE',
]
