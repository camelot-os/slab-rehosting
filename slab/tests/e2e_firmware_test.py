#!/usr/bin/env python3
"""
End-to-End Firmware Emulation Test Suite

Runs all available firmware binaries with QEMU + Python peripheral servers
and reports results. Tests both legacy mode (MCUemuServer built-in peripherals)
and board mode (rich PeripheralSet via board YAML).

Usage:
    PYTHONPATH=slab/python python3 slab/tests/e2e_firmware_test.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import logging
import os
import signal
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "slab" / "python"))

from slab_cortex_m.base_server import BasePeripheralServer, STATUS_OK
from slab_cortex_m.mmio_tracer import MMIOTracer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('E2E')

QEMU_BIN = PROJECT_ROOT / "build" / "qemu-system-arm"


# =============================================================================
# DATA
# =============================================================================

@dataclass
class TestCase:
    name: str
    firmware: str          # Relative to PROJECT_ROOT
    cpu: str               # cortex-m0, m3, m4, m7, m33
    mode: str              # "legacy", "board", "direct"
    board_yaml: str = ""   # For board mode
    mcu: str = ""          # For direct mode (peripheral set)
    timeout: int = 8
    expect_mmio: int = 10  # Minimum MMIO ops to consider "alive"
    known_issue: str = ""  # Non-empty = expected failure, skip pass/fail
    qemu_extra: dict = field(default_factory=dict)  # Extra -M props (flash-base etc)


@dataclass
class TestResult:
    name: str
    passed: bool
    mmio_count: int = 0
    duration: float = 0.0
    qemu_exit: int = -1
    error: str = ""
    qemu_stderr: str = ""
    device_transactions: int = 0
    uart_output: str = ""
    tracer: Optional[MMIOTracer] = None


# =============================================================================
# GENERIC SERVER (works with any PeripheralSet)
# =============================================================================

class DirectServer(BasePeripheralServer):
    """Server using a PeripheralSet directly (for non-board-mode tests)."""

    def __init__(self, pset, port):
        super().__init__(port)
        self.pset = pset
        self.mmio_count = 0

    def create_peripherals(self):
        pass

    def find_peripheral(self, addr):
        if hasattr(self.pset, 'find_peripheral'):
            p = self.pset.find_peripheral(addr)
        elif hasattr(self.pset, 'get_by_address'):
            p = self.pset.get_by_address(addr)
        else:
            p = None
            if hasattr(self.pset, 'peripherals'):
                for pp in self.pset.peripherals:
                    if hasattr(pp, 'contains') and pp.contains(addr):
                        p = pp
                        break
        if p is not None:
            self.mmio_count += 1
            return self  # Return self as proxy
        return None

    def read(self, addr, size, secure=True):
        result = self.pset.read(addr, size)
        if isinstance(result, tuple):
            return result
        return (result if isinstance(result, int) else 0, STATUS_OK)

    def write(self, addr, size, value, secure=True):
        result = self.pset.write(addr, size, value)
        if isinstance(result, int):
            return result
        return STATUS_OK

    def contains(self, addr):
        return self.find_peripheral(addr) is not None


class BoardModeServer(BasePeripheralServer):
    """Server using Board builder (rich peripheral set from YAML)."""

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


# =============================================================================
# TEST RUNNER
# =============================================================================

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


async def run_one_test(tc: TestCase) -> TestResult:
    """Run a single firmware E2E test."""
    result = TestResult(name=tc.name, passed=False)
    start = time.time()
    fw_path = PROJECT_ROOT / tc.firmware

    if not fw_path.exists():
        result.error = f"Firmware not found: {tc.firmware}"
        return result

    port = find_free_port()

    # Create server
    try:
        if tc.mode == "board":
            from slab_cortex_m.board import load_board_config
            from slab_cortex_m.board_builder import build_board
            board_config = load_board_config(str(PROJECT_ROOT / tc.board_yaml))
            board = build_board(board_config)
            server = BoardModeServer(board, port)

        elif tc.mode == "direct":
            from slab_cortex_m.board import BoardConfig, create_peripheral_set
            config = BoardConfig(name=tc.name, mcu=tc.mcu)
            pset = create_peripheral_set(config)
            server = DirectServer(pset, port)

        else:  # legacy
            from slab_cortex_m.mcuemu_server import MCUemuServer, DEFAULT_CONFIG
            server = MCUemuServer(port, DEFAULT_CONFIG)
            server.create_peripherals()
            server.mmio_count = 0
            # Monkey-patch to count MMIO
            orig_find = server.find_peripheral
            def counting_find(addr):
                p = orig_find(addr)
                if p is not None:
                    server.mmio_count += 1
                return p
            server.find_peripheral = counting_find

    except Exception as e:
        result.error = f"Server creation failed: {e}"
        result.duration = time.time() - start
        return result

    # Attach MMIO tracer
    tracer = MMIOTracer()
    server.tracer = tracer

    # Start TCP server
    server.running = True
    tcp_server = await asyncio.start_server(
        server.handle_client, '127.0.0.1', port, reuse_address=True)

    # Build QEMU command
    machine_opts = f'slab-cortex-m,cpu-type={tc.cpu},tcp-port={port}'
    for key, val in tc.qemu_extra.items():
        machine_opts += f',{key}={val}'
    qemu_cmd = [
        str(QEMU_BIN),
        '-M', machine_opts,
        '-kernel', str(fw_path),
        '-nographic', '-monitor', 'none',
    ]

    # Launch QEMU
    try:
        qemu = await asyncio.create_subprocess_exec(
            *qemu_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        result.error = f"QEMU launch failed: {e}"
        tcp_server.close()
        await tcp_server.wait_closed()
        result.duration = time.time() - start
        return result

    # Wait for completion or timeout
    try:
        stdout, stderr = await asyncio.wait_for(
            qemu.communicate(), timeout=tc.timeout)
        result.qemu_exit = qemu.returncode or 0
        if stderr:
            result.qemu_stderr = stderr.decode('utf-8', errors='replace')[:500]
    except asyncio.TimeoutError:
        qemu.terminate()
        try:
            stdout, stderr = await asyncio.wait_for(
                qemu.communicate(), timeout=3)
            if stderr:
                result.qemu_stderr = stderr.decode('utf-8', errors='replace')[:500]
        except asyncio.TimeoutError:
            qemu.kill()
            await qemu.wait()
        result.qemu_exit = 124  # timeout

    # Collect results
    result.mmio_count = getattr(server, 'mmio_count', 0)
    result.duration = time.time() - start
    result.tracer = tracer

    # Collect device transaction data for board-mode tests
    if tc.mode == "board" and hasattr(server, 'board'):
        board = server.board
        # Count external device transactions
        txn_count = 0
        for dev in board.external_devices:
            if hasattr(dev, '_transactions'):
                txn_count += len(dev._transactions)
        result.device_transactions = txn_count
        # Capture UART output
        if board.uart_output:
            result.uart_output = board.uart_output.decode('ascii', errors='replace')

    # Determine pass/fail
    if tc.known_issue:
        result.passed = False
        result.error = f"KNOWN: {tc.known_issue}"
    elif result.mmio_count >= tc.expect_mmio:
        result.passed = True
    elif result.error:
        result.passed = False
    else:
        result.error = f"Only {result.mmio_count} MMIO ops (expected >= {tc.expect_mmio})"

    # Cleanup
    server.running = False
    tcp_server.close()
    await tcp_server.wait_closed()

    return result


# =============================================================================
# TEST CASES
# =============================================================================

def build_test_cases() -> List[TestCase]:
    tests = []

    # -- STM32F405 HelloBlink (legacy mode) --
    tests.append(TestCase(
        name="STM32F405 HelloBlink [legacy]",
        firmware="slab/examples/cortex-m/stm32/f405/demos/hello_blink/build/HelloBlink.bin",
        cpu="cortex-m4", mode="legacy", timeout=6, expect_mmio=50,
    ))

    # -- STM32F405 HelloBlink (board mode) --
    tests.append(TestCase(
        name="STM32F405 HelloBlink [board]",
        firmware="slab/examples/cortex-m/stm32/f405/demos/hello_blink/build/HelloBlink.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f405_hello_blink.yaml",
        timeout=6, expect_mmio=50,
    ))

    # -- STM32F405 HelloBlinkUart (legacy) --
    tests.append(TestCase(
        name="STM32F405 HelloBlinkUart [legacy]",
        firmware="slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin",
        cpu="cortex-m4", mode="legacy", timeout=6, expect_mmio=50,
    ))

    # -- STM32F405 HelloBlinkUart (board mode) --
    tests.append(TestCase(
        name="STM32F405 HelloBlinkUart [board]",
        firmware="slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f405_hello_blink.yaml",
        timeout=6, expect_mmio=50,
    ))

    # -- STM32F405 Peripheral Tests (direct mode) --
    # These CDC-based test firmwares spin on SPI/I2C status flags; they
    # boot and do RCC init but get stuck waiting for peripheral readiness.
    # Still useful to verify they don't crash and do some MMIO.
    tests.append(TestCase(
        name="STM32F405 SPI Flash Test [direct]",
        firmware="slab/examples/cortex-m/stm32/f405/peripherals/spi_flash/spi_flash_test.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32F405",
        timeout=6, expect_mmio=3,
    ))

    tests.append(TestCase(
        name="STM32F405 I2C EEPROM Test [direct]",
        firmware="slab/examples/cortex-m/stm32/f405/peripherals/i2c_eeprom/i2c_eeprom_test.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32F405",
        timeout=6, expect_mmio=3,
    ))

    tests.append(TestCase(
        name="STM32F405 SPI LCD Test [direct]",
        firmware="slab/examples/cortex-m/stm32/f405/peripherals/spi_lcd/spi_lcd_test.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32F405",
        timeout=6, expect_mmio=3,
    ))

    # -- STM32F405 SPI Flash (board mode with W25Q128) --
    tests.append(TestCase(
        name="STM32F405 SPI Flash [board]",
        firmware="slab/examples/cortex-m/stm32/f405/peripherals/spi_flash/spi_flash_test.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f405_spi_flash.yaml",
        timeout=6, expect_mmio=3,
    ))

    # -- STM32F439 Tests (direct mode with F439 peripherals) --
    tests.append(TestCase(
        name="STM32F439 Crypto CDC [direct]",
        firmware="slab/examples/cortex-m/stm32/f439/usb/crypto_cdc/stm32_crypto_cdc.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32F439",
        timeout=6, expect_mmio=10,
    ))

    tests.append(TestCase(
        name="STM32F439 DMA Flash [direct]",
        firmware="slab/examples/cortex-m/stm32/f439/peripherals/dma_flash/stm32f439_dma_flash_test.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32F439",
        timeout=6, expect_mmio=3,
    ))

    tests.append(TestCase(
        name="STM32F439 RTC [direct]",
        firmware="slab/examples/cortex-m/stm32/f439/peripherals/rtc/stm32f439_rtc_test.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32F439",
        timeout=6, expect_mmio=3,
    ))

    # -- STM32F439 Board mode tests --
    tests.append(TestCase(
        name="STM32F439 Crypto CDC [board]",
        firmware="slab/examples/cortex-m/stm32/f439/usb/crypto_cdc/stm32_crypto_cdc.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f439_crypto_cdc.yaml",
        timeout=6, expect_mmio=10,
    ))

    tests.append(TestCase(
        name="STM32F439 DMA Flash [board]",
        firmware="slab/examples/cortex-m/stm32/f439/peripherals/dma_flash/stm32f439_dma_flash_test.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f439_dma_flash.yaml",
        timeout=6, expect_mmio=3,
    ))

    tests.append(TestCase(
        name="STM32F439 RTC [board]",
        firmware="slab/examples/cortex-m/stm32/f439/peripherals/rtc/stm32f439_rtc_test.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f439_rtc.yaml",
        timeout=6, expect_mmio=3,
    ))

    # -- STM32F439 WooKey board --
    tests.append(TestCase(
        name="STM32F439 Crypto CDC [WooKey]",
        firmware="slab/examples/cortex-m/stm32/f439/usb/crypto_cdc/stm32_crypto_cdc.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32f439_wookey.yaml",
        timeout=6, expect_mmio=10,
    ))

    # -- STM32L433 (direct mode with L4xx peripherals) --
    tests.append(TestCase(
        name="STM32L433 I2C EEPROM [direct]",
        firmware="slab/examples/cortex-m/stm32/l433/peripherals/i2c_eeprom/stm32l433_i2c_eeprom_test.bin",
        cpu="cortex-m4", mode="direct", mcu="STM32L433",
        timeout=6, expect_mmio=3,
    ))

    tests.append(TestCase(
        name="STM32L433 I2C EEPROM [board]",
        firmware="slab/examples/cortex-m/stm32/l433/peripherals/i2c_eeprom/stm32l433_i2c_eeprom_test.bin",
        cpu="cortex-m4", mode="board",
        board_yaml="slab/boards/stm32l433_i2c_eeprom.yaml",
        timeout=6, expect_mmio=3,
    ))

    # -- Benchmarks (use peripheral test registers at 0x50000000) --
    for cpu_variant, cpu_type in [
        ("m0", "cortex-m0"), ("m3", "cortex-m3"),
        ("m4", "cortex-m4"), ("m7", "cortex-m7"),
        ("m33", "cortex-m33"),
    ]:
        tests.append(TestCase(
            name=f"Benchmark cortex-{cpu_variant}",
            firmware=f"slab/examples/benchmark/cortex-m/bin/benchmark_cortex-{cpu_variant}.bin",
            cpu=cpu_type, mode="legacy",
            timeout=5, expect_mmio=1,
        ))

    # -- nRF52840 (flash at 0x00000000) --
    for name, fw, mmio in [
        ("nRF52840 EEPROM", "slab/examples/cortex-m/nrf/nrf52840/peripherals/eeprom/nrf52840_eeprom_test.bin", 5),
        ("nRF52840 Flash", "slab/examples/cortex-m/nrf/nrf52840/peripherals/flash/nrf52840_flash_test.bin", 2),
        ("nRF52840 QSPI", "slab/examples/cortex-m/nrf/nrf52840/peripherals/qspi/nrf52840_qspi_test.bin", 5),
    ]:
        tests.append(TestCase(
            name=f"{name} [direct]",
            firmware=fw, cpu="cortex-m4", mode="direct", mcu="nRF52840",
            timeout=6, expect_mmio=mmio,
            qemu_extra={"flash-base": "0x00000000"},
        ))

    # -- RP2040 (flash at 0x10000000) --
    tests.append(TestCase(
        name="RP2040 EEPROM [direct]",
        firmware="slab/examples/cortex-m/rp2040/peripherals/eeprom/rp2040_eeprom_test.bin",
        cpu="cortex-m0", mode="direct", mcu="RP2040",
        timeout=6, expect_mmio=5,
        qemu_extra={"flash-base": "0x10000000"},
    ))

    # -- STM32H563 TZ (flash at 0x0C000000) --
    tests.append(TestCase(
        name="STM32H563 TZ Secure [direct]",
        firmware="slab/examples/cortex-m/stm32/h563/stm32h563_tz_cdc/build/secure_fw.bin",
        cpu="cortex-m33", mode="direct", mcu="STM32H563",
        timeout=6, expect_mmio=5,
        qemu_extra={"flash-base": "0x0C000000", "sram-base": "0x30000000", "sram-size": "0x50000"},
    ))

    return tests


# Expose for import by generate_reports.py
ALL_TESTS = build_test_cases()


# =============================================================================
# MAIN
# =============================================================================

async def main():
    if not QEMU_BIN.exists():
        log.error(f"QEMU binary not found: {QEMU_BIN}")
        sys.exit(1)

    tests = build_test_cases()
    results: List[TestResult] = []

    # Filter out tests with missing firmware
    available_tests = []
    skipped = []
    for tc in tests:
        fw_path = PROJECT_ROOT / tc.firmware
        if fw_path.exists():
            available_tests.append(tc)
        else:
            skipped.append(tc.name)

    print(f"\n{'='*72}")
    print(f"  SLAB E2E Firmware Test Suite")
    print(f"  QEMU: {QEMU_BIN}")
    print(f"  Tests: {len(available_tests)} available, {len(skipped)} skipped (no firmware)")
    print(f"{'='*72}\n")

    if skipped:
        for s in skipped:
            print(f"  [SKIP] {s} (firmware not built)")
        print()

    # Run tests sequentially
    for i, tc in enumerate(available_tests):
        status_line = f"[{i+1}/{len(available_tests)}] {tc.name}"
        print(f"  {status_line}...", end=" ", flush=True)

        result = await run_one_test(tc)
        results.append(result)

        txn_info = ""
        if result.device_transactions > 0:
            txn_info = f", {result.device_transactions} txns"

        if tc.known_issue:
            print(f"XFAIL ({tc.known_issue}, {result.mmio_count} MMIO{txn_info}, "
                  f"exit={result.qemu_exit}, {result.duration:.1f}s)")
        elif result.passed:
            print(f"PASS ({result.mmio_count} MMIO{txn_info}, {result.duration:.1f}s)")
        else:
            print(f"FAIL ({result.error}, exit={result.qemu_exit}, "
                  f"{result.mmio_count} MMIO{txn_info}, {result.duration:.1f}s)")
            if result.qemu_stderr:
                for line in result.qemu_stderr.strip().split('\n')[:2]:
                    print(f"         stderr: {line.strip()}")

    # Summary
    known_issues = [r for r, tc in zip(results, available_tests) if tc.known_issue]
    real_results = [r for r, tc in zip(results, available_tests) if not tc.known_issue]
    passed = sum(1 for r in real_results if r.passed)
    failed = sum(1 for r in real_results if not r.passed)

    print(f"\n{'='*72}")
    print(f"  RESULTS: {passed} passed, {failed} failed / {len(real_results)} tested")
    if known_issues:
        print(f"  XFAIL:   {len(known_issues)} (known issues)")
    if skipped:
        print(f"  SKIPPED: {len(skipped)} (firmware not built)")
    print(f"{'='*72}")

    # Detailed failure report
    if failed > 0:
        print(f"\n  FAILURES:")
        for r, tc in zip(results, available_tests):
            if not r.passed and not tc.known_issue:
                print(f"    - {r.name}: {r.error}")
                if r.qemu_stderr:
                    for line in r.qemu_stderr.strip().split('\n')[:3]:
                        print(f"      stderr: {line.strip()}")

    if known_issues:
        print(f"\n  KNOWN ISSUES:")
        for r in known_issues:
            print(f"    - {r.name}: {r.error}")

    # JSON output
    json_results = {
        'total': len(results),
        'passed': passed,
        'failed': failed,
        'skipped': len(skipped),
        'results': [
            {
                'name': r.name,
                'passed': r.passed,
                'mmio_count': r.mmio_count,
                'device_transactions': r.device_transactions,
                'duration': round(r.duration, 2),
                'qemu_exit': r.qemu_exit,
                'error': r.error,
            }
            for r in results
        ]
    }
    json_path = PROJECT_ROOT / "slab" / "tests" / "e2e_results.json"
    json_path.write_text(json.dumps(json_results, indent=2))
    print(f"\n  JSON results: {json_path}")

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
