"""
Raspberry Pi Pico Board Server - Two-Phase Boot Emulation

Emulates a realistic Raspberry Pi Pico (RP2040) or Pico 2 (RP2350) boot flow:

  Phase 1 - USB Boot Mode (BOOTSEL or no valid flash):
    Python-only USB mass storage (RPI-RP2) accepting .UF2 files.
    The user uploads firmware through USBIP, then the board reboots.

  Phase 2 - Flash Boot Mode (valid firmware in flash):
    QEMU runs the real bootrom binary which validates the stage2
    CRC32, then jumps to the application. Peripherals are proxied
    through the TCP peripheral server.

Usage:
    # USB boot (BOOTSEL held):
    python -m slab_rp2040.pico_server --chip rp2040 --bootsel

    # Flash boot (pre-loaded firmware):
    python -m slab_rp2040.pico_server --chip rp2040 \\
        --bootrom slab/roms/rp2040_b2.bin --flash firmware.uf2

    # Auto: USB boot → upload UF2 → reboot into flash:
    python -m slab_rp2040.pico_server --chip rp2040 \\
        --bootrom slab/roms/rp2040_b2.bin --bootsel

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import argparse
import logging
import struct
import sys
import tempfile
import zlib
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Import RP2040 modules
try:
    from .rp2040_server import (
        RP2040Server, RP2040USBIPServer,
        RP2040_CONFIG, RP2350_ARM_CONFIG, RP2350_RISCV_CONFIG,
    )
    from .rp2040_usb_boot import (
        RP2040BootromUSB, create_rp2040_bootloader, create_rp2350_bootloader,
        UF2Block, create_uf2_file,
        RP2040_FAMILY_ID, RP2350_ARM_FAMILY_ID, RP2350_RISCV_FAMILY_ID,
    )
except ImportError:
    from rp2040_server import (
        RP2040Server, RP2040USBIPServer,
        RP2040_CONFIG, RP2350_ARM_CONFIG, RP2350_RISCV_CONFIG,
    )
    from rp2040_usb_boot import (
        RP2040BootromUSB, create_rp2040_bootloader, create_rp2350_bootloader,
        UF2Block, create_uf2_file,
        RP2040_FAMILY_ID, RP2350_ARM_FAMILY_ID, RP2350_RISCV_FAMILY_ID,
    )

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('PicoBoard')


class PicoBootMode(Enum):
    """Boot mode selection."""
    USB_BOOT = auto()     # BOOTSEL held or no valid flash → USB mass storage
    FLASH_BOOT = auto()   # Valid flash image → bootrom validates stage2, runs app


def stage2_crc_valid(flash_data: bytes) -> bool:
    """Check if the first 256 bytes of flash have a valid stage2 CRC32.

    The RP2040/RP2350 bootrom checks bytes 0-251, computes CRC32, and compares
    against the stored CRC at bytes 252-255 (little-endian).

    Args:
        flash_data: Flash image (at least 256 bytes).

    Returns:
        True if the CRC32 matches.
    """
    if len(flash_data) < 256:
        return False
    computed = zlib.crc32(flash_data[:252]) & 0xFFFFFFFF
    stored = struct.unpack('<I', flash_data[252:256])[0]
    return computed == stored


def load_flash_from_file(filepath: Path, chip: str = "RP2040",
                         arch: str = "ARM") -> bytearray:
    """Load a firmware file (.uf2 or .bin) into a flash image bytearray.

    Args:
        filepath: Path to firmware file.
        chip: "RP2040" or "RP2350".
        arch: "ARM" or "RISCV" (for RP2350).

    Returns:
        Flash image bytearray (offset 0 = flash_base).
    """
    data = filepath.read_bytes()
    config = _get_config(chip, arch)
    flash_base = config['flash_base']
    flash_size = min(config['flash_size'], 16 * 1024 * 1024)  # Cap at 16MB
    image = bytearray(b'\xff' * flash_size)

    if filepath.suffix.lower() == '.uf2':
        # Parse UF2 blocks
        offset = 0
        blocks_loaded = 0
        while offset + 512 <= len(data):
            block = UF2Block.from_bytes(data[offset:offset + 512])
            if block:
                dest = block.target_addr - flash_base
                payload = block.data[:block.payload_size]
                if 0 <= dest < flash_size:
                    image[dest:dest + len(payload)] = payload
                    blocks_loaded += 1
            offset += 512
        log.info(f"Loaded {blocks_loaded} UF2 blocks from {filepath.name}")
    else:
        # Raw binary — load at offset 0
        end = min(len(data), flash_size)
        image[:end] = data[:end]
        log.info(f"Loaded {end} bytes from {filepath.name}")

    return image


def _get_config(chip: str, arch: str = "ARM") -> dict:
    """Get chip configuration dict."""
    if chip.upper() == "RP2040":
        return RP2040_CONFIG
    elif chip.upper() == "RP2350":
        if arch.upper() == "RISCV":
            return RP2350_RISCV_CONFIG
        return RP2350_ARM_CONFIG
    raise ValueError(f"Unknown chip: {chip}")


class PicoBoardServer:
    """Two-phase Pico board server.

    Orchestrates the complete boot flow of a Raspberry Pi Pico / Pico 2:
    - Determines boot mode (USB or flash) based on BOOTSEL and flash state
    - Phase 1: Runs Python USB mass storage for UF2 programming
    - Phase 2: Launches QEMU with real bootrom + peripheral proxy
    """

    def __init__(self, chip: str = "rp2040", arch: str = "arm",
                 bootrom: Optional[Path] = None,
                 flash_file: Optional[Path] = None,
                 bootsel: bool = False,
                 tcp_port: int = 5000,
                 usbip_port: int = 3240):
        self.chip = chip.upper()
        self.arch = arch.upper()
        self.bootrom = bootrom
        self.flash_file = flash_file
        self.bootsel = bootsel
        self.tcp_port = tcp_port
        self.usbip_port = usbip_port

        self.config = _get_config(self.chip, self.arch)

        # Flash image (populated from file or UF2 upload)
        flash_size = min(self.config['flash_size'], 16 * 1024 * 1024)
        self.flash_image = bytearray(b'\xff' * flash_size)

        # Load initial flash if provided
        if flash_file and flash_file.exists():
            self.flash_image = load_flash_from_file(
                flash_file, self.chip, self.arch)

        self._upload_complete = asyncio.Event()
        self._phase2_server: Optional[RP2040Server] = None

    @property
    def boot_mode(self) -> PicoBootMode:
        """Determine boot mode based on BOOTSEL and flash state."""
        if self.bootsel:
            return PicoBootMode.USB_BOOT
        if stage2_crc_valid(bytes(self.flash_image)):
            return PicoBootMode.FLASH_BOOT
        return PicoBootMode.USB_BOOT

    def _on_flash_program(self, addr: int, data: bytes):
        """Flash programming callback from USB mass storage."""
        base = self.config['flash_base']
        offset = addr - base
        if 0 <= offset < len(self.flash_image):
            self.flash_image[offset:offset + len(data)] = data

    def _on_upload_complete(self):
        """Called when UF2 upload finishes (all blocks received)."""
        log.info("UF2 upload complete — preparing to reboot into flash mode")
        self._upload_complete.set()

    async def _run_usb_boot(self):
        """Phase 1: Run USB boot mode (Python-only mass storage)."""
        log.info("=" * 60)
        log.info(f"  {self.config['name']} Pico Board — USB Boot Mode")
        log.info("=" * 60)
        log.info(f"BOOTSEL: {'pressed' if self.bootsel else 'released'}")
        log.info(f"Flash:   {'empty/invalid' if self.boot_mode == PicoBootMode.USB_BOOT else 'valid stage2'}")
        log.info("")

        # Create bootloader
        if self.chip == "RP2040":
            usb_boot = create_rp2040_bootloader()
        else:
            usb_boot = create_rp2350_bootloader(arch=self.arch)

        # Wire callbacks
        usb_boot.set_flash_callback(self._on_flash_program)
        usb_boot.set_upload_complete_callback(self._on_upload_complete)

        # Create USBIP server
        usbip_server = RP2040USBIPServer(usb_boot, self.usbip_port)
        usbip_server.running = True

        log.info(f"USB Mass Storage: VID:PID = {usb_boot.USB_VID:04X}:{usb_boot.usb_pid:04X}")
        log.info(f"USBIP server on port {self.usbip_port}")
        log.info("Upload a .UF2 file to program flash")
        log.info("")

        # Start USBIP server
        server = await asyncio.start_server(
            usbip_server.handle_client,
            '0.0.0.0',
            self.usbip_port,
            reuse_address=True,
        )

        async with server:
            # Wait for either upload completion or cancellation
            serve_task = asyncio.ensure_future(server.serve_forever())
            upload_task = asyncio.ensure_future(self._upload_complete.wait())

            done, pending = await asyncio.wait(
                [serve_task, upload_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._upload_complete.is_set():
            log.info("Flash image populated — transitioning to flash boot")
            return True  # Transition to Phase 2

        return False

    async def _run_flash_boot(self):
        """Phase 2: Run flash boot mode (QEMU + real bootrom + peripheral proxy)."""
        if not self.bootrom or not self.bootrom.exists():
            log.error(f"Bootrom binary required for flash boot: {self.bootrom}")
            log.error("Download with: bash slab/scripts/download_rp2040_bootrom.sh")
            return

        log.info("=" * 60)
        log.info(f"  {self.config['name']} Pico Board — Flash Boot Mode")
        log.info("=" * 60)

        # Write flash image to temp file for QEMU
        flash_file = tempfile.NamedTemporaryFile(
            suffix='.bin', prefix='pico_flash_', delete=False)
        flash_file.write(bytes(self.flash_image))
        flash_file.close()
        flash_path = Path(flash_file.name)

        try:
            # Create peripheral proxy server
            server = RP2040Server(
                chip=self.chip.lower(),
                arch=self.arch.lower(),
                port=self.tcp_port,
                usbip_port=self.usbip_port,
            )
            self._phase2_server = server

            # Set BOOTSEL to released so bootrom boots from flash
            io_qspi = server.peripherals.find_peripheral(0x40018000)
            if io_qspi and hasattr(io_qspi, 'set_bootsel'):
                io_qspi.set_bootsel(False)

            # Print QEMU command for user reference
            machine_props = (
                f"slab-cortex-m,cpu-type={self.config['cpu']}"
                f",tcp-port={self.tcp_port}"
                f",flash-base=0x{self.config['flash_base']:X}"
                f",flash-size=0x{min(len(self.flash_image), 0x200000):X}"
                f",sram-base=0x{self.config['sram_base']:X}"
                f",sram-size=0x{self.config['sram_size']:X}"
                f",bootrom-file={self.bootrom}"
                f",bootrom-base=0,bootrom-size=0x{self.config['rom_size']:X}"
                f",periph-base=0x14000000,periph-size=0xbc000200"
                f",sysclk-hz=12000000"
            )

            log.info(f"TCP port:   {self.tcp_port}")
            log.info(f"Bootrom:    {self.bootrom}")
            log.info(f"Flash:      {flash_path} ({len(self.flash_image)} bytes)")
            log.info(f"Stage2 CRC: {'VALID' if stage2_crc_valid(bytes(self.flash_image)) else 'INVALID'}")
            log.info("")
            log.info("Start QEMU with:")
            log.info(f"  qemu-system-arm -M {machine_props} \\")
            log.info(f"    -kernel {flash_path} -nographic")
            log.info("")

            # Start peripheral server (blocks until stopped)
            await server.start()

        finally:
            # Clean up temp flash file
            try:
                flash_path.unlink()
            except OSError:
                pass

    async def run(self):
        """Run the Pico board server.

        Determines boot mode and runs the appropriate phase.
        If USB boot completes with a UF2 upload and a bootrom is available,
        automatically transitions to flash boot.
        """
        mode = self.boot_mode

        if mode == PicoBootMode.USB_BOOT:
            transitioned = await self._run_usb_boot()
            if transitioned and self.bootrom and self.bootrom.exists():
                # UF2 uploaded — reboot into flash mode
                self.bootsel = False  # Release BOOTSEL
                await self._run_flash_boot()
            elif transitioned:
                log.info("UF2 uploaded but no bootrom provided — cannot flash boot")
                log.info("Provide --bootrom to enable automatic reboot")
        else:
            await self._run_flash_boot()

    async def stop(self):
        """Stop all servers."""
        if self._phase2_server:
            await self._phase2_server.stop()


def main():
    parser = argparse.ArgumentParser(
        description='Raspberry Pi Pico Board Server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # USB boot mode (BOOTSEL pressed):
  %(prog)s --chip rp2040 --bootsel

  # Flash boot with pre-loaded firmware:
  %(prog)s --chip rp2040 --bootrom slab/roms/rp2040_b2.bin --flash firmware.uf2

  # USB boot → upload UF2 → auto reboot into flash:
  %(prog)s --chip rp2040 --bootrom slab/roms/rp2040_b2.bin --bootsel

  # RP2350 Pico 2:
  %(prog)s --chip rp2350 --bootrom slab/roms/rp2350_a4.bin --bootsel
""")
    parser.add_argument('--chip', '-c', choices=['rp2040', 'rp2350'],
                        default='rp2040', help='Chip type (default: rp2040)')
    parser.add_argument('--arch', '-a', choices=['arm', 'riscv'],
                        default='arm', help='Architecture for RP2350 (default: arm)')
    parser.add_argument('--bootrom', '-b', type=Path, default=None,
                        help='Path to bootrom binary (enables flash boot)')
    parser.add_argument('--flash', '-f', type=Path, default=None,
                        help='Pre-load firmware (.uf2 or .bin) into flash')
    parser.add_argument('--bootsel', action='store_true',
                        help='Hold BOOTSEL button (force USB boot mode)')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='TCP port for QEMU peripheral proxy (default: 5000)')
    parser.add_argument('--usbip-port', type=int, default=3240,
                        help='USBIP server port (default: 3240)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable debug logging')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    server = PicoBoardServer(
        chip=args.chip,
        arch=args.arch,
        bootrom=args.bootrom,
        flash_file=args.flash,
        bootsel=args.bootsel,
        tcp_port=args.port,
        usbip_port=args.usbip_port,
    )

    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        print("\n[*] Pico board shutdown")


if __name__ == '__main__':
    main()
