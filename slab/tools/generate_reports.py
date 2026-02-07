#!/usr/bin/env python3
"""
SLAB Test Report Generator

Runs E2E firmware tests with MMIO tracing enabled, then generates
LaTeX test reports and MMIO trace logs for each firmware.

Usage:
    # Generate all reports
    PYTHONPATH=slab/python python3 slab/tools/generate_reports.py

    # Generate reports for specific firmware
    PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
        --firmware "STM32F405 HelloBlink"

    # CI mode (non-zero exit on failure)
    PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
        --ci --junit results.xml

    # Export MMIO traces only
    PYTHONPATH=slab/python python3 slab/tools/generate_reports.py --mmio-log

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, ElementTree

# Setup paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "slab" / "python"))
sys.path.insert(0, str(PROJECT_ROOT / "slab" / "tests"))

from slab_cortex_m.mmio_tracer import MMIOTracer
from slab_cortex_m.report_generator import TestBookReport, generate_test_book

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('ReportGen')


def collect_report(tc, result) -> TestBookReport:
    """Build a TestBookReport from test case and result."""
    tracer = result.tracer

    # Extract peripheral names from tracer data
    periph_names = []
    periph_summary = {}
    register_summary = []
    spin_loops = []
    traces = []

    if tracer and tracer.count > 0:
        periph_summary = tracer.get_peripheral_summary()
        periph_names = sorted(periph_summary.keys())
        register_summary = tracer.get_register_access_table()
        spin_loops = tracer.detect_spin_loops()
        traces = tracer.traces

    # External devices from board config
    ext_devices = []
    if tc.mode == "board" and tc.board_yaml:
        try:
            from slab_cortex_m.board import load_board_config
            config = load_board_config(str(PROJECT_ROOT / tc.board_yaml))
            for dev in config.external_devices:
                ext_devices.append(f"{dev.type} on {dev.bus}")
        except Exception:
            pass

    report = TestBookReport(
        title=tc.name,
        mcu=tc.mcu or tc.cpu,
        firmware_name=tc.firmware,
        peripherals=periph_names,
        external_devices=ext_devices,
        build_command=f"make -C {Path(tc.firmware).parent}",
        run_command=(
            f"PYTHONPATH=slab/python python3 slab/tools/generate_reports.py "
            f'--firmware "{tc.name}"'
        ),
        mmio_count=result.mmio_count,
        device_transactions=result.device_transactions,
        uart_output=result.uart_output,
        mmio_traces=traces,
        spin_loops=spin_loops,
        duration=result.duration,
        passed=result.passed,
        timestamp=datetime.now().isoformat(timespec='seconds'),
        register_summary=register_summary,
        peripheral_summary=periph_summary,
    )
    return report


def results_to_junit(results, test_cases) -> str:
    """Generate JUnit XML from results."""
    testsuites = Element('testsuites')
    testsuite = SubElement(testsuites, 'testsuite',
                           name='slab-e2e',
                           tests=str(len(results)),
                           failures=str(sum(1 for r in results if not r.passed)),
                           time=str(sum(r.duration for r in results)))

    for r, tc in zip(results, test_cases):
        testcase = SubElement(testsuite, 'testcase',
                              name=r.name,
                              time=f'{r.duration:.3f}')
        if not r.passed:
            if tc.known_issue:
                SubElement(testcase, 'skipped', message=tc.known_issue)
            elif r.error:
                SubElement(testcase, 'failure', message=r.error)

    import io
    buf = io.BytesIO()
    tree = ElementTree(testsuites)
    tree.write(buf, xml_declaration=True, encoding='utf-8')
    return buf.getvalue().decode('utf-8')


async def run_all(args):
    """Run tests and generate reports."""
    from e2e_firmware_test import build_test_cases, run_one_test, PROJECT_ROOT as E2E_ROOT, QEMU_BIN

    if not QEMU_BIN.exists():
        log.error(f"QEMU binary not found: {QEMU_BIN}")
        return 1

    all_tests = build_test_cases()
    output_dir = Path(args.output_dir)

    # Filter by firmware name if specified
    if args.firmware:
        pattern = args.firmware.lower()
        all_tests = [tc for tc in all_tests
                     if pattern in tc.name.lower()]
        if not all_tests:
            log.error(f"No test matching '{args.firmware}'")
            return 1

    # Filter out missing firmware
    available = []
    for tc in all_tests:
        fw_path = E2E_ROOT / tc.firmware
        if fw_path.exists():
            available.append(tc)
        elif args.verbose:
            log.info(f"Skipped (no firmware): {tc.name}")

    log.info(f"Running {len(available)} test(s), output: {output_dir}")

    results = []
    reports = []

    for i, tc in enumerate(available):
        log.info(f"[{i+1}/{len(available)}] {tc.name}")
        result = await run_one_test(tc)
        results.append(result)

        # Collect report data
        report = collect_report(tc, result)
        reports.append(report)

        status = "PASS" if result.passed else ("XFAIL" if tc.known_issue else "FAIL")
        log.info(f"  {status} ({result.mmio_count} MMIO, {result.duration:.1f}s)")

        # Export MMIO trace
        tracer = result.tracer
        if tracer and tracer.count > 0 and args.mmio_log:
            trace_dir = output_dir / "traces"
            trace_dir.mkdir(parents=True, exist_ok=True)
            safe_name = tc.name.replace(' ', '_').replace('/', '_')
            tracer.export_text(str(trace_dir / f"{safe_name}.mmio"))
            tracer.export_json(str(trace_dir / f"{safe_name}.jsonl"))
            if args.verbose:
                log.info(f"  Trace: {tracer.count} accesses exported")

    # Generate LaTeX reports
    if 'tex' in args.format or 'all' in args.format:
        tex_dir = output_dir / "tex"
        for report in reports:
            try:
                tex_path = generate_test_book(report, str(tex_dir))
                if args.verbose:
                    log.info(f"  LaTeX: {tex_path}")
            except Exception as e:
                log.warning(f"LaTeX generation failed for {report.title}: {e}")

    # Compile to PDF if requested
    if 'pdf' in args.format or 'all' in args.format:
        tex_dir = output_dir / "tex"
        for tex_file in tex_dir.glob("*.tex"):
            try:
                subprocess.run(
                    ['pdflatex', '-interaction=nonstopmode', str(tex_file)],
                    cwd=str(tex_dir), capture_output=True, timeout=30)
                if args.verbose:
                    log.info(f"  PDF: {tex_file.stem}.pdf")
            except FileNotFoundError:
                log.warning("pdflatex not found, skipping PDF generation")
                break
            except Exception as e:
                log.warning(f"PDF compilation failed for {tex_file.stem}: {e}")

    # Write JSON summary
    json_summary = {
        'generated': datetime.now().isoformat(),
        'total': len(results),
        'passed': sum(1 for r in results if r.passed),
        'failed': sum(1 for r in results if not r.passed),
        'results': [
            {
                'name': r.name,
                'passed': r.passed,
                'mmio_count': r.mmio_count,
                'device_transactions': r.device_transactions,
                'duration': round(r.duration, 2),
                'error': r.error,
                'trace_count': r.tracer.count if r.tracer else 0,
                'spin_loops': len(reports[i].spin_loops) if i < len(reports) else 0,
            }
            for i, r in enumerate(results)
        ]
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "summary.json"
    json_path.write_text(json.dumps(json_summary, indent=2))
    log.info(f"Summary: {json_path}")

    # Write JUnit XML
    if args.junit:
        junit_xml = results_to_junit(results, available)
        Path(args.junit).write_text(junit_xml)
        log.info(f"JUnit: {args.junit}")

    # Print summary table
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    print(f"\n{'='*72}")
    print(f"  SLAB Report Generation Complete")
    print(f"  Results: {passed} passed, {failed} failed / {len(results)} total")
    print(f"  Output:  {output_dir}")
    print(f"{'='*72}")

    if args.ci:
        return 0 if failed == 0 else 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='SLAB Test Report Generator')
    parser.add_argument('--firmware', '-f', type=str, default=None,
                        help='Run specific firmware (substring match)')
    parser.add_argument('--output-dir', '-o', type=str,
                        default='slab/reports',
                        help='Output directory (default: slab/reports/)')
    parser.add_argument('--format', type=str, nargs='+',
                        default=['all'],
                        choices=['all', 'tex', 'pdf', 'json'],
                        help='Output formats (default: all)')
    parser.add_argument('--ci', action='store_true',
                        help='CI mode: exit non-zero on failure')
    parser.add_argument('--junit', type=str, default=None,
                        help='Write JUnit XML to file')
    parser.add_argument('--mmio-log', action='store_true', default=True,
                        help='Export MMIO trace logs (default: enabled)')
    parser.add_argument('--no-mmio-log', action='store_false', dest='mmio_log',
                        help='Disable MMIO trace log export')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Verbose output')
    args = parser.parse_args()

    sys.exit(asyncio.run(run_all(args)))


if __name__ == '__main__':
    main()
