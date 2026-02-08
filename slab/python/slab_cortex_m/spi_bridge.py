#!/usr/bin/env python3
"""
SPI Bridge for MCUemu Multi-MCU Communication

This module provides an SPI bridge that connects two MCUemu peripheral servers,
allowing SPI master on one MCU to communicate with SPI slave on another.

Architecture:
    [MCU1/Master] <--TCP--> [Periph Server 1] <--SPI Bridge--> [Periph Server 2] <--TCP--> [MCU2/Slave]

The bridge:
1. Monitors SPI TX register writes from master
2. Forwards data to slave's RX buffer
3. Captures slave's TX response
4. Makes it available in master's RX register

Usage:
    bridge = SPIBridge(master_server, slave_server)
    bridge.connect_spi(master_spi_base=0x40013000, slave_spi_base=0x40003000)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import logging
from typing import Optional, Callable, List
from dataclasses import dataclass, field

log = logging.getLogger('SPIBridge')


# =============================================================================
# SPI REGISTER DEFINITIONS
# =============================================================================

# STM32-style SPI register offsets
class STM32_SPI:
    CR1 = 0x00      # Control register 1
    CR2 = 0x04      # Control register 2
    SR = 0x08       # Status register
    DR = 0x0C       # Data register
    CRCPR = 0x10    # CRC polynomial register
    RXCRCR = 0x14   # RX CRC register
    TXCRCR = 0x18   # TX CRC register

    # SR bits
    SR_RXNE = (1 << 0)   # RX buffer not empty
    SR_TXE = (1 << 1)    # TX buffer empty
    SR_BSY = (1 << 7)    # Busy flag

    # CR1 bits
    CR1_SPE = (1 << 6)   # SPI enable
    CR1_MSTR = (1 << 2)  # Master mode


# nRF52-style SPI/SPIM register offsets
class NRF52_SPIS:
    # Tasks
    TASKS_ACQUIRE = 0x024
    TASKS_RELEASE = 0x028
    # Events
    EVENTS_END = 0x104
    EVENTS_ACQUIRED = 0x128
    # Registers
    SHORTS = 0x200
    INTENSET = 0x304
    INTENCLR = 0x308
    SEMSTAT = 0x400
    STATUS = 0x440
    ENABLE = 0x500
    PSEL_SCK = 0x508
    PSEL_MISO = 0x50C
    PSEL_MOSI = 0x510
    PSEL_CSN = 0x514
    RXD_PTR = 0x534
    RXD_MAXCNT = 0x538
    RXD_AMOUNT = 0x53C
    TXD_PTR = 0x544
    TXD_MAXCNT = 0x548
    TXD_AMOUNT = 0x54C
    CONFIG = 0x554
    DEF = 0x55C
    ORC = 0x5C0


# =============================================================================
# SPI PERIPHERAL EMULATION
# =============================================================================

class SPIMasterPeripheral:
    """SPI Master peripheral with bridge support."""

    def __init__(self, name: str, base: int, size: int = 0x400):
        self.name = name
        self.base = base
        self.size = size
        self.log = logging.getLogger(f'SPI.{name}')

        # Registers
        self.cr1 = 0
        self.cr2 = 0
        self.sr = STM32_SPI.SR_TXE  # TX empty initially
        self.dr_tx = 0
        self.dr_rx = 0

        # Bridge callback
        self.on_transmit: Optional[Callable[[int], int]] = None

    def read(self, offset: int, size: int) -> int:
        if offset == STM32_SPI.CR1:
            return self.cr1
        elif offset == STM32_SPI.CR2:
            return self.cr2
        elif offset == STM32_SPI.SR:
            return self.sr
        elif offset == STM32_SPI.DR:
            # Reading DR clears RXNE
            value = self.dr_rx
            self.sr &= ~STM32_SPI.SR_RXNE
            self.log.debug(f"Read DR: 0x{value:02X}")
            return value
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == STM32_SPI.CR1:
            self.cr1 = value
            self.log.debug(f"CR1 = 0x{value:04X}")
        elif offset == STM32_SPI.CR2:
            self.cr2 = value
        elif offset == STM32_SPI.DR:
            self.dr_tx = value & 0xFF
            self.log.debug(f"Write DR: 0x{self.dr_tx:02X}")

            # If SPI enabled and we have a bridge callback, do transfer
            if (self.cr1 & STM32_SPI.CR1_SPE) and self.on_transmit:
                # Set busy
                self.sr |= STM32_SPI.SR_BSY
                self.sr &= ~STM32_SPI.SR_TXE

                # Do transfer via bridge
                self.dr_rx = self.on_transmit(self.dr_tx)
                self.log.debug(f"Transfer: TX=0x{self.dr_tx:02X} -> RX=0x{self.dr_rx:02X}")

                # Transfer complete
                self.sr &= ~STM32_SPI.SR_BSY
                self.sr |= STM32_SPI.SR_TXE | STM32_SPI.SR_RXNE


class SPISlavePeripheral:
    """SPI Slave peripheral with bridge support."""

    def __init__(self, name: str, base: int, size: int = 0x400):
        self.name = name
        self.base = base
        self.size = size
        self.log = logging.getLogger(f'SPI.{name}')

        # Registers (STM32 style)
        self.cr1 = 0
        self.cr2 = 0
        self.sr = STM32_SPI.SR_TXE
        self.dr_tx = 0  # Data to send when master clocks
        self.dr_rx = 0  # Data received from master

        # Callback when data received from master
        self.on_receive: Optional[Callable[[int], int]] = None

    def read(self, offset: int, size: int) -> int:
        if offset == STM32_SPI.CR1:
            return self.cr1
        elif offset == STM32_SPI.SR:
            return self.sr
        elif offset == STM32_SPI.DR:
            value = self.dr_rx
            self.sr &= ~STM32_SPI.SR_RXNE
            return value
        return 0

    def write(self, offset: int, size: int, value: int):
        if offset == STM32_SPI.CR1:
            self.cr1 = value
        elif offset == STM32_SPI.DR:
            # Slave preloads response
            self.dr_tx = value & 0xFF
            self.sr |= STM32_SPI.SR_TXE
            self.log.debug(f"Slave preload: 0x{self.dr_tx:02X}")

    def receive_from_master(self, data: int) -> int:
        """Called by bridge when master sends data."""
        self.dr_rx = data
        self.sr |= STM32_SPI.SR_RXNE
        self.log.debug(f"Slave RX: 0x{data:02X}, responding: 0x{self.dr_tx:02X}")

        response = self.dr_tx

        # If slave has callback, let it process and prepare next response
        if self.on_receive:
            next_response = self.on_receive(data)
            self.dr_tx = next_response & 0xFF

        return response


# =============================================================================
# SPI BRIDGE
# =============================================================================

@dataclass
class SPITransaction:
    """Record of an SPI transaction."""
    master_tx: int
    slave_rx: int
    slave_tx: int
    master_rx: int


class SPIBridge:
    """
    Bridge connecting SPI master and slave peripherals.

    This enables communication between two emulated MCUs via SPI.
    """

    def __init__(self):
        self.master: Optional[SPIMasterPeripheral] = None
        self.slave: Optional[SPISlavePeripheral] = None
        self.transactions: List[SPITransaction] = []
        self.log = logging.getLogger('SPIBridge')

    def connect(self, master: SPIMasterPeripheral, slave: SPISlavePeripheral):
        """Connect master and slave peripherals."""
        self.master = master
        self.slave = slave

        # Set up master's transmit callback to go through bridge
        master.on_transmit = self._handle_transfer
        self.log.info(f"Connected {master.name} (master) <-> {slave.name} (slave)")

    def _handle_transfer(self, master_data: int) -> int:
        """Handle SPI transfer from master to slave."""
        # Forward to slave
        slave_response = self.slave.receive_from_master(master_data)

        # Record transaction
        txn = SPITransaction(
            master_tx=master_data,
            slave_rx=master_data,
            slave_tx=slave_response,
            master_rx=slave_response
        )
        self.transactions.append(txn)

        self.log.debug(f"Transfer: MOSI=0x{master_data:02X} MISO=0x{slave_response:02X}")
        return slave_response

    def get_transaction_log(self) -> List[SPITransaction]:
        """Get list of all transactions."""
        return self.transactions.copy()

    def clear_log(self):
        """Clear transaction log."""
        self.transactions.clear()


# =============================================================================
# DUAL MCU TEST HARNESS
# =============================================================================

class DualMCUTestHarness:
    """
    Test harness for running two MCUs with SPI bridge.

    Provides:
    - Two peripheral servers (one per MCU)
    - SPI bridge connecting them
    - Transaction monitoring
    """

    def __init__(self, master_port: int = 5001, slave_port: int = 5002):
        self.master_port = master_port
        self.slave_port = slave_port

        # Peripheral instances
        self.master_spi = SPIMasterPeripheral("SPI1_Master", 0x40013000)
        self.slave_spi = SPISlavePeripheral("SPI1_Slave", 0x40013000)

        # SPI Bridge
        self.bridge = SPIBridge()
        self.bridge.connect(self.master_spi, self.slave_spi)

        # Servers
        self.master_server = None
        self.slave_server = None

        self.log = logging.getLogger('DualMCU')

    async def start(self):
        """Start both peripheral servers."""
        self.master_server = await asyncio.start_server(
            self._handle_master_client, 'localhost', self.master_port
        )
        self.slave_server = await asyncio.start_server(
            self._handle_slave_client, 'localhost', self.slave_port
        )
        self.log.info(f"Master server on port {self.master_port}")
        self.log.info(f"Slave server on port {self.slave_port}")

    async def stop(self):
        """Stop both servers."""
        if self.master_server:
            self.master_server.close()
            await self.master_server.wait_closed()
        if self.slave_server:
            self.slave_server.close()
            await self.slave_server.wait_closed()

    async def _handle_master_client(self, reader, writer):
        """Handle master MCU peripheral requests."""
        await self._handle_client(reader, writer, self.master_spi, "Master")

    async def _handle_slave_client(self, reader, writer):
        """Handle slave MCU peripheral requests."""
        await self._handle_client(reader, writer, self.slave_spi, "Slave")

    async def _handle_client(self, reader, writer, spi_periph, name):
        """Handle peripheral requests for an MCU."""
        import struct

        self.log.info(f"{name} MCU connected")
        try:
            while True:
                cmd = await reader.read(1)
                if not cmd:
                    break

                if cmd == b'R':
                    # Read: addr(4) + size(4) + secure(1)
                    data = await reader.read(9)
                    addr, size, secure = struct.unpack('<IIB', data)
                    offset = addr - spi_periph.base

                    if 0 <= offset < spi_periph.size:
                        value = spi_periph.read(offset, size)
                    else:
                        value = 0

                    response = struct.pack('<IB', value, 0)
                    writer.write(response)
                    await writer.drain()

                elif cmd == b'W':
                    # Write: addr(4) + size(4) + value(4) + secure(1)
                    data = await reader.read(13)
                    addr, size, value, secure = struct.unpack('<IIIB', data)
                    offset = addr - spi_periph.base

                    if 0 <= offset < spi_periph.size:
                        spi_periph.write(offset, size, value)

                    response = struct.pack('<IB', value, 0)
                    writer.write(response)
                    await writer.drain()

        except Exception as e:
            self.log.error(f"{name} error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            self.log.info(f"{name} MCU disconnected")


# =============================================================================
# MAIN
# =============================================================================

async def demo():
    """Demo the SPI bridge with simulated transfers."""
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)-12s: %(message)s'
    )

    print("=" * 60)
    print("SPI Bridge Demo")
    print("=" * 60)

    # Create peripherals
    master = SPIMasterPeripheral("STM32_SPI1", 0x40013000)
    slave = SPISlavePeripheral("NRF_SPIS", 0x40003000)

    # Create bridge
    bridge = SPIBridge()
    bridge.connect(master, slave)

    # Set up slave response pattern
    response_data = [0xAA, 0x55, 0x12, 0x34]
    response_idx = [0]

    def slave_handler(rx_data: int) -> int:
        """Slave processes received byte and prepares response."""
        idx = response_idx[0]
        response_idx[0] = (idx + 1) % len(response_data)
        return response_data[idx]

    slave.on_receive = slave_handler
    slave.dr_tx = response_data[0]  # Preload first response

    # Enable master SPI
    master.write(STM32_SPI.CR1, 4, STM32_SPI.CR1_SPE | STM32_SPI.CR1_MSTR)

    # Do some transfers
    test_data = [0x01, 0x02, 0x03, 0x04]
    print("\nPerforming SPI transfers:")
    for tx_byte in test_data:
        master.write(STM32_SPI.DR, 4, tx_byte)
        rx_byte = master.read(STM32_SPI.DR, 4)
        print(f"  TX: 0x{tx_byte:02X} -> RX: 0x{rx_byte:02X}")

    # Show transaction log
    print("\nTransaction log:")
    for i, txn in enumerate(bridge.transactions):
        print(f"  [{i}] MOSI: 0x{txn.master_tx:02X} MISO: 0x{txn.slave_tx:02X}")

    print("\nDemo complete!")


if __name__ == '__main__':
    asyncio.run(demo())
