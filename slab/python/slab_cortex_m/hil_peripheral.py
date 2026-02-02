#!/usr/bin/env python3
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
Copyright (C) 2026 TwistedWires Security Lab
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
# HIL PERIPHERAL FACTORY
# =============================================================================

def create_hil_peripheral(config: dict) -> HILPeripheral:
    """
    Create HIL peripheral from configuration.

    Config format:
        {
            "name": "GPIOA_HIL",
            "base": "0x40020000",
            "size": "0x400",
            "backend": "serial",  # or "tcp", "openocd"
            "serial_port": "/dev/ttyUSB0",  # for serial
            "host": "localhost",  # for tcp/openocd
            "port": 5001,  # for tcp/openocd
            "baudrate": 115200  # for serial
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
