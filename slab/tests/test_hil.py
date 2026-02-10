"""
Unit tests for Hardware-in-the-Loop (HIL) peripherals.

Tests HILTCPPeripheral, HILOpenOCDPeripheral, HILSerialPeripheral,
create_hil_peripheral factory, and board_builder HIL integration.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import pytest

from slab_cortex_m.hil_peripheral import (
    HILTCPPeripheral,
    HILOpenOCDPeripheral,
    HILSerialPeripheral,
    HILPeripheral,
    HILResponse,
    HILStats,
    HILTraceRecord,
    HILTraceRecorder,
    HILReplayPeripheral,
    HILPyOCDSession,
    HILPyOCDRegion,
    create_hil_peripheral,
)


# =============================================================================
# MOCK HARDWARE SERVER
# =============================================================================

class MockHardwareServer:
    """TCP server that simulates real hardware for HIL tests."""

    def __init__(self, port: int):
        self.port = port
        self.server = None
        self.running = False
        self.registers = {
            0x40020000: 0xA8000000,  # GPIOA MODER
            0x40020004: 0x00000000,  # OTYPER
            0x40020014: 0x00000000,  # ODR
            0x40020018: 0x00000000,  # BSRR
        }

    async def handle_client(self, reader, writer):
        try:
            while self.running:
                cmd = await reader.read(1)
                if not cmd:
                    break

                if cmd == b'R':
                    data = await reader.read(9)
                    if len(data) < 9:
                        break
                    addr_val, size, secure = struct.unpack('<IIB', data)
                    value = self.registers.get(addr_val, 0)
                    writer.write(struct.pack('<IB', value, 0))
                    await writer.drain()

                elif cmd == b'W':
                    data = await reader.read(13)
                    if len(data) < 13:
                        break
                    addr_val, size, value, secure = struct.unpack('<IIIB', data)
                    self.registers[addr_val] = value
                    # BSRR logic
                    if addr_val == 0x40020018:
                        odr = self.registers.get(0x40020014, 0)
                        odr = (odr | (value & 0xFFFF)) & ~((value >> 16) & 0xFFFF)
                        self.registers[0x40020014] = odr
                    writer.write(struct.pack('<IB', value, 0))
                    await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def start(self):
        self.running = True
        self.server = await asyncio.start_server(
            self.handle_client, 'localhost', self.port)

    async def stop(self):
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()


# =============================================================================
# HILPeripheral BASE
# =============================================================================

class TestHILStats:

    def test_avg_latency_zero_ops(self):
        stats = HILStats()
        assert stats.avg_latency_ms == 0.0

    def test_avg_latency(self):
        stats = HILStats(reads=5, writes=5, total_latency_ms=100.0)
        assert stats.avg_latency_ms == 10.0


class TestHILPeripheralBase:

    def test_contains(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=9999)
        assert hil.contains(0x40020000)
        assert hil.contains(0x400203FF)
        assert not hil.contains(0x40020400)
        assert not hil.contains(0x4001FFFF)

    def test_check_security(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=9999)
        assert hil.check_security(True)
        assert hil.check_security(False)

    def test_set_irq_callback(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=9999, irq=25)
        calls = []
        hil.set_irq_callback(lambda irq, level: calls.append((irq, level)))
        hil.trigger_irq(1)
        assert calls == [(25, 1)]

    def test_trigger_irq_no_callback(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=9999, irq=25)
        # Should not raise
        hil.trigger_irq(1)

    def test_trigger_irq_no_irq(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=9999)
        assert hil.irq == -1
        calls = []
        hil.set_irq_callback(lambda irq, level: calls.append((irq, level)))
        hil.trigger_irq(1)
        assert calls == []  # No IRQ assigned


# =============================================================================
# TCP HIL PERIPHERAL
# =============================================================================

class TestHILTCPPeripheral:

    @pytest.mark.asyncio
    async def test_basic_read_write(self):
        mock_hw = MockHardwareServer(port=15001)
        await mock_hw.start()
        await asyncio.sleep(0.05)

        try:
            hil = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=15001)
            assert await hil.connect()

            value = await hil.read(0x40020000, 4)
            assert value == 0xA8000000

            await hil.write(0x40020014, 4, 0x00FF)
            value = await hil.read(0x40020014, 4)
            assert value == 0x00FF

            assert hil.stats.reads == 2
            assert hil.stats.writes == 1

            await hil.disconnect()
        finally:
            await mock_hw.stop()

    @pytest.mark.asyncio
    async def test_bsrr_operation(self):
        mock_hw = MockHardwareServer(port=15002)
        await mock_hw.start()
        await asyncio.sleep(0.05)

        try:
            hil = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=15002)
            assert await hil.connect()

            await hil.write(0x40020018, 4, 0x000F)   # Set bits 0-3
            value = await hil.read(0x40020014, 4)
            assert value == 0x000F

            await hil.write(0x40020018, 4, 0x00030030)  # Reset 0-1, set 4-5
            value = await hil.read(0x40020014, 4)
            assert value == 0x003C

            await hil.disconnect()
        finally:
            await mock_hw.stop()

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400,
                               port=15099, timeout=0.1)
        result = await hil.connect()
        assert not result
        assert not hil.connected

    @pytest.mark.asyncio
    async def test_read_not_connected(self):
        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=15099)
        hil.auto_reconnect = False
        value = await hil.read(0x40020000, 4)
        assert value == 0xDEADBEEF


# =============================================================================
# FACTORY
# =============================================================================

class TestCreateHILPeripheral:

    def test_create_tcp(self):
        hil = create_hil_peripheral({
            'name': 'GPIOA_HIL',
            'base': '0x40020000',
            'size': '0x400',
            'backend': 'tcp',
            'host': 'localhost',
            'port': 5001,
        })
        assert isinstance(hil, HILTCPPeripheral)
        assert hil.name == 'GPIOA_HIL'
        assert hil.base == 0x40020000
        assert hil.size == 0x400

    def test_create_openocd(self):
        hil = create_hil_peripheral({
            'name': 'GPIOB_HIL',
            'base': '0x40020400',
            'size': '0x400',
            'backend': 'openocd',
            'port': 6666,
        })
        assert isinstance(hil, HILOpenOCDPeripheral)
        assert hil.port == 6666

    def test_create_serial(self):
        hil = create_hil_peripheral({
            'name': 'GPIOC_HIL',
            'base': '0x40020800',
            'size': '0x400',
            'backend': 'serial',
            'serial_port': '/dev/ttyUSB0',
            'baudrate': 115200,
        })
        assert isinstance(hil, HILSerialPeripheral)
        assert hil.serial_port == '/dev/ttyUSB0'
        assert hil.baudrate == 115200

    def test_create_default_tcp(self):
        hil = create_hil_peripheral({
            'name': 'TEST',
            'base': '0x40000000',
            'size': '0x1000',
        })
        assert isinstance(hil, HILTCPPeripheral)

    def test_create_with_irq(self):
        hil = create_hil_peripheral({
            'name': 'TEST',
            'base': '0x40000000',
            'size': '0x1000',
            'irq': 25,
        })
        assert hil.irq == 25


# =============================================================================
# BOARD BUILDER INTEGRATION
# =============================================================================

class TestBoardHIL:

    def test_board_hil_peripherals_list(self):
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import Board
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

        class FakePSet:
            peripherals = []

        config = BoardConfig(name="test", mcu="STM32F405")
        adapter = PeripheralSetAdapter(FakePSet())
        board = Board(config, adapter)
        assert board.hil_peripherals == []

    def test_board_find_peripheral_hil_override(self):
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import Board
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

        class FakePSet:
            peripherals = []

        config = BoardConfig(name="test", mcu="STM32F405")
        adapter = PeripheralSetAdapter(FakePSet())
        board = Board(config, adapter)

        # Add HIL peripheral
        hil = HILTCPPeripheral("GPIOA_HIL", 0x40020000, 0x400, port=9999)
        board.hil_peripherals.append(hil)

        # find_peripheral should return HIL first
        found = board.find_peripheral(0x40020000)
        assert found is hil

        # contains should include HIL range
        assert board.contains(0x40020000)

    def test_board_contains_hil(self):
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import Board
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

        class FakePSet:
            peripherals = []

        config = BoardConfig(name="test", mcu="STM32F405")
        adapter = PeripheralSetAdapter(FakePSet())
        board = Board(config, adapter)

        assert not board.contains(0x40020000)

        hil = HILTCPPeripheral("TEST", 0x40020000, 0x400, port=9999)
        board.hil_peripherals.append(hil)

        assert board.contains(0x40020000)
        assert board.contains(0x400203FF)
        assert not board.contains(0x40020400)


# =============================================================================
# HIL TRACE RECORD
# =============================================================================

class TestHILTraceRecord:

    def test_to_dict(self):
        rec = HILTraceRecord(
            sequence=1, timestamp=0.001, is_write=False,
            address=0x40020000, size=4, value=0xA8000000,
            latency_ms=1.5, success=True, peripheral_name="GPIOA",
        )
        d = rec.to_dict()
        assert d['seq'] == 1
        assert d['rw'] == 'R'
        assert d['addr'] == '0x40020000'
        assert d['value'] == '0xA8000000'
        assert d['ok'] is True

    def test_from_dict(self):
        d = {
            'seq': 2, 'ts': 0.5, 'rw': 'W',
            'addr': '0x40020014', 'size': 4,
            'value': '0x000000FF', 'latency_ms': 2.0,
            'ok': True, 'periph': 'GPIOA',
        }
        rec = HILTraceRecord.from_dict(d)
        assert rec.sequence == 2
        assert rec.is_write is True
        assert rec.address == 0x40020014
        assert rec.value == 0xFF

    def test_roundtrip(self):
        rec = HILTraceRecord(
            sequence=3, timestamp=1.0, is_write=True,
            address=0x50060000, size=4, value=0xDEADBEEF,
        )
        d = rec.to_dict()
        rec2 = HILTraceRecord.from_dict(d)
        assert rec2.address == rec.address
        assert rec2.value == rec.value
        assert rec2.is_write == rec.is_write


# =============================================================================
# HIL TRACE RECORDER
# =============================================================================

class TestHILTraceRecorder:

    @pytest.mark.asyncio
    async def test_record_read_write(self):
        mock_hw = MockHardwareServer(port=15003)
        await mock_hw.start()
        await asyncio.sleep(0.05)

        try:
            hil = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=15003)
            recorder = HILTraceRecorder(hil)

            assert await hil.connect()

            # Read through recorder
            value = await recorder.read(0x40020000, 4)
            assert value == 0xA8000000

            # Write through recorder
            await recorder.write(0x40020014, 4, 0xAA)

            # Read back
            await recorder.read(0x40020014, 4)

            assert len(recorder.records) == 3
            assert recorder.records[0].is_write is False
            assert recorder.records[0].address == 0x40020000
            assert recorder.records[1].is_write is True
            assert recorder.records[1].value == 0xAA
            assert recorder.records[2].is_write is False

            await hil.disconnect()
        finally:
            await mock_hw.stop()

    @pytest.mark.asyncio
    async def test_save_load(self, tmp_path):
        mock_hw = MockHardwareServer(port=15004)
        await mock_hw.start()
        await asyncio.sleep(0.05)

        try:
            hil = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=15004)
            recorder = HILTraceRecorder(hil)
            assert await hil.connect()

            await recorder.read(0x40020000, 4)
            await recorder.write(0x40020014, 4, 0x55)

            trace_file = str(tmp_path / "trace.jsonl")
            recorder.save(trace_file)

            loaded = HILTraceRecorder.load(trace_file)
            assert len(loaded) == 2
            assert loaded[0].address == 0x40020000
            assert loaded[1].value == 0x55

            await hil.disconnect()
        finally:
            await mock_hw.stop()

    def test_recorder_properties(self):
        hil = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=9999)
        recorder = HILTraceRecorder(hil)
        assert recorder.name == "GPIOA"
        assert recorder.base == 0x40020000
        assert recorder.size == 0x400
        assert recorder.contains(0x40020000)
        assert not recorder.contains(0x40030000)

    def test_reset(self):
        hil = HILTCPPeripheral("GPIOA", 0x40020000, 0x400, port=9999)
        recorder = HILTraceRecorder(hil)
        recorder.records.append(HILTraceRecord(
            1, 0.0, False, 0x40020000, 4, 0, peripheral_name="GPIOA"))
        assert len(recorder.records) == 1
        recorder.reset()
        assert len(recorder.records) == 0


# =============================================================================
# HIL REPLAY PERIPHERAL
# =============================================================================

class TestHILReplayPeripheral:

    @pytest.mark.asyncio
    async def test_replay_read(self):
        records = [
            HILTraceRecord(1, 0.0, False, 0x40020000, 4, 0xA8000000),
            HILTraceRecord(2, 0.1, True, 0x40020014, 4, 0x00FF),
            HILTraceRecord(3, 0.2, False, 0x40020014, 4, 0x00FF),
        ]
        replay = HILReplayPeripheral("GPIOA", 0x40020000, 0x400, records)
        assert await replay.connect()

        # Sequential read replay
        value = await replay.read(0x40020000, 4)
        assert value == 0xA8000000

        value = await replay.read(0x40020014, 4)
        assert value == 0x00FF

    @pytest.mark.asyncio
    async def test_replay_fallback_to_value_map(self):
        records = [
            HILTraceRecord(1, 0.0, False, 0x40020000, 4, 0x1234),
        ]
        replay = HILReplayPeripheral("TEST", 0x40020000, 0x400, records)
        await replay.connect()

        # First read: sequential match
        await replay.read(0x40020000, 4)
        # Second read: no more sequential records, falls back to value_map
        value = await replay.read(0x40020000, 4)
        assert value == 0x1234

    @pytest.mark.asyncio
    async def test_replay_write_updates_map(self):
        replay = HILReplayPeripheral("TEST", 0x40020000, 0x400, [])
        await replay.connect()

        await replay.write(0x40020014, 4, 0xBEEF)
        value = await replay.read(0x40020014, 4)
        assert value == 0xBEEF

    @pytest.mark.asyncio
    async def test_replay_rewind(self):
        records = [
            HILTraceRecord(1, 0.0, False, 0x40020000, 4, 0xAAAA),
        ]
        replay = HILReplayPeripheral("TEST", 0x40020000, 0x400, records)
        await replay.connect()

        value = await replay.read(0x40020000, 4)
        assert value == 0xAAAA

        replay.rewind()
        value = await replay.read(0x40020000, 4)
        assert value == 0xAAAA

    @pytest.mark.asyncio
    async def test_from_trace_file(self, tmp_path):
        import json
        trace_file = str(tmp_path / "test.jsonl")
        records = [
            {'seq': 1, 'ts': 0.0, 'rw': 'R', 'addr': '0x50060000',
             'size': 4, 'value': '0x00000001', 'latency_ms': 1.0,
             'ok': True, 'periph': 'CRYP'},
        ]
        with open(trace_file, 'w') as f:
            for r in records:
                f.write(json.dumps(r) + '\n')

        replay = HILReplayPeripheral.from_trace(trace_file)
        assert replay.name == "CRYP"
        assert replay.contains(0x50060000)
        await replay.connect()
        value = await replay.read(0x50060000, 4)
        assert value == 1

    def test_create_replay_via_factory(self, tmp_path):
        import json
        trace_file = str(tmp_path / "factory.jsonl")
        with open(trace_file, 'w') as f:
            f.write(json.dumps({
                'seq': 1, 'ts': 0.0, 'rw': 'R', 'addr': '0x40020000',
                'size': 4, 'value': '0x00000042', 'ok': True, 'periph': 'GPIO',
            }) + '\n')

        hil = create_hil_peripheral({
            'name': 'GPIO_REPLAY',
            'base': '0x40020000',
            'size': '0x400',
            'backend': 'replay',
            'trace_file': trace_file,
        })
        assert isinstance(hil, HILReplayPeripheral)


# =============================================================================
# MULTI-REGION SESSION SHARING
# =============================================================================

class TestHILPyOCDSession:

    def test_create_regions(self):
        session = HILPyOCDSession(target_type="stm32f439xi")
        cryp = session.create_region("CRYP", 0x50060000, 0x400)
        hash_ = session.create_region("HASH", 0x50060400, 0x400)

        assert isinstance(cryp, HILPyOCDRegion)
        assert isinstance(hash_, HILPyOCDRegion)
        assert len(session.regions) == 2
        assert cryp.shared_session is session
        assert hash_.shared_session is session

    def test_region_contains(self):
        session = HILPyOCDSession(target_type="stm32f439xi")
        cryp = session.create_region("CRYP", 0x50060000, 0x400)

        assert cryp.contains(0x50060000)
        assert cryp.contains(0x500603FF)
        assert not cryp.contains(0x50060400)

    def test_region_properties(self):
        session = HILPyOCDSession(target_type="stm32f439xi")
        cryp = session.create_region("CRYP", 0x50060000, 0x400, irq=79)

        assert cryp.name == "CRYP"
        assert cryp.base == 0x50060000
        assert cryp.size == 0x400
        assert cryp.irq == 79

    def test_create_shared_via_factory(self):
        from slab_cortex_m.hil_peripheral import _pyocd_sessions
        # Clear session registry
        _pyocd_sessions.clear()

        hil1 = create_hil_peripheral({
            'name': 'CRYP_HIL',
            'base': '0x50060000',
            'size': '0x400',
            'backend': 'pyocd',
            'target_type': 'stm32f439xi',
            'shared_session': True,
        })
        hil2 = create_hil_peripheral({
            'name': 'HASH_HIL',
            'base': '0x50060400',
            'size': '0x400',
            'backend': 'pyocd',
            'target_type': 'stm32f439xi',
            'shared_session': True,
        })

        assert isinstance(hil1, HILPyOCDRegion)
        assert isinstance(hil2, HILPyOCDRegion)
        # Both share the same session
        assert hil1.shared_session is hil2.shared_session
        assert len(hil1.shared_session.regions) == 2

        _pyocd_sessions.clear()
