// dsh-open-dream-rsi bridge: publishes where the vendored ODR Python server
// lives AND acts as the dreamer's brain. The Python child has no idea how to
// reach an LLM — and it must not need one: this bridge runs a tiny
// OpenAI-compatible HTTP proxy INSIDE the harness process and forwards every
// ODR LLM call to the model the harness itself is configured with, through
// the dsh-llm service (ctx.llm.stream). The child only sees
// OPENAI_BASE_URL=http://127.0.0.1:<port>/v1 (plus a dummy key, because ODR
// refuses to call an endpoint without one) and auto-detects the model via
// GET /v1/models. No API keys, no presets, nothing installed alongside.
// Escape hatch: if the harness process already has a real OPENAI_BASE_URL
// set, the child is pointed there directly and the proxy stays idle.
// Zero npm dependencies: node stdlib only.
import http from "node:http";
import { randomUUID } from "node:crypto";

const name = "odr-bundle-paths";

const ENV_KEYS = ["OPENAI_BASE_URL", "OPENAI_API_KEY", "ODR_LLM_MODEL", "ODR_LLM_PRESET", "ODR_LLM_NO_THINKING", "PYTHONPATH"];

const state = { port: 0, provider: null, model: null, ctx: null };

// The server listens from import time, so the port is known long before any
// config materialization can ask childEnv() for it.
const server = http.createServer((req, res) => { handle(req, res).catch(() => {}); });
server.unref();
server.requestTimeout = 0; // dream-cycle completions can run for minutes
server.listen(0, "127.0.0.1", () => { state.port = server.address().port; });

// DSH scrubs the spawned child's inherited environment (names matching
// KEY|PASSWORD|SECRET|TOKEN and all DSH_*), so the LLM vars must be re-passed
// explicitly — but only when actually set: an empty ODR_LLM_PRESET="" must
// never reach the child (older ODR releases fed it into from_preset() and
// died with "Unknown preset ''"; Node spawn passes '' through but omits
// undefined).
function childEnv() {
  const env = {};
  for (const key of ENV_KEYS) {
    if (process.env[key]) env[key] = process.env[key];
  }
  if (!env.OPENAI_BASE_URL) {
    if (!state.port) throw new Error("odr bridge proxy is not listening yet");
    // Proxy mode: the harness's own model is the brain. The dummy key only
    // satisfies ODR's non-empty-credential check; the proxy ignores it.
    env.OPENAI_BASE_URL = `http://127.0.0.1:${state.port}/v1`;
    env.OPENAI_API_KEY = "dsh-bridge";
    delete env.ODR_LLM_PRESET;
  }
  return env;
}

// Resolve the route once per process, in order of intent: ODR_LLM_MODEL pins
// the model; otherwise the harness's own agent default route
// (ctx.agentDefaultModel — "the model this harness is configured with");
// otherwise the first registered provider plus its first catalog model.
async function pickRoute() {
  if (state.model) return { provider: state.provider, model: state.model };
  if (!state.ctx?.llm) {
    throw new Error("dsh-llm service is not available on the plugin context");
  }
  let provider = null;
  const fallback = state.ctx.agentDefaultModel;
  if (fallback) {
    provider = (await fallback.provider) ?? null;
  }
  if (!provider) {
    const providers = await state.ctx.llm.listProviders();
    if (!providers.length) {
      throw new Error(
        "no LLM provider is registered in the harness (ctx.llm.listProviders() is empty) — "
        + "configure a model in DSH settings, or export OPENAI_BASE_URL before starting dsh "
        + "to point ODR at an endpoint directly",
      );
    }
    provider = providers[0].id;
  }
  let model = null;
  const wanted = process.env.ODR_LLM_MODEL;
  if (wanted) {
    model = wanted;
  } else if (fallback) {
    model = (await fallback.model) ?? null;
  }
  if (!model) {
    const models = await state.ctx.llm.listModels(provider).catch(() => []);
    model = models[0]?.id ?? null;
  }
  if (!model) {
    throw new Error(
      `cannot resolve a model for provider "${provider}" — the adapter publishes no model `
      + "catalog. Set ODR_LLM_MODEL=<id> before starting dsh, or configure a model in DSH settings.",
    );
  }
  state.provider = provider;
  state.model = model;
  return { provider, model };
}

