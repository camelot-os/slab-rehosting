"""
RP2040/RP2350 ADC, PWM, and DMA Peripherals

Implements:
- ADC - 12-bit SAR ADC with 5 channels (4 GPIO + temperature)
- PWM - 8 slices with 16-bit counters
- DMA - 12-channel DMA controller

References:
- RP2040 Datasheet, Chapter 4 (Peripherals)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
import time
from typing import Dict, List, Optional, Callable, Tuple
from collections import deque

try:
    from .rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR
except ImportError:
    from rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR


# =============================================================================
# ADC - 0x4004C000
# =============================================================================

class RP2040ADC(RP2040Peripheral):
    """
    RP2040 ADC peripheral - 12-bit SAR ADC.

    Features:
    - 500 ksps sampling rate
    - 5 input channels (GPIO26-29 + temperature sensor)
    - Round-robin sampling
    - FIFO with DMA support
    - Free-running mode

    Register Map:
        0x000: CS       - Control and status
        0x004: RESULT   - Result of most recent conversion
        0x008: FCS      - FIFO control and status
        0x00C: FIFO     - FIFO read
        0x010: DIV      - Clock divider
        0x014: INTR     - Raw interrupts
        0x018: INTE     - Interrupt enable
        0x01C: INTF     - Interrupt force
        0x020: INTS     - Interrupt status
    """

    CS = 0x000
    RESULT = 0x004
    FCS = 0x008
    FIFO = 0x00C
    DIV = 0x010
    INTR = 0x014
    INTE = 0x018
    INTF = 0x01C
    INTS = 0x020

    # CS bits
    CS_RROBIN_MASK = 0x1F << 16
    CS_AINSEL_MASK = 0x7 << 12
    CS_ERR_STICKY = 1 << 10
    CS_ERR = 1 << 9
    CS_READY = 1 << 8
    CS_START_MANY = 1 << 3
    CS_START_ONCE = 1 << 2
    CS_TS_EN = 1 << 1
    CS_EN = 1 << 0

    # FCS bits
    FCS_THRESH_MASK = 0xF << 24
    FCS_LEVEL_MASK = 0xF << 16
    FCS_OVER = 1 << 11
    FCS_UNDER = 1 << 10
    FCS_FULL = 1 << 9
    FCS_EMPTY = 1 << 8
    FCS_DREQ_EN = 1 << 3
    FCS_ERR = 1 << 2
    FCS_SHIFT = 1 << 1
    FCS_EN = 1 << 0

    FIFO_SIZE = 8
    NUM_CHANNELS = 5

    def __init__(self, base: int = 0x4004C000, irq: int = 22):
        super().__init__("ADC", base, 0x100, irq)

        # FIFO
        self.fifo: deque = deque(maxlen=self.FIFO_SIZE)

        # Configuration
        self.cs = self.CS_READY
        self.fcs = 0
        self.div = 0
        self.inte = 0
        self.intf = 0

        # Channel values (0-4095)
        self.channel_values = [2048, 2048, 2048, 2048, 2048]  # Mid-scale default

        # Free-running state
        self.running = False
        self.current_channel = 0

        # Callbacks
        self.on_sample: Optional[Callable[[int], int]] = None  # channel -> value

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CS:
            return self.cs | self.CS_READY

        elif offset == self.RESULT:
            return self._get_last_result()

        elif offset == self.FCS:
            return self._get_fcs()

        elif offset == self.FIFO:
            if self.fifo:
                return self.fifo.popleft()
            self.fcs |= self.FCS_UNDER
            return 0

        elif offset == self.DIV:
            return self.div

        elif offset == self.INTR:
            return self._get_intr()

        elif offset == self.INTE:
            return self.inte

        elif offset == self.INTF:
            return self.intf

        elif offset == self.INTS:
            return (self._get_intr() | self.intf) & self.inte

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CS:
            self.cs = value & 0x1F1F0F

            if value & self.CS_START_ONCE:
                self._do_conversion()
                self.cs &= ~self.CS_START_ONCE

            if value & self.CS_START_MANY:
                self.running = True
            else:
                self.running = False

        elif offset == self.FCS:
            # Clear sticky bits by writing 1
            if value & self.FCS_OVER:
                self.fcs &= ~self.FCS_OVER
            if value & self.FCS_UNDER:
                self.fcs &= ~self.FCS_UNDER
            # Set config bits
            self.fcs = (self.fcs & 0xC00) | (value & ~0xC00)

        elif offset == self.DIV:
            self.div = value & 0xFFFFFF

        elif offset == self.INTE:
            self.inte = value & 1

        elif offset == self.INTF:
            self.intf = value & 1

        else:
            self.regs[offset] = value

    def _get_fcs(self) -> int:
        fcs = self.fcs
        fcs = (fcs & ~self.FCS_LEVEL_MASK) | (len(self.fifo) << 16)
        if len(self.fifo) >= self.FIFO_SIZE:
            fcs |= self.FCS_FULL
        else:
            fcs &= ~self.FCS_FULL
        if not self.fifo:
            fcs |= self.FCS_EMPTY
        else:
            fcs &= ~self.FCS_EMPTY
        return fcs

    def _get_intr(self) -> int:
        # FIFO interrupt when level >= threshold
        threshold = (self.fcs >> 24) & 0xF
        if len(self.fifo) >= threshold:
            return 1
        return 0

    def _get_last_result(self) -> int:
        # Return most recent sample
        if self.fifo:
            return self.fifo[-1]
        return 0

    def _do_conversion(self):
        """Perform ADC conversion."""
        channel = (self.cs >> 12) & 0x7
        if channel >= self.NUM_CHANNELS:
            channel = 0

        # Get channel value
        if self.on_sample:
            value = self.on_sample(channel)
        else:
            value = self.channel_values[channel]

        # Clamp to 12 bits
        value = max(0, min(4095, value))

        # Add to FIFO if enabled
        if self.fcs & self.FCS_EN:
            if len(self.fifo) >= self.FIFO_SIZE:
                self.fcs |= self.FCS_OVER
            else:
                # Include channel number if shift enabled
                if self.fcs & self.FCS_SHIFT:
                    value = value | ((channel & 0x7) << 12)
                self.fifo.append(value)

        # Store result
        self.regs[self.RESULT] = value

        # Handle round-robin
        rrobin = (self.cs >> 16) & 0x1F
        if rrobin and self.running:
            # Find next enabled channel
            for i in range(1, 6):
                next_ch = (channel + i) % 5
                if rrobin & (1 << next_ch):
                    self.cs = (self.cs & ~self.CS_AINSEL_MASK) | (next_ch << 12)
                    break

        self.log.debug(f"ADC ch{channel} = {value}")

    def set_channel_value(self, channel: int, value: int):
        """Set the value for an ADC channel (for simulation)."""
        if 0 <= channel < self.NUM_CHANNELS:
            self.channel_values[channel] = max(0, min(4095, value))

    def tick(self):
        """Called periodically for free-running mode."""
        if self.running and (self.cs & self.CS_EN):
            self._do_conversion()


# =============================================================================
# PWM - 0x40050000
# =============================================================================

class RP2040PWM(RP2040Peripheral):
    """
    RP2040 PWM peripheral - 8 independent slices.

    Each slice has:
    - 16-bit counter
    - Two output channels (A and B)
    - Configurable clock divider
    - Multiple modes (free-running, gating, rising/falling edge)

    Register Map (per slice, 0x14 bytes each):
        +0x00: CHx_CSR  - Control and status
        +0x04: CHx_DIV  - Clock divider (INT.FRAC format)
        +0x08: CHx_CTR  - Counter value
        +0x0C: CHx_CC   - Compare values (B << 16 | A)
        +0x10: CHx_TOP  - Counter wrap value

    Global:
        0x0A0: EN       - Enable register
        0x0A4: INTR     - Raw interrupts
        0x0A8: INTE     - Interrupt enable
        0x0AC: INTF     - Interrupt force
        0x0B0: INTS     - Interrupt status
    """

    # Per-slice offsets
    CSR = 0x00
    DIV = 0x04
    CTR = 0x08
    CC = 0x0C
    TOP = 0x10

    # Global registers
    EN = 0x0A0
    INTR = 0x0A4
    INTE = 0x0A8
    INTF = 0x0AC
    INTS = 0x0B0

    # CSR bits
    CSR_PH_ADV = 1 << 7
    CSR_PH_RET = 1 << 6
    CSR_DIVMODE_MASK = 0x3 << 4
    CSR_B_INV = 1 << 3
    CSR_A_INV = 1 << 2
    CSR_PH_CORRECT = 1 << 1
    CSR_EN = 1 << 0

    NUM_SLICES = 8
    SLICE_SIZE = 0x14

    def __init__(self, base: int = 0x40050000, irq: int = 4):
        super().__init__("PWM", base, 0x100, irq)

        # Per-slice state
        self.slices = []
        for i in range(self.NUM_SLICES):
            self.slices.append({
                'csr': 0,
                'div': 0x10,  # Default divider = 1.0
                'ctr': 0,
                'cc': 0,
                'top': 0xFFFF,
                'output_a': False,
                'output_b': False,
            })

        # Global state
        self.en = 0
        self.inte = 0
        self.intf = 0
        self.intr = 0

        # Callbacks
        self.on_output_change: Optional[Callable[[int, bool, bool], None]] = None  # (slice, a, b)

    def _get_slice_offset(self, offset: int) -> Tuple[int, int]:
        """Get slice index and register offset within slice."""
        if offset < self.EN:
            slice_idx = offset // self.SLICE_SIZE
            reg_offset = offset % self.SLICE_SIZE
            return slice_idx, reg_offset
        return -1, offset

    def _read_reg(self, offset: int, size: int) -> int:
        slice_idx, reg_offset = self._get_slice_offset(offset)

        if slice_idx >= 0 and slice_idx < self.NUM_SLICES:
            s = self.slices[slice_idx]
            if reg_offset == self.CSR:
                return s['csr']
            elif reg_offset == self.DIV:
                return s['div']
            elif reg_offset == self.CTR:
                return s['ctr']
            elif reg_offset == self.CC:
                return s['cc']
            elif reg_offset == self.TOP:
                return s['top']

        elif offset == self.EN:
            return self.en
        elif offset == self.INTR:
            return self.intr
        elif offset == self.INTE:
            return self.inte
        elif offset == self.INTF:
            return self.intf
        elif offset == self.INTS:
            return (self.intr | self.intf) & self.inte

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        slice_idx, reg_offset = self._get_slice_offset(offset)

        if slice_idx >= 0 and slice_idx < self.NUM_SLICES:
            s = self.slices[slice_idx]
            if reg_offset == self.CSR:
                s['csr'] = value & 0xFF
            elif reg_offset == self.DIV:
                s['div'] = value & 0xFFF
            elif reg_offset == self.CTR:
                s['ctr'] = value & 0xFFFF
            elif reg_offset == self.CC:
                s['cc'] = value
            elif reg_offset == self.TOP:
                s['top'] = value & 0xFFFF

        elif offset == self.EN:
            self.en = value & 0xFF
        elif offset == self.INTR:
            self.intr &= ~value  # Write 1 to clear
        elif offset == self.INTE:
            self.inte = value & 0xFF
        elif offset == self.INTF:
            self.intf = value & 0xFF
        else:
            self.regs[offset] = value

    def tick(self):
        """Advance PWM counters."""
        for i, s in enumerate(self.slices):
            if not (self.en & (1 << i)):
                continue
            if not (s['csr'] & self.CSR_EN):
                continue

            # Get divider
            div_int = (s['div'] >> 4) & 0xFF
            if div_int == 0:
                div_int = 1

            # Increment counter
            s['ctr'] += 1

            # Check wrap
            if s['ctr'] > s['top']:
                s['ctr'] = 0
                self.intr |= (1 << i)

            # Update outputs
            cc_a = s['cc'] & 0xFFFF
            cc_b = (s['cc'] >> 16) & 0xFFFF

            new_a = s['ctr'] < cc_a
            new_b = s['ctr'] < cc_b

            if s['csr'] & self.CSR_A_INV:
                new_a = not new_a
            if s['csr'] & self.CSR_B_INV:
                new_b = not new_b

            if new_a != s['output_a'] or new_b != s['output_b']:
                s['output_a'] = new_a
                s['output_b'] = new_b
                if self.on_output_change:
                    self.on_output_change(i, new_a, new_b)

        # Check interrupts
        if (self.intr | self.intf) & self.inte:
            self.trigger_irq(1)

    def get_slice_frequency(self, slice_idx: int, sys_clk: int = 125_000_000) -> float:
        """Calculate PWM frequency for a slice."""
        if slice_idx >= self.NUM_SLICES:
            return 0
        s = self.slices[slice_idx]
        div = s['div'] / 16.0
        top = s['top'] + 1
        if div == 0 or top == 0:
            return 0
        return sys_clk / (div * top)


# =============================================================================
# DMA - 0x50000000
# =============================================================================

class RP2040DMAChannel:
    """Single DMA channel state."""
    def __init__(self, index: int):
        self.index = index
        self.read_addr = 0
        self.write_addr = 0
        self.trans_count = 0
        self.ctrl = 0
        self.busy = False
        self.chain_to = index

    def reset(self):
        self.busy = False


class RP2040DMA(RP2040Peripheral):
    """
    RP2040 DMA controller - 12 independent channels.

    Features:
    - 12 channels with programmable priority
    - Ring buffer support
    - Channel chaining
    - Pacing by DREQ signals
    - Sniff (CRC/checksum) support

    Register Map (per channel, 0x40 bytes):
        +0x00: READ_ADDR       - Read address
        +0x04: WRITE_ADDR      - Write address
        +0x08: TRANS_COUNT     - Transfer count
        +0x0C: CTRL_TRIG       - Control + trigger
        +0x10: AL1_CTRL        - Alias 1 control
        ...

    Global:
        0x400: INTR            - Raw interrupt status
        0x404: INTE0           - Interrupt enable for IRQ0
        0x408: INTF0           - Interrupt force for IRQ0
        0x40C: INTS0           - Interrupt status for IRQ0
        ...
        0x430: TIMER0          - Pacing timer 0
        ...
        0x440: MULTI_CHAN_TRIGGER
        0x444: SNIFF_CTRL
        0x448: SNIFF_DATA
    """

    # Per-channel registers
    CH_READ_ADDR = 0x00
    CH_WRITE_ADDR = 0x04
    CH_TRANS_COUNT = 0x08
    CH_CTRL_TRIG = 0x0C
    CH_AL1_CTRL = 0x10
    CH_AL1_READ_ADDR = 0x14
    CH_AL1_WRITE_ADDR = 0x18
    CH_AL1_TRANS_COUNT_TRIG = 0x1C
    CH_AL2_CTRL = 0x20
    CH_AL2_TRANS_COUNT = 0x24
    CH_AL2_READ_ADDR = 0x28
    CH_AL2_WRITE_ADDR_TRIG = 0x2C
    CH_AL3_CTRL = 0x30
    CH_AL3_WRITE_ADDR = 0x34
    CH_AL3_TRANS_COUNT = 0x38
    CH_AL3_READ_ADDR_TRIG = 0x3C

    # Global registers
    INTR = 0x400
    INTE0 = 0x404
    INTF0 = 0x408
    INTS0 = 0x40C
    INTE1 = 0x414
    INTF1 = 0x418
    INTS1 = 0x41C
    TIMER0 = 0x420
    TIMER1 = 0x424
    TIMER2 = 0x428
    TIMER3 = 0x42C
    MULTI_CHAN_TRIGGER = 0x430
    SNIFF_CTRL = 0x434
    SNIFF_DATA = 0x438

    # CTRL bits
    CTRL_AHB_ERROR = 1 << 31
    CTRL_READ_ERROR = 1 << 30
    CTRL_WRITE_ERROR = 1 << 29
    CTRL_BUSY = 1 << 24
    CTRL_SNIFF_EN = 1 << 23
    CTRL_BSWAP = 1 << 22
    CTRL_IRQ_QUIET = 1 << 21
    CTRL_TREQ_SEL_MASK = 0x3F << 15
    CTRL_CHAIN_TO_MASK = 0xF << 11
    CTRL_RING_SEL = 1 << 10
    CTRL_RING_SIZE_MASK = 0xF << 6
    CTRL_INCR_WRITE = 1 << 5
    CTRL_INCR_READ = 1 << 4
    CTRL_DATA_SIZE_MASK = 0x3 << 2
    CTRL_HIGH_PRIORITY = 1 << 1
    CTRL_EN = 1 << 0

    NUM_CHANNELS = 12
    CHANNEL_SIZE = 0x40

    def __init__(self, base: int = 0x50000000, irq: int = 11):
        super().__init__("DMA", base, 0x1000, irq)

        # Channels
        self.channels = [RP2040DMAChannel(i) for i in range(self.NUM_CHANNELS)]

        # Global state
        self.intr = 0
        self.inte0 = 0
        self.intf0 = 0
        self.inte1 = 0
        self.intf1 = 0
        self.timers = [0, 0, 0, 0]
        self.sniff_ctrl = 0
        self.sniff_data = 0

        # Memory access callbacks
        self.on_read: Optional[Callable[[int, int], bytes]] = None  # (addr, size) -> data
        self.on_write: Optional[Callable[[int, bytes], None]] = None  # (addr, data)

    def _get_channel_offset(self, offset: int) -> Tuple[int, int]:
        """Get channel index and register offset within channel."""
        if offset < self.INTR:
            ch_idx = offset // self.CHANNEL_SIZE
            reg_offset = offset % self.CHANNEL_SIZE
            return ch_idx, reg_offset
        return -1, offset

    def _read_reg(self, offset: int, size: int) -> int:
        ch_idx, reg_offset = self._get_channel_offset(offset)

        if ch_idx >= 0 and ch_idx < self.NUM_CHANNELS:
            ch = self.channels[ch_idx]

            if reg_offset == self.CH_READ_ADDR:
                return ch.read_addr
            elif reg_offset == self.CH_WRITE_ADDR:
                return ch.write_addr
            elif reg_offset == self.CH_TRANS_COUNT:
                return ch.trans_count
            elif reg_offset in (self.CH_CTRL_TRIG, self.CH_AL1_CTRL, self.CH_AL2_CTRL, self.CH_AL3_CTRL):
                ctrl = ch.ctrl
                if ch.busy:
                    ctrl |= self.CTRL_BUSY
                return ctrl

            # Alias registers
            elif reg_offset == self.CH_AL1_READ_ADDR:
                return ch.read_addr
            elif reg_offset == self.CH_AL1_WRITE_ADDR:
                return ch.write_addr
            elif reg_offset == self.CH_AL2_TRANS_COUNT:
                return ch.trans_count
            elif reg_offset == self.CH_AL3_WRITE_ADDR:
                return ch.write_addr

        # Global registers
        elif offset == self.INTR:
            return self.intr
        elif offset == self.INTE0:
            return self.inte0
        elif offset == self.INTF0:
            return self.intf0
        elif offset == self.INTS0:
            return (self.intr | self.intf0) & self.inte0
        elif offset == self.INTE1:
            return self.inte1
        elif offset == self.INTF1:
            return self.intf1
        elif offset == self.INTS1:
            return (self.intr | self.intf1) & self.inte1
        elif self.TIMER0 <= offset <= self.TIMER3:
            return self.timers[(offset - self.TIMER0) // 4]
        elif offset == self.SNIFF_CTRL:
            return self.sniff_ctrl
        elif offset == self.SNIFF_DATA:
            return self.sniff_data

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        ch_idx, reg_offset = self._get_channel_offset(offset)

        if ch_idx >= 0 and ch_idx < self.NUM_CHANNELS:
            ch = self.channels[ch_idx]

            if reg_offset == self.CH_READ_ADDR:
                ch.read_addr = value
            elif reg_offset == self.CH_WRITE_ADDR:
                ch.write_addr = value
            elif reg_offset == self.CH_TRANS_COUNT:
                ch.trans_count = value

            elif reg_offset == self.CH_CTRL_TRIG:
                ch.ctrl = value & 0x00FFFFFF
                ch.chain_to = (value >> 11) & 0xF
                if value & self.CTRL_EN:
                    self._start_transfer(ch_idx)

            # Alias trigger registers
            elif reg_offset == self.CH_AL1_TRANS_COUNT_TRIG:
                ch.trans_count = value
                if ch.ctrl & self.CTRL_EN:
                    self._start_transfer(ch_idx)
            elif reg_offset == self.CH_AL2_WRITE_ADDR_TRIG:
                ch.write_addr = value
                if ch.ctrl & self.CTRL_EN:
                    self._start_transfer(ch_idx)
            elif reg_offset == self.CH_AL3_READ_ADDR_TRIG:
                ch.read_addr = value
                if ch.ctrl & self.CTRL_EN:
                    self._start_transfer(ch_idx)

            # Non-trigger aliases
            elif reg_offset == self.CH_AL1_CTRL:
                ch.ctrl = value & 0x00FFFFFF
            elif reg_offset == self.CH_AL1_READ_ADDR:
                ch.read_addr = value
            elif reg_offset == self.CH_AL1_WRITE_ADDR:
                ch.write_addr = value

        # Global registers
        elif offset == self.INTR:
            self.intr &= ~value  # Write 1 to clear
        elif offset == self.INTE0:
            self.inte0 = value & 0xFFFF
        elif offset == self.INTF0:
            self.intf0 = value & 0xFFFF
        elif offset == self.INTE1:
            self.inte1 = value & 0xFFFF
        elif offset == self.INTF1:
            self.intf1 = value & 0xFFFF
        elif self.TIMER0 <= offset <= self.TIMER3:
            self.timers[(offset - self.TIMER0) // 4] = value
        elif offset == self.MULTI_CHAN_TRIGGER:
            # Start multiple channels
            for i in range(self.NUM_CHANNELS):
                if value & (1 << i):
                    self._start_transfer(i)
        elif offset == self.SNIFF_CTRL:
            self.sniff_ctrl = value
        elif offset == self.SNIFF_DATA:
            self.sniff_data = value
        else:
            self.regs[offset] = value

    def _start_transfer(self, ch_idx: int):
        """Start a DMA transfer."""
        ch = self.channels[ch_idx]
        if ch.busy or ch.trans_count == 0:
            return

        ch.busy = True
        data_size = 1 << ((ch.ctrl >> 2) & 0x3)  # 1, 2, or 4 bytes
        incr_read = bool(ch.ctrl & self.CTRL_INCR_READ)
        incr_write = bool(ch.ctrl & self.CTRL_INCR_WRITE)

        self.log.debug(f"DMA ch{ch_idx}: 0x{ch.read_addr:08X} -> 0x{ch.write_addr:08X}, "
                      f"count={ch.trans_count}, size={data_size}")

        # Perform transfer
        for _ in range(ch.trans_count):
            # Read
            if self.on_read:
                data = self.on_read(ch.read_addr, data_size)
            else:
                data = bytes(data_size)

            # Write
            if self.on_write:
                self.on_write(ch.write_addr, data)

            # Update addresses
            if incr_read:
                ch.read_addr += data_size
            if incr_write:
                ch.write_addr += data_size

        ch.trans_count = 0
        ch.busy = False

        # Set interrupt
        self.intr |= (1 << ch_idx)

        # Chain to next channel
        if ch.chain_to != ch_idx and ch.chain_to < self.NUM_CHANNELS:
            self._start_transfer(ch.chain_to)

        # Check interrupts
        if ((self.intr | self.intf0) & self.inte0) or ((self.intr | self.intf1) & self.inte1):
            self.trigger_irq(1)

    def abort(self, channel_mask: int):
        """Abort DMA channels."""
        for i in range(self.NUM_CHANNELS):
            if channel_mask & (1 << i):
                self.channels[i].busy = False
