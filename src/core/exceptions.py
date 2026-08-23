"""
Custom Domain Exceptions for Agentic PowerScaler.
"""

class PowerScalerException(Exception):
    """Base exception for PowerScaler domain."""
    def __init__(self, message: str, code: str = "POWERSCALER_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ParallelAPIError(PowerScalerException):
    """Raised when Parallel API search/extract fails."""
    def __init__(self, endpoint: str, detail: str):
        super().__init__(
            message=f"Parallel API [{endpoint}] failed: {detail}",
            code="PARALLEL_API_ERROR"
        )


class AgentExecutionError(PowerScalerException):
    """Raised when an agent workflow step fails."""
    def __init__(self, agent_name: str, reason: str):
        super().__init__(
            message=f"Agent '{agent_name}' execution error: {reason}",
            code="AGENT_EXECUTION_ERROR"
        )


class GeminiLLMError(PowerScalerException):
    """Raised when Google Gemini API encounters an issue."""
    def __init__(self, detail: str):
        super().__init__(
            message=f"Gemini LLM Error: {detail}",
            code="GEMINI_ERROR"
        )
