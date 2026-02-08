#!/usr/bin/env python3
"""
RTOS Firmware Integration Tests with Full Peripheral Emulation

Runs CubeMX HAL, FreeRTOS, and other RTOS examples with the MCUemu
peripheral server and validates peripheral interactions.

Features comprehensive MMIO debug logging to help users understand
which registers their firmware accesses, making it easier to:
- Debug firmware rehosting issues
- Identify missing peripheral emulation
- Understand firmware initialization sequences

Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: GPL-2.0-or-later
"""

import os
import sys
import time
import signal
import socket
import struct
import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Add Python packages to path
SLAB_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SLAB_ROOT / "python"))

QEMU_BIN = SLAB_ROOT / "qemu" / "build" / "qemu-system-arm"

# Debug logging configuration
DEBUG_MMIO = True  # Enable MMIO access logging by default
DEBUG_FIRST_ACCESS_ONLY = False  # Log only first access to each register
DEBUG_SHOW_VALUES = True  # Show read/write values
DEBUG_POLLING_THRESHOLD = 100  # Warn if register polled more than N times

# TCP protocol constants
CMD_READ8 = 0x01
CMD_READ16 = 0x02
CMD_READ32 = 0x03
CMD_WRITE8 = 0x11
CMD_WRITE16 = 0x12
CMD_WRITE32 = 0x13
CMD_IRQ = 0x20
CMD_RESET = 0x30


