## System Overview

Client requests enter via the API Gateway and are published to Kafka for asynchronous
processing. The Workflow Engine consumes events, enriches requests using the RAG
Service, and invokes the LLM Orchestrator to generate responses.

This decoupling allows independent scaling, fault isolation, and cost control.
