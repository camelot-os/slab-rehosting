Threat Model
============

This document describes the threat model for the STM32H563 TrustZone
CDC ACM system, identifying assets, threats, and mitigations.

Assets
------

Critical Assets
^^^^^^^^^^^^^^^

1. **Cryptographic Keys**
   - AES-256 encryption keys
   - Device attestation keys
   - MCUboot signing keys (not stored on device)

2. **Secure Firmware**
   - Secure world code and data
   - NSC gateway implementations
   - Boot chain integrity

3. **Protected Storage**
   - User credentials
   - Configuration data
   - Audit logs

Secondary Assets
^^^^^^^^^^^^^^^^

1. **Non-Secure Application**
   - USB CDC functionality
   - User interface logic

2. **Communication Channels**
   - USB data transfer
   - Debug UART (development only)

Threat Actors
-------------

.. list-table:: Threat Actors
   :widths: 20 30 25 25
   :header-rows: 1

   * - Actor
     - Capability
     - Motivation
     - Access
   * - Remote Attacker
     - USB protocol exploitation
     - Data theft, DoS
     - USB interface only
   * - Local Attacker
     - Physical access, debug probes
     - Firmware extraction
     - Physical device access
   * - Supply Chain
     - Firmware modification
     - Backdoor insertion
     - Pre-deployment
   * - Insider
     - Source code access
     - Intentional weakness
     - Development process

Threats and Mitigations
-----------------------

T1: Firmware Extraction via Debug Interface
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Attacker uses SWD/JTAG to dump secure firmware.

**Risk**: HIGH

**Mitigations**:

- Debug interface disabled in production (SECURITY_LOCK_DEBUG)
- RDP Level 2 permanently disables debug access
- DBGMCU configured as secure peripheral

.. code-block:: c

   /* From security_config.h */
   #if PRODUCTION_MODE
   #define SECURITY_LOCK_DEBUG  1
   #endif

T2: Buffer Overflow in NSC Functions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Malicious NS code passes crafted parameters to overflow
secure buffers.

**Risk**: CRITICAL

**Mitigations**:

- CMSE pointer validation for all NSC parameters
- Length limits enforced (SECURE_UART_MAX_MSG_LEN)
- Stack canaries via -fstack-protector-strong

.. code-block:: c

   /* From secure_nsc.c */
   if (NSC_ValidatePointer(msg, len, 1, 0) != 0)
   {
       return -1;  /* Invalid pointer */
   }

T3: Privilege Escalation NS to S
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Compromised NS code attempts to access secure resources
or execute secure code.

**Risk**: CRITICAL

**Mitigations**:

- SAU enforces memory security attributes
- MPCBB protects SRAM1 as secure-only
- GTZC TZSC controls peripheral access
- Only NSC region callable from NS

T4: DMA-Based Memory Access
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: NS code configures DMA to read/write secure memory.

**Risk**: HIGH

**Mitigations**:

- All GPDMA channels explicitly configured
- MPCBB enforces DMA access restrictions
- DMA transactions cannot bypass TrustZone

T5: USB Protocol Attacks
^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Malformed USB packets cause buffer overflows or DoS.

**Risk**: MEDIUM

**Mitigations**:

- Bounds checking in USB string framework
- USB stack runs in NS (isolated from secrets)
- Rate limiting on NSC calls

T6: Side-Channel Attacks
^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Power/timing analysis extracts cryptographic keys.

**Risk**: MEDIUM (requires specialized equipment)

**Mitigations**:

- Hardware crypto accelerators (constant-time)
- PSA Crypto abstracts implementation details
- Keys never leave secure world

T7: Secure Boot Bypass
^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Attacker modifies NS image to inject malicious code.

**Risk**: HIGH

**Mitigations**:

- MCUboot verifies RSA-3072 signatures
- Image hash validated before execution
- Boot chain validates NS stack/reset handler

.. code-block:: c

   /* From main.c */
   if (Security_ValidateNSImage(ns_vector_table) != 0)
   {
       Error_Handler();  /* Halt on validation failure */
   }

T8: Supply Chain Compromise
^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Threat**: Malicious firmware inserted during manufacturing.

**Risk**: HIGH

**Mitigations**:

- Secure boot with hardware-rooted keys
- Device attestation via PSA
- Firmware signing with offline keys

Attack Surface
--------------

.. list-table:: Attack Surface
   :widths: 20 30 25 25
   :header-rows: 1

   * - Entry Point
     - Protocol
     - Trust Level
     - Mitigations
   * - USB CDC
     - USB 2.0
     - Untrusted
     - Input validation, NS isolation
   * - NSC Gateway
     - Function calls
     - NS (low trust)
     - CMSE validation, length checks
   * - Debug UART
     - Serial
     - Trusted (dev only)
     - Disabled in production
   * - SWD/JTAG
     - Debug
     - Trusted (dev only)
     - Locked in production

Security Assumptions
--------------------

1. Hardware is not physically tampered with (no fault injection)
2. Boot ROM is trusted and not modified
3. Option bytes are configured correctly before deployment
4. Signing keys are protected offline
5. Attacker does not have unlimited time/resources for side-channel analysis
