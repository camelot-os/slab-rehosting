"""
Base TCP server for MCUemu peripheral proxying.

Handles the binary protocol shared by all SoC servers:
  Read:     [R/S:1][Addr:4][Size:4][Secure:1][PC:4] = 14 bytes
  Write:    [W/T:1][Addr:4][Size:4][Value:4][Secure:1][PC:4] = 18 bytes
  Response: [Value:4][Status:1]
  IRQ:      [I:1][IRQ#:4][Level:1]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
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

# DMA memory access protocol (Python -> QEMU -> Python)
CMD_MEM_READ = ord('M')   # Request memory read from QEMU
CMD_MEM_WRITE = ord('N')  # Request memory write to QEMU
CMD_MEM_RESP = ord('m')   # Memory read response from QEMU
CMD_MEM_ACK = ord('n')    # Memory write acknowledgment from QEMU

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
        self.tracer = None  # Optional[MMIOTracer] -- set to enable MMIO tracing
        self.last_pc: int = 0  # Program counter from last QEMU transaction
        self.log = logging.getLogger(self.__class__.__name__)
        # DMA pending queue: list of (dma_peripheral, channel_index)
        self._dma_pending: list = []

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
                    data = await reader.readexactly(13)
                    address, size = struct.unpack('<II', data[:8])
                    secure = (cmd == CMD_READ_S) or (data[8] == 1)
                    self.last_pc = struct.unpack('<I', data[9:13])[0]

                    periph = self.find_peripheral(address)
                    if periph:
                        value, status = periph.read(address, size, secure)
                    else:
                        value = 0
                        status = STATUS_OK
                        self.log.debug(
                            f"Unmapped read{'[S]' if secure else '[NS]'}: "
                            f"0x{address:08X}")

                    if self.tracer:
                        self.tracer.trace_read(address, size, value, periph,
                                               pc=self.last_pc)

                    resp = struct.pack('<IB', value, status)
                    writer.write(resp)
                    await writer.drain()

                    if self._dma_pending:
                        await self._process_pending_dma(reader, writer)

                elif cmd in (CMD_WRITE, CMD_WRITE_S):
                    data = await reader.readexactly(17)
                    address, size, value = struct.unpack('<III', data[:12])
                    secure = (cmd == CMD_WRITE_S) or (data[12] == 1)
                    self.last_pc = struct.unpack('<I', data[13:17])[0]

                    periph = self.find_peripheral(address)
                    if periph:
                        status = periph.write(address, size, value, secure)
                    else:
                        status = STATUS_OK
                        self.log.debug(
                            f"Unmapped write{'[S]' if secure else '[NS]'}: "
                            f"0x{address:08X} <- 0x{value:08X}")

                    if self.tracer:
                        self.tracer.trace_write(address, size, value, periph,
                                                pc=self.last_pc)

                    resp = struct.pack('<IB', 0, status)
                    writer.write(resp)
                    await writer.drain()

                    if self._dma_pending:
                        await self._process_pending_dma(reader, writer)

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

    def enqueue_dma(self, dma_periph, ch_idx: int):
        """Enqueue a DMA transfer for deferred execution."""
        self._dma_pending.append((dma_periph, ch_idx))

    async def _process_pending_dma(self, reader: asyncio.StreamReader,
                                    writer: asyncio.StreamWriter):
        """Execute pending DMA transfers after MMIO response sent."""
        while self._dma_pending:
            dma_periph, ch_idx = self._dma_pending.pop(0)
            await dma_periph.execute_transfer(ch_idx, self, reader, writer)

    async def dma_mem_read(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           addr: int, size: int) -> bytes:
        """Request bulk memory read from QEMU.

        Sends CMD_MEM_READ, waits for CMD_MEM_RESP, handling any
        interleaved MMIO requests from the CPU while waiting.
        """
        writer.write(struct.pack('<BII', CMD_MEM_READ, addr, size))
        await writer.drain()

        while True:
            tag = await reader.readexactly(1)
            cmd = tag[0]
            if cmd == CMD_MEM_RESP:
                resp_size = struct.unpack('<I',
                                          await reader.readexactly(4))[0]
                return await reader.readexactly(resp_size)
            elif cmd in (CMD_READ, CMD_READ_S, CMD_WRITE, CMD_WRITE_S,
                         CMD_CONFIG):
                await self._handle_mmio_inline(cmd, reader, writer)
            else:
                self.log.warning(f"Unexpected tag during DMA read: {cmd:#x}")
                break
        return b'\x00' * size

    async def dma_mem_write(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter,
                            addr: int, data: bytes) -> int:
        """Request bulk memory write to QEMU.

        Sends CMD_MEM_WRITE, waits for CMD_MEM_ACK, handling any
        interleaved MMIO requests from the CPU while waiting.
        """
        writer.write(struct.pack('<BII', CMD_MEM_WRITE, addr, len(data)))
        writer.write(data)
        await writer.drain()

        while True:
            tag = await reader.readexactly(1)
            cmd = tag[0]
            if cmd == CMD_MEM_ACK:
                status = (await reader.readexactly(1))[0]
                return status
            elif cmd in (CMD_READ, CMD_READ_S, CMD_WRITE, CMD_WRITE_S,
                         CMD_CONFIG):
                await self._handle_mmio_inline(cmd, reader, writer)
            else:
                self.log.warning(f"Unexpected tag during DMA write: {cmd:#x}")
                break
        return 1  # Error

    async def _handle_mmio_inline(self, cmd: int,
                                   reader: asyncio.StreamReader,
                                   writer: asyncio.StreamWriter):
        """Handle an MMIO request that arrived during a DMA wait."""
        if cmd in (CMD_READ, CMD_READ_S):
            data = await reader.readexactly(13)
            address, size = struct.unpack('<II', data[:8])
            secure = (cmd == CMD_READ_S) or (data[8] == 1)
            self.last_pc = struct.unpack('<I', data[9:13])[0]

            periph = self.find_peripheral(address)
            if periph:
                value, status = periph.read(address, size, secure)
            else:
                value, status = 0, STATUS_OK

            if self.tracer:
                self.tracer.trace_read(address, size, value, periph,
                                        pc=self.last_pc)

            writer.write(struct.pack('<IB', value, status))
            await writer.drain()

        elif cmd in (CMD_WRITE, CMD_WRITE_S):
            data = await reader.readexactly(17)
            address, size, value = struct.unpack('<III', data[:12])
            secure = (cmd == CMD_WRITE_S) or (data[12] == 1)
            self.last_pc = struct.unpack('<I', data[13:17])[0]

            periph = self.find_peripheral(address)
            if periph:
                status = periph.write(address, size, value, secure)
            else:
                status = STATUS_OK

            if self.tracer:
                self.tracer.trace_write(address, size, value, periph,
                                         pc=self.last_pc)

            writer.write(struct.pack('<IB', 0, status))
            await writer.drain()

        elif cmd == CMD_CONFIG:
            data = await reader.readexactly(10)
            writer.write(struct.pack('<IB', 0, STATUS_OK))
            await writer.drain()

    def _start_background_tasks(self):
        """Override to start timer loops, PIO stepping, etc."""
        pass

    async def stop(self):
        """Stop the server."""
        self.running = False
