"""
STM32 LTDC (LCD-TFT Display Controller) Emulation

Implements the LTDC peripheral found in STM32 MCUs with display
interfaces (F4x9, F7, H7, U5A9/U5G9).

Features:
- 2-layer compositing with alpha blending
- Programmable timing (HSYNC, VSYNC, blanking)
- Shadow register reload (immediate or vertical blanking)
- Per-layer: window, pixel format, alpha, framebuffer address

Reference: RM0456 (STM32U5) LTDC chapter.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable

from .stm32_base import STM32Peripheral, STATUS_OK


class STM32LTDC(STM32Peripheral):
    """
    STM32 LTDC controller.

    Register map (RM0456):
        Global:
        0x08: SSCR     Synchronization Size Configuration
        0x0C: BPCR     Back Porch Configuration
        0x10: AWCR     Active Width Configuration
        0x14: TWCR     Total Width Configuration
        0x18: GCR      Global Control
        0x24: SRCR     Shadow Reload Configuration
        0x2C: BCCR     Background Color Configuration
        0x34: IER      Interrupt Enable
        0x38: ISR      Interrupt Status
        0x3C: ICR      Interrupt Clear
        0x40: LIPCR    Line Interrupt Position Configuration
        0x44: CPSR     Current Position Status
        0x48: CDSR     Current Display Status

        Layer 1 (offset 0x84):
        0x84: L1CR     Layer Control
        0x88: L1WHPCR  Layer Window Horizontal Position
        0x8C: L1WVPCR  Layer Window Vertical Position
        0x90: L1CKCR   Layer Color Keying Configuration
        0x94: L1PFCR   Layer Pixel Format Configuration
        0x98: L1CACR   Layer Constant Alpha Configuration
        0x9C: L1DCCR   Layer Default Color Configuration
        0xA0: L1BFCR   Layer Blending Factors Configuration
        0xA8: L1CFBAR  Layer Color Frame Buffer Address
        0xAC: L1CFBLR  Layer Color Frame Buffer Length
        0xB0: L1CFBLNR Layer Color Frame Buffer Line Number

        Layer 2 (offset 0x104):
        Same layout as Layer 1 but at +0x80
    """

    # Global registers
    SSCR  = 0x08
    BPCR  = 0x0C
    AWCR  = 0x10
    TWCR  = 0x14
    GCR   = 0x18
    SRCR  = 0x24
    BCCR  = 0x2C
    IER   = 0x34
    ISR   = 0x38
    ICR   = 0x3C
    LIPCR = 0x40
    CPSR  = 0x44
    CDSR  = 0x48

    # Layer register offsets (relative to layer base)
    LCR     = 0x00
    LWHPCR  = 0x04
    LWVPCR  = 0x08
    LCKCR   = 0x0C
    LPFCR   = 0x10
    LCACR   = 0x14
    LDCCR   = 0x18
    LBFCR   = 0x1C
    LCFBAR  = 0x24
    LCFBLR  = 0x28
    LCFBLNR = 0x2C

    # Layer base addresses (relative to peripheral base)
    LAYER1_BASE = 0x84
    LAYER2_BASE = 0x104

    # GCR bits
    GCR_LTDCEN = 1 << 0
    GCR_DBW    = 0x7 << 4   # Dither Blue Width
    GCR_DGW    = 0x7 << 8   # Dither Green Width
    GCR_DRW    = 0x7 << 12  # Dither Red Width
    GCR_DEN    = 1 << 16    # Dither Enable
    GCR_PCPOL  = 1 << 28
    GCR_DEPOL  = 1 << 29
    GCR_VSPOL  = 1 << 30
    GCR_HSPOL  = 1 << 31

    # SRCR bits
    SRCR_IMR = 1 << 0  # Immediate Reload
    SRCR_VBR = 1 << 1  # Vertical Blanking Reload

    # ISR/IER/ICR bits
    INT_LIF  = 1 << 0  # Line Interrupt Flag
    INT_FUIF = 1 << 1  # FIFO Underrun Interrupt Flag
    INT_TERRIF = 1 << 2  # Transfer Error Interrupt Flag
    INT_RRIF = 1 << 3  # Register Reload Interrupt Flag

    # Pixel formats
    PF_ARGB8888 = 0
    PF_RGB888   = 1
    PF_RGB565   = 2
    PF_ARGB1555 = 3
    PF_ARGB4444 = 4
    PF_L8       = 5
    PF_AL44     = 6
    PF_AL88     = 7

    def __init__(self, base: int = 0x40016800, irq: int = 135, irq_err: int = 136):
        super().__init__("LTDC", base, 0x400, irq)
        self.irq_err = irq_err

        # Global registers
        self.sscr = 0
        self.bpcr = 0
        self.awcr = 0
        self.twcr = 0
        self.gcr = 0
        self.srcr = 0
        self.bccr = 0
        self.ier = 0
        self.isr = 0
        self.lipcr = 0

        # Layer state (2 layers)
        self.layers = [self._LayerState(), self._LayerState()]

        # Reload callback (notifies external code of framebuffer updates)
        self.on_reload: Optional[Callable[[], None]] = None

    class _LayerState:
        def __init__(self):
            self.cr = 0        # Control (bit 0 = enable)
            self.whpcr = 0     # Window horizontal position
            self.wvpcr = 0     # Window vertical position
            self.ckcr = 0      # Color keying
            self.pfcr = 0      # Pixel format
            self.cacr = 0xFF   # Constant alpha (default opaque)
            self.dccr = 0      # Default color
            self.bfcr = 0x0607 # Blending factors
            self.cfbar = 0     # Frame buffer address
            self.cfblr = 0     # Frame buffer length
            self.cfblnr = 0    # Frame buffer line number

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.SSCR:
            return self.sscr
        elif offset == self.BPCR:
            return self.bpcr
        elif offset == self.AWCR:
            return self.awcr
        elif offset == self.TWCR:
            return self.twcr
        elif offset == self.GCR:
            return self.gcr
        elif offset == self.SRCR:
            return 0  # Self-clearing
        elif offset == self.BCCR:
            return self.bccr
        elif offset == self.IER:
            return self.ier
        elif offset == self.ISR:
            return self.isr
        elif offset == self.ICR:
            return 0  # Write-only
        elif offset == self.LIPCR:
            return self.lipcr
        elif offset == self.CPSR:
            # Current position: simulate line 0, pixel 0
            return 0
        elif offset == self.CDSR:
            # Current display status: VSYNCS=1 (vertical sync active)
            return 0x01

        # Layer registers
        layer, layer_offset = self._decode_layer(offset)
        if layer is not None:
            return self._read_layer(layer, layer_offset)

        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.SSCR:
            self.sscr = value
        elif offset == self.BPCR:
            self.bpcr = value
        elif offset == self.AWCR:
            self.awcr = value
        elif offset == self.TWCR:
            self.twcr = value
        elif offset == self.GCR:
            self.gcr = value
        elif offset == self.SRCR:
            self.srcr = value
            if value & (self.SRCR_IMR | self.SRCR_VBR):
                self._do_reload()
        elif offset == self.BCCR:
            self.bccr = value & 0x00FFFFFF
        elif offset == self.IER:
            self.ier = value
            self._update_irq()
        elif offset == self.ICR:
            self.isr &= ~value
            self._update_irq()
        elif offset == self.LIPCR:
            self.lipcr = value & 0x7FF
        else:
            layer, layer_offset = self._decode_layer(offset)
            if layer is not None:
                self._write_layer(layer, layer_offset, value)

    def _decode_layer(self, offset: int):
        """Decode register offset to (layer_index, layer_relative_offset)."""
        if self.LAYER1_BASE <= offset < self.LAYER1_BASE + 0x30:
            return (0, offset - self.LAYER1_BASE)
        elif self.LAYER2_BASE <= offset < self.LAYER2_BASE + 0x30:
            return (1, offset - self.LAYER2_BASE)
        return (None, 0)

    def _read_layer(self, idx: int, offset: int) -> int:
        l = self.layers[idx]
        if offset == self.LCR:
            return l.cr
        elif offset == self.LWHPCR:
            return l.whpcr
        elif offset == self.LWVPCR:
            return l.wvpcr
        elif offset == self.LCKCR:
            return l.ckcr
        elif offset == self.LPFCR:
            return l.pfcr
        elif offset == self.LCACR:
            return l.cacr
        elif offset == self.LDCCR:
            return l.dccr
        elif offset == self.LBFCR:
            return l.bfcr
        elif offset == self.LCFBAR:
            return l.cfbar
        elif offset == self.LCFBLR:
            return l.cfblr
        elif offset == self.LCFBLNR:
            return l.cfblnr
        return 0

    def _write_layer(self, idx: int, offset: int, value: int):
        l = self.layers[idx]
        if offset == self.LCR:
            l.cr = value
        elif offset == self.LWHPCR:
            l.whpcr = value
        elif offset == self.LWVPCR:
            l.wvpcr = value
        elif offset == self.LCKCR:
            l.ckcr = value
        elif offset == self.LPFCR:
            l.pfcr = value & 0x7
        elif offset == self.LCACR:
            l.cacr = value & 0xFF
        elif offset == self.LDCCR:
            l.dccr = value
        elif offset == self.LBFCR:
            l.bfcr = value
        elif offset == self.LCFBAR:
            l.cfbar = value
        elif offset == self.LCFBLR:
            l.cfblr = value
        elif offset == self.LCFBLNR:
            l.cfblnr = value & 0x7FF

    def _do_reload(self):
        """Execute shadow register reload."""
        self.isr |= self.INT_RRIF
        if self.on_reload:
            self.on_reload()
        self._update_irq()

    def _update_irq(self):
        """Assert/deassert IRQ based on ISR & IER."""
        pending = bool(self.isr & self.ier)
        if self.irq_callback:
            self.irq_callback(self.irq, 1 if pending else 0)

    def is_enabled(self) -> bool:
        """Check if LTDC is enabled."""
        return bool(self.gcr & self.GCR_LTDCEN)

    def get_layer_info(self, idx: int) -> dict:
        """Get layer configuration info."""
        l = self.layers[idx]
        return {
            'enabled': bool(l.cr & 1),
            'pixel_format': l.pfcr,
            'alpha': l.cacr,
            'fb_address': l.cfbar,
            'fb_pitch': (l.cfblr >> 16) & 0x1FFF,
            'fb_lines': l.cfblnr,
            'window_h': (l.whpcr & 0xFFF, (l.whpcr >> 16) & 0xFFF),
            'window_v': (l.wvpcr & 0x7FF, (l.wvpcr >> 16) & 0x7FF),
        }
