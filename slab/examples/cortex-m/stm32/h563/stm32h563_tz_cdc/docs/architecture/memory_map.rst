Memory Map
==========

This document describes the memory layout for the STM32H563 TrustZone
CDC ACM project.

Flash Memory Layout
-------------------

.. tikz:: Flash Memory Map
   :libs: arrows.meta,positioning

   \begin{tikzpicture}[
       block/.style={draw, minimum width=6cm, align=center, font=\small},
       secure/.style={block, fill=green!25},
       nsc/.style={block, fill=yellow!35},
       nonsecure/.style={block, fill=red!15},
       addr/.style={font=\tiny\ttfamily}
   ]

   % Secure Flash (via alias 0x0C000000)
   \node[secure, minimum height=2.5cm] (sf) at (0,5.25) {
       \textbf{Secure Flash}\\
       MCUboot (BL2)\\
       Secure main.c\\
       NSC veneers\\
       Secure data
   };
   \node[addr, left=0.3cm of sf.north west, anchor=east] {0x0C000000};
   \node[addr, left=0.3cm of sf.south west, anchor=east] {0x0C03FFFF};

   % NSC Region
   \node[nsc, minimum height=0.8cm] (nsc) at (0,3.6) {
       \textbf{NSC Region} (8 KB)\\
       Gateway functions
   };
   \node[addr, left=0.3cm of nsc.north west, anchor=east] {0x0C040000};
   \node[addr, left=0.3cm of nsc.south west, anchor=east] {0x0C041FFF};

   % Non-Secure Flash
   \node[nonsecure, minimum height=3cm] (nsf) at (0,1.2) {
       \textbf{Non-Secure Flash} (~1.75 MB)\\
       NS Application\\
       USB CDC Stack\\
       ThreadX RTOS
   };
   \node[addr, left=0.3cm of nsf.north west, anchor=east] {0x08042000};
   \node[addr, left=0.3cm of nsf.south west, anchor=east] {0x081FFFFF};

   % Size annotations
   \node[right=0.5cm of sf.east] {256 KB};
   \node[right=0.5cm of nsc.east] {8 KB};
   \node[right=0.5cm of nsf.east] {~1.75 MB};

   \end{tikzpicture}

Flash Address Aliases
^^^^^^^^^^^^^^^^^^^^^

The STM32H563 provides two address aliases for flash:

.. list-table:: Flash Address Aliases
   :widths: 30 30 40
   :header-rows: 1

   * - Alias
     - Address Range
     - Security
   * - Secure
     - 0x0C000000 - 0x0C1FFFFF
     - S or NSC (via SAU)
   * - Non-Secure
     - 0x08000000 - 0x081FFFFF
     - NS only

Linker Script Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Secure linker script** (STM32H563ZITX_FLASH_S.ld):

.. code-block:: text

   MEMORY
   {
     FLASH_S  (rx)  : ORIGIN = 0x0C000000, LENGTH = 256K
     FLASH_NSC (rx) : ORIGIN = 0x0C040000, LENGTH = 8K
     RAM_S    (rwx) : ORIGIN = 0x30000000, LENGTH = 256K
   }

   SECTIONS
   {
     .text : { *(.text*) } > FLASH_S
     .gnu.sgstubs : { *(.gnu.sgstubs*) } > FLASH_NSC
     .data : { *(.data*) } > RAM_S
     .bss : { *(.bss*) } > RAM_S
   }

**Non-Secure linker script** (STM32H563ZITX_FLASH_NS.ld):

.. code-block:: text

   MEMORY
   {
     FLASH_NS (rx)  : ORIGIN = 0x08042000, LENGTH = 1792K
     RAM_NS   (rwx) : ORIGIN = 0x20020000, LENGTH = 512K
   }

SRAM Memory Layout
------------------

