"""Detached command runner that persists job state for the Streamlit console."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import traceback
from pathlib import Path


# Replace the metadata file atomically while the UI is polling it.

def write_json(path: Path, payload: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)


# Run one detached command and update its queued, running, and final states.

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--meta", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        raise SystemExit("No command supplied")

    metadata = json.loads(args.meta.read_text(encoding="utf-8"))
    metadata.update({"status": "running", "started_at": time.time(), "command": command})
    write_json(args.meta, metadata)

    return_code = 1
    with args.log.open("a", encoding="utf-8", buffering=1) as log:
        log.write("$ " + " ".join(command) + "\n\n")
        try:
            return_code = subprocess.run(
                command,
                cwd=metadata["cwd"],
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            ).returncode
        except Exception:
            log.write("\n" + traceback.format_exc())

    metadata.update(
        {
            "status": "completed" if return_code == 0 else "failed",
            "return_code": return_code,
            "finished_at": time.time(),
        }
    )
    write_json(args.meta, metadata)


if __name__ == "__main__":
    main()

    # TODO: Move priority handling into main before subprocess.run; metadata is local to main.

    if metadata.get("priority", "background") == "background":
        try:
            os.nice(10)
        except (AttributeError, OSError):
            pass

