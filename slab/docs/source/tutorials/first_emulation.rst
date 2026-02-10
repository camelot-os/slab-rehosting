.. _first_emulation:

==============================
Emulating Firmware from Scratch
==============================

This tutorial walks you through emulating a real STM32 firmware from scratch,
including SVD parsing, peripheral setup, and debugging boot loops.

Overview
========

We'll emulate a STM32F405 firmware that:

1. Configures the system clock (RCC)
2. Initializes GPIO for LED output
3. Configures USART2 for serial output
4. Runs a blink + hello world loop

.. figure:: ../images/emulation_workflow.png
   :alt: Emulation Workflow
   :align: center
   :width: 90%

   Workflow: SVD → Peripheral Stubs → QEMU Emulation → Debug

Step 1: Analyze the Target MCU
==============================

First, identify the target MCU and obtain its SVD (System View Description) file:

.. code-block:: bash

   # SVD files are in the svd/data directory
   ls svd/data/STMicro/STM32F4*.svd

   # STM32F405.svd contains register definitions for our target

Parse the SVD to understand the peripheral layout:

.. code-block:: python

   from svd_parser import SVDParser

   parser = SVDParser()
   device = parser.parse("svd/data/STMicro/STM32F405.svd")

   print(f"Device: {device.name}")
   print(f"Peripherals: {len(device.peripherals)}")

   # List key peripherals
   for p in device.peripherals:
       if p.name in ['RCC', 'GPIOA', 'USART2', 'TIM2']:
           print(f"  {p.name} @ 0x{p.base_address:08X}")

Output::

   Device: STM32F405
   Peripherals: 91
     RCC @ 0x40023800
     GPIOA @ 0x40020000
     USART2 @ 0x40004400
     TIM2 @ 0x40000000

Step 2: Create the Peripheral Set
=================================

MCUemu provides pre-built peripheral sets, but let's understand how they work:

.. code-block:: python

   from slab_cortex_m import SlabPeripheralServer

   class STM32F405PeripheralSet:
       """Peripheral set for STM32F405."""

       def __init__(self):
           # Memory map ranges
           self.ranges = [
               (0x40000000, 0x5FFFFFFF),  # Peripheral region
           ]

           # Initialize peripherals
           self.peripherals = {}
           self._init_rcc()
           self._init_gpio()
           self._init_usart()

       def _init_rcc(self):
           """Initialize Reset and Clock Control."""
           from slab_stm32.stm32_rcc import STM32F4RCC
           self.rcc = STM32F4RCC(base=0x40023800)
           self.peripherals['RCC'] = self.rcc

       def _init_gpio(self):
           """Initialize GPIO ports."""
           from slab_stm32.stm32_gpio import STM32GPIO
           self.gpio = {}
           for port_idx, port_name in enumerate('ABCDEFGHI'):
               base = 0x40020000 + port_idx * 0x400
               gpio = STM32GPIO(base=base, port_name=port_name)
               self.gpio[port_name] = gpio
               self.peripherals[f'GPIO{port_name}'] = gpio

       def _init_usart(self):
           """Initialize USARTs."""
           from slab_stm32.stm32_usart import STM32USART
           self.usart2 = STM32USART(base=0x40004400, name='USART2')
           self.peripherals['USART2'] = self.usart2

       def read(self, address: int, size: int) -> tuple:
           """Handle MMIO read."""
           for periph in self.peripherals.values():
               if periph.contains(address):
                   return periph.read(address, size)
           return (0, 0)  # Default: return 0

       def write(self, address: int, size: int, value: int) -> int:
           """Handle MMIO write."""
           for periph in self.peripherals.values():
               if periph.contains(address):
                   return periph.write(address, size, value)
           return 0  # OK

Step 3: Debug Boot Loops with MMIO Tracing
==========================================

When firmware gets stuck in a boot loop, trace MMIO accesses to identify the cause:

.. code-block:: python

   import logging
   logging.basicConfig(level=logging.DEBUG)

   # Run with tracing enabled
   ps = STM32F405PeripheralSet()
   ps.rcc.trace = True  # Enable RCC tracing

Boot loop symptoms and fixes:

.. list-table:: Common Boot Loop Causes
   :widths: 30 40 30
   :header-rows: 1

   * - Symptom
     - Root Cause
     - Fix
   * - Stuck polling ``RCC.CR.HSERDY``
     - HSE oscillator not ready
     - Set ``HSERDY=1`` in RCC.CR
   * - Stuck polling ``RCC.CR.PLLRDY``
     - PLL not locked
     - Set ``PLLRDY=1`` in RCC.CR
   * - Stuck polling ``RCC.CFGR.SWS``
     - Clock switch not complete
     - Set ``SWS`` to match ``SW``
   * - Stuck in ``USART.SR.TXE`` loop
     - TX buffer never empty
     - Always return ``TXE=1``

Example: Fixing an HSE Boot Loop
--------------------------------

Observe the MMIO trace::

   [RCC] READ  0x40023800 CR = 0x00000001  # HSI enabled
   [RCC] WRITE 0x40023800 CR = 0x00010001  # Enable HSE
   [RCC] READ  0x40023800 CR = 0x00010001  # Poll HSERDY...
   [RCC] READ  0x40023800 CR = 0x00010001  # Still waiting
   [RCC] READ  0x40023800 CR = 0x00010001  # Infinite loop!

The firmware is waiting for ``HSERDY`` (bit 17) to become 1. Fix it:

