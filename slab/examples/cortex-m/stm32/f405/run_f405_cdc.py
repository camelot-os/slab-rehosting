#!/usr/bin/env python3
"""
STM32F405 CDC Example Runner

Runs STM32F4 CDC firmware using slab-cortex-m peripheral emulation.
This example works with the default QEMU memory layout (flash at 0x08000000).

Usage:
    python run_f405_cdc.py [--verbose] [--timeout 30]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import time
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path

# Add python path
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "python"))

from slab_stm32 import STM32F405PeripheralSet

# Paths
QEMU_BIN = PROJECT_DIR / "qemu" / "build" / "qemu-system-arm"
FIRMWARE = PROJECT_DIR / "tests" / "firmware" / "build" / "test_usb_cdc_crypto.bin"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('F405-CDC')


class F405EmulationServer:
    """TCP server handling QEMU peripheral requests."""

    def __init__(self, port: int = 5000, verbose: bool = False):
        self.port = port
        self.verbose = verbose
        self.peripherals = STM32F405PeripheralSet()
        self.running = False
        self.mmio_count = 0

        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)

        log.info(f"Created {self.peripherals.name} with {len(self.peripherals.peripherals)} peripherals")

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

                    value, status = self.peripherals.read(addr, size)
                    self.mmio_count += 1

                    if self.verbose:
                        log.debug(f"R 0x{addr:08X} -> 0x{value:08X}")

                    # Response: [value:4][status:1]
                    response = value.to_bytes(4, 'little') + bytes([status])
                    writer.write(response)

                elif cmd == ord('W') or cmd == ord('T'):  # Write or Secure Write
                    # Read value + security state: [value:4][security:1]
                    value_sec = await reader.read(5)
                    if len(value_sec) < 5:
                        break
                    value = int.from_bytes(value_sec[0:4], 'little')

                    status = self.peripherals.write(addr, size, value)
                    self.mmio_count += 1

                    if self.verbose:
                        log.debug(f"W 0x{addr:08X} <- 0x{value:08X}")

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


def run_qemu(firmware: Path, port: int) -> subprocess.Popen:
    """Launch QEMU with the F405 firmware."""

    if not QEMU_BIN.exists():
        log.error(f"QEMU not found: {QEMU_BIN}")
        sys.exit(1)

    if not firmware.exists():
        log.error(f"Firmware not found: {firmware}")
        sys.exit(1)

    # Build QEMU command
    cmd = [
        str(QEMU_BIN),
        "-M", "slab-cortex-m",
        "-cpu", "cortex-m4",
        "-nographic",
        "-serial", "stdio",
        "-kernel", str(firmware),
    ]

    log.info(f"Starting QEMU: {' '.join(cmd[:8])}...")
    log.debug(f"Full command: {' '.join(cmd)}")

    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )


async def main():
    parser = argparse.ArgumentParser(description='Run F405 CDC example')
    parser.add_argument('--port', '-p', type=int, default=5000, help='Peripheral server port')
    parser.add_argument('--timeout', '-t', type=int, default=30, help='Timeout in seconds')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--firmware', '-f', type=Path, default=FIRMWARE, help='Firmware path')
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("STM32F405 CDC Emulation")
    log.info("=" * 60)

    # Create peripheral server
    server = F405EmulationServer(port=args.port, verbose=args.verbose)

    # Start server task
    server_task = asyncio.create_task(server.run())

    # Wait for server to be ready
    await asyncio.sleep(0.5)

    # Launch QEMU
    qemu_proc = run_qemu(args.firmware, args.port)

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
