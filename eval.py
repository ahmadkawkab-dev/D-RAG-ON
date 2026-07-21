"""
eval.py
========
Evaluates the local RAG pipeline (retrieve -> rerank -> synthesize)
against golden_dataset.jsonl (aligned via align_golden_dataset.py first --
see the check at startup) using two complementary layers:

  1. Deterministic retrieval metrics (Hit@k, Recall@k, MRR@k) computed
     directly from each example's ground-truth `relevant_chunk_ids`. No
     LLM involved, free, and exact -- but only possible because the
     golden dataset happens to carry real chunk_ids (most eval libraries,
     DeepEval included, have no notion of "chunk id" and can't use this
     signal at all).

  2. DeepEval's LLM-judged RAG metrics (AnswerRelevancy, Faithfulness,
     ContextualPrecision, ContextualRecall, ContextualRelevancy), which
     grade text quality/grounding that (1) can't -- e.g. whether the
     synthesized answer is actually faithful to what was retrieved. The
     judge is a local Ollama model (deepeval.models.OllamaModel), so
     this stays consistent with the rest of the project: no cloud calls,
     no OpenAI key.

NOTE: Models run in strict sequential phases to avoid OOM errors:
  Phase 1: Embedder (Ollama)  -- retrieve candidates for ALL examples
  Phase 2: Reranker (HF)      -- rerank ALL candidates
  Phase 3: Answer model (Ollama) -- generate answers for ALL examples
  Phase 4: Judge model (Ollama)  -- DeepEval LLM-judged metrics

  Each model is explicitly unloaded from CPU/GPU memory before the next
  one loads. This prevents the ggml/transformers OOM crashes seen when
  multiple large models compete for the same buffer pool.

Run:
    python eval.py golden_dataset.aligned.jsonl

    # Use this command when you only want a quick retrieval check.
    python eval.py golden_dataset.aligned.jsonl --no-generate

    # Start with a few records before running the complete evaluation set.
    python eval.py golden_dataset.aligned.jsonl --limit 3

    # A larger local judge is slower but usually gives more reliable scores.
    python eval.py golden_dataset.aligned.jsonl --judge-model qwen2.5:7b
"""

from __future__ import annotations

import argparse
import gc
import json
import logging
import os
import random
import re
import statistics
import time
from pathlib import Path
from typing import Optional

import requests
import weaviate
from ollama import Client

from deepeval import evaluate
from deepeval.evaluate.configs import AsyncConfig, CacheConfig
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    ContextualRelevancyMetric,
    FaithfulnessMetric,
)
from deepeval.models import OllamaModel
from deepeval.test_case import LLMTestCase

from ingestion.embedder import Embedder
from reranker import Reranker
from agent import retrieve, synthesize_answer

logger = logging.getLogger("eval")


class _JudgeClientProxy:
    """Inject Ollama request options that DeepEval's adapter does not expose."""

    def __init__(self, client, keep_alive: str, think: bool):
        self._client = client
        self._keep_alive = keep_alive
        self._think = think

    def chat(self, *args, **kwargs):
        kwargs.setdefault("keep_alive", self._keep_alive)
        kwargs.setdefault("think", self._think)
        return self._client.chat(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)


class StableOllamaJudge(OllamaModel):
    """DeepEval Ollama adapter with keep-alive and Qwen thinking control."""

    def __init__(self, *args, keep_alive: str = "30m", think: bool = False, **kwargs):
        self.keep_alive = keep_alive
        self.think = think
        self._sync_client = None
        super().__init__(*args, **kwargs)

    def _build_client(self, cls):
        return _JudgeClientProxy(super()._build_client(cls), self.keep_alive, self.think)

    def load_model(self, async_mode: bool = False):
        # Reuse one Ollama client so every judge request does not open a new connection.
        if async_mode:
            return super().load_model(async_mode=True)
        if self._sync_client is None:
            self._sync_client = super().load_model(async_mode=False)
        return self._sync_client

    def close(self) -> None:
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

# Answer-based metrics are skipped when answer generation is disabled.
_GENERATION_DEPENDENT_METRICS = {"answer_relevancy", "faithfulness"}