// ODR sends plain string content; dsh-llm wants text content blocks. Unknown
// roles are dropped; system messages are folded into options.system.
function mapMessages(messages) {
  const out = [];
  const system = [];
  for (const msg of messages ?? []) {
    const text = typeof msg.content === "string"
      ? msg.content
      : (msg.content ?? []).map((b) => (typeof b === "string" ? b : b?.text ?? "")).join("");
    if (msg.role === "system") { system.push(text); continue; }
    if (msg.role === "user") out.push({ role: "user", content: [{ type: "text", text }] });
    else if (msg.role === "assistant") out.push({ role: "assistant", content: [{ type: "text", text }] });
  }
  return { system: system.join("\n\n"), messages: out };
}

// One ODR chat call, served from the harness's own LLM service. Assistant
// history entries are plain objects (id/source omitted): the adapters only
// map role+content onto the provider call; no dsh-llm import is needed, so
// the bundle stays dependency-free.
async function chatCompletion(body, signal) {
  const { model } = await pickRoute();
  if (!model) {
    return { status: 503, body: { error: { message: `no models are listed for provider "${state.provider}" in the harness`, type: "bridge_no_models" } } };
  }
  const { system, messages } = mapMessages(body.messages);
  const options = {
    provider: state.provider,
    model,
    messages,
    temperature: body.temperature,
    maxTokens: body.max_tokens,
  };
  if (system) options.system = system;
  if (signal) options.signal = signal;
  let text = "";
  let finish = null;
  for await (const chunk of state.ctx.llm.stream(options)) {
    if (chunk.type === "text-delta") text += chunk.text;
    else if (chunk.type === "finish") finish = chunk.finish;
  }
  const kind = finish?.kind ?? "stop";
  if (kind === "error" || kind === "aborted") {
    const message = finish?.failure?.message ?? `LLM stream ended with "${kind}"`;
    return { status: 502, body: { error: { message: `dsh llm: ${message}`, type: "bridge_llm_failure" } } };
  }
  if (kind === "tool-calls") {
    return { status: 502, body: { error: { message: "dsh llm: model requested tools, but ODR calls are tool-less", type: "bridge_tool_calls" } } };
  }
  return {
    status: 200,
    body: {
      id: `chatcmpl-${randomUUID()}`,
      object: "chat.completion",
      model,
      choices: [{
        index: 0,
        message: { role: "assistant", content: text },
        finish_reason: kind === "max-tokens" ? "length" : "stop",
      }],
    },
  };
}

async function listModelsResponse() {
  const { model } = await pickRoute();
  if (!model) {
    return { status: 503, body: { error: { message: `no models are listed for provider "${state.provider}" in the harness`, type: "bridge_no_models" } } };
  }
  return { status: 200, body: { object: "list", data: [{ id: model, object: "model", owned_by: "dsh" }] } };
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > 16 * 1024 * 1024) { reject(new Error("request body too large")); req.destroy(); return; }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

async function handle(req, res) {
  if (!state.ctx) {
    res.writeHead(503, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { message: "odr bridge is not attached to the harness context yet" } }));
    return;
  }
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const abort = new AbortController();
  req.on("close", () => { if (!res.writableEnded) abort.abort(); });
  try {
    let out;
    if (req.method === "GET" && url.pathname === "/v1/models") out = await listModelsResponse();
    else if (req.method === "POST" && url.pathname === "/v1/chat/completions") {
      let body;
      try { body = JSON.parse(await readBody(req)); } catch { throw new Error("invalid JSON body"); }
      out = await chatCompletion(body, abort.signal);
    } else {
      out = { status: 404, body: { error: { message: `unsupported ${req.method} ${url.pathname}` } } };
    }
    res.writeHead(out.status, { "content-type": "application/json" });
    res.end(JSON.stringify(out.body));
  } catch (error) {
    res.writeHead(500, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: { message: String(error?.message ?? error), type: "bridge_error" } }));
  }
}

function apply(ctx) {
  state.ctx = ctx;
  ctx.provide("odrBundle", {
    python: "python3",
    runner: import.meta.dirname + "/run_mcp.py",
    childEnv,
  });
}

export { name, apply, childEnv, chatCompletion, listModelsResponse, mapMessages, pickRoute, server, state };
