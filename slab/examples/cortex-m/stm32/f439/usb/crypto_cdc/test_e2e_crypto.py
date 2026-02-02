#!/usr/bin/env python3
"""
E2E Test: Python ↔ QEMU ↔ STM32F439 Crypto Firmware

Demonstrates full interaction chain:
  1. Python starts peripheral server (STM32 CRYP/HASH + USART CDC bridge)
  2. QEMU runs crypto firmware on slab-cortex-m
  3. Python injects commands via USART1 RX buffer
  4. Firmware processes crypto operations using CRYP/HASH peripherals
  5. Python reads firmware output from USART1 TX buffer

Data path:
  Python Script
    ↓ (inject into USART1 rx_buffer)
  MCUemu Server (port 5000)
    ↓ (TCP proxy protocol)
  QEMU slab-cortex-m
    ↓ (firmware reads USART1_DR at 0x40011004)
  Firmware processes command (calls CRYP at 0x50060000)
    ↓ (firmware writes result to USART1_DR)
  MCUemu Server captures TX output
    ↓
  Python reads tx_buffer

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import sys
import os
import subprocess
import time
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'python'))

from slab_stm32 import STM32F439PeripheralSet


# =============================================================================
# CDC over USART1 Bridge
# =============================================================================

class CDCoverUSART:
    """Virtual CDC-ACM interface over USART1 registers.

    The firmware uses USART1 at 0x40011000:
      - SR  (0x00): Status register (bit 5=RXNE, bit 7=TXE)
      - DR  (0x04): Data register (read=RX, write=TX)
      - BRR (0x08): Baud rate (ignored in emulation)
      - CR1 (0x0C): Control register

    This class intercepts USART1 read/write operations to provide
    a virtual serial port between the Python script and the firmware.
    """

    USART1_BASE = 0x40011000
    SR_OFFSET = 0x00
    DR_OFFSET = 0x04
    BRR_OFFSET = 0x08
    CR1_OFFSET = 0x0C

    USART_SR_RXNE = (1 << 5)   # RX not empty
    USART_SR_TXE = (1 << 7)    # TX empty (always ready)
    USART_SR_TC = (1 << 6)     # Transmission complete

    def __init__(self):
        self.rx_buffer: deque = deque()  # Characters to feed to firmware
        self.tx_buffer: list = []        # Characters received from firmware
        self.cr1 = 0
        self.brr = 0

    @property
    def size(self):
        return 0x400

    @property
    def base(self):
        return self.USART1_BASE

    def read(self, addr: int, size: int):
        """Handle firmware read from USART1 registers."""
        offset = addr - self.USART1_BASE
        if offset == self.SR_OFFSET:
            sr = self.USART_SR_TXE | self.USART_SR_TC
            if self.rx_buffer:
                sr |= self.USART_SR_RXNE
            return sr, 0
        elif offset == self.DR_OFFSET:
            if self.rx_buffer:
                return self.rx_buffer.popleft(), 0
            return 0, 0
        elif offset == self.BRR_OFFSET:
            return self.brr, 0
        elif offset == self.CR1_OFFSET:
            return self.cr1, 0
        return 0, 0

    def write(self, addr: int, size: int, value: int):
        """Handle firmware write to USART1 registers."""
        offset = addr - self.USART1_BASE
        if offset == self.DR_OFFSET:
            char = chr(value & 0xFF)
            self.tx_buffer.append(char)
        elif offset == self.BRR_OFFSET:
            self.brr = value
        elif offset == self.CR1_OFFSET:
            self.cr1 = value

    def inject_command(self, cmd: str):
        """Queue a command for the firmware to read."""
        for ch in cmd:
            self.rx_buffer.append(ord(ch))
        self.rx_buffer.append(ord('\n'))

    def get_output(self) -> str:
        """Get and clear accumulated TX output."""
        result = ''.join(self.tx_buffer)
        self.tx_buffer.clear()
        return result


# =============================================================================
# Peripheral Server
# =============================================================================

class CryptoE2EServer:
    """Async TCP server handling QEMU peripheral proxy protocol."""

    def __init__(self, port: int = 5000):
        self.port = port
        self.stm32 = STM32F439PeripheralSet()
        self.cdc = CDCoverUSART()
        self.server = None
        self._running = False
        self._access_count = 0

    async def start(self):
        """Start the TCP server."""
        self.server = await asyncio.start_server(
            self._handle_client, '127.0.0.1', self.port
        )
        self._running = True
        async with self.server:
            await self.server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader,
                             writer: asyncio.StreamWriter):
        """Handle binary protocol from QEMU proxy.

        Protocol (little-endian):
          Read:   [CMD:1][addr:4][size:4][secure:1] → resp [value:4][status:1]
          Write:  [CMD:1][addr:4][size:4][value:4][secure:1] → resp [value:4][status:1]
          Config: [CMD:1][subcmd:1][region:4][limit:4][attrs:1] → resp [value:4][status:1]
        """
        try:
            while self._running:
                data = await reader.read(1)
                if not data:
                    break
                cmd = data[0]

                if cmd in (ord('R'), ord('S')):
                    # Read: [addr:4][size:4][secure:1] = 9 bytes
                    payload = await reader.readexactly(9)
                    addr, size = struct.unpack('<II', payload[:8])
                    value = self._dispatch_read(addr, size)
                    writer.write(struct.pack('<IB', value, 0))
                    await writer.drain()
                    self._access_count += 1

                elif cmd in (ord('W'), ord('T')):
                    # Write: [addr:4][size:4][value:4][secure:1] = 13 bytes
                    payload = await reader.readexactly(13)
                    addr, size, value = struct.unpack('<III', payload[:12])
                    self._dispatch_write(addr, size, value)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
                    self._access_count += 1

                elif cmd == ord('C'):
                    # Config: [subcmd:1][region:4][limit:4][attrs:1] = 10 bytes
                    payload = await reader.readexactly(10)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()

        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            writer.close()

    def _dispatch_read(self, addr: int, size: int) -> int:
        """Route read to the correct peripheral."""
        # USART1 CDC bridge (0x40011000 - 0x400113FF)
        if self.cdc.USART1_BASE <= addr < self.cdc.USART1_BASE + self.cdc.size:
            val, _ = self.cdc.read(addr, size)
            return val

        # STM32 peripherals (RCC, CRYP, HASH, etc.)
        for periph in self.stm32.peripherals:
            if periph.base <= addr < periph.base + periph.size:
                val, _ = periph.read(addr, size)
                return val
        return 0

    def _dispatch_write(self, addr: int, size: int, value: int):
        """Route write to the correct peripheral."""
        # USART1 CDC bridge
        if self.cdc.USART1_BASE <= addr < self.cdc.USART1_BASE + self.cdc.size:
            self.cdc.write(addr, size, value)
            return

        # STM32 peripherals
        for periph in self.stm32.peripherals:
            if periph.base <= addr < periph.base + periph.size:
                periph.write(addr, size, value)
                return

    def stop(self):
        self._running = False
        if self.server:
            self.server.close()


# =============================================================================
# E2E Test Runner
# =============================================================================

async def run_e2e_test():
    """Run the full E2E interaction test."""
    print()
    print("=" * 70)
    print("  STM32F439 Crypto CDC - End-to-End Interaction Proof")
    print("=" * 70)
    print()
    print("  Data flow:")
    print("    Python inject_command()")
    print("      → USART1 RX buffer")
    print("        → QEMU slab-cortex-m (TCP proxy)")
    print("          → Firmware reads USART1_DR (0x40011004)")
    print("            → Firmware calls CRYP (0x50060000) / HASH (0x50060400)")
    print("              → Firmware writes result to USART1_DR")
    print("                → Python reads tx_buffer")
    print()

    # Paths
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
    qemu = os.path.join(project_root, 'qemu', 'build', 'qemu-system-arm')
    firmware = os.path.join(os.path.dirname(__file__), 'stm32_crypto_cdc.bin')

    if not os.path.exists(firmware):
        print(f"  ERROR: Firmware not found: {firmware}")
        print(f"         Run: make -C tests/firmware/examples/stm32_crypto_cdc/")
        return False

    if not os.path.exists(qemu):
        print(f"  ERROR: QEMU not found: {qemu}")
        return False

    # Step 1: Start peripheral server
    print("  [1/7] Starting peripheral server (STM32F439 + USART1 CDC)...")
    e2e = CryptoE2EServer(port=5000)
    server_task = asyncio.create_task(e2e.start())
    await asyncio.sleep(0.3)
    print(f"         Peripherals: {len(e2e.stm32.peripherals)} registered")
    print(f"         CDC bridge:  USART1 @ 0x{e2e.cdc.USART1_BASE:08X}")

    # Step 2: Start QEMU
    print()
    print("  [2/7] Starting QEMU with crypto firmware...")
    qemu_proc = subprocess.Popen(
        [qemu, '-M', 'slab-cortex-m', '-cpu', 'cortex-m4',
         '-nographic', '-kernel', firmware],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f"         Machine: slab-cortex-m (Cortex-M4)")
    print(f"         Firmware: {os.path.basename(firmware)}")
    print(f"         PID: {qemu_proc.pid}")

    # Step 3: Wait for firmware initialization
    print()
    print("  [3/7] Waiting for firmware startup...")
    await asyncio.sleep(2.0)

    banner = e2e.cdc.get_output()
    print(f"         MMIO accesses: {e2e._access_count}")
    if banner:
        print(f"         Firmware output: {banner.strip()!r}")
    else:
        print(f"         (Firmware initialized, waiting for commands)")

    results = []

    # Step 4: PING test
    print()
    print("  [4/7] Sending command: PING")
    e2e.cdc.inject_command("PING")
    await asyncio.sleep(1.5)
    response = e2e.cdc.get_output()
    ping_ok = "PONG" in response
    print(f"         Response: {response.strip()!r}")
    print(f"         Result:   {'PASS' if ping_ok else 'FAIL'}")
    results.append(("PING → PONG", ping_ok))

    # Step 5: AES-128-ECB (NIST FIPS-197 vector)
    print()
    print("  [5/7] Sending command: AES128_ECB_ENC (NIST FIPS-197)")
    key = "2b7e151628aed2a6abf7158809cf4f3c"
    pt = "6bc1bee22e409f96e93d7e117393172a"
    expected_ct = "3ad77bb40d7a3660a89ecaf32466ef97"
    e2e.cdc.inject_command(f"AES128_ECB_ENC {key}{pt}")
    await asyncio.sleep(1.5)
    response = e2e.cdc.get_output()
    aes_ok = expected_ct in response.lower()
    print(f"         Key:      {key}")
    print(f"         Input:    {pt}")
    print(f"         Response: {response.strip()!r}")
    print(f"         Expected: {expected_ct}")
    print(f"         Result:   {'PASS' if aes_ok else 'FAIL'}")
    results.append(("AES-128-ECB encrypt (NIST)", aes_ok))

    # Step 6: SHA-256
    print()
    print("  [6/7] Sending command: SHA256('abc')")
    data_hex = "616263"
    expected_sha = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    e2e.cdc.inject_command(f"SHA256 {data_hex}")
    await asyncio.sleep(1.5)
    response = e2e.cdc.get_output()
    sha_ok = expected_sha in response.lower()
    print(f"         Input:    'abc' (hex: {data_hex})")
    print(f"         Response: {response.strip()!r}")
    print(f"         Expected: {expected_sha}")
    print(f"         Result:   {'PASS' if sha_ok else 'FAIL'}")
    results.append(("SHA-256 hash", sha_ok))

    # Step 7: Cleanup
    print()
    print("  [7/7] Cleanup...")
    qemu_proc.terminate()
    try:
        qemu_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        qemu_proc.kill()
        qemu_proc.wait(timeout=2)
    e2e.stop()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    print(f"         Total MMIO accesses handled: {e2e._access_count}")

    # Summary
    print()
    print("=" * 70)
    print("  Results")
    print("=" * 70)
    all_pass = True
    for name, ok in results:
        mark = "✓" if ok else "✗"
        print(f"    {mark} {name}")
        if not ok:
            all_pass = False

    print()
    if all_pass:
        print("  ALL TESTS PASSED - Python ↔ QEMU ↔ Firmware interaction verified!")
    else:
        print("  Some tests FAILED")
    print()
    return all_pass


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
