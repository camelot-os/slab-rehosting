#!/usr/bin/env python3
"""
Slab MCP Server

Model Context Protocol server implementation with automatic capability discovery.

Author: Mathieu Renard <mathieu.renard@twistedwires.io>
Copyright (C) 2025 Twisted Wires Security Lab
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, TextIO
from enum import Enum, IntEnum

from .discovery import discover_packages, SlabCapability, get_available_capabilities
from .tools import MCPToolRegistry, get_tool_registry

logger = logging.getLogger(__name__)


class MCPErrorCode(IntEnum):
    """Standard JSON-RPC and MCP error codes."""
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    RESOURCE_NOT_FOUND = -32001
    TOOL_EXECUTION_ERROR = -32002


@dataclass
class ServerInfo:
    """MCP server information."""
    name: str = "slab-mcp"
    version: str = "0.1.0"


@dataclass
class SlabMCPServer:
    """
    Slab MCP Server.

    Provides MCP protocol implementation with automatic discovery of
    Slab package capabilities.

    Usage:
        server = SlabMCPServer()
        await server.run()
    """

    info: ServerInfo = field(default_factory=ServerInfo)
    tool_registry: MCPToolRegistry = field(default_factory=get_tool_registry)

    # I/O streams
    _input: TextIO = field(default_factory=lambda: sys.stdin)
    _output: TextIO = field(default_factory=lambda: sys.stdout)

    # State
    _initialized: bool = False
    _capabilities: List[SlabCapability] = field(default_factory=list)

    def __post_init__(self):
        """Initialize server with discovered capabilities."""
        self._capabilities = get_available_capabilities()
        logger.info(f"Slab MCP Server initialized with {len(self._capabilities)} capabilities")

    async def run(self):
        """Run the MCP server."""
        logger.info("Starting Slab MCP Server...")

        # Read from stdin, write to stdout (MCP stdio transport)
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        loop = asyncio.get_event_loop()
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                # Read message (newline-delimited JSON)
                line = await reader.readline()
                if not line:
                    break

                message = json.loads(line.decode())
                response = await self._handle_message(message)

                if response:
                    self._send_response(response)

            except json.JSONDecodeError as e:
                self._send_error(None, MCPErrorCode.PARSE_ERROR, str(e))
            except Exception as e:
                logger.exception("Error handling message")
                self._send_error(None, MCPErrorCode.INTERNAL_ERROR, str(e))

    async def _handle_message(self, message: Dict) -> Optional[Dict]:
        """Handle an incoming MCP message."""
        msg_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        if method == "initialize":
            return self._handle_initialize(msg_id, params)
        elif method == "initialized":
            self._initialized = True
            return None  # No response for notifications
        elif method == "tools/list":
            return self._handle_tools_list(msg_id)
        elif method == "tools/call":
            return await self._handle_tools_call(msg_id, params)
        elif method == "resources/list":
            return self._handle_resources_list(msg_id)
        elif method == "resources/read":
            return await self._handle_resources_read(msg_id, params)
        elif method == "prompts/list":
            return self._handle_prompts_list(msg_id)
        elif method == "ping":
            return self._make_response(msg_id, {})
        else:
            return self._make_error(msg_id, MCPErrorCode.METHOD_NOT_FOUND,
                                   f"Unknown method: {method}")

    def _handle_initialize(self, msg_id: Any, params: Dict) -> Dict:
        """Handle initialize request."""
        return self._make_response(msg_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
            "serverInfo": {
                "name": self.info.name,
                "version": self.info.version,
            },
        })

    def _handle_tools_list(self, msg_id: Any) -> Dict:
        """Handle tools/list request."""
        tools = self.tool_registry.get_schemas()
        return self._make_response(msg_id, {"tools": tools})

    async def _handle_tools_call(self, msg_id: Any, params: Dict) -> Dict:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            return self._make_error(msg_id, MCPErrorCode.INVALID_PARAMS,
                                   "Missing tool name")

        try:
            result = await self.tool_registry.invoke(tool_name, arguments)
            return self._make_response(msg_id, {
                "content": [
                    {"type": "text", "text": json.dumps(result, indent=2)}
                ],
            })
        except ValueError as e:
            return self._make_error(msg_id, MCPErrorCode.TOOL_EXECUTION_ERROR, str(e))
        except Exception as e:
            logger.exception(f"Error executing tool {tool_name}")
            return self._make_error(msg_id, MCPErrorCode.INTERNAL_ERROR, str(e))

    def _handle_resources_list(self, msg_id: Any) -> Dict:
        """Handle resources/list request."""
        resources = []

        # Add capability-based resources
        if SlabCapability.TIMING_MODEL_M in self._capabilities:
            resources.append({
                "uri": "slab://timing/cortex-m",
                "name": "Cortex-M Timing Model",
                "description": "Cycle-accurate timing model for ARM Cortex-M",
                "mimeType": "application/json",
            })

        if SlabCapability.TIMING_MODEL_A in self._capabilities:
            resources.append({
                "uri": "slab://timing/cortex-a",
                "name": "Cortex-A Timing Model",
                "description": "Timing model for ARM Cortex-A with cache/OoO",
                "mimeType": "application/json",
            })

        if SlabCapability.POWER_MODEL in self._capabilities:
            resources.append({
                "uri": "slab://sidechannels/power-model",
                "name": "Power Model",
                "description": "Hamming weight/distance power leakage model",
                "mimeType": "application/json",
            })

        if SlabCapability.VOLTAGE_GLITCH in self._capabilities:
            resources.append({
                "uri": "slab://glitch/voltage",
                "name": "Voltage Glitch Model",
                "description": "Voltage glitch fault injection model",
                "mimeType": "application/json",
            })

        return self._make_response(msg_id, {"resources": resources})

    async def _handle_resources_read(self, msg_id: Any, params: Dict) -> Dict:
        """Handle resources/read request."""
        uri = params.get("uri", "")

        if uri.startswith("slab://timing/"):
            content = {"type": "timing_model", "capabilities": "placeholder"}
        elif uri.startswith("slab://sidechannels/"):
            content = {"type": "power_model", "capabilities": "placeholder"}
        elif uri.startswith("slab://glitch/"):
            content = {"type": "glitch_model", "capabilities": "placeholder"}
        else:
            return self._make_error(msg_id, MCPErrorCode.RESOURCE_NOT_FOUND,
                                   f"Unknown resource: {uri}")

        return self._make_response(msg_id, {
            "contents": [
                {"uri": uri, "mimeType": "application/json",
                 "text": json.dumps(content)}
            ],
        })

    def _handle_prompts_list(self, msg_id: Any) -> Dict:
        """Handle prompts/list request."""
        prompts = []

        if SlabCapability.CPA_ATTACK in self._capabilities:
            prompts.append({
                "name": "cpa_attack_guide",
                "description": "Guide for performing a CPA attack",
            })

        if SlabCapability.VOLTAGE_GLITCH in self._capabilities:
            prompts.append({
                "name": "glitch_attack_guide",
                "description": "Guide for performing a voltage glitch attack",
            })

        return self._make_response(msg_id, {"prompts": prompts})

    def _make_response(self, msg_id: Any, result: Dict) -> Dict:
        """Create a successful response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }

    def _make_error(self, msg_id: Any, code: int, message: str) -> Dict:
        """Create an error response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": code,
                "message": message,
            },
        }

    def _send_response(self, response: Dict):
        """Send a response to stdout."""
        json_str = json.dumps(response)
        print(json_str, flush=True)

    def _send_error(self, msg_id: Any, code: int, message: str):
        """Send an error response."""
        self._send_response(self._make_error(msg_id, code, message))


def create_mcp_server() -> SlabMCPServer:
    """Create and return a configured MCP server."""
    return SlabMCPServer()


async def main():
    """Main entry point for the MCP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    server = create_mcp_server()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
