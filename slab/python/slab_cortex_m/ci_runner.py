"""
CI Runner for SLAB Emulation

Run firmware emulation scenarios unattended and produce machine-readable
results (JSON + JUnit XML) for CI/CD integration.

Usage:
    # Single scenario
    python3 -m slab_cortex_m.ci_runner --scenario slab/ci/test_hello_blink.yaml

    # Batch (all YAML in directory)
    python3 -m slab_cortex_m.ci_runner --batch slab/ci/ --junit results.xml

    # JSON output
    python3 -m slab_cortex_m.ci_runner --scenario test.yaml --output results.json

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any
from xml.etree.ElementTree import Element, SubElement, ElementTree

from slab_cortex_m.board import BoardConfig, load_board_config, MCU_REGISTRY, get_qemu_cpu
from slab_cortex_m.board_builder import build_board
from slab_cortex_m.base_server import BasePeripheralServer
from slab_cortex_m.mmio_tracer import MMIOTracer

# Try SHM
try:
    from slab_cortex_m.shm_peripheral import ShmPeripheralBridge, PeripheralHandler, BusAttributes
    from multiprocessing import shared_memory
    HAS_SHM = True
except ImportError:
    HAS_SHM = False

log = logging.getLogger('CIRunner')

# Try YAML
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class Assertion:
    """A single test assertion."""
    type: str                   # "gpio_toggle", "uart_output", "no_crash", "mmio_count"
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Scenario:
    """An emulation scenario to run."""
    name: str
    board: str                  # Path to board YAML or inline BoardConfig
    firmware: str               # Path to .bin file
    timeout: float = 30.0
    assertions: List[Assertion] = field(default_factory=list)
    qemu_args: List[str] = field(default_factory=list)
    mode: str = "tcp"           # "tcp" or "shm"


@dataclass
class AssertionResult:
    """Result of a single assertion."""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ScenarioResult:
    """Result of running one scenario."""
    scenario: str
    passed: bool
    duration: float
    assertions: List[AssertionResult] = field(default_factory=list)
    error: Optional[str] = None
    qemu_exit_code: int = -1
    mmio_count: int = 0


# =============================================================================
# BOARD SERVER (for CI use)
# =============================================================================

class CIBoardServer(BasePeripheralServer):
    """Lightweight server for CI scenarios using board builder."""

    def __init__(self, board, port: int):
        super().__init__(port)
        self.board = board
        self.board.irq_callback = self.send_irq
        self.mmio_count = 0
        self.tracer = MMIOTracer()
        self.gpio_toggles: Dict[str, int] = {}  # "GPIOA.13" -> count
        self._prev_gpio_states: Dict[str, int] = {}

    def create_peripherals(self):
        pass  # Board already has peripherals

    def find_peripheral(self, addr: int):
        if self.board.contains(addr):
            self.mmio_count += 1
            return self.board
        return None

    def _poll_gpio(self):
        """Check GPIO state changes for toggle counting."""
        for p in self.board.adapter.peripherals:
            if hasattr(p, 'name') and 'GPIO' in getattr(p, 'name', ''):
                odr = getattr(p, 'regs', {}).get(0x14, 0)  # ODR offset
                name = p.name
                for pin in range(16):
                    key = f"{name}.{pin}"
                    state = (odr >> pin) & 1
                    prev = self._prev_gpio_states.get(key, 0)
                    if state != prev:
                        self.gpio_toggles[key] = self.gpio_toggles.get(key, 0) + 1
                    self._prev_gpio_states[key] = state


class CIShmHandler(PeripheralHandler if HAS_SHM else object):
    """SHM peripheral handler for CI scenarios using board builder."""

    def __init__(self, board):
        self.board = board
        self.name = board.name
        self.base_address = 0x40000000
        self.size = 0x20000000
        self.registers = {}
        self.mmio_count = 0
        self.gpio_toggles: Dict[str, int] = {}
        self._prev_gpio_states: Dict[str, int] = {}

    def read(self, address, size, bus_attrs=None):
        self.mmio_count += 1
        if self.board.contains(address):
            secure = bus_attrs.ns == False if bus_attrs else True
            result = self.board.read(address, size, secure)
            return result[0] if isinstance(result, tuple) else result
        return 0

    def write(self, address, value, size, bus_attrs=None):
        self.mmio_count += 1
        if self.board.contains(address):
            secure = bus_attrs.ns == False if bus_attrs else True
            self.board.write(address, size, value, secure)

    def _poll_gpio(self):
        """Check GPIO state changes for toggle counting."""
        for p in self.board.adapter.peripherals:
            if hasattr(p, 'name') and 'GPIO' in getattr(p, 'name', ''):
                odr = getattr(p, 'regs', {}).get(0x14, 0)
                name = p.name
                for pin in range(16):
                    key = f"{name}.{pin}"
                    state = (odr >> pin) & 1
                    prev = self._prev_gpio_states.get(key, 0)
                    if state != prev:
                        self.gpio_toggles[key] = self.gpio_toggles.get(key, 0) + 1
                    self._prev_gpio_states[key] = state


# =============================================================================
# ASSERTION CHECKERS
# =============================================================================

def check_no_crash(result: ScenarioResult, params: dict) -> AssertionResult:
    """Check that QEMU didn't crash (exit code 0 or timeout-killed)."""
    # exit code 124 = killed by timeout (normal), 0 = clean exit, 137 = SIGKILL
    ok = result.qemu_exit_code in (0, 124, -15, 143)
    return AssertionResult(
        name="no_crash",
        passed=ok,
        detail=f"QEMU exit code: {result.qemu_exit_code}"
    )


