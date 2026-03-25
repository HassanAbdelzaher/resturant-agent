"""
MCP Manager — Manages multiple MCP server connections from config.

Reads mcp_config.json and launches/connects to all enabled MCP servers.
Provides a unified interface to query tools across all servers.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from app.mcp_client import MCPClient

logger = logging.getLogger(__name__)


class MCPManager:
    """
    Manages multiple MCP server connections.

    Reads from mcp_config.json and maintains a pool of MCPClient instances,
    one per configured server. Provides a unified tool-calling interface.
    """

    def __init__(self, config_path: str = "mcp_servers/mcp_config.json"):
        self.config_path = config_path
        self.clients: dict[str, MCPClient] = {}  # name → client
        self.tool_map: dict[str, str] = {}        # tool_name → server_name
        self.config: dict = {}

    async def initialize(self):
        """Load config and connect to all enabled MCP servers."""
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.warning(f"MCP config not found: {self.config_path}")
            return

        with open(config_file) as f:
            self.config = json.load(f)

        servers = self.config.get("mcpServers", {})

        for name, cfg in servers.items():
            if not cfg.get("enabled", True):
                logger.info(f"MCP server '{name}' is disabled, skipping")
                continue

            try:
                client = MCPClient()
                command = cfg["command"]
                # Resolve "python" / "python3" to the running venv's interpreter
                # so MCP servers always use the same packages as the main app.
                if command in ("python", "python3"):
                    command = sys.executable
                args = cfg.get("args", [])
                env = cfg.get("env")

                await client.connect_stdio(
                    server_command=command,
                    server_args=args,
                    env=env,
                )

                # Cache this server's tools
                tools = await client.list_tools()
                for tool in tools:
                    self.tool_map[tool["name"]] = name

                self.clients[name] = client
                logger.info(
                    f"✅ MCP '{name}' connected — {len(tools)} tools: "
                    f"{', '.join(t['name'] for t in tools)}"
                )

            except BaseException as e:
                logger.error(f"❌ MCP '{name}' failed to connect: {e}")

    async def shutdown(self):
        """Disconnect all MCP servers."""
        for name, client in self.clients.items():
            try:
                await client.disconnect()
                logger.info(f"Disconnected MCP server: {name}")
            except Exception as e:
                logger.error(f"Error disconnecting {name}: {e}")
        self.clients.clear()
        self.tool_map.clear()

    # ── Unified Tool Interface ────────────────────────────────────
    def list_all_tools(self) -> list[dict]:
        """List all tools from all connected MCP servers."""
        all_tools = []
        for name, client in self.clients.items():
            for tool in client._tools_cache:
                all_tools.append({**tool, "_server": name})
        return all_tools

    async def call_tool(self, tool_name: str, arguments: dict = None) -> str:
        """Call a tool by name, routing to the correct MCP server."""
        server_name = self.tool_map.get(tool_name)
        if not server_name:
            raise ValueError(
                f"Tool '{tool_name}' not found. Available: {list(self.tool_map.keys())}"
            )

        client = self.clients[server_name]
        return await client.call_tool(tool_name, arguments)

    async def read_resource(self, server_name: str, uri: str) -> str:
        """Read a resource from a specific MCP server."""
        client = self.clients.get(server_name)
        if not client:
            raise ValueError(f"Server '{server_name}' not connected")
        return await client.read_resource(uri)

    # ── Status ────────────────────────────────────────────────────
    def get_status(self) -> dict:
        """Get connection status for all servers."""
        return {
            name: {
                "connected": client.connected,
                "tools": len(client._tools_cache),
                "tool_names": [t["name"] for t in client._tools_cache],
            }
            for name, client in self.clients.items()
        }

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self.clients.values() if c.connected)

    @property
    def total_tools(self) -> int:
        return len(self.tool_map)
