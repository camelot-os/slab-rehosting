#!/usr/bin/env python3
"""
Slab MCP Tools Registry

Dynamic tool registration based on discovered capabilities.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Coroutine
from enum import Enum
import logging
import asyncio
import inspect

from .discovery import (
    SlabCapability,
    discover_packages,
    load_peripheral_bridge,
)

logger = logging.getLogger(__name__)


@dataclass
class MCPToolParameter:
    """MCP tool parameter definition."""
    name: str
    type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    default: Any = None


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    parameters: List[MCPToolParameter] = field(default_factory=list)
    handler: Optional[Callable] = None
    required_capability: Optional[SlabCapability] = None

    def to_mcp_schema(self) -> Dict:
        """Convert to MCP tool schema."""
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.default is not None:
                properties[param.name]["default"] = param.default
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class MCPToolRegistry:
    """
    Registry for MCP tools with automatic capability-based registration.

    Tools are only registered if their required capabilities are available.
    """

    def __init__(self):
        self.tools: Dict[str, MCPTool] = {}
        self._discovery = None

    def initialize(self):
        """Initialize registry with discovered packages."""
        self._discovery = discover_packages()
        self._register_builtin_tools()

    def _register_builtin_tools(self):
        """Register built-in tools based on available capabilities."""

        # Timing tools (Cortex-M)
        if self._discovery.has_capability(SlabCapability.TIMING_MODEL_M):
            self._register_timing_tools_m()

        # Timing tools (Cortex-A)
        if self._discovery.has_capability(SlabCapability.TIMING_MODEL_A):
            self._register_timing_tools_a()

        # Side-channel tools
        if self._discovery.has_capability(SlabCapability.CPA_ATTACK):
            self._register_sidechannel_tools()

        # Glitch tools
        if self._discovery.has_capability(SlabCapability.VOLTAGE_GLITCH):
            self._register_glitch_tools()

        # Peripheral bridge tools
        if self._discovery.has_capability(SlabCapability.TCP_PERIPHERAL):
            self._register_peripheral_tools()

    def _register_timing_tools_m(self):
        """Register Cortex-M timing tools."""
        self.register(MCPTool(
            name="timing_get_instruction_cycles_m",
            description="Get cycle count for a Cortex-M instruction",
            parameters=[
                MCPToolParameter("instruction", "string", "ARM instruction mnemonic"),
                MCPToolParameter("cpu_model", "string", "CPU model (cortex-m0, m3, m4, m7)", default="cortex-m4"),
            ],
            handler=self._handle_timing_instruction_m,
            required_capability=SlabCapability.TIMING_MODEL_M,
        ))

        self.register(MCPTool(
            name="timing_analyze_function_m",
            description="Analyze timing of a function (list of instructions) for Cortex-M",
            parameters=[
                MCPToolParameter("instructions", "array", "List of instruction mnemonics"),
                MCPToolParameter("cpu_model", "string", "CPU model", default="cortex-m4"),
            ],
            handler=self._handle_timing_function_m,
            required_capability=SlabCapability.TIMING_MODEL_M,
        ))

    def _register_timing_tools_a(self):
        """Register Cortex-A timing tools."""
        self.register(MCPTool(
            name="timing_get_instruction_cycles_a",
            description="Get cycle count for a Cortex-A instruction",
            parameters=[
                MCPToolParameter("instruction", "string", "ARM instruction mnemonic"),
                MCPToolParameter("cpu_model", "string", "CPU model (cortex-a53, a72, a76)", default="cortex-a53"),
            ],
            handler=self._handle_timing_instruction_a,
            required_capability=SlabCapability.TIMING_MODEL_A,
        ))

        self.register(MCPTool(
            name="timing_analyze_cache_a",
            description="Analyze cache behavior for Cortex-A",
            parameters=[
                MCPToolParameter("access_pattern", "array", "List of memory addresses"),
                MCPToolParameter("cpu_model", "string", "CPU model", default="cortex-a53"),
            ],
            handler=self._handle_cache_analysis_a,
            required_capability=SlabCapability.CACHE_TIMING,
        ))

    def _register_sidechannel_tools(self):
        """Register side-channel analysis tools."""
        self.register(MCPTool(
            name="cpa_analyze_traces",
            description="Perform Correlation Power Analysis on traces",
            parameters=[
                MCPToolParameter("traces", "array", "Power trace data"),
                MCPToolParameter("plaintexts", "array", "Plaintext values"),
                MCPToolParameter("key_byte", "number", "Target key byte index"),
                MCPToolParameter("leakage_model", "string", "Leakage model (hw, hd)", default="hw"),
            ],
            handler=self._handle_cpa_analyze,
            required_capability=SlabCapability.CPA_ATTACK,
        ))

        self.register(MCPTool(
            name="power_model_predict",
            description="Predict power consumption for an operation",
            parameters=[
                MCPToolParameter("operation", "string", "Operation type (sbox, xor, load, store)"),
                MCPToolParameter("operand", "number", "Operand value"),
                MCPToolParameter("model", "string", "Power model (hw, hd)", default="hw"),
            ],
            handler=self._handle_power_predict,
            required_capability=SlabCapability.POWER_MODEL,
        ))

    def _register_glitch_tools(self):
        """Register fault injection tools."""
        self.register(MCPTool(
            name="glitch_configure",
            description="Configure voltage glitch parameters",
            parameters=[
                MCPToolParameter("offset_ns", "number", "Glitch offset in nanoseconds"),
                MCPToolParameter("width_ns", "number", "Glitch width in nanoseconds"),
                MCPToolParameter("voltage", "number", "Glitch voltage level", default=0.0),
            ],
            handler=self._handle_glitch_configure,
            required_capability=SlabCapability.VOLTAGE_GLITCH,
        ))

        self.register(MCPTool(
            name="glitch_inject",
            description="Inject a fault and get result",
            parameters=[
                MCPToolParameter("target_pc", "number", "Target program counter address"),
            ],
            handler=self._handle_glitch_inject,
            required_capability=SlabCapability.VOLTAGE_GLITCH,
        ))

    def _register_peripheral_tools(self):
        """Register peripheral bridge tools."""
        self.register(MCPTool(
            name="peripheral_read",
            description="Read from a peripheral register",
            parameters=[
                MCPToolParameter("address", "number", "Peripheral address"),
                MCPToolParameter("size", "number", "Access size (1, 2, or 4)", default=4),
            ],
            handler=self._handle_peripheral_read,
            required_capability=SlabCapability.TCP_PERIPHERAL,
        ))

        self.register(MCPTool(
            name="peripheral_write",
            description="Write to a peripheral register",
            parameters=[
                MCPToolParameter("address", "number", "Peripheral address"),
                MCPToolParameter("value", "number", "Value to write"),
                MCPToolParameter("size", "number", "Access size (1, 2, or 4)", default=4),
            ],
            handler=self._handle_peripheral_write,
            required_capability=SlabCapability.TCP_PERIPHERAL,
        ))

    def register(self, tool: MCPTool):
        """Register a tool."""
        if tool.required_capability:
            if not self._discovery.has_capability(tool.required_capability):
                logger.debug(f"Skipping tool {tool.name}: missing capability {tool.required_capability}")
                return

        self.tools[tool.name] = tool
        logger.info(f"Registered MCP tool: {tool.name}")

    def get_tools(self) -> List[MCPTool]:
        """Get all registered tools."""
        return list(self.tools.values())

    def get_tool(self, name: str) -> Optional[MCPTool]:
        """Get a tool by name."""
        return self.tools.get(name)

    def get_schemas(self) -> List[Dict]:
        """Get MCP schemas for all tools."""
        return [tool.to_mcp_schema() for tool in self.tools.values()]

    async def invoke(self, name: str, arguments: Dict) -> Any:
        """Invoke a tool by name."""
        tool = self.get_tool(name)
        if not tool:
            raise ValueError(f"Unknown tool: {name}")

        if tool.handler is None:
            raise ValueError(f"Tool {name} has no handler")

        if asyncio.iscoroutinefunction(tool.handler):
            return await tool.handler(arguments)
        else:
            return tool.handler(arguments)

    # Tool handlers
    async def _handle_timing_instruction_m(self, args: Dict) -> Dict:
        """Handle timing_get_instruction_cycles_m."""
        try:
            from slab_timing import CortexM4Timing as TimingModel
        except ImportError:
            return {"error": "Timing model not available"}

        # Implementation would query the timing model
        return {
            "instruction": args["instruction"],
            "cpu_model": args.get("cpu_model", "cortex-m4"),
            "cycles": 1,  # Placeholder
        }

    async def _handle_timing_function_m(self, args: Dict) -> Dict:
        """Handle timing_analyze_function_m."""
        return {"total_cycles": len(args.get("instructions", [])), "analysis": "placeholder"}

    async def _handle_timing_instruction_a(self, args: Dict) -> Dict:
        """Handle timing_get_instruction_cycles_a."""
        return {"cycles": 1, "latency": 1, "throughput": 1}

    async def _handle_cache_analysis_a(self, args: Dict) -> Dict:
        """Handle timing_analyze_cache_a."""
        return {"hits": 0, "misses": 0, "analysis": "placeholder"}

    async def _handle_cpa_analyze(self, args: Dict) -> Dict:
        """Handle cpa_analyze_traces."""
        return {"key_guess": 0, "correlation": 0.0, "confidence": 0.0}

    async def _handle_power_predict(self, args: Dict) -> Dict:
        """Handle power_model_predict."""
        operand = args.get("operand", 0)
        hw = bin(operand).count("1")
        return {"predicted_power": hw, "hamming_weight": hw}

    async def _handle_glitch_configure(self, args: Dict) -> Dict:
        """Handle glitch_configure."""
        return {"configured": True, "parameters": args}

    async def _handle_glitch_inject(self, args: Dict) -> Dict:
        """Handle glitch_inject."""
        return {"result": "no_effect", "target_pc": args.get("target_pc", 0)}

    async def _handle_peripheral_read(self, args: Dict) -> Dict:
        """Handle peripheral_read."""
        return {"address": args["address"], "value": 0}

    async def _handle_peripheral_write(self, args: Dict) -> Dict:
        """Handle peripheral_write."""
        return {"address": args["address"], "value": args["value"], "success": True}


# Global registry
_registry: Optional[MCPToolRegistry] = None


def get_tool_registry() -> MCPToolRegistry:
    """Get the global tool registry."""
    global _registry
    if _registry is None:
        _registry = MCPToolRegistry()
        _registry.initialize()
    return _registry


def register_tool(tool: MCPTool):
    """Register a tool in the global registry."""
    get_tool_registry().register(tool)
