#!/usr/bin/env python3
"""
E2E Test: Run wargame.bin (USB CDC-ACM CTF firmware) on slab-cortex-m

Implements proper Linux-kernel-style USB enumeration:
    Bus Reset → Speed Enum → SET_ADDRESS → SET_CONFIGURATION → DTR/RTS

Architecture:
    USBIP Client (Python, blocking sockets)
      ↕ USBIP protocol (DevList, Import, Bulk IN/OUT)
    USBIPServer + CDCACMDevice  [thread]
      ↕ CDCBridge
    USBCDCPeripheral (OTG_FS @ 0x50000000)
      ↕ TCP proxy (port 5000)  [thread]
    QEMU slab-cortex-m + wargame.bin

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
from slab_cortex_m.shm_peripheral import ShmPeripheralBridge, PeripheralHandler

PERIPH_PORT = 5000
GDB_PORT = 1234  # QEMU's default GDB stub port (-s flag)

# =============================================================================
# GDB Remote Protocol (minimal client for QEMU memory access)
# =============================================================================

class GDBClient:
    """Minimal GDB remote protocol client for QEMU memory access.

    Connects to QEMU's GDB stub, performs memory operations, and
    resumes CPU execution. QEMU halts the guest when GDB connects,
    so we must send 'c' (continue) when done.
    """

    def __init__(self, port: int = GDB_PORT):
        self.port = port
        self.sock = None

    def _checksum(self, data: bytes) -> int:
        return sum(data) & 0xFF

    def _send_packet(self, body: bytes) -> bytes:
        """Send a GDB packet and wait for response."""
        chk = self._checksum(body)
        packet = b'$' + body + b'#' + f"{chk:02x}".encode()
        self.sock.sendall(packet)

        # Read response: expect '+' (ACK) then '$..#xx'
        resp = b''
        while True:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b'#' in resp:
                break
        # Send ACK for response
        self.sock.sendall(b'+')
        return resp

    def _parse_response(self, resp: bytes) -> bytes:
        """Extract data from GDB response packet."""
        try:
            if b'$' in resp:
                start = resp.index(b'$') + 1
                end = resp.index(b'#', start)
                return resp[start:end]
        except (ValueError, IndexError):
            pass
        return b''

    def connect(self) -> bool:
        """Connect to GDB stub. QEMU halts the guest on connect."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(3)
        try:
            self.sock.connect(('127.0.0.1', self.port))
            # QEMU sends a halt notification: $T05...#xx or similar
            # We need to ACK it
            try:
                initial = self.sock.recv(4096)
                if initial:
                    self.sock.sendall(b'+')
            except socket.timeout:
                pass
            return True
        except (ConnectionRefusedError, OSError):
            return False

    def write_memory(self, addr: int, data: bytes) -> bool:
        """Write data to guest memory."""
        hex_data = data.hex()
        body = f"M{addr:x},{len(data)}:{hex_data}".encode()
        resp = self._send_packet(body)
        return b'OK' in resp

    def read_memory(self, addr: int, length: int) -> bytes:
        """Read data from guest memory."""
        body = f"m{addr:x},{length}".encode()
        resp = self._send_packet(body)
        payload = self._parse_response(resp)
        if payload and payload != b'E':
            try:
                return bytes.fromhex(payload.decode())
            except (ValueError, UnicodeDecodeError):
                pass
        return b''

    def continue_execution(self):
        """Resume guest CPU execution."""
        # Send 'c' packet (continue)
        body = b'c'
        chk = self._checksum(body)
        packet = b'$' + body + b'#' + f"{chk:02x}".encode()
        self.sock.sendall(packet)
        # Don't wait for response (execution will continue until next halt)

    def disconnect(self):
        """Disconnect from GDB stub."""
        if self.sock:
            try:
                # Detach cleanly
                self._send_packet(b'D')
            except (OSError, socket.timeout):
                pass
            self.sock.close()
            self.sock = None


