"""
RP2040/RP2350 USB Bootloader Emulation

Emulates the RP2040/RP2350 bootrom USB mass storage mode:
- Presents as "RPI-RP2" USB mass storage device
- Accepts .UF2 files for flash programming
- Compatible with both ARM (Cortex-M0+/M33) and RISC-V (Hazard3)

The bootrom enters this mode when:
- No valid boot code in flash (stage 2 bootloader)
- BOOTSEL button is held during power-on
- Software requests reboot to bootloader

References:
- RP2040 Datasheet, Chapter 2.8 (Bootrom)
- UF2 Specification: https://github.com/microsoft/uf2

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from enum import IntEnum

sys.path.insert(0, str(Path(__file__).parent.parent))
from slab_peripherals.usb_controller import USBCoverageTracker

log = logging.getLogger('RP2040.USB')


# =============================================================================
# UF2 FILE FORMAT
# =============================================================================

UF2_MAGIC_START0 = 0x0A324655  # "UF2\n"
UF2_MAGIC_START1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30

# UF2 Flags
UF2_FLAG_FAMILY_ID = 0x00002000
UF2_FLAG_FILE_CONTAINER = 0x00001000
UF2_FLAG_NOT_MAIN_FLASH = 0x00000001

# RP2040 Family ID
RP2040_FAMILY_ID = 0xE48BFF56
RP2350_ARM_FAMILY_ID = 0xE48BFF57  # RP2350 ARM
RP2350_RISCV_FAMILY_ID = 0xE48BFF58  # RP2350 RISC-V


@dataclass
class UF2Block:
    """Single UF2 block (512 bytes)."""
    magic_start0: int = UF2_MAGIC_START0
    magic_start1: int = UF2_MAGIC_START1
    flags: int = 0
    target_addr: int = 0
    payload_size: int = 256
    block_no: int = 0
    num_blocks: int = 0
    family_id: int = RP2040_FAMILY_ID
    data: bytes = field(default_factory=lambda: bytes(476))
    magic_end: int = UF2_MAGIC_END

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional['UF2Block']:
        """Parse a 512-byte UF2 block."""
        if len(data) != 512:
            return None

        magic_start0, magic_start1 = struct.unpack('<II', data[0:8])
        if magic_start0 != UF2_MAGIC_START0 or magic_start1 != UF2_MAGIC_START1:
            return None

        flags, target_addr, payload_size, block_no, num_blocks, family_id = \
            struct.unpack('<IIIIII', data[8:32])

        magic_end = struct.unpack('<I', data[508:512])[0]
        if magic_end != UF2_MAGIC_END:
            return None

        return cls(
            magic_start0=magic_start0,
            magic_start1=magic_start1,
            flags=flags,
            target_addr=target_addr,
            payload_size=payload_size,
            block_no=block_no,
            num_blocks=num_blocks,
            family_id=family_id,
            data=data[32:508],
            magic_end=magic_end
        )

    def to_bytes(self) -> bytes:
        """Convert to 512-byte block."""
        header = struct.pack('<IIIIIIII',
            self.magic_start0, self.magic_start1,
            self.flags, self.target_addr, self.payload_size,
            self.block_no, self.num_blocks, self.family_id
        )
        return header + self.data[:476].ljust(476, b'\x00') + struct.pack('<I', self.magic_end)


# =============================================================================
# FAT12 FILESYSTEM FOR USB MASS STORAGE
# =============================================================================

class RP2040BootromFAT:
    """
    FAT12 filesystem emulation for RP2040 bootrom.

    Presents a minimal FAT12 filesystem with:
    - INFO_UF2.TXT - Device information
    - INDEX.HTM - Redirect to documentation

    Accepts writes of .UF2 files for flash programming.
    """

    # Disk geometry (same as real RP2040 bootrom)
    SECTOR_SIZE = 512
    NUM_SECTORS = 256  # 128KB virtual disk
    FAT_SECTORS = 1
    ROOT_DIR_SECTORS = 1
    DATA_START_SECTOR = 3  # Reserved(1) + FAT(1) + Root(1)

    # Volume label
    VOLUME_LABEL = b'RPI-RP2    '  # 11 chars

    def __init__(self, chip: str = "RP2040", arch: str = "ARM"):
        self.chip = chip
        self.arch = arch
        self.flash_data: Dict[int, bytes] = {}  # addr -> data
        self.flash_callback: Optional[Callable[[int, bytes], None]] = None
        self.on_upload_complete: Optional[Callable[[], None]] = None
        self.log = logging.getLogger('RP2040.FAT')

        # Build static filesystem
        self._build_filesystem()

    def _build_filesystem(self):
        """Build the FAT12 filesystem image."""
        self.sectors: Dict[int, bytes] = {}

        # Sector 0: Boot sector (BPB)
        self.sectors[0] = self._create_boot_sector()

        # Sector 1: FAT
        self.sectors[1] = self._create_fat()

        # Sector 2: Root directory
        self.sectors[2] = self._create_root_directory()

        # Sector 3: INFO_UF2.TXT content
        self.sectors[3] = self._create_info_file()

        # Sector 4: INDEX.HTM content
        self.sectors[4] = self._create_index_file()

    def _create_boot_sector(self) -> bytes:
        """Create FAT12 boot sector with BPB."""
        bpb = bytearray(512)

        # Jump instruction
        bpb[0:3] = b'\xEB\x3C\x90'

        # OEM name
        bpb[3:11] = b'MSWIN4.1'

        # BPB (BIOS Parameter Block)
        struct.pack_into('<H', bpb, 11, self.SECTOR_SIZE)  # BytsPerSec
        bpb[13] = 1  # SecPerClus
        struct.pack_into('<H', bpb, 14, 1)  # RsvdSecCnt
        bpb[16] = 1  # NumFATs
        struct.pack_into('<H', bpb, 17, 16)  # RootEntCnt (16 entries)
        struct.pack_into('<H', bpb, 19, self.NUM_SECTORS)  # TotSec16
        bpb[21] = 0xF8  # Media (fixed disk)
        struct.pack_into('<H', bpb, 22, self.FAT_SECTORS)  # FATSz16
        struct.pack_into('<H', bpb, 24, 1)  # SecPerTrk
        struct.pack_into('<H', bpb, 26, 1)  # NumHeads
        struct.pack_into('<I', bpb, 28, 0)  # HiddSec
        struct.pack_into('<I', bpb, 32, 0)  # TotSec32

        # Extended BPB (FAT12/16)
        bpb[36] = 0x00  # DrvNum
        bpb[37] = 0x00  # Reserved
        bpb[38] = 0x29  # BootSig
        struct.pack_into('<I', bpb, 39, 0x12345678)  # VolID
        bpb[43:54] = self.VOLUME_LABEL  # VolLab
        bpb[54:62] = b'FAT12   '  # FilSysType

        # Boot signature
        bpb[510:512] = b'\x55\xAA'

        return bytes(bpb)

    def _create_fat(self) -> bytes:
        """Create FAT12 table."""
        fat = bytearray(512)

        # FAT12 entries (1.5 bytes each)
        # Cluster 0, 1: Reserved
        fat[0:3] = b'\xF8\xFF\xFF'

        # Cluster 2: INFO_UF2.TXT (1 sector, end of chain)
        # Cluster 3: INDEX.HTM (1 sector, end of chain)
        # Entry for cluster 2: 0xFFF (end)
        # Entry for cluster 3: 0xFFF (end)
        fat[3] = 0xFF
        fat[4] = 0x0F
        fat[5] = 0xFF

        return bytes(fat)

    def _create_root_directory(self) -> bytes:
        """Create root directory with file entries."""
        root = bytearray(512)

        # Entry 0: Volume label
        root[0:11] = self.VOLUME_LABEL
        root[11] = 0x08  # Attribute: Volume label

        # Entry 1: INFO_UF2.TXT
        root[32:43] = b'INFO_UF2TXT'
        root[43] = 0x21  # Attribute: Read-only + Archive
        struct.pack_into('<H', root, 32+26, 2)  # First cluster
        info_size = len(self._get_info_content())
        struct.pack_into('<I', root, 32+28, info_size)  # File size

        # Entry 2: INDEX.HTM
        root[64:75] = b'INDEX   HTM'
        root[75] = 0x21  # Attribute: Read-only + Archive
        struct.pack_into('<H', root, 64+26, 3)  # First cluster
        index_size = len(self._get_index_content())
        struct.pack_into('<I', root, 64+28, index_size)  # File size

        return bytes(root)

    def _get_info_content(self) -> bytes:
        """Get INFO_UF2.TXT content."""
        family_id = RP2040_FAMILY_ID if self.chip == "RP2040" else \
                   (RP2350_ARM_FAMILY_ID if self.arch == "ARM" else RP2350_RISCV_FAMILY_ID)

        content = f"""UF2 Bootloader v3.0
