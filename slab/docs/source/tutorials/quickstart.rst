.. _quickstart:

====================
Quickstart Guide
====================

This guide walks you through setting up MCUemu SLAB and running your first
firmware emulation. By the end, you will have:

1. A working QEMU build with the ``slab-cortex-m`` machine
2. An STM32F405 firmware blinking an LED and printing to UART
3. An STM32H563 TrustZone firmware booting through secure world and jumping to
   non-secure application code

Prerequisites
=============

MCUemu requires a Linux host (tested on Debian 12 / Ubuntu 22.04+). The following
tools must be installed before proceeding.

Python 3.10+
-------------

MCUemu peripheral servers are written in Python. Version 3.10 is required for
``match`` statements and modern type hints.

.. code-block:: bash

   python3 --version
   # Should print: Python 3.10.x or later

ARM Toolchain
--------------

The ``arm-none-eabi-gcc`` cross-compiler is needed to build Cortex-M firmware
examples. Pre-built binaries in ``slab/examples/`` are provided, but you will
need the toolchain if you want to modify and rebuild them.

.. code-block:: bash

   # Debian / Ubuntu
   sudo apt install gcc-arm-none-eabi

   # Verify
   arm-none-eabi-gcc --version

QEMU Build Dependencies
------------------------

QEMU requires several system libraries for compilation. Install them first:

.. code-block:: bash

   # Debian / Ubuntu
   sudo apt install build-essential ninja-build pkg-config \
       libglib2.0-dev libpixman-1-dev libslirp-dev

Python Dependencies
--------------------

The peripheral emulation libraries have minimal dependencies. ``cryptography``
is needed for STM32 CRYP/HASH hardware emulation. ``pygame`` is optional, for
the debug dashboard GUI.

.. code-block:: bash

   pip install cryptography
   # Optional: pip install pygame

Installation
============

1. Clone the Repository
-----------------------

The repository includes QEMU source, peripheral libraries, firmware examples,
and SDK submodules.

.. code-block:: bash

   git clone --recursive https://github.com/GotoHack/slab-rehosting.git
   cd slab-rehosting

If you forgot ``--recursive``, initialize submodules manually:

.. code-block:: bash

   git submodule update --init --recursive

2. Build QEMU with slab-cortex-m
---------------------------------

The ``slab-cortex-m`` machine is compiled as part of the ``arm-softmmu`` target.
The build takes 2-5 minutes depending on your machine.

.. code-block:: bash

   mkdir -p build && cd build
   ../configure --target-list=arm-softmmu --enable-debug --disable-docs
   ninja
   cd ..

Verify the machine is available:

.. code-block:: bash

   ./build/qemu-system-arm -M help | grep slab

Expected output::

   slab-cortex-m        Slab Cortex-M - Generic ARM Cortex-M with peripheral export

3. Verify Python Packages
--------------------------

Check that the peripheral libraries can be imported. The ``PYTHONPATH`` must
point to ``slab/python`` since the packages are not pip-installed.

.. code-block:: bash

   PYTHONPATH=slab/python python3 -c "
   from slab_stm32 import STM32F405PeripheralSet, STM32H563PeripheralSet
   from slab_nrf import NRF52840PeripheralSet
   from slab_rp2040 import RP2040PeripheralSet
   print('All peripheral packages loaded successfully')
   "

Expected output::

   All peripheral packages loaded successfully


Example 1: STM32F405 Hello Blink (UART + LED)
===============================================

This example runs a bare-metal STM32F405 firmware that:

- Configures the clock tree (HSE -> PLL -> 168 MHz SYSCLK)
- Initializes GPIO PA13 as output (LED)
- Initializes USART2 at 115200 baud
- Prints "helloworld" then blinks the LED using TIM2 interrupts

The architecture is simple: QEMU emulates the CPU and memory, while a Python
server emulates all peripheral registers (RCC, GPIO, USART, TIM, FLASH, etc.)
over a TCP connection.

::

    +------------------+       TCP/5555       +--------------------+
    |  QEMU            |<-------------------->| Python Server      |
    |  (cortex-m4 CPU) |  MMIO read/write     | (STM32F4 periph.)  |
    |  Flash + SRAM    |  IRQ injection       | RCC, GPIO, USART,  |
    |                  |                      | TIM, FLASH, SPI... |
    +------------------+                      +--------------------+

You need **two terminals** open in the repository root.

Step 1: Start the Peripheral Server
-------------------------------------

In the first terminal, start the MCUemu peripheral server. This creates a
default STM32F4 peripheral set and listens for QEMU connections on port 5555.

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/python/slab_cortex_m/mcuemu_server.py \
       --port 5555

Expected output::

   ======================================================================
     MCUemu Peripheral Server
     Configuration: STM32F4xx
   ======================================================================

   [Listening] tcp://127.0.0.1:5555

   [Peripherals] 13 configured:
     RCC          @ 0x40023800 (no IRQ)
     PWR          @ 0x40007000 (no IRQ)
     FLASH        @ 0x40023C00 (no IRQ)
     GPIOA        @ 0x40020000 (no IRQ)
     ...
     TIM2         @ 0x40000000 (IRQ 28)
     USB_OTG_FS   @ 0x50000000 (IRQ 67)

