"""
CAN Bus Peripheral Emulation

Provides CAN (Controller Area Network) peripheral emulation compatible with:
- STM32 bxCAN (Basic Extended CAN)
- STM32 FDCAN (Flexible Data-rate CAN)
- NXP FlexCAN
- Linux SocketCAN bridge for real hardware

Features:
- Full CAN 2.0A/B support (11/29-bit identifiers)
- CAN FD support (flexible data-rate)
- Hardware filtering
- TX/RX mailboxes
- Error handling
- SocketCAN bridge for real CAN bus access

Usage:
    from slab_cortex_m.can_peripheral import CANController, SocketCANBridge

    # Create CAN controller
    can = CANController(base_address=0x40006400)  # CAN1 on STM32

    # Bridge to real CAN interface
    bridge = SocketCANBridge("vcan0")
    can.connect_bridge(bridge)

    # Firmware uses CAN normally
    can.write_reg(CANController.TI0R, 0x123 << 21)  # Set ID
    can.write_reg(CANController.TD0LR, 0xDEADBEEF)  # Set data
    can.write_reg(CANController.TI0R, 0x123 << 21 | 1)  # Request TX

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 Twisted Wires Security Lab
"""

import struct
import time
import threading
import queue
import logging
from typing import Optional, Dict, List, Callable, Tuple, Any
from dataclasses import dataclass, field
from enum import IntEnum, auto
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# =============================================================================
# CAN Message Definitions
# =============================================================================

@dataclass
class CANMessage:
    """CAN bus message."""
    arbitration_id: int
    data: bytes
    is_extended: bool = False
    is_remote: bool = False
    is_error: bool = False
    is_fd: bool = False
    bitrate_switch: bool = False
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

        # Ensure data is bytes and properly sized
        if isinstance(self.data, (list, tuple)):
            self.data = bytes(self.data)

        # CAN 2.0: max 8 bytes, CAN FD: max 64 bytes
        max_len = 64 if self.is_fd else 8
        if len(self.data) > max_len:
            self.data = self.data[:max_len]

    @property
    def dlc(self) -> int:
        """Data Length Code."""
        return len(self.data)

    def __str__(self):
        id_str = f"0x{self.arbitration_id:08X}" if self.is_extended else f"0x{self.arbitration_id:03X}"
        data_str = self.data.hex().upper()
        return f"CAN {id_str} [{self.dlc}] {data_str}"


@dataclass
class CANFilter:
    """CAN message filter."""
    id_value: int
    id_mask: int
    is_extended: bool = False
    fifo: int = 0  # 0 or 1

    def matches(self, msg: CANMessage) -> bool:
        """Check if message matches this filter."""
        if msg.is_extended != self.is_extended:
            return False
        return (msg.arbitration_id & self.id_mask) == (self.id_value & self.id_mask)


# =============================================================================
# CAN Controller Types
# =============================================================================

class CANMode(IntEnum):
    """CAN operating modes."""
    NORMAL = 0
    LOOPBACK = 1
    SILENT = 2
    SILENT_LOOPBACK = 3


class CANState(IntEnum):
    """CAN controller state."""
    STOPPED = 0
    ERROR_ACTIVE = 1
    ERROR_WARNING = 2
    ERROR_PASSIVE = 3
    BUS_OFF = 4


# =============================================================================
# CAN Controller Emulation (STM32 bxCAN compatible)
# =============================================================================

