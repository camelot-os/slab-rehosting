Secure Boot Chain
=================

This document describes the secure boot implementation using MCUboot
and the image validation performed before jumping to non-secure code.

Boot Chain Overview
-------------------

.. tikz:: Secure Boot Sequence
   :libs: arrows.meta,positioning,shapes.geometric

   \begin{tikzpicture}[
       node distance=1.5cm,
       block/.style={draw, rounded corners, minimum width=3.5cm, minimum height=1cm, align=center},
       decision/.style={draw, diamond, aspect=2, minimum width=2cm, align=center},
       arrow/.style={-{Stealth[length=3mm]}, thick}
   ]

   % Boot stages
   \node[block, fill=gray!30] (reset) {System Reset};
   \node[block, fill=green!30, below=of reset] (bl2) {MCUboot (BL2)\\Signature Verify};
   \node[decision, below=of bl2] (sigok) {Signature\\Valid?};
   \node[block, fill=green!30, below left=1cm and 0.5cm of sigok] (secure) {Secure World\\(main.c)};
   \node[block, fill=red!30, right=2cm of sigok] (halt) {HALT\\Security Error};
   \node[decision, below=of secure] (nsok) {NS Image\\Valid?};
   \node[block, fill=yellow!30, below=of nsok] (ns) {Non-Secure\\Application};
   \node[block, fill=red!30, right=2cm of nsok] (halt2) {HALT\\Invalid Image};

   % Arrows
   \draw[arrow] (reset) -- (bl2);
   \draw[arrow] (bl2) -- (sigok);
   \draw[arrow] (sigok) -- node[left] {Yes} (secure);
   \draw[arrow] (sigok) -- node[above] {No} (halt);
   \draw[arrow] (secure) -- (nsok);
   \draw[arrow] (nsok) -- node[left] {Yes} (ns);
   \draw[arrow] (nsok) -- node[above] {No} (halt2);

   \end{tikzpicture}

MCUboot Configuration
---------------------

MCUboot (BL2) is enabled in the TF-M build configuration:

.. code-block:: cmake

   # tfm_config/tfm_build.cmake
   set(BL2 ON CACHE BOOL "Enable MCUboot bootloader")
   set(MCUBOOT_IMAGE_NUMBER 2 CACHE STRING "Number of images (S + NS)")
   set(MCUBOOT_SIGNATURE_TYPE "RSA-3072" CACHE STRING "Signature algorithm")
   set(MCUBOOT_HW_KEY ON CACHE BOOL "Use hardware key for verification")

Image Signing
^^^^^^^^^^^^^

Images must be signed before deployment:

.. code-block:: bash

   # Sign secure image
   imgtool sign --key signing_key.pem \
       --align 4 \
       --version 1.0.0 \
       --header-size 0x400 \
       --pad-header \
       --slot-size 0x40000 \
       secure_fw.bin \
       secure_fw_signed.bin

   # Sign non-secure image
   imgtool sign --key signing_key.pem \
       --align 4 \
       --version 1.0.0 \
       --header-size 0x400 \
       --pad-header \
       --slot-size 0x1C0000 \
       nonsecure_fw.bin \
       nonsecure_fw_signed.bin

.. warning::

   Keep signing keys secure! For production:

   - Use HSM for key storage
   - Implement key rotation procedures
   - Never commit keys to version control

NS Image Validation
-------------------

Before jumping to non-secure code, the secure world validates:

1. Stack pointer is within valid NS SRAM range
2. Reset handler is within valid NS Flash range
3. Stack pointer is word-aligned
4. Optional: CRC/hash verification

Validation Code
^^^^^^^^^^^^^^^

.. code-block:: c

   static int Security_ValidateNSImage(uint32_t ns_vector_table)
   {
       uint32_t ns_stack_ptr = *((uint32_t *)ns_vector_table);
       uint32_t ns_reset_handler = *((uint32_t *)(ns_vector_table + 4U));

       /* Clear Thumb bit for address validation */
       ns_reset_handler &= ~1UL;

       /* Validation 1: Stack pointer in valid NS SRAM */
       if ((ns_stack_ptr < NS_STACK_PTR_MIN) ||
           (ns_stack_ptr > NS_STACK_PTR_MAX))
       {
           return -1;
       }

       /* Validation 2: Reset handler in valid NS Flash */
       if ((ns_reset_handler < NS_RESET_HANDLER_MIN) ||
           (ns_reset_handler > NS_RESET_HANDLER_MAX))
       {
           return -1;
       }

       /* Validation 3: Stack pointer word-aligned */
       if ((ns_stack_ptr & 0x3UL) != 0)
       {
           return -1;
       }

       return 0;  /* Valid */
   }

Validation Ranges
^^^^^^^^^^^^^^^^^

From ``security_config.h``:

.. code-block:: c

   /* NS SRAM range */
   #define NS_STACK_PTR_MIN        0x20020000UL
   #define NS_STACK_PTR_MAX        0x200A0000UL

   /* NS Flash range */
   #define NS_RESET_HANDLER_MIN    0x08042000UL
   #define NS_RESET_HANDLER_MAX    0x08200000UL

Boot Failure Handling
---------------------

On validation failure:

1. Error message sent via secure UART (development only)
2. System halts (Error_Handler)
3. Optional: Reset and retry with rollback image

.. code-block:: c

   if (Security_ValidateNSImage(ns_vector_table) != 0)
   {
       const char *err_msg = "[SECURE] ERROR: NS image validation failed!\r\n";
       HAL_UART_Transmit(&huart1, (uint8_t *)err_msg, strlen(err_msg), HAL_MAX_DELAY);
       Error_Handler();
   }

Flash Protection (RDP)
----------------------

For production deployments, enable Read-Out Protection:

.. list-table:: RDP Levels
   :widths: 15 25 60
   :header-rows: 1

   * - Level
     - Protection
     - Notes
   * - 0
     - None
     - Development only
   * - 1
     - Flash read protected
     - Reversible (full erase)
   * - 2
     - Debug fully disabled
     - **PERMANENT - IRREVERSIBLE**

Configuration via STM32CubeProgrammer:

.. code-block:: bash

   # RDP Level 1 (reversible)
   STM32_Programmer_CLI -c port=SWD -ob RDP=0xBB

   # RDP Level 2 (PERMANENT - test thoroughly first!)
   STM32_Programmer_CLI -c port=SWD -ob RDP=0xCC

.. danger::

   RDP Level 2 is **IRREVERSIBLE**. The device cannot be debugged or
   reflashed via debug interface. Test thoroughly with Level 1 first!

Option Bytes Configuration
--------------------------

Recommended option bytes for production:

.. code-block:: bash

   # Enable TrustZone
   STM32_Programmer_CLI -c port=SWD -ob TZEN=1

   # Set secure flash watermark (first 256KB secure)
   STM32_Programmer_CLI -c port=SWD -ob SECWM_PSTRT=0x0 SECWM_PEND=0x7F

   # Enable boot lock (prevent boot from other sources)
   STM32_Programmer_CLI -c port=SWD -ob BOOT_LOCK=1
