Secure World
============

The secure world contains security-critical code that runs with full
hardware access and manages TrustZone configuration.

Responsibilities
----------------

The secure world handles:

1. **System Initialization**
   - SAU configuration
   - GTZC/MPCBB setup
   - Clock configuration
   - Watchdog initialization

2. **Security Services**
   - NSC gateway functions
   - Debug output via secure UART
   - Security status reporting

3. **Boot Management**
   - NS image validation
   - Transition to non-secure world
   - Debug interface control

Boot Sequence
-------------

.. tikz:: Secure Boot Sequence
   :libs: arrows.meta,positioning,shapes.geometric

   \begin{tikzpicture}[
       node distance=0.8cm,
       block/.style={draw, rounded corners, minimum width=4cm, minimum height=0.7cm, align=center, font=\small},
       arrow/.style={-{Stealth[length=2mm]}, thick}
   ]

   \node[block, fill=gray!30] (reset) {Reset Vector};
   \node[block, fill=green!30, below=of reset] (sau) {SAU\_Setup()};
   \node[block, fill=green!30, below=of sau] (hal) {HAL\_Init()};
   \node[block, fill=green!30, below=of hal] (clock) {SystemClock\_Config()};
   \node[block, fill=green!30, below=of clock] (gtzc) {MX\_GTZC\_S\_Init()};
   \node[block, fill=green!30, below=of gtzc] (dma) {Security\_ConfigureGPDMA()};
   \node[block, fill=green!30, below=of dma] (gpio) {MX\_GPIO\_Init()};
   \node[block, fill=green!30, below=of gpio] (uart) {MX\_USART1\_UART\_Init()};
   \node[block, fill=green!30, below=of uart] (iwdg) {MX\_IWDG\_Init()};
   \node[block, fill=yellow!30, below=of iwdg] (ns) {NonSecure\_Init()};

   \draw[arrow] (reset) -- (sau);
   \draw[arrow] (sau) -- (hal);
   \draw[arrow] (hal) -- (clock);
   \draw[arrow] (clock) -- (gtzc);
   \draw[arrow] (gtzc) -- (dma);
   \draw[arrow] (dma) -- (gpio);
   \draw[arrow] (gpio) -- (uart);
   \draw[arrow] (uart) -- (iwdg);
   \draw[arrow] (iwdg) -- (ns);

   \end{tikzpicture}

Key Functions
-------------

main()
^^^^^^

Entry point after reset:

.. code-block:: c

   int main(void)
   {
       /* Configure SAU regions */
       SAU_Setup();

       /* Initialize HAL */
       HAL_Init();

       /* Configure 250 MHz system clock */
       SystemClock_Config();

       /* Configure GTZC for memory/peripheral security */
       MX_GTZC_S_Init();

       /* Configure GPDMA channel security */
       Security_ConfigureGPDMA();

       /* Initialize secure peripherals */
       MX_GPIO_Init();
       MX_USART1_UART_Init();

       /* Enable watchdog */
       MX_IWDG_Init();

       /* Lock debug interface (production only) */
       Security_LockDebugInterface();

       /* Print boot message */
       HAL_UART_Transmit(&huart1, boot_msg, strlen(boot_msg), HAL_MAX_DELAY);

       /* Boot non-secure application */
       NonSecure_Init();

       /* Never reached */
       while (1) {}
   }

NonSecure_Init()
^^^^^^^^^^^^^^^^

Validates and jumps to NS application:

.. code-block:: c

   static void NonSecure_Init(void)
   {
       uint32_t ns_vector_table = VTOR_TABLE_NS_START_ADDR;

       /* Validate NS image */
       if (Security_ValidateNSImage(ns_vector_table) != 0)
       {
           Error_Handler();  /* Halt on validation failure */
       }

       /* Set NS vector table */
       SCB_NS->VTOR = ns_vector_table;

       /* Get NS stack pointer and reset handler */
       uint32_t ns_stack_ptr = *((uint32_t *)ns_vector_table);
       funcptr_NS ns_reset = (funcptr_NS)(*((uint32_t *)(ns_vector_table + 4)));

       /* Set NS stack pointer and jump */
       __TZ_set_MSP_NS(ns_stack_ptr);
       ns_reset();
   }

NSC Gateway Functions
---------------------

The secure world exports functions callable from NS through the NSC region.

SECURE_UART_Print()
^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   CMSE_NS_ENTRY int32_t SECURE_UART_Print(const char *msg, uint32_t len)
   {
       /* Validate NS pointer */
       if (NSC_ValidatePointer(msg, len, 1, 0) != 0)
       {
           return -1;
       }

       /* Limit length */
       if (len > SECURE_UART_MAX_MSG_LEN)
       {
           len = SECURE_UART_MAX_MSG_LEN;
       }

       /* Transmit */
       HAL_UART_Transmit(&huart1, (uint8_t *)msg, (uint16_t)len, 1000);
       return 0;
   }

SECURE_GetSecurityStatus()
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   CMSE_NS_ENTRY uint32_t SECURE_GetSecurityStatus(void)
   {
       uint32_t status = 0;

       /* Bit 0: SAU enabled */
       if (SAU->CTRL & SAU_CTRL_ENABLE_Msk)
           status |= (1UL << 0);

       /* Bit 1: GTZC configured */
       status |= (1UL << 1);

       return status;
   }

SECURE_LED_Toggle()
^^^^^^^^^^^^^^^^^^^

.. code-block:: c

   CMSE_NS_ENTRY void SECURE_LED_Toggle(void)
   {
       HAL_GPIO_TogglePin(LED_GREEN_PORT, LED_GREEN_PIN);
   }

Security Configuration
----------------------

security_config.h
^^^^^^^^^^^^^^^^^

Centralizes security settings:

.. code-block:: c

   /* Production mode enables security lockdown */
   #define PRODUCTION_MODE             0

   /* Debug interface protection */
   #if PRODUCTION_MODE
   #define SECURITY_LOCK_DEBUG         1
   #else
   #define SECURITY_LOCK_DEBUG         0
   #endif

   /* NS image validation */
   #define SECURITY_VERIFY_NS_IMAGE    1
   #define NS_STACK_PTR_MIN            0x20020000UL
   #define NS_STACK_PTR_MAX            0x200A0000UL
   #define NS_RESET_HANDLER_MIN        0x08042000UL
   #define NS_RESET_HANDLER_MAX        0x08200000UL

   /* Watchdog */
   #define SECURITY_ENABLE_IWDG        1

   /* GPDMA security */
   #define SECURITY_CONFIGURE_GPDMA    1

   /* SRAM1 explicit configuration */
   #define SECURITY_EXPLICIT_SRAM1     1

File Structure
--------------

.. code-block:: text

   Secure/
   +-- Inc/
   |   +-- main.h                 # Pin definitions, function prototypes
   |   +-- partition_stm32h563xx.h # SAU region definitions
   |   +-- security_config.h      # Security configuration
   |   +-- stm32h5xx_hal_conf.h   # HAL configuration
   |   +-- stm32h5xx_it.h         # Interrupt handlers
   +-- Src/
   |   +-- main.c                 # Main secure code
   |   +-- secure_nsc.c           # NSC gateway functions
   |   +-- stm32h5xx_it.c         # Interrupt handlers
   |   +-- system_stm32h5xx_s.c   # System initialization
   +-- STM32CubeIDE/
       +-- STM32H563ZITX_FLASH_S.ld # Secure linker script
