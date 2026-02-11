.. _firmware_dump_emulation:

======================================================
Emulating a Firmware Dump with SVD and MMIO Tracing
======================================================

This tutorial walks through the complete workflow of taking a raw firmware
``.bin`` dump -- such as one extracted from a flash chip, obtained via JTAG
read-out, or provided as part of a vulnerability assessment -- and emulating
it in the SLAB framework with full peripheral tracing and register-level
visibility. By the end of this tutorial you will be able to identify the
target MCU, set up the emulation environment, capture every peripheral
access the firmware makes, and analyze the resulting trace to understand
initialization sequences, communication protocols, and runtime behavior.

Overview
========

A security researcher or embedded engineer often encounters a binary firmware
image without access to the original source code. The typical inputs are:

1. **A firmware .bin dump** -- a flat binary extracted from flash memory,
   containing the ARM Cortex-M vector table, code, and read-only data.
2. **An SVD file** (optional) -- a CMSIS System View Description XML file
   provided by the silicon vendor that describes every peripheral register
   on the target MCU.

The goal is to emulate the firmware in a controlled environment where every
memory-mapped I/O (MMIO) access is intercepted, decoded, and logged. This
produces a deterministic trace that reveals:

- The clock and PLL configuration sequence
- Which peripherals the firmware initializes and in what order
- Communication protocols on SPI, I2C, UART buses
- Polling loops and potential stuck points
- Security-relevant register writes (MPU, SAU, FLASH option bytes)

SLAB makes this possible by running the firmware on a generic QEMU
``slab-cortex-m`` machine that proxies every peripheral access to a Python
server over TCP. The Python server hosts accurate peripheral models (or
SVD-based auto-stubs) and an MMIO tracer that records every transaction.


Prerequisites
=============

Before starting, ensure the following are in place:

1. **QEMU built for ARM** with the SLAB ``slab-cortex-m`` machine:

   .. code-block:: bash

      cd /path/to/slab-rehosting
      mkdir -p build && cd build
      ../configure --target-list=arm-softmmu
      ninja

2. **Python environment** with SLAB packages on the import path:

   .. code-block:: bash

      export PYTHONPATH=/path/to/slab-rehosting/slab/python

3. **PyYAML** installed (for board YAML parsing):

   .. code-block:: bash

      pip install pyyaml

4. **arm-none-eabi-gdb** or **gdb-multiarch** (optional, for interactive
   debugging with the GDB stub).

5. **A firmware .bin file** and, optionally, an SVD file for the target MCU.
   SVD files for many STMicro, Nordic, and NXP parts are available in the
   `cmsis-svd <https://github.com/posborne/cmsis-svd>`_ community repository:

   .. code-block:: bash

      git clone https://github.com/posborne/cmsis-svd.git

   Files are organized by vendor: ``cmsis-svd/data/STMicro/``,
   ``cmsis-svd/data/Nordic/``, ``cmsis-svd/data/Freescale/`` (NXP).


Step 1: Identify the Target MCU
================================

Every ARM Cortex-M firmware binary begins with a vector table. The first two
words (8 bytes) are critical:

- **Offset 0x00** -- Initial Stack Pointer (MSP)
- **Offset 0x04** -- Reset Handler address (entry point)

These two values reveal the memory layout of the target MCU, which is
essential for configuring QEMU correctly.

Reading the Vector Table
------------------------

Use a short Python script to inspect the vector table:

.. code-block:: python

   import struct

   with open("firmware.bin", "rb") as f:
       data = f.read(8)

   initial_sp, reset_handler = struct.unpack("<II", data)
   print(f"Initial SP:     0x{initial_sp:08X}")
   print(f"Reset Handler:  0x{reset_handler:08X}")

Example output for an STM32F405 firmware:

.. code-block:: text

   Initial SP:     0x20020000
   Reset Handler:  0x08000299

Deducing the Flash Base Address
-------------------------------

The Reset Handler address reveals the flash base because the vector table
resides at the start of flash:

.. list-table::
   :header-rows: 1
   :widths: 30 25 25 20

   * - Reset Handler Range
     - Flash Base
     - MCU Family
     - QEMU Property
   * - ``0x0800xxxx``
     - ``0x08000000``
     - STM32 (F0/F1/F4/L4/H5/H7/U5/WB)
     - (default)
   * - ``0x0000xxxx``
     - ``0x00000000``
     - nRF52840, nRF5340
     - ``flash-base=0x00000000``
   * - ``0x1000xxxx``
     - ``0x10000000``
     - RP2040, RP2350
     - ``flash-base=0x10000000``
   * - ``0x0C00xxxx``
     - ``0x0C000000``
     - STM32H5 (TrustZone secure)
     - ``flash-base=0x0C000000``

The Initial SP value tells you about SRAM. For example, ``0x20020000``
indicates SRAM extends to 128 KB above ``0x20000000``, consistent with an
STM32F405/F407.

.. note::

   If the Reset Handler address has bit 0 set (e.g., ``0x08000299``), that
   is normal: ARM Cortex-M uses the Thumb instruction set, and the LSB
   indicates Thumb mode. The actual code address is ``0x08000298``.


Step 2: Parse the SVD File
===========================

If you have an SVD file for the target MCU, you can enumerate all
peripherals, their base addresses, and register layouts. SLAB includes a
built-in SVD parser.

.. code-block:: python

   from slab_cortex_m.svd_parser import SVDParser

   parser = SVDParser()
   device = parser.parse("cmsis-svd/data/STMicro/STM32F405.svd")

   print(f"Device: {device.name}")
   print(f"Peripherals ({len(device.peripherals)}):")
   for p in sorted(device.peripherals, key=lambda p: p.base_address):
       print(f"  {p.name:12s} @ 0x{p.base_address:08X}  "
             f"({len(p.registers)} registers)")

Example output:

.. code-block:: text

   Device: STM32F405
   Peripherals (54):
     TIM2         @ 0x40000000  (15 registers)
     TIM3         @ 0x40000400  (15 registers)
     USART2       @ 0x40004400  (7 registers)
     I2C1         @ 0x40005400  (6 registers)
     SPI1         @ 0x40013000  (9 registers)
     GPIOA        @ 0x40020000  (10 registers)
     RCC          @ 0x40023800  (24 registers)
     ...

This information helps you confirm that the SVD matches your firmware's
target MCU and understand the peripheral address map.

.. note::

   SVD files are optional. SLAB's built-in peripheral models for supported
   MCUs already contain register definitions. SVD parsing is most useful
   when working with an MCU that is not yet in the MCU registry, or when
   you want to cross-reference vendor register documentation.


Step 3: Choose a Peripheral Set
================================

SLAB ships with peripheral models for 20 MCUs across five vendors. The
``MCU_REGISTRY`` in ``board.py`` maps MCU names to their implementations:

.. code-block:: python

   from slab_cortex_m.board import MCU_REGISTRY

   print(f"{'MCU':14s} {'CPU':12s} {'Clock':>8s}  Class")
   print("-" * 65)
   for mcu, (pkg, cls, cpu, clk) in sorted(MCU_REGISTRY.items()):
       print(f"  {mcu:12s}  {cpu:12s}  {clk // 1_000_000:4d} MHz  ({cls})")

This produces:

.. code-block:: text

   MCU            CPU            Clock  Class
   -----------------------------------------------------------------
     IMXRT1060     cortex-m7      600 MHz  (IMXRT1060PeripheralSet)
     LPC55S69      cortex-m33     150 MHz  (LPC55S69PeripheralSet)
     RP2040        cortex-m0      125 MHz  (RP2040PeripheralSet)
     RP2350        cortex-m33     150 MHz  (RP2350PeripheralSet)
     STM32F030     cortex-m0       48 MHz  (STM32F0xxPeripheralSet)
     STM32F103     cortex-m3       72 MHz  (STM32F103PeripheralSet)
     STM32F405     cortex-m4      168 MHz  (STM32F405PeripheralSet)
     STM32F407     cortex-m4      168 MHz  (STM32F407PeripheralSet)
     STM32F411     cortex-m4      100 MHz  (STM32F411PeripheralSet)
     STM32F439     cortex-m4      180 MHz  (STM32F439PeripheralSet)
     STM32H563     cortex-m33     250 MHz  (STM32H563PeripheralSet)
     STM32H745     cortex-m7      480 MHz  (STM32H7xxPeripheralSet)
     STM32L433     cortex-m4       80 MHz  (STM32L4xxPeripheralSet)
     STM32U585     cortex-m33     160 MHz  (STM32U585PeripheralSet)
     STM32U5A5     cortex-m33     160 MHz  (STM32U5A5PeripheralSet)
     STM32U5A9     cortex-m33     160 MHz  (STM32U5A9PeripheralSet)
     STM32WB35     cortex-m4       64 MHz  (STM32WB35PeripheralSet)
     STM32WB55     cortex-m4       64 MHz  (STM32WB55PeripheralSet)
     nRF52840      cortex-m4       64 MHz  (NRF52840PeripheralSet)
     nRF5340       cortex-m33     128 MHz  (NRF5340AppPeripheralSet)