Model: {self.chip}
Board-ID: {self.chip.lower()}
Architecture: {self.arch}
Family: 0x{family_id:08X}
"""
        return content.encode('utf-8')

    def _get_index_content(self) -> bytes:
        """Get INDEX.HTM content (redirect to documentation)."""
        url = "https://www.raspberrypi.com/documentation/microcontrollers/raspberry-pi-pico.html"
        content = f"""<!DOCTYPE html>
<html>
<head>
<meta http-equiv="refresh" content="0; url={url}">
</head>
<body>
<a href="{url}">Raspberry Pi Pico Documentation</a>
</body>
</html>
"""
        return content.encode('utf-8')

    def _create_info_file(self) -> bytes:
        """Create INFO_UF2.TXT sector."""
        content = self._get_info_content()
        return content.ljust(512, b'\x00')

    def _create_index_file(self) -> bytes:
        """Create INDEX.HTM sector."""
        content = self._get_index_content()
        return content.ljust(512, b'\x00')

    def read_sector(self, sector: int) -> bytes:
        """Read a sector from the virtual disk."""
        if sector in self.sectors:
            return self.sectors[sector]
        return bytes(512)

    def write_sector(self, sector: int, data: bytes) -> bool:
        """
        Write a sector to the virtual disk.

        Looks for UF2 blocks and programs flash accordingly.
        """
        if len(data) != 512:
            return False

        # Check if this is a UF2 block
        block = UF2Block.from_bytes(data)
        if block:
            return self._handle_uf2_block(block)

        # Otherwise just store in sectors (for directory updates etc)
        self.sectors[sector] = data
        return True

    def _handle_uf2_block(self, block: UF2Block) -> bool:
        """Handle a UF2 block - program to flash."""
        # Check family ID
        expected_family = RP2040_FAMILY_ID if self.chip == "RP2040" else \
                         (RP2350_ARM_FAMILY_ID if self.arch == "ARM" else RP2350_RISCV_FAMILY_ID)

        if block.flags & UF2_FLAG_FAMILY_ID:
            if block.family_id not in (expected_family, 0):
                self.log.warning(f"Wrong family ID: 0x{block.family_id:08X} (expected 0x{expected_family:08X})")
                return False

        # Extract payload and target address
        addr = block.target_addr
        payload = block.data[:block.payload_size]

        self.log.info(f"UF2: Block {block.block_no + 1}/{block.num_blocks} -> 0x{addr:08X} ({block.payload_size} bytes)")

        # Store in flash data
        self.flash_data[addr] = payload

        # Call flash callback if set
        if self.flash_callback:
            self.flash_callback(addr, payload)

        # Detect upload completion (last block received)
        if block.num_blocks > 0 and block.block_no == block.num_blocks - 1:
            self.log.info(f"UF2 upload complete: {block.num_blocks} blocks")
            if self.on_upload_complete:
                self.on_upload_complete()

        return True

    def get_flash_image(self) -> bytes:
        """Get the complete flash image from received UF2 blocks."""
        if not self.flash_data:
            return bytes()

        min_addr = min(self.flash_data.keys())
        max_addr = max(self.flash_data.keys())
        max_end = max_addr + len(self.flash_data[max_addr])

        # Create contiguous image
        image = bytearray(max_end - min_addr)
        for addr, data in self.flash_data.items():
            offset = addr - min_addr
            image[offset:offset + len(data)] = data

        return bytes(image)


# =============================================================================
# USB MASS STORAGE DEVICE
# =============================================================================

class RP2040BootromUSB:
    """
    RP2040 Bootrom USB Mass Storage Device.

    Emulates the USB interface presented by the RP2040 bootrom:
    - USB Vendor/Product ID: 0x2E8A/0x0003 (Raspberry Pi RP2 Boot)
    - Mass Storage Class (Bulk-Only Transport)
    - FAT12 filesystem with INFO_UF2.TXT and INDEX.HTM
    """

    # USB IDs for RP2040 bootrom
    USB_VID = 0x2E8A  # Raspberry Pi
    USB_PID_RP2040 = 0x0003  # RP2 Boot
    USB_PID_RP2350 = 0x000F  # RP2350 Boot (placeholder)

    # USB Mass Storage constants
    CBW_SIGNATURE = 0x43425355  # "USBC"
    CSW_SIGNATURE = 0x53425355  # "USBS"

    # SCSI commands
    SCSI_TEST_UNIT_READY = 0x00
    SCSI_REQUEST_SENSE = 0x03
    SCSI_INQUIRY = 0x12
    SCSI_MODE_SENSE_6 = 0x1A
    SCSI_READ_FORMAT_CAPACITIES = 0x23
    SCSI_READ_CAPACITY_10 = 0x25
    SCSI_READ_10 = 0x28
    SCSI_WRITE_10 = 0x2A

    def __init__(self, chip: str = "RP2040", arch: str = "ARM"):
        self.chip = chip
        self.arch = arch
        self.fat = RP2040BootromFAT(chip, arch)
        self.log = logging.getLogger('RP2040.USB')

        # Coverage tracking
        self.coverage = USBCoverageTracker()

        # USB state
        self.address = 0
        self.configured = False

        # Mass storage state
        self.cbw_tag = 0
        self.data_out_buffer = bytearray()
        self.expected_data_length = 0
        self.current_lba = 0

    @property
    def usb_pid(self) -> int:
        return self.USB_PID_RP2040 if self.chip == "RP2040" else self.USB_PID_RP2350

    # Device descriptor
    @property
    def device_descriptor(self) -> bytes:
        return bytes([
            18, 0x01,           # bLength, bDescriptorType
            0x00, 0x02,         # bcdUSB (2.0)
            0x00, 0x00, 0x00,   # bDeviceClass, SubClass, Protocol
            64,                 # bMaxPacketSize0
            self.USB_VID & 0xFF, (self.USB_VID >> 8) & 0xFF,  # idVendor
            self.usb_pid & 0xFF, (self.usb_pid >> 8) & 0xFF,  # idProduct
            0x00, 0x01,         # bcdDevice (1.0)
            1, 2, 3,            # iManufacturer, iProduct, iSerialNumber
            1                   # bNumConfigurations
        ])

    # Configuration descriptor
    CONFIG_DESC = bytes([
        # Configuration
        9, 0x02, 32, 0, 1, 1, 0, 0x80, 50,
        # Interface 0: Mass Storage
        9, 0x04, 0, 0, 2, 0x08, 0x06, 0x50, 0,  # Class=MSC, SubClass=SCSI, Protocol=BBB
        # Bulk OUT endpoint
        7, 0x05, 0x01, 0x02, 64, 0, 0,
        # Bulk IN endpoint
        7, 0x05, 0x81, 0x02, 64, 0, 0,
    ])

    STRING_LANGID = bytes([4, 0x03, 0x09, 0x04])

    def get_string_desc(self, index: int) -> bytes:
        """Get string descriptor."""
        strings = [
            self.STRING_LANGID,
            "Raspberry Pi".encode('utf-16-le'),
            f"{self.chip} RP2 Boot".encode('utf-16-le'),
            "E0C912D24340".encode('utf-16-le'),  # Serial number
        ]
        if index == 0:
            return strings[0]
        elif index < len(strings):
            data = strings[index]
            return bytes([len(data) + 2, 0x03]) + data
        return bytes([2, 0x03])

    def handle_control(self, setup: bytes, data: bytes = b'') -> bytes:
        """Handle USB control transfer."""
        bmRequestType = setup[0]
        bRequest = setup[1]
        wValue = setup[2] | (setup[3] << 8)
        wIndex = setup[4] | (setup[5] << 8)
        wLength = setup[6] | (setup[7] << 8)

        self.coverage.record_event('control_transfer', {
            'bmRequestType': bmRequestType,
            'bRequest': bRequest,
            'wValue': wValue,
        })

        # Standard requests (host to device)
        if bmRequestType == 0x00:
            if bRequest == 0x05:  # SET_ADDRESS
                self.address = wValue & 0x7F
                self.log.info(f"SET_ADDRESS: {self.address}")
                return bytes()
            elif bRequest == 0x09:  # SET_CONFIGURATION
                self.configured = True
                self.log.info(f"SET_CONFIGURATION: {wValue}")
                return bytes()

        # Standard requests (device to host)
        elif bmRequestType == 0x80:
            if bRequest == 0x06:  # GET_DESCRIPTOR
                desc_type = (wValue >> 8) & 0xFF
                desc_index = wValue & 0xFF
                if desc_type == 0x01:  # Device
                    return self.device_descriptor[:wLength]
                elif desc_type == 0x02:  # Configuration
                    return self.CONFIG_DESC[:wLength]
                elif desc_type == 0x03:  # String
                    return self.get_string_desc(desc_index)[:wLength]
            elif bRequest == 0x00:  # GET_STATUS
                return bytes([0x00, 0x00])

        # Mass Storage class requests
        elif bmRequestType == 0xA1:
            if bRequest == 0xFE:  # GET_MAX_LUN
                return bytes([0])  # Single LUN

        elif bmRequestType == 0x21:
            if bRequest == 0xFF:  # BULK_ONLY_RESET
                self.log.info("Mass Storage Reset")
                return bytes()

        self.log.warning(f"Unknown control: type=0x{bmRequestType:02X} req=0x{bRequest:02X}")
        return bytes()

    def handle_data_out(self, ep: int, data: bytes) -> int:
        """Handle bulk OUT transfer (CBW or data)."""
        self.coverage.record_event('data_out', {'ep': ep, 'size': len(data)})
        if ep != 1:
            return 0

        # Check for CBW (Command Block Wrapper)
        if len(data) >= 31:
            sig = struct.unpack('<I', data[0:4])[0]
            if sig == self.CBW_SIGNATURE:
                return self._handle_cbw(data)

        # Otherwise it's data for a write command
        if self.expected_data_length > 0:
            self.data_out_buffer.extend(data)
            remaining = self.expected_data_length - len(self.data_out_buffer)
            if remaining <= 0:
                self._process_write_data()

        return len(data)

    def _handle_cbw(self, data: bytes) -> int:
        """Handle Command Block Wrapper."""
        sig, tag, transfer_length, flags, lun, cb_length = struct.unpack('<IIIBBB', data[0:15])
        cb = data[15:15 + cb_length]

        self.cbw_tag = tag
        self.cbw_flags = flags
        self.cbw_transfer_length = transfer_length

        scsi_cmd = cb[0]
        self.log.debug(f"SCSI Command: 0x{scsi_cmd:02X}, len={transfer_length}, flags=0x{flags:02X}")

        if scsi_cmd == self.SCSI_TEST_UNIT_READY:
            self.scsi_response = bytes()
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_REQUEST_SENSE:
            # Return "No sense"
            self.scsi_response = bytes([0x70, 0, 0, 0, 0, 0, 0, 10]) + bytes(10)
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_INQUIRY:
            # Return device info
            self.scsi_response = self._scsi_inquiry()
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_MODE_SENSE_6:
            # Return mode page
            self.scsi_response = bytes([0x03, 0, 0, 0])
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_READ_FORMAT_CAPACITIES:
            # Return capacity
            self.scsi_response = self._scsi_read_format_capacities()
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_READ_CAPACITY_10:
            # Return capacity
            self.scsi_response = self._scsi_read_capacity()
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_READ_10:
            lba = struct.unpack('>I', cb[2:6])[0]
            count = struct.unpack('>H', cb[7:9])[0]
            self.scsi_response = self._scsi_read(lba, count)
            self.scsi_status = 0

        elif scsi_cmd == self.SCSI_WRITE_10:
            lba = struct.unpack('>I', cb[2:6])[0]
            count = struct.unpack('>H', cb[7:9])[0]
            self.current_lba = lba
            self.expected_data_length = count * 512
            self.data_out_buffer.clear()
            self.scsi_response = bytes()
            self.scsi_status = 0

        else:
            self.log.warning(f"Unknown SCSI command: 0x{scsi_cmd:02X}")
            self.scsi_response = bytes()
            self.scsi_status = 1  # Error

        return 31

    def _scsi_inquiry(self) -> bytes:
        """Handle SCSI INQUIRY command."""
        vendor = f"{self.chip[:8]:8s}".encode('ascii')
        product = "RPI-RP2         ".encode('ascii')[:16]
        revision = "1.0 ".encode('ascii')

        return bytes([
            0x00,  # Peripheral type (disk)
            0x80,  # Removable
            0x02,  # Version (SCSI-2)
            0x02,  # Response format
            31,    # Additional length
            0, 0, 0
        ]) + vendor + product + revision

    def _scsi_read_format_capacities(self) -> bytes:
        """Handle READ FORMAT CAPACITIES command."""
        num_blocks = self.fat.NUM_SECTORS
        block_size = self.fat.SECTOR_SIZE
        return bytes([0, 0, 0, 8]) + struct.pack('>IxxH', num_blocks, block_size | 0x0200)

    def _scsi_read_capacity(self) -> bytes:
        """Handle READ CAPACITY (10) command."""
        last_lba = self.fat.NUM_SECTORS - 1
        block_size = self.fat.SECTOR_SIZE
        return struct.pack('>II', last_lba, block_size)

    def _scsi_read(self, lba: int, count: int) -> bytes:
        """Handle SCSI READ (10) command."""
        self.log.debug(f"READ: LBA={lba}, count={count}")
        data = bytearray()
        for i in range(count):
            data.extend(self.fat.read_sector(lba + i))
        return bytes(data)

    def _process_write_data(self):
        """Process received write data."""
        data = bytes(self.data_out_buffer)
        lba = self.current_lba
        count = len(data) // 512

        self.log.debug(f"WRITE: LBA={lba}, count={count}")

        for i in range(count):
            sector_data = data[i * 512:(i + 1) * 512]
            self.fat.write_sector(lba + i, sector_data)

        self.expected_data_length = 0
        self.data_out_buffer.clear()

    def handle_data_in(self, ep: int, max_len: int) -> bytes:
        """Handle bulk IN transfer (response data or CSW)."""
        self.coverage.record_event('data_in', {'ep': ep, 'max_len': max_len})
        if ep != 1:
            return bytes()

        # If we have SCSI response data, send it
        if hasattr(self, 'scsi_response') and self.scsi_response:
            data = self.scsi_response[:max_len]
            self.scsi_response = self.scsi_response[max_len:]
            if not self.scsi_response:
                # Queue CSW for next IN
                self._prepare_csw()
            return data

        # Send CSW
        if hasattr(self, 'csw_ready') and self.csw_ready:
            self.csw_ready = False
            return self._build_csw()

        return bytes()

    def _prepare_csw(self):
        """Prepare CSW for next transfer."""
        self.csw_ready = True

    def _build_csw(self) -> bytes:
        """Build Command Status Wrapper."""
        residue = 0
        status = getattr(self, 'scsi_status', 0)
        return struct.pack('<IIIB', self.CSW_SIGNATURE, self.cbw_tag, residue, status)

    def set_flash_callback(self, callback: Callable[[int, bytes], None]):
        """Set callback for flash programming."""
        self.fat.flash_callback = callback

    def set_upload_complete_callback(self, callback: Callable[[], None]):
        """Set callback for UF2 upload completion (all blocks received)."""
        self.fat.on_upload_complete = callback


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_rp2040_bootloader(arch: str = "ARM") -> RP2040BootromUSB:
    """Create RP2040 bootloader instance."""
    return RP2040BootromUSB(chip="RP2040", arch="ARM")


def create_rp2350_bootloader(arch: str = "ARM") -> RP2040BootromUSB:
    """Create RP2350 bootloader instance.

    Args:
        arch: "ARM" for Cortex-M33, "RISCV" for Hazard3
    """
    return RP2040BootromUSB(chip="RP2350", arch=arch)


def create_uf2_file(data: bytes, base_addr: int = 0x10000000,
                    family_id: int = RP2040_FAMILY_ID) -> bytes:
    """Create a UF2 file from binary data."""
    blocks = []
    offset = 0
    block_no = 0
    num_blocks = (len(data) + 255) // 256

    while offset < len(data):
        chunk = data[offset:offset + 256]
        block = UF2Block(
            flags=UF2_FLAG_FAMILY_ID,
            target_addr=base_addr + offset,
            payload_size=len(chunk),
            block_no=block_no,
            num_blocks=num_blocks,
            family_id=family_id,
            data=chunk.ljust(476, b'\xFF')
        )
        blocks.append(block.to_bytes())
        offset += 256
        block_no += 1

    return b''.join(blocks)
