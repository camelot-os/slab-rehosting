#!/usr/bin/env python3
"""
USBIP Client - Pure Python Implementation

A complete USBIP client for testing USB device emulation.
Can connect to:
- Real USBIP servers (usbipd on Linux)
- Slab's USB OTG emulator in device mode
- Any USBIP-compatible server

Features:
- Device enumeration
- Device import/attachment
- Control transfers
- Bulk transfers
- Interrupt transfers
- CDC-ACM serial communication
- HID input handling

Usage:
    # List devices
    python3 usbip_client.py list --host localhost

    # Attach and enumerate device
    python3 usbip_client.py attach --host localhost --busid 1-1

    # Test CDC-ACM serial device
    python3 usbip_client.py cdc --host localhost --busid 1-1

    # Test HID keyboard device (polls for key reports)
    python3 usbip_client.py hid --host localhost --busid 1-1

    # Test HID keyboard with duration limit
    python3 usbip_client.py hid --host localhost --busid 1-1 --duration 10

    # Interactive shell
    python3 usbip_client.py shell --host localhost --busid 1-1

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 Twisted Wires Security Lab
"""

import socket
import struct
import time
import argparse
import sys
import threading
from typing import Optional, List, Tuple, Dict, Any
from dataclasses import dataclass
from enum import IntEnum
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# USBIP Protocol Constants
# =============================================================================

USBIP_VERSION = 0x0111

class USBIPOp(IntEnum):
    REQ_DEVLIST = 0x8005
    REP_DEVLIST = 0x0005
    REQ_IMPORT = 0x8003
    REP_IMPORT = 0x0003
    CMD_SUBMIT = 0x0001
    RET_SUBMIT = 0x0003
    CMD_UNLINK = 0x0002
    RET_UNLINK = 0x0004


class USBRequest(IntEnum):
    GET_STATUS = 0x00
    CLEAR_FEATURE = 0x01
    SET_FEATURE = 0x03
    SET_ADDRESS = 0x05
    GET_DESCRIPTOR = 0x06
    SET_CONFIGURATION = 0x09
    GET_INTERFACE = 0x0A
    SET_INTERFACE = 0x0B


class DescriptorType(IntEnum):
    DEVICE = 1
    CONFIGURATION = 2
    STRING = 3
    INTERFACE = 4
    ENDPOINT = 5


class CDCRequest(IntEnum):
    SET_LINE_CODING = 0x20
    GET_LINE_CODING = 0x21
    SET_CONTROL_LINE_STATE = 0x22


class HIDRequest(IntEnum):
    GET_REPORT = 0x01
    GET_IDLE = 0x02
    GET_PROTOCOL = 0x03
    SET_REPORT = 0x09
    SET_IDLE = 0x0A
    SET_PROTOCOL = 0x0B


class HIDReportType(IntEnum):
    INPUT = 1
    OUTPUT = 2
    FEATURE = 3


# HID Keyboard Modifier Keys (bit flags)
class HIDModifier(IntEnum):
    LEFT_CTRL = 0x01
    LEFT_SHIFT = 0x02
    LEFT_ALT = 0x04
    LEFT_GUI = 0x08
    RIGHT_CTRL = 0x10
    RIGHT_SHIFT = 0x20
    RIGHT_ALT = 0x40
    RIGHT_GUI = 0x80


# HID Keyboard Usage IDs (scan codes)
HID_KEY_NONE = 0x00
HID_KEY_A = 0x04
HID_KEY_B = 0x05
HID_KEY_C = 0x06
HID_KEY_D = 0x07
HID_KEY_E = 0x08
HID_KEY_F = 0x09
HID_KEY_G = 0x0A
HID_KEY_H = 0x0B
HID_KEY_I = 0x0C
HID_KEY_J = 0x0D
HID_KEY_K = 0x0E
HID_KEY_L = 0x0F
HID_KEY_M = 0x10
HID_KEY_N = 0x11
HID_KEY_O = 0x12
HID_KEY_P = 0x13
HID_KEY_Q = 0x14
HID_KEY_R = 0x15
HID_KEY_S = 0x16
HID_KEY_T = 0x17
HID_KEY_U = 0x18
HID_KEY_V = 0x19
HID_KEY_W = 0x1A
HID_KEY_X = 0x1B
HID_KEY_Y = 0x1C
HID_KEY_Z = 0x1D
HID_KEY_1 = 0x1E
HID_KEY_2 = 0x1F
HID_KEY_3 = 0x20
HID_KEY_4 = 0x21
HID_KEY_5 = 0x22
HID_KEY_6 = 0x23
HID_KEY_7 = 0x24
HID_KEY_8 = 0x25
HID_KEY_9 = 0x26
HID_KEY_0 = 0x27
HID_KEY_ENTER = 0x28
HID_KEY_ESCAPE = 0x29
HID_KEY_BACKSPACE = 0x2A
HID_KEY_TAB = 0x2B
HID_KEY_SPACE = 0x2C
HID_KEY_MINUS = 0x2D
HID_KEY_EQUAL = 0x2E
HID_KEY_LEFTBRACE = 0x2F
HID_KEY_RIGHTBRACE = 0x30
HID_KEY_BACKSLASH = 0x31
HID_KEY_SEMICOLON = 0x33
HID_KEY_APOSTROPHE = 0x34
HID_KEY_GRAVE = 0x35
HID_KEY_COMMA = 0x36
HID_KEY_DOT = 0x37
HID_KEY_SLASH = 0x38
HID_KEY_CAPSLOCK = 0x39
HID_KEY_F1 = 0x3A
HID_KEY_F2 = 0x3B
HID_KEY_F3 = 0x3C
HID_KEY_F4 = 0x3D
HID_KEY_F5 = 0x3E
HID_KEY_F6 = 0x3F
HID_KEY_F7 = 0x40
HID_KEY_F8 = 0x41
HID_KEY_F9 = 0x42
HID_KEY_F10 = 0x43
HID_KEY_F11 = 0x44
HID_KEY_F12 = 0x45

# Lookup table: HID usage ID to ASCII character
HID_KEY_TO_CHAR = {
    HID_KEY_A: 'a', HID_KEY_B: 'b', HID_KEY_C: 'c', HID_KEY_D: 'd',
    HID_KEY_E: 'e', HID_KEY_F: 'f', HID_KEY_G: 'g', HID_KEY_H: 'h',
    HID_KEY_I: 'i', HID_KEY_J: 'j', HID_KEY_K: 'k', HID_KEY_L: 'l',
    HID_KEY_M: 'm', HID_KEY_N: 'n', HID_KEY_O: 'o', HID_KEY_P: 'p',
    HID_KEY_Q: 'q', HID_KEY_R: 'r', HID_KEY_S: 's', HID_KEY_T: 't',
    HID_KEY_U: 'u', HID_KEY_V: 'v', HID_KEY_W: 'w', HID_KEY_X: 'x',
    HID_KEY_Y: 'y', HID_KEY_Z: 'z',
    HID_KEY_1: '1', HID_KEY_2: '2', HID_KEY_3: '3', HID_KEY_4: '4',
    HID_KEY_5: '5', HID_KEY_6: '6', HID_KEY_7: '7', HID_KEY_8: '8',
    HID_KEY_9: '9', HID_KEY_0: '0',
    HID_KEY_ENTER: '\n', HID_KEY_SPACE: ' ', HID_KEY_TAB: '\t',
    HID_KEY_MINUS: '-', HID_KEY_EQUAL: '=',
    HID_KEY_LEFTBRACE: '[', HID_KEY_RIGHTBRACE: ']',
    HID_KEY_BACKSLASH: '\\', HID_KEY_SEMICOLON: ';',
    HID_KEY_APOSTROPHE: "'", HID_KEY_GRAVE: '`',
    HID_KEY_COMMA: ',', HID_KEY_DOT: '.', HID_KEY_SLASH: '/',
}

