API Reference
=============

This section documents the APIs provided by the STM32H563 TrustZone
CDC ACM project.

Available APIs
--------------

**NSC Functions (Bare-metal TrustZone)**

Functions callable from non-secure world to access secure services:

- ``SECURE_UART_Print()`` - Debug output via secure UART
- ``SECURE_GetSecurityStatus()`` - Query TrustZone status
- ``SECURE_LED_Toggle()`` - Toggle secure LED

**PSA APIs (TF-M Variant)**

ARM Platform Security Architecture APIs:

- **PSA Crypto** - Encryption, hashing, key management
- **PSA Protected Storage** - Encrypted data storage
- **PSA Attestation** - Device attestation tokens

Contents
--------

.. toctree::
   :maxdepth: 2

   nsc_functions
   psa_demo
