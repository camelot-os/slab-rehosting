"""
Unit tests for MMIO Tracer and Register Name Resolver.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import json
import os
import tempfile

import pytest

from slab_cortex_m.mmio_tracer import (
    MMIOTrace, MMIOTracer, RegisterNameResolver, SpinLoopInfo,
)


# ---------------------------------------------------------------------------
# Mock peripherals (mimic STM32/NRF class constant patterns)
# ---------------------------------------------------------------------------

class MockSTM32SPI:
    """Mimics STM32SPIv1 register layout."""
    CR1 = 0x00
    CR2 = 0x04
    SR = 0x08
    DR = 0x0C

    # Bit-fields
    CR1_SPE = 1 << 6
    CR1_MSTR = 1 << 2
    CR1_BR_MASK = 0x7 << 3
    SR_RXNE = 1 << 0
    SR_TXE = 1 << 1
    SR_BSY = 1 << 7

    def __init__(self):
        self.name = "SPI1"
        self.base = 0x40013000
        self.size = 0x400


class MockNRFTimer:
    """Mimics NRF TIMER register layout."""
    TASKS_START = 0x000
    TASKS_STOP = 0x004
    TASKS_CLEAR = 0x00C
    EVENTS_COMPARE_BASE = 0x140
    SHORTS = 0x200
    INTEN = 0x300
    INTENSET = 0x304
    MODE = 0x504
    BITMODE = 0x508
    PRESCALER = 0x510

    def __init__(self):
        self.name = "TIMER0"
        self.base = 0x40008000
        self.size = 0x1000


class MockSTM32GPIO:
    """Mimics STM32GPIOv2 register layout."""
    MODER = 0x00
    OTYPER = 0x04
    OSPEEDR = 0x08
    PUPDR = 0x0C
    IDR = 0x10
    ODR = 0x14
    BSRR = 0x18

    def __init__(self):
        self.name = "GPIOA"
        self.base = 0x40020000
        self.size = 0x400


# ---------------------------------------------------------------------------
# RegisterNameResolver tests
# ---------------------------------------------------------------------------

class TestRegisterNameResolver:

    def test_stm32_spi_registers(self):
        resolver = RegisterNameResolver()
        spi = MockSTM32SPI()
        assert resolver.resolve(spi, 0x00) == "CR1"
        assert resolver.resolve(spi, 0x04) == "CR2"
        assert resolver.resolve(spi, 0x08) == "SR"
        assert resolver.resolve(spi, 0x0C) == "DR"

    def test_nrf_timer_registers(self):
        resolver = RegisterNameResolver()
        timer = MockNRFTimer()
        assert resolver.resolve(timer, 0x000) == "TASKS_START"
        assert resolver.resolve(timer, 0x004) == "TASKS_STOP"
        assert resolver.resolve(timer, 0x200) == "SHORTS"
        assert resolver.resolve(timer, 0x504) == "MODE"

    def test_unknown_offset(self):
        resolver = RegisterNameResolver()
        spi = MockSTM32SPI()
        result = resolver.resolve(spi, 0x3FC)
        assert result == "REG_0x3FC"

    def test_bitfield_resolution(self):
        resolver = RegisterNameResolver()
        spi = MockSTM32SPI()
        # CR1 value with SPE (bit 6) and MSTR (bit 2) set
        value = (1 << 6) | (1 << 2)  # 0x44
        bits = resolver.resolve_bitfields(spi, "CR1", value)
        assert "SPE" in bits
        assert "MSTR" in bits

    def test_bitfield_excludes_masks(self):
        """Multi-bit masks like CR1_BR_MASK should not appear."""
        resolver = RegisterNameResolver()
        spi = MockSTM32SPI()
        # Set all bits
        bits = resolver.resolve_bitfields(spi, "CR1", 0xFFFF)
        assert "BR_MASK" not in bits

    def test_caching(self):
        """Resolver should cache per-class."""
        resolver = RegisterNameResolver()
        spi1 = MockSTM32SPI()
        spi2 = MockSTM32SPI()
        spi2.name = "SPI2"
        spi2.base = 0x40003800
        # Both share the same class -> same cache entry
        assert resolver.resolve(spi1, 0x00) == "CR1"
        assert resolver.resolve(spi2, 0x00) == "CR1"
        assert len(resolver._offset_cache) == 1

    def test_gpio_registers(self):
        resolver = RegisterNameResolver()
        gpio = MockSTM32GPIO()
        assert resolver.resolve(gpio, 0x00) == "MODER"
        assert resolver.resolve(gpio, 0x14) == "ODR"
        assert resolver.resolve(gpio, 0x18) == "BSRR"


# ---------------------------------------------------------------------------
# MMIOTracer tests
# ---------------------------------------------------------------------------

class TestMMIOTracer:

    def test_trace_read_write(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_write(0x40013000, 4, 0x44, spi)  # CR1
        tracer.trace_read(0x40013008, 4, 0x02, spi)   # SR
        assert tracer.count == 2
        assert tracer.traces[0].is_write is True
        assert tracer.traces[0].register_name == "CR1"
        assert tracer.traces[1].is_write is False
        assert tracer.traces[1].register_name == "SR"

    def test_trace_peripheral_name(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_read(0x40013000, 4, 0, spi)
        assert tracer.traces[0].peripheral_name == "SPI1"

    def test_trace_unmapped(self):
        tracer = MMIOTracer()
        tracer.trace_read(0xDEAD0000, 4, 0, None)
        assert tracer.traces[0].peripheral_name == "UNMAPPED"

    def test_sequence_numbers(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        for i in range(5):
            tracer.trace_read(0x40013008, 4, 0, spi)
        assert tracer.traces[0].sequence == 1
        assert tracer.traces[4].sequence == 5

    def test_reset(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_read(0x40013000, 4, 0, spi)
        assert tracer.count == 1
        tracer.reset()
        assert tracer.count == 0
        tracer.trace_read(0x40013000, 4, 0, spi)
        assert tracer.traces[0].sequence == 1

    def test_export_text(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_write(0x40013000, 4, 0x44, spi)
        tracer.trace_read(0x40013008, 4, 0x02, spi)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.mmio',
                                         delete=False) as f:
            path = f.name
        try:
            tracer.export_text(path)
            content = open(path).read()
            lines = content.strip().split('\n')
            assert len(lines) == 2
            assert "W 0x40013000" in lines[0]
            assert "SPI1->CR1" in lines[0]
            assert "R 0x40013008" in lines[1]
            assert "SPI1->SR" in lines[1]
        finally:
            os.unlink(path)

    def test_export_json(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_write(0x40013000, 4, 0x44, spi)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                         delete=False) as f:
            path = f.name
        try:
            tracer.export_json(path)
            with open(path) as f:
                record = json.loads(f.readline())
            assert record['rw'] == 'W'
            assert record['periph'] == 'SPI1'
            assert record['reg'] == 'CR1'
        finally:
            os.unlink(path)

    def test_export_csv(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_read(0x4001300C, 4, 0xFF, spi)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv',
                                         delete=False) as f:
            path = f.name
        try:
            tracer.export_csv(path)
            content = open(path).read()
            lines = content.strip().split('\n')
            assert lines[0].startswith("sequence,")  # header
            assert "SPI1" in lines[1]
            assert "DR" in lines[1]
        finally:
            os.unlink(path)

    def test_peripheral_summary(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        gpio = MockSTM32GPIO()
        tracer.trace_write(0x40013000, 4, 0x44, spi)  # SPI1.CR1
        tracer.trace_read(0x40013008, 4, 0x02, spi)   # SPI1.SR
        tracer.trace_read(0x40013008, 4, 0x02, spi)   # SPI1.SR
        tracer.trace_write(0x40020014, 4, 0x01, gpio)  # GPIOA.ODR

        summary = tracer.get_peripheral_summary()
        assert summary['SPI1']['reads'] == 2
        assert summary['SPI1']['writes'] == 1
        assert summary['GPIOA']['writes'] == 1
        assert summary['SPI1']['top_reg'] == 'SR'

    def test_register_access_table(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_write(0x40013000, 4, 0x44, spi)
        tracer.trace_read(0x40013008, 4, 0x02, spi)
        tracer.trace_read(0x40013008, 4, 0x02, spi)

        table = tracer.get_register_access_table()
        assert len(table) == 2
        sr_entry = [e for e in table if e['register'] == 'SR'][0]
        assert sr_entry['reads'] == 2
        assert sr_entry['writes'] == 0

    def test_init_sequence(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        # Write some unique values (init)
        for i in range(5):
            tracer.trace_write(0x40013000, 4, i, spi)
        # Then repeat (main loop)
        for _ in range(20):
            tracer.trace_read(0x40013008, 4, 0x02, spi)
            tracer.trace_write(0x4001300C, 4, 0x42, spi)

        init = tracer.get_init_sequence()
        # Should stop before all 40 traces
        assert len(init) < 45

    def test_bitfields_in_write_trace(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        # Write CR1 with SPE + MSTR
        tracer.trace_write(0x40013000, 4, (1 << 6) | (1 << 2), spi)
        assert "SPE" in tracer.traces[0].bitfields
        assert "MSTR" in tracer.traces[0].bitfields

    def test_no_bitfields_in_read_trace(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        tracer.trace_read(0x40013000, 4, 0x44, spi)
        assert tracer.traces[0].bitfields == ""


# ---------------------------------------------------------------------------
# Spin loop detection tests
# ---------------------------------------------------------------------------

class TestSpinLoopDetection:

    def test_detect_spin_loop(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        # Simulate polling SR 10 times
        for _ in range(10):
            tracer.trace_read(0x40013008, 4, 0x00, spi)
        loops = tracer.detect_spin_loops(min_repeats=5)
        assert len(loops) == 1
        assert loops[0].peripheral == "SPI1"
        assert loops[0].register == "SR"
        assert loops[0].count == 10

    def test_no_spin_on_varied_values(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        # Reads with changing values
        for i in range(10):
            tracer.trace_read(0x40013008, 4, i, spi)
        loops = tracer.detect_spin_loops(min_repeats=5)
        assert len(loops) == 0

    def test_no_spin_on_writes(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        for _ in range(10):
            tracer.trace_write(0x40013000, 4, 0x44, spi)
        loops = tracer.detect_spin_loops(min_repeats=5)
        assert len(loops) == 0

    def test_multiple_spin_loops(self):
        tracer = MMIOTracer()
        spi = MockSTM32SPI()
        gpio = MockSTM32GPIO()
        # First spin: SPI1.SR
        for _ in range(8):
            tracer.trace_read(0x40013008, 4, 0x00, spi)
        # Break
        tracer.trace_write(0x40013000, 4, 0x44, spi)
        # Second spin: GPIOA.IDR
        for _ in range(6):
            tracer.trace_read(0x40020010, 4, 0x00, gpio)

        loops = tracer.detect_spin_loops(min_repeats=5)
        assert len(loops) == 2
        assert loops[0].peripheral == "SPI1"
        assert loops[1].peripheral == "GPIOA"


# ---------------------------------------------------------------------------
# Board proxy resolution tests
# ---------------------------------------------------------------------------

class TestProxyResolution:
    """Test that _resolve_peripheral drills through Board proxies."""

    def test_resolve_direct_peripheral(self):
        """Direct peripheral is returned as-is."""
        spi = MockSTM32SPI()
        actual = MMIOTracer._resolve_peripheral(spi, 0x40013000)
        assert actual is spi

    def test_resolve_through_adapter(self):
        """Board with adapter drills down to actual peripheral."""
        spi = MockSTM32SPI()

        class MockAdapter:
            def find_peripheral(self, addr):
                if 0x40013000 <= addr < 0x40013400:
                    return spi
                return None

        class MockBoard:
            def __init__(self):
                self.adapter = MockAdapter()
                self.name = "TestBoard"

        board = MockBoard()
        actual = MMIOTracer._resolve_peripheral(board, 0x40013000)
        assert actual is spi
        assert actual.name == "SPI1"
