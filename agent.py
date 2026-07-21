"""
rag_agent.py
============
Local retrieval agent: embeds a query with EmbeddingGemma, retrieves
candidate chunks from Weaviate, reranks them with a local Ollama LLM,
and (optionally) synthesizes a grounded answer — all against a local
Ollama server, no cloud calls.

Example:
    python rag_agent.py "How does the batch import work?" --answer
"""

from __future__ import annotations

import argparse
import json
import logging

import weaviate
from weaviate.classes.query import HybridFusion, MetadataQuery
from ollama import Client

from ingestion.embedder import Embedder
from reranker import Reranker

logger = logging.getLogger("agent")


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


def retrieve(
    collection,
    embedder: Embedder,
    query: str,
    top_k: int,
    alpha: float,
    query_vector: list[float] | None = None,
) -> list[dict]:
    """
    Hybrid retrieval: fuses BM25 keyword search over `query`'s literal
    terms with vector similarity search over its EmbeddingGemma
    embedding, so exact terms the user typed (names, IDs, jargon that
    embeddings can blur together) still surface results alongside
    purely semantic matches.

    alpha=0.0 -> pure keyword (BM25), alpha=1.0 -> pure vector, 0.5 -> even split.
    """
    if query_vector is None:
        query_vector = embedder.embed_query(query)
    results = collection.query.hybrid(
        query=query,
        vector=query_vector,
        alpha=alpha,
        limit=top_k,
        fusion_type=HybridFusion.RELATIVE_SCORE,
        return_metadata=MetadataQuery(score=True, explain_score=True),
    )
    parsed_results = []
    
    for obj in results.objects:
        raw_meta = obj.properties.get("metadata")
        
        if isinstance(raw_meta, str):
            try:
                metadata = json.loads(raw_meta)
            except Exception:
                metadata = {}
        else:
            metadata = raw_meta or {}
            
        parsed_results.append({
            "text": obj.properties["text"],
            "metadata": metadata,
            "score": obj.metadata.score,
        })
        
    # Return after every Weaviate result has been converted to a plain dictionary.
    return parsed_results


def synthesize_answer(
    chat_client: Client,
    model: str,
    query: str,
    chunks: list[dict],
    on_token=None,
) -> str:
    """Generate a grounded answer, optionally publishing each token as it arrives."""

    context = "\n\n".join(f"[{i + 1}] {c['text']}" for i, c in enumerate(chunks))
    prompt = (
        "Answer the question using ONLY the numbered context below. "
        "Cite sources inline like [1], [2]. If the answer isn't in the "
        "context, reply exactly: Question irrelevant to the available document context. "
        "Do not use outside knowledge.\n\n"
        f"Context:\n{context}\n\nQuestion: {query}\nAnswer:"
    )
    messages = [{"role": "user", "content": prompt}]
    if on_token is None:
        response = chat_client.chat(model=model, messages=messages)
        return response["message"]["content"]

    parts: list[str] = []
    for event in chat_client.chat(model=model, messages=messages, stream=True):
        token = event["message"]["content"]
        if token:
            parts.append(token)
            on_token(token)
    return "".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="The search query / question")
    parser.add_argument("--collection", default="DocumentChunks", help="Weaviate collection name")
    parser.add_argument("--embed-model", default="embeddinggemma")
    parser.add_argument(
        "--rerank-model",
        default="Qwen/Qwen3-Reranker-0.6B",
        help="Hugging Face model id, loaded locally via transformers (not Ollama)",
    )
    parser.add_argument("--rerank-device", default=None, help="cuda / cpu — defaults to cuda if available")
    parser.add_argument("--answer-model", default="qwen2.5:1.5b", help="Model used for final answer synthesis")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama server URL (embedding + answer models)")
    parser.add_argument("--retrieve-k", type=int, default=20, help="Candidates pulled from Weaviate before reranking")
    parser.add_argument(
        "--alpha", type=float, default=0.5,
        help="Hybrid search balance: 0.0=pure keyword (BM25), 1.0=pure vector, 0.5=even split",
    )
    parser.add_argument("--top-n", type=int, default=5, help="Chunks kept after reranking")
    parser.add_argument("--answer", action="store_true", help="Also synthesize a final grounded answer")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)

    embedder = Embedder(model_name=args.embed_model, host=args.host)
    reranker = Reranker(model_name=args.rerank_model, device=args.rerank_device)

    wv_client = weaviate.connect_to_local()
    try:
        collection = wv_client.collections.get(args.collection)

        candidates = retrieve(collection, embedder, args.query, args.retrieve_k, args.alpha)
        logger.info("Retrieved %d candidates from Weaviate (hybrid, alpha=%.2f)", len(candidates), args.alpha)

        ranked = reranker.rerank(args.query, candidates, top_n=args.top_n)
        logger.info("Reranked down to top %d", len(ranked))

        for i, c in enumerate(ranked, 1):
            print(f"[{i}] rerank_score={c['rerank_score']:.2f}  hybrid_score={c['score']:.4f}")
            print(c["text"][:300].replace("\n", " "))
            print()

        if args.answer:
            chat_client = Client(host=args.host)
            answer = synthesize_answer(chat_client, args.answer_model, args.query, ranked)
            print("=== Answer ===")
            print(answer)
    finally:
        wv_client.close()


if __name__ == "__main__":
    main()