.. _changelog:

=========
Changelog
=========

Version 1.0.0 (2026-01-25)
==========================

Initial release of MCUemu.

Features
--------

* **QEMU slab-cortex-m Machine**

  - Support for all Cortex-M variants (M0, M0+, M3, M4, M7, M23, M33, M55, M85)
  - TrustZone support for ARMv8-M cores
  - Dual-core support for STM32H7, RP2040, RP2350
  - TCP and POSIX SHM peripheral proxy modes

* **Peripheral Libraries**

  - STM32: F0, F1, F4, H5, H7, L4, U5, WB families
  - Nordic: nRF52840, nRF5340
  - NXP: LPC55S69, i.MX RT1060
  - Raspberry Pi: RP2040, RP2350

* **Cryptographic Peripherals**

  - STM32 CRYP: AES-128/192/256, DES, TDES
  - STM32 HASH: MD5, SHA-1, SHA-224, SHA-256
  - NIST FIPS-197 validation

* **USB Support**

  - USB OTG FS/HS peripheral emulation
  - USBIP server for host integration
  - CDC-ACM device class support

* **Debug Dashboard**

  - Start/Stop/Reset controls
  - Real-time logic analyzer with zoom/pan
  - Dual console with input fields
  - LED status display
  - VCD and Sigrok export

* **Documentation**

  - Comprehensive Sphinx documentation
  - Tutorials for firmware emulation
  - Peripheral stubbing guide
  - API reference

Known Issues
------------

* USB host mode not yet supported
* Some advanced DMA features not implemented
* RP2350 Hazard3 RISC-V core not emulated

---

Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.
