.. _creating_boards:

============================
Creating Board Configurations
============================

This tutorial teaches you how to create custom board configurations in the SLAB framework,
from understanding the MCU registry to running firmware on a fully-configured board.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>

Copyright (C) 2026 TwistedWires Security Lab

Introduction: The Board Abstraction
====================================

In SLAB, a **board** is a complete hardware configuration that combines:

1. **MCU/SoC**: The microcontroller with its peripheral set (UART, SPI, GPIO, etc.)
2. **External Devices**: Components connected to the MCU (SPI flash, I2C EEPROM, LEDs, displays)
3. **Memory Layout**: Flash and SRAM base addresses and sizes for QEMU
4. **Clock Configuration**: System clock frequency in Hz

The board abstraction allows you to define complete embedded systems declaratively using YAML or JSON files,
which are then assembled into a working emulation environment by the board builder.

.. figure:: ../images/board_architecture.png
   :alt: Board Architecture
   :align: center
   :width: 80%

   Board Architecture: MCU Peripheral Set + External Devices + Memory Layout


Step 1: Understanding the MCU Registry
=======================================

The MCU registry in ``board.py`` maps MCU names to their peripheral set implementations.
Each entry specifies:

- **Package Name**: Python module containing the peripheral set (e.g., ``slab_stm32``)
- **Class Name**: Peripheral set class (e.g., ``STM32F405PeripheralSet``)
- **QEMU CPU**: Default CPU type for QEMU (e.g., ``cortex-m4``)
- **Default Clock**: Default system clock in Hz (e.g., ``168_000_000``)

Current MCU Registry
--------------------

.. code-block:: python

   MCU_REGISTRY = {
       # STM32 Family
       "STM32F030":  ("slab_stm32", "STM32F0xxPeripheralSet",  "cortex-m0",   48_000_000),
       "STM32F103":  ("slab_stm32", "STM32F103PeripheralSet",  "cortex-m3",   72_000_000),
       "STM32F405":  ("slab_stm32", "STM32F405PeripheralSet",  "cortex-m4",  168_000_000),
       "STM32F407":  ("slab_stm32", "STM32F407PeripheralSet",  "cortex-m4",  168_000_000),
       "STM32F439":  ("slab_stm32", "STM32F439PeripheralSet",  "cortex-m4",  180_000_000),
       "STM32L433":  ("slab_stm32", "STM32L4xxPeripheralSet",  "cortex-m4",   80_000_000),
       "STM32H563":  ("slab_stm32", "STM32H563PeripheralSet",  "cortex-m33", 250_000_000),
       "STM32H745":  ("slab_stm32", "STM32H7xxPeripheralSet",  "cortex-m7",  480_000_000),
       "STM32U585":  ("slab_stm32", "STM32U585PeripheralSet",  "cortex-m33", 160_000_000),
       "STM32WB55":  ("slab_stm32", "STM32WB55PeripheralSet",  "cortex-m4",   64_000_000),

       # Nordic Semiconductor
       "nRF52840":   ("slab_nrf",   "NRF52840PeripheralSet",   "cortex-m4",   64_000_000),
       "nRF5340":    ("slab_nrf",   "NRF5340AppPeripheralSet", "cortex-m33", 128_000_000),

       # NXP
       "LPC55S69":   ("slab_nxp",   "LPC55S69PeripheralSet",   "cortex-m33", 150_000_000),
       "IMXRT1060":  ("slab_nxp",   "IMXRT1060PeripheralSet",  "cortex-m7",  600_000_000),

       # Raspberry Pi
       "RP2040":     ("slab_rp2040", "RP2040PeripheralSet",    "cortex-m0",  125_000_000),
       "RP2350":     ("slab_rp2040", "RP2350PeripheralSet",    "cortex-m33", 150_000_000),
   }

The registry enables automatic peripheral set creation: just specify the MCU name in your board YAML,
and SLAB will import the correct module and instantiate the peripheral set.


Step 2: Writing a Board YAML Configuration
===========================================

Board configurations are defined in YAML (or JSON) files. Here's a complete annotated example:

Basic Board: STM32F405 with SPI Flash
--------------------------------------

.. code-block:: yaml

   name: STM32F405_SPI_Flash
   mcu: STM32F405

   external_devices:
     - type: W25Q128              # Winbond 128Mbit SPI NOR flash
       bus: SPI1                  # Connected to SPI1 peripheral
     - type: LED                  # Status LED
       bus: GPIOA                 # Connected to GPIOA
       params:
         pin: 5                   # Pin PA5
         color: green             # LED color (for visualization)

This minimal configuration:

- Names the board ``STM32F405_SPI_Flash``
- Uses the ``STM32F405`` MCU (168 MHz Cortex-M4)
- Connects a W25Q128 SPI flash to SPI1
- Connects a green LED to GPIOA pin 5

Clock Override Example
----------------------

.. code-block:: yaml

   name: STM32L433_I2C_EEPROM
   mcu: STM32L433
   clock: 80000000              # Override default clock (80 MHz)

   external_devices:
     - type: 24C256             # 256Kbit I2C EEPROM
       bus: I2C1
       params:
         address: 0x50          # I2C 7-bit address
     - type: LED
       bus: GPIOB
       params:
         pin: 13
         color: green

