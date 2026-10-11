// dsh-open-dream-rsi bridge: publishes where the vendored ODR Python server
// lives, so the mcp-client row can spawn it without pip or PYTHONPATH.
// The vendored Python sources (open_dream_rsi/) ship inside this npm package.
const name = "odr-bundle-paths";

const ENV_KEYS = [
  "OPENAI_BASE_URL",
  "OPENAI_API_KEY",
  "ODR_LLM_MODEL",
  "ODR_LLM_PRESET",
  "ODR_LLM_NO_THINKING",
  "PYTHONPATH",
];

// DSH scrubs the spawned child's environment (KEY|PASSWORD|SECRET|TOKEN and
// DSH_*); re-pass only the LLM-resolution vars that are actually SET. An
// empty ODR_LLM_PRESET="" must never reach the child: older ODR releases
// fed it straight into from_preset() and died with "Unknown preset ''",
// and current releases treat "" as unset — omitting the key is correct for
// both. Without OPENAI_* the dreamer falls back to the local
// vLLM/Ollama default (http://127.0.0.1:8000/v1, model auto-detection).
function childEnv() {
  const env = {};
  for (const key of ENV_KEYS) {
    if (process.env[key]) env[key] = process.env[key];
  }
  return env;
}

function apply(ctx) {
  ctx.provide("odrBundle", {
    python: "python3",
    runner: import.meta.dirname + "/run_mcp.py",
    childEnv,
  });
}

export { name, apply };
