"""
Slab HW - Base Classes for Hardware Attack Platforms

Abstract interfaces for hardware attack equipment:
- TraceAcquisition: Side-channel trace capture
- GlitchController: Voltage/clock fault injection
- LaserController: Laser/EMFI fault injection
- HardwarePlatform: Combined platform abstraction

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (
    List, Dict, Any, Optional, Callable, Iterator, Tuple,
    Union, BinaryIO, Protocol, runtime_checkable
)
from enum import IntEnum, Flag, auto
import numpy as np
from pathlib import Path
import time


class TraceFormat(IntEnum):
    """Trace data format."""
    INT8 = 0
    INT16 = 1
    INT32 = 2
    FLOAT32 = 3
    FLOAT64 = 4


class TriggerPolarity(IntEnum):
    """External trigger polarity."""
    RISING = 0
    FALLING = 1
    HIGH = 2
    LOW = 3


class GlitchShape(IntEnum):
    """Glitch waveform shape."""
    SQUARE = 0      # Simple on/off
    CROWBAR = 1     # Pull to ground
    BOOST = 2       # Voltage increase
    PULSE = 3       # Short pulse
    CUSTOM = 4      # User-defined waveform


class PlatformCapability(Flag):
    """Hardware platform capabilities."""
    NONE = 0

    # Trace acquisition
    TRACE_POWER = auto()        # Power consumption traces
    TRACE_EM = auto()           # Electromagnetic traces
    TRACE_TIMING = auto()       # Timing traces
    TRACE_PHOTON = auto()       # Photon emission

    # Fault injection
    GLITCH_VOLTAGE = auto()     # Voltage glitching
    GLITCH_CLOCK = auto()       # Clock glitching
    GLITCH_EMFI = auto()        # EM fault injection
    GLITCH_LASER = auto()       # Laser fault injection
    GLITCH_BBI = auto()         # Body-biasing injection

    # Targeting
    XY_POSITIONING = auto()     # XY stage
    Z_POSITIONING = auto()      # Z axis (focus)
    MICROSCOPE = auto()         # Integrated microscope

    # Protocol support
    UART = auto()
    SPI = auto()
    I2C = auto()
    JTAG = auto()
    SWD = auto()

    # Advanced features
    PATTERN_TRIGGER = auto()    # Pattern-based triggering
    MULTI_CHANNEL = auto()      # Multiple acquisition channels
    REAL_TIME = auto()          # Real-time processing


@dataclass
class HardwareConfig:
    """Common hardware configuration."""
    name: str = "hardware"

    # Connection
    port: str = ""              # Serial port or IP
    baudrate: int = 115200
    timeout: float = 1.0

    # Acquisition
    sample_rate: int = 125_000_000  # Samples per second
    samples_per_trace: int = 24000
    trace_format: TraceFormat = TraceFormat.INT16
    channels: int = 1

    # Trigger
    trigger_source: str = "external"
    trigger_polarity: TriggerPolarity = TriggerPolarity.RISING
    trigger_level: float = 0.5  # Volts or normalized
    trigger_offset: int = 0     # Samples before trigger

    # Glitch
    glitch_output: str = "lp"   # Low-power, hp, both
    vglitch: float = 0.0        # Glitch voltage delta
    offset_cycles: int = 0      # Cycles after trigger
    width_cycles: int = 1       # Glitch width in cycles
    repeat: int = 1             # Number of repeat glitches

    # Safety
    max_voltage: float = 3.3
    min_voltage: float = 0.0
    overcurrent_limit: float = 0.5  # Amps


@dataclass
class PlatformCapabilities:
    """Detailed platform capabilities."""
    flags: PlatformCapability = PlatformCapability.NONE

    # Trace acquisition
    max_sample_rate: int = 0
    max_samples: int = 0
    adc_resolution: int = 0     # bits
    bandwidth: int = 0          # Hz

    # Glitch timing
    min_glitch_width_ns: float = 0
    max_glitch_width_ns: float = 0
    glitch_resolution_ns: float = 0
    min_offset_ns: float = 0
    max_offset_ns: float = 0

    # XY stage
    xy_range_mm: Tuple[float, float] = (0, 0)
    xy_resolution_um: float = 0

    # Laser
    laser_wavelengths: List[int] = field(default_factory=list)
    max_laser_power_mw: float = 0


@runtime_checkable
class TraceAcquisition(Protocol):
    """Protocol for trace acquisition hardware."""

    def configure(self, config: HardwareConfig) -> None:
        """Configure acquisition parameters."""
        ...

    def arm(self) -> None:
        """Arm the acquisition trigger."""
        ...

    def capture(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """Capture a single trace. Returns None if timeout."""
        ...

    def capture_batch(
        self,
        count: int,
        callback: Optional[Callable[[int, np.ndarray], None]] = None,
        timeout: float = 10.0
    ) -> List[np.ndarray]:
        """Capture multiple traces."""
        ...

    def get_capabilities(self) -> PlatformCapabilities:
        """Get platform capabilities."""
        ...


@runtime_checkable
class GlitchController(Protocol):
    """Protocol for glitch injection hardware."""

    def configure(self, config: HardwareConfig) -> None:
        """Configure glitch parameters."""
        ...

    def arm(self) -> None:
        """Arm the glitch trigger."""
        ...

    def manual_glitch(self) -> None:
        """Trigger glitch manually."""
        ...

    def set_glitch_parameters(
        self,
        width: float,       # ns or cycles
        offset: float,      # ns or cycles
        voltage: float = 0, # V or normalized
        repeat: int = 1
    ) -> None:
        """Set glitch timing parameters."""
        ...

    def get_capabilities(self) -> PlatformCapabilities:
        """Get platform capabilities."""
        ...


@runtime_checkable
class LaserController(Protocol):
    """Protocol for laser fault injection hardware."""

    def configure(self, config: HardwareConfig) -> None:
        """Configure laser parameters."""
        ...

    def move_to(self, x: float, y: float, z: Optional[float] = None) -> None:
        """Move to XY(Z) position in mm."""
        ...

    def set_power(self, power_mw: float) -> None:
        """Set laser power in milliwatts."""
        ...

    def set_pulse_width(self, width_ns: float) -> None:
        """Set laser pulse width."""
        ...

    def arm(self) -> None:
        """Arm the laser trigger."""
        ...

    def fire(self) -> None:
        """Fire laser manually."""
        ...

    def scan_area(
        self,
        x_start: float,
        y_start: float,
        x_end: float,
        y_end: float,
        step: float,
        callback: Optional[Callable[[float, float, Any], None]] = None
    ) -> Iterator[Tuple[float, float]]:
        """Scan XY area."""
        ...

    def get_capabilities(self) -> PlatformCapabilities:
        """Get platform capabilities."""
        ...


class HardwarePlatform(ABC):
    """
    Abstract base class for hardware attack platforms.

    Combines trace acquisition and fault injection capabilities.
    Implementations should inherit from this and implement the
    required interfaces.
    """

    def __init__(self, config: Optional[HardwareConfig] = None):
        self.config = config or HardwareConfig()
        self._connected = False
        self._capabilities: Optional[PlatformCapabilities] = None

    @abstractmethod
    def connect(self) -> bool:
        """Connect to hardware. Returns True on success."""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from hardware."""
        pass

    @abstractmethod
    def get_capabilities(self) -> PlatformCapabilities:
        """Get detailed platform capabilities."""
        pass

    @property
    def connected(self) -> bool:
        """Check if connected to hardware."""
        return self._connected

    def configure(self, config: HardwareConfig) -> None:
        """Update configuration."""
        self.config = config

    # Optional: Trace acquisition interface
    def arm_acquisition(self) -> None:
        """Arm trace acquisition. Override if supported."""
        raise NotImplementedError("Trace acquisition not supported")

    def capture_trace(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """Capture single trace. Override if supported."""
        raise NotImplementedError("Trace acquisition not supported")

    def capture_traces(
        self,
        count: int,
        callback: Optional[Callable[[int, np.ndarray], None]] = None
    ) -> List[np.ndarray]:
        """Capture multiple traces. Override if supported."""
        traces = []
        for i in range(count):
            self.arm_acquisition()
            trace = self.capture_trace()
            if trace is not None:
                traces.append(trace)
                if callback:
                    callback(i, trace)
        return traces

    # Optional: Glitch interface
    def arm_glitch(self) -> None:
        """Arm glitch trigger. Override if supported."""
        raise NotImplementedError("Glitch injection not supported")

    def trigger_glitch(self) -> None:
        """Manual glitch trigger. Override if supported."""
        raise NotImplementedError("Glitch injection not supported")

    def set_glitch(
        self,
        width: float,
        offset: float,
        voltage: float = 0,
        repeat: int = 1
    ) -> None:
        """Set glitch parameters. Override if supported."""
        raise NotImplementedError("Glitch injection not supported")

    # Optional: Laser interface
    def move_laser(self, x: float, y: float, z: Optional[float] = None) -> None:
        """Move laser position. Override if supported."""
        raise NotImplementedError("Laser control not supported")

    def set_laser_power(self, power_mw: float) -> None:
        """Set laser power. Override if supported."""
        raise NotImplementedError("Laser control not supported")

    def fire_laser(self) -> None:
        """Fire laser. Override if supported."""
        raise NotImplementedError("Laser control not supported")

    # Target communication
    def target_reset(self) -> None:
        """Reset target device. Override if supported."""
        raise NotImplementedError("Target reset not supported")

    def target_write(self, data: bytes) -> int:
        """Write to target. Override if supported."""
        raise NotImplementedError("Target communication not supported")

    def target_read(self, count: int, timeout: float = 1.0) -> bytes:
        """Read from target. Override if supported."""
        raise NotImplementedError("Target communication not supported")

    # Context manager support
    def __enter__(self):
        if not self.connect():
            raise ConnectionError(f"Failed to connect to {self.config.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    # LLM-friendly interface
    def describe(self) -> str:
        """
        Get human-readable description of platform.
        Useful for LLM context.
        """
        caps = self.get_capabilities()
        lines = [
            f"Hardware Platform: {self.config.name}",
            f"Connected: {self._connected}",
            "",
            "Capabilities:",
        ]

        if PlatformCapability.TRACE_POWER in caps.flags:
            lines.append(f"  - Power trace acquisition (up to {caps.max_sample_rate/1e6:.0f} MS/s)")
        if PlatformCapability.TRACE_EM in caps.flags:
            lines.append("  - EM trace acquisition")
        if PlatformCapability.GLITCH_VOLTAGE in caps.flags:
            lines.append(f"  - Voltage glitching ({caps.min_glitch_width_ns:.1f} - {caps.max_glitch_width_ns:.1f} ns)")
        if PlatformCapability.GLITCH_CLOCK in caps.flags:
            lines.append("  - Clock glitching")
        if PlatformCapability.GLITCH_LASER in caps.flags:
            lines.append(f"  - Laser fault injection (wavelengths: {caps.laser_wavelengths})")
        if PlatformCapability.XY_POSITIONING in caps.flags:
            lines.append(f"  - XY positioning ({caps.xy_range_mm[0]}x{caps.xy_range_mm[1]} mm)")

        return "\n".join(lines)


class DummyPlatform(HardwarePlatform):
    """
    Dummy hardware platform for testing and development.

    Simulates all hardware interfaces without real hardware.
    """

    def __init__(self, config: Optional[HardwareConfig] = None):
        super().__init__(config or HardwareConfig(name="dummy"))
        self._traces: List[np.ndarray] = []
        self._glitch_armed = False
        self._laser_pos = (0.0, 0.0, 0.0)
        self._laser_power = 0.0

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            flags=(
                PlatformCapability.TRACE_POWER |
                PlatformCapability.GLITCH_VOLTAGE |
                PlatformCapability.GLITCH_CLOCK |
                PlatformCapability.UART
            ),
            max_sample_rate=125_000_000,
            max_samples=100000,
            adc_resolution=12,
            bandwidth=50_000_000,
            min_glitch_width_ns=10,
            max_glitch_width_ns=10000,
            glitch_resolution_ns=2.5,
            min_offset_ns=0,
            max_offset_ns=1_000_000_000,
        )

    def arm_acquisition(self) -> None:
        pass

    def capture_trace(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        # Generate synthetic trace
        samples = self.config.samples_per_trace
        noise = np.random.randn(samples) * 0.1
        signal = np.sin(np.linspace(0, 10 * np.pi, samples)) * 0.5
        return (signal + noise).astype(np.float32)

    def arm_glitch(self) -> None:
        self._glitch_armed = True

    def trigger_glitch(self) -> None:
        if self._glitch_armed:
            self._glitch_armed = False

    def set_glitch(
        self,
        width: float,
        offset: float,
        voltage: float = 0,
        repeat: int = 1
    ) -> None:
        self.config.width_cycles = int(width)
        self.config.offset_cycles = int(offset)
        self.config.vglitch = voltage
        self.config.repeat = repeat

    def target_reset(self) -> None:
        pass

    def target_write(self, data: bytes) -> int:
        return len(data)

    def target_read(self, count: int, timeout: float = 1.0) -> bytes:
        return b"\x00" * count
