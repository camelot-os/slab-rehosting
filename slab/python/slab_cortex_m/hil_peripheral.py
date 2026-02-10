#!/usr/bin/env python3
from __future__ import annotations
"""
Hardware-in-the-Loop (HIL) Peripheral for MCUemu

This module provides peripheral handlers that forward accesses to real hardware,
enabling hardware-in-the-loop testing similar to avatar2's approach.

Supported backends:
- Serial (UART/USB-Serial): Forward to real MCU via debug interface
- OpenOCD: Forward via JTAG/SWD debugger
- TCP: Forward to remote hardware server

Features:
- Async I/O with ThreadPoolExecutor for blocking operations
- Connection pooling and automatic reconnection
- Access caching for read-only registers
- Transaction logging for debugging

Usage:
    from hil_peripheral import HILSerialPeripheral, HILOpenOCDPeripheral

    # Forward GPIO accesses to real STM32 via serial
    gpio = HILSerialPeripheral(
        name="GPIOA_HIL",
        base=0x40020000,
        size=0x400,
        serial_port="/dev/ttyUSB0",
        baudrate=115200
    )

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
import socket
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Callable, Any, List
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger('HIL')

# Thread pool for blocking I/O operations
_io_executor: Optional[ThreadPoolExecutor] = None

def get_io_executor() -> ThreadPoolExecutor:
    """Get or create I/O thread pool executor."""
    global _io_executor
    if _io_executor is None:
        _io_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hil_io")
    return _io_executor


# =============================================================================
# HIL PROTOCOL
# =============================================================================

@dataclass
class HILRequest:
    """Hardware access request."""
    is_write: bool
    address: int
    size: int
    value: int = 0
    secure: bool = False


@dataclass
class HILResponse:
    """Hardware access response."""
    value: int
    success: bool
    error_msg: str = ""


# =============================================================================
# BASE HIL PERIPHERAL
# =============================================================================

@dataclass
class HILStats:
    """Statistics for HIL peripheral operations."""
    reads: int = 0
    writes: int = 0
    errors: int = 0
    cache_hits: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        total = self.reads + self.writes
        return self.total_latency_ms / total if total > 0 else 0.0


class HILPeripheral(ABC):
    """
    Base class for Hardware-in-the-Loop peripherals.

    Forwards QEMU peripheral accesses to real hardware via configurable backend.
    This enables testing firmware against real peripherals while running in QEMU.

    Features:
    - Thread-safe async operations
    - Access caching for read-only registers
    - Automatic reconnection on failure
    - Statistics collection
    """

    def __init__(self, name: str, base: int, size: int, irq: int = -1):
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq
        self.log = logging.getLogger(f'HIL.{name}')
        self.irq_callback: Optional[Callable[[int, int], None]] = None
        self.connected = False

        # Thread-safe lock
        self._lock = asyncio.Lock()

        # Cache for read-only registers (optional optimization)
        self.cache_enabled = False
        self.cache: Dict[int, int] = {}

        # Statistics
        self.stats = HILStats()

        # Auto-reconnect settings
        self.auto_reconnect = True
        self.reconnect_delay = 1.0

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    def check_security(self, secure: bool) -> bool:
        return True  # HIL peripherals handle security at hardware level

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to hardware backend."""
        pass

    @abstractmethod
    async def disconnect(self):
        """Disconnect from hardware backend."""
        pass

    @abstractmethod
    async def forward_read(self, addr: int, size: int) -> HILResponse:
        """Forward read request to hardware."""
        pass

    @abstractmethod
    async def forward_write(self, addr: int, size: int, value: int) -> HILResponse:
        """Forward write request to hardware."""
        pass

    async def read(self, addr: int, size: int, secure: bool = False) -> int:
        """Handle read from QEMU with locking and caching."""
        offset = addr - self.base

        # Check cache first (no lock needed for read)
        if self.cache_enabled and offset in self.cache:
            self.stats.cache_hits += 1
            return self.cache[offset]

        async with self._lock:
            # Auto-reconnect if needed
            if not self.connected and self.auto_reconnect:
                await self._try_reconnect()

            start_time = time.perf_counter()

            # Forward to hardware
            response = await self.forward_read(addr, size)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.stats.total_latency_ms += elapsed_ms
            self.stats.reads += 1

            if response.success:
                self.log.debug(f"Read[{'S' if secure else 'NS'}] 0x{addr:08X} = 0x{response.value:08X} ({elapsed_ms:.2f}ms)")
                return response.value
            else:
                self.stats.errors += 1
                self.log.error(f"Read failed: {response.error_msg}")
                return 0xDEADBEEF

    async def write(self, addr: int, size: int, value: int, secure: bool = False) -> bool:
        """Handle write from QEMU with locking."""
        offset = addr - self.base

        async with self._lock:
            # Auto-reconnect if needed
            if not self.connected and self.auto_reconnect:
                await self._try_reconnect()

            start_time = time.perf_counter()

            # Forward to hardware
            response = await self.forward_write(addr, size, value)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.stats.total_latency_ms += elapsed_ms
            self.stats.writes += 1

            if response.success:
                self.log.debug(f"Write[{'S' if secure else 'NS'}] 0x{addr:08X} <- 0x{value:08X} ({elapsed_ms:.2f}ms)")
                # Invalidate cache for this address
                if self.cache_enabled and offset in self.cache:
                    del self.cache[offset]
                return True
            else:
                self.stats.errors += 1
                self.log.error(f"Write failed: {response.error_msg}")
                return False

    async def _try_reconnect(self):
        """Try to reconnect to hardware."""
        self.log.info("Attempting reconnect...")
        try:
            await self.connect()
        except Exception as e:
            self.log.warning(f"Reconnect failed: {e}")
            await asyncio.sleep(self.reconnect_delay)

    def set_irq_callback(self, callback: Callable[[int, int], None]):
        """Set callback for IRQ injection."""
        self.irq_callback = callback

    def trigger_irq(self, level: int = 1):
        """Trigger interrupt from hardware to QEMU."""
        if self.irq >= 0 and self.irq_callback:
            self.irq_callback(self.irq, level)


