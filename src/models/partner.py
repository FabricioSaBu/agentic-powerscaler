"""
Models for Partner Track Integrations & MCP Protocol Data.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class MCPToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class MCPToolResult(BaseModel):
    tool_name: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


class PartnerTelemetryPayload(BaseModel):
    track: str = Field(..., description="ClickHouse, Grafana, IBM, Parallel, Replit")
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str
