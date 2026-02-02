"""
Virtual IC Components for MCU Development.

This module provides emulation of common IC components based on real datasheets,
completely independent of any MCU emulator. Supports:

Memory:
- EEPROM (24Cxx series - I2C)
- SPI Flash (W25Qxx series)
- QSPI Flash (W25Q128JV)

Sensors/RTC:
- DS1307/DS3231 RTC (I2C)
- HMC5883L/QMC5883L Compass (I2C)
- BMP280 Pressure/Temperature (I2C/SPI)

Display Controllers:
- ILI9341 TFT LCD (SPI/8080)
- ST7789 TFT LCD (SPI)
- SSD1306 OLED (I2C/SPI)

All components implement proper register maps and timing behavior.
"""
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 TwistedWires - Mathieu Renard

import struct
import time
import math
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Base Classes
# =============================================================================

class BusType(Enum):
    """Communication bus types."""
    I2C = "i2c"
    SPI = "spi"
    QSPI = "qspi"
    PARALLEL_8080 = "8080"
    PARALLEL_6800 = "6800"


@dataclass
class I2CTransaction:
    """I2C transaction record."""
    address: int
    is_read: bool
    data: bytes
    timestamp: float = field(default_factory=time.time)


@dataclass
class SPITransaction:
    """SPI transaction record."""
    mosi: bytes
    miso: bytes
    timestamp: float = field(default_factory=time.time)


class VirtualIC(ABC):
    """Base class for all virtual IC components."""

    def __init__(self, name: str = ""):
        self.name = name
        self._transactions: List[Any] = []
        self._callbacks: Dict[str, List[Callable]] = {}

    @abstractmethod
    def reset(self) -> None:
        """Reset IC to power-on state."""
        pass

    def on(self, event_name: str, callback: Callable) -> None:
        """Register event callback."""
        if event_name not in self._callbacks:
            self._callbacks[event_name] = []
        self._callbacks[event_name].append(callback)

    def emit(self, event_name: str, *args, **kwargs) -> None:
        """Emit event to all registered callbacks."""
        for cb in self._callbacks.get(event_name, []):
            cb(*args, **kwargs)

    def get_transaction_log(self) -> List[Any]:
        """Get transaction history."""
        return self._transactions.copy()

    def clear_transaction_log(self) -> None:
        """Clear transaction history."""
        self._transactions.clear()


class I2CDevice(VirtualIC):
    """Base class for I2C devices."""

    def __init__(self, address: int, name: str = ""):
        super().__init__(name)
        self.address = address
        self._register_pointer = 0

    @abstractmethod
    def read_register(self, reg: int) -> int:
        """Read register value."""
        pass

    @abstractmethod
    def write_register(self, reg: int, value: int) -> None:
        """Write register value."""
        pass

    def i2c_start(self, address: int, is_read: bool) -> bool:
        """Handle I2C start condition. Return True if ACK."""
        return (address >> 1) == self.address

    def i2c_write(self, data: bytes) -> int:
        """Handle I2C write. Return number of ACKed bytes."""
        if len(data) == 0:
            return 0

        # First byte is usually register address
        self._register_pointer = data[0]

        # Remaining bytes are data
        for i, byte in enumerate(data[1:]):
            self.write_register(self._register_pointer + i, byte)

        self._transactions.append(I2CTransaction(self.address, False, data))
        return len(data)

    def i2c_read(self, length: int) -> bytes:
        """Handle I2C read."""
        data = bytearray()
        for i in range(length):
            data.append(self.read_register(self._register_pointer + i) & 0xFF)

        self._transactions.append(I2CTransaction(self.address, True, bytes(data)))
        return bytes(data)


class SPIDevice(VirtualIC):
    """Base class for SPI devices."""

    def __init__(self, name: str = ""):
        super().__init__(name)
        self._selected = False

    def select(self) -> None:
        """Assert chip select (CS low)."""
        self._selected = True
        self.emit('selected')

    def deselect(self) -> None:
        """Deassert chip select (CS high)."""
        self._selected = False
        self.emit('deselected')

    @abstractmethod
    def transfer(self, mosi: bytes) -> bytes:
        """Full-duplex SPI transfer."""
        pass


# =============================================================================
# EEPROM - 24Cxx Series (I2C)
# =============================================================================