# =============================================================================
# SERIAL HIL PERIPHERAL
# =============================================================================

class HILSerialPeripheral(HILPeripheral):
    """
    Forward peripheral accesses to real hardware via serial port.

    Protocol (binary, little-endian):
        Request:  [CMD:1][ADDR:4][SIZE:4][VALUE:4 if write]
        Response: [VALUE:4][STATUS:1]

    Where:
        CMD: 'R' for read, 'W' for write
        STATUS: 0 = OK, 1 = Error

    This protocol matches MCUemu's TCP protocol for consistency.

    Example target firmware (STM32):
        // Simple serial bridge that executes memory accesses
        void handle_serial_command() {
            uint8_t cmd = uart_read_byte();
            uint32_t addr = uart_read_u32();
            uint32_t size = uart_read_u32();

            if (cmd == 'R') {
                uint32_t value = *(volatile uint32_t*)addr;
                uart_write_u32(value);
                uart_write_byte(0);  // OK
            } else if (cmd == 'W') {
                uint32_t value = uart_read_u32();
                *(volatile uint32_t*)addr = value;
                uart_write_u32(value);
                uart_write_byte(0);  // OK
            }
        }
    """

    def __init__(self, name: str, base: int, size: int,
                 serial_port: str, baudrate: int = 115200,
                 timeout: float = 1.0, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.serial_port = serial_port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None

    async def connect(self) -> bool:
        """Connect to serial port (uses thread pool for blocking I/O)."""
        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _connect():
            import serial
            return serial.Serial(
                port=self.serial_port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )

        try:
            self.serial = await loop.run_in_executor(executor, _connect)
            self.connected = True
            self.log.info(f"Connected to {self.serial_port} @ {self.baudrate}")
            return True
        except Exception as e:
            self.log.error(f"Failed to connect: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from serial port."""
        if self.serial:
            loop = asyncio.get_running_loop()
            executor = get_io_executor()
            await loop.run_in_executor(executor, self.serial.close)
            self.serial = None
        self.connected = False

    async def forward_read(self, addr: int, size: int) -> HILResponse:
        """Forward read to serial target (uses thread pool)."""
        if not self.serial:
            return HILResponse(0, False, "Not connected")

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _do_read():
            # Send read request
            request = struct.pack('<cII', b'R', addr, size)
            self.serial.write(request)

            # Read response
            response = self.serial.read(5)  # value(4) + status(1)
            return response

        try:
            response = await loop.run_in_executor(executor, _do_read)

            if len(response) < 5:
                self.connected = False
                return HILResponse(0, False, "Timeout waiting for response")

            value, status = struct.unpack('<IB', response)
            if status == 0:
                return HILResponse(value, True)
            else:
                return HILResponse(0, False, f"Hardware error: status={status}")

        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))

    async def forward_write(self, addr: int, size: int, value: int) -> HILResponse:
        """Forward write to serial target (uses thread pool)."""
        if not self.serial:
            return HILResponse(0, False, "Not connected")

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _do_write():
            # Send write request
            request = struct.pack('<cIII', b'W', addr, size, value)
            self.serial.write(request)

            # Read response
            response = self.serial.read(5)  # value(4) + status(1)
            return response

        try:
            response = await loop.run_in_executor(executor, _do_write)

            if len(response) < 5:
                self.connected = False
                return HILResponse(0, False, "Timeout waiting for response")

            resp_value, status = struct.unpack('<IB', response)
            if status == 0:
                return HILResponse(resp_value, True)
            else:
                return HILResponse(0, False, f"Hardware error: status={status}")

        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))


