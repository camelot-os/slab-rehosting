#!/usr/bin/env python3
"""
LED Blink Demo - Visual or console display for MCUemu GPIO

Displays a virtual LED that mirrors a GPIO pin driven by firmware
running in QEMU. Uses pygame when available, falls back to console
output with ANSI colors.

Usage:
    # Terminal 1: start server + LED display
    PYTHONPATH=slab/python python3 -m slab_cortex_m.led_demo --port 5555

    # Terminal 2: start QEMU with hello_blink firmware
    ./build/qemu-system-arm -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555 \
        -kernel slab/examples/cortex-m/stm32/f405/demos/hello_blink/build/HelloBlink.bin \
        -nographic

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import argparse
import logging
import sys

from slab_cortex_m.mcuemu_server import MCUemuServer, GPIO, Timer, DEFAULT_CONFIG

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d [%(levelname)5s] %(name)-12s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('LEDDemo')


# =============================================================================
# PYGAME DISPLAY
# =============================================================================

BG_COLOR = (30, 30, 30)
LABEL_COLOR = (180, 180, 180)
LED_RADIUS = 40
WINDOW_W = 200
WINDOW_H = 200


def draw_led_pygame(surface, on: bool, pin_label: str):
    """Draw a single LED with glow effect."""
    surface.fill(BG_COLOR)
    cx, cy = WINDOW_W // 2, WINDOW_H // 2 - 10

    if on:
        # Glow halo
        for r in range(LED_RADIUS + 20, LED_RADIUS, -1):
            alpha = int(80 * (1 - (r - LED_RADIUS) / 20))
            glow = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(glow, (0, 255, 0, alpha), (r, r), r)
            surface.blit(glow, (cx - r, cy - r))
        # Bright core
        pygame.draw.circle(surface, (0, 255, 0), (cx, cy), LED_RADIUS)
        # Highlight
        pygame.draw.circle(surface, (180, 255, 180),
                           (cx - 10, cy - 10), LED_RADIUS // 3)
    else:
        # Dim LED
        pygame.draw.circle(surface, (0, 50, 0), (cx, cy), LED_RADIUS)

    # Border
    pygame.draw.circle(surface, (60, 60, 60), (cx, cy), LED_RADIUS, 2)

    # Label
    font = pygame.font.SysFont("monospace", 16)
    label = font.render(pin_label, True, LABEL_COLOR)
    surface.blit(label, (cx - label.get_width() // 2, cy + LED_RADIUS + 12))

    state_text = "ON" if on else "OFF"
    state_color = (0, 255, 0) if on else (100, 100, 100)
    state = font.render(state_text, True, state_color)
    surface.blit(state, (cx - state.get_width() // 2, cy + LED_RADIUS + 32))


async def pygame_loop(screen, gpio, pin: int, pin_label: str):
    """Async loop that pumps pygame events and redraws the LED."""
    clock = pygame.time.Clock()
    prev_state = None

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return

        odr = gpio.regs.get(GPIO.ODR, 0)
        led_on = bool(odr & (1 << pin))

        if led_on != prev_state:
            draw_led_pygame(screen, led_on, pin_label)
            pygame.display.flip()
            prev_state = led_on

        clock.tick(30)
        await asyncio.sleep(1 / 60)


# =============================================================================
# CONSOLE DISPLAY (fallback)
# =============================================================================

ANSI_GREEN = "\033[92m"
ANSI_DIM = "\033[2m"
ANSI_BOLD = "\033[1m"
ANSI_RESET = "\033[0m"

LED_ON = f"{ANSI_GREEN}{ANSI_BOLD}(*){ANSI_RESET}"
LED_OFF = f"{ANSI_DIM}( ){ANSI_RESET}"


async def console_loop(gpio, pin: int, pin_label: str):
    """Async loop that prints LED state changes to console."""
    prev_state = None
    console_log = logging.getLogger('LED')

    while True:
        odr = gpio.regs.get(GPIO.ODR, 0)
        led_on = bool(odr & (1 << pin))

        if led_on != prev_state:
            indicator = LED_ON if led_on else LED_OFF
            state = "ON" if led_on else "OFF"
            console_log.info(f"{indicator} [{pin_label}] {state}")
            prev_state = led_on

        await asyncio.sleep(1 / 30)


# =============================================================================
# MAIN
# =============================================================================

async def run(port: int, usbip_port: int, gpio_name: str, pin: int,
              use_pygame: bool):
    """Start MCUemu server + LED display."""
    server = MCUemuServer(port, DEFAULT_CONFIG, usbip_port=usbip_port)
    server._create_peripherals()

    # Find target GPIO
    gpio = None
    for p in server.peripherals:
        if isinstance(p, GPIO) and p.name == gpio_name:
            gpio = p
            break

    if gpio is None:
        log.error(f"GPIO '{gpio_name}' not found in peripherals")
        sys.exit(1)

    pin_label = f"{gpio_name[-1]}{pin}"  # e.g. "A13"

    # Start timer peripherals
    for p in server.peripherals:
        if isinstance(p, Timer):
            p.start_counter()

    # Start TCP server
    tcp_server = await asyncio.start_server(
        server._handle_client,
        '127.0.0.1',
        port,
        reuse_address=True
    )
    server.running = True

    log.info(f"Listening on tcp://127.0.0.1:{port}")
    log.info(f"Watching {gpio_name} pin {pin}")

    # Choose display backend
    screen = None
    if use_pygame and HAS_PYGAME:
        pygame.init()
        screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption(f"MCUemu LED - P{pin_label}")
        draw_led_pygame(screen, False, f"P{pin_label}")
        pygame.display.flip()
        display_task = pygame_loop(screen, gpio, pin, f"P{pin_label}")
        log.info("Display: pygame")
    else:
        if use_pygame and not HAS_PYGAME:
            log.warning("pygame not available, using console display")
        display_task = console_loop(gpio, pin, f"P{pin_label}")
        log.info("Display: console")

    tasks = [
        tcp_server.serve_forever(),
        display_task,
    ]

    # Start USBIP if requested
    if usbip_port > 0:
        usb_periph = server._find_usb_peripheral()
        if usb_periph:
            from slab_cortex_m.usbip_server import USBIPServer
            server.usbip_server = USBIPServer(port=usbip_port)
            server.usbip_server.set_usb_peripheral(usb_periph)
            usbip_srv = await asyncio.start_server(
                server.usbip_server.handle_client,
                '0.0.0.0',
                usbip_port,
                reuse_address=True
            )
            tasks.append(usbip_srv.serve_forever())
            log.info(f"USBIP on port {usbip_port}")

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        if screen is not None:
            pygame.quit()


def main():
    parser = argparse.ArgumentParser(description='MCUemu LED Blink Demo')
    parser.add_argument('--port', '-p', type=int, default=5555,
                        help='TCP port for QEMU (default: 5555)')
    parser.add_argument('--usbip-port', type=int, default=0,
                        help='USBIP port (0 = disabled)')
    parser.add_argument('--gpio', type=str, default='GPIOA',
                        help='GPIO port name (default: GPIOA)')
    parser.add_argument('--pin', type=int, default=13,
                        help='GPIO pin number (default: 13)')
    parser.add_argument('--console', action='store_true',
                        help='Force console display (no pygame)')
    args = parser.parse_args()

    try:
        asyncio.run(run(args.port, args.usbip_port, args.gpio, args.pin,
                        use_pygame=not args.console))
    except KeyboardInterrupt:
        print("\n[*] Shutdown")


if __name__ == '__main__':
    main()
