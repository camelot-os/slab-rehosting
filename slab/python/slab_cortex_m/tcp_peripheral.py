#!/usr/bin/env python3
"""
TCP Peripheral Bridge

TCP-based peripheral communication for remote/networked emulation.
More compatible than shared memory, works across machines.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import socket
import struct
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, List, Tuple
from enum import IntEnum
import select

from slab_peripherals.bus_logger import log_unhandled as _log_unhandled
from slab_peripherals.mpu import MemoryProtectionController


class TcpCommand(IntEnum):
    """TCP protocol command codes."""
    NOP = 0x00
    READ8 = 0x01
    READ16 = 0x02
    READ32 = 0x03
    WRITE8 = 0x04
    WRITE16 = 0x05
    WRITE32 = 0x06
    IRQ_STATUS = 0x07
    RESET = 0x08
    IDENTIFY = 0x09
    # 64-bit bus extensions (protocol v2)
    READ64 = 0x0A
    WRITE64 = 0x0B
    # Extended access with bus attributes
    READ_EXT = 0x0C
    WRITE_EXT = 0x0D
    # Responses
    ACK = 0x80
    NACK = 0x81
    IRQ_NOTIFY = 0x82
    ACCESS_DENIED = 0x83  # Privilege/security violation


class TcpFlags(IntEnum):
    """TCP packet flag bits."""
    NONE = 0x00
    BUS_64BIT = 0x01      # 64-bit bus width
    NS_BIT = 0x02         # Non-secure access
    PRIVILEGED = 0x04     # Privileged access
    HYPERVISOR = 0x08     # Hypervisor/EL2 access
    HAS_BUS_ATTRS = 0x10  # Extended bus attributes in payload


@dataclass
class BusAttributes:
    """
    Bus transaction attributes for privilege/security context.

    Tracks the CPU/core originating the access, security state,
    privilege level, and bus width for all slab machines.
    """
    core_id: int = 0
    ns: bool = False
    privilege: int = 0         # 0=Unprivileged, 1=Privileged
    exception_level: int = 0   # EL0-EL3
    bus_width: int = 32        # 32 or 64

    def to_flags(self) -> int:
        """Convert to TcpFlags byte."""
        flags = 0
        if self.bus_width == 64:
            flags |= TcpFlags.BUS_64BIT
        if self.ns:
            flags |= TcpFlags.NS_BIT
        if self.privilege >= 1:
            flags |= TcpFlags.PRIVILEGED
        if self.privilege >= 2 or self.exception_level >= 2:
            flags |= TcpFlags.HYPERVISOR
        return flags

    @classmethod
    def from_flags(cls, flags: int, core_id: int = 0) -> 'BusAttributes':
        """Construct from TcpFlags byte."""
        return cls(
            core_id=core_id,
            ns=bool(flags & TcpFlags.NS_BIT),
            privilege=2 if (flags & TcpFlags.HYPERVISOR) else
                      1 if (flags & TcpFlags.PRIVILEGED) else 0,
            exception_level=2 if (flags & TcpFlags.HYPERVISOR) else 0,
            bus_width=64 if (flags & TcpFlags.BUS_64BIT) else 32,
        )

    def pack_extended(self) -> bytes:
        """Pack full bus attributes into 4 bytes for extended payload."""
        word = (
            (self.core_id & 0xFF) |
            ((1 if self.ns else 0) << 8) |
            ((self.privilege & 0x03) << 9) |
            ((self.exception_level & 0x03) << 11) |
            ((1 if self.bus_width == 64 else 0) << 13)
        )
        return struct.pack('<I', word)

    @classmethod
    def unpack_extended(cls, data: bytes) -> 'BusAttributes':
        """Unpack full bus attributes from 4 bytes."""
        word = struct.unpack('<I', data[:4])[0]
        return cls(
            core_id=word & 0xFF,
            ns=bool((word >> 8) & 1),
            privilege=(word >> 9) & 0x03,
            exception_level=(word >> 11) & 0x03,
            bus_width=64 if ((word >> 13) & 1) else 32,
        )


@dataclass
class TcpPacket:
    """
    TCP protocol packet format.

    v1 Format (32-bit, backward compatible):
    [0:1]  - Command (TcpCommand)
    [1:2]  - Flags (TcpFlags)
    [2:4]  - Length
    [4:8]  - Address (32-bit)
    [8:12] - Data (32-bit)
    [12:N] - Extended data (if length > 12)

    v2 Format (64-bit, when BUS_64BIT flag set):
    [0:1]  - Command (TcpCommand)
    [1:2]  - Flags (TcpFlags, includes BUS_64BIT)
    [2:4]  - Length
    [4:12] - Address (64-bit)
    [12:20]- Data (64-bit)
    [20:24]- Bus attributes (core_id, NS, privilege, EL)
    [24:N] - Extended data
    """

    HEADER_SIZE_V1 = 12
    HEADER_SIZE_V2 = 24
    HEADER_SIZE = 12  # Backward compatibility alias (v1 size)

    command: TcpCommand = TcpCommand.NOP
    flags: int = 0
    address: int = 0
    data: int = 0
    extended: bytes = b""
    bus_attrs: Optional[BusAttributes] = None

    def pack(self) -> bytes:
        """Pack packet into bytes."""
        if self.flags & TcpFlags.BUS_64BIT:
            # v2: 64-bit format
            attrs_bytes = self.bus_attrs.pack_extended() if self.bus_attrs else b'\x00' * 4
            length = self.HEADER_SIZE_V2 + len(self.extended)
            header = struct.pack(
                '<BBHQQ',
                self.command,
                self.flags,
                length,
                self.address,
                self.data,
            ) + attrs_bytes
            return header + self.extended
        else:
            # v1: 32-bit format (backward compatible)
            length = self.HEADER_SIZE_V1 + len(self.extended)
            header = struct.pack(
                '<BBHII',
                self.command,
                self.flags,
                length,
                self.address & 0xFFFFFFFF,
                self.data & 0xFFFFFFFF,
            )
            return header + self.extended

    @classmethod
    def unpack(cls, data: bytes) -> 'TcpPacket':
        """Unpack packet from bytes."""
        if len(data) < cls.HEADER_SIZE_V1:
            raise ValueError("Packet too short")

        command, flags, length = struct.unpack('<BBH', data[:4])

        if flags & TcpFlags.BUS_64BIT and len(data) >= cls.HEADER_SIZE_V2:
            # v2: 64-bit format
            address, value = struct.unpack('<QQ', data[4:20])
            bus_attrs = BusAttributes.unpack_extended(data[20:24]) if len(data) >= 24 else BusAttributes()
            extended = data[cls.HEADER_SIZE_V2:length] if length > cls.HEADER_SIZE_V2 else b""
            return cls(
                command=TcpCommand(command),
                flags=flags,
                address=address,
                data=value,
                extended=extended,
                bus_attrs=bus_attrs,
            )
        else:
            # v1: 32-bit format
            address, value = struct.unpack('<II', data[4:12])
            bus_attrs = BusAttributes.from_flags(flags)
            extended = data[cls.HEADER_SIZE_V1:length] if length > cls.HEADER_SIZE_V1 else b""
            return cls(
                command=TcpCommand(command),
                flags=flags,
                address=address,
                data=value,
                extended=extended,
                bus_attrs=bus_attrs,
            )


@dataclass
class TcpPeripheralHandler:
    """Handler for a single peripheral with bus attribute support."""

    name: str = "generic"
    base_address: int = 0
    size: int = 0x1000

    # Register storage
    registers: Dict[int, int] = field(default_factory=dict)

    # Callbacks (legacy 32-bit)
    read_callback: Optional[Callable[[int, int], int]] = None
    write_callback: Optional[Callable[[int, int, int], None]] = None

    # Extended callbacks with bus attributes
    read_callback_ext: Optional[Callable[[int, int, 'BusAttributes'], int]] = None
    write_callback_ext: Optional[Callable[[int, int, int, 'BusAttributes'], None]] = None

    def read(self, address: int, size: int,
             bus_attrs: Optional[BusAttributes] = None) -> int:
        """Read from peripheral with optional bus attributes."""
        offset = address - self.base_address

        if self.read_callback_ext and bus_attrs:
            return self.read_callback_ext(offset, size, bus_attrs)
        elif self.read_callback:
            return self.read_callback(offset, size)

        return self.registers.get(offset, 0)

    def write(self, address: int, value: int, size: int,
              bus_attrs: Optional[BusAttributes] = None):
        """Write to peripheral with optional bus attributes."""
        offset = address - self.base_address

        if self.write_callback_ext and bus_attrs:
            self.write_callback_ext(offset, value, size, bus_attrs)
        elif self.write_callback:
            self.write_callback(offset, value, size)
        else:
            self.registers[offset] = value

    def check_access(self, bus_attrs: Optional[BusAttributes] = None) -> bool:
        """
        Check if access is permitted given bus attributes.
        Override for TrustZone/privilege enforcement.
        """
        return True

    def reset(self):
        """Reset peripheral to default state."""
        self.registers.clear()


@dataclass
class TcpPeripheralBridge:
    """
    TCP-based peripheral bridge.

    Provides remote peripheral emulation over TCP.
    """

    host: str = "127.0.0.1"
    port: int = 5555

    # Peripheral map
    peripheral_map: Dict[int, TcpPeripheralHandler] = field(default_factory=dict)

    # IRQ state
    irq_status: int = 0

    # Memory protection controller (MPU/MMU/DART override mode)
    protection: Optional[MemoryProtectionController] = None

    # Internal state
    _socket: Optional[socket.socket] = None
    _client: Optional[socket.socket] = None
    _running: bool = False
    _thread: Optional[threading.Thread] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # Statistics
    packets_rx: int = 0
    packets_tx: int = 0
    reads: int = 0
    writes: int = 0

    def start_server(self):
        """Start TCP server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen(1)
        self._socket.setblocking(False)

        self._running = True
        self._thread = threading.Thread(target=self._server_loop, daemon=True)
        self._thread.start()

        print(f"TCP peripheral server listening on {self.host}:{self.port}")

    def stop_server(self):
        """Stop TCP server."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._client:
            self._client.close()
        if self._socket:
            self._socket.close()

    def register_peripheral(self, base_addr: int, handler: TcpPeripheralHandler):
        """Register a peripheral handler."""
        self.peripheral_map[base_addr] = handler

    def _server_loop(self):
        """Main server loop."""
        while self._running:
            # Accept new connections
            if self._client is None:
                try:
                    readable, _, _ = select.select([self._socket], [], [], 0.1)
                    if readable:
                        self._client, addr = self._socket.accept()
                        self._client.setblocking(False)
                        print(f"Client connected from {addr}")
                except Exception:
                    pass
                continue

            # Handle client commands
            try:
                readable, _, _ = select.select([self._client], [], [], 0.1)
                if readable:
                    data = self._client.recv(1024)
                    if not data:
                        # Client disconnected
                        print("Client disconnected")
                        self._client.close()
                        self._client = None
                        continue

                    self._handle_data(data)
            except (ConnectionResetError, BrokenPipeError):
                self._client.close()
                self._client = None
            except Exception:
                pass

    def _handle_data(self, data: bytes):
        """Handle received data."""
        try:
            packet = TcpPacket.unpack(data)
            self.packets_rx += 1

            response = self._process_packet(packet)

            if response and self._client:
                self._client.send(response.pack())
                self.packets_tx += 1

        except Exception as e:
            print(f"Error handling packet: {e}")

    def _process_packet(self, packet: TcpPacket) -> Optional[TcpPacket]:
        """Process a command packet with bus attribute support."""
        handler = self._find_handler(packet.address)
        bus_attrs = packet.bus_attrs

        response = TcpPacket(
            command=TcpCommand.ACK,
            flags=packet.flags & TcpFlags.BUS_64BIT,  # Preserve bus width in response
            address=packet.address,
            bus_attrs=bus_attrs,
        )

        # Protection controller override check (MPU/MMU/DART)
        if self.protection and self.protection.override_enabled:
            is_write = packet.command in (
                TcpCommand.WRITE8, TcpCommand.WRITE16,
                TcpCommand.WRITE32, TcpCommand.WRITE64, TcpCommand.WRITE_EXT
            )
            is_priv = bus_attrs.privilege >= 1 if bus_attrs else True
            ns = bus_attrs.ns if bus_attrs else False
            core = bus_attrs.core_id if bus_attrs else 0
            size = {TcpCommand.READ8: 1, TcpCommand.READ16: 2,
                    TcpCommand.READ32: 4, TcpCommand.READ64: 8,
                    TcpCommand.WRITE8: 1, TcpCommand.WRITE16: 2,
                    TcpCommand.WRITE32: 4, TcpCommand.WRITE64: 8}.get(packet.command, 4)
            if not self.protection.check_access(
                packet.address, size=size, is_write=is_write,
                is_privileged=is_priv, ns=ns, core_id=core
            ):
                response.command = TcpCommand.ACCESS_DENIED
                return response

        # Check per-handler access permissions
        if handler and bus_attrs and not handler.check_access(bus_attrs):
            response.command = TcpCommand.ACCESS_DENIED
            return response

        if packet.command == TcpCommand.READ8:
            self.reads += 1
            if handler:
                response.data = handler.read(packet.address, 1, bus_attrs) & 0xFF
            else:
                _log_unhandled("TCP", "READ", packet.address, size=1)
                response.data = 0xFF
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.READ16:
            self.reads += 1
            if handler:
                response.data = handler.read(packet.address, 2, bus_attrs) & 0xFFFF
            else:
                _log_unhandled("TCP", "READ", packet.address, size=2)
                response.data = 0xFFFF
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.READ32:
            self.reads += 1
            if handler:
                response.data = handler.read(packet.address, 4, bus_attrs) & 0xFFFFFFFF
            else:
                _log_unhandled("TCP", "READ", packet.address, size=4)
                response.data = 0xFFFFFFFF
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.READ64:
            self.reads += 1
            if handler:
                response.data = handler.read(packet.address, 8, bus_attrs) & 0xFFFFFFFFFFFFFFFF
                response.flags |= TcpFlags.BUS_64BIT
            else:
                _log_unhandled("TCP", "READ", packet.address, size=8)
                response.data = 0xFFFFFFFFFFFFFFFF
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.WRITE8:
            self.writes += 1
            if handler:
                handler.write(packet.address, packet.data & 0xFF, 1, bus_attrs)
            else:
                _log_unhandled("TCP", "WRITE", packet.address, value=packet.data & 0xFF, size=1)
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.WRITE16:
            self.writes += 1
            if handler:
                handler.write(packet.address, packet.data & 0xFFFF, 2, bus_attrs)
            else:
                _log_unhandled("TCP", "WRITE", packet.address, value=packet.data & 0xFFFF, size=2)
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.WRITE32:
            self.writes += 1
            if handler:
                handler.write(packet.address, packet.data & 0xFFFFFFFF, 4, bus_attrs)
            else:
                _log_unhandled("TCP", "WRITE", packet.address, value=packet.data & 0xFFFFFFFF, size=4)
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.WRITE64:
            self.writes += 1
            if handler:
                handler.write(packet.address, packet.data & 0xFFFFFFFFFFFFFFFF, 8, bus_attrs)
            else:
                _log_unhandled("TCP", "WRITE", packet.address, value=packet.data & 0xFFFFFFFFFFFFFFFF, size=8)
                response.command = TcpCommand.NACK

        elif packet.command == TcpCommand.IRQ_STATUS:
            response.data = self.irq_status

        elif packet.command == TcpCommand.RESET:
            for h in self.peripheral_map.values():
                h.reset()
            self.irq_status = 0

        elif packet.command == TcpCommand.IDENTIFY:
            response.extended = self._get_peripheral_info()

        else:
            response.command = TcpCommand.NACK

        return response

    def _find_handler(self, address: int) -> Optional[TcpPeripheralHandler]:
        """Find peripheral handler for address."""
        for base, handler in self.peripheral_map.items():
            if base <= address < base + handler.size:
                return handler
        return None

    def _get_peripheral_info(self) -> bytes:
        """Get peripheral information as bytes."""
        info = []
        for base, handler in self.peripheral_map.items():
            info.append(f"{handler.name}@{base:#010x}:{handler.size:#x}")
        return ",".join(info).encode()

    def set_irq(self, irq_num: int):
        """Set IRQ line and notify client."""
        with self._lock:
            self.irq_status |= (1 << irq_num)

            if self._client:
                packet = TcpPacket(
                    command=TcpCommand.IRQ_NOTIFY,
                    data=self.irq_status
                )
                try:
                    self._client.send(packet.pack())
                except Exception:
                    pass

    def clear_irq(self, irq_num: int):
        """Clear IRQ line."""
        with self._lock:
            self.irq_status &= ~(1 << irq_num)


@dataclass
class TcpPeripheralServer:
    """
    High-level TCP peripheral server.

    Usage:
        server = TcpPeripheralServer(port=5555)
        server.add_peripheral(GPIOPeripheral(base=0x40020000))
        server.start()
    """

    host: str = "127.0.0.1"
    port: int = 5555
    bridge: Optional[TcpPeripheralBridge] = None

    def __post_init__(self):
        self.bridge = TcpPeripheralBridge(host=self.host, port=self.port)

    def add_peripheral(self, peripheral: TcpPeripheralHandler):
        """Add a peripheral to the server."""
        self.bridge.register_peripheral(peripheral.base_address, peripheral)

    def start(self):
        """Start the server."""
        self.bridge.start_server()

    def stop(self):
        """Stop the server."""
        self.bridge.stop_server()

    def get_stats(self) -> Dict[str, int]:
        """Get server statistics."""
        return {
            "packets_rx": self.bridge.packets_rx,
            "packets_tx": self.bridge.packets_tx,
            "reads": self.bridge.reads,
            "writes": self.bridge.writes,
        }
