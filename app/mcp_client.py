"""
MCP (Model Context Protocol) Client — Connect to any MCP server for data.

MCP allows standardized access to external data sources:
  - Resources: Load context data (CRM records, order history, etc.)
  - Tools: Execute actions (run queries, trigger workflows)
  - Prompts: Reusable templates for consistent responses

This module wraps the official MCP Python SDK to provide a clean interface
for the WhatsApp agent to call MCP tools.
"""

import logging
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.sse import sse_client

from app.config import settings

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Manages connections to MCP servers and provides tool/resource access.

    Usage:
        client = MCPClient()
        await client.connect(server_command="python", server_args=["my_mcp_server.py"])

        # List available tools
        tools = await client.list_tools()

        # Call a tool
        result = await client.call_tool("search_database", {"query": "customer info"})

        # Read a resource
        data = await client.read_resource("customer://123")
    """

    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.connected = False
        self._tools_cache: list[dict] = []

    # ── Connection ────────────────────────────────────────────────
    async def connect_stdio(
        self,
        server_command: str = "python",
        server_args: list[str] = None,
        env: dict = None,
    ):
        """
        Connect to an MCP server via stdio transport.

        Example:
            await client.connect_stdio("python", ["my_server.py"])
            await client.connect_stdio("node", ["dist/server.js"])
        """
        server_params = StdioServerParameters(
            command=server_command,
            args=server_args or [],
            env=env,
        )

        self._stdio_cm = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_cm.__aenter__()

        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()
        await self.session.initialize()

        self.connected = True
        logger.info(f"Connected to MCP server via stdio: {server_command}")

    async def connect_sse(self, url: str = None):
        """
        Connect to an MCP server via SSE (Server-Sent Events) transport.

        Example:
            await client.connect_sse("http://localhost:3000/sse")
        """
        url = url or settings.mcp_server_url

        self._sse_cm = sse_client(url)
        read_stream, write_stream = await self._sse_cm.__aenter__()

        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()
        await self.session.initialize()

        self.connected = True
        logger.info(f"Connected to MCP server via SSE: {url}")

    async def disconnect(self):
        """Disconnect from the MCP server."""
        if self.session:
            await self.session.__aexit__(None, None, None)
        if hasattr(self, "_stdio_cm"):
            await self._stdio_cm.__aexit__(None, None, None)
        if hasattr(self, "_sse_cm"):
            await self._sse_cm.__aexit__(None, None, None)
        self.connected = False
        logger.info("Disconnected from MCP server")

    # ── Tools ─────────────────────────────────────────────────────
    async def list_tools(self) -> list[dict]:
        """List all tools available from the MCP server."""
        if not self.session:
            return []

        result = await self.session.list_tools()
        self._tools_cache = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in result.tools
        ]
        return self._tools_cache

    async def call_tool(self, tool_name: str, arguments: dict = None) -> Any:
        """
        Call an MCP tool by name with arguments.

        Example:
            result = await client.call_tool("query_database", {
                "sql": "SELECT * FROM orders WHERE status = 'pending'"
            })
        """
        if not self.session:
            raise ConnectionError("Not connected to MCP server")

        result = await self.session.call_tool(tool_name, arguments or {})

        # Extract text content from the result
        text_parts = []
        for content_block in result.content:
            if hasattr(content_block, "text"):
                text_parts.append(content_block.text)

        return "\n".join(text_parts) if text_parts else str(result)

    # ── Resources ─────────────────────────────────────────────────
    async def list_resources(self) -> list[dict]:
        """List all resources available from the MCP server."""
        if not self.session:
            return []

        result = await self.session.list_resources()
        return [
            {
                "uri": str(resource.uri),
                "name": resource.name or "",
                "description": resource.description or "",
                "mime_type": resource.mimeType or "",
            }
            for resource in result.resources
        ]

    async def read_resource(self, uri: str) -> str:
        """
        Read a resource by URI.

        Example:
            data = await client.read_resource("customer://12345")
            data = await client.read_resource("file:///path/to/data.json")
        """
        if not self.session:
            raise ConnectionError("Not connected to MCP server")

        result = await self.session.read_resource(uri)

        text_parts = []
        for content_block in result.contents:
            if hasattr(content_block, "text"):
                text_parts.append(content_block.text)

        return "\n".join(text_parts)

    # ── Prompts ───────────────────────────────────────────────────
    async def list_prompts(self) -> list[dict]:
        """List available prompt templates from the MCP server."""
        if not self.session:
            return []

        result = await self.session.list_prompts()
        return [
            {
                "name": prompt.name,
                "description": prompt.description or "",
                "arguments": [
                    {"name": arg.name, "required": arg.required}
                    for arg in (prompt.arguments or [])
                ],
            }
            for prompt in result.prompts
        ]

    async def get_prompt(self, name: str, arguments: dict = None) -> str:
        """Get a rendered prompt template."""
        if not self.session:
            raise ConnectionError("Not connected to MCP server")

        result = await self.session.get_prompt(name, arguments or {})

        text_parts = []
        for message in result.messages:
            if hasattr(message.content, "text"):
                text_parts.append(message.content.text)

        return "\n".join(text_parts)

    # ── Helper: Get tools as LangChain-compatible format ──────────
    def get_tools_for_langchain(self) -> list[dict]:
        """
        Convert MCP tools to LangChain tool format for agent integration.
        Call list_tools() first to populate the cache.
        """
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }
            for tool in self._tools_cache
        ]
