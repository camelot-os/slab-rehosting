"""
Tests for GDB stub integration in CortexM emulator.

All tests use mocking -- no real QEMU or GDB connection needed.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from slab_cortex_m.emulator import CortexM, CortexMConfig


class TestCortexMConfigGDB:
    """Tests for gdb_port field on CortexMConfig."""

    def test_gdb_port_default_disabled(self):
        cfg = CortexMConfig(machine="STM32F405")
        assert cfg.gdb_port == 0

    def test_gdb_port_custom(self):
        cfg = CortexMConfig(machine="STM32F405", gdb_port=1234)
        assert cfg.gdb_port == 1234


class TestQEMUGDBArgs:
    """Tests that QEMU is launched with -gdb flag when gdb_port is set."""

    @patch("slab_cortex_m.emulator.subprocess.Popen")
    def test_qemu_args_include_gdb(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=42)

        cfg = CortexMConfig(machine="STM32F405", gdb_port=1234)
        emu = CortexM(cfg)

        # Provide a fake board so _start_server_and_qemu runs
        fake_board = MagicMock()
        fake_board.qemu_cpu = "cortex-m4"
        fake_board.clock = 168000000
        fake_board.contains.return_value = False
        emu.board = fake_board

        with patch("slab_cortex_m.emulator.asyncio"), \
             patch("slab_cortex_m.emulator.threading"), \
             patch("time.sleep"), \
             patch("slab_hw.hil.GDBTarget") as mock_gdb_cls:
            mock_gdb = MagicMock()
            mock_gdb.connect.return_value = True
            mock_gdb_cls.return_value = mock_gdb

            emu._start_server_and_qemu("/tmp/fake.bin")

        # Verify QEMU was called with -gdb tcp::1234
        args = mock_popen.call_args[0][0]
        assert "-gdb" in args
        gdb_idx = args.index("-gdb")
        assert args[gdb_idx + 1] == "tcp::1234"

    @patch("slab_cortex_m.emulator.subprocess.Popen")
    def test_qemu_args_no_gdb_when_disabled(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=42)

        cfg = CortexMConfig(machine="STM32F405", gdb_port=0)
        emu = CortexM(cfg)

        fake_board = MagicMock()
        fake_board.qemu_cpu = "cortex-m4"
        fake_board.clock = 168000000
        emu.board = fake_board

        with patch("slab_cortex_m.emulator.asyncio"), \
             patch("slab_cortex_m.emulator.threading"):
            emu._start_server_and_qemu("/tmp/fake.bin")

        args = mock_popen.call_args[0][0]
        assert "-gdb" not in args


class TestGDBDelegation:
    """Tests that CortexM methods delegate to GDBTarget when connected."""

    def _make_emu_with_gdb(self):
        cfg = CortexMConfig(machine="STM32F405", gdb_port=1234)
        emu = CortexM(cfg)
        emu._gdb = MagicMock()
        return emu

    def test_read_register_delegates(self):
        emu = self._make_emu_with_gdb()
        emu._gdb.read_register.return_value = 0x0800_0100
        assert emu.read_register("pc") == 0x0800_0100
        emu._gdb.read_register.assert_called_once_with("pc")

    def test_read_register_returns_zero_without_gdb(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu.read_register("pc") == 0

    def test_write_register_delegates(self):
        emu = self._make_emu_with_gdb()
        emu.write_register("r0", 42)
        emu._gdb.write_register.assert_called_once_with("r0", 42)

    def test_write_register_noop_without_gdb(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        emu.write_register("r0", 42)  # should not raise

    def test_halt_delegates(self):
        emu = self._make_emu_with_gdb()
        emu.halt()
        emu._gdb.halt.assert_called_once()

    def test_halt_noop_without_gdb(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        emu.halt()  # should not raise

    def test_resume_delegates(self):
        emu = self._make_emu_with_gdb()
        emu.resume()
        emu._gdb.resume.assert_called_once()

    def test_step_delegates(self):
        emu = self._make_emu_with_gdb()
        emu._gdb.step.return_value = 0x0800_0104
        assert emu.step() == 0x0800_0104
        emu._gdb.step.assert_called_once()

    def test_step_returns_zero_without_gdb(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu.step() == 0

    def test_set_breakpoint_delegates(self):
        emu = self._make_emu_with_gdb()
        emu._gdb.set_breakpoint.return_value = True
        assert emu.set_breakpoint(0x0800_0100) is True
        emu._gdb.set_breakpoint.assert_called_once_with(0x0800_0100)

    def test_set_breakpoint_returns_false_without_gdb(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu.set_breakpoint(0x0800_0100) is False

    def test_remove_breakpoint_delegates(self):
        emu = self._make_emu_with_gdb()
        emu._gdb.remove_breakpoint.return_value = True
        assert emu.remove_breakpoint(0x0800_0100) is True
        emu._gdb.remove_breakpoint.assert_called_once_with(0x0800_0100)

    def test_remove_breakpoint_returns_false_without_gdb(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu.remove_breakpoint(0x0800_0100) is False


class TestGDBLifecycle:
    """Tests for GDB connect/disconnect in start/stop."""

    def test_stop_disconnects_gdb(self):
        cfg = CortexMConfig(machine="STM32F405", gdb_port=1234)
        emu = CortexM(cfg)
        emu._gdb = MagicMock()
        emu._running = True

        emu.stop()

        emu._gdb is None or emu._gdb.disconnect.assert_called_once()
        assert emu._gdb is None

    def test_stop_handles_gdb_disconnect_error(self):
        cfg = CortexMConfig(machine="STM32F405", gdb_port=1234)
        emu = CortexM(cfg)
        mock_gdb = MagicMock()
        mock_gdb.disconnect.side_effect = Exception("connection lost")
        emu._gdb = mock_gdb
        emu._running = True

        emu.stop()  # should not raise
        assert emu._gdb is None

    def test_init_gdb_is_none(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu._gdb is None
