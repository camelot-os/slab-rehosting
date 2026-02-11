.. _architecture_overview:

======================
Architecture Overview
======================

SLAB uses a modular architecture that separates CPU emulation (QEMU) from
peripheral behavior (Python), enabling flexible firmware analysis and testing.

Design Principles
=================

1. **Separation of Concerns**: QEMU handles CPU/memory, Python handles peripherals
2. **Register Accuracy**: Peripheral stubs match real hardware register behavior
3. **Extensibility**: Easy to add new MCU families without QEMU modifications
4. **Performance**: SHM mode achieves ~3μs per MMIO access
5. **Debuggability**: Full MMIO tracing and signal capture

System Components
=================

.. figure:: ../images/mcuemu_architecture.png
   :alt: SLAB Architecture
   :align: center
   :width: 100%

   SLAB Architecture Overview

QEMU slab-cortex-m Machine
--------------------------

A generic ARM Cortex-M machine that:

- Emulates all Cortex-M variants (M0 to M85)
- Provides configurable Flash and SRAM
- Forwards all peripheral MMIO to external server
- Supports TrustZone for ARMv8-M cores
- Supports dual-core for STM32H7, RP2040, etc.

**Configuration Options:**

.. code-block:: text

   -M slab-cortex-m,<options>

   Options:
     cpu-type=<type>       CPU model (cortex-m0 to cortex-m85)
     flash-base=<addr>     Flash base address (default: 0x08000000)
     flash-size=<size>     Flash size in bytes (default: 1MB)
     sram-base=<addr>      SRAM base address (default: 0x20000000)
     sram-size=<size>      SRAM size in bytes (default: 256KB)
     bootrom-base=<addr>   Bootrom base address (default: 0x1FFF0000)
     bootrom-size=<size>   Bootrom size in bytes (default: 64KB)
     periph-base=<addr>    Peripheral proxy range base (default: 0x40000000)
     periph-size=<size>    Peripheral proxy range size (default: 512MB)
     tcp-port=<port>       Peripheral proxy port (default: 5555)
     shm-name=<name>       POSIX SHM name (enables SHM mode)
     sysclk-hz=<freq>      System clock frequency hint
     usbip-port=<port>     USBIP server port (in-QEMU USB bridge)
     trustzone=on/off      Enable TrustZone (ARMv8-M only)
     dual-core=on/off      Enable second CPU core

Peripheral Proxy
----------------

Binary protocol connecting QEMU to Python:

.. code-block:: text

   Read Request (14 bytes):
   +------+----------+----------+--------+----------+
   | Cmd  | Address  |  Size    | Secure |    PC    |
   | 1B   |   4B     |   4B     |   1B   |    4B    |
   +------+----------+----------+--------+----------+

   Write Request (18 bytes):
   +------+----------+----------+----------+--------+----------+
   | Cmd  | Address  |  Size    |  Value   | Secure |    PC    |
   | 1B   |   4B     |   4B     |   4B     |   1B   |    4B    |
   +------+----------+----------+----------+--------+----------+

   Response (5 bytes):
   +----------+--------+
   |  Value   | Status |
   |   4B     |   1B   |
   +----------+--------+

**Commands:**

- ``R`` (0x52): Non-Secure read
- ``W`` (0x57): Non-Secure write
- ``S`` (0x53): Secure read
- ``T`` (0x54): Secure write

Python Peripheral Server
------------------------

Implements peripheral register behavior:

.. code-block:: python

   class PeripheralServer:
       def __init__(self):
           self.peripherals = {}  # name → peripheral

       def read(self, address: int, size: int) -> tuple:
           for p in self.peripherals.values():
               if p.contains(address):
                   return p.read(address, size)
           return (0, 0)

       def write(self, address: int, size: int, value: int) -> int:
           for p in self.peripherals.values():
               if p.contains(address):
                   return p.write(address, size, value)
           return 0

Data Flow
=========

.. figure:: ../images/dataflow.png
   :alt: Data Flow Diagram
   :align: center
   :width: 90%

   MMIO Request Flow: Firmware → QEMU → Proxy → Python → Response

1. Firmware executes load/store to peripheral address
2. QEMU's memory system intercepts the access
3. slab-cortex-m machine forwards to peripheral proxy
4. Python peripheral server processes the request
5. Response sent back through same path
6. QEMU returns value to firmware

