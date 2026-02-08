#!/usr/bin/env python3
"""
STM32H563 TrustZone Example Runner

Runs the H563 TrustZone CDC firmware using slab-cortex-m peripheral emulation.

IMPORTANT: The current slab-cortex-m QEMU machine defaults to 0x08000000 for flash,
but H563 TrustZone firmware is compiled for 0x0C000000. This requires either:
1. Modifying QEMU slab-cortex-m to expose flash_base as a property
2. Recompiling the firmware for 0x08000000

For STM32F4 firmware (compiled for 0x08000000), the machine works correctly.
See tests/firmware/examples/ for working F4 examples.

Memory Map (TrustZone):
    Secure Flash:     0x0C000000 - 0x0C03FFFF (256KB)
    NSC Flash:        0x0C040000 - 0x0C041FFF (8KB)
    Secure SRAM:      0x30000000 - 0x3001FFFF (128KB)
    Non-Secure Flash: 0x08042000 - 0x081FFFFF (~1.75MB)
    Non-Secure SRAM:  0x20020000 - 0x2009FFFF (512KB)

Usage:
    python run_h563_tz.py [--secure-only] [--verbose] [--timeout 30]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import time
import signal
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path

# Add python path
SCRIPT_DIR = Path(__file__).parent
# examples/cortex-m/stm32/h563/ -> 4 levels up to project root
PROJECT_DIR = SCRIPT_DIR.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "python"))

from slab_stm32 import STM32H563PeripheralSet

# Paths
QEMU_BIN = PROJECT_DIR / "build" / "qemu-system-arm"
SECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "secure_fw.bin"
NONSECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "nonsecure_fw.bin"

# Memory map
SECURE_FLASH_BASE = 0x0C000000
SECURE_FLASH_SIZE = 256 * 1024
NSC_FLASH_BASE = 0x0C040000
NSC_FLASH_SIZE = 8 * 1024
SECURE_SRAM_BASE = 0x30000000
SECURE_SRAM_SIZE = 128 * 1024

NS_FLASH_BASE = 0x08042000
NS_FLASH_SIZE = 1784 * 1024
NS_SRAM_BASE = 0x20020000
NS_SRAM_SIZE = 512 * 1024

# TrustZone address translation
SECURE_PERIPH_OFFSET = 0x10000000  # Secure alias = NS + 0x10000000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('H563-TZ')


class F4RCCStub:
    """Stub for STM32F4 RCC registers that QEMU might poll during init."""
    # RCC_CR bits
    HSION = (1 << 0)
    HSIRDY = (1 << 1)
    HSEON = (1 << 16)
    HSERDY = (1 << 17)
    PLLON = (1 << 24)
    PLLRDY = (1 << 25)
    # RCC_CSR bits
    LSIRDY = (1 << 1)

    def __init__(self, base: int = 0x40023800):
        self.base = base
        self.size = 0x100
        # Pre-populate registers with "clocks ON and ready" values
        self.regs = {
            0x00: (self.HSION | self.HSIRDY |
                   self.HSEON | self.HSERDY |
                   self.PLLON | self.PLLRDY),  # RCC_CR: all clocks on & ready
            0x08: 0x00000002,  # RCC_CFGR: PLL as system clock
            0x50: 0x00000000,  # RCC_BDCR
            0x74: self.LSIRDY | (1 << 24),  # RCC_CSR: LSI ready + reset flag
        }

    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size

    def read(self, addr: int, size: int) -> tuple:
        offset = addr - self.base
        return (self.regs.get(offset, 0), 0)

    def write(self, addr: int, size: int, value: int) -> int:
        offset = addr - self.base
        self.regs[offset] = value
        return 0


class H563EmulationServer:
    """TCP server handling QEMU peripheral requests."""

    def __init__(self, port: int = 5000, verbose: bool = False):
        self.port = port
        self.verbose = verbose
        self.peripherals = STM32H563PeripheralSet()
        self.running = False
        self.mmio_count = 0
        # Add stub for F4-style RCC that QEMU may access during init
        self.f4_rcc_stub = F4RCCStub()

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        log.info(f"Created {self.peripherals.name} with {len(self.peripherals.peripherals)} peripherals")

    def _translate_addr(self, addr: int) -> int:
        """Translate secure alias (0x5xxxxxxx) to non-secure (0x4xxxxxxx)."""
        if (addr & 0xF0000000) == 0x50000000:
            return addr - SECURE_PERIPH_OFFSET
        return addr

    def _do_read(self, addr: int, size: int) -> tuple:
        """Perform read, checking stubs first."""
        # Check F4 RCC stub first (for QEMU init compatibility)
        if self.f4_rcc_stub.contains(addr):
            return self.f4_rcc_stub.read(addr, size)
        ns_addr = self._translate_addr(addr)
        return self.peripherals.read(ns_addr, size)

    def _do_write(self, addr: int, size: int, value: int) -> int:
        """Perform write, checking stubs first."""
        if self.f4_rcc_stub.contains(addr):
            return self.f4_rcc_stub.write(addr, size, value)
        ns_addr = self._translate_addr(addr)
        return self.peripherals.write(ns_addr, size, value)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle QEMU client connection.

        Protocol from QEMU slab_cortexm.c:
        - Read:  [cmd:1][addr:4][size:4][security:1] = 10 bytes
        - Write: [cmd:1][addr:4][size:4][value:4][security:1] = 14 bytes
        Response: [value:4][status:1] for reads, [status:1] for writes
        """
        peer = writer.get_extra_info('peername')
        log.info(f"QEMU connected from {peer}")

        try:
            while self.running:
                # Read command header: [cmd:1][addr:4][size:4]
                header = await reader.read(9)
                if len(header) < 9:
                    break

                cmd = header[0]
                addr = int.from_bytes(header[1:5], 'little')
                size = int.from_bytes(header[5:9], 'little')

                if cmd == ord('R') or cmd == ord('S'):  # Read or Secure Read
                    # Read security state byte
                    sec_byte = await reader.read(1)
                    if len(sec_byte) < 1:
                        break

                    value, status = self._do_read(addr, size)
                    self.mmio_count += 1

                    cmd_name = 'SR' if cmd == ord('S') else 'R'
                    if self.verbose:
                        log.debug(f"{cmd_name} 0x{addr:08X} -> 0x{value:08X}")

                    # Response: [value:4][status:1]
                    response = value.to_bytes(4, 'little') + bytes([status])
                    writer.write(response)

                elif cmd == ord('W') or cmd == ord('T'):  # Write or Secure Write
                    # Read value + security state: [value:4][security:1]
                    value_sec = await reader.read(5)
                    if len(value_sec) < 5:
                        break
                    value = int.from_bytes(value_sec[0:4], 'little')

                    status = self._do_write(addr, size, value)
                    self.mmio_count += 1

                    cmd_name = 'SW' if cmd == ord('T') else 'W'
                    if self.verbose:
                        log.debug(f"{cmd_name} 0x{addr:08X} <- 0x{value:08X}")

                    # Response: [status:1]
                    writer.write(bytes([status]))

                await writer.drain()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error(f"Client error: {e}")
        finally:
            log.info(f"QEMU disconnected ({self.mmio_count} MMIO operations)")
            writer.close()

    async def run(self):
        """Start the peripheral server."""
        self.running = True
        server = await asyncio.start_server(
            self.handle_client, '127.0.0.1', self.port
        )
        log.info(f"Peripheral server listening on port {self.port}")

        async with server:
            await server.serve_forever()