_METRIC_REGISTRY = {
    "answer_relevancy": AnswerRelevancyMetric,
    "faithfulness": FaithfulnessMetric,
    "contextual_precision": ContextualPrecisionMetric,
    "contextual_recall": ContextualRecallMetric,
    "contextual_relevancy": ContextualRelevancyMetric,
}

# The parser can create simple numbered IDs or semantic control IDs.
_REAL_CHUNK_ID_PATTERN = re.compile(
    r"(?:"
    r".+-\d{4}|"
    r"control\d{2}-(?:safeguard\d{1,2}\.\d{1,2}|overview)(?:-part\d{2})?|"
    r"(?:glossary|intro)-\d{4}(?:-part\d{2})?"
    r")$"
)


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )



def configure_judge_runtime(timeout_seconds: float, retry_attempts: int) -> None:
    """Override DeepEval's short provider deadlines for a slow local judge."""
    if timeout_seconds <= 0:
        os.environ["DEEPEVAL_DISABLE_TIMEOUTS"] = "true"
        timeout_label = "disabled"
    else:
        os.environ.pop("DEEPEVAL_DISABLE_TIMEOUTS", None)
        os.environ["DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE"] = str(timeout_seconds)
        # Give the full metric enough time to make more than one model request.
        os.environ["DEEPEVAL_PER_TASK_TIMEOUT_SECONDS_OVERRIDE"] = str(
            max(timeout_seconds * 5, timeout_seconds + 60)
        )
        timeout_label = f"{timeout_seconds:g}s per Ollama response"

    os.environ["DEEPEVAL_RETRY_MAX_ATTEMPTS"] = str(max(1, retry_attempts))
    logger.info(
        "Judge connection policy: timeout=%s, retries=%d, concurrency=1",
        timeout_label,
        max(1, retry_attempts),
    )


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def check_dataset_is_aligned(examples: list[dict]) -> None:
    all_ids = [cid for ex in examples for cid in ex.get("relevant_chunk_ids", [])]
    if all_ids and not any(_REAL_CHUNK_ID_PATTERN.match(cid) for cid in all_ids):
        logger.warning(
            "None of this dataset's relevant_chunk_ids look like real "
            "parse.py-assigned chunk_ids (expected a '<stem>-NNNN' "
            "suffix). This looks like the raw golden_dataset.jsonl, not "
            "the output of align_golden_dataset.py -- retrieval hit-rate "
            "metrics will be meaningless (they'll compare against IDs "
            "that were never stored in Weaviate). Run align_golden_dataset.py first."
        )


def warn_if_unverified(examples: list[dict]) -> None:
    unverified = [ex for ex in examples if not ex.get("verified", False)]
    if unverified:
        provenances = sorted({ex.get("provenance", "unknown") for ex in unverified})
        logger.warning(
            "%d/%d golden examples are unverified (%s) -- treat these "
            "scores as provisional until some1 reviews the examples "
            "themselves; a wrong or ambiguous golden example produces a "
            "confidently wrong eval score.",
            len(unverified), len(examples), ", ".join(provenances),
        )


# Free each model before the next evaluation phase starts.

def unload_ollama_model(host: str, model_name: str) -> None:
    """
    Tell Ollama to immediately evict *model_name* from its process memory by
    sending a generate request with keep_alive=0.  This frees the CPU/RAM
    buffer before we load the next model so both never compete for the same
    pool at the same time.
    """
    try:
        logger.info("Unloading Ollama model '%s' from memory ...", model_name)
        client = Client(host=host)
        # keep_alive=0 asks Ollama to remove the model from memory now.
        client.generate(model=model_name, prompt="", keep_alive=0)
        logger.info("Ollama model '%s' unloaded.", model_name)
    except Exception as exc:
        # Cleanup errors are logged because the next phase may still have enough memory.
        logger.warning("Could not unload Ollama model '%s': %s", model_name, exc)

    # Give the operating system a moment to reclaim released memory.
    time.sleep(2)


