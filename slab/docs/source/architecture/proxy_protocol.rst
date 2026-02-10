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

   QEMU (Client)                    Python Server
        |                                |
        |--- Request (14 or 18 bytes) -->|
        |                                | Process
        |<----- Response (5 bytes) ------|
        |                                |
        |<--- IRQ Injection (6 bytes) ---|  (async, server-initiated)
        |                                |

TCP Mode
========

Default port: 5555

Connection is established when QEMU starts. The Python server must be
listening before QEMU connects.

SHM Mode
========

POSIX shared memory (``/dev/shm/slab_<name>``).

Uses a flat header layout for lock-free polling-based communication:

.. code-block:: text

   Shared Memory Layout:
   +--------------------------------------------+
   | Header (64 bytes = 16 x uint32_t)          |
   |   [0]  Magic    (0x534C4142 = "SLAB")      |
   |   [1]  Version  (1 or 2)                   |
   |   [2]  Command  (from QEMU)                |
   |   [3]  Status   (from Python)              |
   |   [4]  Address  (32-bit)                   |
   |   [5]  Data     (32-bit)                   |
   |   [6]  Size                                |
   |   [7]  Sequence number                     |
   |   [8]  IRQ bitmap (bits 0-31)              |
   |   [9]  Snapshot flags                      |
   |   [10] Bus attributes (packed)             |
   |   [11] PC (program counter)                |
   |   [12-15] Reserved                         |
   +--------------------------------------------+
   | Peripheral data region (from offset 64)    |
   +--------------------------------------------+

QEMU writes a command and increments the sequence number; the Python server
polls the sequence number, processes the command, writes the status/data back,
and sets the command word to NOP. IRQ delivery uses an IRQ bitmap at word [8]
with delta-based change detection.

Request Format (TCP)
====================

Read request: **14 bytes** total.

.. code-block:: text

   Offset  Size  Field       Description
   -----------------------------------------------
   0x00    1     Command     'R' (0x52) or 'S' (0x53)
   0x01    4     Address     MMIO address (little-endian)
   0x05    4     Size        Access size (1, 2, or 4)
   0x09    1     Secure      Security state (0=NS, 1=Secure)
   0x0A    4     PC          Program counter (little-endian)

Write request: **18 bytes** total.

.. code-block:: text

   Offset  Size  Field       Description
   -----------------------------------------------
   0x00    1     Command     'W' (0x57) or 'T' (0x54)
   0x01    4     Address     MMIO address (little-endian)
   0x05    4     Size        Access size (1, 2, or 4)
   0x09    4     Value       Write value (little-endian)
   0x0D    1     Secure      Security state (0=NS, 1=Secure)
   0x0E    4     PC          Program counter (little-endian)

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
     - IRQ injection (server -> QEMU)
   * - 0x58
     - 'X'
     - Reset notification

Response Format
===============

5 bytes total:

.. code-block:: text

   Offset  Size  Field       Description
   -----------------------------------------------
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
   -----------------------------------------------
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

Request (14 bytes):

.. code-block:: text

   52 14 00 02 40 04 00 00 00 00 00 00 10 08
   |  +---------+  +-------+  |  +---------+
   |   Address     Size (4) Sec=0   PC
   Command (Read)

Response (5 bytes):

.. code-block:: text

   00 20 00 00 00
   +---------+  |
    Value=0x2000 Status=OK

Write GPIOA BSRR (0x40020018) = 0x00002000
-------------------------------------------

Request (18 bytes):

.. code-block:: text

   57 18 00 02 40 04 00 00 00 00 20 00 00 00 00 00 10 08
   |  +---------+  +-------+  +---------+  |  +---------+
   |   Address     Size (4)   Value      Sec=0   PC
   Command (Write)

Response (5 bytes):

.. code-block:: text

   00 00 00 00 00
   +---------+  |
    Ignored    Status=OK

Python Implementation
=====================

Server side (using ``BasePeripheralServer``):

.. code-block:: python

   async def handle_client(reader, writer):
       """Handle QEMU peripheral proxy."""
       while True:
           # Read command byte (1 byte)
           cmd_data = await reader.read(1)
           if not cmd_data:
               break
           cmd = cmd_data[0]

           if cmd in (0x52, 0x53):  # Read ('R' or 'S')
               data = await reader.readexactly(13)
               address, size = struct.unpack('<II', data[:8])
               secure = (cmd == 0x53) or (data[8] == 1)
               pc = struct.unpack('<I', data[9:13])[0]
               val, status = ps.read(address, size, secure)
               writer.write(struct.pack('<IB', val, status))

           elif cmd in (0x57, 0x54):  # Write ('W' or 'T')
               data = await reader.readexactly(17)
               address, size, value = struct.unpack('<III', data[:12])
               secure = (cmd == 0x54) or (data[12] == 1)
               pc = struct.unpack('<I', data[13:17])[0]
               status = ps.write(address, size, value, secure)
               writer.write(struct.pack('<IB', 0, status))

           await writer.drain()

Performance Considerations
==========================

1. **Non-blocking I/O**: QEMU uses a non-blocking state machine for TCP,
   avoiding 100% CPU spin on the main loop fd handler
2. **Nagle's Algorithm**: Disabled via ``TCP_NODELAY`` for low latency
3. **SHM Polling**: Adaptive timer (10us when CPU halted, 100us when running)
4. **IRQ Interleaving**: IRQ packets (6B) can arrive during transaction
   responses and are processed inline by the state machine

Measured Performance
--------------------

.. list-table::
   :widths: 30 20 50
   :header-rows: 1

   * - Configuration
     - Latency
     - Throughput
   * - TCP (localhost)
     - ~62 us
     - ~16K ops/sec
   * - POSIX SHM
     - ~26 us
     - ~39K ops/sec
