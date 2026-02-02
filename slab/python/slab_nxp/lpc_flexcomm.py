"""
LPC FlexComm - Flexible Serial Communication Interface

FlexComm is NXP's unified serial peripheral that can be configured as:
- USART
- SPI
- I2C
- I2S (audio)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List
from collections import deque
from .nxp_base import NXPPeripheral


class LPCFlexComm(NXPPeripheral):
    """
    LPC FlexComm base peripheral.

    Register Map (common):
        0xFFC: PSELID - Peripheral select/ID
    """

    PSELID = 0xFFC

    # PSELID values
    PSEL_USART = 1
    PSEL_SPI = 2
    PSEL_I2C = 3
    PSEL_I2S = 4

    FLEXCOMM_BASES = {
        0: 0x40086000,
        1: 0x40087000,
        2: 0x40088000,
        3: 0x40089000,
        4: 0x4008A000,
        5: 0x40096000,
        6: 0x40097000,
        7: 0x40098000,
        8: 0x4009F000,  # High-speed
    }

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = self.FLEXCOMM_BASES.get(index, 0x40086000)

        super().__init__(f"FLEXCOMM{index}", base, 0x1000, irq=14 + index)
        self.index = index
        self.pselid = 0  # Not configured

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.PSELID:
            return self.pselid
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.PSELID:
            # Lock on first write
            if self.pselid == 0:
                self.pselid = value & 0x7


class LPCFlexCommUSART(NXPPeripheral):
    """
    LPC FlexComm USART function.

    Register Map:
        0x000: CFG       - Configuration
        0x004: CTL       - Control
        0x008: STAT      - Status
        0x00C: INTENSET  - Interrupt enable set
        0x010: INTENCLR  - Interrupt enable clear
        0x01C: BRG       - Baud rate generator
        0x020: INTSTAT   - Interrupt status
        0x024: OSR       - Oversampling
        0x028: ADDR      - Address (RS-485)
        0x030: FIFOCFG   - FIFO configuration
        0x034: FIFOSTAT  - FIFO status
        0x038: FIFOTRIG  - FIFO trigger settings
        0x040: FIFOINTENSET
        0x044: FIFOINTENCLR
        0x048: FIFOINTSTAT
        0x0E0: FIFOWR    - FIFO write (TX)
        0x0E4: FIFORD    - FIFO read (RX)
        0x0E8: FIFORDNOPOP - FIFO read without pop
    """

    CFG = 0x000
    CTL = 0x004
    STAT = 0x008
    INTENSET = 0x00C
    INTENCLR = 0x010
    BRG = 0x01C
    INTSTAT = 0x020
    OSR = 0x024
    FIFOCFG = 0x030
    FIFOSTAT = 0x034
    FIFOTRIG = 0x038
    FIFOINTENSET = 0x040
    FIFOINTENCLR = 0x044
    FIFOINTSTAT = 0x048
    FIFOWR = 0x0E0
    FIFORD = 0x0E4
    FIFORDNOPOP = 0x0E8

    # CFG bits
    CFG_ENABLE = 1 << 0
    CFG_DATALEN = 0x3 << 2  # 00=7bit, 01=8bit, 10=9bit
    CFG_PARITY = 0x3 << 4   # 00=none, 10=even, 11=odd
    CFG_STOPLEN = 1 << 6    # 0=1 stop, 1=2 stop
    CFG_MODE32K = 1 << 7
    CFG_LINMODE = 1 << 8
    CFG_CTSEN = 1 << 9
    CFG_SYNCEN = 1 << 11
    CFG_CLKPOL = 1 << 12
    CFG_SYNCMST = 1 << 14
    CFG_LOOP = 1 << 15

    # STAT bits
    STAT_RXIDLE = 1 << 1
    STAT_TXIDLE = 1 << 3
    STAT_CTS = 1 << 4
    STAT_TXDISSTAT = 1 << 6
    STAT_RXBRK = 1 << 10
    STAT_START = 1 << 12
    STAT_FRAMERRINT = 1 << 13
    STAT_PARITYERRINT = 1 << 14
    STAT_RXNOISEINT = 1 << 15
    STAT_ABERR = 1 << 16

    # FIFOSTAT bits
    FIFOSTAT_TXERR = 1 << 0
    FIFOSTAT_RXERR = 1 << 1
    FIFOSTAT_PERINT = 1 << 3
    FIFOSTAT_TXEMPTY = 1 << 4
    FIFOSTAT_TXNOTFULL = 1 << 5
    FIFOSTAT_RXNOTEMPTY = 1 << 6
    FIFOSTAT_RXFULL = 1 << 7
    FIFOSTAT_TXLVL = 0x1F << 8
    FIFOSTAT_RXLVL = 0x1F << 16

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = LPCFlexComm.FLEXCOMM_BASES.get(index, 0x40086000)

        super().__init__(f"USART{index}", base, 0x1000, irq=14 + index)
        self.index = index

        self.cfg = 0
        self.ctl = 0
        self.stat = self.STAT_TXIDLE | self.STAT_RXIDLE
        self.intenset = 0
        self.brg = 0
        self.osr = 0xF  # 16x oversampling
        self.fifocfg = 0
        self.fifostat = self.FIFOSTAT_TXEMPTY | self.FIFOSTAT_TXNOTFULL
        self.fifotrig = 0
        self.fifointenset = 0

        self.tx_fifo: deque = deque(maxlen=16)
        self.rx_fifo: deque = deque(maxlen=16)

        self.on_tx: Optional[Callable[[bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CFG:
            return self.cfg
        elif offset == self.CTL:
            return self.ctl
        elif offset == self.STAT:
            return self.stat
        elif offset == self.INTENSET:
            return self.intenset
        elif offset == self.BRG:
            return self.brg
        elif offset == self.INTSTAT:
            return self._get_intstat()
        elif offset == self.OSR:
            return self.osr
        elif offset == self.FIFOCFG:
            return self.fifocfg
        elif offset == self.FIFOSTAT:
            return self._get_fifostat()
        elif offset == self.FIFOTRIG:
            return self.fifotrig
        elif offset == self.FIFOINTENSET:
            return self.fifointenset
        elif offset == self.FIFOINTSTAT:
            return self._get_fifointstat()
        elif offset == self.FIFORD or offset == self.FIFORDNOPOP:
            return self._read_fifo(offset == self.FIFORDNOPOP)
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CFG:
            self.cfg = value
        elif offset == self.CTL:
            self.ctl = value
        elif offset == self.STAT:
            # Write 1 to clear some bits
            self.stat &= ~(value & 0x1F400)
        elif offset == self.INTENSET:
            self.intenset |= value
        elif offset == self.INTENCLR:
            self.intenset &= ~value
        elif offset == self.BRG:
            self.brg = value & 0xFFFF
        elif offset == self.OSR:
            self.osr = value & 0xF
        elif offset == self.FIFOCFG:
            self.fifocfg = value
        elif offset == self.FIFOTRIG:
            self.fifotrig = value
        elif offset == self.FIFOINTENSET:
            self.fifointenset |= value
        elif offset == self.FIFOINTENCLR:
            self.fifointenset &= ~value
        elif offset == self.FIFOWR:
            self._write_fifo(value)

    def _get_intstat(self) -> int:
        return self.stat & self.intenset

    def _get_fifostat(self) -> int:
        stat = self.fifostat & ~(self.FIFOSTAT_TXLVL | self.FIFOSTAT_RXLVL)

        # TX FIFO status
        if len(self.tx_fifo) == 0:
            stat |= self.FIFOSTAT_TXEMPTY
        if len(self.tx_fifo) < 16:
            stat |= self.FIFOSTAT_TXNOTFULL
        stat |= (len(self.tx_fifo) & 0x1F) << 8

        # RX FIFO status
        if len(self.rx_fifo) > 0:
            stat |= self.FIFOSTAT_RXNOTEMPTY
        if len(self.rx_fifo) >= 16:
            stat |= self.FIFOSTAT_RXFULL
        stat |= (len(self.rx_fifo) & 0x1F) << 16

        return stat

    def _get_fifointstat(self) -> int:
        stat = 0
        fifostat = self._get_fifostat()

        if fifostat & self.FIFOSTAT_TXNOTFULL:
            stat |= 1 << 0  # TXLVL
        if fifostat & self.FIFOSTAT_RXNOTEMPTY:
            stat |= 1 << 1  # RXLVL

        return stat & self.fifointenset

    def _write_fifo(self, value: int):
        """Write to TX FIFO."""
        if not (self.cfg & self.CFG_ENABLE):
            return

        data = value & 0x1FF  # 9-bit max
        self.tx_fifo.append(data)

        # Transmit immediately
        if self.on_tx:
            self.on_tx(bytes([data & 0xFF]))
            self.tx_fifo.clear()

    def _read_fifo(self, nopop: bool) -> int:
        """Read from RX FIFO."""
        if len(self.rx_fifo) == 0:
            return 0

        if nopop:
            return self.rx_fifo[0]
        return self.rx_fifo.popleft()

    def receive_byte(self, byte: int):
        """Receive a byte from external source."""
        if len(self.rx_fifo) < 16:
            self.rx_fifo.append(byte & 0xFF)
            self._check_rx_interrupt()

    def _check_rx_interrupt(self):
        if self._get_fifointstat():
            self.trigger_irq(1)


class LPCFlexCommSPI(NXPPeripheral):
    """
    LPC FlexComm SPI function.

    Register Map:
        0x400: CFG
        0x404: DLY       - Delay configuration
        0x408: STAT
        0x40C: INTENSET
        0x410: INTENCLR
        0x424: DIV       - Clock divider
        0x428: INTSTAT
        0x430: FIFOCFG
        0x434: FIFOSTAT
        0x438: FIFOTRIG
        0x440: FIFOINTENSET
        0x4E0: FIFOWR
        0x4E4: FIFORD
    """

    CFG = 0x400
    DLY = 0x404
    STAT = 0x408
    INTENSET = 0x40C
    INTENCLR = 0x410
    DIV = 0x424
    INTSTAT = 0x428
    FIFOCFG = 0x430
    FIFOSTAT = 0x434
    FIFOTRIG = 0x438
    FIFOINTENSET = 0x440
    FIFOINTENCLR = 0x444
    FIFOWR = 0x4E0
    FIFORD = 0x4E4

    # CFG bits
    CFG_ENABLE = 1 << 0
    CFG_MASTER = 1 << 2
    CFG_LSBF = 1 << 3
    CFG_CPHA = 1 << 4
    CFG_CPOL = 1 << 5
    CFG_LOOP = 1 << 7
    CFG_SPOL0 = 1 << 8
    CFG_SPOL1 = 1 << 9
    CFG_SPOL2 = 1 << 10
    CFG_SPOL3 = 1 << 11

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = LPCFlexComm.FLEXCOMM_BASES.get(index, 0x40086000)

        super().__init__(f"SPI{index}", base, 0x1000, irq=14 + index)
        self.index = index

        self.cfg = 0
        self.dly = 0
        self.stat = 0
        self.intenset = 0
        self.div = 0
        self.fifocfg = 0
        self.fifostat = 0x30  # TX empty/not full
        self.fifotrig = 0
        self.fifointenset = 0

        self.tx_fifo: deque = deque(maxlen=8)
        self.rx_fifo: deque = deque(maxlen=8)

        self.on_transfer: Optional[Callable[[bytes], bytes]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.CFG: self.cfg,
            self.DLY: self.dly,
            self.STAT: self.stat,
            self.INTENSET: self.intenset,
            self.DIV: self.div,
            self.FIFOCFG: self.fifocfg,
            self.FIFOSTAT: self._get_fifostat(),
            self.FIFOTRIG: self.fifotrig,
            self.FIFOINTENSET: self.fifointenset,
        }
        if offset in regs:
            return regs[offset]
        elif offset == self.FIFORD:
            return self.rx_fifo.popleft() if self.rx_fifo else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CFG:
            self.cfg = value
        elif offset == self.DLY:
            self.dly = value
        elif offset == self.INTENSET:
            self.intenset |= value
        elif offset == self.INTENCLR:
            self.intenset &= ~value
        elif offset == self.DIV:
            self.div = value & 0xFFFF
        elif offset == self.FIFOCFG:
            self.fifocfg = value
        elif offset == self.FIFOTRIG:
            self.fifotrig = value
        elif offset == self.FIFOINTENSET:
            self.fifointenset |= value
        elif offset == self.FIFOINTENCLR:
            self.fifointenset &= ~value
        elif offset == self.FIFOWR:
            self._write_fifo(value)

    def _get_fifostat(self) -> int:
        stat = 0x30  # TX empty/not full
        if self.rx_fifo:
            stat |= 0x40  # RX not empty
        stat |= (len(self.tx_fifo) & 0x1F) << 8
        stat |= (len(self.rx_fifo) & 0x1F) << 16
        return stat

    def _write_fifo(self, value: int):
        """Write to TX FIFO and perform transfer."""
        if not (self.cfg & self.CFG_ENABLE):
            return

        # Extract data and control
        data = value & 0xFFFF
        ctrl = value >> 16

        length = ((ctrl >> 8) & 0xF) + 1  # LEN field
        if length > 2:
            length = 2  # Max 16-bit for simplicity

        tx_data = data.to_bytes(length, 'little' if self.cfg & self.CFG_LSBF else 'big')

        if self.on_transfer:
            rx_data = self.on_transfer(tx_data)
            if rx_data:
                for b in rx_data:
                    if len(self.rx_fifo) < 8:
                        self.rx_fifo.append(b)


class LPCFlexCommI2C(NXPPeripheral):
    """
    LPC FlexComm I2C function.

    Register Map:
        0x800: CFG
        0x804: STAT
        0x808: INTENSET
        0x80C: INTENCLR
        0x810: TIMEOUT
        0x814: CLKDIV
        0x818: INTSTAT
        0x820: MSTCTL      - Master control
        0x824: MSTTIME     - Master timing
        0x828: MSTDAT      - Master data
        0x840: SLVCTL      - Slave control
        0x844: SLVDAT      - Slave data
        0x848: SLVADR0-3   - Slave addresses
        0x858: SLVQUAL0    - Slave address qualifier
    """

    CFG = 0x800
    STAT = 0x804
    INTENSET = 0x808
    INTENCLR = 0x80C
    TIMEOUT = 0x810
    CLKDIV = 0x814
    INTSTAT = 0x818
    MSTCTL = 0x820
    MSTTIME = 0x824
    MSTDAT = 0x828
    SLVCTL = 0x840
    SLVDAT = 0x844
    SLVADR0 = 0x848

    # CFG bits
    CFG_MSTEN = 1 << 0
    CFG_SLVEN = 1 << 1
    CFG_MONEN = 1 << 2
    CFG_TIMEOUT = 1 << 3
    CFG_MONCLKSTR = 1 << 4
    CFG_HSCAPABLE = 1 << 5

    # STAT bits
    STAT_MSTPENDING = 1 << 0
    STAT_MSTSTATE = 0x7 << 1
    STAT_MSTARBLOSS = 1 << 4
    STAT_MSTSTSTPERR = 1 << 6
    STAT_SLVPENDING = 1 << 8
    STAT_SLVSTATE = 0x3 << 9
    STAT_SLVNOTSTR = 1 << 11
    STAT_SLVIDX = 0x3 << 12
    STAT_SLVSEL = 1 << 14
    STAT_SLVDESEL = 1 << 15
    STAT_MONRDY = 1 << 16
    STAT_MONOV = 1 << 17
    STAT_MONACTIVE = 1 << 18
    STAT_MONIDLE = 1 << 19
    STAT_EVENTTIMEOUT = 1 << 24
    STAT_SCLTIMEOUT = 1 << 25

    # Master states
    MSTSTATE_IDLE = 0
    MSTSTATE_RXRDY = 1
    MSTSTATE_TXRDY = 2
    MSTSTATE_NACKADDR = 3
    MSTSTATE_NACKDATA = 4

    def __init__(self, index: int = 0, base: int = None):
        if base is None:
            base = LPCFlexComm.FLEXCOMM_BASES.get(index, 0x40086000)

        super().__init__(f"I2C{index}", base, 0x1000, irq=14 + index)
        self.index = index

        self.cfg = 0
        self.stat = self.STAT_MSTPENDING | (self.MSTSTATE_IDLE << 1)
        self.intenset = 0
        self.timeout = 0xFFFF
        self.clkdiv = 0
        self.mstctl = 0
        self.msttime = 0
        self.mstdat = 0
        self.slvctl = 0
        self.slvdat = 0
        self.slvadr = [0, 0, 0, 0]

        self.on_transfer: Optional[Callable[[int, bytes, bool], bytes]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        regs = {
            self.CFG: self.cfg,
            self.STAT: self.stat,
            self.INTENSET: self.intenset,
            self.TIMEOUT: self.timeout,
            self.CLKDIV: self.clkdiv,
            self.INTSTAT: self.stat & self.intenset,
            self.MSTCTL: self.mstctl,
            self.MSTTIME: self.msttime,
            self.MSTDAT: self.mstdat,
            self.SLVCTL: self.slvctl,
            self.SLVDAT: self.slvdat,
        }
        if offset in regs:
            return regs[offset]
        elif self.SLVADR0 <= offset < self.SLVADR0 + 16:
            idx = (offset - self.SLVADR0) // 4
            return self.slvadr[idx] if idx < 4 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CFG:
            self.cfg = value
        elif offset == self.STAT:
            # Write 1 to clear
            self.stat &= ~(value & 0x03000070)
        elif offset == self.INTENSET:
            self.intenset |= value
        elif offset == self.INTENCLR:
            self.intenset &= ~value
        elif offset == self.TIMEOUT:
            self.timeout = value
        elif offset == self.CLKDIV:
            self.clkdiv = value & 0xFFFF
        elif offset == self.MSTCTL:
            self._handle_mstctl(value)
        elif offset == self.MSTTIME:
            self.msttime = value
        elif offset == self.MSTDAT:
            self.mstdat = value & 0xFF
        elif offset == self.SLVCTL:
            self.slvctl = value
        elif offset == self.SLVDAT:
            self.slvdat = value & 0xFF
        elif self.SLVADR0 <= offset < self.SLVADR0 + 16:
            idx = (offset - self.SLVADR0) // 4
            if idx < 4:
                self.slvadr[idx] = value

    def _handle_mstctl(self, value: int):
        self.mstctl = value

        if value & 0x01:  # MSTCONTINUE
            pass  # Continue transfer
        if value & 0x02:  # MSTSTART
            # Start transfer - address in MSTDAT
            addr = self.mstdat >> 1
            is_read = self.mstdat & 1

            if self.on_transfer:
                if is_read:
                    rx_data = self.on_transfer(addr, b'', True)
                    if rx_data:
                        self.mstdat = rx_data[0]
                    self.stat = self.STAT_MSTPENDING | (self.MSTSTATE_RXRDY << 1)
                else:
                    self.stat = self.STAT_MSTPENDING | (self.MSTSTATE_TXRDY << 1)
        if value & 0x04:  # MSTSTOP
            self.stat = self.STAT_MSTPENDING | (self.MSTSTATE_IDLE << 1)
