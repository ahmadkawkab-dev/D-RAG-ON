"""
main.py
=======
End-to-end CLI for the local RAG pipeline:

    parse.py            PDF -> layout-aware, semantically-chunked text
        |
        v
    embedder.py          chunk text -> EmbeddingGemma vectors (via Ollama)
    store.py              vectors + metadata -> Weaviate (upsert)
        |
        v
    rag_agent.py          query -> hybrid (BM25 + vector) retrieve
    reranker.py            -> Qwen3-Reranker rerank (via transformers)
                            -> optional grounded answer (via Ollama)
        |
        v
    eval.py                labeled eval_dataset.jsonl -> retrieval / rerank /
                            answer metrics, against the same functions above

Subcommands:
    main.py ingest <pdf_or_dir> [options]   parse + chunk + embed + upload
    main.py query  "<question>" [options]   retrieve + rerank + (optionally) answer
    main.py eval   <eval_dataset.jsonl>     score retrieval / rerank / answer stages

Everything past PDF parsing runs against local services only -- Ollama
for embeddings/answers, Hugging Face transformers for reranking, Weaviate
for storage. No cloud calls.

NOTE: The query and eval commands run models in strict sequential phases so
that only one model occupies CPU/RAM at a time:
    Phase 1: Embedder (Ollama)   -- retrieve
    Phase 2: Reranker (HF)       -- rerank
    Phase 3: Answer model (Ollama) -- synthesize  [optional]
Each model is fully unloaded before the next one loads.
"""

from __future__ import annotations

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import argparse
import gc
import json
import logging
from pathlib import Path
from typing import Sequence

import weaviate
from ollama import Client

from parse import PDFChunkingPipeline, PipelineConfig, Chunk, load_pipeline_config, write_jsonl
from ingestion.embedder import Embedder
from reranker import Reranker
from rerank_policy import (
    DEFAULT_HEAVY_RERANKER,
    DEFAULT_LIGHT_RERANKER,
    choose_rerank_route,
    deduplicate_candidates,
    exact_clause_matches,
)
from ingestion.store import get_or_create_collection, upload_chunks
from agent import retrieve, synthesize_answer
from mineru_parser import MinerU2_5Assistant, MinerUConfig, parse_page_spec
from response_cache import DEFAULT_RESPONSE_CACHE_PATH, ResponseCache
from eval import run_eval

logger = logging.getLogger("main")


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )


# These helpers free each model before the next pipeline step starts.

def unload_ollama_model(host: str, model_name: str) -> None:
    """
    Tell Ollama to immediately evict *model_name* from its process memory.
    Uses keep_alive=0 so the model is released before we load the next one.
    Without this, Ollama holds the previous model in RAM and the next model
    can fail with an OOM / ggml buffer allocation error.
    """
    try:
        logger.info("Unloading Ollama model '%s' from memory ...", model_name)
        with Client(host=host) as client:
            client.generate(model=model_name, prompt="", keep_alive=0)
        logger.info("Ollama model '%s' unloaded.", model_name)
    except Exception as exc:
        logger.warning("Could not unload Ollama model '%s': %s", model_name, exc)


def unload_reranker(reranker: Reranker) -> None:
    """
    Drop all HuggingFace reranker references, force GC, and flush the CUDA
    cache (no-op when running CPU-only) so memory is free before Ollama loads
    the answer model.
    """
    logger.info("Unloading reranker model from memory ...")
    try:
        for attr in ("model", "tokenizer", "_model", "_tokenizer", "pipe", "pipeline"):
            if hasattr(reranker, attr):
                setattr(reranker, attr, None)
    except Exception as exc:
        logger.warning("Error clearing reranker attributes: %s", exc)

    del reranker
    gc.collect()

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except ImportError:
        pass

    logger.info("Reranker unloaded.")


# Ingestion turns one or more PDFs into chunks stored in Weaviate.

