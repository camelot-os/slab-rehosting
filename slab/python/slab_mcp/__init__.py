#!/usr/bin/env python3
"""
Slab MCP Package - Model Context Protocol Server with Subpackage Discovery

This package provides an MCP server that automatically discovers and integrates
with other Slab packages (timing, sidechannels, glitch, cortex_m, cortex_a).

The MCP server exposes discovered capabilities to AI models for intelligent
firmware analysis, debugging, and security testing.

Part of the Slab (Security Lab) project.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"
__author__ = "Mathieu Renard"
__project__ = "Slab"

# Lazy imports to avoid circular dependencies and missing modules
def __getattr__(name):
    """Lazy import mechanism for optional components."""
    _exports = {
        # Discovery
        "SlabPackageDiscovery": (".discovery", "SlabPackageDiscovery"),
        "SlabCapability": (".discovery", "SlabCapability"),
        "PackageInfo": (".discovery", "PackageInfo"),
        "discover_packages": (".discovery", "discover_packages"),
        "get_available_capabilities": (".discovery", "get_available_capabilities"),
        "load_timing_model": (".discovery", "load_timing_model"),
        "load_power_model": (".discovery", "load_power_model"),
        "load_glitch_model": (".discovery", "load_glitch_model"),
        "load_peripheral_bridge": (".discovery", "load_peripheral_bridge"),
        # Server
        "SlabMCPServer": (".server", "SlabMCPServer"),
        "ServerInfo": (".server", "ServerInfo"),
        "MCPErrorCode": (".server", "MCPErrorCode"),
        "create_mcp_server": (".server", "create_mcp_server"),
        # Tools
        "MCPToolRegistry": (".tools", "MCPToolRegistry"),
        "MCPTool": (".tools", "MCPTool"),
        "MCPToolParameter": (".tools", "MCPToolParameter"),
        "get_tool_registry": (".tools", "get_tool_registry"),
        "register_tool": (".tools", "register_tool"),
    }

    if name in _exports:
        module_name, attr_name = _exports[name]
        import importlib
        module = importlib.import_module(module_name, __package__)
        return getattr(module, attr_name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__project__",
    # Discovery
    "SlabPackageDiscovery",
    "SlabCapability",
    "PackageInfo",
    "discover_packages",
    "get_available_capabilities",
    "load_timing_model",
    "load_power_model",
    "load_glitch_model",
    "load_peripheral_bridge",
    # Server
    "SlabMCPServer",
    "ServerInfo",
    "MCPErrorCode",
    "create_mcp_server",
    # Tools
    "MCPToolRegistry",
    "MCPTool",
    "MCPToolParameter",
    "get_tool_registry",
    "register_tool",
]
