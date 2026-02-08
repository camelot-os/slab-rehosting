"""
Slab HW - LaseStudio Integration

Interface to Ledger's LaseStudio laser fault injection platform.
LaseStudio provides:
- Precise XY positioning for laser targeting
- Multiple laser wavelengths (infrared, visible)
- Timing synchronization with target execution
- Automated scanning and cartography

Reference: https://github.com/Ledger-Donjon/laserstudio

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import (
    Optional, Dict, Any, Callable, Iterator, List, Tuple,
    Union, Protocol, TYPE_CHECKING
)
from enum import IntEnum, auto
from pathlib import Path
import numpy as np
import logging
import time
import json

try:
    import serial
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

from .base import (
    HardwarePlatform, HardwareConfig, PlatformCapabilities,
    PlatformCapability, TriggerPolarity
)

logger = logging.getLogger(__name__)


class LaserWavelength(IntEnum):
    """Available laser wavelengths."""
    IR_1064 = 1064      # Infrared (common for silicon)
    IR_1030 = 1030      # Infrared
    VIS_532 = 532       # Green (visible)
    VIS_635 = 635       # Red (visible)


class LaserMode(IntEnum):
    """Laser operation modes."""
    SINGLE = 0          # Single pulse
    BURST = 1           # Multiple pulses
    CONTINUOUS = 2      # CW mode
    TRIGGERED = 3       # External trigger


class ScanPattern(IntEnum):
    """XY scan patterns."""
    RASTER = 0          # Line by line
    SERPENTINE = 1      # Alternating direction
    SPIRAL = 2          # Center outward
    RANDOM = 3          # Random positions


@dataclass
class LaserSpot:
    """Laser spot configuration."""
    x: float = 0.0              # X position (mm)
    y: float = 0.0              # Y position (mm)
    z: float = 0.0              # Z/focus position (mm)
    power_mw: float = 0.0       # Laser power (mW)
    pulse_ns: float = 100.0     # Pulse width (ns)
    wavelength: LaserWavelength = LaserWavelength.IR_1064

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x_mm": self.x,
            "y_mm": self.y,
            "z_mm": self.z,
            "power_mw": self.power_mw,
            "pulse_ns": self.pulse_ns,
            "wavelength_nm": int(self.wavelength),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LaserSpot":
        return cls(
            x=data.get("x_mm", 0),
            y=data.get("y_mm", 0),
            z=data.get("z_mm", 0),
            power_mw=data.get("power_mw", 0),
            pulse_ns=data.get("pulse_ns", 100),
            wavelength=LaserWavelength(data.get("wavelength_nm", 1064)),
        )


@dataclass
class LaserTiming:
    """Laser timing configuration."""
    trigger_source: str = "external"    # external, uart, timer
    trigger_polarity: TriggerPolarity = TriggerPolarity.RISING
    delay_ns: float = 0.0               # Delay after trigger
    jitter_ns: float = 0.0              # Acceptable jitter
    timeout_ms: float = 1000.0          # Trigger timeout


@dataclass
class LaserScan:
    """XY scan configuration."""
    pattern: ScanPattern = ScanPattern.RASTER
    x_start: float = 0.0
    y_start: float = 0.0
    x_end: float = 10.0
    y_end: float = 10.0
    step_mm: float = 0.1
    dwell_ms: float = 100.0     # Time at each position
    shots_per_point: int = 1


@dataclass
class ScanResult:
    """Result from a single scan point."""
    x: float
    y: float
    success: bool               # Did the fault succeed?
    response: bytes             # Target response
    timing_ns: float            # Actual timing
    power_mw: float


class LaseStudioController(HardwarePlatform):
    """
    Interface to LaseStudio laser fault injection platform.

    Provides:
    - XY stage control for precise positioning
    - Laser power and timing control
    - Automated scanning and cartography
    - Integration with target communication
    """

    def __init__(self, config: Optional[HardwareConfig] = None):
        super().__init__(config or HardwareConfig(name="lasestudio"))
        self._serial: Optional['serial.Serial'] = None
        self._spot = LaserSpot()
        self._timing = LaserTiming()
        self._xy_position = (0.0, 0.0)
        self._z_position = 0.0
        self._laser_enabled = False

    def connect(self) -> bool:
        """Connect to LaseStudio controller."""
        if not HAS_SERIAL:
            logger.error("pyserial not installed")
            return False

        try:
            self._serial = serial.Serial(
                port=self.config.port,
                baudrate=self.config.baudrate,
                timeout=self.config.timeout,
            )

            # Test connection
            if self._send_command("*IDN?"):
                self._connected = True
                logger.info("Connected to LaseStudio")
                # Initialize to safe state
                self._send_command("LASER:OFF")
                return True

            self._serial.close()
            return False

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from LaseStudio."""
        if self._serial and self._serial.is_open:
            try:
                self._send_command("LASER:OFF")
                self._serial.close()
            except Exception:
                pass
        self._connected = False
        self._serial = None

    def get_capabilities(self) -> PlatformCapabilities:
        """Get platform capabilities."""
        return PlatformCapabilities(
            flags=(
                PlatformCapability.GLITCH_LASER |
                PlatformCapability.XY_POSITIONING |
                PlatformCapability.Z_POSITIONING |
                PlatformCapability.MICROSCOPE |
                PlatformCapability.PATTERN_TRIGGER
            ),
            xy_range_mm=(100, 100),
            xy_resolution_um=1.0,
            laser_wavelengths=[1064, 532],
            max_laser_power_mw=500.0,
            min_glitch_width_ns=1.0,
            max_glitch_width_ns=1_000_000,  # 1ms
            glitch_resolution_ns=0.1,
        )

    def _send_command(self, cmd: str, expect_response: bool = True) -> Optional[str]:
        """Send SCPI-like command."""
        if not self._serial or not self._serial.is_open:
            return None

        try:
            self._serial.write(f"{cmd}\n".encode())

            if expect_response:
                response = self._serial.readline().decode().strip()
                return response

            return ""

        except Exception as e:
            logger.error(f"Command error: {e}")
            return None

    def move_to(self, x: float, y: float, z: Optional[float] = None) -> None:
        """Move to XY(Z) position."""
        self._send_command(f"STAGE:X {x:.4f}")
        self._send_command(f"STAGE:Y {y:.4f}")
        if z is not None:
            self._send_command(f"STAGE:Z {z:.4f}")
            self._z_position = z
        self._xy_position = (x, y)

        # Wait for motion complete
        self._wait_motion_complete()

    def _wait_motion_complete(self, timeout: float = 10.0) -> bool:
        """Wait for stage motion to complete."""
        start = time.time()
        while time.time() - start < timeout:
            status = self._send_command("STAGE:STATUS?")
            if status and "IDLE" in status:
                return True
            time.sleep(0.01)
        return False

    def get_position(self) -> Tuple[float, float, float]:
        """Get current XYZ position."""
        x = float(self._send_command("STAGE:X?") or 0)
        y = float(self._send_command("STAGE:Y?") or 0)
        z = float(self._send_command("STAGE:Z?") or 0)
        return (x, y, z)

    def set_power(self, power_mw: float) -> None:
        """Set laser power in milliwatts."""
        caps = self.get_capabilities()
        if power_mw > caps.max_laser_power_mw:
            raise ValueError(f"Power exceeds maximum ({caps.max_laser_power_mw} mW)")

        self._send_command(f"LASER:POWER {power_mw:.2f}")
        self._spot.power_mw = power_mw

    def set_pulse_width(self, width_ns: float) -> None:
        """Set laser pulse width in nanoseconds."""
        self._send_command(f"LASER:PULSE {width_ns:.1f}")
        self._spot.pulse_ns = width_ns

    def set_wavelength(self, wavelength: LaserWavelength) -> None:
        """Select laser wavelength."""
        self._send_command(f"LASER:WAVE {int(wavelength)}")
        self._spot.wavelength = wavelength

    def arm(self) -> None:
        """Arm the laser trigger."""
        self._send_command("TRIG:ARM")

    def fire(self) -> None:
        """Fire laser manually."""
        self._send_command("LASER:FIRE")

    def set_timing(self, timing: LaserTiming) -> None:
        """Configure trigger timing."""
        self._timing = timing
        self._send_command(f"TRIG:SOURCE {timing.trigger_source.upper()}")
        self._send_command(f"TRIG:DELAY {timing.delay_ns:.1f}")
        self._send_command(f"TRIG:TIMEOUT {timing.timeout_ms:.1f}")

    def enable_laser(self, enable: bool = True) -> None:
        """Enable/disable laser output."""
        cmd = "LASER:ON" if enable else "LASER:OFF"
        self._send_command(cmd)
        self._laser_enabled = enable

    def wait_triggered(self, timeout: float = 1.0) -> bool:
        """Wait for trigger event."""
        start = time.time()
        while time.time() - start < timeout:
            status = self._send_command("TRIG:STATUS?")
            if status and "TRIGGERED" in status:
                return True
            time.sleep(0.001)
        return False

    def scan_area(
        self,
        scan: LaserScan,
        fire_callback: Optional[Callable[[], Tuple[bool, bytes]]] = None,
        progress_callback: Optional[Callable[[float, float, ScanResult], None]] = None
    ) -> List[ScanResult]:
        """
        Perform XY area scan with laser firing at each point.

        Args:
            scan: Scan configuration
            fire_callback: Called at each point to fire and check result
                          Returns (success, target_response)
            progress_callback: Called with results at each point

        Returns:
            List of results from each scan point
        """
        results = []

        # Calculate scan points
        x_points = int((scan.x_end - scan.x_start) / scan.step_mm) + 1
        y_points = int((scan.y_end - scan.y_start) / scan.step_mm) + 1

        y_direction = 1
        for iy in range(y_points):
            y = scan.y_start + iy * scan.step_mm

            # Serpentine: alternate direction each row
            x_range = range(x_points) if y_direction == 1 else range(x_points - 1, -1, -1)

            for ix in x_range:
                x = scan.x_start + ix * scan.step_mm

                # Move to position
                self.move_to(x, y)

                # Fire and collect result
                for shot in range(scan.shots_per_point):
                    if fire_callback:
                        success, response = fire_callback()
                    else:
                        self.arm()
                        self.fire()
                        success = True
                        response = b""

                    result = ScanResult(
                        x=x,
                        y=y,
                        success=success,
                        response=response,
                        timing_ns=self._timing.delay_ns,
                        power_mw=self._spot.power_mw,
                    )
                    results.append(result)

                    if progress_callback:
                        progress_callback(x, y, result)

                # Dwell time
                time.sleep(scan.dwell_ms / 1000)

            if scan.pattern == ScanPattern.SERPENTINE:
                y_direction *= -1

        return results

    def create_fault_map(
        self,
        results: List[ScanResult],
        output_path: Optional[str] = None
    ) -> np.ndarray:
        """
        Create 2D fault sensitivity map from scan results.

        Args:
            results: List of scan results
            output_path: Optional path to save map

        Returns:
            2D numpy array of success rates
        """
        if not results:
            return np.array([])

        # Determine grid dimensions
        x_coords = sorted(set(r.x for r in results))
        y_coords = sorted(set(r.y for r in results))

        fault_map = np.zeros((len(y_coords), len(x_coords)))

        for result in results:
            ix = x_coords.index(result.x)
            iy = y_coords.index(result.y)
            fault_map[iy, ix] += 1 if result.success else 0

        # Normalize if multiple shots per point
        shot_counts = np.zeros_like(fault_map)
        for result in results:
            ix = x_coords.index(result.x)
            iy = y_coords.index(result.y)
            shot_counts[iy, ix] += 1

        fault_map = np.divide(
            fault_map,
            shot_counts,
            out=np.zeros_like(fault_map),
            where=shot_counts > 0
        )

        if output_path:
            np.savez(
                output_path,
                fault_map=fault_map,
                x_coords=x_coords,
                y_coords=y_coords,
            )

        return fault_map

    def save_scan_results(self, results: List[ScanResult], path: str) -> None:
        """Save scan results to JSON."""
        data = {
            "results": [
                {
                    "x_mm": r.x,
                    "y_mm": r.y,
                    "success": r.success,
                    "response_hex": r.response.hex(),
                    "timing_ns": r.timing_ns,
                    "power_mw": r.power_mw,
                }
                for r in results
            ],
            "spot": self._spot.to_dict(),
            "timing": {
                "trigger_source": self._timing.trigger_source,
                "delay_ns": self._timing.delay_ns,
            },
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def load_scan_results(self, path: str) -> List[ScanResult]:
        """Load scan results from JSON."""
        with open(path) as f:
            data = json.load(f)

        return [
            ScanResult(
                x=r["x_mm"],
                y=r["y_mm"],
                success=r["success"],
                response=bytes.fromhex(r["response_hex"]),
                timing_ns=r["timing_ns"],
                power_mw=r["power_mw"],
            )
            for r in data["results"]
        ]

    def describe(self) -> str:
        """Get human-readable description."""
        lines = [
            "LaseStudio Laser Fault Injection Controller",
            f"Connected: {self._connected}",
        ]
        if self._connected:
            pos = self.get_position()
            lines.extend([
                f"Position: X={pos[0]:.3f} Y={pos[1]:.3f} Z={pos[2]:.3f} mm",
                f"Laser enabled: {self._laser_enabled}",
                f"Power: {self._spot.power_mw:.1f} mW",
                f"Pulse width: {self._spot.pulse_ns:.1f} ns",
                f"Wavelength: {int(self._spot.wavelength)} nm",
            ])
        return "\n".join(lines)


class DummyLaseStudio(LaseStudioController):
    """
    Dummy LaseStudio controller for testing.

    Simulates laser scanning without real hardware.
    """

    def __init__(self, config: Optional[HardwareConfig] = None):
        super().__init__(config or HardwareConfig(name="dummy_laser"))
        self._xy_position = (0.0, 0.0)
        self._z_position = 0.0

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def _send_command(self, cmd: str, expect_response: bool = True) -> Optional[str]:
        # Simulate command responses
        if "?" in cmd:
            if "X?" in cmd:
                return str(self._xy_position[0])
            elif "Y?" in cmd:
                return str(self._xy_position[1])
            elif "Z?" in cmd:
                return str(self._z_position)
            elif "STATUS?" in cmd:
                return "IDLE"
            return "OK"
        return "OK"

    def move_to(self, x: float, y: float, z: Optional[float] = None) -> None:
        self._xy_position = (x, y)
        if z is not None:
            self._z_position = z

    def _wait_motion_complete(self, timeout: float = 10.0) -> bool:
        return True


def create_laser_controller(
    port: str = "",
    dummy: bool = False
) -> LaseStudioController:
    """
    Create LaseStudio controller.

    Args:
        port: Serial port for real hardware
        dummy: Use dummy controller for testing

    Returns:
        LaseStudioController instance
    """
    if dummy:
        controller = DummyLaseStudio()
    else:
        config = HardwareConfig(name="lasestudio", port=port)
        controller = LaseStudioController(config)

    if not controller.connect():
        raise ConnectionError("Failed to connect to LaseStudio")

    return controller
