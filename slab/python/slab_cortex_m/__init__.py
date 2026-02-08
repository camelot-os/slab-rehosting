#!/usr/bin/env python3
"""
Slab Cortex-M Package - ARM Cortex-M Emulation Core

This package provides the core emulation infrastructure for ARM Cortex-M
microcontrollers, including SVD parsing, peripheral modeling, and hardware
abstraction. Peripherals can be exported via TCP or shared memory for
external analysis tools.

Part of the Slab (Security Lab) project.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"

# Lazy imports to avoid circular dependencies and missing modules
def __getattr__(name):
    """Lazy import mechanism for optional components."""
    _exports = {
        # SVD Parser
        "SVDParser": (".svd_parser", "SVDParser"),
        "SVDPeripheral": (".svd_parser", "SVDPeripheral"),
        "SVDRegister": (".svd_parser", "SVDRegister"),
        "SVDField": (".svd_parser", "SVDField"),
        # Async core
        "AsyncPeripheralServer": (".async_core", "AsyncPeripheralServer"),
        "AsyncPeripheral": (".async_core", "AsyncPeripheral"),
        "EventBus": (".async_core", "EventBus"),
        # MCU Server
        "MCUemuServer": (".mcuemu_server", "MCUemuServer"),
        # Peripherals from mcuemu_server
        "GPIO": (".mcuemu_server", "GPIO"),
        "USART": (".mcuemu_server", "USART"),
        "SPI": (".mcuemu_server", "SPI"),
        "Timer": (".mcuemu_server", "Timer"),
        "RCC": (".mcuemu_server", "RCC"),
        "Flash": (".mcuemu_server", "Flash"),
        # Virtual components
        "VirtualIC": (".virtual_components", "VirtualIC"),
        "I2CDevice": (".virtual_components", "I2CDevice"),
        "SPIDevice": (".virtual_components", "SPIDevice"),
        "EEPROM_24Cxx": (".virtual_components", "EEPROM_24Cxx"),
        "W25QxxFlash": (".virtual_components", "W25QxxFlash"),
        "ComponentSDK": (".virtual_components", "ComponentSDK"),
        # TCP/SHM bridges
        "TCPPeripheralBridge": (".tcp_peripheral", "TCPPeripheralBridge"),
        "SHMPeripheralBridge": (".shm_peripheral", "SHMPeripheralBridge"),
    }

    if name in _exports:
        module_name, attr_name = _exports[name]
        import importlib
        module = importlib.import_module(module_name, __package__)
        return getattr(module, attr_name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "__version__",
    "__author__",
    "__project__",
    # SVD parsing
    "SVDParser",
    "SVDPeripheral",
    "SVDRegister",
    "SVDField",
    # Async infrastructure
    "AsyncPeripheralServer",
    "AsyncPeripheral",
    "EventBus",
    # Server
    "MCUemuServer",
    # Peripherals
    "GPIO",
    "USART",
    "SPI",
    "Timer",
    "RCC",
    "Flash",
    # Virtual components
    "VirtualIC",
    "I2CDevice",
    "SPIDevice",
    "EEPROM_24Cxx",
    "W25QxxFlash",
    "ComponentSDK",
    # Bridges
    "TCPPeripheralBridge",
    "SHMPeripheralBridge",
]
