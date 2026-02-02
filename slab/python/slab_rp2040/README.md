# Slab RP2040 - Raspberry Pi Pico Support

Timing models, peripheral emulation, and security analysis tools for the RP2040 microcontroller (Raspberry Pi Pico).

## Features

- **Dual Cortex-M0+ Timing Model**: Cycle-accurate timing for both cores
- **PIO Emulation**: Full PIO (Programmable I/O) state machine emulator
- **Memory Timing**: XIP flash cache hit/miss, SRAM, SIO timing
- **Clock Configuration**: Support for 125-133MHz operation

## Quick Start

### 1. Basic Timing Model

```python
from slab_rp2040 import RP2040Timing, CortexM0PlusTiming

# Create timing model at 125MHz
timing = RP2040Timing(frequency=125_000_000)

# Get instruction cycles
cycles = timing.core0.get_instruction_cycles("mul")
print(f"MUL takes {cycles} cycles")  # 32 cycles on M0+!

# Estimate function execution
instructions = [
    {"mnemonic": "push", "operands": ["r4", "r5", "lr"]},
    {"mnemonic": "ldr", "operands": ["r0", "[r1]"]},
    {"mnemonic": "add", "operands": ["r0", "r2"]},
    {"mnemonic": "str", "operands": ["r0", "[r1]"]},
    {"mnemonic": "pop", "operands": ["r4", "r5", "pc"]},
]
total = timing.estimate_function_cycles(instructions)
print(f"Function: {total} cycles ({timing.cycles_to_us(total):.2f} us)")
```

### 2. Memory Access Timing

```python
from slab_rp2040 import RP2040MemoryTiming

mem = RP2040MemoryTiming()

# SRAM is single-cycle
sram_cycles = mem.get_access_cycles(0x20000000)
print(f"SRAM read: {sram_cycles} cycle")

# XIP Flash depends on cache
xip_hit = mem.get_access_cycles(0x10000000, cache_hit=True)
xip_miss = mem.get_access_cycles(0x10000000, cache_hit=False)
print(f"XIP cache hit: {xip_hit}, miss: {xip_miss}")

# SIO is single-cycle (important for spinlocks!)
sio_cycles = mem.get_access_cycles(0xD0000000)
print(f"SIO access: {sio_cycles} cycle")
```

### 3. PIO Emulation

```python
from slab_rp2040 import PIOEmulator, PIOInstruction, PIOStateMachine

# Create PIO block
pio = PIOEmulator(index=0)

# Load a simple blink program
blink_program = [
    0xE001,  # set pins, 1
    0xFF00,  # nop [31]
    0xE000,  # set pins, 0
    0xFF00,  # nop [31]
]
pio.load_program(blink_program, offset=0)

# Configure state machine 0
pio.configure_sm(0,
    wrap_bottom=0,
    wrap_top=3,
    set_base=25,   # GPIO 25 (LED on Pico)
    set_count=1,
)

# Enable and run
pio.enable_sm(0x1)

for i in range(100):
    pio.step()
    if i % 10 == 0:
        print(f"Cycle {pio.total_cycles}: GPIO={pio.gpio_state:08x}")
```

### 4. Disassemble PIO Program

```python
from slab_rp2040 import PIOInstruction

# WS2812 NeoPixel bitbang program
ws2812 = [0x6221, 0x1023, 0x1000, 0xA442]

for addr, instr_raw in enumerate(ws2812):
    instr = PIOInstruction.decode(instr_raw, side_set_bits=1)
    print(f"{addr}: {instr}")
```

### 5. Dual-Core Timing Analysis

```python
from slab_rp2040 import RP2040Timing

timing = RP2040Timing(frequency=133_000_000)

# Spinlock timing (critical for multicore)
acquire = timing.spinlock_acquire  # 2 cycles (SIO access)
release = timing.spinlock_release  # 1 cycle

# FIFO timing
fifo_push = timing.fifo_push  # 1 cycle if not full
fifo_pop = timing.fifo_pop    # 1 cycle if not empty

# Interrupt latency
irq_overhead = timing.irq_entry + timing.irq_exit
print(f"IRQ overhead: {irq_overhead} cycles")
```

### 6. Security Analysis - Timing Leakage

```python
from slab_rp2040 import RP2040Timing

timing = RP2040Timing()

# Cortex-M0+ has NO single-cycle multiplier!
# This creates timing side-channel in crypto
mul_cycles = timing.core0.get_instruction_cycles("mul")
print(f"MUL: {mul_cycles} cycles")  # 32 cycles - variable!

# Branch timing differs
branch_taken = timing.core0.get_instruction_cycles("beq", branch_taken=True)
branch_not_taken = timing.core0.get_instruction_cycles("beq", branch_taken=False)
print(f"Branch taken: {branch_taken}, not taken: {branch_not_taken}")
```

## Key Timing Characteristics

| Operation | Cycles | Notes |
|-----------|--------|-------|
| Most ALU ops | 1 | add, sub, and, orr, etc. |
| MUL | 32 | No single-cycle multiplier on M0+! |
| LDR/STR | 2 | 1 + memory access |
| Branch taken | 3 | 2-stage pipeline refill |
| Branch not taken | 1 | |
| SRAM access | 1 | Single-cycle |
| XIP cache hit | 1 | |
| XIP cache miss | 8-12 | Flash latency |
| SIO access | 1 | Single-cycle I/O |
| Spinlock acquire | 2 | SIO read-modify-write |

## PIO Instruction Set

| Opcode | Cycles | Description |
|--------|--------|-------------|
| JMP | 1 | Jump (conditional or unconditional) |
| WAIT | 1+ | Wait for GPIO/PIN/IRQ condition |
| IN | 1 | Shift bits into ISR |
| OUT | 1 | Shift bits out of OSR |
| PUSH | 1 | Push ISR to RX FIFO |
| PULL | 1 | Pull TX FIFO to OSR |
| MOV | 1 | Move between registers |
| IRQ | 1 | Set/clear/wait IRQ flag |
| SET | 1 | Set pins/X/Y to immediate value |

All instructions can have 0-31 cycles of delay added.

## Memory Map

| Region | Address | Size | Access Time |
|--------|---------|------|-------------|
| ROM | 0x00000000 | 16KB | 1 cycle |
| XIP Flash | 0x10000000 | 16MB | 1-12 cycles |
| SRAM | 0x20000000 | 264KB | 1 cycle |
| APB Peripherals | 0x40000000 | - | 3 cycles |
| AHB Peripherals | 0x50000000 | - | 2 cycles |
| SIO | 0xD0000000 | - | 1 cycle |

## References

- [RP2040 Datasheet](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf)
- [ARM Cortex-M0+ TRM](https://developer.arm.com/documentation/ddi0484)
- [Pico SDK Documentation](https://raspberrypi.github.io/pico-sdk-doxygen/)

## License

GPL-2.0-or-later
