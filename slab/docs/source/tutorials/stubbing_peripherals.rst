.. _stubbing_peripherals:

=====================
Stubbing Peripherals
=====================

This tutorial explains how to create peripheral stubs for MCUemu.
Stubs intercept MMIO accesses and provide responses that satisfy firmware expectations.

Peripheral Model Architecture
=============================

Every MCUemu peripheral follows a common interface:

.. figure:: ../images/peripheral_model.png
   :alt: Peripheral Model
   :align: center
   :width: 80%

   Peripheral Model: Base address + register map + read/write handlers

.. code-block:: python
   :caption: Base Peripheral Class

   class BasePeripheral:
       """Base class for all MCUemu peripherals."""

       def __init__(self, base: int, size: int = 0x400, name: str = ""):
           self.base = base
           self.size = size
           self.name = name or self.__class__.__name__
           self.regs = {}  # Register storage

       def contains(self, address: int) -> bool:
           """Check if address is within this peripheral's range."""
           return self.base <= address < self.base + self.size

       def read(self, address: int, size: int) -> tuple:
           """
           Handle MMIO read.

           Returns:
               (value, status) where status=0 means OK
           """
           offset = address - self.base
           value = self.regs.get(offset, 0)
           return (value, 0)

       def write(self, address: int, size: int, value: int) -> int:
           """
           Handle MMIO write.

           Returns:
               status (0=OK, 1=error)
           """
           offset = address - self.base
           self.regs[offset] = value
           return 0

Creating a Simple Stub: GPIO
============================

Let's create a GPIO peripheral stub step by step:

Step 1: Define Register Layout
------------------------------

From the STM32 reference manual, GPIO registers are:

.. list-table:: GPIO Register Map
   :widths: 15 15 70
   :header-rows: 1

   * - Offset
     - Name
     - Description
   * - 0x00
     - MODER
     - Mode register (input/output/alternate/analog)
   * - 0x04
     - OTYPER
     - Output type (push-pull/open-drain)
   * - 0x08
     - OSPEEDR
     - Output speed
   * - 0x0C
     - PUPDR
     - Pull-up/pull-down
   * - 0x10
     - IDR
     - Input data register
   * - 0x14
     - ODR
     - Output data register
   * - 0x18
     - BSRR
     - Bit set/reset register

Step 2: Implement the Peripheral
--------------------------------

.. code-block:: python
   :caption: stm32_gpio.py

   from typing import Optional, Callable

   class STM32GPIO:
       """STM32 GPIO peripheral stub."""

       # Register offsets
       MODER   = 0x00
       OTYPER  = 0x04
       OSPEEDR = 0x08
       PUPDR   = 0x0C
       IDR     = 0x10
       ODR     = 0x14
       BSRR    = 0x18
       LCKR    = 0x1C
       AFRL    = 0x20
       AFRH    = 0x24

       def __init__(self, base: int, port_name: str = 'A'):
           self.base = base
           self.size = 0x400
           self.name = f'GPIO{port_name}'
           self.port_name = port_name

           # Register storage
           self.moder = 0
           self.otyper = 0
           self.ospeedr = 0
           self.pupdr = 0
           self.idr = 0  # Input state
           self.odr = 0  # Output state
           self.afr = [0, 0]

           # Callback for pin changes
           self.on_pin_change: Optional[Callable[[int, int, bool], None]] = None

       def contains(self, address: int) -> bool:
           return self.base <= address < self.base + self.size

       def read(self, address: int, size: int) -> tuple:
           offset = address - self.base

           if offset == self.MODER:
               return (self.moder, 0)
           elif offset == self.OTYPER:
               return (self.otyper, 0)
           elif offset == self.OSPEEDR:
               return (self.ospeedr, 0)
           elif offset == self.PUPDR:
               return (self.pupdr, 0)
           elif offset == self.IDR:
               return (self.idr, 0)
           elif offset == self.ODR:
               return (self.odr, 0)
           elif offset == self.AFRL:
               return (self.afr[0], 0)
           elif offset == self.AFRH:
               return (self.afr[1], 0)

           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           offset = address - self.base
           old_odr = self.odr

           if offset == self.MODER:
               self.moder = value
           elif offset == self.OTYPER:
               self.otyper = value
           elif offset == self.OSPEEDR:
               self.ospeedr = value
           elif offset == self.PUPDR:
               self.pupdr = value
           elif offset == self.ODR:
               self.odr = value
               self._notify_pin_change(old_odr)
           elif offset == self.BSRR:
               # Bit Set/Reset Register
               # Lower 16 bits: set pins
               # Upper 16 bits: reset pins
               set_bits = value & 0xFFFF
               reset_bits = (value >> 16) & 0xFFFF
               self.odr = (self.odr | set_bits) & ~reset_bits
               self._notify_pin_change(old_odr)
           elif offset == self.AFRL:
               self.afr[0] = value
           elif offset == self.AFRH:
               self.afr[1] = value

           return 0

       def _notify_pin_change(self, old_odr: int):
           """Notify callback of pin state changes."""
           if self.on_pin_change is None:
               return

           changed = old_odr ^ self.odr
           for pin in range(16):
               if changed & (1 << pin):
                   new_val = (self.odr >> pin) & 1
                   # Check if pin is configured as output
                   mode = (self.moder >> (pin * 2)) & 0x3
                   is_output = (mode == 1)  # 01 = Output mode
                   self.on_pin_change(pin, new_val, is_output)

       def set_input(self, pin: int, value: int):
           """Externally set an input pin value (for simulation)."""
           if value:
               self.idr |= (1 << pin)
           else:
               self.idr &= ~(1 << pin)

