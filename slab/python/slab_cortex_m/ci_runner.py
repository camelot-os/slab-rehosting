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
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import logging
import os
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
    gpio = params.get('gpio', 'GPIOA')
    pin = params.get('pin', 0)
    min_toggles = params.get('min_toggles', 2)
    key = f"{gpio}.{pin}"
    actual = server.gpio_toggles.get(key, 0)
    ok = actual >= min_toggles
    return AssertionResult(
        name=f"gpio_toggle({key}>={min_toggles})",
        passed=ok,
        detail=f"toggles={actual} (min={min_toggles})"
    )


def check_mmio_count(server: 'CIBoardServer', params: dict) -> AssertionResult:
    """Check that MMIO operations exceeded a minimum count."""
    min_count = params.get('min', 10)
    ok = server.mmio_count >= min_count
    return AssertionResult(
        name=f"mmio_count(>={min_count})",
        passed=ok,
        detail=f"count={server.mmio_count}"
    )


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
        """Run a single emulation scenario."""
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
            cmd = [
                self.qemu_bin,
                '-M', f'slab-cortex-m,cpu-type={cpu},tcp-port={port}',
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
                self._poll_loop(server, scenario.timeout))

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
            for assertion in scenario.assertions:
                if assertion.type == 'no_crash':
                    result.assertions.append(
                        check_no_crash(result, assertion.params))
                elif assertion.type == 'gpio_toggle':
                    result.assertions.append(
                        check_gpio_toggle(server, assertion.params))
                elif assertion.type == 'mmio_count':
                    result.assertions.append(
                        check_mmio_count(server, assertion.params))
                else:
                    result.assertions.append(AssertionResult(
                        name=assertion.type,
                        passed=False,
                        detail=f"Unknown assertion type: {assertion.type}"))

            result.passed = all(a.passed for a in result.assertions)

            # Cleanup
            server.running = False
            tcp_server.close()
            await tcp_server.wait_closed()

        except Exception as e:
            result.error = str(e)
            log.error(f"[{scenario.name}] Error: {e}")

        result.duration = time.time() - start_time
        return result

    async def _poll_loop(self, server: CIBoardServer, timeout: float):
        """Poll GPIO states during execution."""
        end = time.time() + timeout
        while time.time() < end:
            server._poll_gpio()
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
    args = parser.parse_args()

    # Load scenarios
    scenarios = []
    if args.scenario:
        scenarios = load_scenarios(args.scenario)
    elif args.batch:
        scenarios = discover_scenarios(args.batch)
    else:
        parser.error("Either --scenario or --batch required")

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
