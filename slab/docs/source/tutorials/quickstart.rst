.. _quickstart:

====================
Quickstart Guide
====================

This guide walks you through setting up MCUemu and running your first firmware emulation.

Prerequisites
=============

* Python 3.10 or later
* ``arm-none-eabi-gcc`` toolchain for firmware compilation
* QEMU source code (included in repository)
* ``pygame`` for visualization (optional)

.. code-block:: bash

   # Check Python version
   python3 --version  # Should be 3.10+

   # Install ARM toolchain (Debian/Ubuntu)
   sudo apt install gcc-arm-none-eabi

   # Install Python dependencies
   pip install cryptography pygame

Installation
============

1. Clone the Repository
-----------------------

.. code-block:: bash

   git clone --recursive https://github.com/GotoHack/slab-rehosting.git
   cd slab-rehosting

2. Build QEMU with slab-cortex-m
--------------------------------

.. code-block:: bash

   mkdir -p build && cd build
   ../configure --target-list=arm-softmmu --enable-debug --disable-docs
   ninja
   cd ..

   # Verify the machine is available
   ./build/qemu-system-arm -M help | grep slab
   # Output: slab-cortex-m   Slab Cortex-M - Generic ARM Cortex-M with peripheral export

3. Verify Python Packages
-------------------------

.. code-block:: python

   import sys
   sys.path.insert(0, "slab/python")

   from slab_stm32 import STM32F439PeripheralSet
   from slab_nrf import NRF52840PeripheralSet
   from slab_rp2040 import RP2040PeripheralSet

   print("MCUemu packages loaded successfully!")

Your First Emulation
====================

Let's run a simple "Hello World" firmware that blinks an LED and outputs to UART.

First, build the example firmware:

.. code-block:: bash

   cd slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart
   make clean && make
   cd -

Step 1: Start the Peripheral Server
-----------------------------------

In one terminal, start the Python peripheral server:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/python/slab_cortex_m/mcuemu_server.py --port 5555

You should see::

   ======================================================================
     MCUemu Peripheral Server
     Configuration: STM32F4xx
   ======================================================================

   [Listening] tcp://127.0.0.1:5555

   [Peripherals] 12 configured:
     GPIOA        @ 0x40020000 (no IRQ)
     ...
     USART2       @ 0x40004400 (IRQ 38)

Step 2: Run QEMU with Firmware
------------------------------

In another terminal, run QEMU with the test firmware:

.. code-block:: bash

   ./build/qemu-system-arm \
       -M slab-cortex-m \
       -global slab-cortex-m.cpu-type=cortex-m4 \
       -global slab-cortex-m.tcp-port=5555 \
       -kernel slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin \
       -nographic

The peripheral server terminal should show MMIO activity as the firmware
initializes clocks, configures GPIO, and starts blinking.

Step 3: View Results
--------------------

The firmware outputs "helloworld" via USART2 and blinks an LED on PA13 using TIM2.
The test passes after 10 LED toggles (~5 seconds).

Architecture Overview
=====================

MCUemu uses a modular architecture separating CPU emulation (QEMU) from peripheral behavior (Python):

.. figure:: ../images/mcuemu_architecture.png
   :alt: MCUemu Architecture Diagram
   :align: center
   :width: 100%

   MCUemu Architecture: QEMU handles CPU/memory, Python handles peripherals

**Key Components:**

1. **QEMU slab-cortex-m Machine**
   - Emulates ARM Cortex-M CPU cores (M0 to M85)
   - Provides Flash and SRAM memory
   - Forwards all peripheral accesses via TCP or SHM

2. **Peripheral Proxy**
   - Binary protocol for MMIO read/write operations
   - ~3μs latency with shared memory, ~45μs with TCP

3. **Python Peripheral Server**
   - Implements peripheral register behavior
   - Supports callbacks for GPIO, UART, SPI, etc.
   - Extensible with custom peripheral models

Next Steps
==========

* :ref:`first_emulation` - Write and emulate your own firmware
* :ref:`peripheral_basics` - Understand how peripherals work
* :ref:`stubbing_peripherals` - Create custom peripheral stubs
