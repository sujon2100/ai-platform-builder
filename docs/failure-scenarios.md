# Failure Scenarios & Handling

## LLM Provider Failure
- Automatic retry with backoff
- Fallback to alternate provider
- Circuit breaker on repeated failures

## Kafka Consumer Failure
- At-least-once processing
- Idempotent handlers
- Poison messages routed to DLQ

## RAG Retrieval Failure
- Graceful degradation to prompt-only generation
- Metrics emitted for retrieval misses
