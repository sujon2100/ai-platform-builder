FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/workflow-engine /app/workflow_engine
COPY services/llm-orchestrator /app/llm_orchestrator
COPY services/rag-service /app/rag_service

RUN touch /app/workflow_engine/__init__.py \
    /app/workflow_engine/observability/__init__.py \
    /app/llm_orchestrator/__init__.py \
    /app/rag_service/__init__.py

ENV PYTHONPATH=/app

CMD ["python", "workflow_engine/worker.py"]
