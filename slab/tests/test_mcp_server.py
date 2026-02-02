"""
Tests for MCUemu MCP Server.

Tests the Model Context Protocol server implementation including
tools, resources, prompts, and protocol handling.
"""
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 TwistedWires - Mathieu Renard

import asyncio
import json
import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from mcp_server import (
    MCPServer,
    MCPTool,
    MCPToolParameter,
    MCPToolResult,
    MCPResource,
    MCPResourceContent,
    MCPPrompt,
    MCPPromptArgument,
    MCPPromptMessage,
    MCPRequest,
    MCPResponse,
    MCPError,
    MCPErrorCode,
    MockEmulatorInterface,
    EmulatorInterface,
    create_mcp_server,
)


# =============================================================================
# Helper for running async tests
# =============================================================================

def run_async(coro):
    """Run async coroutine in sync context."""
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def mock_emulator():
    """Create mock emulator interface."""
    return MockEmulatorInterface()


@pytest.fixture
def mcp_server(mock_emulator):
    """Create MCP server with mock emulator."""
    return MCPServer(emulator=mock_emulator)


# =============================================================================
# Protocol Message Tests
# =============================================================================

class TestMCPProtocol:
    """Test MCP protocol handling."""

    def test_initialize(self, mcp_server):
        """Test initialize request."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }

        response = run_async(mcp_server.handle_message(request))

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert response["result"]["protocolVersion"] == "2024-11-05"
        assert "capabilities" in response["result"]
        assert "serverInfo" in response["result"]
        assert response["result"]["serverInfo"]["name"] == "mcuemu-mcp"
        assert mcp_server.initialized

    def test_shutdown(self, mcp_server):
        """Test shutdown request."""
        # Initialize first
        run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        }))

        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "shutdown"
        }))

        assert response["id"] == 2
        assert response["result"] is None
        assert not mcp_server.initialized

    def test_ping(self, mcp_server):
        """Test ping request."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "ping"
        }))

        assert response["id"] == 1
        assert response["result"] == {}

    def test_unknown_method(self, mcp_server):
        """Test unknown method returns error."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "unknown/method"
        }))

        assert "error" in response
        assert response["error"]["code"] == MCPErrorCode.METHOD_NOT_FOUND

    def test_notification_no_response(self, mcp_server):
        """Test notifications return no response."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "method": "initialized"
        }))

        assert response is None


# =============================================================================
# Tools Tests
# =============================================================================

