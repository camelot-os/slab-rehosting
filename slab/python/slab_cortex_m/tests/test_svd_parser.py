#!/usr/bin/env python3
"""
Test suite for SVD parser.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import unittest
import os
import tempfile

from mcuemu_cortex_m import SVDParser


class TestSVDParser(unittest.TestCase):
    """Test SVD parsing functionality."""

    def test_parser_creation(self):
        """Test creating SVD parser."""
        parser = SVDParser()
        self.assertIsNotNone(parser)

    def test_parse_minimal_svd(self):
        """Test parsing minimal SVD file."""
        minimal_svd = """<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.1" xmlns:xs="http://www.w3.org/2001/XMLSchema-instance">
  <name>TestDevice</name>
  <version>1.0</version>
  <addressUnitBits>8</addressUnitBits>
  <width>32</width>
  <peripherals>
    <peripheral>
      <name>GPIOA</name>
      <baseAddress>0x40020000</baseAddress>
      <registers>
        <register>
          <name>ODR</name>
          <addressOffset>0x14</addressOffset>
          <size>32</size>
        </register>
      </registers>
    </peripheral>
  </peripherals>
</device>"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.svd', delete=False) as f:
            f.write(minimal_svd)
            f.flush()

            try:
                parser = SVDParser()
                device = parser.parse(f.name)

                self.assertEqual(device.name, "TestDevice")
                self.assertIn("GPIOA", [p.name for p in device.peripherals])
            finally:
                os.unlink(f.name)

    def test_register_access(self):
        """Test accessing registers from parsed SVD."""
        # This test assumes STM32F4 SVD is available
        # Skip if not present
        pass


class TestSVDPeripheral(unittest.TestCase):
    """Test SVD peripheral representation."""

    def test_peripheral_base_address(self):
        """Test peripheral base address handling."""
        from mcuemu_cortex_m.svd_parser import SVDPeripheral

        periph = SVDPeripheral(
            name="TEST",
            base_address=0x40000000,
            registers=[]
        )
        self.assertEqual(periph.base_address, 0x40000000)


def run_tests():
    """Run all SVD parser tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestSVDParser))
    suite.addTests(loader.loadTestsFromTestCase(TestSVDPeripheral))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return len(result.failures) == 0 and len(result.errors) == 0


if __name__ == '__main__':
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
