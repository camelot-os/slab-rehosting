"""
USB OTG Emulation with USBIP Support

Provides full USB OTG (On-The-Go) emulation supporting both:
- Device Mode: Emulator acts as USB device, host PC enumerates it via USBIP
- Host Mode: Emulator acts as USB host, enumerates devices from host via USBIP

Architecture:
    ┌─────────────────────────────────────────────────────────────┐
    │                    Host PC                                   │
    │  ┌──────────────┐                    ┌──────────────┐       │
    │  │ Real USB     │                    │ usbip client │       │
    │  │ Device       │                    │ (imports     │       │
    │  └──────┬───────┘                    │  emulated    │       │
    │         │                            │  device)     │       │
    │         ▼                            └──────▲───────┘       │
    │  ┌──────────────┐                           │               │
    │  │ usbipd       │                           │               │
    │  │ (exports     │                           │               │
    │  │  real device)│                           │               │
    │  └──────┬───────┘                           │               │
    └─────────┼───────────────────────────────────┼───────────────┘
              │ TCP/IP                            │ TCP/IP
              ▼                                   │
    ┌─────────────────────────────────────────────────────────────┐
    │                  Slab Emulator                              │
    │  ┌──────────────┐                    ┌──────────────┐       │
    │  │ USBIP Client │                    │ USBIP Server │       │
    │  │ (imports     │                    │ (exports     │       │
    │  │  real device)│                    │  emulated    │       │
    │  └──────┬───────┘                    │  device)     │       │
    │         │                            └──────▲───────┘       │
    │         ▼                                   │               │
    │  ┌──────────────────────────────────────────┴───────┐       │
    │  │              USB OTG Controller                   │       │
    │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐          │       │
    │  │  │ ID Pin  │  │ VBUS    │  │ Mode    │          │       │
    │  │  │ Detect  │  │ Control │  │ Switch  │          │       │
    │  │  └─────────┘  └─────────┘  └─────────┘          │       │
    │  └──────────────────────────────────────────────────┘       │
    │                         │                                    │
    │                         ▼                                    │
    │  ┌──────────────────────────────────────────────────┐       │
    │  │              Emulated Firmware                    │       │
    │  │  (Uses USB in host or device mode)               │       │
    │  └──────────────────────────────────────────────────┘       │
    └─────────────────────────────────────────────────────────────┘

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 Twisted Wires Security Lab
"""

import socket
import struct
import threading
import time
import logging
from typing import Optional, Dict, List, Callable, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from abc import ABC, abstractmethod

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from slab_peripherals.usb_controller import (
    USBControllerBase, USBTimingModel, USBCoverageTracker,
    EP0ControlFSM, EP0Phase, SetupPacket,
    DataToggleTracker, DMAValidator, EndpointState,
    USBSpeed as BaseUSBSpeed, USBEPType, USBDirection as BaseUSBDirection,
)
from slab_peripherals.bus_logger import log_unhandled as _log_unhandled_access

logger = logging.getLogger(__name__)


class OTGMode(Enum):
    """USB OTG operating mode."""
    IDLE = auto()
    HOST = auto()
    DEVICE = auto()
    SRP = auto()  # Session Request Protocol
    HNP = auto()  # Host Negotiation Protocol


class USBSpeed(Enum):
    """USB speed modes."""
    LOW = 1      # 1.5 Mbps
    FULL = 2     # 12 Mbps
    HIGH = 3     # 480 Mbps
    SUPER = 4    # 5 Gbps (USB 3.0)


class USBDirection(IntEnum):
    """USB transfer direction."""
    OUT = 0  # Host to Device
    IN = 1   # Device to Host


class USBTransferType(IntEnum):
    """USB transfer types."""
    CONTROL = 0
    ISOCHRONOUS = 1
    BULK = 2
    INTERRUPT = 3


@dataclass
class USBEndpoint:
    """USB endpoint descriptor."""
    address: int  # Endpoint number + direction
    attributes: int  # Transfer type
    max_packet_size: int
    interval: int

    @property
    def number(self) -> int:
        return self.address & 0x0F

    @property
    def direction(self) -> USBDirection:
        return USBDirection((self.address >> 7) & 1)

    @property
    def transfer_type(self) -> USBTransferType:
        return USBTransferType(self.attributes & 0x03)


@dataclass
class USBDevice:
    """USB device representation."""
    vendor_id: int
    product_id: int
    device_class: int
    device_subclass: int
    device_protocol: int
    manufacturer: str = ""
    product: str = ""
    serial: str = ""
    speed: USBSpeed = USBSpeed.HIGH
    endpoints: List[USBEndpoint] = field(default_factory=list)
    configurations: List[bytes] = field(default_factory=list)

    # Device state
    address: int = 0
    configuration: int = 0
    interface: int = 0
    alternate: int = 0

    def get_device_descriptor(self) -> bytes:
        """Generate USB device descriptor (18 bytes)."""
        import struct
        return struct.pack('<BBHBBBBHHHBBBB',
            18,                     # bLength
            1,                      # bDescriptorType = DEVICE
            0x0200,                 # bcdUSB = USB 2.0
            self.device_class,      # bDeviceClass
            self.device_subclass,   # bDeviceSubClass
            self.device_protocol,   # bDeviceProtocol
            64,                     # bMaxPacketSize0
            self.vendor_id,         # idVendor
            self.product_id,        # idProduct
            0x0100,                 # bcdDevice
            1,                      # iManufacturer string index
            2,                      # iProduct string index
            3,                      # iSerialNumber string index
            len(self.configurations) or 1  # bNumConfigurations
        )


# =============================================================================
# USBIP Protocol Constants (Linux kernel usbip)
# =============================================================================

USBIP_VERSION = 0x0111

# Operation codes
class USBIPOp(IntEnum):
    REQ_DEVLIST = 0x8005
    REP_DEVLIST = 0x0005
    REQ_IMPORT = 0x8003
    REP_IMPORT = 0x0003
    CMD_SUBMIT = 0x0001
    RET_SUBMIT = 0x0003
    CMD_UNLINK = 0x0002
    RET_UNLINK = 0x0004


# Standard USB request types
class USBRequest(IntEnum):
    GET_STATUS = 0x00
    CLEAR_FEATURE = 0x01
    SET_FEATURE = 0x03
    SET_ADDRESS = 0x05
    GET_DESCRIPTOR = 0x06
    SET_DESCRIPTOR = 0x07
    GET_CONFIGURATION = 0x08
    SET_CONFIGURATION = 0x09
    GET_INTERFACE = 0x0A
    SET_INTERFACE = 0x0B


class DescriptorType(IntEnum):
    DEVICE = 1
    CONFIGURATION = 2
    STRING = 3
    INTERFACE = 4
    ENDPOINT = 5
    DEVICE_QUALIFIER = 6
    OTHER_SPEED_CONFIG = 7
    INTERFACE_POWER = 8


# =============================================================================
# USB OTG Controller Emulation
# =============================================================================

class OTGController:
    """
    USB OTG Controller emulation.

    Emulates a DWC2-style OTG controller with:
    - ID pin detection for role determination
    - VBUS control for power management
    - Mode switching between host and device
    - Session Request Protocol (SRP)
    - Host Negotiation Protocol (HNP)
    """

    # Register offsets (DWC2-compatible)
    GOTGCTL = 0x000   # OTG Control and Status
    GOTGINT = 0x004   # OTG Interrupt
    GAHBCFG = 0x008   # AHB Configuration
    GUSBCFG = 0x00C   # USB Configuration
    GRSTCTL = 0x010   # Reset Control
    GINTSTS = 0x014   # Interrupt Status
    GINTMSK = 0x018   # Interrupt Mask
    GRXSTSR = 0x01C   # Receive Status Read
    GRXSTSP = 0x020   # Receive Status Pop
    GRXFSIZ = 0x024   # Receive FIFO Size
    GNPTXFSIZ = 0x028 # Non-periodic TX FIFO Size
    GHWCFG1 = 0x044   # Hardware Config 1
    GHWCFG2 = 0x048   # Hardware Config 2
    GHWCFG3 = 0x04C   # Hardware Config 3
    GHWCFG4 = 0x050   # Hardware Config 4

    # Device mode registers
    DCFG = 0x800      # Device Configuration
    DCTL = 0x804      # Device Control
    DSTS = 0x808      # Device Status

    # Host mode registers
    HCFG = 0x400      # Host Configuration
    HFIR = 0x404      # Host Frame Interval
    HFNUM = 0x408     # Host Frame Number
    HPTXSTS = 0x410   # Host Periodic TX Status

    def __init__(self, base_address: int = 0x50000000):
        self.base = base_address
        self.mode = OTGMode.DEVICE  # Default to device mode
        self.speed = USBSpeed.HIGH

        # Registers
        self.regs: Dict[int, int] = {
            self.GOTGCTL: 0x00010000,  # ID pin high (device)
            self.GUSBCFG: 0x00001400,  # Default config
            self.GAHBCFG: 0x00000000,
            self.GINTSTS: 0x00000000,
            self.GINTMSK: 0x00000000,
            self.GHWCFG1: 0x00000000,
            self.GHWCFG2: 0x228DDD50,  # HS capable
            self.GHWCFG3: 0x0FF000E8,
            self.GHWCFG4: 0x1FF00020,
            self.DCFG: 0x00000000,
            self.DCTL: 0x00000000,
            self.DSTS: 0x00000000,
            self.HCFG: 0x00000000,
        }

        # Callbacks
        self.on_mode_change: Optional[Callable[[OTGMode], None]] = None
        self.on_connect: Optional[Callable[[bool], None]] = None
        self.on_reset: Optional[Callable[[], None]] = None

        # USBIP interfaces
        self.usbip_server: Optional['USBIPServer'] = None
        self.usbip_client: Optional['USBIPClient'] = None

        # Connected device (in host mode)
        self.connected_device: Optional[USBDevice] = None

        # Device descriptors (in device mode)
        self.device_desc: Optional[USBDevice] = None

    def read_reg(self, offset: int) -> int:
        """Read OTG register."""
        if offset in self.regs:
            return self.regs[offset]
        return 0

    def write_reg(self, offset: int, value: int):
        """Write OTG register."""
        old_value = self.regs.get(offset, 0)
        self.regs[offset] = value

        # Handle special registers
        if offset == self.GRSTCTL:
            self._handle_reset(value)
        elif offset == self.GUSBCFG:
            self._handle_config(value)
        elif offset == self.GOTGCTL:
            self._handle_otg_control(value)

    def _handle_reset(self, value: int):
        """Handle reset register write."""
        if value & 1:  # Core soft reset
            logger.info("OTG: Core soft reset")
            if self.on_reset:
                self.on_reset()
            # Clear reset bit
            self.regs[self.GRSTCTL] &= ~1

    def _handle_config(self, value: int):
        """Handle USB config register write."""
        force_host = (value >> 29) & 1
        force_device = (value >> 30) & 1

        if force_host:
            self.set_mode(OTGMode.HOST)
        elif force_device:
            self.set_mode(OTGMode.DEVICE)

    def _handle_otg_control(self, value: int):
        """Handle OTG control register write."""
        # Session request
        if value & (1 << 1):
            logger.info("OTG: Session request")

        # HNP request
        if value & (1 << 9):
            logger.info("OTG: HNP request")

    def set_mode(self, mode: OTGMode):
        """Set OTG operating mode."""
        if mode == self.mode:
            return

        old_mode = self.mode
        self.mode = mode

        logger.info(f"OTG: Mode change {old_mode.name} -> {mode.name}")

        # Update registers
        if mode == OTGMode.HOST:
            self.regs[self.GOTGCTL] &= ~(1 << 16)  # Clear ID (host)
            self.regs[self.GINTSTS] |= (1 << 0)    # Current mode = host
        elif mode == OTGMode.DEVICE:
            self.regs[self.GOTGCTL] |= (1 << 16)   # Set ID (device)
            self.regs[self.GINTSTS] &= ~(1 << 0)   # Current mode = device

        if self.on_mode_change:
            self.on_mode_change(mode)

    def set_id_pin(self, is_device: bool):
        """Set ID pin state (pulled low = host, floating = device)."""
        if is_device:
            self.regs[self.GOTGCTL] |= (1 << 16)
            self.set_mode(OTGMode.DEVICE)
        else:
            self.regs[self.GOTGCTL] &= ~(1 << 16)
            self.set_mode(OTGMode.HOST)

    def start_host_mode(self, usbip_host: str = "localhost", usbip_port: int = 3240):
        """
        Start host mode - connect to USBIP server to enumerate real devices.
        """
        self.set_mode(OTGMode.HOST)

        self.usbip_client = USBIPClient(usbip_host, usbip_port)
        self.usbip_client.on_device_connected = self._on_host_device_connected

        try:
            devices = self.usbip_client.list_devices()
            logger.info(f"OTG Host: Found {len(devices)} devices")
            return devices
        except Exception as e:
            logger.error(f"OTG Host: Failed to list devices: {e}")
            return []

    def start_device_mode(self, device: USBDevice, port: int = 3240):
        """
        Start device mode - export virtual device via USBIP server.
        """
        self.set_mode(OTGMode.DEVICE)
        self.device_desc = device

        self.usbip_server = USBIPServer(device, port)
        self.usbip_server.on_enumerated = self._on_device_enumerated

        self.usbip_server.start()
        logger.info(f"OTG Device: USBIP server started on port {port}")

    def _on_host_device_connected(self, device: USBDevice):
        """Callback when device is connected in host mode."""
        self.connected_device = device
        logger.info(f"OTG Host: Device connected - {device.product}")

        if self.on_connect:
            self.on_connect(True)

    def _on_device_enumerated(self):
        """Callback when we're enumerated by host in device mode."""
        logger.info("OTG Device: Enumerated by host")

        if self.on_connect:
            self.on_connect(True)

    def stop(self):
        """Stop all USBIP connections."""
        if self.usbip_server:
            self.usbip_server.stop()
            self.usbip_server = None

        if self.usbip_client:
            self.usbip_client.disconnect()
            self.usbip_client = None

        self.set_mode(OTGMode.IDLE)


