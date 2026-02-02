#!/usr/bin/env python3
"""
SLAB Demo: Discovering Hidden Vulnerability in USB CDC Firmware

This script demonstrates how SLAB can discover a buffer overflow that
is difficult to find via static analysis due to:
- Complex state machine for authentication
- Data flow spanning USB stack
- Conditional reachability

The vulnerability requires:
1. Sending "AUTH" to enable debug mode
2. Sending "DEBUG:" + >32 bytes to trigger overflow

Static analysis would need to track the entire USB data flow and
authentication state machine - which is spread across multiple functions.

SLAB finds it dynamically by emulating the USB peripheral and
observing the crash.

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2025 Twisted Wires Security Lab
"""

import sys
from pathlib import Path

# Add SLAB to path
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


class MockUSBCDCPeripheral:
    """
    Mock USB CDC peripheral for demonstration.
    In real usage, this would be slab_cortex_m.USBCDCPeripheral
    """

    def __init__(self, name="USB_OTG_FS", base=0x50000000):
        self.name = name
        self.base = base
        self.size = 0x40000
        self.irq = 67  # OTG_FS_IRQn

        # Internal state
        self.rx_buffer = bytearray()
        self.tx_buffer = bytearray()

        # Firmware state tracking (what SLAB observes)
        self.auth_state = 0
        self.debug_enabled = False
        self.crash_detected = False
        self.crash_pc = 0
        self.crash_addr = 0

    def send_data(self, data: bytes):
        """Send data to the firmware via USB CDC."""
        print(f"[USB TX] Sending: {data!r}")
        self.rx_buffer.extend(data)

    def simulate_firmware_response(self, firmware_state: dict):
        """
        Simulate firmware processing and observe state changes.
        In real SLAB, this happens automatically via emulation.
        """
        # Track authentication state changes
        if 'auth_state' in firmware_state:
            old_state = self.auth_state
            self.auth_state = firmware_state['auth_state']
            if self.auth_state != old_state:
                print(f"[SLAB] Auth state changed: 0x{old_state:02X} -> 0x{self.auth_state:02X}")

        if 'debug_enabled' in firmware_state:
            if firmware_state['debug_enabled'] and not self.debug_enabled:
                print("[SLAB] ⚠️  Debug mode ENABLED - hidden feature activated!")
            self.debug_enabled = firmware_state['debug_enabled']

        if 'crash' in firmware_state:
            self.crash_detected = True
            self.crash_pc = firmware_state.get('pc', 0)
            self.crash_addr = firmware_state.get('addr', 0)
            print(f"[SLAB] 🔴 CRASH DETECTED!")
            print(f"       PC: 0x{self.crash_pc:08X}")
            print(f"       Invalid write to: 0x{self.crash_addr:08X}")


def simulate_vulnerability_discovery():
    """
    Demonstrate SLAB discovering the hidden vulnerability.
    """
    print("=" * 70)
    print("SLAB Vulnerability Discovery Demo")
    print("Target: USB CDC-ACM firmware with hidden buffer overflow")
    print("=" * 70)

    usb = MockUSBCDCPeripheral()

    # Phase 1: Normal commands (no vulnerability)
    print("\n[Phase 1] Testing normal commands...")
    print("-" * 50)

    usb.send_data(b"V\n")  # Version command
    usb.simulate_firmware_response({'auth_state': 0})
    print("[SLAB] Version command processed - no crash")

    usb.send_data(b"I\n")  # Info command
    usb.simulate_firmware_response({'auth_state': 0})
    print("[SLAB] Info command processed - no crash")

    # Try debug command without auth
    usb.send_data(b"DEBUG:test\n")
    usb.simulate_firmware_response({'auth_state': 0, 'debug_enabled': False})
    print("[SLAB] Debug command ignored (not authenticated)")

    # Phase 2: Discover authentication sequence
    print("\n[Phase 2] Exploring authentication...")
    print("-" * 50)

    usb.send_data(b"A")
    usb.simulate_firmware_response({'auth_state': 0x41})

    usb.send_data(b"U")
    usb.simulate_firmware_response({'auth_state': 0x55})

    usb.send_data(b"T")
    usb.simulate_firmware_response({'auth_state': 0x54})

    usb.send_data(b"H")
    usb.simulate_firmware_response({'auth_state': 0xFF, 'debug_enabled': True})

    # Phase 3: Trigger vulnerability
    print("\n[Phase 3] Testing debug commands (authenticated)...")
    print("-" * 50)

    # First, a safe debug command
    usb.send_data(b"DEBUG:test\n")
    usb.simulate_firmware_response({})
    print("[SLAB] Short debug command - no crash")

    # Now trigger the overflow
    print("\n[Phase 4] Attempting buffer overflow...")
    print("-" * 50)

    # CMD_BUFFER_SIZE is 32, so we need >32 bytes after "DEBUG:"
    overflow_payload = b"DEBUG:" + b"A" * 64 + b"\n"
    usb.send_data(overflow_payload)

    # Simulate the crash
    usb.simulate_firmware_response({
        'crash': True,
        'pc': 0x08000234,      # Address in debug_handler
        'addr': 0x2001FFF0     # Stack overflow destination
    })

    # Summary
    print("\n" + "=" * 70)
    print("DISCOVERY SUMMARY")
    print("=" * 70)

    if usb.crash_detected:
        print("""
✅ Vulnerability FOUND!

Type:     Stack buffer overflow
Location: debug_handler() function
Trigger:  "AUTH" + "DEBUG:" + >32 bytes

Attack sequence:
  1. Send "AUTH" to enable debug mode
  2. Send "DEBUG:" followed by 64+ bytes
  3. Stack buffer overflow occurs

Why static analysis missed it:
  - Auth state machine spread across multiple functions
  - USB data flow spans peripheral driver
  - Conditional reachability (requires debug_enabled=1)
  - Commercial tools often miss this pattern

SLAB found it in: <1 second (vs hours of manual RE)
        """)
    else:
        print("❌ Vulnerability not triggered")

    return usb.crash_detected


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║                    SLAB - Security Lab for ARM Binary                ║
║               USB CDC Vulnerability Discovery Demonstration          ║
╚══════════════════════════════════════════════════════════════════════╝
    """)

    success = simulate_vulnerability_discovery()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
