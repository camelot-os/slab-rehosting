.. _svd_to_peripheral:

====================================
From SVD to Peripheral Implementation
====================================

This tutorial teaches you how to go from a vendor-provided SVD file to a fully functional peripheral implementation in the SLAB framework. We'll walk through parsing SVD files, understanding register layouts, and creating emulated peripherals that behave like real hardware.

What are SVD Files?
===================

SVD (System View Description) files are XML files that describe the complete memory map of a microcontroller. They are part of the CMSIS (Cortex Microcontroller Software Interface Standard) specification and are provided by chip vendors.

An SVD file contains:

- Device information (CPU type, memory layout)
- Peripheral definitions (base addresses, sizes)
- Register maps (offsets, reset values, access types)
- Field definitions (bit positions, widths, descriptions)
- Interrupt mappings

.. note::

   SVD files are essential for peripheral emulation because they provide the ground truth for hardware behavior. Instead of manually transcribing data from 1000-page reference manuals, we can parse SVD files programmatically.

Why SVD Files Matter
--------------------

Consider the STM32F4 family: it has over 100 peripherals with thousands of registers. Manually implementing each register would be error-prone and time-consuming. SVD files provide:

- **Accuracy**: Vendor-verified register layouts
- **Completeness**: All registers, fields, and reset values
- **Consistency**: Standardized format across vendors
- **Documentation**: Field descriptions and enumerated values

Step 1: Finding SVD Files
==========================

Vendor Sources
--------------

SVD files are typically distributed in CMSIS Device Family Packs (DFPs):

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - Vendor
     - Download Source
     - Example Files
   * - STMicroelectronics
     - `Keil Pack Repository <https://www.keil.com/dd2/pack/>`_
     - ``STM32F4xx.svd``, ``STM32H7xx.svd``
   * - Nordic
     - `Nordic DevZone <https://www.nordicsemi.com/>`_
     - ``nrf52840.svd``
   * - NXP
     - `MCUXpresso <https://www.nxp.com/mcuxpresso>`_
     - ``LPC55S69.svd``
   * - ARM
     - `CMSIS Repository <https://github.com/ARM-software/CMSIS_5>`_
     - ``ARMCM4.svd``

SLAB Project SVD Files
----------------------

The SLAB project includes ARM reference SVD files at:

.. code-block:: text

   slab/examples/repos/CMSIS_5/Device/ARM/SVD/

Available files:

- ``ARMCM0.svd`` - Cortex-M0
- ``ARMCM3.svd`` - Cortex-M3
- ``ARMCM4.svd`` - Cortex-M4
- ``ARMCM7.svd`` - Cortex-M7
- ``ARMCM33.svd`` - Cortex-M33 (TrustZone)
- ``ARMCM55.svd`` - Cortex-M55 (Helium)

Step 2: Parsing with svd_parser.py
===================================

The SLAB framework includes a powerful SVD parser at ``/home/mre/projects/slab-rehosting/slab/python/slab_cortex_m/svd_parser.py``.

Basic Parsing
-------------

.. code-block:: python

   from slab_cortex_m.svd_parser import SVDParser

   # Create parser instance
   parser = SVDParser()

   # Parse SVD file
   device = parser.parse('slab/examples/repos/CMSIS_5/Device/ARM/SVD/ARMCM4.svd')

   # Display device info
   print(f"Device: {device.name}")
   print(f"CPU: {device.cpu_name}")
   print(f"FPU: {'Yes' if device.cpu_fpu_present else 'No'}")
   print(f"Peripherals: {len(device.peripherals)}")

   # List all peripherals with base addresses
   for p in device.peripherals:
       print(f"  {p.name:12s} @ 0x{p.base_address:08X} ({len(p.registers)} regs)")

Output:

.. code-block:: text

   Device: ARMCM4
   CPU: CM4
   FPU: Yes
   Peripherals: 15
     SysTick      @ 0xE000E010 (4 regs)
     NVIC         @ 0xE000E100 (68 regs)
     SCB          @ 0xE000ED00 (18 regs)
     SPI1         @ 0x40010000 (8 regs)
     UART0        @ 0x40011000 (6 regs)
     ...

Accessing Peripheral Information
---------------------------------

.. code-block:: python

   # Get specific peripheral
   spi = device.get_peripheral('SPI1')

   print(f"\nPeripheral: {spi.name}")
   print(f"Base: 0x{spi.base_address:08X}")
   print(f"Description: {spi.description}")

   # List interrupts
   for irq in spi.interrupts:
       print(f"  IRQ {irq.value}: {irq.name}")

Step 3: Understanding the Register Map
=======================================

Inspecting Registers
--------------------

