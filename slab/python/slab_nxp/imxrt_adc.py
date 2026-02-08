"""
i.MX RT ADC Peripheral

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List
from .nxp_base import NXPPeripheral


class IMXRTADC(NXPPeripheral):
    """
    i.MX RT 12-bit SAR ADC.

    Features:
    - 12-bit resolution
    - Up to 16 external channels
    - Single/continuous conversion
    - Hardware trigger
    - Hardware averaging
    - Compare function
    - DMA support

    Memory Map:
        0x00: HC0 - Control register 0
        0x04: HC1 - Control register 1
        ... (up to HC7)
        0x20: HS - Status register
        0x24: R0 - Result register 0
        0x28: R1 - Result register 1
        ... (up to R7)
        0x44: CFG - Configuration
        0x48: GC - General control
        0x4C: GS - General status
        0x50: CV - Compare value
        0x54: OFS - Offset correction
        0x58: CAL - Calibration
    """

    # Register offsets
    HC_BASE = 0x00      # HC0-HC7
    HS = 0x20
    R_BASE = 0x24       # R0-R7
    CFG = 0x44
    GC = 0x48
    GS = 0x4C
    CV = 0x50
    OFS = 0x54
    CAL = 0x58

    # HCx bits
    HC_ADCH_MASK = 0x1F     # Input channel
    HC_AIEN = (1 << 7)       # Interrupt enable

    # HS bits
    HS_COCO0 = (1 << 0)      # Conversion complete 0
    # ... up to COCO7

    # CFG bits
    CFG_ADICLK_MASK = 0x03
    CFG_MODE_MASK = (0x03 << 2)
    CFG_ADLSMP = (1 << 4)    # Long sample time
    CFG_ADIV_MASK = (0x03 << 5)
    CFG_ADLPC = (1 << 7)     # Low power config
    CFG_ADSTS_MASK = (0x03 << 8)
    CFG_ADHSC = (1 << 10)    # High speed config
    CFG_ADTRG = (1 << 13)    # Hardware trigger
    CFG_AVGS_MASK = (0x03 << 14)
    CFG_OVWREN = (1 << 16)   # Overwrite enable

    # GC bits
    GC_ADACKEN = (1 << 0)    # Async clock enable
    GC_DMAEN = (1 << 1)      # DMA enable
    GC_ACREN = (1 << 2)      # Compare range enable
    GC_ACFGT = (1 << 3)      # Compare greater than
    GC_ACFE = (1 << 4)       # Compare function enable
    GC_AVGE = (1 << 5)       # Averaging enable
    GC_ADCO = (1 << 6)       # Continuous conversion
    GC_CAL = (1 << 7)        # Calibration

    # GS bits
    GS_ADACT = (1 << 0)      # Conversion active
    GS_CALF = (1 << 1)       # Calibration failed
    GS_AWKST = (1 << 2)      # Async wakeup status

    def __init__(self, index: int, base: int):
        super().__init__(f"ADC{index}", base, 0x1000)
        self.index = index

        # Control registers (8 channels)
        self.hc = [0x1F] * 8  # Default: disabled
        self.hs = 0
        self.r = [0] * 8

        # Configuration
        self.cfg = 0
        self.gc = 0
        self.gs = 0
        self.cv = 0
        self.ofs = 0
        self.cal = 0

        # Channel values (set externally)
        self.channel_values = [0] * 16

        # Callback
        self.on_sample: Optional[Callable[[int], int]] = None

    def set_channel_value(self, channel: int, value: int):
        """Set ADC channel value (0-4095 for 12-bit)."""
        if 0 <= channel < 16:
            self.channel_values[channel] = value & 0xFFF

    def set_channel_voltage(self, channel: int, voltage: float, vref: float = 3.3):
        """Set ADC channel by voltage."""
        if 0 <= channel < 16 and vref > 0:
            value = int((voltage / vref) * 4095)
            self.channel_values[channel] = max(0, min(4095, value))

    def trigger(self, slot: int = 0):
        """Trigger ADC conversion on slot."""
        if slot >= 8:
            return

        channel = self.hc[slot] & self.HC_ADCH_MASK
        if channel >= 0x10:  # Disabled
            return

        # Get value
        if self.on_sample:
            value = self.on_sample(channel)
        else:
            value = self.channel_values[channel % 16]

        # Apply offset correction
        value = (value + self.ofs) & 0xFFF

        # Apply averaging
        if self.gc & self.GC_AVGE:
            avg_count = 1 << (((self.cfg >> 14) & 0x03) + 2)  # 4, 8, 16, 32
            # In emulation, we just use same value (real HW would average)

        # Store result
        self.r[slot] = value
        self.hs |= (1 << slot)

        # Check compare
        if self.gc & self.GC_ACFE:
            cv1 = self.cv & 0xFFF
            cv2 = (self.cv >> 16) & 0xFFF
            match = False
            if self.gc & self.GC_ACREN:
                # Range compare
                if self.gc & self.GC_ACFGT:
                    match = value >= cv1 and value < cv2
                else:
                    match = value < cv1 or value >= cv2
            else:
                # Single value compare
                if self.gc & self.GC_ACFGT:
                    match = value >= cv1
                else:
                    match = value < cv1
            # Compare result could trigger interrupt

        # Interrupt
        if self.hc[slot] & self.HC_AIEN:
            self.trigger_irq(1)

        # Continuous mode
        if self.gc & self.GC_ADCO:
            # Would re-trigger, but avoid infinite loop in emulation
            pass

    def _read_reg(self, offset: int, size: int) -> int:
        if self.HC_BASE <= offset < self.HC_BASE + 32:
            slot = (offset - self.HC_BASE) // 4
            return self.hc[slot] if slot < 8 else 0
        elif offset == self.HS:
            return self.hs
        elif self.R_BASE <= offset < self.R_BASE + 32:
            slot = (offset - self.R_BASE) // 4
            if slot < 8:
                # Reading clears COCO
                val = self.r[slot]
                self.hs &= ~(1 << slot)
                return val
            return 0
        elif offset == self.CFG:
            return self.cfg
        elif offset == self.GC:
            return self.gc
        elif offset == self.GS:
            return self.gs
        elif offset == self.CV:
            return self.cv
        elif offset == self.OFS:
            return self.ofs
        elif offset == self.CAL:
            return self.cal
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if self.HC_BASE <= offset < self.HC_BASE + 32:
            slot = (offset - self.HC_BASE) // 4
            if slot < 8:
                self.hc[slot] = value & 0xFF
                # Writing HC triggers conversion if software trigger
                if not (self.cfg & self.CFG_ADTRG):
                    channel = value & self.HC_ADCH_MASK
                    if channel < 0x10:
                        self.trigger(slot)
        elif offset == self.CFG:
            self.cfg = value & 0x1FFFF
        elif offset == self.GC:
            if value & self.GC_CAL:
                # Start calibration (instant in emulation)
                self.gs &= ~self.GS_CALF  # Success
            self.gc = value & 0xFF
        elif offset == self.GS:
            # W1C for CALF
            if value & self.GS_CALF:
                self.gs &= ~self.GS_CALF
        elif offset == self.CV:
            self.cv = value
        elif offset == self.OFS:
            self.ofs = value & 0xFFF
        elif offset == self.CAL:
            self.cal = value
