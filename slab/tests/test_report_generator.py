"""
Unit tests for LaTeX Report Generator.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import tempfile

import pytest

from slab_cortex_m.mmio_tracer import MMIOTrace, SpinLoopInfo
from slab_cortex_m.report_generator import (
    TestBookReport,
    generate_architecture_tikz,
    generate_mmio_timeline_tikz,
    generate_register_table,
    generate_peripheral_summary_table,
    generate_init_sequence_table,
    generate_spin_loop_table,
    generate_test_book,
)


def _make_report(**kwargs) -> TestBookReport:
    """Create a TestBookReport with sensible defaults."""
    defaults = dict(
        title="STM32F405 SPI Flash Test",
        mcu="STM32F405",
        firmware_name="spi_flash_test.bin",
        peripherals=["RCC", "SPI1", "GPIOA", "USART1"],
        external_devices=["W25Q128 on SPI1", "LED on GPIOA:13"],
        build_command="make -C slab/examples/.../spi_flash",
        run_command="PYTHONPATH=slab/python python3 ...",
        mmio_count=222,
        device_transactions=5,
        uart_output="Hello from SPI flash test\n",
        mmio_traces=[],
        spin_loops=[],
        duration=3.5,
        passed=True,
        timestamp="2026-02-07T12:00:00",
        register_summary=[],
        peripheral_summary={
            "RCC": {"reads": 10, "writes": 5, "top_reg": "CR"},
            "SPI1": {"reads": 50, "writes": 20, "top_reg": "DR"},
        },
    )
    defaults.update(kwargs)
    return TestBookReport(**defaults)


def _make_traces(n=10) -> list:
    """Create a list of mock MMIOTrace objects."""
    traces = []
    for i in range(n):
        traces.append(MMIOTrace(
            sequence=i + 1,
            timestamp=i * 0.001,
            is_write=(i % 2 == 0),
            address=0x40013000 + (i % 4) * 4,
            size=4,
            value=i * 0x11,
            peripheral_name="SPI1",
            register_name=["CR1", "CR2", "SR", "DR"][i % 4],
            bitfields="SPE" if i == 0 else "",
        ))
    return traces


class TestArchitectureTikz:

    def test_basic_output(self):
        report = _make_report()
        tikz = generate_architecture_tikz(report)
        assert r"\begin{tikzpicture}" in tikz
        assert r"\end{tikzpicture}" in tikz
        assert "STM32F405" in tikz

    def test_external_devices(self):
        report = _make_report()
        tikz = generate_architecture_tikz(report)
        assert "W25Q128" in tikz
        assert "LED" in tikz

    def test_empty_peripherals(self):
        report = _make_report(peripherals=[], external_devices=[])
        tikz = generate_architecture_tikz(report)
        assert r"\begin{tikzpicture}" in tikz


class TestMmioTimeline:

    def test_basic_timeline(self):
        traces = _make_traces(5)
        tikz = generate_mmio_timeline_tikz(traces, limit=5)
        assert r"\begin{tikzpicture}" in tikz
        assert "SPI1" in tikz

    def test_empty_traces(self):
        tikz = generate_mmio_timeline_tikz([], limit=10)
        assert "No MMIO traces" in tikz

    def test_limit_applied(self):
        traces = _make_traces(100)
        tikz = generate_mmio_timeline_tikz(traces, limit=10)
        # Should have 10 sequence entries, not 100
        assert tikz.count("SPI1") <= 10


class TestTables:

    def test_register_table(self):
        reg_summary = [
            {"peripheral": "SPI1", "register": "CR1",
             "reads": 5, "writes": 10, "last_value": 0x44},
            {"peripheral": "SPI1", "register": "SR",
             "reads": 20, "writes": 0, "last_value": 0x02},
        ]
        latex = generate_register_table(reg_summary)
        assert r"\begin{longtable}" in latex
        assert "SPI1" in latex
        assert "CR1" in latex
        assert "0x00000044" in latex

    def test_empty_register_table(self):
        latex = generate_register_table([])
        assert "No register accesses" in latex

    def test_peripheral_summary_table(self):
        summary = {
            "RCC": {"reads": 10, "writes": 5, "top_reg": "CR"},
            "SPI1": {"reads": 50, "writes": 20, "top_reg": "DR"},
        }
        latex = generate_peripheral_summary_table(summary)
        assert "RCC" in latex
        assert "SPI1" in latex
        assert "DR" in latex

    def test_init_sequence_table(self):
        traces = _make_traces(10)
        latex = generate_init_sequence_table(traces)
        assert r"\begin{longtable}" in latex

    def test_spin_loop_table(self):
        loops = [
            SpinLoopInfo(
                peripheral="SPI1", register="SR",
                address=0x40013008, start_seq=10,
                end_seq=25, count=16, value=0x00),
        ]
        latex = generate_spin_loop_table(loops)
        assert "SPI1" in latex
        assert "SR" in latex
        assert "16" in latex

    def test_empty_spin_loop_table(self):
        latex = generate_spin_loop_table([])
        assert "No spin loops" in latex


class TestFullReport:

    def test_generate_tex_file(self):
        report = _make_report(
            mmio_traces=_make_traces(20),
            register_summary=[
                {"peripheral": "SPI1", "register": "DR",
                 "reads": 10, "writes": 10, "last_value": 0xFF},
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = generate_test_book(report, tmpdir)
            assert os.path.exists(tex_path)
            assert tex_path.endswith('.tex')

            content = open(tex_path).read()
            assert r"\documentclass" in content
            assert r"\begin{document}" in content
            assert r"\end{document}" in content
            assert "PASS" in content
            assert "SPI1" in content
            assert "222" in content  # mmio_count

    def test_failed_report(self):
        report = _make_report(passed=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = generate_test_book(report, tmpdir)
            content = open(tex_path).read()
            assert "FAIL" in content
            assert "failred" in content

    def test_uart_output_included(self):
        report = _make_report(uart_output="Hello UART!\nLine 2\n")
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = generate_test_book(report, tmpdir)
            content = open(tex_path).read()
            assert "UART Console Output" in content
            assert "Hello UART!" in content

    def test_spin_loops_section(self):
        report = _make_report(
            spin_loops=[
                SpinLoopInfo(
                    peripheral="RCC", register="CR",
                    address=0x40023800, start_seq=5,
                    end_seq=50, count=46, value=0x00),
            ],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = generate_test_book(report, tmpdir)
            content = open(tex_path).read()
            assert "Spin Loop Detection" in content

    def test_no_spin_loops_section_when_empty(self):
        report = _make_report(spin_loops=[])
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = generate_test_book(report, tmpdir)
            content = open(tex_path).read()
            assert "Spin Loop Detection" not in content
