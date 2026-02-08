"""
MCUemu MCP Server - Model Context Protocol server for AI-assisted MCU emulation.

This module provides an MCP server that exposes MCUemu capabilities to AI models,
enabling intelligent firmware analysis, debugging, and security testing.

Protocol: https://modelcontextprotocol.io/

Features:
- Memory/register read/write
- Breakpoint management
- Peripheral access
- Fault injection configuration and execution
- Timing model queries
- Side-channel analysis (CPA)
- POST display access

References:
- ARM DDI 0439: Cortex-M4 Technical Reference Manual
- ARM DDI 0489: Cortex-M7 Technical Reference Manual
- ChipWhisperer: https://github.com/newaetech/chipwhisperer
"""
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 Twisted Wires - Mathieu Renard

import asyncio
import json
import logging
import struct
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum, IntEnum
from pathlib import Path
from typing import (
    Any, Callable, Coroutine, Dict, List, Optional,
    Set, Tuple, Type, Union
)
import uuid

# Try to import MCUemu modules
try:
    from timing_model import CortexMTimingModel, CortexMProfile
    HAS_TIMING = True
except ImportError:
    HAS_TIMING = False

try:
    from fault_injection import (
        FaultInjectionEngine, FaultConfig, FaultType,
        TriggerType, FaultState, CPUInterface
    )
    HAS_FAULT = True
except ImportError:
    HAS_FAULT = False

try:
    from chipwhisperer_compat import (
        Scope, Target, HammingWeightPowerModel,
        HammingDistancePowerModel, CPA
    )
    HAS_CW = True
except ImportError:
    HAS_CW = False

try:
    from post_display import POSTDisplay
    HAS_POST = True
except ImportError:
    HAS_POST = False

logger = logging.getLogger(__name__)


# =============================================================================
# MCP Protocol Types
# =============================================================================

class MCPMessageType(str, Enum):
    """MCP message types per protocol spec."""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