# =============================================================================
# TCP HIL PERIPHERAL (Remote Hardware)
# =============================================================================

class HILTCPPeripheral(HILPeripheral):
    """
    Forward peripheral accesses to remote hardware via TCP.

    This allows connecting to a remote hardware server that provides
    access to real peripherals, enabling distributed HIL testing.

    Protocol matches MCUemu's binary protocol.
    """

    def __init__(self, name: str, base: int, size: int,
                 host: str = "localhost", port: int = 5001,
                 timeout: float = 5.0, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> bool:
        """Connect to remote hardware server."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout
            )
            self.connected = True
            self.log.info(f"Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            self.log.error(f"Failed to connect: {e}")
            return False

    async def disconnect(self):
        """Disconnect from remote server."""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
        self.reader = None
        self.writer = None
        self.connected = False

    async def forward_read(self, addr: int, size: int) -> HILResponse:
        """Forward read to remote server."""
        if not self.writer or not self.reader:
            return HILResponse(0, False, "Not connected")

        try:
            # Send read request (MCUemu protocol)
            request = struct.pack('<cIIB', b'R', addr, size, 0)  # 0 = non-secure
            self.writer.write(request)
            await self.writer.drain()

            # Read response
            response = await asyncio.wait_for(
                self.reader.read(5),
                timeout=self.timeout
            )
            if len(response) < 5:
                return HILResponse(0, False, "Invalid response")

            value, status = struct.unpack('<IB', response)
            if status == 0:
                return HILResponse(value, True)
            else:
                return HILResponse(0, False, f"Remote error: status={status}")

        except asyncio.TimeoutError:
            return HILResponse(0, False, "Timeout")
        except Exception as e:
            return HILResponse(0, False, str(e))

    async def forward_write(self, addr: int, size: int, value: int) -> HILResponse:
        """Forward write to remote server."""
        if not self.writer or not self.reader:
            return HILResponse(0, False, "Not connected")

        try:
            # Send write request (MCUemu protocol)
            request = struct.pack('<cIIIB', b'W', addr, size, value, 0)  # 0 = non-secure
            self.writer.write(request)
            await self.writer.drain()

            # Read response
            response = await asyncio.wait_for(
                self.reader.read(5),
                timeout=self.timeout
            )
            if len(response) < 5:
                return HILResponse(0, False, "Invalid response")

            resp_value, status = struct.unpack('<IB', response)
            if status == 0:
                return HILResponse(resp_value, True)
            else:
                return HILResponse(0, False, f"Remote error: status={status}")

        except asyncio.TimeoutError:
            return HILResponse(0, False, "Timeout")
        except Exception as e:
            return HILResponse(0, False, str(e))


# =============================================================================
# OPENOCD HIL PERIPHERAL (JTAG/SWD)
# =============================================================================

class HILOpenOCDPeripheral(HILPeripheral):
    """
    Forward peripheral accesses to real hardware via OpenOCD.

    Connects to OpenOCD's TCL interface to perform memory reads/writes
    on the target MCU via JTAG or SWD debugger.

    Requirements:
        - OpenOCD running with TCL server enabled (default port 6666)
        - Target MCU connected and halted (or running with background access)

    Example OpenOCD startup:
        openocd -f interface/stlink.cfg -f target/stm32f4x.cfg
    """

    def __init__(self, name: str, base: int, size: int,
                 host: str = "localhost", port: int = 6666,
                 timeout: float = 5.0, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.host = host
        self.port = port
        self.timeout = timeout
        self.socket: Optional[socket.socket] = None

    async def connect(self) -> bool:
        """Connect to OpenOCD TCL server (uses thread pool)."""
        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _connect():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            return sock

        try:
            self.socket = await loop.run_in_executor(executor, _connect)
            self.connected = True
            self.log.info(f"Connected to OpenOCD at {self.host}:{self.port}")
            return True
        except Exception as e:
            self.log.error(f"Failed to connect to OpenOCD: {e}")
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from OpenOCD."""
        if self.socket:
            loop = asyncio.get_running_loop()
            executor = get_io_executor()
            await loop.run_in_executor(executor, self.socket.close)
            self.socket = None
        self.connected = False

    def _send_tcl_command_sync(self, cmd: str) -> str:
        """Send TCL command to OpenOCD and return response (blocking)."""
        if not self.socket:
            raise RuntimeError("Not connected")

        # OpenOCD TCL protocol: command + 0x1a terminator
        self.socket.send((cmd + '\x1a').encode())

        # Read response until 0x1a terminator
        response = b''
        while True:
            data = self.socket.recv(4096)
            if not data:
                break
            response += data
            if b'\x1a' in data:
                break

        return response.decode().strip('\x1a').strip()

    async def _send_tcl_command(self, cmd: str) -> str:
        """Send TCL command to OpenOCD asynchronously."""
        loop = asyncio.get_running_loop()
        executor = get_io_executor()
        return await loop.run_in_executor(
            executor,
            self._send_tcl_command_sync,
            cmd
        )

    async def forward_read(self, addr: int, size: int) -> HILResponse:
        """Read memory via OpenOCD (async)."""
        if not self.socket:
            return HILResponse(0, False, "Not connected")

        try:
            # Use mdw (memory display word) for 32-bit reads
            if size == 4:
                cmd = f"mdw 0x{addr:08x}"
            elif size == 2:
                cmd = f"mdh 0x{addr:08x}"
            elif size == 1:
                cmd = f"mdb 0x{addr:08x}"
            else:
                cmd = f"mdw 0x{addr:08x}"

            response = await self._send_tcl_command(cmd)

            # Parse response: "0x40020000: aabbccdd"
            if ':' in response:
                value_str = response.split(':')[1].strip().split()[0]
                value = int(value_str, 16)
                return HILResponse(value, True)
            else:
                return HILResponse(0, False, f"Unexpected response: {response}")

        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))

    async def forward_write(self, addr: int, size: int, value: int) -> HILResponse:
        """Write memory via OpenOCD (async)."""
        if not self.socket:
            return HILResponse(0, False, "Not connected")

        try:
            # Use mww (memory write word) for 32-bit writes
            if size == 4:
                cmd = f"mww 0x{addr:08x} 0x{value:08x}"
            elif size == 2:
                cmd = f"mwh 0x{addr:08x} 0x{value:04x}"
            elif size == 1:
                cmd = f"mwb 0x{addr:08x} 0x{value:02x}"
            else:
                cmd = f"mww 0x{addr:08x} 0x{value:08x}"

            response = await self._send_tcl_command(cmd)

            # Write commands return empty on success
            if response == '' or 'error' not in response.lower():
                return HILResponse(value, True)
            else:
                return HILResponse(0, False, f"OpenOCD error: {response}")

        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))