.. code-block:: python

   # Get SPI peripheral
   spi = device.get_peripheral('SPI1')

   print(f"\nRegisters in {spi.name}:")
   for reg in spi.registers:
       print(f"  +0x{reg.address_offset:03X}  {reg.name:12s}  "
             f"{reg.access:12s}  reset=0x{reg.reset_value:08X}")

Output:

.. code-block:: text

   Registers in SPI1:
     +0x000  CR1           read-write    reset=0x00000000
     +0x004  CR2           read-write    reset=0x00000000
     +0x008  SR            read-only     reset=0x00000002
     +0x00C  DR            read-write    reset=0x00000000
     +0x010  CRCPR         read-write    reset=0x00000007

Examining Bit Fields
---------------------

Register fields define the individual control bits within registers:

.. code-block:: python

   # Get a specific register
   cr1 = spi.get_register_by_name('CR1')

   print(f"\nBit fields in {cr1.name}:")
   for field in sorted(cr1.fields, key=lambda f: f.bit_offset, reverse=True):
       msb = field.bit_offset + field.bit_width - 1
       lsb = field.bit_offset

       if field.bit_width == 1:
           print(f"    [{lsb:2d}]      {field.name:16s}  {field.description}")
       else:
           print(f"    [{msb:2d}:{lsb:2d}]  {field.name:16s}  {field.description}")

Output:

.. code-block:: text

   Bit fields in CR1:
       [15]      BIDIMODE         Bidirectional mode enable
       [14]      BIDIOE           Output enable in bidirectional mode
       [13]      CRCEN            Hardware CRC enable
       [11]      DFF              Data frame format (8/16 bit)
       [10]      RXONLY           Receive only mode
       [9]       SSM              Software slave management
       [6]       SPE              SPI enable
       [5:3]     BR               Baud rate control
       [2]       MSTR             Master selection
       [1]       CPOL             Clock polarity
       [0]       CPHA             Clock phase

Field Bit Masks
---------------

.. code-block:: python

   # Calculate bit masks from field definitions
   spe_field = cr1.get_field('SPE')
   print(f"SPE bit mask: 0x{spe_field.bit_mask:08X}")

   br_field = cr1.get_field('BR')
   print(f"BR bit mask: 0x{br_field.bit_mask:08X}")
   print(f"BR occupies bits {br_field.bit_offset} to "
         f"{br_field.bit_offset + br_field.bit_width - 1}")

Step 4: Creating a Peripheral Class
====================================

Now that we understand the register layout from SVD, we can create a peripheral implementation that inherits from ``STM32Peripheral``.

Peripheral Template
-------------------

.. code-block:: python

   from slab_stm32.stm32_base import STM32Peripheral

   class STM32SPI(STM32Peripheral):
       """
       STM32 SPI peripheral implementation.

       Based on SVD register map for SPI1.
       """

       # Register offsets (from SVD)
       CR1 = 0x00      # Control register 1
       CR2 = 0x04      # Control register 2
       SR = 0x08       # Status register
       DR = 0x0C       # Data register
       CRCPR = 0x10    # CRC polynomial register

       # CR1 bit fields (from SVD)
       CR1_CPHA = 1 << 0       # Clock phase
       CR1_CPOL = 1 << 1       # Clock polarity
       CR1_MSTR = 1 << 2       # Master mode
       CR1_BR_MASK = 0x7 << 3  # Baud rate mask
       CR1_SPE = 1 << 6        # SPI enable
       CR1_LSBFIRST = 1 << 7   # LSB first
       CR1_DFF = 1 << 11       # Data frame format

       # SR bit fields (from SVD)
       SR_RXNE = 1 << 0        # RX not empty
       SR_TXE = 1 << 1         # TX empty
       SR_BSY = 1 << 7         # Busy flag
       SR_OVR = 1 << 6         # Overrun flag

       def __init__(self, index, base):
           """
           Initialize SPI peripheral.

           Args:
               index: SPI number (1-6)
               base: Base address from SVD
           """
           super().__init__(f"SPI{index}", base, size=0x400, irq=35)

           # Initialize registers to reset values (from SVD)
           self.regs[self.SR] = self.SR_TXE  # TX empty on reset

           # Internal state
           self._rx_buffer = 0
           self._enabled = False

           # External device callback
           self.on_transfer = None

       def _read_reg(self, offset, size):
           """Handle register reads."""
           if offset == self.SR:
               # Return live status
               return self._get_status()
           elif offset == self.DR:
               # Read received data
               return self._read_data()
           else:
               # Default: return stored value
               return self.regs.get(offset, 0)

       def _write_reg(self, offset, size, value):
           """Handle register writes."""
           self.regs[offset] = value

           if offset == self.CR1:
               # Check if SPI was enabled
               self._enabled = bool(value & self.CR1_SPE)
               if self._enabled:
                   self.log.debug(f"SPI enabled, mode={self._get_mode()}")

           elif offset == self.DR:
               # Write triggers transfer
               self._transfer(value)

       def _get_status(self):
           """Compute live status register value."""
           sr = self.SR_TXE  # Always ready to transmit

           if self._rx_buffer is not None:
               sr |= self.SR_RXNE

           return sr

       def _read_data(self):
           """Read from data register."""
           data = self._rx_buffer if self._rx_buffer is not None else 0
           self._rx_buffer = None  # Clear RXNE
           return data

       def _transfer(self, tx_data):
           """Perform SPI transfer."""
           if not self._enabled:
               return

           # Get data width
           if self.regs.get(self.CR1, 0) & self.CR1_DFF:
               tx_data &= 0xFFFF  # 16-bit
           else:
               tx_data &= 0xFF    # 8-bit

           # Call external device if connected
           if self.on_transfer:
               self._rx_buffer = self.on_transfer(tx_data)
           else:
               self._rx_buffer = 0xFF  # Default: no device (pull-up)

           self.log.debug(f"Transfer: TX=0x{tx_data:02X} RX=0x{self._rx_buffer:02X}")

       def _get_mode(self):
           """Get SPI mode from CPOL/CPHA."""
           cr1 = self.regs.get(self.CR1, 0)
           cpol = bool(cr1 & self.CR1_CPOL)
           cpha = bool(cr1 & self.CR1_CPHA)

           modes = {
               (False, False): "MODE0",
               (False, True): "MODE1",
               (True, False): "MODE2",
               (True, True): "MODE3",
           }
           return modes.get((cpol, cpha), "UNKNOWN")

       def _reset_registers(self):
           """Reset to SVD-defined values."""
           self.regs.clear()
           self.regs[self.SR] = self.SR_TXE
           self.regs[self.CRCPR] = 0x0007
           self._enabled = False