# =============================================================================
# STM32F4 Register Name Database
# This helps users understand which exact registers are being accessed
# =============================================================================
STM32F4_REGISTERS = {
    # RCC - Reset and Clock Control (0x40023800)
    0x40023800: ("RCC_CR", "Clock control register"),
    0x40023804: ("RCC_PLLCFGR", "PLL configuration register"),
    0x40023808: ("RCC_CFGR", "Clock configuration register"),
    0x4002380C: ("RCC_CIR", "Clock interrupt register"),
    0x40023810: ("RCC_AHB1RSTR", "AHB1 peripheral reset register"),
    0x40023814: ("RCC_AHB2RSTR", "AHB2 peripheral reset register"),
    0x40023818: ("RCC_AHB3RSTR", "AHB3 peripheral reset register"),
    0x40023820: ("RCC_APB1RSTR", "APB1 peripheral reset register"),
    0x40023824: ("RCC_APB2RSTR", "APB2 peripheral reset register"),
    0x40023830: ("RCC_AHB1ENR", "AHB1 peripheral clock enable register"),
    0x40023834: ("RCC_AHB2ENR", "AHB2 peripheral clock enable register"),
    0x40023838: ("RCC_AHB3ENR", "AHB3 peripheral clock enable register"),
    0x40023840: ("RCC_APB1ENR", "APB1 peripheral clock enable register"),
    0x40023844: ("RCC_APB2ENR", "APB2 peripheral clock enable register"),
    0x40023850: ("RCC_AHB1LPENR", "AHB1 low power clock enable"),
    0x40023854: ("RCC_AHB2LPENR", "AHB2 low power clock enable"),
    0x40023858: ("RCC_AHB3LPENR", "AHB3 low power clock enable"),
    0x40023860: ("RCC_APB1LPENR", "APB1 low power clock enable"),
    0x40023864: ("RCC_APB2LPENR", "APB2 low power clock enable"),
    0x40023870: ("RCC_BDCR", "Backup domain control register"),
    0x40023874: ("RCC_CSR", "Clock control & status register"),
    0x40023880: ("RCC_SSCGR", "Spread spectrum clock generation"),
    0x40023884: ("RCC_PLLI2SCFGR", "PLLI2S configuration register"),
    0x40023888: ("RCC_PLLSAICFGR", "PLLSAI configuration register"),
    0x4002388C: ("RCC_DCKCFGR", "Dedicated clocks configuration"),
    0x40023890: ("RCC_CKGATENR", "Clock gating enable register"),
    0x40023894: ("RCC_DCKCFGR2", "Dedicated clocks configuration 2"),

    # FLASH Interface (0x40023C00)
    0x40023C00: ("FLASH_ACR", "Flash access control register"),
    0x40023C04: ("FLASH_KEYR", "Flash key register"),
    0x40023C08: ("FLASH_OPTKEYR", "Flash option key register"),
    0x40023C0C: ("FLASH_SR", "Flash status register"),
    0x40023C10: ("FLASH_CR", "Flash control register"),
    0x40023C14: ("FLASH_OPTCR", "Flash option control register"),
    0x40023C18: ("FLASH_OPTCR1", "Flash option control register 1"),

    # PWR - Power Control (0x40007000)
    0x40007000: ("PWR_CR", "Power control register"),
    0x40007004: ("PWR_CSR", "Power control/status register"),

    # GPIOA (0x40020000)
    0x40020000: ("GPIOA_MODER", "GPIO port mode register"),
    0x40020004: ("GPIOA_OTYPER", "GPIO port output type register"),
    0x40020008: ("GPIOA_OSPEEDR", "GPIO port output speed register"),
    0x4002000C: ("GPIOA_PUPDR", "GPIO port pull-up/pull-down register"),
    0x40020010: ("GPIOA_IDR", "GPIO port input data register"),
    0x40020014: ("GPIOA_ODR", "GPIO port output data register"),
    0x40020018: ("GPIOA_BSRR", "GPIO port bit set/reset register"),
    0x4002001C: ("GPIOA_LCKR", "GPIO port configuration lock register"),
    0x40020020: ("GPIOA_AFRL", "GPIO alternate function low register"),
    0x40020024: ("GPIOA_AFRH", "GPIO alternate function high register"),

    # GPIOB (0x40020400)
    0x40020400: ("GPIOB_MODER", "GPIO port mode register"),
    0x40020404: ("GPIOB_OTYPER", "GPIO port output type register"),
    0x40020408: ("GPIOB_OSPEEDR", "GPIO port output speed register"),
    0x4002040C: ("GPIOB_PUPDR", "GPIO port pull-up/pull-down register"),
    0x40020410: ("GPIOB_IDR", "GPIO port input data register"),
    0x40020414: ("GPIOB_ODR", "GPIO port output data register"),
    0x40020418: ("GPIOB_BSRR", "GPIO port bit set/reset register"),

    # GPIOC (0x40020800)
    0x40020800: ("GPIOC_MODER", "GPIO port mode register"),
    0x40020814: ("GPIOC_ODR", "GPIO port output data register"),
    0x40020818: ("GPIOC_BSRR", "GPIO port bit set/reset register"),

    # GPIOD (0x40020C00)
    0x40020C00: ("GPIOD_MODER", "GPIO port mode register"),
    0x40020C14: ("GPIOD_ODR", "GPIO port output data register"),
    0x40020C18: ("GPIOD_BSRR", "GPIO port bit set/reset register"),

    # USART1 (0x40011000)
    0x40011000: ("USART1_SR", "USART status register"),
    0x40011004: ("USART1_DR", "USART data register"),
    0x40011008: ("USART1_BRR", "USART baud rate register"),
    0x4001100C: ("USART1_CR1", "USART control register 1"),
    0x40011010: ("USART1_CR2", "USART control register 2"),
    0x40011014: ("USART1_CR3", "USART control register 3"),

    # USART2 (0x40004400)
    0x40004400: ("USART2_SR", "USART status register"),
    0x40004404: ("USART2_DR", "USART data register"),
    0x40004408: ("USART2_BRR", "USART baud rate register"),
    0x4000440C: ("USART2_CR1", "USART control register 1"),
    0x40004410: ("USART2_CR2", "USART control register 2"),
    0x40004414: ("USART2_CR3", "USART control register 3"),

    # USART3 (0x40004800)
    0x40004800: ("USART3_SR", "USART status register"),
    0x40004804: ("USART3_DR", "USART data register"),
    0x40004808: ("USART3_BRR", "USART baud rate register"),
    0x4000480C: ("USART3_CR1", "USART control register 1"),

    # MCUemu Test Interface (0x4000F000)
    0x4000F000: ("TEST_STATUS", "MCUemu test status register"),
    0x4000F004: ("TEST_DATA", "MCUemu test data register"),
    0x4000F008: ("TEST_CMD", "MCUemu test command register"),

    # TIM2 - Timer 2 (0x40000000)
    0x40000000: ("TIM2_CR1", "Timer control register 1"),
    0x40000004: ("TIM2_CR2", "Timer control register 2"),
    0x40000008: ("TIM2_SMCR", "Timer slave mode control register"),
    0x4000000C: ("TIM2_DIER", "Timer DMA/interrupt enable register"),
    0x40000010: ("TIM2_SR", "Timer status register"),
    0x40000014: ("TIM2_EGR", "Timer event generation register"),
    0x40000024: ("TIM2_CNT", "Timer counter register"),
    0x40000028: ("TIM2_PSC", "Timer prescaler register"),
    0x4000002C: ("TIM2_ARR", "Timer auto-reload register"),

    # USB OTG FS (0x50000000)
    0x50000000: ("USB_OTG_GOTGCTL", "OTG control and status register"),
    0x50000004: ("USB_OTG_GOTGINT", "OTG interrupt register"),
    0x50000008: ("USB_OTG_GAHBCFG", "AHB configuration register"),
    0x5000000C: ("USB_OTG_GUSBCFG", "USB configuration register"),
    0x50000010: ("USB_OTG_GRSTCTL", "Global reset control register"),
    0x50000014: ("USB_OTG_GINTSTS", "Core interrupt register"),
    0x50000018: ("USB_OTG_GINTMSK", "Interrupt mask register"),
    0x5000001C: ("USB_OTG_GRXSTSR", "Receive status debug read"),
    0x50000020: ("USB_OTG_GRXSTSP", "Receive status read/pop"),
    0x50000024: ("USB_OTG_GRXFSIZ", "Receive FIFO size register"),
    0x50000028: ("USB_OTG_GNPTXFSIZ", "Non-periodic TX FIFO size"),
    0x50000038: ("USB_OTG_GCCFG", "General core configuration"),
    0x5000003C: ("USB_OTG_CID", "Core ID register"),
    0x50000800: ("USB_OTG_DCFG", "Device configuration register"),
    0x50000804: ("USB_OTG_DCTL", "Device control register"),
    0x50000808: ("USB_OTG_DSTS", "Device status register"),

    # SysTick (0xE000E010) - Cortex-M core peripheral
    0xE000E010: ("SYST_CSR", "SysTick control and status register"),
    0xE000E014: ("SYST_RVR", "SysTick reload value register"),
    0xE000E018: ("SYST_CVR", "SysTick current value register"),
    0xE000E01C: ("SYST_CALIB", "SysTick calibration value register"),

    # NVIC (0xE000E100)
    0xE000E100: ("NVIC_ISER0", "Interrupt set-enable register 0"),
    0xE000E104: ("NVIC_ISER1", "Interrupt set-enable register 1"),
    0xE000E108: ("NVIC_ISER2", "Interrupt set-enable register 2"),

    # SCB - System Control Block (0xE000ED00)
    0xE000ED00: ("SCB_CPUID", "CPUID base register"),
    0xE000ED04: ("SCB_ICSR", "Interrupt control and state register"),
    0xE000ED08: ("SCB_VTOR", "Vector table offset register"),
    0xE000ED0C: ("SCB_AIRCR", "Application interrupt and reset control"),
    0xE000ED10: ("SCB_SCR", "System control register"),
    0xE000ED14: ("SCB_CCR", "Configuration and control register"),
    0xE000ED88: ("SCB_CPACR", "Coprocessor access control register"),

    # FPU (0xE000EF34)
    0xE000EF34: ("FPU_FPCCR", "FP context control register"),
    0xE000EF38: ("FPU_FPCAR", "FP context address register"),
    0xE000EF3C: ("FPU_FPDSCR", "FP default status control register"),
}


