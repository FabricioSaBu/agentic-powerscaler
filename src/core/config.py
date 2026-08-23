"""
Core Application Configuration for Agentic PowerScaler
Uses pydantic-settings for type-safe environment configuration.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Agentic PowerScaler - Cinematic Battle Engine"
    version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True
    
    # Server settings
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    
    # Google Gemini AI Settings
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    
    # Parallel API Track Configuration (https://docs.parallel.ai/)
    partner_track: str = "parallel"
    parallel_api_key: Optional[str] = None
    parallel_search_url: str = "https://api.parallel.ai/v1/search"
    parallel_extract_url: str = "https://api.parallel.ai/v1/extract"
    parallel_task_url: str = "https://api.parallel.ai/v1/tasks"
    
    # MCP (Model Context Protocol) Integration
    mcp_server_url: Optional[str] = None

    # Database (SQLite via async SQLAlchemy)
    database_url: str = "sqlite+aiosqlite:///./powerscaler.db"

    # LangSmith Observability (traces latency, tokens, and cost per run)
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "agentic-powerscaler"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()

if settings.langsmith_api_key:
    # LangSmith/LangGraph read these from the process environment directly, not from
    # this Settings object, so they have to be copied across explicitly.
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