.. tip::

   Always consult the SVD file for reset values. Many registers have non-zero reset values that firmware depends on.

Step 5: Adding to a Peripheral Set
===================================

Once your peripheral is implemented, add it to a peripheral set:

.. code-block:: python

   from slab_stm32.stm32_base import STM32PeripheralSet

   class MyDevicePeripherals(STM32PeripheralSet):
       """Custom peripheral set based on SVD."""

       def __init__(self):
           super().__init__("MyDevice", cpu_freq=72_000_000)

           # Parse SVD to get addresses
           parser = SVDParser()
           device = parser.parse('path/to/device.svd')

           # Create peripherals from SVD
           spi1_periph = device.get_peripheral('SPI1')
           self.spi1 = STM32SPI(1, spi1_periph.base_address)
           self.add_peripheral(self.spi1)

           spi2_periph = device.get_peripheral('SPI2')
           self.spi2 = STM32SPI(2, spi2_periph.base_address)
           self.add_peripheral(self.spi2)

Step 6: Testing Your Peripheral
================================

Always write tests for your peripherals. Here's a pytest example:

.. code-block:: python

   import pytest
   from slab_stm32.stm32_spi import STM32SPI

   class TestSPIPeripheral:
       """Test SPI peripheral implementation."""

       def setup_method(self):
           """Create SPI instance before each test."""
           self.spi = STM32SPI(index=1, base=0x40013000)

       def test_reset_values(self):
           """Verify reset values match SVD."""
           # SR should have TXE set
           sr, status = self.spi.read(0x40013008, 4)
           assert sr & 0x02  # TXE bit

       def test_enable_spi(self):
           """Test enabling SPI peripheral."""
           # Write CR1 with SPE bit
           self.spi.write(0x40013000, 4, 0x0040)  # SPE=1

           # Verify it was stored
           cr1, _ = self.spi.read(0x40013000, 4)
           assert cr1 & 0x0040

       def test_data_transfer(self):
           """Test SPI data transfer."""
           # Mock external SPI device
           received = []

           def mock_device(tx_byte):
               received.append(tx_byte)
               return 0xAA  # Return fixed value

           self.spi.on_transfer = mock_device

           # Enable SPI
           self.spi.write(0x40013000, 4, 0x0044)  # SPE | MSTR

           # Write data
           self.spi.write(0x4001300C, 4, 0x55)  # Write to DR

           # Verify callback was called
           assert received == [0x55]

           # Read received data
           rx, _ = self.spi.read(0x4001300C, 4)
           assert rx == 0xAA

       def test_16bit_mode(self):
           """Test 16-bit data frame format."""
           self.spi.on_transfer = lambda x: x ^ 0xFFFF

           # Enable SPI with 16-bit mode
           self.spi.write(0x40013000, 4, 0x0844)  # DFF | SPE | MSTR

           # Send 16-bit value
           self.spi.write(0x4001300C, 4, 0x1234)

           # Read result
           rx, _ = self.spi.read(0x4001300C, 4)
           assert rx == 0xEDCB  # 0x1234 ^ 0xFFFF

