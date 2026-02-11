"""
STM32 USART/UART Peripheral Emulation

Implements two USART architectures:
- USARTv1 (F1/F4): SR/DR based
- USARTv2 (L4/H7): ISR/RDR/TDR based with FIFO

References:
- RM0008 (STM32F1xx)
- RM0090 (STM32F4xx)
- RM0351 (STM32L4xx)
- RM0433 (STM32H7xx)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from collections import deque
from .stm32_base import STM32Peripheral, STATUS_OK


# =============================================================================
# USARTv1 - STM32F1/F4 Style (SR/DR)
# =============================================================================

class STM32USARTv1(STM32Peripheral):
    """
    STM32F1/F4 USART peripheral.

    Register Map:
        0x00: SR   - Status register
        0x04: DR   - Data register
        0x08: BRR  - Baud rate register
        0x0C: CR1  - Control register 1
        0x10: CR2  - Control register 2
        0x14: CR3  - Control register 3
        0x18: GTPR - Guard time and prescaler
    """

    # Register offsets
    SR = 0x00
    DR = 0x04
    BRR = 0x08
    CR1 = 0x0C
    CR2 = 0x10
    CR3 = 0x14
    GTPR = 0x18

    # SR bits
    SR_PE = 1 << 0      # Parity error
    SR_FE = 1 << 1      # Framing error
    SR_NE = 1 << 2      # Noise error
    SR_ORE = 1 << 3     # Overrun error
    SR_IDLE = 1 << 4    # IDLE line detected
    SR_RXNE = 1 << 5    # Read data register not empty
    SR_TC = 1 << 6      # Transmission complete
    SR_TXE = 1 << 7     # Transmit data register empty
    SR_LBD = 1 << 8     # LIN break detection
    SR_CTS = 1 << 9     # CTS flag

    # CR1 bits
    CR1_SBK = 1 << 0    # Send break
    CR1_RWU = 1 << 1    # Receiver wakeup
    CR1_RE = 1 << 2     # Receiver enable
    CR1_TE = 1 << 3     # Transmitter enable
    CR1_IDLEIE = 1 << 4 # IDLE interrupt enable
    CR1_RXNEIE = 1 << 5 # RXNE interrupt enable
    CR1_TCIE = 1 << 6   # TC interrupt enable
    CR1_TXEIE = 1 << 7  # TXE interrupt enable
    CR1_PEIE = 1 << 8   # PE interrupt enable
    CR1_PS = 1 << 9     # Parity selection
    CR1_PCE = 1 << 10   # Parity control enable
    CR1_WAKE = 1 << 11  # Wakeup method
    CR1_M = 1 << 12     # Word length (0=8bit, 1=9bit)
    CR1_UE = 1 << 13    # USART enable
    CR1_OVER8 = 1 << 15 # Oversampling mode

    # Base addresses
    USART_BASES_F1 = {
        1: 0x40013800,  # USART1 (APB2)
        2: 0x40004400,  # USART2 (APB1)
        3: 0x40004800,  # USART3 (APB1)
    }

    USART_BASES_F4 = {
        1: 0x40011000,  # USART1 (APB2)
        2: 0x40004400,  # USART2 (APB1)
        3: 0x40004800,  # USART3 (APB1)
        4: 0x40004C00,  # UART4 (APB1)
        5: 0x40005000,  # UART5 (APB1)
        6: 0x40011400,  # USART6 (APB2)
    }

    # IRQ numbers (F4)
    USART_IRQS = {
        1: 37,  # USART1
        2: 38,  # USART2
        3: 39,  # USART3
        4: 52,  # UART4
        5: 53,  # UART5
        6: 71,  # USART6
    }

    def __init__(self, index: int = 1, base: int = None, family: str = "F4"):
        """
        Initialize USART.

        Args:
            index: USART number (1-6)
            base: Base address (auto-calculated if None)
            family: Device family ("F1" or "F4")
        """
        if base is None:
            if family == "F1":
                base = self.USART_BASES_F1.get(index, 0x40013800)
            else:
                base = self.USART_BASES_F4.get(index, 0x40011000)

        irq = self.USART_IRQS.get(index, 37)
        super().__init__(f"USART{index}", base, 0x400, irq)
        self.index = index

        # Registers
        self.sr = self.SR_TC | self.SR_TXE  # Initially TX empty
        self.dr = 0
        self.brr = 0
        self.cr1 = 0
        self.cr2 = 0
        self.cr3 = 0
        self.gtpr = 0

        # FIFOs
        self.tx_fifo: deque = deque(maxlen=16)
        self.rx_fifo: deque = deque(maxlen=16)

        # Callbacks
        self.on_tx: Optional[Callable[[int], None]] = None
        self.on_rx_ready: Optional[Callable[[], List[int]]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.SR:
            return self._get_sr()
        elif offset == self.DR:
            return self._read_dr()
        elif offset == self.BRR:
            return self.brr
        elif offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.CR3:
            return self.cr3
        elif offset == self.GTPR:
            return self.gtpr
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.SR:
            # Some bits are write-0-to-clear
            self.sr &= value | 0x3E0
        elif offset == self.DR:
            self._write_dr(value)
        elif offset == self.BRR:
            self.brr = value
        elif offset == self.CR1:
            self.cr1 = value
            if value & self.CR1_UE:
                self.log.debug(f"USART enabled, BRR=0x{self.brr:04X}")
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.CR3:
            self.cr3 = value
        elif offset == self.GTPR:
            self.gtpr = value

    def _get_sr(self) -> int:
        """Get status register with live flags."""
        sr = self.sr

        # RXNE: set if data available
        if self.rx_fifo:
            sr |= self.SR_RXNE
        else:
            sr &= ~self.SR_RXNE

        # TXE: always set (we handle TX immediately)
        sr |= self.SR_TXE

        return sr

    def _read_dr(self) -> int:
        """Read data register (clears RXNE)."""
        if self.rx_fifo:
            data = self.rx_fifo.popleft()
            if not self.rx_fifo:
                self.sr &= ~self.SR_RXNE
            return data
        return 0

    def _write_dr(self, value: int):
        """Write data register (transmit)."""
        data = value & 0xFF
        if self.cr1 & self.CR1_M:
            data = value & 0x1FF  # 9-bit mode

        if self.cr1 & self.CR1_TE:
            self.tx_fifo.append(data)
            self.sr &= ~self.SR_TC  # Clear TC while transmitting

            # Call TX callback
            if self.on_tx:
                self.on_tx(data)
            else:
                # Echo for loopback testing
                if self.cr3 & 0x10:  # HDSEL - half duplex
                    self.rx_fifo.append(data)

            # Set TC after transmission
            self.sr |= self.SR_TC
            self._check_interrupt()

    def receive_byte(self, data: int):
        """Receive a byte into RX FIFO."""
        if self.cr1 & self.CR1_RE:
            if len(self.rx_fifo) < 16:
                self.rx_fifo.append(data & 0xFF)
                self.sr |= self.SR_RXNE
                self._check_interrupt()
            else:
                self.sr |= self.SR_ORE  # Overrun

    def _check_interrupt(self):
        """Check and trigger interrupt if enabled."""
        if (self.cr1 & self.CR1_RXNEIE) and (self.sr & self.SR_RXNE):
            self.trigger_irq(1)
        if (self.cr1 & self.CR1_TXEIE) and (self.sr & self.SR_TXE):
            self.trigger_irq(1)
        if (self.cr1 & self.CR1_TCIE) and (self.sr & self.SR_TC):
            self.trigger_irq(1)

    def _reset_registers(self):
        """Reset to default state."""
        self.sr = self.SR_TC | self.SR_TXE
        self.dr = 0
        self.brr = 0
        self.cr1 = 0
        self.cr2 = 0
        self.cr3 = 0
        self.gtpr = 0
        self.tx_fifo.clear()
        self.rx_fifo.clear()


# =============================================================================
# USARTv2 - STM32L4/H7 Style (ISR/RDR/TDR with FIFO)
# =============================================================================

class STM32USARTv2(STM32Peripheral):
    """
    STM32L4/H7 USART peripheral with FIFO support.

    Register Map:
        0x00: CR1   - Control register 1
        0x04: CR2   - Control register 2
        0x08: CR3   - Control register 3
        0x0C: BRR   - Baud rate register
        0x10: GTPR  - Guard time and prescaler
        0x14: RTOR  - Receiver timeout
        0x18: RQR   - Request register
        0x1C: ISR   - Interrupt and status register
        0x20: ICR   - Interrupt flag clear register
        0x24: RDR   - Receive data register
        0x28: TDR   - Transmit data register
        0x2C: PRESC - Prescaler register (H7)
    """

    # Register offsets
    CR1 = 0x00
    CR2 = 0x04
    CR3 = 0x08
    BRR = 0x0C
    GTPR = 0x10
    RTOR = 0x14
    RQR = 0x18
    ISR = 0x1C
    ICR = 0x20
    RDR = 0x24
    TDR = 0x28
    PRESC = 0x2C

    # ISR bits
    ISR_PE = 1 << 0
    ISR_FE = 1 << 1
    ISR_NE = 1 << 2
    ISR_ORE = 1 << 3
    ISR_IDLE = 1 << 4
    ISR_RXNE = 1 << 5   # RXNE/RXFNE
    ISR_TC = 1 << 6
    ISR_TXE = 1 << 7    # TXE/TXFNF
    ISR_LBDF = 1 << 8
    ISR_CTSIF = 1 << 9
    ISR_CTS = 1 << 10
    ISR_RTOF = 1 << 11
    ISR_EOBF = 1 << 12
    ISR_UDR = 1 << 13   # SPI slave underrun (H7)
    ISR_ABRE = 1 << 14
    ISR_ABRF = 1 << 15
    ISR_BUSY = 1 << 16
    ISR_CMF = 1 << 17
    ISR_SBKF = 1 << 18
    ISR_RWU = 1 << 19
    ISR_WUF = 1 << 20
    ISR_TEACK = 1 << 21
    ISR_REACK = 1 << 22
    ISR_TXFE = 1 << 23  # FIFO empty (H7)
    ISR_RXFF = 1 << 24  # FIFO full (H7)
    ISR_TCBGT = 1 << 25
    ISR_RXFT = 1 << 26  # FIFO threshold (H7)
    ISR_TXFT = 1 << 27  # FIFO threshold (H7)

    # CR1 bits
    CR1_UE = 1 << 0
    CR1_UESM = 1 << 1
    CR1_RE = 1 << 2
    CR1_TE = 1 << 3
    CR1_IDLEIE = 1 << 4
    CR1_RXNEIE = 1 << 5  # RXNEIE/RXFNEIE
    CR1_TCIE = 1 << 6
    CR1_TXEIE = 1 << 7   # TXEIE/TXFNFIE
    CR1_PEIE = 1 << 8
    CR1_PS = 1 << 9
    CR1_PCE = 1 << 10
    CR1_WAKE = 1 << 11
    CR1_M0 = 1 << 12
    CR1_MME = 1 << 13
    CR1_CMIE = 1 << 14
    CR1_OVER8 = 1 << 15
    CR1_M1 = 1 << 28
    CR1_FIFOEN = 1 << 29

    # Base addresses (L4)
    USART_BASES_L4 = {
        1: 0x40013800,
        2: 0x40004400,
        3: 0x40004800,
    }

    # Base addresses (H7)
    USART_BASES_H7 = {
        1: 0x40011000,
        2: 0x40004400,
        3: 0x40004800,
        6: 0x40011400,
    }

    def __init__(self, index: int = 1, base: int = None, family: str = "L4"):
        """
        Initialize USART.

        Args:
            index: USART number
            base: Base address (auto-calculated if None)
            family: Device family ("L4" or "H7")
        """
        if base is None:
            if family == "H7":
                base = self.USART_BASES_H7.get(index, 0x40011000)
            else:
                base = self.USART_BASES_L4.get(index, 0x40013800)

        super().__init__(f"USART{index}", base, 0x400, 37 + index - 1)
        self.index = index
        self.family = family

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.cr3 = 0
        self.brr = 0
        self.gtpr = 0
        self.rtor = 0
        self.isr = self.ISR_TC | self.ISR_TXE | self.ISR_TEACK | self.ISR_REACK
        self.presc = 0

        # FIFOs (8-deep on H7)
        self.tx_fifo: deque = deque(maxlen=8)
        self.rx_fifo: deque = deque(maxlen=8)

        # Callbacks
        self.on_tx: Optional[Callable[[int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.CR1:
            return self.cr1
        elif offset == self.CR2:
            return self.cr2
        elif offset == self.CR3:
            return self.cr3
        elif offset == self.BRR:
            return self.brr
        elif offset == self.ISR:
            return self._get_isr()
        elif offset == self.RDR:
            return self._read_rdr()
        elif offset == self.PRESC:
            return self.presc
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.CR1:
            old_cr1 = self.cr1
            self.cr1 = value
            ue = bool(value & self.CR1_UE)
            if not ue:
                # UE disabled: hardware resets status flags
                self.isr &= ~(self.ISR_TEACK | self.ISR_REACK)
                self.isr |= self.ISR_TXE | self.ISR_TC
            else:
                # UE enabled: set TEACK/REACK based on TE/RE
                if value & self.CR1_TE:
                    self.isr |= self.ISR_TEACK
                else:
                    self.isr &= ~self.ISR_TEACK
                if value & self.CR1_RE:
                    self.isr |= self.ISR_REACK
                else:
                    self.isr &= ~self.ISR_REACK
                self.log.debug(f"USART enabled")
        elif offset == self.CR2:
            self.cr2 = value
        elif offset == self.CR3:
            self.cr3 = value
        elif offset == self.BRR:
            self.brr = value
        elif offset == self.RQR:
            self._handle_rqr(value)
        elif offset == self.ICR:
            # Clear interrupt flags
            clear_mask = value & 0x00121BDF
            self.isr &= ~clear_mask
        elif offset == self.TDR:
            self._write_tdr(value)
        elif offset == self.PRESC:
            self.presc = value

    def _get_isr(self) -> int:
        """Get interrupt status register with live flags."""
        isr = self.isr

        # RXNE/RXFNE: set if data available
        if self.rx_fifo:
            isr |= self.ISR_RXNE
        else:
            isr &= ~self.ISR_RXNE

        # TXE/TXFNF: set if TX FIFO not full
        if len(self.tx_fifo) < 8:
            isr |= self.ISR_TXE
        else:
            isr &= ~self.ISR_TXE

        # FIFO flags
        if self.cr1 & self.CR1_FIFOEN:
            if len(self.tx_fifo) == 0:
                isr |= self.ISR_TXFE
            if len(self.rx_fifo) == 8:
                isr |= self.ISR_RXFF

        return isr

    def _read_rdr(self) -> int:
        """Read receive data register."""
        if self.rx_fifo:
            return self.rx_fifo.popleft()
        return 0

    def _write_tdr(self, value: int):
        """Write transmit data register."""
        data = value & 0xFF

        if self.cr1 & self.CR1_TE:
            if self.on_tx:
                self.on_tx(data)

            # Set TC after transmission
            self.isr |= self.ISR_TC
            self._check_interrupt()

    def _handle_rqr(self, value: int):
        """Handle request register write."""
        if value & 0x01:  # ABRRQ
            pass
        if value & 0x02:  # SBKRQ - send break
            pass
        if value & 0x04:  # MMRQ - mute mode
            pass
        if value & 0x08:  # RXFRQ - flush RX
            self.rx_fifo.clear()
        if value & 0x10:  # TXFRQ - flush TX
            self.tx_fifo.clear()

    def receive_byte(self, data: int):
        """Receive a byte into RX FIFO."""
        if self.cr1 & self.CR1_RE:
            if len(self.rx_fifo) < 8:
                self.rx_fifo.append(data & 0xFF)
                self._check_interrupt()
            else:
                self.isr |= self.ISR_ORE

    def _check_interrupt(self):
        """Check and trigger interrupt if enabled."""
        if (self.cr1 & self.CR1_RXNEIE) and (self._get_isr() & self.ISR_RXNE):
            self.trigger_irq(1)
        if (self.cr1 & self.CR1_TXEIE) and (self._get_isr() & self.ISR_TXE):
            self.trigger_irq(1)
        if (self.cr1 & self.CR1_TCIE) and (self.isr & self.ISR_TC):
            self.trigger_irq(1)

    def _reset_registers(self):
        """Reset to default state."""
        self.cr1 = 0
        self.cr2 = 0
        self.cr3 = 0
        self.brr = 0
        self.isr = self.ISR_TC | self.ISR_TXE | self.ISR_TEACK | self.ISR_REACK
        self.tx_fifo.clear()
        self.rx_fifo.clear()


# =============================================================================
# LPUART - Low-Power UART (L4/H7)
# =============================================================================

class STM32LPUART(STM32USARTv2):
    """
    STM32 LPUART (Low-Power UART).

    Based on USARTv2 with additional low-power features.
    Can operate in Stop mode with LSE clock.
    """

    def __init__(self, index: int = 1, base: int = 0x40008000, family: str = "L4"):
        """
        Initialize LPUART.

        Args:
            index: LPUART number
            base: Base address
            family: Device family
        """
        super().__init__(index, base, family)
        self.name = f"LPUART{index}"
        self.irq = 70  # LPUART1 IRQ on L4