# Shifted versions
HID_KEY_TO_CHAR_SHIFT = {
    HID_KEY_A: 'A', HID_KEY_B: 'B', HID_KEY_C: 'C', HID_KEY_D: 'D',
    HID_KEY_E: 'E', HID_KEY_F: 'F', HID_KEY_G: 'G', HID_KEY_H: 'H',
    HID_KEY_I: 'I', HID_KEY_J: 'J', HID_KEY_K: 'K', HID_KEY_L: 'L',
    HID_KEY_M: 'M', HID_KEY_N: 'N', HID_KEY_O: 'O', HID_KEY_P: 'P',
    HID_KEY_Q: 'Q', HID_KEY_R: 'R', HID_KEY_S: 'S', HID_KEY_T: 'T',
    HID_KEY_U: 'U', HID_KEY_V: 'V', HID_KEY_W: 'W', HID_KEY_X: 'X',
    HID_KEY_Y: 'Y', HID_KEY_Z: 'Z',
    HID_KEY_1: '!', HID_KEY_2: '@', HID_KEY_3: '#', HID_KEY_4: '$',
    HID_KEY_5: '%', HID_KEY_6: '^', HID_KEY_7: '&', HID_KEY_8: '*',
    HID_KEY_9: '(', HID_KEY_0: ')',
    HID_KEY_MINUS: '_', HID_KEY_EQUAL: '+',
    HID_KEY_LEFTBRACE: '{', HID_KEY_RIGHTBRACE: '}',
    HID_KEY_BACKSLASH: '|', HID_KEY_SEMICOLON: ':',
    HID_KEY_APOSTROPHE: '"', HID_KEY_GRAVE: '~',
    HID_KEY_COMMA: '<', HID_KEY_DOT: '>', HID_KEY_SLASH: '?',
}


@dataclass
class USBIPDevice:
    """Parsed USBIP device info."""
    path: str
    busid: str
    busnum: int
    devnum: int
    speed: int
    vendor_id: int
    product_id: int
    device_class: int
    device_subclass: int
    device_protocol: int
    configuration: int
    num_configurations: int

    def __str__(self):
        return (f"{self.busid}: {self.vendor_id:04x}:{self.product_id:04x} "
                f"(class {self.device_class:02x}/{self.device_subclass:02x})")


