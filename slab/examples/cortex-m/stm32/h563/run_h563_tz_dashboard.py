#!/usr/bin/env python3
"""
STM32H563 TrustZone Demo with Debug Dashboard

Runs the H563 TrustZone firmware with professional debug UI including:
- Start/Stop/Reset control panel
- LED status display
- Real-time logic analyzer with GPIO/UART signals
- Dual console (Secure UART + Non-Secure UART)

Usage:
    python run_h563_tz_dashboard.py [--verbose]

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import os
import sys
import time
import asyncio
import logging
import threading
from pathlib import Path

# Add python path
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "python"))

import pygame
from slab_stm32 import STM32H563PeripheralSet
from slab_gui.debug_dashboard import (
    DebugDashboardPro, SignalCapture, SignalType, Theme
)

# Paths
SECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "secure_fw.bin"
NONSECURE_FW = SCRIPT_DIR / "stm32h563_tz_cdc" / "build" / "nonsecure_fw.bin"

# Memory map
SECURE_FLASH_BASE = 0x0C000000
SECURE_SRAM_BASE = 0x30000000
SECURE_PERIPH_OFFSET = 0x10000000

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(name)-8s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('H563-TZ')


class H563DashboardDemo:
    """STM32H563 TrustZone demo with debug dashboard."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.running = False
        self.emulating = False
        self.port = 5000
        self.mmio_count = 0
        self.start_time = None

        # Create peripheral set
        self.peripherals = STM32H563PeripheralSet()
        log.info(f"Created {self.peripherals.name} with {len(self.peripherals.peripherals)} peripherals")

        # Signal capture for logic analyzer
        self.capture = SignalCapture()

        # Create dashboard
        self.dashboard = DebugDashboardPro(
            width=1000,
            height=750,
            title="STM32H563 TrustZone Debug Dashboard"
        )

        # Use our capture instead of dashboard's default
        self.dashboard.capture = self.capture
        self.dashboard.logic_analyzer.capture = self.capture

        # Wire up callbacks
        self.dashboard.on_start = self._on_start
        self.dashboard.on_stop = self._on_stop
        self.dashboard.on_reset = self._on_reset
        self.dashboard.uart_console.on_input = self._on_secure_input
        self.dashboard.cdc_console.on_input = self._on_nonsecure_input

        # Configure dashboard console titles
        self.dashboard.uart_console.title = "Secure UART"
        self.dashboard.cdc_console.title = "Non-Secure UART"

        # Add LEDs for GPIO pins
        self._setup_leds()

        # Add signal channels
        self._setup_signals()

        # Wire GPIO callbacks
        self._setup_gpio_callbacks()

        # Server state
        self.server = None
        self.server_task = None
        self.qemu_proc = None

    def _setup_leds(self):
        """Configure LED indicators."""
        self.dashboard.add_led("PA5", (0, 255, 0))    # Green LED
        self.dashboard.add_led("PB0", (0, 100, 255))  # Blue LED
        self.dashboard.add_led("PB7", (255, 100, 0))  # Orange LED
        self.dashboard.add_led("PC13", (255, 0, 0))   # Red LED (user button LED)

    def _setup_signals(self):
        """Configure logic analyzer signals."""
        self.capture.add_channel("PA5", color=(0, 255, 0))
        self.capture.add_channel("PB0", color=(0, 100, 255))
        self.capture.add_channel("UART_TX", color=(255, 255, 0))
        self.capture.add_channel("UART_RX", color=(0, 255, 255))
        self.capture.add_channel("Secure", color=(255, 100, 100))
        self.capture.start()

    def _setup_gpio_callbacks(self):
        """Wire GPIO pin change callbacks."""
        # Get GPIO ports from peripheral set (stored as dict in ps.gpio)
        for port_name in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I']:
            gpio = self.peripherals.gpio.get(port_name)
            if gpio and hasattr(gpio, 'on_pin_change'):
                gpio.on_pin_change = lambda pin, val, is_out, port=port_name: \
                    self._on_gpio_change(port, pin, val, is_out)

        # Wire UART callbacks
        for uart_name in ['usart1', 'usart2', 'usart3', 'lpuart1']:
            uart = getattr(self.peripherals, uart_name, None)
            if uart and hasattr(uart, 'on_tx'):
                uart.on_tx = lambda data, name=uart_name: self._on_uart_tx(name, data)

    def _on_gpio_change(self, port: str, pin: int, value: int, is_output: bool):
        """Handle GPIO pin change."""
        pin_name = f"P{port}{pin}"

        # Update LED if it's one of our monitored pins
        if pin_name in ["PA5", "PB0", "PB7", "PC13"]:
            self.dashboard.set_led(pin_name, bool(value))

        # Record to logic analyzer
        if pin_name in ["PA5", "PB0"]:
            self.capture.record(pin_name, value)

        if self.verbose:
            direction = "OUT" if is_output else "IN"
            log.debug(f"GPIO {pin_name} = {value} ({direction})")

    def _on_uart_tx(self, uart_name: str, data: bytes):
        """Handle UART transmit."""
        text = data.decode('utf-8', errors='replace')

        # Route to appropriate console
        if uart_name in ['usart1', 'lpuart1']:
            self.dashboard.add_uart_line(text.rstrip())
        else:
            self.dashboard.add_cdc_line(text.rstrip())

        # Record UART activity
        self.capture.record("UART_TX", 1)
        self.capture.record("UART_TX", 0)

        if self.verbose:
            log.debug(f"{uart_name} TX: {repr(text)}")

    def _on_secure_input(self, text: str):
        """Handle secure console input."""
        log.info(f"Secure input: {text}")
        # TODO: Inject into secure UART RX

    def _on_nonsecure_input(self, text: str):
        """Handle non-secure console input."""
        log.info(f"Non-Secure input: {text}")
        # TODO: Inject into non-secure UART RX

    def _on_start(self):
        """Start emulation."""
        if self.emulating:
            return

        log.info("Starting emulation...")
        self.emulating = True
        self.start_time = time.time()
        self.mmio_count = 0

        # Start peripheral server in background thread
        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        # Record secure world start
        self.capture.record("Secure", 1)

        self.dashboard.add_uart_line("--- Emulation Started ---")
        self.dashboard.add_cdc_line("--- Emulation Started ---")

    def _on_stop(self):
        """Stop emulation."""
        if not self.emulating:
            return

        log.info("Stopping emulation...")
        self.emulating = False

        # Stop QEMU if running
        if self.qemu_proc and self.qemu_proc.poll() is None:
            self.qemu_proc.terminate()
            self.qemu_proc = None

        self.capture.record("Secure", 0)

        elapsed = time.time() - self.start_time if self.start_time else 0
        self.dashboard.add_uart_line(f"--- Stopped ({self.mmio_count} ops, {elapsed:.1f}s) ---")

    def _on_reset(self):
        """Reset emulation."""
        log.info("Resetting...")
        self._on_stop()

        # Clear state
        self.mmio_count = 0
        self.peripherals = STM32H563PeripheralSet()
        self._setup_gpio_callbacks()

        # Clear consoles
        self.dashboard.uart_console.lines.clear()
        self.dashboard.cdc_console.lines.clear()
        self.dashboard.add_uart_line("--- Reset ---")
        self.dashboard.add_cdc_line("--- Reset ---")

        # Clear LEDs
        for led_name in ["PA5", "PB0", "PB7", "PC13"]:
            self.dashboard.set_led(led_name, False)

    def _translate_addr(self, addr: int) -> int:
        """Translate secure alias to non-secure."""
        if (addr & 0xF0000000) == 0x50000000:
            return addr - SECURE_PERIPH_OFFSET
        return addr

    def _handle_read(self, addr: int, size: int) -> tuple:
        """Handle peripheral read."""
        ns_addr = self._translate_addr(addr)
        value, status = self.peripherals.read(ns_addr, size)
        self.mmio_count += 1
        return value, status

    def _handle_write(self, addr: int, size: int, value: int) -> int:
        """Handle peripheral write."""
        ns_addr = self._translate_addr(addr)
        status = self.peripherals.write(ns_addr, size, value)
        self.mmio_count += 1
        return status

    def _run_server(self):
        """Run peripheral server (in background thread)."""
        asyncio.run(self._async_server())

    async def _async_server(self):
        """Async peripheral server."""
        server = await asyncio.start_server(
            self._handle_client, '127.0.0.1', self.port
        )
        log.info(f"Peripheral server on port {self.port}")

        async with server:
            while self.emulating:
                await asyncio.sleep(0.1)

    async def _handle_client(self, reader, writer):
        """Handle QEMU client."""
        log.info("QEMU connected")

        try:
            while self.emulating:
                header = await asyncio.wait_for(reader.read(9), timeout=0.5)
                if len(header) < 9:
                    break

                cmd = header[0]
                addr = int.from_bytes(header[1:5], 'little')
                size = int.from_bytes(header[5:9], 'little')

                if cmd in [ord('R'), ord('S')]:
                    await reader.read(1)  # security byte
                    value, status = self._handle_read(addr, size)
                    writer.write(value.to_bytes(4, 'little') + bytes([status]))

                elif cmd in [ord('W'), ord('T')]:
                    value_sec = await reader.read(5)
                    value = int.from_bytes(value_sec[0:4], 'little')
                    status = self._handle_write(addr, size, value)
                    writer.write(bytes([status]))

                await writer.drain()

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            log.error(f"Client error: {e}")
        finally:
            writer.close()
            log.info(f"QEMU disconnected ({self.mmio_count} ops)")

    def _tick(self):
        """Tick callback for dashboard loop."""
        # Update dashboard stats
        elapsed = time.time() - self.start_time if self.start_time and self.emulating else 0
        self.dashboard.update_stats(self.mmio_count, elapsed)
        self.dashboard.control.set_running(self.emulating)

    def run(self):
        """Run the dashboard."""
        log.info("=" * 60)
        log.info("STM32H563 TrustZone Debug Dashboard")
        log.info("=" * 60)
        log.info(f"Secure FW: {SECURE_FW}")
        log.info(f"Non-Secure FW: {NONSECURE_FW}")
        log.info("=" * 60)

        # Initialize pygame
        self.dashboard.init_pygame()

        # Add initial console messages
        self.dashboard.add_uart_line("STM32H563 Secure World Console")
        self.dashboard.add_uart_line("Press START to begin emulation")
        self.dashboard.add_cdc_line("STM32H563 Non-Secure World Console")
        self.dashboard.add_cdc_line("Waiting for secure boot...")

        # Simulate some initial GPIO activity for demo
        self._simulate_boot_sequence()

        # Run main loop with tick callback
        self.running = True
        try:
            self.dashboard.run_loop(tick_callback=self._tick, fps=30)
        except KeyboardInterrupt:
            log.info("Interrupted")
        finally:
            self._on_stop()

        log.info("Dashboard closed")

    def _simulate_boot_sequence(self):
        """Simulate boot sequence for demo."""
        # Record some initial signals
        self.capture.record("Secure", 0)
        self.capture.record("PA5", 0)
        self.capture.record("PB0", 0)
        self.capture.record("UART_TX", 0)
        self.capture.record("UART_RX", 0)


def main():
    import argparse
    parser = argparse.ArgumentParser(description='H563 TZ Debug Dashboard')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    demo = H563DashboardDemo(verbose=args.verbose)
    demo.run()


if __name__ == '__main__':
    main()