def unload_reranker(reranker: Reranker) -> None:
    """
    Drop all references to the HuggingFace reranker model and tokenizer,
    then force a full GC + CUDA cache flush so the memory is available for
    the next stage before we return.
    """
    logger.info("Unloading reranker model from memory ...")
    try:
        # Clear the possible model attributes before running garbage collection.
        for attr in ("model", "tokenizer", "_model", "_tokenizer", "pipe", "pipeline"):
            if hasattr(reranker, attr):
                setattr(reranker, attr, None)
    except Exception as exc:
        logger.warning("Error while clearing reranker attributes: %s", exc)

    del reranker
    gc.collect()

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except ImportError:
        pass  # torch not installed -- CPU-only run, gc.collect() is enough

    logger.info("Reranker unloaded.")
    time.sleep(2)


# These retrieval scores are deterministic and do not call an LLM.


def compute_retrieval_metrics(retrieved_chunk_ids: list[Optional[str]], relevant_chunk_ids: list[str]) -> dict:
    """Hit@k / Recall@k / MRR@k against the ground-truth chunk_ids,
    where k is len(retrieved_chunk_ids) (i.e. however many chunks were
    actually kept post-rerank and handed to the generator)."""
    relevant_set = set(relevant_chunk_ids)
    retrieved = [cid for cid in retrieved_chunk_ids if cid is not None]

    hit = any(cid in relevant_set for cid in retrieved)
    num_relevant_retrieved = sum(1 for cid in retrieved if cid in relevant_set)
    recall = num_relevant_retrieved / len(relevant_set) if relevant_set else 0.0

    mrr = 0.0
    for rank, cid in enumerate(retrieved, start=1):
        if cid in relevant_set:
            mrr = 1.0 / rank
            break

    return {"hit": hit, "recall": recall, "mrr": mrr}


def print_retrieval_summary(rows: list[dict]) -> None:
    print("\n=== Retrieval metrics (deterministic, no LLM) ===")
    print(f"{'Query':<70} {'Hit':<5} {'Recall':<8} {'MRR':<6}")
    for row in rows:
        query = row["query"][:67] + "..." if len(row["query"]) > 70 else row["query"]
        print(f"{query:<70} {str(row['hit']):<5} {row['recall']:<8.2f} {row['mrr']:<6.2f}")
    print("-" * 90)
    print(
        f"{'MEAN':<70} "
        f"{statistics.mean(r['hit'] for r in rows):<5.2f} "
        f"{statistics.mean(r['recall'] for r in rows):<8.2f} "
        f"{statistics.mean(r['mrr'] for r in rows):<6.2f}"
    )


# Each phase has one job and keeps only one large model active.


def phase_retrieve(examples: list[dict], collection, embedder: Embedder, args: argparse.Namespace) -> list[list[dict]]:
    """
    PHASE 1 -- Embedder (Ollama) only.
    Retrieves hybrid-search candidates for every example.
    Returns a list of candidate lists (one per example), preserving order.
    """
    logger.info("=== PHASE 1/4: Retrieval (embedder model: %s) ===", args.embed_model)
    all_candidates: list[list[dict]] = []
    for i, example in enumerate(examples, start=1):
        logger.info("[retrieve %d/%d] %s", i, len(examples), example["query"][:80])
        candidates = retrieve(collection, embedder, example["query"], args.retrieve_k, args.alpha)
        all_candidates.append(candidates)
    logger.info("Phase 1 complete: retrieved candidates for %d examples.", len(examples))
    return all_candidates


def phase_rerank(examples: list[dict], all_candidates: list[list[dict]], reranker: Reranker, args: argparse.Namespace) -> list[list[dict]]:
    """
    PHASE 2 -- Reranker (HuggingFace transformers) only.
    Reranks the pre-fetched candidates for every example.
    Returns a list of ranked result lists (one per example).
    """
    logger.info("=== PHASE 2/4: Reranking (model: %s) ===", args.rerank_model)
    all_ranked: list[list[dict]] = []
    for i, (example, candidates) in enumerate(zip(examples, all_candidates), start=1):
        logger.info("[rerank %d/%d] %s", i, len(examples), example["query"][:80])
        ranked = reranker.rerank(example["query"], candidates, top_n=args.top_n)
        all_ranked.append(ranked)
    logger.info("Phase 2 complete: reranked for %d examples.", len(examples))
    return all_ranked


