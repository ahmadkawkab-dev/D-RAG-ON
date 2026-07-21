"""Lightweight system and local-service telemetry for the Streamlit console."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import psutil
import requests


# GPU information is optional, so missing tools should not break the dashboard.

def _gpu_snapshot() -> list[dict]:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return []
    command = [
        executable,
        "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=True)
    except (OSError, subprocess.SubprocessError):
        return []

    gpus = []
    for line in result.stdout.splitlines():
        values = [value.strip() for value in line.split(",")]
        if len(values) != 5:
            continue
        try:
            name, utilization, used, total, temperature = values
            gpus.append(
                {
                    "name": name,
                    "utilization": float(utilization),
                    "memory_used_mb": float(used),
                    "memory_total_mb": float(total),
                    "temperature_c": float(temperature),
                }
            )
        except ValueError:
            continue
    return gpus


def _service_ok(url: str) -> bool:
    try:
        response = requests.get(url, timeout=1.5)
        return response.ok
    except requests.RequestException:
        return False


def _ollama_models(host: str) -> list[dict]:
    try:
        response = requests.get(f"{host.rstrip('/')}/api/ps", timeout=1.5)
        response.raise_for_status()
        return response.json().get("models", [])
    except (requests.RequestException, ValueError):
        return []


# Return one small payload for health checks and the Streamlit system dock.

def get_system_snapshot(
    ollama_host: str = "http://localhost:11434",
    workspace: Path | None = None,
) -> dict:
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(str(workspace or Path.cwd()))
    process = psutil.Process()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_count": psutil.cpu_count(logical=True) or 1,
        "memory_percent": memory.percent,
        "memory_used_gb": memory.used / 1024**3,
        "memory_total_gb": memory.total / 1024**3,
        "swap_percent": swap.percent,
        "disk_percent": disk.percent,
        "process_memory_gb": process.memory_info().rss / 1024**3,
        "gpus": _gpu_snapshot(),
        "ollama_ok": _service_ok(f"{ollama_host.rstrip('/')}/api/tags"),
        "weaviate_ok": _service_ok("http://localhost:8080/v1/.well-known/ready"),
        "ollama_models": _ollama_models(ollama_host),
    }