class CANController:
    """
    STM32 bxCAN Controller Emulation.

    Implements the basic extended CAN peripheral found in STM32F1/F2/F4.
    Compatible register layout allows running real STM32 firmware.
    """

    # Register offsets (bxCAN)
    MCR = 0x000   # Master Control Register
    MSR = 0x004   # Master Status Register
    TSR = 0x008   # Transmit Status Register
    RF0R = 0x00C  # Receive FIFO 0 Register
    RF1R = 0x010  # Receive FIFO 1 Register
    IER = 0x014   # Interrupt Enable Register
    ESR = 0x018   # Error Status Register
    BTR = 0x01C   # Bit Timing Register

    # TX Mailbox registers (3 mailboxes)
    TI0R = 0x180  # TX Mailbox 0 Identifier
    TDT0R = 0x184 # TX Mailbox 0 Data Length/Time
    TDL0R = 0x188 # TX Mailbox 0 Data Low
    TDH0R = 0x18C # TX Mailbox 0 Data High

    TI1R = 0x190
    TDT1R = 0x194
    TDL1R = 0x198
    TDH1R = 0x19C

    TI2R = 0x1A0
    TDT2R = 0x1A4
    TDL2R = 0x1A8
    TDH2R = 0x1AC

    # RX FIFO registers
    RI0R = 0x1B0  # RX FIFO 0 Identifier
    RDT0R = 0x1B4 # RX FIFO 0 Data Length/Time
    RDL0R = 0x1B8 # RX FIFO 0 Data Low
    RDH0R = 0x1BC # RX FIFO 0 Data High

    RI1R = 0x1C0
    RDT1R = 0x1C4
    RDL1R = 0x1C8
    RDH1R = 0x1CC

    # Filter registers
    FMR = 0x200   # Filter Master Register
    FM1R = 0x204  # Filter Mode Register
    FS1R = 0x20C  # Filter Scale Register
    FFA1R = 0x214 # Filter FIFO Assignment
    FA1R = 0x21C  # Filter Activation Register
    F0R1 = 0x240  # Filter 0 Register 1
    F0R2 = 0x244  # Filter 0 Register 2
    # ... more filter banks up to F27

    # MCR bits
    MCR_INRQ = 1 << 0   # Initialization request
    MCR_SLEEP = 1 << 1  # Sleep mode request
    MCR_TXFP = 1 << 2   # Transmit FIFO priority
    MCR_RFLM = 1 << 3   # Receive FIFO locked mode
    MCR_NART = 1 << 4   # No automatic retransmission
    MCR_AWUM = 1 << 5   # Automatic wakeup mode
    MCR_ABOM = 1 << 6   # Automatic bus-off management
    MCR_TTCM = 1 << 7   # Time triggered communication mode

    # MSR bits
    MSR_INAK = 1 << 0   # Initialization acknowledge
    MSR_SLAK = 1 << 1   # Sleep acknowledge

    # TSR bits
    TSR_TME0 = 1 << 26  # TX Mailbox 0 empty
    TSR_TME1 = 1 << 27  # TX Mailbox 1 empty
    TSR_TME2 = 1 << 28  # TX Mailbox 2 empty

    def __init__(self, base_address: int = 0x40006400, name: str = "CAN1"):
        self.base = base_address
        self.name = name

        # Registers
        self.regs: Dict[int, int] = {
            self.MCR: self.MCR_SLEEP,
            self.MSR: self.MSR_SLAK,
            self.TSR: self.TSR_TME0 | self.TSR_TME1 | self.TSR_TME2,
            self.RF0R: 0,
            self.RF1R: 0,
            self.IER: 0,
            self.ESR: 0,
            self.BTR: 0x01230000,
            self.FMR: 0x2A1C0E01,  # Default filter config
        }

        # TX mailboxes
        self.tx_mailboxes = [
            {'id': 0, 'dlc': 0, 'data': b'', 'pending': False},
            {'id': 0, 'dlc': 0, 'data': b'', 'pending': False},
            {'id': 0, 'dlc': 0, 'data': b'', 'pending': False},
        ]

        # RX FIFOs
        self.rx_fifo0: List[CANMessage] = []
        self.rx_fifo1: List[CANMessage] = []

        # Filters (28 filter banks)
        self.filters: List[CANFilter] = []

        # State
        self.mode = CANMode.NORMAL
        self.state = CANState.STOPPED
        self.tx_error_count = 0
        self.rx_error_count = 0

        # Bridge to real CAN
        self.bridge: Optional['CANBridge'] = None

        # Callbacks
        self.on_tx: Optional[Callable[[CANMessage], None]] = None
        self.on_rx: Optional[Callable[[CANMessage], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_interrupt: Optional[Callable[[int], None]] = None

        # RX thread
        self._rx_thread: Optional[threading.Thread] = None
        self._running = False

    def read_reg(self, offset: int) -> int:
        """Read CAN register."""
        if offset in self.regs:
            return self.regs[offset]

        # TX mailbox reads
        if offset == self.TI0R:
            return self._get_tx_id_reg(0)
        elif offset == self.TI1R:
            return self._get_tx_id_reg(1)
        elif offset == self.TI2R:
            return self._get_tx_id_reg(2)

        # RX FIFO reads
        if offset == self.RI0R:
            return self._get_rx_id_reg(0)
        elif offset == self.RDL0R:
            return self._get_rx_data_low(0)
        elif offset == self.RDH0R:
            return self._get_rx_data_high(0)
        elif offset == self.RI1R:
            return self._get_rx_id_reg(1)
        elif offset == self.RDL1R:
            return self._get_rx_data_low(1)
        elif offset == self.RDH1R:
            return self._get_rx_data_high(1)

        return 0

    def write_reg(self, offset: int, value: int):
        """Write CAN register."""
        old_value = self.regs.get(offset, 0)
        self.regs[offset] = value

        # Handle special registers
        if offset == self.MCR:
            self._handle_mcr(value)
        elif offset == self.TSR:
            self._handle_tsr(value)
        elif offset == self.RF0R:
            self._handle_rfr(0, value)
        elif offset == self.RF1R:
            self._handle_rfr(1, value)

        # TX mailbox writes
        elif offset == self.TI0R:
            self._handle_tx_id(0, value)
        elif offset == self.TDT0R:
            self.tx_mailboxes[0]['dlc'] = value & 0xF
        elif offset == self.TDL0R:
            self._set_tx_data_low(0, value)
        elif offset == self.TDH0R:
            self._set_tx_data_high(0, value)

        elif offset == self.TI1R:
            self._handle_tx_id(1, value)
        elif offset == self.TDT1R:
            self.tx_mailboxes[1]['dlc'] = value & 0xF
        elif offset == self.TDL1R:
            self._set_tx_data_low(1, value)
        elif offset == self.TDH1R:
            self._set_tx_data_high(1, value)

        elif offset == self.TI2R:
            self._handle_tx_id(2, value)
        elif offset == self.TDT2R:
            self.tx_mailboxes[2]['dlc'] = value & 0xF
        elif offset == self.TDL2R:
            self._set_tx_data_low(2, value)
        elif offset == self.TDH2R:
            self._set_tx_data_high(2, value)

    def _handle_mcr(self, value: int):
        """Handle Master Control Register write."""
        if value & self.MCR_INRQ:
            # Enter initialization mode
            self.state = CANState.STOPPED
            self.regs[self.MSR] |= self.MSR_INAK
            self.regs[self.MSR] &= ~self.MSR_SLAK
        else:
            # Exit initialization mode
            self.regs[self.MSR] &= ~self.MSR_INAK
            self.state = CANState.ERROR_ACTIVE
            self._start_rx()

        if value & self.MCR_SLEEP:
            self.regs[self.MSR] |= self.MSR_SLAK
            self._stop_rx()
        else:
            self.regs[self.MSR] &= ~self.MSR_SLAK

    def _handle_tsr(self, value: int):
        """Handle Transmit Status Register write."""
        # Writing 1 to RQCP bits clears them
        if value & (1 << 0):  # RQCP0
            self.regs[self.TSR] &= ~(1 << 0)
        if value & (1 << 8):  # RQCP1
            self.regs[self.TSR] &= ~(1 << 8)
        if value & (1 << 16):  # RQCP2
            self.regs[self.TSR] &= ~(1 << 16)

        # Abort requests
        if value & (1 << 7):  # ABRQ0
            self.tx_mailboxes[0]['pending'] = False
            self.regs[self.TSR] |= self.TSR_TME0
        if value & (1 << 15):  # ABRQ1
            self.tx_mailboxes[1]['pending'] = False
            self.regs[self.TSR] |= self.TSR_TME1
        if value & (1 << 23):  # ABRQ2
            self.tx_mailboxes[2]['pending'] = False
            self.regs[self.TSR] |= self.TSR_TME2

    def _handle_rfr(self, fifo: int, value: int):
        """Handle Receive FIFO Register write."""
        # RFOM bit - release message
        if value & (1 << 5):
            if fifo == 0 and self.rx_fifo0:
                self.rx_fifo0.pop(0)
                fmp = len(self.rx_fifo0)
                self.regs[self.RF0R] = (self.regs[self.RF0R] & ~3) | min(fmp, 3)
            elif fifo == 1 and self.rx_fifo1:
                self.rx_fifo1.pop(0)
                fmp = len(self.rx_fifo1)
                self.regs[self.RF1R] = (self.regs[self.RF1R] & ~3) | min(fmp, 3)

    def _handle_tx_id(self, mailbox: int, value: int):
        """Handle TX mailbox identifier write."""
        mb = self.tx_mailboxes[mailbox]

        if value & 4:  # Extended ID
            mb['id'] = (value >> 3) & 0x1FFFFFFF
            mb['extended'] = True
        else:  # Standard ID
            mb['id'] = (value >> 21) & 0x7FF
            mb['extended'] = False

        mb['rtr'] = bool(value & 2)

        # TXRQ bit - transmit request
        if value & 1:
            self._transmit_mailbox(mailbox)

    def _set_tx_data_low(self, mailbox: int, value: int):
        """Set TX data bytes 0-3."""
        mb = self.tx_mailboxes[mailbox]
        data = struct.pack("<I", value)
        if len(mb.get('data', b'')) < 8:
            mb['data'] = data + b'\x00' * 4
        else:
            mb['data'] = data + mb['data'][4:8]

    def _set_tx_data_high(self, mailbox: int, value: int):
        """Set TX data bytes 4-7."""
        mb = self.tx_mailboxes[mailbox]
        data = struct.pack("<I", value)
        if len(mb.get('data', b'')) < 4:
            mb['data'] = b'\x00' * 4 + data
        else:
            mb['data'] = mb['data'][:4] + data

    def _get_tx_id_reg(self, mailbox: int) -> int:
        """Get TX mailbox identifier register."""
        mb = self.tx_mailboxes[mailbox]
        if mb.get('extended', False):
            return (mb.get('id', 0) << 3) | 4
        else:
            return mb.get('id', 0) << 21

    def _get_rx_id_reg(self, fifo: int) -> int:
        """Get RX FIFO identifier register."""
        fifo_list = self.rx_fifo0 if fifo == 0 else self.rx_fifo1
        if not fifo_list:
            return 0

        msg = fifo_list[0]
        if msg.is_extended:
            return (msg.arbitration_id << 3) | 4 | (2 if msg.is_remote else 0)
        else:
            return (msg.arbitration_id << 21) | (2 if msg.is_remote else 0)

    def _get_rx_data_low(self, fifo: int) -> int:
        """Get RX FIFO data low register."""
        fifo_list = self.rx_fifo0 if fifo == 0 else self.rx_fifo1
        if not fifo_list:
            return 0

        data = fifo_list[0].data
        if len(data) < 4:
            data = data + b'\x00' * (4 - len(data))
        return struct.unpack("<I", data[:4])[0]

    def _get_rx_data_high(self, fifo: int) -> int:
        """Get RX FIFO data high register."""
        fifo_list = self.rx_fifo0 if fifo == 0 else self.rx_fifo1
        if not fifo_list:
            return 0

        data = fifo_list[0].data
        if len(data) < 8:
            data = data + b'\x00' * (8 - len(data))
        return struct.unpack("<I", data[4:8])[0]

    def _transmit_mailbox(self, mailbox: int):
        """Transmit message from mailbox."""
        mb = self.tx_mailboxes[mailbox]

        # Mark mailbox as not empty
        tme_bit = [self.TSR_TME0, self.TSR_TME1, self.TSR_TME2][mailbox]
        self.regs[self.TSR] &= ~tme_bit

        # Create message
        msg = CANMessage(
            arbitration_id=mb.get('id', 0),
            data=mb.get('data', b'')[:mb.get('dlc', 0)],
            is_extended=mb.get('extended', False),
            is_remote=mb.get('rtr', False)
        )

        logger.debug(f"{self.name} TX: {msg}")

        # Send to bridge
        if self.bridge:
            try:
                self.bridge.send(msg)
            except Exception as e:
                logger.error(f"{self.name} TX error: {e}")
                self.tx_error_count += 1

        # Loopback mode
        if self.mode in (CANMode.LOOPBACK, CANMode.SILENT_LOOPBACK):
            self._receive_message(msg)

        # Callback
        if self.on_tx:
            self.on_tx(msg)

        # Set TXOK and TME
        rqcp_bit = [1, 1 << 8, 1 << 16][mailbox]
        txok_bit = [1 << 1, 1 << 9, 1 << 17][mailbox]
        self.regs[self.TSR] |= rqcp_bit | txok_bit | tme_bit

        # Generate interrupt
        if self.regs[self.IER] & 1:  # TMEIE
            if self.on_interrupt:
                self.on_interrupt(0)  # TX interrupt

    def _receive_message(self, msg: CANMessage):
        """Receive a message into FIFO."""
        # Apply filters
        fifo = 0
        matched = False

        for filt in self.filters:
            if filt.matches(msg):
                fifo = filt.fifo
                matched = True
                break

        if not matched and self.filters:
            return  # Filtered out

        # Add to FIFO
        fifo_list = self.rx_fifo0 if fifo == 0 else self.rx_fifo1

        if len(fifo_list) < 3:  # FIFO depth
            fifo_list.append(msg)

            # Update FMP (FIFO Message Pending)
            if fifo == 0:
                fmp = min(len(self.rx_fifo0), 3)
                self.regs[self.RF0R] = (self.regs[self.RF0R] & ~3) | fmp
            else:
                fmp = min(len(self.rx_fifo1), 3)
                self.regs[self.RF1R] = (self.regs[self.RF1R] & ~3) | fmp

            logger.debug(f"{self.name} RX FIFO{fifo}: {msg}")

            # Callback
            if self.on_rx:
                self.on_rx(msg)

            # Generate interrupt
            fmpie = (1 << 1) if fifo == 0 else (1 << 4)
            if self.regs[self.IER] & fmpie:
                if self.on_interrupt:
                    self.on_interrupt(1 if fifo == 0 else 2)

    def connect_bridge(self, bridge: 'CANBridge'):
        """Connect to a CAN bridge for real bus access."""
        self.bridge = bridge
        bridge.on_receive = self._receive_message

    def _start_rx(self):
        """Start receiving messages."""
        if self._running:
            return

        self._running = True

        if self.bridge:
            self.bridge.start()

    def _stop_rx(self):
        """Stop receiving messages."""
        self._running = False

        if self.bridge:
            self.bridge.stop()

    def add_filter(self, id_value: int, id_mask: int = 0x7FF,
                   is_extended: bool = False, fifo: int = 0):
        """Add a receive filter."""
        self.filters.append(CANFilter(id_value, id_mask, is_extended, fifo))


# =============================================================================
# CAN Bridge Interface
# =============================================================================

class CANBridge(ABC):
    """Abstract base class for CAN bridges."""

    on_receive: Optional[Callable[[CANMessage], None]] = None

    @abstractmethod
    def send(self, msg: CANMessage):
        """Send a CAN message."""
        pass

    @abstractmethod
    def start(self):
        """Start receiving."""
        pass

    @abstractmethod
    def stop(self):
        """Stop receiving."""
        pass


class SocketCANBridge(CANBridge):
    """
    Linux SocketCAN bridge.

    Connects the emulator to a real CAN interface (can0, vcan0, etc.)
    """

    def __init__(self, interface: str = "vcan0"):
        self.interface = interface
        self.sock = None
        self._running = False
        self._rx_thread: Optional[threading.Thread] = None

    def start(self):
        """Start SocketCAN connection."""
        try:
            import socket

            # Create raw CAN socket
            self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            self.sock.bind((self.interface,))
            self.sock.settimeout(0.1)

            self._running = True
            self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
            self._rx_thread.start()

            logger.info(f"SocketCAN bridge started on {self.interface}")

        except Exception as e:
            logger.error(f"Failed to start SocketCAN bridge: {e}")
            raise

    def stop(self):
        """Stop SocketCAN connection."""
        self._running = False

        if self._rx_thread:
            self._rx_thread.join(timeout=1.0)

        if self.sock:
            self.sock.close()
            self.sock = None

    def send(self, msg: CANMessage):
        """Send CAN message via SocketCAN."""
        if not self.sock:
            raise RuntimeError("SocketCAN not connected")

        # Build CAN frame
        # struct can_frame: can_id (4), can_dlc (1), pad (3), data (8)
        can_id = msg.arbitration_id
        if msg.is_extended:
            can_id |= 0x80000000  # CAN_EFF_FLAG
        if msg.is_remote:
            can_id |= 0x40000000  # CAN_RTR_FLAG
        if msg.is_error:
            can_id |= 0x20000000  # CAN_ERR_FLAG

        data = msg.data.ljust(8, b'\x00')
        frame = struct.pack("=IB3x8s", can_id, len(msg.data), data)

        self.sock.send(frame)

    def _rx_loop(self):
        """Receive loop for SocketCAN."""
        while self._running:
            try:
                frame = self.sock.recv(16)
                if len(frame) < 16:
                    continue

                can_id, dlc = struct.unpack("=IB", frame[:5])
                data = frame[8:8 + dlc]

                is_extended = bool(can_id & 0x80000000)
                is_remote = bool(can_id & 0x40000000)
                is_error = bool(can_id & 0x20000000)

                # Mask off flags
                arb_id = can_id & 0x1FFFFFFF if is_extended else can_id & 0x7FF

                msg = CANMessage(
                    arbitration_id=arb_id,
                    data=data,
                    is_extended=is_extended,
                    is_remote=is_remote,
                    is_error=is_error
                )

                if self.on_receive:
                    self.on_receive(msg)

            except TimeoutError:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"SocketCAN RX error: {e}")


class VirtualCANBridge(CANBridge):
    """
    Virtual CAN bridge for testing without real hardware.

    Messages are echoed or routed between multiple controllers.
    """

    def __init__(self):
        self._bus: List[Callable[[CANMessage], None]] = []
        self._running = False

    def connect(self, callback: Callable[[CANMessage], None]):
        """Connect a receiver to the virtual bus."""
        self._bus.append(callback)

    def start(self):
        self._running = True

    def stop(self):
        self._running = False

    def send(self, msg: CANMessage):
        """Send message to all receivers on virtual bus."""
        if not self._running:
            return

        for callback in self._bus:
            try:
                callback(msg)
            except Exception as e:
                logger.error(f"Virtual CAN callback error: {e}")

        # Also deliver to own receiver (loopback)
        if self.on_receive:
            self.on_receive(msg)


# =============================================================================
# Demo
# =============================================================================

def demo_can_controller():
    """Demonstrate CAN controller functionality."""
    print("=" * 60)
    print("CAN Controller Demo")
    print("=" * 60)

    # Create two CAN controllers
    can1 = CANController(0x40006400, "CAN1")
    can2 = CANController(0x40006800, "CAN2")

    # Connect via virtual bridge
    vcan = VirtualCANBridge()
    vcan.connect(can2._receive_message)

    can1.connect_bridge(vcan)
    can2.on_receive = lambda msg: print(f"  CAN2 received: {msg}")

    # Add filter to CAN2
    can2.add_filter(0x100, 0x7F0)  # Accept 0x100-0x10F

    print("\n1. Initialize CAN controllers")
    print("-" * 40)

    # Exit sleep mode, enter init
    can1.write_reg(CANController.MCR, CANController.MCR_INRQ)
    print(f"  CAN1 MCR: 0x{can1.read_reg(CANController.MCR):08X}")
    print(f"  CAN1 MSR: 0x{can1.read_reg(CANController.MSR):08X}")

    # Configure bit timing (500kbps example)
    can1.write_reg(CANController.BTR, 0x001C0003)

    # Exit init mode
    can1.write_reg(CANController.MCR, 0)
    print(f"  CAN1 MSR after init: 0x{can1.read_reg(CANController.MSR):08X}")

    print("\n2. Transmit message")
    print("-" * 40)

    # Prepare TX mailbox 0
    can1.write_reg(CANController.TDL0R, 0xDEADBEEF)  # Data low
    can1.write_reg(CANController.TDH0R, 0xCAFEBABE)  # Data high
    can1.write_reg(CANController.TDT0R, 8)           # DLC = 8

    # Set ID and transmit (standard ID 0x105)
    can1.write_reg(CANController.TI0R, (0x105 << 21) | 1)  # TXRQ = 1

    print(f"  CAN1 TSR: 0x{can1.read_reg(CANController.TSR):08X}")

    print("\n3. Check RX FIFO")
    print("-" * 40)

    print(f"  CAN2 RF0R: 0x{can2.read_reg(CANController.RF0R):08X}")
    print(f"  CAN2 FIFO0 messages: {len(can2.rx_fifo0)}")

    if can2.rx_fifo0:
        msg = can2.rx_fifo0[0]
        print(f"  Received: {msg}")

    print("\n4. Send filtered message (should be filtered)")
    print("-" * 40)

    # Send ID 0x200 (outside filter range)
    can1.write_reg(CANController.TI0R, (0x200 << 21) | 1)
    print(f"  CAN2 FIFO0 messages after 0x200: {len(can2.rx_fifo0)}")

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    demo_can_controller()
