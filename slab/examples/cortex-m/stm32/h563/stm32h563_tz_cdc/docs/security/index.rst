Security Overview
=================

This section documents the security architecture and ANSSI compliance
measures implemented in the STM32H563 TrustZone CDC ACM project.

Security Principles
-------------------

The project follows defense-in-depth principles:

1. **Hardware Isolation**: ARM TrustZone separates secure and non-secure worlds
2. **Memory Protection**: SAU, MPCBB, and MPU enforce access boundaries
3. **Cryptographic Security**: AES-256-GCM, SHA-256 via hardware accelerators
4. **Secure Boot**: MCUboot verifies image signatures before execution
5. **Input Validation**: All NSC functions validate parameters
6. **Compiler Hardening**: Stack protection, format string checks, etc.

Security Boundaries
-------------------

.. image:: ../diagrams/trustzone_arch.svg
   :alt: TrustZone Security Boundaries
   :align: center

The system has three security zones:

- **Secure Zone** (Green): Trusted code and data, hardware crypto
- **Non-Secure Callable** (Yellow): Gateway functions for NS to S calls
- **Non-Secure Zone** (Red): Application code, USB stack

Threat Model Summary
--------------------

Key threats addressed:

- Firmware extraction via debug interface
- Buffer overflow attacks
- Privilege escalation from NS to S
- Side-channel attacks on cryptographic operations
- Unauthorized peripheral access

Contents
--------

.. toctree::
   :maxdepth: 2

   anssi_compliance
   threat_model
   memory_isolation
   secure_boot
