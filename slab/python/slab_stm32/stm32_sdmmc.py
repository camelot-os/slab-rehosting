"""
STM32 SDMMC Controller Emulation

Implements the SDMMC peripheral found in STM32U5xx (and similar).
Supports SD protocol command/response, FIFO data transfer, and
block-level callbacks for virtual SD card integration.

Reference: RM0456 (STM32U5) SDMMC chapter.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from collections import deque
from typing import Optional, Callable

from .stm32_base import STM32Peripheral, STATUS_OK


class STM32SDMMC(STM32Peripheral):
    """
    STM32 SDMMC controller.

    Handles SD/SDHC/SDXC command protocol, response generation, and
    data FIFO for block read/write operations.

    Register map (RM0456):
        0x00: POWER      Power control
        0x04: CLKCR      Clock control
        0x08: ARG        Command argument
        0x0C: CMD        Command register
        0x10: RESPCMD    Response command index
        0x14: RESP1      Response 1
        0x18: RESP2      Response 2
        0x1C: RESP3      Response 3
        0x20: RESP4      Response 4
        0x24: DTIMER     Data timer
        0x28: DLEN       Data length
        0x2C: DCTRL      Data control
        0x30: DCOUNT     Data counter (remaining)
        0x34: STA        Status (read-only, computed)
        0x38: ICR        Interrupt clear (W1C)
        0x3C: MASK       Interrupt mask
        0x40: ACKTIME    Acknowledgement timeout
        0x50: IDMACTRL   Internal DMA control
        0x54: IDMABSIZE  Internal DMA buffer size
        0x58: IDMABASER  Internal DMA buffer base
        0x80: FIFO       Data FIFO (32 words)
    """

    # Register offsets
    POWER     = 0x00
    CLKCR     = 0x04
    ARG       = 0x08
    CMD       = 0x0C
    RESPCMD   = 0x10
    RESP1     = 0x14
    RESP2     = 0x18
    RESP3     = 0x1C
    RESP4     = 0x20
    DTIMER    = 0x24
    DLEN      = 0x28
    DCTRL     = 0x2C
    DCOUNT    = 0x30
    STA       = 0x34
    ICR       = 0x38
    MASK      = 0x3C
    ACKTIME   = 0x40
    IDMACTRL  = 0x50
    IDMABSIZE = 0x54
    IDMABASER = 0x58
    FIFO      = 0x80

    # STA bits
    STA_CCRCFAIL  = 1 << 0
    STA_DCRCFAIL  = 1 << 1
    STA_CTIMEOUT  = 1 << 2
    STA_DTIMEOUT  = 1 << 3
    STA_TXUNDERR  = 1 << 4
    STA_RXOVERR   = 1 << 5
    STA_CMDREND   = 1 << 6
    STA_CMDSENT   = 1 << 7
    STA_DATAEND   = 1 << 8
    STA_DHOLD     = 1 << 9
    STA_DBCKEND   = 1 << 10
    STA_DABORT    = 1 << 11
    STA_DPSMACT   = 1 << 12
    STA_CPSMACT   = 1 << 13
    STA_TXFIFOHE  = 1 << 14
    STA_RXFIFOHF  = 1 << 15
    STA_TXFIFOF   = 1 << 16
    STA_RXFIFOF   = 1 << 17
    STA_TXFIFOE   = 1 << 18
    STA_RXFIFOE   = 1 << 19
    STA_BUSYD0END = 1 << 21
    STA_SDIOIT    = 1 << 22
    STA_ACKFAIL   = 1 << 23
    STA_ACKTIMEOUT = 1 << 24
    STA_VSWEND    = 1 << 25
    STA_CKSTOP    = 1 << 26
    STA_IDMATE    = 1 << 27
    STA_IDMABTC   = 1 << 28

    # CMD bits
    CMD_CMDINDEX = 0x3F
    CMD_CMDTRANS = 1 << 6   # SDMMCv2: auto-start data transfer
    CMD_WAITRESP = 0x3 << 8 # SDMMCv2: bits [9:8]
    CMD_CPSMEN   = 1 << 12

    # DCTRL bits
    DCTRL_DTEN   = 1 << 0
    DCTRL_DTDIR  = 1 << 1   # 0=host-to-card, 1=card-to-host
    DCTRL_DTMODE = 0x3 << 2
    DCTRL_DBLOCKSIZE = 0xF << 4
    DCTRL_FIFORST = 1 << 13

    # SD card states
    SD_IDLE           = 0
    SD_READY          = 1
    SD_IDENTIFICATION = 2
    SD_STANDBY        = 3
    SD_TRANSFER       = 4
    SD_SENDING        = 5
    SD_RECEIVING      = 6

    # SD response types
    RESP_NONE  = 0
    RESP_SHORT = 1  # 48-bit (R1, R3, R6, R7)
    RESP_LONG  = 3  # 136-bit (R2)

    # Default card identity
    _DEFAULT_CID = bytes([
        0x03,                   # MID (manufacturer)
        0x53, 0x44,             # OID ("SD")
        0x53, 0x4C, 0x33, 0x32, 0x47,  # PNM ("SL32G")
        0x80,                   # PRV (product revision 8.0)
        0xDE, 0xAD, 0xBE, 0xEF,  # PSN (serial)
        0x01, 0x9A,             # MDT (Jan 2026)
        0x00,                   # CRC (placeholder)
    ])

    _DEFAULT_SCR = bytes([
        0x02, 0x35,  # SCR structure 0, SD spec v3, bus widths 1+4
        0x80, 0x00,  # SD security v2, ex_security 0
        0x00, 0x00, 0x00, 0x00,
    ])

    def __init__(self, index: int = 1, base: int = 0x420C8000, irq: int = 78):
        super().__init__(f"SDMMC{index}", base, 0x400, irq)
        self.index = index

        # Registers
        self.power = 0
        self.clkcr = 0
        self.arg = 0
        self.cmd = 0
        self.respcmd = 0
        self.resp = [0, 0, 0, 0]
        self.dtimer = 0
        self.dlen = 0
        self.dctrl = 0
        self.dcount = 0
        self.mask = 0
        self.acktime = 0
        self.idmactrl = 0
        self.idmabsize = 0
        self.idmabaser = 0

        # Status flags (sticky, cleared via ICR)
        self._sta_flags = 0

        # FIFO (32 words = 128 bytes)
        self._rx_fifo: deque = deque(maxlen=32)
        self._tx_fifo: deque = deque(maxlen=32)

        # SD card state machine
        self._sd_state = self.SD_IDLE
        self._app_cmd = False  # Next command is ACMD
        self._rca = 0x0001     # Relative Card Address
        self._card_status = 0  # R1 card status bits
        self._capacity_mb = 256
        self._bus_width = 1    # 1 or 4 bit

        # Pending data transfer
        self._data_buf = bytearray()
        self._data_offset = 0

        # External callbacks (wired by board_builder)
        self.on_block_read: Optional[Callable[[int, int], bytes]] = None
        self.on_block_write: Optional[Callable[[int, bytes], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.POWER:
            return self.power
        elif offset == self.CLKCR:
            return self.clkcr
        elif offset == self.ARG:
            return self.arg
        elif offset == self.CMD:
            return self.cmd
        elif offset == self.RESPCMD:
            return self.respcmd
        elif offset == self.RESP1:
            return self.resp[0]
        elif offset == self.RESP2:
            return self.resp[1]
        elif offset == self.RESP3:
            return self.resp[2]
        elif offset == self.RESP4:
            return self.resp[3]
        elif offset == self.DTIMER:
            return self.dtimer
        elif offset == self.DLEN:
            return self.dlen
        elif offset == self.DCTRL:
            return self.dctrl
        elif offset == self.DCOUNT:
            return self.dcount
        elif offset == self.STA:
            return self._compute_sta()
        elif offset == self.ICR:
            return 0  # Write-only
        elif offset == self.MASK:
            return self.mask
        elif offset == self.ACKTIME:
            return self.acktime
        elif offset == self.IDMACTRL:
            return self.idmactrl
        elif offset == self.IDMABSIZE:
            return self.idmabsize
        elif offset == self.IDMABASER:
            return self.idmabaser
        elif 0x80 <= offset <= 0xFC:
            return self._read_fifo()
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.POWER:
            self.power = value & 0x1F
        elif offset == self.CLKCR:
            self.clkcr = value
        elif offset == self.ARG:
            self.arg = value
        elif offset == self.CMD:
            self.cmd = value
            if value & self.CMD_CPSMEN:
                self._process_command(value)
        elif offset == self.DTIMER:
            self.dtimer = value
        elif offset == self.DLEN:
            self.dlen = value & 0x01FFFFFF
        elif offset == self.DCTRL:
            old = self.dctrl
            self.dctrl = value
            if (value & self.DCTRL_FIFORST):
                self._rx_fifo.clear()
                self._tx_fifo.clear()
                self.dctrl &= ~self.DCTRL_FIFORST
            if (value & self.DCTRL_DTEN) and not (old & self.DCTRL_DTEN):
                self._start_data_transfer()
        elif offset == self.ICR:
            self._sta_flags &= ~value
            self._update_irq()
        elif offset == self.MASK:
            self.mask = value
            self._update_irq()
        elif offset == self.ACKTIME:
            self.acktime = value & 0x01FFFFFF
        elif offset == self.IDMACTRL:
            self.idmactrl = value
        elif offset == self.IDMABSIZE:
            self.idmabsize = value
        elif offset == self.IDMABASER:
            self.idmabaser = value
        elif 0x80 <= offset <= 0xFC:
            self._write_fifo(value)

    def _compute_sta(self) -> int:
        """Compute STA register (sticky flags + dynamic FIFO status)."""
        sta = self._sta_flags

        # Dynamic FIFO flags
        rx_count = len(self._rx_fifo)
        tx_count = len(self._tx_fifo)

        if tx_count == 0:
            sta |= self.STA_TXFIFOE
        if tx_count < 16:
            sta |= self.STA_TXFIFOHE
        if tx_count >= 32:
            sta |= self.STA_TXFIFOF

        if rx_count == 0:
            sta |= self.STA_RXFIFOE
        if rx_count >= 16:
            sta |= self.STA_RXFIFOHF
        if rx_count >= 32:
            sta |= self.STA_RXFIFOF

        return sta

    def _read_fifo(self) -> int:
        """Read one word from RX FIFO."""
        if self._rx_fifo:
            val = self._rx_fifo.popleft()
            # Check if all data consumed
            if not self._rx_fifo and self._data_offset >= len(self._data_buf):
                self._sta_flags |= self.STA_DATAEND | self.STA_DBCKEND
                self.dcount = 0
                self._update_irq()
            elif len(self._rx_fifo) < 16 and self._data_offset < len(self._data_buf):
                self._fill_rx_fifo()
            return val
        return 0

    def _write_fifo(self, value: int):
        """Write one word to TX FIFO."""
        self._tx_fifo.append(value)  # maxlen=32 handles overflow
        # Accumulate data for write transfers
        self._data_buf.extend(value.to_bytes(4, 'little'))
        self._data_offset += 4
        if self._data_offset >= self.dlen:
            self._complete_write_transfer()

    def _fill_rx_fifo(self):
        """Refill RX FIFO from data buffer."""
        while len(self._rx_fifo) < 32 and self._data_offset < len(self._data_buf):
            end = min(self._data_offset + 4, len(self._data_buf))
            chunk = self._data_buf[self._data_offset:end]
            if len(chunk) < 4:
                chunk = chunk + b'\x00' * (4 - len(chunk))
            word = int.from_bytes(chunk, 'little')
            self._rx_fifo.append(word)
            self._data_offset += 4

    def _start_data_transfer(self):
        """Handle DCTRL.DTEN -- start data phase."""
        if self.dctrl & self.DCTRL_DTDIR:
            # Card-to-host (read)
            self.dcount = self.dlen
            self._data_offset = 0
            self._fill_rx_fifo()
        else:
            # Host-to-card (write)
            self._data_buf = bytearray()
            self._data_offset = 0
            self.dcount = self.dlen

    def _complete_write_transfer(self):
        """Complete a write data transfer."""
        # Write data to SD card
        if self.on_block_write and self._data_buf:
            block_addr = self._last_block_addr if hasattr(self, '_last_block_addr') else 0
            self.on_block_write(block_addr, bytes(self._data_buf[:self.dlen]))
        self._sta_flags |= self.STA_DATAEND | self.STA_DBCKEND
        self.dcount = 0
        self._tx_fifo.clear()
        self._update_irq()

    def _process_command(self, cmd_reg: int):
        """Process an SD command when CPSMEN is set."""
        cmd_index = cmd_reg & self.CMD_CMDINDEX
        waitresp = (cmd_reg >> 8) & 0x3
        arg = self.arg
        has_cmdtrans = bool(cmd_reg & self.CMD_CMDTRANS)

        self.respcmd = cmd_index
        self.resp = [0, 0, 0, 0]

        if self._app_cmd:
            self._app_cmd = False
            self._process_acmd(cmd_index, arg, waitresp)
            return

        self.log.debug(f"{self.name} CMD{cmd_index} ARG=0x{arg:08X} WAITRESP={waitresp}")

        if cmd_index == 0:      # GO_IDLE_STATE
            self._sd_state = self.SD_IDLE
            self._sta_flags |= self.STA_CMDSENT
        elif cmd_index == 2:    # ALL_SEND_CID
            self._cmd2_all_send_cid()
            self._sd_state = self.SD_IDENTIFICATION
        elif cmd_index == 3:    # SEND_RELATIVE_ADDR
            self._cmd3_send_rca()
            self._sd_state = self.SD_STANDBY
        elif cmd_index == 7:    # SELECT_CARD
            self._cmd7_select(arg)
        elif cmd_index == 8:    # SEND_IF_COND
            self._cmd8_send_if_cond(arg)
        elif cmd_index == 9:    # SEND_CSD
            self._cmd9_send_csd()
        elif cmd_index == 12:   # STOP_TRANSMISSION
            self.resp[0] = self._make_r1()
            self._sta_flags |= self.STA_CMDREND
            self._sd_state = self.SD_TRANSFER
        elif cmd_index == 13:   # SEND_STATUS
            self.resp[0] = self._make_r1()
            self._sta_flags |= self.STA_CMDREND
        elif cmd_index == 16:   # SET_BLOCKLEN
            self.resp[0] = self._make_r1()
            self._sta_flags |= self.STA_CMDREND
        elif cmd_index == 17:   # READ_SINGLE_BLOCK
            self._cmd17_read_block(arg)
        elif cmd_index == 18:   # READ_MULTIPLE_BLOCK
            self._cmd18_read_multi(arg)
        elif cmd_index == 24:   # WRITE_BLOCK
            self._cmd24_write_block(arg)
        elif cmd_index == 25:   # WRITE_MULTIPLE_BLOCK
            self._cmd25_write_multi(arg)
        elif cmd_index == 55:   # APP_CMD
            self._app_cmd = True
            self.resp[0] = self._make_r1() | (1 << 5)  # APP_CMD bit
            self._sta_flags |= self.STA_CMDREND
        else:
            # Unknown command -- respond with R1 if response expected
            if waitresp != 0:
                self.resp[0] = self._make_r1()
                self._sta_flags |= self.STA_CMDREND
            else:
                self._sta_flags |= self.STA_CMDSENT

        # CMDTRANS: auto-start data phase (SDMMCv2, used by HAL_SD)
        if has_cmdtrans and cmd_index in (17, 18, 24, 25):
            self._start_data_transfer()

        self._update_irq()

    def _process_acmd(self, cmd_index: int, arg: int, waitresp: int):
        """Process application-specific command (after CMD55)."""
        self.log.debug(f"{self.name} ACMD{cmd_index} ARG=0x{arg:08X}")

        if cmd_index == 6:     # SET_BUS_WIDTH
            width = arg & 0x3
            self._bus_width = 4 if width == 2 else 1
            self.resp[0] = self._make_r1()
            self._sta_flags |= self.STA_CMDREND
        elif cmd_index == 41:  # SD_SEND_OP_COND
            self._acmd41_send_op_cond(arg)
        elif cmd_index == 51:  # SEND_SCR
            self._acmd51_send_scr()
        else:
            if waitresp != 0:
                self.resp[0] = self._make_r1()
                self._sta_flags |= self.STA_CMDREND
            else:
                self._sta_flags |= self.STA_CMDSENT

        # CMDTRANS: auto-start data phase for ACMD51 (SCR read)
        if self.cmd & self.CMD_CMDTRANS and cmd_index == 51:
            self._start_data_transfer()

        self._update_irq()

    def _make_r1(self) -> int:
        """Build R1 response: current state + status bits."""
        state = self._sd_state & 0xF
        return (state << 9) | (1 << 8)  # READY_FOR_DATA

    def _cmd2_all_send_cid(self):
        """CMD2: Return CID as 136-bit R2 response."""
        cid = self._DEFAULT_CID
        # R2 maps 120 bits of CID into RESP1-4 (MSB first, skip start/end bits)
        self.resp[0] = (cid[0] << 24) | (cid[1] << 16) | (cid[2] << 8) | cid[3]
        self.resp[1] = (cid[4] << 24) | (cid[5] << 16) | (cid[6] << 8) | cid[7]
        self.resp[2] = (cid[8] << 24) | (cid[9] << 16) | (cid[10] << 8) | cid[11]
        self.resp[3] = (cid[12] << 24) | (cid[13] << 16) | (cid[14] << 8) | cid[15]
        self._sta_flags |= self.STA_CMDREND

    def _cmd3_send_rca(self):
        """CMD3: Return R6 with published RCA."""
        self.resp[0] = (self._rca << 16) | 0x0500  # RCA + status
        self._sta_flags |= self.STA_CMDREND

    def _cmd7_select(self, arg: int):
        """CMD7: Select card by RCA."""
        rca = (arg >> 16) & 0xFFFF
        if rca == self._rca:
            self._sd_state = self.SD_TRANSFER
        self.resp[0] = self._make_r1()
        self._sta_flags |= self.STA_CMDREND | self.STA_BUSYD0END

    def _cmd8_send_if_cond(self, arg: int):
        """CMD8: Return R7 echoing check pattern and voltage."""
        # Echo back VHS (bits 11:8) and check pattern (bits 7:0)
        self.resp[0] = arg & 0x1FF
        self._sta_flags |= self.STA_CMDREND
        self._sd_state = self.SD_IDLE

    def _cmd9_send_csd(self):
        """CMD9: Return CSD as 136-bit R2 response."""
        csd = self._build_csd()
        self.resp[0] = (csd[0] << 24) | (csd[1] << 16) | (csd[2] << 8) | csd[3]
        self.resp[1] = (csd[4] << 24) | (csd[5] << 16) | (csd[6] << 8) | csd[7]
        self.resp[2] = (csd[8] << 24) | (csd[9] << 16) | (csd[10] << 8) | csd[11]
        self.resp[3] = (csd[12] << 24) | (csd[13] << 16) | (csd[14] << 8) | csd[15]
        self._sta_flags |= self.STA_CMDREND

    def _acmd41_send_op_cond(self, arg: int):
        """ACMD41: Return R3 (OCR) with card ready."""
        # SDHC card: CCS=1 (bit 30), busy=0 (bit 31 = ready)
        ocr = 0xC0FF8000  # CCS + busy_cleared + voltage window
        self.resp[0] = ocr
        self._sta_flags |= self.STA_CMDREND
        self._sd_state = self.SD_READY

    def _acmd51_send_scr(self):
        """ACMD51: Prepare SCR data for read."""
        self._data_buf = bytearray(self._DEFAULT_SCR)
        self._data_offset = 0
        self.dlen = 8
        self.dcount = 8
        self.resp[0] = self._make_r1()
        self._sta_flags |= self.STA_CMDREND

    def _cmd17_read_block(self, arg: int):
        """CMD17: Read single 512-byte block."""
        self._last_block_addr = arg
        self.resp[0] = self._make_r1()
        self._sta_flags |= self.STA_CMDREND
        self._sd_state = self.SD_SENDING

        # Prepare data for read
        if self.on_block_read:
            self._data_buf = bytearray(self.on_block_read(arg, 1))
        else:
            self._data_buf = bytearray(512)
        self._data_offset = 0

    def _cmd18_read_multi(self, arg: int):
        """CMD18: Read multiple blocks."""
        self._last_block_addr = arg
        self.resp[0] = self._make_r1()
        self._sta_flags |= self.STA_CMDREND
        self._sd_state = self.SD_SENDING

        # Calculate number of blocks from DLEN
        num_blocks = max(1, self.dlen // 512)
        if self.on_block_read:
            self._data_buf = bytearray(self.on_block_read(arg, num_blocks))
        else:
            self._data_buf = bytearray(512 * num_blocks)
        self._data_offset = 0

    def _cmd24_write_block(self, arg: int):
        """CMD24: Write single block."""
        self._last_block_addr = arg
        self.resp[0] = self._make_r1()
        self._sta_flags |= self.STA_CMDREND
        self._sd_state = self.SD_RECEIVING
        self._data_buf = bytearray()
        self._data_offset = 0

    def _cmd25_write_multi(self, arg: int):
        """CMD25: Write multiple blocks."""
        self._last_block_addr = arg
        self.resp[0] = self._make_r1()
        self._sta_flags |= self.STA_CMDREND
        self._sd_state = self.SD_RECEIVING
        self._data_buf = bytearray()
        self._data_offset = 0

    def _build_csd(self) -> bytes:
        """Build CSD v2.0 (SDHC) with capacity from _capacity_mb."""
        # CSD v2.0 structure for SDHC
        c_size = (self._capacity_mb * 1024 // 512) - 1  # In 512KB units
        csd = bytearray(16)
        csd[0] = 0x40   # CSD_STRUCTURE=1 (v2.0)
        csd[1] = 0x0E   # TAAC
        csd[2] = 0x00   # NSAC
        csd[3] = 0x5B   # TRAN_SPEED (50MHz)
        csd[4] = 0x59   # CCC high
        csd[5] = 0x00   # CCC low + READ_BL_LEN(9=512B)
        csd[5] |= 0x09
        csd[6] = 0x00
        # C_SIZE in bytes 7-9 (bits [69:48] of CSD, which is bytes 7[5:0], 8, 9)
        csd[7] = (c_size >> 16) & 0x3F
        csd[8] = (c_size >> 8) & 0xFF
        csd[9] = c_size & 0xFF
        csd[10] = 0x7F  # ERASE_BLK_EN=1, SECTOR_SIZE
        csd[11] = 0x80  # SECTOR_SIZE cont, WP_GRP_SIZE
        csd[12] = 0x0A  # WP_GRP_ENABLE, R2W_FACTOR, WRITE_BL_LEN
        csd[13] = 0x40  # WRITE_BL_LEN cont
        csd[14] = 0x00
        csd[15] = 0x01  # CRC + stop bit
        return bytes(csd)

    def _update_irq(self):
        """Assert/deassert IRQ based on STA & MASK."""
        sta = self._compute_sta()
        pending = bool(sta & self.mask)
        if self.irq_callback:
            self.irq_callback(self.irq, 1 if pending else 0)
