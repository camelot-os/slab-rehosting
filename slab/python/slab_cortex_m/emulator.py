"""
Cortex-M Emulator Adapter

High-level orchestrator that bridges slab_hw (Avatar2Bridge, HILBridge)
to the actual SLAB board/server infrastructure.  Provides the CortexM
and CortexMConfig classes that avatar2_hil.py and hil.py import.

Usage (from Avatar2Bridge):
    from slab_cortex_m import CortexM, CortexMConfig

    config = CortexMConfig(machine="STM32F405", firmware_path="app.bin")
    emu = CortexM(config)
    emu.start()
    data = emu.mem_read(0x40020000, 4)
    emu.stop()

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import logging
import os
import signal
import struct
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger('CortexM')


@dataclass
class CortexMConfig:
    """Configuration for a Cortex-M emulator instance."""
    machine: str                                  # MCU name: "STM32F405", "nRF52840"
    firmware_path: Optional[str] = None
    port: int = 5555
    trace_mmio: bool = False
    board_yaml: Optional[str] = None              # Optional board YAML path
    qemu_path: str = "build/qemu-system-arm"
    hil_peripherals: List[dict] = field(default_factory=list)
    qemu_extra: Dict[str, str] = field(default_factory=dict)


# Alias for hil.py compatibility
EmulatorConfig = CortexMConfig


class CortexM:
    """
    High-level Cortex-M emulator orchestrator.

    Manages a SLAB Board + optional QEMU process together.
    Used by Avatar2Bridge and HILBridge as the emulator target.

    Two modes of operation:
    1. Board-only (no QEMU): create board, forward mem_read/mem_write
       through the peripheral adapter. Useful for peripheral-only testing.
    2. Full emulation (with QEMU): launch QEMU subprocess connected to a
       BasePeripheralServer backed by the board. Firmware runs in QEMU,
       MMIO is proxied through the Python peripheral models.
    """

    def __init__(self, config: CortexMConfig):
        self.config = config
        self.board = None
        self.server = None
        self.qemu_process = None
        self._running = False
        self._server_thread = None
        self._loop = None

    def start(self, firmware_path: Optional[str] = None) -> bool:
        """
        Build board and optionally start QEMU + peripheral server.

        Args:
            firmware_path: Override firmware path from config.

        Returns:
            True if board was created successfully.
        """
        fw = firmware_path or self.config.firmware_path

        # Build the board
        self.board = self._build_board()
        if self.board is None:
            return False

        # Inject HIL peripherals
        self._inject_hil_peripherals()

        # If firmware path is given, start QEMU + server
        if fw and os.path.isfile(fw):
            self._start_server_and_qemu(fw)

        self._running = True
        log.info("CortexM emulator started (machine=%s)", self.config.machine)
        return True

    def stop(self):
        """Stop QEMU process and peripheral server."""
        if self.qemu_process:
            try:
                self.qemu_process.terminate()
                self.qemu_process.wait(timeout=5)
            except Exception:
                self.qemu_process.kill()
            self.qemu_process = None

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=5)

        self._running = False
        self.server = None
        log.info("CortexM emulator stopped")

    def reset(self) -> bool:
        """Reset emulator by restarting QEMU."""
        fw = self.config.firmware_path
        if self.qemu_process:
            self.stop()
            return self.start(fw)
        # Board-only mode: just rebuild
        self.board = self._build_board()
        self._inject_hil_peripherals()
        return self.board is not None

    def mem_read(self, addr: int, size: int) -> bytes:
        """
        Read memory through the board peripheral adapter.

        Used by HILBridge.forward_memory_access() to forward accesses
        from hardware to the emulated peripheral model.
        """
        if self.board is None:
            return b'\x00' * size

        if self.board.contains(addr):
            result = self.board.read(addr, size, secure=True)
            value = result[0] if isinstance(result, tuple) else result
            if size == 4:
                return struct.pack('<I', value & 0xFFFFFFFF)
            elif size == 2:
                return struct.pack('<H', value & 0xFFFF)
            elif size == 1:
                return struct.pack('<B', value & 0xFF)
            return struct.pack('<I', value & 0xFFFFFFFF)

        return b'\x00' * size

    def mem_write(self, addr: int, data: bytes):
        """
        Write memory through the board peripheral adapter.

        Used by HILBridge.forward_memory_access() to forward accesses
        from hardware to the emulated peripheral model.
        """
        if self.board is None:
            return

        if self.board.contains(addr):
            size = len(data)
            if size == 4:
                value = struct.unpack('<I', data)[0]
            elif size == 2:
                value = struct.unpack('<H', data)[0]
            elif size == 1:
                value = data[0]
            else:
                value = struct.unpack('<I', data[:4])[0]
            self.board.write(addr, size, value, secure=True)

    def read_register(self, name: str) -> int:
        """
        Read CPU register.

        In board-only mode this is not supported (would require GDB stub).
        Returns 0 as placeholder.
        """
        return 0

    def write_register(self, name: str, value: int):
        """Write CPU register (not supported in board-only mode)."""
        pass

    def get_state(self) -> dict:
        """Return emulator state as a dict."""
        state = {
            'running': self._running,
            'machine': self.config.machine,
            'has_qemu': self.qemu_process is not None,
            'has_board': self.board is not None,
        }
        if self.board:
            state['peripherals'] = len(self.board.adapter.peripherals)
            state['hil_peripherals'] = len(
                getattr(self.board, 'hil_peripherals', []))
        return state

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _build_board(self):
        """Build a Board from config."""
        try:
            if self.config.board_yaml:
                from slab_cortex_m.board import load_board_config
                from slab_cortex_m.board_builder import build_board
                board_config = load_board_config(self.config.board_yaml)
                return build_board(board_config)

            # Build from MCU name
            from slab_cortex_m.board import BoardConfig
            from slab_cortex_m.board_builder import build_board
            board_config = BoardConfig(
                name=f"{self.config.machine}_HIL",
                mcu=self.config.machine,
                qemu_extra=dict(self.config.qemu_extra),
            )
            return build_board(board_config)

        except Exception as e:
            log.error("Failed to build board: %s", e)
            return None

    def _inject_hil_peripherals(self):
        """Inject HIL peripherals from config into the board."""
        if not self.board or not self.config.hil_peripherals:
            return

        from slab_cortex_m.hil_peripheral import create_hil_peripheral

        if not hasattr(self.board, 'hil_peripherals'):
            self.board.hil_peripherals = []

        for hil_cfg in self.config.hil_peripherals:
            try:
                hil = create_hil_peripheral(hil_cfg)
                self.board.hil_peripherals.append(hil)
                log.info("Injected HIL peripheral: %s @ 0x%08X",
                         hil.name, hil.base)
            except Exception as e:
                log.error("Failed to create HIL peripheral: %s", e)

    def _start_server_and_qemu(self, firmware_path: str):
        """Start peripheral server in a thread and launch QEMU."""
        from slab_cortex_m.base_server import BasePeripheralServer
        from slab_cortex_m.board import get_qemu_cpu, get_default_clock

        board = self.board

        class _EmulatorServer(BasePeripheralServer):
            def __init__(self, port, brd):
                super().__init__(port)
                self.board = brd
                self.board.irq_callback = self.send_irq

            def create_peripherals(self):
                pass

            def find_peripheral(self, addr):
                # Check HIL peripherals first
                for hil in getattr(self.board, 'hil_peripherals', []):
                    if hil.contains(addr):
                        return hil
                if self.board.contains(addr):
                    return self.board
                return None

        self.server = _EmulatorServer(self.config.port, board)

        def _run_server():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self.server.running = True

            async def _serve():
                tcp_server = await asyncio.start_server(
                    self.server.handle_client,
                    '127.0.0.1', self.config.port,
                    reuse_address=True)
                await tcp_server.serve_forever()

            try:
                self._loop.run_until_complete(_serve())
            except Exception:
                pass

        self._server_thread = threading.Thread(
            target=_run_server, daemon=True)
        self._server_thread.start()

        # Build QEMU command
        qemu_cpu = board.qemu_cpu
        clock = board.clock

        cmd = [
            self.config.qemu_path,
            '-M', f'slab-cortex-m,cpu-type={qemu_cpu},'
                  f'tcp-port={self.config.port},'
                  f'sysclk-hz={clock}',
            '-kernel', firmware_path,
            '-nographic',
            '-monitor', 'none',
        ]

        # Add extra QEMU properties
        for key, val in self.config.qemu_extra.items():
            # Append to machine properties
            cmd[2] += f',{key}={val}'

        try:
            self.qemu_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            log.info("QEMU started (PID %d)", self.qemu_process.pid)
        except FileNotFoundError:
            log.warning("QEMU binary not found: %s", self.config.qemu_path)
            self.qemu_process = None


# Alias for hil.py compatibility
Emulator = CortexM