# =============================================================================
# PYOCD HIL PERIPHERAL (JTAG/SWD via pyOCD)
# =============================================================================

class HILPyOCDPeripheral(HILPeripheral):
    """
    Forward peripheral accesses to real hardware via pyOCD.

    Uses pyOCD's Python API directly for memory reads/writes over
    CMSIS-DAP, ST-Link, or J-Link debug probes.

    Requirements:
        - pip install pyocd
        - Debug probe connected (ST-Link, CMSIS-DAP, J-Link)
        - Target MCU connected and powered

    Example:
        hil = HILPyOCDPeripheral(
            name="CRYP_HIL",
            base=0x50060000,
            size=0x400,
            target_type="stm32f439xi"
        )

    PyOCD target types:
        - stm32f405rg, stm32f407vg, stm32f439xi
        - nrf52840, rp2040
        - Run 'pyocd list --targets' for full list
    """

    def __init__(self, name: str, base: int, size: int,
                 target_type: str = "stm32f439xi",
                 probe_id: Optional[str] = None,
                 connect_mode: str = "halt",
                 frequency: int = 4_000_000,
                 irq: int = -1):
        super().__init__(name, base, size, irq)
        self.target_type = target_type
        self.probe_id = probe_id
        self.connect_mode = connect_mode
        self.frequency = frequency
        self.session = None
        self.target = None

    async def connect(self) -> bool:
        """Connect to target via pyOCD (uses thread pool)."""
        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _connect():
            from pyocd.core.helpers import ConnectHelper

            kwargs = {
                'target_override': self.target_type,
                'connect_mode': self.connect_mode,
                'frequency': self.frequency,
            }
            if self.probe_id:
                kwargs['unique_id'] = self.probe_id

            session = ConnectHelper.session_with_chosen_probe(**kwargs)
            session.open()
            return session

        try:
            self.session = await loop.run_in_executor(executor, _connect)
            self.target = self.session.target
            self.connected = True
            self.log.info(
                "Connected to %s via pyOCD (probe=%s)",
                self.target_type,
                self.session.probe.unique_id if self.session.probe else "auto"
            )
            return True
        except ImportError:
            self.log.error("pyocd not installed: pip install pyocd")
            self.connected = False
            return False
        except Exception as e:
            self.log.error("Failed to connect via pyOCD: %s", e)
            self.connected = False
            return False

    async def disconnect(self):
        """Disconnect from target."""
        if self.session:
            loop = asyncio.get_running_loop()
            executor = get_io_executor()
            await loop.run_in_executor(executor, self.session.close)
            self.session = None
            self.target = None
        self.connected = False

    async def forward_read(self, addr: int, size: int) -> HILResponse:
        """Read memory via pyOCD (async via thread pool)."""
        if not self.target:
            return HILResponse(0, False, "Not connected")

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _do_read():
            if size == 4:
                return self.target.read32(addr)
            elif size == 2:
                return self.target.read16(addr)
            elif size == 1:
                return self.target.read8(addr)
            else:
                return self.target.read32(addr)

        try:
            value = await loop.run_in_executor(executor, _do_read)
            return HILResponse(value, True)
        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))

    async def forward_write(self, addr: int, size: int,
                            value: int) -> HILResponse:
        """Write memory via pyOCD (async via thread pool)."""
        if not self.target:
            return HILResponse(0, False, "Not connected")

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _do_write():
            if size == 4:
                self.target.write32(addr, value)
            elif size == 2:
                self.target.write16(addr, value)
            elif size == 1:
                self.target.write8(addr, value)
            else:
                self.target.write32(addr, value)

        try:
            await loop.run_in_executor(executor, _do_write)
            return HILResponse(value, True)
        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))


