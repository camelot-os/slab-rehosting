.. _quickstart:

====================
Quickstart Guide
====================

This guide walks you through setting up MCUemu and running your first firmware emulation.

Prerequisites
=============

* Python 3.10 or later
* ``arm-none-eabi-gcc`` toolchain for firmware compilation
* QEMU source code (provided as submodule)
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

   git clone --recursive https://github.com/twistedwires/mcuemu.git
   cd mcuemu

2. Build QEMU with slab-cortex-m
--------------------------------

.. code-block:: bash

   cd qemu
   mkdir -p build && cd build
   ../configure --target-list=arm-softmmu --enable-debug --disable-docs
   ninja

   # Verify the machine is available
   ./qemu-system-arm -M help | grep slab
   # Output: slab-cortex-m   SLAB Cortex-M - Generic MCU with Peripheral Proxy

3. Verify Python Packages
-------------------------

.. code-block:: python

   import sys
   sys.path.insert(0, "python")

   from slab_stm32 import STM32F439PeripheralSet
   from slab_nrf import NRF52840PeripheralSet
   from slab_rp2040 import RP2040PeripheralSet

   print("MCUemu packages loaded successfully!")

Your First Emulation
====================

Let's run a simple "Hello World" firmware that blinks an LED and outputs to UART.

Step 1: Start the Peripheral Server
-----------------------------------

In one terminal, start the Python peripheral server:

.. code-block:: bash

   cd mcuemu
   PYTHONPATH=python python3 python/slab_cortex_m/mcuemu_server.py --port 5000

You should see::

   [*] MCUemu peripheral server starting on port 5000
   [*] Loaded STM32F4 peripheral set (42 peripherals)
   [*] Waiting for QEMU connection...

Step 2: Run QEMU with Firmware
------------------------------

In another terminal, run QEMU with the test firmware:

.. code-block:: bash

   ./qemu/build/qemu-system-arm \
       -M slab-cortex-m \
       -cpu cortex-m4 \
       -kernel tests/firmware/build/test_basic.bin \
       -nographic

The peripheral server should show MMIO activity::

   [QEMU] Connected
   [RCC]  0x40023800 READ  CR = 0x00000083
   [GPIO] 0x40020014 WRITE ODR = 0x00002000  # LED ON
   [GPIO] 0x40020014 WRITE ODR = 0x00000000  # LED OFF

Step 3: View Results
--------------------

The firmware outputs "helloworld" via UART and blinks an LED 10 times.
After completion, the peripheral server displays statistics::

   [*] Emulation complete
   [*] Total MMIO operations: 1,247
   [*] Elapsed time: 0.8s

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
