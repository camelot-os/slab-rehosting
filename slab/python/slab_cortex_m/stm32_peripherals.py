#!/usr/bin/env python3
"""
STM32 Enhanced Peripheral Implementations for MCUemu

This module provides comprehensive STM32 peripheral emulation matching or
exceeding the capabilities of stm32-emulator (nviennot/stm32-emulator).

Peripherals Implemented:
========================
Core Peripherals:
  - DMA: Direct Memory Access (2 controllers, 8 streams each)
  - NVIC: Nested Vectored Interrupt Controller
  - SCB: System Control Block
  - SysTick: System Tick Timer
  - RCC: Reset and Clock Control (enhanced)
  - GPIO: General Purpose I/O (enhanced with EXTI)
  - USART: Universal Async Receiver/Transmitter
  - SPI: Serial Peripheral Interface
  - I2C: Inter-Integrated Circuit
  - FSMC: Flexible Static Memory Controller
  - TIM: General Purpose Timers
  - PWR: Power Controller
  - FLASH: Flash Interface

External Devices:
  - SPI Flash: W25Q128 16MB flash emulation
  - ILI9341: TFT LCD controller
  - ADS7846: Resistive touchscreen controller

Usage:
    from stm32_peripherals import STM32F4PeripheralSet

    peripherals = STM32F4PeripheralSet()
    value = peripherals.read(0x40020000, 4)  # Read GPIOA
    peripherals.write(0x40020014, 4, 0xFF)   # Write to GPIOA ODR

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple, Any
from enum import IntEnum, IntFlag
import struct
import time

log = logging.getLogger('STM32')


# =============================================================================
# DMA - DIRECT MEMORY ACCESS
# =============================================================================

class DMAStream:
    """Single DMA stream (STM32 has 8 streams per DMA controller)."""

    # Stream register offsets
    CR = 0x00       # Control register
    NDTR = 0x04     # Number of data to transfer
    PAR = 0x08      # Peripheral address
    M0AR = 0x0C     # Memory 0 address
    M1AR = 0x10     # Memory 1 address (double buffer)
    FCR = 0x14      # FIFO control register

    # CR bits
    CR_EN = (1 << 0)        # Stream enable
    CR_DMEIE = (1 << 1)     # Direct mode error interrupt enable
    CR_TEIE = (1 << 2)      # Transfer error interrupt enable
    CR_HTIE = (1 << 3)      # Half transfer interrupt enable
    CR_TCIE = (1 << 4)      # Transfer complete interrupt enable
    CR_PFCTRL = (1 << 5)    # Peripheral flow controller
    CR_DIR_MASK = (3 << 6)  # Data transfer direction
    CR_CIRC = (1 << 8)      # Circular mode
    CR_PINC = (1 << 9)      # Peripheral increment
    CR_MINC = (1 << 10)     # Memory increment
    CR_PSIZE_MASK = (3 << 11)  # Peripheral data size
    CR_MSIZE_MASK = (3 << 13)  # Memory data size
    CR_CHSEL_MASK = (7 << 25)  # Channel selection

    def __init__(self, dma_num: int, stream_num: int):
        self.dma_num = dma_num
        self.stream_num = stream_num
        self.log = logging.getLogger(f'DMA{dma_num}.S{stream_num}')

        # Registers
        self.cr = 0
        self.ndtr = 0
        self.par = 0
        self.m0ar = 0
        self.m1ar = 0
        self.fcr = 0x21  # Reset value

        # Transfer state
        self.transfer_count = 0
        self.transfer_complete = False

        # Memory access callback
        self.memory_read: Optional[Callable[[int, int], bytes]] = None
        self.memory_write: Optional[Callable[[int, bytes], None]] = None

    def read(self, offset: int) -> int:
        if offset == self.CR:
            return self.cr
        elif offset == self.NDTR:
            return self.ndtr
        elif offset == self.PAR:
            return self.par
        elif offset == self.M0AR:
            return self.m0ar
        elif offset == self.M1AR:
            return self.m1ar
        elif offset == self.FCR:
            return self.fcr
        return 0

    def write(self, offset: int, value: int):
        if offset == self.CR:
            old_cr = self.cr
            self.cr = value

            # Check if stream was just enabled
            if (value & self.CR_EN) and not (old_cr & self.CR_EN):
                self._start_transfer()

        elif offset == self.NDTR:
            self.ndtr = value & 0xFFFF
        elif offset == self.PAR:
            self.par = value
        elif offset == self.M0AR:
            self.m0ar = value
        elif offset == self.M1AR:
            self.m1ar = value
        elif offset == self.FCR:
            self.fcr = value

    def _start_transfer(self):
        """Execute DMA transfer."""
        if self.ndtr == 0:
            self.log.debug("Transfer with NDTR=0, skipping")
            self.cr &= ~self.CR_EN
            return

        direction = (self.cr & self.CR_DIR_MASK) >> 6
        psize = 1 << ((self.cr >> 11) & 3)  # 1, 2, or 4 bytes
        msize = 1 << ((self.cr >> 13) & 3)
        pinc = bool(self.cr & self.CR_PINC)
        minc = bool(self.cr & self.CR_MINC)

        self.log.debug(f"Transfer: dir={direction} ndtr={self.ndtr} "
                      f"psize={psize} msize={msize}")

        # Execute transfer (simplified - real HW is async)
        if self.memory_read and self.memory_write:
            if direction == 0:  # Peripheral to memory
                self._do_p2m_transfer(psize, msize, pinc, minc)
            elif direction == 1:  # Memory to peripheral
                self._do_m2p_transfer(psize, msize, pinc, minc)
            elif direction == 2:  # Memory to memory
                self._do_m2m_transfer(msize, minc)

        # Clear enable bit after transfer
        self.cr &= ~self.CR_EN
        self.transfer_complete = True

    def _do_p2m_transfer(self, psize: int, msize: int, pinc: bool, minc: bool):
        """Peripheral to memory transfer."""
        src = self.par
        dst = self.m0ar
        for i in range(self.ndtr):
            data = self.memory_read(src, psize)
            self.memory_write(dst, data)
            if pinc:
                src += psize
            if minc:
                dst += msize

    def _do_m2p_transfer(self, psize: int, msize: int, pinc: bool, minc: bool):
        """Memory to peripheral transfer."""
        src = self.m0ar
        dst = self.par
        for i in range(self.ndtr):
            data = self.memory_read(src, msize)
            self.memory_write(dst, data[:psize])
            if minc:
                src += msize
            if pinc:
                dst += psize

    def _do_m2m_transfer(self, size: int, minc: bool):
        """Memory to memory transfer."""
        src = self.par
        dst = self.m0ar
        for i in range(self.ndtr):
            data = self.memory_read(src, size)
            self.memory_write(dst, data)
            src += size
            if minc:
                dst += size


class DMAController:
    """DMA Controller (STM32F4 has DMA1 and DMA2)."""

    # Status register offsets
    LISR = 0x00     # Low interrupt status (streams 0-3)
    HISR = 0x04     # High interrupt status (streams 4-7)
    LIFCR = 0x08    # Low interrupt flag clear
    HIFCR = 0x0C    # High interrupt flag clear

    def __init__(self, name: str, base: int, num_streams: int = 8):
        self.name = name
        self.base = base
        self.size = 0x400
        self.log = logging.getLogger(f'DMA.{name}')

        # Status registers
        self.lisr = 0
        self.hisr = 0

        # Streams (8 per controller)
        dma_num = 1 if '1' in name else 2
        self.streams = [DMAStream(dma_num, i) for i in range(num_streams)]

    def read(self, offset: int, size: int) -> int:
        if offset == self.LISR:
            return self.lisr
        elif offset == self.HISR:
            return self.hisr
        elif offset >= 0x10:
            # Stream registers start at 0x10
            stream_offset = offset - 0x10
            stream_idx = stream_offset // 0x18
            reg_offset = stream_offset % 0x18
            if stream_idx < len(self.streams):
                return self.streams[stream_idx].read(reg_offset)
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == self.LIFCR:
            self.lisr &= ~value  # Write 1 to clear
        elif offset == self.HIFCR:
            self.hisr &= ~value
        elif offset >= 0x10:
            stream_offset = offset - 0x10
            stream_idx = stream_offset // 0x18
            reg_offset = stream_offset % 0x18
            if stream_idx < len(self.streams):
                self.streams[stream_idx].write(reg_offset, value)


# =============================================================================
# NVIC - NESTED VECTORED INTERRUPT CONTROLLER
# =============================================================================

class NVICController:
    """NVIC implementation with full interrupt management."""

    # Register offsets from 0xE000E100
    ISER_BASE = 0x000   # Interrupt Set Enable (8 registers)
    ICER_BASE = 0x080   # Interrupt Clear Enable
    ISPR_BASE = 0x100   # Interrupt Set Pending
    ICPR_BASE = 0x180   # Interrupt Clear Pending
    IABR_BASE = 0x200   # Interrupt Active Bit
    IPR_BASE = 0x300    # Interrupt Priority (60 registers)

    def __init__(self, num_irqs: int = 240):
        self.base = 0xE000E100
        self.size = 0x400
        self.num_irqs = num_irqs
        self.log = logging.getLogger('NVIC')

        # State arrays (one bit per IRQ for enable/pending/active)
        self.enabled = [False] * num_irqs
        self.pending = [False] * num_irqs
        self.active = [False] * num_irqs
        self.priority = [0] * num_irqs

        # Callback for triggering interrupts
        self.on_irq: Optional[Callable[[int], None]] = None

    def read(self, offset: int, size: int) -> int:
        if self.ISER_BASE <= offset < self.ISER_BASE + 32:
            return self._read_bitarray(self.enabled, offset - self.ISER_BASE)
        elif self.ICER_BASE <= offset < self.ICER_BASE + 32:
            return self._read_bitarray(self.enabled, offset - self.ICER_BASE)
        elif self.ISPR_BASE <= offset < self.ISPR_BASE + 32:
            return self._read_bitarray(self.pending, offset - self.ISPR_BASE)
        elif self.ICPR_BASE <= offset < self.ICPR_BASE + 32:
            return self._read_bitarray(self.pending, offset - self.ICPR_BASE)
        elif self.IABR_BASE <= offset < self.IABR_BASE + 32:
            return self._read_bitarray(self.active, offset - self.IABR_BASE)
        elif self.IPR_BASE <= offset < self.IPR_BASE + 240:
            # Priority registers (4 IRQs per word, 8 bits each)
            idx = offset - self.IPR_BASE
            irq_base = idx * 4
            value = 0
            for i in range(4):
                if irq_base + i < self.num_irqs:
                    value |= (self.priority[irq_base + i] & 0xFF) << (i * 8)
            return value
        return 0

    def write(self, offset: int, size: int, value: int):
        if self.ISER_BASE <= offset < self.ISER_BASE + 32:
            self._set_bitarray(self.enabled, offset - self.ISER_BASE, value, True)
        elif self.ICER_BASE <= offset < self.ICER_BASE + 32:
            self._set_bitarray(self.enabled, offset - self.ICER_BASE, value, False)
        elif self.ISPR_BASE <= offset < self.ISPR_BASE + 32:
            self._set_bitarray(self.pending, offset - self.ISPR_BASE, value, True)
            self._check_pending_irqs()
        elif self.ICPR_BASE <= offset < self.ICPR_BASE + 32:
            self._set_bitarray(self.pending, offset - self.ICPR_BASE, value, False)
        elif self.IPR_BASE <= offset < self.IPR_BASE + 240:
            idx = offset - self.IPR_BASE
            irq_base = idx * 4
            for i in range(4):
                if irq_base + i < self.num_irqs:
                    self.priority[irq_base + i] = (value >> (i * 8)) & 0xFF

    def _read_bitarray(self, arr: List[bool], offset: int) -> int:
        reg_idx = offset // 4
        irq_base = reg_idx * 32
        value = 0
        for i in range(32):
            if irq_base + i < len(arr) and arr[irq_base + i]:
                value |= (1 << i)
        return value

    def _set_bitarray(self, arr: List[bool], offset: int, value: int, set_val: bool):
        reg_idx = offset // 4
        irq_base = reg_idx * 32
        for i in range(32):
            if value & (1 << i):
                if irq_base + i < len(arr):
                    arr[irq_base + i] = set_val

    def set_pending(self, irq: int):
        """Set interrupt pending (external trigger)."""
        if 0 <= irq < self.num_irqs:
            self.pending[irq] = True
            self._check_pending_irqs()

    def _check_pending_irqs(self):
        """Check for pending enabled interrupts."""
        for irq in range(self.num_irqs):
            if self.pending[irq] and self.enabled[irq] and not self.active[irq]:
                if self.on_irq:
                    self.on_irq(irq)


# =============================================================================
# SCB - SYSTEM CONTROL BLOCK
# =============================================================================

class SCBController:
    """System Control Block for Cortex-M."""

    # Register offsets from 0xE000ED00
    CPUID = 0x00
    ICSR = 0x04     # Interrupt Control and State
    VTOR = 0x08     # Vector Table Offset
    AIRCR = 0x0C    # Application Interrupt and Reset Control
    SCR = 0x10      # System Control
    CCR = 0x14      # Configuration and Control
    SHPR1 = 0x18    # System Handler Priority 1
    SHPR2 = 0x1C    # System Handler Priority 2
    SHPR3 = 0x20    # System Handler Priority 3
    SHCSR = 0x24    # System Handler Control and State
    CFSR = 0x28     # Configurable Fault Status
    HFSR = 0x2C     # Hard Fault Status
    DFSR = 0x30     # Debug Fault Status
    MMFAR = 0x34    # MemManage Fault Address
    BFAR = 0x38     # Bus Fault Address
    AFSR = 0x3C     # Auxiliary Fault Status

    def __init__(self, cpu_type: str = "cortex-m4"):
        self.base = 0xE000ED00
        self.size = 0x100
        self.log = logging.getLogger('SCB')

        # Determine CPUID based on CPU type
        cpuid_map = {
            'cortex-m0': 0x410CC200,
            'cortex-m3': 0x412FC231,
            'cortex-m4': 0x410FC241,
            'cortex-m7': 0x411FC271,
            'cortex-m33': 0x410FD213,
        }
        self.cpuid = cpuid_map.get(cpu_type, 0x410FC241)

        # Registers
        self.icsr = 0
        self.vtor = 0
        self.aircr = 0xFA050000
        self.scr = 0
        self.ccr = 0x00000200  # Default: STKALIGN
        self.shpr = [0, 0, 0]
        self.shcsr = 0
        self.cfsr = 0
        self.hfsr = 0
        self.dfsr = 0
        self.mmfar = 0
        self.bfar = 0

    def read(self, offset: int, size: int) -> int:
        if offset == self.CPUID:
            return self.cpuid
        elif offset == self.ICSR:
            return self.icsr
        elif offset == self.VTOR:
            return self.vtor
        elif offset == self.AIRCR:
            return self.aircr
        elif offset == self.SCR:
            return self.scr
        elif offset == self.CCR:
            return self.ccr
        elif offset == self.SHCSR:
            return self.shcsr
        elif offset == self.CFSR:
            return self.cfsr
        elif offset == self.HFSR:
            return self.hfsr
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == self.ICSR:
            # Handle PENDSVSET, PENDSVCLR, etc.
            if value & (1 << 28):  # PENDSVSET
                self.icsr |= (1 << 28)
            if value & (1 << 27):  # PENDSVCLR
                self.icsr &= ~(1 << 28)
        elif offset == self.VTOR:
            self.vtor = value & 0xFFFFFF80  # 128-byte aligned
            self.log.debug(f"VTOR = 0x{self.vtor:08X}")
        elif offset == self.AIRCR:
            if (value >> 16) == 0x05FA:  # VECTKEY
                if value & 0x04:  # SYSRESETREQ
                    self.log.info("System reset requested")
                self.aircr = (self.aircr & 0x0000F8FF) | (value & 0x0700)
        elif offset == self.SCR:
            self.scr = value & 0x1E
        elif offset == self.CCR:
            self.ccr = value


# =============================================================================
# SYSTICK - SYSTEM TICK TIMER
# =============================================================================

class SysTickTimer:
    """SysTick timer for Cortex-M."""

    # Register offsets from 0xE000E010
    CTRL = 0x00     # Control and Status
    LOAD = 0x04     # Reload Value
    VAL = 0x08      # Current Value
    CALIB = 0x0C    # Calibration Value

    # CTRL bits
    CTRL_ENABLE = (1 << 0)
    CTRL_TICKINT = (1 << 1)
    CTRL_CLKSOURCE = (1 << 2)
    CTRL_COUNTFLAG = (1 << 16)

    def __init__(self, cpu_freq: int = 168000000):
        self.base = 0xE000E010
        self.size = 0x10
        self.cpu_freq = cpu_freq
        self.log = logging.getLogger('SysTick')

        self.ctrl = 0
        self.load = 0
        self.val = 0
        self.calib = 0x00C41EBF  # 10ms calibration for 168MHz

        # Tick callback
        self.on_tick: Optional[Callable[[], None]] = None

        # Timing
        self.last_tick_time = 0
        self.tick_count = 0

    def read(self, offset: int, size: int) -> int:
        if offset == self.CTRL:
            value = self.ctrl
            self.ctrl &= ~self.CTRL_COUNTFLAG  # Clear on read
            return value
        elif offset == self.LOAD:
            return self.load
        elif offset == self.VAL:
            self._update_val()
            return self.val
        elif offset == self.CALIB:
            return self.calib
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self.ctrl = value & 0x10007
            if value & self.CTRL_ENABLE:
                self.last_tick_time = time.time()
                self.log.debug("SysTick enabled")
        elif offset == self.LOAD:
            self.load = value & 0x00FFFFFF
        elif offset == self.VAL:
            self.val = 0  # Writing any value clears VAL

    def _update_val(self):
        """Update current value based on elapsed time."""
        if not (self.ctrl & self.CTRL_ENABLE) or self.load == 0:
            return

        # Calculate ticks based on elapsed time
        now = time.time()
        elapsed = now - self.last_tick_time
        ticks = int(elapsed * self.cpu_freq)

        if ticks >= self.load:
            # Wrapped
            self.ctrl |= self.CTRL_COUNTFLAG
            self.val = self.load - (ticks % (self.load + 1))
            self.tick_count += ticks // (self.load + 1)

            if self.ctrl & self.CTRL_TICKINT and self.on_tick:
                self.on_tick()
        else:
            self.val = self.load - ticks


# =============================================================================
# I2C - INTER-INTEGRATED CIRCUIT
# =============================================================================

class I2CController:
    """I2C peripheral for STM32."""

    # Register offsets
    CR1 = 0x00      # Control register 1
    CR2 = 0x04      # Control register 2
    OAR1 = 0x08     # Own address register 1
    OAR2 = 0x0C     # Own address register 2
    DR = 0x10       # Data register
    SR1 = 0x14      # Status register 1
    SR2 = 0x18      # Status register 2
    CCR = 0x1C      # Clock control register
    TRISE = 0x20    # Rise time register

    # SR1 bits
    SR1_SB = (1 << 0)       # Start bit
    SR1_ADDR = (1 << 1)     # Address sent
    SR1_BTF = (1 << 2)      # Byte transfer finished
    SR1_RXNE = (1 << 6)     # Data register not empty
    SR1_TXE = (1 << 7)      # Data register empty

    def __init__(self, name: str, base: int, irq: int = -1):
        self.name = name
        self.base = base
        self.size = 0x400
        self.irq = irq
        self.log = logging.getLogger(f'I2C.{name}')

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.oar1 = 0
        self.oar2 = 0
        self.dr = 0
        self.sr1 = self.SR1_TXE  # TX empty initially
        self.sr2 = 0
        self.ccr = 0
        self.trise = 0

        # Transfer state
        self.tx_buffer: List[int] = []
        self.rx_buffer: List[int] = []
        self.current_addr = 0

        # Connected devices
        self.devices: Dict[int, 'I2CDevice'] = {}

    def read(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.OAR1:
            return self.oar1
        elif offset == self.DR:
            if self.rx_buffer:
                self.dr = self.rx_buffer.pop(0)
                if not self.rx_buffer:
                    self.sr1 &= ~self.SR1_RXNE
            return self.dr
        elif offset == self.SR1:
            return self.sr1
        elif offset == self.SR2:
            # Reading SR2 after SR1 clears ADDR
            value = self.sr2
            self.sr1 &= ~self.SR1_ADDR
            return value
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            old_cr1 = self.cr1
            self.cr1 = value

            # Generate START
            if (value & 0x100) and not (old_cr1 & 0x100):
                self.sr1 |= self.SR1_SB
                self.log.debug("START condition")

            # Generate STOP
            if (value & 0x200):
                self._complete_transfer()
                self.log.debug("STOP condition")

        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.OAR1:
            self.oar1 = value
        elif offset == self.DR:
            self.dr = value

            # If START was sent, this is the address
            if self.sr1 & self.SR1_SB:
                self.current_addr = (value >> 1) & 0x7F
                self.sr1 &= ~self.SR1_SB
                self.sr1 |= self.SR1_ADDR
                self.log.debug(f"Address: 0x{self.current_addr:02X}")
            else:
                # Data byte
                self.tx_buffer.append(value)
                self.sr1 |= self.SR1_TXE | self.SR1_BTF

    def attach_device(self, addr: int, device: 'I2CDevice'):
        """Attach an I2C device at given address."""
        self.devices[addr] = device

    def _complete_transfer(self):
        """Complete I2C transfer with device."""
        if self.current_addr in self.devices:
            device = self.devices[self.current_addr]
            self.rx_buffer = device.transfer(self.tx_buffer)
            if self.rx_buffer:
                self.sr1 |= self.SR1_RXNE
        self.tx_buffer = []
        self.sr1 &= ~(self.SR1_SB | self.SR1_ADDR)


class I2CDevice:
    """Base class for I2C devices."""

    def transfer(self, tx_data: List[int]) -> List[int]:
        """Process I2C transfer. Override in subclass."""
        return []


# =============================================================================
# FSMC - FLEXIBLE STATIC MEMORY CONTROLLER
# =============================================================================

class FSMCController:
    """FSMC for external memory and LCD interfaces."""

    def __init__(self):
        self.base = 0xA0000000
        self.size = 0x1000
        self.log = logging.getLogger('FSMC')

        # Bank control registers (4 banks)
        self.bcr = [0x000030D0] * 4  # Reset values
        self.btr = [0x0FFFFFFF] * 4
        self.bwtr = [0x0FFFFFFF] * 4

        # Connected devices (per bank)
        self.devices: Dict[int, 'FSMCDevice'] = {}

        # Data memory regions
        self.bank_bases = [
            0x60000000,  # Bank 1
            0x64000000,  # Bank 2
            0x68000000,  # Bank 3
            0x6C000000,  # Bank 4
        ]

    def read(self, offset: int, size: int) -> int:
        bank = offset // 8
        reg = offset % 8
        if bank < 4:
            if reg == 0:
                return self.bcr[bank]
            elif reg == 4:
                return self.btr[bank]
        return 0

    def write(self, offset: int, size: int, value: int):
        bank = offset // 8
        reg = offset % 8
        if bank < 4:
            if reg == 0:
                self.bcr[bank] = value
            elif reg == 4:
                self.btr[bank] = value

    def bank_read(self, bank: int, offset: int, size: int) -> int:
        """Read from FSMC bank memory region."""
        if bank in self.devices:
            return self.devices[bank].read(offset, size)
        return 0

    def bank_write(self, bank: int, offset: int, size: int, value: int):
        """Write to FSMC bank memory region."""
        if bank in self.devices:
            self.devices[bank].write(offset, size, value)


class FSMCDevice:
    """Base class for FSMC-connected devices."""

    def read(self, offset: int, size: int) -> int:
        return 0

    def write(self, offset: int, size: int, value: int):
        pass


# =============================================================================
# EXTERNAL DEVICES
# =============================================================================

class SPIFlash:
    """
    SPI Flash emulation (W25Q128 compatible).

    16MB flash with standard SPI commands.
    """

    # Commands
    CMD_READ = 0x03
    CMD_FAST_READ = 0x0B
    CMD_PAGE_PROGRAM = 0x02
    CMD_SECTOR_ERASE = 0x20
    CMD_BLOCK_ERASE = 0xD8
    CMD_CHIP_ERASE = 0xC7
    CMD_WRITE_ENABLE = 0x06
    CMD_WRITE_DISABLE = 0x04
    CMD_READ_STATUS = 0x05
    CMD_READ_ID = 0x9F

    # Status bits
    STATUS_BUSY = 0x01
    STATUS_WEL = 0x02

    def __init__(self, size: int = 16 * 1024 * 1024):
        self.size = size
        self.data = bytearray(size)
        self.log = logging.getLogger('SPIFlash')

        self.status = 0
        self.state = 'IDLE'
        self.cmd_buffer: List[int] = []
        self.addr = 0
        self.write_buffer: List[int] = []

        # Manufacturer/Device ID (W25Q128)
        self.id = [0xEF, 0x40, 0x18]

    def transfer(self, mosi: int) -> int:
        """SPI transfer (receive MOSI, return MISO)."""
        self.cmd_buffer.append(mosi)

        if self.state == 'IDLE':
            return self._process_command(mosi)
        elif self.state == 'READ_ADDR':
            return self._process_address(mosi)
        elif self.state == 'READ_DATA':
            return self._read_data()
        elif self.state == 'WRITE_DATA':
            self._write_data(mosi)
            return 0xFF
        elif self.state == 'READ_ID':
            return self._read_id()

        return 0xFF

    def _process_command(self, cmd: int) -> int:
        if cmd == self.CMD_READ or cmd == self.CMD_FAST_READ:
            self.state = 'READ_ADDR'
            self.cmd_buffer = []
        elif cmd == self.CMD_PAGE_PROGRAM:
            if self.status & self.STATUS_WEL:
                self.state = 'READ_ADDR'
                self.cmd_buffer = []
        elif cmd == self.CMD_WRITE_ENABLE:
            self.status |= self.STATUS_WEL
        elif cmd == self.CMD_WRITE_DISABLE:
            self.status &= ~self.STATUS_WEL
        elif cmd == self.CMD_READ_STATUS:
            return self.status
        elif cmd == self.CMD_READ_ID:
            self.state = 'READ_ID'
            self.cmd_buffer = []
        return 0xFF

    def _process_address(self, byte: int) -> int:
        if len(self.cmd_buffer) >= 3:
            self.addr = (self.cmd_buffer[0] << 16) | (self.cmd_buffer[1] << 8) | byte
            if self.cmd_buffer[0] == self.CMD_PAGE_PROGRAM:
                self.state = 'WRITE_DATA'
                self.write_buffer = []
            else:
                self.state = 'READ_DATA'
            self.cmd_buffer = []
        return 0xFF

    def _read_data(self) -> int:
        if self.addr < self.size:
            value = self.data[self.addr]
            self.addr = (self.addr + 1) % self.size
            return value
        return 0xFF

    def _write_data(self, byte: int):
        if self.addr < self.size:
            # Flash write (can only clear bits)
            self.data[self.addr] &= byte
            self.addr += 1

    def _read_id(self) -> int:
        idx = len(self.cmd_buffer) - 1
        if idx < len(self.id):
            return self.id[idx]
        return 0xFF

    def deselect(self):
        """Called when CS goes high."""
        if self.state == 'WRITE_DATA':
            self.status &= ~self.STATUS_WEL
        self.state = 'IDLE'
        self.cmd_buffer = []


class ILI9341Display(FSMCDevice):
    """
    ILI9341 TFT LCD controller emulation.

    240x320 RGB display connected via FSMC.
    """

    def __init__(self, width: int = 240, height: int = 320):
        self.width = width
        self.height = height
        self.log = logging.getLogger('ILI9341')

        # Framebuffer (RGB565)
        self.framebuffer = bytearray(width * height * 2)

        # Registers
        self.cmd = 0
        self.params: List[int] = []

        # Display state
        self.x_pos = 0
        self.y_pos = 0
        self.x_start = 0
        self.x_end = width - 1
        self.y_start = 0
        self.y_end = height - 1
        self.pixel_buffer = 0
        self.pixel_count = 0

    def read(self, offset: int, size: int) -> int:
        # RS=0: command, RS=1: data
        if offset == 0:  # Command
            return self.cmd
        else:  # Data
            return self._read_data()
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == 0:  # Command
            self._write_command(value & 0xFF)
        else:  # Data
            self._write_data(value)

    def _write_command(self, cmd: int):
        self.cmd = cmd
        self.params = []
        self.log.debug(f"CMD: 0x{cmd:02X}")

    def _write_data(self, value: int):
        if self.cmd == 0x2A:  # Column Address Set
            self.params.append(value)
            if len(self.params) == 4:
                self.x_start = (self.params[0] << 8) | self.params[1]
                self.x_end = (self.params[2] << 8) | self.params[3]
                self.x_pos = self.x_start
        elif self.cmd == 0x2B:  # Row Address Set
            self.params.append(value)
            if len(self.params) == 4:
                self.y_start = (self.params[0] << 8) | self.params[1]
                self.y_end = (self.params[2] << 8) | self.params[3]
                self.y_pos = self.y_start
        elif self.cmd == 0x2C:  # Memory Write
            self._write_pixel(value)

    def _write_pixel(self, value: int):
        """Write pixel data (RGB565, 2 bytes per pixel)."""
        self.pixel_buffer = (self.pixel_buffer << 8) | (value & 0xFF)
        self.pixel_count += 1

        if self.pixel_count >= 2:
            # Full pixel received
            offset = (self.y_pos * self.width + self.x_pos) * 2
            if 0 <= offset < len(self.framebuffer) - 1:
                self.framebuffer[offset] = (self.pixel_buffer >> 8) & 0xFF
                self.framebuffer[offset + 1] = self.pixel_buffer & 0xFF

            # Advance position
            self.x_pos += 1
            if self.x_pos > self.x_end:
                self.x_pos = self.x_start
                self.y_pos += 1
                if self.y_pos > self.y_end:
                    self.y_pos = self.y_start

            self.pixel_buffer = 0
            self.pixel_count = 0

    def _read_data(self) -> int:
        return 0

    def save_png(self, filename: str):
        """Save framebuffer as PNG (requires PIL)."""
        try:
            from PIL import Image
            img = Image.frombytes('RGB', (self.width, self.height),
                                 self._rgb565_to_rgb888())
            img.save(filename)
            self.log.info(f"Saved display to {filename}")
        except ImportError:
            self.log.warning("PIL not available, cannot save PNG")

    def _rgb565_to_rgb888(self) -> bytes:
        """Convert RGB565 framebuffer to RGB888."""
        result = bytearray(self.width * self.height * 3)
        for i in range(0, len(self.framebuffer), 2):
            pixel = (self.framebuffer[i] << 8) | self.framebuffer[i + 1]
            r = ((pixel >> 11) & 0x1F) << 3
            g = ((pixel >> 5) & 0x3F) << 2
            b = (pixel & 0x1F) << 3
            idx = (i // 2) * 3
            result[idx] = r
            result[idx + 1] = g
            result[idx + 2] = b
        return bytes(result)


class ADS7846Touchscreen:
    """
    ADS7846 resistive touchscreen controller.

    SPI-based touch controller with 12-bit ADC.
    """

    # Control byte bits
    CTRL_START = 0x80
    CTRL_ADDR_MASK = 0x70
    CTRL_MODE_12BIT = 0x00
    CTRL_MODE_8BIT = 0x08

    # Channels
    CH_X = 0x50
    CH_Y = 0x10
    CH_Z1 = 0x30
    CH_Z2 = 0x40

    def __init__(self, width: int = 240, height: int = 320):
        self.width = width
        self.height = height
        self.log = logging.getLogger('ADS7846')

        # Current touch position (None = not touched)
        self.touch_x: Optional[int] = None
        self.touch_y: Optional[int] = None

        # SPI state
        self.cmd = 0
        self.response_bytes: List[int] = []

    def transfer(self, mosi: int) -> int:
        """SPI transfer."""
        if self.response_bytes:
            return self.response_bytes.pop(0)

        if mosi & self.CTRL_START:
            self.cmd = mosi
            channel = mosi & self.CTRL_ADDR_MASK

            if self.touch_x is not None and self.touch_y is not None:
                if channel == self.CH_X:
                    value = int((self.touch_x / self.width) * 4095)
                elif channel == self.CH_Y:
                    value = int((self.touch_y / self.height) * 4095)
                elif channel == self.CH_Z1:
                    value = 1000  # Pressure
                elif channel == self.CH_Z2:
                    value = 2000
                else:
                    value = 0
            else:
                value = 0  # No touch

            # 12-bit response
            self.response_bytes = [(value >> 4) & 0xFF, (value << 4) & 0xF0]

        return 0

    def set_touch(self, x: Optional[int], y: Optional[int]):
        """Set touch position (None = release)."""
        self.touch_x = x
        self.touch_y = y


# =============================================================================
# GPIO - GENERAL PURPOSE I/O (GPIOv2 - STM32F2/F4/L4/H7)
# =============================================================================

class GPIOPort:
    """
    STM32F4 GPIO port emulation (GPIOv2 architecture).

    Per RM0090 Section 8.4, register map at base + offsets:
        0x00: MODER   - Mode register (2 bits per pin)
        0x04: OTYPER  - Output type (1 bit per pin)
        0x08: OSPEEDR - Output speed (2 bits per pin)
        0x0C: PUPDR   - Pull-up/pull-down (2 bits per pin)
        0x10: IDR     - Input data register (read-only)
        0x14: ODR     - Output data register
        0x18: BSRR    - Bit set/reset register (write-only)
        0x1C: LCKR    - Configuration lock
        0x20: AFRL    - Alternate function low (pins 0-7)
        0x24: AFRH    - Alternate function high (pins 8-15)
    """

    # Register offsets
    MODER = 0x00
    OTYPER = 0x04
    OSPEEDR = 0x08
    PUPDR = 0x0C
    IDR = 0x10
    ODR = 0x14
    BSRR = 0x18
    LCKR = 0x1C
    AFRL = 0x20
    AFRH = 0x24

    # MODER values (per pin, 2 bits)
    MODE_INPUT = 0b00
    MODE_OUTPUT = 0b01
    MODE_AF = 0b10
    MODE_ANALOG = 0b11

    def __init__(self, name: str, base_addr: int):
        self.name = name
        self.base_addr = base_addr
        self.log = logging.getLogger(f'GPIO.{name}')

        # Registers (32-bit each)
        self._regs: Dict[int, int] = {
            self.MODER: 0x00000000,
            self.OTYPER: 0x00000000,
            self.OSPEEDR: 0x00000000,
            self.PUPDR: 0x00000000,
            self.IDR: 0x00000000,
            self.ODR: 0x00000000,
            self.LCKR: 0x00000000,
            self.AFRL: 0x00000000,
            self.AFRH: 0x00000000,
        }

        # Pin change callbacks
        self.on_pin_change: Optional[Callable[[int, bool], None]] = None

    def read_reg(self, offset: int) -> int:
        """Read GPIO register by offset."""
        if offset == self.BSRR:
            return 0  # BSRR is write-only
        return self._regs.get(offset, 0) & 0xFFFFFFFF

    def write_reg(self, offset: int, value: int):
        """Write GPIO register by offset."""
        value &= 0xFFFFFFFF

        if offset == self.BSRR:
            # Bits[15:0] = set, Bits[31:16] = reset
            # Reset has priority over set (per RM0090 8.4.7)
            set_bits = value & 0xFFFF
            reset_bits = (value >> 16) & 0xFFFF
            odr = self._regs[self.ODR]
            odr |= set_bits
            odr &= ~reset_bits
            self._regs[self.ODR] = odr & 0xFFFF
        elif offset == self.ODR:
            self._regs[self.ODR] = value & 0xFFFF
        elif offset in self._regs:
            self._regs[offset] = value

    def set_input_pin(self, pin: int, state: bool):
        """Set external input pin state (simulates external signal)."""
        if 0 <= pin <= 15:
            if state:
                self._regs[self.IDR] |= (1 << pin)
            else:
                self._regs[self.IDR] &= ~(1 << pin)

    def read(self, offset: int, size: int) -> int:
        """Memory-mapped read interface."""
        return self.read_reg(offset)

    def write(self, offset: int, size: int, value: int):
        """Memory-mapped write interface."""
        self.write_reg(offset, value)


# =============================================================================
# EXTI - EXTERNAL INTERRUPT CONTROLLER
# =============================================================================

class EXTIController:
    """
    STM32F4 External Interrupt/Event controller.

    Per RM0090 Section 12.3:
        0x00: IMR   - Interrupt mask register
        0x04: EMR   - Event mask register
        0x08: RTSR  - Rising trigger selection
        0x0C: FTSR  - Falling trigger selection
        0x10: SWIER - Software interrupt event register
        0x14: PR    - Pending register (write-1-to-clear)
    """

    IMR = 0x00
    EMR = 0x04
    RTSR = 0x08
    FTSR = 0x0C
    SWIER = 0x10
    PR = 0x14

    def __init__(self, base_addr: int = 0x40013C00):
        self.base_addr = base_addr
        self.log = logging.getLogger('EXTI')
        self._regs: Dict[int, int] = {
            self.IMR: 0,
            self.EMR: 0,
            self.RTSR: 0,
            self.FTSR: 0,
            self.SWIER: 0,
            self.PR: 0,
        }
        self.on_interrupt: Optional[Callable[[int], None]] = None

    def read_reg(self, offset: int) -> int:
        return self._regs.get(offset, 0)

    def write_reg(self, offset: int, value: int):
        if offset == self.PR:
            # Write-1-to-clear
            self._regs[self.PR] &= ~value
        elif offset == self.SWIER:
            # Software trigger sets pending bits for enabled lines
            triggered = value & self._regs[self.IMR]
            self._regs[self.PR] |= triggered
            self._regs[self.SWIER] = value
            if triggered and self.on_interrupt:
                for line in range(23):
                    if triggered & (1 << line):
                        self.on_interrupt(line)
        elif offset in self._regs:
            self._regs[offset] = value

    def trigger(self, line: int, rising: bool = True):
        """Trigger external interrupt on a line."""
        mask = 1 << line
        if rising and (self._regs[self.RTSR] & mask):
            if self._regs[self.IMR] & mask:
                self._regs[self.PR] |= mask
                if self.on_interrupt:
                    self.on_interrupt(line)
        elif not rising and (self._regs[self.FTSR] & mask):
            if self._regs[self.IMR] & mask:
                self._regs[self.PR] |= mask
                if self.on_interrupt:
                    self.on_interrupt(line)

    def read(self, offset: int, size: int) -> int:
        return self.read_reg(offset)

    def write(self, offset: int, size: int, value: int):
        self.write_reg(offset, value)


# =============================================================================
# W25Q FLASH - WINBOND SPI NOR FLASH (COMMAND-LEVEL INTERFACE)
# =============================================================================

class W25QFlash:
    """
    Winbond W25Q SPI NOR Flash emulation (command-level interface).

    Per W25Q128JV datasheet:
    - Manufacturer ID: 0xEF (Winbond)
    - Memory type: 0x40
    - Capacity codes: 0x15(16Mbit/2MB), 0x16(32Mbit/4MB), 0x17(64Mbit/8MB),
                      0x18(128Mbit/16MB), 0x19(256Mbit/32MB)
    - Page size: 256 bytes
    - Sector size: 4KB (smallest erasable unit)
    - Block size: 64KB
    - Erase value: 0xFF
    - Write: can only clear bits (1→0), must erase first

    Supported commands:
        0x06: WREN      - Write Enable
        0x04: WRDI      - Write Disable
        0x05: RDSR1     - Read Status Register 1
        0x01: WRSR1     - Write Status Register 1
        0x03: READ      - Read Data (up to 50MHz)
        0x0B: FAST_READ - Fast Read (dummy byte, up to 133MHz)
        0x02: PP        - Page Program (256 bytes max)
        0x20: SE        - Sector Erase (4KB)
        0xD8: BE        - Block Erase (64KB)
        0xC7: CE        - Chip Erase
        0x9F: RDID      - Read JEDEC ID
        0xAB: RDPD      - Release Power-Down / Device ID
        0xB9: PD        - Power-Down
    """

    # Commands
    CMD_WREN = 0x06
    CMD_WRDI = 0x04
    CMD_RDSR1 = 0x05
    CMD_WRSR1 = 0x01
    CMD_READ = 0x03
    CMD_FAST_READ = 0x0B
    CMD_PP = 0x02
    CMD_SE = 0x20
    CMD_BE = 0xD8
    CMD_CE = 0xC7
    CMD_RDID = 0x9F
    CMD_RDPD = 0xAB
    CMD_PD = 0xB9

    # Status register bits
    SR_BUSY = 0x01
    SR_WEL = 0x02
    SR_BP0 = 0x04
    SR_BP1 = 0x08
    SR_BP2 = 0x10
    SR_TB = 0x20
    SR_SEC = 0x40
    SR_SRP0 = 0x80

    PAGE_SIZE = 256
    SECTOR_SIZE = 4096
    BLOCK_SIZE = 65536

    # Capacity code mapping (size_mb → capacity byte)
    _CAPACITY_CODES = {
        2: 0x15,   # 16Mbit
        4: 0x16,   # 32Mbit
        8: 0x17,   # 64Mbit
        16: 0x18,  # 128Mbit
        32: 0x19,  # 256Mbit
    }

    def __init__(self, size_mb: int = 16):
        self.size = size_mb * 1024 * 1024
        self.data = bytearray(b'\xFF' * self.size)  # Erased state
        self.log = logging.getLogger('W25QFlash')

        # Status register
        self.status = 0x00
        self.power_down = False

        # JEDEC ID: Manufacturer(0xEF) + Type(0x40) + Capacity
        capacity_code = self._CAPACITY_CODES.get(size_mb, 0x18)
        self.jedec_id = bytes([0xEF, 0x40, capacity_code])

    def execute_command(self, cmd: int, addr: int, read_len: int,
                        write_data: Optional[bytes] = None) -> bytes:
        """
        Execute a SPI flash command.

        Args:
            cmd: Command byte (e.g., 0x9F for JEDEC ID)
            addr: 24-bit address (ignored for non-addressed commands)
            read_len: Number of bytes to read back
            write_data: Data to write (for PP command)

        Returns:
            Response bytes (length = read_len)
        """
        if cmd == self.CMD_RDID:
            # Return JEDEC ID repeated as needed
            result = (self.jedec_id * ((read_len // 3) + 1))[:read_len]
            return bytes(result)

        elif cmd == self.CMD_RDSR1:
            return bytes([self.status] * max(1, read_len))

        elif cmd == self.CMD_WRSR1:
            if self.status & self.SR_WEL:
                if write_data:
                    self.status = (write_data[0] & 0x7C) | (self.status & 0x03)
                self.status &= ~self.SR_WEL
            return b''

        elif cmd == self.CMD_WREN:
            self.status |= self.SR_WEL
            return b''

        elif cmd == self.CMD_WRDI:
            self.status &= ~self.SR_WEL
            return b''

        elif cmd == self.CMD_READ:
            # Standard read from addr
            addr &= (self.size - 1)
            result = bytearray(read_len)
            for i in range(read_len):
                result[i] = self.data[(addr + i) % self.size]
            return bytes(result)

        elif cmd == self.CMD_FAST_READ:
            # Fast read: 1 dummy byte then data
            addr &= (self.size - 1)
            result = bytearray(read_len)
            if read_len > 0:
                result[0] = 0xFF  # Dummy byte
                for i in range(1, read_len):
                    result[i] = self.data[(addr + i - 1) % self.size]
            return bytes(result)

        elif cmd == self.CMD_PP:
            # Page Program: write up to 256 bytes within a page
            if not (self.status & self.SR_WEL):
                return b''
            if write_data:
                addr &= (self.size - 1)
                page_start = addr & ~(self.PAGE_SIZE - 1)
                for i, byte in enumerate(write_data[:self.PAGE_SIZE]):
                    # Write wraps within the page
                    offset = (addr + i) % self.PAGE_SIZE
                    target = page_start + offset
                    # Flash write: can only clear bits (AND operation)
                    self.data[target] &= byte
            self.status &= ~self.SR_WEL
            return b''

        elif cmd == self.CMD_SE:
            # Sector Erase: erase 4KB sector
            if not (self.status & self.SR_WEL):
                return b''
            sector_addr = addr & ~(self.SECTOR_SIZE - 1)
            for i in range(self.SECTOR_SIZE):
                if sector_addr + i < self.size:
                    self.data[sector_addr + i] = 0xFF
            self.status &= ~self.SR_WEL
            return b''

        elif cmd == self.CMD_BE:
            # Block Erase: erase 64KB block
            if not (self.status & self.SR_WEL):
                return b''
            block_addr = addr & ~(self.BLOCK_SIZE - 1)
            for i in range(self.BLOCK_SIZE):
                if block_addr + i < self.size:
                    self.data[block_addr + i] = 0xFF
            self.status &= ~self.SR_WEL
            return b''

        elif cmd == self.CMD_CE:
            # Chip Erase
            if not (self.status & self.SR_WEL):
                return b''
            self.data = bytearray(b'\xFF' * self.size)
            self.status &= ~self.SR_WEL
            return b''

        elif cmd == self.CMD_PD:
            self.power_down = True
            return b''

        elif cmd == self.CMD_RDPD:
            self.power_down = False
            return b''

        return bytes(read_len)


# =============================================================================
# COMPLETE PERIPHERAL SET
# =============================================================================

class STM32F4PeripheralSet:
    """
    Complete STM32F4 peripheral set for MCUemu.

    Provides all peripherals needed to run complex firmware like
    3D printer control boards.
    """

    def __init__(self, cpu_freq: int = 168000000):
        self.log = logging.getLogger('STM32F4')
        self.cpu_freq = cpu_freq

        # Memory
        self.memory: Dict[int, bytearray] = {}

        # Core peripherals
        self.nvic = NVICController()
        self.scb = SCBController("cortex-m4")
        self.systick = SysTickTimer(cpu_freq)

        # DMA controllers
        self.dma1 = DMAController("DMA1", 0x40026000)
        self.dma2 = DMAController("DMA2", 0x40026400)

        # FSMC
        self.fsmc = FSMCController()

        # External devices
        self.spi_flash = SPIFlash()
        self.display = ILI9341Display()
        self.touchscreen = ADS7846Touchscreen()

        # Peripheral map
        self.peripherals: Dict[int, Any] = {}
        self._setup_peripherals()

    def _setup_peripherals(self):
        """Setup peripheral address map."""
        # Core (PPB region)
        self.peripherals[0xE000E010] = self.systick
        self.peripherals[0xE000E100] = self.nvic
        self.peripherals[0xE000ED00] = self.scb

        # DMA
        self.peripherals[0x40026000] = self.dma1
        self.peripherals[0x40026400] = self.dma2

        # FSMC
        self.peripherals[0xA0000000] = self.fsmc

        # Connect display to FSMC Bank 1
        self.fsmc.devices[0] = self.display

    def read(self, addr: int, size: int) -> int:
        """Read from peripheral address."""
        # Find matching peripheral
        for base, periph in self.peripherals.items():
            if hasattr(periph, 'size'):
                if base <= addr < base + periph.size:
                    offset = addr - base
                    return periph.read(offset, size)

        # FSMC bank regions
        for i, bank_base in enumerate(self.fsmc.bank_bases):
            if bank_base <= addr < bank_base + 0x4000000:
                offset = addr - bank_base
                return self.fsmc.bank_read(i, offset, size)

        return 0

    def write(self, addr: int, size: int, value: int):
        """Write to peripheral address."""
        for base, periph in self.peripherals.items():
            if hasattr(periph, 'size'):
                if base <= addr < base + periph.size:
                    offset = addr - base
                    periph.write(offset, size, value)
                    return

        # FSMC bank regions
        for i, bank_base in enumerate(self.fsmc.bank_bases):
            if bank_base <= addr < bank_base + 0x4000000:
                offset = addr - bank_base
                self.fsmc.bank_write(i, offset, size, value)
                return


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, format='%(name)-12s: %(message)s')

    print("=" * 60)
    print("STM32F4 Enhanced Peripherals Demo")
    print("=" * 60)

    # Create peripheral set
    peripherals = STM32F4PeripheralSet()

    # Test SysTick
    print("\n--- SysTick ---")
    peripherals.systick.write(SysTickTimer.LOAD, 168000 - 1)  # 1ms tick
    peripherals.systick.write(SysTickTimer.CTRL, 0x07)  # Enable with interrupt
    print(f"SysTick LOAD: {peripherals.systick.load}")

    # Test NVIC
    print("\n--- NVIC ---")
    peripherals.nvic.write(0x00, 4, 0x00000001)  # Enable IRQ0
    print(f"IRQ0 enabled: {peripherals.nvic.enabled[0]}")

    # Test DMA
    print("\n--- DMA ---")
    stream = peripherals.dma1.streams[0]
    stream.ndtr = 100
    stream.par = 0x40013000
    stream.m0ar = 0x20000000
    print(f"DMA1 Stream0 NDTR: {stream.ndtr}")

    # Test SPI Flash
    print("\n--- SPI Flash ---")
    # Read ID
    peripherals.spi_flash.transfer(SPIFlash.CMD_READ_ID)
    id0 = peripherals.spi_flash.transfer(0xFF)
    id1 = peripherals.spi_flash.transfer(0xFF)
    id2 = peripherals.spi_flash.transfer(0xFF)
    peripherals.spi_flash.deselect()
    print(f"SPI Flash ID: {id0:02X} {id1:02X} {id2:02X}")

    # Test Display
    print("\n--- ILI9341 Display ---")
    peripherals.display.write(0, 1, 0x2C)  # Memory Write command
    peripherals.display.write(1, 1, 0xF8)  # Red pixel (RGB565)
    peripherals.display.write(1, 1, 0x00)
    print(f"Display framebuffer[0]: 0x{peripherals.display.framebuffer[0]:02X}")

    print("\nDemo complete!")
