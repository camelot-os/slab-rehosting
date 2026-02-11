.. _peripheral_hooks:

==============================
Peripheral Hooks Reference
==============================

Complete reference for all hookable callbacks exposed by SLAB peripheral
models. Hooks let you intercept UART output, SPI/I2C bus traffic, GPIO
changes, CAN frames, ADC samples, and IRQs -- without modifying the
peripheral source code.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>

Copyright (C) 2026 Twisted Wires Security Lab


How Hooks Work
==============

Every SLAB peripheral declares optional callback attributes initialised to
``None``. When a callback is set, the peripheral calls it at the appropriate
point in its state machine. If the callback is ``None``, the peripheral uses
a sensible default (0xFF for SPI, empty bytes for I2C, etc.).

.. code-block:: python

   # Generic pattern -- all hooks follow this
   class SomePeripheral:
       def __init__(self):
           self.on_tx = None          # Callable or None

       def _do_transmit(self, byte):
           if self.on_tx:
               self.on_tx(byte)       # Call the hook

Setting a hook is a simple assignment:

.. code-block:: python

   peripheral.on_tx = my_handler

Hooks are wired **after** the peripheral set is created, either manually
(direct mode) or automatically by ``build_board()`` (board mode).
See :ref:`server_modes` for the two approaches.


Quick Reference Table
=====================

.. list-table::
   :header-rows: 1
   :widths: 16 18 30 18

   * - Bus
     - Callback
     - Signature
     - Peripherals
   * - UART
     - ``on_tx``
     - ``(byte: int) -> None``
     - STM32 USARTv1/v2, NXP LPUART
   * - UART
     - ``on_tx``
     - ``(data: bytes) -> None``
     - NRF UARTE, RP2040 PL011, LPC Flexcomm
   * - UART
     - ``on_tx_empty``
     - ``() -> None``
     - RP2040 PL011
   * - SPI
     - ``on_transfer``
     - ``(tx: int) -> int``
     - STM32 SPIv1/v2, RP2040 SPI
   * - SPI
     - ``on_transfer``
     - ``(tx: bytes) -> bytes``
     - NRF SPIM, LPC Flexcomm SPI
   * - SPI
     - ``on_transfer``
     - ``(tx: int, frame_size: int) -> int``
     - NXP LPSPI
   * - I2C
     - ``on_start``
     - ``(addr_7bit: int, is_read: bool) -> None``
     - STM32 I2Cv1/v2
   * - I2C
     - ``on_write``
     - ``(byte: int) -> None``
     - STM32 I2Cv1/v2
   * - I2C
     - ``on_read``
     - ``() -> int``
     - STM32 I2Cv1/v2
   * - I2C
     - ``on_stop``
     - ``() -> None``
     - STM32 I2Cv1/v2
   * - I2C
     - ``on_transfer``
     - ``(addr: int, data: bytes, is_read: bool) -> bytes``
     - NRF TWIM, LPC Flexcomm I2C
   * - I2C
     - ``on_write``
     - ``(addr: int, data: bytes) -> bool``
     - RP2040 I2C
   * - I2C
     - ``on_read``
     - ``(addr: int, count: int) -> bytes``
     - RP2040 I2C
   * - QSPI
     - ``on_flash_access``
     - ``(op: str, addr: int, data: bytes) -> bytes``
     - NRF QSPI
   * - QSPI
     - ``on_custom_instruction``
     - ``(opcode: int, data_in: bytes) -> bytes``
     - NRF QSPI
   * - GPIO
     - ``on_pin_change``
     - ``(pin: int, value: int, is_output: int) -> None``
     - STM32 GPIOv1/v2
   * - GPIO
     - ``on_gpio_change``
     - ``(gpio_out: int, gpio_oe: int) -> None``
     - RP2040 SIO
   * - CAN
     - ``on_tx``
     - ``(msg: CANMessage) -> None``
     - CAN Controller
   * - CAN
     - ``on_rx``
     - ``(msg: CANMessage) -> None``
     - CAN Controller
   * - ADC
     - ``on_sample``
     - ``(channel: int) -> int``
     - RP2040 ADC, NXP ADC, LPC ADC
   * - IRQ
     - ``irq_callback``
     - ``(irq_num: int, level: int) -> None``
     - All peripherals


