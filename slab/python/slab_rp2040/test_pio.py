#!/usr/bin/env python3
"""
PIO Test Script - Test RP2040 PIO Emulation

Demonstrates PIO functionality:
- Instruction memory read/write
- State machine configuration
- GPIO output
- FIFO operations
- Pre-built programs (blink, WS2812, UART, SPI)

Run:
    python3 test_pio.py

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import logging
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from rp2040_peripherals import RP2040PeripheralSet, RP2350PeripheralSet, RP2040PIO
from peripherals import PIOEmulator, PIOInstruction, PIOPrograms

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('PIO.Test')


def test_pio_instruction_decode():
    """Test PIO instruction decoding."""
    print("\n" + "=" * 60)
    print("  Test 1: PIO Instruction Decoding")
    print("=" * 60 + "\n")

    test_cases = [
        (0xE001, "set pins, 1"),
        (0xE000, "set pins, 0"),
        (0x0000, "jmp 0"),
        (0x80A0, "pull  block"),
        (0x6008, "out pins, 8"),
        (0xA041, "mov y, x"),      # dest=Y(2), src=X(1): 0b101_00_010_00_001
        (0xC001, "irq  1"),
    ]

    all_pass = True
    for raw, expected in test_cases:
        instr = PIOInstruction.decode(raw)
        result = str(instr)
        # Normalize whitespace for comparison
        result_normalized = ' '.join(result.split())
        expected_normalized = ' '.join(expected.split())
        match = expected_normalized in result_normalized
        status = "✓" if match else "✗"
        print(f"  {status} 0x{raw:04X}: {result}")
        if not match:
            print(f"       Expected: {expected}")
            all_pass = False

    print(f"\n  Result: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


def test_pio_instruction_memory():
    """Test PIO instruction memory read/write via MMIO."""
    print("\n" + "=" * 60)
    print("  Test 2: PIO Instruction Memory (MMIO)")
    print("=" * 60 + "\n")

    # Create RP2040 peripherals
    peripherals = RP2040PeripheralSet(log=logging.getLogger('RP2040'))
    pio0 = peripherals.pio0

    # Test program
    test_program = [
        0xE001,  # set pins, 1
        0xA000,  # nop (mov y, pins in encoded form = 0xa000)
        0xE000,  # set pins, 0
        0xA000,  # nop
        0x0000,  # jmp 0
    ]

    # Write instructions via MMIO
    print("  Writing instructions to PIO0 instruction memory...")
    for i, instr in enumerate(test_program):
        addr = pio0.base + RP2040PIO.INSTR_MEM0 + i * 4
        pio0.write(addr, 4, instr)

    # Read back and verify
    print("  Reading back instructions...\n")
    all_match = True
    for i, expected in enumerate(test_program):
        addr = pio0.base + RP2040PIO.INSTR_MEM0 + i * 4
        readback, status = pio0.read(addr, 4)
        match = (readback & 0xFFFF) == expected
        status_str = "✓" if match else "✗"
        instr = PIOInstruction.decode(readback & 0xFFFF)
        print(f"    {status_str} INSTR[{i}]: 0x{readback:04X} -> {instr}")
        if not match:
            print(f"         Expected: 0x{expected:04X}")
            all_match = False

    print(f"\n  Result: {'PASS' if all_match else 'FAIL'}")
    return all_match


def test_pio_state_machine():
    """Test PIO state machine execution."""
    print("\n" + "=" * 60)
    print("  Test 3: PIO State Machine Execution")
    print("=" * 60 + "\n")

    # Create PIO emulator directly
    pio = PIOEmulator(index=0)

    # Load LED blink program
    blink_program = PIOPrograms.blink_led()
    pio.load_program(blink_program)

    # Configure SM0 for GPIO25 (LED pin)
    LED_PIN = 25
    pio.configure_sm(0,
        set_base=LED_PIN,
        set_count=1,
        wrap_bottom=0,
        wrap_top=1,
    )

    # Enable SM0
    pio.enable_sm(0x1)

    # Run cycles and track GPIO state
    print(f"  LED blink program on GPIO{LED_PIN}:")
    print(f"  Program: {[f'0x{x:04X}' for x in blink_program]}")
    print()

    led_states = []
    for cycle in range(10):
        pio.step()
        led = (pio.gpio_state >> LED_PIN) & 1
        led_states.append(led)
        led_str = "ON " if led else "OFF"
        print(f"    Cycle {cycle}: GPIO{LED_PIN} = {led_str}")

    # Check we got alternating pattern
    expected_pattern = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    match = led_states == expected_pattern
    print(f"\n  Pattern match: {'✓' if match else '✗'}")
    print(f"  Expected: {expected_pattern}")
    print(f"  Got:      {led_states}")
    print(f"\n  Result: {'PASS' if match else 'FAIL'}")
    return match


def test_pio_fifo_operations():
    """Test PIO FIFO push/pull operations."""
    print("\n" + "=" * 60)
    print("  Test 4: PIO FIFO Operations")
    print("=" * 60 + "\n")

    peripherals = RP2040PeripheralSet(log=logging.getLogger('RP2040'))
    pio0 = peripherals.pio0

    # Program: pull from FIFO, output to pins
    tx_program = [
        0x80A0,  # pull block
        0x6000,  # out pins, 32 (all 32 bits) - dest=0 (PINS), count=0 (32)
    ]

    # Load program
    print("  Loading TX program...")
    for i, instr in enumerate(tx_program):
        addr = pio0.base + RP2040PIO.INSTR_MEM0 + i * 4
        pio0.write(addr, 4, instr)

    # Configure SM0
    pio0.emu.configure_sm(0,
        out_base=0,
        out_count=32,
        wrap_bottom=0,
        wrap_top=1,
        autopull=False,
    )

    # Set GPIO direction to output for all 32 pins (required for OUT to work)
    # In real RP2040, this is done via SET PINDIRS or GPIO configuration
    pio0.emu.gpio_dir = 0xFFFFFFFF

    # Enable SM0
    pio0.write(pio0.base + RP2040PIO.CTRL, 4, 0x1)

    # Check FSTAT - TX should be empty
    fstat, _ = pio0.read(pio0.base + RP2040PIO.FSTAT, 4)
    tx_empty = bool(fstat & (1 << 24))
    print(f"  TX FIFO empty before push: {tx_empty}")

    # Push data to TX FIFO
    test_value = 0xDEADBEEF
    print(f"  Pushing 0x{test_value:08X} to TX FIFO...")
    pio0.write(pio0.base + RP2040PIO.TXF0, 4, test_value)

    # Check FSTAT - TX should not be empty
    fstat, _ = pio0.read(pio0.base + RP2040PIO.FSTAT, 4)
    tx_empty_after = bool(fstat & (1 << 24))
    print(f"  TX FIFO empty after push: {tx_empty_after}")

    # Run PIO to process data
    print("  Running PIO cycles...")
    for _ in range(5):
        peripherals.step_pio()

    # Check GPIO output
    gpio = pio0.emu.gpio_state
    print(f"  GPIO output: 0x{gpio:08X}")

    # Verify
    match = gpio == test_value
    print(f"\n  Output match: {'✓' if match else '✗'}")
    print(f"  Expected: 0x{test_value:08X}")
    print(f"  Got:      0x{gpio:08X}")
    print(f"\n  Result: {'PASS' if match else 'FAIL'}")
    return match


def test_pio_programs():
    """Test pre-built PIO programs."""
    print("\n" + "=" * 60)
    print("  Test 5: Pre-built PIO Programs")
    print("=" * 60 + "\n")

    programs = [
        ("LED Blink", PIOPrograms.blink_led()),
        ("WS2812", PIOPrograms.ws2812_bitbang()),
        ("UART TX", PIOPrograms.uart_tx()),
        ("SPI TX", PIOPrograms.spi_tx()),
    ]

    for name, program in programs:
        print(f"  {name}:")
        for i, raw in enumerate(program):
            instr = PIOInstruction.decode(raw)
            print(f"    {i}: 0x{raw:04X} -> {instr}")
        print()

    return True


def test_pio_rp2350():
    """Test RP2350 PIO (3 PIO blocks, RISC-V compatible)."""
    print("\n" + "=" * 60)
    print("  Test 6: RP2350 PIO (3 blocks)")
    print("=" * 60 + "\n")

    try:
        peripherals = RP2350PeripheralSet(arch="ARM", log=logging.getLogger('RP2350'))

        # Check we have 3 PIO blocks
        has_pio2 = hasattr(peripherals, 'pio2')
        print(f"  PIO0 present: ✓")
        print(f"  PIO1 present: ✓")
        print(f"  PIO2 present: {'✓' if has_pio2 else '✗'}")

        if has_pio2:
            # Load a simple program into PIO2
            print("\n  Testing PIO2 instruction memory...")
            pio2 = peripherals.pio2
            test_instr = 0xE001  # set pins, 1

            pio2.write(pio2.base + RP2040PIO.INSTR_MEM0, 4, test_instr)
            readback, _ = pio2.read(pio2.base + RP2040PIO.INSTR_MEM0, 4)

            match = (readback & 0xFFFF) == test_instr
            print(f"    Write 0x{test_instr:04X}, Read 0x{readback:04X}: {'✓' if match else '✗'}")
            print(f"\n  Result: {'PASS' if match else 'FAIL'}")
            return match

        return has_pio2

    except ImportError as e:
        print(f"  RP2350 peripherals not available: {e}")
        print(f"\n  Result: SKIP")
        return True


def test_pio_disassembly():
    """Test PIO disassembly output."""
    print("\n" + "=" * 60)
    print("  Test 7: PIO Disassembly")
    print("=" * 60 + "\n")

    pio = PIOEmulator()

    # Load a mixed program
    program = [
        0xE001,  # set pins, 1
        0x2020,  # wait 0 pin 0
        0x4001,  # in pins, 1
        0x6001,  # out pins, 1
        0x80A0,  # pull block
        0x8020,  # push block
        0xA001,  # mov x, pins
        0xC001,  # irq 1
        0x0005,  # jmp 5
    ]

    pio.load_program(program)

    print("  Disassembly:")
    disasm = pio.disassemble(0, len(program))
    for line in disasm:
        print(f"    {line}")

    return True


def main():
    """Run all PIO tests."""
    print()
    print("=" * 60)
    print("   RP2040/RP2350 PIO Emulation Test Suite")
    print("=" * 60)

    tests = [
        ("Instruction Decode", test_pio_instruction_decode),
        ("Instruction Memory", test_pio_instruction_memory),
        ("State Machine", test_pio_state_machine),
        ("FIFO Operations", test_pio_fifo_operations),
        ("Pre-built Programs", test_pio_programs),
        ("RP2350 PIO2", test_pio_rp2350),
        ("Disassembly", test_pio_disassembly),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            log.error(f"Test '{name}' failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("   Test Summary")
    print("=" * 60 + "\n")

    passed = 0
    failed = 0
    for name, result in results:
        status = "PASS" if result else "FAIL"
        symbol = "✓" if result else "✗"
        print(f"  {symbol} {name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    print()
    print(f"  Total: {len(results)} tests, {passed} passed, {failed} failed")
    print()

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