# =============================================================================
# HIL PERIPHERAL FACTORY
# =============================================================================

# Registry of shared pyOCD sessions (keyed by probe_id or target_type)
_pyocd_sessions: Dict[str, Any] = {}  # str -> HILPyOCDSession


def get_shared_pyocd_session(config: dict) -> HILPyOCDSession:
    """Get or create a shared pyOCD session for session-sharing mode."""
    target_type = config.get('target_type', 'cortex_m')
    probe_id = config.get('probe_id')
    key = probe_id or target_type

    if key not in _pyocd_sessions:
        _pyocd_sessions[key] = HILPyOCDSession(
            target_type=target_type,
            probe_id=probe_id,
            connect_mode=config.get('connect_mode', 'halt'),
            frequency=config.get('frequency', 4_000_000),
        )

    return _pyocd_sessions[key]


def create_hil_peripheral(config: dict) -> HILPeripheral:
    """
    Create HIL peripheral from configuration.

    Config format:
        {
            "name": "GPIOA_HIL",
            "base": "0x40020000",
            "size": "0x400",
            "backend": "pyocd",   # or "serial", "tcp", "openocd", "replay"
            "target_type": "stm32f439xi",  # for pyocd
            "serial_port": "/dev/ttyUSB0",  # for serial
            "host": "localhost",  # for tcp/openocd
            "port": 5001,  # for tcp/openocd
            "baudrate": 115200,  # for serial
            "trace_file": "trace.jsonl",  # for replay
            "shared_session": true,  # for pyocd: share session across regions
        }
    """
    name = config.get('name', 'HIL')
    base = int(config.get('base', '0x40000000'), 0)
    size = int(config.get('size', '0x400'), 0)
    backend = config.get('backend', 'tcp')
    irq = config.get('irq', -1)

    if backend == 'serial':
        return HILSerialPeripheral(
            name=name,
            base=base,
            size=size,
            serial_port=config.get('serial_port', '/dev/ttyUSB0'),
            baudrate=config.get('baudrate', 115200),
            irq=irq
        )
    elif backend == 'openocd':
        return HILOpenOCDPeripheral(
            name=name,
            base=base,
            size=size,
            host=config.get('host', 'localhost'),
            port=config.get('port', 6666),
            irq=irq
        )
    elif backend == 'pyocd':
        if config.get('shared_session', False):
            session = get_shared_pyocd_session(config)
            return session.create_region(name, base, size, irq)
        return HILPyOCDPeripheral(
            name=name,
            base=base,
            size=size,
            target_type=config.get('target_type', 'cortex_m'),
            probe_id=config.get('probe_id'),
            connect_mode=config.get('connect_mode', 'halt'),
            frequency=config.get('frequency', 4_000_000),
            irq=irq
        )
    elif backend == 'replay':
        trace_file = config.get('trace_file', '')
        if trace_file:
            return HILReplayPeripheral.from_trace(trace_file, name, base, size)
        return HILReplayPeripheral(name, base, size, [])
    else:  # tcp
        return HILTCPPeripheral(
            name=name,
            base=base,
            size=size,
            host=config.get('host', 'localhost'),
            port=config.get('port', 5001),
            irq=irq
        )