def _discover_pdfs(path: Path) -> list[Path]:
    if path.is_dir():
        pdfs = sorted(path.rglob("*.pdf"))
        if not pdfs:
            raise SystemExit(f"No .pdf files found under {path}")
        return pdfs
    if not path.exists():
        raise SystemExit(f"No such file or directory: {path}")
    return [path]


def prepare_one(
    pdf_path: Path,
    pipeline: PDFChunkingPipeline,
    pipeline_config: PipelineConfig,
    mineru: MinerU2_5Assistant | None,
    save_jsonl_dir: Path | None,
) -> list[Chunk]:
    logger.info("Parsing %s with the authoritative PyMuPDF pipeline.", pdf_path.name)
    chunks: list[Chunk] = pipeline.run(pdf_path)
    if not chunks:
        logger.warning("No chunks produced from %s -- skipping.", pdf_path.name)
        return []

    if mineru is not None:
        supplements = mineru.supplement_chunks(pdf_path, chunks, pipeline_config)
        chunks.extend(supplements)

    if save_jsonl_dir is not None:
        save_jsonl_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(chunks, save_jsonl_dir / f"{pdf_path.stem}.jsonl")
    return chunks


def upload_prepared(
    pdf_path: Path,
    chunks: Sequence[Chunk],
    embedder: Embedder,
    collection,
    batch_size: int,
) -> int:
    texts = [chunk.text for chunk in chunks]
    metadatas = [chunk.metadata.to_json() for chunk in chunks]
    ids = [chunk.metadata.chunk_id for chunk in chunks]
    vectors = embedder.embed_passages(texts, batch_size=batch_size)
    upload_chunks(collection, texts, vectors, metadatas, ids=ids)
    logger.info("Embedded and upserted %d chunks from %s", len(chunks), pdf_path.name)
    return len(chunks)


def cmd_ingest(args: argparse.Namespace) -> None:
    pdf_paths = _discover_pdfs(args.path)
    logger.info("Found %d PDF(s) to ingest", len(pdf_paths))

    config = (
        load_pipeline_config(args.parser_config)
        if args.parser_config
        else PipelineConfig(max_tokens=args.max_tokens, overlap_tokens=args.overlap_tokens)
    )
    pipeline = PDFChunkingPipeline(config)
    try:
        mineru_pages = parse_page_spec(args.mineru_pages)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    mineru_config = MinerUConfig(
        mode=args.mineru_mode,
        model_name=args.mineru_model,
        device=None if args.mineru_device == "auto" else args.mineru_device,
        dpi=args.mineru_dpi,
        max_pages=args.mineru_max_pages,
        pages=mineru_pages,
        cache_dir=args.mineru_cache_dir,
    )
    mineru = MinerU2_5Assistant(mineru_config) if mineru_config.enabled else None

    prepared: list[tuple[Path, list[Chunk]]] = []
    try:
        for index, pdf_path in enumerate(pdf_paths, start=1):
            logger.info("[parse %d/%d] %s", index, len(pdf_paths), pdf_path.name)
            chunks = prepare_one(pdf_path, pipeline, config, mineru, args.save_jsonl)
            if chunks:
                prepared.append((pdf_path, chunks))
    finally:
        if mineru is not None:
            mineru.unload()

    if not prepared:
        logger.warning("No chunks were prepared -- nothing to embed.")
        return

    if mineru is not None:
        logger.info("MinerU phase finished and memory was released before embedding.")
    embedder = Embedder(model_name=args.embed_model, host=args.host)

    wv_client = weaviate.connect_to_local()
    try:
        collection = get_or_create_collection(wv_client, args.collection)
        total = 0
        for index, (pdf_path, chunks) in enumerate(prepared, start=1):
            logger.info("[embed %d/%d] %s", index, len(prepared), pdf_path.name)
            total += upload_prepared(
                pdf_path, chunks, embedder, collection, batch_size=args.batch_size
            )
        logger.info(
            "Ingest complete: %d chunks across %d document(s) into '%s'.",
            total, len(prepared), args.collection,
        )
        ResponseCache(DEFAULT_RESPONSE_CACHE_PATH).clear()
        logger.info("Cleared cached query responses after corpus ingestion.")
    finally:
        wv_client.close()