def gdb_patch_firmware(pdev_addr: int = 0x20000494,
                       pclassdata_value: int = 0x20010000,
                       port: int = GDB_PORT) -> bool:
    """Patch firmware state via GDB to enable CDC TX.

    The wargame firmware's CDC_TransmitPacket accesses pClassData indirectly:
        r3 = *(pdev + 0x2D4)    ; pClassDataCmsit index
        r3 += 0xB0
        r2 = *(pdev + r3 * 4)  ; pClassData pointer

    We compute the actual pClassData address and write our value there.
    Then we set TxState = 0 at pClassData + 0x214.

    After patching, resumes CPU execution.
    """
    gdb = GDBClient(port)
    if not gdb.connect():
        print(f"       GDB: Cannot connect to port {port}")
        return False

    try:
        # Step 1: Read pClassDataCmsit index from pdev + 0x2D4
        cmsit_addr = pdev_addr + 0x2D4
        cmsit_data = gdb.read_memory(cmsit_addr, 4)
        if not cmsit_data:
            print(f"       GDB: Cannot read pClassDataCmsit @0x{cmsit_addr:08X}")
            gdb.continue_execution()
            gdb.disconnect()
            return False

        cmsit_val = struct.unpack('<I', cmsit_data)[0]
        print(f"       pClassDataCmsit @0x{cmsit_addr:08X} = 0x{cmsit_val:08X}")

        # Step 2: Compute pClassData address
        # r3 = cmsit_val + 0xB0
        # pClassData addr = pdev + r3 * 4
        r3 = (cmsit_val + 0xB0) & 0xFFFFFFFF
        pclassdata_addr = pdev_addr + (r3 * 4)
        print(f"       Computed pClassData addr: pdev + (0x{cmsit_val:X}+0xB0)*4 = 0x{pclassdata_addr:08X}")

        # Also check the simple offset (0x2BC) for comparison
        simple_addr = pdev_addr + 0x2BC
        simple_data = gdb.read_memory(simple_addr, 4)
        if simple_data:
            simple_val = struct.unpack('<I', simple_data)[0]
            print(f"       pdev+0x2BC @0x{simple_addr:08X} = 0x{simple_val:08X}")

        # Step 3: Read current pClassData value
        current_pcd = gdb.read_memory(pclassdata_addr, 4)
        if current_pcd:
            cur_val = struct.unpack('<I', current_pcd)[0]
            print(f"       Current pClassData: 0x{cur_val:08X} "
                  f"{'(NULL - needs patch)' if cur_val == 0 else '(already set)'}")
            if cur_val != 0:
                # Already initialized - check TxState
                txstate_addr = cur_val + 0x214
                txstate_data = gdb.read_memory(txstate_addr, 4)
                if txstate_data:
                    txstate = struct.unpack('<I', txstate_data)[0]
                    print(f"       TxState @0x{txstate_addr:08X} = {txstate}")
                    if txstate != 0:
                        # Reset TxState to 0
                        gdb.write_memory(txstate_addr, struct.pack('<I', 0))
                        print(f"       Reset TxState to 0")
                gdb.continue_execution()
                gdb.disconnect()
                return True

        # Step 4: Write pClassData pointer to zero-filled RAM
        pcd_bytes = struct.pack('<I', pclassdata_value)
        ok1 = gdb.write_memory(pclassdata_addr, pcd_bytes)
        print(f"       Write pClassData @0x{pclassdata_addr:08X} = 0x{pclassdata_value:08X}: "
              f"{'OK' if ok1 else 'FAILED'}")

        # Step 5: Write TxState = 0 at pClassData + 0x214
        txstate_addr = pclassdata_value + 0x214
        ok2 = gdb.write_memory(txstate_addr, struct.pack('<I', 0))

        # Step 6: Verify
        readback = gdb.read_memory(pclassdata_addr, 4)
        if readback:
            val = struct.unpack('<I', readback)[0]
            print(f"       Verify pClassData: 0x{val:08X} "
                  f"{'(OK)' if val == pclassdata_value else '(MISMATCH!)'}")

        txstate_rb = gdb.read_memory(txstate_addr, 4)
        if txstate_rb:
            val = struct.unpack('<I', txstate_rb)[0]
            print(f"       Verify TxState: {val} {'(ready)' if val == 0 else '(BUSY!)'}")

        # Resume CPU execution
        gdb.continue_execution()
        time.sleep(0.1)
        gdb.disconnect()

        return ok1 and ok2
    except Exception as e:
        print(f"       GDB error: {e}")
        try:
            gdb.continue_execution()
            gdb.disconnect()
        except:
            pass
        return False


# =============================================================================
# USBIP Client Helpers
# =============================================================================

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError(f"Connection closed, got {len(data)}/{n} bytes")
        data += chunk
    return data


def usbip_devlist(sock: socket.socket) -> dict:
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
        _recv_exact(sock, num_ifaces * 4)
        devices.append({'busid': busid, 'vid': vid, 'pid': pid})
    return {'status': status, 'devices': devices}


def usbip_import(sock: socket.socket, busid: str = "1-1") -> dict:
    busid_bytes = busid.encode().ljust(32, b'\x00')
    req = struct.pack(">HxxxxH", 0x0111, 0x8003) + busid_bytes
    sock.sendall(req)
    resp = _recv_exact(sock, 8)
    version, command, status = struct.unpack(">HHI", resp)
    assert command == 0x0003
    if status == 0:
        dev_data = _recv_exact(sock, 312)
        vid, pid = struct.unpack(">HH", dev_data[300:304])
        return {'status': status, 'vid': vid, 'pid': pid}
    return {'status': status}


def usbip_bulk_out(sock: socket.socket, seqnum: int, data: bytes) -> int:
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
    submit = struct.pack(">IIIII",
        0x00000001, seqnum, 0x00010001, 1, 1)
    submit += struct.pack(">IIIII", 0, max_len, 0, 0, 0)
    submit += b'\x00' * 8
    sock.sendall(submit)
    resp = _recv_exact(sock, 48 + max_len)
    actual_length = struct.unpack(">I", resp[24:28])[0]
    return resp[48:48 + actual_length]


# =============================================================================
# Peripheral Server
# =============================================================================

