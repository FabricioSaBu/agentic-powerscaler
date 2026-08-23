"""
Model Context Protocol (MCP) Adapter.
Connects agent pipeline to external MCP tools and servers.
"""

from typing import Dict, Any, Optional
import httpx
from src.core.config import settings
from src.core.logging import logger
from src.models.partner import MCPToolCall, MCPToolResult


class MCPAdapter:
    def __init__(self, server_url: Optional[str] = None):
        self.server_url = server_url or settings.mcp_server_url

    async def execute_tool(self, tool_call: MCPToolCall) -> MCPToolResult:
        logger.info(f"Executing MCP tool call: {tool_call.name}")
        
        if not self.server_url:
            return MCPToolResult(
                tool_name=tool_call.name,
                success=True,
                data={
                    "status": "local_mock_executed",
                    "output": f"Executed MCP tool {tool_call.name}",
                    "args": tool_call.arguments
                }
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.server_url,
                    json={
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments
                        },
                        "id": 1
                    }
                )
                response.raise_for_status()
                res = response.json()
                return MCPToolResult(
                    tool_name=tool_call.name,
                    success=True,
                    data=res.get("result", {})
                )
        except Exception as e:
            logger.error(f"MCP Tool execution error: {e}")
            return MCPToolResult(
                tool_name=tool_call.name,
                success=False,
                error_message=str(e)
            )