class USBIPClient:
    """
    Pure Python USBIP Client.

    Implements the USBIP protocol for attaching to remote USB devices.
    """

    def __init__(self, host: str = "localhost", port: int = 3240):
        self.host = host
        self.port = port
        self.sock: Optional[socket.socket] = None
        self.seqnum = 0
        self.device: Optional[USBIPDevice] = None
        self.configuration_desc: bytes = b''
        self._recv_lock = threading.Lock()

    def connect(self):
        """Connect to USBIP server."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5.0)
        try:
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to USBIP server at {self.host}:{self.port}")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def disconnect(self):
        """Disconnect from USBIP server."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self.device = None

    def _recv_exact(self, size: int) -> bytes:
        """Receive exactly size bytes."""
        with self._recv_lock:
            data = b''
            remaining = size
            while remaining > 0:
                try:
                    chunk = self.sock.recv(remaining)
                    if not chunk:
                        raise ConnectionError("Connection closed")
                    data += chunk
                    remaining -= len(chunk)
                except socket.timeout:
                    raise TimeoutError("Receive timeout")
            return data

    def list_devices(self) -> List[USBIPDevice]:
        """
        List available devices on USBIP server.

        Returns:
            List of USBIPDevice objects
        """
        if not self.sock:
            self.connect()

        # Send device list request
        # Standard USB/IP header: version(2) + command(2) + status(4)
        req = struct.pack(">HHI",
            USBIP_VERSION,
            USBIPOp.REQ_DEVLIST,
            0   # status
        )
        self.sock.sendall(req)

        # Receive response header
        resp = self._recv_exact(12)
        version, opcode, status, num_devices = struct.unpack(">HHII", resp)

        if opcode != USBIPOp.REP_DEVLIST:
            raise RuntimeError(f"Unexpected opcode: {opcode}")

        devices = []
        for _ in range(num_devices):
            # Device info structure
            path = self._recv_exact(256).rstrip(b'\x00').decode('ascii', errors='ignore')
            busid = self._recv_exact(32).rstrip(b'\x00').decode('ascii', errors='ignore')

            # Device info: 3xI(12) + 3xH(6) + 6xB(6) = 24 bytes
            dev_info = self._recv_exact(24)
            (busnum, devnum, speed, vid, pid, bcd_device,
             dev_class, dev_subclass, dev_protocol,
             config, num_configs, num_ifs) = struct.unpack(">IIIHHHBBBBBB", dev_info)

            # Interface info (skip for now)
            for _ in range(num_ifs):
                self._recv_exact(4)  # interface class/subclass/protocol + padding

            device = USBIPDevice(
                path=path,
                busid=busid,
                busnum=busnum,
                devnum=devnum,
                speed=speed,
                vendor_id=vid,
                product_id=pid,
                device_class=dev_class,
                device_subclass=dev_subclass,
                device_protocol=dev_protocol,
                configuration=config,
                num_configurations=num_configs
            )
            devices.append(device)

        return devices

    def attach(self, busid: str) -> bool:
        """
        Attach to a device on the USBIP server.

        Args:
            busid: Bus ID of device to attach (e.g., "1-1")

        Returns:
            True if successful
        """
        if not self.sock:
            self.connect()

        # Send import request
        # Standard USB/IP header: version(2) + command(2) + status(4) + busid(32)
        busid_bytes = busid.encode('ascii').ljust(32, b'\x00')
        req = struct.pack(">HHI", USBIP_VERSION, USBIPOp.REQ_IMPORT, 0)
        req += busid_bytes
        self.sock.sendall(req)

        # Receive response header
        resp = self._recv_exact(8)
        version, opcode, status = struct.unpack(">HHI", resp)

        if status != 0:
            raise RuntimeError(f"Import failed with status {status}")

        # Read device info
        path = self._recv_exact(256).rstrip(b'\x00').decode('ascii', errors='ignore')
        busid_resp = self._recv_exact(32).rstrip(b'\x00').decode('ascii', errors='ignore')

        # Device info: 3xI(12) + 3xH(6) + 6xB(6) = 24 bytes
        dev_info = self._recv_exact(24)
        (busnum, devnum, speed, vid, pid, bcd_device,
         dev_class, dev_subclass, dev_protocol,
         config, num_configs, num_ifs) = struct.unpack(">IIIHHHBBBBBB", dev_info)

        self.device = USBIPDevice(
            path=path,
            busid=busid_resp,
            busnum=busnum,
            devnum=devnum,
            speed=speed,
            vendor_id=vid,
            product_id=pid,
            device_class=dev_class,
            device_subclass=dev_subclass,
            device_protocol=dev_protocol,
            configuration=config,
            num_configurations=num_configs
        )

        logger.info(f"Attached to device: {self.device}")
        return True

    def control_transfer(
        self,
        bmRequestType: int,
        bRequest: int,
        wValue: int,
        wIndex: int,
        data: bytes = b'',
        length: int = 0,
        timeout: float = 5.0
    ) -> Tuple[int, bytes]:
        """
        Perform a USB control transfer.

        Args:
            bmRequestType: Request type (direction, type, recipient)
            bRequest: Request code
            wValue: Value field
            wIndex: Index field
            data: Data to send (for OUT transfers)
            length: Expected response length (for IN transfers)
            timeout: Timeout in seconds

        Returns:
            Tuple of (status, data)
        """
        if not self.sock or not self.device:
            raise RuntimeError("Not attached to device")

        self.seqnum += 1
        direction = (bmRequestType >> 7) & 1
        transfer_length = length if direction else len(data)

        # Build setup packet
        setup = struct.pack("<BBHHH",
            bmRequestType, bRequest, wValue, wIndex, transfer_length)

        # Build USBIP submit header (48 bytes total)
        header = struct.pack(">IIIIIIIIII",
            USBIPOp.CMD_SUBMIT,
            self.seqnum,
            (self.device.busnum << 16) | self.device.devnum,
            direction,
            0,  # endpoint 0
            0,  # transfer_flags
            transfer_length,
            0,  # start_frame
            0,  # number_of_packets
            0   # interval
        )
        header += setup  # 8 bytes setup packet

        # Send request
        self.sock.settimeout(timeout)
        self.sock.sendall(header)

        # Send data for OUT transfers
        if not direction and data:
            self.sock.sendall(data)

        # Receive response
        resp = self._recv_exact(48)

        (opcode, resp_seqnum, devid, direction_resp, endpoint,
         status, actual_length, start_frame, num_packets,
         error_count) = struct.unpack(">IIIIIIIIII", resp[:40])

        # Read response data for IN transfers
        result_data = b''
        if direction and actual_length > 0:
            result_data = self._recv_exact(actual_length)

        return status, result_data

    def bulk_transfer(
        self,
        endpoint: int,
        data: bytes = b'',
        length: int = 0,
        timeout: float = 5.0
    ) -> Tuple[int, bytes]:
        """
        Perform a USB bulk transfer.

        Args:
            endpoint: Endpoint address (with direction bit)
            data: Data to send (for OUT endpoints)
            length: Expected response length (for IN endpoints)
            timeout: Timeout in seconds

        Returns:
            Tuple of (status, data)
        """
        if not self.sock or not self.device:
            raise RuntimeError("Not attached to device")

        self.seqnum += 1
        direction = (endpoint >> 7) & 1
        transfer_length = length if direction else len(data)

        # Build USBIP submit header
        header = struct.pack(">IIIIIIIII",
            USBIPOp.CMD_SUBMIT,
            self.seqnum,
            (self.device.busnum << 16) | self.device.devnum,
            direction,
            endpoint,
            0,  # transfer_flags
            transfer_length,
            0,  # start_frame
            0   # number_of_packets
        )
        header += struct.pack(">I", 0)  # interval
        header += b'\x00' * 8  # setup (not used for bulk)

        # Send request
        self.sock.settimeout(timeout)
        self.sock.sendall(header)

        # Send data for OUT transfers
        if not direction and data:
            self.sock.sendall(data)

        # Receive response
        resp = self._recv_exact(48)

        (opcode, resp_seqnum, devid, direction_resp, endpoint_resp,
         status, actual_length, start_frame, num_packets,
         error_count) = struct.unpack(">IIIIIIIIII", resp[:40])

        # Read response data for IN transfers
        result_data = b''
        if direction and actual_length > 0:
            result_data = self._recv_exact(actual_length)

        return status, result_data

    def interrupt_transfer(
        self,
        endpoint: int,
        data: bytes = b'',
        length: int = 0,
        timeout: float = 5.0
    ) -> Tuple[int, bytes]:
        """
        Perform a USB interrupt transfer.

        Args:
            endpoint: Endpoint address (with direction bit)
            data: Data to send (for OUT endpoints)
            length: Expected response length (for IN endpoints)
            timeout: Timeout in seconds

        Returns:
            Tuple of (status, data)
        """
        if not self.sock or not self.device:
            raise RuntimeError("Not attached to device")

        self.seqnum += 1
        direction = (endpoint >> 7) & 1
        transfer_length = length if direction else len(data)

        # Build USBIP submit header (same as bulk, but for interrupt EP)
        header = struct.pack(">IIIIIIIII",
            USBIPOp.CMD_SUBMIT,
            self.seqnum,
            (self.device.busnum << 16) | self.device.devnum,
            direction,
            endpoint,
            0,  # transfer_flags
            transfer_length,
            0,  # start_frame
            0   # number_of_packets
        )
        header += struct.pack(">I", 10)  # interval (ms)
        header += b'\x00' * 8  # setup (not used for interrupt)

        # Send request
        self.sock.settimeout(timeout)
        self.sock.sendall(header)

        # Send data for OUT transfers
        if not direction and data:
            self.sock.sendall(data)

        # Receive response
        resp = self._recv_exact(48)

        (opcode, resp_seqnum, devid, direction_resp, endpoint_resp,
         status, actual_length, start_frame, num_packets,
         error_count) = struct.unpack(">IIIIIIIIII", resp[:40])

        # Read response data for IN transfers
        result_data = b''
        if direction and actual_length > 0:
            result_data = self._recv_exact(actual_length)

        return status, result_data

    # =========================================================================
    # High-level USB operations
    # =========================================================================

    def get_device_descriptor(self) -> bytes:
        """Get device descriptor."""
        status, data = self.control_transfer(
            0x80,  # IN, Standard, Device
            USBRequest.GET_DESCRIPTOR,
            (DescriptorType.DEVICE << 8) | 0,
            0,
            length=18
        )
        return data

    def get_configuration_descriptor(self, index: int = 0) -> bytes:
        """Get configuration descriptor."""
        # First get header to find total length
        status, data = self.control_transfer(
            0x80,
            USBRequest.GET_DESCRIPTOR,
            (DescriptorType.CONFIGURATION << 8) | index,
            0,
            length=9
        )

        if len(data) < 4:
            return data

        total_length = struct.unpack("<H", data[2:4])[0]

        # Get full descriptor
        status, data = self.control_transfer(
            0x80,
            USBRequest.GET_DESCRIPTOR,
            (DescriptorType.CONFIGURATION << 8) | index,
            0,
            length=total_length
        )

        self.configuration_desc = data
        return data

    def get_string_descriptor(self, index: int, lang: int = 0x0409) -> str:
        """Get string descriptor."""
        if index == 0:
            # Language IDs
            status, data = self.control_transfer(
                0x80,
                USBRequest.GET_DESCRIPTOR,
                (DescriptorType.STRING << 8) | 0,
                0,
                length=4
            )
            return data.hex()

        status, data = self.control_transfer(
            0x80,
            USBRequest.GET_DESCRIPTOR,
            (DescriptorType.STRING << 8) | index,
            lang,
            length=255
        )

        if len(data) < 2:
            return ""

        # Decode UTF-16LE string (skip first 2 bytes: length + type)
        try:
            return data[2:].decode('utf-16-le').rstrip('\x00')
        except Exception:
            return data.hex()

    def set_configuration(self, config: int) -> bool:
        """Set device configuration."""
        status, _ = self.control_transfer(
            0x00,  # OUT, Standard, Device
            USBRequest.SET_CONFIGURATION,
            config,
            0
        )
        return status == 0

    def parse_configuration(self) -> Dict[str, Any]:
        """Parse configuration descriptor into structured data."""
        if not self.configuration_desc:
            self.get_configuration_descriptor()

        data = self.configuration_desc
        result = {
            'configuration': {},
            'interfaces': [],
            'endpoints': []
        }

        pos = 0
        current_interface = None

        while pos < len(data):
            if pos + 2 > len(data):
                break

            length = data[pos]
            desc_type = data[pos + 1]

            if length < 2 or pos + length > len(data):
                break

            desc_data = data[pos:pos + length]

            if desc_type == DescriptorType.CONFIGURATION:
                result['configuration'] = {
                    'total_length': struct.unpack("<H", desc_data[2:4])[0],
                    'num_interfaces': desc_data[4],
                    'value': desc_data[5],
                    'max_power': desc_data[8] * 2  # mA
                }

            elif desc_type == DescriptorType.INTERFACE:
                current_interface = {
                    'number': desc_data[2],
                    'alternate': desc_data[3],
                    'num_endpoints': desc_data[4],
                    'class': desc_data[5],
                    'subclass': desc_data[6],
                    'protocol': desc_data[7],
                    'endpoints': []
                }
                result['interfaces'].append(current_interface)

            elif desc_type == DescriptorType.ENDPOINT:
                ep = {
                    'address': desc_data[2],
                    'attributes': desc_data[3],
                    'max_packet': struct.unpack("<H", desc_data[4:6])[0],
                    'interval': desc_data[6]
                }
                result['endpoints'].append(ep)
                if current_interface:
                    current_interface['endpoints'].append(ep)

            pos += length

        return result


