# Slab MCP

Model Context Protocol (MCP) server for the Slab security analysis framework.

## Features

- **Dynamic Discovery**: Automatically discovers installed Slab packages
- **Tool Registry**: Exposes package capabilities as MCP tools
- **AI Integration**: Works with MCP-compatible AI assistants

## Installation

```bash
# Standalone installation (server only)
pip install slab-mcp

# Full installation with all Slab packages
pip install slab-mcp[full]
```

## Quick Start

```bash
# Start MCP server
slab-mcp-server

# Or run as module
python -m slab_mcp.server
```

## Discovered Tools

The MCP server automatically discovers and exposes tools from installed packages:

- **slab-cortex-m**: Peripheral access, SVD parsing
- **slab-cortex-a**: Cache simulation, TrustZone testing
- **slab-timing**: Cycle timing, power estimation
- **slab-sidechannels**: CPA, DPA, template attacks
- **slab-glitch**: Fault injection, parameter search

## Configuration

```json
{
  "mcpServers": {
    "slab": {
      "command": "slab-mcp-server",
      "args": []
    }
  }
}
```

## Author

Mathieu Renard <mathieu.renard@twistedwires.io>

## License

GPL-2.0-or-later
