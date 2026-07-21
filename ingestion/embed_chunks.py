from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import weaviate
from embedder import Embedder
from store import get_or_create_collection, upload_chunks

logger = logging.getLogger("embed_chunks")

# Keep CLI logs readable during long embedding runs.

def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

# Load canonical JSONL chunks before creating embeddings.

def load_chunks(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line: continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed line %d: %s", line_number, exc)
                continue
            if "text" not in record:
                logger.warning("Skipping line %d: no 'text' field.", line_number)
                continue
            records.append(record)
    return records

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks_path", type=Path, help="Path to chunks.jsonl")
    parser.add_argument("--collection", default="DocumentChunks", help="Weaviate collection name")
    parser.add_argument("--model-name", default="embeddinggemma", help="Ollama embedding model tag")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    if not args.chunks_path.exists():
        raise SystemExit(f"No such file: {args.chunks_path}")

    records = load_chunks(args.chunks_path)
    if not records:
        logger.warning("No valid chunks found in %s -- nothing to do.", args.chunks_path)
        return

    embedder = Embedder(model_name=args.model_name, host=args.host)
    texts = [r["text"] for r in records]
    embeddings = embedder.embed_passages(texts, batch_size=args.batch_size)

    
    metadatas = [r.get("metadata", r) for r in records]
    ids = [m.get("chunk_id") if isinstance(m, dict) else None for m in metadatas]

    client = weaviate.connect_to_local()
    try:
        collection = get_or_create_collection(client, args.collection)
        upload_chunks(collection, texts, embeddings, metadatas, ids=ids)
        logger.info("Done. Embedded %d chunks and upserted into Weaviate collection '%s'.",
                    len(records), args.collection)
    finally:
        client.close()

if __name__ == "__main__":
    main()