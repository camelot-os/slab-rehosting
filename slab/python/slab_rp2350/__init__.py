"""
Slab RP2350 - Raspberry Pi Pico 2 Support

DEPRECATED: This package is now consolidated into slab_rp2040.
All RP2350 functionality is available from slab_rp2040.

For new code, use:
    from slab_rp2040 import RP2350Timing, TrustZoneModel, ...

This module provides backward compatibility by re-exporting from slab_rp2040.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2026 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import warnings

warnings.warn(
    "slab_rp2350 is deprecated. Use slab_rp2040 instead which includes all RP2350 support.",
    DeprecationWarning,
    stacklevel=2
)

__version__ = "0.1.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"

# Re-export from slab_rp2040 for backward compatibility
from slab_rp2040 import (
    # Timing
    RP2350Timing,
    CortexM33Timing,
    Hazard3Timing,
    RP2350MemoryTiming,
    # Security
    TrustZoneModel,
    SAURegion,
    SAURegionType,
    SecureBootChain,
    OTPModel,
    BootStage,
    SecurityState,
)

__all__ = [
    "__version__",
    "__author__",
    # Timing
    "RP2350Timing",
    "CortexM33Timing",
    "Hazard3Timing",
    "RP2350MemoryTiming",
    # Security
    "TrustZoneModel",
    "SAURegion",
    "SAURegionType",
    "SecureBootChain",
    "OTPModel",
    "BootStage",
    "SecurityState",
]
