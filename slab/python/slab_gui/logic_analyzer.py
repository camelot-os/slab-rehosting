"""
SLAB GUI Logic Analyzer Widget

Real-time signal capture and display with Sigrok-compatible export.

Features:
- Multi-channel digital signal capture
- Real-time waveform display
- VCD (Value Change Dump) export
- Sigrok session export (.sr)
- Configurable sample rate and buffer depth

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import time
import struct
import zipfile
import json
import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Callable
from enum import Enum
from collections import deque
import threading

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class SignalType(Enum):
    """Signal types for the logic analyzer."""
    DIGITAL = "digital"
    UART_TX = "uart_tx"
    UART_RX = "uart_rx"
    SPI_CLK = "spi_clk"
    SPI_MOSI = "spi_mosi"
    SPI_MISO = "spi_miso"
    I2C_SCL = "i2c_scl"
    I2C_SDA = "i2c_sda"


@dataclass
class SignalTransition:
    """Single signal transition."""
    timestamp: float  # Seconds since capture start
    value: int        # New value (0 or 1 for digital)


@dataclass
class SignalChannel:
    """A single signal channel."""
    name: str
    signal_type: SignalType = SignalType.DIGITAL
    color: Tuple[int, int, int] = (0, 255, 0)
    transitions: List[SignalTransition] = field(default_factory=list)
    current_value: int = 0

    def add_transition(self, timestamp: float, value: int):
        """Record a signal transition."""
        if value != self.current_value:
            self.transitions.append(SignalTransition(timestamp, value))
            self.current_value = value

    def get_value_at(self, timestamp: float) -> int:
        """Get signal value at a specific timestamp."""
        value = 0
        for t in self.transitions:
            if t.timestamp <= timestamp:
                value = t.value
            else:
                break
        return value

    def clear(self):
        """Clear all transitions."""
        self.transitions.clear()
        self.current_value = 0


class SignalCapture:
    """
    Signal capture engine for logic analyzer.

    Thread-safe capture of multiple digital signals with timestamps.
    """

    def __init__(self, sample_rate: int = 1000000):
        """
        Initialize signal capture.

        Args:
            sample_rate: Nominal sample rate in Hz (for export metadata)
        """
        self.sample_rate = sample_rate
        self.channels: Dict[str, SignalChannel] = {}
        self.start_time: Optional[float] = None
        self.lock = threading.Lock()
        self._running = False

    def add_channel(self, name: str, signal_type: SignalType = SignalType.DIGITAL,
                    color: Tuple[int, int, int] = None) -> SignalChannel:
        """Add a capture channel."""
        if color is None:
            # Auto-assign colors
            colors = [
                (0, 255, 0),    # Green
                (255, 255, 0),  # Yellow
                (0, 255, 255),  # Cyan
                (255, 0, 255),  # Magenta
                (255, 128, 0),  # Orange
                (128, 255, 0),  # Lime
                (0, 128, 255),  # Sky blue
                (255, 0, 128),  # Pink
            ]
            color = colors[len(self.channels) % len(colors)]

        channel = SignalChannel(name=name, signal_type=signal_type, color=color)
        self.channels[name] = channel
        return channel

    def start(self):
        """Start capture."""
        with self.lock:
            self.start_time = time.time()
            self._running = True
            for ch in self.channels.values():
                ch.clear()

    def stop(self):
        """Stop capture."""
        with self.lock:
            self._running = False

    def record(self, channel_name: str, value: int):
        """Record a signal transition."""
        with self.lock:
            if not self._running or self.start_time is None:
                return

            channel = self.channels.get(channel_name)
            if channel:
                timestamp = time.time() - self.start_time
                channel.add_transition(timestamp, value)

    def get_duration(self) -> float:
        """Get capture duration in seconds."""
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def export_vcd(self, filename: str = None) -> str:
        """
        Export capture to VCD (Value Change Dump) format.

        VCD is a standard format supported by GTKWave, Sigrok, etc.

        Args:
            filename: Output filename (optional, returns string if None)

        Returns:
            VCD content as string
        """
        lines = []

        # Header
        lines.append("$date")
        lines.append(f"   {time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("$end")
        lines.append("$version")
        lines.append("   SLAB Logic Analyzer 1.0")
        lines.append("$end")
        lines.append("$timescale 1ns $end")

        # Variable definitions
        lines.append("$scope module capture $end")

        var_ids = {}
        var_id = ord('!')
        for name, channel in self.channels.items():
            var_ids[name] = chr(var_id)
            lines.append(f"$var wire 1 {chr(var_id)} {name} $end")
            var_id += 1

        lines.append("$upscope $end")
        lines.append("$enddefinitions $end")

        # Initial values
        lines.append("#0")
        for name, channel in self.channels.items():
            lines.append(f"b0 {var_ids[name]}")

        # Collect all transitions and sort by time
        all_transitions = []
        for name, channel in self.channels.items():
            for t in channel.transitions:
                all_transitions.append((t.timestamp, name, t.value))

        all_transitions.sort(key=lambda x: x[0])

        # Output transitions
        for timestamp, name, value in all_transitions:
            # Convert to nanoseconds
            ns = int(timestamp * 1e9)
            lines.append(f"#{ns}")
            lines.append(f"b{value} {var_ids[name]}")

        vcd_content = "\n".join(lines)

        if filename:
            with open(filename, 'w') as f:
                f.write(vcd_content)

        return vcd_content

    def export_sigrok(self, filename: str):
        """
        Export capture to Sigrok session format (.sr).

        The .sr format is a ZIP file containing:
        - metadata: Session metadata in INI format
        - logic-1-1: Raw binary logic data

        Args:
            filename: Output filename (should end with .sr)
        """
        # Calculate total samples needed
        duration = self.get_duration()
        if duration == 0:
            return

        # Use 1MHz sample rate for export
        export_rate = 1000000
        total_samples = int(duration * export_rate)

        # Build logic data (packed bits)
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

        # Build metadata
        metadata_lines = [
            "[global]",
            "sigrok version=0.5.0",
            "",
            "[device 1]",
            "capturefile=logic-1",
            f"total probes={num_channels}",
            f"samplerate={export_rate} Hz",
            f"total analog=0",
            f"unitsize={bytes_per_sample}",
            "",
        ]

        for idx, channel in enumerate(channel_list):
            metadata_lines.append(f"probe{idx + 1}={channel.name}")

        metadata = "\n".join(metadata_lines)

        # Create ZIP file
        with zipfile.ZipFile(filename, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("metadata", metadata)
            zf.writestr("logic-1-1", bytes(logic_data))

    def export_csv(self, filename: str):
        """Export capture to CSV format."""
        lines = ["timestamp_ns," + ",".join(self.channels.keys())]

        # Collect all unique timestamps
        timestamps = set([0.0])
        for channel in self.channels.values():
            for t in channel.transitions:
                timestamps.add(t.timestamp)

        timestamps = sorted(timestamps)

        for ts in timestamps:
            values = [str(ch.get_value_at(ts)) for ch in self.channels.values()]
            lines.append(f"{int(ts * 1e9)}," + ",".join(values))

        with open(filename, 'w') as f:
            f.write("\n".join(lines))


class LogicAnalyzerWidget:
    """
    Pygame-based logic analyzer display widget.

    Features:
    - Real-time waveform display
    - Zoom and pan
    - Signal labels
    - Cursor measurements
    """

    def __init__(self, x: int, y: int, width: int, height: int,
                 capture: SignalCapture):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.capture = capture

        # Display settings
        self.time_scale = 1.0  # Seconds per screen width
        self.time_offset = 0.0  # Start time offset
        self.channel_height = 30
        self.label_width = 80
        self.auto_scroll = True

        # Colors
        self.bg_color = (20, 20, 30)
        self.grid_color = (40, 40, 50)
        self.label_bg_color = (30, 30, 40)
        self.text_color = (200, 200, 200)
        self.cursor_color = (255, 100, 100)

        # Fonts
        self.font = None
        self.small_font = None

    def init_fonts(self):
        """Initialize fonts (call after pygame.init())."""
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 20)
            self.small_font = pygame.font.Font(None, 16)

    def draw(self, surface: 'pygame.Surface'):
        """Draw the logic analyzer widget."""
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, self.bg_color,
                        (self.x, self.y, self.width, self.height))

        # Border
        pygame.draw.rect(surface, self.grid_color,
                        (self.x, self.y, self.width, self.height), 1)

        # Label background
        pygame.draw.rect(surface, self.label_bg_color,
                        (self.x, self.y, self.label_width, self.height))

        # Auto-scroll to show latest data
        if self.auto_scroll:
            duration = self.capture.get_duration()
            if duration > self.time_scale:
                self.time_offset = duration - self.time_scale

        # Draw channels
        waveform_x = self.x + self.label_width
        waveform_width = self.width - self.label_width

        for idx, (name, channel) in enumerate(self.capture.channels.items()):
            y_base = self.y + idx * self.channel_height + self.channel_height // 2

            if y_base > self.y + self.height:
                break

            # Channel label
            label = self.font.render(name[:10], True, channel.color)
            surface.blit(label, (self.x + 5, y_base - 8))

            # Draw waveform
            self._draw_waveform(surface, channel, waveform_x, y_base,
                              waveform_width, self.channel_height - 4)

            # Separator line
            sep_y = self.y + (idx + 1) * self.channel_height
            pygame.draw.line(surface, self.grid_color,
                           (self.x, sep_y), (self.x + self.width, sep_y))

        # Time scale indicator
        time_text = f"{self.time_scale * 1000:.1f}ms/div"
        time_label = self.small_font.render(time_text, True, self.text_color)
        surface.blit(time_label, (self.x + self.width - 80, self.y + 5))

        # Draw grid lines (time divisions)
        num_divs = 10
        for i in range(1, num_divs):
            gx = waveform_x + (waveform_width * i) // num_divs
            pygame.draw.line(surface, self.grid_color,
                           (gx, self.y), (gx, self.y + self.height))

    def _draw_waveform(self, surface: 'pygame.Surface', channel: SignalChannel,
                       x: int, y_center: int, width: int, height: int):
        """Draw a single channel waveform."""
        if not channel.transitions:
            # No transitions - draw flat line at current value
            y = y_center - (height // 2) if channel.current_value else y_center + (height // 2)
            pygame.draw.line(surface, channel.color, (x, y), (x + width, y), 2)
            return

        points = []
        prev_x = x
        prev_y = y_center + (height // 2)  # Start low

        # Find value at start of visible window
        start_value = channel.get_value_at(self.time_offset)
        prev_y = y_center - (height // 2) if start_value else y_center + (height // 2)
        points.append((prev_x, prev_y))

        for t in channel.transitions:
            if t.timestamp < self.time_offset:
                continue
            if t.timestamp > self.time_offset + self.time_scale:
                break

            # Calculate x position
            rel_time = t.timestamp - self.time_offset
            px = x + int((rel_time / self.time_scale) * width)

            # Horizontal line to transition point
            points.append((px, prev_y))

            # Vertical transition
            new_y = y_center - (height // 2) if t.value else y_center + (height // 2)
            points.append((px, new_y))

            prev_x = px
            prev_y = new_y

        # Extend to end of window
        points.append((x + width, prev_y))

        # Draw the waveform
        if len(points) >= 2:
            pygame.draw.lines(surface, channel.color, False, points, 2)

    def zoom_in(self):
        """Zoom in (decrease time scale)."""
        self.time_scale = max(0.001, self.time_scale / 2)

    def zoom_out(self):
        """Zoom out (increase time scale)."""
        self.time_scale = min(10.0, self.time_scale * 2)

    def scroll_left(self):
        """Scroll left in time."""
        self.auto_scroll = False
        self.time_offset = max(0, self.time_offset - self.time_scale / 4)

    def scroll_right(self):
        """Scroll right in time."""
        self.auto_scroll = False
        self.time_offset += self.time_scale / 4

    def toggle_auto_scroll(self):
        """Toggle auto-scroll mode."""
        self.auto_scroll = not self.auto_scroll


class DualConsoleWidget:
    """
    Dual console widget showing UART and USB CDC output side by side.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

        # Console buffers
        self.uart_lines: deque = deque(maxlen=100)
        self.cdc_lines: deque = deque(maxlen=100)

        # Partial line buffers
        self.uart_buffer = bytearray()
        self.cdc_buffer = bytearray()

        # Display settings
        self.line_height = 14
        self.font = None
        self.title_font = None

        # Colors
        self.bg_color = (25, 25, 35)
        self.uart_color = (100, 255, 100)  # Green for UART
        self.cdc_color = (100, 200, 255)   # Blue for CDC
        self.title_color = (200, 200, 200)
        self.border_color = (60, 60, 70)

    def init_fonts(self):
        """Initialize fonts."""
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 16)
            self.title_font = pygame.font.Font(None, 20)

    def add_uart_byte(self, byte: int):
        """Add a byte to UART console."""
        self.uart_buffer.append(byte)
        if byte == 0x0A:  # Newline
            line = self.uart_buffer.decode('utf-8', errors='replace').strip()
            if line:
                self.uart_lines.append(line)
            self.uart_buffer.clear()

    def add_cdc_byte(self, byte: int):
        """Add a byte to CDC console."""
        self.cdc_buffer.append(byte)
        if byte == 0x0A:  # Newline
            line = self.cdc_buffer.decode('utf-8', errors='replace').strip()
            if line:
                self.cdc_lines.append(line)
            self.cdc_buffer.clear()

    def add_uart_line(self, line: str):
        """Add a complete line to UART console."""
        self.uart_lines.append(line)

    def add_cdc_line(self, line: str):
        """Add a complete line to CDC console."""
        self.cdc_lines.append(line)

    def draw(self, surface: 'pygame.Surface'):
        """Draw the dual console widget."""
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        half_width = self.width // 2 - 5

        # Left panel - UART
        self._draw_console_panel(
            surface,
            self.x, self.y,
            half_width, self.height,
            "UART Console",
            self.uart_lines,
            self.uart_color
        )

        # Right panel - USB CDC
        self._draw_console_panel(
            surface,
            self.x + half_width + 10, self.y,
            half_width, self.height,
            "USB CDC Console",
            self.cdc_lines,
            self.cdc_color
        )

    def _draw_console_panel(self, surface: 'pygame.Surface',
                           x: int, y: int, width: int, height: int,
                           title: str, lines: deque, color: Tuple[int, int, int]):
        """Draw a single console panel."""
        # Background
        pygame.draw.rect(surface, self.bg_color, (x, y, width, height))
        pygame.draw.rect(surface, self.border_color, (x, y, width, height), 1)

        # Title bar
        pygame.draw.rect(surface, (40, 40, 50), (x, y, width, 22))
        title_surf = self.title_font.render(title, True, self.title_color)
        surface.blit(title_surf, (x + 5, y + 3))

        # Content area
        content_y = y + 25
        content_height = height - 28
        max_lines = content_height // self.line_height

        # Draw lines (most recent at bottom)
        visible_lines = list(lines)[-max_lines:]
        for idx, line in enumerate(visible_lines):
            line_y = content_y + idx * self.line_height
            # Truncate long lines
            display_line = line[:width // 7]
            text_surf = self.font.render(display_line, True, color)
            surface.blit(text_surf, (x + 5, line_y))


class LEDStatusWidget:
    """
    LED status display widget showing GPIO states.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

        # LED definitions: (name, color)
        self.leds: Dict[str, Tuple[str, Tuple[int, int, int], bool]] = {}
        self.font = None

        # Colors
        self.bg_color = (25, 25, 35)
        self.border_color = (60, 60, 70)

    def init_fonts(self):
        """Initialize fonts."""
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 16)

    def add_led(self, name: str, color: Tuple[int, int, int] = (0, 255, 0)):
        """Add an LED to the display."""
        self.leds[name] = (name, color, False)

    def set_led(self, name: str, state: bool):
        """Set LED state."""
        if name in self.leds:
            led_name, color, _ = self.leds[name]
            self.leds[name] = (led_name, color, state)

    def draw(self, surface: 'pygame.Surface'):
        """Draw the LED status widget."""
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, self.bg_color,
                        (self.x, self.y, self.width, self.height))
        pygame.draw.rect(surface, self.border_color,
                        (self.x, self.y, self.width, self.height), 1)

        # Title
        title = self.font.render("LED Status", True, (200, 200, 200))
        surface.blit(title, (self.x + 5, self.y + 3))

        # Draw LEDs
        led_size = 12
        padding = 5
        leds_per_row = (self.width - 10) // (led_size + 50)

        for idx, (name, (_, color, state)) in enumerate(self.leds.items()):
            row = idx // max(1, leds_per_row)
            col = idx % max(1, leds_per_row)

            lx = self.x + 10 + col * (led_size + 55)
            ly = self.y + 22 + row * (led_size + padding)

            if ly + led_size > self.y + self.height:
                break

            # Draw LED
            center = (lx + led_size // 2, ly + led_size // 2)
            radius = led_size // 2

            if state:
                # Glow effect
                for r in range(radius + 4, radius, -1):
                    alpha = int(100 * (1 - (r - radius) / 4))
                    glow = (*color, alpha)
                    glow_surf = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
                    pygame.draw.circle(glow_surf, glow, (r, r), r)
                    surface.blit(glow_surf, (center[0] - r, center[1] - r))
                pygame.draw.circle(surface, color, center, radius)
            else:
                dark = tuple(c // 5 for c in color)
                pygame.draw.circle(surface, dark, center, radius)

            pygame.draw.circle(surface, (60, 60, 60), center, radius, 1)

            # Label
            label = self.font.render(name[:6], True, (150, 150, 150))
            surface.blit(label, (lx + led_size + 3, ly))


class EmulatorControlWidget:
    """
    Emulator control panel with Start/Reset/Stop buttons.

    Provides callback-based control of QEMU emulation.
    """

    def __init__(self, x: int, y: int, width: int, height: int):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

        # Button state
        self.running = False
        self.buttons: Dict[str, dict] = {}

        # Callbacks
        self.on_start: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_reset: Optional[Callable[[], None]] = None
        self.on_step: Optional[Callable[[], None]] = None

        # Fonts
        self.font = None
        self.title_font = None

        # Colors
        self.bg_color = (25, 25, 35)
        self.border_color = (60, 60, 70)
        self.button_colors = {
            'start': ((50, 150, 50), (80, 200, 80)),      # Green
            'stop': ((150, 50, 50), (200, 80, 80)),       # Red
            'reset': ((150, 150, 50), (200, 200, 80)),    # Yellow
            'step': ((50, 100, 150), (80, 150, 200)),     # Blue
        }

        # Status
        self.status_text = "Stopped"
        self.ops_count = 0
        self.elapsed_time = 0.0

        self._init_buttons()

    def _init_buttons(self):
        """Initialize button definitions."""
        btn_width = 60
        btn_height = 25
        btn_spacing = 8

        # Start button
        self.buttons['start'] = {
            'rect': pygame.Rect(self.x + 10, self.y + 25, btn_width, btn_height) if PYGAME_AVAILABLE else None,
            'text': '▶ Start',
            'hover': False,
            'enabled': True,
        }

        # Stop button
        self.buttons['stop'] = {
            'rect': pygame.Rect(self.x + 10 + btn_width + btn_spacing, self.y + 25, btn_width, btn_height) if PYGAME_AVAILABLE else None,
            'text': '■ Stop',
            'hover': False,
            'enabled': False,
        }

        # Reset button
        self.buttons['reset'] = {
            'rect': pygame.Rect(self.x + 10 + 2 * (btn_width + btn_spacing), self.y + 25, btn_width, btn_height) if PYGAME_AVAILABLE else None,
            'text': '↻ Reset',
            'hover': False,
            'enabled': True,
        }

        # Step button (single-step execution)
        if self.width > 260:
            self.buttons['step'] = {
                'rect': pygame.Rect(self.x + 10 + 3 * (btn_width + btn_spacing), self.y + 25, btn_width, btn_height) if PYGAME_AVAILABLE else None,
                'text': '→ Step',
                'hover': False,
                'enabled': True,
            }

    def init_fonts(self):
        """Initialize fonts."""
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 18)
            self.title_font = pygame.font.Font(None, 20)
            # Re-init button rects after pygame init
            self._init_buttons()

    def set_running(self, running: bool):
        """Set emulator running state."""
        self.running = running
        self.buttons['start']['enabled'] = not running
        self.buttons['stop']['enabled'] = running
        self.status_text = "Running" if running else "Stopped"

    def update_stats(self, ops: int, elapsed: float):
        """Update operation statistics."""
        self.ops_count = ops
        self.elapsed_time = elapsed

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        """
        Handle pygame event.

        Returns True if event was consumed.
        """
        if not PYGAME_AVAILABLE:
            return False

        if event.type == pygame.MOUSEMOTION:
            # Update hover state
            for name, btn in self.buttons.items():
                if btn['rect']:
                    btn['hover'] = btn['rect'].collidepoint(event.pos)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for name, btn in self.buttons.items():
                if btn['rect'] and btn['enabled'] and btn['rect'].collidepoint(event.pos):
                    self._handle_button_click(name)
                    return True

        return False

    def _handle_button_click(self, name: str):
        """Handle button click."""
        if name == 'start' and self.on_start:
            self.set_running(True)
            self.on_start()
        elif name == 'stop' and self.on_stop:
            self.set_running(False)
            self.on_stop()
        elif name == 'reset' and self.on_reset:
            self.on_reset()
        elif name == 'step' and self.on_step:
            self.on_step()

    def draw(self, surface: 'pygame.Surface'):
        """Draw the control widget."""
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, self.bg_color,
                        (self.x, self.y, self.width, self.height))
        pygame.draw.rect(surface, self.border_color,
                        (self.x, self.y, self.width, self.height), 1)

        # Title
        title = self.title_font.render("Emulator Control", True, (200, 200, 200))
        surface.blit(title, (self.x + 5, self.y + 3))

        # Draw buttons
        for name, btn in self.buttons.items():
            if btn['rect'] is None:
                continue

            # Button color
            base_color, hover_color = self.button_colors.get(name, ((100, 100, 100), (150, 150, 150)))

            if not btn['enabled']:
                color = tuple(c // 3 for c in base_color)
                text_color = (80, 80, 80)
            elif btn['hover']:
                color = hover_color
                text_color = (255, 255, 255)
            else:
                color = base_color
                text_color = (220, 220, 220)

            # Draw button
            pygame.draw.rect(surface, color, btn['rect'], border_radius=4)
            pygame.draw.rect(surface, (80, 80, 80), btn['rect'], 1, border_radius=4)

            # Button text
            text = self.font.render(btn['text'], True, text_color)
            text_rect = text.get_rect(center=btn['rect'].center)
            surface.blit(text, text_rect)

        # Status line
        status_y = self.y + 55

        # Status indicator
        status_color = (100, 255, 100) if self.running else (255, 100, 100)
        pygame.draw.circle(surface, status_color, (self.x + 15, status_y + 6), 5)

        status = self.font.render(self.status_text, True, status_color)
        surface.blit(status, (self.x + 25, status_y))

        # Stats
        if self.height > 75:
            stats_y = self.y + 72
            ops_text = f"Ops: {self.ops_count:,}"
            time_text = f"Time: {self.elapsed_time:.1f}s"

            ops_surf = self.font.render(ops_text, True, (150, 150, 150))
            time_surf = self.font.render(time_text, True, (150, 150, 150))

            surface.blit(ops_surf, (self.x + 10, stats_y))
            surface.blit(time_surf, (self.x + 100, stats_y))


class DebugDashboard:
    """
    Complete debug dashboard combining all widgets.

    Layout:
    +-----------------------------------------+
    | Emulator Control         | LED Status   |
    +-----------------------------------------+
    | Logic Analyzer (waveforms)              |
    +-----------------------------------------+
    | UART Console     | USB CDC Console      |
    +-----------------------------------------+

    Keyboard shortcuts:
    - Space: Start/Stop emulation
    - R: Reset emulation
    - E: Export capture
    - +/-: Zoom in/out
    - Left/Right: Scroll
    - A: Toggle auto-scroll
    - C: Clear consoles
    - Q: Quit
    """

    def __init__(self, width: int = 800, height: int = 600, title: str = "MCUemu Debug Dashboard"):
        self.width = width
        self.height = height
        self.title = title

        self.screen: Optional['pygame.Surface'] = None
        self.running = False
        self.clock = None

        # Create widgets
        self._create_widgets()

        # Create signal capture
        self.capture = SignalCapture()
        self.logic_analyzer.capture = self.capture

        # Callbacks for emulator control
        self.on_start: Optional[Callable[[], None]] = None
        self.on_stop: Optional[Callable[[], None]] = None
        self.on_reset: Optional[Callable[[], None]] = None

    def _create_widgets(self):
        """Create and layout widgets."""
        margin = 5

        # Top row: Control + LED status
        top_height = 90
        control_width = self.width * 2 // 3 - margin
        led_width = self.width - control_width - 3 * margin

        self.control = EmulatorControlWidget(
            margin, margin, control_width, top_height
        )

        self.led_status = LEDStatusWidget(
            control_width + 2 * margin, margin, led_width, top_height
        )

        # Middle: Logic analyzer
        la_height = 180
        self.logic_analyzer = LogicAnalyzerWidget(
            margin, top_height + 2 * margin,
            self.width - 2 * margin, la_height,
            SignalCapture()  # Temporary, replaced in __init__
        )

        # Bottom: Dual console
        console_top = top_height + la_height + 3 * margin
        console_height = self.height - console_top - margin

        self.console = DualConsoleWidget(
            margin, console_top,
            self.width - 2 * margin, console_height
        )

    def init_pygame(self) -> bool:
        """Initialize pygame."""
        if not PYGAME_AVAILABLE:
            return False

        pygame.init()
        pygame.display.set_caption(self.title)
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.clock = pygame.time.Clock()

        # Wire up control callbacks
        self.control.on_start = self._on_start
        self.control.on_stop = self._on_stop
        self.control.on_reset = self._on_reset

        return True

    def _on_start(self):
        """Internal start handler."""
        self.capture.start()
        if self.on_start:
            self.on_start()

    def _on_stop(self):
        """Internal stop handler."""
        self.capture.stop()
        if self.on_stop:
            self.on_stop()

    def _on_reset(self):
        """Internal reset handler."""
        # Clear capture
        self.capture.stop()
        for ch in self.capture.channels.values():
            ch.clear()

        # Clear consoles
        self.console.uart_lines.clear()
        self.console.cdc_lines.clear()

        if self.on_reset:
            self.on_reset()

    def add_led(self, name: str, color: Tuple[int, int, int] = (0, 255, 0)):
        """Add an LED to the status display."""
        self.led_status.add_led(name, color)

    def set_led(self, name: str, state: bool):
        """Set LED state."""
        self.led_status.set_led(name, state)
        # Also record in signal capture
        if name in self.capture.channels:
            self.capture.record(name, 1 if state else 0)

    def add_signal(self, name: str, signal_type: SignalType = SignalType.DIGITAL,
                   color: Tuple[int, int, int] = None):
        """Add a signal channel to the logic analyzer."""
        return self.capture.add_channel(name, signal_type, color)

    def record_signal(self, name: str, value: int):
        """Record a signal transition."""
        self.capture.record(name, value)

    def add_uart_line(self, line: str):
        """Add a line to UART console."""
        self.console.add_uart_line(line)

    def add_cdc_line(self, line: str):
        """Add a line to CDC console."""
        self.console.add_cdc_line(line)

    def update_stats(self, ops: int, elapsed: float):
        """Update emulator statistics."""
        self.control.update_stats(ops, elapsed)

    def handle_events(self) -> bool:
        """
        Handle pygame events.

        Returns False if should quit.
        """
        if not PYGAME_AVAILABLE:
            return True

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            # Pass to control widget first
            if self.control.handle_event(event):
                continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q or event.key == pygame.K_ESCAPE:
                    return False
                elif event.key == pygame.K_SPACE:
                    # Toggle start/stop
                    if self.control.running:
                        self._on_stop()
                        self.control.set_running(False)
                    else:
                        self._on_start()
                        self.control.set_running(True)
                elif event.key == pygame.K_r:
                    self._on_reset()
                elif event.key == pygame.K_e:
                    # Export capture
                    self.export_capture("/tmp/slab_capture")
                elif event.key == pygame.K_PLUS or event.key == pygame.K_EQUALS:
                    self.logic_analyzer.zoom_in()
                elif event.key == pygame.K_MINUS:
                    self.logic_analyzer.zoom_out()
                elif event.key == pygame.K_LEFT:
                    self.logic_analyzer.scroll_left()
                elif event.key == pygame.K_RIGHT:
                    self.logic_analyzer.scroll_right()
                elif event.key == pygame.K_a:
                    self.logic_analyzer.toggle_auto_scroll()
                elif event.key == pygame.K_c:
                    self.console.uart_lines.clear()
                    self.console.cdc_lines.clear()

        return True

    def draw(self):
        """Draw all widgets."""
        if not self.screen:
            return

        # Background
        self.screen.fill((15, 15, 20))

        # Draw widgets
        self.control.draw(self.screen)
        self.led_status.draw(self.screen)
        self.logic_analyzer.draw(self.screen)
        self.console.draw(self.screen)

        # Help text
        font = pygame.font.Font(None, 14)
        help_text = "Space=Start/Stop  R=Reset  E=Export  +/-=Zoom  ←→=Scroll  A=AutoScroll  C=Clear  Q=Quit"
        help_surf = font.render(help_text, True, (80, 80, 80))
        self.screen.blit(help_surf, (5, self.height - 15))

        pygame.display.flip()

    def export_capture(self, basename: str):
        """Export capture to multiple formats."""
        self.capture.export_vcd(f"{basename}.vcd")
        self.capture.export_sigrok(f"{basename}.sr")
        self.capture.export_csv(f"{basename}.csv")
        print(f"Exported: {basename}.vcd, .sr, .csv")

    def run_loop(self, tick_callback: Optional[Callable[[], None]] = None,
                 fps: int = 30):
        """
        Run the main pygame loop.

        Args:
            tick_callback: Called every frame (for async integration)
            fps: Target frames per second
        """
        self.running = True

        while self.running:
            if not self.handle_events():
                break

            if tick_callback:
                tick_callback()

            self.draw()
            self.clock.tick(fps)

        # Export on exit
        self.export_capture("/tmp/final_capture")

    def close(self):
        """Close the dashboard."""
        self.running = False
        if PYGAME_AVAILABLE:
            pygame.quit()


# Export all classes
__all__ = [
    'SignalType',
    'SignalTransition',
    'SignalChannel',
    'SignalCapture',
    'LogicAnalyzerWidget',
    'DualConsoleWidget',
    'LEDStatusWidget',
    'EmulatorControlWidget',
    'DebugDashboard',
]
