// dsh-open-dream-rsi bridge: publishes where the vendored ODR Python server
// lives, so the mcp-client row can spawn it without pip or PYTHONPATH.
// The vendored Python sources (open_dream_rsi/) ship inside this npm package.
const name = "odr-bundle-paths";

function apply(ctx) {
  ctx.provide("odrBundle", {
    python: "python3",
    runner: import.meta.dirname + "/run_mcp.py",
  });
}

export { name, apply };
