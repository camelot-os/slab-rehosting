#!/usr/bin/env python3
"""
STM32H563 TrustZone Example Runner

Runs the H563 TrustZone CDC firmware using the slab board infrastructure:
- Loads both Secure (0x0C000000) and Non-Secure (0x08042000) firmware images
- Uses full STM32H563 peripheral set (62 peripherals) via board builder
- Captures UART output from firmware boot messages
- Tracks LED state changes and MMIO activity
- Supports MMIO tracing for detailed peripheral analysis

Memory Map (TrustZone):
    Secure Flash:     0x0C000000 - 0x0C03FFFF (256KB)
    NSC Flash:        0x0C040000 - 0x0C041FFF (8KB)
    Secure SRAM:      0x30000000 - 0x3004FFFF (320KB)
    Non-Secure Flash: 0x08042000 - 0x081FFFFF (~1.75MB)
    Non-Secure SRAM:  0x20020000 - 0x2009FFFF (512KB)

Usage:
    python run_h563_tz.py [--secure-only] [--verbose] [--timeout 30] [--trace]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import time
import asyncio
import logging
import argparse
from pathlib import Path

# Add python path
SCRIPT_DIR = Path(__file__).parent
# slab/examples/cortex-m/stm32/h563/ -> 4 levels up to slab/
SLAB_DIR = SCRIPT_DIR.parent.parent.parent.parent
PROJECT_DIR = SLAB_DIR.parent  # Repository root
sys.path.insert(0, str(SLAB_DIR / "python"))

from slab_cortex_m.base_server import BasePeripheralServer
from slab_cortex_m.board import load_board_config, MCU_REGISTRY
from slab_cortex_m.board_builder import build_board
from slab_cortex_m.mmio_tracer import MMIOTracer

# Paths
QEMU_BIN = PROJECT_DIR / "build" / "qemu-system-arm"
BOARD_YAML = SLAB_DIR / "boards" / "stm32h563_tz.yaml"
SECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "secure_fw.bin"
NONSECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "nonsecure_fw.bin"

# Non-Secure firmware load address
NS_FLASH_BASE = 0x08042000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('H563-TZ')


class BoardServer(BasePeripheralServer):
    """TCP server wrapping a Board from the board builder."""

    def __init__(self, board, port: int):
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


async def main():
    parser = argparse.ArgumentParser(description='Run H563 TrustZone example')
    parser.add_argument('--port', '-p', type=int, default=5555,
                        help='Peripheral server port (default: 5555)')
    parser.add_argument('--timeout', '-t', type=int, default=30,
                        help='Timeout in seconds (default: 30)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    parser.add_argument('--secure-only', '-s', action='store_true',
                        help='Run secure firmware only (no NS image)')
    parser.add_argument('--trace', action='store_true',
                        help='Enable MMIO tracing')
    parser.add_argument('--secure-fw', type=Path, default=SECURE_FW,
                        help='Secure firmware path')
    parser.add_argument('--nonsecure-fw', type=Path, default=NONSECURE_FW,
                        help='Non-secure firmware path')
    parser.add_argument('--board', type=Path, default=BOARD_YAML,
                        help='Board YAML configuration')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=" * 60)
    log.info("STM32H563 TrustZone Emulation")
    log.info("=" * 60)

    # Validate inputs
    if not QEMU_BIN.exists():
        log.error(f"QEMU not found: {QEMU_BIN}")
        return 1
    if not args.secure_fw.exists():
        log.error(f"Secure firmware not found: {args.secure_fw}")
        return 1
    if not args.board.exists():
        log.error(f"Board config not found: {args.board}")
        return 1

    # Load board configuration and build peripheral set
    board_config = load_board_config(str(args.board))
    board = build_board(board_config)
    log.info(f"Board '{board.name}': {len(board.adapter.peripherals)} peripherals")

    # Create server
    server = BoardServer(board, args.port)

    # Optionally attach MMIO tracer
    tracer = None
    if args.trace:
        tracer = MMIOTracer()
        server.tracer = tracer
        log.info("MMIO tracing enabled")

    # Start TCP server
    server.running = True
    tcp_server = await asyncio.start_server(
        server.handle_client, '127.0.0.1', args.port, reuse_address=True)
    log.info(f"Peripheral server listening on port {args.port}")

    # Determine CPU type from MCU registry
    mcu_info = MCU_REGISTRY.get(board_config.mcu)
    cpu = board_config.qemu_cpu or (mcu_info[2] if mcu_info else 'cortex-m33')

    # Build QEMU command
    machine_opts = f'slab-cortex-m,cpu-type={cpu},tcp-port={args.port}'
    for k, v in board_config.qemu_extra.items():
        machine_opts += f',{k}={v}'

    qemu_cmd = [
        str(QEMU_BIN),
        '-M', machine_opts,
        '-kernel', str(args.secure_fw),
        '-nographic', '-monitor', 'none',
    ]

    # Load non-secure firmware into NS flash region
    ns_fw = None if args.secure_only else args.nonsecure_fw
    if ns_fw and ns_fw.exists():
        qemu_cmd.extend([
            '-device', f'loader,file={ns_fw},addr=0x{NS_FLASH_BASE:08X},force-raw=on',
        ])
        log.info(f"NS firmware: {ns_fw.name} @ 0x{NS_FLASH_BASE:08X}")
    elif not args.secure_only:
        log.warning(f"NS firmware not found: {args.nonsecure_fw}")

    log.info(f"Secure firmware: {args.secure_fw.name}")
    log.info(f"QEMU: {' '.join(qemu_cmd[:6])}...")

    # Launch QEMU as async subprocess
    qemu = await asyncio.create_subprocess_exec(
        *qemu_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    log.info(f"QEMU started (PID {qemu.pid})")

    # Wait for completion or timeout
    start = time.time()
    try:
        stdout, stderr = await asyncio.wait_for(
            qemu.communicate(), timeout=args.timeout)
        qemu_exit = qemu.returncode or 0
    except asyncio.TimeoutError:
        log.info(f"Timeout after {args.timeout}s, stopping QEMU")
        qemu.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(
                qemu.communicate(), timeout=3)
        except asyncio.TimeoutError:
            qemu.kill()
            await qemu.wait()
            stdout, stderr = b'', b''
        qemu_exit = 124  # timeout (expected for firmware that runs forever)

    duration = time.time() - start

    # Stop server
    server.running = False
    tcp_server.close()
    await tcp_server.wait_closed()

    # Print QEMU stderr if any
    if stderr:
        for line in stderr.decode('utf-8', errors='replace').strip().split('\n'):
            if line.strip():
                log.debug(f"[QEMU] {line.rstrip()}")

    # Collect UART output
    uart_text = ""
    if board.uart_output:
        uart_text = board.uart_output.decode('ascii', errors='replace')

    # Print results
    log.info("=" * 60)
    log.info("RESULTS")
    log.info("=" * 60)
    log.info(f"Duration:        {duration:.1f}s")
    log.info(f"QEMU Exit Code:  {qemu_exit}")
    log.info(f"MMIO Operations: {server.mmio_count}")
    log.info(f"LED States:      {dict(board.led_states)}")

    if uart_text:
        log.info("UART Output:")
        for line in uart_text.strip().split('\n'):
            log.info(f"  > {line}")
    else:
        log.info("UART Output:     (none)")

    # MMIO trace summary
    if tracer and tracer.traces:
        log.info(f"MMIO Trace:      {tracer.count} entries")
        summary = tracer.get_peripheral_summary()
        total_r = sum(v['reads'] for v in summary.values())
        total_w = sum(v['writes'] for v in summary.values())
        log.info(f"  Reads:  {total_r}")
        log.info(f"  Writes: {total_w}")
        log.info(f"  Peripherals accessed: {len(summary)}")

    # Assertions
    log.info("-" * 60)
    passed = True
    errors = []

    # 1. No crash
    if qemu_exit in (0, 124, 143):
        log.info("[PASS] no_crash: QEMU exit code %d", qemu_exit)
    else:
        log.error("[FAIL] no_crash: QEMU exit code %d", qemu_exit)
        passed = False
        errors.append(f"QEMU crashed with exit code {qemu_exit}")

    # 2. Minimum MMIO activity (firmware reached peripheral init)
    min_mmio = 50
    if server.mmio_count >= min_mmio:
        log.info("[PASS] mmio_count: %d >= %d", server.mmio_count, min_mmio)
    else:
        log.error("[FAIL] mmio_count: %d < %d (firmware may not have booted)",
                  server.mmio_count, min_mmio)
        passed = False
        errors.append(f"Only {server.mmio_count} MMIO ops (expected >= {min_mmio})")

    # 3. UART boot messages (secure firmware prints boot status)
    expected_uart = ["TrustZone Boot", "SAU configured"]
    for expected in expected_uart:
        if expected in uart_text:
            log.info("[PASS] uart_contains: '%s'", expected)
        else:
            log.error("[FAIL] uart_contains: '%s' not found in UART output", expected)
            passed = False
            errors.append(f"Missing UART message: '{expected}'")

    log.info("=" * 60)
    if passed:
        log.info("VERDICT: PASS")
    else:
        log.error("VERDICT: FAIL")
        for err in errors:
            log.error(f"  - {err}")
    log.info("=" * 60)

    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
