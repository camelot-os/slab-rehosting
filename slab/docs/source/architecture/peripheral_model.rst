.. _peripheral_model:

=================
Peripheral Model
=================

This document describes the peripheral implementation model used in MCUemu.

Design Goals
============

1. **Accuracy**: Match real hardware register behavior
2. **Debuggability**: Full MMIO tracing and callbacks
3. **Performance**: Minimize overhead per access
4. **Extensibility**: Easy to add new peripherals

Base Peripheral Class
=====================

All peripherals inherit from a common base:

.. code-block:: python

   class BasePeripheral:
       """Base class for MCUemu peripherals."""

       def __init__(self, base: int, size: int = 0x400, name: str = ""):
           self.base = base
           self.size = size
           self.name = name or self.__class__.__name__
           self.regs = {}

       def contains(self, address: int) -> bool:
           """Check if address is within peripheral's range."""
           return self.base <= address < self.base + self.size

       def read(self, address: int, size: int) -> tuple:
           """
           Handle MMIO read.

           Args:
               address: Absolute MMIO address
               size: Access size (1, 2, or 4 bytes)

           Returns:
               (value, status) tuple
           """
           offset = address - self.base
           value = self.regs.get(offset, 0)
           return (value, 0)

       def write(self, address: int, size: int, value: int) -> int:
           """
           Handle MMIO write.

           Args:
               address: Absolute MMIO address
               size: Access size (1, 2, or 4 bytes)
               value: Value to write

           Returns:
               Status (0=OK, 1=error)
           """
           offset = address - self.base
           self.regs[offset] = value
           return 0

Register Semantics
==================

Different register types require different handling:

Read-Write Registers
--------------------

Standard registers that store written values:

.. code-block:: python

   def write(self, address, size, value):
       offset = address - self.base
       if offset == self.CR:
           self.cr = value
       return 0

   def read(self, address, size):
       offset = address - self.base
       if offset == self.CR:
           return (self.cr, 0)

Read-Only Registers
-------------------

Hardware state that firmware can only observe:

.. code-block:: python

   def read(self, address, size):
       offset = address - self.base
       if offset == self.SR:
           # Build status from internal state
           status = 0
           if self.tx_empty:
               status |= SR_TXE
           if self.rx_ready:
               status |= SR_RXNE
           return (status, 0)

Write-1-to-Clear Registers
--------------------------

Writing 1 clears specific bits:

.. code-block:: python

   def write(self, address, size, value):
       offset = address - self.base
       if offset == self.SR:
           # Clear bits where 1 was written
           self.sr &= ~value
       return 0

Set/Reset Registers
-------------------

Separate set and reset operations (e.g., GPIO BSRR):

.. code-block:: python

   def write(self, address, size, value):
       offset = address - self.base
       if offset == self.BSRR:
           # Lower 16 bits: set pins
           set_bits = value & 0xFFFF
           # Upper 16 bits: reset pins
           reset_bits = (value >> 16) & 0xFFFF
           self.odr = (self.odr | set_bits) & ~reset_bits
       return 0

Callback System
===============

Peripherals support callbacks for external integration:

.. code-block:: python

   class STM32GPIO:
       def __init__(self, base, port_name):
           self.base = base
           self.port_name = port_name

           # Callback: (pin, value, is_output) -> None
           self.on_pin_change = None

       def write(self, address, size, value):
           offset = address - self.base
           old_odr = self.odr

           if offset == self.ODR:
               self.odr = value
               self._notify_changes(old_odr)
           elif offset == self.BSRR:
               # ... BSRR handling
               self._notify_changes(old_odr)

           return 0

       def _notify_changes(self, old_odr):
           if self.on_pin_change is None:
               return

           changed = old_odr ^ self.odr
           for pin in range(16):
               if changed & (1 << pin):
                   new_val = (self.odr >> pin) & 1
                   mode = (self.moder >> (pin * 2)) & 0x3
                   is_output = (mode == 1)
                   self.on_pin_change(pin, new_val, is_output)

Polling Detection
=================

Detect infinite polling loops and auto-set ready flags:

.. code-block:: python

   class STM32RCC:
       def __init__(self, base):
           self.base = base
           self.cr = 0x00000083  # HSI enabled + ready

           # Polling detection
           self._poll_count = {}
           self._poll_threshold = 5

       def read(self, address, size):
           offset = address - self.base

           if offset == self.CR:
               # Track repeated reads
               key = (offset, self.cr)
               self._poll_count[key] = self._poll_count.get(key, 0) + 1

               if self._poll_count[key] >= self._poll_threshold:
                   # Auto-set ready flags
                   self._update_ready_flags()

               return (self.cr, 0)

       def _update_ready_flags(self):
           """Set ready flags for enabled oscillators."""
           if self.cr & (1 << 16):  # HSEON
               self.cr |= (1 << 17)  # HSERDY
           if self.cr & (1 << 24):  # PLLON
               self.cr |= (1 << 25)  # PLLRDY

Peripheral Sets
===============

Group peripherals into MCU-specific sets:

.. code-block:: python

   class STM32F4PeripheralSet:
       """Complete peripheral set for STM32F4."""

       def __init__(self):
           self.peripherals = {}

           # Initialize all peripherals
           self.rcc = STM32F4RCC(0x40023800)
           self.peripherals['RCC'] = self.rcc

           self.gpio = {}
           for i, name in enumerate('ABCDEFGHI'):
               gpio = STM32GPIO(0x40020000 + i * 0x400, name)
               self.gpio[name] = gpio
               self.peripherals[f'GPIO{name}'] = gpio

           self.usart2 = STM32USART(0x40004400)
           self.peripherals['USART2'] = self.usart2

           self.cryp = STM32CRYP(0x50060000)
           self.peripherals['CRYP'] = self.cryp

           # ... more peripherals

       def read(self, address: int, size: int) -> tuple:
           for periph in self.peripherals.values():
               if periph.contains(address):
                   return periph.read(address, size)
           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           for periph in self.peripherals.values():
               if periph.contains(address):
                   return periph.write(address, size, value)
           return 0

Testing Peripherals
===================

Validate peripheral behavior with unit tests:

.. code-block:: python

   def test_gpio_bsrr():
       gpio = STM32GPIO(0x40020000, 'A')

       # Set pin 5
       gpio.write(0x40020018, 4, 0x0020)  # BSRR
       assert gpio.odr == 0x0020

       # Reset pin 5
       gpio.write(0x40020018, 4, 0x00200000)
       assert gpio.odr == 0x0000

   def test_cryp_aes():
       cryp = STM32CRYP(0x50060000)

       key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
       plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
       expected = bytes.fromhex("3ad77bb40d7a3660a89ecaf32466ef97")

       cryp.set_key(key, keysize=128)
       result = cryp.encrypt_block(plaintext)

       assert result == expected

Next Steps
==========

* :ref:`stubbing_peripherals` - Create custom stubs
* :ref:`api/slab_stm32` - STM32 peripheral API
* :ref:`debugging_bootloops` - Handle boot issues
