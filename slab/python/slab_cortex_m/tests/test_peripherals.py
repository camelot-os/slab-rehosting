#!/usr/bin/env python3
"""
Test suite for virtual peripherals.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import unittest


class TestPeripherals(unittest.TestCase):
    """Test virtual peripheral functionality."""

    def test_virtual_led(self):
        """Test virtual LED component."""
        from mcuemu_cortex_m import VirtualLED

        led = VirtualLED(pin=0)
        self.assertFalse(led.state)
        led.on()
        self.assertTrue(led.state)
        led.off()
        self.assertFalse(led.state)

    def test_virtual_button(self):
        """Test virtual button component."""
        from mcuemu_cortex_m import VirtualButton

        button = VirtualButton(pin=0)
        self.assertFalse(button.pressed)
        button.press()
        self.assertTrue(button.pressed)
        button.release()
        self.assertFalse(button.pressed)

    def test_virtual_uart(self):
        """Test virtual UART component."""
        from mcuemu_cortex_m import VirtualUART

        uart = VirtualUART(baudrate=115200)
        uart.write(b"Hello")
        self.assertEqual(uart.read(), b"Hello")


class TestSTM32Peripherals(unittest.TestCase):
    """Test STM32-specific peripherals."""

    def test_stm32_gpio(self):
        """Test STM32 GPIO peripheral."""
        from mcuemu_cortex_m import STM32GPIO

        gpio = STM32GPIO(base_address=0x40020000)
        self.assertIsNotNone(gpio)

    def test_stm32_usart(self):
        """Test STM32 USART peripheral."""
        from mcuemu_cortex_m import STM32USART

        usart = STM32USART(base_address=0x40011000)
        self.assertIsNotNone(usart)


def run_tests():
    """Run all peripheral tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestPeripherals))
    suite.addTests(loader.loadTestsFromTestCase(TestSTM32Peripherals))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return len(result.failures) == 0 and len(result.errors) == 0


if __name__ == '__main__':
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
