#!/usr/bin/env python3
"""Entry point for the vendored ODR MCP server (npm bundle dsh-open-dream-rsi).

Puts this package's root on sys.path so ``open_dream_rsi`` imports without
pip or PYTHONPATH. Requires only a Python 3.10+ interpreter on PATH (ODR is
stdlib-only: dependencies = []).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from open_dream_rsi.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
