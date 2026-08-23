"""
Google Gemini AI Service Wrapper.
Integrates with official google-genai SDK.
"""

from typing import Optional, Dict, Any, Type, TypeVar
from google import genai
from langsmith.wrappers import wrap_gemini
from pydantic import BaseModel
from src.core.config import settings
from src.core.logging import logger
from src.core.exceptions import GeminiLLMError

T = TypeVar("T", bound=BaseModel)


class GeminiService:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.api_key:
                logger.warning("GEMINI_API_KEY is not set. Operating in offline/simulated mode.")
            self._client = genai.Client(api_key=self.api_key or "DUMMY_KEY_FOR_INIT")
            if settings.langsmith_api_key:
                # Auto-traces every call with real latency + token usage, so LangSmith can
                # compute cost per run -- without this, calls are invisible to LangSmith
                # since they go through the raw SDK, not a LangChain chat model wrapper.
                self._client = wrap_gemini(self._client)
        return self._client

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generates text from Gemini model."""
        if not self.api_key:
            logger.info("Using simulated Gemini response (GEMINI_API_KEY unset).")
            return f"[Simulated Gemini Output for prompt: {prompt[:80]}...]"

        try:
            config: Dict[str, Any] = {}
            if system_instruction:
                config["system_instruction"] = system_instruction

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config if config else None
            )
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise GeminiLLMError(str(e))

    async def generate_structured(
        self, prompt: str, response_schema: Type[T], system_instruction: Optional[str] = None
    ) -> T:
        """Generates a response constrained to response_schema's JSON shape, returning a parsed instance.
        Assumes response_schema's fields all have defaults (e.g. empty lists), since that's what's
        returned in offline/simulated mode when no API key is configured."""
        if not self.api_key:
            logger.info("Using simulated (empty) structured response (GEMINI_API_KEY unset).")
            return response_schema()

        try:
            config: Dict[str, Any] = {"response_mime_type": "application/json", "response_schema": response_schema}
            if system_instruction:
                config["system_instruction"] = system_instruction

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=config,
            )
            if response.parsed is not None:
                return response.parsed
            return response_schema.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"Gemini structured output error: {e}")
            raise GeminiLLMError(str(e))
