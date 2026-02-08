#!/usr/bin/env python3
"""
USB CDC-ACM Peripheral Emulation for MCUemu

This module emulates a USB CDC-ACM (Communications Device Class - Abstract Control Model)
device peripheral. CDC-ACM is commonly used for virtual serial ports over USB.

The emulation handles:
- USB device registers (STM32 OTG_FS style)
- Device enumeration (descriptors)
- CDC-ACM data transfer (echo mode for testing)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, field
from enum import IntEnum

log = logging.getLogger('USB')


# =============================================================================
# USB CONSTANTS
# =============================================================================

class USBRequestType(IntEnum):
    STANDARD = 0x00
    CLASS = 0x20
    VENDOR = 0x40

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

class USBDescriptorType(IntEnum):
    DEVICE = 0x01
    CONFIGURATION = 0x02
    STRING = 0x03
    INTERFACE = 0x04
    ENDPOINT = 0x05
    DEVICE_QUALIFIER = 0x06
    CDC_CS_INTERFACE = 0x24
    CDC_CS_ENDPOINT = 0x25

class CDCDescriptorSubtype(IntEnum):
    HEADER = 0x00
    CALL_MANAGEMENT = 0x01
    ACM = 0x02
    UNION = 0x06

class CDCRequest(IntEnum):
    SET_LINE_CODING = 0x20
    GET_LINE_CODING = 0x21
    SET_CONTROL_LINE_STATE = 0x22
    SEND_BREAK = 0x23


# =============================================================================
# USB DESCRIPTORS
# =============================================================================

@dataclass
class LineCoding:
    """CDC Line Coding structure."""
    dwDTERate: int = 115200   # Baud rate
    bCharFormat: int = 0      # 0=1 stop bit, 1=1.5, 2=2
    bParityType: int = 0      # 0=None, 1=Odd, 2=Even
    bDataBits: int = 8        # 5, 6, 7, 8, 16

    def pack(self) -> bytes:
        return struct.pack('<IBBB',
            self.dwDTERate,
            self.bCharFormat,
            self.bParityType,
            self.bDataBits
        )

    @classmethod
    def unpack(cls, data: bytes) -> 'LineCoding':
        rate, char_format, parity, data_bits = struct.unpack('<IBBB', data[:7])
        return cls(rate, char_format, parity, data_bits)


class USBCDCDescriptors:
    """USB CDC-ACM descriptors for virtual serial port."""

    # Device descriptor
    DEVICE_DESC = bytes([
        18,         # bLength
        0x01,       # bDescriptorType (Device)
        0x00, 0x02, # bcdUSB (2.00)
        0x02,       # bDeviceClass (CDC)
        0x02,       # bDeviceSubClass (ACM)
        0x00,       # bDeviceProtocol
        64,         # bMaxPacketSize0
        0x83, 0x04, # idVendor (0x0483 = STMicroelectronics)
        0x40, 0x57, # idProduct (0x5740 = Virtual COM Port)
        0x00, 0x02, # bcdDevice (2.00)
        1,          # iManufacturer
        2,          # iProduct
        3,          # iSerialNumber
        1,          # bNumConfigurations
    ])

    # Configuration descriptor (full)
    CONFIG_DESC = bytes([
        # Configuration descriptor
        9,          # bLength
        0x02,       # bDescriptorType (Configuration)
        67, 0,      # wTotalLength
        2,          # bNumInterfaces
        1,          # bConfigurationValue
        0,          # iConfiguration
        0xC0,       # bmAttributes (self-powered)
        50,         # bMaxPower (100mA)

        # Interface 0: CDC Control
        9,          # bLength
        0x04,       # bDescriptorType (Interface)
        0,          # bInterfaceNumber
        0,          # bAlternateSetting
        1,          # bNumEndpoints
        0x02,       # bInterfaceClass (CDC)
        0x02,       # bInterfaceSubClass (ACM)
        0x01,       # bInterfaceProtocol (AT commands)
        0,          # iInterface

        # CDC Header Functional Descriptor
        5,          # bLength
        0x24,       # bDescriptorType (CS_INTERFACE)
        0x00,       # bDescriptorSubtype (Header)
        0x10, 0x01, # bcdCDC (1.10)

        # CDC Call Management Functional Descriptor
        5,          # bLength
        0x24,       # bDescriptorType (CS_INTERFACE)
        0x01,       # bDescriptorSubtype (Call Management)
        0x00,       # bmCapabilities
        1,          # bDataInterface

        # CDC ACM Functional Descriptor
        4,          # bLength
        0x24,       # bDescriptorType (CS_INTERFACE)
        0x02,       # bDescriptorSubtype (ACM)
        0x02,       # bmCapabilities

        # CDC Union Functional Descriptor
        5,          # bLength
        0x24,       # bDescriptorType (CS_INTERFACE)
        0x06,       # bDescriptorSubtype (Union)
        0,          # bControlInterface
        1,          # bSubordinateInterface0

        # Notification Endpoint
        7,          # bLength
        0x05,       # bDescriptorType (Endpoint)
        0x82,       # bEndpointAddress (EP2 IN)
        0x03,       # bmAttributes (Interrupt)
        8, 0,       # wMaxPacketSize
        16,         # bInterval

        # Interface 1: CDC Data
        9,          # bLength
        0x04,       # bDescriptorType (Interface)
        1,          # bInterfaceNumber
        0,          # bAlternateSetting
        2,          # bNumEndpoints
        0x0A,       # bInterfaceClass (CDC Data)
        0x00,       # bInterfaceSubClass
        0x00,       # bInterfaceProtocol
        0,          # iInterface

        # Data OUT Endpoint
        7,          # bLength
        0x05,       # bDescriptorType (Endpoint)
        0x01,       # bEndpointAddress (EP1 OUT)
        0x02,       # bmAttributes (Bulk)
        64, 0,      # wMaxPacketSize
        0,          # bInterval

        # Data IN Endpoint
        7,          # bLength
        0x05,       # bDescriptorType (Endpoint)
        0x81,       # bEndpointAddress (EP1 IN)
        0x02,       # bmAttributes (Bulk)
        64, 0,      # wMaxPacketSize
        0,          # bInterval
    ])

    # String descriptors
    STRING_LANGID = bytes([4, 0x03, 0x09, 0x04])  # English (US)
    STRING_MANUFACTURER = "Twisted Wires".encode('utf-16-le')
    STRING_PRODUCT = "MCUemu CDC-ACM".encode('utf-16-le')
    STRING_SERIAL = "000001".encode('utf-16-le')

    @classmethod
    def get_string_desc(cls, index: int) -> bytes:
        """Get string descriptor by index."""
        if index == 0:
            return cls.STRING_LANGID
        elif index == 1:
            data = cls.STRING_MANUFACTURER
        elif index == 2:
            data = cls.STRING_PRODUCT
        elif index == 3:
            data = cls.STRING_SERIAL
        else:
            return bytes([2, 0x03])  # Empty string

        return bytes([len(data) + 2, 0x03]) + data


# =============================================================================
# USB CDC-ACM PERIPHERAL
# =============================================================================

class USBCDCPeripheral:
    """
    USB CDC-ACM Peripheral Emulation.

    Emulates STM32 OTG_FS USB device controller with CDC-ACM functionality.
    Supports enumeration and data transfer in echo mode.
    """

    # OTG_FS register offsets (simplified)
    GOTGCTL = 0x000   # Control and status
    GOTGINT = 0x004   # Interrupt
    GAHBCFG = 0x008   # AHB configuration
    GUSBCFG = 0x00C   # USB configuration
    GRSTCTL = 0x010   # Reset
    GINTSTS = 0x014   # Interrupt status
    GINTMSK = 0x018   # Interrupt mask
    GRXSTSR = 0x01C   # Receive status read
    GRXSTSP = 0x020   # Receive status pop
    GRXFSIZ = 0x024   # Receive FIFO size
    DIEPTXF0 = 0x028  # EP0 TX FIFO size
    GCCFG = 0x038     # General core configuration
    DCFG = 0x800      # Device configuration
    DCTL = 0x804      # Device control
    DSTS = 0x808      # Device status
    DIEPMSK = 0x810   # Device IN EP mask
    DOEPMSK = 0x814   # Device OUT EP mask
    DAINT = 0x818     # All EP interrupt
    DAINTMSK = 0x81C  # All EP interrupt mask
    DIEPEMPMSK = 0x834  # IN EP FIFO empty interrupt mask
    # IN endpoint registers start at 0x900
    DIEPCTL0 = 0x900  # IN EP0 control
    DIEPINT0 = 0x908  # IN EP0 interrupt
    DIEPTSIZ0 = 0x910 # IN EP0 transfer size
    DIEPDMA0 = 0x914  # IN EP0 DMA address
    DTXFSTS0 = 0x918  # IN EP0 TX FIFO status
    # OUT endpoint registers start at 0xB00
    DOEPCTL0 = 0xB00  # OUT EP0 control
    DOEPINT0 = 0xB08  # OUT EP0 interrupt
    DOEPTSIZ0 = 0xB10 # OUT EP0 transfer size
    DOEPDMA0 = 0xB14  # OUT EP0 DMA address
    # FIFOs
    FIFO0 = 0x1000    # EP0 FIFO
    FIFO1 = 0x2000    # EP1 FIFO
    FIFO2 = 0x3000    # EP2 FIFO

    def __init__(self, name: str, base: int, size: int = 0x40000, irq: int = -1):
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq
        self.secure_only = False
        self.ns_callable = False
        self.log = logging.getLogger(f'USB.{name}')
        self.irq_callback: Optional[Callable[[int, int], None]] = None

        # USB state
        self.connected = False
        self.configured = False
        self.address = 0
        self.setup_stage = False

        # Line coding (CDC)
        self.line_coding = LineCoding()
        self.control_line_state = 0

        # Data buffers (echo mode)
        self.rx_buffer: List[int] = []
        self.tx_buffer: List[int] = []

        # DWC2 OTG split-FIFO model (per RM0090 §34.17.6):
        # Status mini-FIFO: list of (epnum, pktsts, bcnt) tuples
        # GRXSTSR peeks the front entry, GRXSTSP pops it.
        self._rx_status_queue: List[tuple] = []
        # Shared RX data FIFO: data is available immediately when pushed.
        # On real DWC2, data arrives in the shared FIFO as soon as the
        # USB core receives it. GRXSTSP only pops the status entry -
        # it does NOT gate FIFO data access.
        self._rx_data_queue: bytearray = bytearray()

        # TX transfer tracking: maps EP number -> bytes remaining
        # Used to detect when IN transfer is complete and set XFRC.
        self._tx_pending: Dict[int, int] = {}

        # EP0 async completion: USBIP server awaits firmware EP0 IN response
        self._ep0_event: Optional[asyncio.Event] = None
        self._ep0_response: bytes = b''
        self._ep0_xfer_len: int = 0
        self._ep0_accum: bytearray = bytearray()  # Accumulate multi-packet data
        self._ep0_expected: int = 0  # Expected total from SETUP wLength
        self._ep0_max_pkt: int = 64  # EP0 max packet size

        # RX FIFO consumption tracking: bytes consumed since last status pop.
        # Used to auto-pop status entries for firmware that doesn't read GRXSTSP.
        self._rx_fifo_consumed: int = 0

        # Track whether firmware uses GRXSTSP (pop) vs only GRXSTSR (peek).
        # If GRXSTSP is used, disable auto-pop as firmware handles status explicitly.
        self._grxstsp_used: bool = False

        # Registers
        self.regs: Dict[int, int] = {
            self.GOTGCTL: 0x00010000,  # Current mode = device (VBUS not valid until host connects)
            self.GOTGINT: 0x00000000,
            self.GAHBCFG: 0x00000000,
            self.GUSBCFG: 0x00001440,  # Full-speed
            self.GRSTCTL: 0x80000000,  # AHB master idle
            self.GINTSTS: 0x04000020,  # Session request, mode mismatch
            self.GINTMSK: 0x00000000,
            self.GRXSTSR: 0x00000000,
            self.GRXSTSP: 0x00000000,
            self.GRXFSIZ: 0x00000200,  # 512 bytes
            self.DIEPTXF0: 0x02000200,
            self.GCCFG: 0x00000000,
            self.DCFG: 0x00000000,
            self.DCTL: 0x00000000,
            self.DSTS: 0x00000010,     # Suspend status
            self.DIEPMSK: 0x00000000,
            self.DOEPMSK: 0x00000000,
            self.DAINT: 0x00000000,
            self.DAINTMSK: 0x00000000,
            self.DIEPEMPMSK: 0x00000000,
        }

        # Endpoint registers
        for ep in range(4):
            self.regs[self.DIEPCTL0 + ep * 0x20] = 0x00000000
            self.regs[self.DIEPINT0 + ep * 0x20] = 0x00000000
            self.regs[self.DIEPTSIZ0 + ep * 0x20] = 0x00000000
            self.regs[self.DTXFSTS0 + ep * 0x20] = 0x00000200  # FIFO space
            self.regs[self.DOEPCTL0 + ep * 0x20] = 0x00000000
            self.regs[self.DOEPINT0 + ep * 0x20] = 0x00000000
            self.regs[self.DOEPTSIZ0 + ep * 0x20] = 0x00000000

        # Setup packet buffer
        self.setup_packet: bytes = bytes(8)

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    def check_security(self, secure: bool) -> bool:
        return True

    def set_irq_callback(self, callback: Callable[[int, int], None]):
        self.irq_callback = callback

    def _compute_gintsts(self) -> int:
        """Compute effective GINTSTS including dynamic bits.

        Per DWC2 spec, interrupt propagation chain:
        - DAINT[n] = (DIEPINTn & effective_mask) != 0
          where effective_mask = DIEPMSK | (((DIEPEMPMSK >> n) & 1) << 7)
        - DAINT[16+n] = (DOEPINTn & DOEPMSK) != 0
        - GINTSTS.IEPINT = (DAINT[15:0] & DAINTMSK[15:0]) != 0
        - GINTSTS.OEPINT = (DAINT[31:16] & DAINTMSK[31:16]) != 0
        """
        value = self.regs.get(self.GINTSTS, 0)
        # RXFLVL (bit 4): status queue has pending entries
        if self._rx_status_queue:
            value |= (1 << 4)
        else:
            value &= ~(1 << 4)
        # IEPINT (bit 18) / OEPINT (bit 19): per DWC2 interrupt chain
        daintmsk = self.regs.get(self.DAINTMSK, 0)
        diepmsk = self.regs.get(self.DIEPMSK, 0)
        doepmsk = self.regs.get(self.DOEPMSK, 0)
        diepempmsk = self.regs.get(self.DIEPEMPMSK, 0)
        iep_pending = False
        oep_pending = False
        for ep in range(4):
            # TXFE (bit 7) is masked by DIEPEMPMSK, not DIEPMSK
            ep_mask = diepmsk | (((diepempmsk >> ep) & 1) << 7)
            if (self.regs.get(self.DIEPINT0 + ep * 0x20, 0) & ep_mask) and (daintmsk & (1 << ep)):
                iep_pending = True
            if (self.regs.get(self.DOEPINT0 + ep * 0x20, 0) & doepmsk) and (daintmsk & (1 << (16 + ep))):
                oep_pending = True
        if iep_pending:
            value |= (1 << 18)
        else:
            value &= ~(1 << 18)
        if oep_pending:
            value |= (1 << 19)
        else:
            value &= ~(1 << 19)
        return value

    def trigger_irq(self):
        """Update IRQ line level based on pending state (DWC2 model).
        IRQ level = (GINTSTS & GINTMSK) != 0 && GAHBCFG.GINTMSK(bit0) == 1
        Level-triggered: asserts when pending, de-asserts when cleared.
        """
        if self.irq < 0 or not self.irq_callback:
            return
        gahbcfg = self.regs.get(self.GAHBCFG, 0)
        if not (gahbcfg & 1):  # Global interrupt mask disabled
            self.irq_callback(self.irq, 0)
            return
        gintsts = self._compute_gintsts()
        gintmsk = self.regs.get(self.GINTMSK, 0)
        pending = gintsts & gintmsk
        level = 1 if pending else 0
        if level:
            self.log.debug(f"IRQ assert: GINTSTS=0x{gintsts:08X} & GINTMSK=0x{gintmsk:08X} = 0x{pending:08X}")
        self.irq_callback(self.irq, level)

    def read(self, addr: int, size: int, secure: bool = False) -> tuple:
        offset = addr - self.base

        # FIFO reads: pop data from shared RX data queue (DWC2 model)
        # Data queue is independent of status queue; GRXSTSP pops status separately.
        if 0x1000 <= offset < 0x20000:
            if self._rx_data_queue:
                bytes_read = min(4, len(self._rx_data_queue))
                word = 0
                for i in range(bytes_read):
                    word |= self._rx_data_queue.pop(0) << (i * 8)
                self._rx_fifo_consumed += bytes_read
                # Auto-pop status entry when its data is fully consumed.
                # Handles firmware that uses GRXSTSR (peek) without GRXSTSP (pop).
                # Only auto-pop entries with bcnt > 0 (data entries).
                # Entries with bcnt=0 (like SETUP_COMP, XFER_COMP) must be
                # explicitly popped via GRXSTSP read.
                # IMPORTANT: Disable auto-pop if firmware has used GRXSTSP, as it
                # handles status management explicitly in the HAL pattern.
                if self._rx_status_queue and not self._grxstsp_used:
                    _, _, bcnt = self._rx_status_queue[0]
                    if bcnt > 0 and self._rx_fifo_consumed >= bcnt:
                        self._rx_status_queue.pop(0)
                        self._rx_fifo_consumed = 0
                        self.log.debug(f"Auto-popped status (bcnt={bcnt} consumed)")
                        self.trigger_irq()  # RXFLVL may clear
                self.log.debug(f"FIFO read: 0x{word:08X} (data_remaining={len(self._rx_data_queue)})")
                return (word, 0)
            return (0, 0)

        # DAINT - dynamically reflects which endpoints have pending interrupts
        # Per DWC2 spec: DAINT[n] = (DIEPINTn & effective_mask) != 0
        #   where effective_mask = DIEPMSK | (((DIEPEMPMSK >> n) & 1) << 7)
        #                 DAINT[16+n] = (DOEPINTn & DOEPMSK) != 0
        if offset == self.DAINT:
            daint = 0
            diepmsk = self.regs.get(self.DIEPMSK, 0)
            doepmsk = self.regs.get(self.DOEPMSK, 0)
            diepempmsk = self.regs.get(self.DIEPEMPMSK, 0)
            for ep in range(4):
                # TXFE (bit 7) masked by DIEPEMPMSK, not DIEPMSK
                ep_mask = diepmsk | (((diepempmsk >> ep) & 1) << 7)
                if self.regs.get(self.DIEPINT0 + ep * 0x20, 0) & ep_mask:
                    daint |= (1 << ep)         # IN EP
                if self.regs.get(self.DOEPINT0 + ep * 0x20, 0) & doepmsk:
                    daint |= (1 << (16 + ep))  # OUT EP
            return (daint, 0)

        # GINTSTS - dynamically reflects RXFLVL, IEPINT, OEPINT
        if offset == self.GINTSTS:
            return (self._compute_gintsts(), 0)

        # GRXSTSR (peek) / GRXSTSP (pop) - return status from mini-FIFO
        # Per RM0090 §34.17.6: GRXSTSR peeks without consuming; GRXSTSP pops.
        # Data is already in the shared FIFO (independent of status pop).
        if offset == self.GRXSTSR or offset == self.GRXSTSP:
            if self._rx_status_queue:
                epnum, pktsts, bcnt = self._rx_status_queue[0]
                result = (pktsts << 17) | (bcnt << 4) | epnum
                if offset == self.GRXSTSP:
                    # Pop: remove status entry only (data already in FIFO)
                    # Mark firmware as using GRXSTSP - disable auto-pop
                    self._grxstsp_used = True
                    self._rx_status_queue.pop(0)
                    self._rx_fifo_consumed = 0  # Reset consumption counter
                    self.log.debug(f"GRXSTSP pop: ep={epnum} pktsts={pktsts} bcnt={bcnt}")
                    # DWC2: SETUP_COMP (pktsts=4) sets DOEPINT0.STUP (bit 3)
                    # This signals the firmware's OEPINT handler to process
                    # the SETUP packet. Must be set per-packet for multi-SETUP.
                    if pktsts == 0x4 and epnum == 0:
                        self.regs[self.DOEPINT0] |= 0x08
                        self.log.debug("SETUP_COMP popped: DOEPINT0.STUP set")
                    self.trigger_irq()  # Re-evaluate: RXFLVL may clear
                return (result, 0)
            return (0, 0)

        value = self.regs.get(offset, 0)
        self.log.debug(f"Read[{'S' if secure else 'NS'}] 0x{addr:08X} = 0x{value:08X}")
        return (value, 0)

    def write(self, addr: int, size: int, value: int, secure: bool = False) -> int:
        offset = addr - self.base
        self.log.debug(f"Write[{'S' if secure else 'NS'}] 0x{addr:08X} <- 0x{value:08X}")

        # FIFO writes go to TX buffer
        if 0x1000 <= offset < 0x20000:
            ep = (offset - 0x1000) // 0x1000
            self.handle_tx_data(ep, value)
            # Track IN transfer progress for all endpoints including EP0
            if ep in self._tx_pending:
                self._tx_pending[ep] -= 4  # 32-bit FIFO write = 4 bytes
                self.log.debug(f"EP{ep} FIFO write: 0x{value:08X} (pending={self._tx_pending[ep]})")
                if self._tx_pending[ep] <= 0:
                    del self._tx_pending[ep]
                    # Transfer complete: set XFRC in DIEPINT(ep)
                    self.regs[self.DIEPINT0 + ep * 0x20] |= 0x01
                    self.log.info(f"EP{ep} IN XFRC (transfer complete)")
                    self.trigger_irq()
                    if ep == 0:
                        self._complete_ep0_transfer()
            return 0

        # Handle special registers

        # DIEPINT / DOEPINT are W1C (write-1-to-clear)
        for ep in range(4):
            if offset == self.DIEPINT0 + ep * 0x20:
                # TXFE (bit 7) is read-only status, not W1C - preserve it
                clear_mask = value & ~(1 << 7)
                self.regs[offset] = self.regs.get(offset, 0) & ~clear_mask
                self.trigger_irq()  # Re-evaluate: may de-assert IRQ
                return 0
            if offset == self.DOEPINT0 + ep * 0x20:
                self.regs[offset] = self.regs.get(offset, 0) & ~value
                self.trigger_irq()  # Re-evaluate: may de-assert IRQ
                return 0

        # GINTSTS is W1C (write-1-to-clear) for status bits
        if offset == self.GINTSTS:
            # Clear the bits that firmware wrote 1 to
            current = self.regs.get(self.GINTSTS, 0)
            self.regs[self.GINTSTS] = current & ~value
            self.log.debug(f"GINTSTS W1C: 0x{current:08X} & ~0x{value:08X} = 0x{self.regs[self.GINTSTS]:08X}")
            self.trigger_irq()  # Re-evaluate: may de-assert IRQ
            return 0

        if offset == self.GRSTCTL:
            if value & 0x01:  # Core soft reset
                self.log.info("USB core soft reset")
                self._rx_status_queue.clear()
                self._rx_data_queue.clear()
                self.tx_buffer.clear()
                self.regs[self.GRSTCTL] = 0x80000000
            if value & 0x10:  # RX FIFO flush
                self.log.info("RX FIFO flush")
                self._rx_status_queue.clear()
                self._rx_data_queue.clear()
                self.regs[self.GRSTCTL] = (self.regs.get(self.GRSTCTL, 0) & ~0x10) | 0x80000000
            if value & 0x20:  # TX FIFO flush
                self.log.info(f"TX FIFO flush (fifo_num={(value >> 6) & 0x1F})")
                self.tx_buffer.clear()
                self.regs[self.GRSTCTL] = (self.regs.get(self.GRSTCTL, 0) & ~0x20) | 0x80000000
            return 0

        if offset == self.DCFG:
            self.regs[offset] = value
            speed = (value >> 0) & 0x03
            self.log.info(f"Device config: speed={speed}")
            return 0

        if offset == self.DCTL:
            self.regs[offset] = value
            if value & 0x02:  # Soft disconnect
                self.log.info("USB soft disconnect")
                self.connected = False
            else:
                self.log.info("USB connected")
                self.connected = True
                # Don't fire USBRST/ENUMDNE here - on real hardware these
                # only happen when the HOST sends a reset (after detecting
                # the device pull-up). inject_enumeration() fires them.
            return 0

        # EP0 OUT control - re-arm endpoint for next transfer
        if offset == self.DOEPCTL0:
            self.regs[offset] = value
            if value & (1 << 31):  # EPENA
                self.log.debug("EP0 OUT re-armed (EPENA)")
                # Do NOT auto-set DOEPINT0.STUP here!
                # STUP is only set when a real SETUP packet is received
                # (via inject_setup_packet or DWC2 core in real hardware).
            return 0

        # EP1-3 OUT control: re-arm OUT endpoints
        for ep in range(1, 4):
            if offset == self.DOEPCTL0 + ep * 0x20:
                self.regs[offset] = value
                if value & (1 << 31):  # EPENA
                    self.log.debug(f"EP{ep} OUT re-armed (EPENA)")
                return 0

        # EP0 IN control - track transfer via DIEPTSIZ0
        if offset == self.DIEPCTL0:
            self.regs[offset] = value
            if value & (1 << 31):  # EPENA
                dieptsiz = self.regs.get(self.DIEPTSIZ0, 0)
                xfer_len = dieptsiz & 0x7F  # EP0 max 127 bytes (RM0090)
                self._tx_pending[0] = xfer_len
                self._ep0_xfer_len = xfer_len
                self.tx_buffer.clear()
                self.log.info(f"EP0 IN transfer started: {xfer_len} bytes")
                if xfer_len == 0:
                    # Zero-length IN (status stage): complete immediately
                    self.regs[self.DIEPINT0] |= 0x01  # XFRC
                    self.trigger_irq()
                    self._complete_ep0_transfer()
            return 0

        # EP1-3 IN control: track EPENA to start transfer
        for ep in range(1, 4):
            if offset == self.DIEPCTL0 + ep * 0x20:
                self.regs[offset] = value
                if value & (1 << 31):  # EPENA
                    # Start IN transfer: read xfer_len from DIEPTSIZ(ep)
                    dieptsiz = self.regs.get(self.DIEPTSIZ0 + ep * 0x20, 0)
                    xfer_len = dieptsiz & 0x7FFFF  # bits 18:0
                    self._tx_pending[ep] = xfer_len
                    self.log.debug(f"EP{ep} IN transfer started: {xfer_len} bytes")
                    if xfer_len == 0:
                        # Zero-length packet: immediately complete
                        self.regs[self.DIEPINT0 + ep * 0x20] |= 0x01  # XFRC
                        self.trigger_irq()
                return 0

        # DIEPEMPMSK: TX FIFO empty interrupt enable per EP
        # When set, DIEPINT.TXFE (bit 7) fires if the TX FIFO is empty.
        # Our emulated FIFOs are always empty, so set TXFE immediately.
        # When cleared, clear TXFE in DIEPINT to stop the interrupt.
        if offset == self.DIEPEMPMSK:
            old_val = self.regs.get(offset, 0)
            self.regs[offset] = value
            self.log.info(f"DIEPEMPMSK: 0x{value:08X}")
            for ep in range(4):
                if value & (1 << ep):
                    # FIFO is empty -> set TXFE in DIEPINT
                    self.regs[self.DIEPINT0 + ep * 0x20] |= (1 << 7)  # TXFE
                    self.log.info(f"EP{ep} TXFE set (FIFO empty)")
                elif old_val & (1 << ep):
                    # EP was enabled, now disabled -> clear TXFE
                    self.regs[self.DIEPINT0 + ep * 0x20] &= ~(1 << 7)
                    self.log.debug(f"EP{ep} TXFE cleared (DIEPEMPMSK disabled)")
            self.trigger_irq()
            return 0

        # DAINTMSK: log when firmware enables endpoint interrupts
        if offset == self.DAINTMSK:
            old_val = self.regs.get(self.DAINTMSK, 0)
            self.regs[offset] = value
            if value != old_val:
                in_eps = [ep for ep in range(4) if value & (1 << ep)]
                out_eps = [ep for ep in range(4) if value & (1 << (16 + ep))]
                self.log.info(f"DAINTMSK: 0x{value:08X} (IN={in_eps} OUT={out_eps})")
            self.trigger_irq()
            return 0

        # GCCFG: General core config (VBUS sensing, power down)
        if offset == self.GCCFG:
            self.regs[offset] = value
            self.log.info(f"GCCFG: 0x{value:08X} (PWRDWN={bool(value&(1<<16))}, "
                         f"VBDEN={bool(value&(1<<21))})")
            return 0

        # GINTMSK / GAHBCFG writes: re-evaluate IRQ level
        if offset in (self.GINTMSK, self.GAHBCFG):
            self.regs[offset] = value
            if offset == self.GINTMSK:
                self.log.info(f"GINTMSK: 0x{value:08X} (RXFLVL={bool(value&(1<<4))})")
            if offset == self.GAHBCFG:
                self.log.info(f"GAHBCFG: 0x{value:08X} (GINTMSK={bool(value&1)})")
            self.trigger_irq()
            return 0

        # Generic register write
        self.regs[offset] = value
        return 0

    def inject_setup_packet(self, setup_data: bytes):
        """Inject a USB SETUP packet into EP0 RX path (DWC2 model).

        On real hardware, the DWC2 core receives a SETUP token and generates
        the following status entries in order (RM0090 §34.17.6):

        1. SETUP_UPDT (pktsts=6, bcnt=8): 8 bytes of SETUP data in FIFO
        2. SETUP_COMP (pktsts=4, bcnt=0): SETUP phase complete

        After the firmware reads both status entries, DOEPINT0.STUP (bit 3) is
        set, which fires OEPINT if DAINTMSK has EP0 OUT enabled (bit 16).

        The HAL ISR processes these in order:
        - RXFLVL handler: pops SETUP_UPDT, reads 8 bytes → stores in hpcd->Setup
        - RXFLVL handler: pops SETUP_COMP, no data to read
        - OEPINT handler: sees DOEPINT0.STUP → calls SetupStageCallback

        Note: GINTMSK must have RXFLVL (bit 4) set for this to work via IRQ.
        DAINTMSK must have bit 16 (EP0 OUT) set for OEPINT to propagate.
        """
        assert len(setup_data) == 8, "Setup packet must be 8 bytes"

        # Phase 1: SETUP_UPDT - 8 bytes of SETUP data available in FIFO
        self._rx_data_queue.extend(setup_data)
        self._rx_status_queue.append((0, 0x6, 8))  # pktsts=SETUP_UPDT

        # Phase 2: SETUP_COMP - SETUP phase done (no data)
        # DOEPINT0.STUP (bit 3) is set when SETUP_COMP is popped from the
        # status queue (in the GRXSTSP read handler). This matches DWC2 spec
        # §8.2.4.2.4: "After SETUP data is extracted, core asserts STUP."
        self._rx_status_queue.append((0, 0x4, 0))  # pktsts=SETUP_COMP

        # Store SETUP packet for reference and parse wLength for multi-packet tracking
        self.setup_packet = setup_data
        wLength = setup_data[6] | (setup_data[7] << 8)
        self._ep0_expected = wLength

        self.log.info(f"Injected SETUP: {setup_data.hex()} "
                     f"(bmReqType=0x{setup_data[0]:02X} bReq=0x{setup_data[1]:02X} "
                     f"wVal=0x{setup_data[2]|setup_data[3]<<8:04X} wLen={wLength})")
        self.trigger_irq()

    def is_ready(self) -> bool:
        """Check if firmware has completed DWC2 USB initialization.

        Returns True when GCCFG has been configured (transceiver enabled)
        and device interrupts are enabled.
        """
        gccfg = self.regs.get(self.GCCFG, 0)
        gintmsk = self.regs.get(self.GINTMSK, 0)
        gahbcfg = self.regs.get(self.GAHBCFG, 0)
        # GCCFG non-zero = USB transceiver configured
        # GAHBCFG bit 0 = GINTMSK (global interrupt mask)
        # GINTMSK non-zero = at least some interrupts enabled
        return gccfg != 0 and (gahbcfg & 1) and gintmsk != 0

    def inject_vbus(self, connected: bool = True):
        """Inject VBUS state change.

        On real hardware, VBUS is asserted by the host when a cable is plugged in.
        The DWC2 core detects VBUS via GCCFG.VBDEN and reports status in GOTGCTL.

        When VBUS is asserted:
        - GOTGCTL.BSVLD (bit 19) = 1 (B-session valid)
        - GOTGCTL.ASVLD (bit 18) = 1 (A-session valid)
        - GINTSTS.SRQINT (bit 30) fires (session request)

        When VBUS is deasserted:
        - GOTGCTL.BSVLD = 0, ASVLD = 0
        - GINTSTS.OTGINT (bit 2) fires
        """
        gotgctl = self.regs.get(self.GOTGCTL, 0)
        if connected:
            gotgctl |= (1 << 19) | (1 << 18)  # BSVLD + ASVLD
            self.regs[self.GOTGCTL] = gotgctl
            self.regs[self.GINTSTS] = self.regs.get(self.GINTSTS, 0) | (1 << 30)  # SRQINT
            self.log.info("VBUS asserted (BSVLD=1, ASVLD=1)")
        else:
            gotgctl &= ~((1 << 19) | (1 << 18))
            self.regs[self.GOTGCTL] = gotgctl
            self.regs[self.GINTSTS] = self.regs.get(self.GINTSTS, 0) | (1 << 2)  # OTGINT
            self.log.info("VBUS deasserted (BSVLD=0, ASVLD=0)")
        self.trigger_irq()

    def inject_usbrst(self):
        """Inject USB bus reset (USBRST).

        On real hardware, the host holds D+/D- low for >10ms.
        The DWC2 core detects this and sets GINTSTS.USBRST (bit 12).

        After receiving this interrupt, the HAL firmware:
        - Flushes all FIFOs
        - Re-initializes all endpoints
        - Sets DAINTMSK for EP0 (IN + OUT)
        - Calls USBD_LL_Reset → opens EP0 IN/OUT
        """
        self.regs[self.GINTSTS] |= (1 << 12)  # USBRST
        self.trigger_irq()
        self.log.info("Injected USBRST")

    def inject_enumdne(self):
        """Inject speed enumeration done (ENUMDNE).

        After bus reset, the DWC2 core performs speed negotiation.
        When complete, it sets GINTSTS.ENUMDNE (bit 13) and
        DSTS.ENUMSPD to indicate the negotiated speed.

        DSTS.ENUMSPD = 3 means Full Speed (USB 1.1) using internal PHY.

        After receiving this, the HAL firmware:
        - Reads DSTS.ENUMSPD to determine speed
        - Sets EP0 max packet size (64 bytes for FS)
        """
        self.regs[self.DSTS] = (self.regs.get(self.DSTS, 0) & ~0x06) | (0x03 << 1)
        self.regs[self.GINTSTS] |= (1 << 13)  # ENUMDNE
        self.trigger_irq()
        self.log.info("Injected ENUMDNE (DSTS.ENUMSPD=3, Full Speed)")

    def _complete_ep0_transfer(self):
        """Called when EP0 IN packet finishes (XFRC).

        For multi-packet transfers (data > EP0 max packet size), the HAL sends
        multiple packets. We accumulate data across XFRC events and signal
        completion when:
        - A short packet is received (pkt_len < max_pkt_size), OR
        - Total accumulated data >= expected wLength from SETUP
        DWC2 FIFO writes are 32-bit aligned, so trim each packet to its xfer_len.
        """
        raw = bytes(self.tx_buffer)
        pkt_data = raw[:self._ep0_xfer_len] if self._ep0_xfer_len > 0 else raw
        self._ep0_accum.extend(pkt_data)
        pkt_len = len(pkt_data)
        total = len(self._ep0_accum)

        self.log.info(f"EP0 IN packet: {pkt_len} bytes (total={total}/{self._ep0_expected}): "
                     f"{pkt_data.hex()}")

        # Transfer complete if: short packet OR enough data accumulated
        if pkt_len < self._ep0_max_pkt or total >= self._ep0_expected:
            self._ep0_response = bytes(self._ep0_accum[:self._ep0_expected])
            self.log.info(f"EP0 IN complete: {len(self._ep0_response)} bytes: "
                         f"{self._ep0_response.hex()}")
            if self._ep0_event:
                self._ep0_event.set()
        else:
            self.log.debug(f"EP0 IN multi-packet: waiting for more data "
                          f"({total}/{self._ep0_expected})")

    async def wait_ep0_response(self, timeout: float = 5.0) -> bytes:
        """Wait for firmware to complete EP0 IN transfer.

        Called by USBIPServer when a control IN transfer needs firmware data.
        Creates an asyncio.Event, waits for _complete_ep0_transfer() to set it.
        Handles multi-packet transfers by accumulating across XFRC events.

        Returns:
            Firmware's EP0 IN response data (descriptor bytes, etc.)
        """
        self._ep0_event = asyncio.Event()
        self._ep0_response = b''
        self._ep0_accum = bytearray()
        try:
            await asyncio.wait_for(self._ep0_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.log.warning("EP0 response timeout (firmware did not respond)")
            # Return whatever we accumulated so far
            if self._ep0_accum:
                self._ep0_response = bytes(self._ep0_accum)
        finally:
            self._ep0_event = None
        return self._ep0_response

    def inject_out_data(self, ep: int, data: bytes):
        """Inject OUT data into DWC2 RX path for an endpoint.

        Used for control OUT transfers with data phase (e.g., SET_LINE_CODING).
        Pushes data into the shared RX FIFO with DATA_UPDT + XFER_COMP status.
        """
        self._rx_data_queue.extend(data)
        self._rx_status_queue.append((ep, 0x2, len(data)))  # DATA_UPDT
        self._rx_status_queue.append((ep, 0x3, 0))  # XFER_COMP
        self.regs[self.DOEPINT0 + ep * 0x20] |= 0x01  # XFRC
        self.log.info(f"Injected OUT data EP{ep}: {len(data)} bytes: {data.hex()}")
        self.trigger_irq()

    def enable_setup_delivery(self):
        """Enable interrupt chain for proper SETUP packet delivery.

        DMA-mode firmware has RXFLVL disabled in GINTMSK (DMA handles FIFO).
        To deliver SETUP packets via the FIFO path, we need:
        1. GINTMSK.RXFLVL (bit 4) - enables RXFLVL interrupt
        2. GINTMSK.OEPINT (bit 19) - enables OUT EP interrupt propagation
        3. DAINTMSK EP0 OUT (bit 16) - enables OEPINT for EP0
        4. DOEPMSK.STUP (bit 3) - enables SETUP complete in DAINT/OEPINT chain

        This emulates what happens when the DWC2 core is in non-DMA mode,
        which is compatible with the HAL's RXFLVL handler code (always compiled in).
        """
        # Enable RXFLVL + OEPINT in GINTMSK
        gintmsk = self.regs.get(self.GINTMSK, 0)
        needed = (1 << 4) | (1 << 19)  # RXFLVL | OEPINT
        if (gintmsk & needed) != needed:
            self.regs[self.GINTMSK] = gintmsk | needed
            self.log.info(f"Enabled RXFLVL+OEPINT in GINTMSK: 0x{self.regs[self.GINTMSK]:08X}")

        # Enable DAINTMSK for EP0 IN + OUT (if not already set by firmware)
        daintmsk = self.regs.get(self.DAINTMSK, 0)
        if not (daintmsk & 0x00010001):
            self.regs[self.DAINTMSK] = daintmsk | 0x00010001
            self.log.info(f"Enabled EP0 IN/OUT in DAINTMSK: 0x{self.regs[self.DAINTMSK]:08X}")

        # Enable DOEPMSK: XFRC (bit 0) + STUP (bit 3) - required for
        # DOEPINT0.STUP to propagate through DAINT to GINTSTS.OEPINT.
        # USB_DevInit sets this to 0x0B (XFRC|EPD|STUP) but DMA-mode
        # firmware may not have set it yet.
        doepmsk = self.regs.get(self.DOEPMSK, 0)
        needed_msk = 0x0B  # XFRC(0) | EPD(1) | STUP(3)
        if (doepmsk & needed_msk) != needed_msk:
            self.regs[self.DOEPMSK] = doepmsk | needed_msk
            self.log.info(f"Enabled XFRC+STUP in DOEPMSK: 0x{self.regs[self.DOEPMSK]:08X}")

        self.trigger_irq()

    def force_configured_state(self, dev_addr: int = 1):
        """Force USB peripheral into configured state (bypass SETUP processing).

        For firmware that doesn't properly read FIFO data during SETUP packets
        (e.g., firmware that triggers USB_DevInit during RXFLVL processing),
        this function directly sets the USB registers to the state that would
        result from successful enumeration:
        - Device address set in DCFG
        - EP0 and EP1 IN/OUT enabled in DAINTMSK
        - EP1 control registers configured for CDC data
        - GINTMSK set for normal operation (RXFLVL + OEPINT)

        Args:
            dev_addr: USB device address (1-127)
        """
        # Set device address in DCFG (bits 10:4)
        dcfg = self.regs.get(self.DCFG, 0)
        dcfg = (dcfg & ~(0x7F << 4)) | ((dev_addr & 0x7F) << 4)
        self.regs[self.DCFG] = dcfg
        self.log.info(f"Force configured: DCFG.DAD={dev_addr}")

        # Enable EP0 + EP1 IN/OUT in DAINTMSK
        # EP0 IN (bit 0), EP0 OUT (bit 16), EP1 IN (bit 1), EP1 OUT (bit 17)
        self.regs[self.DAINTMSK] = 0x00030003
        self.log.info(f"Force configured: DAINTMSK=0x{self.regs[self.DAINTMSK]:08X}")

        # Configure EP1 IN (DIEPCTL1): 64-byte bulk endpoint
        # USBAEP (bit 15) = 1, EPTYP (bits 19:18) = 2 (bulk), MPSIZ (bits 10:0) = 64
        diepctl1 = (1 << 15) | (2 << 18) | 64
        self.regs[self.DIEPCTL0 + 0x20] = diepctl1

        # Configure EP1 OUT (DOEPCTL1): 64-byte bulk endpoint
        # USBAEP (bit 15) = 1, EPTYP (bits 19:18) = 2 (bulk), MPSIZ (bits 10:0) = 64
        doepctl1 = (1 << 15) | (2 << 18) | 64
        self.regs[self.DOEPCTL0 + 0x20] = doepctl1

        # Enable DOEPMSK/DIEPMSK for proper interrupt propagation
        self.regs[self.DOEPMSK] = 0x0B  # XFRC + EPD + STUP
        self.regs[self.DIEPMSK] = 0x0B  # XFRC + EPD + TOC

        # Set GINTMSK for normal operation (RXFLVL + OEPINT + IEPINT)
        self.regs[self.GINTMSK] = 0x000C0010  # OEPINT(19) + IEPINT(18) + RXFLVL(4)
        self.log.info(f"Force configured: GINTMSK=0x{self.regs[self.GINTMSK]:08X}")

        # Clear any stale data
        self._rx_status_queue.clear()
        self._rx_data_queue.clear()
        self._rx_fifo_consumed = 0
        self._grxstsp_used = False  # Reset auto-pop detection

        self.configured = True
        self.address = dev_addr
        self.log.info("USB forced to configured state")

    def inject_enumeration(self, include_setup=True):
        """Inject the USB enumeration sequence needed by HAL firmware.

        Simulates the host-side connection sequence:
        1. USB bus reset (USBRST) - firmware re-initializes USB core
        2. Speed enumeration done (ENUMDNE) - firmware reads DSTS.ENUMSPD
        3. (Optional) SETUP packets for address/configuration

        WARNING: This fires USBRST+ENUMDNE simultaneously, which may not give
        the firmware enough time to process each step. For proper Linux-style
        enumeration, use the individual methods (inject_usbrst, inject_enumdne,
        enable_setup_delivery, inject_setup_packet) with delays between them.

        Args:
            include_setup: If True, inject SET_ADDRESS + SET_CONFIGURATION +
                          SET_CONTROL_LINE_STATE. Set to False for firmware
                          that uses polling-only USB (no endpoint interrupts).
        """
        import struct as _st

        self.regs[self.GINTSTS] |= (1 << 12)  # USBRST
        self.regs[self.DSTS] = (self.regs.get(self.DSTS, 0) & ~0x06) | (0x03 << 1)
        self.regs[self.GINTSTS] |= (1 << 13)  # ENUMDNE
        self.trigger_irq()
        self.log.info("Injected USBRST + ENUMDNE")

        if include_setup:
            self.enable_setup_delivery()
            self.inject_setup_packet(_st.pack('<BBHHH', 0x00, 0x05, 1, 0, 0))
            self.inject_setup_packet(_st.pack('<BBHHH', 0x00, 0x09, 1, 0, 0))
            self.inject_setup_packet(_st.pack('<BBHHH', 0x21, 0x22, 0x0003, 0, 0))
            self.log.info("Enumeration + SETUP injected")
        else:
            self.log.info("Enumeration injected (no SETUP - polling mode)")

        self.configured = True

    def handle_tx_data(self, ep: int, value: int):
        """Handle data written to TX FIFO."""
        if ep == 0:
            # EP0 control data
            for i in range(4):
                self.tx_buffer.append((value >> (i * 8)) & 0xFF)
        else:
            # Data endpoint - echo mode (when no bridge is connected)
            echo_bytes = []
            for i in range(4):
                byte = (value >> (i * 8)) & 0xFF
                if byte:
                    echo_bytes.append(byte)
            if echo_bytes:
                self._rx_status_queue.append((1, 0x2, len(echo_bytes)))
                self._rx_data_queue.extend(echo_bytes)
                self.log.info(f"Echo EP{ep}: {bytes(echo_bytes)!r}")

    def handle_ep0_in(self):
        """Handle EP0 IN transaction (device to host)."""
        # Mark transfer complete
        self.regs[self.DIEPINT0] |= 0x01  # Transfer complete
        self.trigger_irq()

    def get_descriptor(self, desc_type: int, desc_index: int, length: int) -> bytes:
        """Get USB descriptor."""
        if desc_type == USBDescriptorType.DEVICE:
            return USBCDCDescriptors.DEVICE_DESC[:length]
        elif desc_type == USBDescriptorType.CONFIGURATION:
            return USBCDCDescriptors.CONFIG_DESC[:length]
        elif desc_type == USBDescriptorType.STRING:
            return USBCDCDescriptors.get_string_desc(desc_index)[:length]
        return bytes()

    def handle_setup(self, setup: bytes):
        """Handle USB setup packet."""
        if len(setup) < 8:
            return

        bmRequestType = setup[0]
        bRequest = setup[1]
        wValue = setup[2] | (setup[3] << 8)
        wIndex = setup[4] | (setup[5] << 8)
        wLength = setup[6] | (setup[7] << 8)

        self.log.info(f"SETUP: type=0x{bmRequestType:02X} req=0x{bRequest:02X} "
                     f"val=0x{wValue:04X} idx=0x{wIndex:04X} len={wLength}")

        # Standard requests
        if (bmRequestType & 0x60) == USBRequestType.STANDARD:
            if bRequest == USBRequest.GET_DESCRIPTOR:
                desc_type = (wValue >> 8) & 0xFF
                desc_index = wValue & 0xFF
                data = self.get_descriptor(desc_type, desc_index, wLength)
                self.tx_buffer = list(data)
                self.log.info(f"GET_DESCRIPTOR: type={desc_type} index={desc_index} -> {len(data)} bytes")

            elif bRequest == USBRequest.SET_ADDRESS:
                self.address = wValue & 0x7F
                self.log.info(f"SET_ADDRESS: {self.address}")

            elif bRequest == USBRequest.SET_CONFIGURATION:
                self.configured = True
                self.log.info(f"SET_CONFIGURATION: {wValue}")

        # CDC class requests
        elif (bmRequestType & 0x60) == USBRequestType.CLASS:
            if bRequest == CDCRequest.SET_LINE_CODING:
                self.log.info("SET_LINE_CODING (waiting for data)")
                # Data follows in DATA stage

            elif bRequest == CDCRequest.GET_LINE_CODING:
                self.tx_buffer = list(self.line_coding.pack())
                self.log.info(f"GET_LINE_CODING: {self.line_coding.dwDTERate} baud")

            elif bRequest == CDCRequest.SET_CONTROL_LINE_STATE:
                self.control_line_state = wValue
                dtr = (wValue & 0x01) != 0
                rts = (wValue & 0x02) != 0
                self.log.info(f"SET_CONTROL_LINE_STATE: DTR={dtr} RTS={rts}")


# =============================================================================
# TEST
# =============================================================================

def test_usb_cdc():
    """Test USB CDC peripheral emulation."""
    logging.basicConfig(level=logging.DEBUG)

    usb = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)

    print("=== USB CDC-ACM Peripheral Test ===")

    # Simulate USB connection
    print("\n1. Connect USB...")
    usb.write(0x50000804, 4, 0x00000000)  # Clear soft disconnect

    # Read device status
    print("\n2. Check status...")
    status, _ = usb.read(0x50000808, 4)
    print(f"   DSTS = 0x{status:08X}")

    # Simulate GET_DESCRIPTOR (device)
    print("\n3. GET_DESCRIPTOR (Device)...")
    setup = bytes([0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x12, 0x00])
    usb.handle_setup(setup)
    print(f"   TX buffer: {len(usb.tx_buffer)} bytes")

    # Simulate SET_ADDRESS
    print("\n4. SET_ADDRESS (1)...")
    setup = bytes([0x00, 0x05, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
    usb.handle_setup(setup)
    print(f"   Address: {usb.address}")

    # Simulate CDC data echo
    print("\n5. CDC Echo test...")
    test_data = "Hello\r\n"
    for i in range(0, len(test_data), 4):
        word = 0
        for j in range(4):
            if i + j < len(test_data):
                word |= ord(test_data[i + j]) << (j * 8)
        usb.write(0x50002000, 4, word)  # Write to EP1 FIFO

    # Read back via DWC2 model: check GINTSTS, GRXSTSP (pop), then FIFO
    echo_result = bytearray()
    while usb.read(0x50000014, 4)[0] & (1 << 4):  # GINTSTS RXFLVL
        grxstsp, _ = usb.read(0x50000020, 4)  # GRXSTSP: pop status entry
        bcnt = (grxstsp >> 4) & 0x7FF
        words = (bcnt + 3) // 4
        for _ in range(words):
            w, _ = usb.read(0x50001000, 4)
            for j in range(4):
                b = (w >> (j * 8)) & 0xFF
                if b:
                    echo_result.append(b)
    print(f"   RX echo (via DWC2 model): {bytes(echo_result)!r}")

    print("\n=== Test Complete ===")


if __name__ == '__main__':
    test_usb_cdc()
