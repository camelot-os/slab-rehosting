.. _hardware_in_the_loop:

================================
Hardware-in-the-Loop (HIL) Testing
================================

This tutorial explains how to forward specific peripheral accesses from
emulated firmware to real hardware using SLAB's Hardware-in-the-Loop
infrastructure. This enables testing firmware against actual silicon
while keeping the rest of the system emulated.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>

Copyright (C) 2026 Twisted Wires Security Lab


Introduction: Why Hardware-in-the-Loop?
========================================

In traditional rehosting, all peripherals are emulated in software. This
works well for standard peripherals (GPIO, UART, SPI), but some use cases
require **real hardware**:

- **Cryptographic accelerators**: Verifying that emulated AES/HASH output
  matches real silicon (CRYP, HASH peripherals)
- **Analog peripherals**: ADC/DAC behavior that is difficult to model
- **Timing-sensitive protocols**: USB PHY, high-speed SPI with precise timing
- **Security research**: Fault injection, glitching, and side-channel analysis
  where real silicon behavior matters

SLAB's HIL approach is selective: you choose which peripherals to forward to
hardware, while everything else (RCC, Flash, GPIO, USART) stays emulated
locally. This gives you the best of both worlds -- fast emulation for
standard peripherals and real silicon for the peripherals that matter.

.. code-block:: text

   +------------------+       +-----------------+
   | QEMU (firmware)  |       | Real MCU (SWD)  |
   |                  |       |                 |
   | RCC  (emulated)  |       |  CRYP  <-----+  |
   | GPIO (emulated)  |       |  HASH  <-----+  |
   | USART(emulated)  |       |               |  |
   | CRYP  -----------+-------+-> pyOCD ------+  |
   | HASH  -----------+-------+-> (shared)       |
   +------------------+       +-----------------+


Step 1: Choosing a HIL Backend
===============================

SLAB supports four HIL backends for connecting to real hardware:

.. list-table::
   :widths: 15 25 30 30
   :header-rows: 1

   * - Backend
     - Connection
     - Pros
     - Cons
   * - **pyocd**
     - SWD/JTAG via debug probe
     - Clean Python API, probe auto-detection
     - Requires debug probe (ST-Link, J-Link)
   * - **openocd**
     - SWD/JTAG via OpenOCD TCL
     - Supports many targets, widely available
     - Requires running OpenOCD process
   * - **serial**
     - UART/USB-Serial
     - No debug probe needed
     - Requires bridge firmware on target
   * - **tcp**
     - TCP socket
     - Remote hardware, distributed testing
     - Requires remote server process

For most use cases, **pyocd** is recommended. It talks directly to debug probes
(ST-Link, CMSIS-DAP, J-Link) without an intermediate process.

Prerequisites
-------------

.. code-block:: bash

   pip install pyocd

   # Verify your probe is detected
   pyocd list --probes

   # List supported target types
   pyocd list --targets | grep stm32


Step 2: Creating a HIL Board Configuration
============================================

A HIL board is a standard SLAB board YAML with ``type: HIL`` entries in the
``external_devices`` section. Each HIL entry specifies an address range to
forward to real hardware.

Simple Example: GPIO on Real Hardware
--------------------------------------

.. code-block:: yaml

   # slab/boards/stm32f405_hil_gpio.yaml
   name: STM32F405_HIL_GPIO
   mcu: STM32F405

   external_devices:
     - type: HIL
       bus: GPIOA
       params:
         backend: pyocd
         target_type: stm32f405rg
         base: "0x40020000"
         size: "0x400"
         connect_mode: under-reset

This board emulates all STM32F405 peripherals (RCC, USART, Flash, etc.) locally,
but forwards GPIOA register accesses (0x40020000-0x400203FF) to a real STM32F405
connected via ST-Link.

When firmware writes to ``GPIOA->ODR``, the write hits the real silicon. When it
reads ``GPIOA->IDR``, it reads real pin states.


