"""
SLAB SocketCAN Backend - CAN Bus Interface

Connects emulated CAN peripherals to Linux SocketCAN interface.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import socket
import struct
import threading
import logging
from dataclasses import dataclass
from typing import Optional, Callable, List
from enum import IntFlag


# CAN frame format constants
CAN_MTU = 16
CANFD_MTU = 72
CAN_MAX_DLEN = 8
CANFD_MAX_DLEN = 64


class CANFlags(IntFlag):
    """CAN ID flags."""
    EFF = 0x80000000  # Extended frame format
    RTR = 0x40000000  # Remote transmission request
    ERR = 0x20000000  # Error frame

    # Mask for actual ID
    SFF_MASK = 0x000007FF  # Standard frame (11 bits)
    EFF_MASK = 0x1FFFFFFF  # Extended frame (29 bits)


@dataclass
class CANFrame:
    """CAN frame structure."""
    can_id: int = 0
    data: bytes = b''

    @property
    def is_extended(self) -> bool:
        return bool(self.can_id & CANFlags.EFF)

    @property
    def is_rtr(self) -> bool:
        return bool(self.can_id & CANFlags.RTR)

    @property
    def is_error(self) -> bool:
        return bool(self.can_id & CANFlags.ERR)

    @property
    def id(self) -> int:
        """Get actual CAN ID without flags."""
        if self.is_extended:
            return self.can_id & CANFlags.EFF_MASK
        return self.can_id & CANFlags.SFF_MASK

    def to_bytes(self) -> bytes:
        """Convert to SocketCAN frame format."""
        dlc = len(self.data)
        # can_id (4) + dlc (1) + padding (3) + data (8)
        frame = struct.pack('=IBB2x', self.can_id, dlc, 0)
        frame += self.data.ljust(CAN_MAX_DLEN, b'\x00')
        return frame

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CANFrame':
        """Parse from SocketCAN frame format."""
        can_id, dlc = struct.unpack('=IB', data[:5])
        frame_data = data[8:8 + dlc]
        return cls(can_id=can_id, data=frame_data)


@dataclass
class CANFDFrame:
    """CAN FD frame structure."""
    can_id: int = 0
    flags: int = 0  # CANFD_BRS, CANFD_ESI
    data: bytes = b''

    CANFD_BRS = 0x01  # Bit rate switch
    CANFD_ESI = 0x02  # Error state indicator

    def to_bytes(self) -> bytes:
        """Convert to SocketCAN FD frame format."""
        dlc = len(self.data)
        # can_id (4) + len (1) + flags (1) + reserved (2) + data (64)
        frame = struct.pack('=IBBH', self.can_id, dlc, self.flags, 0)
        frame += self.data.ljust(CANFD_MAX_DLEN, b'\x00')
        return frame

    @classmethod
    def from_bytes(cls, data: bytes) -> 'CANFDFrame':
        """Parse from SocketCAN FD frame format."""
        can_id, dlc, flags = struct.unpack('=IBB', data[:6])
        frame_data = data[8:8 + dlc]
        return cls(can_id=can_id, flags=flags, data=frame_data)


class SocketCANInterface:
    """
    SocketCAN interface for connecting to Linux CAN interfaces.

    Usage:
        can = SocketCANInterface("vcan0")
        can.on_receive = my_callback
        can.start()
        can.send(CANFrame(can_id=0x123, data=b'\\x01\\x02\\x03'))
        can.stop()
    """

    def __init__(self, interface: str = "vcan0"):
        self.interface = interface
        self.log = logging.getLogger(f"CAN.{interface}")

        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._fd_mode = False

        # Callbacks
        self.on_receive: Optional[Callable[[CANFrame], None]] = None
        self.on_error: Optional[Callable[[Exception], None]] = None

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, fd_mode: bool = False):
        """
        Start the CAN interface.

        Args:
            fd_mode: Enable CAN FD mode
        """
        self._fd_mode = fd_mode

        try:
            # Create raw CAN socket
            self._socket = socket.socket(
                socket.AF_CAN,
                socket.SOCK_RAW,
                socket.CAN_RAW
            )

            # Enable CAN FD if requested
            if fd_mode:
                self._socket.setsockopt(
                    socket.SOL_CAN_RAW,
                    socket.CAN_RAW_FD_FRAMES,
                    1
                )

            # Bind to interface
            self._socket.bind((self.interface,))
            self._running = True

            # Start receive thread
            self._thread = threading.Thread(target=self._receive_loop, daemon=True)
            self._thread.start()

            self.log.info(f"CAN interface {self.interface} started")

        except Exception as e:
            self.log.error(f"Failed to start CAN interface: {e}")
            raise

    def stop(self):
        """Stop the CAN interface."""
        self._running = False
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=1.0)
        self.log.info(f"CAN interface {self.interface} stopped")

    def send(self, frame: CANFrame):
        """Send a CAN frame."""
        if not self._running or not self._socket:
            raise RuntimeError("CAN interface not running")

        try:
            self._socket.send(frame.to_bytes())
        except Exception as e:
            self.log.error(f"Send error: {e}")
            if self.on_error:
                self.on_error(e)

    def send_fd(self, frame: CANFDFrame):
        """Send a CAN FD frame."""
        if not self._fd_mode:
            raise RuntimeError("CAN FD mode not enabled")
        if not self._running or not self._socket:
            raise RuntimeError("CAN interface not running")

        try:
            self._socket.send(frame.to_bytes())
        except Exception as e:
            self.log.error(f"Send error: {e}")
            if self.on_error:
                self.on_error(e)

    def _receive_loop(self):
        """Receive loop for incoming CAN frames."""
        while self._running:
            try:
                self._socket.settimeout(0.5)
                if self._fd_mode:
                    data = self._socket.recv(CANFD_MTU)
                    if len(data) >= 8:
                        frame = CANFDFrame.from_bytes(data)
                        if self.on_receive:
                            self.on_receive(frame)
                else:
                    data = self._socket.recv(CAN_MTU)
                    if len(data) >= 8:
                        frame = CANFrame.from_bytes(data)
                        if self.on_receive:
                            self.on_receive(frame)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.log.error(f"Receive error: {e}")
                    if self.on_error:
                        self.on_error(e)


class CANBus:
    """
    Virtual CAN bus for connecting multiple nodes.

    Useful for testing without actual CAN hardware.
    """

    def __init__(self):
        self.log = logging.getLogger("CAN.Bus")
        self._nodes: List[Callable[[CANFrame], None]] = []
        self._lock = threading.Lock()

    def connect(self, callback: Callable[[CANFrame], None]):
        """Connect a node to the bus."""
        with self._lock:
            self._nodes.append(callback)

    def disconnect(self, callback: Callable[[CANFrame], None]):
        """Disconnect a node from the bus."""
        with self._lock:
            if callback in self._nodes:
                self._nodes.remove(callback)

    def send(self, sender: Callable, frame: CANFrame):
        """Send frame to all nodes except sender."""
        with self._lock:
            for node in self._nodes:
                if node != sender:
                    try:
                        node(frame)
                    except Exception as e:
                        self.log.error(f"Node callback error: {e}")


class CANNode:
    """
    CAN bus node for emulated peripherals.

    Can connect to either SocketCAN interface or virtual bus.
    """

    def __init__(self, node_id: int = 0):
        self.node_id = node_id
        self.log = logging.getLogger(f"CAN.Node.{node_id}")

        self._interface: Optional[SocketCANInterface] = None
        self._bus: Optional[CANBus] = None
        self._tx_queue: List[CANFrame] = []
        self._rx_queue: List[CANFrame] = []

        # Filters
        self.rx_filters: List[tuple] = []  # [(id, mask), ...]

        # Callbacks
        self.on_receive: Optional[Callable[[CANFrame], None]] = None

    def connect_socketcan(self, interface: str):
        """Connect to SocketCAN interface."""
        self._interface = SocketCANInterface(interface)
        self._interface.on_receive = self._handle_rx
        self._interface.start()

    def connect_bus(self, bus: CANBus):
        """Connect to virtual CAN bus."""
        self._bus = bus
        bus.connect(self._handle_rx)

    def disconnect(self):
        """Disconnect from interface/bus."""
        if self._interface:
            self._interface.stop()
            self._interface = None
        if self._bus:
            self._bus.disconnect(self._handle_rx)
            self._bus = None

    def send(self, can_id: int, data: bytes, extended: bool = False, rtr: bool = False):
        """Send a CAN frame."""
        frame_id = can_id
        if extended:
            frame_id |= CANFlags.EFF
        if rtr:
            frame_id |= CANFlags.RTR

        frame = CANFrame(can_id=frame_id, data=data[:8])

        if self._interface:
            self._interface.send(frame)
        elif self._bus:
            self._bus.send(self._handle_rx, frame)
        else:
            # Queue for later
            self._tx_queue.append(frame)

    def receive(self) -> Optional[CANFrame]:
        """Receive next frame from queue."""
        if self._rx_queue:
            return self._rx_queue.pop(0)
        return None

    def _handle_rx(self, frame: CANFrame):
        """Handle received frame."""
        # Apply filters
        if self.rx_filters:
            matched = False
            for filter_id, mask in self.rx_filters:
                if (frame.id & mask) == (filter_id & mask):
                    matched = True
                    break
            if not matched:
                return

        self._rx_queue.append(frame)

        if self.on_receive:
            self.on_receive(frame)

    def add_filter(self, can_id: int, mask: int = 0x7FF):
        """Add receive filter."""
        self.rx_filters.append((can_id, mask))

    def clear_filters(self):
        """Clear all receive filters."""
        self.rx_filters.clear()
