#!/usr/bin/env python3
"""
STM32F4 Bootrom Emulation for MCUemu

This module emulates the STM32F4 System Memory bootloader (bootrom) behavior.
It implements the boot mode selection, Option Bytes, and bootloader protocol.

STM32F4 Boot Modes:
===================
    BOOT1   BOOT0   Boot From
    -----   -----   ---------
      X       0     User Flash (0x0800_0000)
      0       1     System Memory (0x1FFF_0000) - Bootrom
      1       1     Embedded SRAM (0x2000_0000)

Boot Sequence:
==============
1. On reset, CPU samples BOOT0/BOOT1 pins
2. Based on boot mode, address 0x0000_0000 is aliased to:
   - User Flash: 0x0800_0000
   - System Memory: 0x1FFF_0000
   - SRAM: 0x2000_0000
3. CPU loads initial SP from 0x0000_0000 (aliased)
4. CPU loads Reset_Handler from 0x0000_0004 (aliased)
5. Execution begins at Reset_Handler

System Memory Bootloader Features:
==================================
- UART bootloader (USART1/USART3)
- SPI bootloader (SPI1/SPI2)
- CAN bootloader (CAN1/CAN2)
- I2C bootloader (I2C1/I2C2)
- USB DFU bootloader (OTG FS)
- Flash programming
- Read/Write protection

Usage:
    from stm32_bootrom import STM32F4Bootrom, BootMode

    bootrom = STM32F4Bootrom()
    bootrom.set_boot_pins(boot0=True, boot1=False)  # System memory boot
    entry_point = bootrom.get_entry_point()

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
from enum import IntEnum, IntFlag
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple

log = logging.getLogger('Bootrom')


# =============================================================================
# STM32F4 MEMORY MAP
# =============================================================================

class STM32F4Memory:
    """STM32F4 memory regions."""

    # Flash
    FLASH_BASE = 0x08000000
    FLASH_SIZE = 0x100000       # 1MB for STM32F405

    # System Memory (Bootrom)
    SYSTEM_MEM_BASE = 0x1FFF0000
    SYSTEM_MEM_SIZE = 0x7800    # 30KB

    # SRAM
    SRAM_BASE = 0x20000000
    SRAM_SIZE = 0x20000         # 128KB

    # CCM (Core Coupled Memory)
    CCM_BASE = 0x10000000
    CCM_SIZE = 0x10000          # 64KB

    # Option Bytes
    OTP_BASE = 0x1FFF7800       # One-Time Programmable
    OTP_SIZE = 0x400
    OPTION_BYTES_BASE = 0x1FFFC000
    OPTION_BYTES_SIZE = 0x10

    # Alias region (remapped based on boot mode)
    ALIAS_BASE = 0x00000000


# =============================================================================
# BOOT MODE
# =============================================================================

class BootMode(IntEnum):
    """STM32F4 boot mode selection."""
    USER_FLASH = 0      # BOOT0=0, BOOT1=X -> Boot from Flash
    SYSTEM_MEMORY = 1   # BOOT0=1, BOOT1=0 -> Boot from Bootrom
    EMBEDDED_SRAM = 2   # BOOT0=1, BOOT1=1 -> Boot from SRAM


@dataclass
class BootPins:
    """Boot pin configuration."""
    boot0: bool = False   # Low = User Flash
    boot1: bool = False   # Only matters when BOOT0=1

    @property
    def mode(self) -> BootMode:
        if not self.boot0:
            return BootMode.USER_FLASH
        elif not self.boot1:
            return BootMode.SYSTEM_MEMORY
        else:
            return BootMode.EMBEDDED_SRAM


# =============================================================================
# OPTION BYTES
# =============================================================================

class OptionBytesReg(IntEnum):
    """Option Bytes register offsets."""
    OPTCR = 0x00        # Flash option control register
    OPTCR1 = 0x04       # Flash option control register 1 (STM32F42x/43x only)


class RDPLevel(IntEnum):
    """Read Data Protection levels."""
    LEVEL_0 = 0xAA      # No protection
    LEVEL_1 = 0x00      # Read protection
    LEVEL_2 = 0xCC      # Chip protection (IRREVERSIBLE!)


@dataclass
class OptionBytes:
    """
    STM32F4 Option Bytes configuration.

    OPTCR Register (0x1FFFC000):
        Bits 31:28 - Not writable
        Bits 27:16 - nWRP (Write protection for sectors)
        Bits 15:8  - RDP (Read protection level)
        Bit  7     - Reserved
        Bit  6     - nRST_STDBY
        Bit  5     - nRST_STOP
        Bit  4     - Reserved
        Bit  3     - BOR_LEV[1]
        Bit  2     - BOR_LEV[0]
        Bit  1     - OPTSTRT (Start option modification)
        Bit  0     - OPTLOCK (Lock option bytes)
    """
    rdp: int = RDPLevel.LEVEL_0     # Read protection
    nwrp: int = 0xFFF               # Write protection (1=not protected)
    bor_lev: int = 3                # Brown-out reset level
    nrst_stdby: bool = True         # No reset on standby
    nrst_stop: bool = True          # No reset on stop
    iwdg_sw: bool = True            # IWDG software mode
    wwdg_sw: bool = True            # WWDG software mode

    def to_optcr(self) -> int:
        """Convert to OPTCR register value."""
        value = 0
        value |= (self.nwrp & 0xFFF) << 16
        value |= (self.rdp & 0xFF) << 8
        value |= (1 if self.nrst_stdby else 0) << 6
        value |= (1 if self.nrst_stop else 0) << 5
        value |= (self.bor_lev & 0x3) << 2
        value |= 0x01  # OPTLOCK = 1 (locked by default)
        return value

    @classmethod
    def from_optcr(cls, value: int) -> 'OptionBytes':
        """Create from OPTCR register value."""
        return cls(
            nwrp=(value >> 16) & 0xFFF,
            rdp=(value >> 8) & 0xFF,
            nrst_stdby=bool(value & (1 << 6)),
            nrst_stop=bool(value & (1 << 5)),
            bor_lev=(value >> 2) & 0x3,
        )


class OptionBytesPeripheral:
    """
    Option Bytes peripheral emulation.

    Handles reads/writes to the Option Bytes registers.
    """

    def __init__(self):
        self.base = STM32F4Memory.OPTION_BYTES_BASE
        self.size = 0x10
        self.option_bytes = OptionBytes()
        self.optlock = True         # Option bytes locked
        self.keyr_sequence = []     # Key sequence for unlock
        self.log = logging.getLogger('OptBytes')

    def read(self, offset: int, size: int) -> int:
        """Read option bytes register."""
        if offset == OptionBytesReg.OPTCR:
            value = self.option_bytes.to_optcr()
            if self.optlock:
                value |= 0x01
            self.log.debug(f"Read OPTCR: 0x{value:08X}")
            return value
        return 0

    def write(self, offset: int, size: int, value: int):
        """Write option bytes register."""
        if offset == OptionBytesReg.OPTCR:
            self.log.debug(f"Write OPTCR: 0x{value:08X}")

            # Check OPTLOCK
            if self.optlock and not (value & 0x01):
                self.log.warning("Cannot modify OPTCR while locked")
                return

            # Update option bytes (simplified - real HW needs key sequence)
            self.option_bytes = OptionBytes.from_optcr(value)

            # Check for OPTSTRT (start programming)
            if value & 0x02:
                self.log.info("Option bytes programming started")
                # In real HW, this triggers flash programming


# =============================================================================
# BOOTROM EMULATION
# =============================================================================

class BootloaderCommand(IntEnum):
    """STM32 UART bootloader commands."""
    GET = 0x00              # Get version and allowed commands
    GET_VERSION = 0x01      # Get version and read protection status
    GET_ID = 0x02           # Get chip ID
    READ_MEMORY = 0x11      # Read memory
    GO = 0x21               # Jump to user code
    WRITE_MEMORY = 0x31     # Write memory
    ERASE = 0x43            # Erase flash
    EXTENDED_ERASE = 0x44   # Extended erase
    WRITE_PROTECT = 0x63    # Enable write protection
    WRITE_UNPROTECT = 0x73  # Disable write protection
    READOUT_PROTECT = 0x82  # Enable read protection
    READOUT_UNPROTECT = 0x92  # Disable read protection


class STM32F4Bootrom:
    """
    STM32F4 System Memory bootloader emulation.

    Emulates the built-in bootrom behavior including:
    - Boot mode selection
    - UART/SPI/USB bootloader protocol
    - Flash programming
    - Read/Write protection
    """

    # Bootrom identification
    BOOTLOADER_VERSION = 0x31   # Version 3.1
    CHIP_ID = 0x0413            # STM32F405/407

    # Protocol constants
    ACK = 0x79
    NACK = 0x1F

    def __init__(self):
        self.boot_pins = BootPins()
        self.option_bytes = OptionBytesPeripheral()

        # Memory for bootrom operations
        self.flash_data: Dict[int, int] = {}
        self.sram_data: Dict[int, int] = {}

        # State
        self.active = False
        self.state = 'IDLE'
        self.rx_buffer: List[int] = []

        # Callbacks
        self.on_go: Optional[Callable[[int], None]] = None  # Called when GO command executed
        self.on_flash_write: Optional[Callable[[int, bytes], None]] = None

        self.log = logging.getLogger('Bootrom')

    def set_boot_pins(self, boot0: bool, boot1: bool = False):
        """Set boot pin configuration."""
        self.boot_pins.boot0 = boot0
        self.boot_pins.boot1 = boot1
        self.log.info(f"Boot pins: BOOT0={int(boot0)}, BOOT1={int(boot1)} -> {self.boot_pins.mode.name}")

    def get_boot_mode(self) -> BootMode:
        """Get current boot mode based on pin configuration."""
        return self.boot_pins.mode

    def get_alias_base(self) -> int:
        """Get the base address that 0x00000000 is aliased to."""
        mode = self.get_boot_mode()
        if mode == BootMode.USER_FLASH:
            return STM32F4Memory.FLASH_BASE
        elif mode == BootMode.SYSTEM_MEMORY:
            return STM32F4Memory.SYSTEM_MEM_BASE
        else:  # EMBEDDED_SRAM
            return STM32F4Memory.SRAM_BASE

    def get_entry_point(self, flash_data: bytes = None) -> Tuple[int, int]:
        """
        Get initial SP and PC based on boot mode.

        Returns:
            (initial_sp, reset_handler_address)
        """
        alias_base = self.get_alias_base()

        if flash_data and len(flash_data) >= 8:
            # Read from provided firmware image
            initial_sp = struct.unpack('<I', flash_data[0:4])[0]
            reset_handler = struct.unpack('<I', flash_data[4:8])[0]
        else:
            # Default values
            initial_sp = STM32F4Memory.SRAM_BASE + STM32F4Memory.SRAM_SIZE
            reset_handler = alias_base + 4  # Just after SP

        self.log.info(f"Entry point: SP=0x{initial_sp:08X}, PC=0x{reset_handler:08X}")
        return (initial_sp, reset_handler)

    def is_bootrom_active(self) -> bool:
        """Check if bootrom should be active."""
        return self.get_boot_mode() == BootMode.SYSTEM_MEMORY

    # =========================================================================
    # UART BOOTLOADER PROTOCOL
    # =========================================================================

    def uart_receive(self, byte: int) -> List[int]:
        """
        Process byte received on UART bootloader.

        Returns response bytes to send.
        """
        if not self.is_bootrom_active():
            return []

        if self.state == 'IDLE':
            # Waiting for sync byte (0x7F)
            if byte == 0x7F:
                self.active = True
                self.state = 'COMMAND'
                self.rx_buffer = []
                self.log.info("UART bootloader synchronized")
                return [self.ACK]

        elif self.state == 'COMMAND':
            # Waiting for command + complement
            self.rx_buffer.append(byte)
            if len(self.rx_buffer) >= 2:
                cmd = self.rx_buffer[0]
                complement = self.rx_buffer[1]
                self.rx_buffer = []

                if cmd ^ complement != 0xFF:
                    self.log.warning(f"Invalid command complement: {cmd:02X} ^ {complement:02X}")
                    return [self.NACK]

                return self._handle_command(cmd)

        return []

    def _handle_command(self, cmd: int) -> List[int]:
        """Handle bootloader command."""
        self.log.debug(f"Command: 0x{cmd:02X}")

        if cmd == BootloaderCommand.GET:
            # Return version and supported commands
            supported = [
                BootloaderCommand.GET,
                BootloaderCommand.GET_VERSION,
                BootloaderCommand.GET_ID,
                BootloaderCommand.READ_MEMORY,
                BootloaderCommand.GO,
                BootloaderCommand.WRITE_MEMORY,
                BootloaderCommand.ERASE,
            ]
            response = [self.ACK, len(supported), self.BOOTLOADER_VERSION]
            response.extend(supported)
            response.append(self.ACK)
            return response

        elif cmd == BootloaderCommand.GET_VERSION:
            # Return version and option bytes
            response = [self.ACK, self.BOOTLOADER_VERSION, 0x00, 0x00, self.ACK]
            return response

        elif cmd == BootloaderCommand.GET_ID:
            # Return chip ID
            pid_high = (self.CHIP_ID >> 8) & 0xFF
            pid_low = self.CHIP_ID & 0xFF
            response = [self.ACK, 0x01, pid_high, pid_low, self.ACK]
            return response

        elif cmd == BootloaderCommand.GO:
            # Jump to address (simplified - would need address in real protocol)
            self.log.info("GO command - jumping to user code")
            if self.on_go:
                self.on_go(STM32F4Memory.FLASH_BASE)
            return [self.ACK, self.ACK]

        elif cmd == BootloaderCommand.READ_MEMORY:
            # Read memory (simplified)
            self.state = 'READ_ADDR'
            return [self.ACK]

        elif cmd == BootloaderCommand.WRITE_MEMORY:
            # Write memory (simplified)
            self.state = 'WRITE_ADDR'
            return [self.ACK]

        elif cmd == BootloaderCommand.ERASE:
            # Erase flash (simplified - mass erase)
            self.log.info("Erase command - clearing flash")
            self.flash_data.clear()
            return [self.ACK, self.ACK]

        else:
            self.log.warning(f"Unknown command: 0x{cmd:02X}")
            return [self.NACK]


# =============================================================================
# BOOT SEQUENCE EMULATOR
# =============================================================================

class STM32F4BootSequence:
    """
    Full STM32F4 boot sequence emulation.

    This class orchestrates the complete boot process:
    1. Sample boot pins
    2. Configure memory alias
    3. Load initial SP and PC
    4. Execute bootrom or user firmware
    """

    def __init__(self):
        self.bootrom = STM32F4Bootrom()
        self.log = logging.getLogger('BootSeq')

        # Memory contents
        self.flash: bytes = bytes()
        self.bootrom_image: bytes = bytes()

        # Boot state
        self.initial_sp = 0
        self.initial_pc = 0
        self.booted = False

    def load_firmware(self, firmware_path: str):
        """Load firmware image from file."""
        with open(firmware_path, 'rb') as f:
            self.flash = f.read()
        self.log.info(f"Loaded firmware: {len(self.flash)} bytes")

    def load_firmware_bytes(self, data: bytes):
        """Load firmware from bytes."""
        self.flash = data
        self.log.info(f"Loaded firmware: {len(self.flash)} bytes")

    def load_bootrom(self, bootrom_path: str):
        """Load bootrom image from file."""
        with open(bootrom_path, 'rb') as f:
            self.bootrom_image = f.read()
        self.log.info(f"Loaded bootrom: {len(self.bootrom_image)} bytes")

    def configure_boot_mode(self, boot0: bool, boot1: bool = False):
        """Configure boot pins."""
        self.bootrom.set_boot_pins(boot0, boot1)

    def execute_boot(self) -> Tuple[int, int]:
        """
        Execute boot sequence.

        Returns:
            (initial_sp, reset_handler_pc)
        """
        mode = self.bootrom.get_boot_mode()
        self.log.info(f"Boot mode: {mode.name}")

        if mode == BootMode.USER_FLASH:
            # Boot from user flash
            if len(self.flash) >= 8:
                self.initial_sp = struct.unpack('<I', self.flash[0:4])[0]
                self.initial_pc = struct.unpack('<I', self.flash[4:8])[0]
            else:
                self.log.error("No firmware loaded!")
                self.initial_sp = STM32F4Memory.SRAM_BASE + STM32F4Memory.SRAM_SIZE
                self.initial_pc = STM32F4Memory.FLASH_BASE

        elif mode == BootMode.SYSTEM_MEMORY:
            # Boot from bootrom
            if len(self.bootrom_image) >= 8:
                self.initial_sp = struct.unpack('<I', self.bootrom_image[0:4])[0]
                self.initial_pc = struct.unpack('<I', self.bootrom_image[4:8])[0]
            else:
                # Use default bootrom entry
                self.initial_sp = STM32F4Memory.SRAM_BASE + STM32F4Memory.SRAM_SIZE
                self.initial_pc = STM32F4Memory.SYSTEM_MEM_BASE + 4
                self.log.info("Using simulated bootrom entry")

        else:  # EMBEDDED_SRAM
            # Boot from SRAM (rare, used for debugging)
            self.initial_sp = STM32F4Memory.SRAM_BASE + STM32F4Memory.SRAM_SIZE
            self.initial_pc = STM32F4Memory.SRAM_BASE + 4

        self.booted = True
        self.log.info(f"Boot: SP=0x{self.initial_sp:08X}, PC=0x{self.initial_pc:08X}")

        return (self.initial_sp, self.initial_pc)

    def get_vector_table_base(self) -> int:
        """Get vector table base address based on boot mode."""
        return self.bootrom.get_alias_base()

    def read_memory(self, addr: int, size: int) -> bytes:
        """Read from the appropriate memory region."""
        # Check which region
        if STM32F4Memory.FLASH_BASE <= addr < STM32F4Memory.FLASH_BASE + STM32F4Memory.FLASH_SIZE:
            offset = addr - STM32F4Memory.FLASH_BASE
            if offset + size <= len(self.flash):
                return self.flash[offset:offset + size]

        elif STM32F4Memory.SYSTEM_MEM_BASE <= addr < STM32F4Memory.SYSTEM_MEM_BASE + STM32F4Memory.SYSTEM_MEM_SIZE:
            offset = addr - STM32F4Memory.SYSTEM_MEM_BASE
            if offset + size <= len(self.bootrom_image):
                return self.bootrom_image[offset:offset + size]

        # Alias at 0x00000000
        elif addr < 0x00100000:
            alias_base = self.get_vector_table_base()
            return self.read_memory(alias_base + addr, size)

        return bytes(size)


# =============================================================================
# MAIN (Demo/Test)
# =============================================================================

def demo():
    """Demonstrate bootrom functionality."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)-10s: %(message)s'
    )

    print("=" * 60)
    print("STM32F4 Bootrom Emulation Demo")
    print("=" * 60)

    # Create boot sequence
    boot = STM32F4BootSequence()

    # Create a minimal firmware image
    # Vector table: SP, Reset_Handler, NMI, HardFault, ...
    initial_sp = 0x20020000  # Top of SRAM
    reset_handler = 0x08000101  # Flash + offset (thumb)

    firmware = struct.pack('<II', initial_sp, reset_handler)
    firmware += bytes([0] * 120)  # Padding for other vectors
    firmware += bytes([0x00, 0xBF] * 10)  # NOP instructions

    boot.load_firmware_bytes(firmware)

    # Test different boot modes
    print("\n--- Boot Mode: User Flash (BOOT0=0) ---")
    boot.configure_boot_mode(boot0=False, boot1=False)
    sp, pc = boot.execute_boot()
    print(f"Entry: SP=0x{sp:08X}, PC=0x{pc:08X}")
    assert pc == reset_handler, "Should boot to user firmware"

    print("\n--- Boot Mode: System Memory (BOOT0=1, BOOT1=0) ---")
    boot.configure_boot_mode(boot0=True, boot1=False)
    sp, pc = boot.execute_boot()
    print(f"Entry: SP=0x{sp:08X}, PC=0x{pc:08X}")

    print("\n--- Boot Mode: SRAM (BOOT0=1, BOOT1=1) ---")
    boot.configure_boot_mode(boot0=True, boot1=True)
    sp, pc = boot.execute_boot()
    print(f"Entry: SP=0x{sp:08X}, PC=0x{pc:08X}")

    # Test bootloader protocol
    print("\n--- UART Bootloader Protocol ---")
    bootrom = STM32F4Bootrom()
    bootrom.set_boot_pins(boot0=True, boot1=False)

    # Sync
    response = bootrom.uart_receive(0x7F)
    print(f"Sync: TX=0x7F, RX={[hex(b) for b in response]}")

    # GET command
    response = bootrom.uart_receive(BootloaderCommand.GET)
    response.extend(bootrom.uart_receive(~BootloaderCommand.GET & 0xFF))
    print(f"GET: RX={[hex(b) for b in response[:5]]}...")

    # GET_ID command
    bootrom.rx_buffer = []
    bootrom.state = 'COMMAND'
    response = bootrom.uart_receive(BootloaderCommand.GET_ID)
    response.extend(bootrom.uart_receive(~BootloaderCommand.GET_ID & 0xFF))
    print(f"GET_ID: RX={[hex(b) for b in response]}")
    chip_id = (response[2] << 8) | response[3]
    print(f"Chip ID: 0x{chip_id:04X}")

    print("\nDemo complete!")


if __name__ == '__main__':
    demo()
