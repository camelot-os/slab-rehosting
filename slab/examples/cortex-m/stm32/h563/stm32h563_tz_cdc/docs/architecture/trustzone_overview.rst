TrustZone Overview
==================

ARM TrustZone provides hardware-enforced isolation between secure
and non-secure software.

TrustZone Concepts
------------------

Security States
^^^^^^^^^^^^^^^

The Cortex-M33 processor can execute in two security states:

- **Secure State**: Full access to all resources
- **Non-Secure State**: Restricted access as defined by SAU/IDAU

Transitions between states are controlled by hardware.

Memory Attributes
^^^^^^^^^^^^^^^^^

Each memory region has one of three security attributes:

- **Secure (S)**: Only accessible from secure state
- **Non-Secure (NS)**: Accessible from both states
- **Non-Secure Callable (NSC)**: Entry point for secure functions

.. tikz:: Security State Transitions
   :libs: arrows.meta,positioning,shapes.geometric

   \begin{tikzpicture}[
       node distance=3cm,
       state/.style={draw, circle, minimum size=2.5cm, align=center, thick},
       arrow/.style={-{Stealth[length=3mm]}, thick}
   ]

   \node[state, fill=green!30] (secure) {Secure\\State};
   \node[state, fill=red!20, right=of secure] (nonsecure) {Non-Secure\\State};

   \draw[arrow, bend left=20] (nonsecure) to node[above] {SG instruction\\(NSC region)} (secure);
   \draw[arrow, bend left=20] (secure) to node[below] {BXNS/BLXNS} (nonsecure);

   \end{tikzpicture}

SAU (Security Attribution Unit)
-------------------------------

The SAU is a Cortex-M33 core feature that defines up to 8 memory regions
with security attributes.

Our configuration uses 4 regions:

.. list-table:: SAU Regions
   :widths: 10 25 25 20 20
   :header-rows: 1

   * - Region
     - Start
     - End
     - Attribute
     - Purpose
   * - 0
     - 0x08042000
     - 0x081FFFFF
     - NS
     - Non-secure Flash
   * - 1
     - 0x0C040000
     - 0x0C041FFF
     - NSC
     - Secure gateway
   * - 2
     - 0x20020000
     - 0x2009FFFF
     - NS
     - Non-secure SRAM
   * - 3
     - 0x40000000
     - 0x4FFFFFFF
     - NS
     - Peripherals

All memory not covered by SAU regions is treated as **Secure**.

IDAU (Implementation-Defined Attribution Unit)
----------------------------------------------

The IDAU is an STM32-specific extension that provides additional
memory attribution. On STM32H563:

- Flash at 0x0C000000+ is the secure alias
- Flash at 0x08000000+ is the non-secure alias
- SRAM at 0x30000000+ is the secure alias
- SRAM at 0x20000000+ is the non-secure alias

The SAU works together with IDAU. Memory must pass both checks
to be accessible.

NSC (Non-Secure Callable) Region
--------------------------------

The NSC region is a special memory area that:

1. Contains entry points (veneers) for secure functions
2. Can be called from non-secure code
3. Transitions the processor to secure state

Gateway Function Example
^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   /* In secure_nsc.c - placed in NSC region */
   CMSE_NS_ENTRY int32_t SECURE_UART_Print(const char *msg, uint32_t len)
   {
       /* Validate NS pointer */
       if (cmse_check_address_range((void *)msg, len,
                                    CMSE_NONSECURE | CMSE_MPU_READ) == NULL)
       {
           return -1;
       }

       /* Perform secure operation */
       HAL_UART_Transmit(&huart1, (uint8_t *)msg, len, 1000);
       return 0;
   }

The ``CMSE_NS_ENTRY`` attribute:

- Generates an SG (Secure Gateway) instruction at function start
- Places function in the NSC linker section

Calling from Non-Secure
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   /* In NS main.c */
   #include "secure_nsc.h"

   void print_message(void)
   {
       const char *msg = "Hello from NS!\r\n";
       SECURE_UART_Print(msg, strlen(msg));
   }

The call transparently:

1. Executes SG instruction (validates NSC region)
2. Transitions to secure state
3. Runs secure function
4. Returns to non-secure state

CMSE (C/C++ Security Extensions)
--------------------------------

CMSE provides compiler intrinsics for TrustZone:

.. code-block:: c

   #include <arm_cmse.h>

   /* Check if pointer is valid NS memory */
   void *cmse_check_address_range(void *ptr, size_t size, int flags);

   /* Check if pointer is NS-callable */
   void *cmse_check_pointed_object(void *ptr, int flags);

   /* TT (Test Target) instruction wrapper */
   cmse_address_info_t cmse_TT(void *ptr);

Flags:

- ``CMSE_NONSECURE``: Pointer must be in NS memory
- ``CMSE_MPU_READ``: Read access required
- ``CMSE_MPU_READWRITE``: Read/write access required

Architecture Diagram
--------------------

.. tikz:: TrustZone Architecture
   :libs: arrows.meta,positioning,shapes.geometric,fit,backgrounds

   \begin{tikzpicture}[
       world/.style={draw, rounded corners, minimum width=6cm, minimum height=8cm},
       component/.style={draw, rounded corners, minimum width=5cm, minimum height=1cm, align=center},
       nsc/.style={draw, rounded corners, fill=yellow!30, minimum width=2cm, minimum height=2cm, align=center},
       arrow/.style={-{Stealth[length=3mm]}, thick}
   ]

   % Secure World
   \begin{scope}[on background layer]
       \node[world, fill=green!10] (sworld) at (0,0) {};
   \end{scope}
   \node[above] at (0,4.2) {\textbf{Secure World}};

   \node[component, fill=green!30] (crypto) at (0,3) {Crypto Services\\(AES, SHA, RNG)};
   \node[component, fill=green!30] (storage) at (0,1.5) {Secure Storage};
   \node[component, fill=green!30] (gtzc) at (0,0) {GTZC Controller};
   \node[component, fill=green!30] (uart) at (0,-1.5) {Debug UART};
   \node[component, fill=green!30] (boot) at (0,-3) {Secure Boot\\(MCUboot)};

   % NSC Gateway
   \node[nsc] (nscgate) at (4,0) {NSC\\Gateway};

   % Non-Secure World
   \begin{scope}[on background layer]
       \node[world, fill=red!10] (nsworld) at (8,0) {};
   \end{scope}
   \node[above] at (8,4.2) {\textbf{Non-Secure World}};

   \node[component, fill=red!20] (app) at (8,3) {Application Logic};
   \node[component, fill=red!20] (usb) at (8,1.5) {USB CDC Stack\\(USBX)};
   \node[component, fill=red!20] (threadx) at (8,0) {ThreadX RTOS};
   \node[component, fill=red!20] (hal) at (8,-1.5) {HAL Drivers};

   % Arrows
   \draw[arrow] (app) -- (nscgate);
   \draw[arrow] (nscgate) -- (crypto);
   \draw[arrow] (nscgate) -- (storage);

   % Labels
   \node[below] at (4,-4.5) {\small Controlled transition via SG instruction};

   \end{tikzpicture}
