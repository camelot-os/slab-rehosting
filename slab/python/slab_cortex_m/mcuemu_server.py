#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║     MCUemu Python Peripheral Server                                          ║
║                                                                              ║
║  This server handles peripheral accesses from QEMU's MCUemu machine.         ║
║  Each peripheral is configurable via YAML/JSON config files.                 ║
║                                                                              ║
║  Protocol (binary, little-endian):                                           ║
║    Request: [R/W:1][Addr:4][Size:4][Value:4 if write]                       ║
║    Response: [Value:4][Status:1]                                             ║
║    IRQ: [I:1][IRQ#:4][Level:1]                                              ║
║                                                                              ║
║  Usage:                                                                      ║
║    python3 mcuemu_periph_server.py --port 5000 --config stm32f4.yaml        ║
║                                                                              ║
║  Author: Mathieu Renard <mathieu.renard@twistedwires.io>                                           ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 TwistedWires - Mathieu Renard

import asyncio
import struct
import logging
import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable, Any, List
from abc import ABC, abstractmethod
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('MCUemu')


# =============================================================================
# PROTOCOL CONSTANTS
# =============================================================================

CMD_READ = ord('R')       # Non-Secure Read
CMD_WRITE = ord('W')      # Non-Secure Write
CMD_READ_S = ord('S')     # Secure Read (TrustZone)
CMD_WRITE_S = ord('T')    # Secure Write (TrustZone)
CMD_IRQ = ord('I')        # IRQ injection
CMD_CONFIG = ord('C')     # Security configuration

STATUS_OK = 0
STATUS_ERROR = 1
STATUS_SECURITY_FAULT = 2  # TrustZone security violation

# Security states
SECURITY_NS = 0   # Non-Secure
SECURITY_S = 1    # Secure


# =============================================================================
# PERIPHERAL BASE CLASS
# =============================================================================

class Peripheral(ABC):
    """Base class for all peripheral implementations."""
    
    def __init__(self, name: str, base: int, size: int, irq: int = -1,
                 secure_only: bool = False, ns_callable: bool = False):
        """
        Initialize peripheral.
        
        Args:
            name: Peripheral name (e.g., "USART1")
            base: Base address
            size: Size of register space (default 0x400 = 1KB)
            irq: IRQ number (-1 if no IRQ)
            secure_only: If True, only accessible from Secure state (TrustZone)
            ns_callable: If True, can be called from Non-Secure via NSC (TrustZone)
        """
        self.name = name
        self.base = base
        self.size = size
        self.irq = irq
        self.secure_only = secure_only
        self.ns_callable = ns_callable
        self.regs: Dict[int, int] = {}
        self.log = logging.getLogger(f'P.{name}')
        self.irq_callback: Optional[Callable[[int, int], None]] = None
    
    def contains(self, addr: int) -> bool:
        return self.base <= addr < self.base + self.size
    
    def check_security(self, secure: bool) -> bool:
        """Check if access is allowed based on TrustZone security state."""
        if self.secure_only and not secure:
            self.log.warning(f"Security fault: NS access to secure-only peripheral")
            return False
        return True
    
    def read(self, addr: int, size: int, secure: bool = True) -> tuple:
        """Read register with security check. Returns (value, status)."""
        if not self.check_security(secure):
            return (0, STATUS_SECURITY_FAULT)
        offset = addr - self.base
        value = self._read_reg(offset, size)
        self.log.debug(f"Read{'[S]' if secure else '[NS]'} 0x{addr:08X} = 0x{value:08X}")
        return (value, STATUS_OK)
    
    def write(self, addr: int, size: int, value: int, secure: bool = True) -> int:
        """Write register with security check. Returns status."""
        if not self.check_security(secure):
            return STATUS_SECURITY_FAULT
        offset = addr - self.base
        self.log.debug(f"Write{'[S]' if secure else '[NS]'} 0x{addr:08X} <- 0x{value:08X}")
        self._write_reg(offset, size, value)
        return STATUS_OK
    
    def _read_reg(self, offset: int, size: int) -> int:
        """Default implementation - override for special behavior."""
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        """Default implementation - override for special behavior."""
        self.regs[offset] = value
    
    def trigger_irq(self, level: int = 1):
        if self.irq >= 0 and self.irq_callback:
            self.irq_callback(self.irq, level)
    
    def reset(self):
        """Reset peripheral to initial state."""
        self.regs.clear()


# =============================================================================
# STM32-STYLE PERIPHERALS
# =============================================================================

class RCC(Peripheral):
    """Reset and Clock Control - auto-sets ready flags."""
    
    CR = 0x00
    CFGR = 0x08
    
    CR_HSEON = 1 << 16
    CR_HSERDY = 1 << 17
    CR_PLLON = 1 << 24
    CR_PLLRDY = 1 << 25
    CR_HSION = 1 << 0
    CR_HSIRDY = 1 << 1
    
    def __init__(self, name: str, base: int, size: int = 0x400):
        super().__init__(name, base, size)
        self.regs[self.CR] = self.CR_HSIRDY  # HSI ready by default
    
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CFGR:
            val = self.regs.get(offset, 0)
            # Mirror SW bits [1:0] into SWS bits [3:2]
            sw = val & 0x3
            val = (val & ~0xC) | (sw << 2)
            return val
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR:
            # Auto-set ready flags when enable is set
            if value & self.CR_HSEON:
                value |= self.CR_HSERDY
            if value & self.CR_PLLON:
                value |= self.CR_PLLRDY
            if value & self.CR_HSION:
                value |= self.CR_HSIRDY
        self.regs[offset] = value


class GPIO(Peripheral):
    """General Purpose I/O."""
    
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
    
    def __init__(self, name: str, base: int, size: int = 0x400):
        super().__init__(name, base, size)
        self.external_pins = 0  # Set by external connection
    
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.IDR:
            # Input = external pins OR output (for output-configured pins)
            return self.external_pins | self.regs.get(self.ODR, 0)
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.BSRR:
            # Atomic bit set/reset
            odr = self.regs.get(self.ODR, 0)
            odr |= (value & 0xFFFF)          # Set bits
            odr &= ~((value >> 16) & 0xFFFF)  # Reset bits
            self.regs[self.ODR] = odr
        else:
            self.regs[offset] = value
    
    def set_pin(self, pin: int, value: int):
        """Set external pin state (called from test harness)."""
        if value:
            self.external_pins |= (1 << pin)
        else:
            self.external_pins &= ~(1 << pin)


class USART(Peripheral):
    """Universal Synchronous/Asynchronous Receiver Transmitter."""
    
    SR = 0x00
    DR = 0x04
    BRR = 0x08
    CR1 = 0x0C
    CR2 = 0x10
    CR3 = 0x14
    
    SR_TXE = 1 << 7   # TX empty
    SR_TC = 1 << 6    # TX complete
    SR_RXNE = 1 << 5  # RX not empty
    SR_ORE = 1 << 3   # Overrun error
    
    CR1_RXNEIE = 1 << 5  # RX not empty interrupt enable
    CR1_TXEIE = 1 << 7   # TX empty interrupt enable
    
    def __init__(self, name: str, base: int, size: int = 0x400, irq: int = 37):
        super().__init__(name, base, size, irq)
        self.rx_buffer: List[int] = []
        self.tx_callback: Optional[Callable[[int], None]] = None
        self.regs[self.SR] = self.SR_TXE | self.SR_TC  # TX ready
    
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.DR:
            if self.rx_buffer:
                byte = self.rx_buffer.pop(0)
                if not self.rx_buffer:
                    self.regs[self.SR] &= ~self.SR_RXNE
                return byte
            return 0
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.DR:
            byte = value & 0xFF
            if self.tx_callback:
                self.tx_callback(byte)
            self.regs[self.SR] |= self.SR_TXE | self.SR_TC
        else:
            self.regs[offset] = value
    
    def receive_byte(self, byte: int):
        """Receive a byte from external source."""
        if len(self.rx_buffer) < 256:
            self.rx_buffer.append(byte)
            self.regs[self.SR] |= self.SR_RXNE
            # Trigger interrupt if enabled
            if self.regs.get(self.CR1, 0) & self.CR1_RXNEIE:
                self.trigger_irq()
        else:
            self.regs[self.SR] |= self.SR_ORE


class SPI(Peripheral):
    """Serial Peripheral Interface."""
    
    CR1 = 0x00
    CR2 = 0x04
    SR = 0x08
    DR = 0x0C
    
    SR_TXE = 1 << 1
    SR_RXNE = 1 << 0
    SR_BSY = 1 << 7
    
    def __init__(self, name: str, base: int, size: int = 0x400, irq: int = 35):
        super().__init__(name, base, size, irq)
        self.rx_buffer: List[int] = []
        self.tx_callback: Optional[Callable[[int], None]] = None
        self.regs[self.SR] = self.SR_TXE
    
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.DR:
            if self.rx_buffer:
                byte = self.rx_buffer.pop(0)
                if not self.rx_buffer:
                    self.regs[self.SR] &= ~self.SR_RXNE
                return byte
            return 0
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.DR:
            if self.tx_callback:
                self.tx_callback(value & 0xFF)
            self.regs[self.SR] |= self.SR_TXE
        else:
            self.regs[offset] = value
    
    def receive_byte(self, byte: int):
        self.rx_buffer.append(byte)
        self.regs[self.SR] |= self.SR_RXNE


class Timer(Peripheral):
    """Basic Timer with counter and ARR."""
    
    CR1 = 0x00
    DIER = 0x0C
    SR = 0x10
    CNT = 0x24
    PSC = 0x28
    ARR = 0x2C
    
    CR1_CEN = 1 << 0  # Counter enable
    SR_UIF = 1 << 0   # Update interrupt flag
    DIER_UIE = 1 << 0  # Update interrupt enable
    
    def __init__(self, name: str, base: int, size: int = 0x400, irq: int = 28,
                 timer_clk: int = 84_000_000):
        super().__init__(name, base, size, irq)
        self.regs[self.CR1] = 0x00000000
        self.regs[self.DIER] = 0x00000000
        self.regs[self.SR] = 0x00000000
        self.regs[self.CNT] = 0x00000000
        self.regs[self.PSC] = 0x00000000
        self.regs[self.ARR] = 0x0000FFFF
        self.timer_clk = timer_clk  # Input clock to timer (APB1 timer clock)
        self._counter_task = None

    async def _counter_loop(self):
        """Background timer: compute overflow period, sleep, fire IRQ."""
        try:
            while True:
                try:
                    cr1 = self.regs.get(self.CR1, 0)
                    if not (cr1 & self.CR1_CEN):
                        await asyncio.sleep(0.01)
                        continue

                    psc = self.regs.get(self.PSC, 0) + 1
                    arr = self.regs.get(self.ARR, 0xFFFF) + 1

                    # Compute overflow period: (ARR+1) * (PSC+1) / timer_clk
                    period = (arr * psc) / self.timer_clk
                    if period < 0.001:
                        period = 0.001  # Minimum 1ms to avoid busy loop

                    self.log.debug(f"Timer started: period={period:.3f}s "
                                  f"(PSC={psc-1}, ARR={arr-1})")
                    await asyncio.sleep(period)
                    self.log.info(f"Timer fired: IRQ {self.irq}")

                    # Overflow: set UIF and assert IRQ if enabled
                    # Keep IRQ high until firmware clears UIF via SR write
                    self.regs[self.CNT] = 0
                    self.regs[self.SR] |= self.SR_UIF
                    dier = self.regs.get(self.DIER, 0)
                    if dier & self.DIER_UIE:
                        self.trigger_irq(1)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    self.log.error(f"Timer error: {type(e).__name__}: {e}", exc_info=True)
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
    
    def _write_reg(self, offset: int, size: int, value: int):
        """Handle timer register writes. SR is W0C (write-0-to-clear)."""
        if offset == self.SR:
            # STM32 SR bits are rc_w0: write 0 to clear, write 1 has no effect
            self.regs[self.SR] &= value
            # Deassert IRQ if UIF is cleared
            if not (self.regs[self.SR] & self.SR_UIF):
                self.trigger_irq(0)
        else:
            self.regs[offset] = value

    def start_counter(self):
        if self._counter_task is None:
            self._counter_task = asyncio.ensure_future(self._counter_loop())


class Flash(Peripheral):
    """Flash controller (simplified)."""
    
    ACR = 0x00
    KEYR = 0x04
    SR = 0x0C
    CR = 0x10
    
    def __init__(self, name: str, base: int, size: int = 0x400):
        super().__init__(name, base, size)
        self.regs[self.CR] = 0x80000000  # Locked


class PWR(Peripheral):
    """Power controller (simplified)."""
    
    CR = 0x00
    CSR = 0x04
    
    def __init__(self, name: str, base: int, size: int = 0x400):
        super().__init__(name, base, size)


# =============================================================================
# ARM CORESIGHT DEBUG PERIPHERALS
# =============================================================================

class DWT(Peripheral):
    """Data Watchpoint and Trace Unit.
    
    Provides:
    - Cycle counter (CYCCNT)
    - Watchpoint comparators
    - Exception trace
    - PC sampling
    """
    
    # DWT Registers
    CTRL = 0x000        # Control register
    CYCCNT = 0x004      # Cycle count register
    CPICNT = 0x008      # CPI count register
    EXCCNT = 0x00C      # Exception overhead count
    SLEEPCNT = 0x010    # Sleep count register
    LSUCNT = 0x014      # LSU count register
    FOLDCNT = 0x018     # Folded instruction count
    PCSR = 0x01C        # Program counter sample register
    
    # Comparators (up to 4)
    COMP0 = 0x020
    MASK0 = 0x024
    FUNC0 = 0x028
    
    def __init__(self, name: str = "DWT", base: int = 0xE0001000, size: int = 0x1000):
        super().__init__(name, base, size)
        self.cycle_count = 0
        self.regs[self.CTRL] = 0x40000000  # NUMCOMP=4 comparators
        self.regs[self.CYCCNT] = 0
        
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CYCCNT:
            self.cycle_count += 100  # Simulate time passing
            return self.cycle_count & 0xFFFFFFFF
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CYCCNT:
            self.cycle_count = value
        self.regs[offset] = value


class ITM(Peripheral):
    """Instrumentation Trace Macrocell.
    
    Provides:
    - 32 stimulus ports for printf-style debugging
    - Timestamp generation
    - Trace packet formatting
    """
    
    # Stimulus Ports (32 ports x 4 bytes)
    STIM0 = 0x000
    # ... STIM31 = 0x07C
    
    TER = 0xE00         # Trace Enable Register
    TPR = 0xE40         # Trace Privilege Register
    TCR = 0xE80         # Trace Control Register
    LAR = 0xFB0         # Lock Access Register
    LSR = 0xFB4         # Lock Status Register
    
    # CoreSight magic unlock key
    CORESIGHT_UNLOCK = 0xC5ACCE55
    
    def __init__(self, name: str = "ITM", base: int = 0xE0000000, size: int = 0x1000):
        super().__init__(name, base, size)
        self.locked = True
        self.output_buffer: List[tuple] = []  # (port, data)
        self.regs[self.LSR] = 0x03  # Locked
        self.regs[self.TCR] = 0
        
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.LSR:
            return 0x03 if self.locked else 0x01
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.LAR:
            if value == self.CORESIGHT_UNLOCK:
                self.locked = False
                self.regs[self.LSR] = 0x01
                self.log.info("ITM unlocked")
            return
            
        if self.locked:
            self.log.warning("ITM write while locked (offset 0x%03X)", offset)
            return
            
        # Stimulus ports (0x000 - 0x07C)
        if offset < 0x080:
            port = offset // 4
            self.output_buffer.append((port, value))
            # Port 0 is typically used for printf
            if port == 0:
                char = chr(value & 0x7F) if (value & 0x7F) >= 0x20 else '.'
                self.log.debug(f"ITM[{port}]: 0x{value:02X} '{char}'")
        else:
            self.regs[offset] = value
    
    def get_output(self) -> List[tuple]:
        """Get buffered ITM output and clear buffer."""
        output = self.output_buffer.copy()
        self.output_buffer.clear()
        return output


class FPB(Peripheral):
    """Flash Patch and Breakpoint Unit.
    
    Provides:
    - Hardware breakpoints (up to 8)
    - Flash patching
    """
    
    CTRL = 0x000        # Control register
    REMAP = 0x004       # Remap register
    COMP0 = 0x008       # Comparator 0
    # ... COMP7 = 0x024
    
    CTRL_KEY = 1 << 1   # Write key
    CTRL_ENABLE = 1 << 0
    
    def __init__(self, name: str = "FPB", base: int = 0xE0002000, size: int = 0x1000):
        super().__init__(name, base, size)
        self.num_breakpoints = 6  # Typical: 6 code + 2 literal
        # FP_CTRL: NUM_CODE=6, NUM_LIT=2
        self.regs[self.CTRL] = (self.num_breakpoints << 4) | (2 << 8)
        
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            if not (value & self.CTRL_KEY):
                return  # Ignore writes without key
            self.regs[self.CTRL] = (self.regs[self.CTRL] & ~1) | (value & 1)
            if value & self.CTRL_ENABLE:
                self.log.info("FPB enabled")
            else:
                self.log.info("FPB disabled")
        else:
            self.regs[offset] = value


class TPIU(Peripheral):
    """Trace Port Interface Unit.
    
    Provides:
    - Trace output formatting
    - SWO (Serial Wire Output) support
    """
    
    SSPSR = 0x000       # Supported Parallel Port Sizes
    CSPSR = 0x004       # Current Parallel Port Size
    ACPR = 0x010        # Async Clock Prescaler
    SPPR = 0x0F0        # Selected Pin Protocol
    FFSR = 0x300        # Formatter and Flush Status
    FFCR = 0x304        # Formatter and Flush Control
    
    def __init__(self, name: str = "TPIU", base: int = 0xE0040000, size: int = 0x1000):
        super().__init__(name, base, size)
        self.regs[self.SSPSR] = 0x0F  # Supports 1, 2, 4 bit widths
        self.regs[self.CSPSR] = 0x01  # 1 bit (SWO)
        self.regs[self.SPPR] = 0x02   # NRZ encoding


class ROMTable(Peripheral):
    """CoreSight ROM Table.
    
    Provides debug component discovery.
    """
    
    # ROM Table entries (offsets from 0xE00FF000)
    SCS_ENTRY = 0xFD0   # Points to SCS (0xE000E000)
    DWT_ENTRY = 0xFD4   # Points to DWT (0xE0001000)
    FPB_ENTRY = 0xFD8   # Points to FPB (0xE0002000)
    ITM_ENTRY = 0xFDC   # Points to ITM (0xE0000000)
    TPIU_ENTRY = 0xFE0  # Points to TPIU (0xE0040000)
    
    def __init__(self, name: str = "ROM_TABLE", base: int = 0xE00FF000, size: int = 0x1000):
        super().__init__(name, base, size)
        # ROM Table entries: offset from base | present bit
        self.regs[0x000] = 0xFFF0F003  # SCS at -0xF1000 = 0xE000E000
        self.regs[0x004] = 0xFFF02003  # DWT at -0xFE000 = 0xE0001000
        self.regs[0x008] = 0xFFF03003  # FPB at -0xFD000 = 0xE0002000
        self.regs[0x00C] = 0xFFF01003  # ITM at -0xFF000 = 0xE0000000
        self.regs[0x010] = 0xFFF41003  # TPIU at -0xBF000 = 0xE0040000
        self.regs[0x014] = 0x00000000  # End marker
        # Component ID
        self.regs[0xFF0] = 0x0D
        self.regs[0xFF4] = 0x10
        self.regs[0xFF8] = 0x05
        self.regs[0xFFC] = 0xB1


class Mailbox(Peripheral):
    """Inter-CPU Mailbox for dual-core communication.
    
    Provides:
    - 32 interrupt channels per direction
    - Hardware mutex
    - Shared registers for IPC
    """
    
    # Registers
    IRQ0_SET = 0x00     # CPU0 -> CPU1 interrupt set
    IRQ0_CLR = 0x04     # CPU0 -> CPU1 interrupt clear
    IRQ1_SET = 0x08     # CPU1 -> CPU0 interrupt set
    IRQ1_CLR = 0x0C     # CPU1 -> CPU0 interrupt clear
    IRQ0_STATUS = 0x10  # Pending interrupts to CPU0
    IRQ1_STATUS = 0x14  # Pending interrupts to CPU1
    MUTEX = 0x20        # Hardware mutex
    
    def __init__(self, name: str = "MAILBOX", base: int = 0x4002B000, 
                 size: int = 0x400, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.mutex_owner = -1  # -1 = free, 0/1 = owned by CPU
        self.irq0_pending = 0
        self.irq1_pending = 0
        self.cpu0_irq_callback = None
        self.cpu1_irq_callback = None
        
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.MUTEX:
            # Attempt to acquire mutex
            if self.mutex_owner == -1:
                # Mutex was free, now locked
                self.mutex_owner = 0  # Assume CPU0 for now
                return 1  # Success - had mutex
            return 0  # Failed - already locked
        elif offset == self.IRQ0_STATUS:
            return self.irq0_pending
        elif offset == self.IRQ1_STATUS:
            return self.irq1_pending
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.IRQ1_SET:
            self.irq1_pending |= value
            if self.cpu1_irq_callback and self.irq1_pending:
                self.cpu1_irq_callback()
        elif offset == self.IRQ1_CLR:
            self.irq1_pending &= ~value
        elif offset == self.IRQ0_SET:
            self.irq0_pending |= value
            if self.cpu0_irq_callback and self.irq0_pending:
                self.cpu0_irq_callback()
        elif offset == self.IRQ0_CLR:
            self.irq0_pending &= ~value
        elif offset == self.MUTEX:
            if value == 0:
                self.mutex_owner = -1  # Release
        else:
            self.regs[offset] = value


class HSEM(Peripheral):
    """Hardware Semaphore (STM32H7 style).
    
    Provides 32 hardware semaphores for multicore synchronization.
    """
    
    def __init__(self, name: str = "HSEM", base: int = 0x58026400, size: int = 0x400):
        super().__init__(name, base, size)
        self.semaphores = [0] * 32  # 0 = free, else = locked by core ID
        
    def _read_reg(self, offset: int, size: int) -> int:
        if offset < 0x80:
            sem_id = offset // 4
            if sem_id < 32:
                # 1-step lock: read returns previous value and locks
                prev = self.semaphores[sem_id]
                if prev == 0:
                    self.semaphores[sem_id] = 1  # Lock it
                return prev
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset < 0x80:
            sem_id = offset // 4
            if sem_id < 32:
                if value == 0:
                    self.semaphores[sem_id] = 0  # Unlock
        else:
            self.regs[offset] = value


# =============================================================================
# NORDIC nRF5x SPECIFIC PERIPHERALS
# =============================================================================

class NordicPeripheral(Peripheral):
    """Base class for Nordic peripherals using TASK/EVENT model.
    
    Nordic peripherals use a unique programming model:
    - TASKS (0x000-0x07C): Write 1 to trigger action
    - EVENTS (0x100-0x17C): Read/write, set by hardware
    - SHORTS (0x200): Shortcuts between events and tasks
    - INTEN/INTENSET/INTENCLR (0x300-0x308): Interrupt enable
    - Peripheral-specific registers (0x400+)
    """
    
    def __init__(self, name: str, base: int, size: int = 0x1000, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.events = {}  # Event flags
        self.shorts = 0   # Shortcut register
        self.inten = 0    # Interrupt enable
        
    def _read_reg(self, offset: int, size: int) -> int:
        # Events region
        if 0x100 <= offset < 0x180:
            event_id = (offset - 0x100) // 4
            return 1 if self.events.get(event_id, False) else 0
        # SHORTS
        elif offset == 0x200:
            return self.shorts
        # INTEN
        elif offset == 0x300:
            return self.inten
        # INTENSET
        elif offset == 0x304:
            return self.inten
        # INTENCLR
        elif offset == 0x308:
            return self.inten
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        # Tasks region - trigger on write of 1
        if 0x000 <= offset < 0x080:
            if value == 1:
                task_id = offset // 4
                self._handle_task(task_id)
        # Events region - clear on write of 0
        elif 0x100 <= offset < 0x180:
            event_id = (offset - 0x100) // 4
            if value == 0:
                self.events[event_id] = False
        # SHORTS
        elif offset == 0x200:
            self.shorts = value
        # INTENSET (set bits)
        elif offset == 0x304:
            self.inten |= value
        # INTENCLR (clear bits)
        elif offset == 0x308:
            self.inten &= ~value
        else:
            self.regs[offset] = value
    
    def _handle_task(self, task_id: int):
        """Override in subclass to handle specific tasks."""
        self.log.debug(f"Task {task_id} triggered")
    
    def _set_event(self, event_id: int):
        """Set an event flag and check for shortcuts/interrupts."""
        self.events[event_id] = True
        # Check if interrupt is enabled for this event
        if self.inten & (1 << event_id):
            self.trigger_irq()


class NordicCLOCK(NordicPeripheral):
    """Nordic Clock Control.
    
    Manages HFCLK (64MHz) and LFCLK (32.768kHz) sources.
    """
    
    # Tasks
    TASKS_HFCLKSTART = 0x000
    TASKS_HFCLKSTOP = 0x004
    TASKS_LFCLKSTART = 0x008
    TASKS_LFCLKSTOP = 0x00C
    
    # Events
    EVENTS_HFCLKSTARTED = 0x100
    EVENTS_LFCLKSTARTED = 0x104
    
    # Registers
    HFCLKSTAT = 0x40C
    LFCLKSTAT = 0x418
    LFCLKSRC = 0x518
    
    def __init__(self, name: str = "CLOCK", base: int = 0x40000000, size: int = 0x1000):
        super().__init__(name, base, size, irq=0)
        self.hfclk_running = False
        self.lfclk_running = False
        self.regs[self.LFCLKSRC] = 0  # RC oscillator
        
    def _handle_task(self, task_id: int):
        if task_id == 0:  # HFCLKSTART
            self.hfclk_running = True
            self._set_event(0)  # HFCLKSTARTED
            self.log.info("HFCLK started")
        elif task_id == 1:  # HFCLKSTOP
            self.hfclk_running = False
        elif task_id == 2:  # LFCLKSTART
            self.lfclk_running = True
            self._set_event(1)  # LFCLKSTARTED
            self.log.info("LFCLK started")
        elif task_id == 3:  # LFCLKSTOP
            self.lfclk_running = False
            
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.HFCLKSTAT:
            # Bit 0: STATE (1=running), Bit 16: SRC (0=RC, 1=XTAL)
            return (1 if self.hfclk_running else 0) | (1 << 16)
        elif offset == self.LFCLKSTAT:
            return (1 if self.lfclk_running else 0)
        return super()._read_reg(offset, size)


class NordicRADIO(NordicPeripheral):
    """Nordic 2.4GHz Radio.
    
    Supports BLE, 802.15.4, and proprietary protocols.
    """
    
    # Tasks
    TASKS_TXEN = 0x000
    TASKS_RXEN = 0x004
    TASKS_START = 0x008
    TASKS_STOP = 0x00C
    TASKS_DISABLE = 0x010
    
    # Events
    EVENTS_READY = 0x100
    EVENTS_ADDRESS = 0x104
    EVENTS_PAYLOAD = 0x108
    EVENTS_END = 0x10C
    EVENTS_DISABLED = 0x110
    
    # Registers
    PACKETPTR = 0x504
    FREQUENCY = 0x508
    TXPOWER = 0x50C
    MODE = 0x510
    STATE = 0x550
    
    # States
    STATE_DISABLED = 0
    STATE_RXRU = 1
    STATE_RXIDLE = 2
    STATE_RX = 3
    STATE_RXDISABLE = 4
    STATE_TXRU = 9
    STATE_TXIDLE = 10
    STATE_TX = 11
    STATE_TXDISABLE = 12
    
    def __init__(self, name: str = "RADIO", base: int = 0x40001000, size: int = 0x1000):
        super().__init__(name, base, size, irq=1)
        self.state = self.STATE_DISABLED
        self.regs[self.MODE] = 0  # BLE_1MBIT
        self.regs[self.TXPOWER] = 0  # 0 dBm
        self.regs[self.FREQUENCY] = 2  # 2402 MHz
        
    def _handle_task(self, task_id: int):
        if task_id == 0:  # TXEN
            self.state = self.STATE_TXRU
            self._set_event(0)  # READY
            self.state = self.STATE_TXIDLE
            self.log.info("RADIO TX enabled")
        elif task_id == 1:  # RXEN
            self.state = self.STATE_RXRU
            self._set_event(0)  # READY
            self.state = self.STATE_RXIDLE
            self.log.info("RADIO RX enabled")
        elif task_id == 2:  # START
            if self.state == self.STATE_TXIDLE:
                self.state = self.STATE_TX
            elif self.state == self.STATE_RXIDLE:
                self.state = self.STATE_RX
        elif task_id == 3:  # STOP
            if self.state in (self.STATE_TX, self.STATE_RX):
                self._set_event(3)  # END
        elif task_id == 4:  # DISABLE
            self.state = self.STATE_DISABLED
            self._set_event(4)  # DISABLED
            
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.STATE:
            return self.state
        return super()._read_reg(offset, size)


class NordicGPIO(Peripheral):
    """Nordic GPIO Port.
    
    Different register layout than STM32.
    """
    
    OUT = 0x504
    OUTSET = 0x508
    OUTCLR = 0x50C
    IN = 0x510
    DIR = 0x514
    DIRSET = 0x518
    DIRCLR = 0x51C
    LATCH = 0x520
    DETECTMODE = 0x524
    PIN_CNF_BASE = 0x700  # PIN_CNF0 through PIN_CNF31
    
    def __init__(self, name: str, base: int, size: int = 0x300):
        super().__init__(name, base, size)
        self.out_value = 0
        self.direction = 0  # 0 = input, 1 = output
        self.input_value = 0
        self.pin_config = [0] * 32
        
    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.OUT:
            return self.out_value
        elif offset == self.IN:
            # Return inputs for input pins, outputs for output pins
            return (self.input_value & ~self.direction) | (self.out_value & self.direction)
        elif offset == self.DIR:
            return self.direction
        elif self.PIN_CNF_BASE <= offset < self.PIN_CNF_BASE + 128:
            pin = (offset - self.PIN_CNF_BASE) // 4
            return self.pin_config[pin] if pin < 32 else 0
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.OUT:
            self.out_value = value
        elif offset == self.OUTSET:
            self.out_value |= value
        elif offset == self.OUTCLR:
            self.out_value &= ~value
        elif offset == self.DIR:
            self.direction = value
        elif offset == self.DIRSET:
            self.direction |= value
        elif offset == self.DIRCLR:
            self.direction &= ~value
        elif self.PIN_CNF_BASE <= offset < self.PIN_CNF_BASE + 128:
            pin = (offset - self.PIN_CNF_BASE) // 4
            if pin < 32:
                self.pin_config[pin] = value
                # Extract direction from config
                dir_bit = (value >> 0) & 1
                if dir_bit:
                    self.direction |= (1 << pin)
                else:
                    self.direction &= ~(1 << pin)
        else:
            self.regs[offset] = value
            
    def set_input(self, pin: int, value: bool):
        """Set external input value for a pin."""
        if value:
            self.input_value |= (1 << pin)
        else:
            self.input_value &= ~(1 << pin)


class NordicTIMER(NordicPeripheral):
    """Nordic Timer/Counter.
    
    32-bit timer with capture/compare channels.
    """
    
    # Tasks
    TASKS_START = 0x000
    TASKS_STOP = 0x004
    TASKS_COUNT = 0x008
    TASKS_CLEAR = 0x00C
    TASKS_CAPTURE0 = 0x040
    
    # Events  
    EVENTS_COMPARE0 = 0x140
    
    # Registers
    MODE = 0x504
    BITMODE = 0x508
    PRESCALER = 0x510
    CC0 = 0x540
    
    def __init__(self, name: str, base: int, size: int = 0x1000, irq: int = -1):
        super().__init__(name, base, size, irq)
        self.running = False
        self.counter = 0
        self.regs[self.MODE] = 0  # Timer mode
        self.regs[self.BITMODE] = 0  # 16-bit
        self.regs[self.PRESCALER] = 0
        
    def _handle_task(self, task_id: int):
        if task_id == 0:  # START
            self.running = True
            self.log.debug("Timer started")
        elif task_id == 1:  # STOP
            self.running = False
        elif task_id == 2:  # COUNT
            self.counter += 1
        elif task_id == 3:  # CLEAR
            self.counter = 0
        elif 16 <= task_id < 22:  # CAPTURE[0-5]
            cc_idx = task_id - 16
            self.regs[self.CC0 + cc_idx * 4] = self.counter


class NordicNVMC(Peripheral):
    """Nordic Non-Volatile Memory Controller.
    
    Controls flash programming and erasing.
    """
    
    READY = 0x400
    READYNEXT = 0x408
    CONFIG = 0x504
    ERASEPAGE = 0x508
    ERASEALL = 0x50C
    
    CONFIG_WEN = 1   # Write enable
    CONFIG_EEN = 2   # Erase enable
    
    def __init__(self, name: str = "NVMC", base: int = 0x4001E000, size: int = 0x1000):
        super().__init__(name, base, size, irq=30)
        self.regs[self.READY] = 1  # Ready
        self.regs[self.READYNEXT] = 1
        self.regs[self.CONFIG] = 0  # Read-only
        
    def _read_reg(self, offset: int, size: int) -> int:
        return self.regs.get(offset, 0)
    
    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CONFIG:
            self.regs[self.CONFIG] = value & 0x3
            self.log.debug(f"NVMC CONFIG = {value}")
        elif offset == self.ERASEPAGE:
            if self.regs[self.CONFIG] == self.CONFIG_EEN:
                self.log.info(f"NVMC: Erasing page at 0x{value:08X}")
                # Simulate erase time
                self.regs[self.READY] = 0
                # In real impl, would erase flash and set READY=1
                self.regs[self.READY] = 1
        elif offset == self.ERASEALL:
            if value == 1 and self.regs[self.CONFIG] == self.CONFIG_EEN:
                self.log.warning("NVMC: Full chip erase requested!")
        else:
            self.regs[offset] = value


# =============================================================================
# PERIPHERAL FACTORY
# =============================================================================

PERIPHERAL_CLASSES = {
    'rcc': RCC,
    'gpio': GPIO,
    'usart': USART,
    'spi': SPI,
    'timer': Timer,
    'flash': Flash,
    'pwr': PWR,
    'generic': Peripheral,
    # CoreSight Debug
    'dwt': DWT,
    'itm': ITM,
    'fpb': FPB,
    'tpiu': TPIU,
    'rom_table': ROMTable,
    # Dual-Core IPC
    'mailbox': Mailbox,
    'hsem': HSEM,
    # Nordic nRF5x
    'nordic_clock': NordicCLOCK,
    'nordic_radio': NordicRADIO,
    'nordic_gpio': NordicGPIO,
    'nordic_timer': NordicTIMER,
    'nordic_nvmc': NordicNVMC,
    # USB
    'usb_otg': None,  # Lazy import, see create_peripheral()
}


def create_peripheral(config: dict) -> Peripheral:
    """Create peripheral from config dict."""
    ptype = config.get('type', 'generic')
    name = config.get('name', 'unknown')
    base = config.get('base', 0)
    size = config.get('size', 0x400)
    irq = config.get('irq', -1)
    secure_only = config.get('secure_only', False)
    ns_callable = config.get('ns_callable', False)
    
    if ptype == 'usb_otg':
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        periph = USBCDCPeripheral(name, base, size, irq)
        return periph

    cls = PERIPHERAL_CLASSES.get(ptype, Peripheral)

    if ptype in ('usart', 'spi', 'timer'):
        periph = cls(name, base, size, irq)
    else:
        periph = cls(name, base, size)
    
    # Apply TrustZone attributes
    periph.secure_only = secure_only
    periph.ns_callable = ns_callable
    
    return periph


# =============================================================================
# DEFAULT STM32F4 CONFIGURATION
# =============================================================================

DEFAULT_CONFIG = {
    'name': 'STM32F4xx',
    'peripherals': [
        {'name': 'RCC', 'type': 'rcc', 'base': 0x40023800, 'size': 0x400},
        {'name': 'PWR', 'type': 'pwr', 'base': 0x40007000, 'size': 0x400},
        {'name': 'FLASH', 'type': 'flash', 'base': 0x40023C00, 'size': 0x400},
        {'name': 'GPIOA', 'type': 'gpio', 'base': 0x40020000, 'size': 0x400},
        {'name': 'GPIOB', 'type': 'gpio', 'base': 0x40020400, 'size': 0x400},
        {'name': 'GPIOC', 'type': 'gpio', 'base': 0x40020800, 'size': 0x400},
        {'name': 'GPIOD', 'type': 'gpio', 'base': 0x40020C00, 'size': 0x400},
        {'name': 'USART1', 'type': 'usart', 'base': 0x40011000, 'size': 0x400, 'irq': 37},
        {'name': 'USART2', 'type': 'usart', 'base': 0x40004400, 'size': 0x400, 'irq': 38},
        {'name': 'SPI1', 'type': 'spi', 'base': 0x40013000, 'size': 0x400, 'irq': 35},
        {'name': 'TIM2', 'type': 'timer', 'base': 0x40000000, 'size': 0x400, 'irq': 28},
        {'name': 'TIM3', 'type': 'timer', 'base': 0x40000400, 'size': 0x400, 'irq': 29},
        {'name': 'USB_OTG_FS', 'type': 'usb_otg', 'base': 0x50000000, 'size': 0x40000, 'irq': 67},
    ]
}


# =============================================================================
# TCP SERVER
# =============================================================================

class MCUemuServer:
    """TCP server handling QEMU MCUemu peripheral accesses."""
    
    def __init__(self, port: int, config: dict = None, usbip_port: int = 0):
        self.port = port
        self.usbip_port = usbip_port
        self.config = config or DEFAULT_CONFIG
        self.peripherals: List[Peripheral] = []
        self.running = False
        self.client: Optional[asyncio.StreamWriter] = None
        self.usbip_server = None
        self.log = log
    
    def _create_peripherals(self):
        """Create all peripherals from config."""
        self.peripherals.clear()
        for pcfg in self.config.get('peripherals', []):
            p = create_peripheral(pcfg)
            p.irq_callback = self._send_irq
            self.peripherals.append(p)
            self.log.info(f"Created {p.name:12} @ 0x{p.base:08X} - 0x{p.base + p.size - 1:08X}")
    
    def _find_peripheral(self, addr: int) -> Optional[Peripheral]:
        """Find peripheral containing address."""
        for p in self.peripherals:
            if p.contains(addr):
                return p
        return None
    
    def _send_irq(self, irq_num: int, level: int):
        """Send IRQ injection command to QEMU."""
        if self.client:
            try:
                packet = struct.pack('<BIB', CMD_IRQ, irq_num, level)
                self.client.write(packet)
                self.log.debug(f"IRQ {irq_num} level={level}")
            except Exception as e:
                self.log.warning(f"Failed to send IRQ {irq_num}: {e}")
        else:
            self.log.debug(f"IRQ {irq_num} dropped (no client)")
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle connected QEMU client."""
        addr = writer.get_extra_info('peername')
        self.log.info(f"QEMU connected from {addr}")
        self.client = writer
        
        try:
            while self.running:
                # Read command type
                cmd_type = await reader.read(1)
                if not cmd_type:
                    break
                
                cmd = cmd_type[0]
                
                if cmd in (CMD_READ, CMD_READ_S):
                    # Read request: [addr:4][size:4][secure:1]
                    data = await reader.readexactly(9)
                    address, size = struct.unpack('<II', data[:8])
                    secure = (cmd == CMD_READ_S) or (data[8] == 1)
                    
                    # Find peripheral and read
                    periph = self._find_peripheral(address)
                    if periph:
                        value, status = periph.read(address, size, secure)
                    else:
                        value = 0
                        status = STATUS_OK  # Don't error on unmapped reads
                        self.log.debug(f"Unmapped read{'[S]' if secure else '[NS]'}: 0x{address:08X}")
                    
                    # Send response: [value:4][status:1]
                    resp = struct.pack('<IB', value, status)
                    writer.write(resp)
                    await writer.drain()
                
                elif cmd in (CMD_WRITE, CMD_WRITE_S):
                    # Write request: [addr:4][size:4][value:4][secure:1]
                    data = await reader.readexactly(13)
                    address, size, value = struct.unpack('<III', data[:12])
                    secure = (cmd == CMD_WRITE_S) or (data[12] == 1)
                    
                    # Find peripheral and write
                    periph = self._find_peripheral(address)
                    if periph:
                        status = periph.write(address, size, value, secure)
                    else:
                        status = STATUS_OK  # Don't error on unmapped writes
                        self.log.debug(f"Unmapped write{'[S]' if secure else '[NS]'}: 0x{address:08X} <- 0x{value:08X}")
                    
                    # Send response
                    resp = struct.pack('<IB', 0, status)
                    writer.write(resp)
                    await writer.drain()
                
                elif cmd == CMD_CONFIG:
                    # Security configuration (from QEMU for SAU/IDAU setup)
                    data = await reader.readexactly(10)
                    config_cmd = data[0]
                    region = struct.unpack('<I', data[1:5])[0]
                    limit = struct.unpack('<I', data[5:9])[0]
                    attrs = data[9]
                    
                    self.log.info(f"Security config: cmd={config_cmd} region={region} limit=0x{limit:08X} attrs={attrs}")
                    # Could update peripheral security attributes based on SAU config
                    
                    resp = struct.pack('<IB', 0, STATUS_OK)
                    writer.write(resp)
                    await writer.drain()
                
                else:
                    self.log.warning(f"Unknown command: {cmd}")
        
        except asyncio.IncompleteReadError:
            self.log.info("QEMU disconnected (incomplete read)")
        except ConnectionResetError:
            self.log.info("QEMU disconnected (reset)")
        except Exception as e:
            self.log.error(f"Client error: {e}")
        finally:
            self.client = None
            writer.close()
            await writer.wait_closed()
            self.log.info("QEMU disconnected")
    
    def _find_usb_peripheral(self):
        """Find the USB OTG peripheral (if registered)."""
        from slab_cortex_m.usb_cdc_peripheral import USBCDCPeripheral
        for p in self.peripherals:
            if isinstance(p, USBCDCPeripheral):
                return p
        return None

    async def start(self):
        """Start the TCP server."""
        self._create_peripherals()

        # Start background tasks for timer peripherals
        for p in self.peripherals:
            if isinstance(p, Timer):
                p.start_counter()

        server = await asyncio.start_server(
            self._handle_client,
            '127.0.0.1',
            self.port,
            reuse_address=True
        )

        self.running = True

        # Print banner
        print("\n" + "="*70)
        print("  MCUemu Peripheral Server")
        print(f"  Configuration: {self.config.get('name', 'Custom')}")
        print("="*70)
        print(f"\n[Listening] tcp://127.0.0.1:{self.port}")
        print(f"\n[Peripherals] {len(self.peripherals)} configured:")
        for p in sorted(self.peripherals, key=lambda x: x.base):
            irq_str = f"IRQ {p.irq}" if p.irq >= 0 else "no IRQ"
            print(f"  {p.name:12} @ 0x{p.base:08X} ({irq_str})")

        # Start USBIP server if enabled
        tasks = [server.serve_forever()]

        if self.usbip_port > 0:
            usb_periph = self._find_usb_peripheral()
            if usb_periph:
                from slab_cortex_m.usbip_server import USBIPServer
                self.usbip_server = USBIPServer(port=self.usbip_port)
                self.usbip_server.set_usb_peripheral(usb_periph)
                usbip_srv = await asyncio.start_server(
                    self.usbip_server.handle_client,
                    '0.0.0.0',
                    self.usbip_port,
                    reuse_address=True
                )
                tasks.append(usbip_srv.serve_forever())
                print(f"\n[USBIP] Listening on port {self.usbip_port}")
                print(f"  usbip_client.py attach --host localhost --port {self.usbip_port} --busid 1-1")
            else:
                self.log.warning("USBIP port specified but no USB peripheral found")

        print("\n[QEMU Command]")
        print(f"  qemu-system-arm -M slab-cortex-m,tcp-port={self.port} \\")
        print(f"    -kernel firmware.bin")
        print()

        await asyncio.gather(*tasks)

    async def stop(self):
        self.running = False


def load_config(path: str) -> dict:
    """Load configuration from YAML or JSON file."""
    if not path:
        return DEFAULT_CONFIG
    
    p = Path(path)
    if not p.exists():
        log.warning(f"Config not found: {path}, using default")
        return DEFAULT_CONFIG
    
    with open(p) as f:
        if p.suffix in ('.yaml', '.yml'):
            import yaml
            return yaml.safe_load(f)
        else:
            return json.load(f)


async def main_async(args):
    config = load_config(args.config)
    usbip_port = getattr(args, 'usbip_port', 0)
    server = MCUemuServer(args.port, config, usbip_port=usbip_port)

    try:
        await server.start()
    except asyncio.CancelledError:
        await server.stop()


def main():
    parser = argparse.ArgumentParser(description='MCUemu Peripheral Server')
    parser.add_argument('--port', '-p', type=int, default=5000,
                       help='TCP port (default: 5000)')
    parser.add_argument('--usbip-port', type=int, default=0,
                       help='USBIP server port (0 = disabled, default: 0)')
    parser.add_argument('--config', '-c', type=str,
                       help='Peripheral config file (YAML/JSON)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable debug logging')
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[*] Shutdown")


if __name__ == '__main__':
    main()
