#!/usr/bin/env bash
set -euo pipefail

# Ollama Desktop runs as a Windows process in this setup, so its server-level
# cache settings must be stored in the Windows user environment. The backend
# itself continues to start and run from native Ubuntu WSL.
powershell.exe -NoProfile -NonInteractive -Command \
  '[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User"); [Environment]::SetEnvironmentVariable("OLLAMA_KV_CACHE_TYPE", "f16", "User"); [Environment]::SetEnvironmentVariable("OLLAMA_MAX_LOADED_MODELS", "2", "User"); [Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "1", "User")'

printf '%s\n' \
  'Configured Flash Attention, high-precision f16 KV cache, and two loaded models.' \
  'Parallelism remains one to keep context memory bounded on an 8 GB GPU.' \
  'Quit and restart Ollama Desktop before testing the new server settings.'
