#!/usr/bin/env python3
"""
Raspberry Pi Pico Dashboard with Debug Visualization

Real-time emulation dashboard for RP2040 firmware, featuring:
- GPIO25 LED status (Pico built-in LED)
- UART0 console output
- PIO state machine monitoring (SM0-SM3 activity)
- Logic analyzer with GPIO, PIO, and UART channels
- Auto-start emulation with QEMU

Usage:
    PYTHONPATH=slab/python python3 slab/examples/cortex-m/rp2040/run_pico_dashboard.py [--verbose]
    PYTHONPATH=slab/python python3 slab/examples/cortex-m/rp2040/run_pico_dashboard.py --firmware path/to/fw.bin

Close the window or press ESC to stop.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
"""

import os
import sys
import time
import asyncio
import logging
import threading
import subprocess
from pathlib import Path

# Add python path
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "python"))

import pygame
from slab_rp2040 import RP2040PeripheralSet
from slab_cortex_m.base_server import BasePeripheralServer
from slab_gui.debug_dashboard import DebugDashboardPro, SignalCapture

# Paths
QEMU_PATHS = [
    PROJECT_DIR.parent / "build" / "qemu-system-arm",
    PROJECT_DIR.parent / "qemu" / "build" / "qemu-system-arm",
    Path("/usr/bin/qemu-system-arm"),
]
QEMU_BIN = next((p for p in QEMU_PATHS if p.exists()), QEMU_PATHS[0])
DEFAULT_FW = SCRIPT_DIR / "demos" / "pico_dashboard" / "build" / "pico_dashboard.bin"

# RP2040 memory map
FLASH_BASE = 0x10000000
SRAM_BASE = 0x20000000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)-8s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('Pico')


class PicoServer(BasePeripheralServer):
    """TCP server bridging QEMU MMIO to RP2040 peripheral set."""

    def __init__(self, ps, port):
        super().__init__(port)
        self.ps = ps
        self.mmio_count = 0

    def create_peripherals(self):
        pass  # Already created externally

    def find_peripheral(self, addr):
        p = self.ps.find_peripheral(addr)
        if p is not None:
            self.mmio_count += 1
            return self  # Return self as proxy (like DirectServer pattern)
        return None

    def read(self, addr, size, secure=True):
        p = self.ps.find_peripheral(addr)
        if p:
            return p.read(addr, size)
        return (0, 0)

    def write(self, addr, size, value, secure=True):
        p = self.ps.find_peripheral(addr)
        if p:
            return p.write(addr, size, value)
        return 0

    def contains(self, addr):
        return self.ps.find_peripheral(addr) is not None


class UARTLineBuffer:
    """Buffers UART byte-at-a-time callbacks and emits complete lines."""

    def __init__(self, dashboard, console="uart"):
        self.dashboard = dashboard
        self.console = console
        self.buf = bytearray()

    def on_tx(self, data):
        self.buf.extend(data)
        while b'\n' in self.buf:
            idx = self.buf.index(b'\n')
            line = self.buf[:idx].decode('utf-8', errors='replace').rstrip('\r')
            self.buf = self.buf[idx + 1:]
            if self.console == "uart":
                self.dashboard.add_uart_line(line)
            else:
                self.dashboard.add_cdc_line(line)
            self.dashboard.capture.record("UART_TX", 1)
            self.dashboard.capture.record("UART_TX", 0)