class CDCACMClient(USBIPClient):
    """
    CDC-ACM (USB Serial) client.

    Provides serial port-like interface over USBIP.
    """

    def __init__(self, host: str = "localhost", port: int = 3240):
        super().__init__(host, port)
        self.bulk_in_ep = 0x82
        self.bulk_out_ep = 0x02
        self.interrupt_ep = 0x81
        self.interface = 1

        # Line coding (115200 8N1)
        self.baud_rate = 115200
        self.data_bits = 8
        self.parity = 0
        self.stop_bits = 0

    def open(self, busid: str):
        """Open CDC device."""
        self.attach(busid)
        self.set_configuration(1)
        self.set_line_coding()
        self.set_control_line_state(dtr=True, rts=True)

    def set_line_coding(self):
        """Set serial line coding (baud rate, etc.)."""
        data = struct.pack("<IBBB",
            self.baud_rate,
            self.stop_bits,
            self.parity,
            self.data_bits
        )

        self.control_transfer(
            0x21,  # OUT, Class, Interface
            CDCRequest.SET_LINE_CODING,
            0,
            self.interface,
            data=data
        )

    def get_line_coding(self) -> Tuple[int, int, int, int]:
        """Get serial line coding."""
        status, data = self.control_transfer(
            0xA1,  # IN, Class, Interface
            CDCRequest.GET_LINE_CODING,
            0,
            self.interface,
            length=7
        )

        if len(data) >= 7:
            baud, stop, parity, bits = struct.unpack("<IBBB", data)
            return baud, stop, parity, bits

        return 0, 0, 0, 0

    def set_control_line_state(self, dtr: bool = True, rts: bool = True):
        """Set DTR/RTS control lines."""
        value = (1 if dtr else 0) | (2 if rts else 0)

        self.control_transfer(
            0x21,  # OUT, Class, Interface
            CDCRequest.SET_CONTROL_LINE_STATE,
            value,
            self.interface
        )

    def write(self, data: bytes, timeout: float = 5.0) -> int:
        """Write data to CDC device."""
        status, _ = self.bulk_transfer(
            self.bulk_out_ep,
            data=data,
            timeout=timeout
        )
        return len(data) if status == 0 else 0

    def read(self, length: int = 64, timeout: float = 5.0) -> bytes:
        """Read data from CDC device."""
        status, data = self.bulk_transfer(
            self.bulk_in_ep,
            length=length,
            timeout=timeout
        )
        return data if status == 0 else b''

    def readline(self, timeout: float = 5.0) -> str:
        """Read a line from CDC device."""
        data = self.read(256, timeout)
        try:
            return data.decode('utf-8').strip()
        except Exception:
            return data.hex()


@dataclass
class HIDKeyboardReport:
    """Parsed HID keyboard report."""
    modifiers: int
    reserved: int
    keys: List[int]

    @classmethod
    def from_bytes(cls, data: bytes) -> 'HIDKeyboardReport':
        """Parse 8-byte keyboard report."""
        if len(data) < 8:
            data = data + b'\x00' * (8 - len(data))
        return cls(
            modifiers=data[0],
            reserved=data[1],
            keys=list(data[2:8])
        )

    def to_string(self) -> str:
        """Convert report to typed string."""
        shift = bool(self.modifiers & (HIDModifier.LEFT_SHIFT | HIDModifier.RIGHT_SHIFT))
        result = []
        for key in self.keys:
            if key == 0:
                continue
            if shift and key in HID_KEY_TO_CHAR_SHIFT:
                result.append(HID_KEY_TO_CHAR_SHIFT[key])
            elif key in HID_KEY_TO_CHAR:
                result.append(HID_KEY_TO_CHAR[key])
        return ''.join(result)

    def get_pressed_keys(self) -> List[str]:
        """Get list of pressed key names."""
        keys = []
        if self.modifiers & HIDModifier.LEFT_CTRL:
            keys.append("L-Ctrl")
        if self.modifiers & HIDModifier.LEFT_SHIFT:
            keys.append("L-Shift")
        if self.modifiers & HIDModifier.LEFT_ALT:
            keys.append("L-Alt")
        if self.modifiers & HIDModifier.LEFT_GUI:
            keys.append("L-GUI")
        if self.modifiers & HIDModifier.RIGHT_CTRL:
            keys.append("R-Ctrl")
        if self.modifiers & HIDModifier.RIGHT_SHIFT:
            keys.append("R-Shift")
        if self.modifiers & HIDModifier.RIGHT_ALT:
            keys.append("R-Alt")
        if self.modifiers & HIDModifier.RIGHT_GUI:
            keys.append("R-GUI")

        for key in self.keys:
            if key == 0:
                continue
            if key in HID_KEY_TO_CHAR:
                keys.append(f"'{HID_KEY_TO_CHAR[key]}'")
            else:
                keys.append(f"0x{key:02X}")

        return keys

    def __str__(self):
        keys = self.get_pressed_keys()
        return f"Keyboard: [{', '.join(keys) if keys else 'none'}]"