Step 2: Run QEMU with Firmware
-------------------------------

In the second terminal, launch QEMU. The ``-M`` flag configures the machine:

- ``cpu-type=cortex-m4``: ARM Cortex-M4 core
- ``tcp-port=5555``: connect to the Python server on port 5555

.. code-block:: bash

   ./build/qemu-system-arm \
       -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555 \
       -kernel slab/examples/cortex-m/stm32/f405/demos/hello_blink_uart/build/HelloBlinkUart.bin \
       -nographic -monitor none

Step 3: Observe Results
------------------------

Back in the **server terminal**, you will see the firmware initializing peripherals:

- RCC clock configuration (HSE, PLL)
- GPIO pin configuration
- USART2 baud rate setup
- Timer TIM2 firing interrupts every 500ms (LED blink)

::

   21:35:33.415 [ INFO] MCUemu      : QEMU connected from ('127.0.0.1', 35446)
   21:35:33.937 [ INFO] P.TIM2      : Timer fired: IRQ 28
   21:35:34.437 [ INFO] P.TIM2      : Timer fired: IRQ 28
   ...

The firmware runs in a loop blinking the LED via timer interrupts.
Press **Ctrl+C** in both terminals to stop.

Step 4: Run as E2E Test
------------------------

Instead of manual two-terminal setup, you can use the E2E test suite which
automates the process and reports MMIO statistics:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/tests/e2e_firmware_test.py

Expected output (27 tests, all passing)::

   ========================================================================
     SLAB E2E Firmware Test Suite
     QEMU: .../build/qemu-system-arm
     Tests: 27 available, 0 skipped (no firmware)
   ========================================================================

     [1/27] STM32F405 HelloBlink [legacy]... PASS (72192 MMIO, 6.0s)
     [2/27] STM32F405 HelloBlink [board]... PASS (72140 MMIO, 6.0s)
     ...
     [27/27] STM32H563 TZ Secure [direct]... PASS (1600 MMIO, 10.0s)
              uart: [SECURE] STM32H563 TrustZone Boot
              uart: [SECURE] SAU configured, GTZC initialized
              uart: [SECURE] IWDG watchdog enabled
              uart: [SECURE] USART1 debug ready (115200 8N1)
              uart: [SECURE] Validating NS image...

   ========================================================================
     RESULTS: 27 passed, 0 failed / 27 tested
   ========================================================================


Example 2: STM32H563 TrustZone Dual-Image Boot
================================================

This example demonstrates a more advanced scenario: an STM32H563 running
ARMv8-M TrustZone with two firmware images:

- **Secure firmware** (``secure_fw.bin``, 256KB at 0x0C000000): configures SAU,
  GTZC, MPCBB security domains, enables IWDG watchdog, initializes USART1 for
  debug output, validates the non-secure image, then jumps to it.
- **Non-Secure firmware** (``nonsecure_fw.bin``, 58KB at 0x08042000): initializes
  USB CDC-ACM using ThreadX/USBX RTOS, enumerates as a virtual COM port.

The memory layout differs significantly from STM32F4:

::

   Secure Flash    0x0C000000 +-----------+ (256KB)
                              |secure_fw  |
                              +-----------+
   NS Flash        0x08040000 +-----------+ (1792KB)
                   0x08042000 |nonsecure  |
                              |_fw        |
                              +-----------+
   Secure SRAM     0x30000000 +-----------+ (320KB)
                              |           |
                              +-----------+
   Peripherals     0x40000000 -- 0x5FFFFFFF (NS + Secure alias)

Step 1: Understand the QEMU Properties
----------------------------------------

The ``slab-cortex-m`` machine exposes several properties to configure the
memory layout. For H563 TrustZone, we need:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Property
     - Value
     - Purpose
   * - ``cpu-type``
     - ``cortex-m33``
     - ARMv8-M core with TrustZone support
   * - ``flash-base``
     - ``0x0C000000``
     - Secure flash alias (STM32H5 specific)
   * - ``sram-base``
     - ``0x30000000``
     - Secure SRAM (SRAM3 on H5)
   * - ``sram-size``
     - ``0x50000``
     - 320KB SRAM
   * - ``trustzone``
     - ``on``
     - Enable ARMv8-M Security Extension
   * - ``sysclk-hz``
     - ``250000000``
     - H563 PLL1 at 250 MHz (prevents SysTick storm)
   * - ``ns-flash-base``
     - ``0x08040000``
     - Non-secure flash ROM region base
   * - ``ns-flash-size``
     - ``0x1C0000``
     - Non-secure flash size (1792KB)

The non-secure firmware binary is loaded into the NS flash region using
QEMU's ``-device loader`` mechanism.

Step 2: Start the Peripheral Server (Board Mode)
--------------------------------------------------