def run_qemu(secure_fw: Path, nonsecure_fw: Path, port: int, timeout: int) -> subprocess.Popen:
    """Launch QEMU with the H563 TrustZone firmware."""

    if not QEMU_BIN.exists():
        log.error(f"QEMU not found: {QEMU_BIN}")
        sys.exit(1)

    if not secure_fw.exists():
        log.error(f"Secure firmware not found: {secure_fw}")
        sys.exit(1)

    # Build QEMU command with H5 TrustZone memory layout
    # - flash-base=0x0C000000: Secure flash alias for STM32H5
    # - sram-base=0x30000000: Secure SRAM alias for STM32H5
    # - trustzone=on: Enable ARMv8-M TrustZone (required for H5 secure firmware)
    cmd = [
        str(QEMU_BIN),
        "-M", (f"slab-cortex-m"
               f",cpu-type=cortex-m33"
               f",tcp-port={port}"
               f",flash-base=0x{SECURE_FLASH_BASE:08X}"
               f",sram-base=0x{SECURE_SRAM_BASE:08X}"
               f",sram-size=0x{SECURE_SRAM_SIZE:X}"
               f",trustzone=on"
               f",sysclk-hz=250000000"
               f",ns-flash-base=0x08040000"
               f",ns-flash-size=0x1C0000"),
        "-nographic", "-monitor", "none",
        "-kernel", str(secure_fw),
    ]

    # Load non-secure firmware into NS flash region
    if nonsecure_fw and nonsecure_fw.exists():
        cmd.extend([
            "-device", f"loader,file={nonsecure_fw},addr=0x{NS_FLASH_BASE:08X},force-raw=on",
        ])

    log.info(f"Starting QEMU: {' '.join(cmd[:10])}...")
    log.debug(f"Full command: {' '.join(cmd)}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Combine stderr with stdout
        text=True
    )
    return proc


async def main():
    parser = argparse.ArgumentParser(description='Run H563 TrustZone example')
    parser.add_argument('--port', '-p', type=int, default=5000, help='Peripheral server port')
    parser.add_argument('--timeout', '-t', type=int, default=30, help='Timeout in seconds')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--secure-only', '-s', action='store_true', help='Run secure firmware only')
    parser.add_argument('--secure-fw', type=Path, default=SECURE_FW, help='Secure firmware path')
    parser.add_argument('--nonsecure-fw', type=Path, default=NONSECURE_FW, help='Non-secure firmware path')
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("STM32H563 TrustZone Emulation")
    log.info("=" * 60)

    # Create peripheral server
    server = H563EmulationServer(port=args.port, verbose=args.verbose)

    # Start server task
    server_task = asyncio.create_task(server.run())

    # Wait for server to be ready
    await asyncio.sleep(0.5)

    # Launch QEMU
    nonsecure = None if args.secure_only else args.nonsecure_fw
    qemu_proc = run_qemu(args.secure_fw, nonsecure, args.port, args.timeout)

    try:
        # Wait for timeout or completion
        start = time.time()
        while time.time() - start < args.timeout:
            if qemu_proc.poll() is not None:
                break
            await asyncio.sleep(0.1)

            # Print QEMU output
            if qemu_proc.stdout:
                try:
                    line = qemu_proc.stdout.readline()
                    if line:
                        print(f"[QEMU] {line.rstrip()}")
                except:
                    pass

        if qemu_proc.poll() is None:
            log.warning(f"Timeout after {args.timeout}s, terminating QEMU")
            qemu_proc.terminate()
            qemu_proc.wait(timeout=5)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
        qemu_proc.terminate()
    finally:
        server.running = False
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    # Print summary
    log.info("=" * 60)
    log.info(f"MMIO Operations: {server.mmio_count}")
    log.info(f"QEMU Exit Code: {qemu_proc.returncode}")
    log.info("=" * 60)

    return 0 if qemu_proc.returncode == 0 else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
