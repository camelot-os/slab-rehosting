#!/usr/bin/env python3
"""
STM32H563 TrustZone Demo with Debug Dashboard

Clean architecture:
1. UI starts and displays "Ready - click START"
2. User clicks START → peripherals initialized, server started, QEMU launched
3. User clicks STOP → QEMU killed, server stopped
4. User clicks RESET → full reset, ready for new run

Usage:
    python run_h563_tz_dashboard.py [--verbose]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
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
from slab_stm32 import STM32H563PeripheralSet
from slab_gui.debug_dashboard import DebugDashboardPro, SignalCapture

# Paths
QEMU_BIN = PROJECT_DIR.parent / "qemu" / "build" / "qemu-system-arm"
SECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "secure_fw.bin"

# Memory map
SECURE_FLASH_BASE = 0x0C000000
SECURE_SRAM_BASE = 0x30000000
SECURE_PERIPH_OFFSET = 0x10000000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)-8s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('H563-TZ')


class EmulationController:
    """Controls the emulation lifecycle."""

    def __init__(self, dashboard: DebugDashboardPro, verbose: bool = False):
        self.dashboard = dashboard
        self.verbose = verbose
        self.port = 5000

        # State
        self.peripherals = None
        self.server_thread = None
        self.qemu_proc = None
        self.running = False
        self.mmio_count = 0
        self.start_time = None

    def start(self):
        """Initialize peripherals, start server, launch QEMU."""
        if self.running:
            return

        log.info("Starting emulation...")
        self.dashboard.add_uart_line("Initializing peripherals...")

        # 1. Create peripheral set
        self.peripherals = STM32H563PeripheralSet()
        log.info(f"Created {self.peripherals.name} with {len(self.peripherals.peripherals)} peripherals")

        # 2. Wire callbacks
        self._wire_callbacks()

        # 3. Start TCP server
        self.running = True
        self.mmio_count = 0
        self.start_time = time.time()
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        self.dashboard.add_uart_line(f"Server listening on port {self.port}")

        # 4. Launch QEMU (if available)
        if QEMU_BIN.exists() and SECURE_FW.exists():
            self._launch_qemu()
        else:
            self.dashboard.add_uart_line("QEMU not found - server-only mode")
            log.warning(f"QEMU not found at {QEMU_BIN}")

        # 5. Update UI
        self.dashboard.add_uart_line("--- Emulation Started ---")
        self.dashboard.capture.record("Secure", 1)

    def stop(self):
        """Stop QEMU and server."""
        if not self.running:
            return

        log.info("Stopping emulation...")
        self.running = False

        # Kill QEMU
        if self.qemu_proc and self.qemu_proc.poll() is None:
            self.qemu_proc.terminate()
            try:
                self.qemu_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.qemu_proc.kill()
            self.qemu_proc = None

        # Server will stop on next iteration (checks self.running)

        # Update UI
        elapsed = time.time() - self.start_time if self.start_time else 0
        self.dashboard.add_uart_line(f"--- Stopped ({self.mmio_count} ops, {elapsed:.1f}s) ---")
        self.dashboard.capture.record("Secure", 0)

        # Turn off LEDs
        for led in ["PA5", "PB0", "PB7", "PC13"]:
            self.dashboard.set_led(led, False)

    def reset(self):
        """Full reset - stop and clear state."""
        self.stop()

        # Clear peripheral state
        self.peripherals = None
        self.mmio_count = 0
        self.start_time = None

        # Clear UI
        self.dashboard.uart_console.lines.clear()
        self.dashboard.cdc_console.lines.clear()
        self.dashboard.add_uart_line("--- Reset ---")
        self.dashboard.add_uart_line("Ready - click START to begin")
        self.dashboard.add_cdc_line("Non-Secure console ready")

    def get_stats(self) -> tuple:
        """Return (ops_count, elapsed_time, is_running)."""
        elapsed = time.time() - self.start_time if self.start_time and self.running else 0
        return self.mmio_count, elapsed, self.running

    def _wire_callbacks(self):
        """Wire GPIO and UART callbacks."""
        if not self.peripherals:
            return

        # GPIO callbacks
        for port_name in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']:
            gpio = self.peripherals.gpio.get(port_name)
            if gpio and hasattr(gpio, 'on_pin_change'):
                gpio.on_pin_change = lambda pin, val, is_out, port=port_name: \
                    self._on_gpio_change(port, pin, val, is_out)

        # UART callbacks
        for uart_name in ['usart1', 'usart2', 'usart3', 'lpuart1']:
            uart = getattr(self.peripherals, uart_name, None)
            if uart and hasattr(uart, 'on_tx'):
                uart.on_tx = lambda data, name=uart_name: self._on_uart_tx(name, data)

    def _on_gpio_change(self, port: str, pin: int, value: int, is_output: bool):
        """Handle GPIO pin change."""
        pin_name = f"P{port}{pin}"

        # Update LED
        if pin_name in ["PA5", "PB0", "PB7", "PC13"]:
            self.dashboard.set_led(pin_name, bool(value))
            self.dashboard.capture.record(pin_name, value)

        if self.verbose:
            log.debug(f"GPIO {pin_name} = {value}")

    def _on_uart_tx(self, uart_name: str, data: bytes):
        """Handle UART transmit."""
        text = data.decode('utf-8', errors='replace')
        if uart_name in ['usart1', 'lpuart1']:
            self.dashboard.add_uart_line(text.rstrip())
        else:
            self.dashboard.add_cdc_line(text.rstrip())

        self.dashboard.capture.record("UART_TX", 1)
        self.dashboard.capture.record("UART_TX", 0)

    def _launch_qemu(self):
        """Launch QEMU subprocess."""
        cmd = [
            str(QEMU_BIN),
            "-M", f"slab-cortex-m,flash-base=0x{SECURE_FLASH_BASE:08X},sram-base=0x{SECURE_SRAM_BASE:08X}",
            "-cpu", "cortex-m33",
            "-nographic",
            "-kernel", str(SECURE_FW),
        ]

        log.info(f"Launching QEMU: {cmd[0]}")
        self.dashboard.add_uart_line("Starting QEMU...")

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
        """Run peripheral TCP server."""
        asyncio.run(self._async_server())

    async def _async_server(self):
        """Async peripheral server."""
        try:
            server = await asyncio.start_server(
                self._handle_client, '127.0.0.1', self.port
            )
            log.info(f"Server listening on port {self.port}")

            async with server:
                while self.running:
                    await asyncio.sleep(0.1)

        except Exception as e:
            log.error(f"Server error: {e}")

    async def _handle_client(self, reader, writer):
        """Handle QEMU MMIO requests."""
        log.info("QEMU connected")
        self.dashboard.add_uart_line("QEMU connected")

        try:
            while self.running:
                header = await asyncio.wait_for(reader.read(9), timeout=0.5)
                if len(header) < 9:
                    break

                cmd = header[0]
                addr = int.from_bytes(header[1:5], 'little')
                size = int.from_bytes(header[5:9], 'little')

                # Translate secure alias
                if (addr & 0xF0000000) == 0x50000000:
                    addr -= SECURE_PERIPH_OFFSET

                if cmd in [ord('R'), ord('S')]:
                    await reader.read(1)
                    value, status = self.peripherals.read(addr, size) if self.peripherals else (0, 0)
                    self.mmio_count += 1
                    writer.write(value.to_bytes(4, 'little') + bytes([status]))

                elif cmd in [ord('W'), ord('T')]:
                    value_sec = await reader.read(5)
                    value = int.from_bytes(value_sec[0:4], 'little')
                    status = self.peripherals.write(addr, size, value) if self.peripherals else 0
                    self.mmio_count += 1
                    writer.write(bytes([status]))

                await writer.drain()

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            if self.running:
                log.error(f"Client error: {e}")
        finally:
            writer.close()
            log.info(f"QEMU disconnected ({self.mmio_count} ops)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='H563 TZ Debug Dashboard')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    log.info("=" * 60)
    log.info("STM32H563 TrustZone Debug Dashboard")
    log.info("=" * 60)

    # 1. Create dashboard UI
    dashboard = DebugDashboardPro(
        width=1000,
        height=750,
        title="STM32H563 TrustZone Debug Dashboard"
    )

    # 2. Add LED indicators
    dashboard.add_led("PA5", (0, 255, 0))    # Green
    dashboard.add_led("PB0", (0, 100, 255))  # Blue
    dashboard.add_led("PB7", (255, 100, 0))  # Orange
    dashboard.add_led("PC13", (255, 0, 0))   # Red

    # 3. Add signal channels
    dashboard.capture.add_channel("PA5", color=(0, 255, 0))
    dashboard.capture.add_channel("PB0", color=(0, 100, 255))
    dashboard.capture.add_channel("UART_TX", color=(255, 255, 0))
    dashboard.capture.add_channel("Secure", color=(255, 100, 100))
    dashboard.capture.start()

    # 4. Create emulation controller
    controller = EmulationController(dashboard, verbose=args.verbose)

    # 5. Wire button callbacks
    dashboard.on_start = controller.start
    dashboard.on_stop = controller.stop
    dashboard.on_reset = controller.reset

    # 6. Initialize pygame
    dashboard.init_pygame()

    # 7. Show initial state
    dashboard.add_uart_line("STM32H563 TrustZone Emulator")
    dashboard.add_uart_line("Ready - click START to begin")
    dashboard.add_cdc_line("Non-Secure console ready")

    log.info("Dashboard ready - waiting for user input")

    # 8. Tick callback to update stats
    def tick():
        ops, elapsed, running = controller.get_stats()
        dashboard.update_stats(ops, elapsed)
        dashboard.control.set_running(running)

    # 9. Run UI loop
    try:
        dashboard.run_loop(tick_callback=tick, fps=30)
    except KeyboardInterrupt:
        log.info("Interrupted")
    finally:
        controller.stop()

    log.info("Dashboard closed")


if __name__ == '__main__':
    main()
