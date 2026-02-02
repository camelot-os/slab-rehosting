Memory Isolation
================

This document details the memory isolation mechanisms used to enforce
TrustZone security boundaries on the STM32H563.

Hardware Security Components
----------------------------

The STM32H563 provides several hardware mechanisms for memory isolation:

1. **SAU (Security Attribution Unit)**: Core Cortex-M33 feature
2. **GTZC (Global TrustZone Controller)**: STM32-specific extension
3. **MPCBB (Memory Protection Controller Block-Based)**: SRAM protection
4. **MPU (Memory Protection Unit)**: Optional fine-grained control

SAU Configuration
-----------------

The SAU divides the address space into secure, non-secure, and NSC regions.

.. tikz:: SAU Region Layout
   :libs: arrows.meta,positioning,shapes.geometric,fit

   \begin{tikzpicture}[
       block/.style={draw, minimum width=4cm, minimum height=1cm, align=center},
       secure/.style={block, fill=green!30},
       nsc/.style={block, fill=yellow!30},
       nonsecure/.style={block, fill=red!20}
   ]

   % Flash regions
   \node[secure] (sflash) at (0,4) {Secure Flash\\0x0C000000 - 0x0C03FFFF};
   \node[nsc] (nscflash) at (0,2.8) {NSC Region\\0x0C040000 - 0x0C041FFF};
   \node[nonsecure] (nsflash) at (0,1.6) {NS Flash\\0x08042000 - 0x081FFFFF};

   % SRAM regions
   \node[secure] (ssram) at (6,4) {Secure SRAM1\\0x30000000 - 0x3003FFFF};
   \node[nonsecure] (nssram) at (6,2.4) {NS SRAM2/3\\0x20020000 - 0x2009FFFF};

   % Peripherals
   \node[nonsecure] (nsperiph) at (6,0.8) {NS Peripherals\\0x40000000 - 0x4FFFFFFF};

   % Labels
   \node[above] at (0,4.7) {\textbf{Flash Memory}};
   \node[above] at (6,4.7) {\textbf{SRAM \& Peripherals}};

   \end{tikzpicture}

SAU Initialization Code
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   /* Region 0: Non-Secure Flash */
   SAU->RNR  = 0U;
   SAU->RBAR = 0x08042000UL & SAU_RBAR_BADDR_Msk;
   SAU->RLAR = (0x081FFFFFUL & SAU_RLAR_LADDR_Msk) | SAU_RLAR_ENABLE_Msk;

   /* Region 1: Non-Secure Callable (NSC) */
   SAU->RNR  = 1U;
   SAU->RBAR = 0x0C040000UL & SAU_RBAR_BADDR_Msk;
   SAU->RLAR = (0x0C041FFFUL & SAU_RLAR_LADDR_Msk)
               | SAU_RLAR_NSC_Msk | SAU_RLAR_ENABLE_Msk;

   /* Region 2: Non-Secure SRAM */
   SAU->RNR  = 2U;
   SAU->RBAR = 0x20020000UL & SAU_RBAR_BADDR_Msk;
   SAU->RLAR = (0x2009FFFFUL & SAU_RLAR_LADDR_Msk) | SAU_RLAR_ENABLE_Msk;

   /* Region 3: Non-Secure Peripherals */
   SAU->RNR  = 3U;
   SAU->RBAR = 0x40000000UL & SAU_RBAR_BADDR_Msk;
   SAU->RLAR = (0x4FFFFFFFUL & SAU_RLAR_LADDR_Msk) | SAU_RLAR_ENABLE_Msk;

   /* Enable SAU - all uncovered memory is Secure */
   SAU->CTRL = SAU_CTRL_ENABLE_Msk;

MPCBB (SRAM Protection)
-----------------------

MPCBB provides block-based (256-byte granularity) security configuration
for internal SRAM.

SRAM1 Configuration (Secure)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   MPCBB_ConfigTypeDef MPCBB_SecureArea = {0};

   MPCBB_SecureArea.SecureRWIllegalMode = GTZC_MPCBB_SRWILADIS_ENABLE;
   MPCBB_SecureArea.InvertSecureState = GTZC_MPCBB_INVSECSTATE_NOT_INVERTED;

   /* All blocks secure (0xFFFFFFFF) */
   for (uint32_t i = 0; i < GTZC_MPCBB_NB_VCTR_REG_MAX; i++)
   {
       MPCBB_SecureArea.AttributeConfig.MPCBB_SecConfig_array[i] = 0xFFFFFFFFUL;
   }

   HAL_GTZC_MPCBB_ConfigMem(SRAM1_BASE_S, &MPCBB_SecureArea);

