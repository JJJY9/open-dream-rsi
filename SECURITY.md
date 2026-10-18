# Security Policy

## What runs where

Open Dream-RSI executes two kinds of **generated code**: task solutions and
LLM-written exploration policies. Both run in a hardened subprocess
(`open_dream_rsi/sandbox.py`):

- `python -I` (isolated mode) with a scrubbed environment — only `PATH` is
  passed, so **API keys never cross the sandbox wall**;
- a timeout that kills the **entire process group**;
- POSIX address-space / CPU / thread-count limits (`RLIMIT_AS/CPU/NPROC`).

Policy code additionally passes a static **AST gate** before any spawn:
required entry point, no imports, no dunder attribute access, and the name
`__builtins__` banned (constructed-key indexing of it is itself an escape
route — pinned by regression tests).

## What this is not

This is **defence in depth, not a container**. The subprocess does not
restrict filesystem or network access, and an AST gate cannot be provably
complete against code that was not statically gated. If you feed the loop
**hostile task sources**, wrap every spawn with `ODR_SANDBOX_CMD` (e.g.
[bubblewrap](https://github.com/containers/bubblewrap):
`bwrap --unshare-all --die-with-parent --ro-bind / /`) or run the loop inside
a container. When `ODR_SANDBOX_CMD` is unset, the sandbox logs a **one-time
warning** at the first spawn in each process, so the gap is visible in logs
instead of silent.

## The MCP server is a trust boundary

`python -m open_dream_rsi mcp` (stdio) trusts whoever can write to its
stdin. `--http` mode serves a plain HTTP endpoint: **anyone who can reach it
can queue tasks and spend your API budget.** Defaults bind loopback only.
Do not expose port 8800 to a network without authentication in front of it;
treat a tunnelled URL (cloudflared/tailscale funnel) as a credential.

## Credentials

Keys are read **only from the environment** (`OPENAI_API_KEY`,
`OPENAI_BASE_URL`, `ODR_LLM_MODEL`, `ODR_LLM_PRESET`). The library never
writes secrets into memory files, logs, or the event journal; session
ingestion scrubs credential-shaped tokens from transcripts.

## Reporting a vulnerability

Open a [security advisory](https://github.com/patrykorwat/open-dream-rsi/security/advisories/new)
rather than a public issue. Include the version (`python -m open_dream_rsi
--version` reports it via the installed package) and a reproduction.
