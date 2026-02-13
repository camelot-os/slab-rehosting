#!/usr/bin/env python3
"""
Sentry Kernel U5A5 E2E runner with GDB, MMIO tracing, and live UART.

Usage:
    PYTHONPATH=slab/python python3 slab/tests/run_sentry_e2e.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import logging
import os
import signal
import socket
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "slab" / "python"))

from slab_cortex_m.board import load_board_config, get_qemu_cpu, get_default_clock
from slab_cortex_m.board_builder import build_board
from slab_cortex_m.base_server import BasePeripheralServer
from slab_cortex_m.mmio_tracer import MMIOTracer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S',
)
log = logging.getLogger('SentryE2E')

QEMU_BIN = Path(os.environ.get(
    "QEMU_BIN",
    str(PROJECT_ROOT / "build" / "qemu-system-arm"),
))
BOARD_YAML = Path(os.environ.get(
    "BOARD_YAML",
    str(PROJECT_ROOT / "slab" / "boards" / "stm32u5a5_sentry.yaml"),
))

SENTRY_BUILD = Path(os.environ.get(
    "SENTRY_BUILD",
    "/home/mre/projects/sentry-kernel/builddir",
))
KERNEL_HEX = SENTRY_BUILD / "kernel" / "sentry-kernel.hex"
IDLE_HEX = SENTRY_BUILD / "idle" / "idle.hex"
AUTOTEST_HEX = SENTRY_BUILD / "autotest" / "autotest.hex"

TIMEOUT = 30
GDB_PORT = 1234
TCP_PORT = 0  # auto


def parse_ihex(path: Path) -> list[tuple[int, bytes]]:
    """Parse Intel HEX file into a list of (address, data) segments."""
    segments: list[tuple[int, bytes]] = []
    base_addr = 0
    cur_addr = None
    cur_data = bytearray()

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line.startswith(':'):
            continue
        raw = bytes.fromhex(line[1:])
        byte_count = raw[0]
        addr16 = (raw[1] << 8) | raw[2]
        rec_type = raw[3]
        data = raw[4:4 + byte_count]

        if rec_type == 0x00:  # Data
            abs_addr = base_addr + addr16
            if cur_addr is not None and abs_addr == cur_addr + len(cur_data):
                cur_data.extend(data)
            else:
                if cur_data:
                    segments.append((cur_addr, bytes(cur_data)))
                cur_addr = abs_addr
                cur_data = bytearray(data)
        elif rec_type == 0x04:  # Extended Linear Address
            base_addr = ((data[0] << 8) | data[1]) << 16
        elif rec_type == 0x01:  # EOF
            break

    if cur_data:
        segments.append((cur_addr, bytes(cur_data)))
    return segments


def merge_hex_files(hex_files: list[Path], flash_base: int = 0x08000000,
                    flash_size: int = 0x400000) -> bytes:
    """Merge multiple Intel HEX files into a single flat binary for QEMU.

    Addresses are relative to flash_base. Only segments within the flash
    region are included (SRAM-resident sections like .svcexchange are
    skipped). Gaps are filled with 0xFF (erased flash). No external tools.
    """
    flash_end = flash_base + flash_size
    all_segments: list[tuple[int, bytes]] = []
    for hf in hex_files:
        if not hf.exists():
            continue
        segs = parse_ihex(hf)
        for addr, data in segs:
            if addr >= flash_base and addr + len(data) <= flash_end:
                log.info(f"  {hf.name}: {len(data)} bytes at {addr:#010x}")
                all_segments.append((addr, data))
            else:
                log.debug(f"  {hf.name}: skipping {len(data)} bytes at {addr:#010x} (outside flash)")

    if not all_segments:
        raise FileNotFoundError("No valid HEX data in flash range")

    max_end = max(a + len(d) for a, d in all_segments)
    size = max_end - flash_base
    data = bytearray(b'\xff' * size)
    for addr, seg_data in all_segments:
        offset = addr - flash_base
        data[offset:offset + len(seg_data)] = seg_data

    return bytes(data)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


# -- Live UART buffer --------------------------------------------------------

class LiveUartBuffer(bytearray):
    """bytearray that prints each byte to stdout as it arrives."""
    def append(self, byte):
        super().append(byte & 0xFF)
        ch = byte & 0x7F
        if 0x20 <= ch < 0x7F or ch in (0x0A, 0x0D, 0x09):
            sys.stdout.write(chr(ch))
            sys.stdout.flush()


# -- Server -------------------------------------------------------------------

class SentryBoardServer(BasePeripheralServer):
    def __init__(self, board, port):
        super().__init__(port)
        self.board = board
        self.board.irq_callback = self.send_irq
        self.mmio_count = 0

    def create_peripherals(self):
        pass

    def find_peripheral(self, addr):
        if self.board.contains(addr):
            self.mmio_count += 1
            return self.board
        return None


# -- Main ---------------------------------------------------------------------

async def main():
    if not KERNEL_HEX.exists():
        print(f"ERROR: Kernel HEX not found: {KERNEL_HEX}")
        print("Set SENTRY_BUILD env var or build sentry-kernel first.")
        sys.exit(1)
    if not QEMU_BIN.exists():
        print(f"ERROR: QEMU binary not found: {QEMU_BIN}")
        sys.exit(1)

    # -- Merge firmware from Intel HEX files ----------------------------------
    # Sentry builds kernel, idle task, and optional user tasks as separate
    # binaries with their own flash addresses. Merge via Intel HEX (no
    # external toolchain dependency like arm-none-eabi-objcopy).
    hex_files = [KERNEL_HEX, IDLE_HEX]
    if AUTOTEST_HEX.exists():
        hex_files.append(AUTOTEST_HEX)
    log.info("Merging Intel HEX files:")
    fw_data = merge_hex_files(hex_files)
    fw_path = Path('/tmp/sentry-combined.bin')
    fw_path.write_bytes(fw_data)
    log.info(f"Combined firmware: {len(fw_data)} bytes ({len(fw_data):#x})")

    # -- Build board ----------------------------------------------------------
    config = load_board_config(str(BOARD_YAML))
    board = build_board(config)

    # Replace uart_output with live buffer and re-wire on_tx
    board.uart_output = LiveUartBuffer()
    for p in board.adapter.peripherals:
        name = getattr(p, 'name', '')
        if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
            def make_handler(buf=board.uart_output):
                def handler(byte):
                    buf.append(byte & 0xFF)
                return handler
            p.on_tx = make_handler()

    cpu = get_qemu_cpu(config)
    clock = get_default_clock(config)

    # -- Server ---------------------------------------------------------------
    port = find_free_port() if TCP_PORT == 0 else TCP_PORT
    server = SentryBoardServer(board, port)
    server.running = True

    # Attach MMIO tracer
    tracer = MMIOTracer()
    server.tracer = tracer

    tcp_server = await asyncio.start_server(
        server.handle_client, '127.0.0.1', port, reuse_address=True)

    # -- QEMU command ---------------------------------------------------------
    machine_opts = f'slab-cortex-m,cpu-type={cpu},tcp-port={port}'
    if clock:
        machine_opts += f',sysclk-hz={clock}'
    for key, val in config.qemu_extra.items():
        machine_opts += f',{key}={val}'

    qemu_cmd = [
        str(QEMU_BIN),
        '-M', machine_opts,
        '-kernel', str(fw_path),
        '-nographic', '-monitor', 'none',
        '-gdb', f'tcp::{GDB_PORT}',
    ]

    print("=" * 72)
    print(f"  Sentry Kernel E2E -- STM32U5A5")
    hex_names = [h.name for h in hex_files if h.exists()]
    print(f"  HEX files: {', '.join(hex_names)}")
    print(f"  Combined : {fw_path} ({len(fw_data)} bytes)")
    print(f"  Board    : {BOARD_YAML.name}")
    print(f"  CPU      : {cpu} @ {clock // 1_000_000} MHz")
    print(f"  Periphs  : {len(board.adapter.peripherals)}")
    print(f"  TCP port : {port}")
    print(f"  GDB      : localhost:{GDB_PORT} (attach anytime)")
    print(f"  Timeout  : {TIMEOUT}s")
    print("=" * 72)
    print()

    # -- Launch QEMU ----------------------------------------------------------
    start = time.time()
    qemu = await asyncio.create_subprocess_exec(
        *qemu_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # -- Wait for timeout or exit ---------------------------------------------
    try:
        stdout, stderr = await asyncio.wait_for(
            qemu.communicate(), timeout=TIMEOUT)
        exit_code = qemu.returncode or 0
    except asyncio.TimeoutError:
        elapsed = time.time() - start
        print(f"\n\n--- Timeout after {elapsed:.1f}s, stopping QEMU ---")
        qemu.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(
                qemu.communicate(), timeout=3)
        except asyncio.TimeoutError:
            qemu.kill()
            await qemu.wait()
            stderr = b""
        exit_code = 124
    except KeyboardInterrupt:
        print("\n\n--- Interrupted, stopping QEMU ---")
        qemu.terminate()
        try:
            await asyncio.wait_for(qemu.communicate(), timeout=3)
        except (asyncio.TimeoutError, Exception):
            qemu.kill()
            await qemu.wait()
        exit_code = 130

    elapsed = time.time() - start

    # -- Cleanup server -------------------------------------------------------
    server.running = False
    tcp_server.close()
    await tcp_server.wait_closed()

    # -- Results --------------------------------------------------------------
    print()
    print("=" * 72)
    print(f"  Results")
    print("=" * 72)
    print(f"  Duration   : {elapsed:.1f}s")
    print(f"  MMIO ops   : {server.mmio_count}")
    print(f"  QEMU exit  : {exit_code}")
    print(f"  Trace len  : {len(tracer.traces)} entries")

    if stderr:
        stderr_text = stderr.decode('utf-8', errors='replace')[:500]
        if stderr_text.strip():
            print(f"  QEMU stderr: {stderr_text.strip()[:200]}")

    # UART output
    uart_text = board.uart_output.decode('ascii', errors='replace')
    if uart_text.strip():
        print(f"\n  UART output ({len(uart_text)} bytes):")
        for line in uart_text.strip().split('\n'):
            print(f"    | {line}")

    # -- Export MMIO trace ----------------------------------------------------
    log_dir = PROJECT_ROOT / "slab" / "tests" / "e2e_logs"
    log_dir.mkdir(exist_ok=True)

    mmio_file = log_dir / "sentry_u5a5_mmio.txt"
    tracer.export_text(str(mmio_file))
    print(f"\n  MMIO trace : {mmio_file}")

    json_file = log_dir / "sentry_u5a5_mmio.json"
    tracer.export_json(str(json_file))
    print(f"  MMIO json  : {json_file}")

    # Summary
    if tracer.traces:
        psummary = tracer.get_peripheral_summary()
        print(f"\n  Top peripherals accessed:")
        ranked = sorted(psummary.items(),
                        key=lambda x: x[1].get('reads', 0) + x[1].get('writes', 0),
                        reverse=True)
        for name, info in ranked[:15]:
            total = info.get('reads', 0) + info.get('writes', 0)
            top_reg = info.get('top_reg', '?')
            print(f"    {name:24s} {total:6d} ops  (top: {top_reg})")

    print()
    print("=" * 72)
    passed = server.mmio_count >= 10
    print(f"  {'PASS' if passed else 'FAIL'} -- {server.mmio_count} MMIO transactions")
    print("=" * 72)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
