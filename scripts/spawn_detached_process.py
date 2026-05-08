#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spawn a detached background process with merged stdout/stderr logging.")
    parser.add_argument("--log", required=True, help="Absolute path to the log file.")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to execute after '--'.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise SystemExit("command required after '--'")

    log_path = Path(args.log).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab", buffering=0) as log_handle:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
