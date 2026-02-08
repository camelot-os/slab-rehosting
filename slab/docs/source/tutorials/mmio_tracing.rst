.. _mmio_tracing:

===============================================
MMIO Tracing for Testing and Reverse Engineering
===============================================

This tutorial explains how to use MMIO tracing in SLAB to capture every peripheral
register access during firmware emulation. MMIO traces provide deterministic,
human-readable records of firmware behavior, useful for testing proof, CI regression
detection, and reverse engineering unknown firmware.

What is MMIO Tracing?
======================

MMIO (Memory-Mapped I/O) tracing captures every read and write operation that firmware
makes to peripheral registers. In SLAB, the tracer automatically:

- Records the address, size, and value of each access
- Resolves raw addresses to human-readable peripheral and register names
- Decodes bit-fields for write operations
- Provides timestamped, sequential logs

This is useful for:

1. **Testing Proof**: Deterministic trace outputs serve as regression test fixtures
2. **CI Integration**: Compare traces across commits to detect peripheral behavior changes
3. **Reverse Engineering**: Understand firmware initialization sequences, clock configurations,
   and communication protocols
4. **Debug Assistance**: Identify stuck polling loops and missing peripheral functionality

Step 1: Enabling MMIO Tracing
==============================

To enable tracing, create an ``MMIOTracer`` instance and attach it to your peripheral server:

.. code-block:: python
   :caption: Basic tracing setup

   from slab_cortex_m.mmio_tracer import MMIOTracer
   from slab_stm32.stm32f4_server import STM32F4Server

   # Create server
   server = STM32F4Server(port=9999)

   # Attach tracer
   tracer = MMIOTracer()
   server.tracer = tracer

   # Run firmware emulation
   # ... QEMU interaction ...

   # Check results
   print(f"Captured {tracer.count} MMIO accesses")

The tracer integrates transparently with the server's ``handle_client()`` loop.
Every peripheral read/write triggers ``trace_read()`` or ``trace_write()`` callbacks.

Step 2: Understanding Trace Output
===================================

After firmware execution, traces are stored in memory. Each trace contains:

- **Sequence number**: Monotonically increasing counter
- **Timestamp**: Seconds since tracing started
- **Operation**: Read (R) or Write (W)
- **Address**: Full 32-bit peripheral register address
- **Size**: Access size in bytes (1, 2, or 4)
- **Value**: Data read or written
- **Peripheral name**: Resolved from address (e.g., "RCC", "GPIOA", "SPI1")
- **Register name**: Resolved from offset (e.g., "CR", "SR", "DR")
- **Bit-fields**: Active flags for writes (e.g., "HSION|HSEON")

Example trace output (text format):

.. code-block:: text
   :caption: Example MMIO trace (trace.mmio)

   00000001 W 0x40023800 4 0x00000001  RCC->CR  [HSION]
   00000002 R 0x40023800 4 0x00000003  RCC->CR
   00000003 W 0x40023804 4 0x24003008  RCC->PLLCFGR  [PLLSRC|PLLN|PLLM]
   00000004 W 0x40023800 4 0x01010001  RCC->CR  [HSION|PLLON]
   00000005 R 0x40023800 4 0x03010003  RCC->CR
   00000006 R 0x40023800 4 0x03010003  RCC->CR
   00000007 W 0x40023808 4 0x00009401  RCC->CFGR

Format: ``[seq] R/W 0xADDR size 0xVALUE  PERIPH->REG [bitfields]``

This format is compatible with ``svd_composer.py`` for automatic SVD generation.

Step 3: Register Name Resolution
=================================

The ``RegisterNameResolver`` uses class introspection to decode peripheral register
offsets into human-readable names. It works without SVD files by analyzing class-level
constants from peripheral implementations.

Register Naming Patterns
-------------------------

The resolver supports multiple naming conventions:

**STM32-style (single-token registers):**

.. code-block:: python

   class STM32SPI:
       CR1 = 0x00
       CR2 = 0x04
       SR = 0x08
       DR = 0x0C