# =============================================================================
# HIL TRACE RECORDING / REPLAY
# =============================================================================

@dataclass
class HILTraceRecord:
    """A single recorded HIL access."""
    sequence: int
    timestamp: float           # Seconds since recorder start
    is_write: bool
    address: int
    size: int
    value: int                 # Write value or read result
    latency_ms: float = 0.0
    success: bool = True
    peripheral_name: str = ""

    def to_dict(self) -> dict:
        return {
            'seq': self.sequence,
            'ts': round(self.timestamp, 6),
            'rw': 'W' if self.is_write else 'R',
            'addr': f"0x{self.address:08X}",
            'size': self.size,
            'value': f"0x{self.value:08X}",
            'latency_ms': round(self.latency_ms, 3),
            'ok': self.success,
            'periph': self.peripheral_name,
        }

    @staticmethod
    def from_dict(d: dict) -> 'HILTraceRecord':
        return HILTraceRecord(
            sequence=d.get('seq', 0),
            timestamp=d.get('ts', 0.0),
            is_write=(d.get('rw', 'R') == 'W'),
            address=int(d.get('addr', '0'), 0),
            size=d.get('size', 4),
            value=int(d.get('value', '0'), 0),
            latency_ms=d.get('latency_ms', 0.0),
            success=d.get('ok', True),
            peripheral_name=d.get('periph', ''),
        )


class HILTraceRecorder:
    """
    Decorator that wraps a HILPeripheral to record all accesses.

    Usage:
        hil = HILPyOCDPeripheral(name="CRYP", base=0x50060000, size=0x400)
        recorder = HILTraceRecorder(hil)
        # Use recorder.peripheral for board integration (drop-in replacement)
        # After test: recorder.save("trace.jsonl")
        # Later: replay = HILReplayPeripheral.from_trace("trace.jsonl")

    The recorder intercepts read() and write() calls on the inner peripheral,
    recording each access with timestamps and latencies.
    """

    def __init__(self, peripheral: HILPeripheral):
        self.inner = peripheral
        self.records: List[HILTraceRecord] = []
        self._seq = 0
        self._start_time = time.perf_counter()

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def base(self) -> int:
        return self.inner.base

    @property
    def size(self) -> int:
        return self.inner.size

    def contains(self, addr: int) -> bool:
        return self.inner.contains(addr)

    async def read(self, addr: int, size: int, secure: bool = False) -> int:
        """Record a read access."""
        t0 = time.perf_counter()
        value = await self.inner.read(addr, size, secure)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self._seq += 1
        self.records.append(HILTraceRecord(
            sequence=self._seq,
            timestamp=t0 - self._start_time,
            is_write=False,
            address=addr,
            size=size,
            value=value if isinstance(value, int) else 0,
            latency_ms=elapsed_ms,
            success=True,
            peripheral_name=self.inner.name,
        ))
        return value

    async def write(self, addr: int, size: int, value: int,
                    secure: bool = False) -> bool:
        """Record a write access."""
        t0 = time.perf_counter()
        result = await self.inner.write(addr, size, value, secure)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        self._seq += 1
        self.records.append(HILTraceRecord(
            sequence=self._seq,
            timestamp=t0 - self._start_time,
            is_write=True,
            address=addr,
            size=size,
            value=value,
            latency_ms=elapsed_ms,
            success=result if isinstance(result, bool) else True,
            peripheral_name=self.inner.name,
        ))
        return result

    def save(self, path: str):
        """Save recorded trace to JSON Lines file."""
        import json
        with open(path, 'w') as f:
            for rec in self.records:
                f.write(json.dumps(rec.to_dict()) + '\n')
        log.info("Saved %d HIL trace records to %s", len(self.records), path)

    @staticmethod
    def load(path: str) -> List[HILTraceRecord]:
        """Load trace records from JSON Lines file."""
        import json
        records = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(HILTraceRecord.from_dict(json.loads(line)))
        return records

    def reset(self):
        """Clear all recorded traces."""
        self.records.clear()
        self._seq = 0
        self._start_time = time.perf_counter()


