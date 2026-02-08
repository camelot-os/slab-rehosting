#!/usr/bin/env python3
"""
USB OTG Demo - Bidirectional USBIP Support

This demo shows the complete USB OTG capabilities of Slab:

1. Device Mode: Emulator acts as USB device (CDC-ACM, HID, etc.)
   - Host PC enumerates the emulated device via USBIP
   - Firmware interacts with USB as if it were real hardware

2. Host Mode: Emulator acts as USB host
   - Emulator enumerates real USB devices via USBIP
   - Firmware can communicate with external USB peripherals

3. OTG Mode: Dynamic switching based on ID pin / cable detection

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │                     Slab Emulator                        │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │              Firmware Under Test                  │   │
    │  │   (Uses USB API - doesn't know it's emulated)    │   │
    │  └───────────────────┬──────────────────────────────┘   │
    │                      │ USB API                          │
    │  ┌───────────────────┴──────────────────────────────┐   │
    │  │              USB OTG Controller                   │   │
    │  │         (DWC2-compatible registers)              │   │
    │  └───────────────────┬──────────────────────────────┘   │
    │                      │                                   │
    │  ┌─────────────┬─────┴─────┬─────────────┐              │
    │  │ Device Mode │           │  Host Mode  │              │
    │  │ USBIP Server│           │ USBIP Client│              │
    │  └──────┬──────┘           └──────┬──────┘              │
    └─────────┼─────────────────────────┼─────────────────────┘
              │ TCP/IP                  │ TCP/IP
              ▼                         ▼
    ┌──────────────────┐      ┌──────────────────┐
    │    Host PC       │      │   usbipd Server  │
    │ (usbip attach)   │      │   (real device)  │
    └──────────────────┘      └──────────────────┘

Usage:
    # Device mode demo (emulator is a USB device)
    python3 usb_otg_demo.py device

    # Host mode demo (emulator is a USB host)
    python3 usb_otg_demo.py host

    # Self-test (two emulators talking to each other)
    python3 usb_otg_demo.py selftest

SPDX-License-Identifier: GPL-2.0-or-later
Copyright (C) 2025 Twisted Wires Security Lab
"""

import argparse
import sys
import time
import threading
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from slab_cortex_m.usb_otg import (
    OTGController, OTGMode, USBSpeed, USBDevice,
    USBIPServer, USBIPClient,
    create_cdc_acm_device, create_hid_keyboard_device
)
from slab_cortex_m.usbip_client import USBIPClient as PythonUSBIPClient, CDCACMClient

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def print_header(title: str):
    """Print formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def demo_device_mode():
    """
    Demonstrate Device Mode.

    The emulator creates a virtual USB device (CDC-ACM serial port)
    that can be enumerated by the host PC using USBIP.
    """
    print_header("USB OTG Demo - Device Mode")

    print("""
In this mode, the emulator acts as a USB device.
The host PC can attach to it using the USBIP client.

Steps:
1. Emulator starts USBIP server with virtual CDC-ACM device
2. Host PC lists available devices: usbip list -r localhost
3. Host PC attaches device: sudo usbip attach -r localhost -b 1-1
4. A new /dev/ttyACM* appears on the host
5. Host can communicate via serial: screen /dev/ttyACM0 115200
""")

    # Create OTG controller
    otg = OTGController()

    # Create a CDC-ACM device
    device = create_cdc_acm_device(
        vid=0x1234,
        pid=0x5678
    )
    device.manufacturer = "Twisted Wires"
    device.product = "Slab Virtual Serial"
    device.serial = "SLAB-CDC-001"

    print(f"\nCreated device: {device.product}")
    print(f"  VID:PID = {device.vendor_id:04x}:{device.product_id:04x}")
    print(f"  Class: CDC-ACM (USB Serial)")

    # Data handler for CDC
    rx_buffer = bytearray()

    def on_data_out(endpoint: int, data: bytes):
        """Handle data from host."""
        rx_buffer.extend(data)
        print(f"  RX [{endpoint}]: {data}")

    def on_data_in(endpoint: int, length: int) -> bytes:
        """Provide data to host (echo)."""
        # Echo back what we received
        if rx_buffer:
            data = bytes(rx_buffer[:length])
            del rx_buffer[:length]
            return data
        return b''

    # Start device mode
    print("\nStarting USBIP server on port 3240...")

    otg.start_device_mode(device, port=3240)

    if otg.usbip_server:
        otg.usbip_server.on_data_out = on_data_out
        otg.usbip_server.on_data_in = on_data_in

    print("\nServer running. To connect from host:")
    print("  $ sudo modprobe vhci-hcd")
    print("  $ usbip list -r localhost")
    print("  $ sudo usbip attach -r localhost -b 1-1")
    print("\nPress Ctrl-C to stop...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    otg.stop()
    print("\nDevice mode stopped.")


def demo_host_mode():
    """
    Demonstrate Host Mode.

    The emulator acts as a USB host, enumerating devices from
    a USBIP server (which could be real hardware on another machine).
    """
    print_header("USB OTG Demo - Host Mode")

    print("""
