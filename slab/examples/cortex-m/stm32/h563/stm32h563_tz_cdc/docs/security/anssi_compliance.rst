ANSSI Compliance Checklist
==========================

This document tracks compliance with ANSSI (French National Cybersecurity Agency)
recommendations for secure embedded systems.

Compliance Summary
------------------

.. list-table:: ANSSI Compliance Status
   :widths: 10 40 15 35
   :header-rows: 1

   * - ID
     - Recommendation
     - Status
     - Implementation
   * - SEC-01
     - Stack Protection
     - COMPLIANT
     - ``-fstack-protector-strong`` enabled
   * - SEC-02
     - Format String Protection
     - COMPLIANT
     - ``-Wformat-security -Werror=format-security``
   * - SEC-03
     - Buffer Overflow Detection
     - COMPLIANT
     - ``-D_FORTIFY_SOURCE=2``
   * - SEC-04
     - Secure Boot Chain
     - COMPLIANT
     - MCUboot (BL2) enabled with RSA-3072 signatures
   * - SEC-05
     - Debug Interface Lockout
     - COMPLIANT
     - SWD disabled in production mode
   * - SEC-06
     - Memory Isolation
     - COMPLIANT
     - SAU + MPCBB configured for all regions
   * - SEC-07
     - Peripheral Isolation
     - COMPLIANT
     - GTZC TZSC configures all peripherals
   * - SEC-08
     - Watchdog
     - COMPLIANT
     - IWDG enabled with 8s timeout
   * - SEC-09
     - Cryptography (AES-128+)
     - COMPLIANT
     - AES-256-GCM via PSA Crypto
   * - SEC-10
     - Random Number Generation
     - COMPLIANT
     - Hardware TRNG via PSA
   * - SEC-11
     - Flash Protection (RDP)
     - PARTIAL
     - RDP Level 1 recommended; Level 2 for production
   * - SEC-12
     - Input Validation
     - COMPLIANT
     - CMSE checks on all NSC parameters
   * - SEC-13
     - Error Handling
     - COMPLIANT
     - Errors don't leak security info in production
   * - SEC-14
     - DMA Security
     - COMPLIANT
     - All GPDMA channels explicitly configured
   * - SEC-15
     - Clock Security
     - PARTIAL
     - CSS not enabled (application-specific)

Compiler Security Flags
-----------------------

The following compiler flags are enabled for both secure and non-secure builds:

.. code-block:: cmake

   # Stack protection against buffer overflows
   -fstack-protector-strong

   # Fortify source for runtime buffer overflow detection
   -D_FORTIFY_SOURCE=2

   # Format string vulnerability protection
   -Wformat -Wformat-security -Werror=format-security

   # Additional security warnings
   -Wconversion -Wsign-conversion -Wstrict-overflow=2

   # Position independent code
   -fPIC

   # Trap on signed overflow
   -ftrapv

Memory Protection Configuration
-------------------------------

SAU Regions
^^^^^^^^^^^

.. list-table:: SAU Configuration
   :widths: 10 30 30 15 15
   :header-rows: 1

   * - Region
     - Start Address
     - End Address
     - Type
     - Size
   * - 0
     - 0x08042000
     - 0x081FFFFF
     - Non-Secure
     - ~1.75 MB
   * - 1
     - 0x0C040000
     - 0x0C041FFF
     - NSC
     - 8 KB
   * - 2
     - 0x20020000
     - 0x2009FFFF
     - Non-Secure
     - 512 KB
   * - 3
     - 0x40000000
     - 0x4FFFFFFF
     - Non-Secure
     - Peripherals

MPCBB Configuration
^^^^^^^^^^^^^^^^^^^

.. list-table:: SRAM Security
   :widths: 25 30 20 25
   :header-rows: 1

   * - Memory
     - Address Range
     - Security
     - Configuration
   * - SRAM1
     - 0x30000000 - 0x3003FFFF
     - Secure
     - Explicit 0xFFFFFFFF
   * - SRAM2
     - 0x30040000 - 0x3004FFFF
     - Non-Secure
     - Explicit 0x00000000
   * - SRAM3
     - 0x30050000 - 0x300BFFFF
     - Non-Secure
     - Explicit 0x00000000

Cryptographic Compliance
------------------------

The following cryptographic algorithms are used:

- **Symmetric Encryption**: AES-256-GCM (NIST approved)
- **Hash Functions**: SHA-256 (NIST approved)
- **Key Derivation**: HKDF-SHA256
- **Random Generation**: Hardware TRNG (STM32 RNG peripheral)
- **Signature Verification**: RSA-3072 (MCUboot)

All cryptographic operations are performed in the secure world using
hardware accelerators when available.

Production Deployment Checklist
-------------------------------

Before deploying to production:

.. code-block:: text

   [ ] Set PRODUCTION_MODE=1 in security_config.h
   [ ] Verify MCUboot signatures are from production keys
   [ ] Configure RDP Level 2 (IRREVERSIBLE - test with Level 1 first!)
   [ ] Enable BOOT_LOCK option byte
   [ ] Remove debug UART messages or use secure channel
   [ ] Verify all NSC functions have proper input validation
   [ ] Run static analysis (MISRA, Coverity, etc.)
   [ ] Perform penetration testing
   [ ] Document any security exceptions

References
----------

- ANSSI: Guide de Bonnes Pratiques pour les Systemes Embarques
- ARM: TrustZone Technology for ARMv8-M Architecture
- PSA Certified: Level 1 Requirements
- STMicroelectronics: STM32H5 Security Reference Manual (RM0481)
