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
Copyright (C) 2026 Twisted Wires Security Lab
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
    ACCENT_ORANGE = (255, 160, 80)
    ACCENT_PURPLE = (160, 120, 220)

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
# Time-Travel Debug: State Recorder
# =============================================================================

class EventType(Enum):
    """Types of recorded events."""
    MEMORY_WRITE = 1
    MEMORY_READ = 2
    PC_CHANGE = 3
    REGISTER_WRITE = 4
    GPIO_CHANGE = 5
    UART_TX = 6
    UART_RX = 7


@dataclass
class DebugEvent:
    """A single recorded debug event."""
    timestamp: float
    event_type: EventType
    address: int = 0
    value: int = 0
    size: int = 1
    data: bytes = field(default_factory=bytes)
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateRecorder:
    """Records all debug events for time-travel debugging."""

    def __init__(self, max_events: int = 100000):
        self.events: List[DebugEvent] = []
        self.max_events = max_events
        self.start_time: Optional[float] = None
        self.recording = False

        # Snapshots for efficient state reconstruction
        self.memory_snapshots: Dict[float, Dict[int, int]] = {}
        self.snapshot_interval = 1.0  # seconds

        # Current state for live tracking
        self.memory_state: Dict[int, int] = {}
        self.register_state: Dict[str, int] = {}
        self.last_snapshot_time = 0.0

    def start_recording(self):
        """Start recording events."""
        self.events.clear()
        self.memory_snapshots.clear()
        self.memory_state.clear()
        self.start_time = time.time()
        self.last_snapshot_time = self.start_time
        self.recording = True

    def stop_recording(self):
        """Stop recording events."""
        self.recording = False
        # Take final snapshot
        if self.events:
            self._take_snapshot()

    def _take_snapshot(self):
        """Take a memory snapshot for efficient replay."""
        now = time.time()
        self.memory_snapshots[now] = dict(self.memory_state)
        self.last_snapshot_time = now

    def record_memory_write(self, addr: int, value: int, size: int = 1):
        """Record a memory write event."""
        if not self.recording:
            return
        now = time.time()
        self.events.append(DebugEvent(
            timestamp=now,
            event_type=EventType.MEMORY_WRITE,
            address=addr,
            value=value,
            size=size
        ))
        # Update live state
        for i in range(size):
            self.memory_state[addr + i] = (value >> (i * 8)) & 0xFF

        # Periodic snapshot
        if now - self.last_snapshot_time >= self.snapshot_interval:
            self._take_snapshot()

        # Trim if too many events
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events // 2:]

    def record_memory_read(self, addr: int, size: int = 1):
        """Record a memory read event."""
        if not self.recording:
            return
        self.events.append(DebugEvent(
            timestamp=time.time(),
            event_type=EventType.MEMORY_READ,
            address=addr,
            size=size
        ))

    def record_pc(self, pc: int, is_branch: bool = False):
        """Record a PC change event."""
        if not self.recording:
            return
        self.events.append(DebugEvent(
            timestamp=time.time(),
            event_type=EventType.PC_CHANGE,
            address=pc,
            metadata={'is_branch': is_branch}
        ))

    def record_register(self, name: str, value: int):
        """Record a register write event."""
        if not self.recording:
            return
        self.events.append(DebugEvent(
            timestamp=time.time(),
            event_type=EventType.REGISTER_WRITE,
            value=value,
            metadata={'name': name}
        ))
        self.register_state[name] = value

    def record_gpio(self, port: str, pin: int, value: int):
        """Record a GPIO change event."""
        if not self.recording:
            return
        self.events.append(DebugEvent(
            timestamp=time.time(),
            event_type=EventType.GPIO_CHANGE,
            address=pin,
            value=value,
            metadata={'port': port}
        ))

    def get_time_range(self) -> Tuple[float, float]:
        """Get the time range of recorded events."""
        if not self.events:
            return (0.0, 0.0)
        return (self.events[0].timestamp, self.events[-1].timestamp)

    def get_state_at_time(self, target_time: float) -> Tuple[Dict[int, int], List[int]]:
        """Reconstruct memory state and recent PCs at a given time.

        Returns:
            (memory_state, recent_pcs) - memory dict and list of recent PC values
        """
        # Find nearest snapshot before target_time
        snapshot_time = None
        for t in sorted(self.memory_snapshots.keys()):
            if t <= target_time:
                snapshot_time = t
            else:
                break

        # Start from snapshot or empty
        if snapshot_time:
            memory = dict(self.memory_snapshots[snapshot_time])
        else:
            memory = {}

        # Apply events from snapshot to target_time
        recent_pcs = []
        for event in self.events:
            if snapshot_time and event.timestamp < snapshot_time:
                continue
            if event.timestamp > target_time:
                break

            if event.event_type == EventType.MEMORY_WRITE:
                for i in range(event.size):
                    memory[event.address + i] = (event.value >> (i * 8)) & 0xFF
            elif event.event_type == EventType.PC_CHANGE:
                recent_pcs.append(event.address)
                if len(recent_pcs) > 50:
                    recent_pcs = recent_pcs[-50:]

        return memory, recent_pcs

    def get_events_in_range(self, start_time: float, end_time: float,
                            event_type: Optional[EventType] = None) -> List[DebugEvent]:
        """Get events within a time range, optionally filtered by type."""
        result = []
        for event in self.events:
            if event.timestamp < start_time:
                continue
            if event.timestamp > end_time:
                break
            if event_type is None or event.event_type == event_type:
                result.append(event)
        return result


