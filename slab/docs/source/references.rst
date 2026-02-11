.. _references:

==========
References
==========

This page lists the technical references and specifications used in SLAB.

ARM Architecture
================

.. [ARM-CM0] ARM Cortex-M0 Technical Reference Manual (DDI0432)
   https://developer.arm.com/documentation/ddi0432/

.. [ARM-CM4] ARM Cortex-M4 Technical Reference Manual (DDI0439)
   https://developer.arm.com/documentation/ddi0439/

.. [ARM-CM33] ARM Cortex-M33 Technical Reference Manual (DDI0553)
   https://developer.arm.com/documentation/ddi0553/

.. [ARM-TZ] ARMv8-M Security Extensions (TrustZone)
   https://developer.arm.com/documentation/100690/

.. [ARM-CMSIS] CMSIS (Cortex Microcontroller Software Interface Standard)
   https://arm-software.github.io/CMSIS_5/

STMicroelectronics
==================

.. [RM0090] STM32F405/407/415/417 Reference Manual
   https://www.st.com/resource/en/reference_manual/rm0090.pdf

.. [RM0468] STM32H563/573 Reference Manual
   https://www.st.com/resource/en/reference_manual/rm0468.pdf

.. [RM0481] STM32H5 TrustZone Reference Manual
   https://www.st.com/resource/en/reference_manual/rm0481.pdf

.. [PM0214] STM32 Cortex-M4 Programming Manual
   https://www.st.com/resource/en/programming_manual/pm0214.pdf

Nordic Semiconductor
====================

.. [NRF52840-PS] nRF52840 Product Specification
   https://infocenter.nordicsemi.com/pdf/nRF52840_PS_v1.7.pdf

.. [NRF5340-PS] nRF5340 Product Specification
   https://infocenter.nordicsemi.com/pdf/nRF5340_PS_v1.3.pdf

NXP Semiconductors
==================

.. [LPC55S69-UM] LPC55S6x User Manual
   https://www.nxp.com/docs/en/user-guide/UM11126.pdf

.. [IMXRT1060-RM] i.MX RT1060 Reference Manual
   https://www.nxp.com/docs/en/reference-manual/IMXRT1060RM.pdf

Raspberry Pi
============

.. [RP2040-DS] RP2040 Datasheet
   https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf

.. [RP2350-DS] RP2350 Datasheet
   https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf

USB Specifications
==================

.. [USB2.0] Universal Serial Bus Specification, Revision 2.0
   https://www.usb.org/document-library/usb-20-specification

.. [USB-CDC] USB Communications Device Class Specification
   https://www.usb.org/document-library/class-definitions-communication-devices-12

.. [USBIP] USB/IP Protocol
   https://usbip.sourceforge.net/

.. [DWC2] DesignWare Cores USB 2.0 Hi-Speed OTG Controller Databook
   (Synopsys proprietary, NDA required)

CMSIS-SVD
=========

.. [CMSIS-SVD] CMSIS System View Description Format
   https://arm-software.github.io/CMSIS_5/SVD/html/index.html

   SVD files used in SLAB are sourced from:
   https://github.com/posborne/cmsis-svd

QEMU
====

.. [QEMU] QEMU Machine Emulator and Virtualizer
   https://www.qemu.org/

.. [QEMU-ARM] QEMU ARM System Emulator
   https://www.qemu.org/docs/master/system/arm/virt.html

Python Libraries
================

.. [PYGAME] Pygame - Python game development library
   https://www.pygame.org/

.. [CRYPTOGRAPHY] Cryptography library for Python
   https://cryptography.io/

.. [ASYNCIO] Python asyncio library
   https://docs.python.org/3/library/asyncio.html

Waveform Formats
================

.. [VCD] IEEE 1364-2001 Value Change Dump (VCD) Format
   Standard format for recording signal value changes.

.. [SIGROK] Sigrok Logic Analyzer Software
   https://sigrok.org/

   Session file format (.sr) is a ZIP containing metadata and logic data.

Academic References
===================

.. [AVATAR] Zaddach et al., "Avatar: A Framework to Support Dynamic
   Security Analysis of Embedded Systems' Firmwares"
   NDSS 2014

.. [P2IM] Feng et al., "P2IM: Scalable and Hardware-independent Firmware
   Testing via Automatic Peripheral Interface Modeling"
   USENIX Security 2020

.. [FUZZWARE] Scharnowski et al., "Fuzzware: Using Precise MMIO Modeling
   for Effective Firmware Fuzzing"
   USENIX Security 2022

.. [HAL-FUZZ] Clements et al., "HALucinator: Firmware Re-hosting Through
   Abstraction Layer Emulation"
   USENIX Security 2020

Copyright
=========

SLAB is developed by Twisted Wires Security Lab.

Copyright (C) 2026 Twisted Wires Security Lab. All Rights Reserved.

The QEMU machine code (``qemu/hw/``) is licensed under GPL-3.0-or-later.

The Python packages and tests are licensed under Apache-2.0.
