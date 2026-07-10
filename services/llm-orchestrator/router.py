import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
MAX_ATTEMPTS = 2
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_RESET_SECONDS = 30


class LLMRouter:
    """
    Routes generation requests to available LLM providers.

    Only Ollama is wired up right now - self-hosted, no per-request cost.
    select_provider() still exists as a seam for adding OpenAI back in
    later, but there's only one real backend at the moment.
    """

    def __init__(self):
        self.providers = ["ollama"]
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0

    def select_provider(self, context: dict) -> str:
        return "ollama"

    def _circuit_is_open(self) -> bool:
        return time.monotonic() < self._circuit_open_until

    def generate(self, prompt: str, context: dict | None = None) -> dict:
        provider = self.select_provider(context or {})

        if self._circuit_is_open():
            logger.warning("Circuit open for %s; skipping call", provider)
            return {"provider": provider, "response": None, "status": "circuit_open"}

        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = httpx.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                resp.raise_for_status()
                data = resp.json()
                self._consecutive_failures = 0
                return {
                    "provider": provider,
                    "response": data.get("response", ""),
                    "status": "ok",
                }
            except Exception as exc:
                last_error = exc
                logger.warning("Ollama call failed (attempt %s/%s): %s", attempt, MAX_ATTEMPTS, exc)

        self._consecutive_failures += 1
        if self._consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            self._circuit_open_until = time.monotonic() + CIRCUIT_RESET_SECONDS
            logger.error("Circuit breaker opened for %s for %ss", provider, CIRCUIT_RESET_SECONDS)

        return {
            "provider": provider,
            "response": None,
            "status": "unavailable",
            "error": str(last_error),
        }