In this mode, the emulator acts as a USB host.
It can enumerate and communicate with USB devices via USBIP.

Prerequisites:
- Run 'usbipd' on a machine with real USB devices
- Or run another Slab instance in device mode

Steps:
1. Start usbipd: sudo usbipd
2. Bind a device: sudo usbip bind -b 1-1
3. Emulator connects and enumerates the device
""")

    # Create OTG controller
    otg = OTGController()

    # Try to list devices
    print("\nSearching for USBIP servers...")

    hosts_to_try = [
        ("localhost", 3240),
        ("127.0.0.1", 3240),
    ]

    for host, port in hosts_to_try:
        try:
            print(f"\n  Trying {host}:{port}...")
            devices = otg.start_host_mode(host, port)

            if devices:
                print(f"\n  Found {len(devices)} device(s):")
                for dev in devices:
                    print(f"    - {dev.vendor_id:04x}:{dev.product_id:04x} "
                          f"class={dev.device_class:02x}")
                break
            else:
                print("    No devices available")

        except Exception as e:
            print(f"    Connection failed: {e}")

    else:
        print("\nNo USBIP servers found.")
        print("Start a server with: python3 usb_otg_demo.py device")

    otg.stop()


def demo_selftest():
    """
    Self-test: Two emulators communicating via USBIP.

    One acts as device (server), one acts as host (client).
    They communicate over localhost.
    """
    print_header("USB OTG Demo - Self Test")

    print("""
This test runs both device and host mode simultaneously.
The device emulator creates a virtual CDC-ACM device.
The host emulator connects and sends/receives data.
""")

    # Shared state
    server_ready = threading.Event()
    test_passed = False
    test_data = b"Hello from OTG self-test!\r\n"
    received_data = bytearray()

    # Device side (server)
    def run_device():
        device = create_cdc_acm_device(0x1234, 0x5678)

        server = USBIPServer(device, port=3241)

        def on_data_out(ep: int, data: bytes):
            received_data.extend(data)
            print(f"  Device RX: {data}")

        def on_data_in(ep: int, length: int) -> bytes:
            # Echo back
            if received_data:
                data = bytes(received_data[:length])
                del received_data[:length]
                return data
            return b''

        server.on_data_out = on_data_out
        server.on_data_in = on_data_in

        server.start()
        server_ready.set()

        print("  Device: USBIP server started on port 3241")

        # Wait for test to complete
        time.sleep(5)

        server.stop()
        print("  Device: Server stopped")

    # Host side (client)
    def run_host():
        nonlocal test_passed

        # Wait for server
        server_ready.wait(timeout=5.0)
        time.sleep(0.5)

        print("  Host: Connecting to device...")

        try:
            client = PythonUSBIPClient("localhost", 3241)

            # List devices
            devices = client.list_devices()
            print(f"  Host: Found {len(devices)} device(s)")

            if devices:
                # Attach to first device
                busid = devices[0].busid
                client.attach(busid)
                print(f"  Host: Attached to {busid}")

                # Get descriptors
                desc = client.get_device_descriptor()
                print(f"  Host: Device descriptor: {desc.hex()[:36]}...")

                # Set configuration
                client.set_configuration(1)
                print("  Host: Configuration 1 set")

                # Send test data
                status, _ = client.bulk_transfer(0x02, data=test_data)
                print(f"  Host: Sent test data, status={status}")

                # Read echo
                time.sleep(0.2)
                status, response = client.bulk_transfer(0x82, length=64)
                print(f"  Host: Received: {response}")

                if response == test_data:
                    test_passed = True
                    print("  Host: Echo test PASSED!")
                else:
                    print("  Host: Echo test FAILED")

            client.disconnect()

        except Exception as e:
            print(f"  Host: Error - {e}")
            import traceback
            traceback.print_exc()

    # Run both threads
    print("\nStarting device and host threads...")

    device_thread = threading.Thread(target=run_device)
    host_thread = threading.Thread(target=run_host)

    device_thread.start()
    host_thread.start()

    host_thread.join()
    device_thread.join()

    print("\n" + "=" * 60)
    if test_passed:
        print("  SELF-TEST PASSED!")
    else:
        print("  SELF-TEST FAILED")
    print("=" * 60)

    return test_passed


def demo_vulnerable_device():
    """
    Demonstrate a vulnerable USB device (DVID-style).

    Creates a USB device with intentional vulnerabilities:
    1. Buffer overflow in string descriptor
    2. Unvalidated control transfers
    3. Debug backdoor endpoint
    """
    print_header("USB OTG Demo - Vulnerable Device (DVID-style)")

    print("""
