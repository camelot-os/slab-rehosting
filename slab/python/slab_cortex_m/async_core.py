#!/usr/bin/env python3
"""
MCUemu Async Core Infrastructure

This module provides the async/threading infrastructure for MCUemu:
- Concurrent client handling with proper locking
- ThreadPoolExecutor for blocking I/O operations
- Async peripheral base classes
- Event-driven peripheral communication

Architecture:
    - AsyncIO for network I/O and coordination
    - ThreadPoolExecutor for blocking operations (serial, OpenOCD)
    - AsyncLocks for shared peripheral state
    - Event queues for inter-peripheral communication

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Set
from collections import deque
from contextlib import asynccontextmanager

log = logging.getLogger('AsyncCore')


# =============================================================================
# THREAD POOL MANAGER
# =============================================================================

class ThreadPoolManager:
    """
    Manages thread pools for blocking I/O operations.

    Provides separate pools for different operation types:
    - io_pool: Serial, file, and other blocking I/O
    - compute_pool: CPU-bound computations (crypto, compression)
    """

    _instance: Optional['ThreadPoolManager'] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # I/O bound operations (serial, files)
        self.io_pool = ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="slab_io"
        )

        # CPU bound operations (crypto, checksums)
        self.compute_pool = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="slab_compute"
        )

        log.info("ThreadPoolManager initialized (io=8, compute=4 workers)")

    async def run_io(self, func: Callable, *args, **kwargs) -> Any:
        """Run blocking I/O function in thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.io_pool,
            lambda: func(*args, **kwargs)
        )

    async def run_compute(self, func: Callable, *args, **kwargs) -> Any:
        """Run CPU-bound function in thread pool."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.compute_pool,
            lambda: func(*args, **kwargs)
        )

    def shutdown(self):
        """Shutdown thread pools."""
        self.io_pool.shutdown(wait=True)
        self.compute_pool.shutdown(wait=True)
        log.info("ThreadPoolManager shutdown complete")


# Global thread pool manager
_thread_pool: Optional[ThreadPoolManager] = None

def get_thread_pool() -> ThreadPoolManager:
    """Get global thread pool manager."""
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = ThreadPoolManager()
    return _thread_pool


# =============================================================================
# ASYNC PERIPHERAL BASE
# =============================================================================

@dataclass
class PeripheralAccess:
    """Record of a peripheral access."""
    is_write: bool
    address: int
    size: int
    value: int
    secure: bool = False
    timestamp: float = 0.0


class AsyncPeripheral(ABC):
    """
    Base class for async-aware peripherals.

    Provides:
    - Async-safe register access with locks
    - Event notifications
    - Access logging
    """

    def __init__(self, name: str, base: int, size: int, irq: int = -1):
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq
        self.log = logging.getLogger(f'P.{name}')

        # Thread-safe register storage
        self._regs: Dict[int, int] = {}
        self._lock = asyncio.Lock()

        # Event notification
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._subscribers: Set[asyncio.Queue] = set()

        # Access logging
        self._access_log: deque = deque(maxlen=1000)
        self._log_enabled = False

        # IRQ callback
        self.irq_callback: Optional[Callable[[int, int], None]] = None

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    async def read(self, addr: int, size: int, secure: bool = False) -> tuple:
        """Thread-safe async read."""
        async with self._lock:
            offset = addr - self.base
            value = await self._read_reg(offset, size)

            if self._log_enabled:
                import time
                access = PeripheralAccess(
                    is_write=False, address=addr, size=size,
                    value=value, secure=secure, timestamp=time.time()
                )
                self._access_log.append(access)

            self.log.debug(f"Read{'[S]' if secure else ''} 0x{addr:08X} = 0x{value:08X}")
            return (value, 0)  # value, status

    async def write(self, addr: int, size: int, value: int, secure: bool = False) -> int:
        """Thread-safe async write."""
        async with self._lock:
            offset = addr - self.base
            await self._write_reg(offset, size, value)

            if self._log_enabled:
                import time
                access = PeripheralAccess(
                    is_write=True, address=addr, size=size,
                    value=value, secure=secure, timestamp=time.time()
                )
                self._access_log.append(access)

            self.log.debug(f"Write{'[S]' if secure else ''} 0x{addr:08X} <- 0x{value:08X}")
            return 0  # status OK

    async def _read_reg(self, offset: int, size: int) -> int:
        """Override for custom read behavior."""
        return self._regs.get(offset, 0)

    async def _write_reg(self, offset: int, size: int, value: int):
        """Override for custom write behavior."""
        self._regs[offset] = value

    def subscribe(self, queue: asyncio.Queue):
        """Subscribe to peripheral events."""
        self._subscribers.add(queue)

    def unsubscribe(self, queue: asyncio.Queue):
        """Unsubscribe from peripheral events."""
        self._subscribers.discard(queue)

    async def emit_event(self, event_type: str, data: Any = None):
        """Emit event to all subscribers."""
        event = {'type': event_type, 'peripheral': self.name, 'data': data}
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def trigger_irq(self, level: int = 1):
        """Trigger interrupt."""
        if self.irq >= 0 and self.irq_callback:
            self.irq_callback(self.irq, level)


# =============================================================================
# ASYNC SERVER WITH MULTI-CLIENT SUPPORT
# =============================================================================

class AsyncPeripheralServer:
    """
    Async peripheral server with concurrent client support.

    Features:
    - Multiple simultaneous clients
    - Per-peripheral locking
    - IRQ broadcast to all clients
    """

    # Protocol constants
    CMD_READ = ord('R')
    CMD_WRITE = ord('W')
    CMD_READ_S = ord('S')
    CMD_WRITE_S = ord('T')
    CMD_IRQ = ord('I')

    def __init__(self, port: int = 5000):
        self.port = port
        self.peripherals: List[AsyncPeripheral] = []
        self.clients: Set[asyncio.StreamWriter] = set()
        self._clients_lock = asyncio.Lock()
        self.running = False
        self.server = None
        self.log = logging.getLogger('AsyncServer')

    def add_peripheral(self, peripheral: AsyncPeripheral):
        """Add peripheral to server."""
        peripheral.irq_callback = self._broadcast_irq
        self.peripherals.append(peripheral)
        self.log.info(f"Added {peripheral.name} @ 0x{peripheral.base:08X}")

    def find_peripheral(self, addr: int) -> Optional[AsyncPeripheral]:
        """Find peripheral containing address."""
        for p in self.peripherals:
            if p.contains(addr):
                return p
        return None

    async def _broadcast_irq(self, irq_num: int, level: int):
        """Broadcast IRQ to all connected clients."""
        packet = struct.pack('<BIB', self.CMD_IRQ, irq_num, level)

        async with self._clients_lock:
            dead_clients = []
            for writer in self.clients:
                try:
                    writer.write(packet)
                    await writer.drain()
                except Exception:
                    dead_clients.append(writer)

            # Remove dead clients
            for writer in dead_clients:
                self.clients.discard(writer)

    async def handle_client(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter):
        """Handle a single client connection."""
        addr = writer.get_extra_info('peername')
        self.log.info(f"Client connected: {addr}")

        async with self._clients_lock:
            self.clients.add(writer)

        try:
            while self.running:
                cmd_data = await reader.read(1)
                if not cmd_data:
                    break

                cmd = cmd_data[0]

                if cmd in (self.CMD_READ, self.CMD_READ_S):
                    # Read: addr(4) + size(4) + secure(1)
                    data = await reader.readexactly(9)
                    address, size = struct.unpack('<II', data[:8])
                    secure = (cmd == self.CMD_READ_S) or (data[8] == 1)

                    periph = self.find_peripheral(address)
                    if periph:
                        value, status = await periph.read(address, size, secure)
                    else:
                        value, status = 0, 0

                    response = struct.pack('<IB', value, status)
                    writer.write(response)
                    await writer.drain()

                elif cmd in (self.CMD_WRITE, self.CMD_WRITE_S):
                    # Write: addr(4) + size(4) + value(4) + secure(1)
                    data = await reader.readexactly(13)
                    address, size, value = struct.unpack('<III', data[:12])
                    secure = (cmd == self.CMD_WRITE_S) or (data[12] == 1)

                    periph = self.find_peripheral(address)
                    if periph:
                        status = await periph.write(address, size, value, secure)
                    else:
                        status = 0

                    response = struct.pack('<IB', 0, status)
                    writer.write(response)
                    await writer.drain()

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            self.log.error(f"Client error: {e}")
        finally:
            async with self._clients_lock:
                self.clients.discard(writer)
            writer.close()
            await writer.wait_closed()
            self.log.info(f"Client disconnected: {addr}")

    async def start(self):
        """Start the server."""
        self.running = True
        self.server = await asyncio.start_server(
            self.handle_client,
            '127.0.0.1',
            self.port,
            reuse_address=True
        )
        self.log.info(f"Server started on port {self.port}")

        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        """Stop the server."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()


