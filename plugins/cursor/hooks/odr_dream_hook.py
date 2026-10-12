#!/usr/bin/env python3
"""Cursor sessionEnd hook -> fire one ODR dream cycle out-of-band.

Detaches a `python -m open_dream_rsi dream` subprocess (own process group /
DETACHED on Windows) pointed at the Cursor chat store, so the learning loop
runs without MCP: evidence = Cursor chats, queue = `odr task add`-kept
tasks.json, brain = whatever OPENAI_BASE_URL / ODR_LLM_PRESET the
environment carries. Cadence is decided inside the dream module (cheap
maintenance per fire; a full dream only when evidence or staleness
justifies it), so firing on every session end is safe.

Where the ODR checkout / memory dir come from (first match wins):
  1. --home / --memory argv (what the installer writes into hooks.json)
  2. ODR_HOME / ODR_MEMORY environment
  3. the current working directory, when it is the ODR repo root
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_IS_WIN = sys.platform.startswith("win")


def _load_env_file(path: "str | None") -> dict:
    """KEY=VALUE lines -> env dict (the key never travels on argv)."""
    out: dict = {}
    if not path:
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def main(argv: "list[str] | None" = None) -> int:
    try:
        json.loads(sys.stdin.read() or "{}")  # consume the event; content unused
    except Exception:
        pass
    ns = argparse.ArgumentParser(add_help=False)
    ns.add_argument("--home", default=None)
    ns.add_argument("--memory", default=None)
    ns.add_argument("--python", default=None)
    ns.add_argument("--provider", default=None,
                    help="dream LLM preset (openai/cursor/local/goose)")
    ns.add_argument("--model", default=None)
    ns.add_argument("--env-file", default=None,
                    help="KEY=VALUE file merged into the dream child's env "
                         "(OPENAI_BASE_URL / OPENAI_API_KEY / ODR_LLM_*) — "
                         "values stay out of the command line")
    opts, _ = ns.parse_known_args(argv if argv is not None else sys.argv[1:])
    home = opts.home or os.environ.get("ODR_HOME")
    memory = opts.memory or os.environ.get("ODR_MEMORY")
    if not home or not memory:
        return 0  # unconfigured: fire-and-forget nothing
    python = (opts.python or os.environ.get("ODR_PYTHON") or sys.executable)
    log = Path(memory) / "dream.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    child_env = dict(os.environ)
    child_env.update(_load_env_file(opts.env_file))
    child_argv = [python, "-m", "open_dream_rsi",
                  "--memory", memory, "dream", "--source", "cursor"]
    if opts.provider:
        child_argv += ["--provider", opts.provider]
    if opts.model:
        child_argv += ["--model", opts.model]
    flags = 0
    if _IS_WIN:
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        with open(log, "ab") as log_fh:
            # --memory is a TOP-LEVEL flag: it must precede the `dream`
            # subcommand or argparse rejects the child with
            # "unrecognized arguments" (rc=2, silently in dream.log).
            subprocess.Popen(
                child_argv,
                stdout=log_fh, stderr=subprocess.STDOUT, cwd=home,
                env=child_env,
                creationflags=flags,
                start_new_session=not _IS_WIN and flags == 0,
            )
    except Exception:
        pass  # a failed dream must never break the session teardown
    return 0


if __name__ == "__main__":
    sys.exit(main())