The ``clock`` field overrides the default system clock from the MCU registry.


Step 3: Supported External Device Types
========================================

SLAB supports various external device types that can be wired to MCU peripherals.

SPI Devices
-----------

**Winbond W25Qxx SPI NOR Flash**

Supported models: W25Q16, W25Q32, W25Q64, W25Q128, W25Q256

.. code-block:: yaml

   - type: W25Q128
     bus: SPI1                  # STM32 SPI or Nordic SPIM/QSPI

**ILI9341 TFT LCD Display**

240x320 pixel TFT display with SPI interface:

.. code-block:: yaml

   - type: ILI9341
     bus: SPI1

I2C Devices
-----------

**24Cxx I2C EEPROM**

Supported models: 24C02, 24C04, 24C08, 24C16, 24C32, 24C64, 24C128, 24C256, 24C512

.. code-block:: yaml

   - type: 24C256
     bus: I2C1
     params:
       address: 0x50            # I2C 7-bit address (default: 0x50)

**SSD1306 OLED Display**

128x64 pixel OLED display with I2C interface:

.. code-block:: yaml

   - type: SSD1306
     bus: I2C1
     params:
       address: 0x3C            # I2C address (default: 0x3C)

GPIO Devices
------------

**LED Indicators**

LEDs are tracked for visualization and testing:

.. code-block:: yaml

   - type: LED
     bus: GPIOA
     params:
       pin: 13                  # GPIO pin number
       color: green             # Color for GUI display


Step 4: QEMU Memory Layout Configuration
=========================================

Different MCU families have different memory layouts. SLAB allows you to override the default
QEMU memory configuration using the ``qemu_extra`` field.

Default Memory Layouts by MCU Family
-------------------------------------

**STM32F4xx (Default)**

- Flash base: ``0x08000000``
- SRAM base: ``0x20000000``
- No override needed for standard configurations

**Nordic nRF52840**

Flash starts at address 0:

.. code-block:: yaml

   qemu_extra:
     flash-base: "0x00000000"

**Raspberry Pi RP2040**

Flash mapped to XIP region:

.. code-block:: yaml

   qemu_extra:
     flash-base: "0x10000000"

**STM32H563 with TrustZone**

Custom secure memory regions:

.. code-block:: yaml

   qemu_extra:
     flash-base: "0x0C000000"
     sram-base: "0x30000000"
     sram-size: "0x50000"       # 320 KB SRAM

Complete TrustZone Example
---------------------------

.. code-block:: yaml

   name: STM32H563_TZ
   mcu: STM32H563
   clock: 250000000
   qemu_extra:
     flash-base: "0x0C000000"   # Secure flash base
     sram-base: "0x30000000"    # Secure SRAM base
     sram-size: "0x50000"       # SRAM size
   external_devices:
     - type: LED
       bus: GPIOA
       params:
         pin: 5
         color: green


Step 5: How board_builder.py Assembles Boards
==============================================

The ``build_board()`` function in ``board_builder.py`` orchestrates the board assembly process.
Understanding this flow helps debug wiring issues and extend SLAB with new device types.

Assembly Flow
-------------

1. **Create MCU Peripheral Set**

   The builder looks up the MCU name in the registry and dynamically imports the peripheral set class:

   .. code-block:: python

      # From MCU_REGISTRY: ("slab_stm32", "STM32F405PeripheralSet", ...)
      pset = create_peripheral_set(config)

2. **Wrap in PeripheralSetAdapter**

   The adapter provides a unified memory-mapped interface for QEMU:

   .. code-block:: python

      adapter = PeripheralSetAdapter(pset)
      board = Board(config, adapter)

3. **Create External Devices**

   Each device in ``external_devices`` is instantiated:

   .. code-block:: python

      for dev_cfg in config.external_devices:
          device = _create_external_device(dev_cfg)  # W25QxxFlash, EEPROM_24Cxx, etc.
          board.external_devices.append(device)

4. **Wire Devices to Bus Peripherals**

   Devices are connected to their bus peripherals (SPI, I2C, GPIO):

   .. code-block:: python

      _wire_device(board, dev_cfg, device)

5. **Wire UART Console Capture**

   All UART/USART peripherals are wired to capture console output:

   .. code-block:: python

      _wire_uart(board)

6. **Wire LED GPIO Tracking**

   LED GPIO pin changes are tracked in ``board.led_states``:

   .. code-block:: python

      _wire_leds(board)

The result is a fully-assembled ``Board`` object ready for emulation.


Step 6: Understanding Wiring Conventions
=========================================

Different MCU families use different bus protocols. SLAB's wiring layer bridges these differences
to provide a uniform device interface.

SPI Wiring
----------

**STM32 SPI: Byte-Level Transfer**

STM32 SPI peripherals use byte-level callbacks:

.. code-block:: python

   def on_transfer(mosi_byte: int) -> int:
       """Called for each byte written to SPI DR register."""
       return miso_byte

The W25Qxx flash device provides ``transfer_byte(mosi: int) -> int`` which is directly wired:

.. code-block:: python

   spi_peripheral.on_transfer = w25q_flash.transfer_byte

**Nordic SPIM/QSPI: Packet-Level Transfer**

Nordic peripherals use DMA-based packet transfers:

.. code-block:: python

   def on_transfer(mosi_packet: bytes) -> bytes:
       """Called when DMA transfer completes."""
       return miso_packet

The wiring layer wraps the device with chip select handling:

.. code-block:: python

   def spim_transfer(mosi):
       device.select()
       result = device.transfer(mosi)
       device.deselect()
       return result

   spim_peripheral.on_transfer = spim_transfer

I2C Wiring
----------

**STM32 I2C: State Machine Callbacks**

STM32 I2C uses separate callbacks for I2C protocol states:

.. code-block:: python

   def on_start(addr_7bit: int, is_read: bool):
       """Called on START condition."""

   def on_write(byte: int):
       """Called on data byte write."""

   def on_read() -> int:
       """Called on data byte read."""

   def on_stop():
       """Called on STOP condition."""

SLAB uses ``_I2CDeviceAdapter`` to bridge byte-level callbacks to packet-level device protocol:

.. code-block:: python

   adapter = _I2CDeviceAdapter(eeprom_device)
   i2c_peripheral.on_start = adapter.on_start
   i2c_peripheral.on_write = adapter.on_write
   i2c_peripheral.on_read = adapter.on_read
   i2c_peripheral.on_stop = adapter.on_stop

**Nordic TWIM: Packet-Level Transfer**

Nordic I2C (TWIM) uses DMA-based packet transfers:

.. code-block:: python

   def on_transfer(addr_7bit: int, data: bytes, is_read: bool) -> bytes:
       """Called when TWIM DMA transfer completes."""
       if is_read:
           return read_data
       else:
           return b''

GPIO Wiring
-----------

LED tracking uses GPIO pin-change callbacks:

.. code-block:: python

   def on_pin_change(pin: int, value: bool, is_output: bool):
       """Called when GPIO output changes."""
       if pin == led_pin:
           board.led_states[led_key]['state'] = value


Step 7: Running Firmware on Your Board
=======================================

Once your board YAML is ready, you can run firmware using the SLAB emulation infrastructure.

Using the CI Runner
-------------------

The ``ci_runner.py`` module provides a scenario-based test runner:

.. code-block:: bash

   # Start the SLAB Python server
   PYTHONPATH=slab/python python3 -m slab_cortex_m.ci_runner \
       --scenario scenarios/my_scenario.yaml

A scenario YAML references your board configuration:

.. code-block:: yaml

   name: SPI Flash Test
   board: boards/stm32f405_spi_flash.yaml
   firmware: firmware/spi_flash_test.elf
   timeout: 10.0
   checks:
     - type: uart_output
       contains: "Flash ID: 0xEF4018"

Using the E2E Test Runner
--------------------------

For integration testing:

.. code-block:: bash

   # Run end-to-end firmware tests
   PYTHONPATH=slab/python python3 slab/tests/e2e_firmware_test.py

Manual Emulation
----------------

For interactive debugging, load your board in Python:

.. code-block:: python

   from slab_cortex_m.board import load_board_config
   from slab_cortex_m.board_builder import build_board

   # Load board configuration
   config = load_board_config("boards/stm32f405_spi_flash.yaml")

   # Build the board
   board = build_board(config)

   # Access peripherals
   print(f"Board: {board.name}")
   print(f"Peripherals: {len(board.adapter.peripherals)}")
   print(f"External devices: {len(board.external_devices)}")

   # Read/write memory-mapped registers
   rcc_cr = board.read(0x40023800, 4)  # STM32F4 RCC CR register
   print(f"RCC CR: 0x{rcc_cr:08X}")


Best Practices
==============

1. **Start Simple**: Begin with a minimal board (MCU + LED), then add devices incrementally
2. **Use Existing Boards as Templates**: Copy and modify boards from ``slab/boards/``
3. **Test Device Wiring**: Verify each external device works before adding more
4. **Check Console Output**: Enable UART logging to debug initialization issues
5. **Match Real Hardware**: Use the same memory layout and clock frequency as your target board

Example: Creating a Custom STM32F407 Board
-------------------------------------------

.. code-block:: yaml

   name: Custom_STM32F407
   mcu: STM32F407
   clock: 168000000

   external_devices:
     # SPI NOR flash for firmware storage
     - type: W25Q64
       bus: SPI1

     # I2C EEPROM for configuration
     - type: 24C128
       bus: I2C1
       params:
         address: 0x50

     # Status LEDs
     - type: LED
       bus: GPIOD
       params: {pin: 12, color: green}

     - type: LED
       bus: GPIOD
       params: {pin: 13, color: orange}


Next Steps
==========

- :ref:`first_emulation`: Run your first firmware on a custom board
- :ref:`stubbing_peripherals`: Add custom peripheral implementations
- :ref:`debugging_bootloops`: Debug firmware initialization issues
- :ref:`trustzone_emulation`: Configure TrustZone-enabled boards

For questions and support, see the project documentation at https://github.com/twistedwires/slab