Step 3: Use the Peripheral
--------------------------

.. code-block:: python

   # Create GPIO with callback
   gpioa = STM32GPIO(base=0x40020000, port_name='A')

   def on_led_change(pin, value, is_output):
       if is_output and pin == 5:  # PA5 = LED
           print(f"LED {'ON' if value else 'OFF'}")

   gpioa.on_pin_change = on_led_change

   # Simulate firmware write to BSRR (set PA5)
   gpioa.write(0x40020018, 4, 0x0020)  # Set bit 5
   # Output: LED ON

   gpioa.write(0x40020018, 4, 0x00200000)  # Reset bit 5
   # Output: LED OFF

Creating a UART Stub
====================

UART peripherals require handling TX/RX data and status flags:

.. code-block:: python
   :caption: stm32_usart.py

   from collections import deque
   from typing import Optional, Callable

   class STM32USART:
       """STM32 USART peripheral stub."""

       # Register offsets (STM32F4)
       SR   = 0x00  # Status register
       DR   = 0x04  # Data register
       BRR  = 0x08  # Baud rate register
       CR1  = 0x0C  # Control register 1
       CR2  = 0x10  # Control register 2
       CR3  = 0x14  # Control register 3
       GTPR = 0x18  # Guard time and prescaler

       # Status register bits
       SR_TXE  = (1 << 7)   # TX empty
       SR_TC   = (1 << 6)   # Transmission complete
       SR_RXNE = (1 << 5)   # RX not empty
       SR_IDLE = (1 << 4)   # Idle line detected
       SR_ORE  = (1 << 3)   # Overrun error

       def __init__(self, base: int, name: str = 'USART'):
           self.base = base
           self.size = 0x400
           self.name = name

           # Registers
           self.sr = self.SR_TXE | self.SR_TC  # TX ready
           self.dr = 0
           self.brr = 0
           self.cr1 = 0
           self.cr2 = 0
           self.cr3 = 0

           # RX buffer (data from external source)
           self.rx_buffer: deque = deque(maxlen=256)

           # TX buffer (data sent by firmware)
           self.tx_buffer: deque = deque(maxlen=256)

           # Callbacks
           self.on_tx: Optional[Callable[[int], None]] = None

       def contains(self, address: int) -> bool:
           return self.base <= address < self.base + self.size

       def read(self, address: int, size: int) -> tuple:
           offset = address - self.base

           if offset == self.SR:
               # Update RXNE based on buffer
               if self.rx_buffer:
                   self.sr |= self.SR_RXNE
               else:
                   self.sr &= ~self.SR_RXNE
               return (self.sr, 0)

           elif offset == self.DR:
               # Reading DR gets RX data
               if self.rx_buffer:
                   data = self.rx_buffer.popleft()
                   self.sr &= ~self.SR_RXNE
                   return (data, 0)
               return (0, 0)

           elif offset == self.BRR:
               return (self.brr, 0)
           elif offset == self.CR1:
               return (self.cr1, 0)
           elif offset == self.CR2:
               return (self.cr2, 0)
           elif offset == self.CR3:
               return (self.cr3, 0)

           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           offset = address - self.base

           if offset == self.DR:
               # Writing DR sends TX data
               byte = value & 0xFF
               self.tx_buffer.append(byte)
               if self.on_tx:
                   self.on_tx(byte)
               # Keep TXE set (we can always accept more data)
               self.sr |= self.SR_TXE | self.SR_TC

           elif offset == self.SR:
               # Writing 0 to some bits clears them
               self.sr &= value

           elif offset == self.BRR:
               self.brr = value
           elif offset == self.CR1:
               self.cr1 = value
           elif offset == self.CR2:
               self.cr2 = value
           elif offset == self.CR3:
               self.cr3 = value

           return 0

       def inject_rx(self, data: bytes):
           """Inject data into RX buffer (external input)."""
           for byte in data:
               self.rx_buffer.append(byte)
           if self.rx_buffer:
               self.sr |= self.SR_RXNE

       def get_tx_data(self) -> bytes:
           """Get all transmitted data."""
           data = bytes(self.tx_buffer)
           self.tx_buffer.clear()
           return data

