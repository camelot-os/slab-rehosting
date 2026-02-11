.. _server_modes:

====================================
Server Modes and UART Hooking
====================================

This tutorial explains the two ways to run a peripheral server in SLAB
(direct mode vs board mode) and how to hook UART output in real-time
for firmware debugging.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>

Copyright (C) 2026 Twisted Wires Security Lab


Introduction
============

SLAB peripheral emulation runs in a Python TCP server that QEMU connects to.
Every MMIO access from firmware is forwarded over the wire to your Python code,
which responds with register values, triggers IRQs, and drives external devices.

There are two ways to set up this server:

::

    Direct Mode                             Board Mode
    +--------------------------+            +---------------------------+
    | create_peripheral_set()  |            | load_board_config()       |
    | PeripheralSetAdapter()   |            | build_board()             |
    | Manual UART wiring       |            | Automatic UART wiring     |
    | Manual IRQ forwarding    |            | Automatic LED tracking    |
    +--------------------------+            | Automatic device wiring   |
              |                             +---------------------------+
              v                                        |
    +-----------------------------+                    v
    |   BasePeripheralServer      |          +-----------------------------+
    |   subclass                  |          |   BasePeripheralServer      |
    |   (your handle_client TCP)  |          |   subclass (board.contains) |
    +-----------------------------+          +-----------------------------+
              |                                        |
              v                                        v
          QEMU  <-------- TCP / SHM -------->  Python Server


- **Direct mode** -- You instantiate a ``PeripheralSet`` and wire everything
  yourself. Use this when you need full control over peripheral iteration,
  custom UART handling, or are building a one-off test harness.

- **Board mode** -- You write a YAML file and call ``build_board()``.
  UART capture, LED tracking, and external device wiring happen automatically.
  Use this for reproducible configurations and CI integration.


Direct Mode
===========

In direct mode you create a peripheral set from a ``BoardConfig``, wrap it in
a ``PeripheralSetAdapter``, then subclass ``BasePeripheralServer`` to serve it.

Step 1: Create the Peripheral Set
----------------------------------

.. code-block:: python
   :caption: direct_server.py -- create peripheral set from BoardConfig

   from slab_cortex_m.board import BoardConfig, create_peripheral_set
   from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

   # Minimal config -- MCU name is enough
   config = BoardConfig(name="MyTest", mcu="STM32U5A5")

   # Instantiate the peripheral set (imports slab_stm32.STM32U5A5PeripheralSet)
   pset = create_peripheral_set(config)

   # Wrap in adapter (normalizes read/write/IRQ interface)
   adapter = PeripheralSetAdapter(pset)

``create_peripheral_set()`` looks up the MCU name in ``MCU_REGISTRY``
(defined in ``slab/python/slab_cortex_m/board.py:68``) and dynamically
imports the matching class. The ``PeripheralSetAdapter``
(``slab/python/slab_cortex_m/peripheral_adapter.py:27``) normalizes the
read/write return conventions across STM32, Nordic, NXP, and RP2040
families.

Step 2: Wire UART Manually
----------------------------

In direct mode nothing is wired for you. To capture UART output, iterate
the adapter's ``peripherals`` property (always returns a ``list``) and hook
every peripheral whose name contains ``USART`` or ``UART``:

.. code-block:: python
   :caption: direct_server.py -- manual UART wiring

   uart_buf = bytearray()

   for p in adapter.peripherals:
       name = getattr(p, 'name', '')
       if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
           def make_handler(buf=uart_buf):
               def handler(byte):
                   buf.append(byte & 0xFF)
               return handler
           p.on_tx = make_handler()

The ``make_handler()`` factory pattern avoids late-binding closure bugs.
Without it, all UARTs would share the same ``buf`` reference from the
last loop iteration.

``adapter.peripherals`` always returns a list, even when the underlying
``pset.peripherals`` is a dict (see ``slab/python/slab_cortex_m/peripheral_adapter.py:85``).

Step 3: Subclass BasePeripheralServer
--------------------------------------

