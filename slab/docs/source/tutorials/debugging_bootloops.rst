.. _debugging_bootloops:

======================
Debugging Boot Loops
======================

Boot loops are the most common issue when emulating firmware. This tutorial
teaches you to diagnose and fix them using MMIO tracing and PC analysis.

Understanding Boot Loops
========================

A boot loop occurs when firmware gets stuck in an infinite loop, typically
waiting for hardware that never responds:

.. code-block:: c

   // Common boot loop: waiting for oscillator ready
   RCC->CR |= RCC_CR_HSEON;              // Enable HSE
   while (!(RCC->CR & RCC_CR_HSERDY));   // Wait forever!

.. figure:: ../images/bootloop_detection.png
   :alt: Boot Loop Detection
   :align: center
   :width: 90%

   Boot Loop Detection: Trace MMIO + PC to identify stuck loops

Step 1: Enable MMIO Tracing
===========================

Add tracing to your peripheral server:

.. code-block:: python

   import logging
   logging.basicConfig(
       level=logging.DEBUG,
       format='%(name)-10s %(message)s'
   )

   class TracingPeripheralSet:
       def read(self, address: int, size: int) -> tuple:
           result = self._do_read(address, size)
           logging.debug(f"READ  0x{address:08X} = 0x{result[0]:08X}")
           return result

       def write(self, address: int, size: int, value: int) -> int:
           logging.debug(f"WRITE 0x{address:08X} = 0x{value:08X}")
           return self._do_write(address, size, value)

Running with tracing shows the loop:

.. code-block:: text

   RCC        READ  0x40023800 = 0x00000001  # CR
   RCC        WRITE 0x40023800 = 0x00010001  # Enable HSE
   RCC        READ  0x40023800 = 0x00010001  # Poll HSERDY
   RCC        READ  0x40023800 = 0x00010001  # Still waiting...
   RCC        READ  0x40023800 = 0x00010001  # Infinite loop!

Step 2: Identify the Stuck Register
====================================

Analyze the trace to find which register is being polled:

.. code-block:: python

   class PollingDetector:
       """Detect infinite polling loops."""

       def __init__(self, threshold: int = 10):
           self.threshold = threshold
           self.read_counts = {}

       def record_read(self, address: int, value: int):
           key = (address, value)
           self.read_counts[key] = self.read_counts.get(key, 0) + 1

           if self.read_counts[key] == self.threshold:
               print(f"[POLL] Detected polling at 0x{address:08X} "
                     f"(value=0x{value:08X}, reads={self.threshold})")
               return True
           return False

Output::

   [POLL] Detected polling at 0x40023800 (value=0x00010001, reads=10)

Step 3: Decode the Register
===========================

Use SVD to understand the register bits:

.. code-block:: python

   from svd_parser import SVDParser

   parser = SVDParser()
   device = parser.parse("svd/data/STMicro/STM32F405.svd")

   # Find RCC peripheral
   rcc = next(p for p in device.peripherals if p.name == 'RCC')
   cr = next(r for r in rcc.registers if r.name == 'CR')

   print(f"RCC_CR @ 0x{rcc.base_address + cr.address_offset:08X}")
   for field in cr.fields:
       print(f"  [{field.bit_offset:2d}] {field.name}: {field.description}")

Output::

   RCC_CR @ 0x40023800
     [ 0] HSION: Internal high-speed clock enable
     [ 1] HSIRDY: Internal high-speed clock ready (read-only)
     [16] HSEON: HSE clock enable
     [17] HSERDY: HSE clock ready (read-only)
     [24] PLLON: Main PLL enable
     [25] PLLRDY: Main PLL ready (read-only)

The firmware is waiting for bit 17 (HSERDY) = 1.

Step 4: Fix the Peripheral Stub
===============================

Modify the RCC peripheral to auto-set ready flags:

.. code-block:: python

   class STM32F4RCC:
       """RCC with auto-ready logic."""

       CR = 0x00
       CFGR = 0x08

       # CR bits
       HSION = (1 << 0)
       HSIRDY = (1 << 1)
       HSEON = (1 << 16)
       HSERDY = (1 << 17)
       PLLON = (1 << 24)
       PLLRDY = (1 << 25)

       def __init__(self, base: int = 0x40023800):
           self.base = base
           self.cr = self.HSION | self.HSIRDY  # HSI enabled and ready

       def read(self, address: int, size: int) -> tuple:
           offset = address - self.base

           if offset == self.CR:
               # Auto-set ready bits when oscillators are enabled
               self._update_ready_flags()
               return (self.cr, 0)

           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           offset = address - self.base

           if offset == self.CR:
               self.cr = value
               self._update_ready_flags()

           return 0

       def _update_ready_flags(self):
           """Auto-set ready flags when oscillators are enabled."""
           if self.cr & self.HSEON:
               self.cr |= self.HSERDY

           if self.cr & self.PLLON:
               self.cr |= self.PLLRDY

Common Boot Loop Causes and Fixes
=================================

.. list-table::
   :widths: 25 35 40
   :header-rows: 1

   * - Symptom
     - Cause
     - Fix
   * - Polling ``RCC.CR.HSIRDY``
     - HSI not ready
     - Init ``CR = HSION | HSIRDY``
   * - Polling ``RCC.CR.HSERDY``
     - HSE crystal not oscillating
     - Set ``HSERDY`` when ``HSEON`` set
   * - Polling ``RCC.CR.PLLRDY``
     - PLL not locked
     - Set ``PLLRDY`` when ``PLLON`` set
   * - Polling ``RCC.CFGR.SWS``
     - Clock switch not complete
     - Set ``SWS = SW`` after write
   * - Polling ``FLASH.SR.BSY``
     - Flash operation not complete
     - Clear ``BSY`` immediately
   * - Polling ``USART.SR.TXE``
     - TX buffer never empty
     - Always return ``TXE = 1``
   * - Polling ``SPI.SR.TXE``
     - SPI TX buffer full
     - Always return ``TXE = 1``
   * - Polling ``I2C.SR1.SB``
     - Start condition not sent
     - Set ``SB`` after START write
   * - Polling ``ADC.SR.EOC``
     - Conversion not complete
     - Set ``EOC`` after ADON