def check_gpio_toggle(server: 'CIBoardServer', params: dict) -> AssertionResult:
    """Check that a GPIO pin toggled a minimum number of times."""
    return _check_gpio_toggle_dict(server.gpio_toggles, params)


def check_mmio_count(server: 'CIBoardServer', params: dict) -> AssertionResult:
    """Check that MMIO operations exceeded a minimum count."""
    return _check_mmio_count_val(server.mmio_count, params)


def _check_gpio_toggle_dict(gpio_toggles: dict, params: dict) -> AssertionResult:
    """Check GPIO toggle count from a dict."""
    gpio = params.get('gpio', 'GPIOA')
    pin = params.get('pin', 0)
    min_toggles = params.get('min_toggles', 2)
    key = f"{gpio}.{pin}"
    actual = gpio_toggles.get(key, 0)
    ok = actual >= min_toggles
    return AssertionResult(
        name=f"gpio_toggle({key}>={min_toggles})",
        passed=ok,
        detail=f"toggles={actual} (min={min_toggles})"
    )


def _check_mmio_count_val(mmio_count: int, params: dict) -> AssertionResult:
    """Check MMIO count against threshold."""
    min_count = params.get('min', 10)
    ok = mmio_count >= min_count
    return AssertionResult(
        name=f"mmio_count(>={min_count})",
        passed=ok,
        detail=f"count={mmio_count}"
    )


def check_spi_transactions(board, params: dict) -> AssertionResult:
    """Check SPI transaction count and optional MOSI pattern."""
    bus = params.get('bus', 'SPI1')
    min_count = params.get('min_count', 1)
    contains_mosi = params.get('contains_mosi', '')

    devices = board.bus_devices.get(bus, [])
    all_txns = []
    for dev in devices:
        if hasattr(dev, 'get_transaction_log'):
            all_txns.extend(dev.get_transaction_log())

    # Filter to SPI transactions only
    from slab_cortex_m.virtual_components import SPITransaction
    spi_txns = [t for t in all_txns if isinstance(t, SPITransaction)]
    count = len(spi_txns)

    if count < min_count:
        return AssertionResult(
            name=f"spi_transactions({bus}>={min_count})",
            passed=False,
            detail=f"count={count} (min={min_count})")

    if contains_mosi:
        pattern = bytes.fromhex(contains_mosi.replace(' ', ''))
        found = any(pattern in t.mosi for t in spi_txns)
        if not found:
            return AssertionResult(
                name=f"spi_transactions({bus} contains {contains_mosi})",
                passed=False,
                detail=f"MOSI pattern not found in {count} transactions")

    return AssertionResult(
        name=f"spi_transactions({bus}>={min_count})",
        passed=True,
        detail=f"count={count}")


