#!/usr/bin/env python3
"""
E2E Test: USB CDC-ACM over USBIP ↔ QEMU ↔ STM32F439 Crypto Firmware

Architecture:
    USBIP Client (Python, port 3240)
      ↕ USBIP protocol (DevList, Import, Bulk IN/OUT)
    USBIPServer + CDCACMDevice  [separate thread]
      ↕ CDCBridge (tx_buffer/rx_buffer forwarding)
    USBCDCPeripheral (0x50000000, OTG_FS registers + FIFOs)
      ↕ TCP proxy protocol (port 5000)
    QEMU slab-cortex-m  [QEMU always connects to port 5000]
      ↕ Firmware: test_usb_cdc_crypto.bin
    STM32F439PeripheralSet (CRYP 0x50060000, HASH 0x50060400, RCC)

Run:
    python3 tests/firmware/examples/stm32_crypto_cdc/test_e2e_usb_cdc_crypto.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet
from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
from slab_cortex_m.cdc_bridge import CDCBridge
from slab_cortex_m.usbip_server import USBIPServer, CDCACMDevice, USBDevice

# Default ports (QEMU slab-cortex-m connects to TCP port 5000)
PERIPH_PORT = 5000


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
    req = struct.pack(">HxxxxH", 0x0111, 0x8005)
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
        _recv_exact(sock, num_ifaces * 4)  # interface info
        devices.append({'busid': busid, 'vid': vid, 'pid': pid})

    return {'status': status, 'devices': devices}


def usbip_import(sock: socket.socket, busid: str = "1-1") -> dict:
    """Send OP_REQ_IMPORT and parse response."""
    busid_bytes = busid.encode().ljust(32, b'\x00')
    req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid_bytes
    sock.sendall(req)

    resp = _recv_exact(sock, 8)
    version, command, status = struct.unpack(">HHI", resp)
    assert command == 0x0003, f"Expected OP_REP_IMPORT, got 0x{command:04X}"

    if status == 0:
        dev_data = _recv_exact(sock, 312)
        vid, pid = struct.unpack(">HH", dev_data[300:304])
        return {'status': status, 'vid': vid, 'pid': pid}

    return {'status': status}


def usbip_bulk_out(sock: socket.socket, seqnum: int, data: bytes) -> int:
    """Send bulk OUT transfer to EP1. Returns actual_length."""
    submit = struct.pack(">IIIII",
        0x00000001,   # CMD_SUBMIT
        seqnum,
        0x00010001,   # devid
        0,            # direction = OUT
        1             # ep = 1
    )
    submit += struct.pack(">IIIII", 0, len(data), 0, 0, 0)
    submit += b'\x00' * 8  # setup (unused for bulk)
    submit += data

    sock.sendall(submit)
    resp = _recv_exact(sock, 48)
    status = struct.unpack(">i", resp[20:24])[0]
    actual_length = struct.unpack(">I", resp[24:28])[0]
    return actual_length


def usbip_bulk_in(sock: socket.socket, seqnum: int, max_len: int = 64) -> bytes:
    """Send bulk IN transfer from EP1. Returns received data."""
    submit = struct.pack(">IIIII",
        0x00000001,   # CMD_SUBMIT
        seqnum,
        0x00010001,   # devid
        1,            # direction = IN
        1             # ep = 1
    )
    submit += struct.pack(">IIIII", 0, max_len, 0, 0, 0)
    submit += b'\x00' * 8  # setup (unused)

    sock.sendall(submit)
    resp = _recv_exact(sock, 48 + max_len)
    actual_length = struct.unpack(">I", resp[24:28])[0]
    return resp[48:48 + actual_length]


# =============================================================================
# Peripheral Server (TCP proxy for QEMU, runs in dedicated thread)
# =============================================================================

class USBCryptoE2EServer:
    """Async TCP server handling QEMU peripheral proxy protocol.

    Dispatches register accesses to:
    - USBCDCPeripheral (0x50000000 - 0x5003FFFF): USB OTG_FS
    - STM32F439PeripheralSet: RCC, CRYP, HASH, etc.
    """

    def __init__(self, periph_port: int = PERIPH_PORT):
        self.port = periph_port
        self.stm32 = STM32F439PeripheralSet()
        self.usb_periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        self.server = None
        self._loop = None
        self._thread = None
        self._running = False
        self._access_count = 0
        self._cryp_reads = 0
        self._cryp_writes = 0
        self._hash_reads = 0
        self._hash_writes = 0
        self._trace_enabled = False
        self._trace_log = []  # (is_write, addr, value) tuples

    def start_threaded(self):
        """Start the server in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        time.sleep(0.5)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        self.server = await asyncio.start_server(
            self._handle_client, '127.0.0.1', self.port
        )
        self._running = True
        async with self.server:
            await self.server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        """Handle binary protocol from QEMU proxy."""
        try:
            while self._running:
                data = await reader.read(1)
                if not data:
                    break
                cmd = data[0]

                if cmd in (ord('R'), ord('S')):
                    payload = await reader.readexactly(9)
                    addr, size = struct.unpack('<II', payload[:8])
                    value = self._dispatch_read(addr, size)
                    writer.write(struct.pack('<IB', value, 0))
                    await writer.drain()
                    self._access_count += 1

                elif cmd in (ord('W'), ord('T')):
                    payload = await reader.readexactly(13)
                    addr, size, value = struct.unpack('<III', payload[:12])
                    self._dispatch_write(addr, size, value)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
                    self._access_count += 1

                elif cmd == ord('C'):
                    payload = await reader.readexactly(10)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            writer.close()

    def _dispatch_read(self, addr: int, size: int) -> int:
        """Route read to the correct peripheral."""
        if self.usb_periph.contains(addr):
            val = self.usb_periph.read(addr, size)
            if self._trace_enabled and len(self._trace_log) < 200:
                self._trace_log.append(('R', addr, val))
            return val

        for periph in self.stm32.peripherals:
            if periph.base <= addr < periph.base + periph.size:
                if periph.base == 0x50060000:
                    self._cryp_reads += 1
                elif periph.base == 0x50060400:
                    self._hash_reads += 1
                val, _ = periph.read(addr, size)
                if self._trace_enabled and len(self._trace_log) < 200:
                    self._trace_log.append(('R', addr, val))
                return val
        if self._trace_enabled and len(self._trace_log) < 200:
            self._trace_log.append(('R', addr, 0))
        return 0

    def _dispatch_write(self, addr: int, size: int, value: int):
        """Route write to the correct peripheral."""
        if self._trace_enabled and len(self._trace_log) < 200:
            self._trace_log.append(('W', addr, value))

        if self.usb_periph.contains(addr):
            self.usb_periph.write(addr, size, value)
            return

        for periph in self.stm32.peripherals:
            if periph.base <= addr < periph.base + periph.size:
                if periph.base == 0x50060000:
                    self._cryp_writes += 1
                elif periph.base == 0x50060400:
                    self._hash_writes += 1
                periph.write(addr, size, value)
                return

    def stop(self):
        self._running = False
        if self._loop and self.server:
            self._loop.call_soon_threadsafe(self.server.close)