class TestMCPTools:
    """Test MCP tool operations."""

    def test_tools_list(self, mcp_server):
        """Test tools/list returns all tools."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list"
        }))

        assert "result" in response
        tools = response["result"]["tools"]
        assert len(tools) > 0

        # Check some expected tools exist
        tool_names = [t["name"] for t in tools]
        assert "memory_read" in tool_names
        assert "memory_write" in tool_names
        assert "register_read" in tool_names
        assert "step" in tool_names
        assert "breakpoint_set" in tool_names

    def test_tool_memory_read(self, mcp_server, mock_emulator):
        """Test memory_read tool."""
        # Write some data first
        run_async(mock_emulator.write_memory(0x20000000, bytes([0xDE, 0xAD, 0xBE, 0xEF])))

        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "memory_read",
                "arguments": {"address": 0x20000000, "size": 4}
            }
        }))

        assert "result" in response
        assert not response["result"]["isError"]
        content = response["result"]["content"][0]["text"]
        assert "deadbeef" in content.lower()

    def test_tool_memory_write(self, mcp_server, mock_emulator):
        """Test memory_write tool."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "memory_write",
                "arguments": {"address": 0x20000100, "data": "CAFEBABE"}
            }
        }))

        assert "result" in response
        assert not response["result"]["isError"]

        # Verify write
        data = run_async(mock_emulator.read_memory(0x20000100, 4))
        assert data == bytes([0xCA, 0xFE, 0xBA, 0xBE])

    def test_tool_memory_dump(self, mcp_server, mock_emulator):
        """Test memory_dump tool."""
        # Write test pattern
        run_async(mock_emulator.write_memory(0x20000000, b"Hello World! Test pattern."))

        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "memory_dump",
                "arguments": {"address": 0x20000000, "size": 32}
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "0x20000000" in content
        assert "Hello" in content or "48656C6C6F" in content.upper()

    def test_tool_register_read(self, mcp_server, mock_emulator):
        """Test register_read tool."""
        mock_emulator.registers["r0"] = 0x12345678

        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "register_read",
                "arguments": {"name": "r0"}
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "12345678" in content.upper()

    def test_tool_register_write(self, mcp_server, mock_emulator):
        """Test register_write tool."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "register_write",
                "arguments": {"name": "r1", "value": 0xABCDEF00}
            }
        }))

        assert "result" in response
        assert not response["result"]["isError"]
        assert mock_emulator.registers["r1"] == 0xABCDEF00

    def test_tool_registers_dump(self, mcp_server, mock_emulator):
        """Test registers_dump tool."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "registers_dump",
                "arguments": {}
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "PC" in content.upper()
        assert "SP" in content.upper()
        assert "LR" in content.upper()

    def test_tool_step(self, mcp_server, mock_emulator):
        """Test step tool."""
        initial_pc = mock_emulator.registers["pc"]

        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "step",
                "arguments": {"count": 5}
            }
        }))

        assert "result" in response
        assert mock_emulator.registers["pc"] == initial_pc + 10  # 5 * 2 bytes

    def test_tool_breakpoint_set_and_list(self, mcp_server):
        """Test breakpoint_set and breakpoint_list tools."""
        # Set breakpoint
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "breakpoint_set",
                "arguments": {"address": 0x08001000}
            }
        }))

        assert "result" in response
        assert "Breakpoint" in response["result"]["content"][0]["text"]

        # List breakpoints
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "breakpoint_list",
                "arguments": {}
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "08001000" in content.upper()

    def test_tool_breakpoint_remove(self, mcp_server):
        """Test breakpoint_remove tool."""
        # Set breakpoint
        run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "breakpoint_set", "arguments": {"address": 0x08002000}}
        }))

        # Remove it
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "breakpoint_remove",
                "arguments": {"id": 1}
            }
        }))

        assert "result" in response
        assert "removed" in response["result"]["content"][0]["text"]

    def test_tool_peripheral_list(self, mcp_server):
        """Test peripheral_list tool."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "peripheral_list",
                "arguments": {}
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "GPIOA" in content
        assert "USART1" in content

    def test_tool_peripheral_read_write(self, mcp_server, mock_emulator):
        """Test peripheral_read and peripheral_write tools."""
        # Write to GPIOA
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "peripheral_write",
                "arguments": {"name": "GPIOA", "offset": 0x14, "value": 0xFF00}
            }
        }))

        assert "result" in response

        # Read back
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "peripheral_read",
                "arguments": {"name": "GPIOA", "offset": 0x14}
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "FF00" in content.upper()

    def test_tool_halt_continue_reset(self, mcp_server, mock_emulator):
        """Test halt, continue, and reset tools."""
        # Continue
        run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "continue", "arguments": {}}
        }))
        assert not mock_emulator.halted

        # Halt
        run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "halt", "arguments": {}}
        }))
        assert mock_emulator.halted

        # Modify PC
        mock_emulator.registers["pc"] = 0x08010000

        # Reset
        run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "reset", "arguments": {}}
        }))
        assert mock_emulator.registers["pc"] == 0x08000000

    def test_tool_unknown(self, mcp_server):
        """Test unknown tool returns error."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "nonexistent_tool",
                "arguments": {}
            }
        }))

        assert "error" in response
        assert response["error"]["code"] == MCPErrorCode.METHOD_NOT_FOUND


# =============================================================================
# Resources Tests
# =============================================================================

