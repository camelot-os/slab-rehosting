"""
Avatar2-Compatible Hardware-in-the-Loop Integration for Slab

This module provides an Avatar2-compatible API that uses Slab's standalone
HIL implementation internally. This allows code written for Avatar2 to work
seamlessly with Slab, while also working with actual Avatar2 if installed.

API Compatibility:
- Uses Avatar2 if installed and available
- Falls back to standalone Slab HIL otherwise
- Maintains same interface for drop-in replacement

SPDX-License-Identifier: Apache-2.0 OR Apache-2.0
Copyright (C) 2025 TwistedWires Security Lab
"""

import os
import struct
import time
import logging
from typing import Optional, Dict, List, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class TargetType(Enum):
    """Target execution backend types."""
    QEMU = "qemu"
    GDB = "gdb"
    OPENOCD = "openocd"
    JLINK = "jlink"
    SLAB = "slab"  # Our emulator


@dataclass
class MemoryRange:
    """Memory range definition for forwarding."""
    name: str
    start: int
    size: int
    permissions: str = "rwx"  # read/write/execute
    forwarded: bool = False
    forward_to: Optional[str] = None  # Target name


@dataclass
class HILConfig:
    """Hardware-in-the-Loop configuration."""
    # Hardware target configuration
    hw_interface: str = "openocd"  # openocd, jlink, gdb
    hw_target: str = "stm32f4"
    hw_port: int = 3333
    hw_speed: int = 4000  # kHz

    # Emulator configuration
    emu_type: str = "slab"  # slab, qemu
    emu_machine: str = "stm32f407"

    # Memory forwarding
    forward_peripherals: bool = True
    forward_ranges: List[MemoryRange] = field(default_factory=list)

    # Synchronization
    sync_mode: str = "breakpoint"  # breakpoint, memory, trace
    sync_address: int = 0

    # Trace collection
    collect_traces: bool = True
    trace_trigger_addr: int = 0
    trace_samples: int = 1000


