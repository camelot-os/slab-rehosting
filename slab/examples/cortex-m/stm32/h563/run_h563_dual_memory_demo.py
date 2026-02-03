#!/usr/bin/env python3
"""
STM32H563 Dual Memory View Demo

Debug dashboard with:
- LED panel + Logic analyzer + Consoles (left)
- NS-SRAM @ 0x20000000 (top right)
- S-SRAM @ 0x30000000 (middle right)
- PC tracker (bottom right)
"""

import sys
import time
import random
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_DIR / "python"))

import pygame
from slab_gui.debug_dashboard import (
    Theme, DebugDashboardPro, MemoryViewWidget, PCTrackerWidget,
    PYGAME_AVAILABLE
)


class DualMemoryDashboard:
    """Debug dashboard with dual memory views (NS-SRAM + S-SRAM)."""

    def __init__(self, width: int = 1600, height: int = 900):
        self.width = width
        self.height = height

        self.screen = None
        self.clock = None
        self.running = False

        # Layout: left 55%, right 45%
        left_w = int(width * 0.55)
        right_x = left_w + 5
        right_w = width - left_w - 10
        panel_h = height // 3 - 5

        # Base dashboard (left)
        self.dashboard = DebugDashboardPro(
            width=left_w,
            height=height,
            title="STM32H563 TrustZone Debug",
            show_controls=False
        )

        # NS-SRAM memory view (top right)
        self.ns_sram = MemoryViewWidget(
            right_x, 5, right_w, panel_h,
            title="NS-SRAM @ 0x20000000",
            base_addr=0x20000000,
            bytes_per_row=8
        )

        # S-SRAM memory view (middle right)
        self.s_sram = MemoryViewWidget(
            right_x, panel_h + 10, right_w, panel_h,
            title="S-SRAM @ 0x30000000",
            base_addr=0x30000000,
            bytes_per_row=8
        )

        # PC tracker (bottom right)
        self.pc_tracker = PCTrackerWidget(
            right_x, 2 * panel_h + 15, right_w, panel_h - 10,
            title="PC Tracker"
        )

        # Add memory regions
        self.pc_tracker.add_region(0x0C000000, 0x0C100000, "S-Flash")
        self.pc_tracker.add_region(0x08000000, 0x08200000, "NS-Flash")
        self.pc_tracker.add_region(0x30000000, 0x30050000, "S-SRAM")
        self.pc_tracker.add_region(0x20000000, 0x20050000, "NS-SRAM")

    def init_pygame(self) -> bool:
        if not PYGAME_AVAILABLE:
            return False

        pygame.init()
        pygame.display.set_caption("STM32H563 Dual Memory Debug")
        self.screen = pygame.display.set_mode((self.width, self.height))
        self.clock = pygame.time.Clock()
        self.running = True

        self.dashboard.screen = self.screen
        self.dashboard.clock = self.clock
        self.dashboard.running = True

        return True

    def handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # Close expanded view first, then exit
                    for widget in [self.ns_sram, self.s_sram, self.pc_tracker]:
                        if hasattr(widget, 'detached') and widget.detached:
                            widget.detached = False
                            continue
                    else:
                        return False

            # Check if any widget is expanded
            detached_widget = None
            for widget in [self.ns_sram, self.s_sram, self.pc_tracker]:
                if hasattr(widget, 'detached') and widget.detached:
                    detached_widget = widget
                    break

            if detached_widget:
                # Handle events for expanded widget with expanded coordinates
                margin = 40
                orig_x, orig_y = detached_widget.x, detached_widget.y
                orig_w, orig_h = detached_widget.width, detached_widget.height

                detached_widget.x = margin
                detached_widget.y = margin
                detached_widget.width = self.width - 2 * margin
                detached_widget.height = self.height - 2 * margin

                handled = detached_widget.handle_event(event)

                # Restore original position
                detached_widget.x, detached_widget.y = orig_x, orig_y
                detached_widget.width, detached_widget.height = orig_w, orig_h

                if handled:
                    continue
            else:
                # Normal mode - route to all widgets
                if self.ns_sram.handle_event(event):
                    continue
                if self.s_sram.handle_event(event):
                    continue
                if self.pc_tracker.handle_event(event):
                    continue
                if self.dashboard.logic_analyzer.handle_event(event):
                    continue
                if self.dashboard.uart_console.handle_event(event):
                    continue
                if self.dashboard.cdc_console.handle_event(event):
                    continue

        return True

    def draw(self):
        if not self.screen:
            return

        self.screen.fill(Theme.BG_PRIMARY)

        # Check if any widget is detached (expanded mode)
        detached_widget = None
        for widget in [self.ns_sram, self.s_sram, self.pc_tracker]:
            if hasattr(widget, 'detached') and widget.detached:
                detached_widget = widget
                break

        if detached_widget:
            # Draw dimmed background
            overlay = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 180))
            self.screen.blit(overlay, (0, 0))

            # Draw expanded widget (centered, larger)
            margin = 40
            orig_x, orig_y = detached_widget.x, detached_widget.y
            orig_w, orig_h = detached_widget.width, detached_widget.height

            detached_widget.x = margin
            detached_widget.y = margin
            detached_widget.width = self.width - 2 * margin
            detached_widget.height = self.height - 2 * margin

            detached_widget.draw(self.screen)

            # Restore original position
            detached_widget.x, detached_widget.y = orig_x, orig_y
            detached_widget.width, detached_widget.height = orig_w, orig_h

            # Help text
            font = pygame.font.Font(None, 24)
            help_text = "Click window icon to close expanded view"
            help_surf = font.render(help_text, True, Theme.TEXT_DIM)
            self.screen.blit(help_surf, (self.width // 2 - help_surf.get_width() // 2, self.height - 30))
        else:
            # Normal view - draw all widgets
            # Left panel
            self.dashboard.led_status.draw(self.screen)
            self.dashboard.logic_analyzer.draw(self.screen)
            self.dashboard.uart_console.draw(self.screen)
            self.dashboard.cdc_console.draw(self.screen)

            # Right panel
            self.ns_sram.draw(self.screen)
            self.s_sram.draw(self.screen)
            self.pc_tracker.draw(self.screen)

        pygame.display.flip()

    def run_loop(self, tick_callback=None, fps: int = 30):
        while self.running:
            if not self.handle_events():
                break
            if tick_callback:
                tick_callback()
            self.draw()
            self.clock.tick(fps)


def main():
    print("Creating dual memory debug dashboard...")

    db = DualMemoryDashboard(width=1600, height=900)

    # LEDs
    db.dashboard.add_led("PA5", (0, 255, 0))    # Secure LED
    db.dashboard.add_led("PB0", (0, 100, 255))  # NS LED
    db.dashboard.add_led("PB7", (255, 100, 0))  # Activity
    db.dashboard.add_led("PC13", (255, 0, 0))   # Error

    # Signal channels
    db.dashboard.capture.add_channel("PA5", color=(0, 255, 0))
    db.dashboard.capture.add_channel("PB0", color=(0, 100, 255))
    db.dashboard.capture.add_channel("PC", color=(255, 200, 100))
    db.dashboard.capture.start()

    print("Initializing pygame...")
    if not db.init_pygame():
        print("ERROR: pygame init failed!")
        return

    # Initialize NS-SRAM with stack frame (256 bytes for scrolling)
    for i in range(256):
        addr = 0x20000000 + i
        db.ns_sram.memory[addr] = random.randint(0, 255)

    # Initialize S-SRAM with secure data (256 bytes for scrolling)
    for i in range(256):
        addr = 0x30000000 + i
        # Secure SRAM has different pattern
        if i < 32:
            db.s_sram.memory[addr] = 0xDE  # Secure marker
        else:
            db.s_sram.memory[addr] = random.randint(0, 255)

    # Boot messages
    secure_msgs = [
        "=== Secure World Boot ===",
        "SAU configured",
        "S-SRAM @ 0x30000000",
        "Jumping to NS...",
    ]
    ns_msgs = [
        "=== Non-Secure World ===",
        "NS-SRAM @ 0x20000000",
        "HAL initialized",
    ]

    for msg in secure_msgs[:2]:
        db.dashboard.add_uart_line(msg)
    for msg in ns_msgs[:1]:
        db.dashboard.add_cdc_line(msg)

    print("Running... ESC to exit")

    counter = 0
    msg_idx_s = 2
    msg_idx_ns = 1
    led_state = False
    pc_base = 0x0C000100

    def tick():
        nonlocal counter, msg_idx_s, msg_idx_ns, led_state, pc_base

        counter += 1

        # Boot messages
        if counter % 30 == 0:
            if msg_idx_s < len(secure_msgs):
                db.dashboard.add_uart_line(secure_msgs[msg_idx_s])
                msg_idx_s += 1
            if msg_idx_ns < len(ns_msgs):
                db.dashboard.add_cdc_line(ns_msgs[msg_idx_ns])
                msg_idx_ns += 1

        # LED heartbeat
        if counter % 30 == 0:
            led_state = not led_state
            db.dashboard.set_led("PA5", led_state)
            db.dashboard.capture.record("PA5", 1 if led_state else 0)

        if counter % 45 == 0:
            cur = db.dashboard.led_status.leds.get("PB0", (None, None, False))[2]
            db.dashboard.set_led("PB0", not cur)

        # PC execution
        if counter % 3 == 0:
            pc = pc_base + (counter * 4) % 0x1000
            is_branch = random.random() < 0.1

            if is_branch:
                # Branch between secure and non-secure
                if random.random() < 0.3:
                    pc = 0x08000100 + random.randint(0, 0x1000)  # NS Flash
                else:
                    pc = 0x0C000100 + random.randint(0, 0x1000)  # S Flash
                pc_base = pc

            db.pc_tracker.record(pc, is_branch)
            db.dashboard.capture.record("PC", 1)
            db.dashboard.capture.record("PC", 0)

        # NS-SRAM access (stack operations across full range)
        if counter % 4 == 0:
            addr = 0x20000000 + random.randint(0, 252)
            if random.random() < 0.5:
                value = random.randint(0, 0xFF)
                db.ns_sram.write(addr, value, 1)
            else:
                db.ns_sram.read_access(addr, 4)

        # S-SRAM access (secure operations across full range)
        if counter % 6 == 0:
            addr = 0x30000000 + random.randint(32, 252)
            if random.random() < 0.5:
                value = random.randint(0, 0xFF)
                db.s_sram.write(addr, value, 1)
            else:
                db.s_sram.read_access(addr, 4)

        # Hotspots
        if counter % 2 == 0:
            # NS tick counter
            addr = 0x20000000
            old = db.ns_sram.memory.get(addr, 0)
            db.ns_sram.write(addr, (old + 1) & 0xFF, 1)

        if counter % 3 == 0:
            # Secure counter
            addr = 0x30000000 + 16
            old = db.s_sram.memory.get(addr, 0)
            db.s_sram.write(addr, (old + 1) & 0xFF, 1)

    try:
        db.run_loop(tick_callback=tick, fps=30)
    except KeyboardInterrupt:
        print("Interrupted")

    print("Done")


if __name__ == '__main__':
    main()
