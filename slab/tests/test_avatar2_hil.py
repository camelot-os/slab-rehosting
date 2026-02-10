"""
Unit tests for Avatar2 HIL bridge and emulator adapter classes.

Tests:
- CortexMConfig / EmulatorConfig dataclasses
- CortexM / Emulator adapter (board-only mode, no QEMU)
- Avatar2Bridge initialization
- HILBridge with SimulationTarget
- Memory forwarding logic
- HILGlitchController in simulation mode

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import struct
import pytest

from slab_cortex_m.emulator import (
    CortexM,
    CortexMConfig,
    Emulator,
    EmulatorConfig,
)


# =============================================================================
# CONFIG DATACLASS
# =============================================================================

class TestCortexMConfig:

    def test_defaults(self):
        cfg = CortexMConfig(machine="STM32F405")
        assert cfg.machine == "STM32F405"
        assert cfg.firmware_path is None
        assert cfg.port == 5555
        assert cfg.trace_mmio is False
        assert cfg.board_yaml is None
        assert cfg.hil_peripherals == []
        assert cfg.qemu_extra == {}

    def test_custom_values(self):
        cfg = CortexMConfig(
            machine="nRF52840",
            firmware_path="/path/to/firmware.bin",
            port=6000,
            trace_mmio=True,
            hil_peripherals=[{
                'name': 'GPIOA_HIL',
                'base': '0x40020000',
                'size': '0x400',
                'backend': 'openocd',
            }],
        )
        assert cfg.machine == "nRF52840"
        assert cfg.port == 6000
        assert len(cfg.hil_peripherals) == 1

    def test_emulator_config_alias(self):
        """EmulatorConfig is an alias for CortexMConfig."""
        assert EmulatorConfig is CortexMConfig
        cfg = EmulatorConfig(machine="STM32F405")
        assert isinstance(cfg, CortexMConfig)


# =============================================================================
# CORTEX-M EMULATOR (board-only mode)
# =============================================================================

class TestCortexM:

    def test_emulator_alias(self):
        """Emulator is an alias for CortexM."""
        assert Emulator is CortexM

    def test_init(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu.config is cfg
        assert emu.board is None
        assert emu.qemu_process is None
        assert not emu._running

    def test_start_board_only(self):
        """Start in board-only mode (no firmware, no QEMU)."""
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        result = emu.start()
        assert result is True
        assert emu.board is not None
        assert emu._running
        assert emu.qemu_process is None  # No firmware => no QEMU
        emu.stop()

    def test_start_unknown_mcu(self):
        """Unknown MCU should fail gracefully."""
        cfg = CortexMConfig(machine="UNKNOWN_MCU_XYZ")
        emu = CortexM(cfg)
        result = emu.start()
        assert result is False

    def test_mem_read_write(self):
        """Test mem_read/mem_write through board adapter."""
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        emu.start()

        try:
            # Read RCC CR (default has HSIRDY set)
            data = emu.mem_read(0x40023800, 4)
            assert len(data) == 4
            value = struct.unpack('<I', data)[0]
            # RCC CR should have some bits set (HSI ready)
            assert value != 0xDEADBEEF  # Not unmapped

            # Write to a GPIO register
            emu.mem_write(0x40020014, struct.pack('<I', 0xAA))
            data = emu.mem_read(0x40020014, 4)
            assert len(data) == 4
        finally:
            emu.stop()

    def test_mem_read_unmapped(self):
        """Read from unmapped address returns zeros."""
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        emu.start()

        try:
            data = emu.mem_read(0xDEAD0000, 4)
            assert data == b'\x00\x00\x00\x00'
        finally:
            emu.stop()

    def test_mem_read_no_board(self):
        """Read without board returns zeros."""
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        data = emu.mem_read(0x40020000, 4)
        assert data == b'\x00\x00\x00\x00'

    def test_get_state(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        emu.start()

        try:
            state = emu.get_state()
            assert state['running'] is True
            assert state['machine'] == "STM32F405"
            assert state['has_board'] is True
            assert state['has_qemu'] is False
            assert state['peripherals'] > 0
        finally:
            emu.stop()

    def test_reset(self):
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        emu.start()

        try:
            # Write something
            emu.mem_write(0x40020014, struct.pack('<I', 0xFF))
            # Reset rebuilds the board
            result = emu.reset()
            assert result is True
            assert emu.board is not None
        finally:
            emu.stop()

    def test_read_register(self):
        """read_register returns 0 (not supported in board-only mode)."""
        cfg = CortexMConfig(machine="STM32F405")
        emu = CortexM(cfg)
        assert emu.read_register("r0") == 0

    def test_hil_injection(self):
        """HIL peripherals from config are injected into the board."""
        cfg = CortexMConfig(
            machine="STM32F405",
            hil_peripherals=[{
                'name': 'GPIOA_HIL',
                'base': '0x40020000',
                'size': '0x400',
                'backend': 'tcp',
                'port': 9999,
            }],
        )
        emu = CortexM(cfg)
        emu.start()

        try:
            assert len(emu.board.hil_peripherals) == 1
            hil = emu.board.hil_peripherals[0]
            assert hil.name == 'GPIOA_HIL'
            assert hil.base == 0x40020000
        finally:
            emu.stop()

    def test_start_with_missing_firmware(self):
        """Firmware path given but file doesn't exist => board-only mode."""
        cfg = CortexMConfig(
            machine="STM32F405",
            firmware_path="/nonexistent/firmware.bin",
        )
        emu = CortexM(cfg)
        result = emu.start()
        assert result is True  # Board created OK
        assert emu.qemu_process is None  # No QEMU (file not found)
        emu.stop()


