import logging
import time
from time import perf_counter

from .observability.metrics import REQUEST_COUNT, REQUEST_LATENCY, LLM_ERRORS

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
MAX_BACKOFF_SECONDS = 30

logger = logging.getLogger(__name__)


def process_message(event: dict, router, retrieve_context_fn, save_result_fn) -> None:
    """
    Core async workflow processor: enrich with RAG, invoke the LLM
    orchestrator, persist the result.
    """
    tenant_id = event.get("tenant_id")
    message = event.get("message")
    request_id = event.get("request_id")
    if not tenant_id or not message:
        raise ValueError("event must include tenant_id and message")

    logger.info("Processing event", extra={"request_id": request_id})

    start_time = perf_counter()
    try:
        retrieved = retrieve_context_fn(message, tenant_id)

        prompt = message
        if retrieved:
            context_text = "\n".join(doc["content"] for doc in retrieved)
            prompt = f"Context:\n{context_text}\n\nQuestion: {message}"

        result = router.generate(prompt, {"tenant_id": tenant_id})

        if result["status"] != "ok":
            LLM_ERRORS.labels(provider=result["provider"]).inc()

        save_result_fn(
            request_id=request_id,
            status="completed" if result["status"] == "ok" else "failed",
            provider=result["provider"],
            response=result.get("response"),
            error=result.get("error"),
        )

        logger.info(
            "Persisted result",
            extra={"request_id": request_id, "provider": result.get("provider"), "status": result["status"]},
        )

        if result["status"] != "ok":
            raise RuntimeError(f"LLM generation failed: {result.get('error') or result['status']}")
    finally:
        REQUEST_COUNT.labels(service="workflow-engine").inc()
        REQUEST_LATENCY.labels(service="workflow-engine").observe(
            perf_counter() - start_time
        )


def handle_event(event: dict, router, retrieve_context_fn, save_result_fn, dlq_producer=None, dlq_topic: str = "ai-chat-dlq") -> None:
    retries = event.get("retries", 0)

    try:
        process_message(event, router, retrieve_context_fn, save_result_fn)
        logger.info("Event processed successfully", extra={"request_id": event.get("request_id")})

    except Exception:
        logger.error(
            "Processing failed",
            extra={"request_id": event.get("request_id")},
            exc_info=True,
        )

        if retries < MAX_RETRIES:
            event["retries"] = retries + 1
            backoff = calculate_backoff(retries)
            logger.info(
                "Retrying event",
                extra={
                    "request_id": event.get("request_id"),
                    "attempt": event["retries"],
                    "backoff_seconds": backoff,
                },
            )
            time.sleep(backoff)
            handle_event(event, router, retrieve_context_fn, save_result_fn, dlq_producer, dlq_topic)
        else:
            send_to_dlq(event, dlq_producer, dlq_topic)


def send_to_dlq(event: dict, dlq_producer, dlq_topic: str) -> None:
    logger.critical(
        "Sending event to DLQ",
        extra={"request_id": event.get("request_id"), "event": event},
    )
    if dlq_producer is not None:
        try:
            dlq_producer.send(dlq_topic, value=event).get(timeout=5)
        except Exception:
            logger.critical(
                "DLQ publish itself failed - event is now unrecorded",
                extra={"request_id": event.get("request_id")},
                exc_info=True,
            )


def calculate_backoff(retries: int) -> int:
    return min(MAX_BACKOFF_SECONDS, RETRY_BACKOFF_SECONDS ** retries)