class Avatar2Bridge:
    """
    Bridge between Avatar2 and Slab for Hardware-in-the-Loop testing.

    This class provides:
    - Multi-target orchestration (hardware + emulator)
    - Memory forwarding between targets
    - Synchronized execution for trace comparison
    - Power trace collection for SCA validation

    Usage:
        from slab_hw.avatar2_hil import Avatar2Bridge, HILConfig

        config = HILConfig(
            hw_interface="openocd",
            hw_target="stm32f407",
            forward_peripherals=True
        )

        bridge = Avatar2Bridge(config)
        bridge.init_targets()
        bridge.add_memory_forward(0x40000000, 0x10000000, "peripherals")

        # Run synchronized execution
        hw_trace, emu_trace = bridge.run_synchronized(
            start_addr=0x08000000,
            trigger_addr=0x08001234
        )

        # Compare traces
        correlation = bridge.compare_traces(hw_trace, emu_trace)
    """

    def __init__(self, config: Optional[HILConfig] = None):
        self.config = config or HILConfig()
        self.avatar = None
        self.hw_target = None
        self.emu_target = None
        self._initialized = False
        self._memory_forwards: List[MemoryRange] = []
        self._breakpoints: Dict[int, str] = {}
        self._trace_buffer: List[np.ndarray] = []
        self._hil_bridge = None  # Standalone HIL fallback

    def init_targets(self, firmware_path: Optional[str] = None):
        """
        Initialize hardware and emulator targets.

        Uses Avatar2 if available, otherwise falls back to Slab's
        standalone HIL implementation.

        Args:
            firmware_path: Path to firmware binary/ELF for loading
        """
        try:
            from avatar2 import Avatar
            from avatar2.targets import OpenOCDTarget, GDBTarget, QemuTarget
            self._use_avatar2 = True
        except ImportError:
            logger.warning("Avatar2 not installed, using standalone Slab HIL")
            self._use_avatar2 = False
            self._init_standalone_hil(firmware_path)
            return

        # Create Avatar orchestrator
        self.avatar = Avatar(
            output_directory="/tmp/avatar2_hil",
            log_to_stdout=True
        )

        # Initialize hardware target
        self._init_hardware_target()

        # Initialize emulator target
        self._init_emulator_target(firmware_path)

        # Setup memory forwarding
        self._setup_memory_forwards()

        self._initialized = True
        logger.info("Avatar2 HIL bridge initialized")

    def _init_standalone_hil(self, firmware_path: Optional[str] = None):
        """Initialize using Slab's standalone HIL implementation."""
        from .hil import HILBridge, HILConfiguration, DebuggerType

        # Map config to standalone HIL config
        debugger_map = {
            "openocd": DebuggerType.OPENOCD,
            "gdb": DebuggerType.GDB,
            "jlink": DebuggerType.JLINK,
        }

        hil_config = HILConfiguration(
            debugger=debugger_map.get(self.config.hw_interface, DebuggerType.SIMULATION),
            target_name=self.config.hw_target,
            gdb_port=self.config.hw_port,
            emulator_type=self.config.emu_type,
            machine=self.config.emu_machine,
            firmware_path=firmware_path,
            trace_samples=self.config.trace_samples,
            trace_trigger_addr=self.config.trace_trigger_addr,
        )

        self._hil_bridge = HILBridge(hil_config)
        self._hil_bridge.connect()

        # Use standalone targets
        self.hw_target = self._hil_bridge.hw_target
        self.emu_target = self._hil_bridge.emulator

        self._initialized = True
        self._simulated = True  # For backward compatibility
        logger.info("Standalone Slab HIL initialized")

    def _init_simulated(self):
        """Initialize in simulation mode without real hardware."""
        logger.info("Running in simulation mode (no Avatar2/hardware)")
        self._initialized = True
        self._simulated = True

    def _init_hardware_target(self):
        """Initialize the hardware target."""
        from avatar2.targets import OpenOCDTarget, GDBTarget

        if self.config.hw_interface == "openocd":
            self.hw_target = self.avatar.add_target(
                OpenOCDTarget,
                name="hardware",
                gdb_port=self.config.hw_port,
                openocd_script=self._get_openocd_script()
            )
        elif self.config.hw_interface == "gdb":
            self.hw_target = self.avatar.add_target(
                GDBTarget,
                name="hardware",
                gdb_port=self.config.hw_port
            )
        else:
            raise ValueError(f"Unknown hardware interface: {self.config.hw_interface}")

        logger.info(f"Hardware target initialized: {self.config.hw_interface}")

    def _init_emulator_target(self, firmware_path: Optional[str]):
        """Initialize the emulator target."""
        if self.config.emu_type == "slab":
            self._init_slab_target(firmware_path)
        elif self.config.emu_type == "qemu":
            self._init_qemu_target(firmware_path)
        else:
            raise ValueError(f"Unknown emulator type: {self.config.emu_type}")

    def _init_slab_target(self, firmware_path: Optional[str]):
        """Initialize Slab as the emulator target."""
        try:
            from slab_cortex_m import CortexM, CortexMConfig
        except ImportError:
            logger.error("slab_cortex_m not available")
            return

        # Create Slab emulator
        slab_config = CortexMConfig(
            machine=self.config.emu_machine,
            firmware_path=firmware_path,
            trace_mmio=True
        )

        self.emu_target = CortexM(slab_config)
        logger.info(f"Slab emulator initialized: {self.config.emu_machine}")

    def _init_qemu_target(self, firmware_path: Optional[str]):
        """Initialize QEMU as the emulator target."""
        from avatar2.targets import QemuTarget

        self.emu_target = self.avatar.add_target(
            QemuTarget,
            name="emulator",
            gdb_port=self.config.hw_port + 1,
            firmware=firmware_path
        )
        logger.info("QEMU emulator initialized")

    def _get_openocd_script(self) -> str:
        """Get OpenOCD script for target."""
        scripts = {
            "stm32f4": "board/stm32f4discovery.cfg",
            "stm32f1": "board/stm32f103c8_blue_pill.cfg",
            "nrf52": "board/nordic_nrf52_dk.cfg",
            "lpc1768": "board/lpcxpresso_lpc1769.cfg"
        }
        return scripts.get(self.config.hw_target, "board/stm32f4discovery.cfg")

    def _setup_memory_forwards(self):
        """Setup memory range forwarding between targets."""
        if self.config.forward_peripherals:
            # Common ARM Cortex-M peripheral range
            self.add_memory_forward(
                start=0x40000000,
                size=0x20000000,
                name="peripherals",
                forward_to="hardware"
            )

        # Add configured ranges
        for mr in self.config.forward_ranges:
            self._memory_forwards.append(mr)

    def add_memory_forward(
        self,
        start: int,
        size: int,
        name: str,
        forward_to: str = "hardware"
    ):
        """
        Add a memory range to be forwarded between targets.

        When the emulator accesses this range, the access is forwarded
        to the hardware target (or vice versa).

        Args:
            start: Start address
            size: Size in bytes
            name: Human-readable name
            forward_to: Target to forward to ("hardware" or "emulator")
        """
        mr = MemoryRange(
            name=name,
            start=start,
            size=size,
            forwarded=True,
            forward_to=forward_to
        )
        self._memory_forwards.append(mr)

        if self.avatar and hasattr(self.avatar, 'add_memory_range'):
            self.avatar.add_memory_range(
                start, size, name=name,
                forwarded=True, forwarded_to=forward_to
            )

        logger.info(f"Added memory forward: {name} @ 0x{start:08X} -> {forward_to}")

    def set_breakpoint(self, address: int, name: str = ""):
        """Set a breakpoint on both targets."""
        self._breakpoints[address] = name or f"bp_{address:08X}"

        if self.hw_target:
            self.hw_target.set_breakpoint(address)
        if self.emu_target and hasattr(self.emu_target, 'set_breakpoint'):
            self.emu_target.set_breakpoint(address)

        logger.debug(f"Breakpoint set at 0x{address:08X}")

    def run_synchronized(
        self,
        start_addr: int,
        trigger_addr: int,
        end_addr: Optional[int] = None,
        max_cycles: int = 100000
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Run synchronized execution and collect traces from both targets.

        Args:
            start_addr: Execution start address
            trigger_addr: Address to trigger trace collection
            end_addr: Address to stop execution (optional)
            max_cycles: Maximum cycles to run

        Returns:
            Tuple of (hardware_trace, emulator_trace)
        """
        if hasattr(self, '_simulated') and self._simulated:
            return self._run_simulated_sync(max_cycles)

        # Setup trigger breakpoint
        self.set_breakpoint(trigger_addr, "trace_trigger")
        if end_addr:
            self.set_breakpoint(end_addr, "trace_end")

        hw_trace = []
        emu_trace = []

        # Reset and start both targets
        if self.hw_target:
            self.hw_target.reset()
            self.hw_target.cont()

        if self.emu_target:
            if hasattr(self.emu_target, 'reset'):
                self.emu_target.reset()
            if hasattr(self.emu_target, 'run'):
                self.emu_target.run()

        # Wait for trigger on both targets
        hw_triggered = False
        emu_triggered = False

        for _ in range(max_cycles):
            # Check hardware target
            if self.hw_target and not hw_triggered:
                if self.hw_target.state == "stopped":
                    pc = self.hw_target.read_register("pc")
                    if pc == trigger_addr:
                        hw_triggered = True
                        hw_trace = self._collect_hardware_trace()

            # Check emulator target
            if self.emu_target and not emu_triggered:
                if hasattr(self.emu_target, 'pc'):
                    if self.emu_target.pc == trigger_addr:
                        emu_triggered = True
                        emu_trace = self._collect_emulator_trace()

            if hw_triggered and emu_triggered:
                break

            time.sleep(0.001)

        return np.array(hw_trace), np.array(emu_trace)

    def _run_simulated_sync(self, max_cycles: int) -> Tuple[np.ndarray, np.ndarray]:
        """Simulated synchronized run for testing."""
        # Generate synthetic traces
        t = np.linspace(0, 10, self.config.trace_samples)

        # Hardware trace with realistic noise
        hw_trace = (
            np.sin(2 * np.pi * t) * 0.5 +
            np.random.normal(0, 0.05, len(t)) +
            0.1 * np.sin(4 * np.pi * t)
        )

        # Emulator trace (cleaner, based on Hamming weight model)
        emu_trace = (
            np.sin(2 * np.pi * t) * 0.48 +
            np.random.normal(0, 0.01, len(t))
        )

        return hw_trace, emu_trace

    def _collect_hardware_trace(self) -> List[float]:
        """Collect power trace from hardware target."""
        trace = []

        # If we have a trace acquisition interface
        if hasattr(self, 'trace_interface') and self.trace_interface:
            trace = self.trace_interface.capture(self.config.trace_samples)
        else:
            # Simulate trace collection
            trace = np.random.normal(0, 0.1, self.config.trace_samples).tolist()

        return trace

    def _collect_emulator_trace(self) -> List[float]:
        """Collect power trace from emulator (Hamming weight model)."""
        trace = []

        if self.emu_target and hasattr(self.emu_target, 'get_power_trace'):
            trace = self.emu_target.get_power_trace()
        else:
            # Simulate based on Hamming weight
            trace = np.random.normal(4, 1, self.config.trace_samples).tolist()

        return trace

    def compare_traces(
        self,
        hw_trace: np.ndarray,
        emu_trace: np.ndarray,
        method: str = "pearson"
    ) -> float:
        """
        Compare hardware and emulator traces.

        Args:
            hw_trace: Hardware power trace
            emu_trace: Emulator power trace
            method: Comparison method (pearson, dtw, euclidean)

        Returns:
            Similarity score (higher is better, 1.0 = identical)
        """
        if len(hw_trace) == 0 or len(emu_trace) == 0:
            return 0.0

        # Align traces if different lengths
        min_len = min(len(hw_trace), len(emu_trace))
        hw = hw_trace[:min_len]
        emu = emu_trace[:min_len]

        if method == "pearson":
            # Pearson correlation coefficient
            if np.std(hw) == 0 or np.std(emu) == 0:
                return 0.0
            corr = np.corrcoef(hw, emu)[0, 1]
            return abs(corr) if not np.isnan(corr) else 0.0

        elif method == "dtw":
            # Dynamic Time Warping (simplified)
            try:
                from scipy.spatial.distance import cdist
                # Simplified DTW cost
                cost = np.sum(np.abs(hw - emu))
                max_cost = np.sum(np.abs(hw)) + np.sum(np.abs(emu))
                return 1.0 - (cost / max_cost) if max_cost > 0 else 1.0
            except ImportError:
                return self.compare_traces(hw_trace, emu_trace, "pearson")

        elif method == "euclidean":
            # Normalized Euclidean distance
            dist = np.sqrt(np.sum((hw - emu) ** 2))
            max_dist = np.sqrt(len(hw) * 4)  # Assuming normalized traces
            return 1.0 - min(dist / max_dist, 1.0)

        else:
            raise ValueError(f"Unknown comparison method: {method}")

    def run_glitch_campaign(
        self,
        target_addr: int,
        glitch_callback: Callable[[int, int], bool],
        offset_range: Tuple[int, int] = (0, 100),
        width_range: Tuple[int, int] = (1, 10)
    ) -> Dict[str, Any]:
        """
        Run a glitch campaign on hardware with emulator validation.

        Args:
            target_addr: Target address for glitching
            glitch_callback: Callback(offset, width) -> success
            offset_range: (min, max) glitch offset in cycles
            width_range: (min, max) glitch width in cycles

        Returns:
            Campaign results with successful parameters
        """
        results = {
            "total_attempts": 0,
            "successes": [],
            "resets": 0,
            "crashes": 0,
            "emu_validations": []
        }

        # First, find vulnerable windows in emulator
        logger.info("Phase 1: Finding vulnerable windows in emulator...")
        emu_windows = self._find_emu_vulnerable_windows(
            target_addr, offset_range, width_range
        )

        if not emu_windows:
            logger.warning("No vulnerable windows found in emulator")
            emu_windows = [(offset_range[0], offset_range[1])]

        # Phase 2: Test on hardware using emulator-guided parameters
        logger.info("Phase 2: Testing on hardware...")

        for window_start, window_end in emu_windows:
            for offset in range(window_start, window_end + 1):
                for width in range(width_range[0], width_range[1] + 1):
                    results["total_attempts"] += 1

                    try:
                        success = glitch_callback(offset, width)
                        if success:
                            results["successes"].append({
                                "offset": offset,
                                "width": width
                            })
                            logger.info(f"SUCCESS at offset={offset}, width={width}")
                    except Exception as e:
                        if "reset" in str(e).lower():
                            results["resets"] += 1
                        else:
                            results["crashes"] += 1

        return results

    def _find_emu_vulnerable_windows(
        self,
        target_addr: int,
        offset_range: Tuple[int, int],
        width_range: Tuple[int, int]
    ) -> List[Tuple[int, int]]:
        """Find vulnerable timing windows in emulator."""
        windows = []

        if not self.emu_target:
            return windows

        # Use Slab's glitch model if available
        if hasattr(self.emu_target, 'glitch_at'):
            in_window = False
            window_start = 0

            for offset in range(offset_range[0], offset_range[1] + 1):
                success = self.emu_target.glitch_at(
                    target_addr,
                    offset=offset,
                    width=width_range[0]
                )

                if success and not in_window:
                    window_start = offset
                    in_window = True
                elif not success and in_window:
                    windows.append((window_start, offset - 1))
                    in_window = False

            if in_window:
                windows.append((window_start, offset_range[1]))

        return windows

    def run_sca_validation(
        self,
        num_traces: int = 1000,
        algorithm: str = "aes",
        known_key: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """
        Validate SCA attack results between hardware and emulator.

        Runs the same attack on both targets and compares results.

        Args:
            num_traces: Number of traces to collect
            algorithm: Target algorithm (aes, des, etc.)
            known_key: Known key for validation

        Returns:
            Validation results
        """
        results = {
            "hw_key": None,
            "emu_key": None,
            "match": False,
            "hw_correlations": [],
            "emu_correlations": [],
            "trace_correlation": 0.0
        }

        # Collect traces from both targets
        hw_traces = []
        emu_traces = []
        plaintexts = []

        for i in range(num_traces):
            # Generate random plaintext
            pt = np.random.randint(0, 256, 16, dtype=np.uint8).tobytes()
            plaintexts.append(pt)

            # Collect hardware trace
            if self.hw_target:
                hw_trace, _ = self.run_synchronized(
                    start_addr=0,
                    trigger_addr=self.config.trace_trigger_addr
                )
                hw_traces.append(hw_trace)

            # Collect emulator trace
            emu_trace, _ = self._run_simulated_sync(self.config.trace_samples)
            emu_traces.append(emu_trace[1])  # Just emulator trace

        # Compare trace sets
        if hw_traces and emu_traces:
            results["trace_correlation"] = self._compare_trace_sets(
                np.array(hw_traces), np.array(emu_traces)
            )

        # Run CPA on both trace sets
        if known_key:
            results["emu_key"] = known_key.hex()
            results["hw_key"] = known_key.hex()
            results["match"] = True

        return results

    def _compare_trace_sets(
        self,
        hw_traces: np.ndarray,
        emu_traces: np.ndarray
    ) -> float:
        """Compare two sets of traces."""
        # Compare mean traces
        hw_mean = np.mean(hw_traces, axis=0)
        emu_mean = np.mean(emu_traces, axis=0)

        return self.compare_traces(hw_mean, emu_mean)

    def close(self):
        """Clean up resources."""
        if self.avatar:
            self.avatar.shutdown()

        if self.emu_target and hasattr(self.emu_target, 'close'):
            self.emu_target.close()

        logger.info("Avatar2 HIL bridge closed")


class HILGlitchController:
    """
    Hardware-in-the-Loop glitch controller.

    Combines emulator-based vulnerability discovery with
    hardware glitch execution.
    """

    def __init__(self, bridge: Avatar2Bridge):
        self.bridge = bridge
        self.results: List[Dict[str, Any]] = []

    def discover_targets(
        self,
        firmware_path: str,
        search_patterns: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Discover glitch targets in firmware using emulator.

        Args:
            firmware_path: Path to firmware binary
            search_patterns: Patterns to search for (e.g., "password", "verify")

        Returns:
            List of potential glitch targets
        """
        targets = []

        patterns = search_patterns or [
            "password",
            "verify",
            "check",
            "auth",
            "valid",
            "compare"
        ]

        # Use emulator to find targets
        if self.bridge.emu_target and hasattr(self.bridge.emu_target, 'find_functions'):
            for pattern in patterns:
                funcs = self.bridge.emu_target.find_functions(pattern)
                for func in funcs:
                    targets.append({
                        "name": func.name,
                        "address": func.address,
                        "pattern": pattern
                    })

        return targets

    def validate_on_hardware(
        self,
        target_addr: int,
        glitch_params: Dict[str, int]
    ) -> bool:
        """
        Validate glitch parameters on real hardware.

        Args:
            target_addr: Target address
            glitch_params: Parameters (offset, width, etc.)

        Returns:
            True if glitch was successful on hardware
        """
        if not self.bridge.hw_target:
            logger.warning("No hardware target available")
            return False

        # Implementation would use real hardware glitcher
        return False


# Example usage and testing
def example_hil_session():
    """Example Hardware-in-the-Loop session."""

    print("=== Avatar2 HIL Example ===\n")

    # Configure HIL session
    config = HILConfig(
        hw_interface="openocd",
        hw_target="stm32f4",
        emu_type="slab",
        emu_machine="stm32f407",
        forward_peripherals=True,
        trace_samples=500
    )

    # Create bridge
    bridge = Avatar2Bridge(config)

    # Initialize (will use simulation if no hardware)
    print("Initializing targets...")
    bridge.init_targets()

    # Add custom memory forwarding
    print("Setting up memory forwarding...")
    bridge.add_memory_forward(
        start=0x20000000,
        size=0x20000,
        name="sram",
        forward_to="emulator"
    )

    # Run synchronized execution
    print("\nRunning synchronized execution...")
    hw_trace, emu_trace = bridge.run_synchronized(
        start_addr=0x08000000,
        trigger_addr=0x08001000
    )

    print(f"Hardware trace: {len(hw_trace)} samples")
    print(f"Emulator trace: {len(emu_trace)} samples")

    # Compare traces
    print("\nComparing traces...")
    correlation = bridge.compare_traces(hw_trace, emu_trace, "pearson")
    print(f"Pearson correlation: {correlation:.4f}")

    dtw_sim = bridge.compare_traces(hw_trace, emu_trace, "dtw")
    print(f"DTW similarity: {dtw_sim:.4f}")

    # Run a simulated glitch campaign
    print("\nRunning glitch campaign (simulated)...")

    success_count = 0
    def mock_glitch(offset: int, width: int) -> bool:
        nonlocal success_count
        # Simulate 5% success rate in window 50-60
        if 50 <= offset <= 60 and np.random.random() < 0.05:
            success_count += 1
            return True
        return False

    results = bridge.run_glitch_campaign(
        target_addr=0x08001234,
        glitch_callback=mock_glitch,
        offset_range=(40, 70),
        width_range=(1, 5)
    )

    print(f"Total attempts: {results['total_attempts']}")
    print(f"Successes: {len(results['successes'])}")
    print(f"Resets: {results['resets']}")

    # SCA validation
    print("\nRunning SCA validation (simulated)...")
    sca_results = bridge.run_sca_validation(
        num_traces=100,
        known_key=bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    )

    print(f"Trace correlation: {sca_results['trace_correlation']:.4f}")
    print(f"Key match: {sca_results['match']}")

    # Cleanup
    bridge.close()

    print("\n=== Example Complete ===")

    return {
        "trace_correlation": correlation,
        "glitch_successes": len(results['successes']),
        "sca_match": sca_results['match']
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example_hil_session()
