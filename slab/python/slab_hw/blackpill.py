"""
Slab HW - BlackPill Glitch Controller

Interface for STM32F4-based (BlackPill) glitch controllers.
The BlackPill provides:
- High-speed voltage glitching via external MOSFET
- Precise timing using TIM1-TIM8 hardware timers
- External trigger input on PA0
- UART communication for control

Hardware setup:
- BlackPill (STM32F401/F411) development board
- External glitch MOSFET (e.g., IRLML2502) on PA8 (TIM1_CH1)
- Target power through glitch circuit
- UART1 (PA9/PA10) for control
- External trigger input on PA0

Protocol:
- Binary command protocol over UART
- Commands: ARM, GLITCH, CONFIG, STATUS
- Responses: ACK, NAK, DATA

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, Tuple, List
from enum import IntEnum, auto
import struct
import time
import logging

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from .base import (
    HardwarePlatform, HardwareConfig, PlatformCapabilities,
    PlatformCapability, GlitchShape, TriggerPolarity
)

logger = logging.getLogger(__name__)


class Command(IntEnum):
    """BlackPill protocol commands."""
    NOP = 0x00
    ARM = 0x01          # Arm trigger
    DISARM = 0x02       # Disarm trigger
    GLITCH = 0x03       # Manual glitch
    CONFIG = 0x04       # Set configuration
    STATUS = 0x05       # Get status
    RESET = 0x06        # Reset target
    VERSION = 0x07      # Get firmware version
    CALIBRATE = 0x08    # Calibration mode
    SET_TRIGGER = 0x10  # Configure trigger
    SET_GLITCH = 0x11   # Configure glitch params
    SET_DELAY = 0x12    # Set delay parameters
    GET_TRACE = 0x20    # Get timing trace (if ADC equipped)
    GPIO_SET = 0x30     # Set GPIO output
    GPIO_GET = 0x31     # Get GPIO input
    UART_TX = 0x40      # Send to target UART
    UART_RX = 0x41      # Receive from target UART


class Response(IntEnum):
    """BlackPill protocol responses."""
    ACK = 0x80
    NAK = 0x81
    DATA = 0x82
    TRIGGERED = 0x83    # Glitch triggered
    TIMEOUT = 0x84      # Trigger timeout
    ERROR = 0x85


class GlitcherState(IntEnum):
    """Glitch controller state."""
    IDLE = 0
    ARMED = 1
    TRIGGERED = 2
    ERROR = 3


@dataclass
class GlitchWaveform:
    """Glitch waveform configuration."""
    shape: GlitchShape = GlitchShape.CROWBAR
    width_ns: float = 100.0     # Glitch width
    rise_ns: float = 5.0        # Rise time (if controllable)
    fall_ns: float = 5.0        # Fall time (if controllable)
    voltage_high: float = 3.3   # Normal voltage
    voltage_low: float = 0.0    # Glitch voltage
    repeat_count: int = 1       # Number of glitches
    repeat_delay_ns: float = 0  # Delay between repeats


@dataclass
class TriggerConfig:
    """Trigger configuration."""
    source: str = "external"    # external, uart, timer
    polarity: TriggerPolarity = TriggerPolarity.RISING
    level: float = 1.65         # Voltage threshold
    filter_ns: float = 0        # Glitch filter
    holdoff_ns: float = 0       # Minimum time between triggers

    # UART trigger
    uart_pattern: bytes = b""
    uart_mask: bytes = b""

    # Timer trigger
    timer_delay_ns: float = 0


@dataclass
class BlackPillConfig(HardwareConfig):
    """BlackPill-specific configuration."""
    # Timer configuration
    timer_clock_hz: int = 168_000_000   # STM32F4 timer clock
    timer_prescaler: int = 0            # Timer prescaler

    # Glitch output
    glitch_pin: str = "PA8"     # TIM1_CH1
    glitch_invert: bool = False

    # Trigger input
    trigger_pin: str = "PA0"

    # Target UART
    target_uart_tx: str = "PA2"
    target_uart_rx: str = "PA3"
    target_baudrate: int = 115200

    # Safety
    max_glitch_width_ns: float = 10000  # 10us max
    max_repeat_count: int = 10


class BlackPillGlitcher(HardwarePlatform):
    """
    STM32F4 BlackPill-based glitch controller.

    Provides high-speed voltage glitching with:
    - Hardware timer-based precise timing
    - External trigger input
    - UART pattern trigger
    - Target UART pass-through
    """

    # Protocol constants
    SYNC_BYTE = 0x55
    HEADER_SIZE = 4  # sync + cmd + len(2)

    def __init__(self, config: Optional[BlackPillConfig] = None):
        super().__init__(config or BlackPillConfig(name="blackpill"))
        self.config: BlackPillConfig = self.config  # Type hint
        self._serial: Optional['serial.Serial'] = None
        self._state = GlitcherState.IDLE
        self._firmware_version = ""
        self._glitch_waveform = GlitchWaveform()
        self._trigger_config = TriggerConfig()
        self._offset_ns: float = 0
        self._last_trigger_time: float = 0

    def connect(self) -> bool:
        """Connect to BlackPill via serial."""
        if not HAS_SERIAL:
            logger.error("pyserial not installed")
            return False

        try:
            self._serial = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
            )

            # Flush any pending data
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()

            # Check connection with version command
            version = self._get_version()
            if version:
                self._firmware_version = version
                self._connected = True
                logger.info(f"Connected to BlackPill firmware {version}")
                return True

            logger.error("Failed to get version from BlackPill")
            self._serial.close()
            return False

        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from BlackPill."""
        if self._serial and self._serial.is_open:
            try:
                self._send_command(Command.DISARM)
                self._serial.close()
            except Exception:
                pass
        self._connected = False
        self._serial = None

    def get_capabilities(self) -> PlatformCapabilities:
        """Get BlackPill capabilities."""
        return PlatformCapabilities(
            flags=(
                PlatformCapability.GLITCH_VOLTAGE |
                PlatformCapability.UART |
                PlatformCapability.PATTERN_TRIGGER
            ),
            min_glitch_width_ns=10,  # ~6ns with 168MHz timer
            max_glitch_width_ns=self.config.max_glitch_width_ns,
            glitch_resolution_ns=1000 / (self.config.timer_clock_hz / 1e9),
            min_offset_ns=0,
            max_offset_ns=1_000_000_000,  # 1 second
        )

    def _send_command(
        self,
        cmd: Command,
        data: bytes = b"",
        expect_response: bool = True
    ) -> Tuple[Response, bytes]:
        """Send command to BlackPill."""
        if not self._serial or not self._serial.is_open:
            return Response.ERROR, b""

        # Build packet: SYNC + CMD + LEN(2) + DATA
        length = len(data)
        packet = struct.pack("<BBH", self.SYNC_BYTE, cmd, length) + data

        try:
            self._serial.write(packet)

            if not expect_response:
                return Response.ACK, b""

            # Read response header
            header = self._serial.read(self.HEADER_SIZE)
            if len(header) < self.HEADER_SIZE:
                return Response.TIMEOUT, b""

            sync, resp, resp_len = struct.unpack("<BBH", header)
            if sync != self.SYNC_BYTE:
                return Response.ERROR, b""

            # Read response data
            resp_data = b""
            if resp_len > 0:
                resp_data = self._serial.read(resp_len)

            return Response(resp), resp_data

        except Exception as e:
            logger.error(f"Command error: {e}")
            return Response.ERROR, b""

    def _get_version(self) -> str:
        """Get firmware version."""
        resp, data = self._send_command(Command.VERSION)
        if resp == Response.DATA and data:
            return data.decode("utf-8", errors="ignore").strip("\x00")
        return ""

    def arm_glitch(self) -> None:
        """Arm the glitch trigger."""
        resp, _ = self._send_command(Command.ARM)
        if resp == Response.ACK:
            self._state = GlitcherState.ARMED
        else:
            raise RuntimeError("Failed to arm glitch trigger")

    def disarm(self) -> None:
        """Disarm the glitch trigger."""
        resp, _ = self._send_command(Command.DISARM)
        self._state = GlitcherState.IDLE

    def trigger_glitch(self) -> None:
        """Trigger glitch manually."""
        resp, _ = self._send_command(Command.GLITCH)
        if resp == Response.ACK:
            self._state = GlitcherState.TRIGGERED
            self._last_trigger_time = time.time()

    def wait_triggered(self, timeout: float = 1.0) -> bool:
        """
        Wait for trigger event.

        Returns True if triggered, False if timeout.
        """
        if not self._serial:
            return False

        start = time.time()
        self._serial.timeout = timeout

        try:
            # Wait for TRIGGERED response
            header = self._serial.read(self.HEADER_SIZE)
            if len(header) >= self.HEADER_SIZE:
                sync, resp, _ = struct.unpack("<BBH", header)
                if sync == self.SYNC_BYTE and resp == Response.TRIGGERED:
                    self._state = GlitcherState.TRIGGERED
                    self._last_trigger_time = time.time()
                    return True
        except Exception:
            pass

        return False

    def set_glitch(
        self,
        width: float,
        offset: float,
        voltage: float = 0,
        repeat: int = 1
    ) -> None:
        """
        Set glitch parameters.

        Args:
            width: Glitch width in nanoseconds
            offset: Delay from trigger in nanoseconds
            voltage: Glitch voltage (0 = crowbar to GND)
            repeat: Number of glitch pulses
        """
        self._glitch_waveform.width_ns = width
        self._offset_ns = offset
        self._glitch_waveform.voltage_low = voltage
        self._glitch_waveform.repeat_count = repeat

        # Pack parameters for firmware
        # Format: width_ns(4) + offset_ns(4) + voltage_mv(2) + repeat(1)
        data = struct.pack(
            "<IIhB",
            int(width),
            int(offset),
            int(voltage * 1000),  # Convert to mV
            min(repeat, self.config.max_repeat_count)
        )

        resp, _ = self._send_command(Command.SET_GLITCH, data)
        if resp != Response.ACK:
            raise RuntimeError("Failed to set glitch parameters")

    def set_trigger(self, config: TriggerConfig) -> None:
        """Configure trigger source."""
        self._trigger_config = config

        # Pack trigger config
        # Format: source(1) + polarity(1) + filter_ns(4) + pattern_len(1) + pattern
        source_map = {"external": 0, "uart": 1, "timer": 2}
        data = struct.pack(
            "<BBIB",
            source_map.get(config.source, 0),
            int(config.polarity),
            int(config.filter_ns),
            len(config.uart_pattern)
        )
        data += config.uart_pattern[:8]  # Max 8 bytes pattern

        resp, _ = self._send_command(Command.SET_TRIGGER, data)
        if resp != Response.ACK:
            raise RuntimeError("Failed to set trigger configuration")

    def target_reset(self) -> None:
        """Reset target via GPIO."""
        resp, _ = self._send_command(Command.RESET)
        if resp != Response.ACK:
            raise RuntimeError("Failed to reset target")

    def target_write(self, data: bytes) -> int:
        """Write to target UART."""
        if len(data) > 64:
            # Send in chunks
            sent = 0
            for i in range(0, len(data), 64):
                chunk = data[i:i+64]
                resp, _ = self._send_command(Command.UART_TX, chunk)
                if resp == Response.ACK:
                    sent += len(chunk)
                else:
                    break
            return sent

        resp, _ = self._send_command(Command.UART_TX, data)
        return len(data) if resp == Response.ACK else 0

    def target_read(self, count: int, timeout: float = 1.0) -> bytes:
        """Read from target UART."""
        # Request read
        data = struct.pack("<HH", count, int(timeout * 1000))
        resp, result = self._send_command(Command.UART_RX, data)
        if resp == Response.DATA:
            return result
        return b""

    def gpio_set(self, pin: int, state: bool) -> None:
        """Set GPIO output."""
        data = struct.pack("<BB", pin, 1 if state else 0)
        self._send_command(Command.GPIO_SET, data)

    def gpio_get(self, pin: int) -> bool:
        """Get GPIO input."""
        data = struct.pack("<B", pin)
        resp, result = self._send_command(Command.GPIO_GET, data)
        if resp == Response.DATA and result:
            return result[0] != 0
        return False

    def calibrate_timing(self) -> Dict[str, float]:
        """
        Run timing calibration.

        Measures actual glitch timing to account for propagation delays.
        """
        resp, data = self._send_command(Command.CALIBRATE)
        if resp == Response.DATA and len(data) >= 12:
            trigger_delay_ns, glitch_delay_ns, jitter_ns = struct.unpack("<III", data[:12])
            return {
                "trigger_delay_ns": trigger_delay_ns,
                "glitch_delay_ns": glitch_delay_ns,
                "jitter_ns": jitter_ns,
            }
        return {}

    def get_status(self) -> Dict[str, Any]:
        """Get controller status."""
        resp, data = self._send_command(Command.STATUS)
        if resp == Response.DATA and len(data) >= 8:
            state, triggers, glitches, errors = struct.unpack("<BBHI", data[:8])
            return {
                "state": GlitcherState(state).name,
                "trigger_count": triggers,
                "glitch_count": glitches,
                "error_count": errors,
                "firmware_version": self._firmware_version,
            }
        return {"state": "UNKNOWN"}

    # Campaign support
    def run_glitch_sweep(
        self,
        width_range: Tuple[float, float, float],   # (min, max, step) ns
        offset_range: Tuple[float, float, float],  # (min, max, step) ns
        callback: Optional[Callable[[float, float, bool], None]] = None,
        reset_between: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Run a glitch parameter sweep.

        Args:
            width_range: (min_ns, max_ns, step_ns)
            offset_range: (min_ns, max_ns, step_ns)
            callback: Called with (width, offset, success)
            reset_between: Reset target between attempts

        Returns:
            List of results with parameters and outcomes
        """
        results = []

        width_min, width_max, width_step = width_range
        offset_min, offset_max, offset_step = offset_range

        width = width_min
        while width <= width_max:
            offset = offset_min
            while offset <= offset_max:
                if reset_between:
                    self.target_reset()
                    time.sleep(0.01)

                # Configure and arm
                self.set_glitch(width, offset)
                self.arm_glitch()

                # Wait for trigger
                triggered = self.wait_triggered(timeout=1.0)

                result = {
                    "width_ns": width,
                    "offset_ns": offset,
                    "triggered": triggered,
                    "timestamp": time.time(),
                }

                results.append(result)
                if callback:
                    callback(width, offset, triggered)

                offset += offset_step
            width += width_step

        return results

    def describe(self) -> str:
        """Get human-readable description."""
        status = self.get_status() if self._connected else {}
        lines = [
            f"BlackPill Glitch Controller",
            f"Port: {self.config.port}",
            f"Connected: {self._connected}",
        ]
        if self._connected:
            lines.extend([
                f"Firmware: {self._firmware_version}",
                f"State: {status.get('state', 'UNKNOWN')}",
                f"Glitch width: {self._glitch_waveform.width_ns:.1f} ns",
                f"Glitch offset: {self._offset_ns:.1f} ns",
            ])
        return "\n".join(lines)


def create_blackpill_glitcher(
    port: str,
    baudrate: int = 921600
) -> BlackPillGlitcher:
    """
    Create and connect to BlackPill glitcher.

    Args:
        port: Serial port (e.g., "/dev/ttyACM0", "COM3")
        baudrate: Serial baudrate (default 921600 for fast transfers)

    Returns:
        Connected BlackPillGlitcher instance
    """
    config = BlackPillConfig(
        name="blackpill",
        port=port,
        baudrate=baudrate,
    )
    glitcher = BlackPillGlitcher(config)
    if not glitcher.connect():
        raise ConnectionError(f"Failed to connect to BlackPill on {port}")
    return glitcher