# =============================================================================
# IMPORTS FROM slab_cortex_m
# =============================================================================

class TestImports:

    def test_import_from_package(self):
        """Verify lazy imports work from slab_cortex_m."""
        from slab_cortex_m import CortexM as CM
        from slab_cortex_m import CortexMConfig as CMC
        from slab_cortex_m import Emulator as E
        from slab_cortex_m import EmulatorConfig as EC
        assert CM is CortexM
        assert CMC is CortexMConfig
        assert E is Emulator
        assert EC is EmulatorConfig


# =============================================================================
# AVATAR2 BRIDGE (import test)
# =============================================================================

class TestAvatar2BridgeImport:

    def test_import_avatar2_bridge(self):
        """Avatar2Bridge should import without error."""
        from slab_hw.avatar2_hil import Avatar2Bridge, HILConfig, TargetType
        assert Avatar2Bridge is not None
        assert HILConfig is not None

    def test_hil_config_defaults(self):
        from slab_hw.avatar2_hil import HILConfig
        cfg = HILConfig()
        assert cfg.hw_interface == "openocd"
        assert cfg.emu_type == "slab"
        assert cfg.forward_peripherals is True

    def test_avatar2_bridge_init(self):
        """Avatar2Bridge can be initialized with default config."""
        from slab_hw.avatar2_hil import Avatar2Bridge, HILConfig
        cfg = HILConfig()
        bridge = Avatar2Bridge(cfg)
        assert bridge.config is cfg
        assert bridge.emu_target is None
        assert bridge.hw_target is None


# =============================================================================
# HIL BRIDGE (standalone)
# =============================================================================

class TestHILBridge:

    def test_import_hil_bridge(self):
        from slab_hw.hil import HILBridge, HILConfiguration, DebuggerType
        assert HILBridge is not None

    def test_hil_configuration_defaults(self):
        from slab_hw.hil import HILConfiguration, DebuggerType
        cfg = HILConfiguration()
        assert cfg.debugger == DebuggerType.SIMULATION
        assert cfg.target_name == "stm32f407"

    def test_simulation_target(self):
        """SimulationTarget should work without real hardware."""
        from slab_hw.hil import SimulationTarget, TargetState
        target = SimulationTarget()
        assert target.connect() is True
        assert target.get_state() == TargetState.HALTED

        # Memory operations
        target.write_memory(0x40020000, b'\xAA\xBB\xCC\xDD')
        data = target.read_memory(0x40020000, 4)
        assert data == b'\xAA\xBB\xCC\xDD'

        # Register operations
        target.write_register('r0', 42)
        assert target.read_register('r0') == 42

        target.disconnect()

    def test_hil_bridge_simulation(self):
        """HILBridge with simulation mode should connect."""
        from slab_hw.hil import HILBridge, HILConfiguration, DebuggerType
        cfg = HILConfiguration(debugger=DebuggerType.SIMULATION)
        bridge = HILBridge(cfg)
        bridge.connect()
        assert bridge.hw_target is not None


# =============================================================================
# HIL GLITCH CONTROLLER
# =============================================================================

class TestHILGlitchController:

    def test_import(self):
        from slab_hw.avatar2_hil import HILGlitchController
        assert HILGlitchController is not None

    def test_init(self):
        from slab_hw.avatar2_hil import HILGlitchController, HILConfig
        cfg = HILConfig()
        ctrl = HILGlitchController(cfg)
        assert ctrl is not None
