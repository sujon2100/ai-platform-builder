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
        enable_auto_commit=True,
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


if __name__ == "__main__":
    main()