class HIDClient(USBIPClient):
    """
    HID (Human Interface Device) client.

    Supports:
    - Keyboard input reports
    - Mouse input reports (basic)
    - Generic HID reports

    Usage:
        client = HIDClient()
        client.open("1-1")

        # Read keyboard input
        while True:
            report = client.read_keyboard_report()
            if report:
                print(report.to_string())
    """

    def __init__(self, host: str = "localhost", port: int = 3240):
        super().__init__(host, port)
        self.interrupt_in_ep = 0x81  # Default HID interrupt IN endpoint
        self.interface = 0
        self.report_size = 8  # Standard keyboard report size
        self._last_report: Optional[HIDKeyboardReport] = None
        self._typed_text = ""

    def open(self, busid: str):
        """Open HID device."""
        self.attach(busid)

        # Get configuration to find HID interface and endpoints
        config = self.parse_configuration()

        # Find HID interface (class 0x03)
        for iface in config.get('interfaces', []):
            if iface.get('class') == 0x03:  # HID class
                self.interface = iface.get('number', 0)
                # Find interrupt IN endpoint
                for ep in iface.get('endpoints', []):
                    if ep['address'] & 0x80:  # IN endpoint
                        self.interrupt_in_ep = ep['address']
                        self.report_size = ep.get('max_packet', 8)
                        break
                break

        self.set_configuration(1)

        # Set idle rate (0 = report only on change)
        self.set_idle(0)

        logger.info(f"HID device opened: interface={self.interface}, "
                   f"ep=0x{self.interrupt_in_ep:02X}, size={self.report_size}")

    def set_idle(self, duration: int, report_id: int = 0):
        """
        Set idle rate.

        Args:
            duration: Idle duration (0 = infinite, report only on change)
            report_id: Report ID (0 for all reports)
        """
        self.control_transfer(
            0x21,  # OUT, Class, Interface
            HIDRequest.SET_IDLE,
            (duration << 8) | report_id,
            self.interface
        )

    def get_idle(self, report_id: int = 0) -> int:
        """Get idle rate."""
        status, data = self.control_transfer(
            0xA1,  # IN, Class, Interface
            HIDRequest.GET_IDLE,
            report_id,
            self.interface,
            length=1
        )
        return data[0] if data else 0

    def set_protocol(self, protocol: int):
        """
        Set protocol (boot or report).

        Args:
            protocol: 0 = Boot protocol, 1 = Report protocol
        """
        self.control_transfer(
            0x21,  # OUT, Class, Interface
            HIDRequest.SET_PROTOCOL,
            protocol,
            self.interface
        )

    def get_protocol(self) -> int:
        """Get current protocol."""
        status, data = self.control_transfer(
            0xA1,  # IN, Class, Interface
            HIDRequest.GET_PROTOCOL,
            0,
            self.interface,
            length=1
        )
        return data[0] if data else 0

    def get_report(self, report_type: int = HIDReportType.INPUT,
                   report_id: int = 0, length: int = 8) -> bytes:
        """
        Get HID report via control transfer.

        Args:
            report_type: Report type (INPUT, OUTPUT, FEATURE)
            report_id: Report ID
            length: Report length

        Returns:
            Report data
        """
        status, data = self.control_transfer(
            0xA1,  # IN, Class, Interface
            HIDRequest.GET_REPORT,
            (report_type << 8) | report_id,
            self.interface,
            length=length
        )
        return data

    def set_report(self, data: bytes, report_type: int = HIDReportType.OUTPUT,
                   report_id: int = 0):
        """
        Set HID report via control transfer.

        Args:
            data: Report data
            report_type: Report type
            report_id: Report ID
        """
        self.control_transfer(
            0x21,  # OUT, Class, Interface
            HIDRequest.SET_REPORT,
            (report_type << 8) | report_id,
            self.interface,
            data=data
        )

    def read_report(self, timeout: float = 0.1) -> Optional[bytes]:
        """
        Read HID input report via interrupt transfer.

        Args:
            timeout: Timeout in seconds

        Returns:
            Report data or None on timeout
        """
        try:
            status, data = self.interrupt_transfer(
                self.interrupt_in_ep,
                length=self.report_size,
                timeout=timeout
            )
            if status == 0 and data:
                return data
        except TimeoutError:
            pass
        except Exception as e:
            logger.debug(f"Read report error: {e}")
        return None

    def read_keyboard_report(self, timeout: float = 0.1) -> Optional[HIDKeyboardReport]:
        """
        Read and parse keyboard report.

        Args:
            timeout: Timeout in seconds

        Returns:
            HIDKeyboardReport or None
        """
        data = self.read_report(timeout)
        if data:
            report = HIDKeyboardReport.from_bytes(data)
            self._last_report = report
            return report
        return None

    def poll_keyboard(self, callback=None, duration: float = None):
        """
        Poll keyboard for reports.

        Args:
            callback: Function to call with each report
            duration: How long to poll (None = forever)
        """
        import time
        start = time.time()

        while True:
            report = self.read_keyboard_report(timeout=0.1)
            if report:
                # Track typed text
                text = report.to_string()
                if text:
                    self._typed_text += text

                if callback:
                    callback(report)
                else:
                    print(report)

            if duration and (time.time() - start) > duration:
                break

    def get_typed_text(self) -> str:
        """Get accumulated typed text."""
        return self._typed_text

    def clear_typed_text(self):
        """Clear accumulated typed text."""
        self._typed_text = ""


# =============================================================================
# Mass Storage (SCSI BOT) Constants
# =============================================================================

# SCSI Commands
class SCSICommand(IntEnum):
    TEST_UNIT_READY = 0x00
    REQUEST_SENSE = 0x03
    INQUIRY = 0x12
    MODE_SENSE_6 = 0x1A
    START_STOP_UNIT = 0x1B
    PREVENT_ALLOW_MEDIUM_REMOVAL = 0x1E
    READ_CAPACITY_10 = 0x25
    READ_10 = 0x28
    WRITE_10 = 0x2A
    READ_FORMAT_CAPACITIES = 0x23
    MODE_SENSE_10 = 0x5A


# Mass Storage Class Requests
class MSCRequest(IntEnum):
    GET_MAX_LUN = 0xFE
    BULK_ONLY_RESET = 0xFF


# CBW/CSW Signatures
CBW_SIGNATURE = 0x43425355  # 'USBC'
CSW_SIGNATURE = 0x53425355  # 'USBS'

# CBW Flags
CBW_FLAG_DATA_IN = 0x80
CBW_FLAG_DATA_OUT = 0x00

# CSW Status
CSW_STATUS_PASSED = 0x00
CSW_STATUS_FAILED = 0x01
CSW_STATUS_PHASE_ERROR = 0x02


@dataclass
class SCSIInquiryData:
    """Parsed SCSI INQUIRY response."""
    peripheral_type: int
    removable: bool
    version: int
    response_format: int
    additional_length: int
    vendor_id: str
    product_id: str
    product_revision: str

    def __str__(self):
        type_names = {
            0x00: "Direct Access (Disk)",
            0x05: "CD-ROM",
            0x07: "Optical Memory",
            0x0E: "Simplified Direct Access",
        }
        type_name = type_names.get(self.peripheral_type, f"0x{self.peripheral_type:02x}")
        return (f"{self.vendor_id.strip()} {self.product_id.strip()} "
                f"[{type_name}] Rev:{self.product_revision.strip()}")


@dataclass
class MBRPartition:
    """MBR Partition entry."""
    bootable: bool
    partition_type: int
    start_lba: int
    size_sectors: int

    @property
    def size_bytes(self) -> int:
        return self.size_sectors * 512

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    def __str__(self):
        type_names = {
            0x00: "Empty",
            0x01: "FAT12",
            0x04: "FAT16 <32MB",
            0x06: "FAT16",
            0x07: "NTFS/exFAT",
            0x0B: "FAT32 CHS",
            0x0C: "FAT32 LBA",
            0x0E: "FAT16 LBA",
            0x0F: "Extended LBA",
            0x82: "Linux swap",
            0x83: "Linux",
            0xEE: "GPT Protective",
        }
        type_name = type_names.get(self.partition_type, f"0x{self.partition_type:02x}")
        boot = "*" if self.bootable else " "
        return f"{boot} {type_name:<16} LBA {self.start_lba:>10} Size {self.size_mb:>8.1f} MB"


@dataclass
class GPTPartition:
    """GPT Partition entry."""
    type_guid: bytes
    partition_guid: bytes
    start_lba: int
    end_lba: int
    attributes: int
    name: str

    @property
    def size_sectors(self) -> int:
        return self.end_lba - self.start_lba + 1

    @property
    def size_bytes(self) -> int:
        return self.size_sectors * 512

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    def __str__(self):
        # Common GPT type GUIDs
        type_guids = {
            bytes.fromhex("C12A7328F81F11D2BA4B00A0C93EC93B"): "EFI System",
            bytes.fromhex("EBD0A0A2B9E5443387C068B6B72699C7"): "Microsoft Basic Data",
            bytes.fromhex("0FC63DAF848347728E793D69D8477DE4"): "Linux Filesystem",
            bytes.fromhex("A19D880F05FC4D3BA006743F0F84911E"): "Linux /boot",
            bytes.fromhex("0657FD6DA4AB43C484E50933C84B4F4F"): "Linux Swap",
        }
        # Swap byte order for comparison (GUIDs in GPT are mixed-endian)
        guid_le = (self.type_guid[3::-1] + self.type_guid[5:3:-1] +
                   self.type_guid[7:5:-1] + self.type_guid[8:])
        type_name = type_guids.get(guid_le, self.type_guid.hex())
        return f"{type_name:<24} LBA {self.start_lba:>10} Size {self.size_mb:>8.1f} MB  {self.name}"