``BasePeripheralServer`` (``slab/python/slab_cortex_m/base_server.py:34``)
handles the binary protocol. You only need to implement ``create_peripherals()``
and ``find_peripheral()``:

.. code-block:: python
   :caption: direct_server.py -- server subclass

   import asyncio
   from slab_cortex_m.base_server import BasePeripheralServer

   class DirectServer(BasePeripheralServer):
       def __init__(self, adapter, port):
           super().__init__(port)
           self.adapter = adapter
           # Forward IRQs from peripherals to QEMU
           self.adapter.irq_callback = self.send_irq

       def create_peripherals(self):
           pass  # Already created above

       def find_peripheral(self, addr):
           if self.adapter.contains(addr):
               return self.adapter
           return None

   async def main():
       server = DirectServer(adapter, port=5555)
       server.running = True

       tcp = await asyncio.start_server(
           server.handle_client, '127.0.0.1', 5555, reuse_address=True)

       print(f"[Direct] Listening on tcp://127.0.0.1:5555")
       print(f"[Peripherals] {len(adapter.peripherals)}")
       await tcp.serve_forever()

   asyncio.run(main())

``find_peripheral()`` returns the adapter itself because the adapter's
``read()`` and ``write()`` methods satisfy the server protocol
(``read(addr, size, secure) -> (value, status)``).

Step 4: Complete Runnable Script
---------------------------------

The full script combining all steps above:

.. code-block:: python
   :caption: direct_server.py -- save as slab/examples/direct_server.py

   #!/usr/bin/env python3
   """Direct-mode peripheral server with UART capture."""

   import asyncio
   from slab_cortex_m.board import BoardConfig, create_peripheral_set
   from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter
   from slab_cortex_m.base_server import BasePeripheralServer

   # -- 1. Create peripheral set ------------------------------------------------
   config = BoardConfig(name="U5A5_Direct", mcu="STM32U5A5")
   pset = create_peripheral_set(config)
   adapter = PeripheralSetAdapter(pset)

   # -- 2. Wire UART capture ----------------------------------------------------
   uart_buf = bytearray()
   for p in adapter.peripherals:
       name = getattr(p, 'name', '')
       if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
           def make_handler(buf=uart_buf):
               def handler(byte):
                   buf.append(byte & 0xFF)
               return handler
           p.on_tx = make_handler()

   # -- 3. Server subclass ------------------------------------------------------
   class DirectServer(BasePeripheralServer):
       def __init__(self, adpt, port):
           super().__init__(port)
           self.adapter = adpt
           self.adapter.irq_callback = self.send_irq

       def create_peripherals(self):
           pass

       def find_peripheral(self, addr):
           if self.adapter.contains(addr):
               return self.adapter
           return None

   # -- 4. Run ------------------------------------------------------------------
   async def main():
       server = DirectServer(adapter, port=5555)
       server.running = True
       tcp = await asyncio.start_server(
           server.handle_client, '127.0.0.1', 5555, reuse_address=True)
       print(f"[Direct] Listening on tcp://127.0.0.1:5555")
       print(f"[Peripherals] {len(adapter.peripherals)}")
       await tcp.serve_forever()

   asyncio.run(main())


Board Mode
==========

Board mode loads a YAML configuration and calls ``build_board()`` which
handles peripheral creation, adapter wrapping, UART wiring, LED tracking,
and external device wiring in one step.

Step 1: Load the Board YAML
-----------------------------

.. code-block:: python
   :caption: board_server.py -- load and build a board

   from slab_cortex_m.board import load_board_config
   from slab_cortex_m.board_builder import build_board

   config = load_board_config("slab/boards/stm32u5a5_cdc_blinky.yaml")
   board = build_board(config)

``load_board_config()`` (``slab/python/slab_cortex_m/board.py:95``) parses
YAML or JSON into a ``BoardConfig`` dataclass. ``build_board()``
(``slab/python/slab_cortex_m/board_builder.py``) does the assembly:

1. ``create_peripheral_set(config)`` -- instantiate MCU peripherals
2. ``PeripheralSetAdapter(pset)`` -- normalize read/write/IRQ
3. ``Board(config, adapter)`` -- create board object
4. ``_wire_uart(board)`` -- capture all USART/UART ``on_tx`` to ``board.uart_output``
5. ``_wire_leds(board)`` -- track LED GPIO changes in ``board.led_states``
6. External device creation and wiring (SPI flash, I2C EEPROM, etc.)

The UART wiring logic in ``_wire_uart()`` (``slab/python/slab_cortex_m/board_builder.py:317``)
matches peripherals whose name contains ``USART``, ``UART``, or ``UARTE``.
This catches ``USART1``, ``LPUART1``, ``UARTE0`` (Nordic), etc.

Step 2: Serve the Board
-------------------------

The pattern is the same as direct mode, but ``find_peripheral()`` delegates
to ``board.contains(addr)`` and returns the board itself:

.. code-block:: python
   :caption: board_server.py -- save as slab/examples/board_server.py

   #!/usr/bin/env python3
   """Board-mode peripheral server with automatic UART capture."""

   import asyncio
   from slab_cortex_m.board import load_board_config, get_qemu_cpu, get_default_clock
   from slab_cortex_m.board_builder import build_board
   from slab_cortex_m.base_server import BasePeripheralServer

   # -- 1. Build board ----------------------------------------------------------
   config = load_board_config("slab/boards/stm32u5a5_cdc_blinky.yaml")
   board = build_board(config)

   # -- 2. Server subclass ------------------------------------------------------
   class BoardServer(BasePeripheralServer):
       def __init__(self, brd, port):
           super().__init__(port)
           self.board = brd
           self.board.irq_callback = self.send_irq

       def create_peripherals(self):
           pass  # build_board() already created them

       def find_peripheral(self, addr):
           if self.board.contains(addr):
               return self.board
           return None

   # -- 3. Run ------------------------------------------------------------------
   async def main():
       server = BoardServer(board, port=5555)
       server.running = True
       tcp = await asyncio.start_server(
           server.handle_client, '127.0.0.1', 5555, reuse_address=True)

       cpu = get_qemu_cpu(config)       # "cortex-m33"
       clock = get_default_clock(config) # 160000000
       print(f"[Board] {board.name} ({config.mcu})")
       print(f"[CPU] {cpu} @ {clock // 1_000_000} MHz")
       print(f"[Peripherals] {len(board.adapter.peripherals)}")
       print(f"[Listening] tcp://127.0.0.1:5555")

       await tcp.serve_forever()

   asyncio.run(main())

After firmware runs, ``board.uart_output`` contains the captured bytes:

.. code-block:: python

   print(board.uart_output.decode('ascii', errors='replace'))


Comparison
==========

.. list-table::
   :header-rows: 1
   :widths: 35 30 30

   * - Feature
     - Direct Mode
     - Board Mode
   * - Configuration
     - Python code
     - YAML file
   * - UART capture
     - Manual wiring
     - Automatic (``board.uart_output``)
   * - LED tracking
     - Not available
     - Automatic (``board.led_states``)
   * - External devices (flash, EEPROM)
     - Manual wiring
     - Automatic from YAML
   * - HIL support
     - Manual setup
     - YAML ``type: HIL`` entries
   * - Peripheral iteration
     - ``adapter.peripherals`` (list)
     - ``board.adapter.peripherals`` (list)
   * - CI integration
     - Custom test harness
     - ``ci_runner.py`` + YAML scenarios
   * - Typical use case
     - Quick experiments, custom test scripts
     - Reproducible boards, CI pipelines


Live UART Output
================

By default, UART bytes are silently appended to a buffer. For interactive
debugging you often want them printed in real-time.

Direct Mode: Print-on-TX Handler
---------------------------------

Replace the silent handler with one that also writes to stdout:

.. code-block:: python
   :caption: direct_server.py -- live UART (replace the UART wiring section)

   import sys

   uart_buf = bytearray()

   for p in adapter.peripherals:
       name = getattr(p, 'name', '')
       if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
           def make_live_handler(pname, buf=uart_buf):
               def handler(byte):
                   buf.append(byte & 0xFF)
                   sys.stdout.write(chr(byte & 0x7F))
                   sys.stdout.flush()
               return handler
           p.on_tx = make_live_handler(name)