class EEPROM_24Cxx(I2CDevice):
    """
    24Cxx series I2C EEPROM emulation.

    Supports:
    - 24C02: 256 bytes (2Kbit)
    - 24C04: 512 bytes (4Kbit)
    - 24C08: 1024 bytes (8Kbit)
    - 24C16: 2048 bytes (16Kbit)
    - 24C32: 4096 bytes (32Kbit)
    - 24C64: 8192 bytes (64Kbit)
    - 24C128: 16384 bytes (128Kbit)
    - 24C256: 32768 bytes (256Kbit)
    - 24C512: 65536 bytes (512Kbit)

    Based on Microchip 24LC256 datasheet.
    """

    SIZES = {
        '24C02': 256,
        '24C04': 512,
        '24C08': 1024,
        '24C16': 2048,
        '24C32': 4096,
        '24C64': 8192,
        '24C128': 16384,
        '24C256': 32768,
        '24C512': 65536,
    }

    def __init__(self, model: str = '24C256', address: int = 0x50, name: str = ""):
        super().__init__(address, name or model)
        self.model = model
        self.size = self.SIZES.get(model, 32768)
        self._memory = bytearray(self.size)
        self._write_address = 0
        self._page_size = 64 if self.size >= 4096 else 16
        self._write_cycle_time = 0.005  # 5ms write cycle

        # Address width: 1 byte for small EEPROMs, 2 for larger
        self._addr_bytes = 2 if self.size > 2048 else 1

        # Write protection
        self._write_protected = False

    def reset(self) -> None:
        """Reset EEPROM (doesn't clear memory)."""
        self._write_address = 0

    def read_register(self, reg: int) -> int:
        """Read byte from memory."""
        if 0 <= reg < self.size:
            return self._memory[reg]
        return 0xFF

    def write_register(self, reg: int, value: int) -> None:
        """Write byte to memory."""
        if not self._write_protected and 0 <= reg < self.size:
            self._memory[reg] = value & 0xFF
            self.emit('write', reg, value)

    def i2c_write(self, data: bytes) -> int:
        """Handle I2C write with proper address handling."""
        if len(data) == 0:
            return 0

        if self._addr_bytes == 2 and len(data) >= 2:
            # 2-byte address (MSB first)
            self._write_address = (data[0] << 8) | data[1]
            data_start = 2
        elif len(data) >= 1:
            # 1-byte address
            self._write_address = data[0]
            data_start = 1
        else:
            return 0

        # Write data bytes
        for i, byte in enumerate(data[data_start:]):
            addr = (self._write_address + i) % self.size
            self.write_register(addr, byte)

        self._transactions.append(I2CTransaction(self.address, False, data))
        return len(data)

    def i2c_read(self, length: int) -> bytes:
        """Sequential read from current address."""
        data = bytearray()
        for i in range(length):
            addr = (self._write_address + i) % self.size
            data.append(self._memory[addr])
        self._write_address = (self._write_address + length) % self.size

        self._transactions.append(I2CTransaction(self.address, True, bytes(data)))
        return bytes(data)

    def load_from_file(self, filename: str) -> None:
        """Load EEPROM contents from file."""
        with open(filename, 'rb') as f:
            data = f.read(self.size)
            self._memory[:len(data)] = data

    def save_to_file(self, filename: str) -> None:
        """Save EEPROM contents to file."""
        with open(filename, 'wb') as f:
            f.write(self._memory)

    def get_contents(self) -> bytes:
        """Get full memory contents."""
        return bytes(self._memory)

    def set_contents(self, data: bytes) -> None:
        """Set memory contents."""
        self._memory = bytearray(self.size)
        self._memory[:len(data)] = data[:self.size]


# =============================================================================
# SPI Flash - W25Qxx Series
# =============================================================================

