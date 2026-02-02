"""
RP2040 Peripheral Emulation

Emulates key RP2040 peripherals, with focus on PIO (Programmable I/O)
which is unique to the RP2040 and critical for timing analysis.

References:
- RP2040 Datasheet, Chapter 3 (PIO)
- Pico SDK PIO documentation

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Tuple
from enum import Enum, IntEnum


class PIOOpcode(IntEnum):
    """PIO instruction opcodes (3-bit field in bits 15:13)."""
    JMP = 0b000
    WAIT = 0b001
    IN = 0b010
    OUT = 0b011
    PUSH = 0b100  # PUSH/PULL share opcode, distinguished by bit 7
    PULL = 0b100
    MOV = 0b101
    IRQ = 0b110
    SET = 0b111


class PIOCondition(IntEnum):
    """JMP conditions (3-bit field)."""
    ALWAYS = 0b000      # Always jump
    NOT_X = 0b001       # !X (X is zero)
    X_DEC = 0b010       # X-- (post-decrement, jump if non-zero before)
    NOT_Y = 0b011       # !Y (Y is zero)
    Y_DEC = 0b100       # Y-- (post-decrement, jump if non-zero before)
    X_NE_Y = 0b101      # X != Y
    PIN = 0b110         # Jump on input pin
    NOT_OSRE = 0b111    # !OSRE (output shift register not empty)


class PIOWaitSource(IntEnum):
    """WAIT instruction sources."""
    GPIO = 0b00
    PIN = 0b01
    IRQ = 0b10


class PIOMovDest(IntEnum):
    """MOV instruction destinations."""
    PINS = 0b000
    X = 0b001
    Y = 0b010
    EXEC = 0b100
    PC = 0b101
    ISR = 0b110
    OSR = 0b111


class PIOMovSrc(IntEnum):
    """MOV instruction sources."""
    PINS = 0b000
    X = 0b001
    Y = 0b010
    NULL = 0b011
    STATUS = 0b101
    ISR = 0b110
    OSR = 0b111


class PIOMovOp(IntEnum):
    """MOV instruction operations."""
    NONE = 0b00
    INVERT = 0b01
    BIT_REVERSE = 0b10


@dataclass
class PIOInstruction:
    """
    Decoded PIO instruction.

    PIO instructions are 16 bits with the following format:
    - Bits 15:13 - Opcode (3 bits)
    - Bits 12:8  - Delay/side-set (5 bits, configurable split)
    - Bits 7:0   - Instruction-specific data
    """

    raw: int
    opcode: PIOOpcode
    delay: int
    side_set: int
    data: int

    # Decoded fields (instruction-specific)
    condition: Optional[PIOCondition] = None
    address: Optional[int] = None
    wait_polarity: Optional[int] = None
    wait_source: Optional[PIOWaitSource] = None
    wait_index: Optional[int] = None
    bit_count: Optional[int] = None
    source: Optional[int] = None
    destination: Optional[int] = None
    operation: Optional[PIOMovOp] = None
    if_full: Optional[bool] = None
    if_empty: Optional[bool] = None
    block: Optional[bool] = None
    irq_index: Optional[int] = None
    irq_wait: Optional[bool] = None
    irq_clear: Optional[bool] = None

    @classmethod
    def decode(cls, raw: int, side_set_bits: int = 0, side_set_opt: bool = False) -> 'PIOInstruction':
        """
        Decode a 16-bit PIO instruction.

        Args:
            raw: 16-bit instruction word
            side_set_bits: Number of bits used for side-set (0-5)
            side_set_opt: If True, MSB of delay/side-set indicates side-set enable

        Returns:
            Decoded PIOInstruction
        """
        opcode = PIOOpcode((raw >> 13) & 0x7)
        delay_side = (raw >> 8) & 0x1F

        # Split delay/side-set field
        if side_set_opt:
            side_set_enable = (delay_side >> 4) & 1
            if side_set_enable and side_set_bits > 0:
                side_set = (delay_side >> (5 - side_set_bits)) & ((1 << (side_set_bits - 1)) - 1)
                delay = delay_side & ((1 << (4 - side_set_bits)) - 1)
            else:
                side_set = 0
                delay = delay_side & 0xF
        else:
            if side_set_bits > 0:
                side_set = (delay_side >> (5 - side_set_bits)) & ((1 << side_set_bits) - 1)
                delay = delay_side & ((1 << (5 - side_set_bits)) - 1)
            else:
                side_set = 0
                delay = delay_side

        data = raw & 0xFF

        instr = cls(
            raw=raw,
            opcode=opcode,
            delay=delay,
            side_set=side_set,
            data=data,
        )

        # Decode instruction-specific fields
        if opcode == PIOOpcode.JMP:
            instr.condition = PIOCondition((data >> 5) & 0x7)
            instr.address = data & 0x1F

        elif opcode == PIOOpcode.WAIT:
            instr.wait_polarity = (data >> 7) & 1
            instr.wait_source = PIOWaitSource((data >> 5) & 0x3)
            instr.wait_index = data & 0x1F

        elif opcode == PIOOpcode.IN:
            instr.source = (data >> 5) & 0x7
            instr.bit_count = data & 0x1F
            if instr.bit_count == 0:
                instr.bit_count = 32

        elif opcode == PIOOpcode.OUT:
            instr.destination = (data >> 5) & 0x7
            instr.bit_count = data & 0x1F
            if instr.bit_count == 0:
                instr.bit_count = 32

        elif opcode == PIOOpcode.PUSH:  # PUSH or PULL
            is_pull = (data >> 7) & 1
            if is_pull:
                instr.if_empty = bool((data >> 6) & 1)
            else:
                instr.if_full = bool((data >> 6) & 1)
            instr.block = bool((data >> 5) & 1)

        elif opcode == PIOOpcode.MOV:
            instr.destination = (data >> 5) & 0x7
            instr.operation = PIOMovOp((data >> 3) & 0x3)
            instr.source = data & 0x7

        elif opcode == PIOOpcode.IRQ:
            instr.irq_clear = bool((data >> 6) & 1)
            instr.irq_wait = bool((data >> 5) & 1)
            instr.irq_index = data & 0x1F

        elif opcode == PIOOpcode.SET:
            instr.destination = (data >> 5) & 0x7
            instr.data = data & 0x1F

        return instr

    def __str__(self) -> str:
        """Generate assembly-like representation."""
        if self.opcode == PIOOpcode.JMP:
            cond_str = ["", "!x, ", "x--, ", "!y, ", "y--, ", "x!=y, ", "pin, ", "!osre, "]
            return f"jmp {cond_str[self.condition]}{self.address}"
        elif self.opcode == PIOOpcode.WAIT:
            pol = "" if self.wait_polarity else "0 "
            src = ["gpio", "pin", "irq"][self.wait_source]
            return f"wait {pol}{src} {self.wait_index}"
        elif self.opcode == PIOOpcode.IN:
            src = ["pins", "x", "y", "null", "???", "status", "isr", "osr"][self.source]
            return f"in {src}, {self.bit_count}"
        elif self.opcode == PIOOpcode.OUT:
            dst = ["pins", "x", "y", "null", "pindirs", "pc", "isr", "exec"][self.destination]
            return f"out {dst}, {self.bit_count}"
        elif self.opcode == PIOOpcode.PUSH:
            if (self.raw >> 7) & 1:  # PULL
                ife = "ife" if self.if_empty else ""
                blk = "block" if self.block else "noblock"
                return f"pull {ife} {blk}".strip()
            else:  # PUSH
                iff = "iff" if self.if_full else ""
                blk = "block" if self.block else "noblock"
                return f"push {iff} {blk}".strip()
        elif self.opcode == PIOOpcode.MOV:
            dst = ["pins", "x", "y", "???", "exec", "pc", "isr", "osr"][self.destination]
            src = ["pins", "x", "y", "null", "???", "status", "isr", "osr"][self.source]
            op = ["", "!", "::"][self.operation]
            return f"mov {dst}, {op}{src}"
        elif self.opcode == PIOOpcode.IRQ:
            wait = "wait" if self.irq_wait else ""
            clear = "clear" if self.irq_clear else ""
            return f"irq {wait} {clear} {self.irq_index}".strip()
        elif self.opcode == PIOOpcode.SET:
            dst = ["pins", "x", "y", "???", "pindirs"][self.destination]
            return f"set {dst}, {self.data}"
        return f"??? 0x{self.raw:04x}"


@dataclass
class PIOStateMachine:
    """
    Single PIO state machine emulator.

    Each PIO block has 4 state machines that share:
    - 32-word instruction memory
    - IRQ flags

    But have independent:
    - PC (program counter)
    - X, Y scratch registers
    - ISR, OSR shift registers
    - FIFO queues (4 words each, can be combined)
    - Pin mappings
    """

    # State machine index (0-3)
    index: int

    # Program counter
    pc: int = 0

    # Scratch registers (32-bit)
    x: int = 0
    y: int = 0

    # Shift registers
    isr: int = 0
    osr: int = 0
    isr_shift_count: int = 0
    osr_shift_count: int = 0

    # FIFOs
    tx_fifo: List[int] = field(default_factory=list)
    rx_fifo: List[int] = field(default_factory=list)
    fifo_depth: int = 4

    # Configuration
    wrap_bottom: int = 0
    wrap_top: int = 31
    side_set_bits: int = 0
    side_set_opt: bool = False
    side_set_pindirs: bool = False

    # Pin mapping
    out_base: int = 0
    out_count: int = 0
    set_base: int = 0
    set_count: int = 0
    in_base: int = 0
    side_set_base: int = 0
    jmp_pin: int = 0

    # Shift configuration
    pull_threshold: int = 32
    push_threshold: int = 32
    out_shiftdir: bool = True   # True = shift right (LSB first)
    in_shiftdir: bool = True    # True = shift right (LSB first)
    autopull: bool = False
    autopush: bool = False

    # Clock divider
    clkdiv_int: int = 1
    clkdiv_frac: int = 0

    # State
    enabled: bool = False
    stalled: bool = False
    delay_cycles: int = 0

    # Cycle counter
    cycles: int = 0

    def reset(self):
        """Reset state machine to initial state."""
        self.pc = self.wrap_bottom
        self.x = 0
        self.y = 0
        self.isr = 0
        self.osr = 0
        self.isr_shift_count = 0
        self.osr_shift_count = 0
        self.tx_fifo.clear()
        self.rx_fifo.clear()
        self.stalled = False
        self.delay_cycles = 0
        self.cycles = 0

    def tx_empty(self) -> bool:
        """Check if TX FIFO is empty."""
        return len(self.tx_fifo) == 0

    def tx_full(self) -> bool:
        """Check if TX FIFO is full."""
        return len(self.tx_fifo) >= self.fifo_depth

    def rx_empty(self) -> bool:
        """Check if RX FIFO is empty."""
        return len(self.rx_fifo) == 0

    def rx_full(self) -> bool:
        """Check if RX FIFO is full."""
        return len(self.rx_fifo) >= self.fifo_depth

    def push_tx(self, value: int):
        """Push value to TX FIFO (from CPU side)."""
        if not self.tx_full():
            self.tx_fifo.append(value & 0xFFFFFFFF)

    def pop_rx(self) -> Optional[int]:
        """Pop value from RX FIFO (from CPU side)."""
        if self.rx_fifo:
            return self.rx_fifo.pop(0)
        return None

    def osr_empty(self) -> bool:
        """Check if OSR has been fully shifted out."""
        return self.osr_shift_count >= self.pull_threshold

    def isr_full(self) -> bool:
        """Check if ISR has been fully shifted in."""
        return self.isr_shift_count >= self.push_threshold


@dataclass
class PIOEmulator:
    """
    RP2040 PIO block emulator.

    The RP2040 has 2 PIO blocks (PIO0, PIO1), each with:
    - 32-word instruction memory (shared by 4 state machines)
    - 4 state machines
    - 8 IRQ flags

    Key timing characteristics:
    - Instructions execute in 1 system clock cycle (plus optional delay)
    - Side-set happens simultaneously with instruction
    - WAIT instructions can stall indefinitely
    """

    # PIO block index (0 or 1)
    index: int = 0

    # 32-word instruction memory
    instructions: List[int] = field(default_factory=lambda: [0] * 32)

    # 4 state machines
    sm: List[PIOStateMachine] = field(default_factory=lambda: [
        PIOStateMachine(index=i) for i in range(4)
    ])

    # IRQ flags (8 bits)
    irq_flags: int = 0

    # GPIO state (simulated, 32 pins)
    gpio_state: int = 0
    gpio_dir: int = 0

    # System clock frequency
    sys_clk: int = 125_000_000

    # Cycle counter
    total_cycles: int = 0

    # Callbacks for I/O
    on_gpio_write: Optional[Callable[[int, int], None]] = None  # (pins, dirs)
    on_irq: Optional[Callable[[int], None]] = None  # (irq_flags)

    def load_program(self, program: List[int], offset: int = 0):
        """
        Load a PIO program into instruction memory.

        Args:
            program: List of 16-bit instruction words
            offset: Starting address in instruction memory
        """
        for i, instr in enumerate(program):
            if offset + i < 32:
                self.instructions[offset + i] = instr & 0xFFFF

    def configure_sm(self, sm_index: int, **kwargs):
        """Configure a state machine."""
        sm = self.sm[sm_index]
        for key, value in kwargs.items():
            if hasattr(sm, key):
                setattr(sm, key, value)

    def enable_sm(self, sm_mask: int):
        """Enable state machines by mask."""
        for i in range(4):
            if sm_mask & (1 << i):
                self.sm[i].enabled = True

    def disable_sm(self, sm_mask: int):
        """Disable state machines by mask."""
        for i in range(4):
            if sm_mask & (1 << i):
                self.sm[i].enabled = False

    def step_sm(self, sm: PIOStateMachine) -> int:
        """
        Execute one cycle for a state machine.

        Returns:
            Number of cycles consumed (1 + delay)
        """
        if not sm.enabled:
            return 0

        # Handle delay cycles
        if sm.delay_cycles > 0:
            sm.delay_cycles -= 1
            sm.cycles += 1
            return 1

        # Fetch instruction
        instr_raw = self.instructions[sm.pc]
        instr = PIOInstruction.decode(
            instr_raw,
            sm.side_set_bits,
            sm.side_set_opt
        )

        # Execute side-set (happens every cycle, simultaneously)
        if sm.side_set_bits > 0 and instr.side_set > 0:
            if sm.side_set_pindirs:
                # Set pin directions
                mask = ((1 << sm.side_set_bits) - 1) << sm.side_set_base
                self.gpio_dir = (self.gpio_dir & ~mask) | (instr.side_set << sm.side_set_base)
            else:
                # Set pin values
                mask = ((1 << sm.side_set_bits) - 1) << sm.side_set_base
                self.gpio_state = (self.gpio_state & ~mask) | (instr.side_set << sm.side_set_base)

        # Execute instruction
        next_pc = sm.pc + 1
        stall = False

        if instr.opcode == PIOOpcode.JMP:
            take_jump = False
            if instr.condition == PIOCondition.ALWAYS:
                take_jump = True
            elif instr.condition == PIOCondition.NOT_X:
                take_jump = (sm.x == 0)
            elif instr.condition == PIOCondition.X_DEC:
                take_jump = (sm.x != 0)
                sm.x = (sm.x - 1) & 0xFFFFFFFF
            elif instr.condition == PIOCondition.NOT_Y:
                take_jump = (sm.y == 0)
            elif instr.condition == PIOCondition.Y_DEC:
                take_jump = (sm.y != 0)
                sm.y = (sm.y - 1) & 0xFFFFFFFF
            elif instr.condition == PIOCondition.X_NE_Y:
                take_jump = (sm.x != sm.y)
            elif instr.condition == PIOCondition.PIN:
                pin_val = (self.gpio_state >> sm.jmp_pin) & 1
                take_jump = bool(pin_val)
            elif instr.condition == PIOCondition.NOT_OSRE:
                take_jump = not sm.osr_empty()

            if take_jump:
                next_pc = instr.address

        elif instr.opcode == PIOOpcode.WAIT:
            condition_met = False
            if instr.wait_source == PIOWaitSource.GPIO:
                pin_val = (self.gpio_state >> instr.wait_index) & 1
                condition_met = (pin_val == instr.wait_polarity)
            elif instr.wait_source == PIOWaitSource.PIN:
                pin_num = sm.in_base + instr.wait_index
                pin_val = (self.gpio_state >> pin_num) & 1
                condition_met = (pin_val == instr.wait_polarity)
            elif instr.wait_source == PIOWaitSource.IRQ:
                irq_val = (self.irq_flags >> instr.wait_index) & 1
                condition_met = (irq_val == instr.wait_polarity)
                if condition_met and instr.wait_polarity:
                    # Clear IRQ on wait 1 irq
                    self.irq_flags &= ~(1 << instr.wait_index)

            if not condition_met:
                stall = True
                next_pc = sm.pc  # Stay on WAIT instruction

        elif instr.opcode == PIOOpcode.IN:
            # Get source value
            src_val = 0
            if instr.source == 0:  # PINS
                src_val = (self.gpio_state >> sm.in_base) & 0xFFFFFFFF
            elif instr.source == 1:  # X
                src_val = sm.x
            elif instr.source == 2:  # Y
                src_val = sm.y
            elif instr.source == 3:  # NULL
                src_val = 0
            elif instr.source == 6:  # ISR
                src_val = sm.isr
            elif instr.source == 7:  # OSR
                src_val = sm.osr

            # Shift into ISR
            bit_count = instr.bit_count
            if sm.in_shiftdir:  # Shift right
                sm.isr >>= bit_count
                sm.isr |= (src_val & ((1 << bit_count) - 1)) << (32 - bit_count)
            else:  # Shift left
                sm.isr <<= bit_count
                sm.isr |= src_val & ((1 << bit_count) - 1)
            sm.isr &= 0xFFFFFFFF
            sm.isr_shift_count += bit_count

            # Autopush
            if sm.autopush and sm.isr_full():
                if not sm.rx_full():
                    sm.rx_fifo.append(sm.isr)
                    sm.isr = 0
                    sm.isr_shift_count = 0
                else:
                    stall = True
                    next_pc = sm.pc

        elif instr.opcode == PIOOpcode.OUT:
            # Autopull if needed
            if sm.autopull and sm.osr_empty():
                if sm.tx_fifo:
                    sm.osr = sm.tx_fifo.pop(0)
                    sm.osr_shift_count = 0
                else:
                    stall = True
                    next_pc = sm.pc

            if not stall:
                # Shift out of OSR
                bit_count = instr.bit_count
                if sm.out_shiftdir:  # Shift right
                    out_val = sm.osr & ((1 << bit_count) - 1)
                    sm.osr >>= bit_count
                else:  # Shift left
                    out_val = (sm.osr >> (32 - bit_count)) & ((1 << bit_count) - 1)
                    sm.osr <<= bit_count
                sm.osr &= 0xFFFFFFFF
                sm.osr_shift_count += bit_count

                # Write to destination
                if instr.destination == 0:  # PINS
                    mask = ((1 << bit_count) - 1) << sm.out_base
                    self.gpio_state = (self.gpio_state & ~mask) | ((out_val << sm.out_base) & mask)
                elif instr.destination == 1:  # X
                    sm.x = out_val
                elif instr.destination == 2:  # Y
                    sm.y = out_val
                elif instr.destination == 4:  # PINDIRS
                    mask = ((1 << bit_count) - 1) << sm.out_base
                    self.gpio_dir = (self.gpio_dir & ~mask) | ((out_val << sm.out_base) & mask)
                elif instr.destination == 5:  # PC
                    next_pc = out_val & 0x1F
                elif instr.destination == 6:  # ISR
                    sm.isr = out_val
                elif instr.destination == 7:  # EXEC
                    # Execute the shifted-out value as instruction
                    pass  # Complex, skip for now

        elif instr.opcode == PIOOpcode.PUSH:
            is_pull = (instr.raw >> 7) & 1
            if is_pull:
                # PULL instruction
                block = instr.block
                if_empty = instr.if_empty

                if if_empty and not sm.osr_empty():
                    pass  # Don't pull if OSR not empty
                elif sm.tx_fifo:
                    sm.osr = sm.tx_fifo.pop(0)
                    sm.osr_shift_count = 0
                elif block:
                    stall = True
                    next_pc = sm.pc
                else:
                    # Pull from X register if non-blocking and FIFO empty
                    sm.osr = sm.x
                    sm.osr_shift_count = 0
            else:
                # PUSH instruction
                block = instr.block
                if_full = instr.if_full

                if if_full and not sm.isr_full():
                    pass  # Don't push if ISR not full
                elif not sm.rx_full():
                    sm.rx_fifo.append(sm.isr)
                    sm.isr = 0
                    sm.isr_shift_count = 0
                elif block:
                    stall = True
                    next_pc = sm.pc

        elif instr.opcode == PIOOpcode.MOV:
            # Get source value
            src_val = 0
            if instr.source == 0:  # PINS
                src_val = (self.gpio_state >> sm.in_base) & 0xFFFFFFFF
            elif instr.source == 1:  # X
                src_val = sm.x
            elif instr.source == 2:  # Y
                src_val = sm.y
            elif instr.source == 3:  # NULL
                src_val = 0
            elif instr.source == 5:  # STATUS
                # TX FIFO level in bits 3:0, RX FIFO level in bits 7:4
                src_val = len(sm.tx_fifo) | (len(sm.rx_fifo) << 4)
            elif instr.source == 6:  # ISR
                src_val = sm.isr
            elif instr.source == 7:  # OSR
                src_val = sm.osr

            # Apply operation
            if instr.operation == PIOMovOp.INVERT:
                src_val = (~src_val) & 0xFFFFFFFF
            elif instr.operation == PIOMovOp.BIT_REVERSE:
                src_val = int(f'{src_val:032b}'[::-1], 2)

            # Write to destination
            if instr.destination == 0:  # PINS
                mask = ((1 << sm.out_count) - 1) << sm.out_base
                self.gpio_state = (self.gpio_state & ~mask) | ((src_val << sm.out_base) & mask)
            elif instr.destination == 1:  # X
                sm.x = src_val
            elif instr.destination == 2:  # Y
                sm.y = src_val
            elif instr.destination == 4:  # EXEC
                pass  # Execute src_val as instruction
            elif instr.destination == 5:  # PC
                next_pc = src_val & 0x1F
            elif instr.destination == 6:  # ISR
                sm.isr = src_val
                sm.isr_shift_count = 0
            elif instr.destination == 7:  # OSR
                sm.osr = src_val
                sm.osr_shift_count = 0

        elif instr.opcode == PIOOpcode.IRQ:
            irq_num = instr.irq_index & 0x7
            # Relative IRQ addressing
            if instr.irq_index & 0x10:
                irq_num = (irq_num + sm.index) & 0x3

            if instr.irq_clear:
                self.irq_flags &= ~(1 << irq_num)
            else:
                self.irq_flags |= (1 << irq_num)

            if instr.irq_wait:
                # Wait for IRQ to be cleared
                if self.irq_flags & (1 << irq_num):
                    stall = True
                    next_pc = sm.pc

        elif instr.opcode == PIOOpcode.SET:
            if instr.destination == 0:  # PINS
                mask = ((1 << sm.set_count) - 1) << sm.set_base
                self.gpio_state = (self.gpio_state & ~mask) | ((instr.data << sm.set_base) & mask)
            elif instr.destination == 1:  # X
                sm.x = instr.data
            elif instr.destination == 2:  # Y
                sm.y = instr.data
            elif instr.destination == 4:  # PINDIRS
                mask = ((1 << sm.set_count) - 1) << sm.set_base
                self.gpio_dir = (self.gpio_dir & ~mask) | ((instr.data << sm.set_base) & mask)

        # Handle wrap
        if next_pc > sm.wrap_top:
            next_pc = sm.wrap_bottom

        sm.stalled = stall
        if not stall:
            sm.pc = next_pc
            sm.delay_cycles = instr.delay

        sm.cycles += 1
        return 1

    def step(self) -> int:
        """
        Execute one cycle for all enabled state machines.

        Returns:
            Number of cycles consumed
        """
        cycles = 0
        for sm in self.sm:
            cycles += self.step_sm(sm)
        self.total_cycles += 1

        # Trigger GPIO callback if set
        if self.on_gpio_write:
            self.on_gpio_write(self.gpio_state, self.gpio_dir)

        return cycles

    def run_cycles(self, count: int) -> int:
        """Run for a specific number of cycles."""
        for _ in range(count):
            self.step()
        return count

    def disassemble(self, start: int = 0, end: int = 32) -> List[str]:
        """Disassemble instruction memory."""
        result = []
        for addr in range(start, min(end, 32)):
            instr = PIOInstruction.decode(self.instructions[addr])
            result.append(f"{addr:2d}: {instr}")
        return result


# Common PIO programs for testing
class PIOPrograms:
    """Collection of common PIO programs."""

    @staticmethod
    def blink_led() -> List[int]:
        """Simple LED blink program (set pins high, delay, set low, delay)."""
        return [
            0xE001,  # set pins, 1     [0]
            0xE000,  # set pins, 0     [0]
        ]

    @staticmethod
    def ws2812_bitbang() -> List[int]:
        """WS2812 NeoPixel bit-banging program."""
        # This is a simplified version
        return [
            0x6221,  # out x, 1        side 0 [2]
            0x1023,  # jmp !x, 3       side 1 [0]
            0x1000,  # jmp 0           side 1 [0]
            0x0000,  # jmp 0           side 0 [0]
        ]

    @staticmethod
    def uart_tx() -> List[int]:
        """Simple UART TX program."""
        return [
            0x9FA0,  # pull block      side 1 [31]
            0xF727,  # set x, 7        side 0 [7]
            0x6001,  # out pins, 1     [0]
            0x0642,  # jmp x--, 2      [6]
        ]

    @staticmethod
    def spi_tx() -> List[int]:
        """SPI TX program (mode 0)."""
        return [
            0x80A0,  # pull block
            0x6001,  # out pins, 1     ; shift out 1 bit
            0xE000,  # set pins, 0     ; clock low
            0xE001,  # set pins, 1     ; clock high
            0x0001,  # jmp 1           ; loop
        ]
