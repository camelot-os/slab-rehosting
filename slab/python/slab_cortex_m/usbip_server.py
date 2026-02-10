#!/usr/bin/env python3
"""
USBIP Server for MCUemu

This server exposes the emulated USB device (DWC2 OTG) to the host via USBIP protocol.
It bridges between MCUemu's peripheral emulation and the Linux USBIP client.

Architecture:
    [QEMU/MCUemu] <--TCP--> [Peripheral Server] <---> [USBIP Server] <--USBIP--> [Host]

The USBIP server:
1. Receives USB requests from the host via USBIP protocol
2. Forwards them to the emulated USB peripheral
3. Returns responses back to the host

Usage:
    # Start the USBIP server
    python3 usbip_server.py --port 3240

    # On host, attach the virtual device
    sudo modprobe vhci-hcd
    sudo usbip attach -r localhost -b 1-1

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
import socket
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Callable
from enum import IntEnum

log = logging.getLogger('USBIP')


# =============================================================================
# USBIP PROTOCOL CONSTANTS
# =============================================================================

USBIP_VERSION = 0x0111  # Version 1.1.1

class USBIPCommand(IntEnum):
    """USBIP protocol commands."""
    OP_REQ_DEVLIST = 0x8005
    OP_REP_DEVLIST = 0x0005
    OP_REQ_IMPORT = 0x8003
    OP_REP_IMPORT = 0x0003
    USBIP_CMD_SUBMIT = 0x00000001
    USBIP_RET_SUBMIT = 0x00000003
    USBIP_CMD_UNLINK = 0x00000002
    USBIP_RET_UNLINK = 0x00000004

class USBIPStatus(IntEnum):
    """USBIP status codes."""
    ST_OK = 0x00000000
    ST_NA = 0x00000001  # Not available
    ST_DEV_BUSY = 0x00000002
    ST_DEV_ERR = 0x00000003
    ST_NODEV = 0x00000004
    ST_ERROR = 0x00000005


# =============================================================================
# USB CONSTANTS
# =============================================================================

class USBSpeed(IntEnum):
    LOW = 1
    FULL = 2
    HIGH = 3
    WIRELESS = 4
    SUPER = 5
    SUPER_PLUS = 6


# =============================================================================
# USBIP STRUCTURES
# =============================================================================

@dataclass
class USBIPHeader:
    """USBIP header structure."""
    command: int
    seqnum: int
    devid: int
    direction: int
    ep: int

    @classmethod
    def unpack(cls, data: bytes) -> 'USBIPHeader':
        command, seqnum, devid, direction, ep = struct.unpack('>IIIII', data[:20])
        return cls(command, seqnum, devid, direction, ep)

    def pack(self) -> bytes:
        return struct.pack('>IIIII',
            self.command, self.seqnum, self.devid, self.direction, self.ep)


@dataclass
class USBIPSubmit:
    """USBIP URB submit structure."""
    header: USBIPHeader
    transfer_flags: int
    transfer_buffer_length: int
    start_frame: int
    number_of_packets: int
    interval: int
    setup: bytes

    @classmethod
    def unpack(cls, data: bytes) -> 'USBIPSubmit':
        header = USBIPHeader.unpack(data[:20])
        transfer_flags, transfer_buffer_length = struct.unpack('>II', data[20:28])
        start_frame, number_of_packets, interval = struct.unpack('>III', data[28:40])
        setup = data[40:48]
        return cls(header, transfer_flags, transfer_buffer_length,
                  start_frame, number_of_packets, interval, setup)


@dataclass
class USBDevice:
    """USB device information for USBIP."""
    path: str = "/sys/devices/pci0000:00/0000:00:01.2/usb1/1-1"
    busid: str = "1-1"
    busnum: int = 1
    devnum: int = 1
    speed: int = USBSpeed.FULL
    idVendor: int = 0x0483
    idProduct: int = 0x5740
    bcdDevice: int = 0x0200
    bDeviceClass: int = 0x02
    bDeviceSubClass: int = 0x02
    bDeviceProtocol: int = 0x00
    bConfigurationValue: int = 1
    bNumConfigurations: int = 1
    bNumInterfaces: int = 2

    def pack_device_info(self) -> bytes:
        """Pack device info for OP_REP_DEVLIST."""
        path_bytes = self.path.encode('utf-8')[:256].ljust(256, b'\x00')
        busid_bytes = self.busid.encode('utf-8')[:32].ljust(32, b'\x00')

        # USBIP device info structure (per Linux usbip_usb_device):
        # busnum(4) + devnum(4) + speed(4) + idVendor(2) + idProduct(2) +
        # bcdDevice(2) + bDeviceClass(1) + bDeviceSubClass(1) + bDeviceProtocol(1) +
        # bConfigurationValue(1) + bNumConfigurations(1) + bNumInterfaces(1)
        return (
            path_bytes +
            busid_bytes +
            struct.pack('>IIIHHHBBBBBB',
                self.busnum,
                self.devnum,
                self.speed,
                self.idVendor,
                self.idProduct,
                self.bcdDevice,
                self.bDeviceClass,
                self.bDeviceSubClass,
                self.bDeviceProtocol,
                self.bConfigurationValue,
                self.bNumConfigurations,
                self.bNumInterfaces
            )
        )

    def pack_interface_info(self) -> bytes:
        """Pack interface info for device list."""
        interfaces = bytes()
        # Interface 0: CDC Control
        interfaces += struct.pack('>BBBB', 0x02, 0x02, 0x01, 0x00)
        # Interface 1: CDC Data
        interfaces += struct.pack('>BBBB', 0x0A, 0x00, 0x00, 0x00)
        return interfaces


# =============================================================================
# CDC-ACM DEVICE EMULATION
# =============================================================================

class CDCACMDevice:
    """
    CDC-ACM (Virtual COM Port) device emulation.

    Implements USB requests and data transfer for CDC-ACM class.
    """

    # Device descriptor
    DEVICE_DESC = bytes([
        18, 0x01, 0x00, 0x02, 0x02, 0x02, 0x00, 64,
        0x83, 0x04, 0x40, 0x57, 0x00, 0x02, 1, 2, 3, 1
    ])

    # Configuration descriptor (full)
    CONFIG_DESC = bytes([
        # Configuration
        9, 0x02, 67, 0, 2, 1, 0, 0xC0, 50,
        # Interface 0: CDC Control
        9, 0x04, 0, 0, 1, 0x02, 0x02, 0x01, 0,
        # CDC Header
        5, 0x24, 0x00, 0x10, 0x01,
        # CDC Call Management
        5, 0x24, 0x01, 0x00, 1,
        # CDC ACM
        4, 0x24, 0x02, 0x02,
        # CDC Union
        5, 0x24, 0x06, 0, 1,
        # Notification EP
        7, 0x05, 0x82, 0x03, 8, 0, 16,
        # Interface 1: CDC Data
        9, 0x04, 1, 0, 2, 0x0A, 0x00, 0x00, 0,
        # Data OUT EP
        7, 0x05, 0x01, 0x02, 64, 0, 0,
        # Data IN EP
        7, 0x05, 0x81, 0x02, 64, 0, 0,
    ])

    STRING_LANGID = bytes([4, 0x03, 0x09, 0x04])

    def __init__(self):
        self.address = 0
        self.configured = False
        self.line_coding = bytes([0x00, 0xC2, 0x01, 0x00, 0x00, 0x00, 0x08])  # 115200 8N1
        self.control_line_state = 0

        # Echo buffer
        self.rx_buffer: List[int] = []
        self.tx_buffer: List[int] = []

        self.log = logging.getLogger('CDC')

    def get_string_desc(self, index: int) -> bytes:
        """Get string descriptor."""
        strings = [
            self.STRING_LANGID,
            "Twisted Wires".encode('utf-16-le'),
            "MCUemu CDC-ACM".encode('utf-16-le'),
            "000001".encode('utf-16-le'),
        ]
        if index == 0:
            return strings[0]
        elif index < len(strings):
            data = strings[index]
            return bytes([len(data) + 2, 0x03]) + data
        return bytes([2, 0x03])

    def handle_control(self, setup: bytes, data: bytes = b'') -> bytes:
        """Handle USB control transfer."""
        bmRequestType = setup[0]
        bRequest = setup[1]
        wValue = setup[2] | (setup[3] << 8)
        wIndex = setup[4] | (setup[5] << 8)
        wLength = setup[6] | (setup[7] << 8)

        self.log.debug(f"Control: type=0x{bmRequestType:02X} req=0x{bRequest:02X} "
                      f"val=0x{wValue:04X} idx=0x{wIndex:04X} len={wLength}")

        # Standard requests (host to device)
        if bmRequestType == 0x00:
            if bRequest == 0x05:  # SET_ADDRESS
                self.address = wValue & 0x7F
                self.log.info(f"SET_ADDRESS: {self.address}")
                return bytes()
            elif bRequest == 0x09:  # SET_CONFIGURATION
                self.configured = True
                self.log.info(f"SET_CONFIGURATION: {wValue}")
                return bytes()

        # Standard requests (device to host)
        elif bmRequestType == 0x80:
            if bRequest == 0x06:  # GET_DESCRIPTOR
                desc_type = (wValue >> 8) & 0xFF
                desc_index = wValue & 0xFF
                if desc_type == 0x01:  # Device
                    return self.DEVICE_DESC[:wLength]
                elif desc_type == 0x02:  # Configuration
                    return self.CONFIG_DESC[:wLength]
                elif desc_type == 0x03:  # String
                    return self.get_string_desc(desc_index)[:wLength]
            elif bRequest == 0x00:  # GET_STATUS
                return bytes([0x00, 0x00])

        # CDC class requests (host to device)
        elif bmRequestType == 0x21:
            if bRequest == 0x20:  # SET_LINE_CODING
                if data:
                    self.line_coding = data[:7]
                    self.log.info(f"SET_LINE_CODING: {self.line_coding.hex()}")
                return bytes()
            elif bRequest == 0x22:  # SET_CONTROL_LINE_STATE
                self.control_line_state = wValue
                self.log.info(f"SET_CONTROL_LINE_STATE: DTR={(wValue&1)!=0} RTS={(wValue&2)!=0}")
                return bytes()

        # CDC class requests (device to host)
        elif bmRequestType == 0xA1:
            if bRequest == 0x21:  # GET_LINE_CODING
                return self.line_coding[:wLength]

        self.log.warning(f"Unknown control request: type=0x{bmRequestType:02X} req=0x{bRequest:02X}")
        return bytes()

    def handle_data_out(self, ep: int, data: bytes) -> int:
        """Handle data received from host (OUT transfer)."""
        if ep == 1:  # CDC data endpoint
            # Echo mode - store received data
            self.tx_buffer.extend(data)
            self.log.info(f"RX[EP{ep}]: {data.hex()} ({data!r})")
            return len(data)
        return 0

    def handle_data_in(self, ep: int, max_len: int) -> bytes:
        """Handle data to send to host (IN transfer)."""
        if ep == 1:  # CDC data endpoint
            # Echo mode - return stored data
            if self.tx_buffer:
                data = bytes(self.tx_buffer[:max_len])
                self.tx_buffer = self.tx_buffer[max_len:]
                self.log.info(f"TX[EP{ep}]: {data.hex()} ({data!r})")
                return data
        elif ep == 2:  # Notification endpoint
            # No notifications pending
            pass
        return bytes()


# =============================================================================
# USBIP SERVER
# =============================================================================

class USBIPServer:
    """
    USBIP Server implementation.

    Exposes the emulated USB device to the host via USBIP protocol.
    Compatible with Linux usbip client.
    """

    def __init__(self, port: int = 3240):
        self.port = port
        self.server = None
        self.device = CDCACMDevice()
        self.device_info = USBDevice()
        self.imported = False
        self.usb_peripheral = None
        self.log = logging.getLogger('USBIP')

    def set_usb_peripheral(self, peripheral: 'USBDeviceProtocol'):
        """Link to USB peripheral for firmware-in-the-loop injection.

        The peripheral must implement the ``USBDeviceProtocol`` interface
        (see ``slab_peripherals.usb_controller``): inject_vbus(),
        inject_usbrst(), inject_enumdne(), inject_setup_packet(),
        wait_ep0_response(), inject_out_data(), and optionally is_ready().

        Compatible with DWC2 OTG, PMA USB FS, and RP2040 USB controllers.
        """
        self.usb_peripheral = peripheral
        self.log.info(f"Linked to USB peripheral: {type(peripheral).__name__}")

    async def handle_client(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter):
        """Handle USBIP client connection."""
        addr = writer.get_extra_info('peername')
        self.log.info(f"Client connected: {addr}")
        imported = False

        try:
            while True:
                if not imported:
                    # Discovery mode: version(2) + command(2) + status(4) = 8 bytes
                    header = await reader.readexactly(8)

                    version, command, status = struct.unpack('>HHI', header)
                    self.log.debug(f"Command: 0x{command:04X} version=0x{version:04X}")

                    if command == USBIPCommand.OP_REQ_DEVLIST:
                        await self.handle_devlist(reader, writer)

                    elif command == USBIPCommand.OP_REQ_IMPORT:
                        if await self.handle_import(reader, writer):
                            imported = True

                    else:
                        self.log.warning(f"Unknown command: 0x{command:04X}")
                        break
                else:
                    # Attached mode: command(4) is first field of 48-byte header
                    header = await reader.readexactly(4)

                    command = struct.unpack('>I', header)[0]
                    self.log.debug(f"URB Command: 0x{command:08X}")

                    if command == USBIPCommand.USBIP_CMD_SUBMIT:
                        await self.handle_submit(reader, writer, header)

                    elif command == USBIPCommand.USBIP_CMD_UNLINK:
                        await self.handle_unlink(reader, writer, header)

                    else:
                        self.log.warning(f"Unknown URB command: 0x{command:08X}")
                        break

        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            self.log.error(f"Error: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            self.log.info("Client disconnected")

    async def handle_devlist(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        """Handle OP_REQ_DEVLIST - list available devices."""
        self.log.info("OP_REQ_DEVLIST")

        # Response header (8 bytes: version(2) + command(2) + status(4))
        response = struct.pack('>HHI',
            USBIP_VERSION,
            USBIPCommand.OP_REP_DEVLIST,
            USBIPStatus.ST_OK
        )

        # Number of devices
        response += struct.pack('>I', 1)

        # Device info
        response += self.device_info.pack_device_info()

        # Interface info
        response += self.device_info.pack_interface_info()

        writer.write(response)
        await writer.drain()

    async def handle_import(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> bool:
        """Handle OP_REQ_IMPORT - attach device. Returns True if successful.

        IMPORTANT: The USB connection sequence (VBUS/USBRST/ENUMDNE) is injected
        BEFORE sending the OP_REP_IMPORT response. This ensures the firmware has
        fully initialized its USB stack before the host starts sending URBs.
        The usbip client blocks on recv() until we respond, so no URBs can arrive
        during the inject sequence.
        """
        # Read busid (exactly 32 bytes in USBIP protocol)
        busid_data = await reader.readexactly(32)
        busid = busid_data.rstrip(b'\x00').decode('utf-8')
        self.log.info(f"OP_REQ_IMPORT: {busid}")

        if busid != self.device_info.busid:
            # Device not found
            response = struct.pack('>HHI',
                USBIP_VERSION,
                USBIPCommand.OP_REP_IMPORT,
                USBIPStatus.ST_NODEV
            )
            writer.write(response)
            await writer.drain()
            self.log.warning(f"Device not found: {busid}")
            return False

        # Inject USB connection sequence into peripheral BEFORE responding.
        # The usbip client is blocking on recv(), so no URBs will arrive yet.
        if self.usb_peripheral:
            # Wait for firmware to initialize USB (poll is_ready if available)
            if hasattr(self.usb_peripheral, 'is_ready'):
                self.log.info("Waiting for firmware USB initialization...")
                for _ in range(100):  # Up to 10 seconds
                    if self.usb_peripheral.is_ready():
                        break
                    await asyncio.sleep(0.1)
                else:
                    self.log.warning("Firmware USB init timeout -- proceeding anyway")
                self.log.info("Firmware USB initialized")

            # 1. Assert VBUS (cable plugged in)
            self.usb_peripheral.inject_vbus(connected=True)
            self.log.info("Waiting for firmware to detect VBUS...")
            await asyncio.sleep(0.3)
            # 2. Bus reset (host resets device)
            self.usb_peripheral.inject_usbrst()
            self.log.info("Waiting for firmware to process USBRST...")
            await asyncio.sleep(0.5)
            # 3. Enumeration done (speed negotiation complete)
            self.usb_peripheral.inject_enumdne()
            self.log.info("Waiting for firmware to process ENUMDNE...")
            await asyncio.sleep(0.5)

            # 4. Wait for firmware to be ready again after reset sequence
            if hasattr(self.usb_peripheral, 'is_ready'):
                for _ in range(50):  # Up to 5 seconds
                    if self.usb_peripheral.is_ready():
                        break
                    await asyncio.sleep(0.1)
                else:
                    self.log.warning("Firmware post-reset init timeout")

            self.log.info("Firmware USB init complete, sending import response")

        # NOW send the import response - firmware is ready for URBs
        response = struct.pack('>HHI',
            USBIP_VERSION,
            USBIPCommand.OP_REP_IMPORT,
            USBIPStatus.ST_OK
        )
        response += self.device_info.pack_device_info()
        writer.write(response)
        await writer.drain()

        self.imported = True
        self.log.info("Device imported successfully")
        return True

    def _decode_setup(self, setup: bytes) -> str:
        """Decode USB SETUP packet into human-readable string."""
        if len(setup) < 8:
            return f"<invalid {setup.hex()}>"
        bmRequestType = setup[0]
        bRequest = setup[1]
        wValue = setup[2] | (setup[3] << 8)
        wIndex = setup[4] | (setup[5] << 8)
        wLength = setup[6] | (setup[7] << 8)

        # Decode standard requests
        req_type = (bmRequestType >> 5) & 0x03
        direction = "IN" if bmRequestType & 0x80 else "OUT"

        if req_type == 0:  # Standard
            names = {
                0x00: "GET_STATUS",
                0x01: "CLEAR_FEATURE",
                0x03: "SET_FEATURE",
                0x05: f"SET_ADDRESS({wValue})",
                0x06: self._decode_get_descriptor(wValue, wLength),
                0x08: "GET_CONFIGURATION",
                0x09: f"SET_CONFIGURATION({wValue})",
                0x0B: f"SET_INTERFACE({wValue})",
            }
            name = names.get(bRequest, f"STD_0x{bRequest:02X}")
        elif req_type == 1:  # Class
            names = {
                0x20: "SET_LINE_CODING",
                0x21: "GET_LINE_CODING",
                0x22: f"SET_CONTROL_LINE_STATE(0x{wValue:04X})",
                0x23: "SEND_BREAK",
            }
            name = names.get(bRequest, f"CLASS_0x{bRequest:02X}")
        else:
            name = f"VENDOR_0x{bRequest:02X}"

        return f"{direction} {name} wIdx=0x{wIndex:04X} wLen={wLength}"

    def _decode_get_descriptor(self, wValue: int, wLength: int) -> str:
        """Decode GET_DESCRIPTOR wValue."""
        desc_type = (wValue >> 8) & 0xFF
        desc_index = wValue & 0xFF
        type_names = {
            1: "Device", 2: "Configuration", 3: f"String({desc_index})",
            6: "DeviceQualifier", 9: "OTG", 10: "Debug",
        }
        name = type_names.get(desc_type, f"0x{desc_type:02X}")
        return f"GET_DESCRIPTOR({name}, len={wLength})"

    async def handle_submit(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter, header: bytes):
        """Handle USBIP_CMD_SUBMIT - USB request submission."""
        # header contains command(4), need to read remaining 44 bytes for 48-byte total header
        submit_data = header + await reader.readexactly(44)
        submit = USBIPSubmit.unpack(submit_data)

        # Read transfer buffer (for OUT transfers)
        transfer_data = bytes()
        if submit.header.direction == 0 and submit.transfer_buffer_length > 0:
            transfer_data = await reader.readexactly(submit.transfer_buffer_length)

        # Decode and log the SETUP packet for EP0
        setup_desc = ""
        if submit.header.ep == 0:
            setup_desc = self._decode_setup(submit.setup)
            self.log.info(f"CMD_SUBMIT seq={submit.header.seqnum} EP0 {setup_desc}")
        else:
            dir_str = "IN" if submit.header.direction else "OUT"
            self.log.info(f"CMD_SUBMIT seq={submit.header.seqnum} EP{submit.header.ep} "
                         f"{dir_str} len={submit.transfer_buffer_length}")

        response_data = bytes()
        actual_length = 0
        status = 0
        source = "none"

        if submit.header.ep == 0 and self.usb_peripheral:
            # Firmware-in-the-loop path
            if submit.header.direction == 1:  # IN (device to host)
                # Inject SETUP, wait for firmware to respond via EP0 IN
                self.usb_peripheral.inject_setup_packet(submit.setup)
                response_data = await self.usb_peripheral.wait_ep0_response(timeout=5.0)
                actual_length = len(response_data)
                # Inject STATUS OUT ZLP to complete the control transfer
                # (USBIP wraps all 3 phases into one CMD_SUBMIT/RET_SUBMIT)
                if actual_length > 0:
                    await asyncio.sleep(0.01)
                    self.usb_peripheral.inject_out_data(0, b'')
                source = "firmware"
            else:  # OUT (host to device)
                # Inject SETUP into firmware
                self.usb_peripheral.inject_setup_packet(submit.setup)
                if len(transfer_data) > 0:
                    # OUT data phase: inject data after a short delay
                    # (firmware needs time to arm EP0 OUT)
                    await asyncio.sleep(0.05)
                    self.usb_peripheral.inject_out_data(0, transfer_data)
                # Don't wait for ZLP -- respond immediately
                actual_length = 0
                source = "firmware"

        elif submit.header.ep == 0:
            # No peripheral linked: fallback to CDCACMDevice
            if submit.header.direction == 0:  # OUT
                self.device.handle_control(submit.setup, transfer_data)
                actual_length = 0
            else:  # IN
                response_data = self.device.handle_control(submit.setup)
                actual_length = len(response_data)
            source = "fallback"

        else:
            # Bulk/interrupt endpoints: use CDCACMDevice
            ep = submit.header.ep
            if submit.header.direction == 0:  # OUT
                actual_length = self.device.handle_data_out(ep, transfer_data)
            else:  # IN
                response_data = self.device.handle_data_in(ep, submit.transfer_buffer_length)
                actual_length = len(response_data)
            source = "fallback"

        # Cap actual_length to transfer_buffer_length (USBIP protocol requirement)
        actual_length = min(actual_length, submit.transfer_buffer_length)

        # Log response
        if actual_length > 0:
            data_hex = response_data[:32].hex()
            suffix = "..." if len(response_data) > 32 else ""
            self.log.info(f"RET_SUBMIT seq={submit.header.seqnum} [{source}] "
                         f"{actual_length} bytes: {data_hex}{suffix}")
        else:
            self.log.info(f"RET_SUBMIT seq={submit.header.seqnum} [{source}] status={status}")

        # Build response
        response = struct.pack('>IIIII',
            USBIPCommand.USBIP_RET_SUBMIT,
            submit.header.seqnum,
            submit.header.devid,
            submit.header.direction,
            submit.header.ep
        )
        response += struct.pack('>iIIIIxxxxxxxx',
            status,  # status
            actual_length,  # actual_length
            0,  # start_frame
            0,  # number_of_packets
            0   # error_count
        )
        # Per USBIP protocol (Linux kernel vhci_rx.c): only send actual_length bytes
        response += response_data[:actual_length] if submit.header.direction and actual_length > 0 else b''

        writer.write(response)
        await writer.drain()

    async def handle_unlink(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter, header: bytes):
        """Handle USBIP_CMD_UNLINK - cancel pending request."""
        # header contains command(4), read remaining 44 bytes for 48-byte total
        # USBIP_CMD_UNLINK: command(4) + seqnum(4) + devid(4) + direction(4) + ep(4) +
        #                   seqnum_to_unlink(4) + padding(24)
        unlink_data = header + await reader.readexactly(44)
        seqnum = struct.unpack('>I', unlink_data[4:8])[0]
        seqnum_to_unlink = struct.unpack('>I', unlink_data[20:24])[0]
        self.log.info(f"UNLINK: seqnum={seqnum} unlink_seqnum={seqnum_to_unlink}")

        # Send unlink response (48 bytes total: basic(20) + status(4) + padding(24))
        response = struct.pack('>IIIII',
            USBIPCommand.USBIP_RET_UNLINK,
            seqnum,
            0, 0, 0  # devid, direction, ep
        )
        response += struct.pack('>i', -104)  # -ECONNRESET
        response += bytes(24)  # padding to reach 48 bytes total

        writer.write(response)
        await writer.drain()

    async def start(self):
        """Start the USBIP server."""
        self.server = await asyncio.start_server(
            self.handle_client, '0.0.0.0', self.port,
            reuse_address=True
        )
        self.log.info(f"USBIP server started on port {self.port}")
        self.log.info(f"Device: {self.device_info.busid} (VID:PID {self.device_info.idVendor:04X}:{self.device_info.idProduct:04X})")
        self.log.info("To attach: sudo usbip attach -r localhost -b 1-1")

        async with self.server:
            await self.server.serve_forever()

    async def stop(self):
        """Stop the server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()


# =============================================================================
# MAIN
# =============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description='MCUemu USBIP Server')
    parser.add_argument('--port', type=int, default=3240,
                       help='USBIP port (default: 3240)')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Verbose output')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s [%(levelname)5s] %(name)-8s: %(message)s'
    )

    server = USBIPServer(port=args.port)

    try:
        await server.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await server.stop()


if __name__ == '__main__':
    asyncio.run(main())
