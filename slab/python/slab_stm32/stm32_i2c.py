"""
STM32 I2C Peripheral Emulation

Implements:
- I2Cv1 (F1/F4): Standard I2C
- I2Cv2 (L4/H7): Enhanced I2C with timing register

References:
- RM0090 (STM32F4xx) Section 27
- RM0351 (STM32L4xx) Section 39

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from collections import deque
from .stm32_base import STM32Peripheral, STATUS_OK


class STM32I2Cv1(STM32Peripheral):
    """
    STM32F1/F4 I2C peripheral.

    Register Map:
        0x00: CR1    - Control register 1
        0x04: CR2    - Control register 2
        0x08: OAR1   - Own address register 1
        0x0C: OAR2   - Own address register 2
        0x10: DR     - Data register
        0x14: SR1    - Status register 1
        0x18: SR2    - Status register 2
        0x1C: CCR    - Clock control register
        0x20: TRISE  - Rise time register
        0x24: FLTR   - Digital filter (F4 only)
    """

    # Register offsets
    CR1 = 0x00
    CR2 = 0x04
    OAR1 = 0x08
    OAR2 = 0x0C
    DR = 0x10
    SR1 = 0x14
    SR2 = 0x18
    CCR = 0x1C
    TRISE = 0x20
    FLTR = 0x24

    # CR1 bits
    CR1_PE = 1 << 0        # Peripheral enable
    CR1_SMBUS = 1 << 1     # SMBus mode
    CR1_SMBTYPE = 1 << 3   # SMBus type
    CR1_ENARP = 1 << 4     # ARP enable
    CR1_ENPEC = 1 << 5     # PEC enable
    CR1_ENGC = 1 << 6      # General call enable
    CR1_NOSTRETCH = 1 << 7 # Clock stretching disable
    CR1_START = 1 << 8     # Start generation
    CR1_STOP = 1 << 9      # Stop generation
    CR1_ACK = 1 << 10      # Acknowledge enable
    CR1_POS = 1 << 11      # ACK/PEC position
    CR1_PEC = 1 << 12      # Packet error checking
    CR1_ALERT = 1 << 13    # SMBus alert
    CR1_SWRST = 1 << 15    # Software reset

    # SR1 bits
    SR1_SB = 1 << 0        # Start bit
    SR1_ADDR = 1 << 1      # Address sent/matched
    SR1_BTF = 1 << 2       # Byte transfer finished
    SR1_ADD10 = 1 << 3     # 10-bit header sent
    SR1_STOPF = 1 << 4     # Stop detection
    SR1_RXNE = 1 << 6      # Data register not empty
    SR1_TXE = 1 << 7       # Data register empty
    SR1_BERR = 1 << 8      # Bus error
    SR1_ARLO = 1 << 9      # Arbitration lost
    SR1_AF = 1 << 10       # Acknowledge failure
    SR1_OVR = 1 << 11      # Overrun/underrun
    SR1_PECERR = 1 << 12   # PEC error
    SR1_TIMEOUT = 1 << 14  # Timeout
    SR1_SMBALERT = 1 << 15 # SMBus alert

    # SR2 bits
    SR2_MSL = 1 << 0       # Master/slave
    SR2_BUSY = 1 << 1      # Bus busy
    SR2_TRA = 1 << 2       # Transmitter/receiver
    SR2_GENCALL = 1 << 4   # General call address
    SR2_SMBDEFAULT = 1 << 5
    SR2_SMBHOST = 1 << 6
    SR2_DUALF = 1 << 7

    I2C_BASES = {
        1: 0x40005400,
        2: 0x40005800,
        3: 0x40005C00,
    }

    I2C_IRQS = {
        1: (31, 32),  # I2C1_EV, I2C1_ER
        2: (33, 34),
        3: (72, 73),
    }

    def __init__(self, index: int = 1, base: int = None):
        if base is None:
            base = self.I2C_BASES.get(index, 0x40005400)

        irqs = self.I2C_IRQS.get(index, (31, 32))
        super().__init__(f"I2C{index}", base, 0x400, irqs[0])
        self.index = index
        self.irq_ev = irqs[0]
        self.irq_er = irqs[1]

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.oar1 = 0
        self.oar2 = 0
        self.dr = 0
        self.sr1 = 0
        self.sr2 = 0
        self.ccr = 0
        self.trise = 0x0002
        self.fltr = 0

        # Transfer state
        self.state = 'IDLE'
        self.slave_addr = 0
        self.tx_data: List[int] = []
        self.rx_data: deque = deque(maxlen=256)

        # Device callbacks
        self.on_start: Optional[Callable[[int, bool], None]] = None
        self.on_write: Optional[Callable[[int], None]] = None
        self.on_read: Optional[Callable[[], int]] = None
        self.on_stop: Optional[Callable[[], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.OAR1:
            return self.oar1
        elif offset == self.OAR2:
            return self.oar2
        elif offset == self.DR:
            return self._read_dr()
        elif offset == self.SR1:
            return self._get_sr1()
        elif offset == self.SR2:
            return self._get_sr2()
        elif offset == self.CCR:
            return self.ccr
        elif offset == self.TRISE:
            return self.trise
        elif offset == self.FLTR:
            return self.fltr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            self._write_cr1(value)
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.OAR1:
            self.oar1 = value
        elif offset == self.OAR2:
            self.oar2 = value
        elif offset == self.DR:
            self._write_dr(value)
        elif offset == self.CCR:
            self.ccr = value
        elif offset == self.TRISE:
            self.trise = value
        elif offset == self.FLTR:
            self.fltr = value

    def _write_cr1(self, value: int):
        old_cr1 = self.cr1
        self.cr1 = value

        # Software reset
        if value & self.CR1_SWRST:
            self._reset_registers()
            return

        # Start condition
        if (value & self.CR1_START) and not (old_cr1 & self.CR1_START):
            self._generate_start()

        # Stop condition
        if (value & self.CR1_STOP) and not (old_cr1 & self.CR1_STOP):
            self._generate_stop()

    def _generate_start(self):
        """Generate START condition."""
        self.state = 'START'
        self.sr1 |= self.SR1_SB
        self.sr2 |= self.SR2_MSL | self.SR2_BUSY
        self.cr1 &= ~self.CR1_START
        self._check_interrupt()

    def _generate_stop(self):
        """Generate STOP condition."""
        self.state = 'IDLE'
        self.sr1 |= self.SR1_STOPF
        self.sr2 &= ~(self.SR2_MSL | self.SR2_TRA)
        self.cr1 &= ~self.CR1_STOP

        if self.on_stop:
            self.on_stop()

    def _read_dr(self) -> int:
        """Read data register."""
        self.sr1 &= ~self.SR1_RXNE
        if self.rx_data:
            return self.rx_data.popleft()
        return 0

    def _write_dr(self, value: int):
        """Write data register."""
        data = value & 0xFF

        if self.state == 'START':
            # Address phase
            self.slave_addr = data >> 1
            is_read = bool(data & 1)
            self.sr1 |= self.SR1_ADDR

            if is_read:
                self.sr2 &= ~self.SR2_TRA
            else:
                self.sr2 |= self.SR2_TRA

            if self.on_start:
                self.on_start(self.slave_addr, is_read)

            self.state = 'DATA'
            self.sr1 &= ~self.SR1_SB

        elif self.state == 'DATA':
            # Data phase
            if self.sr2 & self.SR2_TRA:  # Transmitter
                if self.on_write:
                    self.on_write(data)
                self.sr1 |= self.SR1_BTF | self.SR1_TXE
            else:  # Receiver
                if self.on_read:
                    rx = self.on_read()
                    self.rx_data.append(rx)
                    self.sr1 |= self.SR1_RXNE

        self._check_interrupt()

    def _get_sr1(self) -> int:
        sr1 = self.sr1
        if self.state == 'DATA' and (self.sr2 & self.SR2_TRA):
            sr1 |= self.SR1_TXE
        return sr1

    def _get_sr2(self) -> int:
        # Reading SR2 clears ADDR flag
        sr2 = self.sr2
        self.sr1 &= ~self.SR1_ADDR
        return sr2

    def _check_interrupt(self):
        """Check and trigger interrupts."""
        if self.sr1 & (self.SR1_SB | self.SR1_ADDR | self.SR1_BTF | self.SR1_RXNE | self.SR1_TXE):
            if self.cr2 & (1 << 9):  # ITEVTEN
                self.trigger_irq(1)

    def _reset_registers(self):
        self.cr1 = 0
        self.sr1 = 0
        self.sr2 = 0
        self.state = 'IDLE'
        self.rx_data.clear()


class STM32I2Cv2(STM32Peripheral):
    """
    STM32L4/H7 I2C peripheral with TIMINGR.

    Enhanced features:
    - Programmable timing register
    - 10-bit addressing
    - SMBus 3.0 support
    - Wakeup from Stop mode
    """

    # Register offsets
    CR1 = 0x00
    CR2 = 0x04
    OAR1 = 0x08
    OAR2 = 0x0C
    TIMINGR = 0x10
    TIMEOUTR = 0x14
    ISR = 0x18
    ICR = 0x1C
    PECR = 0x20
    RXDR = 0x24
    TXDR = 0x28

    # CR1 bits
    CR1_PE = 1 << 0
    CR1_TXIE = 1 << 1
    CR1_RXIE = 1 << 2
    CR1_ADDRIE = 1 << 3
    CR1_NACKIE = 1 << 4
    CR1_STOPIE = 1 << 5
    CR1_TCIE = 1 << 6
    CR1_ERRIE = 1 << 7

    # CR2 bits
    CR2_SADD_MASK = 0x3FF
    CR2_RD_WRN = 1 << 10
    CR2_ADD10 = 1 << 11
    CR2_HEAD10R = 1 << 12
    CR2_START = 1 << 13
    CR2_STOP = 1 << 14
    CR2_NACK = 1 << 15
    CR2_NBYTES_MASK = 0xFF << 16
    CR2_RELOAD = 1 << 24
    CR2_AUTOEND = 1 << 25

    # ISR bits
    ISR_TXE = 1 << 0
    ISR_TXIS = 1 << 1
    ISR_RXNE = 1 << 2
    ISR_ADDR = 1 << 3
    ISR_NACKF = 1 << 4
    ISR_STOPF = 1 << 5
    ISR_TC = 1 << 6
    ISR_TCR = 1 << 7
    ISR_BERR = 1 << 8
    ISR_ARLO = 1 << 9
    ISR_OVR = 1 << 10
    ISR_PECERR = 1 << 11
    ISR_TIMEOUT = 1 << 12
    ISR_ALERT = 1 << 13
    ISR_BUSY = 1 << 15
    ISR_DIR = 1 << 16

    I2C_BASES_L4 = {
        1: 0x40005400,
        2: 0x40005800,
        3: 0x40005C00,
    }

    def __init__(self, index: int = 1, base: int = None, family: str = "L4"):
        if base is None:
            base = self.I2C_BASES_L4.get(index, 0x40005400)

        super().__init__(f"I2C{index}", base, 0x400, 31 + (index - 1) * 2)
        self.index = index
        self.family = family

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.oar1 = 0
        self.oar2 = 0
        self.timingr = 0
        self.timeoutr = 0
        self.isr = self.ISR_TXE
        self.pecr = 0

        # Data
        self.rx_data: deque = deque(maxlen=256)
        self.tx_byte_count = 0

        # Callbacks
        self.on_start: Optional[Callable[[int, bool], None]] = None
        self.on_write: Optional[Callable[[int], None]] = None
        self.on_read: Optional[Callable[[], int]] = None
        self.on_stop: Optional[Callable[[], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.OAR1:
            return self.oar1
        elif offset == self.OAR2:
            return self.oar2
        elif offset == self.TIMINGR:
            return self.timingr
        elif offset == self.ISR:
            return self._get_isr()
        elif offset == self.RXDR:
            return self._read_rxdr()
        elif offset == self.PECR:
            return self.pecr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            self.cr1 = value
        elif offset == self.CR2:
            self._write_cr2(value)
        elif offset == self.OAR1:
            self.oar1 = value
        elif offset == self.OAR2:
            self.oar2 = value
        elif offset == self.TIMINGR:
            self.timingr = value
        elif offset == self.TIMEOUTR:
            self.timeoutr = value
        elif offset == self.ICR:
            self._clear_flags(value)
        elif offset == self.TXDR:
            self._write_txdr(value)

    def _write_cr2(self, value: int):
        self.cr2 = value

        if value & self.CR2_START:
            self._generate_start()

        if value & self.CR2_STOP:
            self._generate_stop()

    def _generate_start(self):
        addr = self.cr2 & self.CR2_SADD_MASK
        is_read = bool(self.cr2 & self.CR2_RD_WRN)
        nbytes = (self.cr2 >> 16) & 0xFF

        self.tx_byte_count = nbytes
        self.isr |= self.ISR_BUSY

        if is_read:
            self.isr |= self.ISR_DIR
        else:
            self.isr &= ~self.ISR_DIR
            self.isr |= self.ISR_TXIS

        if self.on_start:
            self.on_start(addr >> 1, is_read)

        self.cr2 &= ~self.CR2_START

    def _generate_stop(self):
        self.isr &= ~self.ISR_BUSY
        self.isr |= self.ISR_STOPF

        if self.on_stop:
            self.on_stop()

        self.cr2 &= ~self.CR2_STOP

    def _get_isr(self) -> int:
        isr = self.isr
        if self.rx_data:
            isr |= self.ISR_RXNE
        return isr

    def _read_rxdr(self) -> int:
        self.isr &= ~self.ISR_RXNE
        if self.rx_data:
            return self.rx_data.popleft()
        return 0

    def _write_txdr(self, value: int):
        data = value & 0xFF
        self.isr &= ~self.ISR_TXE

        if self.on_write:
            self.on_write(data)

        self.tx_byte_count -= 1
        if self.tx_byte_count <= 0:
            self.isr |= self.ISR_TC
        else:
            self.isr |= self.ISR_TXIS | self.ISR_TXE

    def _clear_flags(self, value: int):
        clear_mask = value & 0x3F38
        self.isr &= ~clear_mask

    def receive_byte(self, data: int):
        """Receive a byte from slave."""
        if len(self.rx_data) < 256:
            self.rx_data.append(data & 0xFF)
            self.isr |= self.ISR_RXNE

    def _reset_registers(self):
        self.cr1 = 0
        self.cr2 = 0
        self.isr = self.ISR_TXE
        self.rx_data.clear()
