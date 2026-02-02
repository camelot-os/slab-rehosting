STM32H563 TrustZone CDC ACM Documentation
==========================================

Welcome to the documentation for the STM32H563 TrustZone CDC ACM project.
This project demonstrates a secure embedded system implementation using
ARM TrustZone technology on the STM32H563 microcontroller, with ANSSI
security compliance.

.. warning::

   This documentation covers security-critical implementation details.
   Ensure proper access control for production deployments.

Overview
--------

This project provides two implementation variants:

1. **Bare-metal TrustZone** (``stm32h563_tz_cdc``): Direct TrustZone
   implementation with custom secure/non-secure partitioning.

2. **TF-M Based** (``stm32h563_tfm_cdc``): PSA-certified TrustZone
   implementation using ARM Trusted Firmware-M.

Both variants implement a USB CDC ACM (virtual COM port) interface with
secure cryptographic services.

Key Features
------------

- ARM TrustZone hardware isolation
- ANSSI-compliant security hardening
- PSA Crypto API (AES-256-GCM, SHA-256)
- Secure boot chain (MCUboot)
- GTZC peripheral/memory protection
- USB CDC ACM communication

Contents
--------

.. toctree::
   :maxdepth: 2
   :caption: Security

   security/index
   security/anssi_compliance
   security/threat_model
   security/memory_isolation
   security/secure_boot

.. toctree::
   :maxdepth: 2
   :caption: Architecture

   architecture/index
   architecture/trustzone_overview
   architecture/memory_map
   architecture/secure_world
   architecture/nonsecure_world

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/index
   api/nsc_functions
   api/psa_demo

.. toctree::
   :maxdepth: 2
   :caption: Build & Deploy

   build/index
   build/prerequisites
   build/building
   build/flashing

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
