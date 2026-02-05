#!/usr/bin/env python3
"""
Pure-Python USBIP CDC-ACM Tests

Tests the USBIP server and CDC-ACM device emulation without kernel modules.
Uses raw socket communication to verify USBIP protocol compliance and
CDC-ACM device functionality.

Run:
    PYTHONPATH=python pytest tests/test_usbip_cdc.py -v

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 TwistedWires Security Lab
"""

import asyncio
import struct
import socket
import time
import threading
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from slab_cortex_m.usbip_server import USBIPServer, CDCACMDevice, USBDevice


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def usbip_port():
    """Find a free port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def usbip_server(usbip_port):
    """Start USBIP server in background thread."""
    server = USBIPServer(port=usbip_port)
    loop = asyncio.new_event_loop()

    def run_server():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.start())

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(0.3)  # Wait for server to start

    yield server

    loop.call_soon_threadsafe(loop.stop)


def _connect(port: int) -> socket.socket:
    """Connect to USBIP server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(('127.0.0.1', port))
    return sock


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes."""
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


# =============================================================================
# CDCACMDevice Unit Tests
# =============================================================================

class TestCDCACMDevice:
    """Test CDCACMDevice without network."""

    def test_device_descriptor(self):
        dev = CDCACMDevice()
        desc = dev.DEVICE_DESC
        assert len(desc) == 18
        assert desc[0] == 18  # bLength
        assert desc[1] == 0x01  # bDescriptorType
        # VID:PID in little-endian at offsets 8-11
        vid = desc[8] | (desc[9] << 8)
        pid = desc[10] | (desc[11] << 8)
        assert vid == 0x0483
        assert pid == 0x5740

    def test_config_descriptor(self):
        dev = CDCACMDevice()
        desc = dev.CONFIG_DESC
        assert desc[0] == 9  # bLength
        assert desc[1] == 0x02  # bDescriptorType = CONFIGURATION
        # Total length
        total_len = desc[2] | (desc[3] << 8)
        assert total_len == len(desc)
        # 2 interfaces
        assert desc[4] == 2

    def test_string_descriptors(self):
        dev = CDCACMDevice()
        # String 0: LANGID
        langid = dev.get_string_desc(0)
        assert langid[0] == 4
        assert langid[1] == 0x03
        # String 1: Manufacturer
        mfr = dev.get_string_desc(1)
        assert mfr[1] == 0x03
        assert b"TwistedWires" in mfr[2:].decode('utf-16-le', errors='ignore').encode()

    def test_set_address(self):
        dev = CDCACMDevice()
        setup = bytes([0x00, 0x05, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
        dev.handle_control(setup)
        assert dev.address == 1

    def test_set_configuration(self):
        dev = CDCACMDevice()
        setup = bytes([0x00, 0x09, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
        dev.handle_control(setup)
        assert dev.configured is True

    def test_set_line_coding(self):
        dev = CDCACMDevice()
        setup = bytes([0x21, 0x20, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00])
        # Line coding: 115200 8N1
        data = struct.pack("<IBBB", 115200, 0, 0, 8)
        dev.handle_control(setup, data)
        assert dev.line_coding[:4] == struct.pack("<I", 115200)

    def test_get_line_coding(self):
        dev = CDCACMDevice()
        setup = bytes([0xA1, 0x21, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00])
        result = dev.handle_control(setup)
        assert len(result) == 7

    def test_set_control_line_state(self):
        dev = CDCACMDevice()
        # DTR=1, RTS=1
        setup = bytes([0x21, 0x22, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])
        dev.handle_control(setup)
        assert dev.control_line_state == 3

    def test_echo_mode(self):
        dev = CDCACMDevice()
        # Write data to EP1 (OUT)
        test_data = b"HELLO"
        dev.handle_data_out(1, test_data)
        assert len(dev.tx_buffer) == 5

        # Read back from EP1 (IN)
        result = dev.handle_data_in(1, 64)
        assert result == b"HELLO"
        assert len(dev.tx_buffer) == 0

    def test_echo_multiple_chunks(self):
        dev = CDCACMDevice()
        dev.handle_data_out(1, b"AB")
        dev.handle_data_out(1, b"CD")
        assert len(dev.tx_buffer) == 4

        result = dev.handle_data_in(1, 2)
        assert result == b"AB"
        result = dev.handle_data_in(1, 2)
        assert result == b"CD"

    def test_ep2_notification(self):
        dev = CDCACMDevice()
        # EP2 IN (notification) returns empty
        result = dev.handle_data_in(2, 8)
        assert result == b""

    def test_get_device_descriptor(self):
        dev = CDCACMDevice()
        setup = bytes([0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x12, 0x00])
        result = dev.handle_control(setup)
        assert len(result) == 18
        assert result[0] == 18  # bLength


# =============================================================================
# USBDevice Info Tests
# =============================================================================

class TestUSBDeviceInfo:
    """Test USB device info packing."""

    def test_device_info_packing(self):
        dev = USBDevice()
        packed = dev.pack_device_info()
        # 256 (path) + 32 (busid) + 24 (fields: 3I+3H+6B) = 312 bytes
        assert len(packed) == 312

    def test_interface_info_packing(self):
        dev = USBDevice()
        packed = dev.pack_interface_info()
        # 2 interfaces * 4 bytes = 8 bytes
        assert len(packed) == 8

    def test_vid_pid(self):
        dev = USBDevice()
        assert dev.idVendor == 0x0483
        assert dev.idProduct == 0x5740

    def test_busid(self):
        dev = USBDevice()
        assert dev.busid == "1-1"


# =============================================================================
# USBIP Protocol Tests (with server)
# =============================================================================

class TestUSBIPProtocol:
    """Test USBIP protocol over network."""

    def test_devlist(self, usbip_server, usbip_port):
        """Test OP_REQ_DEVLIST / OP_REP_DEVLIST."""
        sock = _connect(usbip_port)

        # Send request: version(2) + 4 bytes padding + command(2) = 8 bytes
        # Server reads: '>HxxxxH' format
        req = struct.pack(">HxxxxH", 0x0111, 0x8005)
        sock.sendall(req)

        # Response: version(2) + command(2) + status(4) + num_devices(4)
        resp = _recv_exact(sock, 12)
        version, command, status, num_devices = struct.unpack(">HHII", resp)

        assert version == 0x0111
        assert command == 0x0005  # OP_REP_DEVLIST
        assert status == 0
        assert num_devices == 1

        # Read device info: 256 (path) + 32 (busid) + 24 (fields) = 312 bytes
        dev_data = _recv_exact(sock, 312)
        busid = dev_data[256:288].rstrip(b'\x00').decode()
        assert busid == "1-1"

        # VID:PID at offset 256+32+12 = 300 (after busnum/devnum/speed)
        vid, pid = struct.unpack(">HH", dev_data[300:304])
        assert vid == 0x0483
        assert pid == 0x5740

        # Read interface info (2 interfaces * 4 bytes)
        iface_data = _recv_exact(sock, 8)
        assert len(iface_data) == 8

        sock.close()

    def test_import(self, usbip_server, usbip_port):
        """Test OP_REQ_IMPORT / OP_REP_IMPORT."""
        sock = _connect(usbip_port)

        # Send import request
        busid = b"1-1" + b'\x00' * 29  # 32 bytes
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)

        # Response: version(2) + command(2) + status(4)
        resp = _recv_exact(sock, 8)
        version, command, status = struct.unpack(">HHI", resp)

        assert version == 0x0111
        assert command == 0x0003  # OP_REP_IMPORT
        assert status == 0

        # Read device info (312 bytes)
        dev_data = _recv_exact(sock, 312)
        vid, pid = struct.unpack(">HH", dev_data[300:304])
        assert vid == 0x0483
        assert pid == 0x5740

        sock.close()

    def test_import_unknown_device(self, usbip_server, usbip_port):
        """Test import of non-existent device."""
        sock = _connect(usbip_port)

        busid = b"2-1" + b'\x00' * 29
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)

        resp = _recv_exact(sock, 8)
        _, _, status = struct.unpack(">HHI", resp)
        assert status != 0  # Should fail

        sock.close()

    def test_get_device_descriptor(self, usbip_server, usbip_port):
        """Test GET_DESCRIPTOR after import."""
        sock = _connect(usbip_port)

        # Import first
        busid = b"1-1" + b'\x00' * 29
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)
        _recv_exact(sock, 8 + 312)

        # CMD_SUBMIT: GET_DESCRIPTOR(Device)
        setup = bytes([0x80, 0x06, 0x00, 0x01, 0x00, 0x00, 0x12, 0x00])
        submit = struct.pack(">IIIII",
            0x00000001,  # CMD_SUBMIT
            1,           # seqnum
            0x00010001,  # devid
            1,           # direction = IN
            0            # ep = 0
        )
        submit += struct.pack(">IIIII", 0, 18, 0, 0, 0)  # flags, len, frame, pkts, interval
        submit += setup

        sock.sendall(submit)

        # Read RET_SUBMIT response
        resp = _recv_exact(sock, 48)
        ret_cmd = struct.unpack(">I", resp[:4])[0]
        assert ret_cmd == 0x00000003  # RET_SUBMIT

        status = struct.unpack(">i", resp[20:24])[0]
        actual_length = struct.unpack(">I", resp[24:28])[0]
        assert status == 0
        assert actual_length == 18

        # Read descriptor data (padded to transfer_buffer_length)
        desc = _recv_exact(sock, 18)
        assert desc[0] == 18  # bLength
        assert desc[1] == 1   # bDescriptorType = DEVICE

        sock.close()

    def test_set_address(self, usbip_server, usbip_port):
        """Test SET_ADDRESS control transfer."""
        sock = _connect(usbip_port)

        # Import
        busid = b"1-1" + b'\x00' * 29
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)
        _recv_exact(sock, 8 + 312)

        # SET_ADDRESS (address=1)
        setup = bytes([0x00, 0x05, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
        submit = struct.pack(">IIIII",
            0x00000001, 1, 0x00010001, 0, 0  # OUT, EP0
        )
        submit += struct.pack(">IIIII", 0, 0, 0, 0, 0)
        submit += setup

        sock.sendall(submit)
        resp = _recv_exact(sock, 48)
        status = struct.unpack(">i", resp[20:24])[0]
        assert status == 0

        sock.close()

    def test_cdc_set_line_coding(self, usbip_server, usbip_port):
        """Test CDC SET_LINE_CODING."""
        sock = _connect(usbip_port)

        # Import
        busid = b"1-1" + b'\x00' * 29
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)
        _recv_exact(sock, 8 + 312)

        # SET_LINE_CODING (115200 8N1)
        line_coding = struct.pack("<IBBB", 115200, 0, 0, 8)
        setup = bytes([0x21, 0x20, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00])

        submit = struct.pack(">IIIII",
            0x00000001, 1, 0x00010001, 0, 0  # OUT, EP0
        )
        submit += struct.pack(">IIIII", 0, 7, 0, 0, 0)
        submit += setup
        submit += line_coding

        sock.sendall(submit)
        resp = _recv_exact(sock, 48)
        status = struct.unpack(">i", resp[20:24])[0]
        assert status == 0

        sock.close()

    def test_bulk_echo(self, usbip_server, usbip_port):
        """Test CDC bulk data echo."""
        sock = _connect(usbip_port)

        # Import
        busid = b"1-1" + b'\x00' * 29
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)
        _recv_exact(sock, 8 + 312)

        # Bulk OUT to EP1
        test_data = b"TEST123"
        submit_out = struct.pack(">IIIII",
            0x00000001, 1, 0x00010001, 0, 1  # OUT, EP1
        )
        submit_out += struct.pack(">IIIII", 0, len(test_data), 0, 0, 0)
        submit_out += b'\x00' * 8  # setup unused
        submit_out += test_data

        sock.sendall(submit_out)
        resp_out = _recv_exact(sock, 48)
        status_out = struct.unpack(">i", resp_out[20:24])[0]
        assert status_out == 0

        actual_out = struct.unpack(">I", resp_out[24:28])[0]
        assert actual_out == len(test_data)

        # Bulk IN from EP1 (echo)
        submit_in = struct.pack(">IIIII",
            0x00000001, 2, 0x00010001, 1, 1  # IN, EP1
        )
        submit_in += struct.pack(">IIIII", 0, 64, 0, 0, 0)
        submit_in += b'\x00' * 8

        sock.sendall(submit_in)
        resp_in = _recv_exact(sock, 48 + 64)  # header + padded data
        status_in = struct.unpack(">i", resp_in[20:24])[0]
        actual_in = struct.unpack(">I", resp_in[24:28])[0]

        assert status_in == 0
        assert actual_in == len(test_data)

        echo_data = resp_in[48:48 + actual_in]
        assert echo_data == test_data

        sock.close()

    def test_unlink(self, usbip_server, usbip_port):
        """Test USBIP_CMD_UNLINK."""
        sock = _connect(usbip_port)

        # Import
        busid = b"1-1" + b'\x00' * 29
        req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid
        sock.sendall(req)
        _recv_exact(sock, 8 + 312)

        # CMD_UNLINK: command(4) + seqnum(4) + devid(4) + direction(4) + ep(4)
        # + seqnum_to_unlink(4) + padding(24) = 48 bytes total
        unlink = struct.pack(">IIIII",
            0x00000002,  # CMD_UNLINK
            1,           # seqnum
            0x00010001,  # devid
            0, 0         # direction, ep
        )
        unlink += struct.pack(">I", 42)  # seqnum to unlink
        unlink += b'\x00' * 20  # padding to make 48 total

        sock.sendall(unlink)

        # Server sends: 20 (header) + 4 (status) + 44 (padding) = 68 bytes
        resp = _recv_exact(sock, 68)
        ret_cmd = struct.unpack(">I", resp[:4])[0]
        assert ret_cmd == 0x00000004  # RET_UNLINK

        # Status is -ECONNRESET (-104)
        status = struct.unpack(">i", resp[20:24])[0]
        assert status == -104

        sock.close()


# =============================================================================
# CDC Bridge Tests
# =============================================================================

class TestCDCBridge:
    """Test CDC bridge between peripheral and USBIP."""

    def test_bridge_firmware_tx(self):
        """Test firmware TX data forwarded to USBIP."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        from slab_cortex_m.cdc_bridge import CDCBridge

        periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        usbip_dev = CDCACMDevice()
        bridge = CDCBridge(periph, usbip_dev)

        # Firmware writes to EP1 FIFO (4 bytes at a time)
        # 'T', 'E', 'S', 'T' packed as little-endian word
        word = ord('T') | (ord('E') << 8) | (ord('S') << 16) | (ord('T') << 24)
        periph.handle_tx_data(1, word)

        # Data should appear in USBIP device's tx_buffer
        assert len(usbip_dev.tx_buffer) == 4
        assert bytes(usbip_dev.tx_buffer) == b"TEST"

    def test_bridge_host_rx(self):
        """Test host data forwarded to peripheral (DWC2 model)."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        from slab_cortex_m.cdc_bridge import CDCBridge

        periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        usbip_dev = CDCACMDevice()
        bridge = CDCBridge(periph, usbip_dev)

        # Host sends data via USBIP
        bridge._handle_host_out(1, b"HELLO")

        # Data should appear in peripheral's DWC2 RX data queue
        # (not rx_buffer - that's the old model)
        assert len(periph._rx_data_queue) == 5
        assert bytes(periph._rx_data_queue) == b"HELLO"
        # Status queue should have DATA_UPDT and XFER_COMP entries
        assert len(periph._rx_status_queue) == 2
        assert periph._rx_status_queue[0] == (1, 0x2, 5)  # DATA_UPDT
        assert periph._rx_status_queue[1] == (1, 0x3, 0)  # XFER_COMP

    def test_bridge_ep0_passthrough(self):
        """Test EP0 still works normally (control transfers)."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        from slab_cortex_m.cdc_bridge import CDCBridge

        periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        usbip_dev = CDCACMDevice()
        bridge = CDCBridge(periph, usbip_dev)

        # EP0 write should go through original handler
        periph.handle_tx_data(0, 0x12345678)
        # EP0 data goes to periph.tx_buffer (control)
        assert len(periph.tx_buffer) == 4

        # USBIP device should not have received EP0 data
        assert len(usbip_dev.tx_buffer) == 0

    def test_bridge_disconnect(self):
        """Test bridge disconnect restores original handlers (DWC2 model)."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        from slab_cortex_m.cdc_bridge import CDCBridge

        periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        usbip_dev = CDCACMDevice()
        bridge = CDCBridge(periph, usbip_dev)

        bridge.disconnect()

        # After disconnect, EP1 TX should echo again (original behavior)
        word = ord('A') | (ord('B') << 8)
        periph.handle_tx_data(1, word)

        # Original echo puts data in DWC2 RX data queue (not rx_buffer)
        assert len(periph._rx_data_queue) == 2
        assert bytes(periph._rx_data_queue) == b"AB"
        # USBIP should not receive it
        assert len(usbip_dev.tx_buffer) == 0
