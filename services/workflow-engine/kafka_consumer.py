import time
import json
import logging
from time import perf_counter

from services.observability.metrics import REQUEST_COUNT, REQUEST_LATENCY

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 30

logger = logging.getLogger(__name__)


def retrieve_context(message: str, tenant_id: str) -> list[dict]:
    """
    Fetch context from the RAG service (placeholder).
    """
    logger.info(
        "Retrieving context",
        extra={"tenant_id": tenant_id, "message_length": len(message or "")},
    )
    return []


def generate_response(message: str, context: list[dict]) -> dict:
    """
    Invoke the LLM orchestrator (placeholder).
    """
    logger.info("Invoking LLM", extra={"context_size": len(context)})
    return {"provider": "openai", "response": "placeholder"}


def persist_result(request_id: str | None, response: dict) -> None:
    """
    Persist LLM response output (placeholder).
    """
    logger.info(
        "Persisting result",
        extra={"request_id": request_id, "provider": response.get("provider")},
    )

def process_message(event: dict):
    """
    Core async workflow processor.
    """
    tenant_id = event.get("tenant_id")
    message = event.get("message")
    if not tenant_id or not message:
        raise ValueError("event must include tenant_id and message")
    logger.info("Processing event", extra={"request_id": event.get("request_id")})

    start_time = perf_counter()
    try:
        # 1. Enrich with RAG
        retrieved = retrieve_context(message, tenant_id)

        # 2. Invoke LLM
        response = generate_response(message, retrieved)

        # 3. Persist result (placeholder)
        persist_result(event.get("request_id"), response)
    finally:
        REQUEST_COUNT.labels(service="workflow-engine").inc()
        REQUEST_LATENCY.labels(service="workflow-engine").observe(
            perf_counter() - start_time
        )


def handle_event(event: dict):
    retries = event.get("retries", 0)

    try:
        process_message(event)
        logger.info("Event processed successfully")

    except Exception as e:
        logger.error(
            "Processing failed",
            extra={"request_id": event.get("request_id")},
            exc_info=True,
        )

        if retries < MAX_RETRIES:
            event["retries"] = retries + 1
            time.sleep(calculate_backoff(retries))

            logger.info(
                "Retrying event",
                extra={
                    "request_id": event.get("request_id"),
                    "attempt": event["retries"],
                    "backoff_seconds": calculate_backoff(retries),
                },
            )
            handle_event(event)
        else:
            send_to_dlq(event)


def send_to_dlq(event: dict):
    """
    Dead Letter Queue handler.
    """
    logger.critical(
        "Sending event to DLQ",
        extra={"request_id": event.get("request_id"), "event": event},
    )
    # In production: publish to Kafka DLQ topic


def calculate_backoff(retries: int) -> int:
    """
    Calculate exponential backoff for retry attempts with a hard cap.
    """
    return min(MAX_BACKOFF_SECONDS, RETRY_BACKOFF_SECONDS ** retries)
