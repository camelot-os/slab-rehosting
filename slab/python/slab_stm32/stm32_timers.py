"""
STM32 Timer Peripherals

Implements:
- Basic timers (TIM6/TIM7)
- General purpose timers (TIM2/3/4/5)
- Advanced timers (TIM1/TIM8)
- LPTIM (Low-power timer)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32TimerBase(STM32Peripheral):
    """Base class for STM32 timers."""

    # Common register offsets
    CR1 = 0x00
    CR2 = 0x04
    DIER = 0x0C
    SR = 0x10
    EGR = 0x14
    CNT = 0x24
    PSC = 0x28
    ARR = 0x2C

    # CR1 bits
    CR1_CEN = 1 << 0     # Counter enable
    CR1_UDIS = 1 << 1    # Update disable
    CR1_URS = 1 << 2     # Update request source
    CR1_OPM = 1 << 3     # One-pulse mode
    CR1_DIR = 1 << 4     # Direction
    CR1_CMS = 0x3 << 5   # Center-aligned mode
    CR1_ARPE = 1 << 7    # Auto-reload preload

    # DIER bits
    DIER_UIE = 1 << 0    # Update interrupt enable
    DIER_UDE = 1 << 8    # Update DMA enable

    # SR bits
    SR_UIF = 1 << 0      # Update interrupt flag

    # EGR bits
    EGR_UG = 1 << 0      # Update generation

    def __init__(self, name: str, base: int, irq: int = -1):
        super().__init__(name, base, 0x400, irq)

        self.cr1 = 0
        self.cr2 = 0
        self.dier = 0
        self.sr = 0
        self.cnt = 0
        self.psc = 0
        self.arr = 0xFFFF

        # Internal state
        self.prescaler_counter = 0
        self.on_update: Optional[Callable[[], None]] = None

        # Polling detection (based on Z3 bootloop solver analysis)
        self._read_counts = {}
        self._poll_threshold = 5

    def _read_reg(self, offset: int, size: int) -> int:
        """Read timer register with polling detection and auto-ready."""
        # Track read counts for polling detection (Z3 bootloop solver pattern)
        self._read_counts[offset] = self._read_counts.get(offset, 0) + 1
        count = self._read_counts[offset]

        if offset == self.CR1:
            # Z3 solved TIM6_CR1 to 0x00000001 (CEN bit)
            # If firmware polls CR1, it's likely waiting for timer state
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.DIER:
            return self.dier
        elif offset == self.SR:
            # Auto-set UIF after polling threshold (delay loop pattern)
            # Firmware often polls SR waiting for update event
            if count >= self._poll_threshold and (self.cr1 & self.CR1_CEN):
                self.sr |= self.SR_UIF
                self.log.debug(f"Auto-set SR.UIF after {count} polls")
            return self.sr
        elif offset == self.CNT:
            # Simulate counter increment when enabled and polled
            if (self.cr1 & self.CR1_CEN) and count >= self._poll_threshold:
                # Auto-advance counter to break polling loops
                if self.cr1 & self.CR1_DIR:
                    # Down counting - return 0 to trigger update
                    self.cnt = 0
                else:
                    # Up counting - return ARR to trigger update
                    self.cnt = self.arr
                self.log.debug(f"Auto-advance CNT to {self.cnt} after {count} polls")
            return self.cnt
        elif offset == self.PSC:
            return self.psc
        elif offset == self.ARR:
            return self.arr
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            old_cr1 = self.cr1
            self.cr1 = value
            if (value & self.CR1_CEN) and not (old_cr1 & self.CR1_CEN):
                self.log.debug(f"Timer enabled, PSC={self.psc}, ARR={self.arr}")
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.DIER:
            self.dier = value
        elif offset == self.SR:
            self.sr &= value  # Write 0 to clear
        elif offset == self.EGR:
            if value & self.EGR_UG:
                self._generate_update()
        elif offset == self.CNT:
            self.cnt = value & 0xFFFF
        elif offset == self.PSC:
            self.psc = value & 0xFFFF
        elif offset == self.ARR:
            self.arr = value
        else:
            self.regs[offset] = value

    def _generate_update(self):
        """Generate update event."""
        self.cnt = 0
        self.sr |= self.SR_UIF
        if self.dier & self.DIER_UIE:
            self.trigger_irq(1)
        if self.on_update:
            self.on_update()

    def tick(self):
        """Process one timer clock cycle."""
        if not (self.cr1 & self.CR1_CEN):
            return

        # Prescaler
        self.prescaler_counter += 1
        if self.prescaler_counter <= self.psc:
            return
        self.prescaler_counter = 0

        # Counter
        if self.cr1 & self.CR1_DIR:
            # Down counting
            if self.cnt == 0:
                self.cnt = self.arr
                self._generate_update()
            else:
                self.cnt -= 1
        else:
            # Up counting
            self.cnt += 1
            if self.cnt > self.arr:
                self.cnt = 0
                self._generate_update()


class STM32BasicTimer(STM32TimerBase):
    """
    STM32 Basic Timer (TIM6/TIM7).

    Simple 16-bit up counter with auto-reload.
    Used for basic timing and DAC triggering.
    """

    TIM_BASES = {
        6: 0x40001000,
        7: 0x40001400,
    }

    TIM_IRQS = {
        6: 54,
        7: 55,
    }

    def __init__(self, index: int = 6, base: int = None):
        if base is None:
            base = self.TIM_BASES.get(index, 0x40001000)
        irq = self.TIM_IRQS.get(index, 54)

        super().__init__(f"TIM{index}", base, irq)
        self.index = index


class STM32GeneralTimer(STM32TimerBase):
    """
    STM32 General Purpose Timer (TIM2/3/4/5).

    Features:
    - 16-bit or 32-bit counter (TIM2/5 are 32-bit on F4)
    - 4 capture/compare channels
    - Input capture
    - Output compare
    - PWM generation
    - Encoder interface
    """

    # Additional register offsets
    SMCR = 0x08
    CCMR1 = 0x18
    CCMR2 = 0x1C
    CCER = 0x20
    CCR1 = 0x34
    CCR2 = 0x38
    CCR3 = 0x3C
    CCR4 = 0x40
    DCR = 0x48
    DMAR = 0x4C

    TIM_BASES = {
        2: 0x40000000,
        3: 0x40000400,
        4: 0x40000800,
        5: 0x40000C00,
    }

    TIM_IRQS = {
        2: 28,
        3: 29,
        4: 30,
        5: 50,
    }

    def __init__(self, index: int = 2, base: int = None, is_32bit: bool = False):
        if base is None:
            base = self.TIM_BASES.get(index, 0x40000000)
        irq = self.TIM_IRQS.get(index, 28)

        super().__init__(f"TIM{index}", base, irq)
        self.index = index
        self.is_32bit = is_32bit

        # 32-bit timers
        if is_32bit:
            self.arr = 0xFFFFFFFF

        # Capture/compare registers
        self.ccmr1 = 0
        self.ccmr2 = 0
        self.ccer = 0
        self.ccr = [0, 0, 0, 0]
        self.smcr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.SMCR:
            return self.smcr
        elif offset == self.CCMR1:
            return self.ccmr1
        elif offset == self.CCMR2:
            return self.ccmr2
        elif offset == self.CCER:
            return self.ccer
        elif offset == self.CCR1:
            return self.ccr[0]
        elif offset == self.CCR2:
            return self.ccr[1]
        elif offset == self.CCR3:
            return self.ccr[2]
        elif offset == self.CCR4:
            return self.ccr[3]
        return super()._read_reg(offset, size)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.SMCR:
            self.smcr = value
        elif offset == self.CCMR1:
            self.ccmr1 = value
        elif offset == self.CCMR2:
            self.ccmr2 = value
        elif offset == self.CCER:
            self.ccer = value
        elif offset == self.CCR1:
            self.ccr[0] = value
        elif offset == self.CCR2:
            self.ccr[1] = value
        elif offset == self.CCR3:
            self.ccr[2] = value
        elif offset == self.CCR4:
            self.ccr[3] = value
        else:
            super()._write_reg(offset, size, value)


class STM32AdvancedTimer(STM32GeneralTimer):
    """
    STM32 Advanced Timer (TIM1/TIM8).

    Additional features:
    - Complementary outputs
    - Dead-time generation
    - Break input
    - Repetition counter
    """

    RCR = 0x30   # Repetition counter
    BDTR = 0x44  # Break and dead-time

    TIM_BASES = {
        1: 0x40010000,
        8: 0x40010400,
    }

    TIM_IRQS = {
        1: 25,  # TIM1_UP
        8: 46,  # TIM8_UP
    }

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = self.TIM_BASES.get(index, 0x40010000)
        irq = self.TIM_IRQS.get(index, 25)

        super().__init__(index, base, False)
        self.irq = irq
        self.name = f"TIM{index}"

        self.rcr = 0
        self.bdtr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.RCR:
            return self.rcr
        elif offset == self.BDTR:
            return self.bdtr
        return super()._read_reg(offset, size)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.RCR:
            self.rcr = value & 0xFF
        elif offset == self.BDTR:
            self.bdtr = value
        else:
            super()._write_reg(offset, size, value)


class STM32LPTIM(STM32Peripheral):
    """
    STM32 Low-Power Timer (L4/H7).

    Can operate in Stop mode with LSE/LSI clock.
    """

    ISR = 0x00
    ICR = 0x04
    IER = 0x08
    CFGR = 0x0C
    CR = 0x10
    CMP = 0x14
    ARR = 0x18
    CNT = 0x1C

    def __init__(self, index: int = 1, base: int = 0x40007C00):
        super().__init__(f"LPTIM{index}", base, 0x400, 65)
        self.index = index

        self.isr = 0
        self.ier = 0
        self.cfgr = 0
        self.cr = 0
        self.cmp = 0
        self.arr = 0
        self.cnt = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ISR:
            return self.isr
        elif offset == self.IER:
            return self.ier
        elif offset == self.CFGR:
            return self.cfgr
        elif offset == self.CR:
            return self.cr
        elif offset == self.CMP:
            return self.cmp
        elif offset == self.ARR:
            return self.arr
        elif offset == self.CNT:
            return self.cnt
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ICR:
            self.isr &= ~value
        elif offset == self.IER:
            self.ier = value
        elif offset == self.CFGR:
            self.cfgr = value
        elif offset == self.CR:
            self.cr = value
        elif offset == self.CMP:
            self.cmp = value
        elif offset == self.ARR:
            self.arr = value
