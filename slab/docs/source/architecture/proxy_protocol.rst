.. _proxy_protocol:

=======================
Peripheral Proxy Protocol
=======================

This document specifies the binary protocol between QEMU and the Python
peripheral server.

Overview
========

The protocol uses a simple request-response model over TCP or shared memory:

.. code-block:: text

   QEMU (Client)                Python Server
        │                            │
        │──── Request (9 bytes) ────→│
        │                            │ Process
        │←─── Response (5 bytes) ────│
        │                            │

TCP Mode
========

Default port: 5000

Connection is established when QEMU starts. The Python server must be
listening before QEMU connects.

SHM Mode
========

POSIX shared memory path: ``/dev/shm/slab_peripheral``

Uses lock-free ring buffers for zero-copy communication:

.. code-block:: text

   Shared Memory Layout (4KB):
   ┌────────────────────────────────────────┐
   │ Header (64 bytes)                      │
   │   request_head, request_tail           │
   │   response_head, response_tail         │
   ├────────────────────────────────────────┤
   │ Request Ring Buffer (2KB)              │
   ├────────────────────────────────────────┤
   │ Response Ring Buffer (2KB)             │
   └────────────────────────────────────────┘

Request Format
==============

9 bytes total:

.. code-block:: text

   Offset  Size  Field       Description
   ──────────────────────────────────────────────
   0x00    1     Command     Operation type
   0x01    4     Address     MMIO address (little-endian)
   0x05    4     Size        Access size (1, 2, or 4)

For write operations, 5 additional bytes follow:

.. code-block:: text

   0x09    4     Value       Write value (little-endian)
   0x0D    1     Secure      Security state (TrustZone)

Commands
--------

.. list-table::
   :widths: 10 10 80
   :header-rows: 1

   * - Code
     - Char
     - Description
   * - 0x52
     - 'R'
     - Non-Secure read (8/16/32-bit based on Size)
   * - 0x57
     - 'W'
     - Non-Secure write
   * - 0x53
     - 'S'
     - Secure read (TrustZone)
   * - 0x54
     - 'T'
     - Secure write (TrustZone)
   * - 0x49
     - 'I'
     - IRQ injection (server → QEMU)
   * - 0x58
     - 'X'
     - Reset notification

Response Format
===============

5 bytes total:

.. code-block:: text

   Offset  Size  Field       Description
   ──────────────────────────────────────────────
   0x00    4     Value       Read value (little-endian)
   0x04    1     Status      Result status

Status Codes
------------

.. list-table::
   :widths: 10 90
   :header-rows: 1

   * - Code
     - Description
   * - 0
     - OK - Operation completed successfully
   * - 1
     - Error - Generic error (e.g., unhandled address)
   * - 2
     - Security Fault - Non-Secure access to Secure region

IRQ Injection
=============

The server can inject interrupts into QEMU:

.. code-block:: text

   IRQ Request (6 bytes):
   ──────────────────────────────────────────────
   0x00    1     Command     'I' (0x49)
   0x01    4     IRQ Number  NVIC IRQ number
   0x05    1     Level       0=clear, 1=set

Example: Trigger USART2 interrupt (IRQ 38):

.. code-block:: python

   # Set IRQ 38
   writer.write(b'I' + struct.pack('<IB', 38, 1))

   # Clear IRQ 38
   writer.write(b'I' + struct.pack('<IB', 38, 0))

Protocol Examples
=================

Read GPIOA ODR (0x40020014)
---------------------------

Request:

.. code-block:: text

   52 14 00 02 40 04 00 00 00
   │  └─────────┘  └───────┘
   │   Address     Size (4)
   Command (Read)

Response:

.. code-block:: text

   00 20 00 00 00
   └─────────┘  │
    Value=0x2000 Status=OK

Write GPIOA BSRR (0x40020018) = 0x00002000
------------------------------------------

Request:

.. code-block:: text

   57 18 00 02 40 04 00 00 00 00 20 00 00 00
   │  └─────────┘  └───────┘  └─────────┘  │
   │   Address     Size (4)   Value        Secure=0
   Command (Write)

Response:

.. code-block:: text

   00 00 00 00 00
   └─────────┘  │
    Ignored    Status=OK

TrustZone Secure Read (0x50020014)
----------------------------------

Request:

.. code-block:: text

   53 14 00 02 50 04 00 00 00
   │  └─────────┘  └───────┘
   │   Secure addr  Size (4)
   Command (Secure Read)

Python Implementation
=====================

Server side:

.. code-block:: python

   async def handle_qemu(reader, writer, ps):
       """Handle QEMU peripheral proxy."""
       while True:
           # Read header
           hdr = await reader.read(9)
           if len(hdr) < 9:
               break

           cmd = hdr[0]
           addr = int.from_bytes(hdr[1:5], "little")
           sz = int.from_bytes(hdr[5:9], "little")

           secure = cmd in (ord('S'), ord('T'))

           if cmd in (ord('R'), ord('S')):
               # Read operation
               await reader.read(1)  # Discard padding
               val, status = ps.read(addr, sz, secure)
               writer.write(struct.pack('<IB', val, status))

           else:
               # Write operation
               data = await reader.read(5)
               val = int.from_bytes(data[:4], "little")
               status = ps.write(addr, sz, val, secure)
               writer.write(struct.pack('<IB', 0, status))

           await writer.drain()

Performance Considerations
==========================

1. **Batching**: QEMU may batch multiple requests before waiting for responses
2. **Nagle's Algorithm**: Disable for TCP (``TCP_NODELAY``)
3. **Buffer Sizes**: Use socket buffer tuning for high-throughput
4. **SHM Alignment**: Align ring buffer entries to cache lines (64 bytes)

Measured Performance
--------------------

.. list-table::
   :widths: 30 20 50
   :header-rows: 1

   * - Configuration
     - Latency
     - Throughput
   * - TCP (localhost)
     - ~45 μs
     - ~22K ops/sec
   * - TCP (Nagle off)
     - ~25 μs
     - ~40K ops/sec
   * - POSIX SHM
     - ~3 μs
     - ~330K ops/sec
