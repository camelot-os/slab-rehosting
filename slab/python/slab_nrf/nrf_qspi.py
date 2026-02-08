"""
NRF QSPI - Quad SPI with EasyDMA

The nRF52840 QSPI peripheral provides:
- Execute-in-Place (XIP) support for external flash
- Quad-SPI (4-lane) data transfers
- EasyDMA for autonomous data movement
- Custom instruction support for flash commands
- Deep Power-Down mode support

Register Map (based on nRF52840 Product Specification):
    0x000: TASKS_ACTIVATE    - Activate QSPI interface
    0x004: TASKS_READSTART   - Start read from external flash
    0x008: TASKS_WRITESTART  - Start write to external flash
    0x00C: TASKS_ERASESTART  - Start erase of external flash
    0x010: TASKS_DEACTIVATE  - Deactivate QSPI interface
    0x100: EVENTS_READY      - QSPI ready
    0x500: ENABLE
    0x504: READ.SRC          - Flash source address
    0x508: READ.DST          - RAM destination address
    0x50C: READ.CNT          - Read byte count
    0x510: WRITE.DST         - Flash destination address
    0x514: WRITE.SRC         - RAM source address
    0x518: WRITE.CNT         - Write byte count
    0x51C: ERASE.PTR         - Flash erase address
    0x520: ERASE.LEN         - Erase size (0=4KB, 1=64KB, 2=all)
    0x544: IFCONFIG0         - Interface configuration 0
    0x604: STATUS            - Status register
    0x634: CINSTRCONF        - Custom instruction configuration
    0x638: CINSTRDAT0        - Custom instruction data 0
    0x63C: CINSTRDAT1        - Custom instruction data 1

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable
from .nrf_base import NRFPeripheral


class NRFQSPI(NRFPeripheral):
    """
    NRF52840 QSPI (Quad SPI with EasyDMA).

    This peripheral provides high-speed access to external QSPI flash
    with support for Execute-in-Place (XIP) and custom flash commands.
    """

    # Tasks
    TASKS_ACTIVATE = 0x000
    TASKS_READSTART = 0x004
    TASKS_WRITESTART = 0x008
    TASKS_ERASESTART = 0x00C
    TASKS_DEACTIVATE = 0x010

    # Events
    EVENTS_READY = 0x100

    # Registers
    ENABLE = 0x500
    READ_SRC = 0x504      # Flash address to read from
    READ_DST = 0x508      # RAM address to write to
    READ_CNT = 0x50C      # Number of bytes to read
    WRITE_DST = 0x510     # Flash address to write to
    WRITE_SRC = 0x514     # RAM address to read from
    WRITE_CNT = 0x518     # Number of bytes to write
    ERASE_PTR = 0x51C     # Flash address to erase
    ERASE_LEN = 0x520     # Erase length (0=4KB, 1=64KB, 2=all)

    # Pin selection
    PSEL_SCK = 0x524
    PSEL_CSN = 0x528
    PSEL_IO0 = 0x52C      # MOSI / IO0
    PSEL_IO1 = 0x530      # MISO / IO1
    PSEL_IO2 = 0x534      # IO2
    PSEL_IO3 = 0x538      # IO3

    # Configuration
    XIPOFFSET = 0x540
    IFCONFIG0 = 0x544
    IFCONFIG1 = 0x600
    STATUS = 0x604
    DPMDUR = 0x614
    ADDRCONF = 0x624
    CINSTRCONF = 0x634
    CINSTRDAT0 = 0x638
    CINSTRDAT1 = 0x63C
    IFTIMING = 0x6C0

    # IFCONFIG0 bits
    IFCONFIG0_READOC_FASTREAD = 0    # Fast read (single)
    IFCONFIG0_READOC_READ2O = 1      # Read 2-bit output
    IFCONFIG0_READOC_READ2IO = 2     # Read 2-bit I/O
    IFCONFIG0_READOC_READ4O = 3      # Read 4-bit output (QSPI)
    IFCONFIG0_READOC_READ4IO = 4     # Read 4-bit I/O (QSPI)

    IFCONFIG0_WRITEOC_PP = 0         # Page program (single)
    IFCONFIG0_WRITEOC_PP2O = 1       # Page program 2-bit output
    IFCONFIG0_WRITEOC_PP4O = 2       # Page program 4-bit output
    IFCONFIG0_WRITEOC_PP4IO = 3      # Page program 4-bit I/O

    # ERASE_LEN values
    ERASE_LEN_4KB = 0
    ERASE_LEN_64KB = 1
    ERASE_LEN_ALL = 2

    # CINSTRCONF bits
    CINSTRCONF_OPCODE_SHIFT = 0
    CINSTRCONF_LENGTH_SHIFT = 8
    CINSTRCONF_LIO2_SHIFT = 12
    CINSTRCONF_LIO3_SHIFT = 13
    CINSTRCONF_WIPWAIT_SHIFT = 14
    CINSTRCONF_WREN_SHIFT = 15
    CINSTRCONF_LFEN_SHIFT = 16
    CINSTRCONF_LFSTOP_SHIFT = 17

    def __init__(self, base: int = 0x40029000):
        super().__init__("QSPI", base, 0x1000, irq=37)

        # State
        self.enable = 0
        self.activated = False

        # Read configuration
        self.read_src = 0
        self.read_dst = 0
        self.read_cnt = 0

        # Write configuration
        self.write_dst = 0
        self.write_src = 0
        self.write_cnt = 0

        # Erase configuration
        self.erase_ptr = 0
        self.erase_len = 0

        # Pin selection
        self.psel_sck = 0xFFFFFFFF
        self.psel_csn = 0xFFFFFFFF
        self.psel_io = [0xFFFFFFFF] * 4

        # Configuration
        self.xipoffset = 0
        self.ifconfig0 = 0
        self.ifconfig1 = 0
        self.status = 0
        self.dpmdur = 0
        self.addrconf = 0
        self.cinstrconf = 0
        self.cinstrdat0 = 0
        self.cinstrdat1 = 0
        self.iftiming = 0

        # Memory access callbacks for EasyDMA
        self.mem_read: Optional[Callable[[int, int], bytes]] = None
        self.mem_write: Optional[Callable[[int, bytes], None]] = None

        # Flash access callback
        # Called with: (operation, address, data) -> bytes
        # Operations: 'read', 'write', 'erase_4k', 'erase_64k', 'erase_all', 'custom'
        self.on_flash_access: Optional[Callable[[str, int, bytes], bytes]] = None

        # Custom instruction callback
        # Called with: (opcode, data_in) -> data_out
        self.on_custom_instruction: Optional[Callable[[int, bytes], bytes]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.ENABLE:
            return self.enable
        elif offset == self.READ_SRC:
            return self.read_src
        elif offset == self.READ_DST:
            return self.read_dst
        elif offset == self.READ_CNT:
            return self.read_cnt
        elif offset == self.WRITE_DST:
            return self.write_dst
        elif offset == self.WRITE_SRC:
            return self.write_src
        elif offset == self.WRITE_CNT:
            return self.write_cnt
        elif offset == self.ERASE_PTR:
            return self.erase_ptr
        elif offset == self.ERASE_LEN:
            return self.erase_len
        elif offset == self.PSEL_SCK:
            return self.psel_sck
        elif offset == self.PSEL_CSN:
            return self.psel_csn
        elif offset == self.PSEL_IO0:
            return self.psel_io[0]
        elif offset == self.PSEL_IO1:
            return self.psel_io[1]
        elif offset == self.PSEL_IO2:
            return self.psel_io[2]
        elif offset == self.PSEL_IO3:
            return self.psel_io[3]
        elif offset == self.XIPOFFSET:
            return self.xipoffset
        elif offset == self.IFCONFIG0:
            return self.ifconfig0
        elif offset == self.IFCONFIG1:
            return self.ifconfig1
        elif offset == self.STATUS:
            return self.status
        elif offset == self.DPMDUR:
            return self.dpmdur
        elif offset == self.ADDRCONF:
            return self.addrconf
        elif offset == self.CINSTRCONF:
            return self.cinstrconf
        elif offset == self.CINSTRDAT0:
            return self.cinstrdat0
        elif offset == self.CINSTRDAT1:
            return self.cinstrdat1
        elif offset == self.IFTIMING:
            return self.iftiming
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.ENABLE:
            self.enable = value
        elif offset == self.READ_SRC:
            self.read_src = value
        elif offset == self.READ_DST:
            self.read_dst = value
        elif offset == self.READ_CNT:
            self.read_cnt = value
        elif offset == self.WRITE_DST:
            self.write_dst = value
        elif offset == self.WRITE_SRC:
            self.write_src = value
        elif offset == self.WRITE_CNT:
            self.write_cnt = value
        elif offset == self.ERASE_PTR:
            self.erase_ptr = value
        elif offset == self.ERASE_LEN:
            self.erase_len = value
        elif offset == self.PSEL_SCK:
            self.psel_sck = value
        elif offset == self.PSEL_CSN:
            self.psel_csn = value
        elif offset == self.PSEL_IO0:
            self.psel_io[0] = value
        elif offset == self.PSEL_IO1:
            self.psel_io[1] = value
        elif offset == self.PSEL_IO2:
            self.psel_io[2] = value
        elif offset == self.PSEL_IO3:
            self.psel_io[3] = value
        elif offset == self.XIPOFFSET:
            self.xipoffset = value
        elif offset == self.IFCONFIG0:
            self.ifconfig0 = value
        elif offset == self.IFCONFIG1:
            self.ifconfig1 = value
        elif offset == self.DPMDUR:
            self.dpmdur = value
        elif offset == self.ADDRCONF:
            self.addrconf = value
        elif offset == self.CINSTRCONF:
            self.cinstrconf = value
            # Custom instruction triggers immediately when CINSTRCONF is written
            self._execute_custom_instruction()
        elif offset == self.CINSTRDAT0:
            self.cinstrdat0 = value
        elif offset == self.CINSTRDAT1:
            self.cinstrdat1 = value
        elif offset == self.IFTIMING:
            self.iftiming = value

    def _handle_task(self, offset: int):
        if offset == self.TASKS_ACTIVATE:
            self._activate()
        elif offset == self.TASKS_READSTART:
            self._start_read()
        elif offset == self.TASKS_WRITESTART:
            self._start_write()
        elif offset == self.TASKS_ERASESTART:
            self._start_erase()
        elif offset == self.TASKS_DEACTIVATE:
            self._deactivate()

    def _activate(self):
        """Activate QSPI interface."""
        if self.enable != 1:
            return

        self.activated = True
        self.log.debug("QSPI activated")
        self.set_event(self.EVENTS_READY)

    def _deactivate(self):
        """Deactivate QSPI interface."""
        self.activated = False
        self.log.debug("QSPI deactivated")
        self.set_event(self.EVENTS_READY)

    def _start_read(self):
        """Start read from external flash."""
        if not self.activated or self.enable != 1:
            return

        self.log.debug(f"QSPI read: flash 0x{self.read_src:08X} -> RAM 0x{self.read_dst:08X}, {self.read_cnt} bytes")

        if self.on_flash_access and self.mem_write:
            # Read from flash
            data = self.on_flash_access('read', self.read_src, bytes(self.read_cnt))

            # Write to RAM via DMA
            if data:
                self.mem_write(self.read_dst, data[:self.read_cnt])

        self.set_event(self.EVENTS_READY)

    def _start_write(self):
        """Start write to external flash."""
        if not self.activated or self.enable != 1:
            return

        self.log.debug(f"QSPI write: RAM 0x{self.write_src:08X} -> flash 0x{self.write_dst:08X}, {self.write_cnt} bytes")

        if self.on_flash_access and self.mem_read:
            # Read from RAM via DMA
            data = self.mem_read(self.write_src, self.write_cnt)

            # Write to flash
            if data:
                self.on_flash_access('write', self.write_dst, data)

        self.set_event(self.EVENTS_READY)

    def _start_erase(self):
        """Start erase of external flash."""
        if not self.activated or self.enable != 1:
            return

        if self.erase_len == self.ERASE_LEN_4KB:
            op = 'erase_4k'
            self.log.debug(f"QSPI erase 4KB at 0x{self.erase_ptr:08X}")
        elif self.erase_len == self.ERASE_LEN_64KB:
            op = 'erase_64k'
            self.log.debug(f"QSPI erase 64KB at 0x{self.erase_ptr:08X}")
        else:
            op = 'erase_all'
            self.log.debug("QSPI erase all")

        if self.on_flash_access:
            self.on_flash_access(op, self.erase_ptr, b'')

        self.set_event(self.EVENTS_READY)

    def _execute_custom_instruction(self):
        """Execute a custom flash instruction."""
        if not self.activated or self.enable != 1:
            return

        opcode = (self.cinstrconf >> self.CINSTRCONF_OPCODE_SHIFT) & 0xFF
        length = (self.cinstrconf >> self.CINSTRCONF_LENGTH_SHIFT) & 0x0F
        wipwait = (self.cinstrconf >> self.CINSTRCONF_WIPWAIT_SHIFT) & 0x01
        wren = (self.cinstrconf >> self.CINSTRCONF_WREN_SHIFT) & 0x01

        # Build data from CINSTRDAT0/1 (up to 8 bytes)
        data_in = bytearray()
        if length > 1:
            for i in range(min(length - 1, 4)):
                data_in.append((self.cinstrdat0 >> (i * 8)) & 0xFF)
        if length > 5:
            for i in range(min(length - 5, 4)):
                data_in.append((self.cinstrdat1 >> (i * 8)) & 0xFF)

        self.log.debug(f"QSPI custom instruction: opcode=0x{opcode:02X}, len={length}, wren={wren}, data={data_in.hex()}")

        if self.on_custom_instruction:
            # Execute custom instruction
            result = self.on_custom_instruction(opcode, bytes(data_in))

            # Store result in CINSTRDAT0/1
            if result:
                self.cinstrdat0 = 0
                self.cinstrdat1 = 0
                for i, b in enumerate(result[:4]):
                    self.cinstrdat0 |= (b << (i * 8))
                for i, b in enumerate(result[4:8]):
                    self.cinstrdat1 |= (b << (i * 8))

        self.set_event(self.EVENTS_READY)