class MassStorageClient(USBIPClient):
    """
    USB Mass Storage Class (MSC) client.

    Implements SCSI Bulk-Only Transport (BOT) protocol for accessing
    USB storage devices like flash drives, SD card readers, etc.

    Features:
    - Device inquiry (vendor, product, revision)
    - Capacity detection
    - Block read/write
    - Partition table parsing (MBR/GPT)

    Usage:
        client = MassStorageClient()
        client.open("1-1")

        # Get device info
        info = client.inquiry()
        print(info)

        # Get capacity
        blocks, block_size = client.read_capacity()
        print(f"Capacity: {blocks * block_size / (1024*1024):.1f} MB")

        # Read partition table
        partitions = client.read_partition_table()
        for p in partitions:
            print(p)

        # Read raw block
        data = client.read_blocks(0, 1)
    """

    def __init__(self, host: str = "localhost", port: int = 3240):
        super().__init__(host, port)
        self.bulk_in_ep = 0x81   # Default bulk IN endpoint
        self.bulk_out_ep = 0x01  # Default bulk OUT endpoint
        self.interface = 0
        self.max_lun = 0
        self._tag = 1
        self.block_size = 512
        self.block_count = 0

    def open(self, busid: str):
        """Open Mass Storage device."""
        self.attach(busid)

        # Get configuration to find MSC interface and endpoints
        config = self.parse_configuration()

        # Find Mass Storage interface (class 0x08)
        for iface in config.get('interfaces', []):
            if iface.get('class') == 0x08:  # Mass Storage class
                self.interface = iface.get('number', 0)
                # Find bulk endpoints
                for ep in iface.get('endpoints', []):
                    ep_type = ep['attributes'] & 0x03
                    if ep_type == 2:  # Bulk
                        if ep['address'] & 0x80:  # IN
                            self.bulk_in_ep = ep['address']
                        else:  # OUT
                            self.bulk_out_ep = ep['address']
                break

        self.set_configuration(1)

        # Get max LUN
        try:
            self.max_lun = self.get_max_lun()
        except Exception:
            self.max_lun = 0

        logger.info(f"MSC device opened: interface={self.interface}, "
                   f"in=0x{self.bulk_in_ep:02X}, out=0x{self.bulk_out_ep:02X}, "
                   f"max_lun={self.max_lun}")

    def get_max_lun(self) -> int:
        """Get maximum LUN number."""
        status, data = self.control_transfer(
            0xA1,  # IN, Class, Interface
            MSCRequest.GET_MAX_LUN,
            0,
            self.interface,
            length=1
        )
        return data[0] if data else 0

    def bulk_only_reset(self):
        """Reset bulk-only transport."""
        self.control_transfer(
            0x21,  # OUT, Class, Interface
            MSCRequest.BULK_ONLY_RESET,
            0,
            self.interface
        )

    def _send_cbw(self, command: bytes, data_length: int, direction: int, lun: int = 0) -> int:
        """
        Send Command Block Wrapper.

        Args:
            command: SCSI command (up to 16 bytes)
            data_length: Expected data transfer length
            direction: CBW_FLAG_DATA_IN or CBW_FLAG_DATA_OUT
            lun: Logical Unit Number

        Returns:
            Tag used for this command
        """
        tag = self._tag
        self._tag += 1

        # Pad command to 16 bytes
        cmd_padded = command.ljust(16, b'\x00')

        # Build CBW (31 bytes)
        cbw = struct.pack("<IIIBBB",
            CBW_SIGNATURE,
            tag,
            data_length,
            direction,
            lun,
            len(command)
        ) + cmd_padded

        # Send CBW
        self.bulk_transfer(self.bulk_out_ep, data=cbw)
        return tag

    def _recv_csw(self, expected_tag: int) -> Tuple[int, int]:
        """
        Receive Command Status Wrapper.

        Args:
            expected_tag: Expected tag from CBW

        Returns:
            Tuple of (status, residue)
        """
        # Receive CSW (13 bytes)
        status, data = self.bulk_transfer(self.bulk_in_ep, length=13)

        if len(data) < 13:
            raise RuntimeError(f"CSW too short: {len(data)} bytes")

        signature, tag, residue, csw_status = struct.unpack("<IIIB", data[:13])

        if signature != CSW_SIGNATURE:
            raise RuntimeError(f"Invalid CSW signature: 0x{signature:08X}")

        if tag != expected_tag:
            raise RuntimeError(f"CSW tag mismatch: expected {expected_tag}, got {tag}")

        return csw_status, residue

    def scsi_command(self, command: bytes, data_out: bytes = b'',
                     data_in_length: int = 0, lun: int = 0) -> Tuple[int, bytes]:
        """
        Execute a SCSI command.

        Args:
            command: SCSI command bytes
            data_out: Data to send (for write commands)
            data_in_length: Expected response length (for read commands)
            lun: Logical Unit Number

        Returns:
            Tuple of (status, data)
        """
        if data_out:
            # Data OUT phase
            direction = CBW_FLAG_DATA_OUT
            data_length = len(data_out)
        else:
            # Data IN phase (or no data)
            direction = CBW_FLAG_DATA_IN
            data_length = data_in_length

        # Send CBW
        tag = self._send_cbw(command, data_length, direction, lun)

        # Data phase
        result_data = b''
        if data_out:
            self.bulk_transfer(self.bulk_out_ep, data=data_out)
        elif data_in_length > 0:
            status, result_data = self.bulk_transfer(self.bulk_in_ep, length=data_in_length)

        # Receive CSW
        csw_status, residue = self._recv_csw(tag)

        return csw_status, result_data

    def test_unit_ready(self, lun: int = 0) -> bool:
        """Test if unit is ready."""
        cmd = struct.pack(">BBBBBB",
            SCSICommand.TEST_UNIT_READY,
            lun << 5,
            0, 0, 0, 0
        )
        status, _ = self.scsi_command(cmd, lun=lun)
        return status == CSW_STATUS_PASSED

    def inquiry(self, lun: int = 0) -> SCSIInquiryData:
        """
        Send INQUIRY command.

        Returns device identification data.
        """
        cmd = struct.pack(">BBBBB",
            SCSICommand.INQUIRY,
            0,      # EVPD=0, page_code=0
            0,
            0,
            36      # Allocation length
        ) + b'\x00'

        status, data = self.scsi_command(cmd, data_in_length=36, lun=lun)

        if status != CSW_STATUS_PASSED or len(data) < 36:
            raise RuntimeError(f"INQUIRY failed: status={status}, len={len(data)}")

        return SCSIInquiryData(
            peripheral_type=data[0] & 0x1F,
            removable=bool(data[1] & 0x80),
            version=data[2],
            response_format=data[3] & 0x0F,
            additional_length=data[4],
            vendor_id=data[8:16].decode('ascii', errors='replace'),
            product_id=data[16:32].decode('ascii', errors='replace'),
            product_revision=data[32:36].decode('ascii', errors='replace')
        )

    def read_capacity(self, lun: int = 0) -> Tuple[int, int]:
        """
        Read device capacity.

        Returns:
            Tuple of (block_count, block_size)
        """
        cmd = struct.pack(">BBBBBBBBBB",
            SCSICommand.READ_CAPACITY_10,
            0, 0, 0, 0, 0, 0, 0, 0, 0
        )

        status, data = self.scsi_command(cmd, data_in_length=8, lun=lun)

        if status != CSW_STATUS_PASSED or len(data) < 8:
            raise RuntimeError(f"READ_CAPACITY failed: status={status}")

        last_lba, block_size = struct.unpack(">II", data[:8])
        block_count = last_lba + 1

        self.block_count = block_count
        self.block_size = block_size

        return block_count, block_size

    def read_blocks(self, lba: int, count: int, lun: int = 0) -> bytes:
        """
        Read blocks from device.

        Args:
            lba: Starting Logical Block Address
            count: Number of blocks to read
            lun: Logical Unit Number

        Returns:
            Block data
        """
        cmd = struct.pack(">BBIHB",
            SCSICommand.READ_10,
            0,          # Flags
            lba,        # LBA (32-bit big-endian)
            count,      # Transfer length (16-bit big-endian)
            0           # Control
        ) + b'\x00'

        data_length = count * self.block_size
        status, data = self.scsi_command(cmd, data_in_length=data_length, lun=lun)

        if status != CSW_STATUS_PASSED:
            raise RuntimeError(f"READ_10 failed at LBA {lba}: status={status}")

        return data

    def write_blocks(self, lba: int, data: bytes, lun: int = 0):
        """
        Write blocks to device.

        Args:
            lba: Starting Logical Block Address
            data: Block data to write
            lun: Logical Unit Number
        """
        count = (len(data) + self.block_size - 1) // self.block_size
        # Pad to block boundary
        data_padded = data.ljust(count * self.block_size, b'\x00')

        cmd = struct.pack(">BBIHB",
            SCSICommand.WRITE_10,
            0,          # Flags
            lba,        # LBA (32-bit big-endian)
            count,      # Transfer length (16-bit big-endian)
            0           # Control
        ) + b'\x00'

        status, _ = self.scsi_command(cmd, data_out=data_padded, lun=lun)

        if status != CSW_STATUS_PASSED:
            raise RuntimeError(f"WRITE_10 failed at LBA {lba}: status={status}")

    def request_sense(self, lun: int = 0) -> bytes:
        """Request sense data after error."""
        cmd = struct.pack(">BBBBB",
            SCSICommand.REQUEST_SENSE,
            0,
            0,
            0,
            18  # Allocation length
        ) + b'\x00'

        status, data = self.scsi_command(cmd, data_in_length=18, lun=lun)
        return data

    def read_partition_table(self, lun: int = 0) -> List:
        """
        Read and parse partition table.

        Supports both MBR and GPT partition tables.

        Returns:
            List of MBRPartition or GPTPartition objects
        """
        # Read first sector (MBR/protective MBR)
        mbr = self.read_blocks(0, 1, lun)

        if len(mbr) < 512:
            raise RuntimeError("Failed to read MBR")

        # Check MBR signature
        if mbr[510:512] != b'\x55\xAA':
            raise RuntimeError("Invalid MBR signature")

        partitions = []

        # Parse MBR partition table (4 entries at offset 446)
        for i in range(4):
            offset = 446 + i * 16
            entry = mbr[offset:offset + 16]

            boot_flag = entry[0]
            part_type = entry[4]
            start_lba = struct.unpack("<I", entry[8:12])[0]
            size_sectors = struct.unpack("<I", entry[12:16])[0]

            if part_type == 0x00:
                continue

            # Check for GPT protective MBR
            if part_type == 0xEE:
                # Read GPT header (LBA 1)
                gpt_partitions = self._read_gpt(lun)
                if gpt_partitions:
                    return gpt_partitions

            partitions.append(MBRPartition(
                bootable=boot_flag == 0x80,
                partition_type=part_type,
                start_lba=start_lba,
                size_sectors=size_sectors
            ))

        return partitions

    def _read_gpt(self, lun: int = 0) -> List[GPTPartition]:
        """Read GPT partition table."""
        # Read GPT header (LBA 1)
        header = self.read_blocks(1, 1, lun)

        if header[:8] != b'EFI PART':
            return []

        # Parse GPT header
        revision = struct.unpack("<I", header[8:12])[0]
        header_size = struct.unpack("<I", header[12:16])[0]
        partition_entry_lba = struct.unpack("<Q", header[72:80])[0]
        num_partition_entries = struct.unpack("<I", header[80:84])[0]
        partition_entry_size = struct.unpack("<I", header[84:88])[0]

        # Read partition entries
        entries_per_sector = 512 // partition_entry_size
        sectors_needed = (num_partition_entries + entries_per_sector - 1) // entries_per_sector

        entry_data = self.read_blocks(partition_entry_lba, sectors_needed, lun)

        partitions = []
        for i in range(num_partition_entries):
            offset = i * partition_entry_size
            entry = entry_data[offset:offset + partition_entry_size]

            if len(entry) < 128:
                break

            type_guid = entry[0:16]
            partition_guid = entry[16:32]
            start_lba = struct.unpack("<Q", entry[32:40])[0]
            end_lba = struct.unpack("<Q", entry[40:48])[0]
            attributes = struct.unpack("<Q", entry[48:56])[0]
            name = entry[56:128].decode('utf-16-le', errors='replace').rstrip('\x00')

            # Skip empty entries (all zeros type GUID)
            if type_guid == b'\x00' * 16:
                continue

            partitions.append(GPTPartition(
                type_guid=type_guid,
                partition_guid=partition_guid,
                start_lba=start_lba,
                end_lba=end_lba,
                attributes=attributes,
                name=name
            ))

        return partitions

    def get_device_info(self, lun: int = 0) -> Dict[str, Any]:
        """
        Get comprehensive device information.

        Returns:
            Dictionary with device details
        """
        info = {}

        # Inquiry data
        try:
            inquiry = self.inquiry(lun)
            info['vendor'] = inquiry.vendor_id.strip()
            info['product'] = inquiry.product_id.strip()
            info['revision'] = inquiry.product_revision.strip()
            info['type'] = inquiry.peripheral_type
            info['removable'] = inquiry.removable
        except Exception as e:
            info['inquiry_error'] = str(e)

        # Capacity
        try:
            blocks, block_size = self.read_capacity(lun)
            info['blocks'] = blocks
            info['block_size'] = block_size
            info['capacity_bytes'] = blocks * block_size
            info['capacity_mb'] = info['capacity_bytes'] / (1024 * 1024)
            info['capacity_gb'] = info['capacity_bytes'] / (1024 * 1024 * 1024)
        except Exception as e:
            info['capacity_error'] = str(e)

        # Partition table
        try:
            partitions = self.read_partition_table(lun)
            info['partitions'] = partitions
            info['partition_count'] = len(partitions)
        except Exception as e:
            info['partition_error'] = str(e)

        return info


