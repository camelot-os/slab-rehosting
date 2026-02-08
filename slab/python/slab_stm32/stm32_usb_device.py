"""
STM32F1 USB Device Peripheral Emulation

Implements the USB Device controller found in STM32F103 and similar devices.
This is NOT the USB OTG controller (found in F4/F7/H7) - it's a simpler
full-speed USB device controller.

Memory Map:
- USB registers: 0x40005C00 - 0x40005FFF
- PMA (Packet Memory Area): 0x40006000 - 0x400063FF (512 bytes, word-aligned)

Key Registers:
- EP0R-EP7R (0x00-0x1C): Endpoint registers
- CNTR (0x40): Control register
- ISTR (0x44): Interrupt status register
- FNR (0x48): Frame number register
- DADDR (0x4C): Device address register
- BTABLE (0x50): Buffer table address

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Dict, Tuple, Callable, List
from dataclasses import dataclass, field
from enum import IntEnum

sys.path.insert(0, str(Path(__file__).parent.parent))
from slab_peripherals.usb_controller import (
    USBCoverageTracker, USBTimingModel, DataToggleTracker,
    USBSpeed,
)
from slab_peripherals.bus_logger import (
    log_unhandled as _log_unhandled,
    UninitializedMemoryTracker,
)

from .stm32_base import STM32Peripheral, STATUS_OK

logger = logging.getLogger(__name__)


class USBDeviceReg(IntEnum):
    """USB Device register offsets."""
    EP0R = 0x00
    EP1R = 0x04
    EP2R = 0x08
    EP3R = 0x0C
    EP4R = 0x10
    EP5R = 0x14
    EP6R = 0x18
    EP7R = 0x1C
    # Reserved 0x20-0x3F
    CNTR = 0x40
    ISTR = 0x44
    FNR = 0x48
    DADDR = 0x4C
    BTABLE = 0x50


class USBCntrBits(IntEnum):
    """USB_CNTR register bits."""
    FRES = 0       # Force USB Reset
    PDWN = 1       # Power down
    LP_MODE = 2    # Low-power mode
    FSUSP = 3      # Force suspend
    RESUME = 4     # Resume request
    L1RESUME = 5   # LPM L1 resume request
    L1REQM = 7     # LPM L1 state request interrupt mask
    ESOFM = 8      # Expected start of frame interrupt mask
    SOFM = 9       # Start of frame interrupt mask
    RESETM = 10    # USB reset interrupt mask
    SUSPM = 11     # Suspend mode interrupt mask
    WKUPM = 12     # Wakeup interrupt mask
    ERRM = 13      # Error interrupt mask
    PMAOVRM = 14   # Packet memory overrun interrupt mask
    CTRM = 15      # Correct transfer interrupt mask


class USBIstrBits(IntEnum):
    """USB_ISTR register bits."""
    EP_ID = 0      # Endpoint identifier (bits 0-3)
    DIR = 4        # Direction of transaction
    L1REQ = 7      # LPM L1 state request
    ESOF = 8       # Expected start of frame
    SOF = 9        # Start of frame
    RESET = 10     # USB reset request
    SUSP = 11      # Suspend mode request
    WKUP = 12      # Wakeup
    ERR = 13       # Error
    PMAOVR = 14    # Packet memory overrun
    CTR = 15       # Correct transfer


class EPTypeBits(IntEnum):
    """Endpoint type bits in EPnR."""
    BULK = 0b00
    CONTROL = 0b01
    ISO = 0b10
    INTERRUPT = 0b11


class EPStatBits(IntEnum):
    """Endpoint status bits."""
    DISABLED = 0b00
    STALL = 0b01
    NAK = 0b10
    VALID = 0b11


@dataclass
class EndpointState:
    """State of a USB endpoint."""
    type: int = EPTypeBits.BULK
    tx_status: int = EPStatBits.DISABLED
    rx_status: int = EPStatBits.DISABLED
    tx_addr: int = 0
    tx_count: int = 0
    rx_addr: int = 0
    rx_count: int = 0
    setup: bool = False
    ctr_tx: bool = False
    ctr_rx: bool = False


class STM32USBDevice(STM32Peripheral):
    """
    STM32 USB Device Controller (PMA-based).

    This peripheral provides full-speed (12 Mbps) USB device functionality.
    It uses a packet memory area (PMA) for endpoint buffers.
    Found in STM32F0/F1/F3/L0/L4/WB families.

    Features:
    - 8 endpoints (EP0-EP7)
    - Double buffering support
    - Isochronous transfer support
    - Suspend/resume
    - USBIP firmware-in-the-loop via inject methods
    """

    # USB Device register base (default for F1; WB55 uses 0x40006800)
    USB_BASE = 0x40005C00
    USB_SIZE = 0x400

    # PMA size (accessed as half-words on 32-bit boundaries)
    PMA_SIZE = 0x400

    # Number of endpoints
    NUM_ENDPOINTS = 8

    def __init__(self, base: int = USB_BASE, irq: int = 20, pma_access: int = 2):
        """
        Initialize USB Device peripheral.

        Args:
            base: Base address (default 0x40005C00; WB55 uses 0x40006800)
            irq: USB low-priority IRQ number (default 20)
            pma_access: PMA access mode (1=16-bit aligned for WB55/G0/U5,
                        2=32-bit aligned for F0/F1/F3/L1)
        """
        super().__init__("USB", base, self.USB_SIZE, irq)

        # PMA access mode: 1=direct (16-bit words at 16-bit boundaries)
        #                   2=legacy (16-bit words at 32-bit boundaries)
        self.pma_access = pma_access

        # PMA base is always base + 0x400 (immediately follows USB registers)
        self.pma_base = base + 0x400

        # High priority IRQ for isochronous/double-buffered
        self.irq_hp = 19

        # Endpoint states
        self.endpoints: List[EndpointState] = [EndpointState() for _ in range(self.NUM_ENDPOINTS)]

        # PMA memory (accessed as 16-bit words on 32-bit boundaries)
        self.pma = bytearray(self.PMA_SIZE)

        # Control registers
        self._cntr = (1 << USBCntrBits.FRES) | (1 << USBCntrBits.PDWN)  # Reset state
        self._istr = 0
        self._fnr = 0
        self._daddr = 0
        self._btable = 0

        # Endpoint registers (raw values)
        self._epr = [0] * self.NUM_ENDPOINTS

        # USB state
        self.connected = False
        self.address = 0
        self.suspended = False

        # RX/TX callbacks for external USB stack
        self.rx_callback: Optional[Callable[[int, bytes], None]] = None
        self.tx_callback: Optional[Callable[[int], bytes]] = None

        # CDC-specific state
        self.cdc_rx_buffer: bytearray = bytearray()
        self.cdc_tx_buffer: bytearray = bytearray()

        # USB timing model (Full-Speed only)
        self.timing = USBTimingModel(speed=USBSpeed.FULL_SPEED)

        # Data toggle tracking (per-EP)
        self.data_toggle = DataToggleTracker()

        # Coverage tracking
        self.coverage = USBCoverageTracker()

        # Uninitialized memory tracker for PMA
        self.pma_tracker = UninitializedMemoryTracker(
            "PMA", base=self.pma_base, size=self.PMA_SIZE
        )

        # USBIP firmware-in-the-loop state
        self.setup_packet = b''
        self._ep0_expected = 0
        self._ep0_event: Optional[asyncio.Event] = None
        self._ep0_response = b''
        self._ep0_accum = bytearray()
        self._ep0_max_pkt = 64

        self.log.info(f"USB Device initialized at 0x{base:08X} (PMA at 0x{self.pma_base:08X})")

    def contains(self, addr: int) -> bool:
        """Check if address is in USB or PMA region."""
        if self.base <= addr < self.base + self.size:
            return True
        if self.pma_base <= addr < self.pma_base + self.PMA_SIZE:
            return True
        return False

    def read(self, addr: int, size: int) -> Tuple[int, int]:
        """Read from USB registers or PMA."""
        offset = addr - self.base if addr >= self.base else addr - self.pma_base + 0x400
        self.coverage.record_register_access(offset, is_write=False)
        if self.pma_base <= addr < self.pma_base + self.PMA_SIZE:
            return self._read_pma(addr, size)
        return super().read(addr, size)

    def write(self, addr: int, size: int, value: int) -> int:
        """Write to USB registers or PMA."""
        offset = addr - self.base if addr >= self.base else addr - self.pma_base + 0x400
        self.coverage.record_register_access(offset, is_write=True, value=value)
        if self.pma_base <= addr < self.pma_base + self.PMA_SIZE:
            return self._write_pma(addr, size, value)
        return super().write(addr, size, value)

    def _pma_offset(self, cpu_offset: int) -> int:
        """Convert CPU address offset to PMA internal byte offset.

        PMA_ACCESS=1 (WB55/G0/U5): 16-bit words at 16-bit boundaries (direct).
        PMA_ACCESS=2 (F0/F1/F3):   16-bit words at 32-bit boundaries (packed).
        """
        if self.pma_access == 1:
            return cpu_offset  # Direct: each CPU byte maps 1:1 to PMA byte
        else:
            return (cpu_offset // 4) * 2  # Legacy: skip upper 16 bits of each 32-bit slot

    def _read_pma(self, addr: int, size: int) -> Tuple[int, int]:
        """Read from Packet Memory Area."""
        offset = addr - self.pma_base
        pma_off = self._pma_offset(offset)
        read_size = min(size, 2) if self.pma_access == 2 else size
        if pma_off + read_size <= len(self.pma):
            self.pma_tracker.check_read(self.pma_base + pma_off, read_size)
            value = int.from_bytes(self.pma[pma_off:pma_off + read_size], 'little')
            return (value, STATUS_OK)
        return (0, STATUS_OK)

    def _write_pma(self, addr: int, size: int, value: int) -> int:
        """Write to Packet Memory Area."""
        offset = addr - self.pma_base
        pma_off = self._pma_offset(offset)
        if self.pma_access == 1:
            # Direct mode: write size bytes
            write_size = min(size, len(self.pma) - pma_off) if pma_off < len(self.pma) else 0
            if write_size > 0:
                self.pma[pma_off:pma_off + write_size] = value.to_bytes(
                    write_size, 'little')[:write_size]
                self.pma_tracker.record_write(self.pma_base + pma_off, write_size)
        else:
            # Legacy mode: only lower 16 bits of 32-bit word
            if pma_off + 2 <= len(self.pma):
                self.pma[pma_off:pma_off + 2] = (value & 0xFFFF).to_bytes(2, 'little')
                self.pma_tracker.record_write(self.pma_base + pma_off, 2)
        return STATUS_OK

    def _read_reg(self, offset: int, size: int) -> int:
        """Read USB register."""
        if 0x00 <= offset <= 0x1C:
            # Endpoint registers
            ep = offset // 4
            return self._read_epr(ep)

        elif offset == USBDeviceReg.CNTR:
            return self._cntr

        elif offset == USBDeviceReg.ISTR:
            return self._istr

        elif offset == USBDeviceReg.FNR:
            # FNR: [10:0]=FN, [12:11]=LSOF, [13]=LCK, [14]=RXDM, [15]=RXDP
            fn = self.timing.frame_number & 0x7FF  # 11-bit frame number
            return fn | (1 << 13)  # LCK=1 (frame locked)

        elif offset == USBDeviceReg.DADDR:
            return self._daddr

        elif offset == USBDeviceReg.BTABLE:
            return self._btable

        _log_unhandled("STM32_USB", "READ", self.base + offset, size=size)
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        """Write USB register."""
        if 0x00 <= offset <= 0x1C:
            # Endpoint registers
            ep = offset // 4
            self._write_epr(ep, value)

        elif offset == USBDeviceReg.CNTR:
            self._write_cntr(value)

        elif offset == USBDeviceReg.ISTR:
            self._write_istr(value)

        elif offset == USBDeviceReg.DADDR:
            self._daddr = value & 0xFF
            if value & 0x80:  # EF bit - enable function
                self.address = value & 0x7F
                self.log.debug(f"USB address set to {self.address}")

        elif offset == USBDeviceReg.BTABLE:
            self._btable = value & 0xFFF8  # Must be 8-byte aligned

        else:
            _log_unhandled("STM32_USB", "WRITE", self.base + offset, value=value, size=size)

    def _read_epr(self, ep: int) -> int:
        """Read endpoint register."""
        if ep >= self.NUM_ENDPOINTS:
            return 0

        state = self.endpoints[ep]
        value = self._epr[ep]

        # Update toggle bits from state
        value &= ~0x7070  # Clear status bits
        value |= (state.tx_status << 4) | (state.rx_status << 12)

        # CTR bits
        if state.ctr_rx:
            value |= (1 << 15)
        if state.ctr_tx:
            value |= (1 << 7)

        # SETUP bit (read-only, set by hardware on SETUP packet reception)
        if state.setup:
            value |= (1 << 11)

        return value

    def _write_epr(self, ep: int, value: int):
        """
        Write endpoint register.

        EPnR has complex toggle semantics:
        - Bits 0-3 (EA): Endpoint address (read/write)
        - Bits 4-5 (STAT_TX): TX status (toggle on write 1)
        - Bit 6 (DTOG_TX): TX data toggle (toggle on write 1)
        - Bit 7 (CTR_TX): Correct TX (write 0 to clear, write 1 no effect)
        - Bit 8 (EP_KIND): Endpoint kind
        - Bits 9-10 (EP_TYPE): Endpoint type
        - Bit 11 (SETUP): Setup transaction completed
        - Bits 12-13 (STAT_RX): RX status (toggle on write 1)
        - Bit 14 (DTOG_RX): RX data toggle (toggle on write 1)
        - Bit 15 (CTR_RX): Correct RX (write 0 to clear, write 1 no effect)
        """
        if ep >= self.NUM_ENDPOINTS:
            return

        state = self.endpoints[ep]
        old = self._epr[ep]

        # Endpoint address (direct write)
        new = (old & ~0x0F) | (value & 0x0F)

        # EP_TYPE and EP_KIND (direct write)
        new = (new & ~0x0700) | (value & 0x0700)
        state.type = (value >> 9) & 0x03

        # STAT_TX (toggle)
        tx_toggle = (value >> 4) & 0x03
        state.tx_status ^= tx_toggle

        # DTOG_TX (toggle on write 1)
        if value & (1 << 6):
            new ^= (1 << 6)

        # CTR_TX (write 0 to clear)
        if not (value & (1 << 7)):
            state.ctr_tx = False

        # STAT_RX (toggle)
        rx_toggle = (value >> 12) & 0x03
        state.rx_status ^= rx_toggle

        # DTOG_RX (toggle on write 1)
        if value & (1 << 14):
            new ^= (1 << 14)

        # CTR_RX (write 0 to clear)
        if not (value & (1 << 15)):
            state.ctr_rx = False
            state.setup = False  # SETUP consumed when firmware clears CTR_RX

        self._epr[ep] = new
        self.log.debug(f"EP{ep}: STAT_TX={state.tx_status}, STAT_RX={state.rx_status}")

        # USBIP hook: detect when firmware arms EP0 TX (STAT_TX -> VALID)
        if ep == 0 and state.tx_status == EPStatBits.VALID and self._ep0_event:
            self._handle_ep0_tx_ready()

    def _write_cntr(self, value: int):
        """Write USB_CNTR register."""
        old = self._cntr
        self._cntr = value

        # Check for reset release
        if (old & (1 << USBCntrBits.FRES)) and not (value & (1 << USBCntrBits.FRES)):
            self.log.debug("USB reset released")
            self._reset_endpoints()

        # Check for power up
        if (old & (1 << USBCntrBits.PDWN)) and not (value & (1 << USBCntrBits.PDWN)):
            self.log.debug("USB powered up")

    def _write_istr(self, value: int):
        """
        Write USB_ISTR register.

        Interrupt flags are cleared by writing 0, writing 1 has no effect.
        """
        # Only clear bits that are written as 0
        clear_mask = ~value & 0xFF80  # Only interrupt flags (bits 7-15)
        self._istr &= ~clear_mask

    def _reset_endpoints(self):
        """Reset all endpoints to default state."""
        for i, ep in enumerate(self.endpoints):
            ep.tx_status = EPStatBits.DISABLED
            ep.rx_status = EPStatBits.DISABLED
            ep.ctr_tx = False
            ep.ctr_rx = False
            self._epr[i] = 0

    def reset(self):
        """Reset USB peripheral."""
        super().reset()
        self._cntr = (1 << USBCntrBits.FRES) | (1 << USBCntrBits.PDWN)
        self._istr = 0
        self._fnr = 0
        self._daddr = 0
        self._btable = 0
        self._reset_endpoints()
        self.pma = bytearray(self.PMA_SIZE)
        self.pma_tracker.reset()
        self.connected = False
        self.address = 0
        self.suspended = False
        # Reset USBIP state
        self.setup_packet = b''
        self._ep0_expected = 0
        self._ep0_event = None
        self._ep0_response = b''
        self._ep0_accum = bytearray()

    # =========================================================================
    # USB Transaction Simulation
    # =========================================================================

    def simulate_reset(self):
        """Simulate USB bus reset from host."""
        self._istr |= (1 << USBIstrBits.RESET)
        self.data_toggle.reset_all()
        self.timing.reset()
        self.coverage.record_event("bus_reset")
        if self._cntr & (1 << USBCntrBits.RESETM):
            self.trigger_irq()
        self.log.info("USB bus reset")

    def simulate_sof(self, frame: int = 0):
        """Simulate Start of Frame."""
        if frame:
            self._fnr = (self._fnr & ~0x07FF) | (frame & 0x07FF)
        else:
            # Use timing model for frame number
            self.timing.advance(self.timing.frame_interval)
            self._fnr = (self._fnr & ~0x07FF) | (self.timing.frame_number & 0x7FF)
        self._istr |= (1 << USBIstrBits.SOF)
        if self._cntr & (1 << USBCntrBits.SOFM):
            self.trigger_irq()

    def send_to_endpoint(self, ep: int, data: bytes) -> bool:
        """
        Send data to an endpoint (simulating host OUT transaction).

        Args:
            ep: Endpoint number (0-7)
            data: Data to send

        Returns:
            True if data was accepted
        """
        if ep >= self.NUM_ENDPOINTS:
            return False

        state = self.endpoints[ep]

        # Check if endpoint is ready to receive
        if state.rx_status != EPStatBits.VALID:
            self.log.debug(f"EP{ep} RX not valid (status={state.rx_status})")
            return False

        # Get RX buffer address from buffer table
        btable_entry = self._btable + ep * 8 + 4  # RX address offset
        rx_addr = self._read_pma_word(btable_entry)
        rx_count_reg = self._read_pma_word(btable_entry + 2)

        # Max size from COUNT_RX register
        bl_size = (rx_count_reg >> 15) & 1
        if bl_size:
            max_size = ((rx_count_reg >> 10) & 0x1F) * 32
        else:
            max_size = ((rx_count_reg >> 10) & 0x1F) * 2

        if len(data) > max_size:
            self.log.warning(f"EP{ep}: Data too large ({len(data)} > {max_size})")
            data = data[:max_size]

        # Copy data to PMA
        self._write_pma_buffer(rx_addr, data)

        # Update COUNT_RX with received size
        new_count = (rx_count_reg & 0xFC00) | len(data)
        self._write_pma_word(btable_entry + 2, new_count)

        # Set CTR_RX and trigger interrupt
        state.ctr_rx = True
        state.rx_status = EPStatBits.NAK  # NAK until firmware re-enables

        self._istr = (self._istr & ~0x0F) | ep  # Set EP_ID
        self._istr |= (1 << USBIstrBits.DIR)  # DIR=1 for OUT (host to device)
        self._istr |= (1 << USBIstrBits.CTR)

        if self._cntr & (1 << USBCntrBits.CTRM):
            self.trigger_irq()

        # Flip data toggle (hardware handles this on STM32F1)
        self.data_toggle.flip(ep, direction_in=False)
        self.coverage.record_event("out_transfer", {'ep': ep, 'size': len(data)})
        self.log.debug(f"EP{ep}: Received {len(data)} bytes")
        return True

    def receive_from_endpoint(self, ep: int) -> Optional[bytes]:
        """
        Receive data from an endpoint (simulating host IN transaction).

        Args:
            ep: Endpoint number (0-7)

        Returns:
            Data from endpoint, or None if not ready
        """
        if ep >= self.NUM_ENDPOINTS:
            return None

        state = self.endpoints[ep]

        # Check if endpoint has data to send
        if state.tx_status != EPStatBits.VALID:
            return None

        # Get TX buffer address from buffer table
        btable_entry = self._btable + ep * 8
        tx_addr = self._read_pma_word(btable_entry)
        tx_count = self._read_pma_word(btable_entry + 2) & 0x3FF

        # Read data from PMA
        data = self._read_pma_buffer(tx_addr, tx_count)

        # Set CTR_TX and trigger interrupt
        state.ctr_tx = True
        state.tx_status = EPStatBits.NAK

        self._istr = (self._istr & ~0x0F) | ep
        self._istr &= ~(1 << USBIstrBits.DIR)  # DIR=0 for IN (device to host)
        self._istr |= (1 << USBIstrBits.CTR)

        if self._cntr & (1 << USBCntrBits.CTRM):
            self.trigger_irq()

        # Flip data toggle (hardware handles this on STM32F1)
        self.data_toggle.flip(ep, direction_in=True)
        self.coverage.record_event("in_transfer", {'ep': ep, 'size': len(data)})
        self.log.debug(f"EP{ep}: Sent {len(data)} bytes")
        return data

    def _read_pma_word(self, offset: int) -> int:
        """Read 16-bit word from PMA offset."""
        if offset + 2 <= len(self.pma):
            return int.from_bytes(self.pma[offset:offset + 2], 'little')
        return 0

    def _write_pma_word(self, offset: int, value: int):
        """Write 16-bit word to PMA offset."""
        if offset + 2 <= len(self.pma):
            self.pma[offset:offset + 2] = (value & 0xFFFF).to_bytes(2, 'little')

    def _read_pma_buffer(self, offset: int, size: int) -> bytes:
        """Read buffer from PMA."""
        if offset + size <= len(self.pma):
            self.pma_tracker.check_read(self.pma_base + offset, size)
            return bytes(self.pma[offset:offset + size])
        return b''

    def _write_pma_buffer(self, offset: int, data: bytes):
        """Write buffer to PMA."""
        if offset + len(data) <= len(self.pma):
            self.pma[offset:offset + len(data)] = data
            self.pma_tracker.record_write(self.pma_base + offset, len(data))

    # =========================================================================
    # USBIP Firmware-in-the-Loop Injection
    # =========================================================================

    def is_ready(self) -> bool:
        """Check if firmware has completed USB initialization.

        Returns True when: PDWN cleared, FRES cleared, CTRM enabled.
        """
        pdwn = bool(self._cntr & (1 << USBCntrBits.PDWN))
        fres = bool(self._cntr & (1 << USBCntrBits.FRES))
        ctrm = bool(self._cntr & (1 << USBCntrBits.CTRM))
        return not pdwn and not fres and ctrm

    def inject_vbus(self, connected: bool = True):
        """Inject VBUS state change.

        PMA USB has no hardware VBUS detection (unlike DWC2 OTG).
        Just track the connected state.
        """
        self.connected = connected
        self.log.info(f"VBUS {'asserted' if connected else 'deasserted'}")

    def inject_usbrst(self):
        """Inject USB bus reset. Delegates to simulate_reset()."""
        self.simulate_reset()

    def inject_enumdne(self):
        """Inject enumeration done (no-op for PMA USB).

        PMA USB has no ENUMDNE event. After bus reset, firmware enables
        the device by setting DADDR.EF. Speed is always Full Speed.
        """
        self.log.debug("ENUMDNE not applicable for PMA USB (firmware sets DADDR.EF)")

    def inject_setup_packet(self, setup_data: bytes):
        """Inject a USB SETUP packet into EP0 RX path.

        Writes SETUP data to EP0 RX PMA buffer (from BTABLE), sets
        SETUP + CTR_RX in EP0R state, and triggers CTR interrupt.
        """
        assert len(setup_data) == 8, "SETUP packet must be 8 bytes"

        # Validate BTABLE is initialized
        if self._btable == 0 and not any(
                self.pma[0:16]):
            self.log.warning("BTABLE not initialized (still 0 with empty PMA) -- "
                             "firmware may not have completed USB init")

        # Read EP0 RX buffer address from BTABLE
        btable_entry = self._btable + 4  # EP0 RX addr offset
        rx_addr = self._read_pma_word(btable_entry)
        self.log.debug(f"BTABLE=0x{self._btable:04x}, EP0 RX addr=0x{rx_addr:04x}")

        # Write SETUP data to PMA
        self._write_pma_buffer(rx_addr, setup_data)

        # Update COUNT_RX with 8 bytes received
        rx_count_reg = self._read_pma_word(btable_entry + 2)
        self._write_pma_word(btable_entry + 2, (rx_count_reg & 0xFC00) | 8)

        # Set EP0R: SETUP=1, CTR_RX=1, RX status -> NAK
        state = self.endpoints[0]
        state.setup = True
        state.ctr_rx = True
        state.rx_status = EPStatBits.NAK

        # Set ISTR: CTR=1, DIR=1 (OUT), EP_ID=0
        self._istr = (self._istr & ~0x001F) | (1 << USBIstrBits.DIR)
        self._istr |= (1 << USBIstrBits.CTR)

        # Track SETUP for wait_ep0_response
        self.setup_packet = setup_data
        self._ep0_expected = setup_data[6] | (setup_data[7] << 8)

        self.log.info(f"Injected SETUP: {setup_data.hex()} wLen={self._ep0_expected}")
        ctrm = bool(self._cntr & (1 << USBCntrBits.CTRM))
        self.log.debug(f"CNTR=0x{self._cntr:04x} CTRM={ctrm} ISTR=0x{self._istr:04x} "
                       f"DADDR=0x{self._daddr:02x}")
        if ctrm:
            self.trigger_irq()
        else:
            self.log.warning("CNTR.CTRM not set -- CTR interrupt will not fire!")

    def _handle_ep0_tx_ready(self):
        """EP0 TX armed by firmware -- read response from PMA, simulate IN transfer.

        Called from _write_epr() hook when EP0 STAT_TX toggles to VALID
        while wait_ep0_response() is waiting. Supports multi-packet by
        accumulating data across XFRC events.
        """
        state = self.endpoints[0]

        # Read TX buffer from BTABLE
        btable_entry = self._btable
        tx_addr = self._read_pma_word(btable_entry)
        tx_count = self._read_pma_word(btable_entry + 2) & 0x3FF
        pkt_data = self._read_pma_buffer(tx_addr, tx_count)

        # Accumulate for multi-packet
        self._ep0_accum.extend(pkt_data)
        total = len(self._ep0_accum)
        self.log.info(f"EP0 IN packet: {len(pkt_data)}B (total={total}/{self._ep0_expected})")

        # Simulate IN transfer completing: CTR_TX=1, STAT_TX -> NAK
        state.ctr_tx = True
        state.tx_status = EPStatBits.NAK

        self._istr = (self._istr & ~0x001F) | (1 << USBIstrBits.DIR)
        self._istr |= (1 << USBIstrBits.CTR)
        if self._cntr & (1 << USBCntrBits.CTRM):
            self.trigger_irq()

        # Check completion: short packet or enough data
        if len(pkt_data) < self._ep0_max_pkt or total >= self._ep0_expected:
            self._ep0_response = bytes(self._ep0_accum[:self._ep0_expected])
            self.log.info(f"EP0 IN complete: {len(self._ep0_response)} bytes")
            self._ep0_event.set()

    async def wait_ep0_response(self, timeout: float = 5.0) -> bytes:
        """Wait for firmware to complete EP0 IN transfer.

        Called by USBIPServer for control IN transfers. Creates an
        asyncio.Event and waits for _handle_ep0_tx_ready() to signal it.
        """
        self._ep0_event = asyncio.Event()
        self._ep0_response = b''
        self._ep0_accum = bytearray()
        try:
            await asyncio.wait_for(self._ep0_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.log.warning("EP0 response timeout (firmware did not respond)")
            if self._ep0_accum:
                self._ep0_response = bytes(self._ep0_accum)
        finally:
            self._ep0_event = None
        return self._ep0_response

    def inject_out_data(self, ep: int, data: bytes):
        """Inject OUT data into an endpoint.

        Used for control OUT data phase (e.g., SET_LINE_CODING) and
        STATUS OUT ZLP after control IN transfers.
        """
        if len(data) == 0:
            # ZLP -- just set CTR_RX to signal transfer complete
            state = self.endpoints[ep]
            state.ctr_rx = True
            state.rx_status = EPStatBits.NAK
            self._istr = (self._istr & ~0x0F) | ep
            self._istr |= (1 << USBIstrBits.CTR)
            if self._cntr & (1 << USBCntrBits.CTRM):
                self.trigger_irq()
        else:
            self.send_to_endpoint(ep, data)
        self.log.info(f"Injected OUT data EP{ep}: {len(data)} bytes")

    # =========================================================================
    # CDC ACM Support (Virtual COM Port)
    # =========================================================================

    def cdc_send(self, data: bytes) -> bool:
        """
        Send data via CDC (simulating serial data from host).

        This sends data to the CDC data OUT endpoint (typically EP1 or EP3).
        """
        # Common CDC data endpoint is EP1 OUT or EP3 OUT
        for ep in [1, 3]:
            if self.endpoints[ep].type == EPTypeBits.BULK:
                return self.send_to_endpoint(ep, data)
        return False

    def cdc_receive(self) -> Optional[bytes]:
        """
        Receive data from CDC (simulating serial data to host).

        This receives data from the CDC data IN endpoint.
        """
        for ep in [1, 2]:
            if self.endpoints[ep].type == EPTypeBits.BULK:
                return self.receive_from_endpoint(ep | 0x80)
        return None


class STM32USBDeviceWithPMA(STM32Peripheral):
    """
    Combined USB Device + PMA peripheral.

    This wrapper makes it easier to register both the USB registers
    and the PMA as a single peripheral.
    """

    def __init__(self, irq: int = 20, irq_hp: int = 19):
        # Create with extended range covering both USB and PMA
        super().__init__(
            "USB_PMA",
            base=0x40005C00,
            size=0x800,  # Covers 0x40005C00 to 0x400063FF
            irq=irq
        )
        self.usb = STM32USBDevice(irq=irq)
        self.irq_hp = irq_hp

    def contains(self, addr: int) -> bool:
        return self.usb.contains(addr)

    def read(self, addr: int, size: int) -> Tuple[int, int]:
        return self.usb.read(addr, size)

    def write(self, addr: int, size: int, value: int) -> int:
        return self.usb.write(addr, size, value)

    def reset(self):
        self.usb.reset()

    # Forward commonly used methods
    def simulate_reset(self):
        self.usb.simulate_reset()

    def send_to_endpoint(self, ep: int, data: bytes) -> bool:
        return self.usb.send_to_endpoint(ep, data)

    def receive_from_endpoint(self, ep: int) -> Optional[bytes]:
        return self.usb.receive_from_endpoint(ep)

    def cdc_send(self, data: bytes) -> bool:
        return self.usb.cdc_send(data)

    def cdc_receive(self) -> Optional[bytes]:
        return self.usb.cdc_receive()
