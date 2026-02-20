from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "ai_requests_total",
    "Total number of AI requests",
    ["service"]
)

REQUEST_LATENCY = Histogram(
    "ai_request_latency_seconds",
    "Latency per request",
    ["service"]
)

LLM_ERRORS = Counter(
    "llm_errors_total",
    "Total LLM invocation errors",
    ["provider"]
)
