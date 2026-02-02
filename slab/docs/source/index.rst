.. MCUemu documentation master file

====================================
MCUemu - MCU Emulation Platform
====================================

**MCUemu** is a QEMU-based platform for ARM Cortex-M firmware emulation with Python peripheral control.
It enables firmware testing, peripheral prototyping, and security research without custom QEMU recompilation.

.. image:: images/mcuemu_architecture.png
   :alt: MCUemu Architecture
   :align: center
   :width: 80%

Key Features
------------

* **Generic QEMU Machine**: Single ``slab-cortex-m`` machine supporting all Cortex-M variants (M0 to M85)
* **Python Peripheral Control**: All MMIO accesses forwarded to Python via TCP or shared memory
* **Multi-MCU Support**: STM32, NXP, Nordic, RP2040/2350 peripheral libraries included
* **Real-time Visualization**: Debug dashboard with logic analyzer, console I/O, and LED status
* **Export Formats**: VCD and Sigrok-compatible captures for external analysis

Quick Example
-------------

.. code-block:: python

   from slab_stm32 import STM32F439PeripheralSet

   # Create peripheral set
   ps = STM32F439PeripheralSet()

   # Access CRYP for AES encryption
   ps.cryp.set_key(b'0123456789abcdef')
   ciphertext = ps.cryp.encrypt_block(b'Hello, MCUemu!!\x00')

Documentation
-------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   tutorials/quickstart
   tutorials/first_emulation
   tutorials/peripheral_basics

.. toctree::
   :maxdepth: 2
   :caption: Tutorials

   tutorials/stubbing_peripherals
   tutorials/creating_ui_peripherals
   tutorials/debugging_bootloops
   tutorials/trustzone_emulation

.. toctree::
   :maxdepth: 2
   :caption: Architecture

   architecture/overview
   architecture/proxy_protocol
   architecture/peripheral_model

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/slab_cortex_m
   api/slab_stm32
   api/slab_gui

.. toctree::
   :maxdepth: 1
   :caption: Additional Resources

   references
   changelog

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
