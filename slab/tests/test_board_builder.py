#!/usr/bin/env python3
"""
Tests for board.py, peripheral_adapter.py, board_builder.py, and ci_runner.py

Run with: pytest tests/test_board_builder.py -v

SPDX-License-Identifier: Apache-2.0
Copyright (C) 2026 TwistedWires Security Lab
"""

import sys
import os
import json
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))


# =============================================================================
# BOARD CONFIG TESTS
# =============================================================================

class TestBoardConfig(unittest.TestCase):
    """Test board configuration loading and MCU registry."""

    def test_mcu_registry_completeness(self):
        """All MCU registry entries must be importable."""
        from slab_cortex_m.board import MCU_REGISTRY
        import importlib
        for mcu, (pkg, cls_name, cpu, clock) in MCU_REGISTRY.items():
            mod = importlib.import_module(pkg)
            cls = getattr(mod, cls_name, None)
            self.assertIsNotNone(cls, f"Missing {pkg}.{cls_name} for MCU {mcu}")

    def test_mcu_registry_cpu_types(self):
        """All CPU types should be valid Cortex-M variants."""
        from slab_cortex_m.board import MCU_REGISTRY
        valid_cpus = {'cortex-m0', 'cortex-m0+', 'cortex-m3', 'cortex-m4',
                      'cortex-m7', 'cortex-m23', 'cortex-m33', 'cortex-m55'}
        for mcu, (_, _, cpu, _) in MCU_REGISTRY.items():
            self.assertIn(cpu, valid_cpus, f"Invalid CPU '{cpu}' for {mcu}")

    def test_load_board_yaml(self):
        """Test loading a YAML board config."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")

        from slab_cortex_m.board import load_board_config
        with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
            f.write("""
name: TestBoard
mcu: STM32F405
clock: 168000000
external_devices:
  - type: LED
    bus: GPIOA
    params: {pin: 5, color: green}
""")
            f.flush()
            config = load_board_config(f.name)
        os.unlink(f.name)

        self.assertEqual(config.name, "TestBoard")
        self.assertEqual(config.mcu, "STM32F405")
        self.assertEqual(config.clock, 168_000_000)
        self.assertEqual(len(config.external_devices), 1)
        self.assertEqual(config.external_devices[0].type, "LED")
        self.assertEqual(config.external_devices[0].bus, "GPIOA")
        self.assertEqual(config.external_devices[0].params['pin'], 5)

    def test_load_board_json(self):
        """Test loading a JSON board config."""
        from slab_cortex_m.board import load_board_config
        with tempfile.NamedTemporaryFile(suffix='.json', mode='w', delete=False) as f:
            json.dump({
                "name": "TestBoardJSON",
                "mcu": "nRF52840",
                "external_devices": []
            }, f)
            f.flush()
            config = load_board_config(f.name)
        os.unlink(f.name)

        self.assertEqual(config.name, "TestBoardJSON")
        self.assertEqual(config.mcu, "nRF52840")

    def test_load_board_with_usb(self):
        """Test USB config parsing."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")

        from slab_cortex_m.board import load_board_config
        with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
            f.write("""
name: USBBoard
mcu: STM32F405
usb:
  type: dwc2_otg_fs
  base: 0x50000000
  irq: 67
external_devices: []
""")
            f.flush()
            config = load_board_config(f.name)
        os.unlink(f.name)

        self.assertIsNotNone(config.usb)
        self.assertEqual(config.usb.type, "dwc2_otg_fs")
        self.assertEqual(config.usb.base, 0x50000000)
        self.assertEqual(config.usb.irq, 67)

    def test_create_peripheral_set(self):
        """Test dynamic peripheral set creation."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        config = BoardConfig(name="Test", mcu="STM32F405")
        pset = create_peripheral_set(config)
        self.assertTrue(hasattr(pset, 'peripherals'))
        self.assertGreater(len(pset.peripherals), 0)

    def test_create_peripheral_set_unknown_mcu(self):
        """Unknown MCU should raise ValueError."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        config = BoardConfig(name="Test", mcu="UNKNOWN_MCU")
        with self.assertRaises(ValueError):
            create_peripheral_set(config)

    def test_get_qemu_cpu(self):
        """Test CPU type resolution."""
        from slab_cortex_m.board import BoardConfig, get_qemu_cpu
        config = BoardConfig(name="Test", mcu="STM32F405")
        self.assertEqual(get_qemu_cpu(config), "cortex-m4")

        config = BoardConfig(name="Test", mcu="STM32H563")
        self.assertEqual(get_qemu_cpu(config), "cortex-m33")

        # Override
        config = BoardConfig(name="Test", mcu="STM32F405", qemu_cpu="cortex-m7")
        self.assertEqual(get_qemu_cpu(config), "cortex-m7")

    def test_get_default_clock(self):
        """Test clock frequency resolution."""
        from slab_cortex_m.board import BoardConfig, get_default_clock
        config = BoardConfig(name="Test", mcu="STM32F405")
        self.assertEqual(get_default_clock(config), 168_000_000)

        # Explicit clock overrides default
        config = BoardConfig(name="Test", mcu="STM32F405", clock=84_000_000)
        self.assertEqual(get_default_clock(config), 84_000_000)