UART Hooks
==========

Every USART/UART peripheral exposes an ``on_tx`` callback fired when
firmware writes a byte to the transmit data register.

STM32 USART (byte-level)
--------------------------

Defined in ``slab/python/slab_stm32/stm32_usart.py``.

Both USARTv1 (F1/F4 -- SR/DR style) and USARTv2 (L4/H5/U5 -- ISR/TDR
style) use the same signature:

.. code-block:: python

   # Signature: (byte: int) -> None
   # Called when firmware writes to DR (v1) or TDR (v2) with TE enabled.

   usart.on_tx = lambda byte: print(chr(byte & 0x7F), end='')

NRF UARTE (packet-level)
--------------------------

Defined in ``slab/python/slab_nrf/nrf_uart.py``.

Nordic UARTE uses EasyDMA, so the callback receives bytes:

.. code-block:: python

   # Signature: (data: bytes) -> None
   # Called when TASKS_STARTTX triggers a DMA transfer.

   uarte.on_tx = lambda data: sys.stdout.buffer.write(data)

NXP LPUART (byte-level)
-------------------------

Defined in ``slab/python/slab_nxp/imxrt_lpuart.py``.

i.MX RT LPUART exposes both byte-level and bulk callbacks:

.. code-block:: python

   # Byte-level: (byte: int) -> None
   lpuart.on_tx = lambda byte: buf.append(byte)

   # Bulk: (data: bytes) -> None  (called for FIFO drains)
   lpuart.on_tx_bytes = lambda data: buf.extend(data)

RP2040 PL011 (packet-level)
-----------------------------

Defined in ``slab/python/slab_rp2040/rp2040_uart_spi_i2c.py``.

.. code-block:: python

   # Signature: (data: bytes) -> None
   uart.on_tx = lambda data: buf.extend(data)

   # Fired when TX FIFO empties: () -> None
   uart.on_tx_empty = lambda: None

LPC Flexcomm USART (packet-level)
-----------------------------------

Defined in ``slab/python/slab_nxp/lpc_flexcomm.py``.

.. code-block:: python

   # Signature: (data: bytes) -> None
   flexcomm_usart.on_tx = lambda data: buf.extend(data)

Iterating UARTs
----------------

To wire all UARTs in a peripheral set, check the ``name`` attribute for
substrings ``USART``, ``UART``, or ``UARTE``. This catches ``USART1``,
``LPUART1``, ``UARTE0``, etc.:

.. code-block:: python

   for p in adapter.peripherals:
       name = getattr(p, 'name', '')
       if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
           p.on_tx = make_handler(name)

The ``_wire_uart()`` function in ``slab/python/slab_cortex_m/board_builder.py:317``
does exactly this in board mode.


SPI Hooks
=========

SPI peripherals expose ``on_transfer`` with different granularity depending
on the SoC family.

STM32 SPI (byte-level)
------------------------

Defined in ``slab/python/slab_stm32/stm32_spi.py``.

Both SPIv1 (F1/F4) and SPIv2 (H7) use byte-level callbacks:

.. code-block:: python

   # Signature: (tx_data: int) -> int
   # Called when firmware writes to DR. Return value goes into RX DR.

   from slab_cortex_m.virtual_components import W25QxxFlash
   flash = W25QxxFlash(model="W25Q128")
   spi1.on_transfer = flash.transfer_byte

NRF SPIM (packet-level)
-------------------------

Defined in ``slab/python/slab_nrf/nrf_spi.py``.

Nordic SPIM uses DMA, so the callback receives/returns full buffers:

.. code-block:: python

   # Signature: (tx_data: bytes) -> bytes
   # Called when TASKS_START triggers a DMA transfer.
   # Return bytes are written into the RX DMA buffer.

   def handle_spi(mosi: bytes) -> bytes:
       flash.select()
       result = flash.transfer(mosi)
       flash.deselect()
       return result

   spim.on_transfer = handle_spi

NXP LPSPI (byte + frame size)
-------------------------------

Defined in ``slab/python/slab_nxp/imxrt_lpspi.py``.

The i.MX RT LPSPI passes the frame size (from TCR register) alongside data:

.. code-block:: python

   # Signature: (data: int, frame_size: int) -> int
   lpspi.on_transfer = lambda data, frame_size: 0xFF

RP2040 SPI (byte-level)
-------------------------

Defined in ``slab/python/slab_rp2040/rp2040_uart_spi_i2c.py``.

.. code-block:: python

   # Signature: (tx_data: int) -> int
   spi.on_transfer = flash.transfer_byte

LPC Flexcomm SPI (packet-level)
---------------------------------

Defined in ``slab/python/slab_nxp/lpc_flexcomm.py``.

.. code-block:: python

   # Signature: (tx_data: bytes) -> bytes
   flexcomm_spi.on_transfer = handle_spi


I2C Hooks
=========

I2C hooks come in two flavours: state-machine callbacks (STM32) and
packet-level callbacks (Nordic, RP2040, NXP).

STM32 I2C (state-machine)
---------------------------

Defined in ``slab/python/slab_stm32/stm32_i2c.py``.

Both I2Cv1 (F1/F4) and I2Cv2 (L4/H5/U5) expose four callbacks matching
the I2C protocol states:

.. code-block:: python

   # Called on START condition
   # Signature: (addr_7bit: int, is_read: bool) -> None
   i2c.on_start = lambda addr, is_read: print(f"START 0x{addr:02X} {'R' if is_read else 'W'}")

   # Called for each byte written by master
   # Signature: (byte: int) -> None
   i2c.on_write = lambda byte: device.write(byte)

   # Called when master reads a byte
   # Signature: () -> int
   i2c.on_read = lambda: device.read_next()

   # Called on STOP condition
   # Signature: () -> None
   i2c.on_stop = lambda: device.commit()

For external I2C devices (EEPROM, sensors), use the ``_I2CDeviceAdapter``
bridge from ``slab/python/slab_cortex_m/board_builder.py:74`` which
translates these byte-level callbacks into packet operations:

.. code-block:: python

   from slab_cortex_m.board_builder import _I2CDeviceAdapter
   from slab_cortex_m.virtual_components import EEPROM_24Cxx

   eeprom = EEPROM_24Cxx(model="24C256", address=0x50)
   bridge = _I2CDeviceAdapter(eeprom)

   i2c.on_start = bridge.on_start
   i2c.on_write = bridge.on_write
   i2c.on_read  = bridge.on_read
   i2c.on_stop  = bridge.on_stop

NRF TWIM (packet-level)
-------------------------

Defined in ``slab/python/slab_nrf/nrf_twi.py``.

Nordic TWIM uses DMA, so the callback handles a complete transfer:

.. code-block:: python

   # Signature: (addr: int, data: bytes, is_read: bool) -> bytes
   # addr:    7-bit I2C address
   # data:    TX bytes (write) or empty (read)
   # is_read: direction
   # Returns: RX bytes on read, ignored on write

   def handle_i2c(addr, data, is_read):
       if is_read:
           return eeprom.i2c_read(len(data) or 256)
       else:
           eeprom.i2c_write(data)
           return b''

   twim.on_transfer = handle_i2c

RP2040 I2C (packet-level)
---------------------------

Defined in ``slab/python/slab_rp2040/rp2040_uart_spi_i2c.py``.

RP2040 I2C (Synopsys DW_apb_i2c) uses separate read/write callbacks:

.. code-block:: python

   # Write: (addr: int, data: bytes) -> bool   (returns ACK)
   i2c.on_write = lambda addr, data: True

   # Read: (addr: int, count: int) -> bytes
   i2c.on_read = lambda addr, count: bytes(count)

LPC Flexcomm I2C (packet-level)
---------------------------------

Defined in ``slab/python/slab_nxp/lpc_flexcomm.py``.

Same signature as NRF TWIM:

.. code-block:: python

   # Signature: (addr: int, data: bytes, is_read: bool) -> bytes
   flexcomm_i2c.on_transfer = handle_i2c


QSPI Hooks
===========

NRF QSPI exposes two callbacks for flash operations and custom SPI
instructions. Defined in ``slab/python/slab_nrf/nrf_qspi.py``.

.. code-block:: python

   # Flash access callback
   # Signature: (op: str, addr: int, data: bytes) -> bytes
   # op:   'read', 'write', 'erase_4k', 'erase_64k', 'erase_all'
   # addr: flash address
   # data: write data (write), or length-placeholder (read)
   # Returns: read data (read), ignored otherwise

   def handle_flash(op, addr, data):
       if op == 'read':
           return flash_data[addr:addr+len(data)]
       elif op == 'write':
           flash_data[addr:addr+len(data)] = data
           return b''
       elif op.startswith('erase'):
           size = {'erase_4k': 4096, 'erase_64k': 65536}.get(op, len(flash_data))
           flash_data[addr:addr+size] = b'\xFF' * size
           return b''

   qspi.on_flash_access = handle_flash

.. code-block:: python

   # Custom SPI instruction callback
   # Signature: (opcode: int, data_in: bytes) -> bytes
   # Used for JEDEC ID, status register, etc.

   def handle_custom(opcode, data_in):
       if opcode == 0x9F:       # JEDEC ID
           return b'\xEF\x40\x18'
       return b'\xFF' * len(data_in)

   qspi.on_custom_instruction = handle_custom


GPIO Hooks
==========

GPIO pin-change callbacks let you track LED states, button simulation, and
external device chip-select lines.

STM32 GPIO
-----------

Defined in ``slab/python/slab_stm32/stm32_gpio.py``.

Both GPIOv1 (F1) and GPIOv2 (F4/L4/H5/U5) use:

.. code-block:: python

   # Signature: (pin: int, value: int, is_output: int) -> None
   # pin:       0-15
   # value:     0 or 1
   # is_output: 1 if pin is configured as output, 0 otherwise

   def on_change(pin, value, is_output):
       if pin == 5 and is_output:
           print(f"LED {'ON' if value else 'OFF'}")

   gpioa.on_pin_change = on_change

RP2040 SIO
-----------

Defined in ``slab/python/slab_rp2040/rp2040_peripherals.py``.

RP2040 GPIO is managed through the SIO block. The callback receives the
full 32-bit output and output-enable registers:

.. code-block:: python

   # Signature: (gpio_out: int, gpio_oe: int) -> None
   # gpio_out: 32-bit output register (one bit per GPIO)
   # gpio_oe:  32-bit output-enable register

   def on_change(gpio_out, gpio_oe):
       led_pin = 25
       if gpio_oe & (1 << led_pin):
           state = bool(gpio_out & (1 << led_pin))
           print(f"LED {'ON' if state else 'OFF'}")

   sio.on_gpio_change = on_change


CAN Hooks
=========

The CAN controller (``slab/python/slab_cortex_m/can_peripheral.py``)
exposes TX and RX callbacks for CAN bus frame interception.

.. code-block:: python

   from slab_cortex_m.can_peripheral import CANMessage

   # TX callback -- fired when firmware transmits a frame
   # Signature: (msg: CANMessage) -> None
   def on_can_tx(msg):
       print(f"TX CAN ID=0x{msg.arbitration_id:03X} data={msg.data.hex()}")

   can.on_tx = on_can_tx

   # RX callback -- fired when a frame enters the RX FIFO
   # Signature: (msg: CANMessage) -> None
   can.on_rx = lambda msg: print(f"RX CAN ID=0x{msg.arbitration_id:03X}")