def check_i2c_transactions(board, params: dict) -> AssertionResult:
    """Check I2C transaction count with optional address and data filter."""
    bus = params.get('bus', 'I2C1')
    min_count = params.get('min_count', 1)
    address = params.get('address', None)
    contains_data = params.get('contains_data', '')

    devices = board.bus_devices.get(bus, [])
    all_txns = []
    for dev in devices:
        if hasattr(dev, 'get_transaction_log'):
            all_txns.extend(dev.get_transaction_log())

    # Filter to I2C transactions only
    from slab_cortex_m.virtual_components import I2CTransaction
    i2c_txns = [t for t in all_txns if isinstance(t, I2CTransaction)]

    if address is not None:
        addr_val = address if isinstance(address, int) else int(str(address), 0)
        i2c_txns = [t for t in i2c_txns if t.address == addr_val]

    count = len(i2c_txns)

    if count < min_count:
        addr_str = f" @0x{address:02X}" if address is not None else ""
        return AssertionResult(
            name=f"i2c_transactions({bus}{addr_str}>={min_count})",
            passed=False,
            detail=f"count={count} (min={min_count})")

    if contains_data:
        pattern = bytes.fromhex(contains_data.replace(' ', ''))
        found = any(pattern in t.data for t in i2c_txns)
        if not found:
            return AssertionResult(
                name=f"i2c_transactions({bus} contains {contains_data})",
                passed=False,
                detail=f"data pattern not found in {count} transactions")

    addr_str = f" @0x{address:02X}" if address is not None else ""
    return AssertionResult(
        name=f"i2c_transactions({bus}{addr_str}>={min_count})",
        passed=True,
        detail=f"count={count}")


def check_uart_contains(board, params: dict) -> AssertionResult:
    """Check board UART output for substring or regex match."""
    text = params.get('text', '')
    pattern = params.get('regex', '')
    uart_str = board.uart_output.decode('utf-8', errors='replace')

    if text:
        ok = text in uart_str
        return AssertionResult(
            name=f"uart_contains('{text}')",
            passed=ok,
            detail=f"found={ok}, output={uart_str[:80]!r}")

    if pattern:
        match = re.search(pattern, uart_str)
        ok = match is not None
        return AssertionResult(
            name=f"uart_contains(regex={pattern!r})",
            passed=ok,
            detail=f"found={ok}, output={uart_str[:80]!r}")

    return AssertionResult(
        name="uart_contains",
        passed=False,
        detail="no 'text' or 'regex' param specified")