Step 3: Multiple MMIO Regions with Session Sharing
====================================================

When forwarding multiple peripherals to the same MCU, use ``shared_session: true``
to share a single debug probe connection. Most probes only support one concurrent
session.

.. code-block:: yaml

   # slab/boards/stm32f439_hil_crypto.yaml
   name: STM32F439_HIL_Crypto
   mcu: STM32F439

   external_devices:
     # CRYP accelerator (AES/DES/TDES)
     - type: HIL
       bus: CRYP
       params:
         backend: pyocd
         target_type: stm32f439xi
         base: "0x50060000"
         size: "0x400"
         connect_mode: under-reset
         shared_session: true

     # HASH accelerator (SHA-1/MD5)
     - type: HIL
       bus: HASH
       params:
         backend: pyocd
         target_type: stm32f439xi
         base: "0x50060400"
         size: "0x400"
         connect_mode: under-reset
         shared_session: true

Both CRYP and HASH share the same SWD connection to the STM32F439. Without
``shared_session``, each would try to open its own session and the second one
would fail with a "probe already in use" error.

You can add as many ``type: HIL`` entries as needed -- the only constraint is
that each covers a distinct address range and all entries sharing a session
target the same probe.


Step 4: Writing HIL Test Firmware
==================================

HIL test firmware is identical to regular bare-metal firmware. It doesn't know
which peripherals are emulated and which hit real silicon -- the SLAB proxy
makes this transparent.

AES-128 ECB Example (STM32F439)
--------------------------------

This firmware uses the hardware CRYP accelerator to encrypt a NIST test vector
and reports the result over USART1 (emulated):

.. code-block:: c

   /* Enable CRYP clock */
   RCC->AHB2ENR |= RCC_AHB2ENR_CRYPEN;

   /* Configure AES-128 ECB encrypt */
   cryp_aes_init(CRYP_KEYSIZE_128, CRYP_ALGOMODE_AES_ECB, 1);
   cryp_set_key_128(aes_key);
   cryp_enable();

   /* Encrypt one 16-byte block */
   cryp_process_block(plaintext, ciphertext);
   cryp_disable();

   /* Output ciphertext over USART1 (emulated by SLAB) */
   usart1_puts("CT: ");
   usart1_put_hex(ciphertext, 16);
   usart1_puts("\r\n");

When the firmware accesses ``RCC->AHB2ENR`` or ``USART1->DR``, those go to the
local Python peripheral model. When it accesses ``CRYP->CR`` or ``CRYP->DIN``,
those are forwarded to the real STM32F439 via pyOCD.

The complete example is in ``slab/examples/cortex-m/stm32/f439/hil/aes_test/``.

GPIO Toggle Example (STM32F405)
---------------------------------

A simpler example that toggles real GPIO pins and reads them back:

.. code-block:: c

   /* Configure GPIOA pins 0-7 as outputs (on real silicon) */
   GPIOA->MODER &= ~0x0000FFFF;
   GPIOA->MODER |=  0x00005555;   /* PA0-PA7 = output */

   /* Write pattern and read back */
   GPIOA->ODR = (GPIOA->ODR & ~0xFF) | 0xAA;
   uint32_t idr = GPIOA->IDR;
   /* idr & 0xFF should be 0xAA if pins are not externally loaded */

The complete example is in ``slab/examples/cortex-m/stm32/f405/hil/gpio_test/``.


Step 5: Running HIL Emulation
==============================

Build the firmware and start the SLAB server with the HIL board:

.. code-block:: bash

   # Build the AES test firmware
   cd slab/examples/cortex-m/stm32/f439/hil/aes_test
   make

   # Run with SLAB (connect ST-Link to STM32F439 board first)
   cd /path/to/slab-rehosting
   PYTHONPATH=slab/python python3 -m slab_cortex_m.mcuemu_server \
       --board slab/boards/stm32f439_hil_crypto.yaml \
       --firmware slab/examples/cortex-m/stm32/f439/hil/aes_test/build/aes_test.bin \
       --port 5555

