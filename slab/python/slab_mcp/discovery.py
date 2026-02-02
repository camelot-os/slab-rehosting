#!/usr/bin/env python3
"""
Slab Package Discovery

Automatically discovers installed Slab packages and their capabilities.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 TwistedWires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import importlib
import importlib.util
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum, auto
import logging

logger = logging.getLogger(__name__)


class SlabCapability(Enum):
    """Slab package capabilities."""
    # Core capabilities
    CORTEX_M_EMULATION = auto()
    CORTEX_A_EMULATION = auto()
    TCP_PERIPHERAL = auto()
    SHM_PERIPHERAL = auto()

    # Timing
    TIMING_MODEL_M = auto()
    TIMING_MODEL_A = auto()
    PIPELINE_SIMULATION = auto()
    CACHE_TIMING = auto()
    MEMORY_TIMING = auto()

    # Side-channels
    POWER_MODEL = auto()
    CPA_ATTACK = auto()
    TEMPLATE_ATTACK = auto()
    ML_ATTACK = auto()
    CACHE_SIDECHANNEL = auto()
    SPECTRE_ATTACK = auto()
    BRANCH_SIDECHANNEL = auto()

    # Glitching
    VOLTAGE_GLITCH = auto()
    CLOCK_GLITCH = auto()
    EMFI_GLITCH = auto()
    INSTRUCTION_SKIP = auto()
    TRUSTZONE_BYPASS = auto()
    SPECULATION_FAULT = auto()


@dataclass
class PackageInfo:
    """Information about a discovered package."""
    name: str
    version: str
    module: Any
    capabilities: List[SlabCapability] = field(default_factory=list)
    submodules: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SlabPackageDiscovery:
    """
    Discovers and loads Slab packages.

    Usage:
        discovery = SlabPackageDiscovery()
        discovery.discover_all()
        caps = discovery.get_capabilities()
    """

    # Discovered packages
    packages: Dict[str, PackageInfo] = field(default_factory=dict)

    # Known package names and their capability mappings
    _package_capabilities: Dict[str, List[SlabCapability]] = field(
        default_factory=lambda: {
            "slab_cortex_m": [
                SlabCapability.CORTEX_M_EMULATION,
                SlabCapability.TCP_PERIPHERAL,
                SlabCapability.SHM_PERIPHERAL,
            ],
        }
    )

    def discover_all(self) -> Dict[str, PackageInfo]:
        """Discover all available Slab packages."""
        known_packages = [
            "slab_cortex_m",
        ]

        for pkg_name in known_packages:
            self._try_load_package(pkg_name)

        return self.packages

    def _try_load_package(self, pkg_name: str) -> bool:
        """Try to load a package and register its capabilities."""
        try:
            module = importlib.import_module(pkg_name)
            version = getattr(module, "__version__", "unknown")

            pkg_info = PackageInfo(
                name=pkg_name,
                version=version,
                module=module,
                capabilities=self._package_capabilities.get(pkg_name, []),
            )

            # Discover submodules
            self._discover_submodules(pkg_name, pkg_info)

            self.packages[pkg_name] = pkg_info
            logger.info(f"Discovered package: {pkg_name} v{version}")
            return True

        except ImportError as e:
            logger.debug(f"Package {pkg_name} not available: {e}")
            return False

    def _discover_submodules(self, pkg_name: str, pkg_info: PackageInfo):
        """Discover submodules within a package."""
        submodule_patterns = {}

        if pkg_name in submodule_patterns:
            for submod in submodule_patterns[pkg_name]:
                try:
                    full_name = f"{pkg_name}.{submod}"
                    submodule = importlib.import_module(full_name)
                    pkg_info.submodules[submod] = submodule
                    logger.debug(f"  Discovered submodule: {full_name}")
                except ImportError:
                    pass

    def get_capabilities(self) -> List[SlabCapability]:
        """Get all available capabilities from discovered packages."""
        caps = []
        for pkg_info in self.packages.values():
            caps.extend(pkg_info.capabilities)
        return list(set(caps))

    def has_capability(self, cap: SlabCapability) -> bool:
        """Check if a capability is available."""
        return cap in self.get_capabilities()

    def get_package_for_capability(self, cap: SlabCapability) -> Optional[PackageInfo]:
        """Get the package that provides a capability."""
        for pkg_info in self.packages.values():
            if cap in pkg_info.capabilities:
                return pkg_info
        return None

    def get_module(self, pkg_name: str) -> Optional[Any]:
        """Get a loaded module by name."""
        if pkg_name in self.packages:
            return self.packages[pkg_name].module
        return None

    def get_submodule(self, pkg_name: str, submod_name: str) -> Optional[Any]:
        """Get a submodule from a package."""
        if pkg_name in self.packages:
            return self.packages[pkg_name].submodules.get(submod_name)
        return None


# Global discovery instance
_discovery: Optional[SlabPackageDiscovery] = None


def discover_packages() -> SlabPackageDiscovery:
    """Discover all available Slab packages (cached)."""
    global _discovery
    if _discovery is None:
        _discovery = SlabPackageDiscovery()
        _discovery.discover_all()
    return _discovery


def get_available_capabilities() -> List[SlabCapability]:
    """Get list of available capabilities."""
    return discover_packages().get_capabilities()


def load_peripheral_bridge(mode: str = "tcp"):
    """Load peripheral bridge for specified mode."""
    discovery = discover_packages()

    pkg = discovery.get_module("slab_cortex_m")
    if pkg is None:
        return None

    if mode == "tcp":
        return getattr(pkg, "TcpPeripheralBridge", None)
    elif mode == "shm":
        return getattr(pkg, "ShmPeripheralBridge", None)

    return None