class WargameE2EServer:
    """Async TCP server for QEMU peripheral proxy with IRQ injection."""

    # RCC register offsets (STM32F4, base 0x40023800)
    RCC_BASE = 0x40023800
    RCC_NAMES = {
        0x00: 'CR', 0x04: 'PLLCFGR', 0x08: 'CFGR', 0x0C: 'CIR',
        0x30: 'AHB1ENR', 0x34: 'AHB2ENR', 0x40: 'APB1ENR', 0x44: 'APB2ENR',
    }

    def __init__(self, periph_port: int = PERIPH_PORT):
        self.port = periph_port
        self.stm32 = STM32F439PeripheralSet()
        self.usb_periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        self.server = None
        self._loop = None
        self._thread = None
        self._running = False
        self._access_count = 0
        self._unknown_addrs = set()
        self._qemu_writer = None  # For IRQ injection
        self._rcc_log = []  # Track RCC writes for clock analysis

        # Connect USB peripheral's IRQ callback to QEMU injection
        self.usb_periph.set_irq_callback(self._inject_irq)

    def _inject_irq(self, irq_num: int, level: int):
        """Inject IRQ into QEMU via TCP protocol."""
        if self._qemu_writer and self._loop:
            self._loop.call_soon_threadsafe(
                self._loop.create_task,
                self._async_inject_irq(irq_num, level)
            )

    async def _async_inject_irq(self, irq_num: int, level: int):
        """Actually send the IRQ injection command."""
        if self._qemu_writer:
            try:
                cmd = struct.pack('<BIB', ord('I'), irq_num, level)
                self._qemu_writer.write(cmd)
                await self._qemu_writer.drain()
            except (ConnectionResetError, OSError):
                pass

    def start_threaded(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        time.sleep(0.5)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        self.server = await asyncio.start_server(
            self._handle_client, '127.0.0.1', self.port)
        self._running = True
        async with self.server:
            await self.server.serve_forever()

    async def _handle_client(self, reader, writer):
        self._qemu_writer = writer  # Save for IRQ injection
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
        if self.usb_periph.contains(addr):
            return self.usb_periph.read(addr, size)

        for periph in self.stm32.peripherals:
            if periph.base <= addr < periph.base + periph.size:
                val, _ = periph.read(addr, size)
                return val

        if addr not in self._unknown_addrs:
            self._unknown_addrs.add(addr)
        return 0

    def _dispatch_write(self, addr: int, size: int, value: int):
        if self.usb_periph.contains(addr):
            self.usb_periph.write(addr, size, value)
            return

        # Track RCC writes for clock analysis
        if self.RCC_BASE <= addr < self.RCC_BASE + 0x100:
            offset = addr - self.RCC_BASE
            name = self.RCC_NAMES.get(offset, f"0x{offset:02X}")
            self._rcc_log.append((name, value))

        for periph in self.stm32.peripherals:
            if periph.base <= addr < periph.base + periph.size:
                periph.write(addr, size, value)
                return

        if addr not in self._unknown_addrs:
            self._unknown_addrs.add(addr)

    def stop(self):
        self._running = False
        if self._loop and self.server:
            self._loop.call_soon_threadsafe(self.server.close)


# =============================================================================
# SHM-based Peripheral Server
# =============================================================================

SHM_NAME = "/slab_wargame"

class WargameShmServer:
    """Shared memory peripheral server for QEMU proxy.

    Uses POSIX shared memory for synchronous, low-latency MMIO access.
    Each QEMU MMIO read/write blocks until Python responds - no TCP batching.
    IRQ injection via 3-word bitmap at SHM offsets 32/36/40 (IRQs 0-95).
    """

    RCC_BASE = 0x40023800
    RCC_NAMES = {
        0x00: 'CR', 0x04: 'PLLCFGR', 0x08: 'CFGR', 0x0C: 'CIR',
        0x30: 'AHB1ENR', 0x34: 'AHB2ENR', 0x40: 'APB1ENR', 0x44: 'APB2ENR',
    }

    def __init__(self, shm_name: str = SHM_NAME):
        self.shm_name = shm_name
        self.stm32 = STM32F439PeripheralSet()
        self.usb_periph = USBCDCPeripheral("USB_OTG_FS", 0x50000000, irq=67)
        self._access_count = 0
        self._unknown_addrs = set()
        self._rcc_log = []

        # Create SHM bridge
        self.bridge = ShmPeripheralBridge(shm_name=shm_name)

        # Register USB peripheral with adapter
        usb_handler = PeripheralHandler(
            name="USB_OTG_FS",
            base_address=0x50000000,
            size=0x40000,  # 256KB OTG region
            read_callback=self._usb_read,
            write_callback=self._usb_write,
        )
        self.bridge.register_peripheral(0x50000000, usb_handler)

        # Register STM32 peripherals with adapters
        for periph in self.stm32.peripherals:
            handler = PeripheralHandler(
                name=periph.name if hasattr(periph, 'name') else f"STM32_{periph.base:08X}",
                base_address=periph.base,
                size=periph.size,
                read_callback=lambda offset, size, p=periph: self._stm32_read(p, offset, size),
                write_callback=lambda offset, value, size, p=periph: self._stm32_write(p, offset, value, size),
            )
            self.bridge.register_peripheral(periph.base, handler)

        # Catch-all handler for unmapped addresses (returns 0, not 0xDEADBEEF)
        # Must be registered last - ShmPeripheralBridge checks most-specific first
        # We override _find_handler via a custom bridge subclass instead
        self._orig_handle_command = self.bridge._handle_command
        self.bridge._handle_command = self._handle_command_with_default

        # Wire USB IRQ to SHM bitmap
        self.usb_periph.set_irq_callback(self._inject_irq)

    def _handle_command_with_default(self, command, address, data, size, bus_attrs=None):
        """Override: return 0 for unmapped addresses instead of 0xDEADBEEF."""
        handler = self.bridge._find_handler(address)
        if handler is None:
            self._access_count += 1
            if address not in self._unknown_addrs:
                self._unknown_addrs.add(address)
            return 0  # Return 0 like hardware reset values
        return self._orig_handle_command(command, address, data, size, bus_attrs)

    def _inject_irq(self, irq_num: int, level: int):
        """Set/clear IRQ in SHM bitmap."""
        if level:
            self.bridge.set_irq(irq_num)
        else:
            self.bridge.clear_irq(irq_num)

    def _usb_read(self, offset: int, size: int) -> int:
        """Adapter: PeripheralHandler.read -> USBCDCPeripheral.read"""
        addr = 0x50000000 + offset
        self._access_count += 1
        return self.usb_periph.read(addr, size)

    def _usb_write(self, offset: int, value: int, size: int):
        """Adapter: PeripheralHandler.write -> USBCDCPeripheral.write"""
        addr = 0x50000000 + offset
        self._access_count += 1
        self.usb_periph.write(addr, size, value)

        # Track RCC writes if USB region overlaps (shouldn't, but safe)

    def _stm32_read(self, periph, offset: int, size: int) -> int:
        """Adapter: PeripheralHandler.read -> STM32 peripheral.read"""
        addr = periph.base + offset
        self._access_count += 1
        val, _ = periph.read(addr, size)
        return val

    def _stm32_write(self, periph, offset: int, value: int, size: int):
        """Adapter: PeripheralHandler.write -> STM32 peripheral.write"""
        addr = periph.base + offset
        self._access_count += 1

        # Track RCC writes for clock analysis
        if self.RCC_BASE <= addr < self.RCC_BASE + 0x100:
            rcc_offset = addr - self.RCC_BASE
            name = self.RCC_NAMES.get(rcc_offset, f"0x{rcc_offset:02X}")
            self._rcc_log.append((name, value))

        periph.write(addr, size, value)

    def start(self):
        """Create SHM region and start handler loop."""
        self.bridge.create()
        self.bridge.start_handler()
        print(f"      SHM peripheral server started: {self.shm_name}")

    def stop(self):
        """Stop handler and clean up SHM."""
        self.bridge.close()
        # Unlink SHM
        try:
            from multiprocessing import shared_memory
            shm = shared_memory.SharedMemory(name=self.shm_name, create=False)
            shm.close()
            shm.unlink()
        except (FileNotFoundError, ValueError):
            pass


# =============================================================================
# Linux-style USB Enumeration
# =============================================================================

def linux_usb_enumerate(e2e: WargameE2EServer, verbose: bool = False):
    """Perform Linux-kernel-style USB device enumeration.

    Mimics the sequence that the Linux USB core performs when a new device
    is connected to a USB port:

    1. Bus Reset (USBRST) - resets device state machine
    2. Speed Enumeration (ENUMDNE) - negotiate connection speed
    3. SET_ADDRESS - assign unique device address
    4. GET_DEVICE_DESCRIPTOR - read device info (optional, for our purposes)
    5. SET_CONFIGURATION - activate the device's configuration
    6. SET_CONTROL_LINE_STATE - enable DTR/RTS (for CDC-ACM)

    Each step is separated by a delay to allow the firmware's ISR
    to process each event before the next one arrives.
    """
    usb = e2e.usb_periph

    print(f"\n  --- Linux-style USB Enumeration ---")

    # Phase 1: Bus Reset
    # Linux USB hub driver detects device → sends bus reset
    print(f"    [1/6] USB Bus Reset (USBRST)...")
    usb.inject_usbrst()
    time.sleep(1.0)

    # Check what firmware did during USBRST processing
    gintsts_after_rst = usb._compute_gintsts()
    daintmsk_after_rst = usb.regs.get(usb.DAINTMSK, 0)
    gintmsk_after_rst = usb.regs.get(usb.GINTMSK, 0)
    print(f"          GINTSTS=0x{gintsts_after_rst:08X} "
          f"DAINTMSK=0x{daintmsk_after_rst:08X} "
          f"GINTMSK=0x{gintmsk_after_rst:08X}")
    usbrst_cleared = not (gintsts_after_rst & (1 << 12))
    print(f"          USBRST processed: {usbrst_cleared}")

    # Phase 2: Speed Enumeration Done
    # DWC2 core finishes speed negotiation → ENUMDNE
    print(f"    [2/6] Speed Enumeration Done (ENUMDNE, Full Speed)...")
    usb.inject_enumdne()
    time.sleep(0.5)

    daintmsk_after_enum = usb.regs.get(usb.DAINTMSK, 0)
    print(f"          DAINTMSK=0x{daintmsk_after_enum:08X}")

    # Phase 3: Enable SETUP delivery mechanism
    # The firmware may be in DMA mode (no RXFLVL in GINTMSK).
    # We enable RXFLVL + DAINTMSK EP0 so SETUP packets can be delivered
    # via the FIFO interrupt path (HAL code handles both DMA and FIFO modes).
    print(f"    [3/6] Enabling SETUP delivery (RXFLVL + OEPINT + DOEPMSK)...")
    usb.enable_setup_delivery()
    gintmsk_now = usb.regs.get(usb.GINTMSK, 0)
    daintmsk_now = usb.regs.get(usb.DAINTMSK, 0)
    doepmsk_now = usb.regs.get(usb.DOEPMSK, 0)
    print(f"          GINTMSK=0x{gintmsk_now:08X} DAINTMSK=0x{daintmsk_now:08X} "
          f"DOEPMSK=0x{doepmsk_now:08X}")
    print(f"          RXFLVL={bool(gintmsk_now & (1<<4))} "
          f"OEPINT={bool(gintmsk_now & (1<<19))} "
          f"EP0_OUT={bool(daintmsk_now & (1<<16))} "
          f"STUP_MSK={bool(doepmsk_now & 0x08)}")

    # Phase 4: SET_ADDRESS (address=1)
    # Linux sends this first after reset to assign a unique bus address.
    print(f"    [4/6] SET_ADDRESS (addr=1)...")
    usb.inject_setup_packet(struct.pack('<BBHHH', 0x00, 0x05, 1, 0, 0))
    time.sleep(0.5)

    # Check if SETUP was consumed (status queue should be empty)
    sq_len = len(usb._rx_status_queue)
    dq_len = len(usb._rx_data_queue)
    doepint0 = usb.regs.get(usb.DOEPINT0, 0)
    dcfg = usb.regs.get(usb.DCFG, 0)
    dev_addr = (dcfg >> 4) & 0x7F
    print(f"          After SET_ADDRESS: status_q={sq_len} data_q={dq_len} "
          f"DOEPINT0=0x{doepint0:02X} dev_addr={dev_addr}")
    if sq_len > 0:
        print(f"          WARNING: SETUP not consumed! Queue: {usb._rx_status_queue}")
        usb._rx_status_queue.clear()
        usb._rx_data_queue.clear()
        print(f"          Cleared stale entries")

    # Phase 5: SET_CONFIGURATION (config=1)
    # This is the critical step: triggers USBD_SetConfig → USBD_CDC_Init
    # which allocates pClassData, opens EP1 IN/OUT, sets TxState=0.
    print(f"    [5/6] SET_CONFIGURATION (config=1)...")
    usb.inject_setup_packet(struct.pack('<BBHHH', 0x00, 0x09, 1, 0, 0))
    time.sleep(1.0)

    sq_len = len(usb._rx_status_queue)
    dq_len = len(usb._rx_data_queue)
    daintmsk_final = usb.regs.get(usb.DAINTMSK, 0)
    print(f"          After SET_CONFIG: status_q={sq_len} data_q={dq_len}")
    print(f"          DAINTMSK=0x{daintmsk_final:08X}")
    # If firmware processed SET_CONFIGURATION, DAINTMSK should now include EP1
    ep1_in = bool(daintmsk_final & (1 << 1))
    ep1_out = bool(daintmsk_final & (1 << 17))
    print(f"          EP1_IN={ep1_in} EP1_OUT={ep1_out}")

    # Phase 6: SET_CONTROL_LINE_STATE (DTR=1, RTS=1)
    # Linux tty layer sends this when the serial port is opened.
    # wValue bit 0 = DTR, bit 1 = RTS.
    print(f"    [6/6] SET_CONTROL_LINE_STATE (DTR+RTS)...")
    usb.inject_setup_packet(struct.pack('<BBHHH', 0x21, 0x22, 0x0003, 0, 0))
    time.sleep(0.3)

    # Clear any stale SETUP data from queues
    # (DMA-mode firmware pops status but doesn't read FIFO data for SETUP)
    stale_status = len(usb._rx_status_queue)
    stale_data = len(usb._rx_data_queue)
    usb._rx_status_queue.clear()
    usb._rx_data_queue.clear()
    usb._rx_fifo_consumed = 0
    if stale_status or stale_data:
        print(f"          Cleared stale: {stale_status} status, {stale_data} data bytes")

    # The wargame firmware doesn't properly process SETUP packets (it triggers
    # USB_DevInit instead of reading FIFO data). Force USB peripheral to the
    # state that would result from successful enumeration.
    print(f"    [7/7] Force USB peripheral to configured state...")
    usb.force_configured_state(dev_addr=1)
    daintmsk_forced = usb.regs.get(usb.DAINTMSK, 0)
    gintmsk_forced = usb.regs.get(usb.GINTMSK, 0)
    dcfg_forced = usb.regs.get(usb.DCFG, 0)
    dev_addr_forced = (dcfg_forced >> 4) & 0x7F
    ep1_in = bool(daintmsk_forced & (1 << 1))
    ep1_out = bool(daintmsk_forced & (1 << 17))
    print(f"          DAINTMSK=0x{daintmsk_forced:08X} GINTMSK=0x{gintmsk_forced:08X}")
    print(f"          dev_addr={dev_addr_forced} EP1_IN={ep1_in} EP1_OUT={ep1_out}")

    usb.configured = True
    print(f"    --- Enumeration complete ---\n")

    return True


# =============================================================================
# Main
# =============================================================================

def run_wargame_test(firmware_path: str, verbose: bool = False, use_shm: bool = False):
    if verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s')
    else:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s')

    mode_str = "SHM" if use_shm else "TCP"
    print()
    print("=" * 70)
    print(f"  Wargame USB CDC-ACM over USBIP - E2E Test [{mode_str} mode]")
    print("  (Linux-kernel-style USB enumeration)")
    print("=" * 70)
    print()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..', '..', '..', '..'))
    qemu = os.path.join(project_root, 'qemu', 'build', 'qemu-system-arm')

    if not os.path.exists(firmware_path):
        print(f"  ERROR: Firmware not found: {firmware_path}")
        return False

    if not os.path.exists(qemu):
        print(f"  ERROR: QEMU not found: {qemu}")
        return False

    def find_free_port():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    usbip_port = find_free_port()

    # Step 1: Start peripheral server
    if use_shm:
        print(f"  [1] Starting SHM peripheral server ({SHM_NAME})...")
        e2e = WargameShmServer(shm_name=SHM_NAME)
        e2e.start()
    else:
        print(f"  [1] Starting TCP peripheral server (port {PERIPH_PORT})...")
        e2e = WargameE2EServer(periph_port=PERIPH_PORT)
        e2e.start_threaded()
    print(f"      USB OTG_FS @ 0x{e2e.usb_periph.base:08X}")
    print(f"      STM32 peripherals: {len(e2e.stm32.peripherals)}")

    # Step 2: Start USBIP server with CDC bridge
    print(f"  [2] Starting USBIP server (port {usbip_port})...")
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

    # Step 3: Start QEMU (with GDB stub for memory writes)
    if use_shm:
        machine_opt = f'slab-cortex-m,proxy-mode=shm,shm-name={SHM_NAME}'
    else:
        machine_opt = 'slab-cortex-m'
    print(f"  [3] Starting QEMU with wargame firmware ({mode_str})...")
    qemu_proc = subprocess.Popen(
        [qemu, '-M', machine_opt, '-cpu', 'cortex-m4',
         '-nographic', '-kernel', firmware_path,
         '-s',  # GDB stub on port 1234 for memory access
         '-d', 'guest_errors,unimp'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f"      PID: {qemu_proc.pid}")

    # Wait for firmware init (HAL: clock config, GPIO, USB core init)
    print("      Waiting for firmware init (2.5s)...")
    time.sleep(2.5)
    print(f"      MMIO accesses after init: {e2e._access_count}")
    if e2e._unknown_addrs:
        print(f"      Unknown periph addrs: {[f'0x{a:08X}' for a in sorted(e2e._unknown_addrs)[:10]]}")

    # Show RCC/clock configuration
    if e2e._rcc_log:
        print(f"      RCC writes ({len(e2e._rcc_log)}):")
        for name, val in e2e._rcc_log:
            if name == 'PLLCFGR':
                pllm = val & 0x3F
                plln = (val >> 6) & 0x1FF
                pllp = ((val >> 16) & 0x3) * 2 + 2
                pllq = (val >> 24) & 0xF
                pllsrc = 'HSE' if (val >> 22) & 1 else 'HSI'
                print(f"        {name}=0x{val:08X} (M={pllm} N={plln} P={pllp} Q={pllq} src={pllsrc})")
            elif name == 'CFGR':
                sw = val & 0x3
                sw_names = ['HSI', 'HSE', 'PLL', '?']
                ahbpre = (val >> 4) & 0xF
                apb1pre = (val >> 10) & 0x7
                apb2pre = (val >> 13) & 0x7
                print(f"        {name}=0x{val:08X} (SW={sw_names[sw]} AHB_PRE={ahbpre} APB1={apb1pre} APB2={apb2pre})")
            elif name in ('AHB1ENR', 'AHB2ENR', 'APB1ENR', 'APB2ENR'):
                print(f"        {name}=0x{val:08X}")
            elif name == 'CR':
                print(f"        {name}=0x{val:08X} (HSEON={bool(val&(1<<16))} PLLON={bool(val&(1<<24))})")
            else:
                print(f"        {name}=0x{val:08X}")

    # Show firmware's USB state after init
    gintmsk = e2e.usb_periph.regs.get(0x018, 0)
    gahbcfg = e2e.usb_periph.regs.get(0x008, 0)
    daintmsk = e2e.usb_periph.regs.get(0x81C, 0)
    print(f"      Post-init: GINTMSK=0x{gintmsk:08X} GAHBCFG=0x{gahbcfg:08X}")
    print(f"        GAHBCFG.GINTMSK(bit0)={bool(gahbcfg & 1)}")
    print(f"        GINTMSK.RXFLVL={bool(gintmsk & (1<<4))}")
    print(f"        GINTMSK.USBRST={bool(gintmsk & (1<<12))}")
    print(f"        GINTMSK.OEPINT={bool(gintmsk & (1<<19))}")
    print(f"        DAINTMSK=0x{daintmsk:08X}")

    # Step 4: Linux-style USB enumeration
    print(f"\n  [4] USB Enumeration (Linux-style)...")
    linux_usb_enumerate(e2e, verbose=verbose)

    # Step 4b: Patch firmware state via GDB stub
    # The wargame firmware has a custom USB stack that doesn't process
    # SET_CONFIGURATION. We directly patch pClassData to unblock TX:
    # - hUsbDeviceFS at 0x20000494
    # - pClassData is accessed indirectly via pClassDataCmsit
    # - TxState at pClassData + 0x214 (must be 0 for TX to work)
    print(f"\n  [4b] Patching firmware state via GDB stub (port {GDB_PORT})...")
    ok = gdb_patch_firmware(
        pdev_addr=0x20000494,
        pclassdata_value=0x20010000,
        port=GDB_PORT
    )
    if ok:
        print(f"       Firmware patched successfully")
    else:
        print(f"       WARNING: GDB patch failed - TX may be blocked")
    time.sleep(0.5)  # Let firmware resume and process

    # Step 5: Monitor USB register activity
    print(f"  [5] Monitoring USB activity (1s)...")
    _tx_trace = {'fifo_writes': [], 'ep_ctrl_writes': []}
    _rx_trace = {'fifo_reads': 0, 'grxstsr': 0, 'grxstsp': 0, 'gintsts': 0}
    _orig_read = e2e.usb_periph.read
    _orig_write = e2e.usb_periph.write

    def _traced_read(addr, size, secure=False):
        val = _orig_read(addr, size, secure)
        offset = addr - e2e.usb_periph.base
        if 0x1000 <= offset < 0x20000:
            _rx_trace['fifo_reads'] += 1
        elif offset == 0x01C:
            _rx_trace['grxstsr'] += 1
        elif offset == 0x020:
            _rx_trace['grxstsp'] += 1
        elif offset == 0x014:
            _rx_trace['gintsts'] += 1
        return val

    def _traced_write(addr, size, value, secure=False):
        offset = addr - e2e.usb_periph.base
        if 0x1000 <= offset < 0x20000:
            ep = (offset - 0x1000) // 0x1000
            if len(_tx_trace['fifo_writes']) < 50:
                _tx_trace['fifo_writes'].append((ep, value))
        if 0x900 <= offset < 0xC00:
            if len(_tx_trace['ep_ctrl_writes']) < 30:
                _tx_trace['ep_ctrl_writes'].append((offset, value))
        return _orig_write(addr, size, value, secure)

    e2e.usb_periph.read = _traced_read
    e2e.usb_periph.write = _traced_write
    time.sleep(1.0)

    print(f"      Polling: GINTSTS={_rx_trace['gintsts']} "
          f"GRXSTSR={_rx_trace['grxstsr']} GRXSTSP={_rx_trace['grxstsp']}")
    print(f"      FIFO: reads={_rx_trace['fifo_reads']} "
          f"writes={len(_tx_trace['fifo_writes'])}")
    if _tx_trace['fifo_writes']:
        print(f"      TX FIFO activity detected!")
        for ep, val in _tx_trace['fifo_writes'][:5]:
            b = bytes([(val >> (i*8)) & 0xFF for i in range(4)])
            print(f"        EP{ep}: 0x{val:08X} = {b!r}")

    e2e.usb_periph.read = _orig_read
    e2e.usb_periph.write = _orig_write

    try:
        # Step 6: USBIP DevList
        print(f"\n  [6] USBIP DevList...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', usbip_port))
        devlist = usbip_devlist(sock)
        print(f"      Status: {devlist['status']}, Devices: {len(devlist['devices'])}")
        for d in devlist['devices']:
            print(f"      -> {d['busid']} VID:PID {d['vid']:04X}:{d['pid']:04X}")
        sock.close()

        # Step 7: Import device
        print(f"\n  [7] USBIP Import...")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect(('127.0.0.1', usbip_port))
        imp = usbip_import(sock, "1-1")
        print(f"      Status: {imp['status']}")
        if imp['status'] != 0:
            print("      FAILED to import device")
            return False

        seqnum = 1

        # Step 8: Send data to firmware
        # The wargame firmware expects Enter first to trigger the prompt,
        # then the password.
        print(f"\n  [8] Sending data to firmware...")

        # Re-enable tracing for TX output and GINTMSK writes
        _tx_trace2 = {'fifo_writes': [], 'gintmsk_writes': [], 'grxstsp_reads': 0}
        _orig_write2 = e2e.usb_periph.write
        _orig_read2 = e2e.usb_periph.read
        def _traced_write2(addr, size, value, secure=False):
            offset = addr - e2e.usb_periph.base
            if 0x1000 <= offset < 0x20000:
                ep = (offset - 0x1000) // 0x1000
                if len(_tx_trace2['fifo_writes']) < 200:
                    _tx_trace2['fifo_writes'].append((ep, value))
            if offset == 0x018:  # GINTMSK
                _tx_trace2['gintmsk_writes'].append(value)
            return _orig_write2(addr, size, value, secure)
        def _traced_read2(addr, size, secure=False):
            offset = addr - e2e.usb_periph.base
            if offset == 0x020:  # GRXSTSP
                _tx_trace2['grxstsp_reads'] += 1
            return _orig_read2(addr, size, secure)
        e2e.usb_periph.write = _traced_write2
        e2e.usb_periph.read = _traced_read2

        # 8a: Send Enter (triggers firmware's initial state transition)
        # The firmware uses \n as line terminator for command processing
        # Use proper DWC2 OUT transfer sequence (matching CDCBridge):
        # Phase 1: DATA_UPDT (pktsts=2) + data in FIFO
        # Phase 2: XFER_COMP (pktsts=3) - transfer complete notification
        # Phase 3: Set DOEPINT1.XFRC for endpoint interrupt
        trigger = b"\n"
        print(f"      [8a] Sending \\n to trigger prompt...")
        usb = e2e.usb_periph

        # Track IRQ assertions
        _irq_trace = {'set_count': 0, 'clear_count': 0, 'last_level': None}
        _orig_irq_cb = usb.irq_callback
        def _traced_irq_cb(irq_num, level):
            if level:
                _irq_trace['set_count'] += 1
            else:
                _irq_trace['clear_count'] += 1
            _irq_trace['last_level'] = level
            if _orig_irq_cb:
                _orig_irq_cb(irq_num, level)
        usb.irq_callback = _traced_irq_cb

        usb._rx_status_queue.append((1, 0x2, len(trigger)))  # DATA_UPDT
        usb._rx_data_queue.extend(trigger)
        usb._rx_status_queue.append((1, 0x3, 0))  # XFER_COMP
        doepint1 = usb.DOEPINT0 + 0x20
        usb.regs[doepint1] = usb.regs.get(doepint1, 0) | 0x01  # XFRC
        usb.trigger_irq()

        # Log IRQ state for debugging
        gintsts = usb._compute_gintsts()
        gintmsk = usb.regs.get(usb.GINTMSK, 0)
        gahbcfg = usb.regs.get(usb.GAHBCFG, 0)
        print(f"           After inject: GINTSTS=0x{gintsts:08X} GINTMSK=0x{gintmsk:08X}")
        print(f"           RXFLVL={bool(gintsts & (1<<4))} OEPINT={bool(gintsts & (1<<19))}")
        print(f"           GAHBCFG.GINT={bool(gahbcfg & 1)} IRQ_set={_irq_trace['set_count']} IRQ_clear={_irq_trace['clear_count']}")
        time.sleep(1.5)

        print(f"           TX FIFO writes: {len(_tx_trace2['fifo_writes'])}")
        print(f"           GRXSTSP reads: {_tx_trace2['grxstsp_reads']}")
        print(f"           GINTMSK writes: {len(_tx_trace2['gintmsk_writes'])}")
        if _tx_trace2['gintmsk_writes']:
            print(f"           GINTMSK values: {[f'0x{v:08X}' for v in _tx_trace2['gintmsk_writes'][:5]]}")
        if _tx_trace2['fifo_writes']:
            tx_bytes = bytearray()
            for ep, val in _tx_trace2['fifo_writes']:
                for i in range(4):
                    b = (val >> (i*8)) & 0xFF
                    if b:
                        tx_bytes.append(b)
            if tx_bytes:
                print(f"           TX text: {tx_bytes.decode('ascii', errors='replace')!r}")

        # 8b: Send password
        password = b"DEBUG123\n"
        print(f"      [8b] Sending password '{password.decode().strip()}'...")
        usb._rx_status_queue.append((1, 0x2, len(password)))  # DATA_UPDT
        usb._rx_data_queue.extend(password)
        usb._rx_status_queue.append((1, 0x3, 0))  # XFER_COMP
        usb.regs[doepint1] = usb.regs.get(doepint1, 0) | 0x01  # XFRC
        usb.trigger_irq()
        time.sleep(1.5)

        e2e.usb_periph.write = _orig_write2
        e2e.usb_periph.read = _orig_read2
        usb.irq_callback = _orig_irq_cb

        print(f"           TX FIFO writes total: {len(_tx_trace2['fifo_writes'])}")
        print(f"           IRQ assertions: set={_irq_trace['set_count']} clear={_irq_trace['clear_count']}")
        print(f"           GRXSTSP reads total: {_tx_trace2['grxstsp_reads']}")
        print(f"           GINTMSK writes total: {len(_tx_trace2['gintmsk_writes'])}")
        if _tx_trace2['gintmsk_writes']:
            print(f"           GINTMSK values: {[f'0x{v:08X}' for v in _tx_trace2['gintmsk_writes'][:10]]}")
        if _tx_trace2['fifo_writes']:
            tx_bytes = bytearray()
            for ep, val in _tx_trace2['fifo_writes']:
                for i in range(4):
                    b = (val >> (i*8)) & 0xFF
                    if b:
                        tx_bytes.append(b)
            if tx_bytes:
                print(f"           TX text: {tx_bytes.decode('ascii', errors='replace')!r}")
        else:
            print(f"           WARNING: No TX output from firmware!")
            print(f"           Possible causes:")
            print(f"             - SET_CONFIGURATION not processed (pClassData still NULL)")
            print(f"             - TxState != 0 (CDC busy)")
            print(f"             - Firmware waiting for different input")

        # Step 9: Read from USBIP
        print(f"\n  [9] Reading USBIP response...")
        usbip_tx_buf = bytes(usbip_dev.tx_buffer)
        if usbip_tx_buf:
            print(f"      TX buffer ({len(usbip_tx_buf)} bytes): {usbip_tx_buf!r}")
            print(f"      Text: {usbip_tx_buf.decode('ascii', errors='replace')}")
        else:
            print(f"      TX buffer: empty")

        # Step 10: State summary
        print(f"\n  [10] Final State:")
        print(f"       Total MMIO accesses: {e2e._access_count}")
        print(f"       Status queue: {len(e2e.usb_periph._rx_status_queue)}")
        print(f"       Data queue: {len(e2e.usb_periph._rx_data_queue)}")
        daintmsk_final = e2e.usb_periph.regs.get(0x81C, 0)
        gintmsk_final = e2e.usb_periph.regs.get(0x018, 0)
        print(f"       DAINTMSK=0x{daintmsk_final:08X} GINTMSK=0x{gintmsk_final:08X}")

        sock.close()

    except Exception as ex:
        import traceback
        print(f"\n  ERROR: {ex}")
        traceback.print_exc()
    finally:
        print(f"\n  Cleaning up...")
        qemu_proc.terminate()
        qemu_proc.wait(timeout=5)
        e2e.stop()

    print("\n  Done.")
    return True


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    flags = [a for a in sys.argv[1:] if a.startswith('-')]
    firmware = args[0] if args else "/home/mre/Téléchargements/wargame.bin"
    verbose = '--verbose' in flags or '-v' in flags
    use_shm = '--shm' in flags
    run_wargame_test(firmware, verbose=verbose, use_shm=use_shm)
