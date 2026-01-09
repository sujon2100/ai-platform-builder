from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, validator
from time import perf_counter
from datetime import datetime, timezone
import uuid
import os
import logging

from services.observability.metrics import REQUEST_COUNT, REQUEST_LATENCY

app = FastAPI(title="AI Platform API Gateway")
logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "AI_PLATFORM_API_KEY"
DEFAULT_KAFKA_TOPIC = "ai-chat-requests"


class ChatRequest(BaseModel):
    tenant_id: str
    message: str

    @validator("tenant_id", "message")
    def non_empty(cls, value: str) -> str:
        """Reject empty or whitespace-only fields before enqueueing work."""
        if not value.strip():
            raise ValueError("must not be empty")
        return value

class ChatResponse(BaseModel):
    request_id: str
    status: str


def build_chat_event(req: ChatRequest, request_id: str) -> dict:
    """Construct the outbound event for downstream workflow processing."""
    return {
        "request_id": request_id,
        "tenant_id": req.tenant_id,
        "message": req.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "event_type": "chat.requested",
    }


def publish_event(event: dict, topic: str = DEFAULT_KAFKA_TOPIC) -> None:
    """Publish the event to Kafka (placeholder implementation)."""
    # TODO: replace with Kafka producer publish.
    logger.info("Published chat event", extra={"topic": topic, "event": event})


def verify_api_key(x_api_key: str | None) -> None:
    """Validate the API key header against the configured secret."""
    expected_key = os.getenv(API_KEY_ENV_VAR)
    if not expected_key:
        # Fail fast on misconfiguration to avoid silently accepting requests.
        raise HTTPException(
            status_code=500,
            detail=f"Missing {API_KEY_ENV_VAR} configuration",
        )

    if x_api_key != expected_key:
        # Avoid exposing which part of the credential was invalid.
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    start_time = perf_counter()
    try:
        verify_api_key(x_api_key)
        request_id = str(uuid.uuid4())

        # In production:
        # 1. Authenticate request
        # 2. Publish event to Kafka
        # 3. Return async acknowledgement

        event = build_chat_event(req, request_id)
        publish_event(event)

        # Emit an audit log to correlate the async workflow with request metadata.
        logger.info(
            "Accepted chat request",
            extra={"tenant_id": req.tenant_id, "request_id": request_id},
        )

        return ChatResponse(
            request_id=request_id,
            status="accepted"
        )
    finally:
        REQUEST_COUNT.labels(service="api-gateway").inc()
        REQUEST_LATENCY.labels(service="api-gateway").observe(
            perf_counter() - start_time
        )