def phase_generate(examples: list[dict], all_ranked: list[list[dict]], chat_client: Client, args: argparse.Namespace) -> list[str]:
    """
    PHASE 3 -- Answer model (Ollama) only.
    Synthesizes one answer per example from the pre-reranked context.
    Returns a list of answer strings (empty string when skipped).
    """
    logger.info("=== PHASE 3/4: Answer synthesis (model: %s) ===", args.answer_model)
    all_answers: list[str] = []
    for i, (example, ranked) in enumerate(zip(examples, all_ranked), start=1):
        logger.info("[generate %d/%d] %s", i, len(examples), example["query"][:80])
        answer = synthesize_answer(chat_client, args.answer_model, example["query"], ranked)
        all_answers.append(answer)
    logger.info("Phase 3 complete: answers generated for %d examples.", len(examples))
    return all_answers


# DeepEval uses the local Ollama judge through this adapter.


def build_metrics(judge: OllamaModel, requested: list[str], no_generate: bool) -> list:
    names = list(requested)
    if no_generate:
        dropped = [n for n in names if n in _GENERATION_DEPENDENT_METRICS]
        if dropped:
            logger.info(
                "Skipping %s (require a genuinely synthesized answer; --no-generate was set).",
                ", ".join(dropped),
            )
        names = [n for n in names if n not in _GENERATION_DEPENDENT_METRICS]
    return [_METRIC_REGISTRY[name](model=judge) for name in names]


def summarize_deepeval_results(results) -> list[dict]:
    """Flattens DeepEval's result object into plain rows. Defensive about
    exact attribute names (metrics_data / name / metric) since these have
    shifted slightly across deepeval versions -- falls back gracefully
    instead of crashing the whole eval run over a version mismatch."""
    rows = []
    for test_result in getattr(results, "test_results", []) or []:
        query = getattr(test_result, "input", "")
        for metric_data in getattr(test_result, "metrics_data", None) or []:
            rows.append({
                "query": query,
                "metric": getattr(metric_data, "name", getattr(metric_data, "metric", "unknown")),
                "score": getattr(metric_data, "score", None),
                "success": getattr(metric_data, "success", None),
                "reason": getattr(metric_data, "reason", ""),
            })
    return rows


def print_deepeval_summary(rows: list[dict]) -> None:
    if not rows:
        return
    by_metric: dict[str, list[float]] = {}
    for row in rows:
        if row["score"] is not None:
            by_metric.setdefault(row["metric"], []).append(row["score"])

    print("\n=== DeepEval metrics (LLM-judged) ===")
    print(f"{'Metric':<25} {'Mean score':<12} {'Pass rate':<10} {'n':<5}")
    for metric, scores in by_metric.items():
        passes = [r["success"] for r in rows if r["metric"] == metric and r["success"] is not None]
        pass_rate = statistics.mean(1.0 if p else 0.0 for p in passes) if passes else float("nan")
        print(f"{metric:<25} {statistics.mean(scores):<12.3f} {pass_rate:<10.2f} {len(scores):<5}")