class TestMCPResources:
    """Test MCP resource operations."""

    def test_resources_list(self, mcp_server):
        """Test resources/list returns all resources."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "resources/list"
        }))

        assert "result" in response
        resources = response["result"]["resources"]
        assert len(resources) > 0

        uris = [r["uri"] for r in resources]
        assert "mcuemu://state" in uris
        assert "mcuemu://registers" in uris

    def test_resource_state(self, mcp_server):
        """Test reading state resource."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "mcuemu://state"}
        }))

        assert "result" in response
        contents = response["result"]["contents"]
        assert len(contents) == 1

        state = json.loads(contents[0]["text"])
        assert "halted" in state
        assert "pc" in state

    def test_resource_registers(self, mcp_server):
        """Test reading registers resource."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "mcuemu://registers"}
        }))

        assert "result" in response
        contents = response["result"]["contents"]

        regs = json.loads(contents[0]["text"])
        assert "pc" in regs
        assert "sp" in regs

    def test_resource_peripherals(self, mcp_server):
        """Test reading peripherals resource."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "mcuemu://peripherals"}
        }))

        assert "result" in response
        contents = response["result"]["contents"]

        periphs = json.loads(contents[0]["text"])
        assert len(periphs) > 0
        assert any(p["name"] == "GPIOA" for p in periphs)

    def test_resource_peripheral_detail(self, mcp_server):
        """Test reading specific peripheral resource."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "mcuemu://peripherals/GPIOA"}
        }))

        assert "result" in response
        contents = response["result"]["contents"]

        periph = json.loads(contents[0]["text"])
        assert periph["name"] == "GPIOA"
        assert "base" in periph

    def test_resource_unknown(self, mcp_server):
        """Test reading unknown resource returns error."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "mcuemu://unknown"}
        }))

        assert "error" in response


# =============================================================================
# Prompts Tests
# =============================================================================