# =============================================================================
# Time-Travel Debug: Timeline Widget
# =============================================================================

class TimelineWidget:
    """Interactive timeline for time-travel debugging."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 recorder: StateRecorder):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.recorder = recorder

        # Playback state
        self.playing = False
        self.playback_speed = 1.0
        self.current_time: Optional[float] = None
        self.replay_mode = False

        # UI state
        self.dragging = False
        self.hovered = False

        self.font = None
        self.small_font = None

        # Callbacks
        self.on_time_change: Optional[Callable[[float], None]] = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 16)
            self.small_font = pygame.font.Font(None, 14)

    def set_time(self, t: float):
        """Set the current playback time."""
        start, end = self.recorder.get_time_range()
        self.current_time = max(start, min(end, t))
        if self.on_time_change:
            self.on_time_change(self.current_time)

    def toggle_play(self):
        """Toggle play/pause."""
        self.playing = not self.playing

    def step_forward(self, events: int = 1):
        """Step forward by N events."""
        if not self.recorder.events or self.current_time is None:
            return
        # Find next event after current time
        for event in self.recorder.events:
            if event.timestamp > self.current_time:
                self.set_time(event.timestamp)
                break

    def step_backward(self, events: int = 1):
        """Step backward by N events."""
        if not self.recorder.events or self.current_time is None:
            return
        # Find previous event before current time
        prev_time = None
        for event in self.recorder.events:
            if event.timestamp >= self.current_time:
                break
            prev_time = event.timestamp
        if prev_time:
            self.set_time(prev_time)

    def enter_replay_mode(self):
        """Enter replay mode at the end of recording."""
        self.replay_mode = True
        start, end = self.recorder.get_time_range()
        self.current_time = end

    def exit_replay_mode(self):
        """Exit replay mode and return to live view."""
        self.replay_mode = False
        self.current_time = None
        self.playing = False

    def update(self, dt: float):
        """Update playback position."""
        if self.playing and self.current_time is not None:
            start, end = self.recorder.get_time_range()
            self.current_time += dt * self.playback_speed
            if self.current_time >= end:
                self.current_time = end
                self.playing = False
            if self.on_time_change:
                self.on_time_change(self.current_time)

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE:
            return False

        mx, my = pygame.mouse.get_pos()
        in_bounds = (self.x <= mx <= self.x + self.width and
                     self.y <= my <= self.y + self.height)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if in_bounds and self.recorder.events:
                self.dragging = True
                self._set_time_from_x(mx)
                return True

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self.dragging:
                self.dragging = False
                return True

        elif event.type == pygame.MOUSEMOTION:
            self.hovered = in_bounds
            if self.dragging:
                self._set_time_from_x(mx)
                return True

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_SPACE and in_bounds:
                self.toggle_play()
                return True
            elif event.key == pygame.K_LEFT and self.replay_mode:
                self.step_backward()
                return True
            elif event.key == pygame.K_RIGHT and self.replay_mode:
                self.step_forward()
                return True

        return False

    def _set_time_from_x(self, mx: int):
        """Set time based on mouse X position."""
        start, end = self.recorder.get_time_range()
        if end <= start:
            return
        # Calculate time from position
        timeline_x = self.x + 50
        timeline_w = self.width - 100
        ratio = (mx - timeline_x) / timeline_w
        ratio = max(0, min(1, ratio))
        self.set_time(start + ratio * (end - start))

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        start, end = self.recorder.get_time_range()
        duration = end - start

        # Title and status
        status = "REPLAY" if self.replay_mode else "LIVE"
        status_color = Theme.ACCENT_ORANGE if self.replay_mode else Theme.ACCENT_GREEN
        title_surf = self.font.render(f"Timeline [{status}]", True, status_color)
        surface.blit(title_surf, (self.x + 8, self.y + 4))

        # Event count
        count_text = f"{len(self.recorder.events)} events"
        count_surf = self.small_font.render(count_text, True, Theme.TEXT_DIM)
        surface.blit(count_surf, (self.x + self.width - 80, self.y + 5))

        if not self.recorder.events:
            # No events message
            msg = "Recording..." if self.recorder.recording else "No events"
            msg_surf = self.font.render(msg, True, Theme.TEXT_DIM)
            surface.blit(msg_surf, (self.x + self.width // 2 - 30, self.y + self.height // 2 - 6))
            return

        # Timeline bar
        timeline_x = self.x + 50
        timeline_w = self.width - 100
        timeline_y = self.y + 24
        timeline_h = 12

        # Background bar
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (timeline_x, timeline_y, timeline_w, timeline_h), border_radius=3)

        # Event density visualization
        if duration > 0:
            bucket_count = min(timeline_w, 100)
            bucket_size = duration / bucket_count
            buckets = [0] * bucket_count

            for event in self.recorder.events:
                idx = int((event.timestamp - start) / bucket_size)
                idx = max(0, min(bucket_count - 1, idx))
                buckets[idx] += 1

            max_bucket = max(buckets) if buckets else 1
            for i, count in enumerate(buckets):
                if count > 0:
                    intensity = count / max_bucket
                    bar_h = int(timeline_h * intensity)
                    bar_x = timeline_x + int(i * timeline_w / bucket_count)
                    color = (int(60 + 140 * intensity), int(100 + 80 * intensity), 120)
                    pygame.draw.rect(surface, color,
                                   (bar_x, timeline_y + timeline_h - bar_h,
                                    max(1, timeline_w // bucket_count - 1), bar_h))

        # Current position marker
        if self.current_time is not None and duration > 0:
            pos_ratio = (self.current_time - start) / duration
            pos_x = timeline_x + int(pos_ratio * timeline_w)
            pygame.draw.rect(surface, Theme.ACCENT_RED,
                           (pos_x - 2, timeline_y - 2, 4, timeline_h + 4), border_radius=2)

        # Time labels
        if duration > 0:
            start_label = "0.0s"
            end_label = f"{duration:.1f}s"
            start_surf = self.small_font.render(start_label, True, Theme.TEXT_DIM)
            end_surf = self.small_font.render(end_label, True, Theme.TEXT_DIM)
            surface.blit(start_surf, (timeline_x, timeline_y + timeline_h + 2))
            surface.blit(end_surf, (timeline_x + timeline_w - 30, timeline_y + timeline_h + 2))

            # Current time
            if self.current_time is not None:
                cur_label = f"{self.current_time - start:.2f}s"
                cur_surf = self.font.render(cur_label, True, Theme.TEXT_PRIMARY)
                surface.blit(cur_surf, (self.x + self.width // 2 - 20, timeline_y + timeline_h + 2))

        # Playback controls hint
        if self.replay_mode:
            hint = "[Space] Play  [<][>] Step"
            hint_surf = self.small_font.render(hint, True, Theme.TEXT_DIM)
            surface.blit(hint_surf, (self.x + 8, self.y + self.height - 14))


# =============================================================================
# Input Field Widget
# =============================================================================

class InputField:
    """Text input field with cursor and selection."""

    def __init__(self, x: int, y: int, width: int, height: int = 28):
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
            self.font = pygame.font.Font(None, 22)

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
        self.line_height = 22

        # Input field at bottom
        input_height = 28
        self.input = InputField(x + 2, y + height - input_height - 2, width - 4, input_height)
        self.input.placeholder = f"Send to {title}..."

        # Callback for input
        self.on_input: Optional[Callable[[str], None]] = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 22)
            self.title_font = pygame.font.Font(None, 26)
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
                        (self.x, self.y, self.width, 28), border_radius=4)
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y + 14, self.width, 14))

        # Title
        title_surf = self.title_font.render(self.title, True, self.color)
        surface.blit(title_surf, (self.x + 8, self.y + 5))

        # Content area
        content_y = self.y + 32
        content_height = self.height - 65  # Leave room for input
        max_lines = content_height // self.line_height

        # Draw lines
        visible_lines = list(self.lines)
        if self.scroll_offset > 0:
            visible_lines = visible_lines[:-self.scroll_offset] if self.scroll_offset < len(visible_lines) else []
        visible_lines = visible_lines[-max_lines:]

        for idx, line in enumerate(visible_lines):
            line_y = content_y + idx * self.line_height
            # Truncate for larger font (approx 10px per char)
            max_chars = (self.width - 20) // 10
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
# Detached Window for Widgets
# =============================================================================

class DetachedWindow:
    """A separate window for a detached widget."""

    _windows: List['DetachedWindow'] = []  # Track all detached windows

    def __init__(self, widget, title: str, width: int = 600, height: int = 500):
        self.widget = widget
        self.title = title
        self.width = width
        self.height = height
        self.running = True
        self.screen = None
        self.clock = None

        # Save original widget position
        self.orig_x = widget.x
        self.orig_y = widget.y
        self.orig_width = widget.width
        self.orig_height = widget.height

        # Start in a thread
        self.thread = threading.Thread(target=self._run_window, daemon=True)
        self.thread.start()
        DetachedWindow._windows.append(self)

    def _run_window(self):
        """Run the detached window in its own thread."""
        if not PYGAME_AVAILABLE:
            return

        # Create new window (pygame can only have one display, so we use a subsurface approach)
        # For true multi-window, we'd need a different approach
        # Instead, we'll just mark the widget as detached and draw it larger in main window
        pass

    def close(self):
        """Close the detached window."""
        self.running = False
        # Restore original position
        self.widget.x = self.orig_x
        self.widget.y = self.orig_y
        self.widget.width = self.orig_width
        self.widget.height = self.orig_height
        if self in DetachedWindow._windows:
            DetachedWindow._windows.remove(self)

    @classmethod
    def update_all(cls):
        """Update all detached windows."""
        for win in cls._windows:
            if win.running and win.screen:
                win._draw()

    def _draw(self):
        """Draw the detached window."""
        pass


# =============================================================================
# Memory View Widget (Hexdump style)
# =============================================================================

class MemoryViewWidget:
    """Hexdump-style memory viewer with hotspot highlighting."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 title: str = "Memory", base_addr: int = 0x20000000,
                 bytes_per_row: int = 8):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.title = title
        self.base_addr = base_addr

        # Memory data (address -> byte value)
        self.memory: Dict[int, int] = {}
        # Access counts for hotspot tracking (address -> count)
        self.access_counts: Dict[int, int] = {}
        # Recent accesses for highlighting (address -> timestamp)
        self.recent_accesses: Dict[int, float] = {}

        self.scroll_offset = 0
        # Bytes per row - auto-calculate based on width if not specified
        self.bytes_per_row = bytes_per_row
        self.max_hotspot = 1

        self.font = None
        self.title_font = None
        self.char_width = 10  # Approximate monospace char width for 24pt font

        # Scrollbar state
        self.scrollbar_dragging = False
        self.scrollbar_rect = None  # Set during draw
        self.thumb_rect = None
        self.max_scroll = 1

        # Detached window
        self.detached = False
        self.detached_window = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 24)  # Large font for readability
            self.title_font = pygame.font.Font(None, 28)
            # Measure actual char width
            test_surf = self.font.render("0", True, (255, 255, 255))
            self.char_width = test_surf.get_width()

    def write(self, addr: int, value: int, size: int = 1):
        """Write value to memory and track access."""
        for i in range(size):
            byte_addr = addr + i
            byte_val = (value >> (i * 8)) & 0xFF
            self.memory[byte_addr] = byte_val
            self.access_counts[byte_addr] = self.access_counts.get(byte_addr, 0) + 1
            self.recent_accesses[byte_addr] = time.time()
            self.max_hotspot = max(self.max_hotspot, self.access_counts[byte_addr])

    def read_access(self, addr: int, size: int = 1):
        """Track a read access for hotspot highlighting."""
        for i in range(size):
            byte_addr = addr + i
            self.access_counts[byte_addr] = self.access_counts.get(byte_addr, 0) + 1
            self.recent_accesses[byte_addr] = time.time()
            self.max_hotspot = max(self.max_hotspot, self.access_counts[byte_addr])

    def set_memory_block(self, addr: int, data: bytes):
        """Set a block of memory."""
        for i, b in enumerate(data):
            self.memory[addr + i] = b

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE:
            return False

        mx, my = pygame.mouse.get_pos()
        in_widget = self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height

        # Scrollbar dragging
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Check detach button (top-right corner)
            detach_btn_x = self.x + self.width - 24
            detach_btn_y = self.y + 4
            if detach_btn_x <= mx <= detach_btn_x + 20 and detach_btn_y <= my <= detach_btn_y + 20:
                self.toggle_detach()
                return True

            # Check scrollbar click
            if self.scrollbar_rect and self.scrollbar_rect.collidepoint(mx, my):
                self.scrollbar_dragging = True
                self._update_scroll_from_mouse(my)
                return True

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.scrollbar_dragging = False

        elif event.type == pygame.MOUSEMOTION:
            if self.scrollbar_dragging and self.scrollbar_rect:
                self._update_scroll_from_mouse(my)
                return True

        elif event.type == pygame.MOUSEWHEEL:
            if in_widget:
                self.scroll_offset = max(0, min(self.max_scroll, self.scroll_offset - event.y * 2))
                return True

        return False

    def _update_scroll_from_mouse(self, mouse_y: int):
        """Update scroll position based on mouse Y position."""
        if not self.scrollbar_rect:
            return
        # Calculate scroll position from mouse
        scroll_area_top = self.scrollbar_rect.top
        scroll_area_height = self.scrollbar_rect.height
        rel_y = mouse_y - scroll_area_top
        ratio = max(0, min(1, rel_y / scroll_area_height))
        self.scroll_offset = int(ratio * self.max_scroll)

    def toggle_detach(self):
        """Toggle detached window mode."""
        self.detached = not self.detached
        if self.detached and PYGAME_AVAILABLE:
            # Create detached window
            self.detached_window = DetachedWindow(self, self.title, 500, 600)
        elif self.detached_window:
            self.detached_window.close()
            self.detached_window = None

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()
        now = time.time()

        # Background
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        # Title bar
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y, self.width, 28), border_radius=4)
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y + 14, self.width, 14))

        title_surf = self.title_font.render(self.title, True, Theme.ACCENT_CYAN)
        surface.blit(title_surf, (self.x + 8, self.y + 5))

        # Content area
        content_y = self.y + 32
        content_height = self.height - 38
        row_height = 24  # Large row height for 24pt font
        max_rows = content_height // row_height

        # Get sorted addresses
        if self.memory:
            min_addr = min(self.memory.keys()) // self.bytes_per_row * self.bytes_per_row
            max_addr = max(self.memory.keys())
        else:
            min_addr = self.base_addr
            max_addr = self.base_addr + 256

        # Calculate visible rows
        start_row = self.scroll_offset
        visible_rows = []

        for row in range(start_row, start_row + max_rows):
            row_addr = min_addr + row * self.bytes_per_row
            if row_addr > max_addr + self.bytes_per_row:
                break
            visible_rows.append(row_addr)

        # Calculate layout
        addr_width = self.char_width * 9  # "XXXXXXXX "
        hex_spacing = self.char_width * 3  # "XX "
        ascii_width = self.char_width * self.bytes_per_row

        # Draw rows
        for idx, row_addr in enumerate(visible_rows):
            y_pos = content_y + idx * row_height

            # Address (yellow)
            addr_text = f"{row_addr:08X}"
            addr_surf = self.font.render(addr_text, True, Theme.ACCENT_YELLOW)
            surface.blit(addr_surf, (self.x + 4, y_pos))

            # Hex bytes
            hex_x = self.x + 4 + addr_width
            ascii_str = ""

            for i in range(self.bytes_per_row):
                byte_addr = row_addr + i
                byte_val = self.memory.get(byte_addr, 0)
                access_count = self.access_counts.get(byte_addr, 0)
                last_access = self.recent_accesses.get(byte_addr, 0)

                # Determine color based on hotspot intensity
                if access_count > 0:
                    intensity = min(1.0, access_count / max(1, self.max_hotspot * 0.5))
                    # Recent access (< 0.5s) = bright highlight
                    if now - last_access < 0.5:
                        color = (255, 100, 100)  # Bright red for very recent
                    elif now - last_access < 2.0:
                        color = (255, 180, 100)  # Orange for recent
                    else:
                        # Gradient from dim to bright based on access count
                        r = int(60 + 140 * intensity)
                        g = int(60 + 60 * intensity)
                        b = 80
                        color = (r, g, b)
                else:
                    color = Theme.TEXT_DIM

                hex_text = f"{byte_val:02X}"
                hex_surf = self.font.render(hex_text, True, color)
                byte_x = hex_x + i * hex_spacing
                # Only draw if within bounds
                if byte_x + hex_spacing < self.x + self.width - 4:
                    surface.blit(hex_surf, (byte_x, y_pos))

                # ASCII
                if 32 <= byte_val < 127:
                    ascii_str += chr(byte_val)
                else:
                    ascii_str += "."

            # ASCII column (only if space permits)
            ascii_x = hex_x + self.bytes_per_row * hex_spacing + 4
            if ascii_x + ascii_width < self.x + self.width - 12:
                ascii_surf = self.font.render(ascii_str, True, Theme.TEXT_DIM)
                surface.blit(ascii_surf, (ascii_x, y_pos))

        # Scrollbar (wider, clickable)
        total_rows = (max_addr - min_addr) // self.bytes_per_row + 1
        self.max_scroll = max(1, total_rows - max_rows)
        if total_rows > max_rows:
            scroll_x = self.x + self.width - 16
            scroll_height = content_height
            thumb_height = max(30, scroll_height * max_rows // total_rows)
            thumb_pos = int((scroll_height - thumb_height) * self.scroll_offset / max(1, self.max_scroll))

            # Save scrollbar rect for click detection
            self.scrollbar_rect = pygame.Rect(scroll_x, content_y, 12, scroll_height)
            self.thumb_rect = pygame.Rect(scroll_x, content_y + thumb_pos, 12, thumb_height)

            # Draw scrollbar track
            pygame.draw.rect(surface, Theme.SCROLLBAR,
                           (scroll_x, content_y, 12, scroll_height), border_radius=6)
            # Draw thumb (highlighted if dragging)
            thumb_color = Theme.ACCENT_BLUE if self.scrollbar_dragging else Theme.SCROLLBAR_THUMB
            pygame.draw.rect(surface, thumb_color,
                           (scroll_x, content_y + thumb_pos, 12, thumb_height), border_radius=6)
        else:
            self.scrollbar_rect = None
            self.thumb_rect = None

        # Detach button (top-right)
        btn_x = self.x + self.width - 24
        btn_y = self.y + 4
        btn_color = Theme.ACCENT_CYAN if self.detached else Theme.TEXT_DIM
        pygame.draw.rect(surface, btn_color, (btn_x, btn_y, 18, 18), 2, border_radius=3)
        # Draw window icon
        pygame.draw.line(surface, btn_color, (btn_x + 4, btn_y + 6), (btn_x + 14, btn_y + 6), 2)
        pygame.draw.rect(surface, btn_color, (btn_x + 4, btn_y + 6, 10, 8), 1)

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)


