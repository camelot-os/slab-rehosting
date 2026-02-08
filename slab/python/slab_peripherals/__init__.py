"""
Slab Peripherals - SVD-based Peripheral Models and Auto-Generation

This package provides peripheral modeling for microcontroller emulation,
including SVD parsing, I/O pattern detection, and LLM-assisted peripheral
generation.

Dual-licensed for maximum compatibility:
- SPDX-License-Identifier: Apache-2.0 OR Apache-2.0

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab

This file is distributed under a dual license:
  - GPL-3.0-or-later (for GPL-compatible projects)
  - Apache-2.0 (for Apache-compatible projects like Wookey)
You may choose either license.
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"
__license__ = "GPL-3.0-or-later OR Apache-2.0"

# Lazy imports
def __getattr__(name):
    """Lazy import mechanism for optional components."""
    _exports = {
        # SVD Composer (new!)
        "SVDComposer": (".svd_composer", "SVDComposer"),
        "SVDParser": (".svd_composer", "SVDParser"),
        "SVDDevice": (".svd_composer", "SVDDevice"),
        "SVDPeripheral": (".svd_composer", "SVDPeripheral"),
        "SVDRegister": (".svd_composer", "SVDRegister"),
        "SVDField": (".svd_composer", "SVDField"),
        "SVDInterrupt": (".svd_composer", "SVDInterrupt"),
        "MMIOLogParser": (".svd_composer", "MMIOLogParser"),
        "InteractiveBrowser": (".svd_composer", "InteractiveBrowser"),
        # Peripheral auto-generation
        "PeripheralGenerator": (".auto_generator", "PeripheralGenerator"),
        "IOPattern": (".auto_generator", "IOPattern"),
        "PeripheralTemplate": (".auto_generator", "PeripheralTemplate"),
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
    "__license__",
    "SVDParser",
    "SVDDevice",
    "SVDPeripheral",
    "SVDRegister",
    "SVDField",
    "PeripheralGenerator",
    "IOPattern",
    "PeripheralTemplate",
    "LLMPeripheralHelper",
]
