"""
LPC55xx ADC Peripheral

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import List, Optional, Callable
from .nxp_base import NXPPeripheral


class LPCADC(NXPPeripheral):
    """
    LPC55xx 16-bit SAR ADC.

    Features:
    - 16-bit resolution (actual 12-16 bits depending on mode)
    - Up to 16 channels
    - Hardware averaging
    - Temperature sensor
    - Threshold compare
    - DMA support

    Memory Map:
        0x000: VERID - Version ID
        0x004: PARAM - Parameter
        0x008: Reserved
        0x00C: CTRL - Control
        0x010: STAT - Status
        0x014: IE - Interrupt enable
        0x018: DE - DMA enable
        0x01C: CFG - Configuration
        0x020: PAUSE - Pause
        0x028: FCTRL - FIFO control
        0x02C: SWTRIG - Software trigger
        0x100: TCTRL[0-15] - Trigger control
        0x200: CMDL[1-15] - Command low
        0x204: CMDH[1-15] - Command high
        0x300: CV[0-3] - Compare value
        0x400: RESFIFO - Result FIFO
    """

    # Register offsets
    VERID = 0x000
    PARAM = 0x004
    CTRL = 0x00C
    STAT = 0x010
    IE = 0x014
    DE = 0x018
    CFG = 0x01C
    PAUSE = 0x020
    FCTRL = 0x028
    SWTRIG = 0x02C
    TCTRL_BASE = 0x100
    CMDL_BASE = 0x200
    CMDH_BASE = 0x204
    CV_BASE = 0x300
    RESFIFO = 0x400

    # CTRL bits
    CTRL_ADCEN = (1 << 0)
    CTRL_RST = (1 << 1)

    # STAT bits
    STAT_RDY = (1 << 0)
    STAT_FOF = (1 << 1)
    STAT_TCOMP_INT = (1 << 9)

    # CFG bits
    CFG_REFSEL_MASK = 0x03
    CFG_PWRSEL_MASK = 0x30

    def __init__(self, base: int = 0x400A0000):
        super().__init__("ADC", base, 0x1000)

        # Control registers
        self.ctrl = 0
        self.stat = self.STAT_RDY
        self.ie = 0
        self.de = 0
        self.cfg = 0
        self.pause = 0
        self.fctrl = 0

        # Trigger control (16 triggers)
        self.tctrl = [0] * 16

        # Command pairs (15 commands, 1-indexed in hardware)
        self.cmdl = [0] * 16
        self.cmdh = [0] * 16

        # Compare values
        self.cv = [0] * 4

        # Result FIFO
        self.result_fifo: List[int] = []
        self.fifo_depth = 16

        # Channel values (set externally)
        self.channel_values = [0] * 16
        self.temp_sensor_value = 0x8000  # ~25°C

        # Callback for sampling (external simulation)
        self.on_sample: Optional[Callable[[int], int]] = None

    def set_channel_value(self, channel: int, value: int):
        """Set ADC channel value (0-65535 for 16-bit)."""
        if 0 <= channel < 16:
            self.channel_values[channel] = value & 0xFFFF

    def set_channel_voltage(self, channel: int, voltage: float, vref: float = 3.3):
        """Set ADC channel by voltage."""
        if 0 <= channel < 16 and vref > 0:
            value = int((voltage / vref) * 65535)
            self.channel_values[channel] = max(0, min(65535, value))

    def trigger(self, trigger_num: int = 0):
        """Trigger ADC conversion."""
        if not (self.ctrl & self.CTRL_ADCEN):
            return

        if trigger_num >= 16:
            return

        tctrl = self.tctrl[trigger_num]
        if not (tctrl & 0x01):  # HTEN - hardware trigger enable
            return

        cmd_idx = (tctrl >> 8) & 0x0F
        if cmd_idx == 0:
            return

        # Execute command
        self._execute_command(cmd_idx, trigger_num)

    def software_trigger(self, trigger_mask: int):
        """Software trigger for multiple triggers."""
        if not (self.ctrl & self.CTRL_ADCEN):
            return

        for i in range(16):
            if trigger_mask & (1 << i):
                self.trigger(i)

    def _execute_command(self, cmd_idx: int, trigger_num: int):
        """Execute ADC command and store result."""
        cmdl = self.cmdl[cmd_idx]
        cmdh = self.cmdh[cmd_idx]

        # Get channel from CMDL
        channel = cmdl & 0x1F

        # Get value
        if self.on_sample:
            value = self.on_sample(channel)
        elif channel == 26:  # Temperature sensor
            value = self.temp_sensor_value
        else:
            value = self.channel_values[channel % 16]

        # Apply hardware averaging if configured
        avg = (cmdh >> 12) & 0x07
        if avg > 0:
            # Simulate averaging (in real impl, multiple samples)
            pass

        # Build result word
        # Format: [15:0] = result, [19:16] = channel, [23:20] = trigger
        result = (value & 0xFFFF) | ((channel & 0x1F) << 16)
        result |= ((trigger_num & 0x0F) << 24)

        # Add to FIFO
        if len(self.result_fifo) < self.fifo_depth:
            self.result_fifo.append(result)
            self.stat |= self.STAT_RDY
        else:
            self.stat |= self.STAT_FOF  # FIFO overflow

        # Check threshold compare
        self._check_threshold(value, cmd_idx)

        # IRQ if enabled
        if self.ie & (1 << trigger_num):
            self.trigger_irq(1)

    def _check_threshold(self, value: int, cmd_idx: int):
        """Check value against threshold compare."""
        # Simplified - full impl would check CV registers
        pass

    def _read_fifo(self) -> int:
        """Read from result FIFO."""
        if self.result_fifo:
            result = self.result_fifo.pop(0)
            if not self.result_fifo:
                self.stat &= ~self.STAT_RDY
            return result
        return 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.VERID:
            return 0x01000000  # Version 1.0
        elif offset == self.PARAM:
            return 0x00100F00  # 16 triggers, 15 commands
        elif offset == self.CTRL:
            return self.ctrl
        elif offset == self.STAT:
            return self.stat
        elif offset == self.IE:
            return self.ie
        elif offset == self.DE:
            return self.de
        elif offset == self.CFG:
            return self.cfg
        elif offset == self.PAUSE:
            return self.pause
        elif offset == self.FCTRL:
            return (len(self.result_fifo) << 16) | self.fctrl
        elif offset == self.RESFIFO:
            return self._read_fifo()
        elif self.TCTRL_BASE <= offset < self.TCTRL_BASE + 64:
            idx = (offset - self.TCTRL_BASE) // 4
            return self.tctrl[idx] if idx < 16 else 0
        elif self.CMDL_BASE <= offset < self.CMDL_BASE + 128:
            idx = (offset - self.CMDL_BASE) // 8
            if (offset - self.CMDL_BASE) % 8 == 0:
                return self.cmdl[idx] if idx < 16 else 0
            else:
                return self.cmdh[idx] if idx < 16 else 0
        elif self.CV_BASE <= offset < self.CV_BASE + 16:
            idx = (offset - self.CV_BASE) // 4
            return self.cv[idx] if idx < 4 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            if value & self.CTRL_RST:
                self._reset()
            self.ctrl = value & ~self.CTRL_RST
        elif offset == self.STAT:
            # Write 1 to clear flags
            self.stat &= ~(value & 0x7FE)
        elif offset == self.IE:
            self.ie = value
        elif offset == self.DE:
            self.de = value
        elif offset == self.CFG:
            self.cfg = value
        elif offset == self.PAUSE:
            self.pause = value
        elif offset == self.FCTRL:
            self.fctrl = value & 0xFFFF
        elif offset == self.SWTRIG:
            self.software_trigger(value)
        elif self.TCTRL_BASE <= offset < self.TCTRL_BASE + 64:
            idx = (offset - self.TCTRL_BASE) // 4
            if idx < 16:
                self.tctrl[idx] = value
        elif self.CMDL_BASE <= offset < self.CMDL_BASE + 128:
            idx = (offset - self.CMDL_BASE) // 8
            if (offset - self.CMDL_BASE) % 8 == 0:
                if idx < 16:
                    self.cmdl[idx] = value
            else:
                if idx < 16:
                    self.cmdh[idx] = value
        elif self.CV_BASE <= offset < self.CV_BASE + 16:
            idx = (offset - self.CV_BASE) // 4
            if idx < 4:
                self.cv[idx] = value

    def _reset(self):
        """Reset ADC to default state."""
        self.ctrl = 0
        self.stat = self.STAT_RDY
        self.ie = 0
        self.de = 0
        self.cfg = 0
        self.pause = 0
        self.fctrl = 0
        self.tctrl = [0] * 16
        self.cmdl = [0] * 16
        self.cmdh = [0] * 16
        self.cv = [0] * 4
        self.result_fifo.clear()