def check_usb_setup(board, params: dict) -> AssertionResult:
    """Check USB SETUP transaction count and optional VID/PID."""
    min_count = params.get('min_count', 1)
    expected_vid = params.get('vid', None)
    expected_pid = params.get('pid', None)

    # Collect USB transactions from board or from USB peripherals
    usb_txns = list(board.usb_transactions)
    if not usb_txns:
        # Try to find USB peripheral in the adapter
        for p in board.adapter.peripherals:
            if hasattr(p, 'usb_transactions'):
                usb_txns.extend(p.usb_transactions)

    # Filter SETUP transactions (direction=0 with setup data)
    setup_txns = []
    for t in usb_txns:
        setup = t.get('setup') if isinstance(t, dict) else getattr(t, 'setup', None)
        if setup is not None:
            setup_txns.append(t)

    count = len(setup_txns)

    if count < min_count:
        return AssertionResult(
            name=f"usb_setup(>={min_count})",
            passed=False,
            detail=f"count={count} (min={min_count})")

    # Optional VID/PID check: look for device descriptor response
    if expected_vid is not None or expected_pid is not None:
        vid_val = expected_vid if isinstance(expected_vid, int) else int(str(expected_vid), 0)
        pid_val = expected_pid if isinstance(expected_pid, int) else int(str(expected_pid), 0)

        # Look for IN transactions (direction=1) with device descriptor data (>=18 bytes)
        found_vid_pid = False
        for t in usb_txns:
            direction = t.get('direction') if isinstance(t, dict) else getattr(t, 'direction', -1)
            data = t.get('data', b'') if isinstance(t, dict) else getattr(t, 'data', b'')
            if direction == 1 and len(data) >= 18:
                # Device descriptor: VID at bytes 8-9, PID at bytes 10-11 (little-endian)
                if data[1] == 0x01:  # bDescriptorType == DEVICE
                    vid = data[8] | (data[9] << 8)
                    pid = data[10] | (data[11] << 8)
                    if (expected_vid is None or vid == vid_val) and \
                       (expected_pid is None or pid == pid_val):
                        found_vid_pid = True
                        break

        if not found_vid_pid:
            return AssertionResult(
                name=f"usb_setup(VID=0x{vid_val:04X} PID=0x{pid_val:04X})",
                passed=False,
                detail=f"VID/PID not found in {count} SETUP transactions")

        return AssertionResult(
            name=f"usb_setup(VID=0x{vid_val:04X} PID=0x{pid_val:04X})",
            passed=True,
            detail=f"count={count}")

    return AssertionResult(
        name=f"usb_setup(>={min_count})",
        passed=True,
        detail=f"count={count}")


# =============================================================================
# CI RUNNER
# =============================================================================