The ``CANMessage`` dataclass fields:

.. code-block:: python

   @dataclass
   class CANMessage:
       arbitration_id: int          # 11-bit or 29-bit CAN ID
       data: bytes                  # Payload (0-8 bytes, or 0-64 for CAN FD)
       is_extended: bool = False    # Extended (29-bit) ID
       is_remote: bool = False      # Remote Transmission Request
       is_error: bool = False       # Error frame
       is_fd: bool = False          # CAN FD frame
       bitrate_switch: bool = False # CAN FD bitrate switch
       timestamp: float = 0.0      # Timestamp (seconds)

To inject CAN frames into firmware, use ``receive_message()``:

.. code-block:: python

   msg = CANMessage(arbitration_id=0x123, data=b'\x01\x02\x03')
   can.receive_message(msg)


ADC Hooks
=========

ADC peripherals expose ``on_sample`` to provide analog values at conversion
time. Without this hook, ADC reads return 0.

Defined in:

- ``slab/python/slab_rp2040/rp2040_adc_pwm_dma.py``
- ``slab/python/slab_nxp/imxrt_adc.py``
- ``slab/python/slab_nxp/lpc_adc.py``

.. code-block:: python

   # Signature: (channel: int) -> int
   # channel: ADC channel number
   # Returns: raw ADC value (12-bit: 0-4095)

   import random

   def fake_temperature(channel):
       if channel == 4:    # Internal temperature sensor
           return 1800     # ~25C on STM32
       return random.randint(0, 4095)

   adc.on_sample = fake_temperature


IRQ Callback
============

Every peripheral has an ``irq_callback`` attribute used to signal
interrupts to QEMU. This is not a hook you typically set on individual
peripherals -- instead, use ``setup_irq_callback()`` on the peripheral set
or set ``board.irq_callback`` / ``adapter.irq_callback``.

Signature
---------

.. code-block:: python

   # Signature: (irq_num: int, level: int) -> None
   # irq_num: NVIC interrupt number
   # level:   1 = assert, 0 = deassert

Peripherals call it via ``trigger_irq()``
(``slab/python/slab_stm32/stm32_base.py``):

.. code-block:: python

   def trigger_irq(self, level: int = 1):
       if self.irq >= 0 and self.irq_callback:
           self.irq_callback(self.irq, level)

setup_irq_callback()
---------------------

Defined on all peripheral set base classes (``slab/python/slab_stm32/stm32_base.py``,
``slab/python/slab_rp2040/rp2040_peripherals.py``,
``slab/python/slab_cortex_m/svd_peripheral.py``):

.. code-block:: python

   def setup_irq_callback(self, callback):
       """Set IRQ callback on ALL peripherals in the set."""
       self.irq_callback = callback
       for p in self.peripherals:
           p.irq_callback = callback

In a server subclass, wire it once:

.. code-block:: python

   board.irq_callback = self.send_irq
   # or
   adapter.irq_callback = self.send_irq

The ``PeripheralSetAdapter`` (``slab/python/slab_cortex_m/peripheral_adapter.py``)
propagates the callback through ``_setup_irq_forwarding()`` which handles
the NRF/NXP ``on_irq(level)`` convention by wrapping it with the IRQ number.


Practical Examples
==================

Logging All Bus Traffic
------------------------

This example hooks UART, SPI, and I2C to log all bus activity during
firmware execution. Useful for reverse engineering or debugging peripheral
initialization sequences.