Board mode uses a YAML configuration file that bundles MCU type, clock speed,
memory layout, and external device wiring. The board YAML for H563 TZ is
``slab/boards/stm32h563_tz.yaml``.

In the first terminal:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/python/slab_cortex_m/mcuemu_server.py \
       --port 5555 --board slab/boards/stm32h563_tz.yaml

Expected output::

   [Board] STM32H563_TZ (STM32H563)
   [Listening] tcp://127.0.0.1:5555
   [Peripherals] 62

Step 3: Run QEMU with Dual-Image Firmware
-------------------------------------------

In the second terminal:

.. code-block:: bash

   ./build/qemu-system-arm \
       -M slab-cortex-m,cpu-type=cortex-m33,tcp-port=5555,flash-base=0x0C000000,sram-base=0x30000000,sram-size=0x50000,trustzone=on,sysclk-hz=250000000,ns-flash-base=0x08040000,ns-flash-size=0x1C0000 \
       -kernel slab/examples/cortex-m/stm32/h563/stm32h563_tz_cdc/build/secure_fw.bin \
       -device loader,file=slab/examples/cortex-m/stm32/h563/stm32h563_tz_cdc/build/nonsecure_fw.bin,addr=0x08042000,force-raw=on \
       -nographic -monitor none

The ``-kernel`` loads the secure firmware into the flash at 0x0C000000.
The ``-device loader`` loads the non-secure firmware at 0x08042000 into the
NS flash ROM region we declared with ``ns-flash-base``.

Step 4: Observe the TrustZone Boot
------------------------------------

In the **server terminal**, the MMIO trace shows the secure firmware configuring
TrustZone hardware:

1. **SAU** (Security Attribution Unit): marks memory regions as secure/non-secure
2. **GTZC** (Global TrustZone Controller): configures peripheral security
3. **MPCBB** (Memory Protection Controller): sets SRAM block security
4. **IWDG** (Watchdog): enabled in secure world
5. **USART1**: initialized for debug output at 115200 baud
6. **NS image validation**: reads vector table at 0x08042000, verifies stack
   pointer and reset handler, then jumps

The firmware produces UART output via USART1 showing each stage. After about
10 seconds (timeout), the firmware will have processed ~1600 MMIO operations.

Step 5: Using the Run Script
------------------------------

For convenience, a self-contained run script handles both server and QEMU:

.. code-block:: bash

   PYTHONPATH=slab/python python3 \
       slab/examples/cortex-m/stm32/h563/run_h563_tz.py --timeout 15

This script creates the peripheral server, launches QEMU with the correct
memory layout and TrustZone flags, loads both firmware images, and reports
MMIO statistics when done.


Running the Full Test Suite
============================

The automated E2E test suite runs 27 firmware tests covering multiple MCU
families (STM32F4, F439, L433, H563, nRF52840, RP2040), test modes (legacy,
board, direct), and configurations:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/tests/e2e_firmware_test.py

All 27 tests should pass. Each test:

1. Creates a Python peripheral server on a random port
2. Launches QEMU with the firmware and correct machine properties
3. Waits for the firmware to execute (5-10 seconds)
4. Counts MMIO operations and captures UART output
5. Reports PASS if the MMIO count exceeds the minimum threshold

Unit tests for the peripheral libraries (439 tests) can be run with pytest:

.. code-block:: bash

   PYTHONPATH=slab/python pytest slab/tests/ -q

Expected output::

   439 passed in ~7s


Architecture Overview
=====================

MCUemu uses a modular architecture separating CPU emulation (QEMU) from
peripheral behavior (Python):

.. figure:: ../images/mcuemu_architecture.png
   :alt: MCUemu Architecture Diagram
   :align: center
   :width: 100%

   MCUemu Architecture: QEMU handles CPU/memory, Python handles peripherals

**Key Components:**

1. **QEMU slab-cortex-m Machine**
   - Emulates ARM Cortex-M CPU cores (M0 to M85)
   - Provides Flash, SRAM, and optional NS Flash memory regions
   - Forwards all peripheral MMIO accesses via TCP or shared memory

2. **Peripheral Proxy**
   - Binary protocol for MMIO read/write operations
   - Supports TrustZone secure/non-secure access attribution
   - ~3us latency with shared memory, ~45us with TCP

3. **Python Peripheral Server**
   - Implements peripheral register behavior
   - Supports callbacks for GPIO, UART, SPI, I2C, USB, Timers
   - 17 MCU families with 50+ peripheral types

Next Steps
==========

* :ref:`first_emulation` - Write and emulate your own firmware from scratch
* :ref:`peripheral_basics` - Understand MMIO register access patterns
* :ref:`stubbing_peripherals` - Create custom peripheral stubs for unknown hardware
* :ref:`creating_boards` - Define board configurations with YAML
* :ref:`mmio_tracing` - Capture and analyze MMIO activity
* :ref:`trustzone_emulation` - Deep dive into TrustZone emulation
