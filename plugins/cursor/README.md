# open-dream-rsi — Cursor integration without MCP

Cursor instances where **MCP servers are blocked by policy** can still run
the Dream-RSI loop: hooks and rules are a separate surface, and everything
the loop needs travels through files (`tasks.json`, the memory dir), never
through MCP.

> **Two install paths — pick ONE.** Since 0.3.0 the repository root carries
> a `.cursor-plugin/plugin.json` manifest, so Cursor's **"From github
> repository"** import loads the hooks and the rule (plugin copies run from
> Cursor's plugin store; hook scripts then resolve the ODR checkout via
> `ODR_HOME` / the workspace cwd / `~/open-dream-rsi`). The pinned, explicit
> path is the installer below: it writes absolute paths into
> `~/.cursor/hooks.json` and is the recommended route on Windows. Running
> both is wasteful (duplicate hook fires; the dream lock collapses the
> second cycle, but the sentinel runs twice).

```
.cursor-plugin/plugin.json         Cursor Plugin manifest (GitHub import)
hooks/
├── hooks.json                     plugin wiring (relative paths, || exit 0 guards)
├── odr_sentinel_hook.py           postToolUse/postToolUseFailure → sentinel notes
└── odr_dream_hook.py              sessionEnd → detached dream cycle
rules/odr-no-mcp.mdc               agent rule (plugin auto-discovery)
plugins/cursor/install.py          one command: hooks (absolute paths) + rule
```

## Dreamer brain (default: cursor-agent — no proxy, no API key)

Since 0.3.0 the default dreamer is the **Cursor Agent CLI** headless turn
(`cursor-agent -p --force --output-format text`), authenticated by the
user's own Cursor login. No OpenAI-compatible proxy, no API key, no
endpoint to configure; the model is whatever the user's Cursor uses
(override: `--model` or `ODR_LLM_MODEL`). A machine without the CLI stays
safe: every client failure defers the session (stays unseen) instead of
burning evidence. Other providers still work:
`--provider openai|cursor|local|goose` (+ `--env-file` for
`OPENAI_BASE_URL` / `OPENAI_API_KEY` / `ODR_LLM_MODEL` — keys stay out of
the command line).

## Install (in the open-dream-rsi checkout)

```bash
python plugins/cursor/install.py
# options: --memory D:/odr-mem  --python C:\path\venv\Scripts\python.exe
#          --provider cursor-agent (default) | openai | local | goose
#          --env-file C:\Users\me\odr-env.list
```

The installer:

1. merges the three hook entries into `~/.cursor/hooks.json`
   (existing entries preserved; a 0.2.x-style entry pointing at the old
   `plugins/cursor/hooks/` location is re-pointed in place; idempotent),
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
| A session ends | `odr_dream_hook.py` detaches `python -m open_dream_rsi dream --source cursor` — Cursor chats are the evidence (state.vscdb read directly), cursor-agent (or the configured endpoint) is the brain |
| You (or the agent, via the rule) queue work | `python -m open_dream_rsi task add --id … --category … --prompt … --criteria …` appends to `<memory>/tasks.json` |
| The dream cycle runs | queued tasks are attempted, successes become recipes/policies, candidates face the replay gate |

## Requirements

* Cursor with hooks support (Cursor 2.4+ for `postToolUse`; `sessionEnd`
  fired on conversation end),
* for the default brain: the `cursor-agent` CLI on PATH (Cursor CLI,
  authenticated by your Cursor login; Windows npm shims — `.cmd` — are
  wrapped automatically). Any OpenAI-compatible endpoint works instead via
  `--provider` + `--env-file`,
* the open-dream-rsi checkout importable by the interpreter passed via
  `--python` (or the default `sys.executable`),
* no admin approval beyond hooks: project/user hooks are a user-level
  feature (Enterprise-managed hooks exist but are optional).

## Uninstall

Remove the three entries whose command references `odr_sentinel_hook.py` /
`odr_dream_hook.py` from `~/.cursor/hooks.json`, delete
`<repo>/.cursor/rules/odr-no-mcp.mdc`, and uninstall the plugin in
Customize if it was imported from GitHub.
