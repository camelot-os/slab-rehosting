#!/usr/bin/env python3
"""
RP2040/RP2350 Peripheral Server

Integrated server for RP2040 and RP2350 emulation:
- Works with slab-cortex-m (ARM) or slab-riscv (RISC-V Hazard3)
- Full GPIO, SIO, Timer, Clocks, Resets peripheral support
- USB bootloader mass storage emulation
- USBIP integration for host connectivity

Usage:
    # RP2040 (Cortex-M0+)
    python3 rp2040_server.py --chip rp2040 --port 5000

    # RP2350 ARM (Cortex-M33)
    python3 rp2040_server.py --chip rp2350 --arch arm --port 5000

    # RP2350 RISC-V (Hazard3)
    python3 rp2040_server.py --chip rp2350 --arch riscv --port 5000

QEMU commands:
    # RP2040 (ARM)
    qemu-system-arm -M slab-cortex-m -cpu cortex-m0 -smp 2 \
        -global slab-cortex-m.tcp-port=5000 \
        -kernel firmware.bin

    # RP2350 ARM
    qemu-system-arm -M slab-cortex-m -cpu cortex-m33 -smp 2 \
        -global slab-cortex-m.tcp-port=5000 \
        -kernel firmware.bin

    # RP2350 RISC-V
    qemu-system-riscv32 -M slab-riscv -smp 2 \
        -global slab-riscv.tcp-port=5000 \
        -kernel firmware.bin

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
import argparse
import sys
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path

# Import RP2040 peripheral modules
try:
    from .rp2040_peripherals import RP2040PeripheralSet
    from .rp2040_usb_boot import (
        RP2040BootromUSB, create_rp2040_bootloader, create_rp2350_bootloader,
        RP2040BootromFAT, create_uf2_file
    )
except ImportError:
    from rp2040_peripherals import RP2040PeripheralSet
    from rp2040_usb_boot import (
        RP2040BootromUSB, create_rp2040_bootloader, create_rp2350_bootloader,
        RP2040BootromFAT, create_uf2_file
    )

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('RP2040')


# =============================================================================
# PROTOCOL CONSTANTS
# =============================================================================

CMD_READ = ord('R')       # Non-Secure Read
CMD_WRITE = ord('W')      # Non-Secure Write
CMD_READ_S = ord('S')     # Secure Read (TrustZone)
CMD_WRITE_S = ord('T')    # Secure Write (TrustZone)
CMD_IRQ = ord('I')        # IRQ injection
CMD_CONFIG = ord('C')     # Security configuration
CMD_DMA = ord('D')        # DMA operation

STATUS_OK = 0
STATUS_ERROR = 1
STATUS_SECURITY_FAULT = 2


# =============================================================================
# CHIP CONFIGURATIONS
# =============================================================================

RP2040_CONFIG = {
    'name': 'RP2040',
    'description': 'Raspberry Pi Pico - Dual Cortex-M0+ @ 133MHz',
    'cpu': 'cortex-m0',
    'cores': 2,
    'frequency': 133_000_000,
    'sram_base': 0x20000000,
    'sram_size': 264 * 1024,  # 264KB
    'flash_base': 0x10000000,
    'flash_size': 16 * 1024 * 1024,  # 16MB address space
    'rom_base': 0x00000000,
    'rom_size': 16 * 1024,  # 16KB bootrom
    'qemu_machine': 'slab-cortex-m',
    'qemu_command': 'qemu-system-arm',
}

RP2350_ARM_CONFIG = {
    'name': 'RP2350-ARM',
    'description': 'Raspberry Pi Pico 2 - Dual Cortex-M33 @ 150MHz',
    'cpu': 'cortex-m33',
    'cores': 2,
    'frequency': 150_000_000,
    'sram_base': 0x20000000,
    'sram_size': 520 * 1024,  # 520KB
    'flash_base': 0x10000000,
    'flash_size': 64 * 1024 * 1024,  # 64MB address space
    'rom_base': 0x00000000,
    'rom_size': 32 * 1024,  # 32KB bootrom
    'trustzone': True,
    'qemu_machine': 'slab-cortex-m',
    'qemu_command': 'qemu-system-arm',
}

RP2350_RISCV_CONFIG = {
    'name': 'RP2350-RISCV',
    'description': 'Raspberry Pi Pico 2 - Dual Hazard3 RISC-V @ 150MHz',
    'cpu': 'hazard3',
    'isa': 'rv32imac_zicsr_zifencei_zba_zbb_zbs_zbkb',
    'cores': 2,
    'frequency': 150_000_000,
    'sram_base': 0x20000000,
    'sram_size': 520 * 1024,  # 520KB
    'flash_base': 0x10000000,
    'flash_size': 64 * 1024 * 1024,  # 64MB address space
    'rom_base': 0x00000000,
    'rom_size': 32 * 1024,  # 32KB bootrom
    'qemu_machine': 'slab-riscv',
    'qemu_command': 'qemu-system-riscv32',
}


# =============================================================================
# RP2040/RP2350 PERIPHERAL SERVER
# =============================================================================

class RP2040Server:
    """
    Integrated peripheral server for RP2040/RP2350.

    Handles:
    - TCP proxy connection from QEMU (slab-cortex-m or slab-riscv)
    - Peripheral emulation (GPIO, SIO, Timer, etc.)
    - USB bootloader emulation
    - Optional USBIP server for host connectivity
    """

    def __init__(self, chip: str = "rp2040", arch: str = "arm",
                 port: int = 5000, usbip_port: int = 3240):
        self.port = port
        self.usbip_port = usbip_port
        self.running = False
        self.client = None

        # Select chip configuration
        if chip.lower() == "rp2040":
            self.config = RP2040_CONFIG
            self.arch = "ARM"
        elif chip.lower() == "rp2350":
            if arch.lower() == "riscv":
                self.config = RP2350_RISCV_CONFIG
                self.arch = "RISCV"
            else:
                self.config = RP2350_ARM_CONFIG
                self.arch = "ARM"
        else:
            raise ValueError(f"Unknown chip: {chip}")

        self.chip = self.config['name'].split('-')[0]

        # Create peripherals
        self.peripherals = RP2040PeripheralSet(
            chip=self.chip,
            log=logging.getLogger(f'{self.chip}.Periph')
        )
        self.peripherals.irq_callback = self._send_irq

        # Create USB bootloader
        if self.chip == "RP2040":
            self.usb_boot = create_rp2040_bootloader()
        else:
            self.usb_boot = create_rp2350_bootloader(arch=self.arch)

        self.usb_boot.set_flash_callback(self._on_flash_program)

        # Flash storage
        self.flash_image = bytearray(self.config['flash_size'])

        self.log = log

    def _send_irq(self, irq_num: int, level: int):
        """Send IRQ injection to QEMU."""
        if self.client:
            try:
                packet = struct.pack('<BIB', CMD_IRQ, irq_num, level)
                self.client.write(packet)
            except Exception as e:
                self.log.warning(f"Failed to send IRQ: {e}")

    def _on_flash_program(self, addr: int, data: bytes):
        """Handle flash programming from USB bootloader."""
        # Store in flash image
        base = self.config['flash_base']
        offset = addr - base
        if 0 <= offset < len(self.flash_image):
            self.flash_image[offset:offset + len(data)] = data
            self.log.info(f"Flash programmed: 0x{addr:08X} ({len(data)} bytes)")

    def _find_peripheral(self, addr: int):
        """Find peripheral at address."""
        return self.peripherals.find_peripheral(addr)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle QEMU client connection."""
        addr = writer.get_extra_info('peername')
        self.log.info(f"QEMU connected from {addr}")
        self.client = writer

        try:
            while self.running:
                cmd_type = await reader.read(1)
                if not cmd_type:
                    break

                cmd = cmd_type[0]

                if cmd in (CMD_READ, CMD_READ_S):
                    # Read: [addr:4][size:4][secure:1]
                    data = await reader.readexactly(9)
                    address, size = struct.unpack('<II', data[:8])
                    secure = (cmd == CMD_READ_S) or (data[8] == 1)

                    periph = self._find_peripheral(address)
                    if periph:
                        value, status = periph.read(address, size, secure)
                    else:
                        # Check if reading flash
                        if self.config['flash_base'] <= address < self.config['flash_base'] + self.config['flash_size']:
                            offset = address - self.config['flash_base']
                            value = int.from_bytes(self.flash_image[offset:offset + size], 'little')
                            status = STATUS_OK
                        else:
                            value = 0
                            status = STATUS_OK
                            self.log.debug(f"Unmapped read: 0x{address:08X}")

                    resp = struct.pack('<IB', value, status)
                    writer.write(resp)
                    await writer.drain()

                elif cmd in (CMD_WRITE, CMD_WRITE_S):
                    # Write: [addr:4][size:4][value:4][secure:1]
                    data = await reader.readexactly(13)
                    address, size, value = struct.unpack('<III', data[:12])
                    secure = (cmd == CMD_WRITE_S) or (data[12] == 1)

                    periph = self._find_peripheral(address)
                    if periph:
                        status = periph.write(address, size, value, secure)
                    else:
                        status = STATUS_OK
                        self.log.debug(f"Unmapped write: 0x{address:08X} <- 0x{value:08X}")

                    resp = struct.pack('<IB', 0, status)
                    writer.write(resp)
                    await writer.drain()

                elif cmd == CMD_DMA:
                    # DMA: [channel:1][op:1][src:4][dst:4][len:4] = 14 bytes
                    data = await reader.readexactly(14)
                    channel, op, src, dst, length = struct.unpack('<BBIII', data)

                    # Handle DMA operation
                    status = await self._handle_dma(channel, op, src, dst, length)

                    resp = struct.pack('<IB', length, status)
                    writer.write(resp)
                    await writer.drain()

                elif cmd == CMD_CONFIG:
                    # Security configuration
                    data = await reader.readexactly(10)
                    config_cmd = data[0]
                    region = struct.unpack('<I', data[1:5])[0]
                    limit = struct.unpack('<I', data[5:9])[0]
                    attrs = data[9]

                    self.log.info(f"Security config: cmd={config_cmd} region={region}")

                    resp = struct.pack('<IB', 0, STATUS_OK)
                    writer.write(resp)
                    await writer.drain()

                else:
                    self.log.warning(f"Unknown command: 0x{cmd:02X}")

        except asyncio.IncompleteReadError:
            self.log.info("QEMU disconnected (incomplete read)")
        except ConnectionResetError:
            self.log.info("QEMU disconnected (reset)")
        except Exception as e:
            self.log.error(f"Client error: {e}")
        finally:
            self.client = None
            writer.close()
            await writer.wait_closed()
            self.log.info("QEMU disconnected")

    async def _handle_dma(self, channel: int, op: int, src: int, dst: int, length: int) -> int:
        """Handle DMA operation."""
        self.log.debug(f"DMA ch{channel}: op={op} src=0x{src:08X} dst=0x{dst:08X} len={length}")

        if op == 0:  # Read
            # Read from memory
            data = self._read_memory(src, length)
            # Could forward to Python for processing
            return STATUS_OK

        elif op == 1:  # Write
            # Write to memory handled by QEMU
            return STATUS_OK

        elif op == 2:  # Copy
            # Memory-to-memory copy
            data = self._read_memory(src, length)
            self._write_memory(dst, data)
            return STATUS_OK

        return STATUS_ERROR

    def _read_memory(self, addr: int, length: int) -> bytes:
        """Read from emulated memory."""
        if self.config['flash_base'] <= addr < self.config['flash_base'] + self.config['flash_size']:
            offset = addr - self.config['flash_base']
            return bytes(self.flash_image[offset:offset + length])
        return bytes(length)

    def _write_memory(self, addr: int, data: bytes):
        """Write to emulated memory."""
        if self.config['flash_base'] <= addr < self.config['flash_base'] + self.config['flash_size']:
            offset = addr - self.config['flash_base']
            self.flash_image[offset:offset + len(data)] = data

    async def start(self):
        """Start the peripheral server."""
        self.running = True

        # Start TCP server for QEMU
        server = await asyncio.start_server(
            self._handle_client,
            '127.0.0.1',
            self.port,
            reuse_address=True
        )

        # Print banner
        print("\n" + "=" * 76)
        print(f"  {self.config['name']} Peripheral Server")
        print(f"  {self.config['description']}")
        print("=" * 76)
        print(f"\n[Architecture] {self.arch}")
        print(f"[TCP Port]     {self.port}")
        print(f"[USBIP Port]   {self.usbip_port}")

        print(f"\n[Peripherals]")
        for name, periph in self.peripherals._peripherals.items():
            irq_str = f"IRQ {periph.irq}" if hasattr(periph, 'irq') and periph.irq >= 0 else ""
            print(f"  {name:12} @ 0x{periph.base:08X} - 0x{periph.base + periph.size - 1:08X} {irq_str}")

        print(f"\n[QEMU Command]")
        if self.arch == "RISCV":
            print(f"  {self.config['qemu_command']} -M {self.config['qemu_machine']} -smp {self.config['cores']} \\")
            print(f"    -global {self.config['qemu_machine']}.tcp-port={self.port} \\")
            print(f"    -kernel firmware.bin")
        else:
            print(f"  {self.config['qemu_command']} -M {self.config['qemu_machine']} -cpu {self.config['cpu']} -smp {self.config['cores']} \\")
            if self.config.get('trustzone'):
                print(f"    -global {self.config['qemu_machine']}.trustzone=on \\")
            print(f"    -global {self.config['qemu_machine']}.tcp-port={self.port} \\")
            print(f"    -kernel firmware.bin")

        print(f"\n[USB Bootloader]")
        print(f"  VID:PID = {self.usb_boot.USB_VID:04X}:{self.usb_boot.usb_pid:04X}")
        print(f"  Volume: RPI-RP2")
        print()

        async with server:
            await server.serve_forever()

    async def stop(self):
        """Stop the server."""
        self.running = False