class HILReplayPeripheral(HILPeripheral):
    """
    Replay HIL traces without real hardware.

    Loads a previously recorded trace and replays read values in sequence.
    Writes are accepted but discarded. This enables:
    - Offline testing without hardware
    - Deterministic regression testing
    - Sharing HIL traces between developers

    Usage:
        replay = HILReplayPeripheral.from_trace("trace.jsonl")
        # Use replay as a drop-in replacement for the original HIL peripheral
    """

    def __init__(self, name: str, base: int, size: int,
                 records: List[HILTraceRecord]):
        super().__init__(name, base, size)
        self.records = records
        self._read_index = 0
        # Build address->value map from last seen values for random access
        self._value_map: Dict[int, int] = {}
        for rec in records:
            self._value_map[rec.address] = rec.value

    @classmethod
    def from_trace(cls, path: str, name: str = "REPLAY",
                   base: int = 0, size: int = 0) -> 'HILReplayPeripheral':
        """Create replay peripheral from trace file."""
        records = HILTraceRecorder.load(path)
        if not records:
            return cls(name, base, size, [])

        # Auto-detect base/size from records if not specified
        if base == 0 and size == 0:
            addrs = [r.address for r in records]
            base = min(addrs) & ~0x3FF  # Align to 1KB boundary
            size = max(addrs) - base + 4
            name = records[0].peripheral_name or name

        return cls(name, base, size, records)

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def disconnect(self):
        self.connected = False

    async def forward_read(self, addr: int, size: int) -> HILResponse:
        """Replay recorded read values in order, with address-based fallback."""
        # Try sequential replay first (matches original access pattern)
        while self._read_index < len(self.records):
            rec = self.records[self._read_index]
            if not rec.is_write and rec.address == addr:
                self._read_index += 1
                return HILResponse(rec.value, rec.success)
            self._read_index += 1

        # Fallback: return last known value for this address
        if addr in self._value_map:
            return HILResponse(self._value_map[addr], True)

        return HILResponse(0, True)

    async def forward_write(self, addr: int, size: int,
                            value: int) -> HILResponse:
        """Accept writes (update value map for subsequent reads)."""
        self._value_map[addr] = value
        return HILResponse(value, True)

    def rewind(self):
        """Rewind replay to the beginning."""
        self._read_index = 0


# =============================================================================
# MULTI-REGION PYOCD SESSION SHARING
# =============================================================================

class HILPyOCDSession:
    """
    Shared pyOCD debug session for multiple HIL MMIO regions.

    Instead of opening one pyOCD session per peripheral, this class
    manages a single session that multiple HILPyOCDRegion instances
    share. This is important because most debug probes only support
    one concurrent connection.

    Usage:
        session = HILPyOCDSession(target_type="stm32f439xi")
        cryp = session.create_region("CRYP", 0x50060000, 0x400)
        hash_ = session.create_region("HASH", 0x50060400, 0x400)
        gpio = session.create_region("GPIOA", 0x40020000, 0x400)
        # All three share the same SWD connection
    """

    def __init__(self, target_type: str = "cortex_m",
                 probe_id: Optional[str] = None,
                 connect_mode: str = "halt",
                 frequency: int = 4_000_000):
        self.target_type = target_type
        self.probe_id = probe_id
        self.connect_mode = connect_mode
        self.frequency = frequency
        self.session = None
        self.target = None
        self.connected = False
        self.regions: List['HILPyOCDRegion'] = []
        self.log = logging.getLogger(f'HIL.PyOCD.Session')

    def create_region(self, name: str, base: int, size: int,
                      irq: int = -1) -> 'HILPyOCDRegion':
        """Create a new MMIO region backed by this shared session."""
        region = HILPyOCDRegion(name, base, size, self, irq)
        self.regions.append(region)
        return region

    async def connect(self) -> bool:
        """Open pyOCD session (shared by all regions)."""
        if self.connected:
            return True

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _connect():
            from pyocd.core.helpers import ConnectHelper
            kwargs = {
                'target_override': self.target_type,
                'connect_mode': self.connect_mode,
                'frequency': self.frequency,
            }
            if self.probe_id:
                kwargs['unique_id'] = self.probe_id
            session = ConnectHelper.session_with_chosen_probe(**kwargs)
            session.open()
            return session

        try:
            self.session = await loop.run_in_executor(executor, _connect)
            self.target = self.session.target
            self.connected = True
            self.log.info(
                "Shared session connected to %s (probe=%s, %d regions)",
                self.target_type,
                self.session.probe.unique_id if self.session.probe else "auto",
                len(self.regions))
            return True
        except ImportError:
            self.log.error("pyocd not installed: pip install pyocd")
            return False
        except Exception as e:
            self.log.error("Failed to connect: %s", e)
            return False

    async def disconnect(self):
        """Close shared session."""
        if self.session:
            loop = asyncio.get_running_loop()
            executor = get_io_executor()
            await loop.run_in_executor(executor, self.session.close)
            self.session = None
            self.target = None
        self.connected = False

    async def read(self, addr: int, size: int) -> HILResponse:
        """Read memory through the shared session."""
        if not self.target:
            return HILResponse(0, False, "Not connected")

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _do_read():
            if size == 4:
                return self.target.read32(addr)
            elif size == 2:
                return self.target.read16(addr)
            elif size == 1:
                return self.target.read8(addr)
            return self.target.read32(addr)

        try:
            value = await loop.run_in_executor(executor, _do_read)
            return HILResponse(value, True)
        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))

    async def write(self, addr: int, size: int,
                    value: int) -> HILResponse:
        """Write memory through the shared session."""
        if not self.target:
            return HILResponse(0, False, "Not connected")

        loop = asyncio.get_running_loop()
        executor = get_io_executor()

        def _do_write():
            if size == 4:
                self.target.write32(addr, value)
            elif size == 2:
                self.target.write16(addr, value)
            elif size == 1:
                self.target.write8(addr, value)
            else:
                self.target.write32(addr, value)

        try:
            await loop.run_in_executor(executor, _do_write)
            return HILResponse(value, True)
        except Exception as e:
            self.connected = False
            return HILResponse(0, False, str(e))