.. code-block:: python

   class STM32F4RCC:
       def read(self, address: int, size: int):
           offset = address - self.base
           if offset == 0x00:  # CR register
               # Auto-set ready bits when oscillators are enabled
               if self.cr & (1 << 16):  # HSEON
                   self.cr |= (1 << 17)  # Set HSERDY
               if self.cr & (1 << 24):  # PLLON
                   self.cr |= (1 << 25)  # Set PLLRDY
               return (self.cr, 0)

Step 4: Write Minimal Firmware
==============================

Create a simple test firmware that exercises the peripherals:

.. code-block:: c
   :caption: main.c - Minimal STM32F405 Firmware

   #include <stdint.h>

   // Memory-mapped registers
   #define RCC_BASE      0x40023800
   #define GPIOA_BASE    0x40020000
   #define USART2_BASE   0x40004400

   #define RCC_AHB1ENR   (*(volatile uint32_t*)(RCC_BASE + 0x30))
   #define RCC_APB1ENR   (*(volatile uint32_t*)(RCC_BASE + 0x40))

   #define GPIOA_MODER   (*(volatile uint32_t*)(GPIOA_BASE + 0x00))
   #define GPIOA_ODR     (*(volatile uint32_t*)(GPIOA_BASE + 0x14))

   #define USART2_SR     (*(volatile uint32_t*)(USART2_BASE + 0x00))
   #define USART2_DR     (*(volatile uint32_t*)(USART2_BASE + 0x04))

   void uart_putc(char c) {
       while (!(USART2_SR & (1 << 7)));  // Wait for TXE
       USART2_DR = c;
   }

   void uart_puts(const char *s) {
       while (*s) uart_putc(*s++);
   }

   int main(void) {
       // Enable GPIOA and USART2 clocks
       RCC_AHB1ENR |= (1 << 0);   // GPIOAEN
       RCC_APB1ENR |= (1 << 17);  // USART2EN

       // Configure PA5 as output (LED)
       GPIOA_MODER |= (1 << 10);

       // Print hello
       uart_puts("Hello from STM32F405!\r\n");

       // Blink LED
       for (int i = 0; i < 10; i++) {
           GPIOA_ODR ^= (1 << 5);
           for (volatile int j = 0; j < 100000; j++);
       }

       while (1);
   }

Compile it:

.. code-block:: bash

   arm-none-eabi-gcc -mcpu=cortex-m4 -mthumb -nostartfiles \
       -T linker.ld -o firmware.elf main.c
   arm-none-eabi-objcopy -O binary firmware.elf firmware.bin

Step 5: Run the Emulation
=========================

Start the peripheral server:

.. code-block:: bash

   PYTHONPATH=slab/python python3 -c "
   from slab_stm32 import STM32F4xxPeripheralSet
   from slab_cortex_m.mcuemu_server import MCUemuServer
   import asyncio

   server = MCUemuServer(port=5555)
   server.peripheral_set = STM32F4xxPeripheralSet()
   server.create_peripherals()
   asyncio.run(server.start())
   "

Start QEMU:

.. code-block:: bash

   ./build/qemu-system-arm \
       -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555 \
       -kernel firmware.bin \
       -nographic

Expected output::

   Hello from STM32F405!
   [GPIO] PA5 = 1 (LED ON)
   [GPIO] PA5 = 0 (LED OFF)
   ...

Complete Example Script
=======================

Here's a self-contained script that runs the full emulation:

.. code-block:: python
   :caption: run_stm32f405_test.py

   #!/usr/bin/env python3
   """STM32F405 emulation test."""

   import asyncio
   import subprocess
   import struct
   import sys
   sys.path.insert(0, "slab/python")

   from slab_stm32 import STM32F4xxPeripheralSet

   QEMU_BIN = "build/qemu-system-arm"
   FIRMWARE = "firmware.bin"
   TCP_PORT = 5555

   async def handle_qemu(reader, writer, ps):
       """Handle QEMU peripheral proxy."""
       ops = 0
       try:
           while True:
               cmd_data = await reader.read(1)
               if not cmd_data:
                   break
               cmd = cmd_data[0]

               if cmd in (0x52, 0x53):  # Read ('R' or 'S')
                   data = await reader.readexactly(13)
                   addr, sz = struct.unpack('<II', data[:8])
                   secure = (cmd == 0x53) or (data[8] == 1)
                   val, status = ps.read(addr, sz)
                   writer.write(struct.pack('<IB', val, status))
               elif cmd in (0x57, 0x54):  # Write ('W' or 'T')
                   data = await reader.readexactly(17)
                   addr, sz, val = struct.unpack('<III', data[:12])
                   secure = (cmd == 0x54) or (data[12] == 1)
                   status = ps.write(addr, sz, val)
                   writer.write(struct.pack('<IB', 0, status))

               ops += 1
               await writer.drain()
       finally:
           print(f"Total operations: {ops}")

   async def main():
       ps = STM32F4xxPeripheralSet()

       server = await asyncio.start_server(
           lambda r, w: handle_qemu(r, w, ps),
           "127.0.0.1", TCP_PORT
       )

       proc = subprocess.Popen([
           QEMU_BIN,
           "-M", f"slab-cortex-m,cpu-type=cortex-m4,tcp-port={TCP_PORT}",
           "-kernel", FIRMWARE,
           "-nographic",
       ])

       await asyncio.sleep(5)  # Run for 5 seconds
       proc.terminate()
       server.close()

   if __name__ == '__main__':
       asyncio.run(main())

Next Steps
==========

* :ref:`stubbing_peripherals` - Create custom peripheral stubs
* :ref:`debugging_bootloops` - Advanced boot loop debugging
* :ref:`trustzone_emulation` - Emulate TrustZone firmware