class PicoEmulationController:
    """Controls RP2040 emulation lifecycle with dashboard integration."""

    def __init__(self, dashboard: DebugDashboardPro, firmware: Path,
                 port: int = 5000, verbose: bool = False):
        self.dashboard = dashboard
        self.firmware = firmware
        self.port = port
        self.verbose = verbose

        # State
        self.peripherals = None
        self.server = None
        self.server_thread = None
        self.qemu_proc = None
        self.running = False
        self.start_time = None
        self._last_gpio_out = 0
        self._uart_bufs = {}

    def start(self):
        """Initialize peripherals, start server, launch QEMU."""
        if self.running:
            return

        log.info("Starting RP2040 emulation...")
        self.dashboard.add_uart_line("Initializing RP2040 peripherals...")

        # 1. Create peripheral set
        self.peripherals = RP2040PeripheralSet(enable_all=True)
        log.info(f"Created {self.peripherals.chip} with "
                 f"{len(self.peripherals.peripherals)} peripherals")

        # 2. Wire callbacks
        self._wire_callbacks()

        # 3. Create and start server
        self.server = PicoServer(self.peripherals, self.port)
        self.running = True
        self.start_time = time.time()
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        self.dashboard.add_uart_line(f"Server listening on port {self.port}")

        # 4. Launch QEMU
        if QEMU_BIN.exists() and self.firmware.exists():
            self._launch_qemu()
        else:
            if not QEMU_BIN.exists():
                self.dashboard.add_uart_line("QEMU not found - server-only mode")
                log.warning(f"QEMU not found at {QEMU_BIN}")
            if not self.firmware.exists():
                self.dashboard.add_uart_line(f"Firmware not found: {self.firmware.name}")
                log.warning(f"Firmware not found: {self.firmware}")

        # 5. Update UI
        self.dashboard.add_uart_line("--- Emulation Started ---")
        self.dashboard.capture.record("Running", 1)

    def stop(self):
        """Stop QEMU and server."""
        if not self.running:
            return

        log.info("Stopping emulation...")
        self.running = False
        if self.server:
            self.server.running = False

        if self.qemu_proc and self.qemu_proc.poll() is None:
            self.qemu_proc.terminate()
            try:
                self.qemu_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.qemu_proc.kill()
            self.qemu_proc = None

        elapsed = time.time() - self.start_time if self.start_time else 0
        mmio = self.server.mmio_count if self.server else 0
        self.dashboard.add_uart_line(
            f"--- Stopped ({mmio} ops, {elapsed:.1f}s) ---")
        self.dashboard.capture.record("Running", 0)

        for led in ["GP25", "GP0", "GP1", "GP2"]:
            self.dashboard.set_led(led, False)

    def get_stats(self) -> tuple:
        """Return (ops_count, elapsed_time, is_running)."""
        elapsed = (time.time() - self.start_time
                   if self.start_time and self.running else 0)
        mmio = self.server.mmio_count if self.server else 0
        return mmio, elapsed, self.running

    def _wire_callbacks(self):
        """Wire GPIO, UART, and PIO callbacks."""
        if not self.peripherals:
            return

        # GPIO change callback (via SIO)
        original_on_gpio = self.peripherals.sio.on_gpio_change

        def on_gpio_change(gpio_out: int, gpio_oe: int):
            if original_on_gpio:
                original_on_gpio(gpio_out, gpio_oe)
            self._on_gpio_change(gpio_out, gpio_oe)

        self.peripherals.sio.on_gpio_change = on_gpio_change

        # LED callback
        self.peripherals.on_led_change = lambda state: \
            self.dashboard.set_led("GP25", state)

        # UART callbacks with line buffering
        if hasattr(self.peripherals, 'uart0') and self.peripherals.uart0:
            self._uart_bufs['uart0'] = UARTLineBuffer(self.dashboard, "uart")
            self.peripherals.uart0.on_tx = self._uart_bufs['uart0'].on_tx
        if hasattr(self.peripherals, 'uart1') and self.peripherals.uart1:
            self._uart_bufs['uart1'] = UARTLineBuffer(self.dashboard, "cdc")
            self.peripherals.uart1.on_tx = self._uart_bufs['uart1'].on_tx

    def _on_gpio_change(self, gpio_out: int, gpio_oe: int):
        """Handle GPIO state change from SIO."""
        changed = gpio_out ^ self._last_gpio_out
        self._last_gpio_out = gpio_out

        for pin in [0, 1, 2, 25]:
            if changed & (1 << pin):
                state = bool(gpio_out & (1 << pin))
                pin_name = f"GP{pin}"
                self.dashboard.set_led(pin_name, state)
                self.dashboard.capture.record(pin_name, 1 if state else 0)

    def _launch_qemu(self):
        """Launch QEMU subprocess for RP2040."""
        machine_opts = (f"slab-cortex-m,"
                        f"cpu-type=cortex-m0,"
                        f"flash-base=0x{FLASH_BASE:08X},"
                        f"sram-base=0x{SRAM_BASE:08X},"
                        f"periph-base=0x14000000,"
                        f"periph-size=0xbc000200,"
                        f"sysclk-hz=125000000,"
                        f"tcp-port={self.port}")
        cmd = [
            str(QEMU_BIN),
            "-M", machine_opts,
            "-kernel", str(self.firmware),
            "-nographic", "-monitor", "none",
        ]

        log.info(f"Launching QEMU: {' '.join(cmd[:4])} ...")
        self.dashboard.add_uart_line(f"Loading: {self.firmware.name}")

        try:
            self.qemu_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            self.dashboard.add_uart_line(f"QEMU started (PID {self.qemu_proc.pid})")
        except Exception as e:
            log.error(f"Failed to start QEMU: {e}")
            self.dashboard.add_uart_line(f"QEMU error: {e}")

    def _run_server(self):
        """Run peripheral TCP server in background thread."""
        asyncio.run(self._async_server())

    async def _async_server(self):
        """Async server using BasePeripheralServer.handle_client protocol."""
        self.server.running = True
        try:
            tcp_server = await asyncio.start_server(
                self.server.handle_client, '127.0.0.1', self.port,
                reuse_address=True
            )
            log.info(f"Server listening on port {self.port}")

            async with tcp_server:
                while self.running:
                    await asyncio.sleep(0.1)

        except Exception as e:
            log.error(f"Server error: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Raspberry Pi Pico Debug Dashboard')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--firmware', '-f', type=Path, default=DEFAULT_FW,
                        help='Firmware binary to load')
    parser.add_argument('--port', '-p', type=int, default=5000,
                        help='TCP port for QEMU connection')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=" * 60)
    log.info("Raspberry Pi Pico Debug Dashboard")
    log.info("=" * 60)

    # 1. Create dashboard (auto-start, no control buttons)
    dashboard = DebugDashboardPro(
        width=1100,
        height=750,
        title="Raspberry Pi Pico Debug Dashboard",
        show_controls=False
    )

    # 2. Add LED indicators matching Pico pinout
    dashboard.add_led("GP25", (0, 255, 0))     # Built-in LED (green)
    dashboard.add_led("GP0", (0, 150, 255))    # GPIO0 (blue)
    dashboard.add_led("GP1", (255, 150, 0))    # GPIO1 (orange)
    dashboard.add_led("GP2", (255, 50, 50))    # GPIO2 (red)

    # 3. Add signal channels for logic analyzer
    dashboard.capture.add_channel("GP25", color=(0, 255, 0))
    dashboard.capture.add_channel("GP0", color=(0, 150, 255))
    dashboard.capture.add_channel("GP1", color=(255, 150, 0))
    dashboard.capture.add_channel("GP2", color=(255, 50, 50))
    dashboard.capture.add_channel("UART_TX", color=(255, 255, 0))
    dashboard.capture.add_channel("Running", color=(100, 100, 100))
    dashboard.capture.start()

    # 4. Create emulation controller
    controller = PicoEmulationController(
        dashboard, args.firmware, port=args.port, verbose=args.verbose)

    # 5. Initialize pygame
    dashboard.init_pygame()

    # 6. Show startup messages
    dashboard.add_uart_line("Raspberry Pi Pico Emulator")
    dashboard.add_uart_line(f"CPU: Cortex-M0+ @ 125 MHz")
    dashboard.add_uart_line(f"Flash: {FLASH_BASE:#010x}  SRAM: {SRAM_BASE:#010x}")
    dashboard.add_cdc_line("USB CDC console")

    # 7. Auto-start emulation
    log.info("Auto-starting emulation...")
    controller.start()

    # 8. Tick callback for stats
    def tick():
        ops, elapsed, running = controller.get_stats()
        dashboard.update_stats(ops, elapsed)

    # 9. Run UI loop
    log.info("Running... close window or press ESC to stop")
    try:
        dashboard.run_loop(tick_callback=tick, fps=30)
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        controller.stop()

    log.info("Dashboard closed")


if __name__ == '__main__':
    main()
