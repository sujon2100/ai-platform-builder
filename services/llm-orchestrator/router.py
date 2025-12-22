class LLMRouter:
    def __init__(self):
        self.providers = ["openai", "ollama"]

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
        return {
            "provider": provider,
            "response": f"Generated response from {provider}"
        }