If your target MCU is not in the registry, you can use SVD auto-stub mode
by setting the ``mcu`` field to ``SVD:path/to/device.svd`` in the board
YAML. This generates peripheral stubs automatically from the SVD file.

Choosing the Right Entry
------------------------

Match the MCU from your firmware to the closest entry:

- **Exact match**: Use ``STM32F405`` if the firmware targets an STM32F405.
- **Same sub-family**: STM32F407 firmware often works with the ``STM32F405``
  peripheral set (same peripheral addresses).
- **Generic fallback**: STM32F030 firmware can use ``STM32F030`` (maps to
  ``STM32F0xxPeripheralSet``).
- **SVD auto-stub**: For any MCU not listed, use ``SVD:`` prefix with the
  vendor SVD file.


Step 4: Create a Board YAML
=============================

The board YAML file is the central configuration that ties together the MCU,
clock, memory layout, and external devices. Create a file called
``my_firmware_board.yaml``:

.. code-block:: yaml

   name: MyFirmwareDump
   mcu: STM32F405
   clock: 168000000
   qemu_extra:
     flash-size: "0x100000"
     sram-size: "0x20000"

Field-by-field explanation:

.. list-table::
   :header-rows: 1
   :widths: 20 50 30

   * - Field
     - Description
     - Default
   * - ``name``
     - Human-readable board name (used in reports)
     - (required)
   * - ``mcu``
     - MCU identifier from ``MCU_REGISTRY``, or ``SVD:path.svd``
     - (required)
   * - ``clock``
     - System clock in Hz; overrides MCU default
     - MCU default
   * - ``qemu_extra``
     - Additional ``-M`` properties passed to QEMU
     - ``{}``

The ``qemu_extra`` dictionary maps directly to QEMU machine properties.
Each key-value pair becomes part of the ``-M slab-cortex-m,...`` argument:

.. code-block:: bash

   # qemu_extra: {flash-size: "0x100000", sram-size: "0x20000"}
   # becomes:
   -M slab-cortex-m,...,flash-size=0x100000,sram-size=0x20000

Common ``qemu_extra`` properties:

.. list-table::
   :header-rows: 1
   :widths: 25 50 25

   * - Property
     - Description
     - Default
   * - ``flash-base``
     - Flash memory base address
     - ``0x08000000``
   * - ``flash-size``
     - Flash memory size
     - ``0x100000`` (1 MB)
   * - ``sram-base``
     - SRAM base address
     - ``0x20000000``
   * - ``sram-size``
     - SRAM size
     - ``0x40000`` (256 KB)
   * - ``periph-base``
     - Peripheral proxy region start
     - ``0x40000000``
   * - ``periph-size``
     - Peripheral proxy region size
     - ``0x20000000`` (512 MB)
   * - ``bootrom-base``
     - Boot ROM base address
     - ``0x1FFF0000``
   * - ``bootrom-size``
     - Boot ROM size
     - ``0x10000`` (64 KB)

For an nRF52840 firmware, the board YAML would look like:

.. code-block:: yaml

   name: NRF52840_FirmwareDump
   mcu: nRF52840
   clock: 64000000
   qemu_extra:
     flash-base: "0x00000000"
     flash-size: "0x100000"
     sram-size: "0x40000"


Step 5: Launch the Emulation
=============================

With the board YAML ready, write a Python server script that loads the board,
attaches an MMIO tracer, and serves peripheral requests to QEMU. Save this
as ``run_firmware_dump.py``:

.. code-block:: python

   #!/usr/bin/env python3
   """Emulate a firmware dump with MMIO tracing."""

   import asyncio
   from slab_cortex_m.board import load_board_config, get_qemu_cpu, get_default_clock
   from slab_cortex_m.board_builder import build_board
   from slab_cortex_m.base_server import BasePeripheralServer
   from slab_cortex_m.mmio_tracer import MMIOTracer


   class FirmwareServer(BasePeripheralServer):
       """Peripheral server backed by a Board object."""

       def __init__(self, board, port):
           super().__init__(port)
           self.board = board
           self.board.irq_callback = self.send_irq

       def create_peripherals(self):
           pass  # Board already contains all peripherals

       def find_peripheral(self, addr):
           if self.board.contains(addr):
               return self.board
           return None


   async def main():
       # Load board configuration
       config = load_board_config("my_firmware_board.yaml")
       board = build_board(config)

       # Wire UART live output (print characters as they are transmitted)
       for p in board.adapter.peripherals:
           name = getattr(p, 'name', '')
           if 'USART' in name or 'UART' in name:
               if hasattr(p, 'on_tx'):
                   p.on_tx = lambda b: print(chr(b & 0x7F), end='', flush=True)

       # Create server with MMIO tracer
       server = FirmwareServer(board, 5555)
       server.running = True
       tracer = MMIOTracer()
       server.tracer = tracer

       # Start TCP server for QEMU
       srv = await asyncio.start_server(
           server.handle_client, '127.0.0.1', 5555, reuse_address=True
       )
       print(f"Peripheral server on port 5555, waiting for QEMU...")
       print(f"Board: {board.name}, CPU: {board.qemu_cpu}, "
             f"Clock: {board.clock // 1_000_000} MHz")

       # Run for a fixed duration (adjust as needed)
       await asyncio.sleep(30)

       # Export trace results
       print(f"\nCaptured {tracer.count} MMIO accesses")
       tracer.export_text("firmware_trace.mmio")
       tracer.export_json("firmware_trace.jsonl")
       tracer.export_csv("firmware_trace.csv")
       print("Traces exported to firmware_trace.{mmio,jsonl,csv}")

       srv.close()


   if __name__ == "__main__":
       asyncio.run(main())

In a separate terminal, launch QEMU pointing at the firmware binary:

.. code-block:: bash

   build/qemu-system-arm \
     -M slab-cortex-m,cpu-type=cortex-m4,tcp-port=5555,sysclk-hz=168000000 \
     -kernel firmware.bin \
     -nographic \
     -monitor none \
     -gdb tcp::1234

.. note::

   The ``-gdb tcp::1234`` flag is optional but recommended. It enables the
   GDB stub so you can attach a debugger at any time during emulation (see
   Step 9).

QEMU will connect to the Python server on port 5555 and begin executing
the firmware. Every peripheral register access is forwarded to the Python
server, which responds with register values and records the access in the
tracer.

The ``sysclk-hz`` property is important: it tells QEMU's SysTick timer
the actual system clock frequency, preventing a SysTick interrupt storm
when the firmware configures a clock speed different from the QEMU default.


Step 6: Enable MMIO Tracing
=============================

The server script above already attaches an ``MMIOTracer`` instance to the
server. This section explains what the tracer captures and how the output
is structured.

How the Tracer Works
--------------------

The tracer hooks into the server's ``handle_client()`` loop. After every
read or write transaction, the server calls ``tracer.trace_read()`` or
``tracer.trace_write()`` with:

- The 32-bit peripheral address
- The access size (1, 2, or 4 bytes)
- The data value (read result or written value)
- A reference to the peripheral object (for register name resolution)
- The firmware program counter (PC) at the time of access

The ``RegisterNameResolver`` then uses class introspection on the peripheral
object to decode raw offsets into human-readable register names and bit-field
labels, without requiring an SVD file.

Trace Output Formats
--------------------

**Text format** (``.mmio``) -- human-readable, diffable, version-control friendly:

.. code-block:: text

   00000001 W 0x40023800 4 0x00000001  RCC->CR  [HSION]
   00000002 R 0x40023800 4 0x00000003  RCC->CR
   00000003 W 0x40023804 4 0x24003008  RCC->PLLCFGR  [PLLSRC|PLLN|PLLM]
   00000004 W 0x40023800 4 0x01010001  RCC->CR  [HSION|PLLON]
   00000005 R 0x40023800 4 0x03010003  RCC->CR
   00000006 R 0x40023800 4 0x03010003  RCC->CR
   00000007 W 0x40023808 4 0x00009401  RCC->CFGR

Format: ``[seq] R/W 0xADDR size 0xVALUE  PERIPH->REG  [bitfields]  @PC``

**JSON Lines format** (``.jsonl``) -- machine-readable, compatible with
``replay_peripheral.py``:

.. code-block:: json

   {"seq": 1, "ts": 0.000123, "rw": "W", "addr": "0x40023800", "size": 4, "value": "0x00000001", "periph": "RCC", "reg": "CR", "bits": "HSION"}
   {"seq": 2, "ts": 0.000456, "rw": "R", "addr": "0x40023800", "size": 4, "value": "0x00000003", "periph": "RCC", "reg": "CR"}

**CSV format** (``.csv``) -- for spreadsheet analysis:

.. code-block:: text

   sequence,timestamp,rw,address,size,value,peripheral,register,bitfields,pc
   1,0.000123,W,0x40023800,4,0x00000001,RCC,CR,HSION,
   2,0.000456,R,0x40023800,4,0x00000003,RCC,CR,,


Step 7: Analyze the Trace
==========================

Once the emulation completes and traces are collected, the ``MMIOTracer``
provides several analysis methods to extract meaningful information from
potentially thousands of raw accesses.

Initialization Sequence
-----------------------

The firmware's initialization phase is typically the most informative
segment of the trace. It reveals clock configuration, peripheral enable
sequences, and GPIO pin setup:

.. code-block:: python

   init = tracer.get_init_sequence()
   print(f"Initialization phase: {len(init)} accesses\n")
   for t in init[:20]:
       rw = 'W' if t.is_write else 'R'
       bf = f"  [{t.bitfields}]" if t.bitfields else ""
       print(f"  [{t.sequence:4d}] {rw} {t.peripheral_name}->{t.register_name}"
             f" = 0x{t.value:08X}{bf}")

Example output:

.. code-block:: text

   Initialization phase: 42 accesses

   [   1] W RCC->CR = 0x00000001  [HSION]
   [   2] R RCC->CR = 0x00000003
   [   3] W RCC->PLLCFGR = 0x24003008  [PLLSRC|PLLN|PLLM]
   [   4] W RCC->CR = 0x01010001  [HSION|PLLON]
   [   5] R RCC->CR = 0x03010003
   [   6] W RCC->CFGR = 0x00009401
   [   7] W RCC->AHB1ENR = 0x00000001  [GPIOAEN]
   [   8] W GPIOA->MODER = 0x28000000
   [   9] W GPIOA->OSPEEDR = 0x0C000000
   [  10] W SPI1->CR1 = 0x00000344  [SPE|MSTR]

Peripheral Access Summary
--------------------------

Get per-peripheral statistics to understand which peripherals are most
active and their access patterns:

.. code-block:: python

   summary = tracer.get_peripheral_summary()
   for name, info in sorted(summary.items(),
                             key=lambda x: -(x[1]['reads'] + x[1]['writes'])):
       total = info['reads'] + info['writes']
       print(f"  {name:20s} {total:6d} ops  "
             f"({info['reads']:4d}R / {info['writes']:4d}W)  "
             f"top: {info['top_reg']}")

Example output:

.. code-block:: text

     USART2                 342 ops  ( 171R /  171W)  top: DR
     SPI1                   210 ops  ( 142R /   68W)  top: SR
     RCC                     33 ops  (  15R /   18W)  top: CR
     GPIOA                   20 ops  (   8R /   12W)  top: ODR
     FLASH                    6 ops  (   4R /    2W)  top: ACR

This immediately reveals the firmware's communication patterns. A high
USART DR access count indicates active serial communication. Heavy SPI SR
polling suggests data transfer with an external device.

Spin Loop Detection
-------------------

Firmware that polls a status register waiting for a hardware event will
produce a characteristic pattern of consecutive identical reads. The tracer
detects these automatically:

.. code-block:: python

   loops = tracer.detect_spin_loops(min_repeats=5)
   for loop in loops:
       print(f"  Spin: {loop.peripheral}->{loop.register} "
             f"x{loop.count} (seq {loop.start_seq}-{loop.end_seq}) "
             f"value=0x{loop.value:08X}")

Example output:

.. code-block:: text

     Spin: RCC->CR x12 (seq 5-16) value=0x00000003
     Spin: SPI1->SR x87 (seq 45-132) value=0x00000002

Spin loops are diagnostic gold:

- **RCC->CR spin**: Firmware waiting for PLL lock (PLLRDY bit). If the
  peripheral model sets PLLRDY immediately, the loop is short. If not,
  the firmware may appear stuck.
- **SPI1->SR spin**: Firmware polling TXE or RXNE. A long spin indicates
  the SPI transfer completion flag is not being set by the peripheral model.

Register Access Table
---------------------

For a detailed per-register breakdown:

.. code-block:: python

   table = tracer.get_register_access_table()
   print(f"{'Peripheral':<14s} {'Register':<12s} {'Reads':>6s} "
         f"{'Writes':>7s} {'Last Value':>12s}")
   print("-" * 55)
   for row in table:
       print(f"  {row['peripheral']:<12s} {row['register']:<12s} "
             f"{row['reads']:>6d} {row['writes']:>7d} "
             f"  0x{row['last_value']:08X}")


Step 8: Generate a LaTeX Report
================================

SLAB includes a LaTeX report generator that produces publication-quality
PDF documents with TikZ architecture diagrams, register access tables,
and test verdicts. This is particularly useful for security assessments
and compliance documentation.

.. code-block:: python

   from slab_cortex_m.report_generator import TestBookReport, generate_test_book

   # Build the report data structure from tracer results
   report = TestBookReport(
       title="STM32F405 Firmware Analysis",
       mcu="STM32F405",
       firmware_name="firmware.bin",
       peripherals=list(set(t.peripheral_name for t in tracer.traces)),
       mmio_count=tracer.count,
       mmio_traces=tracer.traces[:500],       # First 500 traces for the report
       spin_loops=tracer.detect_spin_loops(),
       register_summary=tracer.get_register_access_table(),
       peripheral_summary=tracer.get_peripheral_summary(),
       duration=30.0,
       passed=True,
       description="Firmware dump analysis with full MMIO tracing",
       qemu_command=(
           "qemu-system-arm -M slab-cortex-m,cpu-type=cortex-m4,"
           "tcp-port=5555,sysclk-hz=168000000 -kernel firmware.bin"
       ),
       test_mode="board",
       cpu_type="cortex-m4",
   )

   # Generate the LaTeX file
   tex_path = generate_test_book(report, output_dir="reports/")
   print(f"LaTeX report generated: {tex_path}")

Compile the LaTeX file to PDF:

.. code-block:: bash

   cd reports/
   pdflatex firmware.bin_report.tex
   pdflatex firmware.bin_report.tex   # Run twice for TOC/references

The report includes:

- A TikZ architecture diagram showing the MCU, peripherals, and their
  bus connections
- A summary table of all peripheral accesses (reads, writes, top registers)
- The initialization sequence with register names and bit-field annotations
- Detected spin loops with sequence ranges
- UART console output captured during emulation

.. figure:: ../images/mcuemu_architecture.png
   :alt: Example TikZ architecture diagram
   :align: center
   :width: 80%

   Example architecture diagram generated by the report generator.


Step 9: Debug with GDB
========================

If the firmware crashes (HardFault), hangs, or behaves unexpectedly, you
can attach GDB to the QEMU instance for live debugging. The ``-gdb tcp::1234``
flag on the QEMU command line enables the GDB stub.

Batch Debugging
---------------

For quick fault diagnosis, use a batch GDB session:

.. code-block:: bash

   gdb-multiarch -batch \
     -ex "target remote localhost:1234" \
     -ex "file firmware.elf" \
     -ex "break HardFault_Handler" \
     -ex "continue" \
     -ex "bt" \
     -ex "info registers"