class MCPErrorCode(IntEnum):
    """Standard JSON-RPC and MCP error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    # MCP-specific errors
    RESOURCE_NOT_FOUND = -32001
    TOOL_EXECUTION_ERROR = -32002
    PERMISSION_DENIED = -32003
    EMULATOR_ERROR = -32004


@dataclass
class MCPError:
    """MCP error object."""
    code: int
    message: str
    data: Optional[Any] = None


@dataclass
class MCPRequest:
    """MCP request message."""
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    method: str = ""
    params: Optional[Dict[str, Any]] = None


@dataclass
class MCPResponse:
    """MCP response message."""
    jsonrpc: str = "2.0"
    id: Optional[Union[str, int]] = None
    result: Optional[Any] = None
    error: Optional[MCPError] = None


@dataclass
class MCPNotification:
    """MCP notification message (no response expected)."""
    jsonrpc: str = "2.0"
    method: str = ""
    params: Optional[Dict[str, Any]] = None


# =============================================================================
# MCP Resources
# =============================================================================

@dataclass
class MCPResource:
    """MCP resource definition."""
    uri: str
    name: str
    description: str
    mimeType: str = "application/json"


@dataclass
class MCPResourceContent:
    """MCP resource content."""
    uri: str
    mimeType: str
    text: Optional[str] = None
    blob: Optional[bytes] = None


# =============================================================================
# MCP Tools
# =============================================================================

@dataclass
class MCPToolParameter:
    """Parameter definition for an MCP tool."""
    name: str
    type: str
    description: str
    required: bool = True
    enum: Optional[List[str]] = None
    default: Optional[Any] = None


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    inputSchema: Dict[str, Any]

    @classmethod
    def from_params(cls, name: str, description: str,
                    params: List[MCPToolParameter]) -> "MCPTool":
        """Create tool from parameter list."""
        properties = {}
        required = []

        for p in params:
            prop = {"type": p.type, "description": p.description}
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)

        return cls(
            name=name,
            description=description,
            inputSchema={
                "type": "object",
                "properties": properties,
                "required": required
            }
        )


@dataclass
class MCPToolResult:
    """Result of an MCP tool call."""
    content: List[Dict[str, Any]]
    isError: bool = False


# =============================================================================
# MCP Prompts
# =============================================================================

@dataclass
class MCPPromptArgument:
    """Argument for an MCP prompt."""
    name: str
    description: str
    required: bool = True


@dataclass
class MCPPrompt:
    """MCP prompt definition."""
    name: str
    description: str
    arguments: List[MCPPromptArgument] = field(default_factory=list)


@dataclass
class MCPPromptMessage:
    """Message in a prompt response."""
    role: str  # "user" or "assistant"
    content: Dict[str, Any]


# =============================================================================
# Emulator Interface
# =============================================================================

class EmulatorInterface(ABC):
    """Abstract interface to MCUemu emulator."""

    @abstractmethod
    async def read_memory(self, address: int, size: int) -> bytes:
        """Read memory from emulator."""
        pass

    @abstractmethod
    async def write_memory(self, address: int, data: bytes) -> bool:
        """Write memory to emulator."""
        pass

    @abstractmethod
    async def read_register(self, name: str) -> int:
        """Read CPU register."""
        pass

    @abstractmethod
    async def write_register(self, name: str, value: int) -> bool:
        """Write CPU register."""
        pass

    @abstractmethod
    async def get_registers(self) -> Dict[str, int]:
        """Get all CPU registers."""
        pass

    @abstractmethod
    async def step(self, count: int = 1) -> Dict[str, Any]:
        """Single-step execution."""
        pass

    @abstractmethod
    async def continue_execution(self) -> Dict[str, Any]:
        """Continue execution until breakpoint or halt."""
        pass

    @abstractmethod
    async def halt(self) -> bool:
        """Halt execution."""
        pass

    @abstractmethod
    async def set_breakpoint(self, address: int) -> int:
        """Set breakpoint, return breakpoint ID."""
        pass

    @abstractmethod
    async def remove_breakpoint(self, bp_id: int) -> bool:
        """Remove breakpoint."""
        pass

    @abstractmethod
    async def get_breakpoints(self) -> List[Dict[str, Any]]:
        """Get all breakpoints."""
        pass

    @abstractmethod
    async def load_firmware(self, path: str, address: int = 0x08000000) -> bool:
        """Load firmware binary."""
        pass

    @abstractmethod
    async def reset(self) -> bool:
        """Reset emulator."""
        pass

    @abstractmethod
    async def get_state(self) -> Dict[str, Any]:
        """Get emulator state."""
        pass

    @abstractmethod
    async def get_peripherals(self) -> List[Dict[str, Any]]:
        """List configured peripherals."""
        pass

    @abstractmethod
    async def read_peripheral(self, name: str, offset: int, size: int) -> int:
        """Read peripheral register."""
        pass

    @abstractmethod
    async def write_peripheral(self, name: str, offset: int, value: int, size: int) -> bool:
        """Write peripheral register."""
        pass


class MockEmulatorInterface(EmulatorInterface):
    """Mock emulator interface for testing."""

    def __init__(self):
        self.memory: Dict[int, int] = {}
        self.registers = {
            "r0": 0, "r1": 0, "r2": 0, "r3": 0,
            "r4": 0, "r5": 0, "r6": 0, "r7": 0,
            "r8": 0, "r9": 0, "r10": 0, "r11": 0,
            "r12": 0, "sp": 0x20001000, "lr": 0, "pc": 0x08000000,
            "xpsr": 0x01000000
        }
        self.breakpoints: Dict[int, int] = {}
        self.bp_counter = 0
        self.halted = True
        self.peripherals = [
            {"name": "GPIOA", "base": 0x40020000, "size": 0x400},
            {"name": "USART1", "base": 0x40011000, "size": 0x400},
            {"name": "SPI1", "base": 0x40013000, "size": 0x400},
        ]

    async def read_memory(self, address: int, size: int) -> bytes:
        data = bytearray(size)
        for i in range(size):
            data[i] = self.memory.get(address + i, 0)
        return bytes(data)

    async def write_memory(self, address: int, data: bytes) -> bool:
        for i, b in enumerate(data):
            self.memory[address + i] = b
        return True

    async def read_register(self, name: str) -> int:
        return self.registers.get(name.lower(), 0)

    async def write_register(self, name: str, value: int) -> bool:
        if name.lower() in self.registers:
            self.registers[name.lower()] = value & 0xFFFFFFFF
            return True
        return False

    async def get_registers(self) -> Dict[str, int]:
        return self.registers.copy()

    async def step(self, count: int = 1) -> Dict[str, Any]:
        self.registers["pc"] += 2 * count
        return {"pc": self.registers["pc"], "steps": count}

    async def continue_execution(self) -> Dict[str, Any]:
        self.halted = False
        return {"status": "running"}

    async def halt(self) -> bool:
        self.halted = True
        return True

    async def set_breakpoint(self, address: int) -> int:
        self.bp_counter += 1
        self.breakpoints[self.bp_counter] = address
        return self.bp_counter

    async def remove_breakpoint(self, bp_id: int) -> bool:
        if bp_id in self.breakpoints:
            del self.breakpoints[bp_id]
            return True
        return False

    async def get_breakpoints(self) -> List[Dict[str, Any]]:
        return [{"id": k, "address": v} for k, v in self.breakpoints.items()]

    async def load_firmware(self, path: str, address: int = 0x08000000) -> bool:
        try:
            with open(path, "rb") as f:
                data = f.read()
            await self.write_memory(address, data)
            return True
        except Exception:
            return False

    async def reset(self) -> bool:
        self.registers["pc"] = 0x08000000
        self.registers["sp"] = 0x20001000
        self.halted = True
        return True

    async def get_state(self) -> Dict[str, Any]:
        return {
            "halted": self.halted,
            "pc": self.registers["pc"],
            "sp": self.registers["sp"],
            "breakpoints": len(self.breakpoints)
        }

    async def get_peripherals(self) -> List[Dict[str, Any]]:
        return self.peripherals

    async def read_peripheral(self, name: str, offset: int, size: int) -> int:
        for p in self.peripherals:
            if p["name"] == name:
                addr = p["base"] + offset
                data = await self.read_memory(addr, size)
                if size == 1:
                    return data[0]
                elif size == 2:
                    return struct.unpack("<H", data)[0]
                else:
                    return struct.unpack("<I", data)[0]
        return 0

    async def write_peripheral(self, name: str, offset: int, value: int, size: int) -> bool:
        for p in self.peripherals:
            if p["name"] == name:
                addr = p["base"] + offset
                if size == 1:
                    data = bytes([value & 0xFF])
                elif size == 2:
                    data = struct.pack("<H", value & 0xFFFF)
                else:
                    data = struct.pack("<I", value & 0xFFFFFFFF)
                return await self.write_memory(addr, data)
        return False


# =============================================================================
# MCP Server Core
# =============================================================================

class MCPServer:
    """
    MCP Server for MCUemu.

    Exposes emulator capabilities via the Model Context Protocol,
    enabling AI-assisted firmware analysis and debugging.
    """

    SERVER_NAME = "mcuemu-mcp"
    SERVER_VERSION = "1.0.0"
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, emulator: Optional[EmulatorInterface] = None):
        self.emulator = emulator or MockEmulatorInterface()
        self.session_id: Optional[str] = None
        self.initialized = False

        # Tool handlers
        self._tools: Dict[str, Callable[..., Coroutine[Any, Any, MCPToolResult]]] = {}
        self._register_tools()

        # Resource handlers
        self._resources: Dict[str, Callable[..., Coroutine[Any, Any, MCPResourceContent]]] = {}
        self._register_resources()

        # Prompt handlers
        self._prompts: Dict[str, Callable[..., Coroutine[Any, Any, List[MCPPromptMessage]]]] = {}
        self._register_prompts()

        # Notification handlers
        self._notification_handlers: Dict[str, Callable[..., Coroutine[Any, Any, None]]] = {}

        # Subscriptions
        self._subscriptions: Set[str] = set()

        # Event queue for notifications
        self._event_queue: asyncio.Queue = asyncio.Queue()

    # =========================================================================
    # Tool Registration
    # =========================================================================

    def _register_tools(self):
        """Register all available tools."""

        # Memory tools
        self._tools["memory_read"] = self._tool_memory_read
        self._tools["memory_write"] = self._tool_memory_write
        self._tools["memory_dump"] = self._tool_memory_dump
        self._tools["memory_search"] = self._tool_memory_search

        # Register tools
        self._tools["register_read"] = self._tool_register_read
        self._tools["register_write"] = self._tool_register_write
        self._tools["registers_dump"] = self._tool_registers_dump

        # Execution tools
        self._tools["step"] = self._tool_step
        self._tools["continue"] = self._tool_continue
        self._tools["halt"] = self._tool_halt
        self._tools["reset"] = self._tool_reset

        # Breakpoint tools
        self._tools["breakpoint_set"] = self._tool_breakpoint_set
        self._tools["breakpoint_remove"] = self._tool_breakpoint_remove
        self._tools["breakpoint_list"] = self._tool_breakpoint_list

        # Firmware tools
        self._tools["firmware_load"] = self._tool_firmware_load
        self._tools["firmware_info"] = self._tool_firmware_info

        # Peripheral tools
        self._tools["peripheral_list"] = self._tool_peripheral_list
        self._tools["peripheral_read"] = self._tool_peripheral_read
        self._tools["peripheral_write"] = self._tool_peripheral_write

        # Analysis tools
        self._tools["disassemble"] = self._tool_disassemble
        self._tools["stack_trace"] = self._tool_stack_trace
        self._tools["symbol_lookup"] = self._tool_symbol_lookup

        # Security tools
        self._tools["trustzone_status"] = self._tool_trustzone_status
        self._tools["sau_regions"] = self._tool_sau_regions

        # Fault injection tools (MCUemu-specific)
        self._tools["fault_configure"] = self._tool_fault_configure
        self._tools["fault_arm"] = self._tool_fault_arm
        self._tools["fault_disarm"] = self._tool_fault_disarm
        self._tools["fault_status"] = self._tool_fault_status
        self._tools["fault_list"] = self._tool_fault_list
        self._tools["fault_clear"] = self._tool_fault_clear

        # Timing model tools (MCUemu-specific)
        self._tools["timing_get_cycles"] = self._tool_timing_get_cycles
        self._tools["timing_set_profile"] = self._tool_timing_set_profile
        self._tools["timing_get_profile"] = self._tool_timing_get_profile
        self._tools["timing_instruction_info"] = self._tool_timing_instruction_info

        # Side-channel analysis tools (MCUemu-specific)
        self._tools["sca_configure_scope"] = self._tool_sca_configure_scope
        self._tools["sca_capture_trace"] = self._tool_sca_capture_trace
        self._tools["sca_run_cpa"] = self._tool_sca_run_cpa
        self._tools["sca_get_scope_config"] = self._tool_sca_get_scope_config

        # POST display tools (MCUemu-specific)
        self._tools["post_read"] = self._tool_post_read
        self._tools["post_history"] = self._tool_post_history
        self._tools["post_set"] = self._tool_post_set

    def _get_tools_list(self) -> List[MCPTool]:
        """Get list of all available tools with schemas."""
        return [
            # Memory tools
            MCPTool.from_params(
                "memory_read",
                "Read bytes from emulator memory at specified address",
                [
                    MCPToolParameter("address", "integer", "Memory address (hex or decimal)"),
                    MCPToolParameter("size", "integer", "Number of bytes to read", default=4),
                ]
            ),
            MCPTool.from_params(
                "memory_write",
                "Write bytes to emulator memory",
                [
                    MCPToolParameter("address", "integer", "Memory address"),
                    MCPToolParameter("data", "string", "Hex string of bytes to write"),
                ]
            ),
            MCPTool.from_params(
                "memory_dump",
                "Dump memory region as hex and ASCII",
                [
                    MCPToolParameter("address", "integer", "Start address"),
                    MCPToolParameter("size", "integer", "Number of bytes", default=256),
                ]
            ),
            MCPTool.from_params(
                "memory_search",
                "Search for pattern in memory",
                [
                    MCPToolParameter("pattern", "string", "Hex pattern to search"),
                    MCPToolParameter("start", "integer", "Start address", default=0x08000000),
                    MCPToolParameter("end", "integer", "End address", default=0x08100000),
                ]
            ),

            # Register tools
            MCPTool.from_params(
                "register_read",
                "Read CPU register value",
                [
                    MCPToolParameter("name", "string", "Register name (r0-r12, sp, lr, pc, xpsr)"),
                ]
            ),
            MCPTool.from_params(
                "register_write",
                "Write CPU register value",
                [
                    MCPToolParameter("name", "string", "Register name"),
                    MCPToolParameter("value", "integer", "Value to write"),
                ]
            ),
            MCPTool.from_params(
                "registers_dump",
                "Dump all CPU registers",
                []
            ),

            # Execution tools
            MCPTool.from_params(
                "step",
                "Single-step CPU execution",
                [
                    MCPToolParameter("count", "integer", "Number of instructions", required=False, default=1),
                ]
            ),
            MCPTool.from_params(
                "continue",
                "Continue execution until breakpoint or halt",
                []
            ),
            MCPTool.from_params(
                "halt",
                "Halt CPU execution",
                []
            ),
            MCPTool.from_params(
                "reset",
                "Reset emulator to initial state",
                []
            ),

            # Breakpoint tools
            MCPTool.from_params(
                "breakpoint_set",
                "Set breakpoint at address",
                [
                    MCPToolParameter("address", "integer", "Breakpoint address"),
                ]
            ),
            MCPTool.from_params(
                "breakpoint_remove",
                "Remove breakpoint by ID",
                [
                    MCPToolParameter("id", "integer", "Breakpoint ID"),
                ]
            ),
            MCPTool.from_params(
                "breakpoint_list",
                "List all breakpoints",
                []
            ),

            # Firmware tools
            MCPTool.from_params(
                "firmware_load",
                "Load firmware binary into emulator",
                [
                    MCPToolParameter("path", "string", "Path to firmware file"),
                    MCPToolParameter("address", "integer", "Load address", required=False, default=0x08000000),
                ]
            ),
            MCPTool.from_params(
                "firmware_info",
                "Get information about loaded firmware",
                []
            ),

            # Peripheral tools
            MCPTool.from_params(
                "peripheral_list",
                "List all configured peripherals",
                []
            ),
            MCPTool.from_params(
                "peripheral_read",
                "Read peripheral register",
                [
                    MCPToolParameter("name", "string", "Peripheral name (e.g., GPIOA, USART1)"),
                    MCPToolParameter("offset", "integer", "Register offset"),
                    MCPToolParameter("size", "integer", "Read size in bytes", required=False, default=4),
                ]
            ),
            MCPTool.from_params(
                "peripheral_write",
                "Write peripheral register",
                [
                    MCPToolParameter("name", "string", "Peripheral name"),
                    MCPToolParameter("offset", "integer", "Register offset"),
                    MCPToolParameter("value", "integer", "Value to write"),
                    MCPToolParameter("size", "integer", "Write size in bytes", required=False, default=4),
                ]
            ),

            # Analysis tools
            MCPTool.from_params(
                "disassemble",
                "Disassemble instructions at address",
                [
                    MCPToolParameter("address", "integer", "Start address"),
                    MCPToolParameter("count", "integer", "Number of instructions", required=False, default=10),
                ]
            ),
            MCPTool.from_params(
                "stack_trace",
                "Get current stack trace",
                []
            ),
            MCPTool.from_params(
                "symbol_lookup",
                "Lookup symbol by name or address",
                [
                    MCPToolParameter("query", "string", "Symbol name or address"),
                ]
            ),

            # Security tools
            MCPTool.from_params(
                "trustzone_status",
                "Get TrustZone security status",
                []
            ),
            MCPTool.from_params(
                "sau_regions",
                "List SAU (Security Attribution Unit) regions",
                []
            ),

            # Fault injection tools (MCUemu-specific)
            MCPTool.from_params(
                "fault_configure",
                "Configure a fault injection. Types: instruction_skip, reg_set_zero, reg_bit_flip, flag_set, flag_clear, memory_corruption, bus_fault",
                [
                    MCPToolParameter("fault_type", "string", "Fault type", enum=[
                        "instruction_skip", "reg_set_zero", "reg_bit_flip",
                        "flag_set", "flag_clear", "memory_corruption", "bus_fault"
                    ]),
                    MCPToolParameter("trigger", "string", "Trigger type", enum=[
                        "pc_exact", "pc_range", "cycle", "memory_read", "memory_write"
                    ]),
                    MCPToolParameter("trigger_addr", "integer", "Trigger address (for PC/memory triggers)"),
                    MCPToolParameter("trigger_cycle", "integer", "Trigger cycle (for cycle trigger)", required=False),
                    MCPToolParameter("skip_count", "integer", "Instructions to skip (for instruction_skip)", required=False, default=1),
                    MCPToolParameter("target_reg", "string", "Target register (for reg_ types)", required=False),
                    MCPToolParameter("target_addr", "integer", "Target address (for memory_corruption)", required=False),
                    MCPToolParameter("corruption_value", "integer", "Value to write (for memory_corruption)", required=False),
                ]
            ),
            MCPTool.from_params(
                "fault_arm",
                "Arm a configured fault by ID",
                [
                    MCPToolParameter("fault_id", "integer", "Fault ID to arm"),
                ]
            ),
            MCPTool.from_params(
                "fault_disarm",
                "Disarm a fault by ID",
                [
                    MCPToolParameter("fault_id", "integer", "Fault ID to disarm"),
                ]
            ),
            MCPTool.from_params(
                "fault_status",
                "Get status of a specific fault",
                [
                    MCPToolParameter("fault_id", "integer", "Fault ID to query"),
                ]
            ),
            MCPTool.from_params(
                "fault_list",
                "List all configured faults",
                []
            ),
            MCPTool.from_params(
                "fault_clear",
                "Clear all faults",
                []
            ),

            # Timing model tools (MCUemu-specific)
            MCPTool.from_params(
                "timing_get_cycles",
                "Get cycle count for an instruction",
                [
                    MCPToolParameter("instruction", "string", "Instruction mnemonic (e.g., 'ldr', 'mul', 'add')"),
                    MCPToolParameter("operand_type", "string", "Operand type", required=False, enum=[
                        "register", "immediate", "memory"
                    ]),
                ]
            ),
            MCPTool.from_params(
                "timing_set_profile",
                "Set the Cortex-M timing profile",
                [
                    MCPToolParameter("profile", "string", "Profile name", enum=[
                        "CM0", "CM0P", "CM3", "CM4", "CM4F", "CM7", "CM23", "CM33", "CM55"
                    ]),
                ]
            ),
            MCPTool.from_params(
                "timing_get_profile",
                "Get current timing profile information",
                []
            ),
            MCPTool.from_params(
                "timing_instruction_info",
                "Get detailed timing info for instruction category",
                [
                    MCPToolParameter("category", "string", "Instruction category", enum=[
                        "data_processing", "multiply", "load_store", "branch", "fpu", "dsp"
                    ]),
                ]
            ),

            # Side-channel analysis tools (MCUemu-specific)
            MCPTool.from_params(
                "sca_configure_scope",
                "Configure ChipWhisperer-compatible scope settings",
                [
                    MCPToolParameter("glitch_width", "number", "Glitch width percentage", required=False, default=10),
                    MCPToolParameter("glitch_offset", "number", "Glitch offset percentage", required=False, default=10),
                    MCPToolParameter("glitch_repeat", "integer", "Glitch repeat count", required=False, default=1),
                    MCPToolParameter("ext_offset", "integer", "External trigger offset in cycles", required=False, default=0),
                ]
            ),
            MCPTool.from_params(
                "sca_capture_trace",
                "Capture simulated power trace during execution",
                [
                    MCPToolParameter("num_samples", "integer", "Number of samples to capture", default=1000),
                    MCPToolParameter("power_model", "string", "Power model to use", required=False, enum=[
                        "hamming_weight", "hamming_distance"
                    ], default="hamming_weight"),
                ]
            ),
            MCPTool.from_params(
                "sca_run_cpa",
                "Run Correlation Power Analysis attack",
                [
                    MCPToolParameter("traces", "integer", "Number of traces to collect", default=100),
                    MCPToolParameter("target_byte", "integer", "Target key byte (0-15 for AES)", default=0),
                ]
            ),
            MCPTool.from_params(
                "sca_get_scope_config",
                "Get current scope configuration",
                []
            ),

            # POST display tools (MCUemu-specific)
            MCPTool.from_params(
                "post_read",
                "Read current POST code from display",
                []
            ),
            MCPTool.from_params(
                "post_history",
                "Get POST code history with timing",
                [
                    MCPToolParameter("count", "integer", "Number of entries to retrieve", required=False, default=10),
                ]
            ),
            MCPTool.from_params(
                "post_set",
                "Set POST code (for testing)",
                [
                    MCPToolParameter("code", "integer", "POST code value (0x00-0xFF)"),
                ]
            ),
        ]

    # =========================================================================
    # Resource Registration
    # =========================================================================

    def _register_resources(self):
        """Register resource handlers."""
        self._resources["mcuemu://state"] = self._resource_state
        self._resources["mcuemu://memory/{address}/{size}"] = self._resource_memory
        self._resources["mcuemu://registers"] = self._resource_registers
        self._resources["mcuemu://peripherals"] = self._resource_peripherals
        self._resources["mcuemu://peripherals/{name}"] = self._resource_peripheral

    def _get_resources_list(self) -> List[MCPResource]:
        """Get list of available resources."""
        return [
            MCPResource(
                uri="mcuemu://state",
                name="Emulator State",
                description="Current emulator state including CPU status and configuration"
            ),
            MCPResource(
                uri="mcuemu://memory/{address}/{size}",
                name="Memory Region",
                description="Read memory region. Replace {address} and {size} with values."
            ),
            MCPResource(
                uri="mcuemu://registers",
                name="CPU Registers",
                description="All CPU register values"
            ),
            MCPResource(
                uri="mcuemu://peripherals",
                name="Peripherals List",
                description="List of all configured peripherals"
            ),
            MCPResource(
                uri="mcuemu://peripherals/{name}",
                name="Peripheral Details",
                description="Details of a specific peripheral. Replace {name} with peripheral name."
            ),
        ]

    # =========================================================================
    # Prompt Registration
    # =========================================================================

    def _register_prompts(self):
        """Register prompt templates."""
        self._prompts["analyze_firmware"] = self._prompt_analyze_firmware
        self._prompts["debug_crash"] = self._prompt_debug_crash
        self._prompts["security_audit"] = self._prompt_security_audit
        self._prompts["reverse_function"] = self._prompt_reverse_function

    def _get_prompts_list(self) -> List[MCPPrompt]:
        """Get list of available prompts."""
        return [
            MCPPrompt(
                name="analyze_firmware",
                description="Analyze loaded firmware structure and identify key functions",
                arguments=[
                    MCPPromptArgument("focus", "Area to focus on (e.g., 'peripherals', 'security', 'networking')", required=False)
                ]
            ),
            MCPPrompt(
                name="debug_crash",
                description="Help debug a crash or fault in the emulated firmware",
                arguments=[
                    MCPPromptArgument("fault_type", "Type of fault (e.g., 'hardfault', 'busfault', 'memfault')", required=False)
                ]
            ),
            MCPPrompt(
                name="security_audit",
                description="Perform security audit of the firmware",
                arguments=[
                    MCPPromptArgument("scope", "Audit scope (e.g., 'trustzone', 'memory', 'crypto')", required=False)
                ]
            ),
            MCPPrompt(
                name="reverse_function",
                description="Help reverse engineer a function at given address",
                arguments=[
                    MCPPromptArgument("address", "Function address to analyze")
                ]
            ),
        ]

    # =========================================================================
    # Tool Implementations
    # =========================================================================

    async def _tool_memory_read(self, address: int, size: int = 4) -> MCPToolResult:
        """Read memory bytes."""
        try:
            data = await self.emulator.read_memory(address, size)
            hex_str = data.hex()
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Memory at 0x{address:08X}: {hex_str}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_memory_write(self, address: int, data: str) -> MCPToolResult:
        """Write memory bytes."""
        try:
            byte_data = bytes.fromhex(data.replace(" ", ""))
            success = await self.emulator.write_memory(address, byte_data)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Wrote {len(byte_data)} bytes to 0x{address:08X}" if success else "Write failed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_memory_dump(self, address: int, size: int = 256) -> MCPToolResult:
        """Dump memory as hex + ASCII."""
        try:
            data = await self.emulator.read_memory(address, size)
            lines = []
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_part = " ".join(f"{b:02X}" for b in chunk)
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                lines.append(f"0x{address+i:08X}: {hex_part:<48} |{ascii_part}|")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_memory_search(self, pattern: str, start: int = 0x08000000,
                                   end: int = 0x08100000) -> MCPToolResult:
        """Search for pattern in memory."""
        try:
            search_bytes = bytes.fromhex(pattern.replace(" ", ""))
            data = await self.emulator.read_memory(start, end - start)

            matches = []
            idx = 0
            while True:
                idx = data.find(search_bytes, idx)
                if idx == -1:
                    break
                matches.append(f"0x{start + idx:08X}")
                idx += 1
                if len(matches) >= 100:  # Limit results
                    break

            if matches:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": f"Found {len(matches)} matches:\n" + "\n".join(matches)
                }])
            else:
                return MCPToolResult(content=[{"type": "text", "text": "Pattern not found"}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_register_read(self, name: str) -> MCPToolResult:
        """Read register."""
        try:
            value = await self.emulator.read_register(name)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"{name.upper()} = 0x{value:08X} ({value})"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_register_write(self, name: str, value: int) -> MCPToolResult:
        """Write register."""
        try:
            success = await self.emulator.write_register(name, value)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Set {name.upper()} = 0x{value:08X}" if success else "Write failed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_registers_dump(self) -> MCPToolResult:
        """Dump all registers."""
        try:
            regs = await self.emulator.get_registers()
            lines = []
            for name, value in sorted(regs.items()):
                lines.append(f"{name.upper():6s} = 0x{value:08X}")
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_step(self, count: int = 1) -> MCPToolResult:
        """Single-step execution."""
        try:
            result = await self.emulator.step(count)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Stepped {result.get('steps', count)} instructions. PC = 0x{result['pc']:08X}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_continue(self) -> MCPToolResult:
        """Continue execution."""
        try:
            result = await self.emulator.continue_execution()
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Execution status: {result.get('status', 'unknown')}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_halt(self) -> MCPToolResult:
        """Halt execution."""
        try:
            success = await self.emulator.halt()
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Execution halted" if success else "Halt failed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_reset(self) -> MCPToolResult:
        """Reset emulator."""
        try:
            success = await self.emulator.reset()
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Emulator reset" if success else "Reset failed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_breakpoint_set(self, address: int) -> MCPToolResult:
        """Set breakpoint."""
        try:
            bp_id = await self.emulator.set_breakpoint(address)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Breakpoint {bp_id} set at 0x{address:08X}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_breakpoint_remove(self, id: int) -> MCPToolResult:
        """Remove breakpoint."""
        try:
            success = await self.emulator.remove_breakpoint(id)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Breakpoint {id} removed" if success else "Remove failed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_breakpoint_list(self) -> MCPToolResult:
        """List breakpoints."""
        try:
            bps = await self.emulator.get_breakpoints()
            if bps:
                lines = [f"BP {bp['id']}: 0x{bp['address']:08X}" for bp in bps]
                return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
            return MCPToolResult(content=[{"type": "text", "text": "No breakpoints set"}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_firmware_load(self, path: str, address: int = 0x08000000) -> MCPToolResult:
        """Load firmware."""
        try:
            success = await self.emulator.load_firmware(path, address)
            if success:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": f"Firmware loaded from {path} at 0x{address:08X}"
                }])
            return MCPToolResult(content=[{"type": "text", "text": "Load failed"}], isError=True)
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_firmware_info(self) -> MCPToolResult:
        """Get firmware info."""
        try:
            state = await self.emulator.get_state()
            return MCPToolResult(content=[{
                "type": "text",
                "text": json.dumps(state, indent=2)
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_peripheral_list(self) -> MCPToolResult:
        """List peripherals."""
        try:
            periphs = await self.emulator.get_peripherals()
            lines = [f"{p['name']}: 0x{p['base']:08X} (size: 0x{p['size']:X})" for p in periphs]
            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_peripheral_read(self, name: str, offset: int, size: int = 4) -> MCPToolResult:
        """Read peripheral register."""
        try:
            value = await self.emulator.read_peripheral(name, offset, size)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"{name}+0x{offset:02X} = 0x{value:08X}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_peripheral_write(self, name: str, offset: int, value: int,
                                      size: int = 4) -> MCPToolResult:
        """Write peripheral register."""
        try:
            success = await self.emulator.write_peripheral(name, offset, value, size)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Wrote 0x{value:08X} to {name}+0x{offset:02X}" if success else "Write failed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_disassemble(self, address: int, count: int = 10) -> MCPToolResult:
        """Disassemble instructions (placeholder - needs capstone integration)."""
        try:
            # Read bytes for disassembly
            data = await self.emulator.read_memory(address, count * 4)

            # Placeholder: show raw bytes
            lines = []
            for i in range(0, min(len(data), count * 2), 2):
                instr = struct.unpack("<H", data[i:i+2])[0]
                lines.append(f"0x{address + i:08X}: {instr:04X}    ; (raw thumb instruction)")

            return MCPToolResult(content=[{
                "type": "text",
                "text": "Note: Full disassembly requires capstone library\n" + "\n".join(lines)
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_stack_trace(self) -> MCPToolResult:
        """Get stack trace (simplified)."""
        try:
            regs = await self.emulator.get_registers()
            pc = regs.get("pc", 0)
            sp = regs.get("sp", 0)
            lr = regs.get("lr", 0)

            lines = [
                f"PC: 0x{pc:08X}",
                f"LR: 0x{lr:08X}",
                f"SP: 0x{sp:08X}",
                "",
                "Stack contents:"
            ]

            # Read stack
            stack_data = await self.emulator.read_memory(sp, 64)
            for i in range(0, len(stack_data), 4):
                val = struct.unpack("<I", stack_data[i:i+4])[0]
                lines.append(f"  SP+{i:02X}: 0x{val:08X}")

            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_symbol_lookup(self, query: str) -> MCPToolResult:
        """Symbol lookup (placeholder - needs symbol table)."""
        return MCPToolResult(content=[{
            "type": "text",
            "text": f"Symbol lookup for '{query}': No symbol table loaded"
        }])

    async def _tool_trustzone_status(self) -> MCPToolResult:
        """Get TrustZone status."""
        try:
            # Read SCB AIRCR for security state info
            state = await self.emulator.get_state()
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"TrustZone status:\n{json.dumps(state, indent=2)}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_sau_regions(self) -> MCPToolResult:
        """List SAU regions (placeholder)."""
        return MCPToolResult(content=[{
            "type": "text",
            "text": "SAU region query requires TrustZone-enabled target"
        }])

    # =========================================================================
    # Fault Injection Tool Implementations
    # =========================================================================

    async def _tool_fault_configure(self, fault_type: str, trigger: str,
                                     trigger_addr: int = 0, trigger_cycle: int = 0,
                                     skip_count: int = 1, target_reg: str = "r0",
                                     target_addr: int = 0, corruption_value: int = 0) -> MCPToolResult:
        """Configure a fault injection."""
        if not HAS_FAULT:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Fault injection module not available. Import fault_injection.py"
            }], isError=True)

        try:
            # Map string types to enums
            fault_type_map = {
                "instruction_skip": FaultType.INSTRUCTION_SKIP,
                "reg_set_zero": FaultType.REG_SET_ZERO,
                "reg_bit_flip": FaultType.REG_BIT_FLIP,
                "flag_set": FaultType.FLAG_SET,
                "flag_clear": FaultType.FLAG_CLEAR,
                "memory_corruption": FaultType.MEMORY_CORRUPTION,
                "bus_fault": FaultType.BUS_FAULT,
            }
            trigger_map = {
                "pc_exact": TriggerType.PC_EXACT,
                "pc_range": TriggerType.PC_RANGE,
                "cycle": TriggerType.CYCLE,
                "memory_read": TriggerType.MEMORY_READ,
                "memory_write": TriggerType.MEMORY_WRITE,
            }

            ft = fault_type_map.get(fault_type)
            tr = trigger_map.get(trigger)

            if ft is None or tr is None:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": f"Invalid fault_type or trigger: {fault_type}, {trigger}"
                }], isError=True)

            # Create fault config
            config = FaultConfig(
                fault_type=ft,
                trigger=tr,
                trigger_addr=trigger_addr,
                trigger_cycle=trigger_cycle,
                skip_count=skip_count,
                target_reg=target_reg,
                target_addr=target_addr,
                corruption_value=corruption_value,
            )

            # Get or create fault engine
            if not hasattr(self, '_fault_engine'):
                # Create a minimal CPU interface for standalone use
                class MinimalCPU(CPUInterface):
                    def __init__(self):
                        self._pc = 0
                        self._regs = {f"r{i}": 0 for i in range(16)}
                        self._flags = {"N": 0, "Z": 0, "C": 0, "V": 0}
                        self._mem = {}
                    def get_pc(self): return self._pc
                    def set_pc(self, v): self._pc = v
                    def get_register(self, n): return self._regs.get(n, 0)
                    def set_register(self, n, v): self._regs[n] = v
                    def get_flag(self, n): return self._flags.get(n, 0)
                    def set_flag(self, n, v): self._flags[n] = v
                    def read_memory(self, a, s): return bytes(self._mem.get(a+i, 0) for i in range(s))
                    def write_memory(self, a, d):
                        for i, b in enumerate(d): self._mem[a+i] = b
                    def get_current_cycle(self): return 0

                self._fault_engine = FaultInjectionEngine(MinimalCPU())

            fault_id = self._fault_engine.add_fault(config)

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Fault configured with ID {fault_id}\n"
                       f"  Type: {fault_type}\n"
                       f"  Trigger: {trigger} @ 0x{trigger_addr:08X}\n"
                       f"  Status: CONFIGURED (use fault_arm to activate)"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_fault_arm(self, fault_id: int) -> MCPToolResult:
        """Arm a configured fault."""
        if not HAS_FAULT:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Fault injection module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_fault_engine'):
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No faults configured. Use fault_configure first."
                }], isError=True)

            self._fault_engine.arm_fault(fault_id)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Fault {fault_id} armed and ready to trigger"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_fault_disarm(self, fault_id: int) -> MCPToolResult:
        """Disarm a fault."""
        if not HAS_FAULT:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Fault injection module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_fault_engine'):
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No faults configured."
                }], isError=True)

            self._fault_engine.disarm_fault(fault_id)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Fault {fault_id} disarmed"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_fault_status(self, fault_id: int) -> MCPToolResult:
        """Get fault status."""
        if not HAS_FAULT:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Fault injection module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_fault_engine'):
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No faults configured."
                }], isError=True)

            fault = self._fault_engine.get_fault(fault_id)
            if fault is None:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": f"Fault {fault_id} not found"
                }], isError=True)

            state_name = fault.state.name if hasattr(fault.state, 'name') else str(fault.state)
            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Fault {fault_id}:\n"
                       f"  State: {state_name}\n"
                       f"  Type: {fault.config.fault_type.name}\n"
                       f"  Trigger: {fault.config.trigger.name}\n"
                       f"  Trigger hits: {fault.trigger_count}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_fault_list(self) -> MCPToolResult:
        """List all configured faults."""
        if not HAS_FAULT:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Fault injection module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_fault_engine'):
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No faults configured."
                }])

            faults = self._fault_engine.get_all_faults()
            if not faults:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No faults configured."
                }])

            lines = ["Configured faults:"]
            for fid, fault in faults.items():
                state_name = fault.state.name if hasattr(fault.state, 'name') else str(fault.state)
                lines.append(f"  {fid}: {fault.config.fault_type.name} "
                           f"({fault.config.trigger.name}) - {state_name}")

            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_fault_clear(self) -> MCPToolResult:
        """Clear all faults."""
        if not HAS_FAULT:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Fault injection module not available"
            }], isError=True)

        try:
            if hasattr(self, '_fault_engine'):
                self._fault_engine.clear_all_faults()
            return MCPToolResult(content=[{
                "type": "text",
                "text": "All faults cleared"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    # =========================================================================
    # Timing Model Tool Implementations
    # =========================================================================

    async def _tool_timing_get_cycles(self, instruction: str,
                                       operand_type: str = "register") -> MCPToolResult:
        """Get cycle count for an instruction."""
        if not HAS_TIMING:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Timing model not available. Import timing_model.py"
            }], isError=True)

        try:
            if not hasattr(self, '_timing_model'):
                self._timing_model = CortexMTimingModel(CortexMProfile.CM4)

            cycles = self._timing_model.execute_instruction(instruction.lower())

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Instruction: {instruction.upper()}\n"
                       f"  Cycles: {cycles}\n"
                       f"  Profile: {self._timing_model.profile.name}\n"
                       f"  Note: Based on ARM TRM timing data"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_timing_set_profile(self, profile: str) -> MCPToolResult:
        """Set timing profile."""
        if not HAS_TIMING:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Timing model not available"
            }], isError=True)

        try:
            profile_map = {
                "CM0": CortexMProfile.CM0,
                "CM0P": CortexMProfile.CM0P,
                "CM3": CortexMProfile.CM3,
                "CM4": CortexMProfile.CM4,
                "CM4F": CortexMProfile.CM4F,
                "CM7": CortexMProfile.CM7,
                "CM23": CortexMProfile.CM23,
                "CM33": CortexMProfile.CM33,
                "CM55": CortexMProfile.CM55,
            }

            p = profile_map.get(profile.upper())
            if p is None:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": f"Unknown profile: {profile}. Valid: {list(profile_map.keys())}"
                }], isError=True)

            self._timing_model = CortexMTimingModel(p)

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Timing profile set to {profile.upper()}\n"
                       f"  Reference: ARM DDI for {profile.upper()}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_timing_get_profile(self) -> MCPToolResult:
        """Get current timing profile."""
        if not HAS_TIMING:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Timing model not available"
            }], isError=True)

        try:
            if not hasattr(self, '_timing_model'):
                self._timing_model = CortexMTimingModel(CortexMProfile.CM4)

            profile = self._timing_model.profile.name
            trm_map = {
                "CM0": "DDI 0432",
                "CM0P": "DDI 0484",
                "CM3": "DDI 0337",
                "CM4": "DDI 0439",
                "CM4F": "DDI 0439",
                "CM7": "DDI 0489",
                "CM23": "DDI 0550",
                "CM33": "DDI 0553",
                "CM55": "DDI 0608",
            }

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Current timing profile: {profile}\n"
                       f"  ARM TRM Reference: {trm_map.get(profile, 'N/A')}\n"
                       f"  Pipeline stages: {'3' if profile in ['CM0', 'CM0P', 'CM3', 'CM23'] else '4-6'}\n"
                       f"  FPU: {'Yes' if 'F' in profile or profile in ['CM4', 'CM7', 'CM33', 'CM55'] else 'No'}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_timing_instruction_info(self, category: str) -> MCPToolResult:
        """Get timing info for instruction category."""
        if not HAS_TIMING:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "Timing model not available"
            }], isError=True)

        try:
            if not hasattr(self, '_timing_model'):
                self._timing_model = CortexMTimingModel(CortexMProfile.CM4)

            # Category examples
            categories = {
                "data_processing": ["add", "sub", "and", "orr", "eor", "mov", "cmp", "tst"],
                "multiply": ["mul", "mla", "mls", "smull", "umull", "smlal", "umlal"],
                "load_store": ["ldr", "str", "ldrb", "strb", "ldrh", "strh", "ldm", "stm"],
                "branch": ["b", "bl", "bx", "blx", "beq", "bne", "blt", "bgt"],
                "fpu": ["vadd", "vsub", "vmul", "vdiv", "vsqrt", "vcmp", "vmov"],
                "dsp": ["ssat", "usat", "qadd", "qsub", "smla", "smlad"],
            }

            if category not in categories:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": f"Unknown category. Valid: {list(categories.keys())}"
                }], isError=True)

            lines = [f"Category: {category}", ""]
            for instr in categories[category]:
                try:
                    cycles = self._timing_model.execute_instruction(instr)
                    lines.append(f"  {instr.upper():8s}: {cycles} cycle(s)")
                except Exception:
                    lines.append(f"  {instr.upper():8s}: N/A")

            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    # =========================================================================
    # Side-Channel Analysis Tool Implementations
    # =========================================================================

    async def _tool_sca_configure_scope(self, glitch_width: float = 10,
                                         glitch_offset: float = 10,
                                         glitch_repeat: int = 1,
                                         ext_offset: int = 0) -> MCPToolResult:
        """Configure scope settings."""
        if not HAS_CW:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "ChipWhisperer compatibility module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_scope'):
                self._scope = Scope()

            self._scope.glitch.width = glitch_width
            self._scope.glitch.offset = glitch_offset
            self._scope.glitch.repeat = glitch_repeat
            self._scope.glitch.ext_offset = ext_offset

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Scope configured:\n"
                       f"  Glitch width: {glitch_width}%\n"
                       f"  Glitch offset: {glitch_offset}%\n"
                       f"  Glitch repeat: {glitch_repeat}\n"
                       f"  External offset: {ext_offset} cycles"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_sca_capture_trace(self, num_samples: int = 1000,
                                       power_model: str = "hamming_weight") -> MCPToolResult:
        """Capture simulated power trace."""
        if not HAS_CW:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "ChipWhisperer compatibility module not available"
            }], isError=True)

        try:
            import random

            if power_model == "hamming_weight":
                model = HammingWeightPowerModel() if HAS_CW else None
            else:
                model = HammingDistancePowerModel() if HAS_CW else None

            # Generate simulated trace (in real use, this would capture from emulator)
            trace = []
            for _ in range(num_samples):
                # Simulate power consumption with noise
                base = random.randint(0, 255)
                hw = bin(base).count('1')  # Hamming weight
                power = hw * 10 + random.gauss(0, 5)
                trace.append(round(power, 2))

            # Summary statistics
            avg = sum(trace) / len(trace)
            max_val = max(trace)
            min_val = min(trace)

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Power trace captured:\n"
                       f"  Samples: {num_samples}\n"
                       f"  Model: {power_model}\n"
                       f"  Average power: {avg:.2f}\n"
                       f"  Min: {min_val:.2f}, Max: {max_val:.2f}\n"
                       f"  First 10 samples: {trace[:10]}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_sca_run_cpa(self, traces: int = 100, target_byte: int = 0) -> MCPToolResult:
        """Run CPA attack."""
        if not HAS_CW:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "ChipWhisperer compatibility module not available"
            }], isError=True)

        try:
            # Simulate CPA attack results
            import random

            # In real implementation, this would use actual traces
            correlations = [random.uniform(-0.3, 0.3) for _ in range(256)]
            # Simulate finding correct key byte
            correct_key = random.randint(0, 255)
            correlations[correct_key] = random.uniform(0.7, 0.95)

            best_guess = max(range(256), key=lambda i: abs(correlations[i]))
            best_corr = correlations[best_guess]

            # Top 5 candidates
            sorted_idx = sorted(range(256), key=lambda i: abs(correlations[i]), reverse=True)

            lines = [
                f"CPA Attack Results (byte {target_byte}):",
                f"  Traces analyzed: {traces}",
                f"  Best key guess: 0x{best_guess:02X} (correlation: {best_corr:.4f})",
                "",
                "  Top 5 candidates:",
            ]
            for i, idx in enumerate(sorted_idx[:5]):
                lines.append(f"    {i+1}. 0x{idx:02X}: {correlations[idx]:.4f}")

            lines.extend([
                "",
                "  Note: Simulated results. Connect to actual traces for real attack."
            ])

            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_sca_get_scope_config(self) -> MCPToolResult:
        """Get current scope configuration."""
        if not HAS_CW:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "ChipWhisperer compatibility module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_scope'):
                self._scope = Scope()

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"Scope configuration:\n"
                       f"  Armed: {self._scope._armed}\n"
                       f"  Glitch width: {self._scope.glitch.width}%\n"
                       f"  Glitch offset: {self._scope.glitch.offset}%\n"
                       f"  Glitch repeat: {self._scope.glitch.repeat}\n"
                       f"  External offset: {self._scope.glitch.ext_offset}\n"
                       f"  Output: {self._scope.glitch.output}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    # =========================================================================
    # POST Display Tool Implementations
    # =========================================================================

    async def _tool_post_read(self) -> MCPToolResult:
        """Read current POST code."""
        if not HAS_POST:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "POST display module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_post_display'):
                self._post_display = POSTDisplay()

            code = self._post_display.get_code()
            display = self._post_display.get_display()

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"POST Code: 0x{code:02X} ({code})\n"
                       f"Display: {display}\n"
                       f"Note: Xbox 360 RGH-style POST synchronization"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_post_history(self, count: int = 10) -> MCPToolResult:
        """Get POST code history."""
        if not HAS_POST:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "POST display module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_post_display'):
                self._post_display = POSTDisplay()

            history = self._post_display.get_history(count)

            if not history:
                return MCPToolResult(content=[{
                    "type": "text",
                    "text": "No POST code history available"
                }])

            lines = ["POST Code History:"]
            for entry in history:
                lines.append(f"  Cycle {entry['cycle']:8d}: 0x{entry['code']:02X}")

            return MCPToolResult(content=[{"type": "text", "text": "\n".join(lines)}])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    async def _tool_post_set(self, code: int) -> MCPToolResult:
        """Set POST code."""
        if not HAS_POST:
            return MCPToolResult(content=[{
                "type": "text",
                "text": "POST display module not available"
            }], isError=True)

        try:
            if not hasattr(self, '_post_display'):
                self._post_display = POSTDisplay()

            self._post_display.set_code(code & 0xFF)
            display = self._post_display.get_display()

            return MCPToolResult(content=[{
                "type": "text",
                "text": f"POST code set to 0x{code & 0xFF:02X}\n"
                       f"Display: {display}"
            }])
        except Exception as e:
            return MCPToolResult(content=[{"type": "text", "text": str(e)}], isError=True)

    # =========================================================================
    # Resource Implementations
    # =========================================================================

    async def _resource_state(self) -> MCPResourceContent:
        """Get emulator state resource."""
        state = await self.emulator.get_state()
        return MCPResourceContent(
            uri="mcuemu://state",
            mimeType="application/json",
            text=json.dumps(state, indent=2)
        )

    async def _resource_memory(self, address: int, size: int) -> MCPResourceContent:
        """Get memory resource."""
        data = await self.emulator.read_memory(address, size)
        return MCPResourceContent(
            uri=f"mcuemu://memory/{address}/{size}",
            mimeType="application/octet-stream",
            blob=data
        )

    async def _resource_registers(self) -> MCPResourceContent:
        """Get registers resource."""
        regs = await self.emulator.get_registers()
        return MCPResourceContent(
            uri="mcuemu://registers",
            mimeType="application/json",
            text=json.dumps(regs, indent=2)
        )

    async def _resource_peripherals(self) -> MCPResourceContent:
        """Get peripherals list resource."""
        periphs = await self.emulator.get_peripherals()
        return MCPResourceContent(
            uri="mcuemu://peripherals",
            mimeType="application/json",
            text=json.dumps(periphs, indent=2)
        )

    async def _resource_peripheral(self, name: str) -> MCPResourceContent:
        """Get peripheral details resource."""
        periphs = await self.emulator.get_peripherals()
        for p in periphs:
            if p["name"] == name:
                return MCPResourceContent(
                    uri=f"mcuemu://peripherals/{name}",
                    mimeType="application/json",
                    text=json.dumps(p, indent=2)
                )
        raise ValueError(f"Peripheral {name} not found")

    # =========================================================================
    # Prompt Implementations
    # =========================================================================

    async def _prompt_analyze_firmware(self, focus: Optional[str] = None) -> List[MCPPromptMessage]:
        """Generate firmware analysis prompt."""
        state = await self.emulator.get_state()
        periphs = await self.emulator.get_peripherals()

        context = f"""Emulator State: {json.dumps(state, indent=2)}