.. code-block:: python
   :caption: bus_logger.py -- save as slab/examples/bus_logger.py

   #!/usr/bin/env python3
   """Log all bus traffic from firmware execution."""

   import sys
   from slab_cortex_m.board import BoardConfig, create_peripheral_set
   from slab_cortex_m.peripheral_adapter import PeripheralSetAdapter

   config = BoardConfig(name="BusLogger", mcu="STM32F405")
   pset = create_peripheral_set(config)
   adapter = PeripheralSetAdapter(pset)

   for p in adapter.peripherals:
       name = getattr(p, 'name', '')

       # UART: print transmitted bytes
       if ('USART' in name or 'UART' in name) and hasattr(p, 'on_tx'):
           def make_uart(n=name):
               def handler(byte):
                   print(f"[{n}] TX: 0x{byte:02X} '{chr(byte & 0x7F)}'")
               return handler
           p.on_tx = make_uart()

       # SPI: log MOSI/MISO exchanges
       if 'SPI' in name and hasattr(p, 'on_transfer'):
           def make_spi(n=name):
               def handler(tx):
                   print(f"[{n}] MOSI=0x{tx:02X} MISO=0xFF")
                   return 0xFF
               return handler
           p.on_transfer = make_spi()

       # I2C: log protocol events
       if 'I2C' in name:
           if hasattr(p, 'on_start'):
               def make_i2c_start(n=name):
                   def handler(addr, is_read):
                       print(f"[{n}] START 0x{addr:02X} {'R' if is_read else 'W'}")
                   return handler
               p.on_start = make_i2c_start()
           if hasattr(p, 'on_write'):
               def make_i2c_write(n=name):
                   def handler(byte):
                       print(f"[{n}] WRITE 0x{byte:02X}")
                   return handler
               p.on_write = make_i2c_write()
           if hasattr(p, 'on_read'):
               def make_i2c_read(n=name):
                   def handler():
                       print(f"[{n}] READ -> 0xFF")
                       return 0xFF
                   return handler
               p.on_read = make_i2c_read()
           if hasattr(p, 'on_stop'):
               def make_i2c_stop(n=name):
                   def handler():
                       print(f"[{n}] STOP")
                   return handler
               p.on_stop = make_i2c_stop()

   print(f"Hooks installed on {len(adapter.peripherals)} peripherals")
   # ... continue with server setup (see server_modes tutorial)

Injecting UART Input
---------------------

To send data to firmware (e.g., a command-line shell), use
``receive_byte()`` on the USART peripheral:

.. code-block:: python

   usart1 = None
   for p in adapter.peripherals:
       if getattr(p, 'name', '') == 'USART1':
           usart1 = p
           break

   # Send "help\r\n" to the firmware
   for ch in b"help\r\n":
       usart1.receive_byte(ch)


Best Practices
==============

1. **Always use a factory function in loops.** The ``make_handler(n=name)``
   pattern ensures each closure captures its own copy of the loop variable.
   Without it, all callbacks share the last value of ``name``.

2. **Check ``hasattr`` before assigning.** Not every peripheral with a
   matching name exposes every hook. Always guard with
   ``hasattr(p, 'on_tx')`` before assignment.

3. **Match the family convention.** STM32 SPI uses byte-level
   ``(int) -> int``, Nordic SPIM uses packet-level ``(bytes) -> bytes``.
   Check the quick reference table if unsure.

4. **Board mode re-wiring.** In board mode, ``build_board()`` wires UART
   and LEDs automatically. To add custom hooks, iterate
   ``board.adapter.peripherals`` **after** calling ``build_board()`` and
   replace or chain the existing callbacks.

5. **IRQ wiring order.** Set ``irq_callback`` before the server starts
   accepting connections. If IRQs are not forwarded, interrupt-driven
   firmware will hang waiting for events that never arrive.


Next Steps
==========

- :ref:`server_modes` -- Direct vs board mode server setup and UART hooking
- :ref:`creating_boards` -- Write YAML board configurations
- :ref:`mmio_tracing` -- Record and analyze all MMIO accesses
- :ref:`peripheral_basics` -- Peripheral model fundamentals
- :ref:`stubbing_peripherals` -- Create custom peripheral stubs