# =============================================================================
# Interactive Shell
# =============================================================================

class USBIPShell:
    """Interactive shell for USBIP client."""

    def __init__(self, client: USBIPClient):
        self.client = client
        self.running = True

    def run(self):
        """Run interactive shell."""
        print("USBIP Interactive Shell")
        print("Type 'help' for commands, 'quit' to exit")
        print()

        while self.running:
            try:
                cmd = input("usbip> ").strip()
                if not cmd:
                    continue

                parts = cmd.split()
                command = parts[0].lower()
                args = parts[1:]

                if command == "quit" or command == "exit":
                    self.running = False
                elif command == "help":
                    self.cmd_help()
                elif command == "info":
                    self.cmd_info()
                elif command == "desc":
                    self.cmd_descriptors()
                elif command == "config":
                    self.cmd_config(args)
                elif command == "read":
                    self.cmd_read(args)
                elif command == "write":
                    self.cmd_write(args)
                elif command == "control":
                    self.cmd_control(args)
                else:
                    print(f"Unknown command: {command}")

            except KeyboardInterrupt:
                print("\nUse 'quit' to exit")
            except Exception as e:
                print(f"Error: {e}")

    def cmd_help(self):
        """Show help."""
        print("""
Commands:
  info              Show device info
  desc              Show descriptors
  config [n]        Set configuration
  read <ep> [len]   Read from endpoint
  write <ep> <hex>  Write to endpoint
  control <args>    Control transfer
  quit              Exit shell
""")

    def cmd_info(self):
        """Show device info."""
        if not self.client.device:
            print("No device attached")
            return

        dev = self.client.device
        print(f"Device: {dev.vendor_id:04x}:{dev.product_id:04x}")
        print(f"BusID:  {dev.busid}")
        print(f"Class:  {dev.device_class:02x}/{dev.device_subclass:02x}")
        print(f"Speed:  {dev.speed}")

    def cmd_descriptors(self):
        """Show device descriptors."""
        print("\nDevice Descriptor:")
        desc = self.client.get_device_descriptor()
        print(f"  Raw: {desc.hex()}")

        print("\nConfiguration:")
        config = self.client.parse_configuration()
        for key, val in config['configuration'].items():
            print(f"  {key}: {val}")

        print("\nInterfaces:")
        for iface in config['interfaces']:
            print(f"  Interface {iface['number']}: class={iface['class']:02x}")
            for ep in iface['endpoints']:
                direction = "IN" if ep['address'] & 0x80 else "OUT"
                print(f"    EP {ep['address'] & 0x0F} {direction}: max={ep['max_packet']}")

    def cmd_config(self, args):
        """Set configuration."""
        config = int(args[0]) if args else 1
        if self.client.set_configuration(config):
            print(f"Configuration {config} set")
        else:
            print("Failed to set configuration")

    def cmd_read(self, args):
        """Read from endpoint."""
        if not args:
            print("Usage: read <endpoint> [length]")
            return

        ep = int(args[0], 0)
        length = int(args[1]) if len(args) > 1 else 64

        status, data = self.client.bulk_transfer(ep, length=length)
        print(f"Status: {status}")
        print(f"Data: {data.hex()}")
        try:
            print(f"ASCII: {data.decode('ascii', errors='replace')}")
        except Exception:
            pass

    def cmd_write(self, args):
        """Write to endpoint."""
        if len(args) < 2:
            print("Usage: write <endpoint> <hex_data>")
            return

        ep = int(args[0], 0)
        data = bytes.fromhex(args[1])

        status, _ = self.client.bulk_transfer(ep, data=data)
        print(f"Status: {status}")
        print(f"Sent {len(data)} bytes")

    def cmd_control(self, args):
        """Control transfer."""
        if len(args) < 4:
            print("Usage: control <bmRequestType> <bRequest> <wValue> <wIndex> [length|data]")
            return

        bmRequestType = int(args[0], 0)
        bRequest = int(args[1], 0)
        wValue = int(args[2], 0)
        wIndex = int(args[3], 0)

        if bmRequestType & 0x80:  # IN
            length = int(args[4]) if len(args) > 4 else 64
            status, data = self.client.control_transfer(
                bmRequestType, bRequest, wValue, wIndex, length=length)
            print(f"Status: {status}")
            print(f"Data: {data.hex()}")
        else:  # OUT
            data = bytes.fromhex(args[4]) if len(args) > 4 else b''
            status, _ = self.client.control_transfer(
                bmRequestType, bRequest, wValue, wIndex, data=data)
            print(f"Status: {status}")