class CIRunner:
    """Run emulation scenarios and collect results."""

    def __init__(self, qemu_bin: str = None):
        self.qemu_bin = qemu_bin or self._find_qemu()
        if not Path(self.qemu_bin).exists():
            raise FileNotFoundError(f"QEMU not found: {self.qemu_bin}")

    @staticmethod
    def _find_qemu() -> str:
        """Find QEMU binary in common locations."""
        candidates = [
            'build/qemu-system-arm',
            '../build/qemu-system-arm',
            'qemu-system-arm',
        ]
        for c in candidates:
            if Path(c).exists():
                return str(Path(c).resolve())
        return 'build/qemu-system-arm'

    async def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Run a single emulation scenario (dispatches TCP or SHM)."""
        if scenario.mode == "shm":
            return await self.run_scenario_shm(scenario)
        return await self.run_scenario_tcp(scenario)

    async def run_scenario_tcp(self, scenario: Scenario) -> ScenarioResult:
        """Run a single emulation scenario via TCP proxy."""
        start_time = time.time()
        result = ScenarioResult(
            scenario=scenario.name,
            passed=False,
            duration=0,
        )

        try:
            # Load board config
            board_config = load_board_config(scenario.board)
            board = build_board(board_config)

            # Find a free port
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]

            # Start server
            server = CIBoardServer(board, port)
            tcp_server = await asyncio.start_server(
                server.handle_client, '127.0.0.1', port, reuse_address=True)
            server.running = True

            # Build QEMU command
            cpu = get_qemu_cpu(board_config)
            machine_opts = f'slab-cortex-m,cpu-type={cpu},tcp-port={port}'
            for k, v in board_config.qemu_extra.items():
                machine_opts += f',{k}={v}'
            cmd = [
                self.qemu_bin,
                '-M', machine_opts,
                '-kernel', scenario.firmware,
                '-nographic', '-monitor', 'none',
            ] + scenario.qemu_args

            log.info(f"[{scenario.name}] Starting QEMU: {' '.join(cmd[:8])}...")

            # Launch QEMU
            qemu = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # Poll GPIO during execution
            poll_task = asyncio.ensure_future(
                self._poll_loop_tcp(server, scenario.timeout))

            try:
                await asyncio.wait_for(qemu.wait(), timeout=scenario.timeout)
            except asyncio.TimeoutError:
                qemu.terminate()
                try:
                    await asyncio.wait_for(qemu.wait(), timeout=5)
                except asyncio.TimeoutError:
                    qemu.kill()

            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

            result.qemu_exit_code = qemu.returncode or 0
            result.mmio_count = server.mmio_count

            # Run assertions
            self._check_assertions(scenario, result, server.gpio_toggles,
                                   server.mmio_count, board=board)

            # Cleanup
            server.running = False
            tcp_server.close()
            await tcp_server.wait_closed()

        except Exception as e:
            result.error = str(e)
            log.error(f"[{scenario.name}] Error: {e}")

        result.duration = time.time() - start_time
        return result

    async def run_scenario_shm(self, scenario: Scenario) -> ScenarioResult:
        """Run a single emulation scenario via SHM proxy."""
        start_time = time.time()
        result = ScenarioResult(
            scenario=scenario.name,
            passed=False,
            duration=0,
        )

        if not HAS_SHM:
            result.error = "SHM not available"
            result.duration = time.time() - start_time
            return result

        shm_name = f"/slab_ci_{os.getpid()}_{int(time.time() * 1000) % 100000}"

        try:
            board_config = load_board_config(scenario.board)
            board = build_board(board_config)
            handler = CIShmHandler(board)

            bridge = ShmPeripheralBridge(shm_name=shm_name)
            bridge.create()
            bridge.register_peripheral(handler.base_address, handler)

            # Wire board IRQ callback to SHM bridge
            board.irq_callback = lambda irq_num, level=1: (
                bridge.set_irq(irq_num) if level else bridge.clear_irq(irq_num))

            bridge.start_handler()

            # Build QEMU command (SHM mode)
            cpu = get_qemu_cpu(board_config)
            machine_opts = f'slab-cortex-m,cpu-type={cpu},shm-name={shm_name}'
            for k, v in board_config.qemu_extra.items():
                machine_opts += f',{k}={v}'
            cmd = [
                self.qemu_bin,
                '-M', machine_opts,
                '-kernel', scenario.firmware,
                '-nographic', '-monitor', 'none',
            ] + scenario.qemu_args

            log.info(f"[{scenario.name}] Starting QEMU (SHM): "
                     f"{' '.join(cmd[:8])}...")

            qemu = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # Poll GPIO during execution
            poll_task = asyncio.ensure_future(
                self._poll_loop_shm(handler, scenario.timeout))

            try:
                await asyncio.wait_for(qemu.wait(), timeout=scenario.timeout)
            except asyncio.TimeoutError:
                qemu.terminate()
                try:
                    await asyncio.wait_for(qemu.wait(), timeout=5)
                except asyncio.TimeoutError:
                    qemu.kill()

            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass

            result.qemu_exit_code = qemu.returncode or 0
            result.mmio_count = handler.mmio_count

            self._check_assertions(scenario, result, handler.gpio_toggles,
                                   handler.mmio_count, board=board)

            # Cleanup SHM
            bridge._running = False
            if bridge._thread:
                bridge._thread.join(timeout=1.0)
            try:
                shm_obj = shared_memory.SharedMemory(name=shm_name, create=False)
                shm_obj.close()
                shm_obj.unlink()
            except Exception:
                pass
            bridge.close()

        except Exception as e:
            result.error = str(e)
            log.error(f"[{scenario.name}] Error: {e}")

        result.duration = time.time() - start_time
        return result

    def _check_assertions(self, scenario: Scenario, result: ScenarioResult,
                          gpio_toggles: dict, mmio_count: int,
                          board=None):
        """Run assertions for a scenario result."""
        for assertion in scenario.assertions:
            if assertion.type == 'no_crash':
                result.assertions.append(
                    check_no_crash(result, assertion.params))
            elif assertion.type == 'gpio_toggle':
                result.assertions.append(
                    _check_gpio_toggle_dict(gpio_toggles, assertion.params))
            elif assertion.type == 'mmio_count':
                result.assertions.append(
                    _check_mmio_count_val(mmio_count, assertion.params))
            elif assertion.type == 'spi_transactions':
                if board:
                    result.assertions.append(
                        check_spi_transactions(board, assertion.params))
                else:
                    result.assertions.append(AssertionResult(
                        name="spi_transactions", passed=False,
                        detail="board not available"))
            elif assertion.type == 'i2c_transactions':
                if board:
                    result.assertions.append(
                        check_i2c_transactions(board, assertion.params))
                else:
                    result.assertions.append(AssertionResult(
                        name="i2c_transactions", passed=False,
                        detail="board not available"))
            elif assertion.type == 'uart_contains':
                if board:
                    result.assertions.append(
                        check_uart_contains(board, assertion.params))
                else:
                    result.assertions.append(AssertionResult(
                        name="uart_contains", passed=False,
                        detail="board not available"))
            elif assertion.type == 'usb_setup':
                if board:
                    result.assertions.append(
                        check_usb_setup(board, assertion.params))
                else:
                    result.assertions.append(AssertionResult(
                        name="usb_setup", passed=False,
                        detail="board not available"))
            else:
                result.assertions.append(AssertionResult(
                    name=assertion.type,
                    passed=False,
                    detail=f"Unknown assertion type: {assertion.type}"))
        result.passed = all(a.passed for a in result.assertions)

    async def _poll_loop_tcp(self, server: CIBoardServer, timeout: float):
        """Poll GPIO states during TCP execution."""
        end = time.time() + timeout
        while time.time() < end:
            server._poll_gpio()
            await asyncio.sleep(0.05)

    async def _poll_loop_shm(self, handler: 'CIShmHandler', timeout: float):
        """Poll GPIO states during SHM execution."""
        end = time.time() + timeout
        while time.time() < end:
            handler._poll_gpio()
            await asyncio.sleep(0.05)

    def run_batch(self, scenarios: List[Scenario]) -> List[ScenarioResult]:
        """Run multiple scenarios sequentially."""
        results = []
        for s in scenarios:
            log.info(f"Running: {s.name}")
            result = asyncio.run(self.run_scenario(s))
            status = "PASS" if result.passed else "FAIL"
            log.info(f"  {status} ({result.duration:.1f}s, "
                     f"{result.mmio_count} MMIO ops)")
            for a in result.assertions:
                mark = "+" if a.passed else "-"
                log.info(f"    [{mark}] {a.name}: {a.detail}")
            results.append(result)
        return results


# =============================================================================
# OUTPUT FORMATS
# =============================================================================

def results_to_json(results: List[ScenarioResult]) -> str:
    """Convert results to JSON."""
    data = {
        'total': len(results),
        'passed': sum(1 for r in results if r.passed),
        'failed': sum(1 for r in results if not r.passed),
        'results': [asdict(r) for r in results],
    }
    return json.dumps(data, indent=2)


def results_to_junit(results: List[ScenarioResult]) -> str:
    """Convert results to JUnit XML for CI systems."""
    testsuites = Element('testsuites')
    testsuite = SubElement(testsuites, 'testsuite',
                           name='slab-emulation',
                           tests=str(len(results)),
                           failures=str(sum(1 for r in results if not r.passed)),
                           time=str(sum(r.duration for r in results)))

    for r in results:
        tc = SubElement(testsuite, 'testcase',
                        name=r.scenario,
                        time=f'{r.duration:.3f}')
        if not r.passed:
            if r.error:
                failure = SubElement(tc, 'error', message=r.error)
            else:
                failed = [a for a in r.assertions if not a.passed]
                msg = '; '.join(f"{a.name}: {a.detail}" for a in failed)
                failure = SubElement(tc, 'failure', message=msg)

    import io
    buf = io.BytesIO()
    tree = ElementTree(testsuites)
    tree.write(buf, xml_declaration=True, encoding='utf-8')
    return buf.getvalue().decode('utf-8')


# =============================================================================
# SCENARIO LOADING
# =============================================================================

def load_scenarios(path: str) -> List[Scenario]:
    """Load scenarios from a YAML file."""
    if not HAS_YAML:
        raise ImportError("PyYAML required: pip install pyyaml")

    p = Path(path)
    data = yaml.safe_load(p.read_text())

    scenarios = []
    for s in data.get('scenarios', [data] if 'name' in data else []):
        assertions = []
        for a in s.get('assertions', []):
            assertions.append(Assertion(
                type=a['type'],
                params=a.get('params', {}),
            ))
        scenarios.append(Scenario(
            name=s['name'],
            board=s['board'],
            firmware=s['firmware'],
            timeout=s.get('timeout', 30),
            assertions=assertions,
            qemu_args=s.get('qemu_args', []),
            mode=s.get('mode', 'tcp'),
        ))
    return scenarios


def discover_scenarios(directory: str) -> List[Scenario]:
    """Discover all scenario YAML files in a directory."""
    d = Path(directory)
    scenarios = []
    for f in sorted(d.glob('*.yaml')) + sorted(d.glob('*.yml')):
        try:
            scenarios.extend(load_scenarios(str(f)))
        except Exception as e:
            log.warning(f"Failed to load {f}: {e}")
    return scenarios


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
        datefmt='%H:%M:%S'
    )

    parser = argparse.ArgumentParser(description='SLAB CI Emulation Runner')
    parser.add_argument('--scenario', '-s', type=str,
                        help='Path to scenario YAML file')
    parser.add_argument('--batch', '-b', type=str,
                        help='Directory with scenario YAML files')
    parser.add_argument('--output', '-o', type=str,
                        help='Output JSON results to file')
    parser.add_argument('--junit', type=str,
                        help='Output JUnit XML to file')
    parser.add_argument('--qemu', type=str,
                        help='Path to QEMU binary')
    parser.add_argument('--shm', action='store_true',
                        help='Also run each scenario via SHM proxy')
    args = parser.parse_args()

    # Load scenarios
    scenarios = []
    if args.scenario:
        scenarios = load_scenarios(args.scenario)
    elif args.batch:
        scenarios = discover_scenarios(args.batch)
    else:
        parser.error("Either --scenario or --batch required")

    # Duplicate scenarios for SHM testing
    if args.shm and HAS_SHM:
        shm_scenarios = []
        for s in scenarios:
            if s.mode == "tcp":
                shm_s = Scenario(
                    name=f"{s.name} [shm]",
                    board=s.board,
                    firmware=s.firmware,
                    timeout=s.timeout,
                    assertions=s.assertions,
                    qemu_args=s.qemu_args,
                    mode="shm",
                )
                shm_scenarios.append(shm_s)
        scenarios.extend(shm_scenarios)

    if not scenarios:
        log.error("No scenarios found")
        sys.exit(1)

    log.info(f"Running {len(scenarios)} scenario(s)")

    # Run
    runner = CIRunner(qemu_bin=args.qemu)
    results = runner.run_batch(scenarios)

    # Output
    if args.output:
        Path(args.output).write_text(results_to_json(results))
        log.info(f"JSON results written to {args.output}")

    if args.junit:
        Path(args.junit).write_text(results_to_junit(results))
        log.info(f"JUnit XML written to {args.junit}")

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    print(f"\n{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed / {len(results)} total")
    print(f"{'='*60}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