# =============================================================================
# ASYNC SERIAL WRAPPER
# =============================================================================

class AsyncSerial:
    """
    Async wrapper for serial port operations.

    Uses ThreadPoolExecutor for blocking serial I/O.
    """

    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None
        self._lock = asyncio.Lock()
        self._pool = get_thread_pool()

    async def connect(self) -> bool:
        """Connect to serial port."""
        try:
            import serial
            self._serial = await self._pool.run_io(
                lambda: serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout
                )
            )
            return True
        except Exception as e:
            log.error(f"Serial connect failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from serial port."""
        if self._serial:
            await self._pool.run_io(self._serial.close)
            self._serial = None

    async def write(self, data: bytes) -> int:
        """Write data to serial port."""
        async with self._lock:
            if not self._serial:
                return 0
            return await self._pool.run_io(self._serial.write, data)

    async def read(self, size: int) -> bytes:
        """Read data from serial port."""
        async with self._lock:
            if not self._serial:
                return b''
            return await self._pool.run_io(self._serial.read, size)

    async def readline(self) -> bytes:
        """Read line from serial port."""
        async with self._lock:
            if not self._serial:
                return b''
            return await self._pool.run_io(self._serial.readline)


# =============================================================================
# ASYNC EVENT BUS
# =============================================================================

@dataclass
class Event:
    """Event for inter-peripheral communication."""
    source: str
    event_type: str
    data: Any = None


class EventBus:
    """
    Async event bus for peripheral communication.

    Enables:
    - DMA completion notifications
    - IRQ cascade
    - Inter-peripheral triggers
    """

    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()
        self.log = logging.getLogger('EventBus')

    async def subscribe(self, event_type: str, queue: asyncio.Queue):
        """Subscribe to event type."""
        async with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(queue)

    async def unsubscribe(self, event_type: str, queue: asyncio.Queue):
        """Unsubscribe from event type."""
        async with self._lock:
            if event_type in self._subscribers:
                try:
                    self._subscribers[event_type].remove(queue)
                except ValueError:
                    pass

    async def publish(self, event: Event):
        """Publish event to subscribers."""
        async with self._lock:
            # Notify specific type subscribers
            if event.event_type in self._subscribers:
                for queue in self._subscribers[event.event_type]:
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        self.log.warning(f"Queue full for {event.event_type}")

            # Notify wildcard subscribers
            if '*' in self._subscribers:
                for queue in self._subscribers['*']:
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        pass


# Global event bus
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    """Get global event bus."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


# =============================================================================
# ASYNC DMA CONTROLLER
# =============================================================================

class AsyncDMAStream:
    """
    Async DMA stream with background transfer support.

    Executes transfers asynchronously without blocking peripheral accesses.
    """

    def __init__(self, dma_id: int, stream_id: int):
        self.dma_id = dma_id
        self.stream_id = stream_id
        self.log = logging.getLogger(f'DMA{dma_id}.S{stream_id}')

        # Registers
        self.cr = 0
        self.ndtr = 0
        self.par = 0
        self.m0ar = 0
        self.m1ar = 0
        self.fcr = 0x21

        # State
        self._transfer_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        # Memory access callbacks
        self.memory_read: Optional[Callable[[int, int], bytes]] = None
        self.memory_write: Optional[Callable[[int, bytes], None]] = None

        # Completion callback
        self.on_complete: Optional[Callable[[], None]] = None

    async def start_transfer(self):
        """Start async DMA transfer."""
        async with self._lock:
            if self._transfer_task and not self._transfer_task.done():
                return  # Already running

            self._transfer_task = asyncio.create_task(self._do_transfer())

    async def _do_transfer(self):
        """Execute DMA transfer asynchronously."""
        if self.ndtr == 0 or not self.memory_read or not self.memory_write:
            return

        direction = (self.cr >> 6) & 3
        psize = 1 << ((self.cr >> 11) & 3)
        msize = 1 << ((self.cr >> 13) & 3)
        pinc = bool(self.cr & (1 << 9))
        minc = bool(self.cr & (1 << 10))

        self.log.debug(f"Transfer start: ndtr={self.ndtr} dir={direction}")

        pool = get_thread_pool()

        # Execute transfer in chunks for responsiveness
        chunk_size = min(64, self.ndtr)
        remaining = self.ndtr

        src = self.par if direction == 0 else self.m0ar
        dst = self.m0ar if direction == 0 else self.par

        while remaining > 0:
            count = min(chunk_size, remaining)

            # Read source
            data = await pool.run_io(self.memory_read, src, count * psize)

            # Write destination
            await pool.run_io(self.memory_write, dst, data)

            # Update pointers
            if direction == 0:  # P2M
                if pinc:
                    src += count * psize
                if minc:
                    dst += count * msize
            else:  # M2P
                if minc:
                    src += count * msize
                if pinc:
                    dst += count * psize

            remaining -= count

            # Yield to other tasks
            await asyncio.sleep(0)

        # Transfer complete
        self.cr &= ~1  # Clear enable
        self.log.debug("Transfer complete")

        if self.on_complete:
            self.on_complete()

        # Publish event
        event_bus = get_event_bus()
        await event_bus.publish(Event(
            source=f"DMA{self.dma_id}_S{self.stream_id}",
            event_type='dma_complete',
            data={'stream': self.stream_id}
        ))


# =============================================================================
# UTILITIES
# =============================================================================

@asynccontextmanager
async def timeout_context(seconds: float):
    """Async context manager with timeout."""
    try:
        yield asyncio.timeout(seconds)
    except asyncio.TimeoutError:
        raise


async def gather_with_concurrency(n: int, *coros):
    """Run coroutines with limited concurrency."""
    semaphore = asyncio.Semaphore(n)

    async def limited_coro(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*[limited_coro(c) for c in coros])


# =============================================================================
# MAIN / DEMO
# =============================================================================

async def demo():
    """Demo async infrastructure."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)-12s: %(message)s'
    )

    print("=" * 60)
    print("MCUemu Async Core Demo")
    print("=" * 60)

    # Create server with async peripheral
    class DemoPeripheral(AsyncPeripheral):
        async def _write_reg(self, offset: int, size: int, value: int):
            self._regs[offset] = value
            if offset == 0x00 and value == 0x01:
                await self.emit_event('demo_trigger', {'offset': offset})

    server = AsyncPeripheralServer(port=5555)
    demo_periph = DemoPeripheral("DEMO", 0x40000000, 0x100)
    server.add_peripheral(demo_periph)

    # Subscribe to events
    event_queue = asyncio.Queue()
    demo_periph.subscribe(event_queue)

    async def event_monitor():
        while True:
            event = await event_queue.get()
            print(f"Event: {event}")

    # Start in background
    monitor_task = asyncio.create_task(event_monitor())

    # Test thread pool
    pool = get_thread_pool()
    result = await pool.run_compute(lambda: sum(range(1000000)))
    print(f"Compute result: {result}")

    # Simulate some operations
    await demo_periph.write(0x40000000, 4, 0x01)
    value, _ = await demo_periph.read(0x40000000, 4)
    print(f"Read back: 0x{value:08X}")

    # Wait for event
    await asyncio.sleep(0.1)
    monitor_task.cancel()

    # Cleanup
    pool.shutdown()

    print("\nDemo complete!")


if __name__ == '__main__':
    asyncio.run(demo())
