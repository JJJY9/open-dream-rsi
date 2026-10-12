# open-dream-rsi — Cursor integration without MCP

Cursor instances where **MCP servers are blocked by policy** can still run
the Dream-RSI loop: hooks and rules are a separate surface, and everything
the loop needs travels through files (`tasks.json`, the memory dir), never
through MCP.

> **Not a Cursor Plugin.** There is no `.cursor-plugin/plugin.json` in this
> repository, so Cursor's "From github repository" import loads nothing
> here — install by running `install.py` from your checkout.

```
plugins/cursor/
├── install.py                     one command: wires hooks + rule
└── hooks/
    ├── odr_sentinel_hook.py       postToolUse/postToolUseFailure → sentinel notes
    └── odr_dream_hook.py          sessionEnd → detached dream cycle
```

## Install (in the open-dream-rsi checkout)

```bash
python plugins/cursor/install.py
# optional: --memory D:/odr-mem --python C:\path\venv\Scripts\python.exe
```

The installer:

1. merges the three hook entries into `~/.cursor/hooks.json`
   (existing entries preserved; idempotent on re-run),
2. writes the agent rule to `<repo>/.cursor/rules/odr-no-mcp.mdc`
   (project rules apply while the repo is the open workspace; copy the
   `.mdc` into other projects' `.cursor/rules/` as needed — pass
   `--rules-dir` to place it elsewhere),
3. creates the memory dir with an empty `tasks.json`.

It never touches `mcp.json`. Restart Cursor afterwards (hooks config is
watched and reloaded, but a restart is the reliable first activation).

## What runs where

| Moment | What happens |
|---|---|
| A tool call fails the same way twice | `odr_sentinel_hook.py` injects a `[Sentinel]` recurrence note as additional context |
| A session ends | `odr_dream_hook.py` detaches `python -m open_dream_rsi dream --source cursor` — it imports Cursor chats as evidence, runs the lesson gate, publishes earned knowledge |
| You (or the agent, via the rule) queue work | `python -m open_dream_rsi task add --id … --category … --prompt … --criteria …` appends to `<memory>/tasks.json` |
| The dream cycle runs | queued tasks are attempted, successes become recipes/policies, candidates face the replay gate |

The dreamer's LLM comes from the environment the hook inherits
(`OPENAI_BASE_URL` / `ODR_LLM_PRESET=cursor` / `ODR_LLM_MODEL` — any
OpenAI-compatible endpoint). Cadence and budget live inside the `dream`
module; firing on every session end is safe.

## Requirements

* Cursor with hooks support (Cursor 2.4+ for `postToolUse`; `sessionEnd`
  fired on conversation end),
* the open-dream-rsi checkout importable by the interpreter passed via
  `--python` (or the default `sys.executable`),
* no admin approval beyond hooks: project/user hooks are a user-level
  feature (Enterprise-managed hooks exist but are optional).

## Uninstall

Remove the three entries whose command references
`plugins/cursor/hooks/` from `~/.cursor/hooks.json`, delete
`~/.cursor/rules/odr-no-mcp.mdc`, and stop the (optional) dream loop by
removing the hook file.
