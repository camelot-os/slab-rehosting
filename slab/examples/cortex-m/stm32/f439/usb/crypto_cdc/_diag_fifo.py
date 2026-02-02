#!/usr/bin/env python3
"""Minimal diagnostic: trace FIFO reads from firmware."""
import asyncio
import struct
import sys
import os
import subprocess
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet
from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
from slab_cortex_m.cdc_bridge import CDCBridge
from slab_cortex_m.usbip_server import USBIPServer, CDCACMDevice

PERIPH_PORT = 5000
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
QEMU = os.path.join(PROJECT_ROOT, 'qemu', 'build', 'qemu-system-arm')
FIRMWARE = os.path.join(os.path.dirname(__file__), '..', '..', 'build', 'test_usb_cdc_crypto.bin')

# Trace state
trace_log = []  # chronological: (seq, 'R'|'W', offset, value)
fifo_reads = []
fifo_writes = []
grxstsr_reads = []
gintsts_reads = []
seq_counter = [0]
capturing = [False]  # only capture after data injection

class TracingUSBPeripheral(USBCDCPeripheral):
    """USB peripheral with tracing on FIFO and status reads."""

    def read(self, addr, size, secure=False):
        offset = addr - self.base
        value = super().read(addr, size, secure)

        if capturing[0]:
            seq_counter[0] += 1
            seq = seq_counter[0]
            if seq <= 50:  # Log first 50 accesses after injection
                if 0x1000 <= offset < 0x20000:
                    b = bytes([(value>>(i*8))&0xFF for i in range(4)])
                    trace_log.append(f"  [{seq:3d}] RD FIFO(0x{offset:04X}) -> 0x{value:08X} ({b!r}) rxbuf={len(self.rx_buffer)}")
                elif offset == 0x014:
                    rxflvl = (value >> 4) & 1
                    trace_log.append(f"  [{seq:3d}] RD GINTSTS -> 0x{value:08X} RXFLVL={rxflvl}")
                elif offset == 0x01C:
                    pktsts = (value >> 17) & 0xF
                    bcnt = (value >> 4) & 0x7FF
                    trace_log.append(f"  [{seq:3d}] RD GRXSTSR -> 0x{value:08X} pktsts={pktsts} bcnt={bcnt}")
                else:
                    trace_log.append(f"  [{seq:3d}] RD 0x{offset:04X} -> 0x{value:08X}")

        if 0x1000 <= offset < 0x20000:
            fifo_reads.append((len(fifo_reads), offset, value, len(self.rx_buffer)))
        elif offset == 0x01C:
            pktsts = (value >> 17) & 0xF
            bcnt = (value >> 4) & 0x7FF
            epnum = value & 0xF
            grxstsr_reads.append((pktsts, bcnt, epnum, value))
        elif offset == 0x014:
            gintsts_reads.append(value)

        return value

    def write(self, addr, size, value, secure=False):
        offset = addr - self.base
        if capturing[0]:
            seq_counter[0] += 1
            seq = seq_counter[0]
            if seq <= 50:
                if 0x1000 <= offset < 0x20000:
                    ep = (offset - 0x1000) // 0x1000
                    b = bytes([(value>>(i*8))&0xFF for i in range(4)])
                    trace_log.append(f"  [{seq:3d}] WR FIFO(EP{ep}) <- 0x{value:08X} ({b!r})")
                elif offset == 0x014:
                    trace_log.append(f"  [{seq:3d}] WR GINTSTS <- 0x{value:08X} (W1C)")
                else:
                    trace_log.append(f"  [{seq:3d}] WR 0x{offset:04X} <- 0x{value:08X}")
        if 0x1000 <= offset < 0x20000:
            ep = (offset - 0x1000) // 0x1000
            fifo_writes.append((ep, value))
        return super().write(addr, size, value, secure)