SRAM2/SRAM3 Configuration (Non-Secure)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   MPCBB_ConfigTypeDef MPCBB_NonSecureArea = {0};

   MPCBB_NonSecureArea.SecureRWIllegalMode = GTZC_MPCBB_SRWILADIS_ENABLE;
   MPCBB_NonSecureArea.InvertSecureState = GTZC_MPCBB_INVSECSTATE_NOT_INVERTED;

   /* All blocks non-secure (0x00000000) */
   for (uint32_t i = 0; i < GTZC_MPCBB_NB_VCTR_REG_MAX; i++)
   {
       MPCBB_NonSecureArea.AttributeConfig.MPCBB_SecConfig_array[i] = 0x00000000UL;
   }

   HAL_GTZC_MPCBB_ConfigMem(SRAM2_BASE_S, &MPCBB_NonSecureArea);
   HAL_GTZC_MPCBB_ConfigMem(SRAM3_BASE_S, &MPCBB_NonSecureArea);

GTZC TZSC (Peripheral Protection)
---------------------------------

TZSC configures the security state of peripherals.

.. list-table:: Peripheral Security Assignment
   :widths: 25 20 55
   :header-rows: 1

   * - Peripheral
     - Security
     - Rationale
   * - USART1
     - Secure
     - Debug output from secure world
   * - USB OTG FS
     - Non-Secure
     - CDC ACM runs in NS world
   * - GPDMA1 CH0-7
     - Non-Secure
     - USB DMA operations
   * - DBGMCU
     - Secure
     - Debug control protected
   * - RNG
     - Secure
     - Crypto operations

Configuration Code
^^^^^^^^^^^^^^^^^^

.. code-block:: c

   /* USB OTG FS: Non-Secure (for CDC ACM) */
   HAL_GTZC_TZSC_ConfigPeriphAttributes(GTZC_PERIPH_USB, GTZC_TZSC_PERIPH_NSEC);

   /* GPDMA channels: Non-Secure (for USB DMA) */
   HAL_GTZC_TZSC_ConfigPeriphAttributes(GTZC_PERIPH_GPDMA1_CH0, GTZC_TZSC_PERIPH_NSEC);
   /* ... repeat for CH1-CH7 ... */

   /* DBGMCU: Secure (protect debug control) */
   HAL_GTZC_TZSC_ConfigPeriphAttributes(GTZC_PERIPH_DBGMCU, GTZC_TZSC_PERIPH_SEC);

Illegal Access Detection
------------------------

GTZC can generate interrupts on illegal access attempts:

.. code-block:: c

   /* Enable GTZC secure interrupt */
   HAL_NVIC_SetPriority(GTZC_IRQn, 0, 0);
   HAL_NVIC_EnableIRQ(GTZC_IRQn);

The interrupt handler logs the violation and can trigger a system reset:

.. code-block:: c

   void GTZC_IRQHandler(void)
   {
       /* Log violation details */
       /* Optional: Reset system for security */
   }

Memory Map Diagram
------------------

.. tikz:: Complete Memory Map
   :libs: arrows.meta,positioning

   \begin{tikzpicture}[
       memblock/.style={draw, minimum width=5cm, align=center, font=\small},
       secure/.style={memblock, fill=green!20},
       nsc/.style={memblock, fill=yellow!30},
       nonsecure/.style={memblock, fill=red!15},
       addr/.style={font=\tiny\ttfamily, anchor=east}
   ]

   % Addresses on left
   \node[addr] at (-0.1,7) {0x0C000000};
   \node[addr] at (-0.1,5.5) {0x0C040000};
   \node[addr] at (-0.1,4.5) {0x0C042000};
   \node[addr] at (-0.1,3) {0x08042000};
   \node[addr] at (-0.1,1.5) {0x08200000};

   % Flash regions
   \node[secure, minimum height=1.5cm] (sf) at (2.5,6.25) {Secure Flash\\(256 KB)};
   \node[nsc, minimum height=0.8cm] (nsc) at (2.5,5) {NSC Region\\(8 KB)};
   \node[nonsecure, minimum height=2cm] (nsf) at (2.5,3.5) {Non-Secure Flash\\(~1.75 MB)};

   % SRAM column
   \node[addr] at (6.9,7) {0x30000000};
   \node[addr] at (6.9,5.5) {0x30040000};
   \node[addr] at (6.9,3) {0x300C0000};

   \node[secure, minimum height=1.5cm] at (9.5,6.25) {SRAM1 (Secure)\\(256 KB)};
   \node[nonsecure, minimum height=2.5cm] at (9.5,4) {SRAM2/3 (NS)\\(320 KB)};

   % Legend
   \node[secure, minimum height=0.5cm, minimum width=1.5cm] at (2,-0.5) {};
   \node[right] at (3,-0.5) {Secure};
   \node[nsc, minimum height=0.5cm, minimum width=1.5cm] at (5.5,-0.5) {};
   \node[right] at (6.5,-0.5) {NSC};
   \node[nonsecure, minimum height=0.5cm, minimum width=1.5cm] at (9,-0.5) {};
   \node[right] at (10,-0.5) {Non-Secure};

   \end{tikzpicture}