**STM32-style (bit-fields):**

.. code-block:: python

   class STM32SPI:
       CR1_SPE = 1 << 6   # Enable bit
       CR1_MSTR = 1 << 2  # Master mode
       SR_TXE = 1 << 1    # TX empty
       SR_RXNE = 1 << 0   # RX not empty

**NRF-style (multi-token registers):**

.. code-block:: python

   class NRFTIMER:
       TASKS_START = 0x000
       TASKS_STOP = 0x004
       EVENTS_COMPARE = 0x140
       SHORTS = 0x200

Bit-Field Decoding
------------------

For write operations, the resolver decodes active single-bit flags. Multi-bit masks
(e.g., ``CR1_BR_MASK``) are excluded to reduce noise.

.. code-block:: text

   00000010 W 0x40013000 4 0x00000344  SPI1->CR1  [SPE|MSTR]

This trace shows that both ``SPE`` (bit 6) and ``MSTR`` (bit 2) were set in the CR1 write.

Step 4: Export Formats
=======================

The tracer supports three export formats, each optimized for different workflows.

Text Format (.mmio)
-------------------

Human-readable format compatible with ``svd_composer.py``:

.. code-block:: python

   tracer.export_text("trace.mmio")

Output:

.. code-block:: text

   00000001 W 0x40023800 4 0x00000001  RCC->CR  [HSION]
   00000002 R 0x40023800 4 0x00000003  RCC->CR
   00000003 W 0x40023804 4 0x24003008  RCC->PLLCFGR  [PLLSRC|PLLN|PLLM]

JSON Lines Format (.jsonl)
---------------------------

Machine-readable format compatible with ``replay_peripheral.py``:

.. code-block:: python

   tracer.export_json("trace.jsonl")

Output:

.. code-block:: json

   {"seq": 1, "ts": 0.000123, "rw": "W", "addr": "0x40023800", "size": 4, "value": "0x00000001", "periph": "RCC", "reg": "CR", "bits": "HSION"}
   {"seq": 2, "ts": 0.000456, "rw": "R", "addr": "0x40023800", "size": 4, "value": "0x00000003", "periph": "RCC", "reg": "CR"}

CSV Format (.csv)
-----------------

Spreadsheet-compatible format for manual analysis:

.. code-block:: python

   tracer.export_csv("trace.csv")

Output:

.. code-block:: text

   sequence,timestamp,rw,address,size,value,peripheral,register,bitfields
   1,0.000123,W,0x40023800,4,0x00000001,RCC,CR,HSION
   2,0.000456,R,0x40023800,4,0x00000003,RCC,CR,

Step 5: Analyzing Initialization Sequences
===========================================

Firmware typically follows a predictable pattern: initialization phase (writes unique
configuration values) followed by main loop (repetitive polling). The ``get_init_sequence()``
method extracts the initialization phase:

.. code-block:: python
   :caption: Extract initialization sequence

   init = tracer.get_init_sequence()
   print(f"Init phase: {len(init)} accesses")

   for t in init:
       if t.is_write:
           print(f"  {t.peripheral_name}->{t.register_name} = 0x{t.value:08X}")

Example output:

.. code-block:: text

   Init phase: 42 accesses
     RCC->CR = 0x00000001
     RCC->PLLCFGR = 0x24003008
     RCC->CR = 0x01010001
     RCC->CFGR = 0x00009401
     GPIOA->MODER = 0x28000000
     GPIOA->OSPEEDR = 0x0C000000
     SPI1->CR1 = 0x00000344

This is particularly useful for:

- **Clock Configuration**: Understanding RCC register writes to reconstruct PLL settings
- **GPIO Setup**: Identifying which pins are configured as outputs, alternate functions, etc.
- **Peripheral Enable Sequence**: Discovering the order in which peripherals are initialized

Step 6: Spin Loop Detection
============================