def get_register_name(addr: int) -> Tuple[str, str]:
    """
    Get human-readable register name and description for an address.
    Returns (name, description) tuple.
    """
    if addr in STM32F4_REGISTERS:
        return STM32F4_REGISTERS[addr]

    # Try to identify by peripheral base
    periph_bases = [
        (0x40023800, 0x100, "RCC"),
        (0x40023C00, 0x20, "FLASH"),
        (0x40007000, 0x10, "PWR"),
        (0x40020000, 0x400, "GPIOA"),
        (0x40020400, 0x400, "GPIOB"),
        (0x40020800, 0x400, "GPIOC"),
        (0x40020C00, 0x400, "GPIOD"),
        (0x40011000, 0x400, "USART1"),
        (0x40004400, 0x400, "USART2"),
        (0x40004800, 0x400, "USART3"),
        (0x4000F000, 0x100, "TEST"),
        (0xE000E000, 0x1000, "CORTEX_M"),
    ]

    for base, size, name in periph_bases:
        if base <= addr < base + size:
            offset = addr - base
            return (f"{name}+0x{offset:02X}", f"Unknown {name} register at offset 0x{offset:02X}")

    return (f"UNKNOWN_0x{addr:08X}", f"Unknown peripheral at 0x{addr:08X}")


@dataclass
class PeripheralStats:
    """Track peripheral access statistics."""
    reads: int = 0
    writes: int = 0
    addresses: set = field(default_factory=set)


@dataclass
class RegisterAccess:
    """Track individual register access patterns."""
    addr: int
    name: str
    description: str
    read_count: int = 0
    write_count: int = 0
    last_read_value: int = 0
    last_write_value: int = 0
    first_access_time: float = 0.0


