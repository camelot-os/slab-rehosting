"""
i.MX RT LPI2C Peripheral

Low-Power I2C used in i.MX RT series.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from typing import Optional, Callable, List, Dict
from .nxp_base import NXPPeripheral


class IMXRTLpi2c(NXPPeripheral):
    """
    i.MX RT Low-Power I2C.

    Features:
    - Master and slave modes
    - Standard/Fast/Fast+ mode (up to 1MHz)
    - High-speed mode support
    - Multi-master capable
    - FIFO with DMA support

    Memory Map:
        0x00: VERID - Version ID
        0x04: PARAM - Parameter
        0x10: MCR - Master control
        0x14: MSR - Master status
        0x18: MIER - Master interrupt enable
        0x1C: MDER - Master DMA enable
        0x20: MCFGR0 - Master config 0
        0x24: MCFGR1 - Master config 1
        0x28: MCFGR2 - Master config 2
        0x2C: MCFGR3 - Master config 3
        0x40: MDMR - Master data match
        0x48: MCCR0 - Master clock config 0
        0x50: MCCR1 - Master clock config 1
        0x58: MFCR - Master FIFO control
        0x5C: MFSR - Master FIFO status
        0x60: MTDR - Master transmit data
        0x70: MRDR - Master receive data
        0x110: SCR - Slave control
        0x114: SSR - Slave status
        0x118: SIER - Slave interrupt enable
        0x11C: SDER - Slave DMA enable
        0x120: SCFGR1 - Slave config 1
        0x124: SCFGR2 - Slave config 2
        0x140: SAMR - Slave address match
        0x158: SASR - Slave address status
        0x15C: STAR - Slave transmit ACK
        0x160: STDR - Slave transmit data
        0x170: SRDR - Slave receive data
    """

    # Register offsets
    VERID = 0x00
    PARAM = 0x04
    MCR = 0x10
    MSR = 0x14
    MIER = 0x18
    MDER = 0x1C
    MCFGR0 = 0x20
    MCFGR1 = 0x24
    MCFGR2 = 0x28
    MCFGR3 = 0x2C
    MDMR = 0x40
    MCCR0 = 0x48
    MCCR1 = 0x50
    MFCR = 0x58
    MFSR = 0x5C
    MTDR = 0x60
    MRDR = 0x70
    SCR = 0x110
    SSR = 0x114
    SIER = 0x118
    SDER = 0x11C
    SCFGR1 = 0x120
    SCFGR2 = 0x124
    SAMR = 0x140
    SASR = 0x158
    STAR = 0x15C
    STDR = 0x160
    SRDR = 0x170

    # MCR bits
    MCR_MEN = (1 << 0)        # Master enable
    MCR_RST = (1 << 1)        # Software reset
    MCR_DOZEN = (1 << 2)      # Doze mode enable
    MCR_DBGEN = (1 << 3)      # Debug enable
    MCR_RTF = (1 << 8)        # Reset transmit FIFO
    MCR_RRF = (1 << 9)        # Reset receive FIFO

    # MSR bits
    MSR_TDF = (1 << 0)        # Transmit data flag
    MSR_RDF = (1 << 1)        # Receive data flag
    MSR_EPF = (1 << 8)        # End packet flag
    MSR_SDF = (1 << 9)        # STOP detect flag
    MSR_NDF = (1 << 10)       # NACK detect flag
    MSR_ALF = (1 << 11)       # Arbitration lost flag
    MSR_FEF = (1 << 12)       # FIFO error flag
    MSR_PLTF = (1 << 13)      # Pin low timeout flag
    MSR_DMF = (1 << 14)       # Data match flag
    MSR_MBF = (1 << 24)       # Master busy flag
    MSR_BBF = (1 << 25)       # Bus busy flag

    # MTDR commands
    MTDR_CMD_TX = (0 << 8)    # Transmit data
    MTDR_CMD_RX = (1 << 8)    # Receive data
    MTDR_CMD_STOP = (2 << 8)  # Generate STOP
    MTDR_CMD_RX_DISC = (3 << 8)  # Receive and discard
    MTDR_CMD_START = (4 << 8)    # Generate START
    MTDR_CMD_START_NACK = (5 << 8)  # START with NACK
    MTDR_CMD_HS = (6 << 8)    # High-speed START
    MTDR_CMD_HS_NACK = (7 << 8)  # HS START with NACK

    def __init__(self, index: int, base: int):
        super().__init__(f"LPI2C{index}", base, 0x1000)
        self.index = index

        # Master registers
        self.mcr = 0
        self.msr = self.MSR_TDF
        self.mier = 0
        self.mder = 0
        self.mcfgr0 = 0
        self.mcfgr1 = 0
        self.mcfgr2 = 0
        self.mcfgr3 = 0
        self.mdmr = 0
        self.mccr0 = 0
        self.mccr1 = 0
        self.mfcr = 0

        # Slave registers
        self.scr = 0
        self.ssr = 0
        self.sier = 0
        self.sder = 0
        self.scfgr1 = 0
        self.scfgr2 = 0
        self.samr = 0

        # FIFOs
        self.tx_fifo: List[int] = []
        self.rx_fifo: List[int] = []
        self.fifo_depth = 4

        # Current transaction state
        self._current_addr = 0
        self._is_read = False

        # I2C devices (address -> callback)
        self.devices: Dict[int, Callable] = {}
        # Callback signature: (addr, is_read, data) -> response_byte or None

    def attach_device(self, address: int, callback: Callable):
        """Attach an I2C device at given address."""
        self.devices[address] = callback

    def _do_transaction(self, addr: int, is_read: bool, data: int = 0) -> Optional[int]:
        """Perform I2C transaction with device."""
        if addr in self.devices:
            return self.devices[addr](addr, is_read, data)
        return None  # NACK

    def _process_command(self, cmd_data: int):
        """Process master command."""
        cmd = (cmd_data >> 8) & 0x07
        data = cmd_data & 0xFF

        if cmd == 0:  # TX data
            if self._current_addr:
                result = self._do_transaction(self._current_addr, False, data)
                if result is None:
                    self.msr |= self.MSR_NDF
                self.msr |= self.MSR_EPF

        elif cmd == 1:  # RX data
            count = data + 1
            for _ in range(count):
                result = self._do_transaction(self._current_addr, True, 0)
                if result is not None:
                    if len(self.rx_fifo) < self.fifo_depth:
                        self.rx_fifo.append(result)
                    else:
                        self.msr |= self.MSR_FEF
                else:
                    self.msr |= self.MSR_NDF
                    break
            self.msr |= self.MSR_EPF

        elif cmd == 2:  # STOP
            self._current_addr = 0
            self.msr |= self.MSR_SDF
            self.msr &= ~(self.MSR_MBF | self.MSR_BBF)

        elif cmd in (4, 5):  # START
            self._current_addr = data >> 1
            self._is_read = bool(data & 1)
            self.msr |= self.MSR_MBF | self.MSR_BBF
            # Check if device exists
            if self._current_addr not in self.devices:
                self.msr |= self.MSR_NDF

    def _update_status(self):
        """Update status flags."""
        # TX flag
        tx_water = self.mfcr & 0x03
        if len(self.tx_fifo) <= tx_water:
            self.msr |= self.MSR_TDF
        else:
            self.msr &= ~self.MSR_TDF

        # RX flag
        rx_water = (self.mfcr >> 16) & 0x03
        if len(self.rx_fifo) > rx_water:
            self.msr |= self.MSR_RDF
        else:
            self.msr &= ~self.MSR_RDF

        # Check interrupts
        if (self.msr & self.mier) & 0x7F03:
            self.trigger_irq(1)

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.VERID:
            return 0x01000003
        elif offset == self.PARAM:
            return (self.fifo_depth << 8) | self.fifo_depth
        elif offset == self.MCR:
            return self.mcr
        elif offset == self.MSR:
            return self.msr
        elif offset == self.MIER:
            return self.mier
        elif offset == self.MDER:
            return self.mder
        elif offset == self.MCFGR0:
            return self.mcfgr0
        elif offset == self.MCFGR1:
            return self.mcfgr1
        elif offset == self.MCFGR2:
            return self.mcfgr2
        elif offset == self.MCFGR3:
            return self.mcfgr3
        elif offset == self.MDMR:
            return self.mdmr
        elif offset == self.MCCR0:
            return self.mccr0
        elif offset == self.MCCR1:
            return self.mccr1
        elif offset == self.MFCR:
            return self.mfcr
        elif offset == self.MFSR:
            return (len(self.rx_fifo) << 16) | len(self.tx_fifo)
        elif offset == self.MRDR:
            if self.rx_fifo:
                data = self.rx_fifo.pop(0)
                self._update_status()
                return data
            return (1 << 14)  # RXEMPTY flag
        elif offset == self.SCR:
            return self.scr
        elif offset == self.SSR:
            return self.ssr
        elif offset == self.SIER:
            return self.sier
        elif offset == self.SDER:
            return self.sder
        elif offset == self.SCFGR1:
            return self.scfgr1
        elif offset == self.SCFGR2:
            return self.scfgr2
        elif offset == self.SAMR:
            return self.samr
        elif offset == self.SASR:
            return 0
        elif offset == self.SRDR:
            return (1 << 14)  # RXEMPTY
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.MCR:
            if value & self.MCR_RST:
                self._reset()
                return
            if value & self.MCR_RTF:
                self.tx_fifo.clear()
            if value & self.MCR_RRF:
                self.rx_fifo.clear()
            self.mcr = value & ~(self.MCR_RST | self.MCR_RTF | self.MCR_RRF)
            self._update_status()
        elif offset == self.MSR:
            # W1C for flags
            self.msr &= ~(value & 0x7F00)
        elif offset == self.MIER:
            self.mier = value
        elif offset == self.MDER:
            self.mder = value
        elif offset == self.MCFGR0:
            self.mcfgr0 = value
        elif offset == self.MCFGR1:
            self.mcfgr1 = value
        elif offset == self.MCFGR2:
            self.mcfgr2 = value
        elif offset == self.MCFGR3:
            self.mcfgr3 = value
        elif offset == self.MDMR:
            self.mdmr = value
        elif offset == self.MCCR0:
            self.mccr0 = value
        elif offset == self.MCCR1:
            self.mccr1 = value
        elif offset == self.MFCR:
            self.mfcr = value
        elif offset == self.MTDR:
            if self.mcr & self.MCR_MEN:
                self._process_command(value)
                self._update_status()
        elif offset == self.SCR:
            self.scr = value
        elif offset == self.SSR:
            self.ssr &= ~(value & 0x0F00)
        elif offset == self.SIER:
            self.sier = value
        elif offset == self.SDER:
            self.sder = value
        elif offset == self.SCFGR1:
            self.scfgr1 = value
        elif offset == self.SCFGR2:
            self.scfgr2 = value
        elif offset == self.SAMR:
            self.samr = value
        elif offset == self.STAR:
            pass  # Slave ACK
        elif offset == self.STDR:
            pass  # Slave TX data

    def _reset(self):
        """Reset I2C to defaults."""
        self.mcr = 0
        self.msr = self.MSR_TDF
        self.mier = 0
        self.mder = 0
        self.mcfgr0 = 0
        self.mcfgr1 = 0
        self.mcfgr2 = 0
        self.mcfgr3 = 0
        self.mdmr = 0
        self.mccr0 = 0
        self.mccr1 = 0
        self.mfcr = 0
        self.scr = 0
        self.ssr = 0
        self.sier = 0
        self.sder = 0
        self.scfgr1 = 0
        self.scfgr2 = 0
        self.samr = 0
        self.tx_fifo.clear()
        self.rx_fifo.clear()
        self._current_addr = 0