# A query runs in three steps so only one large model is active at a time.


def run_adaptive_rerank(
    query: str,
    candidates: list[dict],
    *,
    light_model: str = DEFAULT_LIGHT_RERANKER,
    heavy_model: str = DEFAULT_HEAVY_RERANKER,
    device: str | None = None,
    top_n: int = 5,
    light_rerank_k: int = 8,
    heavy_rerank_k: int = 12,
    adaptive: bool = True,
    relevance_floor: float = 0.20,
    confidence_threshold: float = 0.80,
    margin_threshold: float = 0.10,
    emit=None,
) -> tuple[list[dict], dict]:
    """Rerank quickly first, then use the 4B model only when it adds value."""
    emit = emit or (lambda _line: None)
    unique = deduplicate_candidates(candidates)
    light_count = min(len(unique), max(top_n, light_rerank_k))
    light_candidates = unique[:light_count]
    emit(
        f"[phase 2/3] lightweight rerank with {light_model} "
        f"({len(candidates)} retrieved, {len(unique)} unique, {light_count} scored)"
    )

    light_reranker = Reranker(model_name=light_model, device=device)
    try:
        light_ranked = light_reranker.rerank(
            query, light_candidates, top_n=max(top_n, 2)
        )
    finally:
        unload_reranker(light_reranker)

    route = choose_rerank_route(
        query,
        light_ranked,
        relevance_floor=relevance_floor,
        confidence_threshold=confidence_threshold,
        margin_threshold=margin_threshold,
    )
    route.update({
        "selected_model": light_model,
        "escalated": False,
        "retrieved_candidate_count": len(candidates),
        "unique_candidate_count": len(unique),
        "light_candidate_count": light_count,
    })

    if adaptive and route["route"] == "heavy" and heavy_model != light_model:
        heavy_count = min(len(unique), max(top_n, heavy_rerank_k))
        emit(f"rerank escalation: {route['reason']}")
        emit(f"[phase 2/3] precision rerank with {heavy_model} ({heavy_count} scored)")
        heavy_reranker = Reranker(model_name=heavy_model, device=device)
        try:
            ranked = heavy_reranker.rerank(query, unique[:heavy_count], top_n=top_n)
        finally:
            unload_reranker(heavy_reranker)
        route.update({
            "selected_model": heavy_model,
            "escalated": True,
            "heavy_candidate_count": heavy_count,
        })
    else:
        ranked = light_ranked[:top_n]
        emit(f"rerank route: {route['route']} ({route['reason']})")

    return ranked, route

