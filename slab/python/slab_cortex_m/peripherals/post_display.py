#!/usr/bin/env python3
"""
POST Code 7-Segment Display Peripheral Emulation

Emulates a dual 7-segment display for POST (Power-On Self-Test) codes,
similar to those found on Xbox 360 development kits and PC debug cards.

Features:
- Dual 7-segment display (2 hex digits)
- POST code history logging
- Timing capture for synchronization
- ASCII art display output
- Trigger callbacks for fault injection

Memory Map:
0x4000E000 - POST_CODE     (W)  Current POST code
0x4000E004 - POST_HISTORY  (R)  16-entry circular buffer
0x4000E044 - POST_INDEX    (R)  Current history index
0x4000E048 - POST_TRIGGER  (R)  Last triggered POST code
0x4000E04C - POST_CYCLE    (R)  Cycle count at last POST

Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Dict, Tuple
from enum import IntEnum


class PostDisplayReg(IntEnum):
    """POST display register offsets."""
    CODE = 0x00      # Current POST code (write triggers display)
    HISTORY = 0x04   # History buffer start (16 x 4 bytes)
    INDEX = 0x44     # Current history index
    TRIGGER = 0x48   # Last POST code that triggered callback
    CYCLE = 0x4C     # Cycle count when last POST was written


# 7-segment encoding for hex digits
# Segments:  _a_
#           |   |
#           f   b
#           |_g_|
#           |   |
#           e   c
#           |_d_|  .dp
#
SEVEN_SEG_FONT = {
    0x0: 0b0111111,  # 0: abcdef
    0x1: 0b0000110,  # 1: bc
    0x2: 0b1011011,  # 2: abdeg
    0x3: 0b1001111,  # 3: abcdg
    0x4: 0b1100110,  # 4: bcfg
    0x5: 0b1101101,  # 5: acdfg
    0x6: 0b1111101,  # 6: acdefg
    0x7: 0b0000111,  # 7: abc
    0x8: 0b1111111,  # 8: all
    0x9: 0b1101111,  # 9: abcdfg
    0xA: 0b1110111,  # A: abcefg
    0xB: 0b1111100,  # b: cdefg
    0xC: 0b0111001,  # C: adef
    0xD: 0b1011110,  # d: bcdeg
    0xE: 0b1111001,  # E: adefg
    0xF: 0b1110001,  # F: aefg
}


def render_7seg_digit(value: int) -> List[str]:
    """
    Render a hex digit as ASCII art 7-segment display.

    Returns 5 lines of 4 characters each.
    """
    segs = SEVEN_SEG_FONT.get(value & 0xF, 0)

    a = '═' if segs & 0b0000001 else ' '
    b = '║' if segs & 0b0000010 else ' '
    c = '║' if segs & 0b0000100 else ' '
    d = '═' if segs & 0b0001000 else ' '
    e = '║' if segs & 0b0010000 else ' '
    f = '║' if segs & 0b0100000 else ' '
    g = '═' if segs & 0b1000000 else ' '

    return [
        f" {a}{a} ",
        f"{f}  {b}",
        f" {g}{g} ",
        f"{e}  {c}",
        f" {d}{d} ",
    ]


def render_post_code(code: int) -> str:
    """
    Render a POST code (2 hex digits) as ASCII art.

    Returns multi-line string.
    """
    high = (code >> 4) & 0xF
    low = code & 0xF

    high_lines = render_7seg_digit(high)
    low_lines = render_7seg_digit(low)

    lines = []
    lines.append("┌────┬────┐")
    for i in range(5):
        lines.append(f"│{high_lines[i]}│{low_lines[i]}│")
    lines.append("└────┴────┘")

    return "\n".join(lines)


@dataclass
class PostEvent:
    """Record of a POST code event."""
    code: int           # POST code value
    cycle: int          # Cycle count when posted
    description: str    # Human-readable description


# Xbox 360-style POST code descriptions
POST_DESCRIPTIONS = {
    # 1BL codes
    0x10: "1BL: Starting",
    0x11: "1BL: Reading CB from NAND",
    0x12: "1BL: Decrypting CB",
    0x13: "1BL: Verifying CB RSA signature",
    0x14: "1BL: Jumping to CB",

    # CB_A codes
    0x30: "CB_A: Starting",
    0x31: "CB_A: Initialize security engine",
    0x32: "CB_A: Reading CB_B from NAND",
    0x33: "CB_A: Decrypting CB_B",
    0x34: "CB_A: Initialize CPU PLL",
    0x35: "CB_A: Initialize RAM controller",
    0x36: "CB_A: Copy CB_B to RAM",
    0x37: "CB_A: Calculate CB_B hash",
    0x38: "CB_A: Load stored hash from fuses",
    0x39: "CB_A: Compare hashes [GLITCH TARGET]",
    0x3A: "CB_A: Hash verification passed",
    0x3B: "CB_A: Jump to CB_B",

    # CB_B codes
    0x40: "CB_B: Starting",
    0x41: "CB_B: Initialize hardware",
    0x42: "CB_B: Read CD (kernel)",
    0x43: "CB_B: Verify CD signature",
    0x44: "CB_B: Decompress kernel",
    0x45: "CB_B: Jump to kernel",

    # Error codes
    0xA1: "ERROR: CB RSA verification failed",
    0xAD: "ERROR: CB_B hash mismatch",
    0xAE: "ERROR: CD signature failed",
    0xFE: "ERROR: Glitch detected",
    0xFF: "ERROR: System panic",

    # Control codes
    0xAA: "CTRL: Arm glitch hardware",
}


class PostDisplay:
    """
    POST Code Display Peripheral.

    Emulates Xbox 360-style POST output with:
    - 7-segment display visualization
    - History logging with timestamps
    - Callback triggers for fault injection
    """

    BASE_ADDR = 0x4000E000

    def __init__(self):
        self.current_code = 0
        self.history: List[int] = []
        self.history_index = 0
        self.max_history = 16

        self.cycle_count = 0
        self.post_cycles: Dict[int, int] = {}

        # Callbacks for POST code triggers
        self.triggers: Dict[int, List[Callable[[int, int], None]]] = {}

        # Event log for analysis
        self.events: List[PostEvent] = []

        # Display options
        self.show_display = True
        self.show_description = True

    def reset(self):
        """Reset peripheral state."""
        self.current_code = 0
        self.history.clear()
        self.history_index = 0
        self.post_cycles.clear()
        self.events.clear()
        self.cycle_count = 0

    def write(self, offset: int, value: int, size: int = 4):
        """Handle register write."""
        if offset == PostDisplayReg.CODE:
            self._post_code(value & 0xFF)

    def read(self, offset: int, size: int = 4) -> int:
        """Handle register read."""
        if offset == PostDisplayReg.CODE:
            return self.current_code

        elif PostDisplayReg.HISTORY <= offset < PostDisplayReg.INDEX:
            idx = (offset - PostDisplayReg.HISTORY) // 4
            if idx < len(self.history):
                return self.history[idx]
            return 0

        elif offset == PostDisplayReg.INDEX:
            return self.history_index

        elif offset == PostDisplayReg.CYCLE:
            return self.post_cycles.get(self.current_code, 0)

        return 0

    def _post_code(self, code: int):
        """Process a POST code output."""
        self.current_code = code

        # Record in history
        if len(self.history) < self.max_history:
            self.history.append(code)
        else:
            self.history[self.history_index % self.max_history] = code
        self.history_index += 1

        # Record timing
        self.post_cycles[code] = self.cycle_count

        # Get description
        desc = POST_DESCRIPTIONS.get(code, f"Unknown POST 0x{code:02X}")

        # Log event
        self.events.append(PostEvent(
            code=code,
            cycle=self.cycle_count,
            description=desc
        ))

        # Display
        if self.show_display:
            self._display_post(code, desc)

        # Trigger callbacks
        if code in self.triggers:
            for callback in self.triggers[code]:
                callback(code, self.cycle_count)

    def _display_post(self, code: int, desc: str):
        """Display POST code on virtual 7-segment display."""
        print(f"\n{'─'*40}")
        print(f"POST Code: 0x{code:02X}")
        if self.show_description:
            print(f"  {desc}")
        print(render_post_code(code))
        print(f"Cycle: {self.cycle_count}")
        print(f"{'─'*40}")

    def advance_cycles(self, cycles: int):
        """Advance the cycle counter."""
        self.cycle_count += cycles

    def register_trigger(self, post_code: int,
                         callback: Callable[[int, int], None]):
        """
        Register a callback for a specific POST code.

        Callback signature: callback(post_code, cycle_count)
        """
        if post_code not in self.triggers:
            self.triggers[post_code] = []
        self.triggers[post_code].append(callback)

    def unregister_trigger(self, post_code: int,
                           callback: Callable[[int, int], None]):
        """Remove a registered callback."""
        if post_code in self.triggers:
            self.triggers[post_code].remove(callback)

    def get_cycles_since(self, post_code: int) -> Optional[int]:
        """Get cycles elapsed since a POST code was output."""
        if post_code in self.post_cycles:
            return self.cycle_count - self.post_cycles[post_code]
        return None

    def get_event_log(self) -> List[PostEvent]:
        """Get the POST event log."""
        return self.events.copy()

    def print_event_log(self):
        """Print the POST event log in a nice format."""
        print("\n" + "="*60)
        print("POST Code Event Log")
        print("="*60)
        print(f"{'Code':<8} {'Cycle':<12} {'Description'}")
        print("-"*60)
        for event in self.events:
            print(f"0x{event.code:02X}     {event.cycle:<12} {event.description}")
        print("="*60)


# =============================================================================
# Integration with Fault Injection
# =============================================================================

def create_post_triggered_fault(post_display: PostDisplay,
                                 fault_engine,
                                 post_code: int,
                                 fault_config,
                                 delay_cycles: int = 0):
    """
    Create a fault that triggers on a specific POST code.

    This enables RGH-style attacks where the glitch is synchronized
    to POST bus activity.
    """
    def on_post(code: int, cycle: int):
        # Arm the fault when POST code is seen
        fault_engine.arm(fault_config.fault_id)
        # Set the arm cycle for delay calculation
        fault = fault_engine.get_fault(fault_config.fault_id)
        if fault:
            fault.arm_cycle = cycle
            fault.trigger_delay = delay_cycles

    post_display.register_trigger(post_code, on_post)


# =============================================================================
# Demo
# =============================================================================

def demo():
    """Demonstrate POST display functionality."""
    print("POST Display Peripheral Demo")
    print("="*40)

    display = PostDisplay()
    display.show_display = True

    # Simulate Xbox 360 boot sequence
    boot_sequence = [
        (0x10, 100),   # 1BL start
        (0x11, 200),   # Read CB
        (0x12, 300),   # Decrypt
        (0x13, 500),   # RSA verify
        (0x14, 100),   # Jump to CB
        (0x30, 100),   # CB_A start
        (0x31, 200),   # Init security
        (0x32, 300),   # Read CB_B
        (0x33, 400),   # Decrypt CB_B
        (0x39, 500),   # Compare hash [TARGET]
        (0x3A, 100),   # Hash OK
        (0x40, 100),   # CB_B start
        (0x45, 200),   # Jump to kernel
    ]

    for code, cycles in boot_sequence:
        display.advance_cycles(cycles)
        display.write(PostDisplayReg.CODE, code)

    display.print_event_log()


if __name__ == "__main__":
    demo()
