"""
SLAB USB-IP Backend - USB over IP Protocol Implementation

Allows emulated USB devices to appear on the host system via USBIP.

Protocol based on Linux kernel USBIP implementation.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import socket
import struct
import threading
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable
from enum import IntEnum


class USBIPCommand(IntEnum):
    """USBIP protocol commands."""
    OP_REQ_DEVLIST = 0x8005
    OP_REP_DEVLIST = 0x0005
    OP_REQ_IMPORT = 0x8003
    OP_REP_IMPORT = 0x0003
    USBIP_CMD_SUBMIT = 0x0001
    USBIP_RET_SUBMIT = 0x0003
    USBIP_CMD_UNLINK = 0x0002
    USBIP_RET_UNLINK = 0x0004


class USBDirection(IntEnum):
    """USB transfer direction."""
    OUT = 0  # Host to device
    IN = 0x80  # Device to host


class USBRequestType(IntEnum):
    """USB request types."""
    STANDARD = 0x00
    CLASS = 0x20
    VENDOR = 0x40


class USBStandardRequest(IntEnum):
    """USB standard requests."""
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
    SYNCH_FRAME = 0x0C


class USBDescriptorType(IntEnum):
    """USB descriptor types."""
    DEVICE = 0x01
    CONFIGURATION = 0x02
    STRING = 0x03
    INTERFACE = 0x04
    ENDPOINT = 0x05
    DEVICE_QUALIFIER = 0x06
    OTHER_SPEED_CONFIG = 0x07
    INTERFACE_POWER = 0x08
    HID = 0x21
    HID_REPORT = 0x22


@dataclass
class USBDeviceDescriptor:
    """USB device descriptor."""
    bLength: int = 18
    bDescriptorType: int = USBDescriptorType.DEVICE
    bcdUSB: int = 0x0200
    bDeviceClass: int = 0
    bDeviceSubClass: int = 0
    bDeviceProtocol: int = 0
    bMaxPacketSize0: int = 64
    idVendor: int = 0x1234
    idProduct: int = 0x5678
    bcdDevice: int = 0x0100
    iManufacturer: int = 1
    iProduct: int = 2
    iSerialNumber: int = 3
    bNumConfigurations: int = 1

    def to_bytes(self) -> bytes:
        return struct.pack('<BBHBBBBHHHBBBB',
            self.bLength, self.bDescriptorType, self.bcdUSB,
            self.bDeviceClass, self.bDeviceSubClass, self.bDeviceProtocol,
            self.bMaxPacketSize0, self.idVendor, self.idProduct,
            self.bcdDevice, self.iManufacturer, self.iProduct,
            self.iSerialNumber, self.bNumConfigurations)


@dataclass
class USBConfigDescriptor:
    """USB configuration descriptor."""
    bLength: int = 9
    bDescriptorType: int = USBDescriptorType.CONFIGURATION
    wTotalLength: int = 9
    bNumInterfaces: int = 1
    bConfigurationValue: int = 1
    iConfiguration: int = 0
    bmAttributes: int = 0x80  # Bus powered
    bMaxPower: int = 50  # 100mA

    def to_bytes(self) -> bytes:
        return struct.pack('<BBHBBBBB',
            self.bLength, self.bDescriptorType, self.wTotalLength,
            self.bNumInterfaces, self.bConfigurationValue,
            self.iConfiguration, self.bmAttributes, self.bMaxPower)


@dataclass
class USBInterfaceDescriptor:
    """USB interface descriptor."""
    bLength: int = 9
    bDescriptorType: int = USBDescriptorType.INTERFACE
    bInterfaceNumber: int = 0
    bAlternateSetting: int = 0
    bNumEndpoints: int = 0
    bInterfaceClass: int = 0xFF  # Vendor specific
    bInterfaceSubClass: int = 0
    bInterfaceProtocol: int = 0
    iInterface: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack('<BBBBBBBBB',
            self.bLength, self.bDescriptorType, self.bInterfaceNumber,
            self.bAlternateSetting, self.bNumEndpoints,
            self.bInterfaceClass, self.bInterfaceSubClass,
            self.bInterfaceProtocol, self.iInterface)


@dataclass
class USBEndpointDescriptor:
    """USB endpoint descriptor."""
    bLength: int = 7
    bDescriptorType: int = USBDescriptorType.ENDPOINT
    bEndpointAddress: int = 0x81  # EP1 IN
    bmAttributes: int = 0x02  # Bulk
    wMaxPacketSize: int = 512
    bInterval: int = 0

    def to_bytes(self) -> bytes:
        return struct.pack('<BBBBHB',
            self.bLength, self.bDescriptorType, self.bEndpointAddress,
            self.bmAttributes, self.wMaxPacketSize, self.bInterval)


@dataclass
class USBIPDeviceInfo:
    """USBIP device information for device list."""
    path: str = "/virtual/usb/0"
    busid: str = "1-1"
    busnum: int = 1
    devnum: int = 1
    speed: int = 3  # USB_SPEED_HIGH
    idVendor: int = 0x1234
    idProduct: int = 0x5678
    bcdDevice: int = 0x0100
    bDeviceClass: int = 0
    bDeviceSubClass: int = 0
    bDeviceProtocol: int = 0
    bConfigurationValue: int = 1
    bNumConfigurations: int = 1
    bNumInterfaces: int = 1


class USBDevice(ABC):
    """
    Base class for emulated USB devices.

    Subclass this to implement specific USB device types.
    """

    def __init__(self, vid: int = 0x1234, pid: int = 0x5678):
        self.vid = vid
        self.pid = pid
        self.address = 0
        self.configuration = 0
        self.strings: Dict[int, str] = {
            0: "",  # Language ID
            1: "SLAB Emulator",
            2: "Virtual USB Device",
            3: "000000000001",
        }

        self.device_desc = USBDeviceDescriptor(
            idVendor=vid,
            idProduct=pid,
        )

        self.config_desc = USBConfigDescriptor()
        self.interfaces: List[USBInterfaceDescriptor] = []
        self.endpoints: List[USBEndpointDescriptor] = []

    def get_device_descriptor(self) -> bytes:
        """Get device descriptor."""
        return self.device_desc.to_bytes()

    def get_config_descriptor(self) -> bytes:
        """Get full configuration descriptor."""
        # Build complete config with interfaces and endpoints
        data = bytearray()

        # Interface descriptors
        iface_data = bytearray()
        for iface in self.interfaces:
            iface_data.extend(iface.to_bytes())

        # Endpoint descriptors
        ep_data = bytearray()
        for ep in self.endpoints:
            ep_data.extend(ep.to_bytes())

        total_len = 9 + len(iface_data) + len(ep_data)
        self.config_desc.wTotalLength = total_len

        data.extend(self.config_desc.to_bytes())
        data.extend(iface_data)
        data.extend(ep_data)

        return bytes(data)

    def get_string_descriptor(self, index: int, lang_id: int = 0x0409) -> bytes:
        """Get string descriptor."""
        if index == 0:
            # Language ID descriptor
            return struct.pack('<BBH', 4, USBDescriptorType.STRING, 0x0409)

        string = self.strings.get(index, "")
        encoded = string.encode('utf-16-le')
        length = 2 + len(encoded)
        return struct.pack('<BB', length, USBDescriptorType.STRING) + encoded

    @abstractmethod
    def handle_control(self, bmRequestType: int, bRequest: int,
                      wValue: int, wIndex: int, data: bytes) -> Optional[bytes]:
        """Handle control transfer. Return response data or None."""
        pass

    @abstractmethod
    def handle_bulk_out(self, endpoint: int, data: bytes):
        """Handle bulk OUT transfer (host to device)."""
        pass

    @abstractmethod
    def handle_bulk_in(self, endpoint: int, max_length: int) -> bytes:
        """Handle bulk IN transfer (device to host)."""
        pass


class USBIPServer:
    """
    USBIP server for exporting virtual USB devices.

    Usage:
        device = MyUSBDevice()
        server = USBIPServer(device)
        server.start()
        # ... device is now available via 'usbip attach'
        server.stop()
    """

    def __init__(self, device: USBDevice, host: str = "0.0.0.0", port: int = 3240):
        self.device = device
        self.host = host
        self.port = port
        self.log = logging.getLogger("USBIP")

        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._client: Optional[socket.socket] = None
        self._attached = False

    def start(self):
        """Start the USBIP server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((self.host, self.port))
        self._socket.listen(1)
        self._running = True

        self._thread = threading.Thread(target=self._server_loop, daemon=True)
        self._thread.start()

        self.log.info(f"USBIP server listening on {self.host}:{self.port}")

    def stop(self):
        """Stop the USBIP server."""
        self._running = False
        if self._client:
            self._client.close()
        if self._socket:
            self._socket.close()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _server_loop(self):
        """Main server loop."""
        while self._running:
            try:
                self._socket.settimeout(1.0)
                client, addr = self._socket.accept()
                self.log.info(f"Client connected from {addr}")
                self._client = client
                self._handle_client(client)
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    self.log.error(f"Server error: {e}")
                break

    def _handle_client(self, client: socket.socket):
        """Handle client connection."""
        try:
            while self._running:
                # Read USBIP header (version + command)
                header = client.recv(8)
                if len(header) < 8:
                    break

                version, command = struct.unpack('>HH', header[:4])
                status = struct.unpack('>I', header[4:8])[0]

                if command == USBIPCommand.OP_REQ_DEVLIST:
                    self._handle_devlist(client)
                elif command == USBIPCommand.OP_REQ_IMPORT:
                    self._handle_import(client)
                elif command == USBIPCommand.USBIP_CMD_SUBMIT:
                    self._handle_submit(client, header)
                elif command == USBIPCommand.USBIP_CMD_UNLINK:
                    self._handle_unlink(client, header)
                else:
                    self.log.warning(f"Unknown command: {command:#x}")

        except Exception as e:
            self.log.error(f"Client error: {e}")
        finally:
            client.close()
            self._attached = False

    def _handle_devlist(self, client: socket.socket):
        """Handle device list request."""
        # Build device info
        info = USBIPDeviceInfo(
            idVendor=self.device.vid,
            idProduct=self.device.pid,
        )

        # Response header
        response = struct.pack('>HHI',
            0x0111,  # Version
            USBIPCommand.OP_REP_DEVLIST,
            0)  # Status

        # Number of devices
        response += struct.pack('>I', 1)

        # Device path (256 bytes)
        path = info.path.encode('ascii')
        response += path.ljust(256, b'\x00')

        # Bus ID (32 bytes)
        busid = info.busid.encode('ascii')
        response += busid.ljust(32, b'\x00')

        # Device info
        response += struct.pack('>IIIHBBBBBB',
            info.busnum, info.devnum, info.speed,
            info.idVendor, info.idProduct,
            info.bcdDevice >> 8, info.bcdDevice & 0xFF,
            info.bDeviceClass, info.bDeviceSubClass,
            info.bDeviceProtocol, info.bConfigurationValue)

        # Padding
        response += struct.pack('>BB', info.bNumConfigurations, info.bNumInterfaces)

        # Interface info (for each interface)
        response += struct.pack('>BBB', 0, 0, 0)  # class, subclass, protocol

        client.sendall(response)

    def _handle_import(self, client: socket.socket):
        """Handle device import request."""
        # Read bus ID
        busid = client.recv(32).rstrip(b'\x00').decode('ascii')
        self.log.info(f"Import request for {busid}")

        # Build response
        info = USBIPDeviceInfo(
            idVendor=self.device.vid,
            idProduct=self.device.pid,
        )

        response = struct.pack('>HHI',
            0x0111,
            USBIPCommand.OP_REP_IMPORT,
            0)  # Status OK

        # Device path
        path = info.path.encode('ascii')
        response += path.ljust(256, b'\x00')

        # Bus ID
        response += busid.encode('ascii').ljust(32, b'\x00')

        # Device info
        response += struct.pack('>IIIHBBBBBB',
            info.busnum, info.devnum, info.speed,
            info.idVendor, info.idProduct,
            info.bcdDevice >> 8, info.bcdDevice & 0xFF,
            info.bDeviceClass, info.bDeviceSubClass,
            info.bDeviceProtocol, info.bConfigurationValue)

        response += struct.pack('>BB', info.bNumConfigurations, info.bNumInterfaces)

        client.sendall(response)
        self._attached = True

    def _handle_submit(self, client: socket.socket, header: bytes):
        """Handle URB submit."""
        # Read rest of submit header (40 bytes total after initial 8)
        rest = client.recv(40)
        if len(rest) < 40:
            return

        full_header = header + rest

        # Parse USBIP URB header
        (command, seqnum, devid, direction, endpoint,
         transfer_flags, transfer_buffer_length, start_frame,
         number_of_packets, interval, setup) = struct.unpack(
            '>IIIIIIIIII8s', full_header)

        # Read transfer buffer if OUT
        transfer_buffer = b''
        if direction == USBDirection.OUT and transfer_buffer_length > 0:
            transfer_buffer = client.recv(transfer_buffer_length)

        # Process the request
        response_data = b''
        status = 0

        if endpoint == 0:
            # Control transfer
            bmRequestType, bRequest, wValue, wIndex, wLength = struct.unpack('<BBHHH', setup)

            if bmRequestType & 0x80:
                # IN - device to host
                response_data = self._handle_control_in(
                    bmRequestType, bRequest, wValue, wIndex, wLength)
            else:
                # OUT - host to device
                self._handle_control_out(
                    bmRequestType, bRequest, wValue, wIndex, transfer_buffer)

        elif direction == USBDirection.IN:
            # Bulk/Interrupt IN
            response_data = self.device.handle_bulk_in(endpoint & 0x0F, transfer_buffer_length)

        else:
            # Bulk/Interrupt OUT
            self.device.handle_bulk_out(endpoint & 0x0F, transfer_buffer)

        # Send response
        actual_length = len(response_data)
        resp_header = struct.pack('>IIIIIIIIII8s',
            USBIPCommand.USBIP_RET_SUBMIT,
            seqnum, devid, direction, endpoint,
            status, actual_length, start_frame,
            number_of_packets, 0, b'\x00' * 8)

        client.sendall(resp_header + response_data)

    def _handle_control_in(self, bmRequestType: int, bRequest: int,
                          wValue: int, wIndex: int, wLength: int) -> bytes:
        """Handle control IN transfer."""
        req_type = bmRequestType & 0x60

        if req_type == USBRequestType.STANDARD:
            if bRequest == USBStandardRequest.GET_DESCRIPTOR:
                desc_type = wValue >> 8
                desc_index = wValue & 0xFF

                if desc_type == USBDescriptorType.DEVICE:
                    return self.device.get_device_descriptor()[:wLength]
                elif desc_type == USBDescriptorType.CONFIGURATION:
                    return self.device.get_config_descriptor()[:wLength]
                elif desc_type == USBDescriptorType.STRING:
                    return self.device.get_string_descriptor(desc_index, wIndex)[:wLength]

            elif bRequest == USBStandardRequest.GET_CONFIGURATION:
                return struct.pack('<B', self.device.configuration)

        # Try device-specific handler
        result = self.device.handle_control(
            bmRequestType, bRequest, wValue, wIndex, b'')
        return result[:wLength] if result else b''

    def _handle_control_out(self, bmRequestType: int, bRequest: int,
                           wValue: int, wIndex: int, data: bytes):
        """Handle control OUT transfer."""
        req_type = bmRequestType & 0x60

        if req_type == USBRequestType.STANDARD:
            if bRequest == USBStandardRequest.SET_ADDRESS:
                self.device.address = wValue
            elif bRequest == USBStandardRequest.SET_CONFIGURATION:
                self.device.configuration = wValue
            return

        # Try device-specific handler
        self.device.handle_control(bmRequestType, bRequest, wValue, wIndex, data)

    def _handle_unlink(self, client: socket.socket, header: bytes):
        """Handle URB unlink."""
        rest = client.recv(40)
        seqnum = struct.unpack('>I', header[4:8])[0]

        # Send unlink response
        response = struct.pack('>IIIIIIIIII8s',
            USBIPCommand.USBIP_RET_UNLINK,
            seqnum, 0, 0, 0, 0, 0, 0, 0, 0, b'\x00' * 8)
        client.sendall(response)
