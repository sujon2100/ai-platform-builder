import time
import json
import logging

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2

logger = logging.getLogger(__name__)

def process_message(event: dict):
    """
    Core async workflow processor.
    """
    # 1. Enrich with RAG
    # 2. Invoke LLM
    # 3. Persist result
    logger.info(f"Processing event: {event}")


def handle_event(event: dict):
    retries = event.get("retries", 0)

    try:
        process_message(event)
        logger.info("Event processed successfully")

    except Exception as e:
        logger.error(f"Processing failed: {e}")

        if retries < MAX_RETRIES:
            event["retries"] = retries + 1
            time.sleep(RETRY_BACKOFF_SECONDS ** retries)

            logger.info(f"Retrying event, attempt {event['retries']}")
            handle_event(event)
        else:
            send_to_dlq(event)


def send_to_dlq(event: dict):
    """
    Dead Letter Queue handler.
    """
    logger.critical(f"Sending event to DLQ: {json.dumps(event)}")
    # In production: publish to Kafka DLQ topic
