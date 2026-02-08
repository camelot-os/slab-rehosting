"""
ARM PrimeCell and Synopsys DesignWare Communication Peripherals

This module implements standard IP blocks used in many microcontrollers:

IP Blocks:
- PL011UART       - ARM PrimeCell PL011 UART
- PrimeCellSSP    - ARM PrimeCell SSP (SPI/SSI) controller
- SynopsysDWI2C   - Synopsys DesignWare APB I2C controller

Aliases for RP2040 compatibility:
- RP2040UART = PL011UART
- RP2040SPI  = PrimeCellSSP
- RP2040I2C  = SynopsysDWI2C

These IP blocks are reusable across different MCUs:
- PL011: Raspberry Pi, STM32, NXP LPC, many ARM SoCs
- SSP: NXP LPC, Cirrus Logic, many ARM SoCs
- DW I2C: Intel, Synopsys reference designs, many SoCs

References:
- ARM PrimeCell UART (PL011) TRM: DDI0183
- ARM PrimeCell SSP (PL022) TRM: DDI0194
- Synopsys DW_apb_i2c Databook

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Dict, List, Optional, Callable, Tuple
from collections import deque

# Import base class
try:
    from .rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR
except ImportError:
    from rp2040_peripherals import RP2040Peripheral, STATUS_OK, STATUS_ERROR


# =============================================================================
# PL011 UART - ARM PrimeCell UART (DDI0183)
# Default addresses: 0x40034000 (UART0), 0x40038000 (UART1) on RP2040
# =============================================================================

class PL011UART(RP2040Peripheral):
    """
    ARM PrimeCell PL011 UART.

    This IP block is used in many ARM-based microcontrollers including:
    - RP2040/RP2350 (Raspberry Pi Pico)
    - Raspberry Pi SoCs
    - Many ARM Cortex-A/M based SoCs

    Features:
    - 16550-like UART with 32-byte TX/RX FIFOs
    - Programmable baud rate, data bits, parity, stop bits
    - Hardware flow control (RTS/CTS)
    - DMA support
    - Interrupt generation

    Register Map (PL011 standard):
        0x000: UARTDR      - Data register
        0x004: UARTRSR     - Receive status / Error clear
        0x018: UARTFR      - Flag register
        0x020: UARTILPR    - IrDA low-power counter
        0x024: UARTIBRD    - Integer baud rate divisor
        0x028: UARTFBRD    - Fractional baud rate divisor
        0x02C: UARTLCR_H   - Line control
        0x030: UARTCR      - Control register
        0x034: UARTIFLS    - Interrupt FIFO level select
        0x038: UARTIMSC    - Interrupt mask
        0x03C: UARTRIS     - Raw interrupt status
        0x040: UARTMIS     - Masked interrupt status
        0x044: UARTICR     - Interrupt clear
        0x048: UARTDMACR   - DMA control
    """

    # Register offsets
    UARTDR = 0x000
    UARTRSR = 0x004
    UARTFR = 0x018
    UARTILPR = 0x020
    UARTIBRD = 0x024
    UARTFBRD = 0x028
    UARTLCR_H = 0x02C
    UARTCR = 0x030
    UARTIFLS = 0x034
    UARTIMSC = 0x038
    UARTRIS = 0x03C
    UARTMIS = 0x040
    UARTICR = 0x044
    UARTDMACR = 0x048

    # UARTFR bits
    FR_TXFE = 1 << 7   # TX FIFO empty
    FR_RXFF = 1 << 6   # RX FIFO full
    FR_TXFF = 1 << 5   # TX FIFO full
    FR_RXFE = 1 << 4   # RX FIFO empty
    FR_BUSY = 1 << 3   # UART busy
    FR_CTS = 1 << 0    # Clear to send

    # UARTCR bits
    CR_CTSEN = 1 << 15
    CR_RTSEN = 1 << 14
    CR_RTS = 1 << 11
    CR_RXE = 1 << 9
    CR_TXE = 1 << 8
    CR_LBE = 1 << 7    # Loopback enable
    CR_UARTEN = 1 << 0

    # Interrupt bits
    INT_OE = 1 << 10   # Overrun error
    INT_BE = 1 << 9    # Break error
    INT_PE = 1 << 8    # Parity error
    INT_FE = 1 << 7    # Framing error
    INT_RT = 1 << 6    # Receive timeout
    INT_TX = 1 << 5    # Transmit
    INT_RX = 1 << 4    # Receive
    INT_CTS = 1 << 1   # CTS modem

    FIFO_SIZE = 32

    def __init__(self, index: int = 0, base: int = None, irq: int = None):
        if base is None:
            base = 0x40034000 if index == 0 else 0x40038000
        if irq is None:
            irq = 20 if index == 0 else 21  # UART0_IRQ, UART1_IRQ

        super().__init__(f"UART{index}", base, 0x1000, irq)
        self.index = index

        # FIFOs
        self.tx_fifo: deque = deque(maxlen=self.FIFO_SIZE)
        self.rx_fifo: deque = deque(maxlen=self.FIFO_SIZE)

        # Configuration
        self.baud_int = 0
        self.baud_frac = 0
        self.lcr_h = 0
        self.cr = 0
        self.ifls = 0x12  # Default: 1/2 full
        self.imsc = 0
        self.ris = 0
        self.dmacr = 0

        # Callbacks
        self.on_tx: Optional[Callable[[int], None]] = None  # Called when byte transmitted
        self.on_tx_empty: Optional[Callable[[], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.UARTDR:
            # Read from RX FIFO
            if self.rx_fifo:
                data = self.rx_fifo.popleft()
                self._update_interrupts()
                return data
            return 0

        elif offset == self.UARTRSR:
            return self.regs.get(offset, 0) & 0xF

        elif offset == self.UARTFR:
            return self._get_flags()

        elif offset == self.UARTIBRD:
            return self.baud_int

        elif offset == self.UARTFBRD:
            return self.baud_frac

        elif offset == self.UARTLCR_H:
            return self.lcr_h

        elif offset == self.UARTCR:
            return self.cr

        elif offset == self.UARTIFLS:
            return self.ifls

        elif offset == self.UARTIMSC:
            return self.imsc

        elif offset == self.UARTRIS:
            return self.ris

        elif offset == self.UARTMIS:
            return self.ris & self.imsc

        elif offset == self.UARTDMACR:
            return self.dmacr

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.UARTDR:
            # Write to TX FIFO
            if len(self.tx_fifo) < self.FIFO_SIZE:
                self.tx_fifo.append(value & 0xFF)
                self._do_transmit()
                self._update_interrupts()

        elif offset == self.UARTRSR:
            # Write clears errors
            self.regs[offset] = 0

        elif offset == self.UARTIBRD:
            self.baud_int = value & 0xFFFF

        elif offset == self.UARTFBRD:
            self.baud_frac = value & 0x3F

        elif offset == self.UARTLCR_H:
            self.lcr_h = value & 0xFF

        elif offset == self.UARTCR:
            self.cr = value & 0xFFFF
            if value & self.CR_UARTEN:
                self.log.debug(f"UART{self.index} enabled")

        elif offset == self.UARTIFLS:
            self.ifls = value & 0x3F

        elif offset == self.UARTIMSC:
            self.imsc = value & 0x7FF
            self._update_interrupts()

        elif offset == self.UARTICR:
            # Write 1 to clear interrupts
            self.ris &= ~value
            self._update_interrupts()

        elif offset == self.UARTDMACR:
            self.dmacr = value & 0x7

        else:
            self.regs[offset] = value

    def _get_flags(self) -> int:
        flags = 0
        if not self.tx_fifo:
            flags |= self.FR_TXFE
        if len(self.tx_fifo) >= self.FIFO_SIZE:
            flags |= self.FR_TXFF
        if not self.rx_fifo:
            flags |= self.FR_RXFE
        if len(self.rx_fifo) >= self.FIFO_SIZE:
            flags |= self.FR_RXFF
        flags |= self.FR_CTS  # Always clear to send
        return flags

    def _do_transmit(self):
        """Transmit data from TX FIFO."""
        if not (self.cr & self.CR_UARTEN) or not (self.cr & self.CR_TXE):
            return

        while self.tx_fifo:
            byte = self.tx_fifo.popleft()

            # Loopback mode
            if self.cr & self.CR_LBE:
                if len(self.rx_fifo) < self.FIFO_SIZE:
                    self.rx_fifo.append(byte)

            # Callback for external transmission
            if self.on_tx:
                self.on_tx(byte)

            self.log.debug(f"TX: 0x{byte:02X} ({chr(byte) if 32 <= byte < 127 else '?'})")

        if self.on_tx_empty:
            self.on_tx_empty()

    def _update_interrupts(self):
        """Update interrupt status."""
        # TX interrupt when FIFO below threshold
        tx_threshold = [1, 2, 4, 8, 16, 24, 28, 30][(self.ifls >> 0) & 0x7]
        if len(self.tx_fifo) <= tx_threshold:
            self.ris |= self.INT_TX

        # RX interrupt when FIFO above threshold
        rx_threshold = [1, 2, 4, 8, 16, 24, 28, 30][(self.ifls >> 3) & 0x7]
        if len(self.rx_fifo) >= rx_threshold:
            self.ris |= self.INT_RX

        # Trigger interrupt if any masked bits set
        if self.ris & self.imsc:
            self.trigger_irq(1)

    def receive(self, data: bytes):
        """Receive data into RX FIFO (from external source)."""
        for byte in data:
            if len(self.rx_fifo) < self.FIFO_SIZE:
                self.rx_fifo.append(byte)
                self.log.debug(f"RX: 0x{byte:02X}")
        self._update_interrupts()

    def get_baud_rate(self, clk_peri: int = 125_000_000) -> int:
        """Calculate baud rate from divisor registers."""
        if self.baud_int == 0:
            return 0
        divisor = self.baud_int + (self.baud_frac / 64.0)
        return int(clk_peri / (16 * divisor))


# =============================================================================
# PrimeCell SSP (PL022) - ARM SPI/SSI controller
# Default addresses: 0x4003C000 (SPI0), 0x40040000 (SPI1) on RP2040
# =============================================================================

class PrimeCellSSP(RP2040Peripheral):
    """
    ARM PrimeCell SSP (PL022) - Synchronous Serial Port.

    This IP block is used in many ARM-based microcontrollers including:
    - RP2040/RP2350 (Raspberry Pi Pico)
    - NXP LPC series
    - Many ARM Cortex-M based SoCs

    Features:
    - Master/Slave mode
    - 4-16 bit data frames
    - Motorola SPI, TI SSI, National Microwire formats
    - 8-entry TX/RX FIFOs
    - DMA support

    Register Map (PL022 standard):
        0x000: SSPCR0   - Control register 0
        0x004: SSPCR1   - Control register 1
        0x008: SSPDR    - Data register
        0x00C: SSPSR    - Status register
        0x010: SSPCPSR  - Clock prescale
        0x014: SSPIMSC  - Interrupt mask
        0x018: SSPRIS   - Raw interrupt status
        0x01C: SSPMIS   - Masked interrupt status
        0x020: SSPICR   - Interrupt clear
        0x024: SSPDMACR - DMA control
    """

    # Register offsets
    SSPCR0 = 0x000
    SSPCR1 = 0x004
    SSPDR = 0x008
    SSPSR = 0x00C
    SSPCPSR = 0x010
    SSPIMSC = 0x014
    SSPRIS = 0x018
    SSPMIS = 0x01C
    SSPICR = 0x020
    SSPDMACR = 0x024

    # SSPCR1 bits
    CR1_SOD = 1 << 3   # Slave output disable
    CR1_MS = 1 << 2    # Master/slave select (0=master)
    CR1_SSE = 1 << 1   # SSP enable
    CR1_LBM = 1 << 0   # Loopback mode

    # SSPSR bits
    SR_BSY = 1 << 4    # Busy
    SR_RFF = 1 << 3    # RX FIFO full
    SR_RNE = 1 << 2    # RX FIFO not empty
    SR_TNF = 1 << 1    # TX FIFO not full
    SR_TFE = 1 << 0    # TX FIFO empty

    # Interrupt bits
    INT_TX = 1 << 3    # TX FIFO half empty or less
    INT_RX = 1 << 2    # RX FIFO half full or more
    INT_RT = 1 << 1    # RX timeout
    INT_ROR = 1 << 0   # RX overrun

    FIFO_SIZE = 8

    def __init__(self, index: int = 0, base: int = None, irq: int = None):
        if base is None:
            base = 0x4003C000 if index == 0 else 0x40040000
        if irq is None:
            irq = 18 if index == 0 else 19  # SPI0_IRQ, SPI1_IRQ

        super().__init__(f"SPI{index}", base, 0x1000, irq)
        self.index = index

        # FIFOs
        self.tx_fifo: deque = deque(maxlen=self.FIFO_SIZE)
        self.rx_fifo: deque = deque(maxlen=self.FIFO_SIZE)

        # Configuration
        self.cr0 = 0
        self.cr1 = 0
        self.cpsr = 0
        self.imsc = 0
        self.ris = 0
        self.dmacr = 0

        # Callbacks
        self.on_transfer: Optional[Callable[[int], int]] = None  # tx_data -> rx_data

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.SSPCR0:
            return self.cr0

        elif offset == self.SSPCR1:
            return self.cr1

        elif offset == self.SSPDR:
            if self.rx_fifo:
                data = self.rx_fifo.popleft()
                self._update_interrupts()
                return data
            return 0

        elif offset == self.SSPSR:
            return self._get_status()

        elif offset == self.SSPCPSR:
            return self.cpsr

        elif offset == self.SSPIMSC:
            return self.imsc

        elif offset == self.SSPRIS:
            return self.ris

        elif offset == self.SSPMIS:
            return self.ris & self.imsc

        elif offset == self.SSPDMACR:
            return self.dmacr

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.SSPCR0:
            self.cr0 = value & 0xFFFF

        elif offset == self.SSPCR1:
            self.cr1 = value & 0xF
            if value & self.CR1_SSE:
                self.log.debug(f"SPI{self.index} enabled")

        elif offset == self.SSPDR:
            if len(self.tx_fifo) < self.FIFO_SIZE:
                data_bits = ((self.cr0 >> 0) & 0xF) + 1
                mask = (1 << data_bits) - 1
                self.tx_fifo.append(value & mask)
                self._do_transfer()
                self._update_interrupts()

        elif offset == self.SSPCPSR:
            self.cpsr = value & 0xFE  # Must be even, 2-254

        elif offset == self.SSPIMSC:
            self.imsc = value & 0xF
            self._update_interrupts()

        elif offset == self.SSPICR:
            self.ris &= ~(value & 0x3)  # Only RT and ROR clearable
            self._update_interrupts()

        elif offset == self.SSPDMACR:
            self.dmacr = value & 0x3

        else:
            self.regs[offset] = value

    def _get_status(self) -> int:
        status = 0
        if not self.tx_fifo:
            status |= self.SR_TFE
        if len(self.tx_fifo) < self.FIFO_SIZE:
            status |= self.SR_TNF
        if self.rx_fifo:
            status |= self.SR_RNE
        if len(self.rx_fifo) >= self.FIFO_SIZE:
            status |= self.SR_RFF
        return status

    def _do_transfer(self):
        """Perform SPI transfer."""
        if not (self.cr1 & self.CR1_SSE):
            return

        while self.tx_fifo:
            tx_data = self.tx_fifo.popleft()

            # Loopback mode
            if self.cr1 & self.CR1_LBM:
                rx_data = tx_data
            elif self.on_transfer:
                rx_data = self.on_transfer(tx_data)
            else:
                rx_data = 0xFF  # No slave connected

            if len(self.rx_fifo) < self.FIFO_SIZE:
                self.rx_fifo.append(rx_data)
            else:
                self.ris |= self.INT_ROR  # Overrun

            self.log.debug(f"SPI: TX=0x{tx_data:04X} RX=0x{rx_data:04X}")

    def _update_interrupts(self):
        """Update interrupt status."""
        if len(self.tx_fifo) <= self.FIFO_SIZE // 2:
            self.ris |= self.INT_TX
        else:
            self.ris &= ~self.INT_TX

        if len(self.rx_fifo) >= self.FIFO_SIZE // 2:
            self.ris |= self.INT_RX
        else:
            self.ris &= ~self.INT_RX

        if self.ris & self.imsc:
            self.trigger_irq(1)

    def get_clock_rate(self, clk_peri: int = 125_000_000) -> int:
        """Calculate SPI clock rate."""
        if self.cpsr == 0:
            return 0
        scr = (self.cr0 >> 8) & 0xFF
        return clk_peri // (self.cpsr * (1 + scr))


# =============================================================================
# Synopsys DesignWare I2C (DW_apb_i2c)
# Default addresses: 0x40044000 (I2C0), 0x40048000 (I2C1) on RP2040
# =============================================================================

class SynopsysDWI2C(RP2040Peripheral):
    """
    Synopsys DesignWare APB I2C Controller (DW_apb_i2c).

    This IP block is used in many SoCs including:
    - RP2040/RP2350 (Raspberry Pi Pico)
    - Intel/AMD SoCs
    - Many ARM-based designs

    Features:
    - Master and slave mode
    - Standard (100kHz), Fast (400kHz), Fast+ (1MHz) modes
    - 7-bit and 10-bit addressing
    - TX/RX FIFOs
    - DMA support

    Register Map (DW_apb_i2c standard):
        0x000: IC_CON           - Control
        0x004: IC_TAR           - Target address
        0x008: IC_SAR           - Slave address
        0x010: IC_DATA_CMD      - Data/command
        0x014: IC_SS_SCL_HCNT   - Standard speed SCL high count
        0x018: IC_SS_SCL_LCNT   - Standard speed SCL low count
        0x02C: IC_INTR_STAT     - Interrupt status
        0x030: IC_INTR_MASK     - Interrupt mask
        0x034: IC_RAW_INTR_STAT - Raw interrupt status
        0x054: IC_CLR_INTR      - Clear all interrupts
        0x06C: IC_ENABLE        - Enable
        0x070: IC_STATUS        - Status
        0x074: IC_TXFLR         - TX FIFO level
        0x078: IC_RXFLR         - RX FIFO level
    """

    # Register offsets
    IC_CON = 0x000
    IC_TAR = 0x004
    IC_SAR = 0x008
    IC_DATA_CMD = 0x010
    IC_SS_SCL_HCNT = 0x014
    IC_SS_SCL_LCNT = 0x018
    IC_FS_SCL_HCNT = 0x01C
    IC_FS_SCL_LCNT = 0x020
    IC_INTR_STAT = 0x02C
    IC_INTR_MASK = 0x030
    IC_RAW_INTR_STAT = 0x034
    IC_RX_TL = 0x038
    IC_TX_TL = 0x03C
    IC_CLR_INTR = 0x040
    IC_CLR_RX_UNDER = 0x044
    IC_CLR_RX_OVER = 0x048
    IC_CLR_TX_OVER = 0x04C
    IC_CLR_RD_REQ = 0x050
    IC_CLR_TX_ABRT = 0x054
    IC_CLR_RX_DONE = 0x058
    IC_CLR_ACTIVITY = 0x05C
    IC_CLR_STOP_DET = 0x060
    IC_CLR_START_DET = 0x064
    IC_CLR_GEN_CALL = 0x068
    IC_ENABLE = 0x06C
    IC_STATUS = 0x070
    IC_TXFLR = 0x074
    IC_RXFLR = 0x078
    IC_SDA_HOLD = 0x07C
    IC_TX_ABRT_SOURCE = 0x080
    IC_DMA_CR = 0x088
    IC_DMA_TDLR = 0x08C
    IC_DMA_RDLR = 0x090
    IC_COMP_PARAM_1 = 0x0F4
    IC_COMP_VERSION = 0x0F8
    IC_COMP_TYPE = 0x0FC

    # IC_CON bits
    CON_STOP_DET_IFADDRESSED = 1 << 7
    CON_IC_SLAVE_DISABLE = 1 << 6
    CON_IC_RESTART_EN = 1 << 5
    CON_IC_10BITADDR_MASTER = 1 << 4
    CON_IC_10BITADDR_SLAVE = 1 << 3
    CON_SPEED_MASK = 0x6
    CON_SPEED_STANDARD = 0x2
    CON_SPEED_FAST = 0x4
    CON_SPEED_HIGH = 0x6
    CON_MASTER_MODE = 1 << 0

    # IC_STATUS bits
    STATUS_SLV_ACTIVITY = 1 << 6
    STATUS_MST_ACTIVITY = 1 << 5
    STATUS_RFF = 1 << 4
    STATUS_RFNE = 1 << 3
    STATUS_TFE = 1 << 2
    STATUS_TFNF = 1 << 1
    STATUS_ACTIVITY = 1 << 0

    # Interrupt bits
    INT_GEN_CALL = 1 << 11
    INT_START_DET = 1 << 10
    INT_STOP_DET = 1 << 9
    INT_ACTIVITY = 1 << 8
    INT_RX_DONE = 1 << 7
    INT_TX_ABRT = 1 << 6
    INT_RD_REQ = 1 << 5
    INT_TX_EMPTY = 1 << 4
    INT_TX_OVER = 1 << 3
    INT_RX_FULL = 1 << 2
    INT_RX_OVER = 1 << 1
    INT_RX_UNDER = 1 << 0

    FIFO_SIZE = 16

    def __init__(self, index: int = 0, base: int = None, irq: int = None):
        if base is None:
            base = 0x40044000 if index == 0 else 0x40048000
        if irq is None:
            irq = 23 if index == 0 else 24  # I2C0_IRQ, I2C1_IRQ

        super().__init__(f"I2C{index}", base, 0x1000, irq)
        self.index = index

        # FIFOs
        self.tx_fifo: deque = deque(maxlen=self.FIFO_SIZE)
        self.rx_fifo: deque = deque(maxlen=self.FIFO_SIZE)

        # Configuration
        self.con = self.CON_IC_SLAVE_DISABLE | self.CON_IC_RESTART_EN | self.CON_SPEED_FAST | self.CON_MASTER_MODE
        self.tar = 0
        self.sar = 0x55
        self.enable = 0
        self.intr_mask = 0
        self.raw_intr = 0
        self.tx_tl = 0
        self.rx_tl = 0

        # Callbacks for I2C transactions
        self.on_write: Optional[Callable[[int, bytes], bool]] = None  # (addr, data) -> ack
        self.on_read: Optional[Callable[[int, int], bytes]] = None  # (addr, len) -> data

        # Transaction state
        self.tx_buffer: List[int] = []
        self.pending_reads = 0

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.IC_CON:
            return self.con

        elif offset == self.IC_TAR:
            return self.tar

        elif offset == self.IC_SAR:
            return self.sar

        elif offset == self.IC_DATA_CMD:
            if self.rx_fifo:
                data = self.rx_fifo.popleft()
                self._update_interrupts()
                return data
            return 0

        elif offset == self.IC_INTR_STAT:
            return self.raw_intr & self.intr_mask

        elif offset == self.IC_INTR_MASK:
            return self.intr_mask

        elif offset == self.IC_RAW_INTR_STAT:
            return self.raw_intr

        elif offset == self.IC_ENABLE:
            return self.enable

        elif offset == self.IC_STATUS:
            return self._get_status()

        elif offset == self.IC_TXFLR:
            return len(self.tx_fifo)

        elif offset == self.IC_RXFLR:
            return len(self.rx_fifo)

        elif offset == self.IC_COMP_PARAM_1:
            return 0x00FFFF6E  # Standard DW params

        elif offset == self.IC_COMP_VERSION:
            return 0x3230312A  # "201*"

        elif offset == self.IC_COMP_TYPE:
            return 0x44570140  # "DW" type

        # Clear interrupt registers return 0 and clear on read
        elif offset in (self.IC_CLR_INTR, self.IC_CLR_RX_UNDER, self.IC_CLR_RX_OVER,
                       self.IC_CLR_TX_OVER, self.IC_CLR_RD_REQ, self.IC_CLR_TX_ABRT,
                       self.IC_CLR_RX_DONE, self.IC_CLR_ACTIVITY, self.IC_CLR_STOP_DET,
                       self.IC_CLR_START_DET, self.IC_CLR_GEN_CALL):
            self._clear_interrupt(offset)
            return 0

        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.IC_CON:
            self.con = value & 0xFF

        elif offset == self.IC_TAR:
            self.tar = value & 0x3FF

        elif offset == self.IC_SAR:
            self.sar = value & 0x3FF

        elif offset == self.IC_DATA_CMD:
            # Bit 8: CMD (0=write, 1=read)
            # Bit 9: STOP
            # Bit 10: RESTART
            cmd = (value >> 8) & 1
            stop = (value >> 9) & 1
            restart = (value >> 10) & 1

            if cmd == 0:
                # Write data
                self.tx_buffer.append(value & 0xFF)
                if stop:
                    self._do_write_transaction()
            else:
                # Read request
                self.pending_reads += 1
                if stop:
                    self._do_read_transaction()

        elif offset == self.IC_INTR_MASK:
            self.intr_mask = value & 0xFFF
            self._update_interrupts()

        elif offset == self.IC_RX_TL:
            self.rx_tl = value & 0xFF

        elif offset == self.IC_TX_TL:
            self.tx_tl = value & 0xFF

        elif offset == self.IC_ENABLE:
            was_enabled = self.enable & 1
            self.enable = value & 0x3
            if (value & 1) and not was_enabled:
                self.log.debug(f"I2C{self.index} enabled, target=0x{self.tar:02X}")

        else:
            self.regs[offset] = value

    def _get_status(self) -> int:
        status = 0
        if not self.tx_fifo and not self.tx_buffer:
            status |= self.STATUS_TFE
        if len(self.tx_fifo) < self.FIFO_SIZE:
            status |= self.STATUS_TFNF
        if self.rx_fifo:
            status |= self.STATUS_RFNE
        if len(self.rx_fifo) >= self.FIFO_SIZE:
            status |= self.STATUS_RFF
        return status

    def _do_write_transaction(self):
        """Perform I2C write transaction."""
        if not self.tx_buffer:
            return

        addr = self.tar & 0x7F
        data = bytes(self.tx_buffer)
        self.tx_buffer.clear()

        self.log.debug(f"I2C Write: addr=0x{addr:02X} data={data.hex()}")

        if self.on_write:
            ack = self.on_write(addr, data)
            if not ack:
                self.raw_intr |= self.INT_TX_ABRT

        self.raw_intr |= self.INT_STOP_DET
        self._update_interrupts()

    def _do_read_transaction(self):
        """Perform I2C read transaction."""
        if self.pending_reads == 0:
            return

        addr = self.tar & 0x7F
        count = self.pending_reads
        self.pending_reads = 0

        self.log.debug(f"I2C Read: addr=0x{addr:02X} len={count}")

        if self.on_read:
            data = self.on_read(addr, count)
            for byte in data:
                if len(self.rx_fifo) < self.FIFO_SIZE:
                    self.rx_fifo.append(byte)

        self.raw_intr |= self.INT_STOP_DET
        self._update_interrupts()

    def _clear_interrupt(self, offset: int):
        """Clear specific interrupt."""
        clear_map = {
            self.IC_CLR_INTR: 0xFFF,
            self.IC_CLR_RX_UNDER: self.INT_RX_UNDER,
            self.IC_CLR_RX_OVER: self.INT_RX_OVER,
            self.IC_CLR_TX_OVER: self.INT_TX_OVER,
            self.IC_CLR_RD_REQ: self.INT_RD_REQ,
            self.IC_CLR_TX_ABRT: self.INT_TX_ABRT,
            self.IC_CLR_RX_DONE: self.INT_RX_DONE,
            self.IC_CLR_ACTIVITY: self.INT_ACTIVITY,
            self.IC_CLR_STOP_DET: self.INT_STOP_DET,
            self.IC_CLR_START_DET: self.INT_START_DET,
            self.IC_CLR_GEN_CALL: self.INT_GEN_CALL,
        }
        self.raw_intr &= ~clear_map.get(offset, 0)

    def _update_interrupts(self):
        """Update interrupt status."""
        # TX empty when below threshold
        if len(self.tx_fifo) <= self.tx_tl:
            self.raw_intr |= self.INT_TX_EMPTY
        else:
            self.raw_intr &= ~self.INT_TX_EMPTY

        # RX full when above threshold
        if len(self.rx_fifo) > self.rx_tl:
            self.raw_intr |= self.INT_RX_FULL
        else:
            self.raw_intr &= ~self.INT_RX_FULL

        if self.raw_intr & self.intr_mask:
            self.trigger_irq(1)


# =============================================================================
# ALIASES FOR BACKWARD COMPATIBILITY
# =============================================================================

# RP2040-specific aliases (these use the standard IP blocks)
RP2040UART = PL011UART
RP2040SPI = PrimeCellSSP
RP2040I2C = SynopsysDWI2C
