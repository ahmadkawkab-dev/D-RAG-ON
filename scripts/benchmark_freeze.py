"""Freeze and verify the corpus contract used by a RAG benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from parse import PipelineConfig, load_pipeline_config


ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
RUNTIME_PACKAGES = ('pymupdf', 'tiktoken')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def resolve(path: str, manifest_path: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT / candidate


def file_record(path: Path) -> dict:
    return {
        'path': relative(path),
        'sha256': sha256(path),
        'bytes': path.stat().st_size,
    }


def runtime_versions() -> dict:
    packages = {}
    for package in RUNTIME_PACKAGES:
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return {
        'python': platform.python_version(),
        'packages': packages,
    }


def chunk_statistics(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    if not rows:
        raise ValueError(f'No chunks found in {path}')
    ids = [row['metadata']['chunk_id'] for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f'Chunk IDs are not unique: {duplicates[:10]}')
    tokens = [int(row['metadata']['token_count']) for row in rows]
    return {
        'count': len(rows),
        'unique_chunk_ids': len(set(ids)),
        'total_tokens': sum(tokens),
        'min_tokens': min(tokens),
        'max_tokens': max(tokens),
        'page_start': min(row['metadata']['page_start'] for row in rows),
        'page_end': max(row['metadata']['page_end'] for row in rows),
        'element_types': dict(Counter(row['metadata']['element_type'] for row in rows)),
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temp.replace(path)


# Freeze parser settings, chunks, hashes, and model choices into one benchmark version.

def freeze(args: argparse.Namespace) -> Path:
    source = args.source.resolve()
    chunks = args.chunks.resolve()
    if not source.exists() or not chunks.exists():
        raise SystemExit('Source PDF and chunks JSONL must both exist.')

    config = PipelineConfig(max_tokens=args.max_tokens, overlap_tokens=args.overlap_tokens)
    config_payload = {
        'schema_version': SCHEMA_VERSION,
        'config_version': args.version,
        'pipeline_config': asdict(config),
    }
    output_dir = args.output_dir.resolve()
    config_path = output_dir / 'parser_config.json'
    write_json(config_path, config_payload)

    chunk_hash = sha256(chunks)
    chunk_version = f'{args.version}-{chunk_hash[:12]}'
    manifest = {
        'schema_version': SCHEMA_VERSION,
        'benchmark_version': args.version,
        'chunk_set_version': chunk_version,
        'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'frozen',
        'source_document': file_record(source),
        'chunks': {**file_record(chunks), 'statistics': chunk_statistics(chunks)},
        'parser': {
            'config': file_record(config_path),
            'source': file_record(ROOT / 'parse.py'),
            'runtime': runtime_versions(),
        },
        'ingestion': {
            'collection': args.collection,
            'embedding_model': args.embedding_model,
            'embedding_batch_size': args.batch_size,
            'recorded_run': relative(args.ingestion_run.resolve()) if args.ingestion_run else None,
        },
        'golden_datasets': {},
        'human_review': {
            'required': True,
            'completed': False,
            'reviewer': None,
            'reviewed_at_utc': None,
            'notes': 'Only humans may mark benchmark questions reviewed.',
        },
    }
    for dataset in args.golden_dataset:
        if dataset.exists():
            manifest['golden_datasets'][dataset.name] = file_record(dataset.resolve())

    manifest_path = output_dir / 'manifest.json'
    write_json(manifest_path, manifest)
    return manifest_path


# Recalculate the saved hashes to catch accidental benchmark changes.

def verify(manifest_path: Path, quiet: bool = False) -> bool:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    failures = []

    records = {
        'source document': manifest['source_document'],
        'chunks': manifest['chunks'],
        'parser config': manifest['parser']['config'],
        'parser source': manifest['parser']['source'],
        **{f'golden dataset {name}': record for name, record in manifest.get('golden_datasets', {}).items()},
    }
    for label, record in records.items():
        path = resolve(record['path'], manifest_path)
        if not path.exists():
            failures.append(f'{label}: missing {path}')
            continue
        actual = sha256(path)
        if actual != record['sha256']:
            failures.append(f'{label}: SHA-256 drift ({actual} != {record["sha256"]})')

    chunks_path = resolve(manifest['chunks']['path'], manifest_path)
    if chunks_path.exists():
        actual_stats = chunk_statistics(chunks_path)
        if actual_stats != manifest['chunks']['statistics']:
            failures.append('chunks: structural statistics drift')

    config_path = resolve(manifest['parser']['config']['path'], manifest_path)
    if config_path.exists():
        try:
            load_pipeline_config(config_path)
        except Exception as exc:
            failures.append(f'parser config: invalid ({exc})')

    expected_runtime = manifest['parser']['runtime']
    actual_runtime = runtime_versions()
    if actual_runtime != expected_runtime:
        failures.append(f'parser runtime drift ({actual_runtime} != {expected_runtime})')

    if failures:
        if not quiet:
            print('BENCHMARK FREEZE: FAILED')
            for failure in failures:
                print(f' - {failure}')
        return False
    if not quiet:
        print('BENCHMARK FREEZE: VERIFIED')
        print(f' version: {manifest["benchmark_version"]}')
        print(f' chunk set: {manifest["chunk_set_version"]}')
        print(f' chunks: {manifest["chunks"]["statistics"]["count"]}')
        print(f' sha256: {manifest["chunks"]["sha256"]}')
        if not manifest.get('human_review', {}).get('completed'):
            print(' human review: PENDING')
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)

    freezer = subparsers.add_parser('freeze')
    freezer.add_argument('--source', type=Path, required=True)
    freezer.add_argument('--chunks', type=Path, required=True)
    freezer.add_argument('--output-dir', type=Path, default=Path('benchmark/cis-controls-v8-v1'))
    freezer.add_argument('--version', default='cis-controls-v8-v1')
    freezer.add_argument('--max-tokens', type=int, default=400)
    freezer.add_argument('--overlap-tokens', type=int, default=60)
    freezer.add_argument('--collection', default='DocumentChunks')
    freezer.add_argument('--embedding-model', default='embeddinggemma')
    freezer.add_argument('--batch-size', type=int, default=32)
    freezer.add_argument('--ingestion-run', type=Path)
    freezer.add_argument('--golden-dataset', type=Path, action='append', default=[])

    verifier = subparsers.add_parser('verify')
    verifier.add_argument('manifest', type=Path)

    args = parser.parse_args()
    if args.command == 'freeze':
        manifest_path = freeze(args)
        print(manifest_path)
        if not verify(manifest_path):
            raise SystemExit(1)
    elif not verify(args.manifest):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
