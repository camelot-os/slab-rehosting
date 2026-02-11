.. _peripheral_basics:

==================
Peripheral Basics
==================

This tutorial explains how SLAB peripherals work and how to interact with them.

MMIO Access Model
=================

ARM Cortex-M peripherals are accessed via Memory-Mapped I/O (MMIO).
Each peripheral occupies a range of addresses and exposes registers:

.. figure:: ../images/mmio_model.png
   :alt: MMIO Access Model
   :align: center
   :width: 80%

   MMIO Model: CPU reads/writes to memory addresses that map to peripheral registers

.. code-block:: text

   Memory Map (Cortex-M):
   ─────────────────────────────────────────
   0x00000000 - 0x1FFFFFFF   Code/Flash
   0x20000000 - 0x3FFFFFFF   SRAM
   0x40000000 - 0x5FFFFFFF   Peripherals  ← SLAB proxies this
   0x60000000 - 0x9FFFFFFF   External RAM
   0xA0000000 - 0xDFFFFFFF   External Device
   0xE0000000 - 0xFFFFFFFF   Private Peripheral Bus (PPB)

Register Access Sizes
---------------------

Firmware can access registers with different sizes:

.. list-table::
   :widths: 20 30 50
   :header-rows: 1

   * - Size
     - C Type
     - Example
   * - 8-bit
     - ``uint8_t``
     - ``*(volatile uint8_t*)0x40004404 = 'A';``
   * - 16-bit
     - ``uint16_t``
     - ``*(volatile uint16_t*)0x40004408 = 115200;``
   * - 32-bit
     - ``uint32_t``
     - ``*(volatile uint32_t*)0x40020014 = 0x2000;``

Peripheral Lifecycle
====================

A typical peripheral interaction follows this pattern:

1. **Enable Clock**: Write to RCC to enable peripheral clock
2. **Configure**: Write configuration registers
3. **Enable**: Set enable bit in control register
4. **Operate**: Read/write data registers
5. **Wait**: Poll status register or use interrupts

.. code-block:: c
   :caption: Example: USART Initialization

   // 1. Enable USART2 clock
   RCC->APB1ENR |= RCC_APB1ENR_USART2EN;

   // 2. Configure baud rate
   USART2->BRR = SystemCoreClock / 115200;

   // 3. Configure: 8N1, TX enable
   USART2->CR1 = USART_CR1_TE;

   // 4. Enable USART
   USART2->CR1 |= USART_CR1_UE;

   // 5. Send data
   while (!(USART2->SR & USART_SR_TXE));  // Wait for TX empty
   USART2->DR = 'H';

Register Types
==============

Different register types have different read/write semantics:

Read-Only (RO)
--------------

Value reflects hardware state. Writing has no effect.

.. code-block:: c

   // Read USART status
   uint32_t status = USART2->SR;  // Read-only

Write-Only (WO)
---------------

Writing triggers an action. Reading returns 0 or last written value.

.. code-block:: c

   // Send data (write-only)
   USART2->DR = data;

Read-Write (RW)
---------------

Standard register. Read returns current value, write updates it.

.. code-block:: c

   // Configure mode
   USART2->CR1 = USART_CR1_TE | USART_CR1_UE;

Read-Clear (RC_W1)
------------------

Reading returns status. Writing 1 clears bits.

.. code-block:: c

   // Clear RXNE flag by reading DR
   (void)USART2->DR;

Write-1-to-Set/Clear (W1S/W1C)
------------------------------

Writing 1 sets or clears specific bits without affecting others.

.. code-block:: c

   // GPIO BSRR: set pin 5
   GPIOA->BSRR = (1 << 5);     // Lower 16 bits: SET

   // GPIO BSRR: clear pin 5
   GPIOA->BSRR = (1 << 21);    // Upper 16 bits: RESET

Using Pre-built Peripheral Sets
===============================

SLAB provides complete peripheral sets for common MCUs:

.. code-block:: python

   from slab_stm32 import STM32F439PeripheralSet

   # Create peripheral set
   ps = STM32F439PeripheralSet()

   # List available peripherals
   for name, periph in ps.peripherals.items():
       print(f"{name}: 0x{periph.base:08X}")

   # Access specific peripherals
   ps.rcc.write(ps.rcc.AHB1ENR, 4, 0x01)  # Enable GPIOA
   ps.gpio['A'].write(ps.gpio['A'].ODR, 4, 0x20)  # Set PA5

CRYP Peripheral Example
-----------------------

.. code-block:: python

   # AES-128 encryption using CRYP peripheral
   cryp = ps.cryp

   # Set key
   key = b'0123456789ABCDEF'
   cryp.set_key(key, keysize=128)

   # Set algorithm
   cryp.cr |= (cryp.ALGOMODE_AES_ECB << 3)

   # Encrypt
   plaintext = b'Hello, World!!!'
   ciphertext = cryp.encrypt_block(plaintext)

   print(f"Ciphertext: {ciphertext.hex()}")

HASH Peripheral Example
-----------------------

.. code-block:: python

   # SHA-256 using HASH peripheral
   hash_periph = ps.hash

   hash_periph.set_algorithm('sha256')
   digest = hash_periph.hash_data(b'Hello, World!')

   print(f"SHA-256: {digest.hex()}")

Callbacks and Events
====================

Peripherals support callbacks for state changes:

.. code-block:: python

   # GPIO pin change callback
   def on_gpio_change(pin, value, is_output):
       if is_output:
           print(f"GPIO pin {pin} = {'HIGH' if value else 'LOW'}")

   ps.gpio['A'].on_pin_change = on_gpio_change

   # UART TX callback
   def on_uart_tx(byte):
       print(chr(byte), end='', flush=True)

   ps.usart2.on_tx = on_uart_tx

Next Steps
==========

* :ref:`stubbing_peripherals` - Create custom peripheral stubs
* :ref:`first_emulation` - Emulate real firmware
* :ref:`api/slab_stm32` - Full STM32 API reference