This demo creates a deliberately vulnerable USB device.
Useful for testing USB fuzzing and security tools.

Vulnerabilities:
1. String descriptor buffer overflow (long strings crash parser)
2. Vendor control requests expose memory
3. Debug endpoint bypasses authentication
4. Firmware update doesn't verify signatures
""")

    class VulnerableUSBDevice:
        """A USB device with intentional security vulnerabilities."""

        def __init__(self):
            self.secret = b"FLAG{USB_V3nd0r_Backd00r_CVE-2025-XXXX}"
            self.debug_enabled = False
            self.firmware = bytearray(1024)

        def handle_control(self, bmRequestType: int, bRequest: int,
                          wValue: int, wIndex: int, data: bytes) -> bytes:
            """Handle control transfers with vulnerabilities."""

            # Vendor request type
            if (bmRequestType & 0x60) == 0x40:

                if bRequest == 0x01:
                    # VULN: Read arbitrary memory
                    addr = wValue | (wIndex << 16)
                    length = len(data) if data else 64
                    print(f"  [VULN] Memory read at 0x{addr:08x}, len={length}")
                    return self.secret[:length]

                elif bRequest == 0x02:
                    # VULN: Enable debug without auth
                    self.debug_enabled = True
                    print("  [VULN] Debug enabled without authentication!")
                    return b'\x01'

                elif bRequest == 0x03:
                    # VULN: Firmware update without signature check
                    offset = wValue
                    if offset + len(data) <= len(self.firmware):
                        self.firmware[offset:offset+len(data)] = data
                        print(f"  [VULN] Firmware written at offset {offset}")
                    return b'\x00'

                elif bRequest == 0xFF:
                    # Hidden debug command - dump secrets
                    if self.debug_enabled:
                        print("  [VULN] Secret dumped via debug command!")
                        return self.secret
                    return b''

            return b''

    vuln_device = VulnerableUSBDevice()

    # Create USB device
    device = USBDevice(
        vendor_id=0xDEAD,
        product_id=0xBEEF,
        device_class=0xFF,  # Vendor-specific
        device_subclass=0x00,
        device_protocol=0x00,
        manufacturer="VulnCorp",
        product="Insecure Device v1.0",
        serial="VULN001"
    )

    print(f"\nVulnerable device created:")
    print(f"  VID:PID = {device.vendor_id:04x}:{device.product_id:04x}")
    print(f"  Secret flag hidden in device memory")
    print()
    print("Attack vectors:")
    print("  1. Vendor Request 0x01: Read memory (wValue=addr_lo, wIndex=addr_hi)")
    print("  2. Vendor Request 0x02: Enable debug mode")
    print("  3. Vendor Request 0x03: Write firmware (no signature check)")
    print("  4. Vendor Request 0xFF: Dump secrets (if debug enabled)")
    print()

    # Start server
    server = USBIPServer(device, port=3242)

    original_control = server._handle_control
    def patched_control(setup: bytes, data: bytes):
        bmRequestType, bRequest, wValue, wIndex, wLength = \
            __import__('struct').unpack("<BBHHH", setup)

        # Check for vendor requests
        if (bmRequestType & 0x60) == 0x40:
            result = vuln_device.handle_control(
                bmRequestType, bRequest, wValue, wIndex, data)
            if result:
                return result, 0

        return original_control(setup, data)

    server._handle_control = patched_control

    server.start()
    print("Vulnerable device server running on port 3242")
    print("Connect with: python3 -m slab_cortex_m.usbip_client shell --port 3242 --busid 1-1")
    print("\nPress Ctrl-C to stop...")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    server.stop()
    print("\nVulnerable device stopped.")


def main():
    parser = argparse.ArgumentParser(description="USB OTG Demo")
    parser.add_argument("mode", choices=["device", "host", "selftest", "vuln"],
                       help="Demo mode to run")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 60)
    print("       Slab USB OTG Demo")
    print("       Bidirectional USBIP Support")
    print("=" * 60)

    if args.mode == "device":
        demo_device_mode()
    elif args.mode == "host":
        demo_host_mode()
    elif args.mode == "selftest":
        success = demo_selftest()
        sys.exit(0 if success else 1)
    elif args.mode == "vuln":
        demo_vulnerable_device()


if __name__ == "__main__":
    main()