Firmware often polls status registers in busy-wait loops. The tracer detects these patterns
automatically:

.. code-block:: python
   :caption: Detect spin loops

   loops = tracer.detect_spin_loops(min_repeats=5)
   for sl in loops:
       print(f"Spin: {sl.peripheral}->{sl.register} x{sl.count} "
             f"(seq {sl.start_seq}-{sl.end_seq})")

Example output:

.. code-block:: text

   Spin: SPI1->SR x87 (seq 45-132)
   Spin: RCC->CR x12 (seq 8-20)

Spin loops indicate:

- **Missing Functionality**: Firmware waiting for a flag that never gets set
- **Timing Issues**: Peripheral state transitions not modeled correctly
- **Bootloops**: Stuck initialization waiting for hardware that doesn't respond

Heuristic Details
-----------------

The detector identifies consecutive reads from the same address returning the same value.
This pattern is typical of polling loops like:

.. code-block:: c

   while (!(SPI1->SR & SPI_SR_TXE)) {
       // Wait for TX buffer empty
   }

If your peripheral stub never sets the ``TXE`` flag, the tracer will detect the spin loop
and report exactly which register is being polled.

Step 7: Peripheral Access Summary
==================================

Generate per-peripheral statistics to understand firmware activity:

.. code-block:: python
   :caption: Peripheral access summary

   summary = tracer.get_peripheral_summary()
   for name, data in sorted(summary.items()):
       print(f"{name:12s}: {data['reads']:4d}R / {data['writes']:4d}W, "
             f"top: {data['top_reg']}")

Example output:

.. code-block:: text

   GPIOA       :    8R /   12W, top: ODR
   RCC         :   15R /   18W, top: CR
   SPI1        :  142R /   68W, top: SR
   USART2      :   24R /   96W, top: DR

This helps identify:

- Which peripherals are most active
- Whether firmware is read-heavy (polling) or write-heavy (configuration)
- The most frequently accessed register per peripheral

Step 8: CI Integration
======================

MMIO traces provide deterministic test fixtures for continuous integration. Use
``generate_reports.py`` to capture traces during automated testing:

.. code-block:: bash
   :caption: Generate MMIO trace in CI

   PYTHONPATH=slab/python python3 slab/tools/generate_reports.py \
       --mmio-log --output-dir reports/

This creates:

- ``reports/trace.mmio`` - Full MMIO trace
- ``reports/trace.jsonl`` - JSON Lines format
- ``reports/summary.txt`` - Peripheral access statistics

Regression Detection
--------------------

Compare traces across commits to detect behavioral changes:

.. code-block:: bash

   # Capture baseline
   git checkout main
   ./generate_reports.py --mmio-log --output-dir baseline/

   # Test new branch
   git checkout feature-branch
   ./generate_reports.py --mmio-log --output-dir test/

   # Compare
   diff baseline/trace.mmio test/trace.mmio

Differences indicate that the firmware's peripheral access pattern has changed, potentially
revealing bugs or unintended behavior modifications.

Step 9: Reverse Engineering Workflow
=====================================

MMIO tracing is a powerful tool for understanding unknown firmware. Here's a systematic
workflow:

1. Load Unknown Firmware
------------------------

Attach the tracer and run the firmware without any peripheral implementations:

.. code-block:: python

   from slab_cortex_m.base_server import BasePeripheralServer
   from slab_cortex_m.mmio_tracer import MMIOTracer

   class MinimalServer(BasePeripheralServer):
       def create_peripherals(self):
           pass  # No peripherals yet

   server = MinimalServer(port=9999)
   tracer = MMIOTracer()
   server.tracer = tracer

   # Run QEMU with unknown firmware
   # ... firmware will likely hang, but we'll capture accesses ...

2. Identify Active Peripherals
-------------------------------

Analyze the peripheral access summary to see which peripherals the firmware uses:

.. code-block:: python

   summary = tracer.get_peripheral_summary()
   # Output: RCC, GPIOA, SPI1, USART2, TIM2, I2C1

