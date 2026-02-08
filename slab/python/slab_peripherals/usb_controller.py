"""
USB Controller Base Class - Unified Interface for DWC2/DWC3/xHCI Emulation

Provides common infrastructure for all USB controller emulations:
- Timing model (SOF generation, frame counting)
- Coverage tracking (register, state, event, DMA instrumentation)
- EP0 control transfer FSM (SETUP -> DATA -> STATUS)
- Data toggle tracking (DATA0/DATA1 per endpoint)
- DMA address validation
- Endpoint state management

Based on Synopsys DWC2 OTG v3.30a datasheet and DWC3 specifications.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025-2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import struct
from abc import ABC, abstractmethod
from enum import IntEnum, auto
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional, Callable, Any
from collections import defaultdict
import logging

logger = logging.getLogger("usb_controller")


# =============================================================================
# USB Constants (from USB 2.0 Specification)
# =============================================================================

class USBSpeed(IntEnum):
    HIGH_SPEED = 0    # 480 Mbps (DWC2: 30/60 MHz PHY)
    FULL_SPEED = 1    # 12 Mbps (DWC2: 48 MHz PHY)
    LOW_SPEED = 2     # 1.5 Mbps
    SUPER_SPEED = 3   # 5 Gbps (DWC3 only)


class USBEPType(IntEnum):
    CONTROL = 0
    ISOCHRONOUS = 1
    BULK = 2
    INTERRUPT = 3


class USBDirection(IntEnum):
    OUT = 0  # Host to Device
    IN = 1   # Device to Host


# Standard USB Request Types
USB_REQ_GET_STATUS = 0x00
USB_REQ_CLEAR_FEATURE = 0x01
USB_REQ_SET_FEATURE = 0x03
USB_REQ_SET_ADDRESS = 0x05
USB_REQ_GET_DESCRIPTOR = 0x06
USB_REQ_SET_DESCRIPTOR = 0x07
USB_REQ_GET_CONFIGURATION = 0x08
USB_REQ_SET_CONFIGURATION = 0x09
USB_REQ_GET_INTERFACE = 0x0A
USB_REQ_SET_INTERFACE = 0x0B

# Feature selectors
USB_FEATURE_ENDPOINT_HALT = 0x00


# =============================================================================
# Timing Model
# =============================================================================

@dataclass
class TimerCallback:
    """Scheduled timer event."""
    fire_cycle: int
    callback: Callable
    name: str = ""
    repeat_interval: int = 0  # 0 = one-shot, >0 = periodic


class USBTimingModel:
    """
    USB timing model with cycle counting and SOF generation.

    Per DWC2 datasheet Section 2.4:
    - HS: 125 us microframe (SOF every 7500 PHY clocks @ 60MHz)
    - FS: 1 ms frame (SOF every 48000 PHY clocks @ 48MHz)
    - USB turnaround: 5 PHY clocks
    - USB reset: ~10ms
    """

    # PHY clock frequencies (Hz)
    PHY_CLK_HS_8BIT = 60_000_000   # 60 MHz (8-bit UTMI+)
    PHY_CLK_HS_16BIT = 30_000_000  # 30 MHz (16-bit UTMI+)
    PHY_CLK_FS = 48_000_000        # 48 MHz (Full-Speed)

    # SOF intervals in PHY clocks
    SOF_INTERVAL_HS = 7500     # 125 us @ 60MHz
    SOF_INTERVAL_FS = 48000    # 1 ms @ 48MHz

    # USB timing constants (in PHY clocks)
    USB_TURNAROUND_CLOCKS = 5  # Core allocation for turnaround
    USB_RESET_CLOCKS = 600000  # ~10ms @ 60MHz
    REMOTE_WAKEUP_CLOCKS = 3000  # 50us @ 60MHz

    def __init__(self, speed: USBSpeed = USBSpeed.HIGH_SPEED,
                 phy_width: int = 8):
        self.speed = speed
        self.phy_width = phy_width

        # Set PHY clock based on speed/width
        if speed == USBSpeed.HIGH_SPEED:
            self.phy_clk = (self.PHY_CLK_HS_8BIT if phy_width == 8
                           else self.PHY_CLK_HS_16BIT)
            self.sof_interval = self.SOF_INTERVAL_HS
        else:
            self.phy_clk = self.PHY_CLK_FS
            self.sof_interval = self.SOF_INTERVAL_FS

        # Counters
        self.cycle: int = 0
        self.frame_number: int = 0       # 14-bit (0-0x3FFF)
        self.microframe_number: int = 0  # 3-bit (0-7) for HS
        self.frame_remaining: int = self.sof_interval

        # Timer queue (sorted by fire_cycle)
        self._timers: List[TimerCallback] = []
        self._sof_callbacks: List[Callable] = []

    def advance(self, cycles: int = 1):
        """Advance the timing model by N PHY clock cycles."""
        target = self.cycle + cycles

        while self.cycle < target:
            step = min(target - self.cycle, self.frame_remaining)
            self.cycle += step
            self.frame_remaining -= step

            # Check for SOF
            if self.frame_remaining <= 0:
                self._generate_sof()
                self.frame_remaining = self.sof_interval

            # Fire expired timers
            self._check_timers()

    def _generate_sof(self):
        """Generate Start-of-Frame event."""
        if self.speed == USBSpeed.HIGH_SPEED:
            self.microframe_number = (self.microframe_number + 1) & 0x7
            if self.microframe_number == 0:
                self.frame_number = (self.frame_number + 1) & 0x3FFF
        else:
            self.frame_number = (self.frame_number + 1) & 0x3FFF

        for cb in self._sof_callbacks:
            cb(self.frame_number, self.microframe_number)

    def _check_timers(self):
        """Fire any expired timer callbacks, including repeated firings."""
        fired = []
        for timer in self._timers:
            if self.cycle >= timer.fire_cycle:
                timer.callback()
                if timer.repeat_interval > 0:
                    # Fire multiple times if we skipped past several intervals
                    while self.cycle >= timer.fire_cycle + timer.repeat_interval:
                        timer.fire_cycle += timer.repeat_interval
                        timer.callback()
                    timer.fire_cycle += timer.repeat_interval
                else:
                    fired.append(timer)

        for t in fired:
            self._timers.remove(t)

    def schedule(self, delay_cycles: int, callback: Callable,
                 name: str = "", repeat: int = 0) -> TimerCallback:
        """Schedule a timer callback."""
        timer = TimerCallback(
            fire_cycle=self.cycle + delay_cycles,
            callback=callback,
            name=name,
            repeat_interval=repeat,
        )
        self._timers.append(timer)
        self._timers.sort(key=lambda t: t.fire_cycle)
        return timer

    def cancel_timer(self, timer: TimerCallback):
        """Cancel a scheduled timer."""
        if timer in self._timers:
            self._timers.remove(timer)

    def register_sof_callback(self, callback: Callable):
        """Register callback for SOF events."""
        self._sof_callbacks.append(callback)

    def get_soffn(self) -> int:
        """Get current SOF frame number (14-bit) for DSTS register."""
        if self.speed == USBSpeed.HIGH_SPEED:
            # HS: SOFFN = frame_number[10:0] << 3 | microframe[2:0]
            return ((self.frame_number & 0x7FF) << 3) | self.microframe_number
        else:
            return self.frame_number & 0x3FFF

    def get_frame_remaining(self) -> int:
        """Get time remaining in current frame (for HFNUM.FRREM)."""
        return self.frame_remaining

    def reset(self):
        """Reset timing model."""
        self.cycle = 0
        self.frame_number = 0
        self.microframe_number = 0
        self.frame_remaining = self.sof_interval
        self._timers.clear()


# =============================================================================
# Coverage Tracker
# =============================================================================

@dataclass
class CoveragePoint:
    """Single coverage observation point."""
    type: str       # 'register', 'state', 'event', 'error', 'dma'
    location: str   # register offset, state name, event type
    context: str = ""  # additional context (read/write, value, etc.)


class USBCoverageTracker:
    """
    Unified USB controller coverage tracker for fuzzing.

    Tracks register accesses, state transitions, events, DMA operations,
    and errors. Compatible with the FuzzEngine edge-based coverage.
    """

    def __init__(self):
        self.coverage_points: Set[str] = set()
        self.coverage_edges: Dict[str, int] = defaultdict(int)
        self.register_hits: Dict[int, int] = defaultdict(int)
        self.state_hits: Dict[str, int] = defaultdict(int)
        self.event_hits: Dict[str, int] = defaultdict(int)
        self.error_hits: Dict[str, int] = defaultdict(int)
        self.dma_hits: Dict[int, int] = defaultdict(int)
        self.interesting_events: List[Dict] = []
        self.crashes: List[Dict] = []
        self._last_point: Optional[str] = None

    def record_register_access(self, offset: int, is_write: bool,
                                value: int = 0):
        """Record a register read/write for coverage."""
        rw = "W" if is_write else "R"
        point = f"register:0x{offset:03X}:{rw}"
        self._add_point(point)
        self.register_hits[offset] += 1

    def record_state_transition(self, from_state: str, to_state: str):
        """Record a state machine transition."""
        point = f"state:{from_state}->{to_state}"
        self._add_point(point)
        self.state_hits[to_state] += 1
        self.interesting_events.append({
            'type': 'state_transition',
            'from': from_state,
            'to': to_state,
        })

    def record_event(self, event_type: str, data: Optional[Dict] = None):
        """Record a USB event."""
        point = f"event:{event_type}"
        if data:
            # Include key data fields in the coverage point
            for k, v in sorted(data.items())[:3]:
                point += f",{k}={v}"
        self._add_point(point)
        self.event_hits[event_type] += 1

    def record_dma_operation(self, addr: int, size: int, is_write: bool):
        """Record a DMA operation."""
        # Bucket by high 16 bits of address for coverage
        bucket = (addr >> 16) & 0xFFFF
        point = f"dma:0x{bucket:04X}:{'W' if is_write else 'R'}:{size}"
        self._add_point(point)
        self.dma_hits[bucket] += 1

    def record_error(self, error_type: str, details: Optional[Dict] = None):
        """Record an error condition."""
        point = f"error:{error_type}"
        self._add_point(point)
        self.error_hits[error_type] += 1
        self.interesting_events.append({
            'type': 'error',
            'error_type': error_type,
            'details': details or {},
        })

    def record_crash(self, crash_type: str, addr: int = 0,
                     details: Optional[Dict] = None):
        """Record a crash/violation."""
        self.crashes.append({
            'type': crash_type,
            'addr': addr,
            'details': details or {},
        })
        self.record_error(f"crash:{crash_type}", details)

    def _add_point(self, point: str):
        """Add coverage point and track edge."""
        self.coverage_points.add(point)
        if self._last_point:
            edge = f"{self._last_point} -> {point}"
            self.coverage_edges[edge] += 1
        self._last_point = point

    def get_stats(self) -> Dict:
        """Get coverage statistics."""
        return {
            'total_points': len(self.coverage_points),
            'total_edges': len(self.coverage_edges),
            'register_coverage': len(self.register_hits),
            'state_coverage': len(self.state_hits),
            'event_coverage': len(self.event_hits),
            'error_coverage': len(self.error_hits),
            'dma_coverage': len(self.dma_hits),
            'interesting_events': len(self.interesting_events),
            'crashes': len(self.crashes),
        }

    def reset_session(self):
        """Reset per-session tracking (keep cumulative points)."""
        self._last_point = None


# =============================================================================
# EP0 Control Transfer FSM
# =============================================================================

class EP0Phase(IntEnum):
    """EP0 control transfer phases."""
    IDLE = 0
    SETUP_RECEIVED = 1
    DATA_IN = 2       # Device -> Host (IN tokens)
    DATA_OUT = 3      # Host -> Device (OUT tokens)
    STATUS_IN = 4     # Zero-length IN (after DATA_OUT or no-data)
    STATUS_OUT = 5    # Zero-length OUT (after DATA_IN)
    COMPLETE = 6


@dataclass
class SetupPacket:
    """Parsed USB SETUP packet (8 bytes)."""
    bmRequestType: int = 0
    bRequest: int = 0
    wValue: int = 0
    wIndex: int = 0
    wLength: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> 'SetupPacket':
        if len(data) < 8:
            return cls()
        rt, req, val, idx, length = struct.unpack_from('<BBHHH', data)
        return cls(bmRequestType=rt, bRequest=req, wValue=val,
                   wIndex=idx, wLength=length)

    @property
    def direction_in(self) -> bool:
        """True if device-to-host (IN)."""
        return bool(self.bmRequestType & 0x80)

    @property
    def request_type(self) -> int:
        """Request type: 0=Standard, 1=Class, 2=Vendor."""
        return (self.bmRequestType >> 5) & 0x03

    @property
    def recipient(self) -> int:
        """Recipient: 0=Device, 1=Interface, 2=Endpoint, 3=Other."""
        return self.bmRequestType & 0x1F


class EP0ControlFSM:
    """
    EP0 Control Transfer state machine per DWC2 datasheet Section 7-10.

    Handles:
    - Normal control transfers (SETUP -> DATA -> STATUS)
    - No-data control transfers (SETUP -> STATUS)
    - Back-to-back SETUP packets (abort current, restart)
    - Premature status phase
    - SUPCnt=3 buffering (up to 3 queued SETUP packets)
    """

    def __init__(self, coverage: Optional[USBCoverageTracker] = None):
        self.phase = EP0Phase.IDLE
        self.setup_packet = SetupPacket()
        self.setup_buffer: List[bytes] = []  # SUPCnt buffering
        self.sup_cnt: int = 3  # Max back-to-back SETUP packets
        self.data_remaining: int = 0
        self.data_transferred: int = 0
        self._coverage = coverage
        self._callbacks: Dict[str, Callable] = {}

    def register_callback(self, event: str, callback: Callable):
        """Register callback for FSM events: 'setup', 'data_in', 'data_out', 'status', 'complete'."""
        self._callbacks[event] = callback

    def receive_setup(self, data: bytes) -> bool:
        """
        Handle incoming SETUP packet.

        Per datasheet: SETUP can arrive at any time and aborts current transfer.
        Returns True if SETUP was accepted.
        """
        if len(data) < 8:
            if self._coverage:
                self._coverage.record_error("short_setup", {'size': len(data)})
            return False

        # Back-to-back SETUP: abort current transfer
        if self.phase not in (EP0Phase.IDLE, EP0Phase.COMPLETE):
            if self._coverage:
                self._coverage.record_event("back_to_back_setup", {
                    'prev_phase': self.phase.name
                })

        old_phase = self.phase
        self.setup_packet = SetupPacket.from_bytes(data)
        self.phase = EP0Phase.SETUP_RECEIVED
        self.data_remaining = self.setup_packet.wLength
        self.data_transferred = 0

        if self._coverage:
            self._coverage.record_state_transition(
                old_phase.name, self.phase.name)

        # Buffer SETUP for SUPCnt tracking
        self.setup_buffer.append(data[:8])
        if len(self.setup_buffer) > self.sup_cnt:
            self.setup_buffer.pop(0)

        # Notify callback
        if 'setup' in self._callbacks:
            self._callbacks['setup'](self.setup_packet)

        return True

    def start_data_phase(self) -> EP0Phase:
        """
        Transition from SETUP_RECEIVED to DATA phase.
        Call after firmware has processed the SETUP packet.
        """
        if self.phase != EP0Phase.SETUP_RECEIVED:
            return self.phase

        old_phase = self.phase

        if self.setup_packet.wLength == 0:
            # No data stage - go directly to status
            if self.setup_packet.direction_in:
                self.phase = EP0Phase.STATUS_OUT
            else:
                self.phase = EP0Phase.STATUS_IN
        elif self.setup_packet.direction_in:
            self.phase = EP0Phase.DATA_IN
        else:
            self.phase = EP0Phase.DATA_OUT

        if self._coverage:
            self._coverage.record_state_transition(
                old_phase.name, self.phase.name)

        return self.phase

    def data_packet_done(self, size: int) -> bool:
        """
        Called when a data packet completes.
        Returns True if data phase is complete (all data transferred or short packet).
        """
        self.data_transferred += size
        self.data_remaining = max(0, self.setup_packet.wLength - self.data_transferred)

        if self._coverage:
            self._coverage.record_event("ep0_data_packet", {
                'size': size,
                'remaining': self.data_remaining,
            })

        # Data phase complete if all data transferred or short packet
        return self.data_remaining == 0 or size == 0

    def start_status_phase(self) -> EP0Phase:
        """
        Transition to STATUS phase after data phase completes.
        Status is always in the opposite direction of data.
        """
        old_phase = self.phase

        if self.phase == EP0Phase.DATA_IN:
            self.phase = EP0Phase.STATUS_OUT
        elif self.phase == EP0Phase.DATA_OUT:
            self.phase = EP0Phase.STATUS_IN
        elif self.phase == EP0Phase.SETUP_RECEIVED:
            # No-data: status IN for host-to-device SETUP
            self.phase = EP0Phase.STATUS_IN

        if self._coverage:
            self._coverage.record_state_transition(
                old_phase.name, self.phase.name)

        if 'status' in self._callbacks:
            self._callbacks['status'](self.phase)

        return self.phase

    def status_complete(self):
        """Status phase completed - transfer is done."""
        old_phase = self.phase
        self.phase = EP0Phase.COMPLETE

        if self._coverage:
            self._coverage.record_state_transition(
                old_phase.name, self.phase.name)
            self._coverage.record_event("ep0_transfer_complete", {
                'request': self.setup_packet.bRequest,
                'wValue': self.setup_packet.wValue,
                'wLength': self.setup_packet.wLength,
            })

        if 'complete' in self._callbacks:
            self._callbacks['complete'](self.setup_packet)

        # Return to idle
        self.phase = EP0Phase.IDLE

    def premature_status(self):
        """
        Handle premature status phase (host sends status before all data).
        Per datasheet: DOEPINTn.StsPhseRcvd with XferCompl=0.
        """
        if self._coverage:
            self._coverage.record_event("premature_status", {
                'phase': self.phase.name,
                'remaining': self.data_remaining,
            })

        # Skip remaining data, go to status
        self.data_remaining = 0
        self.start_status_phase()

    def reset(self):
        """Reset EP0 FSM to IDLE."""
        self.phase = EP0Phase.IDLE
        self.setup_packet = SetupPacket()
        self.setup_buffer.clear()
        self.data_remaining = 0
        self.data_transferred = 0


# =============================================================================
# Data Toggle Tracker
# =============================================================================

class DataToggleTracker:
    """
    Per-endpoint DATA0/DATA1 toggle tracking.

    Per USB 2.0 spec Section 8.6:
    - Toggle initialized to DATA0 on configuration/interface events
    - Alternates DATA0/DATA1 on each successful transfer
    - Reset by ClearFeature(ENDPOINT_HALT)
    """

    def __init__(self):
        # Key: (ep_number, direction_in) -> toggle value (0 or 1)
        self._toggles: Dict[Tuple[int, bool], int] = {}

    def get(self, ep: int, direction_in: bool) -> int:
        """Get current data toggle (0=DATA0, 1=DATA1)."""
        return self._toggles.get((ep, direction_in), 0)

    def flip(self, ep: int, direction_in: bool):
        """Flip toggle after successful transfer."""
        key = (ep, direction_in)
        self._toggles[key] = 1 - self._toggles.get(key, 0)

    def reset_endpoint(self, ep: int):
        """Reset toggle for endpoint (both directions) - on ClearFeature(HALT)."""
        for direction in (True, False):
            self._toggles[(ep, direction)] = 0

    def reset_all(self):
        """Reset all toggles - on SET_CONFIGURATION or SET_INTERFACE."""
        self._toggles.clear()

    def set(self, ep: int, direction_in: bool, value: int):
        """Explicitly set toggle value (for SetD0PID/SetD1PID)."""
        self._toggles[(ep, direction_in)] = value & 1


# =============================================================================
# DMA Validator
# =============================================================================

class DMAValidator:
    """
    DMA address validation for USB controllers.

    Validates that DMA addresses and sizes fall within allowed memory zones.
    Per DWC2 datasheet: DMA buffers must be DWORD-aligned (4-byte boundary).
    """

    DWORD_ALIGNMENT = 4

    def __init__(self, zones: Optional[List[Tuple[int, int]]] = None,
                 require_alignment: bool = True):
        """
        Args:
            zones: List of (start, end) allowed address ranges
            require_alignment: Require DWORD alignment
        """
        self.zones = zones or []
        self.require_alignment = require_alignment
        self.violations: List[Dict] = []

    def add_zone(self, start: int, end: int):
        """Add an allowed DMA zone."""
        self.zones.append((start, end))

    def validate(self, addr: int, size: int = 0,
                 coverage: Optional[USBCoverageTracker] = None) -> bool:
        """
        Validate DMA address.

        Returns True if valid, False if violation.
        Records violation in coverage tracker if provided.
        """
        # Check alignment
        if self.require_alignment and (addr & (self.DWORD_ALIGNMENT - 1)):
            violation = {
                'type': 'alignment',
                'addr': addr,
                'size': size,
                'required': self.DWORD_ALIGNMENT,
            }
            self.violations.append(violation)
            if coverage:
                coverage.record_error("dma_alignment_violation", violation)
            return False

        # Check zone containment
        if self.zones:
            end_addr = addr + size if size > 0 else addr + 1
            for zone_start, zone_end in self.zones:
                if zone_start <= addr and end_addr <= zone_end:
                    return True

            violation = {
                'type': 'zone_violation',
                'addr': addr,
                'size': size,
                'zones': [(s, e) for s, e in self.zones],
            }
            self.violations.append(violation)
            if coverage:
                coverage.record_error("dma_zone_violation", violation)
            return False

        # No zones configured = all addresses allowed
        return True

    def reset(self):
        """Clear violation history."""
        self.violations.clear()


# =============================================================================
# Endpoint State
# =============================================================================

@dataclass
class EndpointState:
    """Per-endpoint hardware state."""
    number: int = 0
    direction_in: bool = False
    enabled: bool = False
    stalled: bool = False
    nak: bool = True  # NAK by default until enabled
    mps: int = 64     # Max Packet Size (bytes)
    ep_type: USBEPType = USBEPType.CONTROL
    fifo_num: int = 0

    # Transfer state
    xfer_size: int = 0         # Total transfer size programmed
    xfer_remaining: int = 0    # Bytes remaining
    pkt_cnt: int = 0           # Packets remaining
    dma_addr: int = 0          # Current DMA buffer address

    # DWC2-specific
    dpid: int = 0              # Data PID (DATA0/DATA1)
    next_ep: int = 0           # Next endpoint (shared FIFO mode)

    def start_transfer(self, xfer_size: int, pkt_cnt: int, dma_addr: int = 0):
        """Start a new transfer on this endpoint."""
        self.xfer_size = xfer_size
        self.xfer_remaining = xfer_size
        self.pkt_cnt = pkt_cnt
        self.dma_addr = dma_addr
        self.enabled = True

    def packet_complete(self, size: int) -> bool:
        """
        Called when a packet completes.
        Returns True if transfer is complete.
        """
        self.xfer_remaining = max(0, self.xfer_remaining - size)
        self.pkt_cnt = max(0, self.pkt_cnt - 1)
        self.dma_addr += size

        # Transfer complete if no bytes remaining or short packet
        return self.xfer_remaining == 0 or size < self.mps or self.pkt_cnt == 0

    def reset(self):
        """Reset endpoint state."""
        self.enabled = False
        self.stalled = False
        self.nak = True
        self.xfer_size = 0
        self.xfer_remaining = 0
        self.pkt_cnt = 0
        self.dma_addr = 0
        self.dpid = 0


# =============================================================================
# USB Controller Base Class
# =============================================================================

class USBControllerBase(ABC):
    """
    Abstract base class for all USB controller emulations.

    Subclasses implement register-level emulation for specific controllers
    (DWC2, DWC3, xHCI, STM32F1, etc.) while this class provides the common
    timing, coverage, FSM, and state management infrastructure.
    """

    # Number of endpoints (override in subclass)
    NUM_ENDPOINTS = 4

    def __init__(self, speed: USBSpeed = USBSpeed.HIGH_SPEED,
                 num_endpoints: int = 4,
                 dma_zones: Optional[List[Tuple[int, int]]] = None):
        self.NUM_ENDPOINTS = num_endpoints

        # Timing
        self.timing = USBTimingModel(speed=speed)
        self.timing.register_sof_callback(self._on_sof)

        # Coverage
        self.coverage = USBCoverageTracker()

        # EP0 FSM
        self.ep0_fsm = EP0ControlFSM(coverage=self.coverage)

        # Data toggle
        self.data_toggle = DataToggleTracker()

        # DMA validation
        self.dma_validator = DMAValidator(
            zones=dma_zones or [],
            require_alignment=True,
        )

        # Endpoint states (IN and OUT separate)
        self.ep_in: List[EndpointState] = [
            EndpointState(number=i, direction_in=True)
            for i in range(num_endpoints)
        ]
        self.ep_out: List[EndpointState] = [
            EndpointState(number=i, direction_in=False)
            for i in range(num_endpoints)
        ]

        # Device state
        self.device_address: int = 0
        self.device_speed: USBSpeed = speed
        self.connected: bool = False
        self.suspended: bool = False
        self.configured: bool = False

        # Interrupt state
        self._irq_pending: bool = False
        self._irq_callback: Optional[Callable] = None

    # =========================================================================
    # Abstract Interface (must implement in subclass)
    # =========================================================================

    @abstractmethod
    def read_register(self, offset: int) -> int:
        """Read a controller register at the given offset."""
        ...

    @abstractmethod
    def write_register(self, offset: int, value: int):
        """Write a controller register at the given offset."""
        ...

    @abstractmethod
    def assert_interrupt(self, irq_type: str, **kwargs):
        """Assert an interrupt to the CPU."""
        ...

    # =========================================================================
    # Common Operations
    # =========================================================================

    def set_irq_callback(self, callback: Callable):
        """Set callback for interrupt assertion."""
        self._irq_callback = callback

    def _on_sof(self, frame_number: int, microframe: int):
        """Handle SOF event from timing model."""
        self.coverage.record_event("sof", {
            'frame': frame_number,
            'microframe': microframe,
        })
        self.assert_interrupt("sof", frame=frame_number)

    def usb_reset(self):
        """Handle USB bus reset."""
        self.device_address = 0
        self.configured = False
        self.suspended = False

        # Reset all endpoints
        for ep in self.ep_in + self.ep_out:
            ep.reset()

        # Reset EP0 FSM
        self.ep0_fsm.reset()

        # Reset data toggles
        self.data_toggle.reset_all()

        # Reset timing
        self.timing.reset()

        self.coverage.record_event("usb_reset")
        self.assert_interrupt("usb_reset")

    def set_address(self, address: int):
        """Handle SET_ADDRESS request."""
        self.device_address = address & 0x7F
        self.coverage.record_event("set_address", {'addr': address})

    def set_configuration(self, config: int):
        """Handle SET_CONFIGURATION request."""
        self.configured = config > 0
        self.data_toggle.reset_all()
        self.coverage.record_event("set_configuration", {'config': config})

    def stall_endpoint(self, ep: int, direction_in: bool):
        """Stall an endpoint."""
        ep_state = self.ep_in[ep] if direction_in else self.ep_out[ep]
        ep_state.stalled = True
        self.coverage.record_event("ep_stall", {
            'ep': ep, 'dir': 'IN' if direction_in else 'OUT'
        })

    def clear_stall(self, ep: int, direction_in: bool):
        """Clear stall and reset data toggle."""
        ep_state = self.ep_in[ep] if direction_in else self.ep_out[ep]
        ep_state.stalled = False
        self.data_toggle.reset_endpoint(ep)
        self.coverage.record_event("ep_clear_stall", {
            'ep': ep, 'dir': 'IN' if direction_in else 'OUT'
        })

    def get_endpoint(self, ep: int, direction_in: bool) -> EndpointState:
        """Get endpoint state."""
        return self.ep_in[ep] if direction_in else self.ep_out[ep]

    def advance_time(self, cycles: int = 1):
        """Advance the timing model (call from emulator main loop)."""
        self.timing.advance(cycles)
