Non-Secure World
================

The non-secure world runs the USB CDC ACM application and ThreadX RTOS.
It has restricted access to system resources as defined by TrustZone.

Responsibilities
----------------

The non-secure application handles:

1. **USB Communication**
   - CDC ACM device initialization
   - Virtual COM port data transfer
   - USB event handling

2. **User Interaction**
   - Command processing
   - Response formatting
   - LED indication (via NSC)

3. **RTOS Management**
   - ThreadX kernel
   - Task scheduling
   - Resource management

Application Architecture
------------------------

.. tikz:: Non-Secure Application Stack
   :libs: arrows.meta,positioning,shapes.geometric,fit

   \begin{tikzpicture}[
       layer/.style={draw, rounded corners, minimum width=8cm, minimum height=1cm, align=center},
       arrow/.style={-{Stealth[length=2mm]}, thick}
   ]

   \node[layer, fill=blue!20] (app) at (0,4) {Application Layer\\(main.c, ux\_device\_cdc\_acm.c)};
   \node[layer, fill=purple!20] (usbx) at (0,2.8) {USBX Device Stack\\(CDC ACM Class)};
   \node[layer, fill=orange!20] (threadx) at (0,1.6) {ThreadX RTOS\\(Kernel, Memory, Timers)};
   \node[layer, fill=gray!20] (hal) at (0,0.4) {STM32 HAL\\(USB, GPIO, DMA)};
   \node[layer, fill=green!15] (hw) at (0,-0.8) {Hardware\\(USB OTG FS, SRAM2/3)};

   \draw[arrow] (app) -- (usbx);
   \draw[arrow] (usbx) -- (threadx);
   \draw[arrow] (threadx) -- (hal);
   \draw[arrow] (hal) -- (hw);

   \end{tikzpicture}

Boot Sequence
-------------

After secure world calls ``NonSecure_Init()``:

1. NS Reset Handler executes
2. ``main()`` initializes HAL and system clock (NS portions)
3. ThreadX kernel starts
4. Application thread initializes USBX
5. CDC ACM device enumerated by host

Main Entry Point
^^^^^^^^^^^^^^^^

.. code-block:: c

   int main(void)
   {
       /* Initialize HAL for NS */
       HAL_Init();

       /* Configure clocks (NS accessible only) */
       SystemClock_Config();

       /* Initialize GPIOs */
       MX_GPIO_Init();

       /* Print via secure UART */
       SECURE_UART_Print("[NS] Starting ThreadX\r\n", 23);

       /* Start ThreadX kernel */
       tx_kernel_enter();

       /* Never reached */
       while (1) {}
   }

ThreadX Configuration
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   void tx_application_define(void *first_unused_memory)
   {
       CHAR *pointer = (CHAR *)first_unused_memory;

       /* Create application thread */
       tx_thread_create(&app_thread, "App Thread",
                        app_thread_entry, 0,
                        pointer, APP_STACK_SIZE,
                        APP_PRIORITY, APP_PRIORITY,
                        TX_NO_TIME_SLICE, TX_AUTO_START);

       /* Initialize USBX */
       ux_system_initialize(pointer + APP_STACK_SIZE, UX_MEMORY_SIZE,
                            UX_NULL, 0);
   }

USB CDC ACM Implementation
--------------------------

The CDC ACM class provides a virtual serial port over USB.

Initialization
^^^^^^^^^^^^^^

.. code-block:: c

   UINT app_usbx_device_init(void)
   {
       /* Initialize USBX device stack */
       ux_device_stack_initialize(USBD_Get_Device_Framework_Speed(&length),
                                   length,
                                   USBD_Get_String_Framework(&length),
                                   length,
                                   USBD_Get_Language_Id_Framework(&length),
                                   length,
                                   USBD_ChangeFunction);

       /* Register CDC ACM class */
       ux_device_stack_class_register(_ux_system_slave_class_cdc_acm_name,
                                       ux_device_class_cdc_acm_entry,
                                       1, 0, &cdc_acm_params);

       /* Start USB controller */
       HAL_PCD_Start(&hpcd_USB_OTG_FS);

       return UX_SUCCESS;
   }