3. Reconstruct Clock Configuration
-----------------------------------

Extract RCC writes from the init sequence to understand the clock tree:

.. code-block:: python

   init = tracer.get_init_sequence()
   rcc_writes = [t for t in init if t.peripheral_name == "RCC" and t.is_write]
   for t in rcc_writes:
       print(f"{t.register_name} = 0x{t.value:08X}  [{t.bitfields}]")

Example:

.. code-block:: text

   CR = 0x00000001  [HSION]
   PLLCFGR = 0x24003008  [PLLSRC|PLLN|PLLM]
   CR = 0x01010001  [HSION|PLLON]
   CFGR = 0x00009401

This reveals:

- HSI (internal oscillator) is enabled
- PLL is configured with specific multiplier/divider values
- System clock is switched to PLL output

4. Identify Communication Protocols
------------------------------------

Look for characteristic patterns in SPI, I2C, or UART traces:

.. code-block:: python

   spi_traces = [t for t in tracer.traces if t.peripheral_name == "SPI1"]
   # Analyze CR1 writes (mode, baud rate)
   # Analyze DR writes (data transmission)

For SPI, look for:

- CR1 writes setting MSTR (master mode), SPE (enable)
- Alternating SR reads (polling TXE/RXNE) and DR writes (transmitting data)

5. Compare Firmware Versions
-----------------------------

Run multiple firmware versions and diff their traces to identify changes:

.. code-block:: bash

   # Version 1.0
   python3 run_firmware.py v1.0.bin --trace v1.mmio

   # Version 2.0
   python3 run_firmware.py v2.0.bin --trace v2.mmio

   # Diff
   diff v1.mmio v2.mmio

This reveals:

- New peripherals enabled in v2.0
- Changed register configurations
- Removed or reordered initialization steps

Best Practices
==============

1. **Always Export Traces After Emulation**

   Don't rely on in-memory traces for long-term storage. Export to disk immediately:

   .. code-block:: python

      tracer.export_text("trace.mmio")
      tracer.export_json("trace.jsonl")

2. **Use Text Format for Version Control**

   The text format is human-readable and diffable, making it ideal for Git:

   .. code-block:: bash

      git add baseline/trace.mmio
      git commit -m "Add baseline MMIO trace for regression testing"

3. **Filter Noisy Peripherals**

   Some peripherals (like timers or DMA) generate thousands of accesses. Consider
   excluding them from analysis:

   .. code-block:: python

      filtered = [t for t in tracer.traces if t.peripheral_name not in ["TIM2", "DMA1"]]

4. **Combine with UART Output**

   Cross-reference MMIO traces with firmware console output to correlate register
   accesses with high-level behavior:

   .. code-block:: python

      # Capture UART output
      usart = server.peripherals['USART2']
      print(usart.get_tx_data().decode('utf-8'))

      # Then analyze MMIO traces around that timestamp

5. **Verify Against Datasheets**

   When reverse engineering, always validate your findings against the MCU datasheet.
   Register offsets and bit-field meanings are documented and should match your traces.

Summary
=======

MMIO tracing in SLAB provides a powerful lens into firmware behavior:

- **Automatic resolution** of peripheral and register names via class introspection
- **Three export formats** for different workflows (testing, replay, analysis)
- **Built-in analysis tools** for init sequences, spin loops, and peripheral summaries
- **CI integration** for regression detection across commits
- **Reverse engineering support** for understanding unknown firmware

For more details on the tracer API, see the :ref:`api/slab_cortex_m` documentation.

Next Steps
==========

* :ref:`stubbing_peripherals` - Create peripheral stubs that generate interesting traces
* :ref:`debugging_bootloops` - Use spin loop detection to fix stuck firmware
* :ref:`api/slab_cortex_m` - Full API reference for MMIOTracer

---

**Author**: Mathieu Renard <mathieu.renard@twistedwires.io>

**Copyright**: (C) 2026 Twisted Wires Security Lab