Using the UART stub:

.. code-block:: python

   usart2 = STM32USART(base=0x40004400, name='USART2')

   # Capture TX output
   output = []
   usart2.on_tx = lambda b: output.append(chr(b))

   # Simulate firmware sending "Hello"
   for c in "Hello\r\n":
       usart2.write(0x40004404, 4, ord(c))

   print("".join(output))  # "Hello\r\n"

   # Inject RX data for firmware to receive
   usart2.inject_rx(b"Response\r\n")
   # Firmware will see RXNE=1 and can read bytes from DR

Creating a Timer Stub
=====================

Timer peripherals often need special handling for ready/complete flags:

.. code-block:: python
   :caption: stm32_timer.py

   class STM32Timer:
       """STM32 Timer peripheral stub with auto-ready logic."""

       CR1  = 0x00
       CR2  = 0x04
       DIER = 0x0C
       SR   = 0x10
       CNT  = 0x24
       PSC  = 0x28
       ARR  = 0x2C

       def __init__(self, base: int, name: str = 'TIM'):
           self.base = base
           self.size = 0x400
           self.name = name

           self.cr1 = 0
           self.cr2 = 0
           self.dier = 0
           self.sr = 0
           self.cnt = 0
           self.psc = 0
           self.arr = 0xFFFF

           # Polling detection
           self._sr_read_count = 0
           self._max_polls = 5

       def read(self, address: int, size: int) -> tuple:
           offset = address - self.base

           if offset == self.SR:
               # Detect polling and auto-set update flag
               self._sr_read_count += 1
               if self._sr_read_count >= self._max_polls:
                   self.sr |= 0x01  # Set UIF (update interrupt flag)
               return (self.sr, 0)

           elif offset == self.CNT:
               # Increment counter on read (simulate passage of time)
               self.cnt = (self.cnt + 1) & 0xFFFF
               return (self.cnt, 0)

           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           offset = address - self.base

           if offset == self.SR:
               # Writing 0 clears flags
               self.sr &= value
               self._sr_read_count = 0  # Reset polling counter

           elif offset == self.CR1:
               self.cr1 = value
           elif offset == self.CNT:
               self.cnt = value
           elif offset == self.PSC:
               self.psc = value
           elif offset == self.ARR:
               self.arr = value

           return 0

Best Practices
==============

1. **Always Return Valid Status Flags**

   Firmware often polls status registers. Ensure flags like TXE, RXNE, READY
   are set appropriately to prevent infinite loops.

2. **Use Callbacks for External Events**

   Instead of hardcoding behavior, use callbacks to integrate with
   visualization (LEDs), logging (UART), or external systems.

3. **Document Register Behavior**

   Add comments explaining which datasheet section defines each register's
   behavior.

4. **Test Against Real Firmware**

   Validate stubs against actual firmware that runs on hardware. Compare
   MMIO traces to identify missing functionality.

Next Steps
==========

* :ref:`creating_ui_peripherals` - Add visual feedback
* :ref:`debugging_bootloops` - Fix common boot issues
* :ref:`api/slab_stm32` - Full STM32 peripheral API reference