Advanced: Using PC Tracing
==========================

When MMIO tracing isn't enough, add PC (Program Counter) tracing:

.. code-block:: c

   // In QEMU, enable PC tracing via -d cpu
   // or use QEMU's -icount option for deterministic execution

Modify your peripheral server to request PC from QEMU:

.. code-block:: python

   # Extended protocol: request PC with each MMIO access
   async def handle_qemu(reader, writer, ps):
       while True:
           hdr = await reader.read(13)  # Extended: includes PC
           if len(hdr) < 13:
               break

           cmd = hdr[0]
           addr = int.from_bytes(hdr[1:5], "little")
           sz = int.from_bytes(hdr[5:9], "little")
           pc = int.from_bytes(hdr[9:13], "little")

           # Log with PC
           logging.debug(f"PC=0x{pc:08X} READ 0x{addr:08X}")

           # Cross-reference with firmware symbols
           symbol = lookup_symbol(pc)  # From ELF debug info
           if symbol:
               logging.debug(f"  → {symbol}")

Output with PC::

   PC=0x08001234 READ 0x40023800  → SystemClock_Config
   PC=0x08001238 READ 0x40023800  → SystemClock_Config
   PC=0x0800123C READ 0x40023800  → SystemClock_Config

Using GDB for Analysis
======================

Attach GDB to QEMU for interactive debugging:

.. code-block:: bash

   # Start QEMU with GDB server
   qemu-system-arm -M slab-cortex-m -kernel firmware.bin -s -S

   # Connect GDB
   arm-none-eabi-gdb firmware.elf
   (gdb) target remote :1234
   (gdb) break main
   (gdb) continue

   # When stuck, interrupt and examine
   (gdb) Ctrl+C
   (gdb) bt          # Backtrace
   (gdb) info reg    # Registers
   (gdb) x/10i $pc   # Disassemble

Systematic Debugging Process
============================

Follow this process for any boot loop:

1. **Enable MMIO tracing** - See which registers are accessed
2. **Identify repeated reads** - Find the polling loop
3. **Decode register bits** - Understand what firmware expects
4. **Check datasheet** - Understand when bits should change
5. **Modify peripheral** - Auto-set flags as hardware would
6. **Test again** - Verify firmware proceeds
7. **Repeat** - Next boot loop (if any)

Example: Full RCC Fix
=====================

Complete RCC implementation that handles all common STM32F4 boot loops:

.. code-block:: python
   :caption: stm32_rcc_complete.py

   class STM32F4RCC:
       """Complete STM32F4 RCC with auto-ready logic."""

       # Registers
       CR = 0x00
       PLLCFGR = 0x04
       CFGR = 0x08
       CIR = 0x0C
       AHB1RSTR = 0x10
       AHB1ENR = 0x30
       APB1ENR = 0x40
       APB2ENR = 0x44

       def __init__(self, base: int = 0x40023800):
           self.base = base
           self.size = 0x400

           # Initialize with HSI enabled and ready
           self.cr = 0x00000083      # HSIRDY + HSION
           self.pllcfgr = 0x24003010
           self.cfgr = 0x00000000
           self.ahb1enr = 0x00000000
           self.apb1enr = 0x00000000
           self.apb2enr = 0x00000000

           # Polling detection
           self._poll_count = 0

       def read(self, address: int, size: int) -> tuple:
           offset = address - self.base

           if offset == self.CR:
               self._update_cr_ready()
               return (self.cr, 0)
           elif offset == self.CFGR:
               self._update_cfgr_sws()
               return (self.cfgr, 0)
           elif offset == self.AHB1ENR:
               return (self.ahb1enr, 0)
           elif offset == self.APB1ENR:
               return (self.apb1enr, 0)
           elif offset == self.APB2ENR:
               return (self.apb2enr, 0)

           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           offset = address - self.base

           if offset == self.CR:
               self.cr = value
               self._update_cr_ready()
           elif offset == self.PLLCFGR:
               self.pllcfgr = value
           elif offset == self.CFGR:
               self.cfgr = value
               self._update_cfgr_sws()
           elif offset == self.AHB1ENR:
               self.ahb1enr = value
           elif offset == self.APB1ENR:
               self.apb1enr = value
           elif offset == self.APB2ENR:
               self.apb2enr = value

           return 0

       def _update_cr_ready(self):
           """Set ready flags for enabled oscillators."""
           # HSIRDY follows HSION
           if self.cr & (1 << 0):
               self.cr |= (1 << 1)

           # HSERDY follows HSEON
           if self.cr & (1 << 16):
               self.cr |= (1 << 17)

           # PLLRDY follows PLLON
           if self.cr & (1 << 24):
               self.cr |= (1 << 25)

           # PLLI2SRDY follows PLLI2SON
           if self.cr & (1 << 26):
               self.cr |= (1 << 27)

       def _update_cfgr_sws(self):
           """Set SWS to match SW (clock switch complete)."""
           sw = self.cfgr & 0x3
           self.cfgr = (self.cfgr & ~0xC) | (sw << 2)

Next Steps
==========

* :ref:`trustzone_emulation` - Debug TrustZone boot sequences
* :ref:`creating_ui_peripherals` - Visualize boot progress
* :ref:`api/slab_stm32` - RCC and other peripheral APIs
