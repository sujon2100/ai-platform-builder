def process_message(event: dict):
    """
    Process async AI workflow events.
    """
    try:
        # Call RAG
        # Call LLM Orchestrator
        # Persist result
        pass
    except Exception as e:
        # Retry / send to DLQ
        raise e