async def run_diag():
    print("=" * 60)
    print("  DIAGNOSTIC: FIFO read/write trace")
    print("=" * 60)

    stm32 = STM32F439PeripheralSet()
    usb_periph = TracingUSBPeripheral("USB_OTG_FS", 0x50000000, irq=67)

    # --- Start peripheral server ---
    tcp_log = []  # (seq, 'R'|'W', addr, size, val_or_write)
    tcp_seq = [0]

    async def handle_client(reader, writer):
        try:
            while True:
                data = await reader.read(1)
                if not data:
                    break
                cmd = data[0]
                if cmd in (ord('R'), ord('S')):
                    payload = await reader.readexactly(9)
                    addr, sz = struct.unpack('<II', payload[:8])
                    if usb_periph.contains(addr):
                        val = usb_periph.read(addr, sz)
                    else:
                        val = 0
                        for p in stm32.peripherals:
                            if p.base <= addr < p.base + p.size:
                                val, _ = p.read(addr, sz)
                                break
                    resp = struct.pack('<IB', val & 0xFFFFFFFF, 0)
                    writer.write(resp)
                    await writer.drain()
                    if capturing[0]:
                        tcp_seq[0] += 1
                        if tcp_seq[0] <= 30:
                            off = addr - 0x50000000 if 0x50000000 <= addr < 0x50040000 else addr
                            tcp_log.append(f"TCP[{tcp_seq[0]:2d}] R addr=0x{addr:08X}(off=0x{off:04X}) sz={sz} -> val=0x{val:08X} resp={resp.hex()}")
                elif cmd in (ord('W'), ord('T')):
                    payload = await reader.readexactly(13)
                    addr, sz, val = struct.unpack('<III', payload[:12])
                    if usb_periph.contains(addr):
                        usb_periph.write(addr, sz, val)
                    else:
                        for p in stm32.peripherals:
                            if p.base <= addr < p.base + p.size:
                                p.write(addr, sz, val)
                                break
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
                    if capturing[0]:
                        tcp_seq[0] += 1
                        if tcp_seq[0] <= 30:
                            off = addr - 0x50000000 if 0x50000000 <= addr < 0x50040000 else addr
                            tcp_log.append(f"TCP[{tcp_seq[0]:2d}] W addr=0x{addr:08X}(off=0x{off:04X}) sz={sz} val=0x{val:08X}")
                elif cmd == ord('C'):
                    await reader.readexactly(10)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle_client, '127.0.0.1', PERIPH_PORT)
    print(f"\n[1] Peripheral server started on port {PERIPH_PORT}")

    # --- Start QEMU ---
    print(f"[2] Starting QEMU with {os.path.basename(FIRMWARE)}")
    qemu_proc = subprocess.Popen(
        [QEMU, '-M', 'slab-cortex-m', '-cpu', 'cortex-m4',
         '-nographic', '-kernel', FIRMWARE],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    # --- Wait for firmware to initialize ---
    print("[3] Waiting for firmware init (2s)...")
    await asyncio.sleep(2.0)
    print(f"    GINTSTS reads so far: {len(gintsts_reads)}")
    print(f"    FIFO reads: {len(fifo_reads)}, FIFO writes: {len(fifo_writes)}")

    # --- Setup CDCBridge + CDCACMDevice ---
    usbip_dev = CDCACMDevice()
    bridge = CDCBridge(usb_periph, usbip_dev)
    print(f"    CDCBridge connected: handle_tx_data patched={usb_periph.handle_tx_data != TracingUSBPeripheral.handle_tx_data}")

    # --- Inject "PING\n" via CDCBridge (simulating USBIP host OUT) ---
    print("\n[4] Injecting 'PING\\n' via CDCBridge._handle_host_out...")
    data = b'PING\n'
    bridge._handle_host_out(1, data)
    print(f"    rx_buffer: {list(usb_periph.rx_buffer)} ({len(usb_periph.rx_buffer)} bytes)")
    capturing[0] = True  # Start chronological trace

    # --- Wait for firmware to process ---
    print("[5] Waiting for firmware to process (3s)...")
    await asyncio.sleep(3.0)

    print(f"\n[6] Results:")
    print(f"\n  --- Chronological Access Log (first {len(trace_log)} entries) ---")
    for entry in trace_log:
        print(entry)
    print(f"  --- End Log ---\n")
    print(f"    rx_buffer remaining: {list(usb_periph.rx_buffer)}")
    print(f"    GRXSTSR reads: {len(grxstsr_reads)}")
    for i, (pktsts, bcnt, epnum, raw) in enumerate(grxstsr_reads):
        print(f"      [{i}] pktsts={pktsts} bcnt={bcnt} epnum={epnum} raw=0x{raw:08X}")
    print(f"    FIFO reads: {len(fifo_reads)}")
    for i, (idx, off, val, remaining) in enumerate(fifo_reads):
        b = bytes([(val>>(j*8))&0xFF for j in range(4)])
        print(f"      [{i}] offset=0x{off:04X} val=0x{val:08X} ({b!r}) remaining={remaining}")
    print(f"    FIFO writes (firmware TX): {len(fifo_writes)}")
    tx_bytes = bytearray()
    for ep, val in fifo_writes:
        for j in range(4):
            byte = (val >> (j*8)) & 0xFF
            if byte:
                tx_bytes.append(byte)
    print(f"    TX output (from FIFO writes): {bytes(tx_bytes)!r}")
    print(f"    USBIP tx_buffer: {bytes(usbip_dev.tx_buffer)!r}")

    if tcp_log:
        print(f"\n  --- TCP Protocol Log (first {len(tcp_log)} entries) ---")
        for entry in tcp_log:
            print(f"    {entry}")
        print(f"  --- End TCP Log ---")

    # Cleanup
    qemu_proc.terminate()
    try:
        qemu_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        qemu_proc.kill()
    server.close()
    await server.wait_closed()

    return b'PONG' in tx_bytes or b'PONG' in bytes(usbip_dev.tx_buffer)

if __name__ == "__main__":
    ok = asyncio.run(run_diag())
    print(f"\n{'PASS' if ok else 'FAIL'}: {'PONG received' if ok else 'PONG not received'}")
    sys.exit(0 if ok else 1)
