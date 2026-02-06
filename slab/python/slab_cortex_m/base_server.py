"""
Base TCP server for MCUemu peripheral proxying.

Handles the binary protocol shared by all SoC servers:
  Request:  [R/W/S/T:1][Addr:4][Size:4][Value:4 if write][Secure:1]
  Response: [Value:4][Status:1]
  IRQ:      [I:1][IRQ#:4][Level:1]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import struct
import logging
from abc import ABC, abstractmethod
from typing import Optional

# Protocol constants
CMD_READ = ord('R')       # Non-Secure Read
CMD_WRITE = ord('W')      # Non-Secure Write
CMD_READ_S = ord('S')     # Secure Read (TrustZone)
CMD_WRITE_S = ord('T')    # Secure Write (TrustZone)
CMD_IRQ = ord('I')        # IRQ injection
CMD_CONFIG = ord('C')     # Security configuration

STATUS_OK = 0
STATUS_ERROR = 1
STATUS_SECURITY_FAULT = 2


class BasePeripheralServer(ABC):
    """
    Base TCP server for QEMU peripheral proxy protocol.

    Subclasses must implement:
      - create_peripherals() -> populate self.peripherals
      - find_peripheral(addr) -> peripheral or None

    Peripherals must implement:
      - read(addr, size, secure) -> (value, status)
      - write(addr, size, value, secure) -> status
      - contains(addr) -> bool
    """

    def __init__(self, port: int, usbip_port: int = 0):
        self.port = port
        self.usbip_port = usbip_port
        self.running = False
        self.client: Optional[asyncio.StreamWriter] = None
        self.log = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def create_peripherals(self):
        """Create all peripherals. Called before server starts."""
        pass

    @abstractmethod
    def find_peripheral(self, addr: int):
        """Find peripheral containing the given address. Returns None if unmapped."""
        pass

    def send_irq(self, irq_num: int, level: int):
        """Send IRQ injection command to QEMU."""
        if self.client:
            try:
                packet = struct.pack('<BIB', CMD_IRQ, irq_num, level)
                self.client.write(packet)
                self.log.debug(f"IRQ {irq_num} level={level}")
            except Exception as e:
                self.log.warning(f"Failed to send IRQ {irq_num}: {e}")
        else:
            self.log.debug(f"IRQ {irq_num} dropped (no client)")

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        """Handle connected QEMU client -- binary protocol loop."""
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
                    data = await reader.readexactly(9)
                    address, size = struct.unpack('<II', data[:8])
                    secure = (cmd == CMD_READ_S) or (data[8] == 1)

                    periph = self.find_peripheral(address)
                    if periph:
                        value, status = periph.read(address, size, secure)
                    else:
                        value = 0
                        status = STATUS_OK
                        self.log.debug(
                            f"Unmapped read{'[S]' if secure else '[NS]'}: "
                            f"0x{address:08X}")

                    resp = struct.pack('<IB', value, status)
                    writer.write(resp)
                    await writer.drain()

                elif cmd in (CMD_WRITE, CMD_WRITE_S):
                    data = await reader.readexactly(13)
                    address, size, value = struct.unpack('<III', data[:12])
                    secure = (cmd == CMD_WRITE_S) or (data[12] == 1)

                    periph = self.find_peripheral(address)
                    if periph:
                        status = periph.write(address, size, value, secure)
                    else:
                        status = STATUS_OK
                        self.log.debug(
                            f"Unmapped write{'[S]' if secure else '[NS]'}: "
                            f"0x{address:08X} <- 0x{value:08X}")

                    resp = struct.pack('<IB', 0, status)
                    writer.write(resp)
                    await writer.drain()

                elif cmd == CMD_CONFIG:
                    data = await reader.readexactly(10)
                    config_cmd = data[0]
                    region = struct.unpack('<I', data[1:5])[0]
                    limit = struct.unpack('<I', data[5:9])[0]
                    attrs = data[9]

                    self.log.info(
                        f"Security config: cmd={config_cmd} region={region} "
                        f"limit=0x{limit:08X} attrs={attrs}")

                    resp = struct.pack('<IB', 0, STATUS_OK)
                    writer.write(resp)
                    await writer.drain()

                else:
                    self.log.warning(f"Unknown command: {cmd}")

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

    def _start_background_tasks(self):
        """Override to start timer loops, PIO stepping, etc."""
        pass

    async def stop(self):
        """Stop the server."""
        self.running = False
