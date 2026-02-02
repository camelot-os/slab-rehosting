#!/usr/bin/env python3
"""
Unified Test Runner for MCU Peripheral Tests

Runs all CDC-based peripheral tests across all supported MCU families:
- STM32F439: I2C EEPROM, SPI Flash, SPI LCD
- NRF52840: I2C EEPROM, SPI Flash
- RP2040: I2C EEPROM

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os
import importlib.util
import time
from pathlib import Path

# Add the Python modules to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'python'))


# Test definitions: (name, module_path, description)
TESTS = [
    # STM32F439 Tests
    ("STM32F439 I2C EEPROM", "i2c_eeprom_test/test_i2c_eeprom_cdc.py", "24C256 EEPROM via STM32 I2C"),
    ("STM32F439 SPI Flash", "spi_flash_test/test_spi_flash_cdc.py", "W25Q128 Flash via STM32 SPI"),
    ("STM32F439 SPI LCD", "spi_lcd_test/test_spi_lcd_cdc.py", "ILI9341 LCD via STM32 SPI"),
    ("STM32F439 DMA Flash", "stm32f439_dma_flash_test/test_stm32f439_dma_flash_cdc.py", "W25Q128 Flash via STM32 DMA+SPI"),
    ("STM32F439 I2C RTC", "stm32f439_rtc_test/test_stm32f439_rtc_cdc.py", "DS3231 RTC via STM32 I2C"),

    # STM32L433 Tests
    ("STM32L433 I2C EEPROM", "stm32l433_i2c_eeprom_test/test_stm32l433_i2c_eeprom_cdc.py", "24C256 EEPROM via STM32L4 I2Cv2"),

    # NRF52840 Tests
    ("NRF52840 I2C EEPROM", "nrf52840_eeprom_test/test_nrf52840_eeprom_cdc.py", "24C256 EEPROM via NRF TWIM"),
    ("NRF52840 SPI Flash", "nrf52840_flash_test/test_nrf52840_flash_cdc.py", "W25Q128 Flash via NRF SPIM"),
    ("NRF52840 QSPI Flash", "nrf52840_qspi_test/test_nrf52840_qspi_cdc.py", "W25Q128 Flash via NRF QSPI"),

    # RP2040 Tests
    ("RP2040 I2C EEPROM", "rp2040_eeprom_test/test_rp2040_eeprom_cdc.py", "24C256 EEPROM via RP2040 I2C"),

    # RP2350 Tests
    ("RP2350 Security", "rp2350_security_test/test_rp2350_security_cdc.py", "SHA256, TRNG, OTP, Glitch Detector"),

    # Multicore Tests
    ("RP2040 Multicore", "rp2040_multicore_test/test_rp2040_multicore_cdc.py", "Dual Cortex-M0+ FIFO, Spinlock, Shared Memory"),
    ("RP2350 Multicore", "rp2350_multicore_test/test_rp2350_multicore_cdc.py", "Dual Cortex-M33 FIFO, SHA256, TRNG"),
    ("STM32H745 Multicore", "stm32h745_multicore_test/test_stm32h745_multicore_cdc.py", "Cortex-M7 + M4 HSEM, Shared Memory"),

    # DVID IoT Board (ATmega328p)
    ("DVID IoT Board", "dvid_iot_board/test_dvid_iot_board.py", "ATmega328p Smart Lock (DVID-style vulnerabilities)"),
]


def load_test_module(module_path: str):
    """Dynamically load a test module."""
    base_dir = Path(__file__).parent
    full_path = base_dir / module_path

    if not full_path.exists():
        return None

    spec = importlib.util.spec_from_file_location("test_module", full_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_test(name: str, module_path: str, description: str, verbose: bool = False) -> tuple:
    """
    Run a single test module.

    Returns: (name, passed, failed, error_message)
    """
    print(f"\n{'=' * 60}")
    print(f"Running: {name}")
    print(f"  {description}")
    print('=' * 60)

    try:
        module = load_test_module(module_path)
        if module is None:
            return (name, 0, 1, f"Module not found: {module_path}")

        # Call the main function and capture the result
        if hasattr(module, 'main'):
            result = module.main()
            if result == 0:
                return (name, 1, 0, None)
            else:
                return (name, 0, 1, "Test failed")
        else:
            return (name, 0, 1, "No main() function found")

    except Exception as e:
        import traceback
        if verbose:
            traceback.print_exc()
        return (name, 0, 1, str(e))


def main():
    """Run all peripheral tests."""
    print("=" * 60)
    print("MCU Peripheral Test Suite")
    print("=" * 60)
    print(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Tests: {len(TESTS)}")
    print()

    # Parse arguments
    verbose = '-v' in sys.argv or '--verbose' in sys.argv
    filter_mcu = None
    for arg in sys.argv[1:]:
        if arg.startswith('--mcu='):
            filter_mcu = arg.split('=')[1].upper()

    # Filter tests if MCU specified
    tests_to_run = TESTS
    if filter_mcu:
        tests_to_run = [(n, p, d) for n, p, d in TESTS if filter_mcu in n.upper()]
        print(f"Filtering tests for MCU: {filter_mcu}")
        print(f"Running {len(tests_to_run)} of {len(TESTS)} tests")

    results = []
    start_time = time.time()

    for name, module_path, description in tests_to_run:
        result = run_test(name, module_path, description, verbose)
        results.append(result)

    elapsed = time.time() - start_time

    # Summary
    print()
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    total_passed = 0
    total_failed = 0

    for name, passed, failed, error in results:
        if error:
            status = f"FAIL: {error}"
            total_failed += 1
        else:
            status = "PASS"
            total_passed += 1
        print(f"  {name}: {status}")

    print()
    print("-" * 60)
    print(f"Total: {total_passed} passed, {total_failed} failed")
    print(f"Time: {elapsed:.2f}s")
    print("=" * 60)

    if total_failed > 0:
        print("\nSome tests FAILED!")
        return 1
    else:
        print("\nAll tests PASSED!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