# =============================================================================
# DWC2 Device Mode Controller (per Synopsys DWC2 OTG v3.30a Datasheet)
# =============================================================================

class DWC2DeviceController(USBControllerBase):
    """
    DWC2 OTG Device Mode controller emulation per Synopsys DWC2 v3.30a.

    Implements:
    - Global registers (GOTGCTL through GHWCFG4)
    - Device mode registers (DCFG, DCTL, DSTS)
    - Device endpoint mask/interrupt aggregation (DIEPMSK, DOEPMSK, DAINT, DAINTMSK)
    - Per-endpoint registers (DIEPCTLn, DOEPCTLn, DIEPTSIZn, DOEPTSIZn, DIEPINTn, DOEPINTn)
    - DMA address registers (DIEPDMAn, DOEPDMAn)
    - FIFO sizing (GRXFSIZ, GNPTXFSIZ, DIEPTXFn)
    - Interrupt model (GINTSTS/GINTMSK with proper bit mapping)
    - Transfer size decrement with XferCompl generation
    - EP0 control transfer FSM with SUPCnt=3
    - Core soft reset, FIFO flush, global NAK handling
    """

    # Number of device endpoints (per DWC2 config - typically 4-6)
    MAX_EPS = 6

    # =========================================================================
    # Register Offsets - Global (0x000 - 0x0FF)
    # =========================================================================
    GOTGCTL   = 0x000   # OTG Control and Status
    GOTGINT   = 0x004   # OTG Interrupt
    GAHBCFG   = 0x008   # AHB Configuration
    GUSBCFG   = 0x00C   # USB Configuration
    GRSTCTL   = 0x010   # Reset Control
    GINTSTS   = 0x014   # Core Interrupt Status
    GINTMSK   = 0x018   # Core Interrupt Mask
    GRXSTSR   = 0x01C   # Receive Status Read (debug)
    GRXSTSP   = 0x020   # Receive Status Pop
    GRXFSIZ   = 0x024   # Receive FIFO Size
    GNPTXFSIZ = 0x028   # Non-periodic TX FIFO Size / EP0 TX FIFO Size
    GNPTXSTS  = 0x02C   # Non-periodic TX FIFO Status
    GHWCFG1   = 0x044   # Hardware Config 1
    GHWCFG2   = 0x048   # Hardware Config 2
    GHWCFG3   = 0x04C   # Hardware Config 3
    GHWCFG4   = 0x050   # Hardware Config 4
    GLPMCFG   = 0x054   # Core LPM Configuration
    GDFIFOCFG = 0x05C   # Global DFIFO Configuration

    # Periodic TX FIFO size registers (0x100 + n*4, n=1..15)
    DIEPTXF_BASE = 0x100

    # =========================================================================
    # Register Offsets - Device Mode (0x800 - 0x8FF)
    # =========================================================================
    DCFG      = 0x800   # Device Configuration
    DCTL      = 0x804   # Device Control
    DSTS      = 0x808   # Device Status (read-only)
    DIEPMSK   = 0x810   # Device IN Endpoint Common Interrupt Mask
    DOEPMSK   = 0x814   # Device OUT Endpoint Common Interrupt Mask
    DAINT     = 0x818   # Device All Endpoints Interrupt (read-only)
    DAINTMSK  = 0x81C   # Device All Endpoints Interrupt Mask
    DVBUSDIS  = 0x828   # Device VBUS Discharge Time
    DVBUSPULSE = 0x82C  # Device VBUS Pulsing Time
    DTHRCTL   = 0x830   # Device Threshold Control
    DIEPEMPMSK = 0x834  # Device IN Endpoint FIFO Empty Interrupt Mask

    # =========================================================================
    # Register Offsets - Device Endpoints (0x900 - 0xBFF)
    # Per-EP stride = 0x20, max 16 EPs each direction
    # =========================================================================
    # IN Endpoints (0x900 + n*0x20)
    DIEPCTL_BASE  = 0x900   # DIEPCTLn: Device IN Endpoint n Control
    DIEPINT_BASE  = 0x908   # DIEPINTn: Device IN Endpoint n Interrupt
    DIEPTSIZ_BASE = 0x910   # DIEPTSIZn: Device IN Endpoint n Transfer Size
    DIEPDMA_BASE  = 0x914   # DIEPDMAn: Device IN Endpoint n DMA Address

    # OUT Endpoints (0xB00 + n*0x20)
    DOEPCTL_BASE  = 0xB00   # DOEPCTLn: Device OUT Endpoint n Control
    DOEPINT_BASE  = 0xB08   # DOEPINTn: Device OUT Endpoint n Interrupt
    DOEPTSIZ_BASE = 0xB10   # DOEPTSIZn: Device OUT Endpoint n Transfer Size
    DOEPDMA_BASE  = 0xB14   # DOEPDMAn: Device OUT Endpoint n DMA Address

    EP_STRIDE = 0x20

    # =========================================================================
    # GINTSTS Bit Definitions
    # =========================================================================
    GINTSTS_CURMOD      = (1 << 0)   # Current Mode (0=Device, 1=Host)
    GINTSTS_MODEMIS     = (1 << 1)   # Mode Mismatch
    GINTSTS_SOF         = (1 << 3)   # Start of Frame
    GINTSTS_RXFLVL      = (1 << 4)   # RxFIFO Non-Empty
    GINTSTS_NPTXFEMP    = (1 << 5)   # Non-periodic TX FIFO Empty
    GINTSTS_GINNAKEFF   = (1 << 6)   # Global IN NAK Effective
    GINTSTS_GOUTNAKEFF  = (1 << 7)   # Global OUT NAK Effective
    GINTSTS_ULPICKINT   = (1 << 8)   # ULPI Carkit Interrupt
    GINTSTS_I2CINT      = (1 << 9)   # I2C Access
    GINTSTS_ERLYSUSP    = (1 << 10)  # Early Suspend
    GINTSTS_USBSUSP     = (1 << 11)  # USB Suspend
    GINTSTS_USBRST      = (1 << 12)  # USB Reset
    GINTSTS_ENUMDONE    = (1 << 13)  # Enumeration Done
    GINTSTS_ISOUTDROP   = (1 << 14)  # Isochronous OUT Packet Dropped
    GINTSTS_EOPF        = (1 << 15)  # End of Periodic Frame
    GINTSTS_IEPINT      = (1 << 18)  # IN Endpoint Interrupt
    GINTSTS_OEPINT      = (1 << 19)  # OUT Endpoint Interrupt
    GINTSTS_INCOMPISOIN = (1 << 20)  # Incomplete Isochronous IN
    GINTSTS_INCOMPISOOUT = (1 << 21) # Incomplete Isochronous OUT
    GINTSTS_FETSUSP     = (1 << 22)  # Data Fetch Suspended
    GINTSTS_RESETDET    = (1 << 23)  # Reset Detected
    GINTSTS_CONIDSTSCHNG = (1 << 28) # Connector ID Status Change
    GINTSTS_DISCONNINT  = (1 << 29)  # Disconnect Detected
    GINTSTS_SESSREQINT  = (1 << 30)  # Session Request/New Session
    GINTSTS_WKUPINT     = (1 << 31)  # Resume/Remote Wakeup

    # =========================================================================
    # GAHBCFG Bit Definitions
    # =========================================================================
    GAHBCFG_GLBLINTRMSK = (1 << 0)   # Global Interrupt Mask
    GAHBCFG_DMAEN       = (1 << 5)   # DMA Enable

    # =========================================================================
    # GRSTCTL Bit Definitions
    # =========================================================================
    GRSTCTL_CSFTRST     = (1 << 0)   # Core Soft Reset
    GRSTCTL_RXFFLSH     = (1 << 4)   # RxFIFO Flush
    GRSTCTL_TXFFLSH     = (1 << 5)   # TxFIFO Flush
    GRSTCTL_TXFNUM_MASK = (0x1F << 6)  # TxFIFO Number
    GRSTCTL_AHBIDLE     = (1 << 31)  # AHB Master Idle

    # =========================================================================
    # DCFG Bit Definitions
    # =========================================================================
    DCFG_DEVSPD_MASK    = 0x03       # Device Speed [1:0]
    DCFG_NZSTSOUTHSHK   = (1 << 2)  # Non-zero-length Status OUT Handshake
    DCFG_DEVADDR_MASK   = (0x7F << 4)  # Device Address [10:4]
    DCFG_DEVADDR_SHIFT  = 4
    DCFG_PERFRINT_MASK  = (0x03 << 11)  # Periodic Frame Interval [12:11]

    # Device Speed values for DCFG.DevSpd
    DCFG_SPEED_HS       = 0  # High-speed (USB 2.0 PHY @ 30/60 MHz)
    DCFG_SPEED_FS       = 1  # Full-speed (USB 2.0 PHY @ 30/60 MHz)
    DCFG_SPEED_FS_48    = 3  # Full-speed (dedicated FS PHY @ 48 MHz)

    # =========================================================================
    # DCTL Bit Definitions
    # =========================================================================
    DCTL_RMTWKUPSIG     = (1 << 0)   # Remote Wakeup Signaling
    DCTL_SFTDISCON      = (1 << 1)   # Soft Disconnect
    DCTL_GNPINNAKSTS    = (1 << 2)   # Global Non-periodic IN NAK Status (RO)
    DCTL_GOUTNAKSTS     = (1 << 3)   # Global OUT NAK Status (RO)
    DCTL_SGNPINNAK      = (1 << 7)   # Set Global Non-periodic IN NAK
    DCTL_CGNPINNAK      = (1 << 8)   # Clear Global Non-periodic IN NAK
    DCTL_SGOUTNAK       = (1 << 9)   # Set Global OUT NAK
    DCTL_CGOUTNAK       = (1 << 10)  # Clear Global OUT NAK
    DCTL_PWRONPRGDONE   = (1 << 11)  # Power-On Programming Done

    # =========================================================================
    # DSTS Bit Definitions (Read-Only)
    # =========================================================================
    DSTS_SUSPSTS        = (1 << 0)   # Suspend Status
    DSTS_ENUMSPD_MASK   = (0x03 << 1)  # Enumerated Speed [2:1]
    DSTS_ENUMSPD_SHIFT  = 1
    DSTS_ERRTICERR      = (1 << 3)   # Erratic Error
    DSTS_SOFFN_MASK     = (0x3FFF << 8)  # Frame/Microframe Number [21:8]
    DSTS_SOFFN_SHIFT    = 8

    # Enumerated Speed values for DSTS.EnumSpd
    DSTS_ENUMSPD_HS     = 0  # High-speed
    DSTS_ENUMSPD_FS     = 1  # Full-speed (PHY clock = 30/60 MHz)
    DSTS_ENUMSPD_FS_48  = 3  # Full-speed (PHY clock = 48 MHz)

    # =========================================================================
    # DIEPCTLn / DOEPCTLn Bit Definitions
    # =========================================================================
    DEPCTL_MPS_MASK     = 0x7FF      # Maximum Packet Size [10:0]
    DEPCTL_USBACTEP     = (1 << 15)  # USB Active Endpoint
    DEPCTL_DPID         = (1 << 16)  # Endpoint Data PID (even/odd frame)
    DEPCTL_NAKSTS       = (1 << 17)  # NAK Status (RO)
    DEPCTL_EPTYPE_MASK  = (0x03 << 18)  # Endpoint Type [19:18]
    DEPCTL_EPTYPE_SHIFT = 18
    DEPCTL_SNP          = (1 << 20)  # Snoop Mode (OUT only)
    DEPCTL_STALL        = (1 << 21)  # STALL Handshake
    DEPCTL_TXFNUM_MASK  = (0x0F << 22)  # TxFIFO Number [25:22] (IN only)
    DEPCTL_TXFNUM_SHIFT = 22
    DEPCTL_CNAK         = (1 << 26)  # Clear NAK
    DEPCTL_SNAK         = (1 << 27)  # Set NAK
    DEPCTL_SETD0PID     = (1 << 28)  # Set DATA0 PID
    DEPCTL_SETD1PID     = (1 << 29)  # Set DATA1 PID (odd frame)
    DEPCTL_EPDIS        = (1 << 30)  # Endpoint Disable
    DEPCTL_EPENA        = (1 << 31)  # Endpoint Enable

    # =========================================================================
    # DIEPTSIZn / DOEPTSIZn Bit Definitions
    # =========================================================================
    DEPTSIZ_XFERSIZE_MASK = 0x7FFFF           # Transfer Size [18:0]
    DEPTSIZ_PKTCNT_MASK   = (0x3FF << 19)     # Packet Count [28:19]
    DEPTSIZ_PKTCNT_SHIFT  = 19
    DEPTSIZ_MC_MASK       = (0x03 << 29)      # Multi Count [30:29] (IN isoc)
    DEPTSIZ_SUPCNT_MASK   = (0x03 << 29)      # SETUP Count [30:29] (OUT EP0)
    DEPTSIZ_SUPCNT_SHIFT  = 29

    # =========================================================================
    # DIEPINTn / DOEPINTn Bit Definitions (per-endpoint interrupts)
    # =========================================================================
    DEPINT_XFERCOMPL    = (1 << 0)   # Transfer Completed
    DEPINT_EPDISABLED   = (1 << 1)   # Endpoint Disabled
    DEPINT_AHBERR       = (1 << 2)   # AHB Error (DMA)
    DEPINT_SETUP        = (1 << 3)   # SETUP Phase Done (OUT only)
    DEPINT_TIMEOUT      = (1 << 3)   # Timeout (IN only, shared bit)
    DEPINT_INTKNTXFEMP  = (1 << 4)   # IN Token When TxFIFO Empty (IN only)
    DEPINT_OUTTKNEPDIS  = (1 << 4)   # OUT Token When EP Disabled (OUT only)
    DEPINT_INEPNAKEFF   = (1 << 6)   # IN EP NAK Effective (IN only)
    DEPINT_B2BSETUP     = (1 << 6)   # Back-to-Back SETUP (OUT only)
    DEPINT_OUTPKTERR    = (1 << 8)   # OUT Packet Error (OUT only)
    DEPINT_BNAINTR      = (1 << 9)   # BNA Interrupt (Buffer Not Available)
    DEPINT_PKTDRPSTS    = (1 << 11)  # Packet Drop Status (isoc)
    DEPINT_NYETINTR     = (1 << 14)  # NYET Interrupt (OUT only)
    DEPINT_STUPPKTRCVD  = (1 << 15)  # Setup Packet Received (OUT only)

    # =========================================================================
    # GUSBCFG Bit Definitions
    # =========================================================================
    GUSBCFG_TOUTCAL_MASK = 0x07      # HS/FS Timeout Calibration [2:0]
    GUSBCFG_PHYIF        = (1 << 3)  # PHY Interface (0=8-bit, 1=16-bit)
    GUSBCFG_ULPI_UTMI_SEL = (1 << 4) # ULPI/UTMI+ Select
    GUSBCFG_FSINTF       = (1 << 5)  # Full-Speed Serial Interface Select
    GUSBCFG_USBTRDTIM_MASK = (0x0F << 10)  # USB Turnaround Time [13:10]
    GUSBCFG_USBTRDTIM_SHIFT = 10
    GUSBCFG_SRPCAP       = (1 << 8)  # SRP-Capable
    GUSBCFG_HNPCAP       = (1 << 9)  # HNP-Capable
    GUSBCFG_FORCEDEVMODE = (1 << 30) # Force Device Mode
    GUSBCFG_FORCEHSTMODE = (1 << 29) # Force Host Mode

    def __init__(self, base_address: int = 0x50000000,
                 num_endpoints: int = 6,
                 dma_zones: Optional[List[Tuple[int, int]]] = None,
                 speed: BaseUSBSpeed = BaseUSBSpeed.HIGH_SPEED):
        """
        Initialize DWC2 device controller.

        Args:
            base_address: MMIO base address
            num_endpoints: Number of IN/OUT endpoint pairs (max 16)
            dma_zones: Allowed DMA address ranges
            speed: Initial USB speed
        """
        super().__init__(
            speed=speed,
            num_endpoints=min(num_endpoints, self.MAX_EPS),
            dma_zones=dma_zones,
        )

        self.base = base_address
        self.num_eps = min(num_endpoints, self.MAX_EPS)

        # Global registers
        self._gahbcfg: int = 0
        self._gusbcfg: int = 0x00001400  # Default: FS timeout cal, UTMI+
        self._grstctl: int = self.GRSTCTL_AHBIDLE  # AHB idle by default
        self._gintsts: int = 0
        self._gintmsk: int = 0
        self._grxfsiz: int = 0x00000200  # 512 words default RxFIFO
        self._gnptxfsiz: int = 0x02000200  # Start=0x200, Depth=0x200
        self._gotgctl: int = 0x00010000  # ID pin high (device mode)
        self._gotgint: int = 0

        # Device registers
        self._dcfg: int = 0
        self._dctl: int = self.DCTL_SFTDISCON  # Soft disconnect on reset
        self._diepmsk: int = 0
        self._doepmsk: int = 0
        self._daintmsk: int = 0
        self._diepempmsk: int = 0

        # Global NAK state
        self._global_in_nak: bool = False
        self._global_out_nak: bool = False

        # Per-EP IN registers
        self._diepctl: List[int] = [0] * self.num_eps
        self._diepint: List[int] = [0] * self.num_eps
        self._dieptsiz: List[int] = [0] * self.num_eps
        self._diepdma: List[int] = [0] * self.num_eps

        # Per-EP OUT registers
        self._doepctl: List[int] = [0] * self.num_eps
        self._doepint: List[int] = [0] * self.num_eps
        self._doeptsiz: List[int] = [0] * self.num_eps
        self._doepdma: List[int] = [0] * self.num_eps

        # Periodic TX FIFO size registers (for IN EPs 1-15)
        self._dieptxf: List[int] = [0x02000400] * 15  # Default sizes

        # FIFO state
        self._rxfifo: List[int] = []  # RxFIFO entries (status words)
        self._txfifo_space: List[int] = [0x200] * self.num_eps  # Per-EP TX space

        # Hardware config (read-only)
        self._ghwcfg1: int = 0x00000000
        self._ghwcfg2: int = 0x228DDD50  # HS, DMA, IN/OUT EPs
        self._ghwcfg3: int = 0x0FF000E8  # FIFO depth, width
        self._ghwcfg4: int = 0x1FF00020  # DED FIFO, EP directions

        # Enumerated speed (set after reset/enumeration)
        self._enumerated_speed: int = self.DSTS_ENUMSPD_HS

        # Setup EP0 defaults
        self._diepctl[0] = self.DEPCTL_USBACTEP  # EP0 always active
        self._doepctl[0] = self.DEPCTL_USBACTEP
        self.ep_in[0].mps = 64
        self.ep_out[0].mps = 64
        self.ep_in[0].ep_type = USBEPType.CONTROL
        self.ep_out[0].ep_type = USBEPType.CONTROL

        # Wire EP0 FSM callbacks
        self.ep0_fsm.register_callback('setup', self._on_ep0_setup)
        self.ep0_fsm.register_callback('complete', self._on_ep0_complete)

        logger.debug(f"DWC2 Device Controller initialized: base=0x{base_address:08X}, "
                     f"eps={self.num_eps}, speed={speed.name}")

    # =========================================================================
    # USBControllerBase Abstract Methods
    # =========================================================================

    def read_register(self, offset: int) -> int:
        """Read DWC2 register at offset."""
        self.coverage.record_register_access(offset, is_write=False)
        value = self._read_reg_internal(offset)
        return value

    def write_register(self, offset: int, value: int):
        """Write DWC2 register at offset."""
        self.coverage.record_register_access(offset, is_write=True, value=value)
        self._write_reg_internal(offset, value)

    def assert_interrupt(self, irq_type: str, **kwargs):
        """Assert interrupt by setting appropriate GINTSTS bits."""
        if irq_type == "sof":
            self._gintsts |= self.GINTSTS_SOF
        elif irq_type == "usb_reset":
            self._gintsts |= self.GINTSTS_USBRST
        elif irq_type == "enum_done":
            self._gintsts |= self.GINTSTS_ENUMDONE
        elif irq_type == "iep":
            self._gintsts |= self.GINTSTS_IEPINT
        elif irq_type == "oep":
            self._gintsts |= self.GINTSTS_OEPINT
        elif irq_type == "suspend":
            self._gintsts |= self.GINTSTS_USBSUSP
        elif irq_type == "early_suspend":
            self._gintsts |= self.GINTSTS_ERLYSUSP
        elif irq_type == "disconnect":
            self._gintsts |= self.GINTSTS_DISCONNINT
        elif irq_type == "wakeup":
            self._gintsts |= self.GINTSTS_WKUPINT
        elif irq_type == "rxflvl":
            self._gintsts |= self.GINTSTS_RXFLVL
        elif irq_type == "nptxfemp":
            self._gintsts |= self.GINTSTS_NPTXFEMP
        elif irq_type == "in_nak_eff":
            self._gintsts |= self.GINTSTS_GINNAKEFF
        elif irq_type == "out_nak_eff":
            self._gintsts |= self.GINTSTS_GOUTNAKEFF

        # Check if interrupt should be signaled to CPU
        self._check_global_interrupt()

    # =========================================================================
    # Register Read Logic
    # =========================================================================

    def _read_reg_internal(self, offset: int) -> int:
        """Internal register read dispatch."""
        # Global registers
        if offset == self.GOTGCTL:
            return self._gotgctl
        elif offset == self.GOTGINT:
            return self._gotgint
        elif offset == self.GAHBCFG:
            return self._gahbcfg
        elif offset == self.GUSBCFG:
            return self._gusbcfg
        elif offset == self.GRSTCTL:
            return self._grstctl
        elif offset == self.GINTSTS:
            return self._compute_gintsts()
        elif offset == self.GINTMSK:
            return self._gintmsk
        elif offset == self.GRXSTSR:
            return self._peek_rxfifo()
        elif offset == self.GRXSTSP:
            return self._pop_rxfifo()
        elif offset == self.GRXFSIZ:
            return self._grxfsiz
        elif offset == self.GNPTXFSIZ:
            return self._gnptxfsiz
        elif offset == self.GNPTXSTS:
            return self._compute_gnptxsts()
        elif offset == self.GHWCFG1:
            return self._ghwcfg1
        elif offset == self.GHWCFG2:
            return self._ghwcfg2
        elif offset == self.GHWCFG3:
            return self._ghwcfg3
        elif offset == self.GHWCFG4:
            return self._ghwcfg4

        # Periodic TX FIFO registers (0x100 + n*4)
        if 0x100 <= offset < 0x140:
            idx = (offset - 0x100) // 4
            if idx < len(self._dieptxf):
                return self._dieptxf[idx]

        # Device mode registers
        if offset == self.DCFG:
            return self._dcfg
        elif offset == self.DCTL:
            return self._compute_dctl()
        elif offset == self.DSTS:
            return self._compute_dsts()
        elif offset == self.DIEPMSK:
            return self._diepmsk
        elif offset == self.DOEPMSK:
            return self._doepmsk
        elif offset == self.DAINT:
            return self._compute_daint()
        elif offset == self.DAINTMSK:
            return self._daintmsk
        elif offset == self.DIEPEMPMSK:
            return self._diepempmsk

        # Per-EP IN registers
        if 0x900 <= offset < 0x900 + self.num_eps * self.EP_STRIDE:
            return self._read_diep_reg(offset)

        # Per-EP OUT registers
        if 0xB00 <= offset < 0xB00 + self.num_eps * self.EP_STRIDE:
            return self._read_doep_reg(offset)

        _log_unhandled_access("DWC2", "READ", offset, size=4)
        return 0

    def _read_diep_reg(self, offset: int) -> int:
        """Read device IN endpoint register."""
        ep = (offset - 0x900) // self.EP_STRIDE
        reg_off = (offset - 0x900) % self.EP_STRIDE

        if ep >= self.num_eps:
            return 0

        if reg_off == 0x00:    # DIEPCTLn
            return self._diepctl[ep]
        elif reg_off == 0x08:  # DIEPINTn
            return self._diepint[ep]
        elif reg_off == 0x10:  # DIEPTSIZn
            return self._dieptsiz[ep]
        elif reg_off == 0x14:  # DIEPDMAn
            return self._diepdma[ep]
        return 0

    def _read_doep_reg(self, offset: int) -> int:
        """Read device OUT endpoint register."""
        ep = (offset - 0xB00) // self.EP_STRIDE
        reg_off = (offset - 0xB00) % self.EP_STRIDE

        if ep >= self.num_eps:
            return 0

        if reg_off == 0x00:    # DOEPCTLn
            return self._doepctl[ep]
        elif reg_off == 0x08:  # DOEPINTn
            return self._doepint[ep]
        elif reg_off == 0x10:  # DOEPTSIZn
            return self._doeptsiz[ep]
        elif reg_off == 0x14:  # DOEPDMAn
            return self._doepdma[ep]
        return 0

    # =========================================================================
    # Register Write Logic
    # =========================================================================

    def _write_reg_internal(self, offset: int, value: int):
        """Internal register write dispatch."""
        # Global registers
        if offset == self.GOTGCTL:
            self._gotgctl = value
            return
        elif offset == self.GOTGINT:
            # W1C: write-1-to-clear
            self._gotgint &= ~value
            return
        elif offset == self.GAHBCFG:
            self._gahbcfg = value
            return
        elif offset == self.GUSBCFG:
            self._write_gusbcfg(value)
            return
        elif offset == self.GRSTCTL:
            self._write_grstctl(value)
            return
        elif offset == self.GINTSTS:
            # W1C for most bits (some are read-only)
            ro_bits = (self.GINTSTS_CURMOD | self.GINTSTS_IEPINT |
                      self.GINTSTS_OEPINT | self.GINTSTS_RXFLVL |
                      self.GINTSTS_NPTXFEMP)
            self._gintsts &= ~(value & ~ro_bits)
            return
        elif offset == self.GINTMSK:
            self._gintmsk = value
            return
        elif offset == self.GRXFSIZ:
            self._grxfsiz = value & 0xFFFF  # 16-bit depth
            return
        elif offset == self.GNPTXFSIZ:
            self._gnptxfsiz = value
            return

        # Periodic TX FIFO registers
        if 0x100 <= offset < 0x140:
            idx = (offset - 0x100) // 4
            if idx < len(self._dieptxf):
                self._dieptxf[idx] = value
            return

        # Device mode registers
        if offset == self.DCFG:
            self._write_dcfg(value)
            return
        elif offset == self.DCTL:
            self._write_dctl(value)
            return
        elif offset == self.DIEPMSK:
            self._diepmsk = value
            return
        elif offset == self.DOEPMSK:
            self._doepmsk = value
            return
        elif offset == self.DAINTMSK:
            self._daintmsk = value
            return
        elif offset == self.DIEPEMPMSK:
            self._diepempmsk = value
            return

        # Per-EP IN registers
        if 0x900 <= offset < 0x900 + self.num_eps * self.EP_STRIDE:
            self._write_diep_reg(offset, value)
            return

        # Per-EP OUT registers
        if 0xB00 <= offset < 0xB00 + self.num_eps * self.EP_STRIDE:
            self._write_doep_reg(offset, value)
            return

        _log_unhandled_access("DWC2", "WRITE", offset, value=value, size=4)

    def _write_diep_reg(self, offset: int, value: int):
        """Write device IN endpoint register."""
        ep = (offset - 0x900) // self.EP_STRIDE
        reg_off = (offset - 0x900) % self.EP_STRIDE

        if ep >= self.num_eps:
            return

        if reg_off == 0x00:    # DIEPCTLn
            self._write_diepctl(ep, value)
        elif reg_off == 0x08:  # DIEPINTn (W1C)
            self._diepint[ep] &= ~value
            self._update_daint_in(ep)
        elif reg_off == 0x10:  # DIEPTSIZn
            self._dieptsiz[ep] = value & 0x7FFFFFFF
            # Update endpoint transfer state from register
            xfer_size = value & self.DEPTSIZ_XFERSIZE_MASK
            pkt_cnt = (value & self.DEPTSIZ_PKTCNT_MASK) >> self.DEPTSIZ_PKTCNT_SHIFT
            self.ep_in[ep].xfer_size = xfer_size
            self.ep_in[ep].xfer_remaining = xfer_size
            self.ep_in[ep].pkt_cnt = pkt_cnt
        elif reg_off == 0x14:  # DIEPDMAn
            self._diepdma[ep] = value
            self.ep_in[ep].dma_addr = value

    def _write_doep_reg(self, offset: int, value: int):
        """Write device OUT endpoint register."""
        ep = (offset - 0xB00) // self.EP_STRIDE
        reg_off = (offset - 0xB00) % self.EP_STRIDE

        if ep >= self.num_eps:
            return

        if reg_off == 0x00:    # DOEPCTLn
            self._write_doepctl(ep, value)
        elif reg_off == 0x08:  # DOEPINTn (W1C)
            self._doepint[ep] &= ~value
            self._update_daint_out(ep)
        elif reg_off == 0x10:  # DOEPTSIZn
            self._doeptsiz[ep] = value & 0x7FFFFFFF
            xfer_size = value & self.DEPTSIZ_XFERSIZE_MASK
            pkt_cnt = (value & self.DEPTSIZ_PKTCNT_MASK) >> self.DEPTSIZ_PKTCNT_SHIFT
            self.ep_out[ep].xfer_size = xfer_size
            self.ep_out[ep].xfer_remaining = xfer_size
            self.ep_out[ep].pkt_cnt = pkt_cnt
            # EP0 SUPCnt
            if ep == 0:
                supcnt = (value & self.DEPTSIZ_SUPCNT_MASK) >> self.DEPTSIZ_SUPCNT_SHIFT
                self.ep0_fsm.sup_cnt = supcnt
        elif reg_off == 0x14:  # DOEPDMAn
            self._doepdma[ep] = value
            self.ep_out[ep].dma_addr = value

    # =========================================================================
    # Register Write Handlers
    # =========================================================================

    def _write_gusbcfg(self, value: int):
        """Handle GUSBCFG write."""
        self._gusbcfg = value

        # Force mode bits
        if value & self.GUSBCFG_FORCEHSTMODE:
            self.coverage.record_event("force_host_mode")
        if value & self.GUSBCFG_FORCEDEVMODE:
            self.coverage.record_event("force_device_mode")

        # PHY width change
        if value & self.GUSBCFG_PHYIF:
            self.timing.phy_width = 16
        else:
            self.timing.phy_width = 8

    def _write_grstctl(self, value: int):
        """Handle GRSTCTL write - core reset and FIFO flush."""
        if value & self.GRSTCTL_CSFTRST:
            self._core_soft_reset()
            # Clear CSftRst after reset completes
            self._grstctl = self.GRSTCTL_AHBIDLE
            self.coverage.record_event("core_soft_reset")
            return

        if value & self.GRSTCTL_RXFFLSH:
            self._rxfifo.clear()
            self.coverage.record_event("rxfifo_flush")

        if value & self.GRSTCTL_TXFFLSH:
            txf_num = (value & self.GRSTCTL_TXFNUM_MASK) >> 6
            self._flush_txfifo(txf_num)
            self.coverage.record_event("txfifo_flush", {'fifo': txf_num})

        # Keep AHB idle set, clear flush bits
        self._grstctl = self.GRSTCTL_AHBIDLE

    def _write_dcfg(self, value: int):
        """Handle DCFG write - device configuration."""
        old_dcfg = self._dcfg
        self._dcfg = value

        # Device speed
        dev_spd = value & self.DCFG_DEVSPD_MASK
        if dev_spd == self.DCFG_SPEED_HS:
            self.device_speed = BaseUSBSpeed.HIGH_SPEED
        elif dev_spd in (self.DCFG_SPEED_FS, self.DCFG_SPEED_FS_48):
            self.device_speed = BaseUSBSpeed.FULL_SPEED

        # Device address
        new_addr = (value & self.DCFG_DEVADDR_MASK) >> self.DCFG_DEVADDR_SHIFT
        if new_addr != self.device_address:
            self.set_address(new_addr)

        self.coverage.record_event("dcfg_write", {
            'speed': dev_spd,
            'addr': new_addr,
        })

    def _write_dctl(self, value: int):
        """Handle DCTL write - device control."""
        old_dctl = self._dctl

        # Soft Disconnect
        if (value & self.DCTL_SFTDISCON) and not (old_dctl & self.DCTL_SFTDISCON):
            # Rising edge -> disconnect
            self.connected = False
            self.assert_interrupt("disconnect")
            self.coverage.record_event("soft_disconnect")
        elif not (value & self.DCTL_SFTDISCON) and (old_dctl & self.DCTL_SFTDISCON):
            # Falling edge -> connect
            self.connected = True
            self.coverage.record_event("soft_connect")

        # Remote Wakeup Signaling
        if value & self.DCTL_RMTWKUPSIG:
            if self.suspended:
                self.suspended = False
                self.assert_interrupt("wakeup")
                self.coverage.record_event("remote_wakeup")

        # Global IN NAK
        if value & self.DCTL_SGNPINNAK:
            self._global_in_nak = True
            self.assert_interrupt("in_nak_eff")
        if value & self.DCTL_CGNPINNAK:
            self._global_in_nak = False

        # Global OUT NAK
        if value & self.DCTL_SGOUTNAK:
            self._global_out_nak = True
            self.assert_interrupt("out_nak_eff")
        if value & self.DCTL_CGOUTNAK:
            self._global_out_nak = False

        # Store (minus set/clear action bits)
        action_bits = (self.DCTL_SGNPINNAK | self.DCTL_CGNPINNAK |
                      self.DCTL_SGOUTNAK | self.DCTL_CGOUTNAK)
        self._dctl = value & ~action_bits

    def _write_diepctl(self, ep: int, value: int):
        """Handle DIEPCTLn write."""
        old = self._diepctl[ep]
        ep_state = self.ep_in[ep]

        # MPS
        mps = value & self.DEPCTL_MPS_MASK
        if ep == 0:
            # EP0 MPS encoding: 0=64, 1=32, 2=16, 3=8
            mps_table = {0: 64, 1: 32, 2: 16, 3: 8}
            ep_state.mps = mps_table.get(mps & 0x03, 64)
        else:
            ep_state.mps = mps

        # EP Type
        ep_type = (value & self.DEPCTL_EPTYPE_MASK) >> self.DEPCTL_EPTYPE_SHIFT
        ep_state.ep_type = USBEPType(ep_type)

        # TxFIFO number
        ep_state.fifo_num = (value & self.DEPCTL_TXFNUM_MASK) >> self.DEPCTL_TXFNUM_SHIFT

        # USB Active EP
        if value & self.DEPCTL_USBACTEP:
            ep_state.enabled = True

        # STALL
        if value & self.DEPCTL_STALL:
            ep_state.stalled = True
        else:
            ep_state.stalled = False

        # NAK control
        if value & self.DEPCTL_SNAK:
            ep_state.nak = True
            value |= self.DEPCTL_NAKSTS  # Set NAKSTS read-back
        if value & self.DEPCTL_CNAK:
            ep_state.nak = False
            value &= ~self.DEPCTL_NAKSTS

        # Data PID
        if value & self.DEPCTL_SETD0PID:
            self.data_toggle.set(ep, True, 0)
            ep_state.dpid = 0
        if value & self.DEPCTL_SETD1PID:
            self.data_toggle.set(ep, True, 1)
            ep_state.dpid = 1

        # EP Enable -> start transfer
        if (value & self.DEPCTL_EPENA) and not (old & self.DEPCTL_EPENA):
            self._start_in_transfer(ep)

        # EP Disable
        if value & self.DEPCTL_EPDIS:
            ep_state.enabled = False
            self._set_diepint(ep, self.DEPINT_EPDISABLED)
            value &= ~self.DEPCTL_EPENA

        # Clear action bits, update register
        action_bits = (self.DEPCTL_SNAK | self.DEPCTL_CNAK |
                      self.DEPCTL_SETD0PID | self.DEPCTL_SETD1PID)
        self._diepctl[ep] = value & ~action_bits

    def _write_doepctl(self, ep: int, value: int):
        """Handle DOEPCTLn write."""
        old = self._doepctl[ep]
        ep_state = self.ep_out[ep]

        # MPS
        mps = value & self.DEPCTL_MPS_MASK
        if ep == 0:
            mps_table = {0: 64, 1: 32, 2: 16, 3: 8}
            ep_state.mps = mps_table.get(mps & 0x03, 64)
        else:
            ep_state.mps = mps

        # EP Type
        ep_type = (value & self.DEPCTL_EPTYPE_MASK) >> self.DEPCTL_EPTYPE_SHIFT
        ep_state.ep_type = USBEPType(ep_type)

        # USB Active EP
        if value & self.DEPCTL_USBACTEP:
            ep_state.enabled = True

        # STALL
        if value & self.DEPCTL_STALL:
            ep_state.stalled = True
        else:
            ep_state.stalled = False

        # NAK control
        if value & self.DEPCTL_SNAK:
            ep_state.nak = True
            value |= self.DEPCTL_NAKSTS
        if value & self.DEPCTL_CNAK:
            ep_state.nak = False
            value &= ~self.DEPCTL_NAKSTS

        # Data PID
        if value & self.DEPCTL_SETD0PID:
            self.data_toggle.set(ep, False, 0)
            ep_state.dpid = 0
        if value & self.DEPCTL_SETD1PID:
            self.data_toggle.set(ep, False, 1)
            ep_state.dpid = 1

        # EP Enable -> prepare to receive
        if (value & self.DEPCTL_EPENA) and not (old & self.DEPCTL_EPENA):
            self._start_out_transfer(ep)

        # EP Disable
        if value & self.DEPCTL_EPDIS:
            ep_state.enabled = False
            self._set_doepint(ep, self.DEPINT_EPDISABLED)
            value &= ~self.DEPCTL_EPENA

        # Clear action bits
        action_bits = (self.DEPCTL_SNAK | self.DEPCTL_CNAK |
                      self.DEPCTL_SETD0PID | self.DEPCTL_SETD1PID)
        self._doepctl[ep] = value & ~action_bits

    # =========================================================================
    # Computed Register Values
    # =========================================================================

    def _compute_gintsts(self) -> int:
        """Compute GINTSTS with dynamic bits."""
        val = self._gintsts

        # Current Mode (0=Device)
        val &= ~self.GINTSTS_CURMOD

        # IEPInt and OEPInt are computed from DAINT
        daint = self._compute_daint()
        if daint & 0xFFFF:  # Any IN EP interrupt
            val |= self.GINTSTS_IEPINT
        else:
            val &= ~self.GINTSTS_IEPINT

        if daint & 0xFFFF0000:  # Any OUT EP interrupt
            val |= self.GINTSTS_OEPINT
        else:
            val &= ~self.GINTSTS_OEPINT

        # RxFIFO non-empty
        if self._rxfifo:
            val |= self.GINTSTS_RXFLVL
        else:
            val &= ~self.GINTSTS_RXFLVL

        return val & 0xFFFFFFFF

    def _compute_dctl(self) -> int:
        """Compute DCTL with NAK status bits."""
        val = self._dctl

        if self._global_in_nak:
            val |= self.DCTL_GNPINNAKSTS
        else:
            val &= ~self.DCTL_GNPINNAKSTS

        if self._global_out_nak:
            val |= self.DCTL_GOUTNAKSTS
        else:
            val &= ~self.DCTL_GOUTNAKSTS

        return val

    def _compute_dsts(self) -> int:
        """Compute DSTS (read-only status register)."""
        val = 0

        # Suspend status
        if self.suspended:
            val |= self.DSTS_SUSPSTS

        # Enumerated speed
        val |= (self._enumerated_speed << self.DSTS_ENUMSPD_SHIFT) & self.DSTS_ENUMSPD_MASK

        # SOFFN from timing model
        soffn = self.timing.get_soffn()
        val |= (soffn << self.DSTS_SOFFN_SHIFT) & self.DSTS_SOFFN_MASK

        return val

    def _compute_daint(self) -> int:
        """Compute DAINT from per-EP interrupt status."""
        val = 0
        for ep in range(self.num_eps):
            if self._diepint[ep] & self._diepmsk:
                val |= (1 << ep)
            if self._doepint[ep] & self._doepmsk:
                val |= (1 << (16 + ep))
        return val

    def _compute_gnptxsts(self) -> int:
        """Compute non-periodic TX FIFO status."""
        # NpTxFSpcAvail [15:0]: Available space in words
        # NpTxQSpcAvail [23:16]: Queue space available
        fifo_depth = (self._gnptxfsiz >> 16) & 0xFFFF
        space = min(self._txfifo_space[0], fifo_depth)
        return (space & 0xFFFF) | (0x04 << 16)  # 4 queue entries available

    # =========================================================================
    # Transfer Engine
    # =========================================================================

    def _start_in_transfer(self, ep: int):
        """Start an IN transfer (device-to-host)."""
        ep_state = self.ep_in[ep]

        if ep_state.stalled:
            self.coverage.record_event("in_transfer_stalled", {'ep': ep})
            return

        if self._global_in_nak:
            ep_state.nak = True
            self.coverage.record_event("in_transfer_global_nak", {'ep': ep})
            return

        # Read transfer parameters from TSIZn
        xfer_size = self._dieptsiz[ep] & self.DEPTSIZ_XFERSIZE_MASK
        pkt_cnt = (self._dieptsiz[ep] & self.DEPTSIZ_PKTCNT_MASK) >> self.DEPTSIZ_PKTCNT_SHIFT

        if pkt_cnt == 0:
            pkt_cnt = 1  # At least 1 packet

        ep_state.start_transfer(xfer_size, pkt_cnt, self._diepdma[ep])

        # DMA validation
        if self._gahbcfg & self.GAHBCFG_DMAEN:
            if not self.dma_validator.validate(ep_state.dma_addr, xfer_size,
                                               self.coverage):
                self._set_diepint(ep, self.DEPINT_AHBERR)
                return

        self.coverage.record_event("in_transfer_start", {
            'ep': ep,
            'size': xfer_size,
            'pkt_cnt': pkt_cnt,
        })

        # Mark EP as enabled
        self._diepctl[ep] |= self.DEPCTL_EPENA

    def _start_out_transfer(self, ep: int):
        """Start an OUT transfer (host-to-device) - prepare to receive."""
        ep_state = self.ep_out[ep]

        if ep_state.stalled:
            self.coverage.record_event("out_transfer_stalled", {'ep': ep})
            return

        if self._global_out_nak:
            ep_state.nak = True
            self.coverage.record_event("out_transfer_global_nak", {'ep': ep})
            return

        # Read transfer parameters
        xfer_size = self._doeptsiz[ep] & self.DEPTSIZ_XFERSIZE_MASK
        pkt_cnt = (self._doeptsiz[ep] & self.DEPTSIZ_PKTCNT_MASK) >> self.DEPTSIZ_PKTCNT_SHIFT

        if pkt_cnt == 0:
            pkt_cnt = 1

        ep_state.start_transfer(xfer_size, pkt_cnt, self._doepdma[ep])

        # DMA validation
        if self._gahbcfg & self.GAHBCFG_DMAEN:
            if not self.dma_validator.validate(ep_state.dma_addr, xfer_size,
                                               self.coverage):
                self._set_doepint(ep, self.DEPINT_AHBERR)
                return

        self.coverage.record_event("out_transfer_start", {
            'ep': ep,
            'size': xfer_size,
            'pkt_cnt': pkt_cnt,
        })

        self._doepctl[ep] |= self.DEPCTL_EPENA

    def process_in_packet(self, ep: int, size: int = 0) -> bool:
        """
        Process an IN packet transmission (device sends data to host).
        Called by USBIP/protocol layer when host issues IN token.

        Returns True if transfer is complete.
        """
        ep_state = self.ep_in[ep]

        if not ep_state.enabled:
            return False

        if ep_state.stalled:
            return False

        if ep_state.nak or self._global_in_nak:
            return False

        # Determine packet size
        pkt_size = min(size or ep_state.mps,
                       ep_state.mps,
                       ep_state.xfer_remaining)

        # Process packet
        complete = ep_state.packet_complete(pkt_size)

        # Update DIEPTSIZn register
        self._dieptsiz[ep] = (
            (ep_state.xfer_remaining & self.DEPTSIZ_XFERSIZE_MASK) |
            ((ep_state.pkt_cnt << self.DEPTSIZ_PKTCNT_SHIFT) & self.DEPTSIZ_PKTCNT_MASK)
        )

        # Update DMA address
        if self._gahbcfg & self.GAHBCFG_DMAEN:
            self._diepdma[ep] = ep_state.dma_addr
            self.coverage.record_dma_operation(
                ep_state.dma_addr - pkt_size, pkt_size, False)

        # Flip data toggle
        self.data_toggle.flip(ep, True)

        if complete:
            self._diepctl[ep] &= ~self.DEPCTL_EPENA
            self._set_diepint(ep, self.DEPINT_XFERCOMPL)
            self.coverage.record_event("in_xfer_complete", {'ep': ep})

        self.timing.advance(self.timing.USB_TURNAROUND_CLOCKS)
        return complete

    def process_out_packet(self, ep: int, data: bytes) -> bool:
        """
        Process an OUT packet reception (host sends data to device).
        Called by USBIP/protocol layer when host sends OUT data.

        Returns True if transfer is complete.
        """
        ep_state = self.ep_out[ep]

        if not ep_state.enabled:
            return False

        if ep_state.stalled:
            return False

        if ep_state.nak or self._global_out_nak:
            return False

        pkt_size = len(data)

        # DMA write validation
        if self._gahbcfg & self.GAHBCFG_DMAEN:
            if not self.dma_validator.validate(ep_state.dma_addr, pkt_size,
                                               self.coverage):
                self._set_doepint(ep, self.DEPINT_AHBERR)
                return False
            self.coverage.record_dma_operation(ep_state.dma_addr, pkt_size, True)

        # Process packet
        complete = ep_state.packet_complete(pkt_size)

        # Update DOEPTSIZn
        self._doeptsiz[ep] = (
            (ep_state.xfer_remaining & self.DEPTSIZ_XFERSIZE_MASK) |
            ((ep_state.pkt_cnt << self.DEPTSIZ_PKTCNT_SHIFT) & self.DEPTSIZ_PKTCNT_MASK)
        )

        # Update DMA address
        if self._gahbcfg & self.GAHBCFG_DMAEN:
            self._doepdma[ep] = ep_state.dma_addr

        # Flip data toggle
        self.data_toggle.flip(ep, False)

        if complete:
            self._doepctl[ep] &= ~self.DEPCTL_EPENA
            self._set_doepint(ep, self.DEPINT_XFERCOMPL)
            self.coverage.record_event("out_xfer_complete", {'ep': ep})

        self.timing.advance(self.timing.USB_TURNAROUND_CLOCKS)
        return complete

    def process_setup_packet(self, data: bytes) -> bool:
        """
        Process a SETUP packet on EP0.
        Called by USBIP/protocol layer when host sends SETUP.

        Returns True if accepted.
        """
        if len(data) < 8:
            self.coverage.record_error("short_setup_packet", {'len': len(data)})
            return False

        # EP0 FSM handles the SETUP
        accepted = self.ep0_fsm.receive_setup(data)

        if accepted:
            # Set SETUP interrupt for EP0 OUT
            self._set_doepint(0, self.DEPINT_SETUP)

            # Check back-to-back SETUP
            if len(self.ep0_fsm.setup_buffer) > 1:
                self._set_doepint(0, self.DEPINT_B2BSETUP)

            # Update DOEPTSIZn.SUPCnt
            supcnt = max(0, self.ep0_fsm.sup_cnt - len(self.ep0_fsm.setup_buffer))
            self._doeptsiz[0] = (self._doeptsiz[0] & ~self.DEPTSIZ_SUPCNT_MASK) | \
                                (supcnt << self.DEPTSIZ_SUPCNT_SHIFT)

            self.coverage.record_event("setup_received", {
                'bRequest': self.ep0_fsm.setup_packet.bRequest,
                'wValue': self.ep0_fsm.setup_packet.wValue,
                'wLength': self.ep0_fsm.setup_packet.wLength,
            })

        return accepted

    # =========================================================================
    # Interrupt Management
    # =========================================================================

    def _set_diepint(self, ep: int, bits: int):
        """Set IN endpoint interrupt bits and update DAINT."""
        self._diepint[ep] |= bits
        self._update_daint_in(ep)

    def _set_doepint(self, ep: int, bits: int):
        """Set OUT endpoint interrupt bits and update DAINT."""
        self._doepint[ep] |= bits
        self._update_daint_out(ep)

    def _update_daint_in(self, ep: int):
        """Update GINTSTS.IEPInt based on DAINT/DAINTMSK."""
        daint = self._compute_daint()
        if daint & self._daintmsk & 0xFFFF:
            self._gintsts |= self.GINTSTS_IEPINT
        else:
            self._gintsts &= ~self.GINTSTS_IEPINT
        self._check_global_interrupt()

    def _update_daint_out(self, ep: int):
        """Update GINTSTS.OEPInt based on DAINT/DAINTMSK."""
        daint = self._compute_daint()
        if daint & self._daintmsk & 0xFFFF0000:
            self._gintsts |= self.GINTSTS_OEPINT
        else:
            self._gintsts &= ~self.GINTSTS_OEPINT
        self._check_global_interrupt()

    def _check_global_interrupt(self):
        """Check if global interrupt should be signaled to CPU."""
        if not (self._gahbcfg & self.GAHBCFG_GLBLINTRMSK):
            return  # Global interrupt masked

        active = self._compute_gintsts() & self._gintmsk
        if active and not self._irq_pending:
            self._irq_pending = True
            if self._irq_callback:
                self._irq_callback(active)
        elif not active:
            self._irq_pending = False

    # =========================================================================
    # FIFO Operations
    # =========================================================================

    def _peek_rxfifo(self) -> int:
        """Peek at RxFIFO status (GRXSTSR - non-destructive read)."""
        if not self._rxfifo:
            return 0
        return self._rxfifo[0]

    def _pop_rxfifo(self) -> int:
        """Pop from RxFIFO (GRXSTSP - destructive read)."""
        if not self._rxfifo:
            return 0
        val = self._rxfifo.pop(0)
        if not self._rxfifo:
            self._gintsts &= ~self.GINTSTS_RXFLVL
        return val

    def push_rxfifo(self, ep: int, byte_count: int, pkt_status: int,
                    dpid: int = 0):
        """
        Push entry to RxFIFO (called when OUT data received).

        Per datasheet GRXSTSP format:
        [3:0] EPNum, [10:4] BCnt, [12:11] DPID, [16:13] PktSts
        PktSts: 1=Global OUT NAK, 2=OUT data, 4=SETUP complete,
                6=SETUP data, others=reserved
        """
        entry = ((ep & 0xF) |
                ((byte_count & 0x7F) << 4) |
                ((dpid & 0x03) << 11) |
                ((pkt_status & 0x0F) << 13))
        self._rxfifo.append(entry)
        self._gintsts |= self.GINTSTS_RXFLVL

    def _flush_txfifo(self, fifo_num: int):
        """Flush TX FIFO. fifo_num=0x10 means flush all."""
        if fifo_num == 0x10:
            # Flush all TX FIFOs
            for i in range(self.num_eps):
                self._txfifo_space[i] = self._get_txfifo_size(i)
        elif fifo_num < self.num_eps:
            self._txfifo_space[fifo_num] = self._get_txfifo_size(fifo_num)

    def _get_txfifo_size(self, fifo_num: int) -> int:
        """Get TX FIFO depth in words for given FIFO number."""
        if fifo_num == 0:
            return (self._gnptxfsiz >> 16) & 0xFFFF
        elif fifo_num <= len(self._dieptxf):
            return (self._dieptxf[fifo_num - 1] >> 16) & 0xFFFF
        return 0x200  # Default

    # =========================================================================
    # Reset and Initialization
    # =========================================================================

    def _core_soft_reset(self):
        """Perform core soft reset per datasheet Section 7.1."""
        # Reset global registers
        self._gahbcfg = 0
        self._gintsts = 0
        self._gintmsk = 0
        self._gotgint = 0

        # Reset device registers
        self._dcfg = 0
        self._dctl = self.DCTL_SFTDISCON
        self._diepmsk = 0
        self._doepmsk = 0
        self._daintmsk = 0
        self._diepempmsk = 0
        self._global_in_nak = False
        self._global_out_nak = False

        # Reset per-EP registers
        for ep in range(self.num_eps):
            self._diepctl[ep] = 0
            self._diepint[ep] = 0
            self._dieptsiz[ep] = 0
            self._diepdma[ep] = 0
            self._doepctl[ep] = 0
            self._doepint[ep] = 0
            self._doeptsiz[ep] = 0
            self._doepdma[ep] = 0

        # EP0 always active after reset
        self._diepctl[0] = self.DEPCTL_USBACTEP
        self._doepctl[0] = self.DEPCTL_USBACTEP

        # Reset FIFOs
        self._rxfifo.clear()
        self._txfifo_space = [self._get_txfifo_size(i) for i in range(self.num_eps)]

        # Reset base class state
        self.usb_reset()

        self._irq_pending = False

    def enumeration_done(self, speed: BaseUSBSpeed = BaseUSBSpeed.HIGH_SPEED):
        """
        Signal enumeration complete (call after speed negotiation).
        Sets DSTS.EnumSpd and triggers ENUMDONE interrupt.
        """
        if speed == BaseUSBSpeed.HIGH_SPEED:
            self._enumerated_speed = self.DSTS_ENUMSPD_HS
        elif speed == BaseUSBSpeed.FULL_SPEED:
            self._enumerated_speed = self.DSTS_ENUMSPD_FS
        else:
            self._enumerated_speed = self.DSTS_ENUMSPD_FS_48

        self.device_speed = speed
        self.assert_interrupt("enum_done")
        self.coverage.record_event("enumeration_done", {'speed': speed.name})

    def bus_reset(self):
        """Handle USB bus reset from host."""
        self._core_soft_reset()
        self.assert_interrupt("usb_reset")
        self.coverage.record_event("bus_reset")

    # =========================================================================
    # EP0 FSM Callbacks
    # =========================================================================

    def _on_ep0_setup(self, setup: SetupPacket):
        """EP0 SETUP received callback."""
        # Handle standard requests that affect the controller
        if setup.request_type == 0:  # Standard
            if setup.bRequest == 0x05:  # SET_ADDRESS
                # Address is programmed into DCFG after status phase
                pass
            elif setup.bRequest == 0x09:  # SET_CONFIGURATION
                self.set_configuration(setup.wValue)

    def _on_ep0_complete(self, setup: SetupPacket):
        """EP0 transfer complete callback."""
        if setup.request_type == 0 and setup.bRequest == 0x05:
            # SET_ADDRESS: program address after status phase
            self._dcfg = (self._dcfg & ~self.DCFG_DEVADDR_MASK) | \
                         ((setup.wValue & 0x7F) << self.DCFG_DEVADDR_SHIFT)
            self.device_address = setup.wValue & 0x7F

    # =========================================================================
    # Bus Event Simulation (for fuzzer/test harness)
    # =========================================================================

    def simulate_bus_reset(self):
        """
        Simulate USB bus reset event from host.

        Per DWC2 datasheet: a bus reset does NOT reset core configuration
        registers (GAHBCFG, GUSBCFG, GINTMSK, DCFG). It resets protocol-level
        state (address, endpoints) and fires USBRst interrupt. Only CSftRst
        (GRSTCTL bit 0) performs a full core reset.
        """
        # Reset protocol state
        self.device_address = 0
        self._dcfg &= ~self.DCFG_DEVADDR_MASK  # Clear address in DCFG
        self.configured = False
        self.suspended = False

        # Reset endpoints (but not masks/config)
        for ep in range(self.num_eps):
            self.ep_in[ep].reset()
            self.ep_out[ep].reset()
            self._diepint[ep] = 0
            self._doepint[ep] = 0
            self._dieptsiz[ep] = 0
            self._doeptsiz[ep] = 0

        # EP0 always active
        self.ep_in[0].enabled = True
        self.ep_out[0].enabled = True
        self._diepctl[0] = self.DEPCTL_USBACTEP
        self._doepctl[0] = self.DEPCTL_USBACTEP

        # Reset EP0 FSM and data toggles
        self.ep0_fsm.reset()
        self.data_toggle.reset_all()

        # Fire USBRst interrupt
        self.assert_interrupt("usb_reset")
        self.coverage.record_event("bus_reset")

    def simulate_suspend(self):
        """Simulate USB suspend."""
        self.suspended = True
        self.assert_interrupt("suspend")
        self.coverage.record_event("usb_suspend")

    def simulate_resume(self):
        """Simulate USB resume."""
        self.suspended = False
        self.assert_interrupt("wakeup")
        self.coverage.record_event("usb_resume")

    def simulate_sof(self):
        """Manually trigger SOF (if timing model not advancing)."""
        self.timing._generate_sof()
        self._gintsts |= self.GINTSTS_SOF

    def get_report(self) -> Dict:
        """Get controller state report for debugging/testing."""
        return {
            'device_address': self.device_address,
            'device_speed': self.device_speed.name,
            'connected': self.connected,
            'suspended': self.suspended,
            'configured': self.configured,
            'ep0_phase': self.ep0_fsm.phase.name,
            'global_in_nak': self._global_in_nak,
            'global_out_nak': self._global_out_nak,
            'gintsts': f"0x{self._compute_gintsts():08X}",
            'daint': f"0x{self._compute_daint():08X}",
            'enumerated_speed': self._enumerated_speed,
            'frame_number': self.timing.frame_number,
            'coverage': self.coverage.get_stats(),
        }


