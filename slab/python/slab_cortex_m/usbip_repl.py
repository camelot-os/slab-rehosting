#!/usr/bin/env python3
"""
USB/IP Client REPL - Interactive USB Device Explorer

A powerful interactive shell for exploring and communicating with USB devices
over the USB/IP protocol. Supports:
- Device enumeration and attachment
- Descriptor parsing and display
- Control, bulk, and interrupt transfers
- CDC-ACM serial communication
- HID keyboard/mouse input
- Raw hex data exchange
- Scripting and automation

Usage:
    python3 usbip_repl.py [--host HOST] [--port PORT]

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 TwistedWires Security Lab
"""

import cmd
import struct
import time
import threading
import sys
import os
import readline
import argparse
from typing import Optional, List, Dict, Any
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from usbip_client import (
    USBIPClient, CDCACMClient, HIDClient, MassStorageClient,
    USBIPDevice, HIDKeyboardReport, HIDReportType,
    USBRequest, DescriptorType, HIDRequest,
    HID_KEY_TO_CHAR, HIDModifier,
    SCSIInquiryData, MBRPartition, GPTPartition
)


class USBIPRepl(cmd.Cmd):
    """
    Interactive USB/IP Client REPL.

    Provides a command-line interface for exploring USB devices.
    """

    intro = """
╔══════════════════════════════════════════════════════════════════╗
║                    USB/IP Client REPL                            ║
║                                                                  ║
║  Type 'help' for commands, 'quit' to exit                        ║
║  Tab completion available for commands                           ║
╚══════════════════════════════════════════════════════════════════╝
"""
    prompt = '\033[1;36musbip>\033[0m '

    def __init__(self, host: str = "localhost", port: int = 3240):
        super().__init__()
        self.host = host
        self.port = port
        self.client: Optional[USBIPClient] = None
        self.cdc_client: Optional[CDCACMClient] = None
        self.hid_client: Optional[HIDClient] = None
        self.msc_client: Optional[MassStorageClient] = None
        self.devices: List[USBIPDevice] = []
        self.history_file = os.path.expanduser("~/.usbip_repl_history")
        self._hid_poll_thread: Optional[threading.Thread] = None
        self._hid_polling = False

        # Load history
        try:
            readline.read_history_file(self.history_file)
        except FileNotFoundError:
            pass

    def preloop(self):
        """Called before the command loop starts."""
        print(f"Server: {self.host}:{self.port}")
        print()

    def postloop(self):
        """Called after the command loop ends."""
        # Save history
        try:
            readline.write_history_file(self.history_file)
        except Exception:
            pass

        # Cleanup
        self._stop_hid_polling()
        if self.client:
            self.client.disconnect()

    def emptyline(self):
        """Do nothing on empty line."""
        pass

    def default(self, line: str):
        """Handle unknown commands."""
        print(f"Unknown command: {line}")
        print("Type 'help' for available commands")

    # =========================================================================
    # Connection Commands
    # =========================================================================

    def do_connect(self, arg: str):
        """
        Connect to USB/IP server.
        Usage: connect [host] [port]
        """
        args = arg.split()
        if args:
            self.host = args[0]
        if len(args) > 1:
            self.port = int(args[1])

        try:
            self.client = USBIPClient(self.host, self.port)
            self.client.connect()
            print(f"Connected to {self.host}:{self.port}")
        except Exception as e:
            print(f"Connection failed: {e}")
            self.client = None

    def do_disconnect(self, arg: str):
        """Disconnect from server."""
        self._stop_hid_polling()
        if self.client:
            self.client.disconnect()
            self.client = None
        self.cdc_client = None
        self.hid_client = None
        self.msc_client = None
        print("Disconnected")

    def do_status(self, arg: str):
        """Show connection status."""
        print(f"Server: {self.host}:{self.port}")
        if self.client and self.client.sock:
            print("Status: Connected")
            if self.client.device:
                dev = self.client.device
                print(f"Device: {dev.vendor_id:04x}:{dev.product_id:04x} ({dev.busid})")
        else:
            print("Status: Disconnected")

    # =========================================================================
    # Device Commands
    # =========================================================================

    def do_list(self, arg: str):
        """
        List available devices on server.
        Usage: list
        """
        try:
            client = USBIPClient(self.host, self.port)
            self.devices = client.list_devices()
            client.disconnect()

            if not self.devices:
                print("No devices available")
                return

            print(f"\n{'ID':<4} {'BusID':<10} {'VID:PID':<12} {'Class':<8} {'Description'}")
            print("-" * 60)

            for i, dev in enumerate(self.devices):
                class_name = self._get_class_name(dev.device_class)
                print(f"{i:<4} {dev.busid:<10} {dev.vendor_id:04x}:{dev.product_id:04x}  "
                      f"{class_name:<8}")

        except Exception as e:
            print(f"Error: {e}")

    def do_attach(self, arg: str):
        """
        Attach to a device.
        Usage: attach <busid|index>
        Examples:
            attach 1-1
            attach 0
        """
        if not arg:
            print("Usage: attach <busid|index>")
            return

        # Check if it's an index
        try:
            idx = int(arg)
            if 0 <= idx < len(self.devices):
                busid = self.devices[idx].busid
            else:
                print(f"Invalid index: {idx}")
                return
        except ValueError:
            busid = arg

        try:
            self.client = USBIPClient(self.host, self.port)
            self.client.attach(busid)
            print(f"Attached to {busid}")

            dev = self.client.device
            if dev:
                print(f"  VID:PID: {dev.vendor_id:04x}:{dev.product_id:04x}")
                print(f"  Class: {self._get_class_name(dev.device_class)}")

        except Exception as e:
            print(f"Attach failed: {e}")
            self.client = None

    def do_detach(self, arg: str):
        """Detach from current device."""
        self.do_disconnect(arg)

    # =========================================================================
    # Descriptor Commands
    # =========================================================================

    def do_desc(self, arg: str):
        """
        Show device descriptors.
        Usage: desc [device|config|string <n>|hid|all]
        """
        if not self._check_attached():
            return

        args = arg.split() if arg else ['all']
        cmd = args[0].lower()

        try:
            if cmd in ('device', 'dev', 'd'):
                self._show_device_descriptor()
            elif cmd in ('config', 'cfg', 'c'):
                self._show_config_descriptor()
            elif cmd in ('string', 'str', 's'):
                idx = int(args[1]) if len(args) > 1 else 1
                self._show_string_descriptor(idx)
            elif cmd in ('hid', 'h'):
                self._show_hid_report_descriptor()
            elif cmd == 'all':
                self._show_device_descriptor()
                print()
                self._show_config_descriptor()
            else:
                print(f"Unknown descriptor type: {cmd}")

        except Exception as e:
            print(f"Error: {e}")

    def _show_device_descriptor(self):
        """Display device descriptor."""
        data = self.client.get_device_descriptor()

        print("\n[Device Descriptor]")
        print(f"  Raw: {data.hex()}")

        if len(data) >= 18:
            print(f"  bLength:            {data[0]}")
            print(f"  bDescriptorType:    {data[1]}")
            print(f"  bcdUSB:             {data[2] | (data[3] << 8):04x}")
            print(f"  bDeviceClass:       {data[4]:02x} ({self._get_class_name(data[4])})")
            print(f"  bDeviceSubClass:    {data[5]:02x}")
            print(f"  bDeviceProtocol:    {data[6]:02x}")
            print(f"  bMaxPacketSize0:    {data[7]}")
            vid = data[8] | (data[9] << 8)
            pid = data[10] | (data[11] << 8)
            print(f"  idVendor:           {vid:04x}")
            print(f"  idProduct:          {pid:04x}")
            print(f"  bcdDevice:          {data[12] | (data[13] << 8):04x}")
            print(f"  iManufacturer:      {data[14]}")
            print(f"  iProduct:           {data[15]}")
            print(f"  iSerialNumber:      {data[16]}")
            print(f"  bNumConfigurations: {data[17]}")

    def _show_config_descriptor(self):
        """Display configuration descriptor."""
        config = self.client.parse_configuration()

        print("\n[Configuration Descriptor]")
        for key, val in config['configuration'].items():
            print(f"  {key}: {val}")

        for iface in config['interfaces']:
            print(f"\n  [Interface {iface['number']}]")
            print(f"    bInterfaceClass:    {iface['class']:02x} ({self._get_class_name(iface['class'])})")
            print(f"    bInterfaceSubClass: {iface['subclass']:02x}")
            print(f"    bInterfaceProtocol: {iface['protocol']:02x}")

            for ep in iface['endpoints']:
                direction = "IN" if ep['address'] & 0x80 else "OUT"
                ep_type = self._get_ep_type(ep['attributes'])
                print(f"    [Endpoint 0x{ep['address']:02x}]")
                print(f"      Direction:    {direction}")
                print(f"      Type:         {ep_type}")
                print(f"      MaxPacket:    {ep['max_packet']}")
                print(f"      Interval:     {ep['interval']}")

    def _show_string_descriptor(self, index: int):
        """Display string descriptor."""
        try:
            s = self.client.get_string_descriptor(index)
            print(f"\n[String Descriptor {index}]")
            print(f"  Value: {s}")
        except Exception as e:
            print(f"Error reading string {index}: {e}")

    def _show_hid_report_descriptor(self):
        """Display HID report descriptor (if available)."""
        # HID report descriptor is requested via GET_DESCRIPTOR with type=0x22
        try:
            status, data = self.client.control_transfer(
                0x81,  # IN, Standard, Interface
                USBRequest.GET_DESCRIPTOR,
                (0x22 << 8) | 0,  # HID Report descriptor
                0,  # Interface 0
                length=256
            )
            print("\n[HID Report Descriptor]")
            print(f"  Raw ({len(data)} bytes): {data.hex()}")
            self._parse_hid_report_descriptor(data)
        except Exception as e:
            print(f"Error: {e}")

    def _parse_hid_report_descriptor(self, data: bytes):
        """Parse and display HID report descriptor items."""
        # Basic HID report descriptor parsing
        pos = 0
        indent = 2

        while pos < len(data):
            item = data[pos]
            size = item & 0x03
            if size == 3:
                size = 4
            item_type = (item >> 2) & 0x03
            tag = (item >> 4) & 0x0F

            # Read value
            if pos + 1 + size > len(data):
                break
            value = int.from_bytes(data[pos+1:pos+1+size], 'little', signed=False)

            # Format item
            prefix = "  " * indent

            # Main items
            if item_type == 0:  # Main
                if tag == 0x08:  # Input
                    print(f"{prefix}Input({value:02x})")
                elif tag == 0x09:  # Output
                    print(f"{prefix}Output({value:02x})")
                elif tag == 0x0A:  # Collection
                    coll_types = {0: "Physical", 1: "Application", 2: "Logical"}
                    print(f"{prefix}Collection({coll_types.get(value, value)})")
                    indent += 1
                elif tag == 0x0C:  # End Collection
                    indent = max(2, indent - 1)
                    print(f"{prefix}End Collection")
                elif tag == 0x0B:  # Feature
                    print(f"{prefix}Feature({value:02x})")

            # Global items
            elif item_type == 1:  # Global
                if tag == 0x00:  # Usage Page
                    pages = {1: "Generic Desktop", 7: "Keyboard", 9: "Button"}
                    print(f"{prefix}Usage Page({pages.get(value, f'0x{value:02x}')})")
                elif tag == 0x01:  # Logical Minimum
                    print(f"{prefix}Logical Minimum({value})")
                elif tag == 0x02:  # Logical Maximum
                    print(f"{prefix}Logical Maximum({value})")
                elif tag == 0x03:  # Physical Minimum
                    print(f"{prefix}Physical Minimum({value})")
                elif tag == 0x04:  # Physical Maximum
                    print(f"{prefix}Physical Maximum({value})")
                elif tag == 0x07:  # Report Size
                    print(f"{prefix}Report Size({value})")
                elif tag == 0x08:  # Report ID
                    print(f"{prefix}Report ID({value})")
                elif tag == 0x09:  # Report Count
                    print(f"{prefix}Report Count({value})")

            # Local items
            elif item_type == 2:  # Local
                if tag == 0x00:  # Usage
                    print(f"{prefix}Usage(0x{value:02x})")
                elif tag == 0x01:  # Usage Minimum
                    print(f"{prefix}Usage Minimum(0x{value:02x})")
                elif tag == 0x02:  # Usage Maximum
                    print(f"{prefix}Usage Maximum(0x{value:02x})")

            pos += 1 + size

    # =========================================================================
    # Transfer Commands
    # =========================================================================

    def do_control(self, arg: str):
        """
        Send control transfer.
        Usage: control <bmRequestType> <bRequest> <wValue> <wIndex> [length|hex_data]

        Examples:
            control 0x80 0x06 0x0100 0 18      # GET_DESCRIPTOR (device)
            control 0x00 0x09 1 0              # SET_CONFIGURATION(1)
            control 0x21 0x0a 0 0              # HID SET_IDLE
        """
        if not self._check_attached():
            return

        args = arg.split()
        if len(args) < 4:
            print("Usage: control <bmRequestType> <bRequest> <wValue> <wIndex> [length|data]")
            return

        try:
            bmRequestType = int(args[0], 0)
            bRequest = int(args[1], 0)
            wValue = int(args[2], 0)
            wIndex = int(args[3], 0)

            if bmRequestType & 0x80:  # IN transfer
                length = int(args[4]) if len(args) > 4 else 64
                status, data = self.client.control_transfer(
                    bmRequestType, bRequest, wValue, wIndex, length=length)
                print(f"Status: {status}")
                print(f"Data ({len(data)} bytes): {data.hex()}")
                self._print_ascii(data)
            else:  # OUT transfer
                data = bytes.fromhex(args[4]) if len(args) > 4 else b''
                status, _ = self.client.control_transfer(
                    bmRequestType, bRequest, wValue, wIndex, data=data)
                print(f"Status: {status}")

        except Exception as e:
            print(f"Error: {e}")

    def do_bulk(self, arg: str):
        """
        Send bulk transfer.
        Usage: bulk <endpoint> [length|hex_data]

        Examples:
            bulk 0x81 64        # Read 64 bytes from EP1 IN
            bulk 0x02 48454c4c  # Write "HELL" to EP2 OUT
        """
        if not self._check_attached():
            return

        args = arg.split()
        if not args:
            print("Usage: bulk <endpoint> [length|hex_data]")
            return

        try:
            endpoint = int(args[0], 0)

            if endpoint & 0x80:  # IN transfer
                length = int(args[1]) if len(args) > 1 else 64
                status, data = self.client.bulk_transfer(endpoint, length=length)
                print(f"Status: {status}")
                print(f"Data ({len(data)} bytes): {data.hex()}")
                self._print_ascii(data)
            else:  # OUT transfer
                data = bytes.fromhex(args[1]) if len(args) > 1 else b''
                status, _ = self.client.bulk_transfer(endpoint, data=data)
                print(f"Status: {status}")
                print(f"Sent {len(data)} bytes")

        except Exception as e:
            print(f"Error: {e}")

    def do_interrupt(self, arg: str):
        """
        Send interrupt transfer.
        Usage: interrupt <endpoint> [length|hex_data] [timeout_ms]

        Examples:
            interrupt 0x81 8 100    # Read 8 bytes from EP1 IN, 100ms timeout
        """
        if not self._check_attached():
            return

        args = arg.split()
        if not args:
            print("Usage: interrupt <endpoint> [length|hex_data] [timeout_ms]")
            return

        try:
            endpoint = int(args[0], 0)
            timeout = float(args[2]) / 1000.0 if len(args) > 2 else 1.0

            if endpoint & 0x80:  # IN transfer
                length = int(args[1]) if len(args) > 1 else 8
                status, data = self.client.interrupt_transfer(
                    endpoint, length=length, timeout=timeout)
                print(f"Status: {status}")
                print(f"Data ({len(data)} bytes): {data.hex()}")
                self._print_ascii(data)
            else:  # OUT transfer
                data = bytes.fromhex(args[1]) if len(args) > 1 else b''
                status, _ = self.client.interrupt_transfer(
                    endpoint, data=data, timeout=timeout)
                print(f"Status: {status}")

        except TimeoutError:
            print("Timeout")
        except Exception as e:
            print(f"Error: {e}")

    # =========================================================================
    # CDC Commands
    # =========================================================================

    def do_cdc(self, arg: str):
        """
        CDC-ACM commands.
        Usage: cdc <subcommand> [args]

        Subcommands:
            cdc open              - Open CDC device
            cdc close             - Close CDC device
            cdc write <text>      - Write text
            cdc writehex <hex>    - Write hex data
            cdc read [length]     - Read data
            cdc line [baud] [bits] [parity] [stop] - Set/get line coding
            cdc dtr <0|1>         - Set DTR
            cdc rts <0|1>         - Set RTS
        """
        if not arg:
            print("Usage: cdc <subcommand> [args]")
            return

        args = arg.split(None, 1)
        subcmd = args[0].lower()
        subarg = args[1] if len(args) > 1 else ""

        try:
            if subcmd == 'open':
                self._cdc_open()
            elif subcmd == 'close':
                self._cdc_close()
            elif subcmd == 'write':
                self._cdc_write(subarg)
            elif subcmd == 'writehex':
                self._cdc_write_hex(subarg)
            elif subcmd == 'read':
                self._cdc_read(subarg)
            elif subcmd == 'line':
                self._cdc_line_coding(subarg)
            elif subcmd == 'dtr':
                self._cdc_dtr(subarg)
            elif subcmd == 'rts':
                self._cdc_rts(subarg)
            else:
                print(f"Unknown CDC subcommand: {subcmd}")
        except Exception as e:
            print(f"Error: {e}")

    def _cdc_open(self):
        """Open CDC device."""
        if not self.client or not self.client.device:
            print("Not attached to device")
            return

        busid = self.client.device.busid
        self.client.disconnect()

        self.cdc_client = CDCACMClient(self.host, self.port)
        self.cdc_client.open(busid)
        self.client = self.cdc_client
        print("CDC device opened")

    def _cdc_close(self):
        """Close CDC device."""
        if self.cdc_client:
            self.cdc_client.disconnect()
            self.cdc_client = None
        print("CDC device closed")

    def _cdc_write(self, text: str):
        """Write text to CDC."""
        if not self.cdc_client:
            print("CDC not open")
            return
        n = self.cdc_client.write(text.encode() + b'\r\n')
        print(f"Sent {n} bytes")

    def _cdc_write_hex(self, hex_str: str):
        """Write hex data to CDC."""
        if not self.cdc_client:
            print("CDC not open")
            return
        data = bytes.fromhex(hex_str)
        n = self.cdc_client.write(data)
        print(f"Sent {n} bytes")

    def _cdc_read(self, arg: str):
        """Read from CDC."""
        if not self.cdc_client:
            print("CDC not open")
            return
        length = int(arg) if arg else 64
        data = self.cdc_client.read(length, timeout=2.0)
        print(f"Received ({len(data)} bytes): {data.hex()}")
        self._print_ascii(data)

    def _cdc_line_coding(self, arg: str):
        """Set/get line coding."""
        if not self.cdc_client:
            print("CDC not open")
            return

        if arg:
            args = arg.split()
            if args:
                self.cdc_client.baud_rate = int(args[0])
            if len(args) > 1:
                self.cdc_client.data_bits = int(args[1])
            self.cdc_client.set_line_coding()
            print(f"Set line coding: {self.cdc_client.baud_rate} {self.cdc_client.data_bits}N1")
        else:
            baud, stop, parity, bits = self.cdc_client.get_line_coding()
            print(f"Line coding: {baud} baud, {bits} bits, parity={parity}, stop={stop}")

    def _cdc_dtr(self, arg: str):
        """Set DTR."""
        if not self.cdc_client:
            print("CDC not open")
            return
        dtr = bool(int(arg)) if arg else True
        self.cdc_client.set_control_line_state(dtr=dtr)
        print(f"DTR = {dtr}")

    def _cdc_rts(self, arg: str):
        """Set RTS."""
        if not self.cdc_client:
            print("CDC not open")
            return
        rts = bool(int(arg)) if arg else True
        self.cdc_client.set_control_line_state(rts=rts)
        print(f"RTS = {rts}")

    # =========================================================================
    # HID Commands
    # =========================================================================

    def do_hid(self, arg: str):
        """
        HID commands.
        Usage: hid <subcommand> [args]

        Subcommands:
            hid open              - Open HID device
            hid close             - Close HID device
            hid report [id]       - Get input report
            hid set <hex>         - Set output report
            hid poll [duration]   - Poll for keyboard input
            hid stop              - Stop polling
            hid idle [rate]       - Set/get idle rate
            hid protocol [0|1]    - Set/get protocol (0=boot, 1=report)
        """
        if not arg:
            print("Usage: hid <subcommand> [args]")
            return

        args = arg.split(None, 1)
        subcmd = args[0].lower()
        subarg = args[1] if len(args) > 1 else ""

        try:
            if subcmd == 'open':
                self._hid_open()
            elif subcmd == 'close':
                self._hid_close()
            elif subcmd == 'report':
                self._hid_get_report(subarg)
            elif subcmd == 'set':
                self._hid_set_report(subarg)
            elif subcmd == 'poll':
                self._hid_poll(subarg)
            elif subcmd == 'stop':
                self._stop_hid_polling()
            elif subcmd == 'idle':
                self._hid_idle(subarg)
            elif subcmd == 'protocol':
                self._hid_protocol(subarg)
            else:
                print(f"Unknown HID subcommand: {subcmd}")
        except Exception as e:
            print(f"Error: {e}")

    def _hid_open(self):
        """Open HID device."""
        if not self.client or not self.client.device:
            print("Not attached to device")
            return

        busid = self.client.device.busid
        self.client.disconnect()

        self.hid_client = HIDClient(self.host, self.port)
        self.hid_client.open(busid)
        self.client = self.hid_client
        print(f"HID device opened")
        print(f"  Interface: {self.hid_client.interface}")
        print(f"  Endpoint: 0x{self.hid_client.interrupt_in_ep:02X}")
        print(f"  Report size: {self.hid_client.report_size}")

    def _hid_close(self):
        """Close HID device."""
        self._stop_hid_polling()
        if self.hid_client:
            self.hid_client.disconnect()
            self.hid_client = None
        print("HID device closed")

    def _hid_get_report(self, arg: str):
        """Get HID report."""
        if not self.hid_client:
            print("HID not open")
            return

        report_id = int(arg) if arg else 0
        data = self.hid_client.get_report(HIDReportType.INPUT, report_id)
        print(f"Report ({len(data)} bytes): {data.hex()}")

        # Parse as keyboard report
        if len(data) >= 8:
            report = HIDKeyboardReport.from_bytes(data)
            print(f"  {report}")

    def _hid_set_report(self, arg: str):
        """Set HID output report."""
        if not self.hid_client:
            print("HID not open")
            return

        data = bytes.fromhex(arg) if arg else b'\x00'
        self.hid_client.set_report(data, HIDReportType.OUTPUT)
        print(f"Sent output report: {data.hex()}")

    def _hid_poll(self, arg: str):
        """Poll for HID input."""
        if not self.hid_client:
            print("HID not open")
            return

        duration = float(arg) if arg else None

        print("Polling for keyboard input (Ctrl+C or 'hid stop' to stop)...")
        print("-" * 40)

        self._hid_polling = True

        def poll_thread():
            start = time.time()
            while self._hid_polling:
                try:
                    report = self.hid_client.read_keyboard_report(timeout=0.1)
                    if report:
                        if report.modifiers or any(k != 0 for k in report.keys):
                            text = report.to_string()
                            keys = report.get_pressed_keys()
                            if text:
                                print(f"[{', '.join(keys)}] -> '{text}'")
                            else:
                                print(f"[{', '.join(keys)}]")
                except Exception:
                    pass

                if duration and (time.time() - start) > duration:
                    break

            print("-" * 40)
            typed = self.hid_client.get_typed_text() if self.hid_client else ""
            if typed:
                print(f"Typed: {repr(typed)}")
            self._hid_polling = False

        self._hid_poll_thread = threading.Thread(target=poll_thread, daemon=True)
        self._hid_poll_thread.start()

        if duration:
            self._hid_poll_thread.join()

    def _stop_hid_polling(self):
        """Stop HID polling."""
        self._hid_polling = False
        if self._hid_poll_thread:
            self._hid_poll_thread.join(timeout=1.0)
            self._hid_poll_thread = None

    def _hid_idle(self, arg: str):
        """Set/get idle rate."""
        if not self.hid_client:
            print("HID not open")
            return

        if arg:
            rate = int(arg)
            self.hid_client.set_idle(rate)
            print(f"Idle rate set to {rate}")
        else:
            rate = self.hid_client.get_idle()
            print(f"Idle rate: {rate}")

    def _hid_protocol(self, arg: str):
        """Set/get protocol."""
        if not self.hid_client:
            print("HID not open")
            return

        if arg:
            protocol = int(arg)
            self.hid_client.set_protocol(protocol)
            print(f"Protocol set to {'Report' if protocol else 'Boot'}")
        else:
            protocol = self.hid_client.get_protocol()
            print(f"Protocol: {'Report' if protocol else 'Boot'}")

    # =========================================================================
    # Mass Storage Commands
    # =========================================================================

    def do_msc(self, arg: str):
        """
        Mass Storage commands.
        Usage: msc <subcommand> [args]

        Subcommands:
            msc open              - Open Mass Storage device
            msc close             - Close Mass Storage device
            msc info              - Show device info (vendor, product, capacity)
            msc capacity          - Show device capacity
            msc partitions        - Show partition table
            msc read <lba> [n]    - Read n blocks from LBA
            msc write <lba> <hex> - Write hex data to LBA
            msc hexdump <lba> [n] - Hex dump n blocks from LBA
            msc sense             - Request sense data
            msc reset             - Bulk-only reset
        """
        if not arg:
            print("Usage: msc <subcommand> [args]")
            return

        args = arg.split(None, 1)
        subcmd = args[0].lower()
        subarg = args[1] if len(args) > 1 else ""

        try:
            if subcmd == 'open':
                self._msc_open()
            elif subcmd == 'close':
                self._msc_close()
            elif subcmd == 'info':
                self._msc_info()
            elif subcmd == 'capacity':
                self._msc_capacity()
            elif subcmd == 'partitions':
                self._msc_partitions()
            elif subcmd == 'read':
                self._msc_read(subarg)
            elif subcmd == 'write':
                self._msc_write(subarg)
            elif subcmd == 'hexdump':
                self._msc_hexdump(subarg)
            elif subcmd == 'sense':
                self._msc_sense()
            elif subcmd == 'reset':
                self._msc_reset()
            else:
                print(f"Unknown MSC subcommand: {subcmd}")
        except Exception as e:
            print(f"Error: {e}")

    def _msc_open(self):
        """Open Mass Storage device."""
        if not self.client or not self.client.device:
            print("Not attached to device")
            return

        busid = self.client.device.busid
        self.client.disconnect()

        self.msc_client = MassStorageClient(self.host, self.port)
        self.msc_client.open(busid)
        self.client = self.msc_client
        print("Mass Storage device opened")
        print(f"  Interface: {self.msc_client.interface}")
        print(f"  Bulk IN:  0x{self.msc_client.bulk_in_ep:02X}")
        print(f"  Bulk OUT: 0x{self.msc_client.bulk_out_ep:02X}")
        print(f"  Max LUN:  {self.msc_client.max_lun}")

    def _msc_close(self):
        """Close Mass Storage device."""
        if self.msc_client:
            self.msc_client.disconnect()
            self.msc_client = None
        print("Mass Storage device closed")

    def _msc_info(self):
        """Show device info."""
        if not self.msc_client:
            print("MSC not open")
            return

        info = self.msc_client.get_device_info()

        print("\n[Device Information]")
        if 'vendor' in info:
            print(f"  Vendor:     {info['vendor']}")
            print(f"  Product:    {info['product']}")
            print(f"  Revision:   {info['revision']}")
            print(f"  Type:       {info['type']}")
            print(f"  Removable:  {info['removable']}")
        if 'inquiry_error' in info:
            print(f"  Inquiry error: {info['inquiry_error']}")

        if 'blocks' in info:
            print(f"\n[Capacity]")
            print(f"  Blocks:     {info['blocks']:,}")
            print(f"  Block size: {info['block_size']}")
            print(f"  Capacity:   {info['capacity_mb']:.1f} MB ({info['capacity_gb']:.2f} GB)")
        if 'capacity_error' in info:
            print(f"  Capacity error: {info['capacity_error']}")

        if 'partitions' in info and info['partitions']:
            print(f"\n[Partitions] ({info['partition_count']})")
            for i, p in enumerate(info['partitions']):
                print(f"  {i}: {p}")
        if 'partition_error' in info:
            print(f"  Partition error: {info['partition_error']}")

    def _msc_capacity(self):
        """Show device capacity."""
        if not self.msc_client:
            print("MSC not open")
            return

        blocks, block_size = self.msc_client.read_capacity()
        total_bytes = blocks * block_size

        print(f"Blocks:     {blocks:,}")
        print(f"Block size: {block_size} bytes")
        print(f"Capacity:   {total_bytes / (1024*1024):.1f} MB ({total_bytes / (1024*1024*1024):.2f} GB)")

    def _msc_partitions(self):
        """Show partition table."""
        if not self.msc_client:
            print("MSC not open")
            return

        partitions = self.msc_client.read_partition_table()

        if not partitions:
            print("No partitions found")
            return

        # Determine type
        if partitions and isinstance(partitions[0], GPTPartition):
            print("\n[GPT Partition Table]")
        else:
            print("\n[MBR Partition Table]")

        print(f"{'#':<3} {'Boot':<5} {'Type':<24} {'Start LBA':<12} {'Size':<12}")
        print("-" * 60)

        for i, p in enumerate(partitions):
            if isinstance(p, MBRPartition):
                boot = "*" if p.bootable else ""
                type_names = {
                    0x01: "FAT12", 0x04: "FAT16 <32MB", 0x06: "FAT16",
                    0x07: "NTFS/exFAT", 0x0B: "FAT32 CHS", 0x0C: "FAT32 LBA",
                    0x0E: "FAT16 LBA", 0x82: "Linux swap", 0x83: "Linux",
                    0xEE: "GPT Protective"
                }
                type_name = type_names.get(p.partition_type, f"0x{p.partition_type:02x}")
                print(f"{i:<3} {boot:<5} {type_name:<24} {p.start_lba:<12} {p.size_mb:.1f} MB")
            else:  # GPTPartition
                print(f"{i:<3} {'':5} {p}")

    def _msc_read(self, arg: str):
        """Read blocks."""
        if not self.msc_client:
            print("MSC not open")
            return

        args = arg.split()
        if not args:
            print("Usage: msc read <lba> [count]")
            return

        lba = int(args[0], 0)
        count = int(args[1]) if len(args) > 1 else 1

        data = self.msc_client.read_blocks(lba, count)
        print(f"Read {len(data)} bytes from LBA {lba}:")
        print(data.hex()[:128] + ("..." if len(data) > 64 else ""))
        self._print_ascii(data[:64])

    def _msc_write(self, arg: str):
        """Write blocks."""
        if not self.msc_client:
            print("MSC not open")
            return

        args = arg.split()
        if len(args) < 2:
            print("Usage: msc write <lba> <hex_data>")
            return

        lba = int(args[0], 0)
        data = bytes.fromhex(args[1])

        self.msc_client.write_blocks(lba, data)
        print(f"Wrote {len(data)} bytes to LBA {lba}")

    def _msc_hexdump(self, arg: str):
        """Hex dump blocks."""
        if not self.msc_client:
            print("MSC not open")
            return

        args = arg.split()
        if not args:
            print("Usage: msc hexdump <lba> [count]")
            return

        lba = int(args[0], 0)
        count = int(args[1]) if len(args) > 1 else 1

        data = self.msc_client.read_blocks(lba, count)

        print(f"\nLBA {lba} ({count} block(s), {len(data)} bytes):")
        self._hexdump(data)

    def _msc_sense(self):
        """Request sense data."""
        if not self.msc_client:
            print("MSC not open")
            return

        data = self.msc_client.request_sense()
        print(f"Sense data ({len(data)} bytes): {data.hex()}")

        if len(data) >= 14:
            error_code = data[0] & 0x7F
            sense_key = data[2] & 0x0F
            asc = data[12]
            ascq = data[13]

            sense_keys = {
                0x00: "NO SENSE", 0x01: "RECOVERED ERROR",
                0x02: "NOT READY", 0x03: "MEDIUM ERROR",
                0x04: "HARDWARE ERROR", 0x05: "ILLEGAL REQUEST",
                0x06: "UNIT ATTENTION", 0x07: "DATA PROTECT",
                0x0B: "ABORTED COMMAND"
            }
            print(f"  Error code: 0x{error_code:02X}")
            print(f"  Sense key:  0x{sense_key:X} ({sense_keys.get(sense_key, 'Unknown')})")
            print(f"  ASC/ASCQ:   0x{asc:02X}/0x{ascq:02X}")

    def _msc_reset(self):
        """Bulk-only reset."""
        if not self.msc_client:
            print("MSC not open")
            return

        self.msc_client.bulk_only_reset()
        print("Bulk-only reset sent")

    # =========================================================================
    # Vendor Commands
    # =========================================================================

    def do_vendor(self, arg: str):
        """
        Vendor-specific USB commands.
        Usage: vendor <subcommand> [args]

        Subcommands:
            vendor in <bRequest> <wValue> <wIndex> [length]
                Send vendor IN control transfer (device to host)

            vendor out <bRequest> <wValue> <wIndex> [hex_data]
                Send vendor OUT control transfer (host to device)

            vendor iface_in <bRequest> <wValue> <wIndex> [length]
                Vendor IN to interface

            vendor iface_out <bRequest> <wValue> <wIndex> [hex_data]
                Vendor OUT to interface

            vendor ep_in <bRequest> <wValue> <wIndex> [length]
                Vendor IN to endpoint

            vendor ep_out <bRequest> <wValue> <wIndex> [hex_data]
                Vendor OUT to endpoint

        Request types:
            Device IN:    0xC0  Device OUT:    0x40
            Interface IN: 0xC1  Interface OUT: 0x41
            Endpoint IN:  0xC2  Endpoint OUT:  0x42

        Examples:
            vendor in 0x01 0x1234 0 64       # Vendor device IN
            vendor out 0x02 0x5678 0 DEADBEEF  # Vendor device OUT
            vendor iface_in 0x81 0 1 32     # Vendor interface IN to iface 1
        """
        if not self._check_attached():
            return

        if not arg:
            print("Usage: vendor <in|out|iface_in|iface_out|ep_in|ep_out> <args>")
            return

        args = arg.split()
        subcmd = args[0].lower()
        subargs = args[1:]

        try:
            if subcmd == 'in':
                self._vendor_transfer(0xC0, subargs)  # Device IN
            elif subcmd == 'out':
                self._vendor_transfer(0x40, subargs)  # Device OUT
            elif subcmd == 'iface_in':
                self._vendor_transfer(0xC1, subargs)  # Interface IN
            elif subcmd == 'iface_out':
                self._vendor_transfer(0x41, subargs)  # Interface OUT
            elif subcmd == 'ep_in':
                self._vendor_transfer(0xC2, subargs)  # Endpoint IN
            elif subcmd == 'ep_out':
                self._vendor_transfer(0x42, subargs)  # Endpoint OUT
            else:
                print(f"Unknown vendor subcommand: {subcmd}")
        except Exception as e:
            print(f"Error: {e}")

    def _vendor_transfer(self, bmRequestType: int, args: List[str]):
        """Execute vendor control transfer."""
        if len(args) < 3:
            print("Usage: vendor <type> <bRequest> <wValue> <wIndex> [length|data]")
            return

        bRequest = int(args[0], 0)
        wValue = int(args[1], 0)
        wIndex = int(args[2], 0)

        is_in = bool(bmRequestType & 0x80)

        if is_in:
            # IN transfer: expect length
            length = int(args[3]) if len(args) > 3 else 64
            status, data = self.client.control_transfer(
                bmRequestType, bRequest, wValue, wIndex, length=length)
            print(f"bmRequestType: 0x{bmRequestType:02X}")
            print(f"bRequest:      0x{bRequest:02X}")
            print(f"wValue:        0x{wValue:04X}")
            print(f"wIndex:        0x{wIndex:04X}")
            print(f"Status:        {status}")
            print(f"Data ({len(data)} bytes): {data.hex()}")
            self._print_ascii(data)
        else:
            # OUT transfer: expect hex data
            data = bytes.fromhex(args[3]) if len(args) > 3 else b''
            status, _ = self.client.control_transfer(
                bmRequestType, bRequest, wValue, wIndex, data=data)
            print(f"bmRequestType: 0x{bmRequestType:02X}")
            print(f"bRequest:      0x{bRequest:02X}")
            print(f"wValue:        0x{wValue:04X}")
            print(f"wIndex:        0x{wIndex:04X}")
            print(f"Data sent:     {data.hex() if data else '(none)'}")
            print(f"Status:        {status}")

    def do_raw(self, arg: str):
        """
        Raw USB transfers for advanced usage.
        Usage: raw <type> <args>

        Types:
            raw ctrl <bmReqType> <bReq> <wVal> <wIdx> [len|data]
                Raw control transfer

            raw bulk_in <ep> [length]
                Raw bulk IN transfer

            raw bulk_out <ep> <hex_data>
                Raw bulk OUT transfer

            raw int_in <ep> [length] [timeout_ms]
                Raw interrupt IN transfer

            raw int_out <ep> <hex_data>
                Raw interrupt OUT transfer

        Examples:
            raw ctrl 0x80 0x06 0x0100 0 18    # GET_DESCRIPTOR
            raw bulk_in 0x81 512              # Read 512 bytes from EP1 IN
            raw bulk_out 0x02 48454C4C4F      # Write "HELLO" to EP2 OUT
        """
        if not self._check_attached():
            return

        if not arg:
            print("Usage: raw <ctrl|bulk_in|bulk_out|int_in|int_out> <args>")
            return

        args = arg.split()
        subcmd = args[0].lower()
        subargs = args[1:]

        try:
            if subcmd == 'ctrl':
                self._raw_control(subargs)
            elif subcmd == 'bulk_in':
                self._raw_bulk_in(subargs)
            elif subcmd == 'bulk_out':
                self._raw_bulk_out(subargs)
            elif subcmd == 'int_in':
                self._raw_interrupt_in(subargs)
            elif subcmd == 'int_out':
                self._raw_interrupt_out(subargs)
            else:
                print(f"Unknown raw transfer type: {subcmd}")
        except Exception as e:
            print(f"Error: {e}")

    def _raw_control(self, args: List[str]):
        """Raw control transfer."""
        if len(args) < 4:
            print("Usage: raw ctrl <bmRequestType> <bRequest> <wValue> <wIndex> [len|data]")
            return

        bmRequestType = int(args[0], 0)
        bRequest = int(args[1], 0)
        wValue = int(args[2], 0)
        wIndex = int(args[3], 0)

        is_in = bool(bmRequestType & 0x80)

        if is_in:
            length = int(args[4]) if len(args) > 4 else 64
            status, data = self.client.control_transfer(
                bmRequestType, bRequest, wValue, wIndex, length=length)
            print(f"Status: {status}")
            print(f"Data ({len(data)} bytes): {data.hex()}")
            self._print_ascii(data)
        else:
            data = bytes.fromhex(args[4]) if len(args) > 4 else b''
            status, _ = self.client.control_transfer(
                bmRequestType, bRequest, wValue, wIndex, data=data)
            print(f"Status: {status}")

    def _raw_bulk_in(self, args: List[str]):
        """Raw bulk IN transfer."""
        if not args:
            print("Usage: raw bulk_in <endpoint> [length]")
            return

        endpoint = int(args[0], 0) | 0x80  # Ensure IN direction
        length = int(args[1]) if len(args) > 1 else 64

        status, data = self.client.bulk_transfer(endpoint, length=length)
        print(f"Status: {status}")
        print(f"Data ({len(data)} bytes): {data.hex()}")
        self._print_ascii(data)

    def _raw_bulk_out(self, args: List[str]):
        """Raw bulk OUT transfer."""
        if len(args) < 2:
            print("Usage: raw bulk_out <endpoint> <hex_data>")
            return

        endpoint = int(args[0], 0) & 0x7F  # Ensure OUT direction
        data = bytes.fromhex(args[1])

        status, _ = self.client.bulk_transfer(endpoint, data=data)
        print(f"Status: {status}")
        print(f"Sent {len(data)} bytes")

    def _raw_interrupt_in(self, args: List[str]):
        """Raw interrupt IN transfer."""
        if not args:
            print("Usage: raw int_in <endpoint> [length] [timeout_ms]")
            return

        endpoint = int(args[0], 0) | 0x80  # Ensure IN direction
        length = int(args[1]) if len(args) > 1 else 8
        timeout = float(args[2]) / 1000.0 if len(args) > 2 else 1.0

        try:
            status, data = self.client.interrupt_transfer(
                endpoint, length=length, timeout=timeout)
            print(f"Status: {status}")
            print(f"Data ({len(data)} bytes): {data.hex()}")
            self._print_ascii(data)
        except TimeoutError:
            print("Timeout")

    def _raw_interrupt_out(self, args: List[str]):
        """Raw interrupt OUT transfer."""
        if len(args) < 2:
            print("Usage: raw int_out <endpoint> <hex_data>")
            return

        endpoint = int(args[0], 0) & 0x7F  # Ensure OUT direction
        data = bytes.fromhex(args[1])

        status, _ = self.client.interrupt_transfer(endpoint, data=data)
        print(f"Status: {status}")
        print(f"Sent {len(data)} bytes")

    # =========================================================================
    # Utility Commands
    # =========================================================================

    def do_hexdump(self, arg: str):
        """
        Hex dump data.
        Usage: hexdump <hex_string>
        """
        if not arg:
            print("Usage: hexdump <hex_string>")
            return

        try:
            data = bytes.fromhex(arg.replace(' ', ''))
            self._hexdump(data)
        except Exception as e:
            print(f"Error: {e}")

    def do_config(self, arg: str):
        """
        Set device configuration.
        Usage: config [value]
        """
        if not self._check_attached():
            return

        config = int(arg) if arg else 1
        if self.client.set_configuration(config):
            print(f"Configuration {config} set")
        else:
            print("Failed to set configuration")

    def do_strings(self, arg: str):
        """
        Show all string descriptors.
        Usage: strings [max_index]
        """
        if not self._check_attached():
            return

        max_idx = int(arg) if arg else 10

        for i in range(max_idx):
            try:
                s = self.client.get_string_descriptor(i)
                if s and s != "04030904":  # Not just language ID
                    print(f"  String {i}: {s}")
            except Exception:
                break

    def do_reset(self, arg: str):
        """Reset current device (if supported)."""
        if not self._check_attached():
            return
        print("Device reset not implemented in USB/IP")

    def do_script(self, arg: str):
        """
        Execute commands from file.
        Usage: script <filename>
        """
        if not arg:
            print("Usage: script <filename>")
            return

        try:
            with open(arg) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        print(f"> {line}")
                        self.onecmd(line)
        except Exception as e:
            print(f"Error: {e}")

    def do_sleep(self, arg: str):
        """
        Sleep for seconds.
        Usage: sleep <seconds>
        """
        try:
            time.sleep(float(arg) if arg else 1.0)
        except Exception as e:
            print(f"Error: {e}")

    def do_quit(self, arg: str):
        """Exit the REPL."""
        print("Goodbye!")
        return True

    do_exit = do_quit
    do_q = do_quit

    # =========================================================================
    # Helpers
    # =========================================================================

    def _check_attached(self) -> bool:
        """Check if attached to device."""
        if not self.client or not self.client.device:
            print("Not attached to device. Use 'attach <busid>' first.")
            return False
        return True

    def _get_class_name(self, class_code: int) -> str:
        """Get USB class name."""
        classes = {
            0x00: "Composite",
            0x01: "Audio",
            0x02: "CDC",
            0x03: "HID",
            0x05: "Physical",
            0x06: "Image",
            0x07: "Printer",
            0x08: "Mass Storage",
            0x09: "Hub",
            0x0A: "CDC-Data",
            0x0B: "Smart Card",
            0x0D: "Content Security",
            0x0E: "Video",
            0x0F: "Healthcare",
            0x10: "AV",
            0xDC: "Diagnostic",
            0xE0: "Wireless",
            0xEF: "Misc",
            0xFE: "App Specific",
            0xFF: "Vendor",
        }
        return classes.get(class_code, f"0x{class_code:02x}")

    def _get_ep_type(self, attributes: int) -> str:
        """Get endpoint type name."""
        types = {0: "Control", 1: "Isochronous", 2: "Bulk", 3: "Interrupt"}
        return types.get(attributes & 0x03, "Unknown")

    def _print_ascii(self, data: bytes):
        """Print ASCII representation if printable."""
        try:
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in data)
            if any(32 <= b < 127 for b in data):
                print(f"ASCII: {ascii_str}")
        except Exception:
            pass

    def _hexdump(self, data: bytes, width: int = 16):
        """Print hex dump."""
        for i in range(0, len(data), width):
            chunk = data[i:i+width]
            hex_str = ' '.join(f'{b:02x}' for b in chunk)
            ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
            print(f"{i:04x}: {hex_str:<{width*3}} {ascii_str}")


def main():
    parser = argparse.ArgumentParser(description="USB/IP Client REPL")
    parser.add_argument("--host", default="localhost", help="USB/IP server host")
    parser.add_argument("--port", type=int, default=3240, help="USB/IP server port")

    args = parser.parse_args()

    repl = USBIPRepl(args.host, args.port)

    try:
        repl.cmdloop()
    except KeyboardInterrupt:
        print("\nGoodbye!")


if __name__ == "__main__":
    main()