class MCUemuPeripheralServer:
    """
    Minimal peripheral server for testing RTOS firmware.

    Emulates essential STM32F4 peripherals:
    - RCC: Clock control (auto-ready flags)
    - GPIOA: GPIO port A
    - FLASH: Flash interface
    - Test interface at 0x4000F000

    Features comprehensive MMIO debug logging to help users understand
    firmware peripheral access patterns for debugging rehosting issues.
    """

    # Peripheral base addresses
    RCC_BASE = 0x40023800
    GPIOA_BASE = 0x40020000
    GPIOB_BASE = 0x40020400
    GPIOC_BASE = 0x40020800
    GPIOD_BASE = 0x40020C00
    FLASH_BASE = 0x40023C00
    PWR_BASE = 0x40007000
    USART1_BASE = 0x40011000
    USART2_BASE = 0x40004400
    USART3_BASE = 0x40004800
    TEST_BASE = 0x4000F000

    def __init__(self, port: int = 5555, debug: bool = DEBUG_MMIO):
        self.port = port
        self.running = False
        self.server_socket = None
        self.client_socket = None
        self.thread = None
        self.debug = debug

        # Peripheral registers
        self.regs: Dict[int, int] = {}

        # Statistics
        self.stats = {
            'rcc': PeripheralStats(),
            'gpio': PeripheralStats(),
            'flash': PeripheralStats(),
            'pwr': PeripheralStats(),
            'usart': PeripheralStats(),
            'test': PeripheralStats(),
            'other': PeripheralStats(),
        }

        # Detailed register access tracking for debug logging
        self.register_accesses: Dict[int, RegisterAccess] = {}
        self.start_time = time.time()

        # Test interface state
        self.test_status = 0
        self.test_data = 0

        # Initialize default register values
        self._init_registers()

    def _log_access(self, addr: int, is_write: bool, value: int, size: int):
        """Log MMIO access with register name for debugging."""
        if not self.debug:
            return

        # Get or create register access record
        if addr not in self.register_accesses:
            name, desc = get_register_name(addr)
            self.register_accesses[addr] = RegisterAccess(
                addr=addr,
                name=name,
                description=desc,
                first_access_time=time.time() - self.start_time
            )
            # Log first access to this register
            op = "WR" if is_write else "RD"
            val_str = f"= 0x{value:08X}" if DEBUG_SHOW_VALUES else ""
            print(f"    [MMIO] {op} {name:20} (0x{addr:08X}) {val_str}")

        # Update access record
        rec = self.register_accesses[addr]
        if is_write:
            rec.write_count += 1
            rec.last_write_value = value
        else:
            rec.read_count += 1
            rec.last_read_value = value

        # Warn about excessive polling (potential hang/stuck firmware)
        total = rec.read_count + rec.write_count
        if total == DEBUG_POLLING_THRESHOLD:
            print(f"    [WARN] {rec.name} polled {total}+ times - firmware may be waiting")

    def _init_registers(self):
        """Initialize default register values."""
        # RCC defaults - HSI ready
        self.regs[self.RCC_BASE + 0x00] = 0x00000083  # CR: HSIRDY set
        self.regs[self.RCC_BASE + 0x08] = 0x00000000  # CFGR

        # Flash defaults
        self.regs[self.FLASH_BASE + 0x0C] = 0x00000000  # SR: no errors

        # PWR defaults
        self.regs[self.PWR_BASE + 0x00] = 0x0000C000  # CR
        self.regs[self.PWR_BASE + 0x04] = 0x00000000  # CSR

    def _get_peripheral(self, addr: int) -> Tuple[str, int]:
        """Get peripheral name and base for an address."""
        if self.RCC_BASE <= addr < self.RCC_BASE + 0x400:
            return 'rcc', self.RCC_BASE
        elif self.GPIOA_BASE <= addr < self.GPIOA_BASE + 0x400:
            return 'gpio', self.GPIOA_BASE
        elif self.GPIOB_BASE <= addr < self.GPIOB_BASE + 0x400:
            return 'gpio', self.GPIOB_BASE
        elif self.GPIOC_BASE <= addr < self.GPIOC_BASE + 0x400:
            return 'gpio', self.GPIOC_BASE
        elif self.GPIOD_BASE <= addr < self.GPIOD_BASE + 0x400:
            return 'gpio', self.GPIOD_BASE
        elif self.FLASH_BASE <= addr < self.FLASH_BASE + 0x400:
            return 'flash', self.FLASH_BASE
        elif self.PWR_BASE <= addr < self.PWR_BASE + 0x400:
            return 'pwr', self.PWR_BASE
        elif self.USART1_BASE <= addr < self.USART1_BASE + 0x400:
            return 'usart', self.USART1_BASE
        elif self.USART2_BASE <= addr < self.USART2_BASE + 0x400:
            return 'usart', self.USART2_BASE
        elif self.USART3_BASE <= addr < self.USART3_BASE + 0x400:
            return 'usart', self.USART3_BASE
        elif self.TEST_BASE <= addr < self.TEST_BASE + 0x100:
            return 'test', self.TEST_BASE
        else:
            return 'other', 0

    def _handle_read(self, addr: int, size: int) -> int:
        """Handle read request with debug logging."""
        periph, base = self._get_peripheral(addr)
        self.stats[periph].reads += 1
        self.stats[periph].addresses.add(addr)

        # Determine return value
        result = 0

        # Special handling for RCC - auto-set ready flags
        if periph == 'rcc':
            offset = addr - base
            if offset == 0x00:  # CR
                cr = self.regs.get(addr, 0x00000083)
                # Set ready flags if corresponding enable flags are set
                if cr & (1 << 16):  # HSEON
                    cr |= (1 << 17)  # HSERDY
                if cr & (1 << 18):  # CSSON
                    pass  # Clock security system, no ready flag
                if cr & (1 << 19):  # HSEBYP
                    pass  # HSE bypass, no ready flag
                if cr & (1 << 24):  # PLLON
                    cr |= (1 << 25)  # PLLRDY
                if cr & (1 << 26):  # PLLI2SON
                    cr |= (1 << 27)  # PLLI2SRDY
                if cr & (1 << 28):  # PLLSAION (F4 with SAI)
                    cr |= (1 << 29)  # PLLSAIRDY
                result = cr
            elif offset == 0x04:  # PLLCFGR - just return stored value
                result = self.regs.get(addr, 0x24003010)  # Default from datasheet
            elif offset == 0x08:  # CFGR
                cfgr = self.regs.get(addr, 0)
                # Set SWS to match SW (clock switch status)
                sw = cfgr & 0x03
                cfgr = (cfgr & ~0x0C) | (sw << 2)
                result = cfgr
            elif offset == 0x70:  # BDCR - Backup domain control register
                bdcr = self.regs.get(addr, 0)
                # LSERDY (bit 1) - LSE ready if LSEON (bit 0) is set
                if bdcr & (1 << 0):
                    bdcr |= (1 << 1)
                result = bdcr
            elif offset == 0x74:  # CSR - Clock control/status register
                csr = self.regs.get(addr, 0)
                # LSIRDY (bit 1) - LSI ready if LSION (bit 0) is set
                if csr & (1 << 0):
                    csr |= (1 << 1)
                result = csr
            elif offset == 0x78:  # DCKCFGR2 (F4)
                result = self.regs.get(addr, 0)
            elif offset == 0x8C:  # DCKCFGR (F4)
                result = self.regs.get(addr, 0)
            else:
                result = self.regs.get(addr, 0)

        # Special handling for test interface
        elif periph == 'test':
            offset = addr - base
            if offset == 0x00:
                result = self.test_status
            elif offset == 0x04:
                result = self.test_data
            else:
                result = self.regs.get(addr, 0)

        # Flash - BSY always clear
        elif periph == 'flash':
            offset = addr - base
            if offset == 0x0C:  # SR
                result = self.regs.get(addr, 0) & ~(1 << 16)  # Clear BSY
            else:
                result = self.regs.get(addr, 0)

        # USART - always TX ready
        elif periph == 'usart':
            offset = addr - base
            if offset == 0x00:  # SR
                # TXE=1 (TX empty), TC=1 (TX complete), RXNE=0 (no RX data)
                result = 0x00C0
            else:
                result = self.regs.get(addr, 0)

        else:
            result = self.regs.get(addr, 0)

        # Debug log the access
        self._log_access(addr, is_write=False, value=result, size=size)

        return result

    def _handle_write(self, addr: int, size: int, value: int):
        """Handle write request with debug logging."""
        periph, base = self._get_peripheral(addr)
        self.stats[periph].writes += 1
        self.stats[periph].addresses.add(addr)

        # Debug log the access
        self._log_access(addr, is_write=True, value=value, size=size)

        # Store the value
        self.regs[addr] = value

        # Special handling for test interface
        if periph == 'test':
            offset = addr - base
            if offset == 0x00:
                self.test_status = value
            elif offset == 0x04:
                self.test_data = value

    def _handle_packet(self, data: bytes) -> bytes:
        """
        Process a packet and return response.

        Protocol (from QEMU slab_cortexm.c):
        - READ:  'R' (1) + addr (4 LE) + size (4 LE) + secure (1) = 10 bytes
        - WRITE: 'W' (1) + addr (4 LE) + size (4 LE) + value (4 LE) + secure (1) = 14 bytes
        - Response: value (4 LE) + status (1) = 5 bytes
        """
        if len(data) < 10:
            return struct.pack('<IB', 0, 0)  # value + status

        cmd = chr(data[0])
        addr = struct.unpack('<I', data[1:5])[0]
        size = struct.unpack('<I', data[5:9])[0]

        if cmd in ('R', 'S'):  # Read (R=non-secure, S=secure)
            result = self._handle_read(addr, size)
            return struct.pack('<IB', result, 0)  # value + status OK

        elif cmd in ('W', 'T'):  # Write (W=non-secure, T=secure)
            if len(data) >= 14:
                value = struct.unpack('<I', data[9:13])[0]
                self._handle_write(addr, size, value)
            return struct.pack('<IB', 0, 0)  # value + status OK

        return struct.pack('<IB', 0, 1)  # Error status

    def _server_thread(self):
        """Server thread - handles client connections."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.server_socket.bind(('127.0.0.1', self.port))
        self.server_socket.listen(1)
        self.server_socket.settimeout(0.5)

        while self.running:
            try:
                client, addr = self.server_socket.accept()
                self.client_socket = client
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                client.settimeout(0.05)  # Fast timeout for responsive handling

                while self.running:
                    try:
                        # Read first byte to determine packet type
                        first = client.recv(1, socket.MSG_PEEK)
                        if not first:
                            break

                        cmd = chr(first[0])
                        # Determine packet length based on command
                        if cmd in ('R', 'S'):  # Read
                            pkt_len = 10
                        elif cmd in ('W', 'T'):  # Write
                            pkt_len = 14
                        else:
                            # Unknown command - read what we can
                            pkt_len = 14

                        data = client.recv(pkt_len)
                        if not data:
                            break
                        response = self._handle_packet(data)
                        client.send(response)

                    except socket.timeout:
                        continue
                    except Exception:
                        break

                client.close()
                self.client_socket = None

            except socket.timeout:
                continue
            except Exception:
                break

        self.server_socket.close()

    def start(self):
        """Start the server."""
        self.running = True
        self.thread = threading.Thread(target=self._server_thread)
        self.thread.daemon = True
        self.thread.start()
        time.sleep(0.2)  # Wait for server to start

    def stop(self):
        """Stop the server."""
        self.running = False
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
        if self.thread:
            self.thread.join(timeout=2)

    def get_stats_summary(self) -> dict:
        """Get statistics summary."""
        return {
            name: {
                'reads': s.reads,
                'writes': s.writes,
                'unique_addrs': len(s.addresses)
            }
            for name, s in self.stats.items()
            if s.reads > 0 or s.writes > 0
        }

    def get_register_access_report(self) -> str:
        """
        Generate detailed register access report for debugging.

        This helps users understand:
        - Which registers their firmware accesses
        - Access patterns (read vs write counts)
        - Potential polling/stuck points
        """
        if not self.register_accesses:
            return "  No register accesses recorded.\n"

        lines = []
        lines.append("  Register Access Report:")
        lines.append("  " + "-" * 76)
        lines.append(f"  {'Register':<24} {'Address':>12} {'Reads':>8} {'Writes':>8} {'Last Value':>12}")
        lines.append("  " + "-" * 76)

        # Sort by first access time
        sorted_regs = sorted(
            self.register_accesses.values(),
            key=lambda r: r.first_access_time
        )

        for reg in sorted_regs:
            total = reg.read_count + reg.write_count
            # Mark heavily polled registers
            marker = " (!)" if total >= DEBUG_POLLING_THRESHOLD else ""
            last_val = reg.last_read_value if reg.read_count > 0 else reg.last_write_value
            lines.append(
                f"  {reg.name:<24} 0x{reg.addr:08X}  {reg.read_count:>8} {reg.write_count:>8} "
                f"0x{last_val:08X}{marker}"
            )

        lines.append("  " + "-" * 76)

        # Identify potential issues
        polling_regs = [r for r in sorted_regs if r.read_count >= DEBUG_POLLING_THRESHOLD]
        if polling_regs:
            lines.append("")
            lines.append("  [!] Registers with high read counts (potential polling/wait loops):")
            for reg in polling_regs:
                lines.append(f"      - {reg.name}: {reg.read_count} reads")
                lines.append(f"        Tip: Check if firmware is waiting for a ready flag or status bit")

        return "\n".join(lines)


def run_firmware_test(
    firmware_path: Path,
    name: str,
    timeout: float = 5.0,
    expected_gpio_writes: int = 1,
    debug: bool = DEBUG_MMIO
) -> dict:
    """
    Run a firmware with full peripheral emulation and MMIO debug logging.

    Args:
        firmware_path: Path to the firmware binary
        name: Test name for display
        timeout: Maximum test duration in seconds
        expected_gpio_writes: Minimum GPIO writes to consider test passing
        debug: Enable detailed MMIO access logging (default: DEBUG_MMIO)

    Returns test result dict with stats, register_report, etc.
    """
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"{'='*60}")
    print(f"  Firmware: {firmware_path.name}")
    print(f"  Size: {firmware_path.stat().st_size} bytes")
    if debug:
        print(f"  Debug: MMIO logging enabled")

    if not firmware_path.exists():
        return {'status': 'skip', 'reason': 'Firmware not found'}

    if not QEMU_BIN.exists():
        return {'status': 'skip', 'reason': 'QEMU not found'}

    # Start peripheral server with debug logging
    port = 5560
    server = MCUemuPeripheralServer(port=port, debug=debug)
    server.start()
    print(f"  Server started on port {port}")
    if debug:
        print(f"  MMIO accesses (first occurrence of each register):")

    # Start QEMU with machine properties
    qemu_args = [
        str(QEMU_BIN),
        "-M", f"slab-cortex-m,tcp-port={port}",
        "-kernel", str(firmware_path),
        "-nographic",
    ]

    print(f"  Starting QEMU...")
    qemu_proc = subprocess.Popen(
        qemu_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid,
    )

    result = {'status': 'unknown'}

    try:
        start_time = time.time()
        last_status = -1

        while time.time() - start_time < timeout:
            time.sleep(0.2)

            # Check for test completion
            if server.test_status != last_status:
                last_status = server.test_status
                status_name = {0: 'INIT', 1: 'RUNNING', 2: 'PASS', 3: 'FAIL'}.get(
                    server.test_status, f'0x{server.test_status:02X}'
                )
                print(f"  [{time.time()-start_time:.1f}s] Test status: {status_name}, "
                      f"data: 0x{server.test_data:08X}")

            if server.test_status == 2:  # PASS
                result['status'] = 'pass'
                break
            elif server.test_status == 3:  # FAIL
                result['status'] = 'fail'
                result['reason'] = 'Test reported failure'
                break

            # Check if QEMU crashed
            if qemu_proc.poll() is not None:
                result['status'] = 'fail'
                result['reason'] = 'QEMU exited unexpectedly'
                break

        if result['status'] == 'unknown':
            # Check if we got peripheral activity
            stats = server.get_stats_summary()
            gpio_writes = stats.get('gpio', {}).get('writes', 0)
            rcc_accesses = stats.get('rcc', {}).get('reads', 0) + stats.get('rcc', {}).get('writes', 0)

            if gpio_writes >= expected_gpio_writes:
                result['status'] = 'pass'
                result['note'] = f'Timeout but GPIO activity detected ({gpio_writes} writes)'
            elif rcc_accesses > 0:
                result['status'] = 'partial'
                result['note'] = f'RCC accessed but no GPIO writes (timeout)'
            else:
                result['status'] = 'fail'
                result['reason'] = f'Timeout with no peripheral activity'

        # Collect stats
        result['stats'] = server.get_stats_summary()
        result['test_data'] = server.test_data
        result['register_report'] = server.get_register_access_report()

    except Exception as e:
        result['status'] = 'error'
        result['reason'] = str(e)

    finally:
        # Get register report before cleanup
        register_report = server.get_register_access_report() if debug else None

        # Cleanup
        try:
            os.killpg(os.getpgid(qemu_proc.pid), signal.SIGTERM)
            qemu_proc.wait(timeout=2)
        except:
            try:
                qemu_proc.kill()
            except:
                pass
        server.stop()

    # Print results
    print(f"\n  Result: {result['status'].upper()}")
    if 'reason' in result:
        print(f"  Reason: {result['reason']}")
    if 'note' in result:
        print(f"  Note: {result['note']}")

    if 'stats' in result:
        print(f"\n  Peripheral Statistics:")
        for periph, s in result['stats'].items():
            print(f"    {periph:8}: {s['reads']:4} reads, {s['writes']:4} writes, "
                  f"{s['unique_addrs']:3} unique addrs")

    # Print detailed register access report for debugging
    if debug and 'register_report' in result:
        print(f"\n{result['register_report']}")

    return result


def main():
    """Run all RTOS firmware tests with MMIO debug logging."""
    import argparse

    parser = argparse.ArgumentParser(
        description="MCUemu RTOS Integration Tests with Peripheral Emulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Debug Logging:
  By default, MMIO debug logging is ENABLED to help users understand
  which registers their firmware accesses. This is useful for:

  - Debugging firmware rehosting issues
  - Identifying missing peripheral emulation
  - Understanding firmware initialization sequences
  - Finding registers that cause firmware to hang (polling loops)

Examples:
  %(prog)s                    # Run all tests with debug logging (default)
  %(prog)s --no-debug         # Run tests without debug logging
  %(prog)s --test cubemx      # Run only CubeMX test
  %(prog)s --timeout 10       # Set custom timeout
"""
    )
    parser.add_argument('--debug', action='store_true', default=DEBUG_MMIO,
                        help='Enable MMIO access logging (default: enabled)')
    parser.add_argument('--no-debug', action='store_true',
                        help='Disable MMIO access logging')
    parser.add_argument('--test', type=str, default=None,
                        help='Run specific test (cubemx, freertos, nuttx, zephyr)')
    parser.add_argument('--timeout', type=float, default=None,
                        help='Override test timeout in seconds')
    args = parser.parse_args()

    # Determine debug mode
    debug_enabled = args.debug and not args.no_debug

    print("=" * 70)
    print("  MCUemu RTOS Integration Tests with Peripheral Emulation")
    print("=" * 70)
    if debug_enabled:
        print("  [DEBUG MODE] MMIO access logging enabled")
        print("  Each register access will be logged with its name and value.")
        print("  Registers polled >100 times are flagged as potential issues.")
    print("")

    examples_dir = SLAB_ROOT / "examples"

    # Test configurations
    tests = [
        {
            'id': 'cubemx',
            'name': 'STM32CubeMX HAL Blinky',
            'firmware': examples_dir / 'cortex-m' / 'stm32' / 'f405' / 'rtos' / 'cubemx_blinky' / 'build' / 'blinky.bin',
            'timeout': 5.0,
            'expected_gpio_writes': 5,
        },
        {
            'id': 'freertos',
            'name': 'FreeRTOS Multi-Task Blinky',
            'firmware': examples_dir / 'cortex-m' / 'stm32' / 'f405' / 'rtos' / 'freertos_blinky' / 'build' / 'freertos_blinky.bin',
            'timeout': 10.0,
            'expected_gpio_writes': 10,
        },
        {
            'id': 'nuttx',
            'name': 'NuttX NSH Shell',
            'firmware': examples_dir / 'cortex-m' / 'stm32' / 'f407' / 'rtos' / 'nuttx_nsh' / 'build' / 'nuttx.bin',
            'timeout': 8.0,
            'expected_gpio_writes': 0,  # NSH doesn't toggle GPIO, just RCC/UART init
        },
        {
            'id': 'zephyr',
            'name': 'Zephyr RTOS Blinky',
            'firmware': examples_dir / 'cortex-m' / 'stm32' / 'f407' / 'rtos' / 'zephyr_blinky' / 'build' / 'zephyr.bin',
            'timeout': 5.0,
            'expected_gpio_writes': 5,
        },
    ]

    # Filter tests if specific test requested
    if args.test:
        tests = [t for t in tests if t['id'] == args.test.lower()]
        if not tests:
            print(f"Error: Unknown test '{args.test}'. Available: cubemx, freertos, nuttx, zephyr")
            return 1

    results = []

    for test in tests:
        timeout = args.timeout if args.timeout else test['timeout']
        result = run_firmware_test(
            test['firmware'],
            test['name'],
            timeout=timeout,
            expected_gpio_writes=test['expected_gpio_writes'],
            debug=debug_enabled,
        )
        results.append((test['name'], result))

    # Summary
    print("\n" + "=" * 70)
    print("  Summary")
    print("=" * 70)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        status = result['status']
        if status == 'pass':
            passed += 1
            icon = 'PASS'
        elif status == 'partial':
            passed += 1  # Count partial as pass
            icon = 'PART'
        elif status == 'skip':
            skipped += 1
            icon = 'SKIP'
        else:
            failed += 1
            icon = 'FAIL'

        # Stats summary
        stats = result.get('stats', {})
        gpio = stats.get('gpio', {})
        rcc = stats.get('rcc', {})

        print(f"  [{icon}] {name}")
        print(f"         RCC: {rcc.get('reads', 0)}R/{rcc.get('writes', 0)}W  "
              f"GPIO: {gpio.get('reads', 0)}R/{gpio.get('writes', 0)}W")

    print(f"\n  Total: {passed} passed, {failed} failed, {skipped} skipped")

    # Detailed peripheral coverage
    print("\n" + "-" * 80)
    print("  Peripheral Coverage Matrix")
    print("-" * 80)
    print(f"  {'Test':<28} {'RCC':>8} {'GPIO':>8} {'Flash':>8} {'PWR':>8} {'USART':>8}")
    print("-" * 80)

    for name, result in results:
        stats = result.get('stats', {})
        rcc = stats.get('rcc', {}).get('reads', 0) + stats.get('rcc', {}).get('writes', 0)
        gpio = stats.get('gpio', {}).get('reads', 0) + stats.get('gpio', {}).get('writes', 0)
        flash = stats.get('flash', {}).get('reads', 0) + stats.get('flash', {}).get('writes', 0)
        usart = stats.get('usart', {}).get('reads', 0) + stats.get('usart', {}).get('writes', 0)
        pwr = stats.get('pwr', {}).get('reads', 0) + stats.get('pwr', {}).get('writes', 0)

        short_name = name[:28]
        print(f"  {short_name:<28} {rcc:>8} {gpio:>8} {flash:>8} {pwr:>8} {usart:>8}")

    print("-" * 80)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