# =============================================================================
# Main / Demo
# =============================================================================

def demo_list_devices(host: str, port: int):
    """List devices on USBIP server."""
    client = USBIPClient(host, port)

    try:
        devices = client.list_devices()
        print(f"\nDevices on {host}:{port}:")
        print("-" * 60)

        if not devices:
            print("  No devices available")
        else:
            for dev in devices:
                print(f"  {dev}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.disconnect()


def demo_attach_and_enumerate(host: str, port: int, busid: str):
    """Attach to device and enumerate."""
    client = USBIPClient(host, port)

    try:
        print(f"\nAttaching to {busid} on {host}:{port}...")
        client.attach(busid)

        print("\nDevice Descriptor:")
        desc = client.get_device_descriptor()
        print(f"  Raw: {desc.hex()}")

        if len(desc) >= 18:
            vid = struct.unpack("<H", desc[8:10])[0]
            pid = struct.unpack("<H", desc[10:12])[0]
            print(f"  VID:PID = {vid:04x}:{pid:04x}")

        print("\nConfiguration:")
        config = client.parse_configuration()
        print(f"  {config['configuration']}")

        print("\nStrings:")
        for i in range(1, 4):
            try:
                s = client.get_string_descriptor(i)
                print(f"  String {i}: {s}")
            except Exception:
                pass

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.disconnect()


def demo_cdc_echo(host: str, port: int, busid: str):
    """Test CDC-ACM echo functionality."""
    client = CDCACMClient(host, port)

    try:
        print(f"\nOpening CDC device {busid}...")
        client.open(busid)

        print("Sending test data...")
        test_data = b"Hello, USBIP CDC!\r\n"
        written = client.write(test_data)
        print(f"  Sent {written} bytes")

        print("Reading response...")
        response = client.read(64, timeout=2.0)
        print(f"  Received: {response}")

        # Interactive echo test
        print("\nInteractive mode (Ctrl-C to exit):")
        while True:
            try:
                line = input("> ")
                client.write((line + "\r\n").encode())
                response = client.readline(timeout=2.0)
                print(f"< {response}")
            except KeyboardInterrupt:
                break

    except Exception as e:
        print(f"Error: {e}")
    finally:
        client.disconnect()


def demo_hid_keyboard(host: str, port: int, busid: str, duration: float = None):
    """Test HID keyboard device."""
    client = HIDClient(host, port)

    try:
        print(f"\nOpening HID device {busid}...")
        client.open(busid)

        print("\nDevice info:")
        print(f"  VID:PID = {client.device.vendor_id:04x}:{client.device.product_id:04x}")
        print(f"  Interface: {client.interface}")
        print(f"  Endpoint: 0x{client.interrupt_in_ep:02X}")
        print(f"  Report size: {client.report_size}")

        # Get protocol
        try:
            protocol = client.get_protocol()
            print(f"  Protocol: {'Report' if protocol else 'Boot'}")
        except Exception:
            pass

        # Get initial report via control transfer
        print("\nGetting initial report via GET_REPORT...")
        try:
            report_data = client.get_report(HIDReportType.INPUT, 0, 8)
            print(f"  Report: {report_data.hex()}")
            report = HIDKeyboardReport.from_bytes(report_data)
            print(f"  Parsed: {report}")
        except Exception as e:
            print(f"  Error: {e}")

        print("\nPolling keyboard (Ctrl-C to stop)...")
        print("-" * 40)

        def on_report(report: HIDKeyboardReport):
            # Only print if keys are pressed
            if report.modifiers or any(k != 0 for k in report.keys):
                text = report.to_string()
                keys = report.get_pressed_keys()
                if text:
                    print(f"Keys: [{', '.join(keys)}] -> '{text}'")
                else:
                    print(f"Keys: [{', '.join(keys)}]")

        try:
            client.poll_keyboard(callback=on_report, duration=duration)
        except KeyboardInterrupt:
            pass

        print("\n" + "-" * 40)
        typed = client.get_typed_text()
        if typed:
            print(f"Typed text: {repr(typed)}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        client.disconnect()


def main():
    parser = argparse.ArgumentParser(description="USBIP Client")
    parser.add_argument("command", choices=["list", "attach", "cdc", "hid", "shell"],
                       help="Command to run")
    parser.add_argument("--host", default="localhost", help="USBIP server host")
    parser.add_argument("--port", type=int, default=3240, help="USBIP server port")
    parser.add_argument("--busid", help="Device bus ID")
    parser.add_argument("--duration", type=float, help="Duration for HID polling (seconds)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.command == "list":
        demo_list_devices(args.host, args.port)

    elif args.command == "attach":
        if not args.busid:
            print("Error: --busid required for attach")
            sys.exit(1)
        demo_attach_and_enumerate(args.host, args.port, args.busid)

    elif args.command == "cdc":
        if not args.busid:
            print("Error: --busid required for cdc")
            sys.exit(1)
        demo_cdc_echo(args.host, args.port, args.busid)

    elif args.command == "hid":
        if not args.busid:
            print("Error: --busid required for hid")
            sys.exit(1)
        demo_hid_keyboard(args.host, args.port, args.busid, args.duration)

    elif args.command == "shell":
        if not args.busid:
            print("Error: --busid required for shell")
            sys.exit(1)

        client = USBIPClient(args.host, args.port)
        try:
            client.attach(args.busid)
            shell = USBIPShell(client)
            shell.run()
        finally:
            client.disconnect()


if __name__ == "__main__":
    main()