Latency Characteristics
-----------------------

.. list-table::
   :widths: 30 20 50
   :header-rows: 1

   * - Mode
     - Latency
     - Use Case
   * - TCP (localhost)
     - ~62 us
     - Remote debugging, distributed (~16K ops/sec)
   * - POSIX SHM
     - ~26 us
     - High-performance local emulation (~39K ops/sec)

Peripheral Model
================

Each peripheral follows a common interface:

.. code-block:: python

   class BasePeripheral:
       def __init__(self, base: int, size: int = 0x400):
           self.base = base
           self.size = size
           self.regs = {}

       def contains(self, address: int) -> bool:
           return self.base <= address < self.base + self.size

       def read(self, address: int, size: int) -> tuple:
           """Return (value, status)"""
           offset = address - self.base
           return (self.regs.get(offset, 0), 0)

       def write(self, address: int, size: int, value: int) -> int:
           """Return status (0=OK)"""
           offset = address - self.base
           self.regs[offset] = value
           return 0

Peripheral Sets
---------------

Pre-built peripheral collections for common MCUs:

.. code-block:: python

   from slab_stm32 import STM32F439PeripheralSet

   ps = STM32F439PeripheralSet()
   # Includes: RCC, GPIO×9, USART×6, SPI×3, I2C×3,
   #           DMA×2, CRYP, HASH, USB_OTG, ...

USB OTG Integration
===================

For USB device emulation, SLAB includes a USBIP bridge:

.. figure:: ../images/usb_architecture.png
   :alt: USB Architecture
   :align: center
   :width: 90%

   USB Path: Firmware → OTG Peripheral → USBIP → Host

1. Firmware writes to USB OTG registers
2. Python USB peripheral interprets protocol
3. USBIP server presents virtual USB device
4. Host system sees ``/dev/ttyACM0`` (CDC) or other device

Visualization Integration
=========================

The debug dashboard connects to peripheral callbacks:

.. code-block:: python

   # GPIO → LED display
   gpio.on_pin_change = lambda pin, val, out: \
       dashboard.set_led(f"P{pin}", val)

   # UART → Console
   usart.on_tx = lambda byte: \
       dashboard.add_uart_byte(byte)

   # All signals → Logic analyzer
   capture.record("GPIO_PA5", value)

Hardware-in-the-Loop Integration
=================================

SLAB supports selective hardware forwarding where specific peripheral
address ranges are proxied to real silicon via debug probes, while
all other peripherals remain emulated locally.

.. code-block:: text

   Firmware → QEMU → Proxy → Python Server
                                ├── Emulated: RCC, GPIO, USART, Flash, ...
                                └── HIL: CRYP, HASH → pyOCD → Real MCU (SWD)

HIL peripherals are configured in board YAML using ``type: HIL``:

.. code-block:: yaml

   external_devices:
     - type: HIL
       bus: CRYP
       params:
         backend: pyocd
         target_type: stm32f439xi
         base: "0x50060000"
         size: "0x400"
         shared_session: true

**Supported backends:**

- **pyOCD**: Direct Python API to CMSIS-DAP, ST-Link, J-Link probes
- **OpenOCD**: TCL interface to running OpenOCD instance
- **Serial**: UART bridge firmware on target MCU
- **TCP**: Remote hardware server
- **Replay**: Offline replay of recorded HIL traces

**Key features:**

- Session sharing across multiple MMIO regions (one probe connection)
- Trace recording (JSON Lines) for every forwarded access
- Offline replay without hardware for CI integration
- ``CortexM`` / ``Emulator`` adapter classes for Avatar2-style workflows

Typical latency is 1-5 ms per forwarded access over SWD, which is acceptable
for peripheral initialization sequences and register configuration, but not
for tight polling loops. The selective approach ensures only the peripherals
that need real silicon are forwarded.

See :ref:`hardware_in_the_loop` for a complete tutorial.


Next Steps
==========

* :ref:`proxy_protocol` - Detailed protocol specification
* :ref:`peripheral_model` - Peripheral implementation guide
* :ref:`hardware_in_the_loop` - Hardware-in-the-Loop tutorial
* :ref:`api/slab_cortex_m` - Core API reference
