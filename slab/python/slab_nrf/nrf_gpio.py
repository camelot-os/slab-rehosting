"""
NRF GPIO and GPIOTE Peripherals

GPIO features:
- 32 pins per port (P0, P1 on some devices)
- Individual pin configuration
- Drive strength selection
- Pull-up/pull-down
- Sense for wake-up

GPIOTE (GPIO Tasks and Events):
- 8 channels
- Task mode (set/clear/toggle pin)
- Event mode (detect pin change)
- Port event (any configured pin)

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import logging
from typing import Optional, Callable, List
from .nrf_base import NRFPeripheral


class NRFGPIO(NRFPeripheral):
    """
    NRF GPIO Port.

    Register Map:
        0x504: OUT       - Write output
        0x508: OUTSET    - Set output bits
        0x50C: OUTCLR    - Clear output bits
        0x510: IN        - Read input
        0x514: DIR       - Direction
        0x518: DIRSET    - Set direction bits
        0x51C: DIRCLR    - Clear direction bits
        0x520: LATCH     - Latch for sense
        0x524: DETECTMODE
        0x700+: PIN_CNF[n] - Per-pin configuration
    """

    OUT = 0x504
    OUTSET = 0x508
    OUTCLR = 0x50C
    IN = 0x510
    DIR = 0x514
    DIRSET = 0x518
    DIRCLR = 0x51C
    LATCH = 0x520
    DETECTMODE = 0x524
    PIN_CNF_BASE = 0x700

    # PIN_CNF bits
    CNF_DIR = 1 << 0         # 0=input, 1=output
    CNF_INPUT = 1 << 1       # 0=connect, 1=disconnect
    CNF_PULL = 0x3 << 2      # 00=none, 01=down, 11=up
    CNF_DRIVE = 0x7 << 8     # Drive strength
    CNF_SENSE = 0x3 << 16    # Sense mode

    GPIO_BASES = {
        0: 0x50000000,  # P0
        1: 0x50000300,  # P1 (nRF52840/nRF5340)
    }

    def __init__(self, port: int = 0, base: int = None):
        if base is None:
            base = self.GPIO_BASES.get(port, 0x50000000)

        # Size must include PIN_CNF registers (up to 0x77C)
        super().__init__(f"GPIO{port}", base, 0x800)
        self.port = port

        self.out = 0
        self.dir = 0
        self.latch = 0
        self.detectmode = 0
        self.pin_cnf = [0] * 32

        # External input state
        self._input = 0

        # Callbacks
        self.on_output_change: Optional[Callable[[int, int], None]] = None

    def _read_reg(self, offset: int, size: int) -> int:
        if offset == self.OUT:
            return self.out
        elif offset == self.IN:
            return self._get_input()
        elif offset == self.DIR:
            return self.dir
        elif offset == self.LATCH:
            return self.latch
        elif offset == self.DETECTMODE:
            return self.detectmode
        elif self.PIN_CNF_BASE <= offset < self.PIN_CNF_BASE + 128:
            pin = (offset - self.PIN_CNF_BASE) // 4
            return self.pin_cnf[pin] if pin < 32 else 0
        return 0

    def _write_reg(self, offset: int, size: int, value: int):
        if offset == self.OUT:
            self._set_out(value)
        elif offset == self.OUTSET:
            self._set_out(self.out | value)
        elif offset == self.OUTCLR:
            self._set_out(self.out & ~value)
        elif offset == self.DIR:
            self.dir = value
        elif offset == self.DIRSET:
            self.dir |= value
        elif offset == self.DIRCLR:
            self.dir &= ~value
        elif offset == self.LATCH:
            self.latch &= ~value  # Write 1 to clear
        elif offset == self.DETECTMODE:
            self.detectmode = value
        elif self.PIN_CNF_BASE <= offset < self.PIN_CNF_BASE + 128:
            pin = (offset - self.PIN_CNF_BASE) // 4
            if pin < 32:
                self.pin_cnf[pin] = value

    def _set_out(self, value: int):
        old = self.out
        self.out = value

        if old != value and self.on_output_change:
            self.on_output_change(self.port, value)

    def _get_input(self) -> int:
        """Get input value, combining external input with output for outputs."""
        result = 0
        for pin in range(32):
            if self.dir & (1 << pin):
                # Output pin - read back output
                if self.out & (1 << pin):
                    result |= (1 << pin)
            else:
                # Input pin - read external input
                if self._input & (1 << pin):
                    result |= (1 << pin)
        return result

    def set_input(self, pin: int, value: bool):
        """Set external input state for a pin."""
        if value:
            self._input |= (1 << pin)
        else:
            self._input &= ~(1 << pin)

    def set_input_word(self, value: int):
        """Set all external inputs at once."""
        self._input = value

    # Convenience methods for easier use
    def set_pin_mode(self, pin: int, output: bool = True):
        """Configure pin as input or output."""
        if output:
            self.dir |= (1 << pin)
            # Configure pin for output
            self.pin_cnf[pin] = self.CNF_DIR | (1 << 1)  # output, disconnect input
        else:
            self.dir &= ~(1 << pin)
            # Configure pin for input, connect input buffer
            self.pin_cnf[pin] = 0

    def write_pin(self, pin: int, value: bool):
        """Set output pin high or low."""
        if value:
            self._set_out(self.out | (1 << pin))
        else:
            self._set_out(self.out & ~(1 << pin))

    def read_pin(self, pin: int) -> bool:
        """Read pin state (input or output)."""
        return bool(self._get_input() & (1 << pin))

    def read_port(self) -> int:
        """Read all pins as a word."""
        return self._get_input()


class NRFGPIOTE(NRFPeripheral):
    """
    NRF GPIO Tasks and Events.

    Provides task/event interface to GPIO pins:
    - 8 channels (0-7)
    - Task mode: OUT, SET, CLR tasks
    - Event mode: IN events
    - Port event: any pin change

    Register Map:
        0x000: TASKS_OUT[0-7]  - Output tasks
        0x030: TASKS_SET[0-7]  - Set tasks
        0x060: TASKS_CLR[0-7]  - Clear tasks
        0x100: EVENTS_IN[0-7]  - Input events
        0x17C: EVENTS_PORT     - Port event
        0x200: SHORTS
        0x300: INTEN/SET/CLR
        0x510: CONFIG[0-7]     - Channel configuration
    """

    TASKS_OUT_BASE = 0x000
    TASKS_SET_BASE = 0x030
    TASKS_CLR_BASE = 0x060
    EVENTS_IN_BASE = 0x100
    EVENTS_PORT = 0x17C
    CONFIG_BASE = 0x510

    # CONFIG bits
    CONFIG_MODE = 0x3         # 00=disabled, 01=event, 11=task
    CONFIG_PSEL = 0x1F << 8   # Pin select
    CONFIG_PORT = 0x1 << 13   # Port select (nRF52840)
    CONFIG_POLARITY = 0x3 << 16  # 01=LoToHi, 02=HiToLo, 03=Toggle
    CONFIG_OUTINIT = 1 << 20  # Initial output value

    def __init__(self, base: int = 0x40006000):
        super().__init__("GPIOTE", base, 0x1000, irq=6)

        self.config = [0] * 8

        # GPIO port references
        self.gpio_ports: List[Optional[NRFGPIO]] = [None, None]

    def _read_reg(self, offset: int, size: int) -> int:
        if self.CONFIG_BASE <= offset < self.CONFIG_BASE + 32:
            ch = (offset - self.CONFIG_BASE) // 4
            return self.config[ch] if ch < 8 else 0
        return self.regs.get(offset, 0)

    def _write_reg(self, offset: int, size: int, value: int):
        if self.CONFIG_BASE <= offset < self.CONFIG_BASE + 32:
            ch = (offset - self.CONFIG_BASE) // 4
            if ch < 8:
                self._configure_channel(ch, value)
        else:
            self.regs[offset] = value

    def _handle_task(self, offset: int):
        if self.TASKS_OUT_BASE <= offset < self.TASKS_OUT_BASE + 32:
            ch = (offset - self.TASKS_OUT_BASE) // 4
            self._do_task_out(ch)
        elif self.TASKS_SET_BASE <= offset < self.TASKS_SET_BASE + 32:
            ch = (offset - self.TASKS_SET_BASE) // 4
            self._do_task_set(ch)
        elif self.TASKS_CLR_BASE <= offset < self.TASKS_CLR_BASE + 32:
            ch = (offset - self.TASKS_CLR_BASE) // 4
            self._do_task_clr(ch)

    def _configure_channel(self, ch: int, value: int):
        self.config[ch] = value

        mode = value & self.CONFIG_MODE
        if mode == 3:  # Task mode
            # Set initial output
            outinit = (value >> 20) & 1
            self._set_pin(ch, outinit)

    def _get_pin_port(self, ch: int):
        """Get GPIO port and pin for channel."""
        cfg = self.config[ch]
        port = (cfg >> 13) & 1
        pin = (cfg >> 8) & 0x1F
        return port, pin

    def _set_pin(self, ch: int, value: int):
        """Set pin output."""
        port, pin = self._get_pin_port(ch)
        gpio = self.gpio_ports[port]
        if gpio:
            if value:
                gpio.out |= (1 << pin)
            else:
                gpio.out &= ~(1 << pin)

    def _do_task_out(self, ch: int):
        """Toggle pin."""
        port, pin = self._get_pin_port(ch)
        gpio = self.gpio_ports[port]
        if gpio:
            gpio.out ^= (1 << pin)

    def _do_task_set(self, ch: int):
        """Set pin high."""
        self._set_pin(ch, 1)

    def _do_task_clr(self, ch: int):
        """Set pin low."""
        self._set_pin(ch, 0)

    def check_pin_change(self, port: int, pin: int, rising: bool):
        """Check if pin change triggers any channel."""
        for ch in range(8):
            cfg = self.config[ch]
            if (cfg & self.CONFIG_MODE) != 1:  # Not event mode
                continue

            cfg_port = (cfg >> 13) & 1
            cfg_pin = (cfg >> 8) & 0x1F

            if port != cfg_port or pin != cfg_pin:
                continue

            polarity = (cfg >> 16) & 0x3
            if polarity == 1 and rising:
                self.set_event(self.EVENTS_IN_BASE + ch * 4)
            elif polarity == 2 and not rising:
                self.set_event(self.EVENTS_IN_BASE + ch * 4)
            elif polarity == 3:  # Toggle
                self.set_event(self.EVENTS_IN_BASE + ch * 4)
