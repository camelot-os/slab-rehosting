#!/usr/bin/env python3
"""
STM32H563 Simple Demo - UI Test without QEMU

Shows the debug dashboard with simulated boot messages.
"""

import sys
import time
import random
from pathlib import Path

# Add python path
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "python"))

from slab_gui.debug_dashboard import DebugDashboardPro

def main():
    print("Creating dashboard (no controls)...")

    # Create dashboard without control buttons
    dashboard = DebugDashboardPro(
        width=1000,
        height=750,
        title="STM32H563 TrustZone Demo",
        show_controls=False
    )

    # Add LEDs
    dashboard.add_led("PA5", (0, 255, 0))    # Green - Secure heartbeat
    dashboard.add_led("PB0", (0, 100, 255))  # Blue - Non-secure heartbeat
    dashboard.add_led("PB7", (255, 100, 0))  # Orange - Activity
    dashboard.add_led("PC13", (255, 0, 0))   # Red - Error

    # Add signal channels for logic analyzer
    dashboard.capture.add_channel("PA5", color=(0, 255, 0))
    dashboard.capture.add_channel("PB0", color=(0, 100, 255))
    dashboard.capture.add_channel("UART", color=(255, 255, 0))
    dashboard.capture.start()

    # Initialize pygame
    print("Initializing pygame...")
    if not dashboard.init_pygame():
        print("ERROR: pygame init failed!")
        return

    # Simulated boot messages
    secure_boot = [
        "=== STM32H563 TrustZone Secure Boot ===",
        "SAU: Configuring security regions...",
        "SAU: Region 0: 0x0C000000-0x0C03FFFF (Secure)",
        "SAU: Region 1: 0x08000000-0x080FFFFF (Non-Secure)",
        "GTZC: Setting peripheral security...",
        "RCC: Initializing clocks...",
        "RCC: HSE ready, PLL1 locked",
        "RCC: System clock = 250 MHz",
        "UART1: Secure console initialized",
        "GPIO: PA5 configured as output (Secure LED)",
        "TrustZone: Secure world ready",
        "--- Jumping to Non-Secure ---",
    ]

    nonsecure_boot = [
        "=== Non-Secure World Started ===",
        "HAL: Initializing peripherals...",
        "UART2: Non-secure console ready",
        "GPIO: PB0 configured as output (NS LED)",
        "USB: CDC device initializing...",
        "USB: Enumerated as /dev/ttyACM0",
        "App: Non-secure application running",
    ]

    # Add initial messages
    for msg in secure_boot[:3]:
        dashboard.add_uart_line(msg)
    for msg in nonsecure_boot[:2]:
        dashboard.add_cdc_line(msg)

    print("Running UI loop... close window to exit")

    boot_idx_s = 3
    boot_idx_ns = 2
    counter = 0
    led_state = False

    def tick():
        nonlocal boot_idx_s, boot_idx_ns, counter, led_state

        counter += 1

        # Add boot messages progressively
        if counter % 15 == 0:  # Every 0.5s at 30fps
            if boot_idx_s < len(secure_boot):
                dashboard.add_uart_line(secure_boot[boot_idx_s])
                boot_idx_s += 1
            if boot_idx_ns < len(nonsecure_boot):
                dashboard.add_cdc_line(nonsecure_boot[boot_idx_ns])
                boot_idx_ns += 1

        # Toggle LEDs (heartbeat)
        if counter % 30 == 0:  # Every second
            led_state = not led_state
            dashboard.set_led("PA5", led_state)
            dashboard.capture.record("PA5", 1 if led_state else 0)

        if counter % 45 == 0:  # NS heartbeat slightly different rate
            current = dashboard.led_status.leds.get("PB0", (None, None, False))[2]
            dashboard.set_led("PB0", not current)
            dashboard.capture.record("PB0", 0 if current else 1)

        # Activity LED on UART activity
        if boot_idx_s < len(secure_boot) or boot_idx_ns < len(nonsecure_boot):
            if counter % 10 == 0:
                dashboard.set_led("PB7", True)
                dashboard.capture.record("UART", 1)
            elif counter % 10 == 5:
                dashboard.set_led("PB7", False)
                dashboard.capture.record("UART", 0)

    # Run the UI loop
    try:
        dashboard.run_loop(tick_callback=tick, fps=30)
    except KeyboardInterrupt:
        print("Interrupted")

    print("Done")


if __name__ == '__main__':
    main()
