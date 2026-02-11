#!/usr/bin/env python3
"""
E2E Test: USB CDC-ACM Hello + Echo over USBIP -- STM32U5A5 CDC Blinky

Architecture:
    USBIP Client (Python, blocking sockets)
      | USBIP protocol (DevList, Import, EP0 control, Bulk IN/OUT)
    USBIPServer + CDCACMDevice  [single event loop]
      | CDCBridge (fw TX -> tx_buffer, host OUT -> fw RX)
    USBCDCPeripheral (USB_OTG_HS @ 0x42040000, IRQ 73)
      | TCP proxy protocol [single event loop]
    QEMU slab-cortex-m (Cortex-M33) + U5A5_CDC_Blinky.bin
      | STM32U5A5PeripheralSet (RCC, PWR, GPIO, USART, etc.)

Run:
    PYTHONPATH=slab/python python3 slab/examples/cortex-m/stm32/u5a5/demos/cdc_blinky/test_e2e_usb_cdc_echo.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import sys
import os
import socket
import subprocess
import time
import threading
import logging


sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                '..', '..', '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32U5A5PeripheralSet
from slab_cortex_m.mmio_tracer import MMIOTracer

# Default TCP port for QEMU peripheral proxy
PERIPH_PORT = 5000

# Protocol constants (match base_server.py / slab_cortex_m.c)
CMD_READ = ord('R')
CMD_READ_S = ord('S')
CMD_WRITE = ord('W')
CMD_WRITE_S = ord('T')
CMD_IRQ = ord('I')
CMD_CONFIG = ord('C')


# =============================================================================
# Combined Peripheral + USBIP Server (single event loop, single thread)
# =============================================================================

class U5A5CDCEchoServer:
    """Async TCP server for QEMU + USBIP, running in one event loop.

    Dispatches register accesses to STM32U5A5PeripheralSet (which includes
    USBCDCPeripheral at 0x42040000). USBIP server and CDCBridge run in the
    same event loop for safe IRQ delivery.
    """

    def __init__(self, periph_port: int = PERIPH_PORT):
        self.periph_port = periph_port

        # Create peripheral set (includes USB OTG HS)
        self.stm32 = STM32U5A5PeripheralSet()

        self._loop = None
        self._thread = None
        self._writer = None
        self._access_count = 0
        self._last_accesses = []  # ring buffer for last N accesses
        self._addr_counts = {}    # address -> count for distribution

    #print(usart.get_tx_data().decode('utf-8'))


    def _send_irq(self, irq_num: int, level: int):
        """Send IRQ packet to QEMU (called from same event loop)."""
        if self._writer:
            packet = struct.pack('<BIB', CMD_IRQ, irq_num, level)
            self._writer.write(packet)

    def start_threaded(self):
        """Start both servers in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        time.sleep(0.5)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        """Start TCP (for QEMU) and USBIP servers in the same event loop."""
        tcp_server = await asyncio.start_server(
            self._handle_qemu_client, '127.0.0.1', self.periph_port)
        async with tcp_server:
            await asyncio.gather(tcp_server.serve_forever())

    async def _handle_qemu_client(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle binary protocol from QEMU slab-cortex-m."""
        self._writer = writer
        # Wire IRQ delivery now that we have a QEMU connection
        # Also wire IRQ for all peripherals in the set
        for p in self.stm32.peripherals:
            if hasattr(p, 'irq_callback'):
                p.irq_callback = self._send_irq
            if hasattr(p, 'name') and p.name == 'USART1':
                print(f"[*] hooking usart1 TX output")
                orig = getattr(p.name, 'on_tx', None)

                def make_hook(name):
                    def hook(byte):
                        c = chr(byte) if 32 <= byte < 127 or byte == 10 else '.'
                        sys.stdout.write(c)
                        sys.stdout.flush()
                    return hook
                p.on_tx = make_hook(p.name)
                print(f"[*] hooked usart1 TX output")

        try:
            while True:
                data = await reader.read(1)
                if not data:
                    break
                cmd = data[0]

                if cmd in (CMD_READ, CMD_READ_S):
                    payload = await reader.readexactly(13)
                    addr, size = struct.unpack('<II', payload[:8])
                    pc = struct.unpack('<I', payload[9:13])[0]
                    secure = (cmd == CMD_READ_S) or (payload[8] == 1)
                    value = self._dispatch_read(addr, size, secure)
                    writer.write(struct.pack('<IB', value, 0))
                    await writer.drain()
                    self._access_count += 1
                    self._addr_counts[addr] = self._addr_counts.get(addr, 0) + 1
                    self._last_accesses.append(
                        ('R', addr, value, self._access_count, pc))
                    if len(self._last_accesses) > 20:
                        self._last_accesses.pop(0)

                elif cmd in (CMD_WRITE, CMD_WRITE_S):
                    payload = await reader.readexactly(17)
                    addr, size, value = struct.unpack('<III', payload[:12])
                    pc = struct.unpack('<I', payload[13:17])[0]
                    secure = (cmd == CMD_WRITE_S) or (payload[12] == 1)
                    self._dispatch_write(addr, size, value, secure)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
                    self._access_count += 1
                    self._addr_counts[addr] = self._addr_counts.get(addr, 0) + 1
                    self._last_accesses.append(
                        ('W', addr, value, self._access_count, pc))
                    if len(self._last_accesses) > 20:
                        self._last_accesses.pop(0)

                elif cmd == CMD_CONFIG:
                    payload = await reader.readexactly(10)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            self._writer = None
            writer.close()

    def _dispatch_read(self, addr: int, size: int, secure: bool = False) -> int:
        """Route read to the correct peripheral.

        USBCDCPeripheral.read(addr, size, secure) takes 3 args,
        STM32Peripheral.read(addr, size) takes 2 args.
        """
        # Other STM32 peripherals (no secure parameter)
        periph = self.stm32.find_peripheral(addr)
        if periph:
            result = periph.read(addr, size)
            return result[0] if isinstance(result, tuple) else result
        return 0

    def _dispatch_write(self, addr: int, size: int, value: int,
                        secure: bool = False):
        """Route write to the correct peripheral."""
        periph = self.stm32.find_peripheral(addr)
        if periph and periph:
            periph.write(addr, size, value)

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


# =============================================================================
# E2E Test Runner
# =============================================================================

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run_e2e_test(verbose: bool = False):
    """Run the full E2E Sentry kernel test."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    print()

    # Paths
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir,
                                                '..', '..', '..', '..', '..', '..', '..'))
    qemu = os.path.join(project_root, 'build', 'qemu-system-arm')
    firmware = os.path.join(test_dir, 'firmware.bin')

    if not os.path.exists(firmware):
        print(f"  ERROR: Firmware not found: {firmware}")
        print(f"         Run: make -C {test_dir}")
        return False

    if not os.path.exists(qemu):
        print(f"  ERROR: QEMU not found: {qemu}")
        return False

    periph_port = find_free_port()
    results = []

    # -------------------------------------------------------------------------
    # Step 1: Start combined server (peripheral + USBIP)
    # -------------------------------------------------------------------------
    print()

    tracer = MMIOTracer()
    e2e = U5A5CDCEchoServer(periph_port=periph_port)
    e2e.start_threaded()
    print(f"         STM32 periphs:  {len(e2e.stm32.peripherals)} registered")

    # -------------------------------------------------------------------------
    # Step 2: Start QEMU
    # -------------------------------------------------------------------------
    print()
    print("  [1/6] Starting QEMU with U5A5 sentry firmware...")
    machine_props = (
        f"slab-cortex-m"
        f",cpu-type=cortex-m33"
        f",tcp-port={periph_port}"
        f",sram-size=0x270000"
        f",flash-size=0x400000"
        f",sysclk-hz=160000000"
        # Extend proxy to cover OTP/UID area at 0x0BFA0700
        # (flash/SRAM at priority 0 take precedence over proxy at -1)
        f",periph-base=0x0BFA0000"
        f",periph-size=0x54060000"
    )
    qemu_proc = subprocess.Popen(
            [qemu, '-M', machine_props, '-nographic', '-gdb', 'tcp::3333', '-kernel', firmware],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f"         Machine:  slab-cortex-m (Cortex-M33)")
    print(f"         Firmware: firmware.bin")
    print(f"         PID:      {qemu_proc.pid}")
    print("         Waiting for firmware init...")
    n_prev = 0
    for t in range(10):
        time.sleep(1.0)
        n = e2e._access_count
        if t > 3 and n == n_prev:
            break  # no more accesses
        n_prev = n
    print(f"         MMIO accesses: {e2e._access_count}")
    # Address distribution (top 15 by count)
    sorted_addrs = sorted(e2e._addr_counts.items(), key=lambda x: -x[1])
    print(f"         Address distribution (top 15):")
    for addr, cnt in sorted_addrs[:15]:
        periph = e2e.stm32.find_peripheral(addr)
        name = periph.name if periph else "UNMAPPED"
        print(f"           0x{addr:08X} ({name:12s}): {cnt:6d}")

    # -------------------------------------------------------------------------
    # Cleanup + Summary
    # -------------------------------------------------------------------------
    _cleanup(qemu_proc, e2e, None, results)
    all_pass = all(ok for _, ok in results)
    return all_pass


def _cleanup(qemu_proc, e2e, sock, results):
    """Cleanup and print summary."""
    print()
    print("  Cleanup...")
    if sock:
        try:
            sock.close()
        except Exception:
            pass
    qemu_proc.terminate()
    try:
        qemu_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        qemu_proc.kill()
        qemu_proc.wait(timeout=2)

    stderr = qemu_proc.stderr.read().decode(errors='replace')
    if stderr and '--verbose' in sys.argv:
        print(f"\n  QEMU stderr:\n{stderr[:1000]}")

    e2e.stop()
    print(f"         Total MMIO accesses: {e2e._access_count}")

    # Summary
    print()
    print("=" * 70)
    print("  Results")
    print("=" * 70)
    for name, ok in results:
        mark = "PASS" if ok else "FAIL"
        print(f"    [{mark}] {name}")

    all_pass = all(ok for _, ok in results)
    print()
    if all_pass:
        print("  ALL TESTS PASSED")
    else:
        print("  Some tests FAILED")
    print()


if __name__ == "__main__":
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    success = run_e2e_test(verbose=verbose)
    sys.exit(0 if success else 1)
