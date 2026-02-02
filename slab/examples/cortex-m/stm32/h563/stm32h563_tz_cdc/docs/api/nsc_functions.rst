NSC Functions Reference
=======================

Non-Secure Callable (NSC) functions provide controlled access from the
non-secure world to secure services.

Header File
-----------

Include the shared header in non-secure code:

.. code-block:: c

   #include "secure_nsc.h"

Functions
---------

SECURE_UART_Print
^^^^^^^^^^^^^^^^^

Print a debug message via the secure UART1.

**Prototype:**

.. code-block:: c

   int32_t SECURE_UART_Print(const char *msg, uint32_t len);

**Parameters:**

- ``msg``: Pointer to message string (must be in NS memory)
- ``len``: Length of the message in bytes

**Returns:**

- ``0``: Success
- ``-1``: Error (invalid pointer or UART failure)

**Security:**

- Validates pointer is in non-secure memory (CMSE check)
- Limits message length to ``SECURE_UART_MAX_MSG_LEN`` (256 bytes)
- Null pointer check

**Example:**

.. code-block:: c

   const char *msg = "Hello from NS world!\r\n";
   int32_t result = SECURE_UART_Print(msg, strlen(msg));

   if (result != 0)
   {
       /* Handle error */
   }

SECURE_GetSecurityStatus
^^^^^^^^^^^^^^^^^^^^^^^^

Query the current TrustZone security status.

**Prototype:**

.. code-block:: c

   uint32_t SECURE_GetSecurityStatus(void);

**Parameters:**

None.

**Returns:**

Bitmask of security status flags:

- Bit 0: SAU enabled
- Bit 1: GTZC configured

**Example:**

.. code-block:: c

   uint32_t status = SECURE_GetSecurityStatus();

   if (status & 0x01)
       printf("SAU is enabled\n");

   if (status & 0x02)
       printf("GTZC is configured\n");

SECURE_LED_Toggle
^^^^^^^^^^^^^^^^^

Toggle the secure LED (PB0 on NUCLEO-H563ZI).

**Prototype:**

.. code-block:: c

   void SECURE_LED_Toggle(void);

**Parameters:**

None.

**Returns:**

None.

**Notes:**

This provides controlled access to the secure-owned LED GPIO.
The non-secure world cannot directly access this peripheral.

**Example:**

.. code-block:: c

   /* Toggle LED as activity indicator */
   SECURE_LED_Toggle();

Security Considerations
-----------------------

Pointer Validation
^^^^^^^^^^^^^^^^^^

All NSC functions must validate pointers from the non-secure world:

.. code-block:: c

   /* Validate pointer is in NS memory with read permission */
   if (cmse_check_address_range((void *)ptr, size,
                                CMSE_NONSECURE | CMSE_MPU_READ) == NULL)
   {
       return -1;  /* Invalid pointer */
   }

This prevents:

- NULL pointer dereference
- Access to secure memory through crafted pointers
- Buffer overflows from excessive lengths

Rate Limiting
^^^^^^^^^^^^^

For production systems, consider rate limiting NSC calls:

.. code-block:: c

   static volatile uint32_t call_count = 0;
   #define MAX_CALLS_PER_PERIOD  1000

   CMSE_NS_ENTRY int32_t SECURE_Function(...)
   {
       if (call_count >= MAX_CALLS_PER_PERIOD)
           return -1;  /* Rate limited */

       call_count++;
       /* ... function body ... */
   }

Minimal Attack Surface
^^^^^^^^^^^^^^^^^^^^^^

Keep NSC functions simple and minimal:

- Validate all inputs
- Don't expose internal details
- Return generic error codes in production
- Limit functionality to what's necessary

Adding New NSC Functions
------------------------

To add a new NSC function:

1. **Declare in secure_nsc.h:**

   .. code-block:: c

      int32_t SECURE_NewFunction(uint32_t param1, const void *data, uint32_t len);

2. **Implement in secure_nsc.c:**

   .. code-block:: c

      CMSE_NS_ENTRY int32_t SECURE_NewFunction(uint32_t param1,
                                                const void *data,
                                                uint32_t len)
      {
          /* Validate pointer */
          if (NSC_ValidatePointer(data, len, 1, 0) != 0)
          {
              return -1;
          }

          /* Implement secure operation */
          /* ... */

          return 0;
      }

3. **Ensure placement in NSC section:**

   The ``CMSE_NS_ENTRY`` attribute places the function in the
   ``.gnu.sgstubs`` section, which is mapped to the NSC region.

4. **Rebuild both secure and non-secure projects:**

   The linker generates an import library (``secure_nsc_lib.o``)
   that the non-secure project links against.