The server will connect to the debug probe, forward CRYP/HASH accesses to
the real MCU, and emulate everything else locally.


Step 6: Recording HIL Traces
==============================

SLAB can record every HIL access with timestamps and latencies, enabling
offline replay and regression testing without hardware.

Recording
---------

Wrap any HIL peripheral with ``HILTraceRecorder``:

.. code-block:: python

   from slab_cortex_m.hil_peripheral import (
       HILPyOCDPeripheral, HILTraceRecorder
   )

   # Create the real HIL peripheral
   cryp = HILPyOCDPeripheral(
       name="CRYP", base=0x50060000, size=0x400,
       target_type="stm32f439xi"
   )

   # Wrap with recorder
   recorder = HILTraceRecorder(cryp)

   # Use recorder as a drop-in replacement in your board
   board.hil_peripherals.append(recorder)

   # ... run firmware ...

   # Save trace to disk
   recorder.save("cryp_trace.jsonl")

The trace file is JSON Lines format, one record per access:

.. code-block:: json

   {"seq": 1, "ts": 0.000123, "rw": "W", "addr": "0x50060000", "size": 4, "value": "0x00000020", "latency_ms": 1.234, "ok": true, "periph": "CRYP"}
   {"seq": 2, "ts": 0.001456, "rw": "W", "addr": "0x50060004", "size": 4, "value": "0x2B7E1516", "latency_ms": 0.987, "ok": true, "periph": "CRYP"}
   {"seq": 3, "ts": 0.002789, "rw": "R", "addr": "0x50060000", "size": 4, "value": "0x00000021", "latency_ms": 1.102, "ok": true, "periph": "CRYP"}


Step 7: Replaying HIL Traces Offline
======================================

Once you have a recorded trace, you can replay it without the real hardware.
This is useful for:

- Running the same test on CI (no debug probe needed)
- Sharing traces between developers
- Deterministic regression testing

Replay from Trace File
-----------------------

.. code-block:: python

   from slab_cortex_m.hil_peripheral import HILReplayPeripheral

   # Load and replay a recorded trace
   replay = HILReplayPeripheral.from_trace("cryp_trace.jsonl")

   # Use as drop-in replacement
   board.hil_peripherals.append(replay)

   # Firmware will see the exact same values as the original run

The replay peripheral returns recorded read values in sequence. Writes are
accepted and update an internal value map for subsequent reads. Call
``replay.rewind()`` to restart the replay from the beginning.

Replay via Board YAML
----------------------

You can also use the ``replay`` backend directly in board configuration:

.. code-block:: yaml

   external_devices:
     - type: HIL
       bus: CRYP
       params:
         backend: replay
         trace_file: "cryp_trace.jsonl"
         base: "0x50060000"
         size: "0x400"

This makes it trivial to switch between live hardware and recorded traces
by changing one line in the YAML.


Step 8: Programmatic HIL with the Emulator API
================================================

For scripted testing and Avatar2-style workflows, use the ``CortexM`` emulator
class directly:

.. code-block:: python

   from slab_cortex_m import CortexM, CortexMConfig

   config = CortexMConfig(
       machine="STM32F439",
       firmware_path="build/aes_test.bin",
       hil_peripherals=[{
           'name': 'CRYP_HIL',
           'base': '0x50060000',
           'size': '0x400',
           'backend': 'pyocd',
           'target_type': 'stm32f439xi',
       }],
   )

   emu = CortexM(config)
   emu.start()

   # Board is ready -- HIL peripherals are injected
   state = emu.get_state()
   print(f"Peripherals: {state['peripherals']}")
   print(f"HIL peripherals: {state['hil_peripherals']}")

   # Direct memory access through the board adapter
   data = emu.mem_read(0x40023800, 4)   # RCC CR (emulated)
   emu.mem_write(0x40020014, b'\xFF\x00\x00\x00')  # GPIOA ODR

   emu.stop()

