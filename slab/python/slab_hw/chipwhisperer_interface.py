"""
Slab HW - ChipWhisperer Integration

Interface to NewAE Technology's ChipWhisperer platform.
ChipWhisperer provides:
- Power analysis trace acquisition
- Voltage/clock glitching
- Target communication (serial)
- Pattern-based triggering

This module wraps ChipWhisperer's Python API to provide
a consistent interface with other Slab hardware modules.

Reference: https://github.com/newaetech/chipwhisperer

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import (
    Optional, Dict, Any, Callable, Iterator, List, Tuple, Union
)
from enum import IntEnum, auto
import numpy as np
import logging
import time

# Lazy import of ChipWhisperer
try:
    import chipwhisperer as cw
    HAS_CHIPWHISPERER = True
except ImportError:
    HAS_CHIPWHISPERER = False

from .base import (
    HardwarePlatform, HardwareConfig, PlatformCapabilities,
    PlatformCapability, TriggerPolarity, GlitchShape
)

logger = logging.getLogger(__name__)


class CWPlatform(IntEnum):
    """ChipWhisperer platform types."""
    LITE = 0
    PRO = 1
    HUSKY = 2
    NANO = 3


@dataclass
class CWScope:
    """ChipWhisperer scope configuration."""
    platform: CWPlatform = CWPlatform.LITE

    # ADC settings
    samples: int = 24000
    offset: int = 0
    presamples: int = 0
    decimate: int = 1
    gain_db: float = 25.0

    # Clock settings
    adc_src: str = "clkgen_x4"
    clkgen_freq: int = 7_370_000  # Default for many targets
    clkgen_mul: int = 2
    clkgen_div: int = 1

    # Trigger
    trigger_source: str = "tio4"  # GPIO4 usually trigger out


@dataclass
class CWTarget:
    """ChipWhisperer target configuration."""
    platform: str = "CW308_STM32F3"  # Target board
    programmer: str = "stm32fserial"

    # Communication
    baud: int = 38400
    protocol: str = "simpleserial"
    key_cmd: str = "k"
    plaintext_cmd: str = "p"


class ChipWhispererInterface(HardwarePlatform):
    """
    Interface to ChipWhisperer hardware.

    Provides unified access to:
    - Scope (trace acquisition)
    - Glitch (fault injection)
    - Target (communication)
    """

    def __init__(
        self,
        scope_config: Optional[CWScope] = None,
        target_config: Optional[CWTarget] = None,
    ):
        super().__init__(HardwareConfig(name="chipwhisperer"))
        self.scope_config = scope_config or CWScope()
        self.target_config = target_config or CWTarget()

        self._scope = None
        self._target = None
        self._platform_type = self.scope_config.platform

    def connect(self) -> bool:
        """Connect to ChipWhisperer."""
        if not HAS_CHIPWHISPERER:
            logger.error("ChipWhisperer not installed")
            return False

        try:
            # Connect scope
            if self._platform_type == CWPlatform.HUSKY:
                self._scope = cw.scope(type=cw.scopes.HuskyScope)
            else:
                self._scope = cw.scope()

            # Configure scope
            self._configure_scope()

            # Connect target
            self._target = cw.target(self._scope)

            self._connected = True
            logger.info(f"Connected to ChipWhisperer ({self._scope.sn})")
            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from ChipWhisperer."""
        try:
            if self._scope:
                self._scope.dis()
            if self._target:
                self._target.dis()
        except Exception:
            pass

        self._scope = None
        self._target = None
        self._connected = False

    def _configure_scope(self) -> None:
        """Apply scope configuration."""
        if not self._scope:
            return

        scope = self._scope
        cfg = self.scope_config

        # ADC settings
        scope.adc.samples = cfg.samples
        scope.adc.offset = cfg.offset
        scope.adc.presamples = cfg.presamples
        scope.adc.decimate = cfg.decimate

        # Gain
        scope.gain.db = cfg.gain_db

        # Clock
        scope.clock.adc_src = cfg.adc_src
        scope.clock.clkgen_freq = cfg.clkgen_freq

        # Trigger
        scope.trigger.triggers = cfg.trigger_source

    def get_capabilities(self) -> PlatformCapabilities:
        """Get platform capabilities."""
        flags = (
            PlatformCapability.TRACE_POWER |
            PlatformCapability.GLITCH_VOLTAGE |
            PlatformCapability.GLITCH_CLOCK |
            PlatformCapability.UART |
            PlatformCapability.PATTERN_TRIGGER
        )

        if self._platform_type == CWPlatform.HUSKY:
            flags |= PlatformCapability.MULTI_CHANNEL

        max_rate = {
            CWPlatform.LITE: 105_000_000,
            CWPlatform.PRO: 105_000_000,
            CWPlatform.HUSKY: 200_000_000,
            CWPlatform.NANO: 20_000_000,
        }.get(self._platform_type, 105_000_000)

        return PlatformCapabilities(
            flags=flags,
            max_sample_rate=max_rate,
            max_samples=100000 if self._platform_type == CWPlatform.PRO else 24000,
            adc_resolution=10,
            bandwidth=50_000_000,
            min_glitch_width_ns=2.5,
            max_glitch_width_ns=50000,
            glitch_resolution_ns=2.5,
            min_offset_ns=0,
            max_offset_ns=1_000_000_000,
        )

    # Trace acquisition interface
    def arm_acquisition(self) -> None:
        """Arm trace acquisition."""
        if self._scope:
            self._scope.arm()

    def capture_trace(self, timeout: float = 1.0) -> Optional[np.ndarray]:
        """Capture single trace."""
        if not self._scope:
            return None

        ret = self._scope.capture()
        if ret:
            logger.warning("Capture timeout")
            return None

        return self._scope.get_last_trace()

    def capture_traces(
        self,
        count: int,
        callback: Optional[Callable[[int, np.ndarray], None]] = None
    ) -> List[np.ndarray]:
        """Capture multiple traces."""
        traces = []
        for i in range(count):
            self.arm_acquisition()
            trace = self.capture_trace()
            if trace is not None:
                traces.append(trace)
                if callback:
                    callback(i, trace)
        return traces

    # Glitch interface
    def arm_glitch(self) -> None:
        """Arm glitch trigger."""
        if self._scope and hasattr(self._scope, 'glitch'):
            self._scope.glitch.arm()

    def trigger_glitch(self) -> None:
        """Manual glitch trigger."""
        if self._scope and hasattr(self._scope, 'glitch'):
            self._scope.glitch.manual_trigger()

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
            width: Glitch width as percentage of clock period
            offset: Offset as percentage of clock period
            voltage: Ignored (CW uses ext_offset instead)
            repeat: Number of glitch cycles
        """
        if not self._scope or not hasattr(self._scope, 'glitch'):
            return

        glitch = self._scope.glitch
        glitch.width = width
        glitch.offset = offset
        glitch.repeat = repeat

    def set_glitch_ext_offset(self, cycles: int) -> None:
        """Set external offset (cycles after trigger)."""
        if self._scope and hasattr(self._scope, 'glitch'):
            self._scope.glitch.ext_offset = cycles

    def set_glitch_output(self, output: str) -> None:
        """
        Set glitch output type.

        Args:
            output: "clock_xor", "clock_or", "enable_only", "glitch_only"
        """
        if self._scope and hasattr(self._scope, 'glitch'):
            self._scope.glitch.output = output

    def set_glitch_trigger(self, trigger: str) -> None:
        """
        Set glitch trigger source.

        Args:
            trigger: "ext_single", "ext_continuous", "continuous", "manual"
        """
        if self._scope and hasattr(self._scope, 'glitch'):
            self._scope.glitch.trigger_src = trigger

    # Target communication
    def target_reset(self) -> None:
        """Reset target."""
        if self._scope:
            self._scope.io.nrst = 'low'
            time.sleep(0.05)
            self._scope.io.nrst = 'high_z'
            time.sleep(0.05)

    def target_write(self, data: bytes) -> int:
        """Write to target serial."""
        if self._target:
            self._target.ser.write(data)
            return len(data)
        return 0

    def target_read(self, count: int, timeout: float = 1.0) -> bytes:
        """Read from target serial."""
        if self._target:
            return self._target.ser.read(count, timeout=int(timeout * 1000))
        return b""

    # SimpleSerial interface
    def send_key(self, key: bytes) -> None:
        """Send encryption key using SimpleSerial."""
        if self._target:
            self._target.set_key(list(key))

    def send_plaintext(self, plaintext: bytes) -> bytes:
        """
        Send plaintext and get ciphertext using SimpleSerial.

        Returns:
            Ciphertext bytes
        """
        if self._target:
            self._target.simpleserial_write('p', list(plaintext))
            return bytes(self._target.simpleserial_read('r', 16))
        return b""

    def run_crypto_operation(
        self,
        plaintext: bytes,
        key: Optional[bytes] = None
    ) -> Tuple[Optional[np.ndarray], bytes]:
        """
        Run crypto operation with trace capture.

        Args:
            plaintext: Input data
            key: Optional key (if not already set)

        Returns:
            (trace, ciphertext)
        """
        if key:
            self.send_key(key)

        self.arm_acquisition()
        ciphertext = self.send_plaintext(plaintext)
        trace = self.capture_trace()

        return trace, ciphertext

    # Campaign support
    def run_glitch_campaign(
        self,
        width_range: Tuple[float, float, float],
        offset_range: Tuple[float, float, float],
        ext_offset_range: Tuple[int, int, int],
        check_success: Callable[[], bool],
        reset_target: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run comprehensive glitch parameter sweep.

        Args:
            width_range: (min, max, step) for glitch width %
            offset_range: (min, max, step) for glitch offset %
            ext_offset_range: (min, max, step) for external offset cycles
            check_success: Function to check if glitch succeeded
            reset_target: Reset target between attempts
            progress_callback: Called with result at each point

        Returns:
            List of results with parameters and outcomes
        """
        results = []

        for ext_offset in range(ext_offset_range[0], ext_offset_range[1], ext_offset_range[2]):
            self.set_glitch_ext_offset(ext_offset)

            width = width_range[0]
            while width <= width_range[1]:
                offset = offset_range[0]
                while offset <= offset_range[1]:
                    if reset_target:
                        self.target_reset()
                        time.sleep(0.01)

                    self.set_glitch(width, offset)
                    self.arm_glitch()

                    # Trigger target operation
                    success = check_success()

                    result = {
                        "width": width,
                        "offset": offset,
                        "ext_offset": ext_offset,
                        "success": success,
                        "timestamp": time.time(),
                    }
                    results.append(result)

                    if progress_callback:
                        progress_callback(result)

                    offset += offset_range[2]
                width += width_range[2]

        return results

    def describe(self) -> str:
        """Get human-readable description."""
        lines = [
            "ChipWhisperer Interface",
            f"Connected: {self._connected}",
        ]
        if self._connected and self._scope:
            lines.extend([
                f"Serial: {self._scope.sn}",
                f"Samples: {self._scope.adc.samples}",
                f"Sample rate: {self._scope.clock.adc_freq / 1e6:.1f} MS/s",
            ])
            if hasattr(self._scope, 'glitch'):
                lines.extend([
                    f"Glitch width: {self._scope.glitch.width}%",
                    f"Glitch offset: {self._scope.glitch.offset}%",
                    f"Ext offset: {self._scope.glitch.ext_offset} cycles",
                ])
        return "\n".join(lines)


def create_cw_interface(
    platform: CWPlatform = CWPlatform.LITE,
    samples: int = 24000,
    gain_db: float = 25.0,
) -> ChipWhispererInterface:
    """
    Create and connect to ChipWhisperer.

    Args:
        platform: ChipWhisperer platform type
        samples: Number of samples per trace
        gain_db: ADC gain in dB

    Returns:
        Connected ChipWhispererInterface
    """
    scope_config = CWScope(
        platform=platform,
        samples=samples,
        gain_db=gain_db,
    )

    interface = ChipWhispererInterface(scope_config)
    if not interface.connect():
        raise ConnectionError("Failed to connect to ChipWhisperer")

    return interface
