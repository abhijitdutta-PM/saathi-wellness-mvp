"""Pinecone adapter for the approved knowledge library.

Only approved knowledge vectors are stored here. Student messages and transcripts must never be upserted. Tenant content is written to a per-tenant namespace; platform-approved
shared content uses the `global` namespace.
The relational database remains the source of truth and every result is re-authorized
against PostgreSQL before content is returned.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.config import settings

logger = logging.getLogger("saathi.pinecone")


def configured() -> bool:
    return bool(settings.pinecone_api_key and settings.pinecone_index_name)


def query_vectors_enabled() -> bool:
    return configured() and settings.pinecone_query_vectors_enabled


def namespace_for_tenant(tenant_id: str | None) -> str:
    # Never derive the namespace from user-supplied request parameters. Call with the
    # authenticated tenant ID resolved by the application, or None for shared content.
    return "global" if tenant_id is None else f"school-{tenant_id}"


@lru_cache(maxsize=1)
def pinecone_client():
    if not configured():
        raise RuntimeError("Pinecone is not configured; set PINECONE_API_KEY and PINECONE_INDEX_NAME.")
    from pinecone import Pinecone
    return Pinecone(api_key=settings.pinecone_api_key)


@lru_cache(maxsize=1)
def pinecone_index():
    # Uses the index-name resolution API. For SDKs where a host is required, run the
    # setup script, which describes the index and prints the endpoint for diagnosis.
    return pinecone_client().Index(settings.pinecone_index_name)


def upsert_knowledge_vector(item: Any, vector: list[float]) -> None:
    if not configured():
        raise RuntimeError("Pinecone is not configured.")
    if len(vector) != settings.pinecone_dimension:
        raise ValueError(
            f"Embedding dimension {len(vector)} does not match PINECONE_DIMENSION={settings.pinecone_dimension}."
        )
    # Only reviewed knowledge metadata is stored. Student messages and transcripts
    # must never be upserted into Pinecone by this adapter.
    metadata = {
        "knowledge_item_id": item.id,
        "age_band": item.age_band or "all",
        "published": bool(item.published),
        "review_status": item.review_status,
        "content_version": str(item.content_version),
    }
    pinecone_index().upsert(
        namespace=namespace_for_tenant(item.tenant_id),
        vectors=[{"id": item.id, "values": vector, "metadata": metadata}],
    )


def query_knowledge_vectors(vector: list[float], tenant_id: str, age_band: str | None, top_k: int = 6) -> list[tuple[str, float]]:
    if not query_vectors_enabled():
        return []
    if len(vector) != settings.pinecone_dimension:
        raise ValueError(
            f"Query embedding dimension {len(vector)} does not match PINECONE_DIMENSION={settings.pinecone_dimension}."
        )
    index = pinecone_index()
    allowed_ages = list(dict.fromkeys([age_band or "all", "all"]))
    metadata_filter = {
        "$and": [
            {"age_band": {"$in": allowed_ages}},
            {"published": {"$eq": True}},
            {"review_status": {"$eq": "approved"}},
        ]
    }
    scored: dict[str, float] = {}
    # Separate namespaces stop ordinary queries from mixing school-owned content.
    # The database authorization check below remains mandatory in either case.
    for namespace in (namespace_for_tenant(tenant_id), namespace_for_tenant(None)):
        response = index.query(
            namespace=namespace,
            vector=vector,
            top_k=top_k,
            include_metadata=True,
            filter=metadata_filter,
        )
        matches = getattr(response, "matches", None)
        if matches is None and isinstance(response, dict):
            matches = response.get("matches", [])
        for match in matches or []:
            if isinstance(match, dict):
                item_id = match.get("id")
                score = match.get("score", 0.0)
            else:
                item_id = getattr(match, "id", None)
                score = getattr(match, "score", 0.0)
            if item_id:
                scored[str(item_id)] = max(float(score or 0.0), scored.get(str(item_id), float("-inf")))
    return sorted(scored.items(), key=lambda pair: pair[1], reverse=True)[:top_k]


def describe_index() -> dict[str, Any]:
    if not configured():
        return {"configured": False, "index_name": settings.pinecone_index_name}
    description = pinecone_client().describe_index(settings.pinecone_index_name)
    if isinstance(description, dict):
        status = description.get("status", {})
        host = description.get("host")
        dimension = description.get("dimension")
    else:
        status = getattr(description, "status", {})
        host = getattr(description, "host", None)
        dimension = getattr(description, "dimension", None)
    ready = status.get("ready") if isinstance(status, dict) else getattr(status, "ready", None)
    return {"configured": True, "index_name": settings.pinecone_index_name,
            "host": host, "dimension": dimension, "ready": ready}