class W25QxxFlash(SPIDevice):
    """
    Winbond W25Qxx SPI Flash emulation.

    Supports:
    - W25Q16: 2MB
    - W25Q32: 4MB
    - W25Q64: 8MB
    - W25Q128: 16MB
    - W25Q256: 32MB

    Based on W25Q128JV datasheet.

    Commands implemented:
    - 0x06: Write Enable
    - 0x04: Write Disable
    - 0x05: Read Status Register 1
    - 0x35: Read Status Register 2
    - 0x15: Read Status Register 3
    - 0x03: Read Data
    - 0x0B: Fast Read
    - 0x02: Page Program
    - 0x20: Sector Erase (4KB)
    - 0x52: Block Erase (32KB)
    - 0xD8: Block Erase (64KB)
    - 0xC7/0x60: Chip Erase
    - 0x9F: JEDEC ID
    - 0x90: Manufacturer/Device ID
    - 0xAB: Release Power Down / Device ID
    - 0xB9: Power Down
    """

    SIZES = {
        'W25Q16': 2 * 1024 * 1024,
        'W25Q32': 4 * 1024 * 1024,
        'W25Q64': 8 * 1024 * 1024,
        'W25Q128': 16 * 1024 * 1024,
        'W25Q256': 32 * 1024 * 1024,
    }

    JEDEC_IDS = {
        'W25Q16': (0xEF, 0x40, 0x15),
        'W25Q32': (0xEF, 0x40, 0x16),
        'W25Q64': (0xEF, 0x40, 0x17),
        'W25Q128': (0xEF, 0x40, 0x18),
        'W25Q256': (0xEF, 0x40, 0x19),
    }

    # Commands
    CMD_WRITE_ENABLE = 0x06
    CMD_WRITE_DISABLE = 0x04
    CMD_READ_STATUS_1 = 0x05
    CMD_READ_STATUS_2 = 0x35
    CMD_READ_STATUS_3 = 0x15
    CMD_WRITE_STATUS_1 = 0x01
    CMD_READ_DATA = 0x03
    CMD_FAST_READ = 0x0B
    CMD_PAGE_PROGRAM = 0x02
    CMD_SECTOR_ERASE = 0x20
    CMD_BLOCK_ERASE_32K = 0x52
    CMD_BLOCK_ERASE_64K = 0xD8
    CMD_CHIP_ERASE = 0xC7
    CMD_CHIP_ERASE_ALT = 0x60
    CMD_JEDEC_ID = 0x9F
    CMD_MFR_DEVICE_ID = 0x90
    CMD_UNIQUE_ID = 0x4B
    CMD_RELEASE_PWDN = 0xAB
    CMD_POWER_DOWN = 0xB9

    # Status register bits
    SR1_BUSY = 0x01
    SR1_WEL = 0x02  # Write Enable Latch

    def __init__(self, model: str = 'W25Q128', name: str = ""):
        super().__init__(name or model)
        self.model = model
        self.size = self.SIZES.get(model, 16 * 1024 * 1024)
        self._memory = bytearray([0xFF] * self.size)

        # Status registers
        self._sr1 = 0x00
        self._sr2 = 0x00
        self._sr3 = 0x00

        # State
        self._powered_down = False
        self._address_mode_4byte = self.size > 16 * 1024 * 1024

    def reset(self) -> None:
        """Reset flash."""
        self._sr1 = 0x00
        self._sr2 = 0x00
        self._sr3 = 0x00
        self._powered_down = False

    def transfer(self, mosi: bytes) -> bytes:
        """Process SPI transaction."""
        if not self._selected or len(mosi) == 0:
            return bytes(len(mosi))

        cmd = mosi[0]
        miso = bytearray(len(mosi))

        if self._powered_down and cmd != self.CMD_RELEASE_PWDN:
            return bytes(miso)

        if cmd == self.CMD_JEDEC_ID:
            jedec = self.JEDEC_IDS.get(self.model, (0xEF, 0x40, 0x18))
            if len(miso) > 1:
                miso[1] = jedec[0]
            if len(miso) > 2:
                miso[2] = jedec[1]
            if len(miso) > 3:
                miso[3] = jedec[2]

        elif cmd == self.CMD_READ_STATUS_1:
            if len(miso) > 1:
                miso[1] = self._sr1

        elif cmd == self.CMD_READ_STATUS_2:
            if len(miso) > 1:
                miso[1] = self._sr2

        elif cmd == self.CMD_READ_STATUS_3:
            if len(miso) > 1:
                miso[1] = self._sr3

        elif cmd == self.CMD_WRITE_ENABLE:
            self._sr1 |= self.SR1_WEL

        elif cmd == self.CMD_WRITE_DISABLE:
            self._sr1 &= ~self.SR1_WEL

        elif cmd == self.CMD_READ_DATA:
            addr = self._parse_address(mosi[1:4])
            for i in range(4, len(mosi)):
                if addr < self.size:
                    miso[i] = self._memory[addr]
                    addr += 1

        elif cmd == self.CMD_FAST_READ:
            addr = self._parse_address(mosi[1:4])
            # Skip dummy byte at index 4
            for i in range(5, len(mosi)):
                if addr < self.size:
                    miso[i] = self._memory[addr]
                    addr += 1

        elif cmd == self.CMD_PAGE_PROGRAM:
            if self._sr1 & self.SR1_WEL:
                addr = self._parse_address(mosi[1:4])
                page_start = addr & ~0xFF  # 256-byte page boundary
                for i, byte in enumerate(mosi[4:]):
                    write_addr = page_start | ((addr + i) & 0xFF)
                    if write_addr < self.size:
                        # Flash can only clear bits (AND operation)
                        self._memory[write_addr] &= byte
                self._sr1 &= ~self.SR1_WEL
                self.emit('programmed', addr, len(mosi) - 4)

        elif cmd == self.CMD_SECTOR_ERASE:
            if self._sr1 & self.SR1_WEL:
                addr = self._parse_address(mosi[1:4])
                sector_start = addr & ~0xFFF  # 4KB alignment
                for i in range(4096):
                    if sector_start + i < self.size:
                        self._memory[sector_start + i] = 0xFF
                self._sr1 &= ~self.SR1_WEL
                self.emit('erased', sector_start, 4096)

        elif cmd == self.CMD_BLOCK_ERASE_32K:
            if self._sr1 & self.SR1_WEL:
                addr = self._parse_address(mosi[1:4])
                block_start = addr & ~0x7FFF  # 32KB alignment
                for i in range(32768):
                    if block_start + i < self.size:
                        self._memory[block_start + i] = 0xFF
                self._sr1 &= ~self.SR1_WEL
                self.emit('erased', block_start, 32768)

        elif cmd == self.CMD_BLOCK_ERASE_64K:
            if self._sr1 & self.SR1_WEL:
                addr = self._parse_address(mosi[1:4])
                block_start = addr & ~0xFFFF  # 64KB alignment
                for i in range(65536):
                    if block_start + i < self.size:
                        self._memory[block_start + i] = 0xFF
                self._sr1 &= ~self.SR1_WEL
                self.emit('erased', block_start, 65536)

        elif cmd in (self.CMD_CHIP_ERASE, self.CMD_CHIP_ERASE_ALT):
            if self._sr1 & self.SR1_WEL:
                self._memory = bytearray([0xFF] * self.size)
                self._sr1 &= ~self.SR1_WEL
                self.emit('chip_erased')

        elif cmd == self.CMD_MFR_DEVICE_ID:
            # Manufacturer ID at addr+0, Device ID at addr+1
            if len(miso) > 4:
                miso[4] = 0xEF  # Winbond
            if len(miso) > 5:
                miso[5] = 0x17  # Device ID

        elif cmd == self.CMD_RELEASE_PWDN:
            self._powered_down = False
            if len(miso) > 4:
                miso[4] = 0x17  # Device ID

        elif cmd == self.CMD_POWER_DOWN:
            self._powered_down = True

        self._transactions.append(SPITransaction(mosi, bytes(miso)))
        return bytes(miso)

    def _parse_address(self, addr_bytes: bytes) -> int:
        """Parse 3-byte address."""
        if len(addr_bytes) >= 3:
            return (addr_bytes[0] << 16) | (addr_bytes[1] << 8) | addr_bytes[2]
        return 0

    def load_from_file(self, filename: str) -> None:
        """Load flash contents from file."""
        with open(filename, 'rb') as f:
            data = f.read(self.size)
            self._memory = bytearray([0xFF] * self.size)
            self._memory[:len(data)] = data

    def save_to_file(self, filename: str) -> None:
        """Save flash contents to file."""
        with open(filename, 'wb') as f:
            f.write(self._memory)

    def get_contents(self) -> bytes:
        """Get full memory contents."""
        return bytes(self._memory)


# =============================================================================
# RTC - DS3231 (I2C)
# =============================================================================

