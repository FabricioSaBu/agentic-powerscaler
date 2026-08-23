"""
Base Agent Interface for PowerScaler Agents.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.gemini_service import GeminiService
from src.core.logging import logger


class BaseAgent(ABC):
    def __init__(self, name: str, role: str, gemini_service: GeminiService):
        self.name = name
        self.role = role
        self.gemini_service = gemini_service

    @abstractmethod
    async def process(self, context: Dict[str, Any], session: AsyncSession) -> Dict[str, Any]:
        """Executes agent-specific logic given the shared workflow context and DB session."""
        pass

    def log(self, message: str):
        logger.info(f"[{self.name} | {self.role}] {message}")
