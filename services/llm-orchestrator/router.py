import logging

from services.observability.metrics import LLM_ERRORS


logger = logging.getLogger(__name__)

class LLMRouter:
    def __init__(self):
        self.providers = ["openai", "ollama"]

    def _invoke_provider(self, provider: str, prompt: str, context: dict) -> str:
        """Invoke the selected provider (placeholder implementation)."""
        if provider not in self.providers:
            raise ValueError(f"Unsupported provider: {provider}")
        if context.get("force_provider_error"):
            raise RuntimeError("Forced provider error for testing")
        return f"Generated response from {provider}"

    def select_provider(self, context: dict) -> str:
        """
        Select LLM provider based on cost, latency, and availability.
        """
        # Placeholder heuristic
        if context.get("low_cost"):
            return "ollama"
        return "openai"

    def generate(self, prompt: str, context: dict):
        provider = self.select_provider(context)
        try:
            return {
                "provider": provider,
                "response": self._invoke_provider(provider, prompt, context),
            }
        except Exception:
            logger.exception("LLM generation failed", extra={"provider": provider})
            LLM_ERRORS.labels(provider=provider).inc()
            raise