The ``CortexM`` class manages the board, optional QEMU process, and HIL
peripheral injection. It is also the adapter used by ``Avatar2Bridge``
and ``HILBridge`` in the ``slab_hw`` module.


Step 9: Using Other Backends
=============================

OpenOCD Backend
---------------

If you already have OpenOCD running, use the ``openocd`` backend:

.. code-block:: bash

   # Start OpenOCD (in a separate terminal)
   openocd -f interface/stlink.cfg -f target/stm32f4x.cfg

.. code-block:: yaml

   - type: HIL
     bus: GPIOA
     params:
       backend: openocd
       host: localhost
       port: 6666
       base: "0x40020000"
       size: "0x400"

Serial Backend
--------------

The serial backend talks to a bridge firmware running on the target MCU that
interprets a simple binary protocol (R/W commands + address + value):

.. code-block:: yaml

   - type: HIL
     bus: GPIOA
     params:
       backend: serial
       serial_port: /dev/ttyUSB0
       baudrate: 115200
       base: "0x40020000"
       size: "0x400"

TCP Backend
-----------

For remote hardware servers:

.. code-block:: yaml

   - type: HIL
     bus: CRYP
     params:
       backend: tcp
       host: 192.168.1.100
       port: 5001
       base: "0x50060000"
       size: "0x400"


Latency Considerations
=======================

HIL introduces latency on every forwarded MMIO access:

.. list-table::
   :widths: 25 25 50
   :header-rows: 1

   * - Backend
     - Typical Latency
     - Notes
   * - pyOCD (ST-Link V2)
     - 1-5 ms/access
     - Adequate for register setup, not for polling loops
   * - pyOCD (J-Link)
     - 0.5-2 ms/access
     - Faster probe, better for bulk transfers
   * - OpenOCD (TCL)
     - 2-10 ms/access
     - TCL parsing overhead
   * - TCP (localhost)
     - 0.1-1 ms/access
     - Lowest latency, depends on server
   * - Replay
     - < 0.01 ms/access
     - In-memory, no I/O

To minimize impact:

1. **Forward only what you need** -- keep RCC, Flash, GPIO emulated unless you
   specifically need real silicon behavior
2. **Avoid spin-loop registers on HIL** -- status registers polled in tight loops
   will be very slow over SWD
3. **Use trace recording** -- record once on real hardware, replay for all
   subsequent test runs


Best Practices
===============

1. **Start with emulation, add HIL selectively**: Get your firmware running
   fully emulated first, then replace specific peripherals with HIL
2. **Use shared sessions**: When forwarding multiple address ranges to the same
   MCU, always use ``shared_session: true``
3. **Record and replay**: Record HIL traces during initial bring-up, then use
   replay for CI and regression testing
4. **Verify with known test vectors**: For crypto peripherals, use NIST test
   vectors to validate that HIL forwarding produces correct results
5. **Keep the target MCU powered and halted**: The debug probe reads/writes
   memory while the target CPU is halted -- this is safe for peripheral
   registers but the target firmware should not be running


Summary
========

SLAB's HIL infrastructure enables selective hardware forwarding:

- **Board YAML** declares which peripherals go to real hardware (``type: HIL``)
- **pyOCD** is the recommended backend for debug probe connections
- **Session sharing** enables multiple MMIO regions on one probe
- **Trace recording** captures every access for offline replay
- **Replay** enables CI testing without hardware
- **CortexM API** provides programmatic access for scripted workflows

All HIL peripherals are transparent to firmware -- the same binary runs
identically in fully-emulated or HIL mode.


Next Steps
==========

- :ref:`creating_boards`: Board YAML configuration reference
- :ref:`mmio_tracing`: Trace all MMIO accesses (emulated and HIL)
- :ref:`ci_testing`: Integrate HIL replay traces into CI pipelines
- :ref:`trustzone_emulation`: HIL with TrustZone-enabled MCUs