def write_eval_output(
    output_path: Path,
    examples: list[dict],
    retrieval_rows: list[dict],
    example_rows: list[dict],
    deepeval_rows: list[dict],
    judged_cases: int,
    total_cases: int,
    complete: bool,
) -> None:
    """Write an atomic checkpoint so a dropped run does not lose its results."""
    output = {
        "summary": {
            "n_examples": len(examples),
            "unverified_examples": sum(1 for ex in examples if not ex.get("verified", False)),
            "retrieval": {
                "mean_hit_rate": statistics.mean(r["hit"] for r in retrieval_rows),
                "mean_recall": statistics.mean(r["recall"] for r in retrieval_rows),
                "mean_mrr": statistics.mean(r["mrr"] for r in retrieval_rows),
            },
            "judge": {
                "completed_cases": judged_cases,
                "total_cases": total_cases,
                "complete": complete,
            },
        },
        "examples": example_rows,
        "deepeval_metric_rows": deepeval_rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(output_path)

# This runner coordinates retrieval, reranking, generation, and judging.


def run_eval(args: argparse.Namespace) -> None:
    configure_logging(args.verbose)

    # main.py and this standalone script use different dataset argument names.
    dataset_path = getattr(args, "golden_dataset", getattr(args, "dataset", None))

    examples = load_jsonl(dataset_path)
    if not examples:
        raise SystemExit(f"No examples found in {dataset_path}")
    if getattr(args, "limit", None):
        limit = min(args.limit, len(examples))
        sample_seed = getattr(args, "sample_seed", None)
        examples = (
            random.Random(sample_seed).sample(examples, limit)
            if sample_seed is not None else examples[:limit]
        )

    check_dataset_is_aligned(examples)
    warn_if_unverified(examples)

    skip_generate = getattr(args, "no_generate", False) or ("answer" not in getattr(args, "stages", ["answer"]))

    judge_timeout = getattr(args, "judge_timeout", 900.0)
    judge_retries = getattr(args, "judge_retries", 3)
    judge_keep_alive = getattr(args, "judge_keep_alive", "30m")
    judge_thinking = getattr(args, "judge_thinking", False)
    judge_temperature = getattr(args, "judge_temperature", 0.0)
    configure_judge_runtime(judge_timeout, judge_retries)


    # Step 1: Retrieve candidate chunks for every evaluation question.
    embedder = Embedder(model_name=args.embed_model, host=args.host)
    wv_client = weaviate.connect_to_local()
    try:
        collection = wv_client.collections.get(args.collection)
        all_candidates = phase_retrieve(examples, collection, embedder, args)
    finally:
        wv_client.close()

    # Free the embedding model before the reranker is loaded.
    del embedder
    gc.collect()
    unload_ollama_model(args.host, args.embed_model)

    # Step 2: Rerank the candidates and keep the strongest matches.
    reranker = Reranker(model_name=args.rerank_model, device=args.rerank_device)
    all_ranked = phase_rerank(examples, all_candidates, reranker, args)

    # Free the reranker before the answer model is loaded.
    unload_reranker(reranker)
    # Do not access reranker after unload_reranker has cleared it.

    # Step 3: Generate answers from the selected chunks.
    if not skip_generate:
        chat_client = Client(host=args.host)
        all_answers = phase_generate(examples, all_ranked, chat_client, args)
        del chat_client
        gc.collect()
        unload_ollama_model(args.host, args.answer_model)
    else:
        logger.info("=== PHASE 3/4: Answer synthesis SKIPPED (--no-generate / no answer stage) ===")
        all_answers = [""] * len(examples)

    # Combine the outputs into one row for each evaluation question.
    retrieval_rows: list[dict] = []
    test_cases: list[LLMTestCase] = []
    example_rows: list[dict] = []

    for example, candidates, ranked, actual_output in zip(examples, all_candidates, all_ranked, all_answers):
        retrieved_chunk_ids: list[Optional[str]] = []
        for c in ranked:
            meta = c.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            elif not isinstance(meta, dict):
                meta = {}
            retrieved_chunk_ids.append(meta.get("chunk_id"))

        retrieval_context = [c["text"] for c in ranked]
        retrieval_metrics = compute_retrieval_metrics(retrieved_chunk_ids, example.get("relevant_chunk_ids", []))
        retrieval_rows.append({"query": example["query"], **retrieval_metrics})

        test_cases.append(
            LLMTestCase(
                input=example["query"],
                actual_output=actual_output,
                expected_output=example.get("reference_answer", ""),
                retrieval_context=retrieval_context,
            )
        )
        example_rows.append({
            "query": example["query"],
            "relevant_chunk_ids": example.get("relevant_chunk_ids", []),
            "retrieved_chunk_ids": retrieved_chunk_ids,
            **retrieval_metrics,
            "actual_output": actual_output,
            "expected_output": example.get("reference_answer", ""),
            "retrieval_context": retrieval_context,
        })

    print_retrieval_summary(retrieval_rows)

    # Step 4: Judge one completed question at a time to limit model load.
    deepeval_rows: list[dict] = []
    metrics_to_run = getattr(args, "metrics", list(_METRIC_REGISTRY))
    if metrics_to_run:
        logger.info("=== PHASE 4/4: DeepEval judging (judge model: %s) ===", args.judge_model)
        # The Ollama call has no HTTP timeout; DeepEval handles the deadline separately.
        judge = StableOllamaJudge(
            model=args.judge_model,
            base_url=args.host,
            temperature=judge_temperature,
            timeout=None,
            keep_alive=judge_keep_alive,
            think=judge_thinking,
        )
        # Load the judge once and keep it available for the whole judging phase.
        with Client(host=args.host, timeout=None) as warm_client:
            warm_client.generate(
                model=args.judge_model, prompt="", keep_alive=judge_keep_alive
            )
        metrics = build_metrics(judge, metrics_to_run, skip_generate)
        if metrics:
            n = len(test_cases)
            for idx, test_case in enumerate(test_cases, start=1):
                logger.info(
                    "[judge %d/%d] %s",
                    idx, n, (test_case.input or "")[:80],
                )
                # A one-item list makes DeepEval finish this case before the next one starts.
                result = evaluate(
                    test_cases=[test_case],
                    metrics=metrics,
                    async_config=AsyncConfig(run_async=False, max_concurrent=1),
                    cache_config=CacheConfig(write_cache=True, use_cache=True),
                )
                deepeval_rows.extend(summarize_deepeval_results(result))
                write_eval_output(
                    args.output,
                    examples,
                    retrieval_rows,
                    example_rows,
                    deepeval_rows,
                    judged_cases=idx,
                    total_cases=n,
                    complete=False,
                )
                logger.info("Checkpointed judge progress to %s", args.output)
            print_deepeval_summary(deepeval_rows)
        judge.close()
        del judge
        gc.collect()
        unload_ollama_model(args.host, args.judge_model)

    total_cases = len(test_cases) if metrics_to_run else 0
    write_eval_output(
        args.output,
        examples,
        retrieval_rows,
        example_rows,
        deepeval_rows,
        judged_cases=total_cases,
        total_cases=total_cases,
        complete=True,
    )
    logger.info("Full results written to %s", args.output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("golden_dataset", type=Path, help="Aligned golden_dataset.*.jsonl (see align_golden_dataset.py)")
    parser.add_argument("--collection", default="DocumentChunks", help="Weaviate collection name")
    parser.add_argument("--embed-model", default="embeddinggemma")
    parser.add_argument("--rerank-model", default="Qwen/Qwen3-Reranker-4B")
    parser.add_argument("--rerank-device", default=None, help="cuda / cpu -- defaults to cuda if available")
    parser.add_argument("--answer-model", default="qwen2.5:1.5b", help="Model used for answer synthesis")
    parser.add_argument("--judge-model", default="qwen3:8b", help="Ollama model used by DeepEval")
    parser.add_argument(
        "--judge-timeout", type=float, default=900,
        help="Seconds per judge response; 0 disables DeepEval timeouts (default: 900)",
    )
    parser.add_argument("--judge-retries", type=int, default=3, help="Attempts per failed judge request")
    parser.add_argument("--judge-keep-alive", default="30m", help="How long Ollama keeps the judge loaded")
    parser.add_argument(
        "--judge-temperature", type=float, default=0.0,
        help="Judge sampling temperature (default: 0 for reproducible grading)",
    )
    parser.add_argument(
        "--judge-thinking", action="store_true",
        help="Enable Qwen thinking (slower; disabled by default for structured grading)",
    )
    parser.add_argument("--host", default="http://localhost:11434", help="Ollama server URL")
    parser.add_argument("--retrieve-k", type=int, default=20)
    parser.add_argument("--alpha", type=float, default=0.5, help="Hybrid search balance: 0=BM25, 1=vector")
    parser.add_argument("--top-n", type=int, default=5, help="Chunks kept after reranking")
    parser.add_argument("--metrics", nargs="+", choices=list(_METRIC_REGISTRY), default=list(_METRIC_REGISTRY), help="Which DeepEval metrics to run.")
    parser.add_argument("--no-generate", action="store_true", help="Skip answer synthesis entirely.")
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N examples.")
    parser.add_argument("--sample-seed", type=int, default=None, help="Randomly sample limited examples reproducibly.")
    parser.add_argument("--skip-judge", action="store_true", help="Skip all DeepEval/Ollama judge metrics.")
    parser.add_argument("-o", "--output", type=Path, default=Path("eval_results.json"))
    parser.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()
    if args.skip_judge:
        args.metrics = []
    run_eval(args)