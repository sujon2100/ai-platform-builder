import json
import logging
import os
import sys

from kafka import KafkaConsumer, KafkaProducer

sys.path.insert(0, "/app")

from llm_orchestrator.router import LLMRouter  # noqa: E402
from rag_service.retrieval import retrieve_context  # noqa: E402
from workflow_engine import db  # noqa: E402
from workflow_engine.kafka_consumer import handle_event  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
CHAT_TOPIC = os.getenv("CHAT_TOPIC", "ai-chat-requests")
DLQ_TOPIC = os.getenv("DLQ_TOPIC", "ai-chat-dlq")
CONSUMER_GROUP = os.getenv("CONSUMER_GROUP", "workflow-engine")


def save_result(request_id, status, provider, response, error):
    db.update_result(request_id=request_id, status=status, provider=provider, response=response, error=error)


def main():
    db.init_db()

    consumer = KafkaConsumer(
        CHAT_TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        auto_offset_reset="earliest",
        # Manual commits: with retries, a single message can legitimately
        # take several minutes (each attempt up to OLLAMA_TIMEOUT_SECONDS,
        # up to MAX_RETRIES attempts). Auto-commit runs on its own timer in
        # the background and is just as vulnerable to CPU starvation as
        # anything else - if it misses a beat mid-processing, the group
        # rebalances against a stale offset and re-processes a whole batch
        # of messages that already completed. Committing explicitly right
        # after a message is actually done avoids that regardless of what
        # else is happening on the machine. See docs/monitoring_log.md
        # 2026-07-24 for the incident that surfaced this.
        enable_auto_commit=False,
        # Worst case for one message: MAX_RETRIES(3) attempts, each up to
        # MAX_ATTEMPTS(2) x OLLAMA_TIMEOUT_SECONDS(220s) = 440s, plus
        # backoff between retries - close to 22 minutes. The 5 minute
        # default here would make Kafka assume the consumer is dead and
        # force a rebalance mid-retry, which is likely the dominant cause
        # of the group instability, independent of actual CPU pressure.
        max_poll_interval_ms=1800000,
    )
    dlq_producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    router = LLMRouter()

    logger.info("Warming up LLM provider before serving traffic")
    warm_up_result = router.generate("ping", {})
    logger.info("Warm-up result: %s", warm_up_result["status"])

    logger.info("Workflow engine started, listening on topic %s", CHAT_TOPIC)
    for message in consumer:
        event = message.value
        try:
            handle_event(event, router, retrieve_context, save_result, dlq_producer, DLQ_TOPIC)
        except Exception:
            logger.error("Unhandled error processing event", exc_info=True)
        finally:
            # Commit only after the message is fully handled (including
            # handle_event's own internal retries/DLQ routing), not on a
            # background timer. See the comment on enable_auto_commit above.
            try:
                consumer.commit()
            except Exception:
                logger.error("Offset commit failed", exc_info=True)


if __name__ == "__main__":
    main()