# =============================================================================
# USBIP SERVER FOR RP2040 BOOTLOADER
# =============================================================================

class RP2040USBIPServer:
    """
    USBIP server exposing the RP2040 bootloader mass storage device.

    Allows the host to interact with the emulated bootrom USB mass storage
    and program firmware via .UF2 files.
    """

    USBIP_VERSION = 0x0111

    # USBIP commands
    OP_REQ_DEVLIST = 0x8005
    OP_REP_DEVLIST = 0x0005
    OP_REQ_IMPORT = 0x8003
    OP_REP_IMPORT = 0x0003
    USBIP_CMD_SUBMIT = 0x00000001
    USBIP_RET_SUBMIT = 0x00000003
    USBIP_CMD_UNLINK = 0x00000002
    USBIP_RET_UNLINK = 0x00000004

    def __init__(self, usb_device: RP2040BootromUSB, port: int = 3240):
        self.port = port
        self.usb = usb_device
        self.running = False
        self.log = logging.getLogger('USBIP')

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle USBIP client."""
        addr = writer.get_extra_info('peername')
        self.log.info(f"USBIP client connected: {addr}")
        imported = False

        try:
            while self.running:
                if not imported:
                    header = await reader.read(8)
                    if not header or len(header) < 8:
                        break

                    version, command = struct.unpack('>HxxxxH', header)
                    self.log.debug(f"Command: 0x{command:04X}")

                    if command == self.OP_REQ_DEVLIST:
                        await self._handle_devlist(writer)
                    elif command == self.OP_REQ_IMPORT:
                        imported = await self._handle_import(reader, writer)
                    else:
                        break
                else:
                    header = await reader.read(4)
                    if not header:
                        break

                    command = struct.unpack('>I', header)[0]

                    if command == self.USBIP_CMD_SUBMIT:
                        await self._handle_submit(reader, writer, header)
                    elif command == self.USBIP_CMD_UNLINK:
                        await self._handle_unlink(reader, writer, header)
                    else:
                        break

        except Exception as e:
            self.log.error(f"USBIP error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
            self.log.info("USBIP client disconnected")

    async def _handle_devlist(self, writer: asyncio.StreamWriter):
        """Handle device list request."""
        self.log.info("Device list requested")

        # Pack device info
        path = b'/sys/devices/platform/rp2040/usb1/1-1'.ljust(256, b'\x00')
        busid = b'1-1'.ljust(32, b'\x00')

        response = struct.pack('>HHI', self.USBIP_VERSION, self.OP_REP_DEVLIST, 0)
        response += struct.pack('>I', 1)  # One device
        response += path + busid
        response += struct.pack('>IIIHHHBBBBBB',
            1, 1, 2,  # busnum, devnum, speed (FULL)
            self.usb.USB_VID, self.usb.usb_pid, 0x0100,  # VID, PID, bcdDevice
            0x00, 0x00, 0x00,  # Device class (defined at interface)
            1, 1, 1  # bConfigurationValue, bNumConfigurations, bNumInterfaces
        )
        # Interface info
        response += struct.pack('>BBBB', 0x08, 0x06, 0x50, 0x00)  # MSC

        writer.write(response)
        await writer.drain()

    async def _handle_import(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> bool:
        """Handle device import request."""
        busid_data = await reader.read(32)
        busid = busid_data.rstrip(b'\x00').decode('utf-8')
        self.log.info(f"Import requested: {busid}")

        if busid == "1-1":
            path = b'/sys/devices/platform/rp2040/usb1/1-1'.ljust(256, b'\x00')
            busid_bytes = b'1-1'.ljust(32, b'\x00')

            response = struct.pack('>HHI', self.USBIP_VERSION, self.OP_REP_IMPORT, 0)
            response += path + busid_bytes
            response += struct.pack('>IIIHHHBBBBBB',
                1, 1, 2,
                self.usb.USB_VID, self.usb.usb_pid, 0x0100,
                0x00, 0x00, 0x00,
                1, 1, 1
            )

            writer.write(response)
            await writer.drain()
            self.log.info("Device imported successfully")
            return True
        else:
            response = struct.pack('>HHI', self.USBIP_VERSION, self.OP_REP_IMPORT, 1)
            writer.write(response)
            await writer.drain()
            return False

    async def _handle_submit(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, header: bytes):
        """Handle URB submit."""
        submit_data = header + await reader.read(44)

        seqnum = struct.unpack('>I', submit_data[4:8])[0]
        devid = struct.unpack('>I', submit_data[8:12])[0]
        direction = struct.unpack('>I', submit_data[12:16])[0]
        ep = struct.unpack('>I', submit_data[16:20])[0]
        transfer_flags = struct.unpack('>I', submit_data[20:24])[0]
        transfer_length = struct.unpack('>I', submit_data[24:28])[0]
        setup = submit_data[40:48]

        # Read OUT data
        out_data = bytes()
        if direction == 0 and transfer_length > 0:
            out_data = await reader.read(transfer_length)

        # Handle request
        response_data = bytes()
        actual_length = 0
        status = 0

        if ep == 0:
            # Control transfer
            if direction == 0:
                response_data = self.usb.handle_control(setup, out_data)
            else:
                response_data = self.usb.handle_control(setup)
            actual_length = len(response_data)
        else:
            # Bulk transfer
            if direction == 0:
                actual_length = self.usb.handle_data_out(ep, out_data)
            else:
                response_data = self.usb.handle_data_in(ep, transfer_length)
                actual_length = len(response_data)

        # Build response
        resp = struct.pack('>IIIII',
            self.USBIP_RET_SUBMIT, seqnum, devid, direction, ep
        )
        resp += struct.pack('>iIIIIxxxxxxxx', status, actual_length, 0, 0, 0)

        if direction != 0:
            resp += response_data.ljust(transfer_length, b'\x00')[:transfer_length]

        writer.write(resp)
        await writer.drain()

    async def _handle_unlink(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, header: bytes):
        """Handle unlink request."""
        data = header + await reader.read(44)
        seqnum = struct.unpack('>I', data[4:8])[0]

        resp = struct.pack('>IIIII', self.USBIP_RET_UNLINK, seqnum, 0, 0, 0)
        resp += struct.pack('>i', -104)
        resp += bytes(44)

        writer.write(resp)
        await writer.drain()

    async def start(self):
        """Start the USBIP server."""
        self.running = True

        server = await asyncio.start_server(
            self.handle_client,
            '0.0.0.0',
            self.port,
            reuse_address=True
        )

        self.log.info(f"USBIP server started on port {self.port}")
        self.log.info(f"Device: {self.usb.chip} ({self.usb.USB_VID:04X}:{self.usb.usb_pid:04X})")
        self.log.info("To attach: sudo usbip attach -r localhost -b 1-1")

        async with server:
            await server.serve_forever()

    async def stop(self):
        """Stop the USBIP server."""
        self.running = False


# =============================================================================
# MAIN
# =============================================================================

async def main_async(args):
    """Main async entry point."""
    # Create peripheral server
    server = RP2040Server(
        chip=args.chip,
        arch=args.arch,
        port=args.port,
        usbip_port=args.usbip_port
    )

    # Create USBIP server if enabled
    usbip_server = None
    if args.usbip:
        usbip_server = RP2040USBIPServer(server.usb_boot, args.usbip_port)

    try:
        if usbip_server:
            # Run both servers
            await asyncio.gather(
                server.start(),
                usbip_server.start()
            )
        else:
            await server.start()
    except asyncio.CancelledError:
        await server.stop()
        if usbip_server:
            await usbip_server.stop()


def main():
    parser = argparse.ArgumentParser(description='RP2040/RP2350 Peripheral Server')
    parser.add_argument('--chip', '-c', choices=['rp2040', 'rp2350'], default='rp2040',
                        help='Chip type (default: rp2040)')
    parser.add_argument('--arch', '-a', choices=['arm', 'riscv'], default='arm',
                        help='Architecture for RP2350 (default: arm)')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='TCP port for QEMU (default: 5000)')
    parser.add_argument('--usbip', action='store_true',
                        help='Enable USBIP server for bootloader mass storage')
    parser.add_argument('--usbip-port', type=int, default=3240,
                        help='USBIP port (default: 3240)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\n[*] Shutdown")


if __name__ == '__main__':
    main()
