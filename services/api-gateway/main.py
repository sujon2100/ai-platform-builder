import json
import logging
import os
import uuid
from datetime import datetime, timezone
from time import perf_counter

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from kafka import KafkaProducer
from kafka.errors import KafkaError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, validator

import db
from observability.metrics import REQUEST_COUNT, REQUEST_LATENCY

app = FastAPI(title="AI Platform API Gateway")
logger = logging.getLogger(__name__)

API_KEY_ENV_VAR = "AI_PLATFORM_API_KEY"
CHAT_TOPIC = os.getenv("CHAT_TOPIC", "ai-chat-requests")
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

_producer: KafkaProducer | None = None


def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            request_timeout_ms=5000,
        )
    return _producer


@app.on_event("startup")
def on_startup():
    db.init_db()


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

        event = build_chat_event(req, request_id)
        db.create_pending(request_id, req.tenant_id)

        try:
            get_producer().send(CHAT_TOPIC, value=event)
            get_producer().flush(timeout=5)
        except KafkaError as exc:
            db.update_result(request_id, "failed", None, None, f"publish failed: {exc}")
            raise HTTPException(status_code=503, detail="Unable to accept request, try again")

        logger.info(
            "Accepted chat request",
            extra={"tenant_id": req.tenant_id, "request_id": request_id},
        )

        return ChatResponse(request_id=request_id, status="accepted")
    finally:
        REQUEST_COUNT.labels(service="api-gateway").inc()
        REQUEST_LATENCY.labels(service="api-gateway").observe(
            perf_counter() - start_time
        )


@app.get("/chat/{request_id}")
async def get_chat_result(request_id: str, x_api_key: str | None = Header(default=None)):
    verify_api_key(x_api_key)
    result = db.get_result(request_id)
    if result is None:
        raise HTTPException(status_code=404, detail="request_id not found")
    return result


@app.get("/health/live")
async def health_live():
    """Liveness check: process is up, no dependency checks."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready():
    """Readiness check: can this instance actually reach its dependencies."""
    checks = {}
    try:
        get_producer().bootstrap_connected()
        checks["kafka"] = "ok"
    except Exception as exc:
        checks["kafka"] = f"error: {exc}"

    try:
        db.init_db()
        checks["db"] = "ok"
    except Exception as exc:
        checks["db"] = f"error: {exc}"

    healthy = all(v == "ok" for v in checks.values())
    status_code = 200 if healthy else 503
    return Response(
        content=json.dumps({"status": "ok" if healthy else "degraded", "checks": checks}),
        media_type="application/json",
        status_code=status_code,
    )


@app.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