.. note::

   The ``file firmware.elf`` command requires the ELF file (with debug
   symbols) corresponding to the .bin dump. If you only have the .bin file,
   you can still inspect registers and memory, but you will not have symbol
   names or source-level debugging.

Interactive Debugging
---------------------

For interactive sessions, connect manually:

.. code-block:: bash

   gdb-multiarch firmware.elf
   (gdb) target remote localhost:1234
   (gdb) monitor system_reset
   (gdb) break main
   (gdb) continue
   (gdb) info registers
   (gdb) x/16xw 0x40023800    # Dump RCC registers
   (gdb) x/8xw 0x20000000     # Inspect SRAM contents

Useful GDB commands for Cortex-M debugging:

.. code-block:: text

   info registers          # All core registers (r0-r12, sp, lr, pc, xpsr)
   x/16xw 0xE000ED00       # System Control Block (SCB)
   x/4xw 0xE000E100        # NVIC ISER (interrupt enable)
   x/4xw 0xE000E200        # NVIC ISPR (interrupt pending)
   x/8xw 0xE000ED90        # MPU registers (Type, CTRL, RNR, RBAR, RASR)

Combining GDB with MMIO Tracing
--------------------------------

A powerful workflow is to run the MMIO tracer and GDB simultaneously. The
tracer captures the full register access history, while GDB lets you set
breakpoints at specific firmware functions. When the firmware hits a
breakpoint, you can inspect the trace to see exactly which peripheral
accesses led to that point:

1. Start the Python peripheral server with MMIO tracing (Step 5).
2. Start QEMU with ``-gdb tcp::1234``.
3. Attach GDB and set breakpoints on interesting functions.
4. When a breakpoint hits, check the tracer's ``count`` property.
5. Export the trace and analyze the accesses leading up to the breakpoint.


Step 10: Advanced -- SVD Auto-Stub Mode
=========================================

If your target MCU is not in the MCU registry, SLAB can generate peripheral
stubs automatically from an SVD file. This mode creates a read/write
register model for every peripheral described in the SVD, with correct
reset values and access permissions.

To use SVD auto-stub mode, set the ``mcu`` field in the board YAML to
``SVD:`` followed by the SVD file path:

.. code-block:: yaml

   name: UnknownMCU_FirmwareDump
   mcu: "SVD:cmsis-svd/data/STMicro/STM32G474.svd"
   clock: 170000000
   qemu_extra:
     flash-size: "0x80000"
     sram-size: "0x20000"
   qemu_cpu: cortex-m4

When loaded, the board builder calls ``SVDStubPeripheralSet.from_svd()``
which parses the SVD and creates a peripheral stub for every entry:

.. code-block:: python

   config = load_board_config("svd_board.yaml")
   board = build_board(config)
   print(f"Loaded {len(board.adapter.peripherals)} peripheral stubs from SVD")

SVD auto-stubs respond to reads with the register's reset value and store
writes to shadow registers. They do not model peripheral behavior (no
interrupts, no side effects), but they prevent the firmware from seeing
``0x00000000`` for every read, which is often enough to get past the
initialization phase.

.. warning::

   SVD auto-stubs do not model hardware behavior. Status register polling
   loops (e.g., waiting for PLL lock or SPI transfer complete) will spin
   indefinitely unless you supplement the stubs with a proper peripheral
   model or use firmware patching to skip the wait loop.


Best Practices
===============

This section collects the most common pitfalls and their solutions when
emulating firmware dumps.

Flash Base Address Mismatch
---------------------------

The most frequent configuration error is using the wrong ``flash-base``.
Always verify the Reset Handler address in the vector table:

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - Symptom
     - Likely Cause
     - Fix
   * - Immediate HardFault at boot
     - Wrong flash-base; vector table misaligned
     - Check Reset Handler address
   * - Firmware runs but accesses wrong peripherals
     - Correct flash-base but wrong MCU peripheral set
     - Verify SVD against actual MCU
   * - QEMU refuses to start
     - flash-base overlaps with other memory regions
     - Check for bootrom/SRAM overlap

Missing ``sysclk-hz`` Property
-------------------------------

