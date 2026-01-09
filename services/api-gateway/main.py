from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from time import perf_counter
import uuid
import os

from services.observability.metrics import REQUEST_COUNT, REQUEST_LATENCY

app = FastAPI(title="AI Platform API Gateway")

API_KEY_ENV_VAR = "AI_PLATFORM_API_KEY"


class ChatRequest(BaseModel):
    tenant_id: str
    message: str

class ChatResponse(BaseModel):
    request_id: str
    status: str


def verify_api_key(x_api_key: str | None) -> None:
    """Validate the API key header against the configured secret."""
    expected_key = os.getenv(API_KEY_ENV_VAR)
    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail=f"Missing {API_KEY_ENV_VAR} configuration",
        )

    if x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, x_api_key: str | None = Header(default=None)):
    verify_api_key(x_api_key)
    start_time = perf_counter()
    request_id = str(uuid.uuid4())

    # In production:
    # 1. Authenticate request
    # 2. Publish event to Kafka
    # 3. Return async acknowledgement

    REQUEST_COUNT.labels(service="api-gateway").inc()
    REQUEST_LATENCY.labels(service="api-gateway").observe(
        perf_counter() - start_time
    )

    return ChatResponse(
        request_id=request_id,
        status="accepted"
    )
