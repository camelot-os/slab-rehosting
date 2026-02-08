"""
STM32 ADC Peripheral Emulation

Implements:
- ADCv1 (F1xx): 12-bit ADC
- ADCv2 (F4xx): 12-bit ADC with triple interleaved
- ADCv3 (L4/H7/U5): 16-bit ADC with oversampling

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from collections import deque
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32ADCv1(STM32Peripheral):
    """
    STM32F1xx ADC (12-bit).

    Register Map:
        0x00: SR     - Status
        0x04: CR1    - Control 1
        0x08: CR2    - Control 2
        0x0C: SMPR1  - Sample time 1
        0x10: SMPR2  - Sample time 2
        0x14-0x28: JOFRx - Injected offset
        0x2C: HTR    - High threshold
        0x30: LTR    - Low threshold
        0x34: SQR1   - Sequence 1
        0x38: SQR2   - Sequence 2
        0x3C: SQR3   - Sequence 3
        0x40: JSQR   - Injected sequence
        0x44-0x50: JDRx - Injected data
        0x4C: DR     - Regular data
    """

    SR = 0x00
    CR1 = 0x04
    CR2 = 0x08
    SMPR1 = 0x0C
    SMPR2 = 0x10
    HTR = 0x2C
    LTR = 0x30
    SQR1 = 0x34
    SQR2 = 0x38
    SQR3 = 0x3C
    JSQR = 0x40
    DR = 0x4C

    # SR bits
    SR_AWD = 1 << 0     # Analog watchdog
    SR_EOC = 1 << 1     # End of conversion
    SR_JEOC = 1 << 2    # Injected end of conversion
    SR_JSTRT = 1 << 3   # Injected start
    SR_STRT = 1 << 4    # Regular start

    # CR1 bits
    CR1_AWDCH = 0x1F    # Analog watchdog channel
    CR1_EOCIE = 1 << 5  # EOC interrupt enable
    CR1_AWDIE = 1 << 6  # AWD interrupt enable
    CR1_JEOCIE = 1 << 7 # JEOC interrupt enable
    CR1_SCAN = 1 << 8   # Scan mode
    CR1_AWDSGL = 1 << 9 # Single channel watchdog

    # CR2 bits
    CR2_ADON = 1 << 0   # ADC on
    CR2_CONT = 1 << 1   # Continuous mode
    CR2_CAL = 1 << 2    # Calibration
    CR2_RSTCAL = 1 << 3 # Reset calibration
    CR2_DMA = 1 << 8    # DMA mode
    CR2_ALIGN = 1 << 11 # Data alignment
    CR2_JEXTTRIG = 1 << 15  # Injected external trigger
    CR2_EXTTRIG = 1 << 20   # External trigger
    CR2_JSWSTART = 1 << 21  # Injected SW start
    CR2_SWSTART = 1 << 22   # SW start

    def __init__(self, index: int = 1, base: int = 0x40012400):
        super().__init__(f"ADC{index}", base, 0x100, 18)
        self.index = index

        self.sr = 0
        self.cr1 = 0
        self.cr2 = 0
        self.smpr1 = 0
        self.smpr2 = 0
        self.htr = 0x0FFF
        self.ltr = 0
        self.sqr = [0, 0, 0]
        self.jsqr = 0
        self.dr = 0
        self.jdr = [0, 0, 0, 0]

        # Channel values (simulated)
        self.channel_values: List[int] = [2048] * 18  # Default mid-scale

        self.on_conversion: Optional[Callable[[int], int]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.SR:
            return self.sr
        elif offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.SMPR1:
            return self.smpr1
        elif offset == self.SMPR2:
            return self.smpr2
        elif offset == self.HTR:
            return self.htr
        elif offset == self.LTR:
            return self.ltr
        elif offset == self.SQR1:
            return self.sqr[0]
        elif offset == self.SQR2:
            return self.sqr[1]
        elif offset == self.SQR3:
            return self.sqr[2]
        elif offset == self.DR:
            self.sr &= ~self.SR_EOC
            return self.dr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.SR:
            self.sr &= value  # Write 0 to clear
        elif offset == self.CR1:
            self.cr1 = value
        elif offset == self.CR2:
            self._write_cr2(value)
        elif offset == self.SMPR1:
            self.smpr1 = value
        elif offset == self.SMPR2:
            self.smpr2 = value
        elif offset == self.HTR:
            self.htr = value & 0xFFF
        elif offset == self.LTR:
            self.ltr = value & 0xFFF
        elif offset == self.SQR1:
            self.sqr[0] = value
        elif offset == self.SQR2:
            self.sqr[1] = value
        elif offset == self.SQR3:
            self.sqr[2] = value

    def _write_cr2(self, value: int):
        self.cr2 = value

        if value & self.CR2_SWSTART:
            self._start_conversion()
            self.cr2 &= ~self.CR2_SWSTART

        if value & self.CR2_CAL:
            # Calibration complete immediately
            self.cr2 &= ~self.CR2_CAL

    def _start_conversion(self):
        """Start ADC conversion."""
        self.sr |= self.SR_STRT

        # Get channel from sequence
        channel = self.sqr[2] & 0x1F  # First channel in sequence

        # Get value
        if self.on_conversion:
            self.dr = self.on_conversion(channel)
        else:
            self.dr = self.channel_values[channel] if channel < 18 else 0

        self.sr |= self.SR_EOC
        if self.cr1 & self.CR1_EOCIE:
            self.trigger_irq(1)

    def set_channel_value(self, channel: int, value: int):
        """Set simulated ADC channel value."""
        if 0 <= channel < 18:
            self.channel_values[channel] = value & 0xFFF


class STM32ADCv2(STM32Peripheral):
    """
    STM32F4xx ADC (12-bit with triple interleaved).

    Similar to v1 but with common registers for triple ADC.
    """

    # Instance registers (same as v1 offsets)
    SR = 0x00
    CR1 = 0x04
    CR2 = 0x08
    SMPR1 = 0x0C
    SMPR2 = 0x10
    SQR1 = 0x34
    SQR2 = 0x38
    SQR3 = 0x3C
    DR = 0x4C

    # Common registers (at ADC_COMMON_BASE = ADC1_BASE + 0x300)
    CSR = 0x00  # Common status
    CCR = 0x04  # Common control
    CDR = 0x08  # Common data (dual/triple mode)

    ADC_BASES = {
        1: 0x40012000,
        2: 0x40012100,
        3: 0x40012200,
    }

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = self.ADC_BASES.get(index, 0x40012000)

        super().__init__(f"ADC{index}", base, 0x100, 18)
        self.index = index

        self.sr = 0
        self.cr1 = 0
        self.cr2 = 0
        self.dr = 0
        self.channel_values: List[int] = [2048] * 19

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.SR:
            return self.sr
        elif offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.DR:
            self.sr &= ~0x02
            return self.dr
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR2:
            self.cr2 = value
            if value & (1 << 30):  # SWSTART
                self._start_conversion()
        else:
            self.regs[offset] = value

    def _start_conversion(self):
        channel = self.regs.get(self.SQR3, 0) & 0x1F
        self.dr = self.channel_values[channel] if channel < 19 else 0
        self.sr |= 0x02  # EOC


class STM32ADCv3(STM32Peripheral):
    """
    STM32L4/H7/U5 ADC (16-bit with oversampling).

    New features:
    - 16-bit resolution
    - Hardware oversampling
    - Offset calibration
    - Dual ADC modes
    """

    ISR = 0x00
    IER = 0x04
    CR = 0x08
    CFGR = 0x0C
    CFGR2 = 0x10
    SMPR1 = 0x14
    SMPR2 = 0x18
    SQR1 = 0x30
    SQR2 = 0x34
    SQR3 = 0x38
    SQR4 = 0x3C
    DR = 0x40
    CALFACT = 0xC4

    # ISR bits
    ISR_ADRDY = 1 << 0
    ISR_EOSMP = 1 << 1
    ISR_EOC = 1 << 2
    ISR_EOS = 1 << 3
    ISR_OVR = 1 << 4

    # CR bits
    CR_ADEN = 1 << 0
    CR_ADDIS = 1 << 1
    CR_ADSTART = 1 << 2
    CR_ADSTP = 1 << 4
    CR_ADVREGEN = 1 << 28
    CR_DEEPPWD = 1 << 29
    CR_ADCAL = 1 << 31

    def __init__(self, index: int = 1, base: int = 0x50040000):
        super().__init__(f"ADC{index}", base, 0x100, 18)
        self.index = index

        self.isr = self.ISR_ADRDY
        self.ier = 0
        self.cr = 0
        self.cfgr = 0
        self.cfgr2 = 0
        self.dr = 0
        self.calfact = 0

        self.channel_values: List[int] = [32768] * 20  # 16-bit mid-scale

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ISR:
            return self.isr
        elif offset == self.IER:
            return self.ier
        elif offset == self.CR:
            return self._get_cr()
        elif offset == self.CFGR:
            return self.cfgr
        elif offset == self.CFGR2:
            return self.cfgr2
        elif offset == self.DR:
            self.isr &= ~self.ISR_EOC
            return self.dr
        elif offset == self.CALFACT:
            return self.calfact
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ISR:
            self.isr &= ~value
        elif offset == self.IER:
            self.ier = value
        elif offset == self.CR:
            self._write_cr(value)
        elif offset == self.CFGR:
            self.cfgr = value
        elif offset == self.CFGR2:
            self.cfgr2 = value
        else:
            self.regs[offset] = value

    def _get_cr(self) -> int:
        cr = self.cr
        # ADRDY when ADEN set
        if cr & self.CR_ADEN:
            self.isr |= self.ISR_ADRDY
        return cr

    def _write_cr(self, value: int):
        self.cr = value

        if value & self.CR_ADCAL:
            # Calibration
            self.calfact = 0x80
            self.cr &= ~self.CR_ADCAL

        if value & self.CR_ADSTART:
            self._start_conversion()
            self.cr &= ~self.CR_ADSTART

    def _start_conversion(self):
        channel = self.regs.get(self.SQR1, 0) & 0x1F
        self.dr = self.channel_values[channel] if channel < 20 else 0
        self.isr |= self.ISR_EOC | self.ISR_EOS
        if self.ier & self.ISR_EOC:
            self.trigger_irq(1)