.. tikz:: SRAM Memory Map
   :libs: arrows.meta,positioning

   \begin{tikzpicture}[
       block/.style={draw, minimum width=5cm, align=center, font=\small},
       secure/.style={block, fill=green!25},
       nonsecure/.style={block, fill=red!15},
       addr/.style={font=\tiny\ttfamily}
   ]

   % SRAM1 (Secure)
   \node[secure, minimum height=2cm] (sram1) at (0,4) {
       \textbf{SRAM1 (Secure)}\\
       Secure stack\\
       Secure heap\\
       Crypto buffers
   };
   \node[addr, left=0.3cm of sram1.north west, anchor=east] {0x30000000};
   \node[addr, left=0.3cm of sram1.south west, anchor=east] {0x3003FFFF};

   % SRAM2 (Non-Secure)
   \node[nonsecure, minimum height=1.5cm] (sram2) at (0,2.1) {
       \textbf{SRAM2 (NS)}\\
       NS stack
   };
   \node[addr, left=0.3cm of sram2.north west, anchor=east] {0x30040000};
   \node[addr, left=0.3cm of sram2.south west, anchor=east] {0x3004FFFF};

   % SRAM3 (Non-Secure)
   \node[nonsecure, minimum height=2cm] (sram3) at (0,0.2) {
       \textbf{SRAM3 (NS)}\\
       USB buffers\\
       ThreadX stacks\\
       Application heap
   };
   \node[addr, left=0.3cm of sram3.north west, anchor=east] {0x30050000};
   \node[addr, left=0.3cm of sram3.south west, anchor=east] {0x300BFFFF};

   % Size annotations
   \node[right=0.5cm of sram1.east] {256 KB};
   \node[right=0.5cm of sram2.east] {64 KB};
   \node[right=0.5cm of sram3.east] {320 KB};

   \end{tikzpicture}

SRAM Address Aliases
^^^^^^^^^^^^^^^^^^^^

.. list-table:: SRAM Address Aliases
   :widths: 20 30 30 20
   :header-rows: 1

   * - Region
     - Secure Alias
     - NS Alias
     - Security
   * - SRAM1
     - 0x30000000
     - 0x20000000
     - Secure
   * - SRAM2
     - 0x30040000
     - 0x20040000
     - Non-Secure
   * - SRAM3
     - 0x30050000
     - 0x20050000
     - Non-Secure

MPCBB Block Configuration
^^^^^^^^^^^^^^^^^^^^^^^^^

MPCBB configures SRAM security at 256-byte granularity.

.. code-block:: c

   /* SRAM1: All blocks secure (0xFFFFFFFF) */
   for (uint32_t i = 0; i < GTZC_MPCBB_NB_VCTR_REG_MAX; i++)
   {
       SecureArea.AttributeConfig.MPCBB_SecConfig_array[i] = 0xFFFFFFFFUL;
   }
   HAL_GTZC_MPCBB_ConfigMem(SRAM1_BASE_S, &SecureArea);

   /* SRAM2/SRAM3: All blocks non-secure (0x00000000) */
   for (uint32_t i = 0; i < GTZC_MPCBB_NB_VCTR_REG_MAX; i++)
   {
       NonSecureArea.AttributeConfig.MPCBB_SecConfig_array[i] = 0x00000000UL;
   }
   HAL_GTZC_MPCBB_ConfigMem(SRAM2_BASE_S, &NonSecureArea);

Peripheral Address Space
------------------------

Peripherals are mapped in the 0x40000000-0x5FFFFFFF range.

.. list-table:: Key Peripheral Addresses
   :widths: 25 30 20 25
   :header-rows: 1

   * - Peripheral
     - Address
     - Security
     - TZSC Config
   * - USB OTG FS
     - 0x40080000
     - Non-Secure
     - GTZC_PERIPH_USB
   * - USART1
     - 0x40013800
     - Secure
     - Default (secure)
   * - RNG
     - 0x420C0800
     - Secure
     - Default (secure)
   * - GPDMA1
     - 0x40020000
     - Non-Secure
     - CH0-CH7 NS

Complete Memory Map Table
-------------------------

.. list-table:: Complete Memory Map
   :widths: 25 20 20 15 20
   :header-rows: 1

   * - Region
     - Start
     - End
     - Size
     - Security
   * - Secure Flash
     - 0x0C000000
     - 0x0C03FFFF
     - 256 KB
     - Secure
   * - NSC Flash
     - 0x0C040000
     - 0x0C041FFF
     - 8 KB
     - NSC
   * - NS Flash
     - 0x08042000
     - 0x081FFFFF
     - 1792 KB
     - Non-Secure
   * - SRAM1
     - 0x30000000
     - 0x3003FFFF
     - 256 KB
     - Secure
   * - SRAM2
     - 0x30040000
     - 0x3004FFFF
     - 64 KB
     - Non-Secure
   * - SRAM3
     - 0x30050000
     - 0x300BFFFF
     - 448 KB
     - Non-Secure
   * - Peripherals
     - 0x40000000
     - 0x5FFFFFFF
     - 512 MB
     - Mixed (TZSC)
