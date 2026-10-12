#!/usr/bin/env python3
"""Cursor postToolUse / postToolUseFailure hook -> ODR Sentinel recurrence notes.

Reads one Cursor hook event (JSON on stdin), feeds the tool result into the
ODR sentinel engine, and — when the same error class recurs — prints a
Cursor-format response that injects the note as additional context:

    {"additional_context": "[Sentinel] ..."}

Nothing on stdout means "no note, continue normally"; the hook never blocks
a tool call and always exits 0 (a broken hook must never break the agent).

Where the ODR checkout / memory dir come from (first match wins):
  1. --home / --memory argv (what the installer writes into hooks.json)
  2. ODR_HOME / ODR_MEMORY environment
  3. the current working directory, when it is the ODR repo root
     (project hooks run from the project root — opening the ODR repo as
     the workspace makes this hook work with zero configuration)
"""

import argparse
import json
import os
import sys
from pathlib import Path


def _repo_root_from_cwd() -> "str | None":
    cwd = Path.cwd()
    return str(cwd) if (cwd / "open_dream_rsi" / "sentinel.py").exists() else None


def _resolve(argv: "list[str] | None") -> "tuple[str, str] | None":
    args = argv if argv is not None else sys.argv[1:]
    ns = argparse.ArgumentParser(add_help=False)
    ns.add_argument("--home", default=None)
    ns.add_argument("--memory", default=None)
    opts, _ = ns.parse_known_args(args)
    home = opts.home or os.environ.get("ODR_HOME") or _repo_root_from_cwd()
    if not home:
        return None
    memory = opts.memory or os.environ.get("ODR_MEMORY") \
        or str(Path(home) / ".dream_rsi")
    return home, memory


def _engine(home: str, memory: str):
    """Import the sentinel engine from the configured ODR checkout."""
    if home not in sys.path:
        sys.path.insert(0, home)
    try:
        from open_dream_rsi.sentinel import SentinelEngine
    except Exception:
        return None
    state = Path(memory) / "sentinel_state.json"
    try:
        return SentinelEngine(state_path=state)
    except Exception:
        return None


def main(argv: "list[str] | None" = None) -> int:
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict):
            event = {}
    except Exception:
        event = {}

    resolved = _resolve(argv)
    if resolved is None:  # unconfigured: degrade silently
        return 0
    engine = _engine(*resolved)
    if engine is None:
        return 0

    tool = str(event.get("tool_name") or event.get("tool") or "?")
    result = event.get("tool_output")
    if result is None:
        result = event.get("result", event.get("tool_response"))
    if not isinstance(result, str):
        result = json.dumps(result, default=str) if result is not None else ""
    # A per-workspace stable key (the cwd) keeps recurrence counting
    # session-shaped even where Cursor exposes no session id.
    session = str(event.get("session_id") or event.get("conversation_id")
                  or event.get("cwd") or "default")
    failed = (event.get("hook_event_name") == "postToolUseFailure")
    try:
        note = engine.observe(tool, result, session,
                              status="error" if failed else None,
                              error_message=result if failed else None)
    except Exception:
        return 0
    if note:
        print(json.dumps({"additional_context": note.strip()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