# =============================================================================
# PERIPHERAL ADAPTER TESTS
# =============================================================================

class TestPeripheralAdapter(unittest.TestCase):
    """Test peripheral set adapter interface normalization."""

    def test_stm32_adapter(self):
        """STM32 adapter wraps read/write correctly."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        config = BoardConfig(name="Test", mcu="STM32F405")
        pset = create_peripheral_set(config)
        adapter = PeripheralSetAdapter(pset)

        self.assertEqual(adapter.family, 'stm32')
        self.assertGreater(len(adapter.peripherals), 0)

        # GPIOA at 0x40020000 -- MODER register
        self.assertTrue(adapter.contains(0x40020000))
        val, status = adapter.read(0x40020000, 4)
        self.assertEqual(status, 0)
        status = adapter.write(0x40020000, 4, 0x55555555)
        self.assertEqual(status, 0)
        val, status = adapter.read(0x40020000, 4)
        self.assertEqual(val, 0x55555555)

    def test_nrf_adapter(self):
        """nRF adapter wraps read/write (raw int returns) to tuples."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        config = BoardConfig(name="Test", mcu="nRF52840")
        pset = create_peripheral_set(config)
        adapter = PeripheralSetAdapter(pset)

        self.assertEqual(adapter.family, 'nrf')
        self.assertGreater(len(adapter.peripherals), 0)

    def test_nxp_adapter(self):
        """NXP adapter wraps correctly."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        config = BoardConfig(name="Test", mcu="LPC55S69")
        pset = create_peripheral_set(config)
        adapter = PeripheralSetAdapter(pset)

        self.assertEqual(adapter.family, 'nxp')
        self.assertGreater(len(adapter.peripherals), 0)

    def test_rp2040_adapter(self):
        """RP2040 adapter wraps correctly."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        config = BoardConfig(name="Test", mcu="RP2040")
        pset = create_peripheral_set(config)
        adapter = PeripheralSetAdapter(pset)

        self.assertEqual(adapter.family, 'rp2040')
        self.assertGreater(len(adapter.peripherals), 0)

    def test_unmapped_address(self):
        """Unmapped address returns (0, STATUS_OK)."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        config = BoardConfig(name="Test", mcu="STM32F405")
        pset = create_peripheral_set(config)
        adapter = PeripheralSetAdapter(pset)

        self.assertFalse(adapter.contains(0xDEADBEEF))
        val, status = adapter.read(0xDEADBEEF, 4)
        self.assertEqual(val, 0)
        self.assertEqual(status, 0)

    def test_irq_callback(self):
        """IRQ callback propagation."""
        from slab_cortex_m.board import BoardConfig, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
        config = BoardConfig(name="Test", mcu="STM32F405")
        pset = create_peripheral_set(config)
        adapter = PeripheralSetAdapter(pset)

        irqs = []
        adapter.irq_callback = lambda irq, level: irqs.append((irq, level))
        self.assertIsNotNone(adapter.irq_callback)


# =============================================================================
# BOARD BUILDER TESTS
# =============================================================================

class TestBoardBuilder(unittest.TestCase):
    """Test board building from config."""

    def test_build_simple_board(self):
        """Build a board with no external devices."""
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(name="Simple", mcu="STM32F405")
        board = build_board(config)

        self.assertEqual(board.name, "Simple")
        self.assertEqual(board.qemu_cpu, "cortex-m4")
        self.assertEqual(board.clock, 168_000_000)
        self.assertEqual(len(board.external_devices), 0)

    def test_build_board_with_led(self):
        """Build a board with LED (observation-only, no device object)."""
        from slab_cortex_m.board import BoardConfig, ExternalDevice
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(
            name="LEDBoard", mcu="STM32F405",
            external_devices=[ExternalDevice("LED", "GPIOA", {"pin": 5})]
        )
        board = build_board(config)
        # LED creates no device object
        self.assertEqual(len(board.external_devices), 0)

    def test_build_board_with_spi_flash(self):
        """Build a board with W25Q128 SPI flash."""
        from slab_cortex_m.board import BoardConfig, ExternalDevice
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(
            name="FlashBoard", mcu="STM32F405",
            external_devices=[ExternalDevice("W25Q128", "SPI1")]
        )
        board = build_board(config)
        self.assertEqual(len(board.external_devices), 1)
        self.assertEqual(board.external_devices[0].__class__.__name__, 'W25QxxFlash')

    def test_build_board_with_eeprom(self):
        """Build a board with I2C EEPROM."""
        from slab_cortex_m.board import BoardConfig, ExternalDevice
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(
            name="EEPROMBoard", mcu="STM32F405",
            external_devices=[ExternalDevice("24C256", "I2C1", {"address": 0x50})]
        )
        board = build_board(config)
        self.assertEqual(len(board.external_devices), 1)
        self.assertEqual(board.external_devices[0].__class__.__name__, 'EEPROM_24Cxx')

    def test_board_read_write_interface(self):
        """Board read/write must accept (addr, size, secure) signature."""
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(name="Test", mcu="STM32F405")
        board = build_board(config)

        # Write GPIOA MODER
        status = board.write(0x40020000, 4, 0xAAAAAAAA, False)
        self.assertEqual(status, 0)
        val, status = board.read(0x40020000, 4, False)
        self.assertEqual(val, 0xAAAAAAAA)
        self.assertEqual(status, 0)

    def test_board_contains(self):
        """Board.contains() delegates to adapter."""
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(name="Test", mcu="STM32F405")
        board = build_board(config)

        self.assertTrue(board.contains(0x40020000))  # GPIOA
        self.assertFalse(board.contains(0xDEADBEEF))

    def test_board_irq_callback(self):
        """Board IRQ callback property."""
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import build_board
        config = BoardConfig(name="Test", mcu="STM32F405")
        board = build_board(config)

        cb = lambda irq, level: None
        board.irq_callback = cb
        self.assertEqual(board.irq_callback, cb)

    def test_build_all_board_yamls(self):
        """All board YAML files in slab/boards/ should build successfully."""
        from slab_cortex_m.board import load_board_config
        from slab_cortex_m.board_builder import build_board
        boards_dir = Path(__file__).parent.parent / 'boards'
        if not boards_dir.exists():
            self.skipTest("slab/boards/ not found")

        for yaml_file in sorted(boards_dir.glob('*.yaml')):
            with self.subTest(board=yaml_file.name):
                config = load_board_config(str(yaml_file))
                board = build_board(config)
                self.assertGreater(len(board.adapter.peripherals), 0)


# =============================================================================
# ADAPTER FAMILY DETECTION
# =============================================================================

class TestAdapterFamilyDetection(unittest.TestCase):
    """Test that family auto-detection works for all MCU families."""

    def test_all_families(self):
        """Each MCU family should be detected correctly."""
        from slab_cortex_m.board import BoardConfig, MCU_REGISTRY, create_peripheral_set
        from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

        expected = {
            'STM32F405': 'stm32',
            'nRF52840': 'nrf',
            'LPC55S69': 'nxp',
            'RP2040': 'rp2040',
        }
        for mcu, expected_family in expected.items():
            with self.subTest(mcu=mcu):
                config = BoardConfig(name="Test", mcu=mcu)
                pset = create_peripheral_set(config)
                adapter = PeripheralSetAdapter(pset)
                self.assertEqual(adapter.family, expected_family)


# =============================================================================
# CI RUNNER DATA STRUCTURES
# =============================================================================

class TestCIRunnerDataStructures(unittest.TestCase):
    """Test CI runner data structures and output formatting."""

    def test_scenario_creation(self):
        """Test Scenario dataclass."""
        from slab_cortex_m.ci_runner import Scenario, Assertion
        s = Scenario(
            name="Test",
            board="board.yaml",
            firmware="test.bin",
            timeout=10,
            assertions=[Assertion("no_crash"), Assertion("gpio_toggle", {"pin": 5})]
        )
        self.assertEqual(s.name, "Test")
        self.assertEqual(len(s.assertions), 2)

    def test_results_to_json(self):
        """Test JSON output format."""
        from slab_cortex_m.ci_runner import ScenarioResult, AssertionResult, results_to_json
        results = [ScenarioResult(
            scenario="Test1",
            passed=True,
            duration=1.5,
            assertions=[AssertionResult("no_crash", True, "exit=0")],
            qemu_exit_code=0,
            mmio_count=100,
        )]
        out = json.loads(results_to_json(results))
        self.assertEqual(out['total'], 1)
        self.assertEqual(out['passed'], 1)
        self.assertEqual(out['failed'], 0)

    def test_results_to_junit(self):
        """Test JUnit XML output."""
        from slab_cortex_m.ci_runner import ScenarioResult, AssertionResult, results_to_junit
        results = [
            ScenarioResult("Pass", True, 1.0, [AssertionResult("no_crash", True)]),
            ScenarioResult("Fail", False, 2.0,
                           [AssertionResult("gpio_toggle", False, "toggles=0")]),
        ]
        xml = results_to_junit(results)
        self.assertIn('<?xml', xml)
        self.assertIn('testsuite', xml)
        self.assertIn('tests="2"', xml)
        self.assertIn('failures="1"', xml)

    def test_load_scenarios_yaml(self):
        """Test YAML scenario loading."""
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")

        from slab_cortex_m.ci_runner import load_scenarios
        with tempfile.NamedTemporaryFile(suffix='.yaml', mode='w', delete=False) as f:
            f.write("""