def run_query_pipeline(
    query: str,
    *,
    collection: str = "DocumentChunks",
    embed_model: str = "embeddinggemma",
    host: str = "http://localhost:11434",
    rerank_model: str = DEFAULT_LIGHT_RERANKER,
    heavy_rerank_model: str = DEFAULT_HEAVY_RERANKER,
    rerank_device: str | None = None,
    adaptive_rerank: bool = True,
    answer_model: str = "qwen2.5:1.5b",
    retrieve_k: int = 20,
    alpha: float = 0.5,
    light_rerank_k: int = 8,
    heavy_rerank_k: int = 12,
    rerank_confidence_threshold: float = 0.80,
    rerank_margin_threshold: float = 0.10,
    top_n: int = 5,
    answer: bool = False,
    relevance_threshold: float = 0.20,
    on_line=None,
    weaviate_client=None,
) -> dict:
    """Programmatic query entry point used by the Streamlit UI."""
    emit = on_line or (lambda _line: None)

    emit(f"[phase 1/3] retrieve with {embed_model}")
    embedder = Embedder(model_name=embed_model, host=host)
    owns_weaviate_client = weaviate_client is None
    wv_client = weaviate_client or weaviate.connect_to_local()
    try:
        wv_collection = wv_client.collections.get(collection)
        candidates = retrieve(wv_collection, embedder, query, retrieve_k, alpha)
    finally:
        embedder.close()
        if owns_weaviate_client:
            wv_client.close()
    emit(f"retrieved {len(candidates)} candidates")
    del embedder
    gc.collect()
    unload_ollama_model(host, embed_model)

    exact = exact_clause_matches(query, candidates)
    if exact:
        ranked = [{**candidate, "rerank_score": 1.0} for candidate in exact[:top_n]]
        rerank_route = {
            "route": "exact",
            "reason": "high-confidence retrieval matched the named clause",
            "selected_model": None,
            "escalated": False,
            "rerank_bypassed": True,
        }
        emit("[phase 2/3] exact clause match; reranker bypassed")
    else:
        ranked, rerank_route = run_adaptive_rerank(
            query, candidates, light_model=rerank_model,
            heavy_model=heavy_rerank_model, device=rerank_device,
            top_n=top_n, light_rerank_k=light_rerank_k,
            heavy_rerank_k=heavy_rerank_k, adaptive=adaptive_rerank,
            relevance_floor=relevance_threshold,
            confidence_threshold=rerank_confidence_threshold,
            margin_threshold=rerank_margin_threshold, emit=emit,
        )

    for i, chunk in enumerate(ranked, 1):
        emit(
            f"[{i}] rerank_score={chunk['rerank_score']:.2f}  "
            f"hybrid_score={chunk['score']:.4f}"
        )
        emit(chunk["text"][:300].replace("\n", " "))
        emit("")

    top_score = ranked[0]["rerank_score"] if ranked else 0.0
    is_relevant = bool(ranked) and top_score >= relevance_threshold
    emit(
        f"context gate: {'relevant' if is_relevant else 'irrelevant'} "
        f"(top relevance={top_score:.3f}, threshold={relevance_threshold:.3f})"
    )

    answer_text = None
    if answer:
        if not is_relevant:
            answer_text = "Question irrelevant to the available document context."
            emit(answer_text)
        else:
            emit(f"[phase 3/3] synthesize with {answer_model}")
            try:
                with Client(host=host, timeout=None) as chat_client:
                    answer_text = synthesize_answer(chat_client, answer_model, query, ranked)
            finally:
                unload_ollama_model(host, answer_model)
            emit(answer_text)
    else:
        emit("[phase 3/3] answer synthesis skipped")

    return {
        "query": query,
        "ranked": ranked,
        "answer": answer_text,
        "is_relevant": is_relevant,
        "top_relevance_score": top_score,
        "rerank_route": rerank_route,
        "relevance_threshold": relevance_threshold,
    }


def cmd_query(args: argparse.Namespace) -> None:
    """Run the same query path used by Streamlit and future API clients."""
    run_query_pipeline(
        args.query,
        collection=args.collection,
        embed_model=args.embed_model,
        host=args.host,
        rerank_model=args.rerank_model,
        heavy_rerank_model=args.heavy_rerank_model,
        rerank_device=args.rerank_device,
        adaptive_rerank=not args.no_adaptive_rerank,
        answer_model=args.answer_model,
        retrieve_k=args.retrieve_k,
        light_rerank_k=args.light_rerank_k,
        heavy_rerank_k=args.heavy_rerank_k,
        rerank_confidence_threshold=args.rerank_confidence_threshold,
        rerank_margin_threshold=args.rerank_margin_threshold,
        alpha=args.alpha,
        top_n=args.top_n,
        answer=args.answer,
        on_line=print,
    )


# Evaluation runs the same RAG steps against the saved golden dataset.

_METRIC_REGISTRY = {
    "mrr": "MRR",
    "recall": "Recall",
    "ndcg": "NDCG",
    "faithfulness": "Faithfulness",
    "relevance": "Answer Relevancy",
    "citation_correctness": "Citation Correctness"
}


