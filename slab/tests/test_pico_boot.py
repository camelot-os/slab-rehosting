"""
Unit tests for Pico board boot flow emulation.

Tests BOOTSEL button, UF2 flash loading, stage2 CRC validation,
boot mode determination, and upload completion callbacks.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import struct
import zlib
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from slab_rp2040.rp2040_misc import RP2040IOQSPI
from slab_rp2040.rp2040_usb_boot import (
    RP2040BootromFAT, RP2040BootromUSB, UF2Block,
    create_rp2040_bootloader, create_uf2_file,
    RP2040_FAMILY_ID,
)
from slab_rp2040.pico_server import (
    PicoBoardServer, PicoBootMode,
    stage2_crc_valid, load_flash_from_file,
)


# =============================================================================
# BOOTSEL IO_QSPI Tests
# =============================================================================

class TestBootselIOQSPI:
    """Test BOOTSEL button emulation via IO_QSPI STATUS register."""

    def test_bootsel_default_not_pressed(self):
        """BOOTSEL defaults to not pressed (SS INFROMPAD = 1)."""
        io_qspi = RP2040IOQSPI()
        # Pin 1 (SS) STATUS at offset 0x08, bit 17 = INFROMPAD
        status = io_qspi.read(0x40018008, 4, False)[0]
        assert status & (1 << 17), "INFROMPAD should be HIGH when BOOTSEL not pressed"

    def test_bootsel_pressed(self):
        """BOOTSEL pressed: SS INFROMPAD = 0 (active low)."""
        io_qspi = RP2040IOQSPI(bootsel_pressed=True)
        status = io_qspi.read(0x40018008, 4, False)[0]
        assert not (status & (1 << 17)), "INFROMPAD should be LOW when BOOTSEL pressed"

    def test_bootsel_set_runtime(self):
        """BOOTSEL can be toggled at runtime."""
        io_qspi = RP2040IOQSPI()

        # Initially not pressed
        status = io_qspi.read(0x40018008, 4, False)[0]
        assert status & (1 << 17)

        # Press BOOTSEL
        io_qspi.set_bootsel(True)
        status = io_qspi.read(0x40018008, 4, False)[0]
        assert not (status & (1 << 17))

        # Release BOOTSEL
        io_qspi.set_bootsel(False)
        status = io_qspi.read(0x40018008, 4, False)[0]
        assert status & (1 << 17)

    def test_other_pins_unaffected(self):
        """Other QSPI pins always show INFROMPAD=1 regardless of BOOTSEL."""
        io_qspi = RP2040IOQSPI(bootsel_pressed=True)

        # Pin 0 (SCLK) STATUS at offset 0x00
        status = io_qspi.read(0x40018000, 4, False)[0]
        assert status & (1 << 17), "SCLK INFROMPAD should be HIGH"

        # Pin 2 (SD0) STATUS at offset 0x10
        status = io_qspi.read(0x40018010, 4, False)[0]
        assert status & (1 << 17), "SD0 INFROMPAD should be HIGH"

    def test_ctrl_register_writable(self):
        """CTRL register (offset 4 within each pin) should be writable."""
        io_qspi = RP2040IOQSPI()
        # Pin 0 CTRL at offset 0x04
        io_qspi.write(0x40018004, 4, 0x05, False)
        val = io_qspi.read(0x40018004, 4, False)[0]
        assert val == 0x05


# =============================================================================
# Stage2 CRC Validation Tests
# =============================================================================

class TestStage2CRC:
    """Test CRC32 validation of stage2 bootloader in flash."""

    def _make_stage2(self, payload: bytes = None) -> bytearray:
        """Create a 256-byte stage2 with valid CRC32."""
        data = bytearray(256)
        if payload:
            data[:len(payload)] = payload[:252]
        crc = zlib.crc32(bytes(data[:252])) & 0xFFFFFFFF
        struct.pack_into('<I', data, 252, crc)
        return data

    def test_valid_crc(self):
        """Valid stage2 CRC passes validation."""
        stage2 = self._make_stage2(b'\x00' * 252)
        assert stage2_crc_valid(bytes(stage2))

    def test_invalid_crc(self):
        """Corrupted CRC fails validation."""
        stage2 = self._make_stage2()
        stage2[252] ^= 0xFF  # Corrupt CRC
        assert not stage2_crc_valid(bytes(stage2))

    def test_empty_flash(self):
        """All-0xFF flash (erased) has invalid CRC."""
        flash = b'\xff' * 256
        assert not stage2_crc_valid(flash)

    def test_too_short(self):
        """Flash shorter than 256 bytes fails."""
        assert not stage2_crc_valid(b'\x00' * 100)
        assert not stage2_crc_valid(b'')

    def test_real_stage2_pattern(self):
        """Stage2 with XIP enable code pattern has valid CRC."""
        # Typical RP2040 stage2 starts with XIP SSI configuration
        payload = bytearray(252)
        payload[0:4] = b'\x00\xb5\x32\x4b'  # push {lr}; ldr r3, [pc, #200]
        stage2 = self._make_stage2(payload)
        assert stage2_crc_valid(bytes(stage2))


# =============================================================================
# UF2 Upload and Flash Callback Tests
# =============================================================================

class TestUF2Upload:
    """Test UF2 upload flow with flash programming callbacks."""

    def test_uf2_to_flash(self):
        """UF2 blocks populate flash_image via flash callback."""
        fat = RP2040BootromFAT("RP2040", "ARM")
        flash_data = {}

        def on_flash(addr, data):
            flash_data[addr] = data

        fat.flash_callback = on_flash

        # Create a UF2 block targeting 0x10000000
        block = UF2Block(
            flags=0x2000,  # FAMILY_ID
            target_addr=0x10000000,
            payload_size=256,
            block_no=0,
            num_blocks=1,
            family_id=RP2040_FAMILY_ID,
            data=b'\xAA' * 256 + b'\x00' * 220,
        )

        fat.write_sector(3, block.to_bytes())
        assert 0x10000000 in flash_data
        assert flash_data[0x10000000][:4] == b'\xAA' * 4

    def test_uf2_completion_callback(self):
        """Upload completion callback fires on last block."""
        fat = RP2040BootromFAT("RP2040", "ARM")
        completed = []

        fat.on_upload_complete = lambda: completed.append(True)

        # Send 3 blocks
        for i in range(3):
            block = UF2Block(
                flags=0x2000,
                target_addr=0x10000000 + i * 256,
                payload_size=256,
                block_no=i,
                num_blocks=3,
                family_id=RP2040_FAMILY_ID,
                data=bytes(476),
            )
            fat.write_sector(10 + i, block.to_bytes())

        assert len(completed) == 1, "Callback should fire exactly once on last block"

    def test_uf2_completion_not_early(self):
        """Completion callback does not fire before last block."""
        fat = RP2040BootromFAT("RP2040", "ARM")
        completed = []

        fat.on_upload_complete = lambda: completed.append(True)

        # Send first of 3 blocks
        block = UF2Block(
            flags=0x2000,
            target_addr=0x10000000,
            payload_size=256,
            block_no=0,
            num_blocks=3,
            family_id=RP2040_FAMILY_ID,
            data=bytes(476),
        )
        fat.write_sector(10, block.to_bytes())
        assert len(completed) == 0

    def test_usb_boot_set_callback(self):
        """RP2040BootromUSB.set_upload_complete_callback() wires through to FAT."""
        usb = create_rp2040_bootloader()
        called = []
        usb.set_upload_complete_callback(lambda: called.append(True))
        assert usb.fat.on_upload_complete is not None


# =============================================================================
# Boot Mode Determination Tests
# =============================================================================

class TestBootModeDetermination:
    """Test automatic boot mode selection."""

    def _make_valid_flash(self) -> bytearray:
        """Create flash image with valid stage2 CRC."""
        flash = bytearray(b'\xff' * 1024)
        payload = bytearray(252)
        payload[0:4] = b'\x00\xb5\x32\x4b'
        flash[:252] = payload
        crc = zlib.crc32(bytes(flash[:252])) & 0xFFFFFFFF
        struct.pack_into('<I', flash, 252, crc)
        return flash

    def test_bootsel_forces_usb(self):
        """BOOTSEL pressed → USB boot regardless of flash state."""
        server = PicoBoardServer(bootsel=True)
        # Even with valid flash, BOOTSEL overrides
        server.flash_image[:256] = self._make_valid_flash()[:256]
        assert server.boot_mode == PicoBootMode.USB_BOOT

    def test_empty_flash_usb_boot(self):
        """Empty flash (all 0xFF) → USB boot."""
        server = PicoBoardServer()
        assert server.boot_mode == PicoBootMode.USB_BOOT

    def test_valid_flash_boots(self):
        """Valid stage2 in flash → flash boot."""
        server = PicoBoardServer()
        server.flash_image[:256] = self._make_valid_flash()[:256]
        assert server.boot_mode == PicoBootMode.FLASH_BOOT

    def test_invalid_crc_usb_boot(self):
        """Invalid stage2 CRC → USB boot."""
        server = PicoBoardServer()
        server.flash_image[:256] = self._make_valid_flash()[:256]
        server.flash_image[252] ^= 0xFF  # Corrupt CRC
        assert server.boot_mode == PicoBootMode.USB_BOOT


# =============================================================================
# Flash File Loading Tests
# =============================================================================

class TestFlashFileLoading:
    """Test loading firmware files into flash image."""

    def test_load_raw_binary(self):
        """Load raw .bin file into flash at offset 0."""
        payload = b'\x00\xb5\x32\x4b' + b'\xAA' * 252
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(payload)
            f.flush()
            path = Path(f.name)

        try:
            image = load_flash_from_file(path, "RP2040")
            assert image[:4] == b'\x00\xb5\x32\x4b'
            assert image[4:8] == b'\xAA' * 4
        finally:
            path.unlink()

    def test_load_uf2_file(self):
        """Load .UF2 file — blocks placed at correct offsets."""
        payload = b'\xDE\xAD\xBE\xEF' * 64  # 256 bytes
        uf2_data = create_uf2_file(payload, base_addr=0x10000000)

        with tempfile.NamedTemporaryFile(suffix='.uf2', delete=False) as f:
            f.write(uf2_data)
            f.flush()
            path = Path(f.name)

        try:
            image = load_flash_from_file(path, "RP2040")
            assert image[:4] == b'\xDE\xAD\xBE\xEF'
        finally:
            path.unlink()

    def test_load_multi_block_uf2(self):
        """UF2 with multiple blocks populates contiguous flash."""
        payload = bytes(range(256)) * 4  # 1024 bytes → 4 blocks
        uf2_data = create_uf2_file(payload, base_addr=0x10000000)

        with tempfile.NamedTemporaryFile(suffix='.uf2', delete=False) as f:
            f.write(uf2_data)
            f.flush()
            path = Path(f.name)

        try:
            image = load_flash_from_file(path, "RP2040")
            # Check first and last blocks
            assert image[0] == 0x00
            assert image[255] == 0xFF
            assert image[256] == 0x00  # Second block
            assert image[768] == 0x00  # Fourth block
        finally:
            path.unlink()

    def test_pico_server_preload_flash(self):
        """PicoBoardServer --flash loads firmware at construction."""
        payload = bytearray(256)
        payload[0:4] = b'\x00\xb5\x32\x4b'
        crc = zlib.crc32(bytes(payload[:252])) & 0xFFFFFFFF
        struct.pack_into('<I', payload, 252, crc)

        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as f:
            f.write(bytes(payload))
            f.flush()
            path = Path(f.name)

        try:
            server = PicoBoardServer(flash_file=path)
            assert server.flash_image[:4] == b'\x00\xb5\x32\x4b'
            assert server.boot_mode == PicoBootMode.FLASH_BOOT
        finally:
            path.unlink()


# =============================================================================
# RP2350 Variant Tests
# =============================================================================

class TestRP2350Variants:
    """Test RP2350-specific boot mode variants."""

    def test_rp2350_arm_config(self):
        """RP2350 ARM server uses correct config."""
        server = PicoBoardServer(chip="rp2350", arch="arm")
        assert server.config['name'] == 'RP2350-ARM'
        assert server.config['cpu'] == 'cortex-m33'

    def test_rp2350_riscv_config(self):
        """RP2350 RISC-V server uses correct config."""
        server = PicoBoardServer(chip="rp2350", arch="riscv")
        assert server.config['name'] == 'RP2350-RISCV'

    def test_rp2350_bootsel(self):
        """RP2350 BOOTSEL works the same as RP2040."""
        server = PicoBoardServer(chip="rp2350", bootsel=True)
        assert server.boot_mode == PicoBootMode.USB_BOOT

    def test_invalid_chip_raises(self):
        """Unknown chip raises ValueError."""
        with pytest.raises(ValueError):
            PicoBoardServer(chip="rp9999")
