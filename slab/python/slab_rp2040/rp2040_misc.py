"""
RP2040/RP2350 Miscellaneous Peripherals

Implements:
- RTC - Real-Time Clock
- ROSC - Ring Oscillator
- SYSINFO - System Information
- SYSCFG - System Configuration
- VREG - Voltage Regulator
- TBMAN - Testbench Manager
- BUSCTRL - Bus Controller
- XIP - Execute-In-Place controller
- IO_QSPI / PADS_QSPI - QSPI GPIO and Pads
- USB - USB Controller

References:
- RP2040 Datasheet

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Tuple

try:
    from .rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR
except ImportError:
    from rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR


# =============================================================================
# RTC - 0x4005C000
# =============================================================================

class RP2040RTC(RP2040Peripheral):
    """
    RP2040 Real-Time Clock.

    Features:
    - Calendar with year, month, day, day-of-week, hour, minute, second
    - Alarm with interrupt
    - Can run from external 32.768kHz crystal or derived from system clock

    Register Map:
        0x00: CLKDIV_M1    - Divider minus 1
        0x04: SETUP_0      - RTC setup 0 (year, month, day)
        0x08: SETUP_1      - RTC setup 1 (dow, hour, min, sec)
        0x0C: CTRL         - Control
        0x10: IRQ_SETUP_0  - Alarm IRQ setup 0
        0x14: IRQ_SETUP_1  - Alarm IRQ setup 1
        0x18: RTC_1        - RTC value 1 (read)
        0x1C: RTC_0        - RTC value 0 (read)
        0x20: INTR         - Raw interrupt
        0x24: INTE         - Interrupt enable
        0x28: INTF         - Interrupt force
        0x2C: INTS         - Interrupt status
    """

    CLKDIV_M1 = 0x00
    SETUP_0 = 0x04
    SETUP_1 = 0x08
    CTRL = 0x0C
    IRQ_SETUP_0 = 0x10
    IRQ_SETUP_1 = 0x14
    RTC_1 = 0x18
    RTC_0 = 0x1C
    INTR = 0x20
    INTE = 0x24
    INTF = 0x28
    INTS = 0x2C

    # CTRL bits
    CTRL_FORCE_NOTLEAPYEAR = 1 << 8
    CTRL_LOAD = 1 << 4
    CTRL_RTC_ACTIVE = 1 << 1
    CTRL_RTC_ENABLE = 1 << 0

    def __init__(self, base: int = 0x4005C000, irq: int = 25):
        super().__init__("RTC", base, 0x100, irq)

        # Time storage
        self.year = 2025
        self.month = 1
        self.day = 1
        self.dotw = 0  # Day of week (0=Sunday)
        self.hour = 0
        self.minute = 0
        self.second = 0

        # Alarm
        self.alarm_year = 0
        self.alarm_month = 0
        self.alarm_day = 0
        self.alarm_dotw = 0
        self.alarm_hour = 0
        self.alarm_minute = 0
        self.alarm_second = 0
        self.alarm_enabled = 0  # Bitmask of which fields are enabled

        # State
        self.enabled = False
        self.clkdiv = 0
        self.inte = 0
        self.intf = 0
        self.intr = 0

        # Setup registers (pending values)
        self.setup_0 = 0
        self.setup_1 = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CLKDIV_M1:
            return self.clkdiv

        elif offset == self.SETUP_0:
            return self.setup_0

        elif offset == self.SETUP_1:
            return self.setup_1

        elif offset == self.CTRL:
            ctrl = 0
            if self.enabled:
                ctrl |= self.CTRL_RTC_ENABLE | self.CTRL_RTC_ACTIVE
            return ctrl

        elif offset == self.RTC_1:
            # Year[23:12], Month[11:8], Day[4:0]
            return (self.year << 12) | (self.month << 8) | self.day

        elif offset == self.RTC_0:
            # DOTW[26:24], Hour[20:16], Min[13:8], Sec[5:0]
            return (self.dotw << 24) | (self.hour << 16) | (self.minute << 8) | self.second

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
        if offset == self.CLKDIV_M1:
            self.clkdiv = value & 0xFFFF

        elif offset == self.SETUP_0:
            self.setup_0 = value
            # Year[23:12], Month[11:8], Day[4:0]
            self.year = (value >> 12) & 0xFFF
            self.month = (value >> 8) & 0xF
            self.day = value & 0x1F

        elif offset == self.SETUP_1:
            self.setup_1 = value
            # DOTW[26:24], Hour[20:16], Min[13:8], Sec[5:0]
            self.dotw = (value >> 24) & 0x7
            self.hour = (value >> 16) & 0x1F
            self.minute = (value >> 8) & 0x3F
            self.second = value & 0x3F

        elif offset == self.CTRL:
            if value & self.CTRL_LOAD:
                # Load values from setup registers
                pass  # Already loaded when setup regs written
            self.enabled = bool(value & self.CTRL_RTC_ENABLE)

        elif offset == self.IRQ_SETUP_0:
            self.regs[offset] = value
            self.alarm_year = (value >> 12) & 0xFFF
            self.alarm_month = (value >> 8) & 0xF
            self.alarm_day = value & 0x1F
            # Enable bits in upper byte
            self.alarm_enabled = (self.alarm_enabled & 0x0F) | ((value >> 24) & 0xF0)

        elif offset == self.IRQ_SETUP_1:
            self.regs[offset] = value
            self.alarm_dotw = (value >> 24) & 0x7
            self.alarm_hour = (value >> 16) & 0x1F
            self.alarm_minute = (value >> 8) & 0x3F
            self.alarm_second = value & 0x3F
            self.alarm_enabled = (self.alarm_enabled & 0xF0) | (value >> 28)

        elif offset == self.INTE:
            self.inte = value & 1
        elif offset == self.INTF:
            self.intf = value & 1
        elif offset == self.INTR:
            self.intr &= ~value  # Write 1 to clear
        else:
            self.regs[offset] = value

    def tick(self):
        """Called every second to advance RTC."""
        if not self.enabled:
            return

        self.second += 1
        if self.second >= 60:
            self.second = 0
            self.minute += 1
            if self.minute >= 60:
                self.minute = 0
                self.hour += 1
                if self.hour >= 24:
                    self.hour = 0
                    self.dotw = (self.dotw + 1) % 7
                    self.day += 1
                    # Simplified month handling
                    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
                    if self.day > days_in_month[self.month - 1]:
                        self.day = 1
                        self.month += 1
                        if self.month > 12:
                            self.month = 1
                            self.year += 1

        # Check alarm
        self._check_alarm()

    def _check_alarm(self):
        """Check if alarm matches current time."""
        # Simplified - check all enabled fields
        match = True
        if self.alarm_enabled:
            # Implementation would check each enabled field
            pass

    def set_from_datetime(self, dt: datetime):
        """Set RTC from Python datetime."""
        self.year = dt.year
        self.month = dt.month
        self.day = dt.day
        self.dotw = dt.weekday()  # Monday=0 in Python
        self.hour = dt.hour
        self.minute = dt.minute
        self.second = dt.second


# =============================================================================
# ROSC - 0x40060000
# =============================================================================

class RP2040ROSC(RP2040Peripheral):
    """
    RP2040 Ring Oscillator.

    The ROSC provides a clock source that doesn't require an external crystal.
    Frequency varies with voltage and temperature (1.8-12 MHz typical).

    Register Map:
        0x00: CTRL      - Control
        0x04: FREQA     - Frequency control A
        0x08: FREQB     - Frequency control B
        0x0C: DORMANT   - Enter dormant mode
        0x10: DIV       - Output divider
        0x14: PHASE     - Phase control
        0x18: STATUS    - Status
        0x1C: RANDOMBIT - Random bit from ring oscillator
        0x20: COUNT     - Cycle count
    """

    CTRL = 0x00
    FREQA = 0x04
    FREQB = 0x08
    DORMANT = 0x0C
    DIV = 0x10
    PHASE = 0x14
    STATUS = 0x18
    RANDOMBIT = 0x1C
    COUNT = 0x20

    # CTRL bits
    CTRL_ENABLE = 0xFAB << 12  # Enable magic value

    # STATUS bits
    STATUS_STABLE = 1 << 31
    STATUS_BADWRITE = 1 << 24
    STATUS_DIV_RUNNING = 1 << 16
    STATUS_ENABLED = 1 << 12

    def __init__(self, base: int = 0x40060000):
        super().__init__("ROSC", base, 0x100)

        self.ctrl = 0xAA0  # Default enabled
        self.freqa = 0
        self.freqb = 0
        self.div = 0
        self.phase = 0
        self.count = 0
        self._random_state = 0x12345678

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CTRL:
            return self.ctrl

        elif offset == self.FREQA:
            return self.freqa

        elif offset == self.FREQB:
            return self.freqb

        elif offset == self.DIV:
            return self.div

        elif offset == self.PHASE:
            return self.phase

        elif offset == self.STATUS:
            status = self.STATUS_STABLE | self.STATUS_DIV_RUNNING
            if self.ctrl & 0xFFF == 0xAA0:
                status |= self.STATUS_ENABLED
            return status

        elif offset == self.RANDOMBIT:
            # Generate pseudo-random bit
            self._random_state ^= self._random_state << 13
            self._random_state ^= self._random_state >> 17
            self._random_state ^= self._random_state << 5
            return self._random_state & 1

        elif offset == self.COUNT:
            return self.count

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self.ctrl = value

        elif offset == self.FREQA:
            # Requires password in upper bits
            if (value >> 16) == 0x9696:
                self.freqa = value & 0xFFFF

        elif offset == self.FREQB:
            if (value >> 16) == 0x9696:
                self.freqb = value & 0xFFFF

        elif offset == self.DIV:
            self.div = value & 0xFFF

        elif offset == self.PHASE:
            self.phase = value & 0xFF

        elif offset == self.COUNT:
            self.count = value & 0xFF

        else:
            self.regs[offset] = value


# =============================================================================
# SYSINFO - 0x40000000
# =============================================================================

class RP2040SYSINFO(RP2040Peripheral):
    """
    RP2040 System Information.

    Read-only registers providing chip identification.

    Register Map:
        0x00: CHIP_ID        - JEDEC chip ID
        0x04: PLATFORM       - Platform register
        0x40: GITREF_RP2040  - Git hash of RP2040 bootrom
    """

    CHIP_ID = 0x00
    PLATFORM = 0x04
    GITREF_RP2040 = 0x40

    def __init__(self, base: int = 0x40000000, chip: str = "RP2040"):
        super().__init__("SYSINFO", base, 0x100)

        self.chip = chip

        # RP2040 CHIP_ID: Manufacturer=Raspberry Pi, Part=RP2040, Revision
        # Format: [31:28]=Revision, [27:12]=Part, [11:1]=Manufacturer, [0]=1
        if chip == "RP2040":
            self.chip_id = (0x0 << 28) | (0x2040 << 12) | (0x14D << 1) | 1
        else:  # RP2350
            self.chip_id = (0x0 << 28) | (0x2350 << 12) | (0x14D << 1) | 1

        # Platform: [1]=ASIC, [0]=FPGA
        self.platform = 0x2  # ASIC

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CHIP_ID:
            return self.chip_id
        elif offset == self.PLATFORM:
            return self.platform
        elif offset == self.GITREF_RP2040:
            return 0x12345678  # Fake git hash
        return 0


# =============================================================================
# SYSCFG - 0x40004000
# =============================================================================

class RP2040SYSCFG(RP2040Peripheral):
    """
    RP2040 System Configuration.

    Register Map:
        0x00: PROC0_NMI_MASK    - NMI mask for proc0
        0x04: PROC1_NMI_MASK    - NMI mask for proc1
        0x08: PROC_CONFIG       - Processor configuration
        0x0C: PROC_IN_SYNC_BYPASS - Input sync bypass
        0x10: PROC_IN_SYNC_BYPASS_HI
        0x14: DBGFORCE          - Debug force
        0x18: MEMPOWERDOWN      - Memory power down
    """

    PROC0_NMI_MASK = 0x00
    PROC1_NMI_MASK = 0x04
    PROC_CONFIG = 0x08
    PROC_IN_SYNC_BYPASS = 0x0C
    PROC_IN_SYNC_BYPASS_HI = 0x10
    DBGFORCE = 0x14
    MEMPOWERDOWN = 0x18

    def __init__(self, base: int = 0x40004000):
        super().__init__("SYSCFG", base, 0x100)

        # Default: all processors can execute from SRAM
        self.regs[self.PROC_CONFIG] = 0x3


# =============================================================================
# VREG_AND_CHIP_RESET - 0x40064000
# =============================================================================

class RP2040VREG(RP2040Peripheral):
    """
    RP2040 Voltage Regulator and Chip Reset.

    Register Map:
        0x00: VREG     - Voltage regulator control
        0x04: BOD      - Brown-out detection control
        0x08: CHIP_RESET - Chip reset control

    The CHIP_RESET register can trigger a full chip reset when written.
    """

    VREG = 0x00
    BOD = 0x04
    CHIP_RESET = 0x08

    # VREG bits
    VREG_ROK = 1 << 12  # Regulator OK
    VREG_VSEL_MASK = 0xF << 4
    VREG_HIZ = 1 << 1
    VREG_EN = 1 << 0

    # CHIP_RESET bits (RP2040 datasheet section 2.8.4.3)
    CHIP_RESET_PSM_RESTART_FLAG = 1 << 24  # Debugger PSM restart flag (RW1C)
    CHIP_RESET_HAD_PSM = 1 << 20           # Had PSM restart (RW1C)
    CHIP_RESET_HAD_RUN = 1 << 16           # Had RUN pin reset (RW1C)
    CHIP_RESET_HAD_POR = 1 << 8            # Had power-on reset (RW1C)

    def __init__(self, base: int = 0x40064000):
        super().__init__("VREG", base, 0x100)

        # Default: 1.1V output, enabled
        self.regs[self.VREG] = self.VREG_ROK | self.VREG_EN | (0xB << 4)  # 1.1V
        self.regs[self.BOD] = 0x91  # Default BOD settings
        self.regs[self.CHIP_RESET] = self.CHIP_RESET_HAD_POR  # Started from POR

        # System reset callback (called when chip reset triggered)
        self.on_system_reset: Optional[Callable[[str], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.VREG:
            # Always report regulator OK
            return self.regs.get(offset, 0) | self.VREG_ROK
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CHIP_RESET:
            # W1C: writing 1 to any status bit clears it
            w1c_mask = (self.CHIP_RESET_PSM_RESTART_FLAG |
                        self.CHIP_RESET_HAD_PSM |
                        self.CHIP_RESET_HAD_RUN |
                        self.CHIP_RESET_HAD_POR)
            self.regs[self.CHIP_RESET] &= ~(value & w1c_mask)
        else:
            self.regs[offset] = value


# =============================================================================
# TBMAN - 0x4006C000
# =============================================================================

class RP2040TBMAN(RP2040Peripheral):
    """
    RP2040 Testbench Manager.

    Used for chip testing. Only one register.

    Register Map:
        0x00: PLATFORM - Platform identification (1=ASIC, 0=FPGA)
    """

    PLATFORM = 0x00

    def __init__(self, base: int = 0x4006C000):
        super().__init__("TBMAN", base, 0x100)
        self.regs[self.PLATFORM] = 1  # ASIC


# =============================================================================
# BUSCTRL - 0x40030000
# =============================================================================

class RP2040BUSCTRL(RP2040Peripheral):
    """
    RP2040 Bus Controller.

    Controls bus fabric priority and performance counters.

    Register Map:
        0x00: BUS_PRIORITY        - Bus priority settings
        0x04: BUS_PRIORITY_ACK    - Acknowledge
        0x08: PERFCTR0            - Performance counter 0
        0x0C: PERFSEL0            - Counter 0 event select
        0x10: PERFCTR1            - Performance counter 1
        0x14: PERFSEL1            - Counter 1 event select
        0x18: PERFCTR2            - Performance counter 2
        0x1C: PERFSEL2            - Counter 2 event select
        0x20: PERFCTR3            - Performance counter 3
        0x24: PERFSEL3            - Counter 3 event select
    """

    BUS_PRIORITY = 0x00
    BUS_PRIORITY_ACK = 0x04
    PERFCTR0 = 0x08
    PERFSEL0 = 0x0C
    PERFCTR1 = 0x10
    PERFSEL1 = 0x14
    PERFCTR2 = 0x18
    PERFSEL2 = 0x1C
    PERFCTR3 = 0x20
    PERFSEL3 = 0x24

    def __init__(self, base: int = 0x40030000):
        super().__init__("BUSCTRL", base, 0x100)


# =============================================================================
# XIP_CTRL - 0x14000000
# =============================================================================

class RP2040XIP(RP2040Peripheral):
    """
    RP2040 XIP (Execute-In-Place) Controller.

    Controls flash execute-in-place behavior.

    Register Map:
        0x00: CTRL        - Control
        0x04: FLUSH       - Cache flush
        0x08: STAT        - Status
        0x0C: CTR_HIT     - Cache hit counter
        0x10: CTR_ACC     - Cache access counter
        0x14: STREAM_ADDR - Stream address
        0x18: STREAM_CTR  - Stream counter
        0x1C: STREAM_FIFO - Stream FIFO
    """

    CTRL = 0x00
    FLUSH = 0x04
    STAT = 0x08
    CTR_HIT = 0x0C
    CTR_ACC = 0x10
    STREAM_ADDR = 0x14
    STREAM_CTR = 0x18
    STREAM_FIFO = 0x1C

    def __init__(self, base: int = 0x14000000):
        super().__init__("XIP_CTRL", base, 0x100)

        # Default: XIP enabled
        self.regs[self.CTRL] = 0x3  # EN + ERR_BADWRITE


# =============================================================================
# XIP_SSI - 0x18000000
# =============================================================================

class RP2040SSI(RP2040Peripheral):
    """
    RP2040 SSI (Serial Peripheral Interface for Flash).

    Synopsys DW_apb_ssi controller for QSPI flash access.

    Register Map:
        0x00: CTRLR0       - Control register 0
        0x04: CTRLR1       - Control register 1
        0x08: SSIENR       - SSI enable
        0x10: SER          - Slave enable
        0x14: BAUDR        - Baud rate
        0x18: TXFTLR       - TX FIFO threshold
        0x1C: RXFTLR       - RX FIFO threshold
        0x20: TXFLR        - TX FIFO level
        0x24: RXFLR        - RX FIFO level
        0x28: SR           - Status
        0x2C: IMR          - Interrupt mask
        0x30: ISR          - Interrupt status
        0x34: RISR         - Raw interrupt status
        0x48: ICR          - Interrupt clear
        0x60: DR0          - Data register
        0xF0: SPI_CTRLR0   - SPI control register
    """

    CTRLR0 = 0x00
    CTRLR1 = 0x04
    SSIENR = 0x08
    SER = 0x10
    BAUDR = 0x14
    TXFTLR = 0x18
    RXFTLR = 0x1C
    TXFLR = 0x20
    RXFLR = 0x24
    SR = 0x28
    IMR = 0x2C
    ISR = 0x30
    RISR = 0x34
    ICR = 0x48
    DR0 = 0x60
    SPI_CTRLR0 = 0xF0

    # SR bits
    SR_DCOL = 1 << 6
    SR_TXE = 1 << 5
    SR_RFF = 1 << 4
    SR_RFNE = 1 << 3
    SR_TFE = 1 << 2
    SR_TFNF = 1 << 1
    SR_BUSY = 1 << 0

    def __init__(self, base: int = 0x18000000):
        super().__init__("XIP_SSI", base, 0x100)

        # Default: TX FIFO empty, not busy
        self.regs[self.SR] = self.SR_TFE | self.SR_TFNF


# =============================================================================
# IO_QSPI - 0x40018000
# =============================================================================

class RP2040IOQSPI(RP2040Peripheral):
    """
    RP2040 QSPI GPIO control.

    Controls the 6 QSPI pins (SCLK, SS, SD0-SD3).

    Register Map (per pin):
        +0x00: STATUS  - GPIO status
        +0x04: CTRL    - GPIO control
    """

    NUM_PINS = 6  # SCLK, SS, SD0-SD3

    def __init__(self, base: int = 0x40018000):
        super().__init__("IO_QSPI", base, 0x100)

        # Initialize function select to XIP (default)
        for i in range(self.NUM_PINS):
            self.regs[i * 8 + 4] = 0  # FUNCSEL = 0 (XIP)


# =============================================================================
# PADS_QSPI - 0x40020000
# =============================================================================

class RP2040PADSQSPI(RP2040Peripheral):
    """
    RP2040 QSPI Pad control.

    Controls electrical characteristics of QSPI pins.

    Register Map:
        0x00: VOLTAGE_SELECT
        0x04: GPIO_QSPI_SCLK
        0x08: GPIO_QSPI_SD0
        0x0C: GPIO_QSPI_SD1
        0x10: GPIO_QSPI_SD2
        0x14: GPIO_QSPI_SD3
        0x18: GPIO_QSPI_SS
    """

    VOLTAGE_SELECT = 0x00
    GPIO_QSPI_SCLK = 0x04
    GPIO_QSPI_SD0 = 0x08
    GPIO_QSPI_SD1 = 0x0C
    GPIO_QSPI_SD2 = 0x10
    GPIO_QSPI_SD3 = 0x14
    GPIO_QSPI_SS = 0x18

    def __init__(self, base: int = 0x40020000):
        super().__init__("PADS_QSPI", base, 0x100)

        # Default pad settings (4mA drive, schmitt trigger enabled)
        default_pad = 0x56  # IE=1, OD=0, PUE=1, PDE=0, SCHMITT=1, SLEWFAST=0, DRIVE=4mA
        for offset in range(0x04, 0x1C, 4):
            self.regs[offset] = default_pad


# =============================================================================
# USB (USBCTRL_REGS) - 0x50110000
# =============================================================================

class RP2040USB(RP2040Peripheral):
    """
    RP2040 USB Device Controller.

    Full-speed USB 2.0 device controller with integrated PHY.

    Register Map (key registers):
        0x00: ADDR_ENDP        - Device address and endpoint control
        0x04: ADDR_ENDP1-15    - Additional endpoint configs
        0x40: MAIN_CTRL        - Main control register
        0x44: SOF_WR           - SOF write (host)
        0x48: SOF_RD           - SOF read
        0x4C: SIE_CTRL         - Serial Interface Engine control
        0x50: SIE_STATUS       - SIE status
        0x54: INT_EP_CTRL      - Interrupt endpoint control
        0x58: BUFF_STATUS      - Buffer status
        0x5C: BUFF_CPU_SHOULD_HANDLE
        0x60: EP_ABORT         - Endpoint abort
        0x64: EP_ABORT_DONE
        0x68: EP_STALL_ARM
        0x6C: NAK_POLL
        0x70: EP_STATUS_STALL_NAK
        0x74: USB_MUXING       - USB mux control
        0x78: USB_PWR          - USB power control
        0x7C: USBPHY_DIRECT    - Direct PHY control
        0x80: USBPHY_DIRECT_OVERRIDE
        0x84: USBPHY_TRIM      - PHY trim values
        0x8C: INTR             - Raw interrupts
        0x90: INTE             - Interrupt enable
        0x94: INTF             - Interrupt force
        0x98: INTS             - Interrupt status
    """

    ADDR_ENDP = 0x00
    MAIN_CTRL = 0x40
    SOF_WR = 0x44
    SOF_RD = 0x48
    SIE_CTRL = 0x4C
    SIE_STATUS = 0x50
    INT_EP_CTRL = 0x54
    BUFF_STATUS = 0x58
    BUFF_CPU_SHOULD_HANDLE = 0x5C
    EP_ABORT = 0x60
    EP_ABORT_DONE = 0x64
    EP_STALL_ARM = 0x68
    NAK_POLL = 0x6C
    EP_STATUS_STALL_NAK = 0x70
    USB_MUXING = 0x74
    USB_PWR = 0x78
    USBPHY_DIRECT = 0x7C
    USBPHY_DIRECT_OVERRIDE = 0x80
    USBPHY_TRIM = 0x84
    INTR = 0x8C
    INTE = 0x90
    INTF = 0x94
    INTS = 0x98

    # MAIN_CTRL bits
    MAIN_CTRL_SIM_TIMING = 1 << 31
    MAIN_CTRL_HOST_NDEVICE = 1 << 1
    MAIN_CTRL_CONTROLLER_EN = 1 << 0

    # SIE_CTRL bits
    SIE_CTRL_EP0_INT_STALL = 1 << 31
    SIE_CTRL_PULLUP_EN = 1 << 16
    SIE_CTRL_TRANSCEIVER_PD = 1 << 18
    SIE_CTRL_START_TRANS = 1 << 15
    SIE_CTRL_RESUME = 1 << 13
    SIE_CTRL_VBUS_EN = 1 << 11

    # SIE_STATUS bits
    SIE_STATUS_CONNECTED = 1 << 16
    SIE_STATUS_SUSPENDED = 1 << 4
    SIE_STATUS_SPEED = 0x3 << 8  # 1=LS, 2=FS
    SIE_STATUS_VBUS_DETECTED = 1 << 0

    # Interrupt bits
    INT_EP_STALL_NAK = 1 << 19
    INT_ABORT_DONE = 1 << 18
    INT_DEV_SOF = 1 << 17
    INT_SETUP_REQ = 1 << 16
    INT_DEV_RESUME_FROM_HOST = 1 << 15
    INT_DEV_SUSPEND = 1 << 14
    INT_DEV_CONN_DIS = 1 << 13
    INT_BUS_RESET = 1 << 12
    INT_VBUS_DETECT = 1 << 11
    INT_STALL = 1 << 10
    INT_ERROR_CRC = 1 << 9
    INT_ERROR_BIT_STUFF = 1 << 8
    INT_ERROR_RX_OVERFLOW = 1 << 7
    INT_ERROR_RX_TIMEOUT = 1 << 6
    INT_ERROR_DATA_SEQ = 1 << 5
    INT_BUFF_STATUS = 1 << 4
    INT_TRANS_COMPLETE = 1 << 3
    INT_HOST_SOF = 1 << 2
    INT_HOST_RESUME = 1 << 1
    INT_HOST_CONN_DIS = 1 << 0

    # DPRAM layout (verified against Pico SDK usb_device_dpram.h)
    DPRAM_SETUP_PACKET     = 0x00   # 8-byte SETUP packet (LOW=0x00, HIGH=0x04)
    DPRAM_EP_CTRL_BASE     = 0x08   # EP1-15 control registers (8 bytes each)
    DPRAM_EP_BUF_CTRL_BASE = 0x80   # EP0-15 buffer control (IN=+0, OUT=+4, 8B each)
    DPRAM_EP0_BUF_DATA_IN  = 0x100  # EP0 IN data buffer (ep0_buf_a, 64 bytes)
    DPRAM_EP0_BUF_DATA_OUT = 0x140  # EP0 OUT data buffer (ep0_buf_b, 64 bytes)
    DPRAM_EPX_DATA         = 0x180  # EP1+ data buffers (64 bytes each)

    # Buffer control bits (in DPRAM)
    BUF_CTRL_FULL = 1 << 15
    BUF_CTRL_LAST = 1 << 14
    BUF_CTRL_DATA_PID = 1 << 13
    BUF_CTRL_AVAILABLE = 1 << 10
    BUF_CTRL_LEN_MASK = 0x3FF

    def __init__(self, base: int = 0x50110000, irq: int = 5):
        super().__init__("USB", base, 0x100, irq)

        self.addr_endp = [0] * 16
        self.main_ctrl = 0
        self.sie_ctrl = 0
        self.sie_status = self.SIE_STATUS_SPEED  # Full-speed
        self.buff_status = 0
        self.inte = 0
        self.intf = 0
        self.intr = 0

        # DPRAM reference (set by peripheral set after creation)
        self.dpram = None  # type: Optional[RP2040USBDPRAM]

        # USBIP firmware-in-the-loop state
        self.setup_packet = b''
        self._ep0_expected = 0
        self._ep0_event = None  # type: Optional[asyncio.Event]
        self._ep0_response = b''
        self._ep0_accum = bytearray()
        self._ep0_max_pkt = 64

        # Bulk endpoint state (EP1-EP15)
        self._ep_events = {}   # ep_num -> asyncio.Event
        self._ep_data = {}     # ep_num -> bytes (IN response data)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ADDR_ENDP:
            return self.addr_endp[0]
        elif 0x04 <= offset < 0x40:
            idx = (offset - 0x04) // 4 + 1
            return self.addr_endp[idx] if idx < 16 else 0
        elif offset == self.MAIN_CTRL:
            return self.main_ctrl
        elif offset == self.SIE_CTRL:
            return self.sie_ctrl
        elif offset == self.SIE_STATUS:
            return self.sie_status
        elif offset == self.BUFF_STATUS:
            return self.buff_status
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
        if offset == self.ADDR_ENDP:
            self.addr_endp[0] = value & 0x7F  # 7-bit address
        elif 0x04 <= offset < 0x40:
            idx = (offset - 0x04) // 4 + 1
            if idx < 16:
                self.addr_endp[idx] = value
        elif offset == self.MAIN_CTRL:
            self.main_ctrl = value
            if value & self.MAIN_CTRL_CONTROLLER_EN:
                self.log.debug("USB controller enabled")
        elif offset == self.SIE_CTRL:
            self.sie_ctrl = value
            if value & self.SIE_CTRL_PULLUP_EN:
                self.sie_status |= self.SIE_STATUS_CONNECTED
        elif offset == self.SIE_STATUS:
            # Write 1 to clear some bits
            self.sie_status &= ~(value & 0xFFFF0000)
        elif offset == self.BUFF_STATUS:
            self.buff_status &= ~value  # Write 1 to clear
        elif offset == self.INTE:
            self.inte = value
        elif offset == self.INTF:
            self.intf = value
        elif offset == self.INTR:
            self.intr &= ~value  # Write 1 to clear
        else:
            self.regs[offset] = value

    def _update_interrupts(self):
        """Update interrupt status and trigger IRQ if needed."""
        ints = (self.intr | self.intf) & self.inte
        if ints:
            self.trigger_irq()

    # =========================================================================
    # USBIP Firmware-in-the-Loop Injection
    # =========================================================================

    def inject_vbus(self, connected: bool = True):
        """Inject VBUS state change."""
        if connected:
            self.intr |= self.INT_VBUS_DETECT
            self.sie_status |= self.SIE_STATUS_VBUS_DETECTED
            self.log.info("VBUS asserted")
        else:
            self.intr &= ~self.INT_VBUS_DETECT
            self.sie_status &= ~self.SIE_STATUS_VBUS_DETECTED
            self.log.info("VBUS deasserted")
        self._update_interrupts()

    def inject_usbrst(self):
        """Inject USB bus reset."""
        self.intr |= self.INT_BUS_RESET
        self.addr_endp[0] = 0  # Reset device address
        self.log.info("Injected BUS_RESET")
        self._update_interrupts()

    def inject_enumdne(self):
        """Inject enumeration done (no-op for RP2040).

        RP2040 does not have an explicit enumeration done event.
        After bus reset, firmware enables the pullup via SIE_CTRL.PULLUP_EN.
        """
        self.log.debug("ENUMDNE not applicable for RP2040 USB")

    def inject_setup_packet(self, setup_data: bytes):
        """Inject a USB SETUP packet into EP0.

        Writes SETUP data to DPRAM setup buffer (offset 0x00),
        sets INT_SETUP_REQ, and triggers interrupt.
        """
        assert len(setup_data) == 8, "SETUP packet must be 8 bytes"

        if self.dpram:
            # Write 8-byte SETUP packet to DPRAM offset 0x00
            self.dpram.mem[self.DPRAM_SETUP_PACKET:self.DPRAM_SETUP_PACKET + 8] = setup_data

        # Track SETUP for wait_ep0_response
        self.setup_packet = setup_data
        self._ep0_expected = setup_data[6] | (setup_data[7] << 8)

        # Set SETUP_REQ interrupt
        self.intr |= self.INT_SETUP_REQ
        self.log.info(f"Injected SETUP: {setup_data.hex()} wLen={self._ep0_expected}")
        self._update_interrupts()

    def _handle_ep0_in_ready(self):
        """EP0 IN buffer filled by firmware -- read response from DPRAM.

        Called when firmware writes to EP0 IN buffer control with FULL bit set.
        """
        if not self.dpram or not self._ep0_event:
            return

        # Read EP0 IN buffer control from DPRAM (offset 0x80)
        ep0_in_ctrl = self.DPRAM_EP_BUF_CTRL_BASE  # 0x80
        buf_ctrl = int.from_bytes(
            self.dpram.mem[ep0_in_ctrl:ep0_in_ctrl + 4],
            'little')

        if not (buf_ctrl & self.BUF_CTRL_FULL):
            return

        pkt_len = buf_ctrl & self.BUF_CTRL_LEN_MASK
        pkt_data = bytes(self.dpram.mem[self.DPRAM_EP0_BUF_DATA_IN:self.DPRAM_EP0_BUF_DATA_IN + pkt_len])

        # Clear FULL bit (host consumed the data)
        buf_ctrl &= ~self.BUF_CTRL_FULL
        self.dpram.mem[ep0_in_ctrl:ep0_in_ctrl + 4] = \
            buf_ctrl.to_bytes(4, 'little')

        # Set BUFF_STATUS for EP0 IN (bit 0) and trigger interrupt
        self.buff_status |= 1  # EP0 IN = bit 0
        self.intr |= self.INT_BUFF_STATUS
        self._update_interrupts()

        # Accumulate for multi-packet
        self._ep0_accum.extend(pkt_data)
        total = len(self._ep0_accum)
        self.log.info(f"EP0 IN packet: {pkt_len}B (total={total}/{self._ep0_expected})")

        # Check completion: short packet or enough data
        if pkt_len < self._ep0_max_pkt or total >= self._ep0_expected:
            self._ep0_response = bytes(self._ep0_accum[:self._ep0_expected])
            self.log.info(f"EP0 IN complete: {len(self._ep0_response)} bytes")
            self._ep0_event.set()

    async def wait_ep0_response(self, timeout: float = 5.0) -> bytes:
        """Wait for firmware to complete EP0 IN transfer."""
        import asyncio
        self._ep0_event = asyncio.Event()
        self._ep0_response = b''
        self._ep0_accum = bytearray()
        try:
            await asyncio.wait_for(self._ep0_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.log.warning("EP0 response timeout (firmware did not respond)")
            if self._ep0_accum:
                self._ep0_response = bytes(self._ep0_accum)
        finally:
            self._ep0_event = None
        return self._ep0_response

    def inject_out_data(self, ep: int, data: bytes):
        """Inject OUT data into an endpoint via DPRAM.

        Writes data to the EP OUT buffer in DPRAM and sets BUFF_STATUS.
        """
        if self.dpram and len(data) > 0:
            # EP0 OUT buffer data at 0x140 (ep0_buf_b)
            self.dpram.mem[self.DPRAM_EP0_BUF_DATA_OUT:self.DPRAM_EP0_BUF_DATA_OUT + len(data)] = data

            # Set EP0 OUT buffer control (offset 0x84): length + FULL
            ep0_out_ctrl = self.DPRAM_EP_BUF_CTRL_BASE + 4  # 0x84
            buf_ctrl = len(data) | self.BUF_CTRL_FULL | self.BUF_CTRL_LAST
            self.dpram.mem[ep0_out_ctrl:ep0_out_ctrl + 4] = \
                buf_ctrl.to_bytes(4, 'little')

        # Set BUFF_STATUS for EP0 OUT (bit 1) and trigger interrupt
        self.buff_status |= (1 << 1)  # EP0 OUT = bit 1
        self.intr |= self.INT_BUFF_STATUS
        self.log.info(f"Injected OUT data EP{ep}: {len(data)} bytes")
        self._update_interrupts()

    # =========================================================================
    # Bulk Endpoint Support (EP1-EP15)
    # =========================================================================

    def _get_ep_buf_ctrl_offset(self, ep: int, direction_in: bool) -> int:
        """Get DPRAM offset for an EP's buffer control register.

        EP buf_ctrl layout: EP0_IN=0x80, EP0_OUT=0x84, EP1_IN=0x88, ...
        """
        return self.DPRAM_EP_BUF_CTRL_BASE + ep * 8 + (0 if direction_in else 4)

    def _get_ep_data_offset(self, ep: int, direction_in: bool) -> int:
        """Get DPRAM offset for an EP's data buffer.

        EP0: IN=0x100 (ep0_buf_a), OUT=0x140 (ep0_buf_b)
        EP1+: read BUFFER_ADDRESS from EP_CTRL register at 0x08 + (ep-1)*8
        """
        if ep == 0:
            return self.DPRAM_EP0_BUF_DATA_IN if direction_in else self.DPRAM_EP0_BUF_DATA_OUT
        if not self.dpram:
            return self.DPRAM_EPX_DATA + (ep - 1) * 128 + (0 if direction_in else 64)
        # Read BUFFER_ADDRESS from EP_CTRL (bits 15:0)
        ctrl_offset = self.DPRAM_EP_CTRL_BASE + (ep - 1) * 8 + (0 if direction_in else 4)
        ep_ctrl = int.from_bytes(
            self.dpram.mem[ctrl_offset:ctrl_offset + 4], 'little')
        buf_addr = ep_ctrl & 0xFFFF
        if buf_addr == 0:
            # Fallback: default layout
            return self.DPRAM_EPX_DATA + (ep - 1) * 128 + (0 if direction_in else 64)
        return buf_addr

    def inject_bulk_out(self, ep: int, data: bytes):
        """Inject bulk OUT data into EPn via DPRAM.

        Writes data to the EP OUT buffer and sets BUFF_STATUS.
        """
        if not self.dpram or ep == 0:
            return

        buf_offset = self._get_ep_data_offset(ep, direction_in=False)
        self.dpram.mem[buf_offset:buf_offset + len(data)] = data

        # Set EP OUT buffer control: length + FULL
        ctrl_offset = self._get_ep_buf_ctrl_offset(ep, direction_in=False)
        buf_ctrl = len(data) | self.BUF_CTRL_FULL | self.BUF_CTRL_LAST
        self.dpram.mem[ctrl_offset:ctrl_offset + 4] = buf_ctrl.to_bytes(4, 'little')

        # Set BUFF_STATUS bit for EPn OUT (bit ep*2+1)
        self.buff_status |= (1 << (ep * 2 + 1))
        self.intr |= self.INT_BUFF_STATUS
        self.log.info(f"Injected bulk OUT EP{ep}: {len(data)} bytes")
        self._update_interrupts()

    def _handle_ep_in_ready(self, ep: int):
        """EP IN buffer filled by firmware -- read response from DPRAM.

        Generalized handler for both EP0 and EP1+.
        """
        if ep == 0:
            self._handle_ep0_in_ready()
            return

        if not self.dpram:
            return

        ctrl_offset = self._get_ep_buf_ctrl_offset(ep, direction_in=True)
        buf_ctrl = int.from_bytes(
            self.dpram.mem[ctrl_offset:ctrl_offset + 4], 'little')

        if not (buf_ctrl & self.BUF_CTRL_FULL):
            return

        pkt_len = buf_ctrl & self.BUF_CTRL_LEN_MASK
        buf_offset = self._get_ep_data_offset(ep, direction_in=True)
        pkt_data = bytes(self.dpram.mem[buf_offset:buf_offset + pkt_len])

        # Clear FULL bit
        buf_ctrl &= ~self.BUF_CTRL_FULL
        self.dpram.mem[ctrl_offset:ctrl_offset + 4] = buf_ctrl.to_bytes(4, 'little')

        # Set BUFF_STATUS for EPn IN (bit ep*2)
        self.buff_status |= (1 << (ep * 2))
        self.intr |= self.INT_BUFF_STATUS
        self._update_interrupts()

        self.log.info(f"EP{ep} IN ready: {pkt_len} bytes")

        # Signal waiting coroutine
        self._ep_data[ep] = pkt_data
        event = self._ep_events.get(ep)
        if event:
            event.set()

    async def wait_bulk_in_response(self, ep: int, timeout: float = 5.0) -> bytes:
        """Wait for firmware to complete EPn IN transfer."""
        import asyncio
        self._ep_events[ep] = asyncio.Event()
        self._ep_data[ep] = b''
        try:
            await asyncio.wait_for(self._ep_events[ep].wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.log.warning(f"EP{ep} IN response timeout")
        finally:
            self._ep_events.pop(ep, None)
        return self._ep_data.pop(ep, b'')


class RP2040USBDPRAM(RP2040Peripheral):
    """
    RP2040 USB DPRAM (4KB endpoint buffers at 0x50100000).

    Memory layout (verified against Pico SDK usb_device_dpram.h):
    - 0x000-0x007: SETUP packet (8 bytes)
    - 0x008-0x07F: EP1-EP15 control registers (IN+OUT, 8 bytes each)
    - 0x080-0x0FF: EP0-EP15 buffer control (IN=+0, OUT=+4, 8 bytes each)
    - 0x100-0x13F: EP0 IN data buffer (ep0_buf_a, 64 bytes)
    - 0x140-0x17F: EP0 OUT data buffer (ep0_buf_b, 64 bytes)
    - 0x180-0xFFF: EP1+ data buffers (64 bytes each)
    """

    def __init__(self, base: int = 0x50100000):
        super().__init__("USB_DPRAM", base, 0x1000, irq=-1)
        self.mem = bytearray(0x1000)
        self._usb_ctrl = None  # Back-reference to RP2040USB (set by peripheral set)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset + size <= len(self.mem):
            return int.from_bytes(self.mem[offset:offset + min(size, 4)], 'little')
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset + size <= len(self.mem):
            self.mem[offset:offset + min(size, 4)] = \
                (value & ((1 << (min(size, 4) * 8)) - 1)).to_bytes(min(size, 4), 'little')

        # Hook: detect EP IN buffer control writes with FULL bit
        # EP IN buf_ctrl offsets: 0x80 (EP0), 0x88 (EP1), 0x90 (EP2), ...
        if (0x80 <= offset < 0x100 and (offset - 0x80) % 8 == 0
                and self._usb_ctrl):
            if value & RP2040USB.BUF_CTRL_FULL:
                ep = (offset - 0x80) // 8
                self._usb_ctrl._handle_ep_in_ready(ep)


# =============================================================================
# XOSC - 0x40024000
# =============================================================================

class RP2040XOSC(RP2040Peripheral):
    """
    RP2040 Crystal Oscillator.

    External 12MHz crystal oscillator for stable clock source.

    Register Map:
        0x00: CTRL      - Control
        0x04: STATUS    - Status
        0x08: DORMANT   - Enter dormant mode
        0x0C: STARTUP   - Startup delay
        0x10: COUNT     - Cycle counter
    """

    CTRL = 0x00
    STATUS = 0x04
    DORMANT = 0x08
    STARTUP = 0x0C
    COUNT = 0x10

    # CTRL bits
    CTRL_ENABLE = 0xFAB << 12   # Enable magic value
    CTRL_DISABLE = 0xD1E << 12  # Disable magic value
    CTRL_FREQ_RANGE_MASK = 0xFFF

    # STATUS bits
    STATUS_STABLE = 1 << 31
    STATUS_BADWRITE = 1 << 24
    STATUS_ENABLED = 1 << 12
    STATUS_FREQ_RANGE_MASK = 0x3

    def __init__(self, base: int = 0x40024000):
        super().__init__("XOSC", base, 0x100)

        self.ctrl = 0xAA0  # Default: enabled, 1-15MHz range
        self.startup = 0xC4  # Default startup delay
        self.count = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CTRL:
            return self.ctrl

        elif offset == self.STATUS:
            # Always report stable when enabled
            status = 0
            if (self.ctrl & 0xFFF000) == self.CTRL_ENABLE or (self.ctrl & 0xFFF) == 0xAA0:
                status |= self.STATUS_STABLE | self.STATUS_ENABLED
            return status

        elif offset == self.STARTUP:
            return self.startup

        elif offset == self.COUNT:
            return self.count

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self.ctrl = value

        elif offset == self.STARTUP:
            self.startup = value & 0x3FFF

        elif offset == self.COUNT:
            self.count = value & 0xFF

        else:
            self.regs[offset] = value


# =============================================================================
# PLL - 0x40028000 (SYS) / 0x4002c000 (USB)
# =============================================================================

class RP2040PLL(RP2040Peripheral):
    """
    RP2040 Phase-Locked Loop.

    Generates high-frequency clocks from XOSC reference.

    Register Map:
        0x00: CS        - Control and status
        0x04: PWR       - Power control
        0x08: FBDIV_INT - Feedback divider (integer)
        0x0C: PRIM      - Primary divider
    """

    CS = 0x00
    PWR = 0x04
    FBDIV_INT = 0x08
    PRIM = 0x0C

    # CS bits
    CS_LOCK = 1 << 31
    CS_BYPASS = 1 << 8
    CS_REFDIV_MASK = 0x3F

    # PWR bits
    PWR_VCOPD = 1 << 5
    PWR_POSTDIVPD = 1 << 3
    PWR_DSMPD = 1 << 2
    PWR_PD = 1 << 0

    def __init__(self, name: str, base: int, target_freq: int = 125000000):
        super().__init__(name, base, 0x100)

        self.target_freq = target_freq
        self.cs = 1  # REFDIV = 1
        self.pwr = self.PWR_VCOPD | self.PWR_POSTDIVPD | self.PWR_PD  # All powered down
        self.fbdiv = 0
        self.prim = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CS:
            cs = self.cs
            # Report locked when powered on and configured
            if not (self.pwr & self.PWR_PD) and self.fbdiv > 0:
                cs |= self.CS_LOCK
            return cs

        elif offset == self.PWR:
            return self.pwr

        elif offset == self.FBDIV_INT:
            return self.fbdiv

        elif offset == self.PRIM:
            return self.prim

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CS:
            self.cs = value & 0x13F  # REFDIV and BYPASS

        elif offset == self.PWR:
            self.pwr = value & 0x2D

        elif offset == self.FBDIV_INT:
            self.fbdiv = value & 0xFFF

        elif offset == self.PRIM:
            self.prim = value

        else:
            self.regs[offset] = value


# =============================================================================
# RESETS - 0x4000c000
# =============================================================================

class RP2040RESETS(RP2040Peripheral):
    """
    RP2040 Reset Controller.

    Controls reset state of all peripherals. Critical for bootrom operation.

    Register Map:
        0x00: RESET          - Reset control (1=hold in reset)
        0x04: WDSEL          - Watchdog select
        0x08: RESET_DONE     - Reset done status (1=out of reset)
    """

    RESET = 0x00
    WDSEL = 0x04
    RESET_DONE = 0x08

    # Reset bits for each peripheral
    RESET_USBCTRL = 1 << 24
    RESET_UART1 = 1 << 23
    RESET_UART0 = 1 << 22
    RESET_TIMER = 1 << 21
    RESET_TBMAN = 1 << 20
    RESET_SYSINFO = 1 << 19
    RESET_SYSCFG = 1 << 18
    RESET_SPI1 = 1 << 17
    RESET_SPI0 = 1 << 16
    RESET_RTC = 1 << 15
    RESET_PWM = 1 << 14
    RESET_PLL_USB = 1 << 13
    RESET_PLL_SYS = 1 << 12
    RESET_PIO1 = 1 << 11
    RESET_PIO0 = 1 << 10
    RESET_PADS_QSPI = 1 << 9
    RESET_PADS_BANK0 = 1 << 8
    RESET_JTAG = 1 << 7
    RESET_IO_QSPI = 1 << 6
    RESET_IO_BANK0 = 1 << 5
    RESET_I2C1 = 1 << 4
    RESET_I2C0 = 1 << 3
    RESET_DMA = 1 << 2
    RESET_BUSCTRL = 1 << 1
    RESET_ADC = 1 << 0

    ALL_RESETS = 0x1FFFFFF  # All 25 reset bits

    def __init__(self, base: int = 0x4000c000):
        super().__init__("RESETS", base, 0x100)

        # Default: all peripherals in reset
        self.reset = self.ALL_RESETS
        self.wdsel = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.RESET:
            return self.reset

        elif offset == self.WDSEL:
            return self.wdsel

        elif offset == self.RESET_DONE:
            # Return inverse of reset (peripherals out of reset are "done")
            return (~self.reset) & self.ALL_RESETS

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.RESET:
            old_reset = self.reset
            self.reset = value & self.ALL_RESETS
            # Log changes
            released = old_reset & ~self.reset
            if released:
                self.log.debug(f"Released from reset: 0x{released:06x}")

        elif offset == self.WDSEL:
            self.wdsel = value & self.ALL_RESETS

        else:
            self.regs[offset] = value


# =============================================================================
# CLOCKS - 0x40008000
# =============================================================================

class RP2040CLOCKS(RP2040Peripheral):
    """
    RP2040 Clock Controller.

    Manages clock sources and distribution.

    Register Map:
        0x00: CLK_GPOUT0_CTRL
        0x04: CLK_GPOUT0_DIV
        0x08: CLK_GPOUT0_SELECTED
        ...
        0x30: CLK_REF_CTRL
        0x34: CLK_REF_DIV
        0x38: CLK_REF_SELECTED
        0x3C: CLK_SYS_CTRL
        0x40: CLK_SYS_DIV
        0x44: CLK_SYS_SELECTED
        0x48: CLK_PERI_CTRL
        0x50: CLK_PERI_SELECTED
        0x54: CLK_USB_CTRL
        0x58: CLK_USB_DIV
        0x5C: CLK_USB_SELECTED
        0x60: CLK_ADC_CTRL
        0x64: CLK_ADC_DIV
        0x68: CLK_ADC_SELECTED
        0x6C: CLK_RTC_CTRL
        0x70: CLK_RTC_DIV
        0x74: CLK_RTC_SELECTED
        0x78: CLK_SYS_RESUS_CTRL
        0x7C: CLK_SYS_RESUS_STATUS
        0x80: FC0_REF_KHZ
        0x84: FC0_MIN_KHZ
        0x88: FC0_MAX_KHZ
        0x8C: FC0_DELAY
        0x90: FC0_INTERVAL
        0x94: FC0_SRC
        0x98: FC0_STATUS
        0x9C: FC0_RESULT
        ...
    """

    # Clock control registers (CTRL, DIV, SELECTED triplets)
    CLK_GPOUT0_CTRL = 0x00
    CLK_GPOUT0_DIV = 0x04
    CLK_GPOUT0_SELECTED = 0x08

    CLK_GPOUT1_CTRL = 0x0C
    CLK_GPOUT1_DIV = 0x10
    CLK_GPOUT1_SELECTED = 0x14

    CLK_GPOUT2_CTRL = 0x18
    CLK_GPOUT2_DIV = 0x1C
    CLK_GPOUT2_SELECTED = 0x20

    CLK_GPOUT3_CTRL = 0x24
    CLK_GPOUT3_DIV = 0x28
    CLK_GPOUT3_SELECTED = 0x2C

    CLK_REF_CTRL = 0x30
    CLK_REF_DIV = 0x34
    CLK_REF_SELECTED = 0x38

    CLK_SYS_CTRL = 0x3C
    CLK_SYS_DIV = 0x40
    CLK_SYS_SELECTED = 0x44

    CLK_PERI_CTRL = 0x48
    CLK_PERI_SELECTED = 0x50

    CLK_USB_CTRL = 0x54
    CLK_USB_DIV = 0x58
    CLK_USB_SELECTED = 0x5C

    CLK_ADC_CTRL = 0x60
    CLK_ADC_DIV = 0x64
    CLK_ADC_SELECTED = 0x68

    CLK_RTC_CTRL = 0x6C
    CLK_RTC_DIV = 0x70
    CLK_RTC_SELECTED = 0x74

    CLK_SYS_RESUS_CTRL = 0x78
    CLK_SYS_RESUS_STATUS = 0x7C

    # Frequency counter
    FC0_REF_KHZ = 0x80
    FC0_MIN_KHZ = 0x84
    FC0_MAX_KHZ = 0x88
    FC0_DELAY = 0x8C
    FC0_INTERVAL = 0x90
    FC0_SRC = 0x94
    FC0_STATUS = 0x98
    FC0_RESULT = 0x9C

    # Interrupt registers
    WAKE_EN0 = 0xA0
    WAKE_EN1 = 0xA4
    SLEEP_EN0 = 0xA8
    SLEEP_EN1 = 0xAC
    ENABLED0 = 0xB0
    ENABLED1 = 0xB4
    INTR = 0xB8
    INTE = 0xBC
    INTF = 0xC0
    INTS = 0xC4

    def __init__(self, base: int = 0x40008000, irq: int = 17):
        super().__init__("CLOCKS", base, 0x100, irq)

        # Selected registers show which clock source is active (1-hot)
        # Default: ROSC for ref, ref for sys
        self.clk_ref_selected = 0x1   # ROSC
        self.clk_sys_selected = 0x1   # CLK_REF
        self.clk_peri_selected = 0x1
        self.clk_usb_selected = 0x1
        self.clk_adc_selected = 0x1
        self.clk_rtc_selected = 0x1

        self.inte = 0
        self.intf = 0
        self.intr = 0

    def _read_reg(self, offset: int, size: int) -> int:
        # SELECTED registers return 1-hot encoding of active source
        if offset == self.CLK_REF_SELECTED:
            return self.clk_ref_selected
        elif offset == self.CLK_SYS_SELECTED:
            return self.clk_sys_selected
        elif offset == self.CLK_PERI_SELECTED:
            return self.clk_peri_selected
        elif offset == self.CLK_USB_SELECTED:
            return self.clk_usb_selected
        elif offset == self.CLK_ADC_SELECTED:
            return self.clk_adc_selected
        elif offset == self.CLK_RTC_SELECTED:
            return self.clk_rtc_selected
        elif offset in (self.CLK_GPOUT0_SELECTED, self.CLK_GPOUT1_SELECTED,
                        self.CLK_GPOUT2_SELECTED, self.CLK_GPOUT3_SELECTED):
            return 0x1

        elif offset == self.FC0_STATUS:
            return 0x10  # DONE bit set
        elif offset == self.FC0_RESULT:
            return 12000  # 12MHz in kHz

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
        # CTRL registers trigger clock switching
        if offset == self.CLK_REF_CTRL:
            self.regs[offset] = value
            # Update selected based on SRC field
            src = value & 0x3
            self.clk_ref_selected = 1 << src

        elif offset == self.CLK_SYS_CTRL:
            self.regs[offset] = value
            # SRC is bit 0, AUXSRC is bits 5-7
            src = value & 0x1
            self.clk_sys_selected = 1 << src

        elif offset == self.CLK_PERI_CTRL:
            self.regs[offset] = value
            if value & (1 << 11):  # ENABLE bit
                self.clk_peri_selected = 1 << ((value >> 5) & 0x7)

        elif offset == self.CLK_USB_CTRL:
            self.regs[offset] = value
            if value & (1 << 11):
                self.clk_usb_selected = 1 << ((value >> 5) & 0x7)

        elif offset == self.CLK_ADC_CTRL:
            self.regs[offset] = value
            if value & (1 << 11):
                self.clk_adc_selected = 1 << ((value >> 5) & 0x7)

        elif offset == self.CLK_RTC_CTRL:
            self.regs[offset] = value
            if value & (1 << 11):
                self.clk_rtc_selected = 1 << ((value >> 5) & 0x7)

        elif offset == self.INTE:
            self.inte = value
        elif offset == self.INTF:
            self.intf = value
        elif offset == self.INTR:
            self.intr &= ~value

        else:
            self.regs[offset] = value


# =============================================================================
# PSM - 0x40010000
# =============================================================================

class RP2040PSM(RP2040Peripheral):
    """
    RP2040 Power-on State Machine.

    Controls power sequencing during startup.

    Register Map:
        0x00: FRCE_ON   - Force block on
        0x04: FRCE_OFF  - Force block off
        0x08: WDSEL     - Watchdog select
        0x0C: DONE      - Power-up done status
    """

    FRCE_ON = 0x00
    FRCE_OFF = 0x04
    WDSEL = 0x08
    DONE = 0x0C

    # Power domain bits
    PSM_PROC1 = 1 << 16
    PSM_PROC0 = 1 << 15
    PSM_SIO = 1 << 14
    PSM_VREG_AND_CHIP_RESET = 1 << 13
    PSM_XIP = 1 << 12
    PSM_SRAM5 = 1 << 11
    PSM_SRAM4 = 1 << 10
    PSM_SRAM3 = 1 << 9
    PSM_SRAM2 = 1 << 8
    PSM_SRAM1 = 1 << 7
    PSM_SRAM0 = 1 << 6
    PSM_ROM = 1 << 5
    PSM_BUSFABRIC = 1 << 4
    PSM_RESETS = 1 << 3
    PSM_CLOCKS = 1 << 2
    PSM_XOSC = 1 << 1
    PSM_ROSC = 1 << 0

    ALL_DOMAINS = 0x1FFFF

    def __init__(self, base: int = 0x40010000):
        super().__init__("PSM", base, 0x100)

        self.frce_on = 0
        self.frce_off = 0
        self.wdsel = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.FRCE_ON:
            return self.frce_on

        elif offset == self.FRCE_OFF:
            return self.frce_off

        elif offset == self.WDSEL:
            return self.wdsel

        elif offset == self.DONE:
            # All power domains done (powered up)
            return self.ALL_DOMAINS

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.FRCE_ON:
            self.frce_on = value & self.ALL_DOMAINS

        elif offset == self.FRCE_OFF:
            self.frce_off = value & self.ALL_DOMAINS

        elif offset == self.WDSEL:
            self.wdsel = value & self.ALL_DOMAINS

        else:
            self.regs[offset] = value


# =============================================================================
# WATCHDOG - 0x40058000
# =============================================================================

class RP2040WATCHDOG(RP2040Peripheral):
    """
    RP2040 Watchdog Timer.

    System watchdog with support for bootloader scratch registers.
    Also provides TICK register for clk_tick generation.

    Register Map:
        0x00: CTRL      - Control
        0x04: LOAD      - Load value
        0x08: REASON    - Reset reason
        0x0C: SCRATCH0-7 - Scratch registers (8 x 4 bytes)
        0x2C: TICK      - Tick generator control
    """

    CTRL = 0x00
    LOAD = 0x04
    REASON = 0x08
    SCRATCH0 = 0x0C
    SCRATCH1 = 0x10
    SCRATCH2 = 0x14
    SCRATCH3 = 0x18
    SCRATCH4 = 0x1C
    SCRATCH5 = 0x20
    SCRATCH6 = 0x24
    SCRATCH7 = 0x28
    TICK = 0x2C

    # CTRL bits
    CTRL_TRIGGER = 1 << 31
    CTRL_ENABLE = 1 << 30
    CTRL_PAUSE_DBG1 = 1 << 26
    CTRL_PAUSE_DBG0 = 1 << 25
    CTRL_PAUSE_JTAG = 1 << 24
    CTRL_TIME_MASK = 0xFFFFFF

    # TICK bits
    TICK_COUNT_MASK = 0x1FF << 11
    TICK_RUNNING = 1 << 10
    TICK_ENABLE = 1 << 9
    TICK_CYCLES_MASK = 0x1FF

    def __init__(self, base: int = 0x40058000):
        super().__init__("WATCHDOG", base, 0x100)

        self.ctrl = 0x07000000  # All pause bits set
        self.load = 0
        self.reason = 0
        self.scratch = [0] * 8
        self.tick = 0

        # Countdown timer
        self.counter = 0

        # System reset callback (called when watchdog triggers reset)
        self.on_system_reset: Optional[Callable[[str], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CTRL:
            return (self.ctrl & ~self.CTRL_TIME_MASK) | (self.counter & self.CTRL_TIME_MASK)

        elif offset == self.LOAD:
            return self.load

        elif offset == self.REASON:
            return self.reason

        elif self.SCRATCH0 <= offset <= self.SCRATCH7:
            idx = (offset - self.SCRATCH0) // 4
            return self.scratch[idx]

        elif offset == self.TICK:
            tick = self.tick
            if tick & self.TICK_ENABLE:
                tick |= self.TICK_RUNNING
            return tick

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CTRL:
            self.ctrl = value
            if value & self.CTRL_TRIGGER:
                self.log.warning("Watchdog triggered - system reset")
                self.reason = 1  # Watchdog reset
                if self.on_system_reset:
                    self.on_system_reset("WATCHDOG")

        elif offset == self.LOAD:
            self.load = value & self.CTRL_TIME_MASK
            self.counter = self.load

        elif self.SCRATCH0 <= offset <= self.SCRATCH7:
            idx = (offset - self.SCRATCH0) // 4
            self.scratch[idx] = value

        elif offset == self.TICK:
            self.tick = value & (self.TICK_ENABLE | self.TICK_CYCLES_MASK)

        else:
            self.regs[offset] = value
