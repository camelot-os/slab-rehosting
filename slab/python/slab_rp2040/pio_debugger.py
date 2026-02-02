#!/usr/bin/env python3
"""
PIO Debugger UI - Visual debugging for RP2040 PIO emulation

Provides real-time visualization of:
- State machine status (PC, X, Y registers, enabled state)
- Instruction memory with PC highlighting
- GPIO pin states (30 pins with direction indicators)
- TX/RX FIFO status and contents
- Clock divider and shift register state
- Step/Run/Stop controls

Usage:
    python3 pio_debugger.py [--chip rp2040|rp2350] [--program blink|ws2812|uart|spi]

Keyboard shortcuts:
    Space   - Toggle run/pause
    S       - Single step
    R       - Reset all state machines
    1-4     - Toggle SM0-SM3 enable
    G       - Toggle GPIO25 (LED)
    Q/Esc   - Quit

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

try:
    import pygame
    from pygame import gfxdraw
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False
    print("pygame not installed. Install with: pip install pygame")
    sys.exit(1)

from rp2040_peripherals import RP2040PeripheralSet, RP2350PeripheralSet
from peripherals import PIOEmulator, PIOInstruction, PIOPrograms, PIOStateMachine

# Setup logging
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger('PIO.Debug')


# =============================================================================
# COLORS
# =============================================================================

class Colors:
    """Color scheme for the debugger."""
    BACKGROUND = (30, 30, 40)
    PANEL_BG = (45, 45, 55)
    PANEL_BORDER = (80, 80, 100)
    TEXT = (220, 220, 230)
    TEXT_DIM = (140, 140, 160)
    TEXT_BRIGHT = (255, 255, 255)
    HIGHLIGHT = (100, 150, 255)
    ACTIVE = (80, 200, 120)
    INACTIVE = (100, 100, 120)
    WARNING = (255, 180, 50)
    ERROR = (255, 80, 80)

    # GPIO colors
    GPIO_HIGH = (80, 255, 80)
    GPIO_LOW = (60, 60, 80)
    GPIO_OUTPUT = (100, 150, 255)
    GPIO_INPUT = (180, 180, 200)

    # LED colors
    LED_ON = (255, 200, 50)
    LED_OFF = (60, 50, 40)

    # FIFO colors
    FIFO_FULL = (255, 100, 100)
    FIFO_EMPTY = (100, 100, 120)
    FIFO_DATA = (100, 200, 255)


# =============================================================================
# PIO DEBUGGER
# =============================================================================

class PIODebugger:
    """Visual PIO debugger using pygame."""

    def __init__(self, chip: str = "rp2040", width: int = 1200, height: int = 800):
        pygame.init()
        pygame.display.set_caption(f"PIO Debugger - {chip.upper()}")

        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        self.clock = pygame.time.Clock()
        self.running = True
        self.paused = True
        self.step_request = False
        self.cycles_per_frame = 1

        # Fonts
        self.font_small = pygame.font.SysFont("monospace", 12)
        self.font_medium = pygame.font.SysFont("monospace", 14)
        self.font_large = pygame.font.SysFont("monospace", 18)
        self.font_title = pygame.font.SysFont("monospace", 20, bold=True)

        # Create peripherals
        if chip.lower() == "rp2350":
            self.peripherals = RP2350PeripheralSet(log=logging.getLogger('RP2350'))
            self.chip = "RP2350"
        else:
            self.peripherals = RP2040PeripheralSet(log=logging.getLogger('RP2040'))
            self.chip = "RP2040"

        self.pio = self.peripherals.pio0.emu
        self.pio_index = 0

        # UI state
        self.selected_sm = 0
        self.show_all_sm = True
        self.total_cycles = 0

        # LED state
        self.led_state = False
        self.peripherals.on_led_change = self._on_led_change

    def _on_led_change(self, state: bool):
        """Callback when LED state changes."""
        self.led_state = state

    def load_program(self, name: str):
        """Load a pre-built PIO program."""
        programs = {
            'blink': (PIOPrograms.blink_led(), {'set_base': 25, 'set_count': 1, 'wrap_top': 1}),
            'ws2812': (PIOPrograms.ws2812_bitbang(), {'out_base': 0, 'side_set_bits': 1, 'wrap_top': 3}),
            'uart': (PIOPrograms.uart_tx(), {'out_base': 0, 'side_set_bits': 1, 'wrap_top': 3}),
            'spi': (PIOPrograms.spi_tx(), {'out_base': 0, 'set_base': 1, 'wrap_top': 4}),
        }

        if name.lower() in programs:
            program, config = programs[name.lower()]
            self.pio.load_program(program)
            self.pio.configure_sm(0, **config, wrap_bottom=0)
            self.pio.enable_sm(0x1)
            log.info(f"Loaded program: {name}")

    def draw_panel(self, x: int, y: int, w: int, h: int, title: str = ""):
        """Draw a panel with optional title."""
        # Background
        pygame.draw.rect(self.screen, Colors.PANEL_BG, (x, y, w, h))
        pygame.draw.rect(self.screen, Colors.PANEL_BORDER, (x, y, w, h), 1)

        # Title
        if title:
            title_surf = self.font_medium.render(title, True, Colors.TEXT_BRIGHT)
            self.screen.blit(title_surf, (x + 8, y + 4))
            pygame.draw.line(self.screen, Colors.PANEL_BORDER,
                           (x, y + 22), (x + w, y + 22))
            return y + 28
        return y + 4

    def draw_state_machine(self, sm: PIOStateMachine, x: int, y: int, w: int, selected: bool):
        """Draw state machine status panel."""
        h = 140

        # Panel
        color = Colors.HIGHLIGHT if selected else Colors.PANEL_BORDER
        pygame.draw.rect(self.screen, Colors.PANEL_BG, (x, y, w, h))
        pygame.draw.rect(self.screen, color, (x, y, w, h), 2 if selected else 1)

        # Title with enable indicator
        status_color = Colors.ACTIVE if sm.enabled else Colors.INACTIVE
        pygame.draw.circle(self.screen, status_color, (x + 15, y + 14), 6)

        title = f"SM{sm.index}"
        title_surf = self.font_medium.render(title, True, Colors.TEXT_BRIGHT)
        self.screen.blit(title_surf, (x + 28, y + 6))

        # State
        state_text = "RUN" if sm.enabled and not sm.stalled else ("STALL" if sm.stalled else "STOP")
        state_color = Colors.ACTIVE if sm.enabled and not sm.stalled else (
            Colors.WARNING if sm.stalled else Colors.INACTIVE)
        state_surf = self.font_small.render(state_text, True, state_color)
        self.screen.blit(state_surf, (x + w - 40, y + 6))

        # Registers
        cy = y + 28
        regs = [
            (f"PC:  {sm.pc:2d}", Colors.HIGHLIGHT),
            (f"X:   0x{sm.x:08X}", Colors.TEXT),
            (f"Y:   0x{sm.y:08X}", Colors.TEXT),
            (f"ISR: 0x{sm.isr:08X}", Colors.TEXT_DIM),
            (f"OSR: 0x{sm.osr:08X}", Colors.TEXT_DIM),
        ]

        for text, color in regs:
            surf = self.font_small.render(text, True, color)
            self.screen.blit(surf, (x + 8, cy))
            cy += 16

        # FIFO status
        cy = y + 28
        tx_fill = len(sm.tx_fifo)
        rx_fill = len(sm.rx_fifo)

        tx_text = f"TX: {'█' * tx_fill}{'░' * (4-tx_fill)}"
        rx_text = f"RX: {'█' * rx_fill}{'░' * (4-rx_fill)}"

        tx_surf = self.font_small.render(tx_text, True,
            Colors.FIFO_FULL if tx_fill == 4 else (Colors.FIFO_DATA if tx_fill > 0 else Colors.FIFO_EMPTY))
        rx_surf = self.font_small.render(rx_text, True,
            Colors.FIFO_FULL if rx_fill == 4 else (Colors.FIFO_DATA if rx_fill > 0 else Colors.FIFO_EMPTY))

        self.screen.blit(tx_surf, (x + w - 90, cy))
        self.screen.blit(rx_surf, (x + w - 90, cy + 16))

        return h

    def draw_instruction_memory(self, x: int, y: int, w: int, h: int):
        """Draw instruction memory with current PC highlighted."""
        cy = self.draw_panel(x, y, w, h, "Instruction Memory")

        # Get current PCs
        pcs = [sm.pc for sm in self.pio.sm if sm.enabled]

        # Show 20 instructions
        for addr in range(min(20, 32)):
            instr_raw = self.pio.instructions[addr]
            instr = PIOInstruction.decode(instr_raw)

            # Highlight if any SM is at this address
            is_current = addr in pcs
            bg_color = Colors.HIGHLIGHT if is_current else None
            if bg_color:
                pygame.draw.rect(self.screen, bg_color, (x + 2, cy, w - 4, 16))

            # Address
            addr_text = f"{addr:2d}:"
            addr_color = Colors.TEXT_BRIGHT if is_current else Colors.TEXT_DIM
            addr_surf = self.font_small.render(addr_text, True, addr_color)
            self.screen.blit(addr_surf, (x + 8, cy))

            # Hex
            hex_text = f"0x{instr_raw:04X}"
            hex_surf = self.font_small.render(hex_text, True, Colors.TEXT_DIM)
            self.screen.blit(hex_surf, (x + 40, cy))

            # Disassembly
            asm_text = str(instr)[:20]
            asm_color = Colors.TEXT_BRIGHT if is_current else Colors.TEXT
            asm_surf = self.font_small.render(asm_text, True, asm_color)
            self.screen.blit(asm_surf, (x + 100, cy))

            cy += 16

    def draw_gpio(self, x: int, y: int, w: int, h: int):
        """Draw GPIO state visualization."""
        cy = self.draw_panel(x, y, w, h, "GPIO (30 pins)")

        gpio_state = self.pio.gpio_state
        gpio_dir = self.pio.gpio_dir

        # Draw pins in 3 rows of 10
        pin_size = 24
        pin_margin = 4

        for row in range(3):
            cx = x + 10
            for col in range(10):
                pin = row * 10 + col
                if pin >= 30:
                    break

                is_high = bool(gpio_state & (1 << pin))
                is_output = bool(gpio_dir & (1 << pin))

                # Pin background (output = blue border, input = gray)
                border_color = Colors.GPIO_OUTPUT if is_output else Colors.GPIO_INPUT
                fill_color = Colors.GPIO_HIGH if is_high else Colors.GPIO_LOW

                pygame.draw.rect(self.screen, fill_color,
                               (cx, cy, pin_size, pin_size))
                pygame.draw.rect(self.screen, border_color,
                               (cx, cy, pin_size, pin_size), 2)

                # Pin number
                pin_text = f"{pin}"
                pin_surf = self.font_small.render(pin_text, True,
                    Colors.TEXT_BRIGHT if is_high else Colors.TEXT_DIM)
                text_x = cx + (pin_size - pin_surf.get_width()) // 2
                text_y = cy + (pin_size - pin_surf.get_height()) // 2
                self.screen.blit(pin_surf, (text_x, text_y))

                cx += pin_size + pin_margin

            cy += pin_size + pin_margin

        # Legend
        cy += 8
        legend = [("█ High", Colors.GPIO_HIGH), ("█ Low", Colors.GPIO_LOW),
                  ("□ Output", Colors.GPIO_OUTPUT), ("□ Input", Colors.GPIO_INPUT)]
        cx = x + 10
        for text, color in legend:
            surf = self.font_small.render(text, True, color)
            self.screen.blit(surf, (cx, cy))
            cx += 80

    def draw_led(self, x: int, y: int):
        """Draw LED indicator."""
        radius = 30
        color = Colors.LED_ON if self.led_state else Colors.LED_OFF

        # Glow effect
        if self.led_state:
            for i in range(5, 0, -1):
                glow_color = (color[0] // (i + 1), color[1] // (i + 1), color[2] // (i + 1))
                pygame.draw.circle(self.screen, glow_color, (x, y), radius + i * 3)

        pygame.draw.circle(self.screen, color, (x, y), radius)
        pygame.draw.circle(self.screen, Colors.PANEL_BORDER, (x, y), radius, 2)

        # Label
        label = self.font_small.render("LED (GPIO25)", True, Colors.TEXT)
        self.screen.blit(label, (x - label.get_width() // 2, y + radius + 8))

    def draw_controls(self, x: int, y: int, w: int, h: int):
        """Draw control panel."""
        cy = self.draw_panel(x, y, w, h, "Controls")

        # Status
        status = "PAUSED" if self.paused else "RUNNING"
        status_color = Colors.WARNING if self.paused else Colors.ACTIVE
        status_surf = self.font_large.render(status, True, status_color)
        self.screen.blit(status_surf, (x + 8, cy))
        cy += 28

        # Cycle counter
        cycle_text = f"Cycles: {self.total_cycles:,}"
        cycle_surf = self.font_medium.render(cycle_text, True, Colors.TEXT)
        self.screen.blit(cycle_surf, (x + 8, cy))
        cy += 24

        # Keyboard shortcuts
        shortcuts = [
            "Space - Run/Pause",
            "S     - Step",
            "R     - Reset",
            "1-4   - Toggle SM",
            "G     - Toggle GPIO25",
            "Q/Esc - Quit",
        ]

        cy += 8
        for shortcut in shortcuts:
            surf = self.font_small.render(shortcut, True, Colors.TEXT_DIM)
            self.screen.blit(surf, (x + 8, cy))
            cy += 16

    def draw_info(self, x: int, y: int, w: int, h: int):
        """Draw chip info panel."""
        cy = self.draw_panel(x, y, w, h, f"{self.chip} Info")

        info = [
            f"PIO{self.pio_index}",
            f"Clock: 125 MHz",
            f"Instr Mem: 32 words",
            f"State Machines: 4",
            f"FIFO Depth: 4 words",
            "",
            f"GPIO State: 0x{self.pio.gpio_state:08X}",
            f"GPIO Dir:   0x{self.pio.gpio_dir:08X}",
            f"IRQ Flags:  0x{self.pio.irq_flags:02X}",
        ]

        for line in info:
            surf = self.font_small.render(line, True, Colors.TEXT)
            self.screen.blit(surf, (x + 8, cy))
            cy += 16

    def handle_events(self):
        """Handle pygame events."""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False

            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    self.running = False

                elif event.key == pygame.K_SPACE:
                    self.paused = not self.paused

                elif event.key == pygame.K_s:
                    self.step_request = True

                elif event.key == pygame.K_r:
                    for sm in self.pio.sm:
                        sm.reset()
                    self.total_cycles = 0

                elif event.key == pygame.K_g:
                    # Toggle GPIO25
                    self.pio.gpio_state ^= (1 << 25)

                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                    sm_idx = event.key - pygame.K_1
                    self.pio.sm[sm_idx].enabled = not self.pio.sm[sm_idx].enabled

    def update(self):
        """Update PIO state."""
        if not self.paused or self.step_request:
            for _ in range(self.cycles_per_frame):
                self.peripherals.step_pio()
                self.total_cycles += 1
            self.step_request = False

    def draw(self):
        """Draw the entire UI."""
        self.screen.fill(Colors.BACKGROUND)

        # Title
        title = f"PIO Debugger - {self.chip}"
        title_surf = self.font_title.render(title, True, Colors.TEXT_BRIGHT)
        self.screen.blit(title_surf, (10, 10))

        # State machines (top left)
        sm_width = 180
        for i, sm in enumerate(self.pio.sm):
            x = 10 + i * (sm_width + 10)
            self.draw_state_machine(sm, x, 50, sm_width, i == self.selected_sm)

        # Instruction memory (left)
        self.draw_instruction_memory(10, 200, 280, 360)

        # GPIO (center)
        self.draw_gpio(300, 200, 320, 180)

        # LED (center right)
        self.draw_led(500, 460)

        # Controls (right)
        self.draw_controls(640, 200, 180, 200)

        # Info (right)
        self.draw_info(640, 410, 180, 180)

        pygame.display.flip()

    def run(self):
        """Main loop."""
        while self.running:
            self.handle_events()
            self.update()
            self.draw()
            self.clock.tick(60)

        pygame.quit()


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="PIO Debugger")
    parser.add_argument("--chip", choices=["rp2040", "rp2350"], default="rp2040",
                       help="Target chip")
    parser.add_argument("--program", choices=["blink", "ws2812", "uart", "spi"],
                       default="blink", help="Program to load")
    parser.add_argument("--width", type=int, default=840, help="Window width")
    parser.add_argument("--height", type=int, default=600, help="Window height")
    args = parser.parse_args()

    debugger = PIODebugger(chip=args.chip, width=args.width, height=args.height)
    debugger.load_program(args.program)
    debugger.run()


if __name__ == "__main__":
    main()