class HILPyOCDRegion(HILPeripheral):
    """
    A single MMIO region backed by a shared HILPyOCDSession.

    Multiple HILPyOCDRegion instances can share one debug probe connection.
    Each region covers a specific address range (e.g. CRYP at 0x50060000).
    """

    def __init__(self, name: str, base: int, size: int,
                 session: HILPyOCDSession, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.shared_session = session

    async def connect(self) -> bool:
        result = await self.shared_session.connect()
        self.connected = result
        return result

    async def disconnect(self):
        # Don't close the shared session -- other regions may still use it
        self.connected = False

    async def forward_read(self, addr: int, size: int) -> HILResponse:
        return await self.shared_session.read(addr, size)

    async def forward_write(self, addr: int, size: int,
                            value: int) -> HILResponse:
        return await self.shared_session.write(addr, size, value)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

async def main():
    """Example: Forward GPIO accesses to real hardware."""
    import argparse

    parser = argparse.ArgumentParser(description='HIL Peripheral Test')
    parser.add_argument('--backend', choices=['serial', 'tcp', 'openocd'],
                       default='tcp', help='HIL backend')
    parser.add_argument('--port', type=str, default='/dev/ttyUSB0',
                       help='Serial port (for serial backend)')
    parser.add_argument('--host', default='localhost',
                       help='Host (for tcp/openocd backend)')
    parser.add_argument('--tcp-port', type=int, default=5001,
                       help='TCP port (for tcp backend)')
    parser.add_argument('--openocd-port', type=int, default=6666,
                       help='OpenOCD TCL port')
    args = parser.parse_args()

    # Create HIL peripheral for STM32F4 GPIOA
    if args.backend == 'serial':
        hil = HILSerialPeripheral(
            name="GPIOA_HIL",
            base=0x40020000,
            size=0x400,
            serial_port=args.port
        )
    elif args.backend == 'openocd':
        hil = HILOpenOCDPeripheral(
            name="GPIOA_HIL",
            base=0x40020000,
            size=0x400,
            host=args.host,
            port=args.openocd_port
        )
    else:
        hil = HILTCPPeripheral(
            name="GPIOA_HIL",
            base=0x40020000,
            size=0x400,
            host=args.host,
            port=args.tcp_port
        )

    print(f"Testing HIL peripheral with {args.backend} backend...")

    if await hil.connect():
        # Test read
        value = await hil.read(0x40020000, 4)  # GPIOA->MODER
        print(f"GPIOA->MODER = 0x{value:08X}")

        # Test write
        await hil.write(0x40020014, 4, 0x00FF)  # GPIOA->ODR
        print("Wrote 0x00FF to GPIOA->ODR")

        # Read back
        value = await hil.read(0x40020014, 4)
        print(f"GPIOA->ODR = 0x{value:08X}")

        await hil.disconnect()
    else:
        print("Failed to connect!")


if __name__ == '__main__':
    asyncio.run(main())