class TestMCPPrompts:
    """Test MCP prompt operations."""

    def test_prompts_list(self, mcp_server):
        """Test prompts/list returns all prompts."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "prompts/list"
        }))

        assert "result" in response
        prompts = response["result"]["prompts"]
        assert len(prompts) > 0

        names = [p["name"] for p in prompts]
        assert "analyze_firmware" in names
        assert "debug_crash" in names
        assert "security_audit" in names

    def test_prompt_analyze_firmware(self, mcp_server):
        """Test analyze_firmware prompt."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "prompts/get",
            "params": {
                "name": "analyze_firmware",
                "arguments": {"focus": "security"}
            }
        }))

        assert "result" in response
        messages = response["result"]["messages"]
        assert len(messages) > 0
        assert messages[0]["role"] == "user"
        assert "Analyze" in messages[0]["content"]["text"]

    def test_prompt_debug_crash(self, mcp_server):
        """Test debug_crash prompt."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "prompts/get",
            "params": {
                "name": "debug_crash",
                "arguments": {"fault_type": "hardfault"}
            }
        }))

        assert "result" in response
        messages = response["result"]["messages"]
        assert "hardfault" in messages[0]["content"]["text"]

    def test_prompt_unknown(self, mcp_server):
        """Test unknown prompt returns error."""
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "prompts/get",
            "params": {"name": "unknown_prompt", "arguments": {}}
        }))

        assert "error" in response


# =============================================================================
# Mock Emulator Tests
# =============================================================================

class TestMockEmulator:
    """Test MockEmulatorInterface."""

    def test_memory_operations(self, mock_emulator):
        """Test memory read/write."""
        data = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        run_async(mock_emulator.write_memory(0x10000000, data))

        read_data = run_async(mock_emulator.read_memory(0x10000000, 8))
        assert read_data == data

    def test_register_operations(self, mock_emulator):
        """Test register read/write."""
        run_async(mock_emulator.write_register("r5", 0xDEADBEEF))
        value = run_async(mock_emulator.read_register("r5"))
        assert value == 0xDEADBEEF

    def test_breakpoint_operations(self, mock_emulator):
        """Test breakpoint set/remove."""
        bp1 = run_async(mock_emulator.set_breakpoint(0x08001000))
        bp2 = run_async(mock_emulator.set_breakpoint(0x08002000))

        bps = run_async(mock_emulator.get_breakpoints())
        assert len(bps) == 2

        run_async(mock_emulator.remove_breakpoint(bp1))
        bps = run_async(mock_emulator.get_breakpoints())
        assert len(bps) == 1

    def test_execution_control(self, mock_emulator):
        """Test halt/continue/step/reset."""
        assert mock_emulator.halted

        run_async(mock_emulator.continue_execution())
        assert not mock_emulator.halted

        run_async(mock_emulator.halt())
        assert mock_emulator.halted

        pc = mock_emulator.registers["pc"]
        run_async(mock_emulator.step(3))
        assert mock_emulator.registers["pc"] == pc + 6

        run_async(mock_emulator.reset())
        assert mock_emulator.registers["pc"] == 0x08000000

    def test_peripheral_operations(self, mock_emulator):
        """Test peripheral read/write."""
        # Write to GPIOA ODR offset
        run_async(mock_emulator.write_peripheral("GPIOA", 0x14, 0xAAAA, 4))
        value = run_async(mock_emulator.read_peripheral("GPIOA", 0x14, 4))
        assert value == 0xAAAA


# =============================================================================
# Tool Parameter Tests
# =============================================================================

class TestMCPToolParameter:
    """Test MCPTool and MCPToolParameter."""

    def test_tool_from_params(self):
        """Test creating tool from parameters."""
        params = [
            MCPToolParameter("address", "integer", "Memory address", required=True),
            MCPToolParameter("size", "integer", "Size in bytes", required=False, default=4),
        ]

        tool = MCPTool.from_params("test_tool", "Test tool description", params)

        assert tool.name == "test_tool"
        assert tool.description == "Test tool description"
        assert tool.inputSchema["type"] == "object"
        assert "address" in tool.inputSchema["properties"]
        assert "size" in tool.inputSchema["properties"]
        assert "address" in tool.inputSchema["required"]
        assert "size" not in tool.inputSchema["required"]

    def test_tool_with_enum(self):
        """Test tool parameter with enum."""
        params = [
            MCPToolParameter("mode", "string", "Operation mode",
                           enum=["read", "write", "readwrite"]),
        ]

        tool = MCPTool.from_params("mode_tool", "Tool with mode", params)

        assert "enum" in tool.inputSchema["properties"]["mode"]
        assert "read" in tool.inputSchema["properties"]["mode"]["enum"]


# =============================================================================
# Factory Function Tests
# =============================================================================

class TestFactory:
    """Test factory functions."""

    def test_create_mcp_server_default(self):
        """Test creating server with default emulator."""
        server = create_mcp_server()
        assert server.emulator is not None
        assert isinstance(server.emulator, MockEmulatorInterface)

    def test_create_mcp_server_custom(self, mock_emulator):
        """Test creating server with custom emulator."""
        server = create_mcp_server(mock_emulator)
        assert server.emulator is mock_emulator


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for MCP server."""

    def test_full_debugging_session(self, mcp_server, mock_emulator):
        """Test a complete debugging session workflow."""
        # 1. Initialize
        run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        }))

        # 2. Load some "firmware" data
        run_async(mock_emulator.write_memory(0x08000000, bytes(range(256))))

        # 3. Read state
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 2, "method": "resources/read",
            "params": {"uri": "mcuemu://state"}
        }))
        assert "result" in response

        # 4. Set breakpoint
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "breakpoint_set", "arguments": {"address": 0x08000100}}
        }))
        assert "result" in response

        # 5. Step a few instructions
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "step", "arguments": {"count": 10}}
        }))
        assert "result" in response

        # 6. Dump registers
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "registers_dump", "arguments": {}}
        }))
        assert "result" in response

        # 7. Dump memory
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "memory_dump", "arguments": {"address": 0x08000000, "size": 64}}
        }))
        assert "result" in response

        # 8. Reset
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": "reset", "arguments": {}}
        }))
        assert mock_emulator.registers["pc"] == 0x08000000

        # 9. Shutdown
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 8, "method": "shutdown"
        }))
        assert not mcp_server.initialized

    def test_memory_search_workflow(self, mcp_server, mock_emulator):
        """Test memory search and analysis workflow."""
        # Write pattern in memory
        pattern = b"\xDE\xAD\xBE\xEF"
        run_async(mock_emulator.write_memory(0x08000100, pattern))
        run_async(mock_emulator.write_memory(0x08000200, pattern))
        run_async(mock_emulator.write_memory(0x08000300, pattern))

        # Search for pattern
        response = run_async(mcp_server.handle_message({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "memory_search",
                "arguments": {
                    "pattern": "DEADBEEF",
                    "start": 0x08000000,
                    "end": 0x08001000
                }
            }
        }))

        assert "result" in response
        content = response["result"]["content"][0]["text"]
        assert "3 matches" in content or "Found" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
