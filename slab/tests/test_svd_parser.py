#!/usr/bin/env python3
"""
SVD Parser Tests for MCUemu

Tests the SVD parser functionality with sample SVD files.

Usage:
    python3 test_svd_parser.py

Author: Twisted Wires Security Lab
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import os

# Add parent directory for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from svd_parser import SVDParser, SVDDevice, SVDDebugHelper


# =============================================================================
# TEST CASES
# =============================================================================

def test_parse_arm_sample():
    """Test parsing ARM sample SVD file."""
    print("\n=== Test: Parse ARM Sample SVD ===")

    svd_path = os.path.join(
        os.path.dirname(__file__), '..', 'svd', 'data', 'ARM_SAMPLE', 'ARM_Sample.svd'
    )

    if not os.path.exists(svd_path):
        print(f"SKIP: SVD file not found: {svd_path}")
        return None

    parser = SVDParser()
    device = parser.parse(svd_path)

    print(f"Device: {device.name}")
    print(f"Vendor: {device.vendor}")
    print(f"CPU: {device.cpu_name}")
    print(f"Peripherals: {len(device.peripherals)}")

    assert device.name, "Device name should not be empty"
    assert len(device.peripherals) > 0, "Should have at least one peripheral"

    # Check TIMER0 peripheral
    timer = device.get_peripheral('TIMER0')
    if timer:
        print(f"\nTIMER0 found at 0x{timer.base_address:08X}")
        print(f"  Registers: {len(timer.registers)}")
        assert len(timer.registers) > 0, "TIMER0 should have registers"
    else:
        print("Note: TIMER0 not found in this SVD")

    print("PASS: ARM Sample SVD parsing")
    return True


def test_parse_stm32f4():
    """Test parsing STM32F407 SVD file."""
    print("\n=== Test: Parse STM32F407 SVD ===")

    svd_path = os.path.join(
        os.path.dirname(__file__), '..', 'svd', 'data', 'STMicro', 'STM32F407.svd'
    )

    if not os.path.exists(svd_path):
        print(f"SKIP: SVD file not found: {svd_path}")
        return None

    parser = SVDParser()
    device = parser.parse(svd_path)

    print(f"Device: {device.name}")
    print(f"Peripherals: {len(device.peripherals)}")

    # Verify expected peripherals
    expected_peripherals = ['RCC', 'GPIOA', 'USART1', 'TIM2']
    for name in expected_peripherals:
        periph = device.get_peripheral(name)
        if periph:
            print(f"  {name}: 0x{periph.base_address:08X} ({len(periph.registers)} regs)")
        else:
            print(f"  {name}: Not found")

    # Test address lookup
    gpioa = device.get_peripheral('GPIOA')
    if gpioa:
        # GPIOA should be at 0x40020000
        desc = device.describe_address(gpioa.base_address)
        print(f"\nAddress lookup: {desc}")

    print("PASS: STM32F407 SVD parsing")
    return True


def test_parse_nrf52840():
    """Test parsing nRF52840 SVD file."""
    print("\n=== Test: Parse nRF52840 SVD ===")

    svd_path = os.path.join(
        os.path.dirname(__file__), '..', 'svd', 'data', 'Nordic', 'nrf52840.svd'
    )

    if not os.path.exists(svd_path):
        print(f"SKIP: SVD file not found: {svd_path}")
        return None

    parser = SVDParser()
    device = parser.parse(svd_path)

    print(f"Device: {device.name}")
    print(f"Peripherals: {len(device.peripherals)}")

    # Check for Nordic-specific peripherals
    for name in ['CLOCK', 'RADIO', 'TIMER0', 'GPIO']:
        periph = device.get_peripheral(name)
        if periph:
            print(f"  {name}: 0x{periph.base_address:08X}")

    print("PASS: nRF52840 SVD parsing")
    return True


def test_yaml_generation():
    """Test YAML configuration generation."""
    print("\n=== Test: YAML Generation ===")

    # Find any available SVD file
    svd_dirs = [
        ('ARM_SAMPLE', 'ARM_Sample.svd'),
        ('STMicro', 'STM32F407.svd'),
        ('Nordic', 'nrf52840.svd'),
    ]

    svd_path = None
    for vendor, filename in svd_dirs:
        path = os.path.join(
            os.path.dirname(__file__), '..', 'svd', 'data', vendor, filename
        )
        if os.path.exists(path):
            svd_path = path
            break

    if not svd_path:
        print("SKIP: No SVD files found")
        return None

    parser = SVDParser()
    device = parser.parse(svd_path)

    yaml_config = parser.generate_yaml_config(device)
    print(f"Generated YAML for {device.name}:")
    print(yaml_config[:500] + "..." if len(yaml_config) > 500 else yaml_config)

    # Verify YAML structure
    assert 'name:' in yaml_config, "YAML should have device name"
    assert 'machine:' in yaml_config, "YAML should have machine config"
    assert 'peripherals:' in yaml_config, "YAML should have peripherals"

    print("PASS: YAML generation")
    return True


def test_register_field_parsing():
    """Test register and field parsing."""
    print("\n=== Test: Register Field Parsing ===")

    # Use embedded SVD content for testing
    svd_content = '''<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.1">
  <name>TestDevice</name>
  <version>1.0</version>
  <description>Test device for SVD parser</description>
  <cpu>
    <name>CM4</name>
    <revision>r0p1</revision>
    <endian>little</endian>
    <nvicPrioBits>4</nvicPrioBits>
  </cpu>
  <addressUnitBits>8</addressUnitBits>
  <width>32</width>
  <peripherals>
    <peripheral>
      <name>GPIO</name>
      <description>General Purpose I/O</description>
      <baseAddress>0x40020000</baseAddress>
      <addressBlock>
        <offset>0</offset>
        <size>0x400</size>
        <usage>registers</usage>
      </addressBlock>
      <interrupt>
        <name>GPIO_IRQ</name>
        <value>16</value>
      </interrupt>
      <registers>
        <register>
          <name>MODER</name>
          <description>GPIO port mode register</description>
          <addressOffset>0x00</addressOffset>
          <size>32</size>
          <access>read-write</access>
          <resetValue>0xA8000000</resetValue>
          <fields>
            <field>
              <name>MODE0</name>
              <description>Port x configuration bits (0-1)</description>
              <bitOffset>0</bitOffset>
              <bitWidth>2</bitWidth>
              <enumeratedValues>
                <enumeratedValue>
                  <name>Input</name>
                  <value>0</value>
                </enumeratedValue>
                <enumeratedValue>
                  <name>Output</name>
                  <value>1</value>
                </enumeratedValue>
                <enumeratedValue>
                  <name>Alternate</name>
                  <value>2</value>
                </enumeratedValue>
                <enumeratedValue>
                  <name>Analog</name>
                  <value>3</value>
                </enumeratedValue>
              </enumeratedValues>
            </field>
            <field>
              <name>MODE1</name>
              <description>Port x configuration bits (2-3)</description>
              <bitOffset>2</bitOffset>
              <bitWidth>2</bitWidth>
            </field>
          </fields>
        </register>
        <register>
          <name>ODR</name>
          <description>GPIO port output data register</description>
          <addressOffset>0x14</addressOffset>
          <size>32</size>
          <resetValue>0x00000000</resetValue>
        </register>
      </registers>
    </peripheral>
  </peripherals>
</device>
'''

    parser = SVDParser()
    device = parser.parse_string(svd_content)

    print(f"Device: {device.name}")
    print(f"CPU: {device.cpu_name}")

    # Verify peripheral
    gpio = device.get_peripheral('GPIO')
    assert gpio is not None, "GPIO peripheral should exist"
    assert gpio.base_address == 0x40020000, "GPIO base should be 0x40020000"
    assert len(gpio.interrupts) == 1, "GPIO should have one interrupt"
    assert gpio.interrupts[0].value == 16, "GPIO IRQ should be 16"

    # Verify registers
    moder = gpio.get_register_by_name('MODER')
    assert moder is not None, "MODER register should exist"
    assert moder.address_offset == 0x00, "MODER offset should be 0"
    assert moder.reset_value == 0xA8000000, "MODER reset value should match"
    assert len(moder.fields) == 2, "MODER should have 2 fields"

    # Verify fields
    mode0 = moder.get_field('MODE0')
    assert mode0 is not None, "MODE0 field should exist"
    assert mode0.bit_offset == 0, "MODE0 bit offset should be 0"
    assert mode0.bit_width == 2, "MODE0 bit width should be 2"
    assert len(mode0.enumerated_values) == 4, "MODE0 should have 4 enum values"
    assert mode0.enumerated_values['Output'] == 1, "Output enum should be 1"

    # Test address lookup
    info = device.get_register_info(0x40020000)
    assert info is not None, "Should find register at GPIO base"
    periph, reg, idx = info
    assert periph.name == 'GPIO', "Should be GPIO peripheral"
    assert reg.name == 'MODER', "Should be MODER register"

    # Test debug helper
    helper = SVDDebugHelper(device)
    desc = helper.describe_value(0x40020000, 0x00000001)
    print(f"\nDebug description:\n{desc}")
    assert 'GPIO' in desc, "Description should mention GPIO"
    assert 'MODER' in desc, "Description should mention MODER"
    assert 'MODE0' in desc, "Description should mention MODE0"

    print("PASS: Register field parsing")
    return True


def test_derived_peripherals():
    """Test derived peripheral handling."""
    print("\n=== Test: Derived Peripherals ===")

    svd_content = '''<?xml version="1.0" encoding="utf-8"?>
<device schemaVersion="1.1">
  <name>TestDevice</name>
  <version>1.0</version>
  <description>Test device</description>
  <peripherals>
    <peripheral>
      <name>GPIOA</name>
      <description>GPIO Port A</description>
      <baseAddress>0x40020000</baseAddress>
      <addressBlock>
        <offset>0</offset>
        <size>0x400</size>
        <usage>registers</usage>
      </addressBlock>
      <registers>
        <register>
          <name>MODER</name>
          <addressOffset>0x00</addressOffset>
        </register>
        <register>
          <name>ODR</name>
          <addressOffset>0x14</addressOffset>
        </register>
      </registers>
    </peripheral>
    <peripheral derivedFrom="GPIOA">
      <name>GPIOB</name>
      <description>GPIO Port B</description>
      <baseAddress>0x40020400</baseAddress>
    </peripheral>
    <peripheral derivedFrom="GPIOA">
      <name>GPIOC</name>
      <description>GPIO Port C</description>
      <baseAddress>0x40020800</baseAddress>
    </peripheral>
  </peripherals>
</device>
'''

    parser = SVDParser()
    device = parser.parse_string(svd_content)

    # GPIOB and GPIOC should inherit registers from GPIOA
    gpiob = device.get_peripheral('GPIOB')
    gpioc = device.get_peripheral('GPIOC')

    assert gpiob is not None, "GPIOB should exist"
    assert gpioc is not None, "GPIOC should exist"

    assert len(gpiob.registers) == 2, "GPIOB should have 2 inherited registers"
    assert len(gpioc.registers) == 2, "GPIOC should have 2 inherited registers"

    assert gpiob.base_address == 0x40020400, "GPIOB base should be 0x40020400"
    assert gpioc.base_address == 0x40020800, "GPIOC base should be 0x40020800"

    print(f"GPIOA: 0x{device.get_peripheral('GPIOA').base_address:08X}")
    print(f"GPIOB: 0x{gpiob.base_address:08X} (derived, {len(gpiob.registers)} regs)")
    print(f"GPIOC: 0x{gpioc.base_address:08X} (derived, {len(gpioc.registers)} regs)")

    print("PASS: Derived peripherals")
    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all SVD parser tests."""
    print("=" * 60)
    print("MCUemu SVD Parser Tests")
    print("=" * 60)

    tests = [
        test_register_field_parsing,
        test_derived_peripherals,
        test_parse_arm_sample,
        test_parse_stm32f4,
        test_parse_nrf52840,
        test_yaml_generation,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except AssertionError as e:
            print(f"FAIL: {e}")
            results.append(False)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append(False)

    # Summary
    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r is True)
    skipped = sum(1 for r in results if r is None)
    failed = sum(1 for r in results if r is False)
    total = len(results) - skipped

    print(f"Results: {passed}/{total} tests passed ({skipped} skipped)")

    if failed == 0:
        print("All SVD parser tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