scenarios:
  - name: "Test Scenario"
    board: slab/boards/stm32f405_hello_blink.yaml
    firmware: test.bin
    timeout: 5
    assertions:
      - type: no_crash
      - type: mmio_count
        params: {min: 10}
""")
            f.flush()
            scenarios = load_scenarios(f.name)
        os.unlink(f.name)

        self.assertEqual(len(scenarios), 1)
        self.assertEqual(scenarios[0].name, "Test Scenario")
        self.assertEqual(scenarios[0].timeout, 5)
        self.assertEqual(len(scenarios[0].assertions), 2)

    def test_assertion_checkers(self):
        """Test individual assertion checker functions."""
        from slab_cortex_m.ci_runner import (
            ScenarioResult, AssertionResult,
            check_no_crash, check_mmio_count,
        )

        # no_crash: exit code 0
        r = ScenarioResult("t", True, 0, qemu_exit_code=0)
        res = check_no_crash(r, {})
        self.assertTrue(res.passed)

        # no_crash: exit code 1 (crash)
        r = ScenarioResult("t", True, 0, qemu_exit_code=1)
        res = check_no_crash(r, {})
        self.assertFalse(res.passed)

        # no_crash: exit code 124 (timeout kill -- normal)
        r = ScenarioResult("t", True, 0, qemu_exit_code=124)
        res = check_no_crash(r, {})
        self.assertTrue(res.passed)

    def test_ci_board_server_find_peripheral(self):
        """CIBoardServer.find_peripheral returns board proxy, not raw peripheral."""
        from slab_cortex_m.board import BoardConfig
        from slab_cortex_m.board_builder import build_board
        from slab_cortex_m.ci_runner import CIBoardServer

        config = BoardConfig(name="Test", mcu="STM32F405")
        board = build_board(config)
        server = CIBoardServer(board, 0)

        # Mapped address -> returns board (which has read/write/contains)
        result = server.find_peripheral(0x40020000)
        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'read'))
        self.assertTrue(hasattr(result, 'write'))
        self.assertTrue(hasattr(result, 'contains'))
        self.assertEqual(server.mmio_count, 1)

        # Unmapped address -> None
        result = server.find_peripheral(0xDEADBEEF)
        self.assertIsNone(result)
        self.assertEqual(server.mmio_count, 1)  # unchanged


if __name__ == '__main__':
    unittest.main()