Board Mode: LiveUartBuffer
---------------------------

In board mode, ``_wire_uart()`` has already wired ``on_tx`` to append to
``board.uart_output``. To get live printing, replace ``board.uart_output``
with a custom ``bytearray`` subclass and re-wire the callbacks through
``board.adapter.peripherals``:

.. code-block:: python
   :caption: board_server.py -- live UART (add after build_board)

   import sys

   class LiveUartBuffer(bytearray):
       """bytearray subclass that prints each byte as it arrives."""
       def append(self, byte):
           super().append(byte & 0xFF)
           sys.stdout.write(chr(byte & 0x7F))
           sys.stdout.flush()

   # Replace the buffer and re-wire on_tx
   board.uart_output = LiveUartBuffer()
   for p in board.adapter.peripherals:
       name = getattr(p, 'name', '')
       if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
           def make_handler(buf=board.uart_output):
               def handler(byte):
                   buf.append(byte & 0xFF)
               return handler
           p.on_tx = make_handler()

``board.adapter.peripherals`` always returns a list
(see ``PeripheralSetAdapter.peripherals`` at
``slab/python/slab_cortex_m/peripheral_adapter.py:160``),
regardless of whether the underlying ``pset.peripherals`` is a ``dict`` or ``list``.


Running with QEMU
==================

Both server scripts expect QEMU to connect on TCP port 5555. Start them in
separate terminals.

Terminal 1 -- Python server:

.. code-block:: bash

   PYTHONPATH=slab/python python3 slab/examples/direct_server.py
   # or
   PYTHONPATH=slab/python python3 slab/examples/board_server.py

Terminal 2 -- QEMU:

.. code-block:: bash
   :caption: STM32U5A5 example (Cortex-M33, 160 MHz)

   ./build/qemu-system-arm \
       -M slab-cortex-m,cpu-type=cortex-m33,sysclk-hz=160000000 \
       -kernel path/to/firmware.bin \
       -nographic

For MCUs with non-default memory layout, add the ``qemu_extra`` properties
from the board YAML. For example, the STM32U5A5 board at
``slab/boards/stm32u5a5_cdc_blinky.yaml`` needs:

.. code-block:: bash

   ./build/qemu-system-arm \
       -M slab-cortex-m,cpu-type=cortex-m33,sysclk-hz=160000000,\
   sram-size=0x270000,flash-size=0x400000,\
   periph-base=0x0BFA0000,periph-size=0x54060000 \
       -kernel path/to/firmware.bin \
       -nographic

The default TCP port is 5555 for both QEMU and the Python server.


Best Practices
==============

1. **Use board mode for anything reproducible.** Direct mode is for quick
   experiments; board YAML files are self-documenting and work with the CI
   runner.

2. **Closure capture pattern.** Always use the ``buf=uart_buf`` default
   argument trick when wiring ``on_tx`` in a loop, or use a factory function
   (``make_handler()``). Without it, all closures share the last value of the
   loop variable.

3. **LPUART is matched by substring.** The ``_wire_uart()`` function checks
   for ``'UART'`` as a substring, so ``LPUART1`` is matched automatically.
   Nordic ``UARTE0`` is matched by an explicit ``'UARTE'`` check.

4. **``pset.peripherals`` can be dict or list.** STM32 peripheral sets use
   a ``dict`` (keyed by name), while Nordic/NXP use a ``list``.
   ``adapter.peripherals`` normalizes this to always return a ``list``.

5. **IRQ forwarding.** Always set ``board.irq_callback = self.send_irq``
   (or ``adapter.irq_callback = self.send_irq``) so that peripheral IRQs
   reach QEMU. Without this, interrupt-driven firmware will hang.


Next Steps
==========

- :ref:`creating_boards` -- Write YAML board configurations from scratch
- :ref:`mmio_tracing` -- Record and analyze MMIO accesses during emulation
- :ref:`ci_testing` -- Run automated firmware test scenarios
- :ref:`hardware_in_the_loop` -- Forward selected peripherals to real silicon
