#!/usr/bin/env python3
"""
Test suite for async emulator core.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import unittest


class TestAsyncCore(unittest.TestCase):
    """Test async emulator core functionality."""

    def test_emulator_creation(self):
        """Test creating async emulator."""
        from mcuemu_cortex_m import AsyncEmulator

        emu = AsyncEmulator()
        self.assertIsNotNone(emu)

    def test_emulator_state(self):
        """Test emulator state enum."""
        from mcuemu_cortex_m import EmulatorState

        self.assertIsNotNone(EmulatorState.STOPPED)
        self.assertIsNotNone(EmulatorState.RUNNING)


def run_tests():
    """Run all async core tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestAsyncCore))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return len(result.failures) == 0 and len(result.errors) == 0


if __name__ == '__main__':
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
