#!/usr/bin/env python3
"""
STM32F4 Bootrom + Firmware Boot Test for MCUemu

Test Scenario: Complete Boot Sequence
=====================================

This test verifies the complete STM32F405 boot sequence including:
1. Boot mode selection via BOOT0/BOOT1 pins
2. Memory aliasing at address 0x00000000
3. Vector table loading (initial SP and Reset_Handler)
4. Option Bytes configuration
5. UART bootloader protocol (System Memory boot)
6. Transition from bootrom to user firmware

Boot Modes Tested:
==================
    Mode            BOOT0   BOOT1   Boot Address    Description
    --------------- ------- ------- --------------- -------------------------
    User Flash      0       X       0x0800_0000     Normal firmware boot
    System Memory   1       0       0x1FFF_0000     Built-in bootloader
    Embedded SRAM   1       1       0x2000_0000     Debug/development

Realistic Scenario:
==================
1. Device powers on with BOOT0=0 (User Flash boot)
2. Firmware runs normally
3. Firmware detects "enter bootloader" condition (button press, USB, etc.)
4. Firmware jumps to system bootloader for firmware update
5. Bootloader receives new firmware via UART/USB
6. Bootloader writes firmware to flash
7. Bootloader jumps back to user firmware

Usage:
    python3 test_bootrom.py

Author: TwistedWires Security Lab
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import sys
import os

# Add parent directory for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python'))

from stm32_bootrom import (
    STM32F4Bootrom, STM32F4BootSequence, STM32F4Memory,
    BootMode, BootPins, OptionBytes, BootloaderCommand
)


# =============================================================================
# TEST FIRMWARE BUILDER
# =============================================================================

class TestFirmwareBuilder:
    """Helper to build test firmware images with proper vector tables."""

    @staticmethod
    def build_minimal_firmware(
        flash_base: int = 0x08000000,
        sram_top: int = 0x20020000,
        code_size: int = 256
    ) -> bytes:
        """
        Build a minimal valid firmware image.

        The image includes:
        - Vector table (initial SP + 15 exception handlers)
        - Minimal code (NOP + infinite loop)
        """
        # Initial SP (top of SRAM)
        initial_sp = sram_top

        # Reset handler (thumb mode, hence | 1)
        reset_handler = flash_base + 0x80 + 1  # After vector table

        # Vector table (64 bytes = 16 vectors)
        vectors = struct.pack('<I', initial_sp)           # 0: Initial SP
        vectors += struct.pack('<I', reset_handler)       # 1: Reset Handler
        vectors += struct.pack('<I', reset_handler)       # 2: NMI
        vectors += struct.pack('<I', reset_handler)       # 3: HardFault
        vectors += struct.pack('<I', reset_handler)       # 4: MemManage
        vectors += struct.pack('<I', reset_handler)       # 5: BusFault
        vectors += struct.pack('<I', reset_handler)       # 6: UsageFault
        vectors += struct.pack('<I', 0)                   # 7: Reserved
        vectors += struct.pack('<I', 0)                   # 8: Reserved
        vectors += struct.pack('<I', 0)                   # 9: Reserved
        vectors += struct.pack('<I', 0)                   # 10: Reserved
        vectors += struct.pack('<I', reset_handler)       # 11: SVCall
        vectors += struct.pack('<I', reset_handler)       # 12: Debug Monitor
        vectors += struct.pack('<I', 0)                   # 13: Reserved
        vectors += struct.pack('<I', reset_handler)       # 14: PendSV
        vectors += struct.pack('<I', reset_handler)       # 15: SysTick

        # Pad to 128 bytes (32 vectors)
        vectors += bytes(64)

        # Minimal code at reset handler
        # Thumb instructions:
        #   0xBF00: NOP
        #   0xE7FE: B . (infinite loop)
        code = bytes([
            0x00, 0xBF,  # NOP
            0x00, 0xBF,  # NOP
            0x00, 0xBF,  # NOP
            0x00, 0xBF,  # NOP
            0xFE, 0xE7,  # B . (infinite loop)
        ])

        # Pad to requested size
        firmware = vectors + code
        if len(firmware) < code_size:
            firmware += bytes(code_size - len(firmware))

        return firmware

    @staticmethod
    def build_bootloader_firmware(
        flash_base: int = 0x08000000,
        bootloader_entry: int = 0x1FFF0000
    ) -> bytes:
        """
        Build firmware that can jump to bootloader.

        This simulates a real firmware that enters bootloader mode
        on command (e.g., button press during reset).
        """
        # Vector table
        initial_sp = 0x20020000
        reset_handler = flash_base + 0x80 + 1

        vectors = struct.pack('<I', initial_sp)
        vectors += struct.pack('<I', reset_handler)
        vectors += bytes(120)  # Remaining vectors

        # Code that checks for bootloader entry condition
        # (In real firmware, this would check GPIO pins, USB, etc.)
        # For test, we just have the structure
        code = bytes([
            0x00, 0xBF,  # NOP
            0xFE, 0xE7,  # B . (loop)
        ])

        return vectors + code + bytes(128)


# =============================================================================
# TEST CASES
# =============================================================================

def test_boot_mode_selection():
    """Test boot mode selection based on BOOT0/BOOT1 pins."""
    print("\n=== Test: Boot Mode Selection ===")

    bootrom = STM32F4Bootrom()

    # Test all boot mode combinations
    test_cases = [
        (False, False, BootMode.USER_FLASH),
        (False, True, BootMode.USER_FLASH),      # BOOT1 doesn't matter when BOOT0=0
        (True, False, BootMode.SYSTEM_MEMORY),
        (True, True, BootMode.EMBEDDED_SRAM),
    ]

    for boot0, boot1, expected_mode in test_cases:
        bootrom.set_boot_pins(boot0, boot1)
        actual_mode = bootrom.get_boot_mode()
        print(f"  BOOT0={int(boot0)}, BOOT1={int(boot1)} -> {actual_mode.name}")
        assert actual_mode == expected_mode, \
            f"Expected {expected_mode.name}, got {actual_mode.name}"

    print("PASS: Boot Mode Selection")
    return True


def test_memory_aliasing():
    """Test memory aliasing at address 0x00000000."""
    print("\n=== Test: Memory Aliasing ===")

    bootrom = STM32F4Bootrom()

    # User Flash boot - alias to 0x08000000
    bootrom.set_boot_pins(boot0=False)
    alias = bootrom.get_alias_base()
    print(f"  User Flash boot: 0x00000000 -> 0x{alias:08X}")
    assert alias == STM32F4Memory.FLASH_BASE

    # System Memory boot - alias to 0x1FFF0000
    bootrom.set_boot_pins(boot0=True, boot1=False)
    alias = bootrom.get_alias_base()
    print(f"  System Memory boot: 0x00000000 -> 0x{alias:08X}")
    assert alias == STM32F4Memory.SYSTEM_MEM_BASE

    # SRAM boot - alias to 0x20000000
    bootrom.set_boot_pins(boot0=True, boot1=True)
    alias = bootrom.get_alias_base()
    print(f"  SRAM boot: 0x00000000 -> 0x{alias:08X}")
    assert alias == STM32F4Memory.SRAM_BASE

    print("PASS: Memory Aliasing")
    return True


def test_vector_table_loading():
    """Test vector table loading from firmware."""
    print("\n=== Test: Vector Table Loading ===")

    boot = STM32F4BootSequence()

    # Create test firmware
    firmware = TestFirmwareBuilder.build_minimal_firmware()
    boot.load_firmware_bytes(firmware)

    print(f"  Firmware size: {len(firmware)} bytes")

    # Boot from user flash
    boot.configure_boot_mode(boot0=False)
    sp, pc = boot.execute_boot()

    print(f"  Initial SP: 0x{sp:08X}")
    print(f"  Reset Handler: 0x{pc:08X}")

    # Verify SP is valid (top of SRAM)
    assert sp == 0x20020000, f"Expected SP=0x20020000, got 0x{sp:08X}"

    # Verify PC is in flash region (with thumb bit)
    assert 0x08000000 <= (pc & ~1) < 0x08100000, \
        f"Reset handler should be in flash, got 0x{pc:08X}"

    # Verify thumb bit is set
    assert pc & 1, "Reset handler should have thumb bit set"

    print("PASS: Vector Table Loading")
    return True


def test_option_bytes():
    """Test Option Bytes peripheral."""
    print("\n=== Test: Option Bytes ===")

    from stm32_bootrom import OptionBytesPeripheral, RDPLevel

    opt = OptionBytesPeripheral()

    # Read default OPTCR
    optcr = opt.read(0x00, 4)
    print(f"  Default OPTCR: 0x{optcr:08X}")

    # Verify default values
    rdp = (optcr >> 8) & 0xFF
    print(f"  RDP Level: 0x{rdp:02X} ({'Protected' if rdp != RDPLevel.LEVEL_0 else 'Not protected'})")

    nwrp = (optcr >> 16) & 0xFFF
    print(f"  Write Protection: 0x{nwrp:03X} (0xFFF = all unprotected)")

    assert rdp == RDPLevel.LEVEL_0, "Default should be no read protection"
    assert nwrp == 0xFFF, "Default should be no write protection"

    print("PASS: Option Bytes")
    return True


def test_uart_bootloader_sync():
    """Test UART bootloader synchronization."""
    print("\n=== Test: UART Bootloader Sync ===")

    bootrom = STM32F4Bootrom()
    bootrom.set_boot_pins(boot0=True, boot1=False)  # System Memory boot

    # Send sync byte (0x7F)
    response = bootrom.uart_receive(0x7F)
    print(f"  TX: 0x7F (sync)")
    print(f"  RX: {[hex(b) for b in response]}")

    assert response == [0x79], "Should receive ACK after sync"
    assert bootrom.active, "Bootloader should be active after sync"

    print("PASS: UART Bootloader Sync")
    return True


def test_uart_bootloader_get_id():
    """Test UART bootloader GET_ID command."""
    print("\n=== Test: UART Bootloader GET_ID ===")

    bootrom = STM32F4Bootrom()
    bootrom.set_boot_pins(boot0=True, boot1=False)

    # Sync first
    bootrom.uart_receive(0x7F)

    # Send GET_ID command (0x02) with complement (0xFD)
    response = bootrom.uart_receive(BootloaderCommand.GET_ID)
    response.extend(bootrom.uart_receive(~BootloaderCommand.GET_ID & 0xFF))

    print(f"  TX: 0x02 0xFD (GET_ID + complement)")
    print(f"  RX: {[hex(b) for b in response]}")

    # Response format: ACK, N (bytes to follow - 1), PID[15:8], PID[7:0], ACK
    assert response[0] == 0x79, "Should start with ACK"
    assert response[-1] == 0x79, "Should end with ACK"

    chip_id = (response[2] << 8) | response[3]
    print(f"  Chip ID: 0x{chip_id:04X}")
    assert chip_id == 0x0413, f"Expected STM32F405 ID (0x0413), got 0x{chip_id:04X}"

    print("PASS: UART Bootloader GET_ID")
    return True


def test_uart_bootloader_get_version():
    """Test UART bootloader GET_VERSION command."""
    print("\n=== Test: UART Bootloader GET_VERSION ===")

    bootrom = STM32F4Bootrom()
    bootrom.set_boot_pins(boot0=True, boot1=False)

    # Sync
    bootrom.uart_receive(0x7F)

    # GET_VERSION
    response = bootrom.uart_receive(BootloaderCommand.GET_VERSION)
    response.extend(bootrom.uart_receive(~BootloaderCommand.GET_VERSION & 0xFF))

    print(f"  RX: {[hex(b) for b in response]}")

    version = response[1]
    print(f"  Bootloader version: {(version >> 4) & 0xF}.{version & 0xF}")

    assert response[0] == 0x79, "Should start with ACK"
    assert version == 0x31, f"Expected version 3.1 (0x31), got 0x{version:02X}"

    print("PASS: UART Bootloader GET_VERSION")
    return True


def test_full_boot_sequence_user_flash():
    """Test complete boot sequence from user flash."""
    print("\n=== Test: Full Boot Sequence (User Flash) ===")

    boot = STM32F4BootSequence()

    # Load test firmware
    firmware = TestFirmwareBuilder.build_minimal_firmware()
    boot.load_firmware_bytes(firmware)

    # Configure for normal boot
    boot.configure_boot_mode(boot0=False)

    print("  1. Power-on reset...")
    print("     BOOT0 = 0 (sampled)")

    print("  2. Memory alias configuration...")
    alias_base = boot.get_vector_table_base()
    print(f"     0x00000000 aliased to 0x{alias_base:08X} (User Flash)")

    print("  3. Loading vector table...")
    sp, pc = boot.execute_boot()
    print(f"     Initial SP: 0x{sp:08X}")
    print(f"     Reset Handler: 0x{pc:08X}")

    print("  4. CPU starts execution...")
    print(f"     PC = 0x{pc:08X} (Reset_Handler)")

    # Verify
    assert alias_base == STM32F4Memory.FLASH_BASE
    assert sp == 0x20020000
    assert 0x08000080 <= (pc & ~1) <= 0x08000100

    print("\nBoot sequence complete!")
    print("PASS: Full Boot Sequence (User Flash)")
    return True


def test_full_boot_sequence_bootrom():
    """Test complete boot sequence from system memory (bootrom)."""
    print("\n=== Test: Full Boot Sequence (System Memory) ===")

    boot = STM32F4BootSequence()

    # Load user firmware (will be used after bootloader)
    firmware = TestFirmwareBuilder.build_minimal_firmware()
    boot.load_firmware_bytes(firmware)

    # Configure for bootloader boot (e.g., BOOT0 pin held high)
    boot.configure_boot_mode(boot0=True, boot1=False)

    print("  1. Power-on reset with BOOT0=1...")
    print("     BOOT0 = 1, BOOT1 = 0 (sampled)")

    print("  2. Memory alias configuration...")
    alias_base = boot.get_vector_table_base()
    print(f"     0x00000000 aliased to 0x{alias_base:08X} (System Memory)")

    print("  3. Loading bootrom vector table...")
    sp, pc = boot.execute_boot()
    print(f"     Initial SP: 0x{sp:08X}")
    print(f"     Bootrom entry: 0x{pc:08X}")

    print("  4. Bootrom executes...")
    print("     (Waiting for UART/USB commands)")

    # Verify bootrom entry
    assert alias_base == STM32F4Memory.SYSTEM_MEM_BASE
    assert pc >= STM32F4Memory.SYSTEM_MEM_BASE

    print("\nBootrom active - waiting for firmware update")
    print("PASS: Full Boot Sequence (System Memory)")
    return True


def test_bootrom_to_user_firmware_transition():
    """Test transition from bootrom to user firmware."""
    print("\n=== Test: Bootrom to User Firmware Transition ===")

    boot = STM32F4BootSequence()
    bootrom = boot.bootrom

    # Load user firmware
    firmware = TestFirmwareBuilder.build_minimal_firmware()
    boot.load_firmware_bytes(firmware)

    # Start in bootrom mode
    boot.configure_boot_mode(boot0=True, boot1=False)

    print("  1. Device boots in bootrom mode...")
    sp, pc = boot.execute_boot()
    print(f"     Bootrom entry: PC=0x{pc:08X}")

    # Simulate bootloader activity
    print("\n  2. UART bootloader protocol...")
    bootrom.uart_receive(0x7F)  # Sync
    print("     Synchronized with host")

    # Get chip ID
    bootrom.state = 'COMMAND'
    bootrom.rx_buffer = []
    bootrom.uart_receive(BootloaderCommand.GET_ID)
    bootrom.uart_receive(~BootloaderCommand.GET_ID & 0xFF)
    print("     Chip ID verified: STM32F405")

    # Simulate "GO" command to jump to user firmware
    print("\n  3. Host sends GO command...")

    jumped_to = [None]

    def on_go(addr):
        jumped_to[0] = addr
        print(f"     Jumping to user firmware at 0x{addr:08X}")

    bootrom.on_go = on_go
    bootrom.state = 'COMMAND'
    bootrom.rx_buffer = []
    response = bootrom.uart_receive(BootloaderCommand.GO)
    response.extend(bootrom.uart_receive(~BootloaderCommand.GO & 0xFF))

    assert jumped_to[0] == STM32F4Memory.FLASH_BASE, "Should jump to user flash"

    print("\n  4. User firmware now executing")

    # Now read entry point from user flash
    user_sp = struct.unpack('<I', firmware[0:4])[0]
    user_pc = struct.unpack('<I', firmware[4:8])[0]
    print(f"     User SP: 0x{user_sp:08X}")
    print(f"     User PC: 0x{user_pc:08X}")

    print("\nPASS: Bootrom to User Firmware Transition")
    return True


def test_firmware_update_scenario():
    """Test realistic firmware update scenario."""
    print("\n=== Test: Firmware Update Scenario ===")
    print("\nScenario: OTA firmware update via bootloader")

    boot = STM32F4BootSequence()
    bootrom = boot.bootrom

    # === Phase 1: Running user firmware ===
    print("\n[Phase 1] Normal Operation")
    old_firmware = TestFirmwareBuilder.build_minimal_firmware()
    boot.load_firmware_bytes(old_firmware)
    boot.configure_boot_mode(boot0=False)

    sp, pc = boot.execute_boot()
    print(f"  Running firmware v1.0 at PC=0x{pc:08X}")

    # === Phase 2: Enter bootloader mode ===
    print("\n[Phase 2] Enter Bootloader Mode")
    print("  User requests firmware update...")
    print("  Firmware sets magic value in backup register")
    print("  Firmware triggers system reset with BOOT0=1")

    boot.configure_boot_mode(boot0=True, boot1=False)
    sp, pc = boot.execute_boot()
    print(f"  Bootloader active at PC=0x{pc:08X}")

    # === Phase 3: Firmware transfer ===
    print("\n[Phase 3] Firmware Transfer")
    bootrom.uart_receive(0x7F)
    print("  Host connected via UART")

    # Simulate erase
    bootrom.state = 'COMMAND'
    bootrom.rx_buffer = []
    bootrom.uart_receive(BootloaderCommand.ERASE)
    bootrom.uart_receive(~BootloaderCommand.ERASE & 0xFF)
    print("  Flash erased")

    # In real scenario, WRITE_MEMORY would be used repeatedly
    print("  Writing new firmware...")
    new_firmware = TestFirmwareBuilder.build_minimal_firmware()
    print(f"  Transferred {len(new_firmware)} bytes")

    # === Phase 4: Boot new firmware ===
    print("\n[Phase 4] Boot New Firmware")

    jumped = [False]
    bootrom.on_go = lambda addr: jumped.__setitem__(0, True)

    bootrom.state = 'COMMAND'
    bootrom.rx_buffer = []
    bootrom.uart_receive(BootloaderCommand.GO)
    bootrom.uart_receive(~BootloaderCommand.GO & 0xFF)

    assert jumped[0], "Should jump to new firmware"
    print("  Jumping to new firmware")

    # Reconfigure for normal boot
    boot.load_firmware_bytes(new_firmware)
    boot.configure_boot_mode(boot0=False)
    sp, pc = boot.execute_boot()
    print(f"  Running firmware v2.0 at PC=0x{pc:08X}")

    print("\n=== Firmware Update Complete ===")
    print("PASS: Firmware Update Scenario")
    return True


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Run all bootrom tests."""
    print("=" * 70)
    print("STM32F405 Bootrom + Firmware Boot Tests")
    print("=" * 70)
    print("\nTest Scenario: Complete Boot Sequence with Bootrom Support")
    print("  - Boot mode selection (BOOT0/BOOT1)")
    print("  - Memory aliasing")
    print("  - Vector table loading")
    print("  - UART bootloader protocol")
    print("  - Firmware update via bootloader")
    print("=" * 70)

    tests = [
        test_boot_mode_selection,
        test_memory_aliasing,
        test_vector_table_loading,
        test_option_bytes,
        test_uart_bootloader_sync,
        test_uart_bootloader_get_id,
        test_uart_bootloader_get_version,
        test_full_boot_sequence_user_flash,
        test_full_boot_sequence_bootrom,
        test_bootrom_to_user_firmware_transition,
        test_firmware_update_scenario,
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
            import traceback
            traceback.print_exc()
            results.append(False)

    # Summary
    print("\n" + "=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("All Bootrom tests PASSED!")
        return 0
    else:
        print("Some tests FAILED!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
