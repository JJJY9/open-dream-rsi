# Try it — no API key, no install

A quick, key-free walk of the whole loop. Commands assume the checkout
root; the install table for real agents lives in the README's
[Quick start](../README.md#quick-start).

From a fresh clone, two commands show the whole loop on your machine. The
demo spins up a mock OpenAI server in-process, so nothing leaves your laptop:

```bash
git clone https://github.com/patrykorwat/open-dream-rsi.git
cd open-dream-rsi
python examples/live_loop_demo.py          # full dream cycle, ~10 s
python -m open_dream_rsi bench --cycles 10 --markdown   # deterministic self-check
```

The demo solves one task against a mock model that *fails on purpose* the
first time, records the failure into a Discovery Tree, "dreams" over the
recorded history between cycles, and reuses the verified fix afterwards —
watch the cycle lines: the first cycle pays the failure tax (6 API calls),
every later cycle solves from memory in 3. The benchmark prints the
cold-baseline comparison (53% fewer calls at equal solve quality, re-run on
every commit in CI).

**Then point it at a real model** — any OpenAI-compatible endpoint, keys from
the environment only, model name auto-detected: see [Quick start](../README.md#quick-start).

## Docker

The sandbox already runs generated code as a `python -I` subprocess with a
scrubbed environment and resource limits. The image wraps the whole system in
a non-root, version-pinned environment so reproducibility is free; for a
stronger sandbox jail, install `bubblewrap` in a derived image and point
`ODR_SANDBOX_CMD` at it (see the Security model section):

```bash
docker build -t open-dream-rsi .
docker run --rm open-dream-rsi status
# journal + artifacts persist in a mounted volume:
docker run --rm --mount type=bind,src=$PWD/.dream_rsi,dst=/work/.dream_rsi \
  open-dream-rsi loop --tasks tasks.json
```

CI builds this image on every push.