# =============================================================================
# USBIP Server (Device Mode - export emulated device)
# =============================================================================

class USBIPServer:
    """
    USBIP Server - exports an emulated USB device.

    Allows a host PC to connect and enumerate/use the virtual device
    as if it were a real USB device.
    """

    def __init__(self, device: USBDevice, port: int = 3240):
        self.device = device
        self.port = port
        self.server_sock: Optional[socket.socket] = None
        self.client_sock: Optional[socket.socket] = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

        # Callbacks
        self.on_enumerated: Optional[Callable[[], None]] = None
        self.on_data_out: Optional[Callable[[int, bytes], None]] = None
        self.on_data_in: Optional[Callable[[int, int], bytes]] = None

        # Device state
        self.address = 0
        self.configuration = 0

    def start(self):
        """Start the USBIP server."""
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(('0.0.0.0', self.port))
        self.server_sock.listen(1)
        self.server_sock.settimeout(1.0)

        self.running = True
        self.thread = threading.Thread(target=self._server_loop, daemon=True)
        self.thread.start()

        logger.info(f"USBIP Server listening on port {self.port}")

    def stop(self):
        """Stop the USBIP server."""
        self.running = False

        if self.client_sock:
            try:
                self.client_sock.close()
            except Exception:
                pass

        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass

        if self.thread:
            self.thread.join(timeout=2.0)

    def _server_loop(self):
        """Main server loop."""
        while self.running:
            try:
                self.client_sock, addr = self.server_sock.accept()
                logger.info(f"USBIP: Client connected from {addr}")
                self._handle_client()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"USBIP Server error: {e}")

    def _handle_client(self):
        """Handle a connected USBIP client."""
        try:
            while self.running and self.client_sock:
                # Read USBIP header
                header = self._recv_exact(8)
                if not header:
                    break

                version, opcode = struct.unpack(">HH", header[:4])
                status = struct.unpack(">I", header[4:8])[0]

                if opcode == USBIPOp.REQ_DEVLIST:
                    self._handle_devlist()
                elif opcode == USBIPOp.REQ_IMPORT:
                    self._handle_import()
                elif opcode == USBIPOp.CMD_SUBMIT:
                    self._handle_submit(header)
                elif opcode == USBIPOp.CMD_UNLINK:
                    self._handle_unlink(header)

        except Exception as e:
            logger.error(f"USBIP: Client handler error: {e}")
        finally:
            if self.client_sock:
                self.client_sock.close()
                self.client_sock = None

    def _recv_exact(self, size: int) -> Optional[bytes]:
        """Receive exactly size bytes."""
        data = b''
        while len(data) < size:
            try:
                chunk = self.client_sock.recv(size - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                continue
            except Exception:
                return None
        return data

    def _handle_devlist(self):
        """Handle device list request."""
        # Build device list response
        dev = self.device
        busid = b'/sys/devices/pci0000:00/0000:00:01.2/usb1/1-1'
        busid = busid.ljust(32, b'\x00')

        path = b'/sys/devices/pci0000:00/0000:00:01.2/usb1/1-1'
        path = path.ljust(256, b'\x00')

        # Reply header
        resp = struct.pack(">HHII",
            USBIP_VERSION,
            USBIPOp.REP_DEVLIST,
            0,  # status
            1   # num_devices
        )

        # Device info
        resp += path
        resp += busid
        resp += struct.pack(">IIIBBBBBBBB",
            1,  # busnum
            1,  # devnum
            USBSpeed.HIGH.value,
            dev.vendor_id,
            dev.product_id,
            0x0100,  # bcdDevice
            dev.device_class,
            dev.device_subclass,
            dev.device_protocol,
            0,  # configuration value
            1   # num configurations
        )

        # Interface info (1 interface)
        resp += struct.pack(">BBBB",
            dev.device_class,
            dev.device_subclass,
            dev.device_protocol,
            0  # padding
        )

        self.client_sock.sendall(resp)

    def _handle_import(self):
        """Handle device import request."""
        # Read busid
        busid = self._recv_exact(32)

        # Reply with device info
        dev = self.device
        path = b'/sys/devices/pci0000:00/0000:00:01.2/usb1/1-1'
        path = path.ljust(256, b'\x00')
        busid_resp = busid.ljust(32, b'\x00')

        resp = struct.pack(">HHI",
            USBIP_VERSION,
            USBIPOp.REP_IMPORT,
            0  # status = success
        )

        resp += path
        resp += busid_resp
        resp += struct.pack(">IIIHHBBBBBB",
            1,  # busnum
            1,  # devnum
            USBSpeed.HIGH.value,
            dev.vendor_id,
            dev.product_id,
            0x0100,  # bcdDevice
            dev.device_class,
            dev.device_subclass,
            dev.device_protocol,
            0,  # configuration
            1   # num configurations
        )

        self.client_sock.sendall(resp)

        if self.on_enumerated:
            self.on_enumerated()

    def _handle_submit(self, header: bytes):
        """Handle URB submit."""
        # Read rest of submit header (40 bytes total, already have 8)
        rest = self._recv_exact(40)
        if not rest:
            return

        full_header = header + rest
        (_, seqnum, devid, direction, ep,
         transfer_flags, transfer_buffer_length,
         start_frame, number_of_packets,
         interval, setup) = struct.unpack(">IIIIIIIIIH8s", full_header)

        # Read transfer buffer for OUT transfers
        data = b''
        if direction == 0 and transfer_buffer_length > 0:
            data = self._recv_exact(transfer_buffer_length)

        # Handle the request
        response_data = b''
        status = 0

        if ep == 0:  # Control endpoint
            response_data, status = self._handle_control(setup, data)
        else:
            if direction == 1:  # IN
                if self.on_data_in:
                    response_data = self.on_data_in(ep, transfer_buffer_length)
                else:
                    response_data = b'\x00' * min(transfer_buffer_length, 64)
            else:  # OUT
                if self.on_data_out:
                    self.on_data_out(ep, data)

        # Send response
        actual_length = len(response_data) if direction == 1 else 0
        resp = struct.pack(">IIIIIIIIII",
            USBIPOp.RET_SUBMIT << 16,
            seqnum,
            devid,
            direction,
            ep,
            status,
            actual_length,
            start_frame,
            number_of_packets,
            0  # error_count
        )
        resp += b'\x00' * 8  # setup (padding)

        if direction == 1 and response_data:
            resp += response_data

        self.client_sock.sendall(resp)

    def _handle_control(self, setup: bytes, data: bytes) -> Tuple[bytes, int]:
        """Handle control transfer."""
        bmRequestType, bRequest, wValue, wIndex, wLength = struct.unpack("<BBHHH", setup)

        direction = (bmRequestType >> 7) & 1
        req_type = (bmRequestType >> 5) & 3
        recipient = bmRequestType & 0x1F

        if req_type == 0:  # Standard request
            if bRequest == USBRequest.GET_DESCRIPTOR:
                desc_type = (wValue >> 8) & 0xFF
                desc_index = wValue & 0xFF
                return self._get_descriptor(desc_type, desc_index, wLength)

            elif bRequest == USBRequest.SET_ADDRESS:
                self.address = wValue
                return b'', 0

            elif bRequest == USBRequest.SET_CONFIGURATION:
                self.configuration = wValue
                return b'', 0

            elif bRequest == USBRequest.GET_CONFIGURATION:
                return bytes([self.configuration]), 0

        return b'', 0

    def _get_descriptor(self, desc_type: int, index: int, length: int) -> Tuple[bytes, int]:
        """Get USB descriptor."""
        dev = self.device

        if desc_type == DescriptorType.DEVICE:
            desc = struct.pack("<BBHBBBBHHHBBBB",
                18,  # bLength
                DescriptorType.DEVICE,
                0x0200,  # bcdUSB
                dev.device_class,
                dev.device_subclass,
                dev.device_protocol,
                64,  # bMaxPacketSize0
                dev.vendor_id,
                dev.product_id,
                0x0100,  # bcdDevice
                1,  # iManufacturer
                2,  # iProduct
                3,  # iSerialNumber
                1   # bNumConfigurations
            )
            return desc[:length], 0

        elif desc_type == DescriptorType.CONFIGURATION:
            # Build configuration descriptor
            config = struct.pack("<BBHBBBBB",
                9,   # bLength
                DescriptorType.CONFIGURATION,
                32,  # wTotalLength (config + interface + endpoints)
                1,   # bNumInterfaces
                1,   # bConfigurationValue
                0,   # iConfiguration
                0x80,  # bmAttributes (bus powered)
                50   # bMaxPower (100mA)
            )

            # Interface descriptor
            interface = struct.pack("<BBBBBBBBB",
                9,   # bLength
                DescriptorType.INTERFACE,
                0,   # bInterfaceNumber
                0,   # bAlternateSetting
                2,   # bNumEndpoints
                dev.device_class,
                dev.device_subclass,
                dev.device_protocol,
                0    # iInterface
            )

            # Endpoint descriptors
            ep_in = struct.pack("<BBBBHB",
                7,    # bLength
                DescriptorType.ENDPOINT,
                0x81,  # bEndpointAddress (IN, EP1)
                0x02,  # bmAttributes (Bulk)
                64,    # wMaxPacketSize
                0      # bInterval
            )

            ep_out = struct.pack("<BBBBHB",
                7,    # bLength
                DescriptorType.ENDPOINT,
                0x02,  # bEndpointAddress (OUT, EP2)
                0x02,  # bmAttributes (Bulk)
                64,    # wMaxPacketSize
                0      # bInterval
            )

            full_config = config + interface + ep_in + ep_out
            # Update total length
            full_config = full_config[:2] + struct.pack("<H", len(full_config)) + full_config[4:]

            return full_config[:length], 0

        elif desc_type == DescriptorType.STRING:
            if index == 0:
                # Language IDs
                return struct.pack("<BBH", 4, 3, 0x0409), 0
            elif index == 1:
                return self._make_string_desc(dev.manufacturer), 0
            elif index == 2:
                return self._make_string_desc(dev.product), 0
            elif index == 3:
                return self._make_string_desc(dev.serial), 0

        return b'', -1

    def _make_string_desc(self, s: str) -> bytes:
        """Create USB string descriptor."""
        encoded = s.encode('utf-16-le')
        return struct.pack("<BB", 2 + len(encoded), 3) + encoded

    def _handle_unlink(self, header: bytes):
        """Handle URB unlink."""
        rest = self._recv_exact(40)
        seqnum = struct.unpack(">I", header[4:8])[0]

        # Send unlink response
        resp = struct.pack(">IIIIIIIIII",
            USBIPOp.RET_UNLINK << 16,
            seqnum,
            0, 0, 0, 0, 0, 0, 0, 0
        )
        resp += b'\x00' * 8

        self.client_sock.sendall(resp)


# =============================================================================
# USBIP Client (Host Mode - import real devices)
# =============================================================================

class USBIPClient:
    """
    USBIP Client - imports USB devices from a USBIP server.

    Allows the emulator to act as a USB host and enumerate/use
    real USB devices connected to the host PC.
    """

    def __init__(self, host: str = "localhost", port: int = 3240):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.imported_device: Optional[USBDevice] = None
        self.seqnum = 0

        # Callbacks
        self.on_device_connected: Optional[Callable[[USBDevice], None]] = None

    def connect(self):
        """Connect to USBIP server."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))
        self.sock.settimeout(5.0)

    def disconnect(self):
        """Disconnect from USBIP server."""
        if self.sock:
            self.sock.close()
            self.sock = None

    def list_devices(self) -> List[USBDevice]:
        """List available devices on USBIP server."""
        if not self.sock:
            self.connect()

        # Send device list request
        req = struct.pack(">HHII",
            USBIP_VERSION,
            USBIPOp.REQ_DEVLIST,
            0,  # status
            0   # padding
        )
        self.sock.sendall(req)

        # Receive response header
        resp_header = self._recv_exact(12)
        version, opcode, status, num_devices = struct.unpack(">HHII", resp_header)

        devices = []
        for _ in range(num_devices):
            # Read device info
            path = self._recv_exact(256)
            busid = self._recv_exact(32)
            dev_info = self._recv_exact(24)

            (busnum, devnum, speed,
             vid, pid, bcdDevice,
             dev_class, dev_subclass, dev_protocol,
             config, num_configs) = struct.unpack(">IIIHHBBBBBB", dev_info[:23] + b'\x00')

            # Read interface info
            for _ in range(1):  # Simplified - just 1 interface
                iface_info = self._recv_exact(4)

            device = USBDevice(
                vendor_id=vid,
                product_id=pid,
                device_class=dev_class,
                device_subclass=dev_subclass,
                device_protocol=dev_protocol,
                speed=USBSpeed(speed) if speed <= 4 else USBSpeed.HIGH
            )
            devices.append(device)

        return devices

    def import_device(self, busid: str) -> bool:
        """Import a device from the USBIP server."""
        if not self.sock:
            self.connect()

        # Send import request
        busid_bytes = busid.encode('ascii').ljust(32, b'\x00')
        req = struct.pack(">HHI",
            USBIP_VERSION,
            USBIPOp.REQ_IMPORT,
            0
        )
        req += busid_bytes
        self.sock.sendall(req)

        # Receive response
        resp_header = self._recv_exact(8)
        version, opcode, status = struct.unpack(">HHI", resp_header)

        if status != 0:
            logger.error(f"USBIP: Import failed with status {status}")
            return False

        # Read device info
        path = self._recv_exact(256)
        busid_resp = self._recv_exact(32)
        dev_info = self._recv_exact(24)

        (busnum, devnum, speed,
         vid, pid, bcdDevice,
         dev_class, dev_subclass, dev_protocol,
         config, num_configs) = struct.unpack(">IIIHHBBBBBB", dev_info[:23] + b'\x00')

        self.imported_device = USBDevice(
            vendor_id=vid,
            product_id=pid,
            device_class=dev_class,
            device_subclass=dev_subclass,
            device_protocol=dev_protocol,
            speed=USBSpeed(speed) if speed <= 4 else USBSpeed.HIGH
        )

        if self.on_device_connected:
            self.on_device_connected(self.imported_device)

        return True

    def control_transfer(self, bmRequestType: int, bRequest: int,
                        wValue: int, wIndex: int, data: bytes = b'',
                        length: int = 0) -> bytes:
        """Perform a control transfer."""
        if not self.sock or not self.imported_device:
            raise RuntimeError("No device imported")

        self.seqnum += 1
        direction = (bmRequestType >> 7) & 1

        setup = struct.pack("<BBHHH",
            bmRequestType, bRequest, wValue, wIndex,
            length if direction else len(data)
        )

        # Build submit header
        header = struct.pack(">IIIIIIIIIH",
            USBIPOp.CMD_SUBMIT << 16,
            self.seqnum,
            1,  # devid
            direction,
            0,  # endpoint 0
            0,  # transfer_flags
            length if direction else len(data),
            0,  # start_frame
            0,  # number_of_packets
            0   # interval
        )
        header += setup

        # Send request
        self.sock.sendall(header)
        if not direction and data:
            self.sock.sendall(data)

        # Receive response
        resp = self._recv_exact(48)
        if not resp:
            raise RuntimeError("No response from USBIP server")

        # Parse response
        (opcode_status, seqnum, devid, dir_resp, ep,
         status, actual_length, start_frame,
         num_packets, error_count) = struct.unpack(">IIIIIIIIII", resp[:40])

        # Read data for IN transfers
        result = b''
        if direction and actual_length > 0:
            result = self._recv_exact(actual_length)

        return result

    def bulk_transfer(self, endpoint: int, data: bytes = b'', length: int = 0) -> bytes:
        """Perform a bulk transfer."""
        if not self.sock or not self.imported_device:
            raise RuntimeError("No device imported")

        self.seqnum += 1
        direction = (endpoint >> 7) & 1

        # Build submit header
        header = struct.pack(">IIIIIIIIIH8s",
            USBIPOp.CMD_SUBMIT << 16,
            self.seqnum,
            1,  # devid
            direction,
            endpoint,
            0,  # transfer_flags
            length if direction else len(data),
            0,  # start_frame
            0,  # number_of_packets
            0,  # interval
            b'\x00' * 8  # setup (not used for bulk)
        )

        # Send request
        self.sock.sendall(header)
        if not direction and data:
            self.sock.sendall(data)

        # Receive response
        resp = self._recv_exact(48)
        if not resp:
            raise RuntimeError("No response from USBIP server")

        (opcode_status, seqnum, devid, dir_resp, ep,
         status, actual_length, start_frame,
         num_packets, error_count) = struct.unpack(">IIIIIIIIII", resp[:40])

        # Read data for IN transfers
        result = b''
        if direction and actual_length > 0:
            result = self._recv_exact(actual_length)

        return result

    def _recv_exact(self, size: int) -> Optional[bytes]:
        """Receive exactly size bytes."""
        data = b''
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                return None
            data += chunk
        return data


# =============================================================================
# Predefined USB Device Classes
# =============================================================================

def create_cdc_acm_device(vid: int = 0x1234, pid: int = 0x5678) -> USBDevice:
    """Create a CDC-ACM (virtual serial port) device."""
    return USBDevice(
        vendor_id=vid,
        product_id=pid,
        device_class=0x02,  # CDC
        device_subclass=0x00,
        device_protocol=0x00,
        manufacturer="Twisted Wires",
        product="Slab Virtual Serial",
        serial="SLAB001",
        endpoints=[
            USBEndpoint(0x81, 0x03, 8, 10),   # Interrupt IN (notifications)
            USBEndpoint(0x82, 0x02, 64, 0),   # Bulk IN (data)
            USBEndpoint(0x02, 0x02, 64, 0),   # Bulk OUT (data)
        ]
    )


def create_hid_keyboard_device(vid: int = 0x1234, pid: int = 0x5679) -> USBDevice:
    """Create a HID keyboard device."""
    return USBDevice(
        vendor_id=vid,
        product_id=pid,
        device_class=0x00,  # Defined at interface level
        device_subclass=0x00,
        device_protocol=0x00,
        manufacturer="Twisted Wires",
        product="Slab Virtual Keyboard",
        serial="SLABKBD001",
        endpoints=[
            USBEndpoint(0x81, 0x03, 8, 10),  # Interrupt IN
        ]
    )


def create_mass_storage_device(vid: int = 0x1234, pid: int = 0x567A) -> USBDevice:
    """Create a mass storage device."""
    return USBDevice(
        vendor_id=vid,
        product_id=pid,
        device_class=0x00,
        device_subclass=0x00,
        device_protocol=0x00,
        manufacturer="Twisted Wires",
        product="Slab Virtual Storage",
        serial="SLABMSC001",
        endpoints=[
            USBEndpoint(0x81, 0x02, 512, 0),  # Bulk IN
            USBEndpoint(0x02, 0x02, 512, 0),  # Bulk OUT
        ]
    )


# =============================================================================
# Demo
# =============================================================================

def demo_otg_controller():
    """Demonstrate USB OTG functionality."""
    print("=" * 60)
    print("USB OTG Controller Demo")
    print("=" * 60)

    otg = OTGController()

    # Test mode switching
    print("\n1. Mode Switching")
    print("-" * 40)

    print(f"   Initial mode: {otg.mode.name}")

    otg.set_id_pin(False)  # Host mode
    print(f"   After ID pin low (host cable): {otg.mode.name}")

    otg.set_id_pin(True)   # Device mode
    print(f"   After ID pin float (device cable): {otg.mode.name}")

    # Test device mode with USBIP
    print("\n2. Device Mode (USBIP Server)")
    print("-" * 40)

    device = create_cdc_acm_device()
    print(f"   Created CDC-ACM device: {device.product}")
    print(f"   VID:PID = {device.vendor_id:04X}:{device.product_id:04X}")

    print("   Starting USBIP server on port 3240...")
    otg.start_device_mode(device, port=3240)

    print("   Server running. Connect with:")
    print("     sudo modprobe vhci-hcd")
    print("     sudo usbip attach -r localhost -b 1-1")

    # Wait a bit then stop
    time.sleep(2)
    otg.stop()
    print("   Server stopped.")

    print("\n3. Register Access")
    print("-" * 40)

    # Test register read/write
    gotgctl = otg.read_reg(OTGController.GOTGCTL)
    print(f"   GOTGCTL: 0x{gotgctl:08X}")

    gusbcfg = otg.read_reg(OTGController.GUSBCFG)
    print(f"   GUSBCFG: 0x{gusbcfg:08X}")

    ghwcfg2 = otg.read_reg(OTGController.GHWCFG2)
    print(f"   GHWCFG2: 0x{ghwcfg2:08X} (capabilities)")

    print("\n" + "=" * 60)
    print("Demo Complete!")
    print("=" * 60)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    demo_otg_controller()
