"""
Domain Models for Agentic Cinema.
Defines cinematic assets: Script, Scene, Shot, Workflow Task, and Production Output.
"""

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Shot(BaseModel):
    shot_number: int
    description: str
    camera_angle: str = Field(default="Wide Shot")
    lighting_notes: str = Field(default="Cinematic Dramatic")
    audio_cue: Optional[str] = None


class Scene(BaseModel):
    scene_number: int
    title: str
    location: str
    time_of_day: str = "DAY"
    summary: str
    shots: List[Shot] = Field(default_factory=list)


class Script(BaseModel):
    title: str
    genre: str
    logline: str
    scenes: List[Scene] = Field(default_factory=list)


class AgentTaskRequest(BaseModel):
    prompt: str = Field(..., description="Prompt or high-level idea for the cinematic production")
    genre: str = Field(default="Sci-Fi Thriller")
    partner_track: Optional[str] = Field(default=None, description="IBM, Grafana, Parallel, ClickHouse, Replit")


class ProductionResult(BaseModel):
    task_id: str
    title: str
    status: WorkflowStatus
    script: Optional[Script] = None
    telemetry_logs: List[str] = Field(default_factory=list)
    partner_metrics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