Run tests with:

.. code-block:: bash

   PYTHONPATH=/home/mre/projects/slab-rehosting/slab/python pytest test_my_peripheral.py -v

Step 7: Wiring External Devices
================================

Peripherals become useful when connected to external devices or other peripherals.

SPI Flash Example
-----------------

.. code-block:: python

   class SPIFlash:
       """Simple SPI Flash emulator."""

       def __init__(self, size=1024*1024):
           self.memory = bytearray(size)
           self.cmd = None
           self.addr = 0
           self.pos = 0

       def transfer(self, tx_byte):
           """Handle SPI byte transfer."""
           if self.cmd is None:
               # First byte is command
               self.cmd = tx_byte
               self.pos = 0
               return 0

           if self.cmd == 0x03:  # READ_DATA
               if self.pos < 3:
                   # Collect address bytes
                   self.addr = (self.addr << 8) | tx_byte
                   self.pos += 1
                   return 0
               else:
                   # Return data
                   data = self.memory[self.addr % len(self.memory)]
                   self.addr += 1
                   return data

           elif self.cmd == 0x9F:  # READ_ID
               jedec_id = [0xEF, 0x40, 0x18]  # Winbond W25Q128
               return jedec_id[min(self.pos, 2)]

           return 0xFF

   # Connect flash to SPI
   flash = SPIFlash()
   spi1.on_transfer = flash.transfer

UART Logging
------------

.. code-block:: python

   from slab_stm32.stm32_uart import STM32UART

   # Create UART
   uart = STM32UART(index=2, base=0x40004400)

   # Capture transmitted bytes
   output_buffer = []

   def on_uart_tx(byte):
       output_buffer.append(byte)
       print(chr(byte), end='', flush=True)

   uart.on_tx = on_uart_tx

   # Now firmware writes will be printed to console

GPIO Pin Change Callbacks
--------------------------

.. code-block:: python

   from slab_stm32.stm32_gpio import STM32GPIO

   # Create GPIO port
   gpioa = STM32GPIO(port='A', base=0x40020000)

   def on_pin_change(pin, value, is_output):
       """Called when firmware changes pin state."""
       if is_output:
           print(f"GPIOA Pin {pin}: {'HIGH' if value else 'LOW'}")

           # Example: Control external LED
           if pin == 5:
               external_led.set_state(value)

   gpioa.on_pin_change = on_pin_change

.. warning::

   Callbacks run in the emulation thread. Keep them lightweight and avoid blocking operations.

Advanced: Generating Peripheral Skeletons
==========================================

You can automate peripheral class generation from SVD files:

.. code-block:: python

   def generate_peripheral_skeleton(svd_path, peripheral_name):
       """Generate Python class skeleton from SVD."""
       parser = SVDParser()
       device = parser.parse(svd_path)
       periph = device.get_peripheral(peripheral_name)

       print(f"class STM32{peripheral_name}(STM32Peripheral):")
       print(f'    """')
       print(f'    {periph.description}')
       print(f'    """')
       print()

       # Generate register offset constants
       print("    # Register offsets")
       for reg in periph.registers:
           print(f"    {reg.name} = 0x{reg.address_offset:02X}")

       print()

       # Generate bit field constants
       for reg in periph.registers:
           if reg.fields:
               print(f"    # {reg.name} bits")
               for field in reg.fields:
                   if field.bit_width == 1:
                       print(f"    {reg.name}_{field.name} = 1 << {field.bit_offset}")
                   else:
                       mask = ((1 << field.bit_width) - 1) << field.bit_offset
                       print(f"    {reg.name}_{field.name}_MASK = 0x{mask:X}")

   # Usage
   generate_peripheral_skeleton('device.svd', 'SPI1')

Summary
=======

In this tutorial, you learned:

1. Where to find SVD files (vendor packs, CMSIS repository)
2. How to parse SVD files with ``SVDParser``
3. How to inspect peripherals, registers, and bit fields
4. How to create peripheral classes from SVD data
5. How to add peripherals to peripheral sets
6. How to write tests for your peripherals
7. How to wire external devices using callbacks

SVD files bridge the gap between hardware documentation and software emulation, enabling accurate and maintainable peripheral implementations.

Next Steps
==========

- :ref:`peripheral_basics` - Understand MMIO and peripheral architecture
- :ref:`stubbing_peripherals` - Create minimal peripheral stubs
- :ref:`creating_ui_peripherals` - Add GUI controls to peripherals

.. note::

   Author: Mathieu Renard <mathieu.renard@twistedwires.io>

   Copyright (C) 2026 TwistedWires Security Lab