Data Reception
^^^^^^^^^^^^^^

.. code-block:: c

   void cdc_acm_read_thread(ULONG arg)
   {
       ULONG actual_length;
       UCHAR buffer[64];

       while (1)
       {
           /* Read from USB */
           ux_device_class_cdc_acm_read(cdc_acm, buffer, 64, &actual_length);

           if (actual_length > 0)
           {
               /* Process received data */
               process_command(buffer, actual_length);
           }
       }
   }

Data Transmission
^^^^^^^^^^^^^^^^^

.. code-block:: c

   void cdc_acm_send(const char *data, ULONG length)
   {
       ULONG actual_length;

       ux_device_class_cdc_acm_write(cdc_acm, (UCHAR *)data, length, &actual_length);
   }

Calling Secure Services
-----------------------

The non-secure application uses NSC functions to access secure resources.

Debug Output
^^^^^^^^^^^^

.. code-block:: c

   #include "secure_nsc.h"

   void ns_debug_print(const char *msg)
   {
       SECURE_UART_Print(msg, strlen(msg));
   }

Security Status
^^^^^^^^^^^^^^^

.. code-block:: c

   void print_security_status(void)
   {
       uint32_t status = SECURE_GetSecurityStatus();

       if (status & 0x01)
           ns_debug_print("SAU: Enabled\r\n");
       if (status & 0x02)
           ns_debug_print("GTZC: Configured\r\n");
   }

TF-M Variant (PSA APIs)
-----------------------

The TF-M variant uses PSA APIs for cryptographic services:

.. code-block:: c

   #include "psa/crypto.h"

   /* Initialize PSA crypto */
   psa_crypto_init();

   /* Generate AES-256 key */
   psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
   psa_set_key_type(&attr, PSA_KEY_TYPE_AES);
   psa_set_key_bits(&attr, 256);
   psa_set_key_algorithm(&attr, PSA_ALG_GCM);
   psa_generate_key(&attr, &key_id);

   /* Encrypt data */
   psa_aead_encrypt(key_id, PSA_ALG_GCM,
                    nonce, 12,
                    NULL, 0,
                    plaintext, plaintext_len,
                    ciphertext, ciphertext_size, &ciphertext_len);

File Structure
--------------

.. code-block:: text

   NonSecure/
   +-- Inc/
   |   +-- main.h                   # Application header
   |   +-- app_usbx_device.h        # USBX configuration
   |   +-- ux_device_descriptors.h  # USB descriptors
   |   +-- ux_device_cdc_acm.h      # CDC ACM interface
   |   +-- tx_user.h                # ThreadX config
   +-- Src/
   |   +-- main.c                   # Application entry
   |   +-- app_usbx_device.c        # USBX initialization
   |   +-- ux_device_descriptors.c  # USB descriptor data
   |   +-- ux_device_cdc_acm.c      # CDC ACM callbacks
   |   +-- stm32h5xx_it.c           # Interrupt handlers
   +-- STM32CubeIDE/
       +-- STM32H563ZITX_FLASH_NS.ld # NS linker script

Memory Usage
------------

Typical NS memory usage:

.. list-table:: NS Memory Footprint
   :widths: 30 20 50
   :header-rows: 1

   * - Component
     - Size
     - Location
   * - ThreadX Kernel
     - ~20 KB
     - NS Flash
   * - USBX Stack
     - ~40 KB
     - NS Flash
   * - Application Code
     - ~15 KB
     - NS Flash
   * - Thread Stacks
     - ~8 KB
     - SRAM3
   * - USB Buffers
     - ~4 KB
     - SRAM3
   * - Heap
     - ~16 KB
     - SRAM3
