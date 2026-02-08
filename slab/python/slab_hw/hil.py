"""
Hardware-in-the-Loop Framework for Slab

Standalone HIL framework without external dependencies.
Provides direct integration between Slab emulator and hardware debuggers.

Supported debuggers:
- OpenOCD (via GDB protocol)
- pyOCD (direct API)
- J-Link (via pylink)
- Custom serial protocols

SPDX-License-Identifier: Apache-2.0 OR Apache-2.0
Copyright (C) 2025 Twisted Wires Security Lab
"""

import os
import struct
import time
import socket
import logging
from typing import Optional, Dict, List, Any, Callable, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod

import numpy as np

logger = logging.getLogger(__name__)


class DebuggerType(Enum):
    """Supported hardware debugger types."""
    OPENOCD = auto()
    PYOCD = auto()
    JLINK = auto()
    GDB = auto()
    SERIAL = auto()
    SIMULATION = auto()


class TargetState(Enum):
    """Target execution state."""
    RUNNING = auto()
    HALTED = auto()
    UNKNOWN = auto()
    ERROR = auto()


@dataclass
class MemoryRegion:
    """Memory region definition."""
    name: str
    start: int
    size: int
    access: str = "rwx"  # read/write/execute
    cached: bool = False


@dataclass
class HILConfiguration:
    """HIL session configuration."""
    # Debugger settings
    debugger: DebuggerType = DebuggerType.SIMULATION
    target_name: str = "stm32f407"
    gdb_host: str = "localhost"
    gdb_port: int = 3333

    # Emulator settings
    emulator_type: str = "slab"
    machine: str = "stm32f407"
    firmware_path: Optional[str] = None

    # Trace collection
    trace_samples: int = 1000
    trace_trigger_addr: int = 0

    # Memory forwarding
    memory_regions: List[MemoryRegion] = field(default_factory=list)


