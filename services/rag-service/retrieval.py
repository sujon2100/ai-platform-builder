import json
import logging
import os
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

_CORPUS_PATH = Path(os.getenv("RAG_CORPUS_PATH", Path(__file__).parent / "corpus.json"))


def _load_corpus() -> list[dict]:
    if not _CORPUS_PATH.exists():
        logger.warning("RAG corpus not found at %s", _CORPUS_PATH)
        return []
    with open(_CORPUS_PATH) as f:
        return json.load(f)


_CORPUS = _load_corpus()


def retrieve_context(query: str, tenant_id: str, top_k: int = 2) -> list[dict]:
    """
    Retrieve relevant documents using local TF-IDF cosine-similarity search.

    Stands in for the Pinecone-backed retrieval described in the README -
    real similarity search over sparse vectors, just no external index or
    account to manage.
    """
    tenant_docs = [d for d in _CORPUS if d.get("tenant_id") in (tenant_id, "shared")]
    if not tenant_docs or not query.strip():
        logger.info("No corpus/query available", extra={"tenant_id": tenant_id})
        return []

    contents = [d["content"] for d in tenant_docs]
    vectorizer = TfidfVectorizer().fit(contents + [query])
    doc_vectors = vectorizer.transform(contents)
    query_vector = vectorizer.transform([query])
    scores = cosine_similarity(query_vector, doc_vectors)[0]

    ranked = sorted(zip(tenant_docs, scores), key=lambda pair: pair[1], reverse=True)
    return [
        {"doc_id": doc["doc_id"], "content": doc["content"], "score": float(score)}
        for doc, score in ranked[:top_k]
        if score > 0
    ]