# =============================================================================
# PC Tracker Widget (Execution Flow)
# =============================================================================

class PCTrackerWidget:
    """Program Counter tracker showing execution flow over time."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 title: str = "PC Tracker"):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.title = title

        # PC history: list of (timestamp, pc_value, is_branch)
        self.pc_history: deque = deque(maxlen=10000)
        # Region labels for annotation
        self.regions: Dict[Tuple[int, int], str] = {}
        # Hotspot tracking
        self.pc_counts: Dict[int, int] = {}
        self.max_pc_count = 1

        self.scroll_offset = 0
        self.auto_scroll = True
        self.view_mode = "list"  # "list" or "graph"

        self.font = None
        self.title_font = None

        # Scrollbar state
        self.scrollbar_dragging = False
        self.scrollbar_rect = None
        self.max_scroll = 1

        # Detach support
        self.detached = False

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 24)  # Large font for readability
            self.title_font = pygame.font.Font(None, 28)

    def add_region(self, start: int, end: int, name: str):
        """Add a named memory region for PC annotation."""
        self.regions[(start, end)] = name

    def record(self, pc: int, is_branch: bool = False):
        """Record a PC value."""
        self.pc_history.append((time.time(), pc, is_branch))
        self.pc_counts[pc] = self.pc_counts.get(pc, 0) + 1
        self.max_pc_count = max(self.max_pc_count, self.pc_counts[pc])
        if self.auto_scroll:
            self.scroll_offset = 0

    def get_region_name(self, pc: int) -> str:
        """Get region name for a PC value."""
        for (start, end), name in self.regions.items():
            if start <= pc < end:
                return name
        return ""

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE:
            return False

        mx, my = pygame.mouse.get_pos()
        in_widget = self.x <= mx <= self.x + self.width and self.y <= my <= self.y + self.height

        # Scrollbar and detach button handling
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Check detach button (top-right corner, before stats)
            detach_btn_x = self.x + self.width - 130
            detach_btn_y = self.y + 4
            if detach_btn_x <= mx <= detach_btn_x + 20 and detach_btn_y <= my <= detach_btn_y + 20:
                self.detached = not self.detached
                return True

            # Check scrollbar click
            if self.scrollbar_rect and self.scrollbar_rect.collidepoint(mx, my):
                self.scrollbar_dragging = True
                self._update_scroll_from_mouse(my)
                return True

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.scrollbar_dragging = False

        elif event.type == pygame.MOUSEMOTION:
            if self.scrollbar_dragging and self.scrollbar_rect:
                self._update_scroll_from_mouse(my)
                return True

        elif event.type == pygame.MOUSEWHEEL:
            if in_widget:
                self.scroll_offset = max(0, min(self.max_scroll, self.scroll_offset - event.y * 3))
                self.auto_scroll = (self.scroll_offset == 0)
                return True

        return False

    def _update_scroll_from_mouse(self, mouse_y: int):
        """Update scroll position based on mouse Y position."""
        if not self.scrollbar_rect:
            return
        scroll_area_top = self.scrollbar_rect.top
        scroll_area_height = self.scrollbar_rect.height
        rel_y = mouse_y - scroll_area_top
        ratio = max(0, min(1, rel_y / scroll_area_height))
        self.scroll_offset = int(ratio * self.max_scroll)
        self.auto_scroll = (self.scroll_offset == 0)

    def draw(self, surface: 'pygame.Surface'):
        if not PYGAME_AVAILABLE:
            return

        self.init_fonts()

        # Background
        pygame.draw.rect(surface, Theme.BG_SECONDARY,
                        (self.x, self.y, self.width, self.height), border_radius=4)

        # Title bar
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y, self.width, 28), border_radius=4)
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y + 14, self.width, 14))

        title_surf = self.title_font.render(self.title, True, Theme.ACCENT_PURPLE)
        surface.blit(title_surf, (self.x + 8, self.y + 5))

        # Stats
        stats_text = f"{len(self.pc_history)} samples"
        stats_surf = self.font.render(stats_text, True, Theme.TEXT_DIM)
        surface.blit(stats_surf, (self.x + self.width - 100, self.y + 6))

        # Content area
        content_y = self.y + 32
        content_height = self.height - 38

        if self.view_mode == "list":
            self._draw_list_view(surface, content_y, content_height)
        else:
            self._draw_graph_view(surface, content_y, content_height)

        # Scrollbar (for list view)
        row_height = 24
        max_rows = content_height // row_height
        total_items = len(self.pc_history)
        self.max_scroll = max(1, total_items - max_rows)

        if total_items > max_rows:
            scroll_x = self.x + self.width - 16
            scroll_height = content_height
            thumb_height = max(30, scroll_height * max_rows // total_items)
            thumb_pos = int((scroll_height - thumb_height) * self.scroll_offset / max(1, self.max_scroll))

            self.scrollbar_rect = pygame.Rect(scroll_x, content_y, 12, scroll_height)

            pygame.draw.rect(surface, Theme.SCROLLBAR,
                           (scroll_x, content_y, 12, scroll_height), border_radius=6)
            thumb_color = Theme.ACCENT_BLUE if self.scrollbar_dragging else Theme.SCROLLBAR_THUMB
            pygame.draw.rect(surface, thumb_color,
                           (scroll_x, content_y + thumb_pos, 12, thumb_height), border_radius=6)
        else:
            self.scrollbar_rect = None

        # Detach button (top-right, before stats)
        btn_x = self.x + self.width - 130
        btn_y = self.y + 4
        btn_color = Theme.ACCENT_PURPLE if self.detached else Theme.TEXT_DIM
        pygame.draw.rect(surface, btn_color, (btn_x, btn_y, 18, 18), 2, border_radius=3)
        pygame.draw.line(surface, btn_color, (btn_x + 4, btn_y + 6), (btn_x + 14, btn_y + 6), 2)
        pygame.draw.rect(surface, btn_color, (btn_x + 4, btn_y + 6, 10, 8), 1)

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)

    def _draw_list_view(self, surface: 'pygame.Surface', content_y: int, content_height: int):
        """Draw PC history as a list."""
        row_height = 24  # Large row height for 24pt font
        max_rows = content_height // row_height

        history = list(self.pc_history)
        if self.scroll_offset > 0:
            history = history[:-self.scroll_offset] if self.scroll_offset < len(history) else []
        history = history[-max_rows:]

        for idx, (ts, pc, is_branch) in enumerate(history):
            y_pos = content_y + idx * row_height

            # Hotspot intensity
            count = self.pc_counts.get(pc, 1)
            intensity = min(1.0, count / max(1, self.max_pc_count * 0.3))

            # Color based on branch and hotspot
            if is_branch:
                color = Theme.ACCENT_ORANGE
            else:
                r = int(100 + 120 * intensity)
                g = int(100 + 80 * intensity)
                b = int(100 + 50 * intensity)
                color = (r, g, b)

            # PC value
            pc_text = f"0x{pc:08X}"
            pc_surf = self.font.render(pc_text, True, color)
            surface.blit(pc_surf, (self.x + 6, y_pos))

            # Region name
            region = self.get_region_name(pc)
            if region:
                region_surf = self.font.render(region[:12], True, Theme.ACCENT_CYAN)
                surface.blit(region_surf, (self.x + 120, y_pos))

            # Count indicator (bar)
            bar_width = int(40 * intensity)
            if bar_width > 0:
                bar_color = (int(80 + 100 * intensity), 60, 60)
                pygame.draw.rect(surface, bar_color,
                               (self.x + self.width - 50, y_pos + 4, bar_width, 12))

    def _draw_graph_view(self, surface: 'pygame.Surface', content_y: int, content_height: int):
        """Draw PC history as a graph (address over time)."""
        if len(self.pc_history) < 2:
            return

        # Get min/max PC for scaling
        pcs = [pc for _, pc, _ in self.pc_history]
        min_pc = min(pcs)
        max_pc = max(pcs)
        pc_range = max(1, max_pc - min_pc)

        graph_width = self.width - 10
        graph_height = content_height - 10

        # Draw points
        points = []
        history = list(self.pc_history)[-graph_width:]

        for i, (ts, pc, is_branch) in enumerate(history):
            x = self.x + 5 + i
            y = content_y + graph_height - int((pc - min_pc) / pc_range * graph_height)
            points.append((x, y))

            # Highlight branches
            if is_branch:
                pygame.draw.circle(surface, Theme.ACCENT_ORANGE, (x, y), 2)

        # Draw line connecting points
        if len(points) > 1:
            pygame.draw.lines(surface, Theme.ACCENT_GREEN, False, points, 1)


# =============================================================================
# QEMU Control Widget (GDB Server)
# =============================================================================

class QemuControlWidget:
    """QEMU control panel using GDB server protocol."""

    def __init__(self, x: int, y: int, width: int, height: int,
                 gdb_host: str = "127.0.0.1", gdb_port: int = 1234):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.gdb_host = gdb_host
        self.gdb_port = gdb_port

        # Connection state
        self.socket = None
        self.connected = False
        self.running = False  # CPU running state
        self.last_error = ""

        # Register cache
        self.registers: Dict[str, int] = {}
        self.pc = 0

        # Button rects
        self.btn_connect = None
        self.btn_run = None
        self.btn_stop = None
        self.btn_step = None

        self.font = None
        self.title_font = None
        self.small_font = None

        # Callbacks
        self.on_stop: Optional[Callable[[int], None]] = None  # Called with PC when stopped
        self.on_step: Optional[Callable[[int], None]] = None

    def init_fonts(self):
        if PYGAME_AVAILABLE and self.font is None:
            self.font = pygame.font.Font(None, 18)
            self.title_font = pygame.font.Font(None, 22)
            self.small_font = pygame.font.Font(None, 16)

            # Create button rects
            btn_w = (self.width - 20) // 4
            btn_h = 28
            btn_y = self.y + 30
            self.btn_connect = pygame.Rect(self.x + 5, btn_y, btn_w - 2, btn_h)
            self.btn_run = pygame.Rect(self.x + 5 + btn_w, btn_y, btn_w - 2, btn_h)
            self.btn_stop = pygame.Rect(self.x + 5 + 2 * btn_w, btn_y, btn_w - 2, btn_h)
            self.btn_step = pygame.Rect(self.x + 5 + 3 * btn_w, btn_y, btn_w - 2, btn_h)

    def connect(self) -> bool:
        """Connect to QEMU GDB server."""
        import socket
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(2.0)
            self.socket.connect((self.gdb_host, self.gdb_port))
            self.socket.settimeout(0.5)
            self.connected = True
            self.last_error = ""
            # Initial handshake
            self._send_packet("qSupported")
            self._recv_packet()
            return True
        except Exception as e:
            self.last_error = str(e)
            self.connected = False
            if self.socket:
                self.socket.close()
                self.socket = None
            return False

    def disconnect(self):
        """Disconnect from GDB server."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False

    def _checksum(self, data: str) -> str:
        """Calculate GDB packet checksum."""
        return f"{sum(ord(c) for c in data) & 0xFF:02x}"

    def _send_packet(self, data: str):
        """Send a GDB packet."""
        if not self.socket:
            return
        packet = f"${data}#{self._checksum(data)}"
        self.socket.send(packet.encode())

    def _recv_packet(self) -> str:
        """Receive a GDB packet."""
        if not self.socket:
            return ""
        try:
            data = self.socket.recv(4096).decode()
            # Parse packet (skip +/- acks)
            if '$' in data:
                start = data.index('$') + 1
                end = data.index('#', start)
                return data[start:end]
            return data
        except:
            return ""

    def cmd_continue(self):
        """Continue execution."""
        if not self.connected:
            return
        self._send_packet("c")
        self.running = True

    def cmd_stop(self):
        """Stop/break execution."""
        if not self.connected or not self.socket:
            return
        # Send break (Ctrl+C)
        self.socket.send(b'\x03')
        self.running = False
        # Read stop reply
        reply = self._recv_packet()
        self._update_pc()
        if self.on_stop:
            self.on_stop(self.pc)

    def cmd_step(self):
        """Single step."""
        if not self.connected:
            return
        self._send_packet("s")
        self.running = False
        reply = self._recv_packet()
        self._update_pc()
        if self.on_step:
            self.on_step(self.pc)

    def _update_pc(self):
        """Read PC register."""
        if not self.connected:
            return
        # Read registers (ARM Cortex-M: r15 is PC)
        self._send_packet("g")
        reply = self._recv_packet()
        if reply and len(reply) >= 128:
            # PC is at offset 15*8 = 120 in hex dump (32-bit little endian)
            try:
                pc_hex = reply[120:128]
                # Convert from little-endian
                pc_bytes = bytes.fromhex(pc_hex)
                self.pc = int.from_bytes(pc_bytes, 'little')
            except:
                pass

    def read_memory(self, addr: int, size: int) -> bytes:
        """Read memory from target."""
        if not self.connected:
            return b''
        self._send_packet(f"m{addr:x},{size:x}")
        reply = self._recv_packet()
        if reply and reply != "E00":
            try:
                return bytes.fromhex(reply)
            except:
                pass
        return b''

    def handle_event(self, event: 'pygame.event.Event') -> bool:
        if not PYGAME_AVAILABLE:
            return False

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mx, my = event.pos

            if self.btn_connect and self.btn_connect.collidepoint(mx, my):
                if self.connected:
                    self.disconnect()
                else:
                    self.connect()
                return True

            if self.connected:
                if self.btn_run and self.btn_run.collidepoint(mx, my):
                    self.cmd_continue()
                    return True
                if self.btn_stop and self.btn_stop.collidepoint(mx, my):
                    self.cmd_stop()
                    return True
                if self.btn_step and self.btn_step.collidepoint(mx, my):
                    self.cmd_step()
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
                        (self.x, self.y, self.width, 24), border_radius=4)
        pygame.draw.rect(surface, Theme.BG_TERTIARY,
                        (self.x, self.y + 12, self.width, 12))

        title = "QEMU Control (GDB)"
        title_surf = self.title_font.render(title, True, Theme.ACCENT_CYAN)
        surface.blit(title_surf, (self.x + 8, self.y + 3))

        # Connection status
        status_color = Theme.ACCENT_GREEN if self.connected else Theme.ACCENT_RED
        status_text = "Connected" if self.connected else "Disconnected"
        status_surf = self.small_font.render(status_text, True, status_color)
        surface.blit(status_surf, (self.x + self.width - 80, self.y + 5))

        # Buttons
        if self.btn_connect:
            self._draw_button(surface, self.btn_connect,
                             "Disconnect" if self.connected else "Connect",
                             Theme.ACCENT_RED if self.connected else Theme.ACCENT_GREEN)

        if self.connected:
            run_color = Theme.ACCENT_GREEN if not self.running else Theme.BG_TERTIARY
            stop_color = Theme.ACCENT_RED if self.running else Theme.BG_TERTIARY
            self._draw_button(surface, self.btn_run, "Run", run_color)
            self._draw_button(surface, self.btn_stop, "Stop", stop_color)
            self._draw_button(surface, self.btn_step, "Step", Theme.ACCENT_YELLOW)

            # PC display
            pc_text = f"PC: 0x{self.pc:08X}"
            pc_surf = self.font.render(pc_text, True, Theme.TEXT_PRIMARY)
            surface.blit(pc_surf, (self.x + 8, self.y + 65))

            # Running indicator
            state_text = "Running..." if self.running else "Stopped"
            state_color = Theme.ACCENT_ORANGE if self.running else Theme.ACCENT_CYAN
            state_surf = self.font.render(state_text, True, state_color)
            surface.blit(state_surf, (self.x + 150, self.y + 65))

        # Error message
        if self.last_error:
            err_surf = self.small_font.render(self.last_error[:40], True, Theme.ACCENT_RED)
            surface.blit(err_surf, (self.x + 8, self.y + self.height - 18))

        # Border
        pygame.draw.rect(surface, Theme.BORDER,
                        (self.x, self.y, self.width, self.height), 1, border_radius=4)

    def _draw_button(self, surface: 'pygame.Surface', rect: 'pygame.Rect',
                     text: str, color: Tuple[int, int, int]):
        """Draw a button."""
        # Check hover
        mx, my = pygame.mouse.get_pos()
        hovered = rect.collidepoint(mx, my)

        # Button background
        bg_color = tuple(min(255, c + 30) for c in color) if hovered else color
        pygame.draw.rect(surface, bg_color, rect, border_radius=4)

        # Button text
        text_surf = self.small_font.render(text, True, Theme.TEXT_PRIMARY)
        text_rect = text_surf.get_rect(center=rect.center)
        surface.blit(text_surf, text_rect)


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
    'EventType',
    'DebugEvent',
    'StateRecorder',
    'TimelineWidget',
    'InputField',
    'ConsoleWidget',
    'LogicAnalyzerPro',
    'LEDStatusPro',
    'MemoryViewWidget',
    'PCTrackerWidget',
    'QemuControlWidget',
    'ControlPanel',
    'DebugDashboardPro',
    'PYGAME_AVAILABLE',
]