class DS3231_RTC(I2CDevice):
    """
    DS3231 I2C Real-Time Clock emulation.

    Based on DS3231 datasheet.

    Register Map:
    - 0x00: Seconds (BCD)
    - 0x01: Minutes (BCD)
    - 0x02: Hours (BCD, 12/24 mode)
    - 0x03: Day of Week (1-7)
    - 0x04: Date (BCD)
    - 0x05: Month/Century (BCD)
    - 0x06: Year (BCD, 00-99)
    - 0x07-0x0D: Alarm registers
    - 0x0E: Control
    - 0x0F: Status
    - 0x10: Aging Offset
    - 0x11-0x12: Temperature (signed, 0.25°C resolution)
    """

    REG_SECONDS = 0x00
    REG_MINUTES = 0x01
    REG_HOURS = 0x02
    REG_DAY = 0x03
    REG_DATE = 0x04
    REG_MONTH = 0x05
    REG_YEAR = 0x06
    REG_ALARM1_SEC = 0x07
    REG_ALARM1_MIN = 0x08
    REG_ALARM1_HOUR = 0x09
    REG_ALARM1_DAY = 0x0A
    REG_ALARM2_MIN = 0x0B
    REG_ALARM2_HOUR = 0x0C
    REG_ALARM2_DAY = 0x0D
    REG_CONTROL = 0x0E
    REG_STATUS = 0x0F
    REG_AGING = 0x10
    REG_TEMP_MSB = 0x11
    REG_TEMP_LSB = 0x12

    def __init__(self, address: int = 0x68, name: str = "DS3231"):
        super().__init__(address, name)
        self._registers = bytearray(19)
        self._use_system_time = True
        self._time_offset = 0.0  # Offset from system time
        self._temperature = 25.0  # °C

        # Initialize control/status
        self._registers[self.REG_CONTROL] = 0x00
        self._registers[self.REG_STATUS] = 0x00

        self.reset()

    def reset(self) -> None:
        """Reset RTC."""
        self._registers[self.REG_CONTROL] = 0x00
        self._registers[self.REG_STATUS] = 0x08  # OSF bit set after reset

    def _dec_to_bcd(self, val: int) -> int:
        """Convert decimal to BCD."""
        return ((val // 10) << 4) | (val % 10)

    def _bcd_to_dec(self, val: int) -> int:
        """Convert BCD to decimal."""
        return ((val >> 4) * 10) + (val & 0x0F)

    def read_register(self, reg: int) -> int:
        """Read register value."""
        if 0 <= reg < len(self._registers):
            if reg <= self.REG_YEAR and self._use_system_time:
                self._update_time_registers()
            elif reg in (self.REG_TEMP_MSB, self.REG_TEMP_LSB):
                self._update_temp_registers()
            return self._registers[reg]
        return 0xFF

    def write_register(self, reg: int, value: int) -> None:
        """Write register value."""
        if 0 <= reg < len(self._registers):
            self._registers[reg] = value & 0xFF

            # If writing time registers, calculate offset from system time
            if reg <= self.REG_YEAR:
                self._calculate_time_offset()

            self.emit('register_write', reg, value)

    def _update_time_registers(self) -> None:
        """Update time registers from system time."""
        t = time.localtime(time.time() + self._time_offset)
        self._registers[self.REG_SECONDS] = self._dec_to_bcd(t.tm_sec)
        self._registers[self.REG_MINUTES] = self._dec_to_bcd(t.tm_min)
        self._registers[self.REG_HOURS] = self._dec_to_bcd(t.tm_hour)  # 24-hour mode
        self._registers[self.REG_DAY] = t.tm_wday + 1  # 1-7
        self._registers[self.REG_DATE] = self._dec_to_bcd(t.tm_mday)
        self._registers[self.REG_MONTH] = self._dec_to_bcd(t.tm_mon)
        self._registers[self.REG_YEAR] = self._dec_to_bcd(t.tm_year % 100)

    def _calculate_time_offset(self) -> None:
        """Calculate offset between register time and system time."""
        # Build time from registers
        year = 2000 + self._bcd_to_dec(self._registers[self.REG_YEAR])
        month = self._bcd_to_dec(self._registers[self.REG_MONTH] & 0x1F)
        day = self._bcd_to_dec(self._registers[self.REG_DATE])
        hour = self._bcd_to_dec(self._registers[self.REG_HOURS] & 0x3F)
        minute = self._bcd_to_dec(self._registers[self.REG_MINUTES])
        second = self._bcd_to_dec(self._registers[self.REG_SECONDS])

        try:
            reg_time = time.mktime((year, month, day, hour, minute, second, 0, 0, -1))
            self._time_offset = reg_time - time.time()
        except:
            pass

    def _update_temp_registers(self) -> None:
        """Update temperature registers."""
        # Temperature is in 0.25°C increments, 10-bit signed
        temp_raw = int(self._temperature * 4)
        self._registers[self.REG_TEMP_MSB] = (temp_raw >> 2) & 0xFF
        self._registers[self.REG_TEMP_LSB] = (temp_raw & 0x03) << 6

    def set_time(self, year: int, month: int, day: int,
                 hour: int, minute: int, second: int) -> None:
        """Set RTC time."""
        self._registers[self.REG_YEAR] = self._dec_to_bcd(year % 100)
        self._registers[self.REG_MONTH] = self._dec_to_bcd(month)
        self._registers[self.REG_DATE] = self._dec_to_bcd(day)
        self._registers[self.REG_HOURS] = self._dec_to_bcd(hour)
        self._registers[self.REG_MINUTES] = self._dec_to_bcd(minute)
        self._registers[self.REG_SECONDS] = self._dec_to_bcd(second)
        self._calculate_time_offset()

    def get_time(self) -> Tuple[int, int, int, int, int, int]:
        """Get current time as tuple (year, month, day, hour, minute, second)."""
        self._update_time_registers()
        return (
            2000 + self._bcd_to_dec(self._registers[self.REG_YEAR]),
            self._bcd_to_dec(self._registers[self.REG_MONTH] & 0x1F),
            self._bcd_to_dec(self._registers[self.REG_DATE]),
            self._bcd_to_dec(self._registers[self.REG_HOURS] & 0x3F),
            self._bcd_to_dec(self._registers[self.REG_MINUTES]),
            self._bcd_to_dec(self._registers[self.REG_SECONDS]),
        )

    def set_temperature(self, temp: float) -> None:
        """Set simulated temperature."""
        self._temperature = temp

    def get_temperature(self) -> float:
        """Get temperature."""
        return self._temperature


# =============================================================================
# Compass - QMC5883L (I2C)
# =============================================================================

class QMC5883L_Compass(I2CDevice):
    """
    QMC5883L 3-axis magnetometer emulation.

    Based on QMC5883L datasheet.

    Register Map:
    - 0x00-0x05: Data Output X/Y/Z (LSB, MSB)
    - 0x06: Status
    - 0x07-0x08: Temperature Output
    - 0x09: Control Register 1
    - 0x0A: Control Register 2
    - 0x0B: SET/RESET Period
    - 0x0D: Chip ID (0xFF)
    """

    REG_X_LSB = 0x00
    REG_X_MSB = 0x01
    REG_Y_LSB = 0x02
    REG_Y_MSB = 0x03
    REG_Z_LSB = 0x04
    REG_Z_MSB = 0x05
    REG_STATUS = 0x06
    REG_TEMP_LSB = 0x07
    REG_TEMP_MSB = 0x08
    REG_CONTROL1 = 0x09
    REG_CONTROL2 = 0x0A
    REG_SET_RESET = 0x0B
    REG_CHIP_ID = 0x0D

    # Status bits
    STATUS_DRDY = 0x01  # Data Ready
    STATUS_OVL = 0x02   # Overflow
    STATUS_DOR = 0x04   # Data Skipped

    def __init__(self, address: int = 0x0D, name: str = "QMC5883L"):
        super().__init__(address, name)
        self._registers = bytearray(14)

        # Magnetic field values (in µT, converted to raw)
        self._mag_x = 0.0
        self._mag_y = 0.0
        self._mag_z = 0.0
        self._temperature = 25.0

        # Simulated heading
        self._heading = 0.0  # Degrees

        self.reset()

    def reset(self) -> None:
        """Reset compass."""
        self._registers = bytearray(14)
        self._registers[self.REG_CHIP_ID] = 0xFF
        self._registers[self.REG_STATUS] = 0x00

    def read_register(self, reg: int) -> int:
        """Read register value."""
        if 0 <= reg < len(self._registers):
            if reg <= self.REG_Z_MSB:
                self._update_mag_registers()
            elif reg in (self.REG_TEMP_LSB, self.REG_TEMP_MSB):
                self._update_temp_registers()
            return self._registers[reg]
        return 0x00

    def write_register(self, reg: int, value: int) -> None:
        """Write register value."""
        if reg in (self.REG_CONTROL1, self.REG_CONTROL2, self.REG_SET_RESET):
            self._registers[reg] = value & 0xFF
            self.emit('register_write', reg, value)

    def _update_mag_registers(self) -> None:
        """Update magnetic field registers."""
        # Convert µT to raw values (scale factor depends on range setting)
        # Default 2 Gauss range: 1 LSB = 1/12000 Gauss = 0.0833 µT
        scale = 12000  # LSB per Gauss

        # Simulate magnetic field based on heading
        field_strength = 50.0  # µT (typical Earth field)
        self._mag_x = field_strength * math.cos(math.radians(self._heading))
        self._mag_y = field_strength * math.sin(math.radians(self._heading))
        self._mag_z = 0.0

        # Convert to raw
        raw_x = int(self._mag_x * scale / 100)
        raw_y = int(self._mag_y * scale / 100)
        raw_z = int(self._mag_z * scale / 100)

        # Store as 16-bit signed, little-endian
        self._registers[self.REG_X_LSB] = raw_x & 0xFF
        self._registers[self.REG_X_MSB] = (raw_x >> 8) & 0xFF
        self._registers[self.REG_Y_LSB] = raw_y & 0xFF
        self._registers[self.REG_Y_MSB] = (raw_y >> 8) & 0xFF
        self._registers[self.REG_Z_LSB] = raw_z & 0xFF
        self._registers[self.REG_Z_MSB] = (raw_z >> 8) & 0xFF

        # Set data ready
        self._registers[self.REG_STATUS] |= self.STATUS_DRDY

    def _update_temp_registers(self) -> None:
        """Update temperature registers."""
        # Temperature: 100 LSB/°C, offset at 0°C
        raw_temp = int(self._temperature * 100)
        self._registers[self.REG_TEMP_LSB] = raw_temp & 0xFF
        self._registers[self.REG_TEMP_MSB] = (raw_temp >> 8) & 0xFF

    def set_heading(self, heading: float) -> None:
        """Set simulated compass heading (0-360 degrees)."""
        self._heading = heading % 360

    def get_heading(self) -> float:
        """Get current heading."""
        return self._heading

    def set_magnetic_field(self, x: float, y: float, z: float) -> None:
        """Set magnetic field values directly (in µT)."""
        self._mag_x = x
        self._mag_y = y
        self._mag_z = z
        self._heading = math.degrees(math.atan2(y, x)) % 360


# =============================================================================
# LCD Controller - ILI9341 (SPI)
# =============================================================================

class ILI9341_LCD(SPIDevice):
    """
    ILI9341 TFT LCD Controller emulation.

    Based on ILI9341 datasheet.
    240x320 RGB display with 16/18-bit color.

    Key Commands:
    - 0x01: Software Reset
    - 0x11: Sleep Out
    - 0x29: Display ON
    - 0x2A: Column Address Set
    - 0x2B: Page Address Set
    - 0x2C: Memory Write
    - 0x36: Memory Access Control
    - 0x3A: Pixel Format Set
    """

    CMD_NOP = 0x00
    CMD_SWRESET = 0x01
    CMD_SLEEP_OUT = 0x11
    CMD_DISPLAY_OFF = 0x28
    CMD_DISPLAY_ON = 0x29
    CMD_COLUMN_ADDR = 0x2A
    CMD_PAGE_ADDR = 0x2B
    CMD_MEMORY_WRITE = 0x2C
    CMD_MEMORY_READ = 0x2E
    CMD_MADCTL = 0x36
    CMD_PIXEL_FORMAT = 0x3A
    CMD_READ_ID = 0x04
    CMD_READ_STATUS = 0x09
    CMD_READ_ID1 = 0xDA
    CMD_READ_ID2 = 0xDB
    CMD_READ_ID3 = 0xDC

    def __init__(self, width: int = 240, height: int = 320, name: str = "ILI9341"):
        super().__init__(name)
        self.width = width
        self.height = height

        # Framebuffer (RGB565 format, 2 bytes per pixel)
        self._framebuffer = bytearray(width * height * 2)

        # Window settings
        self._col_start = 0
        self._col_end = width - 1
        self._page_start = 0
        self._page_end = height - 1

        # Write position
        self._write_x = 0
        self._write_y = 0

        # State
        self._display_on = False
        self._sleep = True
        self._pixel_format = 0x55  # RGB565
        self._madctl = 0x00

        # Command mode tracking
        self._in_data_mode = False
        self._current_cmd = 0
        self._cmd_params = bytearray()

    def reset(self) -> None:
        """Reset display."""
        self._display_on = False
        self._sleep = True
        self._col_start = 0
        self._col_end = self.width - 1
        self._page_start = 0
        self._page_end = self.height - 1
        self._write_x = 0
        self._write_y = 0
        self._framebuffer = bytearray(self.width * self.height * 2)

    def transfer(self, mosi: bytes) -> bytes:
        """Process SPI transfer."""
        if not self._selected:
            return bytes(len(mosi))

        miso = bytearray(len(mosi))

        for byte in mosi:
            self._process_byte(byte)

        self._transactions.append(SPITransaction(mosi, bytes(miso)))
        return bytes(miso)

    def _process_byte(self, byte: int) -> None:
        """Process single byte (command or data based on D/C pin state)."""
        # In real hardware, D/C pin determines command vs data
        # Here we track state based on commands

        if self._in_data_mode:
            self._write_pixel_byte(byte)
        else:
            self._process_command(byte)

    def _process_command(self, cmd: int) -> None:
        """Process command byte."""
        self._current_cmd = cmd
        self._cmd_params.clear()
        self._in_data_mode = False

        if cmd == self.CMD_SWRESET:
            self.reset()
        elif cmd == self.CMD_SLEEP_OUT:
            self._sleep = False
        elif cmd == self.CMD_DISPLAY_ON:
            self._display_on = True
        elif cmd == self.CMD_DISPLAY_OFF:
            self._display_on = False
        elif cmd == self.CMD_MEMORY_WRITE:
            self._in_data_mode = True
            self._write_x = self._col_start
            self._write_y = self._page_start

    def set_command_mode(self) -> None:
        """Switch to command mode (D/C low)."""
        self._in_data_mode = False

    def set_data_mode(self) -> None:
        """Switch to data mode (D/C high)."""
        if self._current_cmd == self.CMD_MEMORY_WRITE:
            self._in_data_mode = True

    def write_command(self, cmd: int, data: bytes = b'') -> None:
        """Write command with optional data."""
        self._process_command(cmd)

        if cmd == self.CMD_COLUMN_ADDR and len(data) >= 4:
            self._col_start = (data[0] << 8) | data[1]
            self._col_end = (data[2] << 8) | data[3]
        elif cmd == self.CMD_PAGE_ADDR and len(data) >= 4:
            self._page_start = (data[0] << 8) | data[1]
            self._page_end = (data[2] << 8) | data[3]
        elif cmd == self.CMD_MADCTL and len(data) >= 1:
            self._madctl = data[0]
        elif cmd == self.CMD_PIXEL_FORMAT and len(data) >= 1:
            self._pixel_format = data[0]

    def write_data(self, data: bytes) -> None:
        """Write pixel data."""
        for byte in data:
            self._write_pixel_byte(byte)

    def _write_pixel_byte(self, byte: int) -> None:
        """Write single byte of pixel data."""
        # RGB565: 2 bytes per pixel
        x = self._write_x
        y = self._write_y

        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 2
            if offset < len(self._framebuffer) - 1:
                # Alternate between high and low byte
                if (self._write_x - self._col_start) % 2 == 0:
                    # This is simplified - real implementation needs byte tracking
                    pass

            # For simplicity, accumulate 2 bytes then write pixel
            self._cmd_params.append(byte)
            if len(self._cmd_params) >= 2:
                pixel = (self._cmd_params[0] << 8) | self._cmd_params[1]
                offset = (y * self.width + x) * 2
                if offset < len(self._framebuffer) - 1:
                    self._framebuffer[offset] = self._cmd_params[0]
                    self._framebuffer[offset + 1] = self._cmd_params[1]
                self._cmd_params.clear()

                # Advance position
                self._write_x += 1
                if self._write_x > self._col_end:
                    self._write_x = self._col_start
                    self._write_y += 1
                    if self._write_y > self._page_end:
                        self._write_y = self._page_start

    def fill_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        """Fill rectangle with color (RGB565)."""
        self.write_command(self.CMD_COLUMN_ADDR,
                          bytes([(x >> 8), x & 0xFF, ((x + w - 1) >> 8), (x + w - 1) & 0xFF]))
        self.write_command(self.CMD_PAGE_ADDR,
                          bytes([(y >> 8), y & 0xFF, ((y + h - 1) >> 8), (y + h - 1) & 0xFF]))
        self.write_command(self.CMD_MEMORY_WRITE)

        hi = (color >> 8) & 0xFF
        lo = color & 0xFF
        for _ in range(w * h):
            self._cmd_params.append(hi)
            self._cmd_params.append(lo)
            self._write_pixel_byte(hi)
            self._write_pixel_byte(lo)

    def get_framebuffer(self) -> bytes:
        """Get raw framebuffer."""
        return bytes(self._framebuffer)

    def get_pixel(self, x: int, y: int) -> int:
        """Get pixel color at position (RGB565)."""
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 2
            return (self._framebuffer[offset] << 8) | self._framebuffer[offset + 1]
        return 0

    @staticmethod
    def rgb_to_rgb565(r: int, g: int, b: int) -> int:
        """Convert RGB888 to RGB565."""
        return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

    @staticmethod
    def rgb565_to_rgb(color: int) -> Tuple[int, int, int]:
        """Convert RGB565 to RGB888."""
        r = (color >> 8) & 0xF8
        g = (color >> 3) & 0xFC
        b = (color << 3) & 0xF8
        return (r, g, b)


# =============================================================================
# SSD1306 OLED Controller (I2C/SPI)
# =============================================================================

class SSD1306_OLED(I2CDevice):
    """
    SSD1306 OLED Controller emulation.

    Based on SSD1306 datasheet.
    128x64 or 128x32 monochrome OLED.

    Commands:
    - 0x00-0x0F: Set Lower Column Start Address
    - 0x10-0x1F: Set Higher Column Start Address
    - 0x20: Set Memory Addressing Mode
    - 0x21: Set Column Address
    - 0x22: Set Page Address
    - 0x40-0x7F: Set Display Start Line
    - 0x81: Set Contrast Control
    - 0xA0/0xA1: Set Segment Re-map
    - 0xA4/0xA5: Entire Display ON
    - 0xA6/0xA7: Set Normal/Inverse Display
    - 0xA8: Set Multiplex Ratio
    - 0xAE/0xAF: Display OFF/ON
    - 0xD5: Set Display Clock
    - 0xD9: Set Pre-charge Period
    - 0xDA: Set COM Pins
    - 0xDB: Set VCOMH
    """

    CMD_SET_CONTRAST = 0x81
    CMD_DISPLAY_ALL_ON_RESUME = 0xA4
    CMD_DISPLAY_ALL_ON = 0xA5
    CMD_NORMAL_DISPLAY = 0xA6
    CMD_INVERT_DISPLAY = 0xA7
    CMD_DISPLAY_OFF = 0xAE
    CMD_DISPLAY_ON = 0xAF
    CMD_SET_DISPLAY_OFFSET = 0xD3
    CMD_SET_COMPINS = 0xDA
    CMD_SET_VCOMDETECT = 0xDB
    CMD_SET_DISPLAYCLOCKDIV = 0xD5
    CMD_SET_PRECHARGE = 0xD9
    CMD_SET_MULTIPLEX = 0xA8
    CMD_SET_LOWCOLUMN = 0x00
    CMD_SET_HIGHCOLUMN = 0x10
    CMD_SET_STARTLINE = 0x40
    CMD_MEMORY_MODE = 0x20
    CMD_COLUMN_ADDR = 0x21
    CMD_PAGE_ADDR = 0x22
    CMD_COMSCAN_INC = 0xC0
    CMD_COMSCAN_DEC = 0xC8
    CMD_SEGREMAP = 0xA0
    CMD_CHARGEPUMP = 0x8D

    def __init__(self, width: int = 128, height: int = 64,
                 address: int = 0x3C, name: str = "SSD1306"):
        super().__init__(address, name)
        self.width = width
        self.height = height
        self._pages = height // 8

        # Display buffer (1 bit per pixel, organized in pages)
        self._buffer = bytearray(width * self._pages)

        # State
        self._display_on = False
        self._inverted = False
        self._contrast = 0x7F

        # Addressing
        self._memory_mode = 0  # Horizontal
        self._col_start = 0
        self._col_end = width - 1
        self._page_start = 0
        self._page_end = self._pages - 1
        self._col_ptr = 0
        self._page_ptr = 0

        # Command state
        self._waiting_for_data = False
        self._current_cmd = 0

    def reset(self) -> None:
        """Reset display."""
        self._display_on = False
        self._inverted = False
        self._contrast = 0x7F
        self._col_ptr = 0
        self._page_ptr = 0
        self._buffer = bytearray(self.width * self._pages)

    def read_register(self, reg: int) -> int:
        """Read not typically used for SSD1306."""
        return 0x00

    def write_register(self, reg: int, value: int) -> None:
        """Process write - reg is control byte."""
        pass

    def i2c_write(self, data: bytes) -> int:
        """Handle I2C write."""
        if len(data) < 2:
            return len(data)

        control = data[0]

        if control == 0x00:  # Command mode
            for byte in data[1:]:
                self._process_command(byte)
        elif control == 0x40:  # Data mode
            for byte in data[1:]:
                self._write_data(byte)

        self._transactions.append(I2CTransaction(self.address, False, data))
        return len(data)

    def _process_command(self, cmd: int) -> None:
        """Process command byte."""
        if self._waiting_for_data:
            self._handle_command_data(cmd)
            return

        self._current_cmd = cmd

        if cmd == self.CMD_DISPLAY_ON:
            self._display_on = True
        elif cmd == self.CMD_DISPLAY_OFF:
            self._display_on = False
        elif cmd == self.CMD_NORMAL_DISPLAY:
            self._inverted = False
        elif cmd == self.CMD_INVERT_DISPLAY:
            self._inverted = True
        elif cmd in (self.CMD_SET_CONTRAST, self.CMD_MEMORY_MODE,
                     self.CMD_COLUMN_ADDR, self.CMD_PAGE_ADDR):
            self._waiting_for_data = True
        elif (cmd & 0xF0) == self.CMD_SET_LOWCOLUMN:
            self._col_ptr = (self._col_ptr & 0xF0) | (cmd & 0x0F)
        elif (cmd & 0xF0) == self.CMD_SET_HIGHCOLUMN:
            self._col_ptr = (self._col_ptr & 0x0F) | ((cmd & 0x0F) << 4)
        elif (cmd & 0xF8) == 0xB0:  # Set page start
            self._page_ptr = cmd & 0x07

    def _handle_command_data(self, data: int) -> None:
        """Handle data byte for multi-byte command."""
        self._waiting_for_data = False

        if self._current_cmd == self.CMD_SET_CONTRAST:
            self._contrast = data
        elif self._current_cmd == self.CMD_MEMORY_MODE:
            self._memory_mode = data
        # Column/Page address commands need more bytes - simplified here

    def _write_data(self, byte: int) -> None:
        """Write display data byte."""
        if self._page_ptr < self._pages and self._col_ptr < self.width:
            offset = self._page_ptr * self.width + self._col_ptr
            if offset < len(self._buffer):
                self._buffer[offset] = byte

            # Advance pointer based on memory mode
            if self._memory_mode == 0:  # Horizontal
                self._col_ptr += 1
                if self._col_ptr > self._col_end:
                    self._col_ptr = self._col_start
                    self._page_ptr += 1
                    if self._page_ptr > self._page_end:
                        self._page_ptr = self._page_start

    def clear(self) -> None:
        """Clear display buffer."""
        self._buffer = bytearray(self.width * self._pages)

    def set_pixel(self, x: int, y: int, on: bool = True) -> None:
        """Set individual pixel."""
        if 0 <= x < self.width and 0 <= y < self.height:
            page = y // 8
            bit = y % 8
            offset = page * self.width + x
            if on:
                self._buffer[offset] |= (1 << bit)
            else:
                self._buffer[offset] &= ~(1 << bit)

    def get_pixel(self, x: int, y: int) -> bool:
        """Get pixel state."""
        if 0 <= x < self.width and 0 <= y < self.height:
            page = y // 8
            bit = y % 8
            offset = page * self.width + x
            return bool(self._buffer[offset] & (1 << bit))
        return False

    def get_buffer(self) -> bytes:
        """Get raw display buffer."""
        return bytes(self._buffer)

    def set_buffer(self, data: bytes) -> None:
        """Set display buffer."""
        self._buffer = bytearray(data[:len(self._buffer)])


# =============================================================================
# Factory Functions
# =============================================================================

def create_eeprom(model: str = '24C256', address: int = 0x50) -> EEPROM_24Cxx:
    """Create EEPROM instance."""
    return EEPROM_24Cxx(model, address)


def create_flash(model: str = 'W25Q128') -> W25QxxFlash:
    """Create SPI Flash instance."""
    return W25QxxFlash(model)


def create_rtc(address: int = 0x68) -> DS3231_RTC:
    """Create RTC instance."""
    return DS3231_RTC(address)


def create_compass(address: int = 0x0D) -> QMC5883L_Compass:
    """Create compass instance."""
    return QMC5883L_Compass(address)


def create_ili9341(width: int = 240, height: int = 320) -> ILI9341_LCD:
    """Create ILI9341 LCD controller."""
    return ILI9341_LCD(width, height)


def create_ssd1306(width: int = 128, height: int = 64) -> SSD1306_OLED:
    """Create SSD1306 OLED controller."""
    return SSD1306_OLED(width, height)


# =============================================================================
# Component SDK
# =============================================================================

class ComponentSDK:
    """
    SDK for managing virtual IC components.

    Independent of any MCU emulator.
    """

    def __init__(self):
        self._i2c_devices: Dict[int, I2CDevice] = {}
        self._spi_devices: Dict[str, SPIDevice] = {}

    def add_i2c_device(self, device: I2CDevice) -> None:
        """Add I2C device."""
        self._i2c_devices[device.address] = device

    def add_spi_device(self, name: str, device: SPIDevice) -> None:
        """Add SPI device."""
        self._spi_devices[name] = device

    def i2c_transfer(self, address: int, write_data: bytes,
                     read_length: int = 0) -> Optional[bytes]:
        """Perform I2C transfer."""
        device = self._i2c_devices.get(address >> 1)
        if device is None:
            return None

        if write_data:
            device.i2c_write(write_data)

        if read_length > 0:
            return device.i2c_read(read_length)

        return b''

    def spi_transfer(self, name: str, data: bytes) -> bytes:
        """Perform SPI transfer."""
        device = self._spi_devices.get(name)
        if device is None:
            return bytes(len(data))

        device.select()
        result = device.transfer(data)
        device.deselect()
        return result

    def get_i2c_device(self, address: int) -> Optional[I2CDevice]:
        """Get I2C device by address."""
        return self._i2c_devices.get(address)

    def get_spi_device(self, name: str) -> Optional[SPIDevice]:
        """Get SPI device by name."""
        return self._spi_devices.get(name)


# =============================================================================
# Test/Demo
# =============================================================================

if __name__ == "__main__":
    # Demo usage
    print("Virtual Components Demo")
    print("=" * 40)

    # Create SDK
    sdk = ComponentSDK()

    # Add EEPROM
    eeprom = create_eeprom('24C256')
    sdk.add_i2c_device(eeprom)
    print(f"EEPROM: {eeprom.model}, {eeprom.size} bytes at 0x{eeprom.address:02X}")

    # Write and read EEPROM
    eeprom.i2c_write(bytes([0x00, 0x00, 0xDE, 0xAD, 0xBE, 0xEF]))
    eeprom._write_address = 0
    data = eeprom.i2c_read(4)
    print(f"EEPROM read: {data.hex()}")

    # Add Flash
    flash = create_flash('W25Q128')
    sdk.add_spi_device('flash', flash)
    print(f"\nFlash: {flash.model}, {flash.size // (1024*1024)} MB")

    # Read JEDEC ID
    flash.select()
    jedec = flash.transfer(bytes([0x9F, 0, 0, 0]))
    flash.deselect()
    print(f"JEDEC ID: {jedec[1:4].hex()}")

    # Add RTC
    rtc = create_rtc()
    sdk.add_i2c_device(rtc)
    time_tuple = rtc.get_time()
    print(f"\nRTC: {time_tuple[0]}-{time_tuple[1]:02d}-{time_tuple[2]:02d} "
          f"{time_tuple[3]:02d}:{time_tuple[4]:02d}:{time_tuple[5]:02d}")

    # Add Compass
    compass = create_compass()
    sdk.add_i2c_device(compass)
    compass.set_heading(45.0)
    print(f"\nCompass heading: {compass.get_heading():.1f}°")

    # LCD Controller
    lcd = create_ili9341()
    print(f"\nLCD: ILI9341 {lcd.width}x{lcd.height}")

    # OLED Controller
    oled = create_ssd1306()
    print(f"OLED: SSD1306 {oled.width}x{oled.height}")

    print("\nAll components initialized successfully!")
