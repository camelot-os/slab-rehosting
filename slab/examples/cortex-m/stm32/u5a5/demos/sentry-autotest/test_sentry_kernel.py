#!/usr/bin/env python3
"""
E2E Test: Sentry Kernel boot on STM32U5A5 (Cortex-M33, PMSAv8)

Tests:
  1. Kernel boot: clock/GPIO/UART init, security manager, MPU init
  2. PMSAv8 MPU region verification against Python CortexMPU model
  3. Peripheral access distribution (RCC, PWR, GPIO, USART)

Architecture:
    QEMU slab-cortex-m (Cortex-M33)
      | TCP proxy protocol
    SentryPeripheralServer (STM32U5A5PeripheralSet)
      | PMSAv8 MPU verification (Python model)

Run:
    PYTHONPATH=slab/python python3 \
        slab/examples/cortex-m/stm32/u5a5/demos/sentry-autotest/test_sentry_kernel.py

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
from slab_peripherals.mpu import CortexMPU, MPUReg, AccessPermissionV8

# Protocol constants (match base_server.py / slab_cortex_m.c)
CMD_READ = ord('R')
CMD_READ_S = ord('S')
CMD_WRITE = ord('W')
CMD_WRITE_S = ord('T')
CMD_IRQ = ord('I')
CMD_CONFIG = ord('C')


# =============================================================================
# Peripheral Server
# =============================================================================

class SentryPeripheralServer:
    """Async TCP server for QEMU peripheral proxy."""

    def __init__(self, periph_port: int):
        self.periph_port = periph_port
        self.stm32 = STM32U5A5PeripheralSet()
        self._loop = None
        self._thread = None
        self._writer = None
        self._access_count = 0
        self._addr_counts = {}
        self.uart_output = bytearray()

    def _send_irq(self, irq_num: int, level: int):
        if self._writer:
            packet = struct.pack('<BIB', CMD_IRQ, irq_num, level)
            self._writer.write(packet)

    def start_threaded(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        time.sleep(0.3)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        tcp_server = await asyncio.start_server(
            self._handle_qemu_client, '127.0.0.1', self.periph_port)
        async with tcp_server:
            await asyncio.gather(tcp_server.serve_forever())

    async def _handle_qemu_client(self, reader, writer):
        self._writer = writer
        for p in self.stm32.peripherals:
            if hasattr(p, 'irq_callback'):
                p.irq_callback = self._send_irq
            if hasattr(p, 'name') and 'USART' in p.name and hasattr(p, 'on_tx'):
                buf = self.uart_output
                def make_hook(b=buf):
                    def hook(byte):
                        b.append(byte & 0xFF)
                        ch = byte & 0x7F
                        if 0x20 <= ch < 0x7F or ch in (0x0A, 0x0D):
                            sys.stdout.write(chr(ch))
                            sys.stdout.flush()
                    return hook
                p.on_tx = make_hook()

        try:
            while True:
                data = await reader.read(1)
                if not data:
                    break
                cmd = data[0]
                if cmd in (CMD_READ, CMD_READ_S):
                    payload = await reader.readexactly(13)
                    addr, size = struct.unpack('<II', payload[:8])
                    value = self._dispatch_read(addr, size)
                    writer.write(struct.pack('<IB', value, 0))
                    await writer.drain()
                    self._access_count += 1
                    self._addr_counts[addr] = self._addr_counts.get(addr, 0) + 1
                elif cmd in (CMD_WRITE, CMD_WRITE_S):
                    payload = await reader.readexactly(17)
                    addr, size, value = struct.unpack('<III', payload[:12])
                    self._dispatch_write(addr, size, value)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
                    self._access_count += 1
                    self._addr_counts[addr] = self._addr_counts.get(addr, 0) + 1
                elif cmd == CMD_CONFIG:
                    payload = await reader.readexactly(10)
                    writer.write(struct.pack('<IB', 0, 0))
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        finally:
            self._writer = None
            writer.close()

    def _dispatch_read(self, addr, size):
        periph = self.stm32.find_peripheral(addr)
        if periph:
            result = periph.read(addr, size)
            return result[0] if isinstance(result, tuple) else result
        return 0

    def _dispatch_write(self, addr, size, value):
        periph = self.stm32.find_peripheral(addr)
        if periph:
            periph.write(addr, size, value)

    def stop(self):
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


# =============================================================================
# PMSAv8 MPU Verification
# =============================================================================

# Sentry kernel MPU layout (from kernel/src/managers/memory/memory_mpu.c):
#
# mgr_mm_init() configures:
#   Region 0: Kernel TXT (code)  -- RO_PRIV, XN=0, AttrIdx=1 (Normal NC)
#   Region 1: Kernel DATA (ram)  -- RW_PRIV, XN=1, AttrIdx=1 (Normal NC)
#   MAIR: attr[0]=0x00 (Device-nGnRnE), attr[1]=0x44 (Normal NC)
#   CTRL: ENABLE | HFNMIENA | PRIVDEFENA
#
# After task switch (mgr_mm_map_task), additional regions:
#   Region 2: Task TXT   -- RO_ANY, XN=0
#   Region 3: Task DATA  -- RW_ANY, XN=1
#   Region 4-7: Task resources (devices, SHM)

# Memory layout from sentry DTS (nucleo_u5a5_autotest):
KERNEL_CODE_BASE = 0x08000000
KERNEL_CODE_SIZE = 0x8000   # 32KB (from mgr_mm_init)
KERNEL_DATA_BASE = 0x20000000
KERNEL_DATA_SIZE = 0x4000   # 16KB (from mgr_mm_init)


def verify_mpu_regions():
    """Configure Python CortexMPU with sentry kernel's expected regions
    and verify access control logic matches PMSAv8 semantics."""

    mpu = CortexMPU(num_regions=8, arch_v8m=True)
    results = []

    # -- Configure kernel regions (matching mgr_mm_init) ---------------------
    # MAIR: attr[0]=0x00 (Device), attr[1]=0x44 (Normal non-cacheable)
    mpu.write_register(MPUReg.MAIR0, 0x00004400)

    # Region 0: Kernel TXT (flash, 32KB)
    # RBAR: base=0x08000000, SH=0 (non-shareable), AP=10 (RO_PRIV), XN=0
    rbar0 = (KERNEL_CODE_BASE & 0xFFFFFFE0) | (0 << 3) | (0b10 << 1) | 0
    # RLAR: limit=0x08007FFF (base+32K-1), AttrIdx=1, EN=1
    rlar0 = ((KERNEL_CODE_BASE + KERNEL_CODE_SIZE - 1) & 0xFFFFFFE0) | (1 << 1) | 1
    mpu.write_register(MPUReg.RNR, 0)
    mpu.write_register(MPUReg.RBAR, rbar0)
    mpu.write_register(MPUReg.RLAR, rlar0)

    # Region 1: Kernel DATA (SRAM, 16KB)
    # RBAR: base=0x20000000, SH=0, AP=00 (RW_PRIV), XN=1
    rbar1 = (KERNEL_DATA_BASE & 0xFFFFFFE0) | (0 << 3) | (0b00 << 1) | 1
    # RLAR: limit=0x20003FFF, AttrIdx=1, EN=1
    rlar1 = ((KERNEL_DATA_BASE + KERNEL_DATA_SIZE - 1) & 0xFFFFFFE0) | (1 << 1) | 1
    mpu.write_register(MPUReg.RNR, 1)
    mpu.write_register(MPUReg.RBAR, rbar1)
    mpu.write_register(MPUReg.RLAR, rlar1)

    # Enable MPU with PRIVDEFENA
    mpu.write_register(MPUReg.CTRL, 0x07)  # ENABLE | HFNMIENA | PRIVDEFENA

    # -- Verify region configuration ----------------------------------------
    r0 = mpu.regions[0]
    r1 = mpu.regions[1]

    # Region 0: kernel code
    ok = r0.enabled and r0.base == KERNEL_CODE_BASE
    results.append(("Region 0 base correct", ok))

    ok = r0.ap == AccessPermissionV8.RO_PRIV and not r0.xn
    results.append(("Region 0 RO_PRIV + executable", ok))

    ok = r0.end == KERNEL_CODE_BASE + KERNEL_CODE_SIZE
    results.append(("Region 0 end correct", ok))

    # Region 1: kernel data
    ok = r1.enabled and r1.base == KERNEL_DATA_BASE
    results.append(("Region 1 base correct", ok))

    ok = r1.ap == AccessPermissionV8.RW_PRIV and r1.xn
    results.append(("Region 1 RW_PRIV + XN", ok))

    ok = r1.end == KERNEL_DATA_BASE + KERNEL_DATA_SIZE
    results.append(("Region 1 end correct", ok))

    # -- Verify access control ----------------------------------------------
    # Privileged read of kernel code: ALLOWED
    ok = mpu.check_access(0x08000100, 4, is_write=False, is_privileged=True)
    results.append(("Priv read kernel code: allowed", ok))

    # Privileged write to kernel code: DENIED (RO)
    ok = not mpu.check_access(0x08000100, 4, is_write=True, is_privileged=True)
    results.append(("Priv write kernel code: denied", ok))

    # Unprivileged read of kernel code: DENIED (PRIV only)
    ok = not mpu.check_access(0x08000100, 4, is_write=False, is_privileged=False)
    results.append(("Unpriv read kernel code: denied", ok))

    # Privileged RW to kernel data: ALLOWED
    ok = mpu.check_access(0x20000100, 4, is_write=True, is_privileged=True)
    results.append(("Priv write kernel data: allowed", ok))

    # Unprivileged write to kernel data: DENIED (PRIV only)
    ok = not mpu.check_access(0x20000100, 4, is_write=True, is_privileged=False)
    results.append(("Unpriv write kernel data: denied", ok))

    # Instruction fetch from kernel data: DENIED (XN)
    ok = not mpu.check_access(0x20000100, 4, is_write=False,
                               is_privileged=True, is_instruction=True)
    results.append(("Exec from kernel data: denied (XN)", ok))

    # Peripheral access (0x40020000 GPIO): ALLOWED via PRIVDEFENA
    ok = mpu.check_access(0x40020000, 4, is_write=True, is_privileged=True)
    results.append(("Priv peripheral access: PRIVDEFENA", ok))

    # Unprivileged peripheral access: DENIED (no region, no PRIVDEFENA)
    ok = not mpu.check_access(0x40020000, 4, is_write=True, is_privileged=False)
    results.append(("Unpriv peripheral access: denied", ok))

    # -- Dump regions -------------------------------------------------------
    regions = mpu.dump_regions()

    return mpu, regions, results


# =============================================================================
# E2E Test Runner
# =============================================================================

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run_e2e_test(verbose=False):
    """Run the Sentry kernel E2E test with MPU verification."""
    if verbose:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir,
                                                '..', '..', '..', '..', '..', '..', '..'))
    qemu = os.path.join(project_root, 'build', 'qemu-system-arm')
    firmware = os.path.join(test_dir, 'firmware.bin')

    if not os.path.exists(firmware):
        print(f"  ERROR: Firmware not found: {firmware}")
        return False
    if not os.path.exists(qemu):
        print(f"  ERROR: QEMU not found: {qemu}")
        return False

    periph_port = find_free_port()
    all_results = []

    # -- Step 1: PMSAv8 MPU verification (Python model) ---------------------
    print()
    print("=" * 70)
    print("  Sentry Kernel E2E -- STM32U5A5 (Cortex-M33, PMSAv8)")
    print("=" * 70)

    print()
    print("  [1/3] PMSAv8 MPU region verification...")
    mpu, regions, mpu_results = verify_mpu_regions()

    for name, ok in mpu_results:
        mark = "PASS" if ok else "FAIL"
        print(f"    [{mark}] {name}")
    all_results.extend(mpu_results)

    print()
    print("  MPU regions (sentry kernel layout):")
    for r in regions:
        print(f"    Region {r['index']}: {r['base']}-{r['end']} "
              f"({r['size']}) AP={r['ap']} XN={r['xn']} "
              f"SH={r.get('sh', '?')} AttrIdx={r.get('attr_idx', '?')}")

    stats = mpu.get_stats()
    print(f"    CTRL: enabled={stats['enabled']} "
          f"privdefena={stats['privdefena']} "
          f"regions={stats['active_regions']}/{stats['num_regions']}")

    # -- Step 2: Boot sentry firmware in QEMU -------------------------------
    print()
    print("  [2/3] Booting sentry kernel in QEMU...")
    server = SentryPeripheralServer(periph_port)
    server.start_threaded()
    print(f"         Peripherals: {len(server.stm32.peripherals)}")

    gdb_port = find_free_port()
    machine_props = (
        f"slab-cortex-m"
        f",cpu-type=cortex-m33"
        f",tcp-port={periph_port}"
        f",sram-size=0x270000"
        f",flash-size=0x400000"
        f",sysclk-hz=160000000"
        # STM32U5A5 has 8 MPU regions (QEMU M33 defaults to 16)
        f",mpu-regions=8"
        f",periph-base=0x0BFA0000"
        f",periph-size=0x54060000"
    )
    qemu_proc = subprocess.Popen(
        [qemu, '-M', machine_props, '-nographic',
         '-gdb', f'tcp::{gdb_port}', '-kernel', firmware],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    print(f"         PID: {qemu_proc.pid}, GDB: localhost:{gdb_port}")
    print("         Waiting for boot...")
    print()
    print("  --- UART output ---")

    # Wait for boot (up to 15s, exit early if MMIO stalls)
    n_prev = 0
    for t in range(15):
        time.sleep(1.0)
        n = server._access_count
        if t > 4 and n == n_prev:
            break
        n_prev = n

    print()
    print("  --- end UART ---")
    print()

    # -- Step 3: Verify boot results ----------------------------------------
    print("  [3/3] Boot verification...")

    uart_text = server.uart_output.decode('ascii', errors='replace')
    mmio_count = server._access_count

    # Check kernel reached security init
    boot_ok = "Starting Sentry kernel" in uart_text
    all_results.append(("Kernel boot banner", boot_ok))
    print(f"    [{'PASS' if boot_ok else 'FAIL'}] Kernel boot banner")

    # Check security manager init
    sec_ok = "mgr_security_init" in uart_text
    all_results.append(("Security manager init", sec_ok))
    print(f"    [{'PASS' if sec_ok else 'FAIL'}] Security manager init")

    # Check RNG init
    rng_ok = "RNG init done" in uart_text
    all_results.append(("RNG initialization", rng_ok))
    print(f"    [{'PASS' if rng_ok else 'FAIL'}] RNG initialization")

    # Check MMIO activity
    mmio_ok = mmio_count >= 100
    all_results.append((f"MMIO accesses >= 100 (got {mmio_count})", mmio_ok))
    print(f"    [{'PASS' if mmio_ok else 'FAIL'}] MMIO accesses >= 100 (got {mmio_count})")

    # Peripheral distribution
    sorted_addrs = sorted(server._addr_counts.items(), key=lambda x: -x[1])
    print()
    print(f"  Address distribution (top 10):")
    for addr, cnt in sorted_addrs[:10]:
        periph = server.stm32.find_peripheral(addr)
        name = periph.name if periph else "UNMAPPED"
        print(f"    0x{addr:08X} ({name:12s}): {cnt:5d}")

    # -- Cleanup ------------------------------------------------------------
    qemu_proc.terminate()
    try:
        qemu_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        qemu_proc.kill()
        qemu_proc.wait(timeout=2)

    if verbose:
        stderr = qemu_proc.stderr.read().decode(errors='replace')
        if stderr.strip():
            print(f"\n  QEMU stderr:\n{stderr[:500]}")

    server.stop()

    # -- Summary ------------------------------------------------------------
    print()
    print("=" * 70)
    print("  Results")
    print("=" * 70)
    n_pass = sum(1 for _, ok in all_results if ok)
    n_fail = sum(1 for _, ok in all_results if not ok)
    for name, ok in all_results:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")

    print()
    all_pass = all(ok for _, ok in all_results)
    if all_pass:
        print(f"  ALL {n_pass} TESTS PASSED")
    else:
        print(f"  {n_pass} passed, {n_fail} FAILED")
    print()
    return all_pass


if __name__ == "__main__":
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    success = run_e2e_test(verbose=verbose)
    sys.exit(0 if success else 1)
