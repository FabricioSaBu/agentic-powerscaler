"""
Core Application Configuration for Agentic PowerScaler
Uses pydantic-settings for type-safe environment configuration.
"""

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

    # Google Gemini AI Settings. Vertex AI is used when google_cloud_project is set
    # (hackathon-compliant Google Cloud path); gemini_api_key is the AI Studio fallback
    # for local/offline development without a GCP project configured.
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-2.5-flash"
    google_cloud_project: Optional[str] = None
    # "global" (not a region) is required for current-generation Gemini 3.x models on
    # Vertex AI -- a regional endpoint like us-central1 404s even though the model exists.
    google_cloud_location: str = "global"

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def use_vertex_ai(self) -> bool:
        return bool(self.google_cloud_project)


settings = Settings()