If ``sysclk-hz`` is not set, QEMU defaults to a 12 MHz SysTick reference
clock. Firmware that configures the PLL to run at 168 MHz will expect
SysTick to fire at a rate proportional to the system clock. The mismatch
causes SysTick interrupts to fire orders of magnitude too fast, creating
an interrupt storm that overwhelms the peripheral server.

.. code-block:: bash

   # Always set sysclk-hz to match the firmware's expected clock
   -M slab-cortex-m,...,sysclk-hz=168000000

ARMv7-M Bitband vs ARMv8-M AHB2
---------------------------------

On ARMv7-M cores (Cortex-M3, M4, M7), the address region
``0x42000000-0x43FFFFFF`` is a bitband alias for ``0x40000000-0x400FFFFF``.
A single bit in the peripheral region can be read or written via a word
access in the bitband alias.

On ARMv8-M cores (Cortex-M23, M33, M55, M85), bitband is **removed**. The
``0x42000000`` region is used for AHB2 peripherals instead (e.g., USB OTG HS
on STM32U5 at ``0x42040000``).

.. warning::

   If you emulate an ARMv8-M firmware (STM32H5, U5, nRF5340) with QEMU's
   ``enable-bitband`` option enabled (the default for some configurations),
   accesses to ``0x42xxxxxx`` will be silently redirected to bitband alias
   reads instead of reaching the AHB2 peripherals. This causes USB, GPIO,
   and other AHB2 peripherals to malfunction.

   Ensure ``enable-bitband`` is disabled for ARMv8-M targets. SLAB handles
   this automatically for registered MCUs.

Unimplemented Peripheral Reads
-------------------------------

When the firmware reads a peripheral register that is not implemented in
the peripheral model, the server returns ``0x00000000`` by default. Some
firmware is sensitive to specific reset values (e.g., RCC CR should report
HSI ready on reset). Check the MMIO trace for reads that return zero
from registers that should have non-zero reset values.

Firmware Patching
-----------------

For firmware that contains anti-emulation checks or peripheral waits that
cannot be satisfied, use the ``patches`` field in the board YAML to patch
out problematic code:

.. code-block:: yaml

   patches:
     - start: "0x08001234"
       data: "00 BF"            # NOP (Thumb encoding: 0xBF00)
       description: "Skip watchdog enable"
     - start: "0x08001240"
       data: [0x01, 0x20]       # MOVS r0, #1 (force success return)
       description: "Force crypto self-test pass"


Next Steps
==========

This tutorial covered the end-to-end workflow for emulating a firmware dump.
For deeper exploration of individual topics, see:

- :ref:`creating_boards` -- Full board configuration reference with external
  device wiring (SPI flash, I2C EEPROM, LEDs, displays)
- :ref:`mmio_tracing` -- Advanced MMIO tracing techniques including CI
  integration and regression detection
- :ref:`ci_testing` -- Automated testing with YAML-driven CI scenarios
  and JUnit XML output
- :ref:`svd_to_peripheral` -- Converting SVD files into full peripheral
  implementations
- :ref:`debugging_bootloops` -- Systematic approach to diagnosing firmware
  that fails to boot
- :ref:`trustzone_emulation` -- Emulating ARMv8-M TrustZone secure firmware
  (STM32H5, U5)

For the complete API reference, see the :ref:`api/slab_cortex_m` documentation.


Summary
=======

The firmware dump emulation workflow in SLAB follows a systematic process:

1. **Identify** the target MCU from the vector table (Initial SP + Reset Handler)
2. **Parse** the SVD file to enumerate peripherals and registers
3. **Choose** a peripheral set from the MCU registry (or use SVD auto-stub)
4. **Configure** a board YAML with the correct memory layout and clock
5. **Launch** the emulation with a Python peripheral server and MMIO tracer
6. **Capture** every peripheral access with full register name resolution
7. **Analyze** initialization sequences, peripheral summaries, and spin loops
8. **Report** findings with LaTeX/TikZ architecture diagrams and tables
9. **Debug** interactively with GDB when the firmware faults or hangs

This workflow transforms an opaque binary blob into a fully observable
execution environment, giving security researchers and embedded engineers
deep visibility into firmware behavior without physical hardware.

---

**Author**: Mathieu Renard <mathieu.renard@twistedwires.io>

**Copyright**: (C) 2026 Twisted Wires Security Lab