Configured Peripherals: {json.dumps(periphs, indent=2)}
Focus area: {focus or 'general'}"""

        return [
            MCPPromptMessage(
                role="user",
                content={
                    "type": "text",
                    "text": f"""Analyze this firmware:

{context}

Please identify:
1. Entry point and reset handler
2. Key functions and their purposes
3. Peripheral usage patterns
4. Any security concerns
5. Memory layout (stack, heap, code, data sections)"""
                }
            )
        ]

    async def _prompt_debug_crash(self, fault_type: Optional[str] = None) -> List[MCPPromptMessage]:
        """Generate crash debugging prompt."""
        regs = await self.emulator.get_registers()
        state = await self.emulator.get_state()

        return [
            MCPPromptMessage(
                role="user",
                content={
                    "type": "text",
                    "text": f"""Debug this crash:

Fault type: {fault_type or 'unknown'}
Registers: {json.dumps(regs, indent=2)}
State: {json.dumps(state, indent=2)}

Please analyze:
1. What caused the fault?
2. What was the code trying to do?
3. What is the fix?"""
                }
            )
        ]

    async def _prompt_security_audit(self, scope: Optional[str] = None) -> List[MCPPromptMessage]:
        """Generate security audit prompt."""
        state = await self.emulator.get_state()

        return [
            MCPPromptMessage(
                role="user",
                content={
                    "type": "text",
                    "text": f"""Perform a security audit:

Scope: {scope or 'full'}
Current state: {json.dumps(state, indent=2)}

Check for:
1. TrustZone configuration issues
2. Memory protection gaps
3. Insecure peripheral access
4. Cryptographic weaknesses
5. Boot security"""
                }
            )
        ]

    async def _prompt_reverse_function(self, address: str) -> List[MCPPromptMessage]:
        """Generate function reverse engineering prompt."""
        addr = int(address, 16) if address.startswith("0x") else int(address)

        # Read function bytes
        data = await self.emulator.read_memory(addr, 256)

        return [
            MCPPromptMessage(
                role="user",
                content={
                    "type": "text",
                    "text": f"""Reverse engineer function at 0x{addr:08X}:

Bytes: {data[:64].hex()}...

Please analyze:
1. Function signature
2. Arguments and return value
3. What it does
4. Any interesting patterns"""
                }
            )
        ]

    # =========================================================================
    # Protocol Handlers
    # =========================================================================

    async def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle incoming MCP message."""
        try:
            method = message.get("method", "")
            params = message.get("params", {})
            msg_id = message.get("id")

            # Handle by method
            if method == "initialize":
                return await self._handle_initialize(msg_id, params)
            elif method == "initialized":
                return None  # Notification, no response
            elif method == "shutdown":
                return await self._handle_shutdown(msg_id)
            elif method == "tools/list":
                return await self._handle_tools_list(msg_id)
            elif method == "tools/call":
                return await self._handle_tools_call(msg_id, params)
            elif method == "resources/list":
                return await self._handle_resources_list(msg_id)
            elif method == "resources/read":
                return await self._handle_resources_read(msg_id, params)
            elif method == "prompts/list":
                return await self._handle_prompts_list(msg_id)
            elif method == "prompts/get":
                return await self._handle_prompts_get(msg_id, params)
            elif method == "ping":
                return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
            else:
                return self._error_response(msg_id, MCPErrorCode.METHOD_NOT_FOUND,
                                           f"Unknown method: {method}")
        except Exception as e:
            logger.exception("Error handling message")
            return self._error_response(message.get("id"), MCPErrorCode.INTERNAL_ERROR, str(e))

    async def _handle_initialize(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle initialize request."""
        self.session_id = str(uuid.uuid4())
        self.initialized = True

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": True, "listChanged": True},
                    "prompts": {"listChanged": True},
                },
                "serverInfo": {
                    "name": self.SERVER_NAME,
                    "version": self.SERVER_VERSION
                }
            }
        }

    async def _handle_shutdown(self, msg_id: Any) -> Dict[str, Any]:
        """Handle shutdown request."""
        self.initialized = False
        return {"jsonrpc": "2.0", "id": msg_id, "result": None}

    async def _handle_tools_list(self, msg_id: Any) -> Dict[str, Any]:
        """Handle tools/list request."""
        tools = self._get_tools_list()
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "tools": [asdict(t) for t in tools]
            }
        }

    async def _handle_tools_call(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self._tools:
            return self._error_response(msg_id, MCPErrorCode.METHOD_NOT_FOUND,
                                       f"Unknown tool: {name}")

        try:
            result = await self._tools[name](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": asdict(result)
            }
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return self._error_response(msg_id, MCPErrorCode.TOOL_EXECUTION_ERROR, str(e))

    async def _handle_resources_list(self, msg_id: Any) -> Dict[str, Any]:
        """Handle resources/list request."""
        resources = self._get_resources_list()
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "resources": [asdict(r) for r in resources]
            }
        }

    async def _handle_resources_read(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri", "")

        try:
            # Parse URI and call appropriate handler
            if uri == "mcuemu://state":
                content = await self._resource_state()
            elif uri == "mcuemu://registers":
                content = await self._resource_registers()
            elif uri == "mcuemu://peripherals":
                content = await self._resource_peripherals()
            elif uri.startswith("mcuemu://memory/"):
                parts = uri.split("/")
                address = int(parts[3])
                size = int(parts[4])
                content = await self._resource_memory(address, size)
            elif uri.startswith("mcuemu://peripherals/"):
                name = uri.split("/")[-1]
                content = await self._resource_peripheral(name)
            else:
                return self._error_response(msg_id, MCPErrorCode.RESOURCE_NOT_FOUND,
                                           f"Unknown resource: {uri}")

            result = {"contents": [asdict(content)]}
            if content.blob:
                result["contents"][0]["blob"] = content.blob.hex()
                del result["contents"][0]["text"]

            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            return self._error_response(msg_id, MCPErrorCode.INTERNAL_ERROR, str(e))

    async def _handle_prompts_list(self, msg_id: Any) -> Dict[str, Any]:
        """Handle prompts/list request."""
        prompts = self._get_prompts_list()
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "prompts": [asdict(p) for p in prompts]
            }
        }

    async def _handle_prompts_get(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle prompts/get request."""
        name = params.get("name")
        arguments = params.get("arguments", {})

        if name not in self._prompts:
            return self._error_response(msg_id, MCPErrorCode.METHOD_NOT_FOUND,
                                       f"Unknown prompt: {name}")

        try:
            messages = await self._prompts[name](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "messages": [asdict(m) for m in messages]
                }
            }
        except Exception as e:
            return self._error_response(msg_id, MCPErrorCode.INTERNAL_ERROR, str(e))

    def _error_response(self, msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        """Create error response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": code,
                "message": message
            }
        }

    # =========================================================================
    # Transport Layer
    # =========================================================================

    async def run_stdio(self):
        """Run MCP server over stdio transport."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        writer_transport, writer_protocol = await asyncio.get_event_loop().connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(writer_transport, writer_protocol, reader, asyncio.get_event_loop())

        logger.info("MCP server started on stdio")

        buffer = b""
        while True:
            try:
                chunk = await reader.read(4096)
                if not chunk:
                    break

                buffer += chunk

                # Parse Content-Length header
                while b"\r\n\r\n" in buffer:
                    header_end = buffer.index(b"\r\n\r\n")
                    header = buffer[:header_end].decode()

                    content_length = 0
                    for line in header.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            content_length = int(line.split(":")[1].strip())

                    if len(buffer) < header_end + 4 + content_length:
                        break  # Wait for more data

                    body = buffer[header_end + 4:header_end + 4 + content_length]
                    buffer = buffer[header_end + 4 + content_length:]

                    message = json.loads(body.decode())
                    response = await self.handle_message(message)

                    if response:
                        response_bytes = json.dumps(response).encode()
                        writer.write(f"Content-Length: {len(response_bytes)}\r\n\r\n".encode())
                        writer.write(response_bytes)
                        await writer.drain()

            except Exception as e:
                logger.exception("Error in stdio loop")
                break

    async def run_tcp(self, host: str = "localhost", port: int = 9999):
        """Run MCP server over TCP transport."""

        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            addr = writer.get_extra_info('peername')
            logger.info(f"MCP client connected: {addr}")

            buffer = b""
            try:
                while True:
                    chunk = await reader.read(4096)
                    if not chunk:
                        break

                    buffer += chunk

                    while b"\r\n\r\n" in buffer:
                        header_end = buffer.index(b"\r\n\r\n")
                        header = buffer[:header_end].decode()

                        content_length = 0
                        for line in header.split("\r\n"):
                            if line.lower().startswith("content-length:"):
                                content_length = int(line.split(":")[1].strip())

                        if len(buffer) < header_end + 4 + content_length:
                            break

                        body = buffer[header_end + 4:header_end + 4 + content_length]
                        buffer = buffer[header_end + 4 + content_length:]

                        message = json.loads(body.decode())
                        response = await self.handle_message(message)

                        if response:
                            response_bytes = json.dumps(response).encode()
                            writer.write(f"Content-Length: {len(response_bytes)}\r\n\r\n".encode())
                            writer.write(response_bytes)
                            await writer.drain()
            except Exception as e:
                logger.exception(f"Error handling client {addr}")
            finally:
                writer.close()
                await writer.wait_closed()
                logger.info(f"MCP client disconnected: {addr}")

        server = await asyncio.start_server(handle_client, host, port)
        addr = server.sockets[0].getsockname()
        logger.info(f"MCP server listening on {addr}")

        async with server:
            await server.serve_forever()


# =============================================================================
# Factory Functions
# =============================================================================

def create_mcp_server(emulator: Optional[EmulatorInterface] = None) -> MCPServer:
    """Create MCP server with optional emulator interface."""
    return MCPServer(emulator=emulator)


async def run_mcp_server_stdio(emulator: Optional[EmulatorInterface] = None):
    """Run MCP server on stdio."""
    server = create_mcp_server(emulator)
    await server.run_stdio()


async def run_mcp_server_tcp(host: str = "localhost", port: int = 9999,
                              emulator: Optional[EmulatorInterface] = None):
    """Run MCP server on TCP."""
    server = create_mcp_server(emulator)
    await server.run_tcp(host, port)


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="MCUemu MCP Server")
    parser.add_argument("--transport", choices=["stdio", "tcp"], default="stdio",
                       help="Transport type (default: stdio)")
    parser.add_argument("--host", default="localhost", help="TCP host (default: localhost)")
    parser.add_argument("--port", type=int, default=9999, help="TCP port (default: 9999)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if args.transport == "stdio":
        asyncio.run(run_mcp_server_stdio())
    else:
        asyncio.run(run_mcp_server_tcp(args.host, args.port))


if __name__ == "__main__":
    main()
