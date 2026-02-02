Architecture Overview
=====================

This section describes the system architecture of the STM32H563
TrustZone CDC ACM project.

System Architecture
-------------------

The system is divided into two isolated execution environments:

- **Secure World**: Handles security-critical operations
- **Non-Secure World**: Runs the USB CDC application

Communication between worlds occurs through the Non-Secure Callable (NSC)
gateway region.

.. image:: ../diagrams/trustzone_arch.svg
   :alt: TrustZone Architecture
   :align: center

Hardware Platform
-----------------

**STM32H563ZI (NUCLEO-H563ZI)**

- ARM Cortex-M33 @ 250 MHz
- TrustZone security extensions
- 2 MB Flash, 640 KB SRAM
- GTZC security controller
- Hardware crypto accelerators (AES, SHA, RNG)
- USB OTG Full-Speed

Project Variants
----------------

This repository contains two implementation variants:

**1. Bare-metal TrustZone (stm32h563_tz_cdc)**

- Direct TrustZone implementation
- Custom secure/non-secure partitioning
- Lightweight (no OS dependencies)
- Good for understanding TrustZone fundamentals

**2. TF-M Based (stm32h563_tfm_cdc)**

- ARM Trusted Firmware-M
- PSA Certified architecture
- PSA Crypto, Protected Storage, Attestation APIs
- Production-ready security services

Directory Structure
-------------------

.. code-block:: text

   stm32h563_tz_cdc/
   +-- Secure/              # Secure world firmware
   |   +-- Src/main.c       # SAU/GTZC setup, NS boot
   |   +-- Src/secure_nsc.c # NSC gateway functions
   |   +-- Inc/             # Secure headers
   +-- NonSecure/           # Non-secure application
   |   +-- Src/main.c       # USB CDC application
   |   +-- Src/ux_*.c       # USBX device stack
   +-- Secure_nsclib/       # Shared NSC header
   +-- CMakeLists.txt       # Build configuration
   +-- docs/                # This documentation

   stm32h563_tfm_cdc/
   +-- app_ns/              # Non-secure application
   |   +-- Src/main.c       # PSA API demo
   |   +-- Src/psa_*.c      # Crypto/Storage examples
   +-- tfm_config/          # TF-M build configuration
   +-- CMakeLists.txt       # NS app build
   +-- setup.sh             # TF-M clone/build script

Contents
--------

.. toctree::
   :maxdepth: 2

   trustzone_overview
   memory_map
   secure_world
   nonsecure_world