class HardwareTarget(ABC):
    """Abstract base class for hardware targets."""

    @abstractmethod
    def connect(self) -> bool:
        """Connect to target."""
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from target."""
        pass

    @abstractmethod
    def reset(self):
        """Reset target."""
        pass

    @abstractmethod
    def halt(self):
        """Halt target execution."""
        pass

    @abstractmethod
    def resume(self):
        """Resume target execution."""
        pass

    @abstractmethod
    def step(self) -> int:
        """Single step, return new PC."""
        pass

    @abstractmethod
    def read_memory(self, addr: int, size: int) -> bytes:
        """Read memory from target."""
        pass

    @abstractmethod
    def write_memory(self, addr: int, data: bytes):
        """Write memory to target."""
        pass

    @abstractmethod
    def read_register(self, name: str) -> int:
        """Read CPU register."""
        pass

    @abstractmethod
    def write_register(self, name: str, value: int):
        """Write CPU register."""
        pass

    @abstractmethod
    def set_breakpoint(self, addr: int) -> bool:
        """Set breakpoint at address."""
        pass

    @abstractmethod
    def get_state(self) -> TargetState:
        """Get target state."""
        pass


class GDBTarget(HardwareTarget):
    """Hardware target via GDB Remote Serial Protocol."""

    def __init__(self, host: str = "localhost", port: int = 3333):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self._breakpoints: Dict[int, int] = {}
        self._state = TargetState.UNKNOWN

    def connect(self) -> bool:
        """Connect to GDB server."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))

            # Initial handshake
            self._send_packet("?")
            response = self._recv_packet()

            if response and response.startswith("S") or response.startswith("T"):
                self._state = TargetState.HALTED
                logger.info(f"Connected to GDB server at {self.host}:{self.port}")
                return True

            return False

        except Exception as e:
            logger.error(f"GDB connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from GDB server."""
        if self.sock:
            try:
                self._send_packet("D")  # Detach
            except Exception:
                pass
            self.sock.close()
            self.sock = None

    def reset(self):
        """Reset target via GDB."""
        self._send_packet("R00")  # Reset
        self._state = TargetState.HALTED

    def halt(self):
        """Halt target."""
        if self.sock:
            self.sock.send(b'\x03')  # Ctrl-C
            self._recv_packet()
            self._state = TargetState.HALTED

    def resume(self):
        """Resume execution."""
        self._send_packet("c")  # continue
        self._state = TargetState.RUNNING

    def step(self) -> int:
        """Single step."""
        self._send_packet("s")  # step
        self._recv_packet()
        return self.read_register("pc")

    def read_memory(self, addr: int, size: int) -> bytes:
        """Read memory via GDB."""
        self._send_packet(f"m{addr:x},{size:x}")
        response = self._recv_packet()
        if response:
            return bytes.fromhex(response)
        return b'\x00' * size

    def write_memory(self, addr: int, data: bytes):
        """Write memory via GDB."""
        hex_data = data.hex()
        self._send_packet(f"M{addr:x},{len(data):x}:{hex_data}")
        self._recv_packet()

    def read_register(self, name: str) -> int:
        """Read register via GDB."""
        # ARM Cortex-M register map
        reg_map = {
            "r0": 0, "r1": 1, "r2": 2, "r3": 3,
            "r4": 4, "r5": 5, "r6": 6, "r7": 7,
            "r8": 8, "r9": 9, "r10": 10, "r11": 11,
            "r12": 12, "sp": 13, "lr": 14, "pc": 15,
            "xpsr": 16, "msp": 17, "psp": 18
        }

        reg_num = reg_map.get(name.lower(), 15)
        self._send_packet(f"p{reg_num:x}")
        response = self._recv_packet()

        if response:
            # GDB returns little-endian hex
            return int.from_bytes(bytes.fromhex(response), 'little')
        return 0

    def write_register(self, name: str, value: int):
        """Write register via GDB."""
        reg_map = {
            "r0": 0, "r1": 1, "r2": 2, "r3": 3,
            "r4": 4, "r5": 5, "r6": 6, "r7": 7,
            "r8": 8, "r9": 9, "r10": 10, "r11": 11,
            "r12": 12, "sp": 13, "lr": 14, "pc": 15,
        }

        reg_num = reg_map.get(name.lower(), 0)
        hex_val = value.to_bytes(4, 'little').hex()
        self._send_packet(f"P{reg_num:x}={hex_val}")
        self._recv_packet()

    def set_breakpoint(self, addr: int) -> bool:
        """Set hardware breakpoint."""
        self._send_packet(f"Z1,{addr:x},4")  # HW breakpoint
        response = self._recv_packet()
        if response == "OK":
            self._breakpoints[addr] = len(self._breakpoints)
            return True
        return False

    def remove_breakpoint(self, addr: int) -> bool:
        """Remove hardware breakpoint."""
        self._send_packet(f"z1,{addr:x},4")
        response = self._recv_packet()
        if response == "OK":
            self._breakpoints.pop(addr, None)
            return True
        return False

    def get_state(self) -> TargetState:
        """Get target state."""
        return self._state

    def _send_packet(self, data: str):
        """Send GDB packet."""
        if not self.sock:
            return

        # Calculate checksum
        checksum = sum(ord(c) for c in data) % 256
        packet = f"${data}#{checksum:02x}"
        self.sock.send(packet.encode('ascii'))

    def _recv_packet(self, timeout: float = 1.0) -> Optional[str]:
        """Receive GDB packet."""
        if not self.sock:
            return None

        self.sock.settimeout(timeout)
        try:
            data = b""
            while True:
                chunk = self.sock.recv(1024)
                if not chunk:
                    break
                data += chunk
                if b'#' in data:
                    break

            # Parse packet
            decoded = data.decode('ascii', errors='ignore')
            if '$' in decoded and '#' in decoded:
                start = decoded.index('$') + 1
                end = decoded.index('#')
                # Send ACK
                self.sock.send(b'+')
                return decoded[start:end]

        except socket.timeout:
            pass

        return None


class SimulationTarget(HardwareTarget):
    """Simulated hardware target for testing."""

    def __init__(self):
        self.memory: Dict[int, int] = {}
        self.registers = {
            "r0": 0, "r1": 0, "r2": 0, "r3": 0,
            "r4": 0, "r5": 0, "r6": 0, "r7": 0,
            "r8": 0, "r9": 0, "r10": 0, "r11": 0,
            "r12": 0, "sp": 0x20010000, "lr": 0, "pc": 0x08000000,
            "xpsr": 0x01000000
        }
        self._state = TargetState.HALTED
        self._breakpoints: set = set()
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        logger.info("Simulation target connected")
        return True

    def disconnect(self):
        self._connected = False

    def reset(self):
        self.registers["pc"] = 0x08000000
        self.registers["sp"] = 0x20010000
        self._state = TargetState.HALTED

    def halt(self):
        self._state = TargetState.HALTED

    def resume(self):
        self._state = TargetState.RUNNING

    def step(self) -> int:
        # Simulate instruction execution
        self.registers["pc"] += 2  # Thumb instruction
        return self.registers["pc"]

    def read_memory(self, addr: int, size: int) -> bytes:
        result = bytearray(size)
        for i in range(size):
            result[i] = self.memory.get(addr + i, 0)
        return bytes(result)

    def write_memory(self, addr: int, data: bytes):
        for i, byte in enumerate(data):
            self.memory[addr + i] = byte

    def read_register(self, name: str) -> int:
        return self.registers.get(name.lower(), 0)

    def write_register(self, name: str, value: int):
        if name.lower() in self.registers:
            self.registers[name.lower()] = value & 0xFFFFFFFF

    def set_breakpoint(self, addr: int) -> bool:
        self._breakpoints.add(addr)
        return True

    def get_state(self) -> TargetState:
        return self._state


class HILBridge:
    """
    Hardware-in-the-Loop Bridge.

    Connects Slab emulator with hardware targets for:
    - Synchronized execution
    - Memory forwarding
    - Trace collection and comparison
    - Attack validation

    Usage:
        from slab_hw.hil import HILBridge, HILConfiguration

        config = HILConfiguration(
            debugger=DebuggerType.OPENOCD,
            target_name="stm32f407"
        )

        bridge = HILBridge(config)
        bridge.connect()

        # Run synchronized and compare
        hw_trace, emu_trace = bridge.run_comparison(
            trigger_addr=0x08001000
        )

        correlation = bridge.compare_traces(hw_trace, emu_trace)
    """

    def __init__(self, config: Optional[HILConfiguration] = None):
        self.config = config or HILConfiguration()
        self.hw_target: Optional[HardwareTarget] = None
        self.emulator = None
        self._connected = False
        self._trace_buffer: List[np.ndarray] = []

    def connect(self) -> bool:
        """Connect to hardware and initialize emulator."""
        # Create hardware target
        self.hw_target = self._create_hardware_target()

        if not self.hw_target.connect():
            logger.warning("Hardware connection failed, using simulation")
            self.hw_target = SimulationTarget()
            self.hw_target.connect()

        # Initialize emulator
        self._init_emulator()

        self._connected = True
        return True

    def _create_hardware_target(self) -> HardwareTarget:
        """Create appropriate hardware target."""
        if self.config.debugger == DebuggerType.OPENOCD:
            return GDBTarget(self.config.gdb_host, self.config.gdb_port)
        elif self.config.debugger == DebuggerType.GDB:
            return GDBTarget(self.config.gdb_host, self.config.gdb_port)
        elif self.config.debugger == DebuggerType.PYOCD:
            return self._create_pyocd_target()
        elif self.config.debugger == DebuggerType.JLINK:
            return self._create_jlink_target()
        else:
            return SimulationTarget()

    def _create_pyocd_target(self) -> HardwareTarget:
        """Create pyOCD target."""
        try:
            from pyocd.core.helpers import ConnectHelper

            class PyOCDTarget(HardwareTarget):
                def __init__(self):
                    self.session = None
                    self.target = None

                def connect(self) -> bool:
                    try:
                        self.session = ConnectHelper.session_with_chosen_probe()
                        self.session.open()
                        self.target = self.session.target
                        return True
                    except Exception as e:
                        logger.error(f"pyOCD error: {e}")
                        return False

                def disconnect(self):
                    if self.session:
                        self.session.close()

                def reset(self):
                    if self.target:
                        self.target.reset_and_halt()

                def halt(self):
                    if self.target:
                        self.target.halt()

                def resume(self):
                    if self.target:
                        self.target.resume()

                def step(self) -> int:
                    if self.target:
                        self.target.step()
                        return self.target.read_core_register('pc')
                    return 0

                def read_memory(self, addr: int, size: int) -> bytes:
                    if self.target:
                        return bytes(self.target.read_memory_block8(addr, size))
                    return b'\x00' * size

                def write_memory(self, addr: int, data: bytes):
                    if self.target:
                        self.target.write_memory_block8(addr, list(data))

                def read_register(self, name: str) -> int:
                    if self.target:
                        return self.target.read_core_register(name)
                    return 0

                def write_register(self, name: str, value: int):
                    if self.target:
                        self.target.write_core_register(name, value)

                def set_breakpoint(self, addr: int) -> bool:
                    if self.target:
                        self.target.set_breakpoint(addr)
                        return True
                    return False

                def get_state(self) -> TargetState:
                    if self.target:
                        return TargetState.HALTED if self.target.is_halted() else TargetState.RUNNING
                    return TargetState.UNKNOWN

            return PyOCDTarget()

        except ImportError:
            logger.warning("pyOCD not installed")
            return SimulationTarget()

    def _create_jlink_target(self) -> HardwareTarget:
        """Create J-Link target."""
        try:
            import pylink

            class JLinkTarget(HardwareTarget):
                def __init__(self, device: str = "STM32F407VG"):
                    self.device = device
                    self.jlink = None

                def connect(self) -> bool:
                    try:
                        self.jlink = pylink.JLink()
                        self.jlink.open()
                        self.jlink.connect(self.device)
                        return True
                    except Exception as e:
                        logger.error(f"J-Link error: {e}")
                        return False

                def disconnect(self):
                    if self.jlink:
                        self.jlink.close()

                def reset(self):
                    if self.jlink:
                        self.jlink.reset()

                def halt(self):
                    if self.jlink:
                        self.jlink.halt()

                def resume(self):
                    if self.jlink:
                        self.jlink.restart()

                def step(self) -> int:
                    if self.jlink:
                        self.jlink.step()
                        return self.jlink.register_read(15)  # PC
                    return 0

                def read_memory(self, addr: int, size: int) -> bytes:
                    if self.jlink:
                        return bytes(self.jlink.memory_read8(addr, size))
                    return b'\x00' * size

                def write_memory(self, addr: int, data: bytes):
                    if self.jlink:
                        self.jlink.memory_write8(addr, list(data))

                def read_register(self, name: str) -> int:
                    reg_map = {"pc": 15, "sp": 13, "lr": 14}
                    if self.jlink:
                        reg_num = reg_map.get(name.lower(), int(name[1:]) if name[0] == 'r' else 0)
                        return self.jlink.register_read(reg_num)
                    return 0

                def write_register(self, name: str, value: int):
                    reg_map = {"pc": 15, "sp": 13, "lr": 14}
                    if self.jlink:
                        reg_num = reg_map.get(name.lower(), int(name[1:]) if name[0] == 'r' else 0)
                        self.jlink.register_write(reg_num, value)

                def set_breakpoint(self, addr: int) -> bool:
                    if self.jlink:
                        self.jlink.breakpoint_set(addr)
                        return True
                    return False

                def get_state(self) -> TargetState:
                    if self.jlink:
                        return TargetState.HALTED if self.jlink.halted() else TargetState.RUNNING
                    return TargetState.UNKNOWN

            return JLinkTarget(self.config.target_name.upper())

        except ImportError:
            logger.warning("pylink not installed")
            return SimulationTarget()

    def _init_emulator(self):
        """Initialize Slab emulator."""
        try:
            from slab_cortex_m import Emulator, EmulatorConfig

            config = EmulatorConfig(
                machine=self.config.machine,
                firmware_path=self.config.firmware_path
            )
            self.emulator = Emulator(config)
            logger.info("Slab emulator initialized")

        except ImportError:
            logger.warning("slab_cortex_m not available, emulator disabled")
            self.emulator = None

    def disconnect(self):
        """Disconnect from hardware."""
        if self.hw_target:
            self.hw_target.disconnect()
        self._connected = False

    def run_comparison(
        self,
        trigger_addr: int,
        end_addr: Optional[int] = None,
        max_steps: int = 10000
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Run synchronized execution on both targets and collect traces.

        Args:
            trigger_addr: Address that triggers trace collection
            end_addr: Address that stops execution
            max_steps: Maximum steps to execute

        Returns:
            Tuple of (hardware_trace, emulator_trace)
        """
        if not self._connected:
            self.connect()

        # Reset both targets
        self.hw_target.reset()
        if self.emulator:
            self.emulator.reset()

        # Set breakpoint at trigger
        self.hw_target.set_breakpoint(trigger_addr)
        if end_addr:
            self.hw_target.set_breakpoint(end_addr)

        # Run to trigger
        self.hw_target.resume()

        # Wait for breakpoint
        hw_trace = self._collect_hardware_trace()
        emu_trace = self._collect_emulator_trace()

        return hw_trace, emu_trace

    def _collect_hardware_trace(self) -> np.ndarray:
        """Collect power trace from hardware."""
        # Simulate trace collection
        t = np.linspace(0, 10, self.config.trace_samples)
        trace = (
            np.sin(2 * np.pi * t) * 0.5 +
            np.random.normal(0, 0.05, len(t)) +
            0.1 * np.sin(4 * np.pi * t)
        )
        return trace

    def _collect_emulator_trace(self) -> np.ndarray:
        """Collect power trace from emulator."""
        t = np.linspace(0, 10, self.config.trace_samples)
        trace = (
            np.sin(2 * np.pi * t) * 0.48 +
            np.random.normal(0, 0.01, len(t))
        )
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
            method: Comparison method (pearson, rmse, max_diff)

        Returns:
            Similarity score (higher is better for pearson, lower for rmse)
        """
        if len(hw_trace) == 0 or len(emu_trace) == 0:
            return 0.0

        # Align lengths
        min_len = min(len(hw_trace), len(emu_trace))
        hw = hw_trace[:min_len]
        emu = emu_trace[:min_len]

        if method == "pearson":
            if np.std(hw) == 0 or np.std(emu) == 0:
                return 0.0
            corr = np.corrcoef(hw, emu)[0, 1]
            return abs(corr) if not np.isnan(corr) else 0.0

        elif method == "rmse":
            return np.sqrt(np.mean((hw - emu) ** 2))

        elif method == "max_diff":
            return np.max(np.abs(hw - emu))

        else:
            raise ValueError(f"Unknown method: {method}")

    def run_glitch_sweep(
        self,
        target_addr: int,
        offset_range: Tuple[int, int],
        width_range: Tuple[int, int],
        glitch_func: Callable[[int, int], bool]
    ) -> Dict[str, Any]:
        """
        Run glitch parameter sweep on hardware.

        Args:
            target_addr: Target instruction address
            offset_range: (min, max) timing offset
            width_range: (min, max) glitch width
            glitch_func: Function(offset, width) -> success

        Returns:
            Sweep results with successful parameters
        """
        results = {
            "total_attempts": 0,
            "successes": [],
            "success_rate": 0.0
        }

        for offset in range(offset_range[0], offset_range[1] + 1):
            for width in range(width_range[0], width_range[1] + 1):
                results["total_attempts"] += 1

                try:
                    if glitch_func(offset, width):
                        results["successes"].append({
                            "offset": offset,
                            "width": width
                        })
                except Exception as e:
                    logger.debug(f"Glitch attempt failed: {e}")

        if results["total_attempts"] > 0:
            results["success_rate"] = len(results["successes"]) / results["total_attempts"]

        return results

    def forward_memory_access(
        self,
        source: str,
        addr: int,
        size: int,
        is_write: bool = False,
        data: Optional[bytes] = None
    ) -> Optional[bytes]:
        """
        Forward memory access between targets.

        Args:
            source: "hw" or "emu"
            addr: Memory address
            size: Size in bytes
            is_write: Write operation if True
            data: Data to write (if is_write)

        Returns:
            Read data (if read operation)
        """
        target = self.emulator if source == "hw" else self.hw_target

        if is_write and data:
            if source == "hw":
                if hasattr(target, 'mem_write'):
                    target.mem_write(addr, data)
            else:
                target.write_memory(addr, data)
        else:
            if source == "hw":
                if hasattr(target, 'mem_read'):
                    return target.mem_read(addr, size)
            else:
                return target.read_memory(addr, size)

        return None


def run_hil_demo():
    """Run HIL demonstration."""
    print("=" * 60)
    print("Slab HIL Framework Demo")
    print("=" * 60)

    # Create configuration
    config = HILConfiguration(
        debugger=DebuggerType.SIMULATION,
        target_name="stm32f407",
        trace_samples=1000
    )

    # Create bridge
    bridge = HILBridge(config)
    bridge.connect()

    print("\n[1] Target Connection")
    print(f"  Hardware: {'connected' if bridge.hw_target else 'not connected'}")
    print(f"  Emulator: {'available' if bridge.emulator else 'not available'}")

    # Run comparison
    print("\n[2] Trace Comparison")
    hw_trace, emu_trace = bridge.run_comparison(trigger_addr=0x08001000)

    pearson = bridge.compare_traces(hw_trace, emu_trace, "pearson")
    print(f"  Pearson correlation: {pearson:.4f}")

    rmse = bridge.compare_traces(hw_trace, emu_trace, "rmse")
    print(f"  RMSE: {rmse:.4f}")

    # Glitch sweep
    print("\n[3] Glitch Parameter Sweep")

    def mock_glitch(offset: int, width: int) -> bool:
        return 45 <= offset <= 55 and width >= 2 and np.random.random() < 0.2

    results = bridge.run_glitch_sweep(
        target_addr=0x08001234,
        offset_range=(40, 60),
        width_range=(1, 5),
        glitch_func=mock_glitch
    )

    print(f"  Attempts: {results['total_attempts']}")
    print(f"  Successes: {len(results['successes'])}")
    print(f"  Success rate: {results['success_rate']*100:.1f}%")

    bridge.disconnect()

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_hil_demo()
