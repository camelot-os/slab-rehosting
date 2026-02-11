"""
Tests for STM32 SDMMC controller and VirtualSDCard.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from slab_stm32.stm32_sdmmc import STM32SDMMC
from slab_cortex_m.virtual_components import VirtualSDCard


# ---------------------------------------------------------------------------
# SDMMC register tests
# ---------------------------------------------------------------------------

class TestSDMMCRegisters:
    """Test SDMMC register reset values and basic access."""

    def setup_method(self):
        self.sdmmc = STM32SDMMC(index=1, base=0x420C8000, irq=78)

    def test_reset_values(self):
        assert self.sdmmc.read(0x420C8000, 4)[0] == 0  # POWER
        assert self.sdmmc.read(0x420C8004, 4)[0] == 0  # CLKCR
        assert self.sdmmc.read(0x420C8034, 4)[0] != 0  # STA (FIFO flags)

    def test_power_control(self):
        self.sdmmc.write(0x420C8000, 4, 0x03)  # Power on
        assert self.sdmmc.read(0x420C8000, 4)[0] == 0x03

    def test_clkcr_readback(self):
        self.sdmmc.write(0x420C8004, 4, 0x400)  # WIDBUS=4bit
        assert self.sdmmc.read(0x420C8004, 4)[0] == 0x400

    def test_mask_readback(self):
        self.sdmmc.write(0x420C803C, 4, 0x1FF)
        assert self.sdmmc.read(0x420C803C, 4)[0] == 0x1FF

    def test_icr_clears_sta_flags(self):
        # Force some flags
        self.sdmmc._sta_flags = 0xFF
        sta = self.sdmmc.read(0x420C8034, 4)[0]
        assert sta & 0xFF

        # Clear via ICR
        self.sdmmc.write(0x420C8038, 4, 0xFF)
        sta = self.sdmmc.read(0x420C8034, 4)[0]
        assert (sta & 0xFF) == 0

    def test_sta_fifo_flags(self):
        """STA shows TXFIFOE and RXFIFOE when FIFOs are empty."""
        sta = self.sdmmc.read(0x420C8034, 4)[0]
        assert sta & STM32SDMMC.STA_TXFIFOE
        assert sta & STM32SDMMC.STA_RXFIFOE


# ---------------------------------------------------------------------------
# SD command protocol tests
# ---------------------------------------------------------------------------

class TestSDMMCCommands:
    """Test SD command processing and response generation."""

    def setup_method(self):
        self.sdmmc = STM32SDMMC(index=1, base=0x420C8000, irq=78)
        self.base = 0x420C8000

    def _send_cmd(self, cmd_index, arg=0, waitresp=1):
        """Send SD command."""
        self.sdmmc.write(self.base + 0x08, 4, arg)  # ARG
        cmd_val = cmd_index | (waitresp << 8) | (1 << 12)  # CPSMEN
        self.sdmmc.write(self.base + 0x0C, 4, cmd_val)  # CMD
        # Clear status
        self.sdmmc.write(self.base + 0x38, 4, 0xFFFFFFFF)

    def test_cmd0_go_idle(self):
        """CMD0 should set CMDSENT and transition to IDLE."""
        self.sdmmc.write(self.base + 0x08, 4, 0)
        self.sdmmc.write(self.base + 0x0C, 4, 0 | (0 << 8) | (1 << 12))
        sta = self.sdmmc.read(self.base + 0x34, 4)[0]
        assert sta & STM32SDMMC.STA_CMDSENT

    def test_cmd8_send_if_cond(self):
        """CMD8 should echo back voltage and check pattern."""
        self._send_cmd(8, arg=0x1AA, waitresp=1)
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]  # RESP1
        assert resp1 == 0x1AA

    def test_acmd41_send_op_cond(self):
        """CMD55+ACMD41 should return OCR with CCS and busy cleared."""
        # CMD55
        self._send_cmd(55, arg=0, waitresp=1)
        # ACMD41
        self._send_cmd(41, arg=0x40100000, waitresp=1)
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]
        assert resp1 & (1 << 30)  # CCS (SDHC)
        assert resp1 & (1 << 31)  # Busy cleared (ready)

    def test_cmd2_all_send_cid(self):
        """CMD2 should return R2 (136-bit CID)."""
        self._send_cmd(2, arg=0, waitresp=3)  # Long response
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]
        # Should have manufacturer data
        assert resp1 != 0

    def test_cmd3_send_rca(self):
        """CMD3 should return R6 with RCA."""
        self._send_cmd(3, arg=0, waitresp=1)
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]
        rca = (resp1 >> 16) & 0xFFFF
        assert rca == 1  # Default RCA

    def test_full_init_sequence(self):
        """Complete SD card init sequence."""
        # CMD0
        self._send_cmd(0, waitresp=0)
        # CMD8
        self._send_cmd(8, arg=0x1AA, waitresp=1)
        # CMD55 + ACMD41
        self._send_cmd(55, waitresp=1)
        self._send_cmd(41, arg=0x40100000, waitresp=1)
        # CMD2
        self._send_cmd(2, waitresp=3)
        # CMD3
        self._send_cmd(3, waitresp=1)
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]
        rca = (resp1 >> 16) & 0xFFFF
        # CMD9
        self._send_cmd(9, arg=(rca << 16), waitresp=3)
        # CMD7 (select)
        self._send_cmd(7, arg=(rca << 16), waitresp=1)
        # CMD16 (set block length)
        self._send_cmd(16, arg=512, waitresp=1)

        # Should be in TRANSFER state now
        assert self.sdmmc._sd_state == STM32SDMMC.SD_TRANSFER

    def test_cmd7_select_card(self):
        """CMD7 should transition to TRANSFER state."""
        self._send_cmd(7, arg=(1 << 16), waitresp=1)
        assert self.sdmmc._sd_state == STM32SDMMC.SD_TRANSFER

    def test_cmd13_send_status(self):
        """CMD13 should return R1 with state."""
        self._send_cmd(13, arg=(1 << 16), waitresp=1)
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]
        assert resp1 & (1 << 8)  # READY_FOR_DATA

    def test_cmd9_send_csd(self):
        """CMD9 should return CSD v2.0."""
        self._send_cmd(9, arg=(1 << 16), waitresp=3)
        resp1 = self.sdmmc.read(self.base + 0x14, 4)[0]
        csd_structure = (resp1 >> 30) & 0x3
        assert csd_structure == 1  # CSD v2.0

    def test_acmd6_set_bus_width(self):
        """CMD55+ACMD6 should set bus width."""
        self._send_cmd(55, waitresp=1)
        self._send_cmd(6, arg=2, waitresp=1)  # 4-bit
        assert self.sdmmc._bus_width == 4


# ---------------------------------------------------------------------------
# Block read/write tests
# ---------------------------------------------------------------------------

class TestSDMMCDataTransfer:
    """Test block read/write with FIFO."""

    def setup_method(self):
        self.sdmmc = STM32SDMMC(index=1, base=0x420C8000, irq=78)
        self.base = 0x420C8000
        self.sdcard = VirtualSDCard(capacity_mb=64)

        # Wire callbacks
        self.sdmmc.on_block_read = self.sdcard.read_blocks
        self.sdmmc.on_block_write = self.sdcard.write_blocks

    def _send_cmd(self, cmd_index, arg=0, waitresp=1):
        self.sdmmc.write(self.base + 0x08, 4, arg)
        cmd_val = cmd_index | (waitresp << 8) | (1 << 12)
        self.sdmmc.write(self.base + 0x0C, 4, cmd_val)
        self.sdmmc.write(self.base + 0x38, 4, 0xFFFFFFFF)

    def test_read_single_block(self):
        """CMD17 read single block via FIFO."""
        # Write test data to SD card
        test_data = bytes(range(256)) * 2  # 512 bytes
        self.sdcard.write_blocks(0, test_data)

        # CMD17 read block 0
        self._send_cmd(17, arg=0, waitresp=1)

        # Setup DLEN and DCTRL for read
        self.sdmmc.write(self.base + 0x28, 4, 512)  # DLEN
        self.sdmmc.write(self.base + 0x2C, 4, 0x93)  # DCTRL: DTEN=1, DTDIR=1, DBLOCKSIZE=9

        # Read data from FIFO
        words_read = []
        for _ in range(128):  # 512/4 = 128 words
            w = self.sdmmc.read(self.base + 0x80, 4)[0]  # FIFO
            words_read.append(w)

        # Verify first word
        expected = int.from_bytes(test_data[0:4], 'little')
        assert words_read[0] == expected

    def test_write_single_block(self):
        """CMD24 write single block via FIFO."""
        # CMD24 write block 5
        self._send_cmd(24, arg=5, waitresp=1)

        # Setup DLEN and DCTRL for write
        self.sdmmc.write(self.base + 0x28, 4, 512)  # DLEN
        self.sdmmc.write(self.base + 0x2C, 4, 0x91)  # DCTRL: DTEN=1, DTDIR=0, DBLOCKSIZE=9

        # Write data to FIFO
        for i in range(128):
            self.sdmmc.write(self.base + 0x80, 4, i)

        # Verify data was written to SD card
        data = self.sdcard.read_blocks(5, 1)
        assert int.from_bytes(data[0:4], 'little') == 0

    def test_fifo_reset(self):
        """DCTRL.FIFORST should clear FIFOs."""
        # Put data in RX FIFO
        self.sdmmc._rx_fifo.append(0x12345678)
        assert len(self.sdmmc._rx_fifo) == 1

        # Reset FIFO
        self.sdmmc.write(self.base + 0x2C, 4, 1 << 13)  # FIFORST
        assert len(self.sdmmc._rx_fifo) == 0

    def test_irq_on_cmdrend(self):
        """IRQ should fire when CMDREND and MASK match."""
        irq_fired = [False]

        def irq_cb(irq, level):
            if level:
                irq_fired[0] = True

        self.sdmmc.irq_callback = irq_cb

        # Enable CMDREND interrupt
        self.sdmmc.write(self.base + 0x3C, 4, STM32SDMMC.STA_CMDREND)

        # Send CMD8 (will set CMDREND)
        self._send_cmd(8, arg=0x1AA, waitresp=1)

        assert irq_fired[0]


# ---------------------------------------------------------------------------
# VirtualSDCard tests
# ---------------------------------------------------------------------------

class TestVirtualSDCard:
    """Test VirtualSDCard standalone functionality."""

    def test_default_capacity(self):
        sd = VirtualSDCard(capacity_mb=128)
        assert sd.get_capacity_bytes() == 128 * 1024 * 1024

    def test_read_empty(self):
        sd = VirtualSDCard(capacity_mb=64)
        data = sd.read_blocks(0, 1)
        assert len(data) == 512
        assert data == b'\x00' * 512

    def test_write_and_read(self):
        sd = VirtualSDCard(capacity_mb=64)
        test_data = b'\xAA' * 512
        sd.write_blocks(10, test_data)

        # Read back
        data = sd.read_blocks(10, 1)
        assert data == test_data

        # Other blocks still empty
        data = sd.read_blocks(11, 1)
        assert data == b'\x00' * 512

    def test_multi_block_read(self):
        sd = VirtualSDCard(capacity_mb=64)
        sd.write_blocks(0, b'\x11' * 512)
        sd.write_blocks(1, b'\x22' * 512)

        data = sd.read_blocks(0, 2)
        assert len(data) == 1024
        assert data[:512] == b'\x11' * 512
        assert data[512:] == b'\x22' * 512

    def test_multi_block_write(self):
        sd = VirtualSDCard(capacity_mb=64)
        data = b'\xAA' * 512 + b'\xBB' * 512
        sd.write_blocks(5, data)

        assert sd.read_blocks(5, 1) == b'\xAA' * 512
        assert sd.read_blocks(6, 1) == b'\xBB' * 512

    def test_cid(self):
        sd = VirtualSDCard(capacity_mb=256)
        cid = sd.get_cid()
        assert len(cid) == 16
        assert cid[0] == 0x03  # MID

    def test_csd_v2(self):
        sd = VirtualSDCard(capacity_mb=256)
        csd = sd.get_csd()
        assert len(csd) == 16
        assert (csd[0] >> 6) == 1  # CSD v2.0

    def test_scr(self):
        sd = VirtualSDCard(capacity_mb=256)
        scr = sd.get_scr()
        assert len(scr) == 8
        assert scr[0] == 0x02  # SCR version

    def test_ocr(self):
        sd = VirtualSDCard(capacity_mb=256)
        ocr = sd.get_ocr()
        assert ocr & (1 << 30)  # CCS
        assert ocr & (1 << 31)  # Power up done

    def test_used_blocks(self):
        sd = VirtualSDCard(capacity_mb=64)
        assert sd.get_used_blocks() == 0
        sd.write_blocks(0, b'\x01' * 512)
        assert sd.get_used_blocks() == 1


# ---------------------------------------------------------------------------
# SDMMC instance tests
# ---------------------------------------------------------------------------

class TestSDMMCInstances:
    """Test multiple SDMMC instances."""

    def test_sdmmc1_base(self):
        s1 = STM32SDMMC(index=1, base=0x420C8000, irq=78)
        assert s1.name == "SDMMC1"
        assert s1.base == 0x420C8000
        assert s1.irq == 78

    def test_sdmmc2_base(self):
        s2 = STM32SDMMC(index=2, base=0x420C8C00, irq=79)
        assert s2.name == "SDMMC2"
        assert s2.base == 0x420C8C00
        assert s2.irq == 79


# ---------------------------------------------------------------------------
# CMDTRANS tests (HAL_SD v2 mechanism)
# ---------------------------------------------------------------------------

class TestSDMMCCmdtrans:
    """Test CMDTRANS data transfer mechanism used by STM32U5 HAL_SD.

    HAL_SD uses CMDTRANS (CMD bit 6) to auto-start data transfers
    instead of DCTRL.DTEN. The sequence is:
    1. DLEN = block_size
    2. DCTRL = DTDIR | DBLOCKSIZE (no DTEN)
    3. CMD = cmd_index | CMDTRANS | CPSMEN | WAITRESP
    4. Poll STA.RXFIFOHF / write FIFO
    """

    def setup_method(self):
        self.sdmmc = STM32SDMMC(index=1, base=0x420C8000, irq=78)
        self.base = 0x420C8000
        self.sdcard = VirtualSDCard(capacity_mb=64)
        self.sdmmc.on_block_read = self.sdcard.read_blocks
        self.sdmmc.on_block_write = self.sdcard.write_blocks

    def _send_cmd_cmdtrans(self, cmd_index, arg=0, waitresp=1):
        """Send SD command with CMDTRANS bit set (HAL_SD v2 style)."""
        self.sdmmc.write(self.base + 0x08, 4, arg)  # ARG
        cmd_val = (cmd_index
                   | STM32SDMMC.CMD_CMDTRANS
                   | (waitresp << 8)
                   | STM32SDMMC.CMD_CPSMEN)
        self.sdmmc.write(self.base + 0x0C, 4, cmd_val)  # CMD
        self.sdmmc.write(self.base + 0x38, 4, 0xFFFFFFFF)  # Clear ICR

    def _send_cmd(self, cmd_index, arg=0, waitresp=1):
        """Send SD command without CMDTRANS (for init sequence)."""
        self.sdmmc.write(self.base + 0x08, 4, arg)
        cmd_val = cmd_index | (waitresp << 8) | (1 << 12)
        self.sdmmc.write(self.base + 0x0C, 4, cmd_val)
        self.sdmmc.write(self.base + 0x38, 4, 0xFFFFFFFF)

    def test_cmdtrans_read_single(self):
        """CMD17 with CMDTRANS should auto-fill RX FIFO without DTEN."""
        test_data = bytes(range(256)) * 2  # 512 bytes
        self.sdcard.write_blocks(0, test_data)

        # HAL_SD sequence: DLEN -> DCTRL (no DTEN) -> CMD17+CMDTRANS
        self.sdmmc.write(self.base + 0x28, 4, 512)  # DLEN
        self.sdmmc.write(self.base + 0x2C, 4, 0x92)  # DCTRL: DTDIR=1, DBLOCKSIZE=9, DTEN=0

        self._send_cmd_cmdtrans(17, arg=0, waitresp=1)

        # STA should show RXFIFOHF (FIFO half-full)
        sta = self.sdmmc.read(self.base + 0x34, 4)[0]
        assert sta & STM32SDMMC.STA_RXFIFOHF

        # Read 128 words (512 bytes) from FIFO
        words = []
        for _ in range(128):
            w = self.sdmmc.read(self.base + 0x80, 4)[0]
            words.append(w)

        expected = int.from_bytes(test_data[0:4], 'little')
        assert words[0] == expected

        # After reading all data, DATAEND should be set
        sta = self.sdmmc.read(self.base + 0x34, 4)[0]
        assert sta & STM32SDMMC.STA_DATAEND

    def test_cmdtrans_write_single(self):
        """CMD24 with CMDTRANS should accept FIFO writes without DTEN."""
        # HAL_SD sequence: DLEN -> DCTRL (no DTEN) -> CMD24+CMDTRANS
        self.sdmmc.write(self.base + 0x28, 4, 512)  # DLEN
        self.sdmmc.write(self.base + 0x2C, 4, 0x90)  # DCTRL: DTDIR=0, DBLOCKSIZE=9, DTEN=0

        self._send_cmd_cmdtrans(24, arg=3, waitresp=1)

        # Write 128 words (512 bytes) to FIFO
        for i in range(128):
            self.sdmmc.write(self.base + 0x80, 4, i)

        # DATAEND should be set after all data written
        sta = self.sdmmc.read(self.base + 0x34, 4)[0]
        assert sta & STM32SDMMC.STA_DATAEND

        # Verify data on SD card
        data = self.sdcard.read_blocks(3, 1)
        assert int.from_bytes(data[0:4], 'little') == 0
        assert int.from_bytes(data[4:8], 'little') == 1

    def test_cmdtrans_scr(self):
        """CMD55+ACMD51 with CMDTRANS should return SCR via FIFO."""
        # CMD55 (no CMDTRANS)
        self._send_cmd(55, arg=0, waitresp=1)

        # DLEN = 8 (SCR is 8 bytes)
        self.sdmmc.write(self.base + 0x28, 4, 8)
        self.sdmmc.write(self.base + 0x2C, 4, 0x62)  # DCTRL: DTDIR=1, DBLOCKSIZE=3 (8B), DTEN=0

        # ACMD51 with CMDTRANS
        self._send_cmd_cmdtrans(51, arg=0, waitresp=1)

        # Read 2 words (8 bytes) from FIFO
        w0 = self.sdmmc.read(self.base + 0x80, 4)[0]
        w1 = self.sdmmc.read(self.base + 0x80, 4)[0]

        # SCR first byte is 0x02 (version)
        scr_bytes = w0.to_bytes(4, 'little') + w1.to_bytes(4, 'little')
        assert scr_bytes[0] == 0x02

    def test_cmdtrans_hal_init_sequence(self):
        """Full HAL_SD init sequence: CMD0->CMD8->ACMD41->CMD2->CMD3->CMD9->CMD7->CMD16."""
        # CMD0
        self._send_cmd(0, waitresp=0)
        assert self.sdmmc._sd_state == STM32SDMMC.SD_IDLE

        # CMD8
        self._send_cmd(8, arg=0x1AA, waitresp=1)
        resp = self.sdmmc.read(self.base + 0x14, 4)[0]
        assert resp == 0x1AA

        # CMD55 + ACMD41
        self._send_cmd(55, waitresp=1)
        self._send_cmd(41, arg=0x40100000, waitresp=1)
        resp = self.sdmmc.read(self.base + 0x14, 4)[0]
        assert resp & (1 << 31)  # Power up done

        # CMD2
        self._send_cmd(2, waitresp=3)

        # CMD3
        self._send_cmd(3, waitresp=1)
        resp = self.sdmmc.read(self.base + 0x14, 4)[0]
        rca = (resp >> 16) & 0xFFFF
        assert rca == 1

        # CMD9
        self._send_cmd(9, arg=(rca << 16), waitresp=3)

        # CMD7 (select)
        self._send_cmd(7, arg=(rca << 16), waitresp=1)
        assert self.sdmmc._sd_state == STM32SDMMC.SD_TRANSFER

        # CMD16 (set block length)
        self._send_cmd(16, arg=512, waitresp=1)

        # Now do a CMDTRANS read
        test_data = b'\xDE\xAD\xBE\xEF' * 128
        self.sdcard.write_blocks(0, test_data)

        self.sdmmc.write(self.base + 0x28, 4, 512)
        self.sdmmc.write(self.base + 0x2C, 4, 0x92)
        self._send_cmd_cmdtrans(17, arg=0, waitresp=1)

        w0 = self.sdmmc.read(self.base + 0x80, 4)[0]
        assert w0 == 0xEFBEADDE  # Little-endian

    def test_cmdtrans_no_effect_on_non_data_cmd(self):
        """CMDTRANS on non-data commands (e.g. CMD13) should not start data phase."""
        # Set some stale data in buffer from a previous transfer
        self.sdmmc._data_buf = bytearray(512)
        self.sdmmc._data_offset = 0
        self.sdmmc.dlen = 512
        self.sdmmc.dctrl = 0x92  # DTDIR=1, DBLOCKSIZE=9

        # Send CMD13 (SEND_STATUS) -- even with CMDTRANS, should NOT fill FIFO
        self.sdmmc.write(self.base + 0x08, 4, (1 << 16))
        cmd_val = (13
                   | STM32SDMMC.CMD_CMDTRANS
                   | (1 << 8)
                   | STM32SDMMC.CMD_CPSMEN)
        self.sdmmc.write(self.base + 0x0C, 4, cmd_val)

        # RX FIFO should still be empty (CMD13 is not a data command)
        assert len(self.sdmmc._rx_fifo) == 0
