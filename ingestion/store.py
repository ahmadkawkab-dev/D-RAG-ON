"""
store.py
========
Shared Weaviate collection helpers used by both `embed_chunks.py` (JSONL
ingestion) and `main.py` (end-to-end PDF ingestion), so the schema
definition and upsert logic live in exactly one place instead of being
copy-pasted across scripts.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Sequence

import weaviate
from weaviate.classes.config import Configure
from weaviate.util import generate_uuid5

logger = logging.getLogger("store")


# Reuse the collection when it exists so ingestion can safely run again.

def get_or_create_collection(client: weaviate.WeaviateClient, name: str):
    """
    Fetches the collection, creating it if it doesn't exist yet.
    No auto-vectorizer is configured -- every caller supplies
    pre-computed EmbeddingGemma vectors directly.
    """
    if not client.collections.exists(name):
        logger.info("Creating Weaviate collection '%s'", name)
        client.collections.create(
            name=name,
            vectorizer_config=Configure.Vectorizer.none(),
        )
    return client.collections.get(name)


# Stable chunk IDs become stable Weaviate object IDs during upserts.

def upload_chunks(
    collection,
    texts: Sequence[str],
    vectors: Sequence[list[float]],
    metadatas: Sequence[dict],
    ids: Optional[Sequence[Optional[str]]] = None,
) -> None:
    """
    Upserts (text, vector, metadata) triples into `collection`.

    `ids` should be stable, deterministic strings (e.g. a chunk_id from
    the parsing pipeline: "<source-stem>-0004") when you want re-ingesting
    the same document to *update* existing objects in place instead of
    duplicating them -- object UUIDs are derived from these via
    generate_uuid5. Pass None (or omit `ids`) to fall back to random
    UUIDs, in which case re-ingestion WILL create duplicates.
    """
    if ids is None:
        ids = [None] * len(texts)

    with collection.batch.dynamic() as batch:
        for text, vector, metadata, chunk_id in zip(texts, vectors, metadatas, ids):
            batch.add_object(
                properties={"text": text, "metadata": json.dumps(metadata)},
                vector=vector,
                uuid=generate_uuid5(chunk_id) if chunk_id is not None else None,
            )