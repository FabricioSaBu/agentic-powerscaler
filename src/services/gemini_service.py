"""
Google Gemini AI Service Wrapper.
Integrates with the official google-genai SDK, talking to Vertex AI (Google Cloud) when a
project is configured, and falling back to the AI Studio API key for local/offline dev.
"""

from typing import Optional, Dict, Any, Type, TypeVar
from google import genai
from google.genai import errors as genai_errors, types
from pydantic import BaseModel
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from src.core.config import settings
from src.core.logging import logger
from src.core.exceptions import GeminiLLMError

T = TypeVar("T", bound=BaseModel)

# gemini-3.x's thinking control (this app's configured model, GEMINI_MODEL=gemini-3.5-flash-lite):
# "minimal"/"low" for structured extraction/lookup tasks that don't need deliberation, "high"
# only for the one call that actually reasons about a matchup (the Analyst's verdict).
DEFAULT_THINKING_LEVEL = "low"
DEFAULT_MAX_OUTPUT_TOKENS = 4096

# 503 UNAVAILABLE ("high demand") and 429 rate limits are explicitly temporary, and a single
# one otherwise fails a whole matchup run. Retried with backoff; 4xx (bad key, bad request)
# is not retried, since repeating it would never help.
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, genai_errors.APIError) and getattr(exc, "code", None) in _RETRYABLE_CODES


_retry_transient = retry(
    retry=retry_if_exception(_is_transient),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=2, min=2, max=16),
    reraise=True,
)


class GeminiService:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_model
        self.use_vertex = settings.use_vertex_ai
        # Only truly offline when there is neither a GCP project (Vertex AI, uses
        # Application Default Credentials -- no key needed) nor an AI Studio key.
        self._offline = not self.use_vertex and not self.api_key
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if self.use_vertex:
                self._client = genai.Client(
                    vertexai=True,
                    project=settings.google_cloud_project,
                    location=settings.google_cloud_location,
                )
            else:
                if self._offline:
                    logger.warning("No GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY set. Operating in offline/simulated mode.")
                self._client = genai.Client(api_key=self.api_key or "DUMMY_KEY_FOR_INIT")
        return self._client

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        thinking_level: str = DEFAULT_THINKING_LEVEL,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> str:
        """Generates text from Gemini model."""
        if self._offline:
            logger.info("Using simulated Gemini response (no Vertex AI project or API key configured).")
            return f"[Simulated Gemini Output for prompt: {prompt[:80]}...]"

        try:
            config: Dict[str, Any] = {
                "thinking_config": types.ThinkingConfig(thinking_level=thinking_level.upper()),
                "max_output_tokens": max_output_tokens,
            }
            if system_instruction:
                config["system_instruction"] = system_instruction

            @_retry_transient
            def _call():
                return self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )

            response = _call()
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise GeminiLLMError(str(e))

    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: Optional[str] = None,
        thinking_level: str = DEFAULT_THINKING_LEVEL,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> T:
        """Generates a response constrained to response_schema's JSON shape, returning a parsed instance.
        Assumes response_schema's fields all have defaults (e.g. empty lists), since that's what's
        returned in offline/simulated mode when no API key is configured."""
        if self._offline:
            logger.info("Using simulated (empty) structured response (no Vertex AI project or API key configured).")
            return response_schema()

        try:
            config: Dict[str, Any] = {
                "response_mime_type": "application/json",
                "response_schema": response_schema,
                "thinking_config": types.ThinkingConfig(thinking_level=thinking_level.upper()),
                "max_output_tokens": max_output_tokens,
            }
            if system_instruction:
                config["system_instruction"] = system_instruction

            @_retry_transient
            def _call():
                return self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )

            response = _call()
            if response.parsed is not None:
                return response.parsed
            return response_schema.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"Gemini structured output error: {e}")
            raise GeminiLLMError(str(e))
