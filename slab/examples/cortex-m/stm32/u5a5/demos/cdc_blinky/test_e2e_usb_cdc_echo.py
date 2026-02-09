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
from slab_cortex_m.cdc_bridge import CDCBridge
from slab_cortex_m.usbip_server import USBIPServer, CDCACMDevice

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
# USBIP Client Helpers (blocking sockets, run from main thread)
# =============================================================================

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly n bytes from a socket."""
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError(f"Connection closed, got {len(data)}/{n} bytes")
        data += chunk
    return data


def usbip_devlist(sock: socket.socket) -> dict:
    """Send OP_REQ_DEVLIST and parse response."""
    req = struct.pack(">HHI", 0x0111, 0x8005, 0)
    sock.sendall(req)

    resp = _recv_exact(sock, 12)
    version, command, status, num_devices = struct.unpack(">HHII", resp)
    assert command == 0x0005, f"Expected OP_REP_DEVLIST, got 0x{command:04X}"

    devices = []
    for _ in range(num_devices):
        dev_data = _recv_exact(sock, 312)
        busid = dev_data[256:288].rstrip(b'\x00').decode()
        vid, pid = struct.unpack(">HH", dev_data[300:304])
        num_ifaces = dev_data[311]
        _recv_exact(sock, num_ifaces * 4)
        devices.append({'busid': busid, 'vid': vid, 'pid': pid})

    return {'status': status, 'devices': devices}


def usbip_import(sock: socket.socket, busid: str = "1-1") -> dict:
    """Send OP_REQ_IMPORT and parse response."""
    busid_bytes = busid.encode().ljust(32, b'\x00')
    req = struct.pack(">HHI", 0x0111, 0x8003, 0) + busid_bytes
    sock.sendall(req)

    resp = _recv_exact(sock, 8)
    version, command, status = struct.unpack(">HHI", resp)
    assert command == 0x0003, f"Expected OP_REP_IMPORT, got 0x{command:04X}"

    if status == 0:
        dev_data = _recv_exact(sock, 312)
        vid, pid = struct.unpack(">HH", dev_data[300:304])
        return {'status': status, 'vid': vid, 'pid': pid}

    return {'status': status}


def usbip_ep0_out(sock: socket.socket, seqnum: int,
                  setup: bytes, data: bytes = b'') -> int:
    """Send EP0 OUT (host-to-device) control transfer. Returns status."""
    transfer_len = len(data)
    submit = struct.pack(">IIIII",
        0x00000001,   # CMD_SUBMIT
        seqnum,
        0x00010001,   # devid
        0,            # direction = OUT
        0             # ep = 0
    )
    submit += struct.pack(">IIIII", 0, transfer_len, 0, 0, 0)
    submit += setup[:8].ljust(8, b'\x00')
    if data:
        submit += data
    sock.sendall(submit)

    resp = _recv_exact(sock, 48)
    status = struct.unpack(">i", resp[20:24])[0]
    return status


def usbip_ep0_in(sock: socket.socket, seqnum: int,
                 setup: bytes, max_len: int = 64) -> bytes:
    """Send EP0 IN (device-to-host) control transfer. Returns data."""
    submit = struct.pack(">IIIII",
        0x00000001,   # CMD_SUBMIT
        seqnum,
        0x00010001,   # devid
        1,            # direction = IN
        0             # ep = 0
    )
    submit += struct.pack(">IIIII", 0, max_len, 0, 0, 0)
    submit += setup[:8].ljust(8, b'\x00')
    sock.sendall(submit)

    # Server sends 48-byte header + actual_length bytes (not max_len)
    hdr = _recv_exact(sock, 48)
    actual_length = struct.unpack(">I", hdr[24:28])[0]
    data = _recv_exact(sock, actual_length) if actual_length > 0 else b''
    return data


def usbip_bulk_out(sock: socket.socket, seqnum: int, data: bytes) -> int:
    """Send bulk OUT transfer to EP1. Returns actual_length."""
    submit = struct.pack(">IIIII",
        0x00000001, seqnum, 0x00010001, 0, 1)
    submit += struct.pack(">IIIII", 0, len(data), 0, 0, 0)
    submit += b'\x00' * 8
    submit += data
    sock.sendall(submit)

    resp = _recv_exact(sock, 48)
    actual_length = struct.unpack(">I", resp[24:28])[0]
    return actual_length


def usbip_bulk_in(sock: socket.socket, seqnum: int, max_len: int = 64) -> bytes:
    """Send bulk IN transfer from EP1. Returns received data."""
    submit = struct.pack(">IIIII",
        0x00000001, seqnum, 0x00010001, 1, 1)
    submit += struct.pack(">IIIII", 0, max_len, 0, 0, 0)
    submit += b'\x00' * 8
    sock.sendall(submit)

    # Server sends 48-byte header + actual_length bytes (not max_len)
    hdr = _recv_exact(sock, 48)
    actual_length = struct.unpack(">I", hdr[24:28])[0]
    data = _recv_exact(sock, actual_length) if actual_length > 0 else b''
    return data


# =============================================================================
# Combined Peripheral + USBIP Server (single event loop, single thread)
# =============================================================================

class U5A5CDCEchoServer:
    """Async TCP server for QEMU + USBIP, running in one event loop.

    Dispatches register accesses to STM32U5A5PeripheralSet (which includes
    USBCDCPeripheral at 0x42040000). USBIP server and CDCBridge run in the
    same event loop for safe IRQ delivery.
    """

    def __init__(self, periph_port: int = PERIPH_PORT, usbip_port: int = 3240):
        self.periph_port = periph_port
        self.usbip_port = usbip_port

        # Create peripheral set (includes USB OTG HS)
        self.stm32 = STM32U5A5PeripheralSet()
        self.usb_periph = self.stm32.usb

        # USBIP components
        self.cdc_device = CDCACMDevice()
        self.bridge = CDCBridge(self.usb_periph, self.cdc_device)
        self.usbip_server = USBIPServer(port=usbip_port)
        self.usbip_server.device = self.cdc_device
        self.usbip_server.set_usb_peripheral(self.usb_periph)

        self._loop = None
        self._thread = None
        self._writer = None
        self._access_count = 0
        self._last_accesses = []  # ring buffer for last N accesses
        self._addr_counts = {}    # address -> count for distribution

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
        usbip_tcp = await asyncio.start_server(
            self.usbip_server.handle_client, '127.0.0.1', self.usbip_port)
        async with tcp_server, usbip_tcp:
            await asyncio.gather(
                tcp_server.serve_forever(),
                usbip_tcp.serve_forever())

    async def _handle_qemu_client(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter):
        """Handle binary protocol from QEMU slab-cortex-m."""
        self._writer = writer
        # Wire IRQ delivery now that we have a QEMU connection
        self.usb_periph.irq_callback = self._send_irq
        # Also wire IRQ for all peripherals in the set
        for p in self.stm32.peripherals:
            if hasattr(p, 'irq_callback'):
                p.irq_callback = self._send_irq

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
        # Check USB first (supports secure parameter)
        if self.usb_periph.contains(addr):
            result = self.usb_periph.read(addr, size, secure)
            return result[0] if isinstance(result, tuple) else result
        # Other STM32 peripherals (no secure parameter)
        periph = self.stm32.find_peripheral(addr)
        if periph and periph is not self.usb_periph:
            result = periph.read(addr, size)
            return result[0] if isinstance(result, tuple) else result
        return 0

    def _dispatch_write(self, addr: int, size: int, value: int,
                        secure: bool = False):
        """Route write to the correct peripheral."""
        if self.usb_periph.contains(addr):
            self.usb_periph.write(addr, size, value, secure)
            return
        periph = self.stm32.find_peripheral(addr)
        if periph and periph is not self.usb_periph:
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
    """Run the full E2E USB CDC hello + echo test."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    print()
    print("=" * 70)
    print("  STM32U5A5 USB CDC-ACM Hello + Echo over USBIP - E2E Test")
    print("=" * 70)

    # Paths
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir,
                                                '..', '..', '..', '..', '..', '..', '..'))
    qemu = os.path.join(project_root, 'build', 'qemu-system-arm')
    firmware = os.path.join(test_dir, 'build', 'U5A5_CDC_Blinky.bin')

    if not os.path.exists(firmware):
        print(f"  ERROR: Firmware not found: {firmware}")
        print(f"         Run: make -C {test_dir}")
        return False

    if not os.path.exists(qemu):
        print(f"  ERROR: QEMU not found: {qemu}")
        return False

    periph_port = find_free_port()
    usbip_port = find_free_port()
    results = []

    # -------------------------------------------------------------------------
    # Step 1: Start combined server (peripheral + USBIP)
    # -------------------------------------------------------------------------
    print()
    print(f"  [1/6] Starting combined server "
          f"(TCP:{periph_port}, USBIP:{usbip_port})...")
    e2e = U5A5CDCEchoServer(periph_port=periph_port, usbip_port=usbip_port)
    e2e.start_threaded()
    print(f"         USB OTG_HS:     0x{e2e.usb_periph.base:08X}")
    print(f"         STM32 periphs:  {len(e2e.stm32.peripherals)} registered")

    # -------------------------------------------------------------------------
    # Step 2: Start QEMU
    # -------------------------------------------------------------------------
    print()
    print("  [2/6] Starting QEMU with U5A5 CDC Blinky firmware...")
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
        [qemu, '-M', machine_props, '-nographic', '-kernel', firmware],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f"         Machine:  slab-cortex-m (Cortex-M33)")
    print(f"         Firmware: U5A5_CDC_Blinky.bin")
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
    # Step 3: USBIP DevList
    # -------------------------------------------------------------------------
    print()
    print("  [3/6] USBIP: OP_REQ_DEVLIST...")
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', usbip_port))

        devlist = usbip_devlist(sock)
        devlist_ok = (devlist['status'] == 0 and len(devlist['devices']) == 1 and
                      devlist['devices'][0]['vid'] == 0x0483 and
                      devlist['devices'][0]['pid'] == 0x5740)
        if devlist_ok:
            dev = devlist['devices'][0]
            print(f"         Found: {dev['busid']} "
                  f"VID:PID {dev['vid']:04X}:{dev['pid']:04X}")
        else:
            print(f"         FAILED: {devlist}")
        results.append(("USBIP DevList: CDC-ACM visible", devlist_ok))
        sock.close()
        sock = None
    except Exception as ex:
        print(f"         ERROR: {ex}")
        results.append(("USBIP DevList: CDC-ACM visible", False))
        if sock:
            sock.close()
            sock = None

    # Diagnostic: check USB register state before import
    usb = e2e.usb_periph
    gccfg = usb.regs.get(usb.GCCFG, 0)
    gahbcfg = usb.regs.get(usb.GAHBCFG, 0)
    gintmsk = usb.regs.get(usb.GINTMSK, 0)
    print(f"         USB is_ready(): {usb.is_ready()}")
    print(f"         GCCFG=0x{gccfg:08X} GAHBCFG=0x{gahbcfg:08X} "
          f"GINTMSK=0x{gintmsk:08X}")
    if e2e._last_accesses:
        print(f"         Last {len(e2e._last_accesses)} MMIO accesses:")
        for entry in e2e._last_accesses:
            typ, addr, val, n = entry[:4]
            pc = entry[4] if len(entry) > 4 else 0
            print(f"           [{n:4d}] {typ} 0x{addr:08X} = 0x{val:08X}  PC=0x{pc:08X}")

    # -------------------------------------------------------------------------
    # Step 4: USBIP Import + USB Enumeration
    # -------------------------------------------------------------------------
    print()
    print("  [4/6] USBIP: Import + Enumeration (SET_ADDRESS, SET_CONFIGURATION)...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(('127.0.0.1', usbip_port))

        import_result = usbip_import(sock, "1-1")
        import_ok = (import_result['status'] == 0)
        if import_ok:
            print(f"         Attached: VID:PID "
                  f"{import_result['vid']:04X}:{import_result['pid']:04X}")
        else:
            print(f"         FAILED: status={import_result['status']}")
            results.append(("USBIP Import + Enumeration", False))
            sock.close()
            sock = None
            # Skip remaining tests
            _cleanup(qemu_proc, e2e, sock, results)
            return False

        # Complete USB enumeration via EP0 control transfers
        seqnum = 1

        # SET_ADDRESS(1): bmRequestType=0x00, bRequest=0x05, wValue=1
        setup_addr = struct.pack("<BBHHH", 0x00, 0x05, 1, 0, 0)
        usbip_ep0_out(sock, seqnum, setup_addr)
        seqnum += 1
        time.sleep(0.3)
        print("         SET_ADDRESS(1): OK")

        # SET_CONFIGURATION(1): bmRequestType=0x00, bRequest=0x09, wValue=1
        setup_cfg = struct.pack("<BBHHH", 0x00, 0x09, 1, 0, 0)
        usbip_ep0_out(sock, seqnum, setup_cfg)
        seqnum += 1
        time.sleep(0.5)
        print("         SET_CONFIGURATION(1): OK")

        # SET_CONTROL_LINE_STATE (DTR=1, RTS=1) -- some firmware waits for this
        setup_cls = struct.pack("<BBHHH", 0x21, 0x22, 0x0003, 0, 0)
        usbip_ep0_out(sock, seqnum, setup_cls)
        seqnum += 1
        time.sleep(0.3)
        print("         SET_CONTROL_LINE_STATE(DTR|RTS): OK")

        results.append(("USBIP Import + Enumeration", True))
        print(f"         MMIO accesses: {e2e._access_count}")

    except Exception as ex:
        print(f"         ERROR: {ex}")
        results.append(("USBIP Import + Enumeration", False))
        if sock:
            sock.close()
            sock = None

    # -------------------------------------------------------------------------
    # Step 5: Read Hello message (firmware sends "helloworld\n\r" after CDC init)
    # -------------------------------------------------------------------------
    print()
    print("  [5/6] Bulk IN: reading hello message...")
    hello_ok = False
    if sock:
        try:
            # Give firmware time to send the hello message
            time.sleep(1.0)

            response = usbip_bulk_in(sock, seqnum, 64)
            seqnum += 1

            if b"helloworld" in response:
                hello_ok = True
                print(f"         Received: {response!r}")
                print(f"         Result:   PASS")
            else:
                print(f"         Received: {response!r}")
                print(f"         Expected: b'helloworld\\n\\r'")
                print(f"         Result:   FAIL")
                # Try one more time after a delay
                time.sleep(1.0)
                response2 = usbip_bulk_in(sock, seqnum, 64)
                seqnum += 1
                if b"helloworld" in response2:
                    hello_ok = True
                    print(f"         Retry:    {response2!r} -- PASS")

            results.append(("Hello: firmware startup message", hello_ok))
        except Exception as ex:
            print(f"         ERROR: {ex}")
            results.append(("Hello: firmware startup message", False))
    else:
        results.append(("Hello: firmware startup message", False))

    # -------------------------------------------------------------------------
    # Step 6: Echo test (send data, read it back)
    # -------------------------------------------------------------------------
    print()
    print("  [6/6] Bulk OUT/IN: echo test...")
    echo_ok = False
    if sock:
        try:
            test_msg = b"Hello Echo\n"
            usbip_bulk_out(sock, seqnum, test_msg)
            seqnum += 1
            print(f"         Sent:     {test_msg!r}")

            # Wait for firmware to process and echo back
            time.sleep(1.0)

            response = usbip_bulk_in(sock, seqnum, 64)
            seqnum += 1

            # Check if echo matches (firmware echoes exact bytes)
            if test_msg in response:
                echo_ok = True
                print(f"         Received: {response!r}")
                print(f"         Result:   PASS")
            else:
                print(f"         Received: {response!r}")
                print(f"         Expected: {test_msg!r}")
                print(f"         Result:   FAIL")
                # Retry
                time.sleep(1.0)
                response2 = usbip_bulk_in(sock, seqnum, 64)
                seqnum += 1
                if test_msg in response2:
                    echo_ok = True
                    print(f"         Retry:    {response2!r} -- PASS")

            results.append(("Echo: round-trip data", echo_ok))
        except Exception as ex:
            print(f"         ERROR: {ex}")
            results.append(("Echo: round-trip data", False))
    else:
        results.append(("Echo: round-trip data", False))

    # -------------------------------------------------------------------------
    # Cleanup + Summary
    # -------------------------------------------------------------------------
    _cleanup(qemu_proc, e2e, sock, results)
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
        print("  Full stack: USBIP <-> CDCBridge <-> OTG_HS <-> QEMU <-> U5A5 Firmware")
    else:
        print("  Some tests FAILED")
    print()


if __name__ == "__main__":
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    success = run_e2e_test(verbose=verbose)
    sys.exit(0 if success else 1)