def print_registry_metrics(results_dict: dict) -> None:
    """Flattens the nested results dictionary and prints metrics from the registry."""
    print("\n" + "="*50)
    print(" REGISTRY METRICS SUMMARY".center(50))
    print("="*50)

    flat_results = {}
    for stage, metrics in results_dict.items():
        if isinstance(metrics, dict):
            flat_results.update(metrics)

    for metric_key in _METRIC_REGISTRY.keys():
        score = flat_results.get(metric_key, "N/A")
        display_name = metric_key.replace("_", " ").title()
        if isinstance(score, float):
            print(f" {display_name:<25}: {score:.4f}")
        else:
            print(f" {display_name:<25}: {score}")

    print("="*50 + "\n")


def cmd_eval(args: argparse.Namespace) -> None:
    """Delegates evaluation directly to eval.py's integrated test runner."""
    args.no_generate = "answer" not in args.stages
    args.golden_dataset = args.dataset
    if getattr(args, "skip_judge", False):
        args.metrics = []

    logger.info("Starting multi-stage evaluation pipeline...")
    run_eval(args)


# The CLI keeps ingestion, querying, and evaluation available without a UI.

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collection", default="DocumentChunks", help="Weaviate collection name")
    parser.add_argument("--embed-model", default="embeddinggemma", help="Ollama embedding model tag")
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("-v", "--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_ingest = subparsers.add_parser("ingest", help="Parse, chunk, embed, and upload PDF(s)")
    p_ingest.add_argument("path", type=Path, help="A PDF file, or a directory to scan recursively for PDFs")
    p_ingest.add_argument("--max-tokens", type=int, default=400)
    p_ingest.add_argument("--overlap-tokens", type=int, default=60)
    p_ingest.add_argument("--parser-config", type=Path, default=None,
                          help="Complete frozen parser JSON; overrides chunking flags")
    p_ingest.add_argument("--batch-size", type=int, default=32, help="Embedding batch size")
    p_ingest.add_argument("--save-jsonl", type=Path, default=None,
                           help="Optional directory to also write each document's chunks.jsonl to")
    p_ingest.set_defaults(func=cmd_ingest)

    p_query = subparsers.add_parser("query", help="Retrieve, rerank, and (optionally) answer a question")
    p_query.add_argument("query", help="The search query / question")
    p_query.add_argument("--rerank-model", default=DEFAULT_LIGHT_RERANKER,
                          help="Lightweight HuggingFace reranker used for every query")
    p_query.add_argument("--heavy-rerank-model", default=DEFAULT_HEAVY_RERANKER,
                          help="Larger reranker used only when the fast result is uncertain")
    p_query.add_argument("--rerank-device", default=None, help="cuda / cpu -- defaults to cuda if available")
    p_query.add_argument("--no-adaptive-rerank", action="store_true",
                          help="Never escalate uncertain results to the larger reranker")
    p_query.add_argument("--light-rerank-k", type=int, default=8,
                          help="Unique candidates scored by the lightweight reranker")
    p_query.add_argument("--heavy-rerank-k", type=int, default=12,
                          help="Unique candidates scored after escalation")
    p_query.add_argument("--rerank-confidence-threshold", type=float, default=0.80,
                          help="Fast-path minimum top score")
    p_query.add_argument("--rerank-margin-threshold", type=float, default=0.10,
                          help="Fast-path minimum separation from the second result")
    p_ingest.add_argument(
        "--mineru-mode", choices=["off", "selective", "all"], default="off",
        help="Add MinerU2.5 visual supplement chunks; PyMuPDF chunks remain authoritative",
    )
    p_ingest.add_argument(
        "--mineru-model", default="opendatalab/MinerU2.5-2509-1.2B",
        help="Hugging Face MinerU2.5 model id or local model path",
    )
    p_ingest.add_argument(
        "--mineru-device", choices=["auto", "cuda", "cpu"], default="auto",
    )
    p_ingest.add_argument("--mineru-dpi", type=int, default=200, help="Page render DPI")
    p_ingest.add_argument(
        "--mineru-max-pages", type=int, default=12,
        help="Safety cap for MinerU pages per ingestion; 0 means unlimited",
    )
    p_ingest.add_argument(
        "--mineru-pages", default="",
        help="One-based pages/ranges to force through MinerU, for example 4,9-12",
    )
    p_ingest.add_argument("--mineru-cache-dir", type=Path, default=Path(".mineru_cache"))
    p_query.add_argument("--answer-model", default="qwen2.5:1.5b", help="Model used for final answer synthesis")
    p_query.add_argument("--retrieve-k", type=int, default=20, help="Candidates pulled from Weaviate before reranking")
    p_query.add_argument("--alpha", type=float, default=0.5,
                          help="Hybrid search balance: 0.0=pure keyword (BM25), 1.0=pure vector, 0.5=even split")
    p_query.add_argument("--top-n", type=int, default=5, help="Chunks kept after reranking")
    p_query.add_argument("--answer", action="store_true", help="Also synthesize a final grounded answer")
    p_query.set_defaults(func=cmd_query)

    p_eval = subparsers.add_parser("eval", help="Score retrieval / rerank / answer stages against a labeled dataset")
    p_eval.add_argument("dataset", type=Path, help="Path to eval_dataset.jsonl (see generate_eval_dataset.py)")
    p_eval.add_argument("--stages", nargs="+", choices=["retrieval", "rerank", "answer"],
                         default=["retrieval", "rerank", "answer"])
    p_eval.add_argument("--rerank-model", default="Qwen/Qwen3-Reranker-4B",
                         help="HuggingFace model id, loaded locally via transformers (not Ollama)")
    p_eval.add_argument("--rerank-device", default=None, help="cuda / cpu -- defaults to cuda if available")
    p_eval.add_argument("--answer-model", default="qwen2.5:1.5b", help="Model used for final answer synthesis")
    p_eval.add_argument("--judge-model", default="qwen3:8b",
                         help="Ideally a stronger/different model than --answer-model to avoid self-grading bias")
    p_eval.add_argument(
        "--judge-timeout", type=float, default=900,
        help="Seconds per judge response; 0 disables DeepEval timeouts (default: 900)",
    )
    p_eval.add_argument("--judge-retries", type=int, default=3, help="Attempts per failed judge request")
    p_eval.add_argument("--judge-keep-alive", default="30m", help="How long Ollama keeps the judge loaded")
    p_eval.add_argument(
        "--judge-temperature", type=float, default=0.0,
        help="Judge sampling temperature (default: 0 for reproducible grading)",
    )
    p_eval.add_argument(
        "--judge-thinking", action="store_true",
        help="Enable Qwen thinking (slower; disabled by default for structured grading)",
    )
    p_eval.add_argument("--retrieve-k", type=int, default=20, help="Candidates pulled from Weaviate before reranking")
    p_eval.add_argument("--alpha", type=float, default=0.5,
                         help="Hybrid search balance: 0.0=pure keyword (BM25), 1.0=pure vector, 0.5=even split")
    p_eval.add_argument("--top-n", type=int, default=5, help="Chunks kept after reranking")
    p_eval.add_argument("--k-values", nargs="+", type=int, default=[1, 3, 5, 10])
    p_eval.add_argument("--limit", type=int, default=None, help="Only evaluate the first N examples")
    p_eval.add_argument("--sample-seed", type=int, default=None,
                        help="Randomly sample the limited examples with this reproducible seed")
    p_eval.add_argument("--skip-judge", action="store_true", help="Skip all DeepEval/Ollama judge metrics")
    p_eval.add_argument("-o", "--output", type=Path, default=Path("eval_results.json"))
    p_eval.add_argument("--metrics", nargs="+", default=["answer_relevancy", "faithfulness", "contextual_precision", "contextual_recall", "contextual_relevancy"],
                         help="Which DeepEval metrics to run.")
    p_eval.set_defaults(func=cmd_eval)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)
    args.func(args)


if __name__ == "__main__":
    main()

    # Example: uv run python main.py eval golden_dataset.jsonl --stages retrieval rerank answer