# =============================================================================
# E2E Test Runner
# =============================================================================

def run_e2e_test(verbose: bool = False):
    """Run the full E2E USB CDC crypto test.

    Uses threads for async servers and blocking sockets for the USBIP client
    to avoid event-loop contention.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    print()
    print("=" * 70)
    print("  STM32F439 USB CDC-ACM Crypto over USBIP - E2E Test")
    print("=" * 70)
    print()
    print("  Architecture:")
    print("    USBIP Client (Python, blocking sockets)")
    print("      ↕ USBIP protocol")
    print("    USBIPServer + CDCACMDevice  [thread]")
    print("      ↕ CDCBridge")
    print("    USBCDCPeripheral (OTG_FS @ 0x50000000)")
    print("      ↕ TCP proxy (port 5000)  [thread]")
    print("    QEMU slab-cortex-m + test_usb_cdc_crypto.bin")
    print("      ↕ CRYP/HASH peripherals")
    print()

    # Paths
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', '..', '..', '..'))
    qemu = os.path.join(project_root, 'qemu', 'build', 'qemu-system-arm')
    firmware = os.path.join(project_root, 'tests', 'firmware', 'build',
                           'test_usb_cdc_crypto.bin')

    if not os.path.exists(firmware):
        print(f"  ERROR: Firmware not found: {firmware}")
        print(f"         Run: make -C tests/firmware build/test_usb_cdc_crypto.bin")
        return False

    if not os.path.exists(qemu):
        print(f"  ERROR: QEMU not found: {qemu}")
        return False

    # Find a free port for USBIP
    def find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    usbip_port = find_free_port()
    results = []

    # -------------------------------------------------------------------------
    # Step 1: Start peripheral server (port 5000, in thread)
    # -------------------------------------------------------------------------
    print(f"  [1/8] Starting peripheral server (port {PERIPH_PORT})...")
    e2e = USBCryptoE2EServer(periph_port=PERIPH_PORT)
    e2e.start_threaded()
    print(f"         USB OTG_FS:     0x{e2e.usb_periph.base:08X}")
    print(f"         STM32 periphs:  {len(e2e.stm32.peripherals)} registered")

    # -------------------------------------------------------------------------
    # Step 2: Start USBIP server with CDC bridge (in thread)
    # -------------------------------------------------------------------------
    print()
    print(f"  [2/8] Starting USBIP server (port {usbip_port})...")
    usbip_dev = CDCACMDevice()
    bridge = CDCBridge(e2e.usb_periph, usbip_dev)

    usbip_server = USBIPServer(port=usbip_port)
    usbip_server.device = usbip_dev

    usbip_loop = asyncio.new_event_loop()
    def run_usbip():
        asyncio.set_event_loop(usbip_loop)
        usbip_loop.run_until_complete(usbip_server.start())
    usbip_thread = threading.Thread(target=run_usbip, daemon=True)
    usbip_thread.start()
    time.sleep(0.5)
    print(f"         Device: CDC-ACM (VID:PID 0483:5740)")
    print(f"         Bridge: USBCDCPeripheral <-> CDCACMDevice")

    # -------------------------------------------------------------------------
    # Step 3: Start QEMU
    # -------------------------------------------------------------------------
    print()
    print("  [3/8] Starting QEMU with USB CDC crypto firmware...")
    qemu_proc = subprocess.Popen(
        [qemu, '-M', 'slab-cortex-m', '-cpu', 'cortex-m4',
         '-nographic', '-kernel', firmware,
         '-d', 'guest_errors,unimp'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f"         Machine:  slab-cortex-m (Cortex-M4)")
    print(f"         Firmware: test_usb_cdc_crypto.bin")
    print(f"         PID:      {qemu_proc.pid}")

    # Wait for firmware init
    print("         Waiting for firmware init...")
    time.sleep(2.0)
    print(f"         MMIO accesses: {e2e._access_count}")

    # -------------------------------------------------------------------------
    # Step 4: USBIP DevList
    # -------------------------------------------------------------------------
    print()
    print("  [4/8] USBIP: OP_REQ_DEVLIST...")
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
            print(f"         Found: {dev['busid']} VID:PID {dev['vid']:04X}:{dev['pid']:04X}")
        else:
            print(f"         FAILED: {devlist}")
        results.append(("USBIP DevList: CDC-ACM visible", devlist_ok))
        sock.close()
    except Exception as ex:
        print(f"         ERROR: {ex}")
        results.append(("USBIP DevList: CDC-ACM visible", False))

    # -------------------------------------------------------------------------
    # Step 5: USBIP Import
    # -------------------------------------------------------------------------
    print()
    print("  [5/8] USBIP: OP_REQ_IMPORT (busid=1-1)...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', usbip_port))

        import_result = usbip_import(sock, "1-1")
        import_ok = (import_result['status'] == 0)
        if import_ok:
            print(f"         Attached: VID:PID {import_result['vid']:04X}:{import_result['pid']:04X}")
        else:
            print(f"         FAILED: status={import_result['status']}")
        results.append(("USBIP Import: device attached", import_ok))
    except Exception as ex:
        print(f"         ERROR: {ex}")
        results.append(("USBIP Import: device attached", False))
        sock = None

    # -------------------------------------------------------------------------
    # Step 6: PING via USB bulk
    # -------------------------------------------------------------------------
    # Minimal diagnostic: log first FIFO reads/writes after injection
    _diag = {'timeline': [], 'fifo_wr': [], 'armed': False}
    _orig_read = e2e.usb_periph.read
    _orig_write = e2e.usb_periph.write
    def _diag_read(addr, size, secure=False):
        val = _orig_read(addr, size, secure)
        if _diag['armed'] and len(_diag['timeline']) < 40:
            offset = addr - e2e.usb_periph.base
            if 0x1000 <= offset < 0x20000:
                remaining = len(e2e.usb_periph._rx_data_queue)
                _diag['timeline'].append(('FIFO_RD', offset, val, remaining))
            elif offset in (0x01C, 0x020):
                sts_q = len(e2e.usb_periph._rx_status_queue)
                label = 'GRXSTSR' if offset == 0x01C else 'GRXSTSP'
                _diag['timeline'].append((label, offset, val, sts_q))
            elif offset == 0x014:
                rxflvl = (val >> 4) & 1
                _diag['timeline'].append(('GINTSTS', offset, val, rxflvl))
        return val
    def _diag_write(addr, size, value, secure=False):
        if _diag['armed'] and len(_diag['fifo_wr']) < 20:
            offset = addr - e2e.usb_periph.base
            if 0x1000 <= offset < 0x20000:
                ep = (offset - 0x1000) // 0x1000
                _diag['fifo_wr'].append((ep, value))
        return _orig_write(addr, size, value, secure)
    e2e.usb_periph.read = _diag_read
    e2e.usb_periph.write = _diag_write

    print()
    print("  [6/8] Bulk OUT: PING -> Bulk IN: PONG...")
    if sock:
        try:
            seqnum = 1
            _diag['armed'] = True
            usbip_bulk_out(sock, seqnum, b"PING\n")
            seqnum += 1

            time.sleep(1.5)

            response = usbip_bulk_in(sock, seqnum, 64)
            seqnum += 1
            _diag['armed'] = False

            ping_ok = b"PONG" in response
            print(f"         Response: {response!r}")
            print(f"         Result:   {'PASS' if ping_ok else 'FAIL'}")
            # Print timeline
            if _diag['timeline']:
                print(f"         Timeline ({len(_diag['timeline'])} events):")
                for i, entry in enumerate(_diag['timeline'][:30]):
                    typ = entry[0]
                    if typ == 'FIFO_RD':
                        _, off, val, remaining = entry
                        b = bytes([(val>>(j*8))&0xFF for j in range(4)])
                        print(f"           [{i:2d}] FIFO_RD  val=0x{val:08X} ({b!r}) data_q={remaining}")
                    elif typ in ('GRXSTSR', 'GRXSTSP'):
                        _, off, val, sts_q = entry
                        pktsts = (val >> 17) & 0xF
                        bcnt = (val >> 4) & 0x7FF
                        print(f"           [{i:2d}] {typ:7s}  off=0x{off:03X} pktsts={pktsts} bcnt={bcnt} sts_q={sts_q}")
                    elif typ == 'GINTSTS':
                        _, off, val, rxflvl = entry
                        print(f"           [{i:2d}] GINTSTS  val=0x{val:08X} RXFLVL={rxflvl}")
            if _diag['fifo_wr']:
                print(f"         FIFO writes ({len(_diag['fifo_wr'])}):")
                for i, (ep, val) in enumerate(_diag['fifo_wr'][:10]):
                    b = bytes([(val>>(j*8))&0xFF for j in range(4)])
                    print(f"           [{i}] EP{ep} val=0x{val:08X} ({b!r})")
            results.append(("PING -> PONG over USB bulk", ping_ok))
        except Exception as ex:
            print(f"         ERROR: {ex}")
            results.append(("PING -> PONG over USB bulk", False))
    else:
        results.append(("PING -> PONG over USB bulk", False))

    # Restore original read/write
    e2e.usb_periph.read = _orig_read
    e2e.usb_periph.write = _orig_write

    # -------------------------------------------------------------------------
    # Step 7: AES-128-ECB via USB bulk
    # -------------------------------------------------------------------------
    print()
    print("  [7/8] Bulk OUT: AES128_ECB_ENC (NIST FIPS-197)...")
    if sock:
        try:
            key = "2b7e151628aed2a6abf7158809cf4f3c"
            pt = "6bc1bee22e409f96e93d7e117393172a"
            expected_ct = "3ad77bb40d7a3660a89ecaf32466ef97"

            cmd = f"AES128_ECB_ENC {key}{pt}\n".encode()
            print(f"         [diag] Sending {len(cmd)} bytes: {cmd[:40]}...")

            # Hook FIFO reads and GRXSTSP pops to track exact data flow
            _aes_diag = {
                'fifo_reads': [],      # (word_value, data_q_before, data_q_after)
                'grxstsp_pops': [],    # (epnum, pktsts, bcnt, data_released)
                'echo_calls': 0,       # count of echo-mode handle_tx_data calls
                'tx_writes': [],       # (ep, value) from CDCBridge._handle_firmware_tx
            }
            _orig_periph_read = e2e.usb_periph.read.__func__ if hasattr(e2e.usb_periph.read, '__func__') else None
            _periph = e2e.usb_periph

            def _hooked_read(addr, size, secure=False):
                offset = addr - _periph.base
                # Intercept GRXSTSP pop
                if offset == 0x020 and _periph._rx_status_queue:
                    epnum, pktsts, bcnt = _periph._rx_status_queue[0]
                    data_preview = bytes(_periph._rx_data_queue[:20])
                    val = USBCDCPeripheral.read(_periph, addr, size, secure)
                    _aes_diag['grxstsp_pops'].append((epnum, pktsts, bcnt, data_preview))
                    return val
                # Intercept FIFO reads
                if 0x1000 <= offset < 0x20000:
                    dq_before = len(_periph._rx_data_queue)
                    val = USBCDCPeripheral.read(_periph, addr, size, secure)
                    dq_after = len(_periph._rx_data_queue)
                    if len(_aes_diag['fifo_reads']) < 30:
                        _aes_diag['fifo_reads'].append((val, dq_before, dq_after))
                    return val
                return USBCDCPeripheral.read(_periph, addr, size, secure)

            # Hook CDCBridge TX to detect any stray echo
            _orig_bridge_tx = bridge._handle_firmware_tx
            def _hooked_bridge_tx(ep, value):
                if len(_aes_diag['tx_writes']) < 20:
                    _aes_diag['tx_writes'].append((ep, value))
                return _orig_bridge_tx(ep, value)
            _periph.handle_tx_data = _hooked_bridge_tx

            # Check pre-injection state
            print(f"         [diag] Pre-inject: status_q={len(_periph._rx_status_queue)}, "
                  f"data_q={len(_periph._rx_data_queue)}")

            e2e.usb_periph.read = _hooked_read
            usbip_bulk_out(sock, seqnum, cmd)
            seqnum += 1

            # Check post-injection state (before firmware processes)
            print(f"         [diag] Post-inject: status_q={len(_periph._rx_status_queue)}, "
                  f"data_q={len(_periph._rx_data_queue)}")

            time.sleep(1.5)
            e2e.usb_periph.read = USBCDCPeripheral.read.__get__(_periph)
            _periph.handle_tx_data = bridge._handle_firmware_tx

            # Dump diagnostics
            print(f"         [diag] GRXSTSP pops: {len(_aes_diag['grxstsp_pops'])}")
            for i, (ep, ps, bc, data) in enumerate(_aes_diag['grxstsp_pops']):
                print(f"           pop[{i}]: ep={ep} pktsts={ps} bcnt={bc} data_start={data!r}")
            print(f"         [diag] FIFO reads: {len(_aes_diag['fifo_reads'])}")
            accumulated = bytearray()
            for i, (val, dq_b, dq_a) in enumerate(_aes_diag['fifo_reads'][:25]):
                b = bytes([(val>>(j*8))&0xFF for j in range(4)])
                accumulated.extend(x for x in b if x != 0)
                print(f"           fifo[{i:2d}]: 0x{val:08X} ({b!r}) dq={dq_b}->{dq_a}")
            print(f"         [diag] Accumulated FIFO bytes ({len(accumulated)}): {bytes(accumulated[:80])!r}")
            print(f"         [diag] TX writes: {len(_aes_diag['tx_writes'])}")
            for i, (ep, val) in enumerate(_aes_diag['tx_writes'][:10]):
                b = bytes([(val>>(j*8))&0xFF for j in range(4)])
                print(f"           tx[{i}]: EP{ep} 0x{val:08X} ({b!r})")
            print(f"         [diag] tx_buffer={len(usbip_dev.tx_buffer)}, "
                  f"CRYP rd={e2e._cryp_reads} wr={e2e._cryp_writes}")

            response = usbip_bulk_in(sock, seqnum, 64)
            seqnum += 1

            aes_ok = expected_ct.encode() in response.lower()
            print(f"         Key:      {key}")
            print(f"         Input:    {pt}")
            print(f"         Response: {response!r}")
            print(f"         Expected: {expected_ct}")
            print(f"         Result:   {'PASS' if aes_ok else 'FAIL'}")
            results.append(("AES-128-ECB encrypt (NIST vector)", aes_ok))
        except Exception as ex:
            print(f"         ERROR: {ex}")
            results.append(("AES-128-ECB encrypt (NIST vector)", False))
    else:
        results.append(("AES-128-ECB encrypt (NIST vector)", False))

    # -------------------------------------------------------------------------
    # Step 8: SHA-256 via USB bulk
    # -------------------------------------------------------------------------
    print()
    print("  [8/8] Bulk OUT: SHA256('abc')...")
    if sock:
        try:
            data_hex = "616263"
            expected_sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

            cmd = f"SHA256 {data_hex}\n".encode()
            usbip_bulk_out(sock, seqnum, cmd)
            seqnum += 1

            time.sleep(1.5)

            response = usbip_bulk_in(sock, seqnum, 128)
            seqnum += 1

            sha_ok = expected_sha.encode() in response.lower()
            print(f"         Input:    'abc' (hex: {data_hex})")
            print(f"         Response: {response!r}")
            print(f"         Expected: {expected_sha}")
            print(f"         Result:   {'PASS' if sha_ok else 'FAIL'}")
            results.append(("SHA-256 hash (NIST)", sha_ok))
        except Exception as ex:
            print(f"         ERROR: {ex}")
            results.append(("SHA-256 hash (NIST)", False))
    else:
        results.append(("SHA-256 hash (NIST)", False))

    # -------------------------------------------------------------------------
    # Cleanup
    # -------------------------------------------------------------------------
    print()
    print("  Cleanup...")
    if sock:
        sock.close()
    qemu_proc.terminate()
    try:
        qemu_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        qemu_proc.kill()
        qemu_proc.wait(timeout=2)

    # Capture QEMU output
    stdout = qemu_proc.stdout.read().decode(errors='replace')
    stderr = qemu_proc.stderr.read().decode(errors='replace')
    if verbose:
        if stderr:
            print(f"\n  QEMU stderr:\n{stderr[:1000]}")

    e2e.stop()
    usbip_loop.call_soon_threadsafe(usbip_loop.stop)

    print(f"         Total MMIO accesses: {e2e._access_count}")

    # Summary
    print()
    print("=" * 70)
    print("  Results")
    print("=" * 70)
    all_pass = True
    for name, ok in results:
        mark = "PASS" if ok else "FAIL"
        print(f"    [{mark}] {name}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("  ALL TESTS PASSED")
        print("  Full stack verified: USBIP <-> CDCBridge <-> OTG_FS <-> QEMU <-> Crypto")
    else:
        print("  Some tests FAILED")
    print()
    return all_pass


if __name__ == "__main__":
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    success = run_e2e_test(verbose=verbose)
    sys.exit(0 if success else 1)
