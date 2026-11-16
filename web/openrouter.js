// OpenRouter Generate: shows the last run's cost and the remaining balance,
// with "refresh balance" and "refresh models" buttons. Plain JS, no build step.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODES = ["OpenRouterGenerate", "OpenRouterSpeak", "OpenRouterVideo"];
const shared = { balance: "Balance: not loaded", pending: null };

function money(value, digits = 2) {
  return typeof value === "number" ? `$${value.toFixed(digits)}` : "?";
}

function formatBalance(data) {
  const parts = [];
  if (data.key) {
    const left = data.key.limit_remaining;
    parts.push(left === null || left === undefined ? "Key: no limit" : `Key left: ${money(left)}`);
  }
  if (data.credits) parts.push(`Account: ${money(data.credits.remaining)}`);
  if (data.errors && data.errors.length) parts.push(`Error: ${data.errors[0]}`);
  return parts.join("  ·  ") || "Balance: unavailable";
}

function redraw() {
  app.graph?.setDirtyCanvas(true, true);
}

// One request at a time, shared by all Generate nodes.
function loadBalance() {
  if (shared.pending) return shared.pending;
  shared.balance = "Balance: loading…";
  redraw();
  shared.pending = api
    .fetchApi("/openrouter/balance")
    .then((r) => r.json())
    .then((data) => { shared.balance = formatBalance(data); })
    .catch((err) => { shared.balance = `Balance: error (${err.message || err})`; })
    .finally(() => { shared.pending = null; redraw(); });
  return shared.pending;
}

async function refreshModels() {
  shared.balance = "Refreshing model list…";
  redraw();
  try {
    const data = await (await api.fetchApi("/openrouter/refresh_models", { method: "POST" })).json();
    if (data.error) {
      shared.balance = `Models: ${data.error}`;
    } else {
      shared.balance = `Models: ${data.count} loaded`;
      if (app.refreshComboInNodes) await app.refreshComboInNodes();
      for (const node of app.graph?._nodes || []) {
        if (node.type === "OpenRouterSpeak") loadVoices(node);
      }
    }
  } catch (err) {
    shared.balance = `Models: error (${err.message || err})`;
  }
  redraw();
}

// Speak node: a "voice list" dropdown for the selected model. Picking an entry fills
// the "voice" text widget (the saved value); the list itself is not serialized.
async function loadVoices(node) {
  const model = node.widgets?.find((w) => w.name === "model")?.value;
  const picker = node.widgets?.find((w) => w.name === "voice list");
  if (!model || !picker) return;
  try {
    const url = `/openrouter/voices?model=${encodeURIComponent(model)}`;
    const data = await (await api.fetchApi(url)).json();
    picker.options.values = data.labels;
    node.openrouterVoiceIds = Object.fromEntries(data.labels.map((l, i) => [l, data.ids[i]]));
    const voice = node.widgets.find((w) => w.name === "voice")?.value || "";
    picker.value = data.labels[data.ids.indexOf(voice)] ?? data.labels[0];
  } catch (err) {
    picker.options.values = ["(voices unavailable)"];
  }
  redraw();
}

// Speak node: "language filter" narrows the model dropdown to models that suit the
// language (data from the server: description words + user/languages.json).
async function applyLanguage(node, code) {
  const model = node.widgets?.find((w) => w.name === "model");
  if (!model) return;
  try {
    const url = `/openrouter/speech_models?language=${encodeURIComponent(code)}`;
    const data = await (await api.fetchApi(url)).json();
    const labels = data.labels.length ? data.labels : ["(no model for this language)"];
    model.options = { ...model.options, values: labels }; // own copy, not shared
    const bare = (s) => String(s).replace(" · multilingual", "").replace(/^★ /, "");
    const match = labels.find((l) => bare(l) === bare(model.value));
    model.value = match ?? labels[0];
    await loadVoices(node);
  } catch (err) {
    console.warn("[OpenRouter] language filter failed", err);
  }
  redraw();
}

async function addLanguagePicker(node) {
  const names = { "All languages": "all" };
  const picker = node.addWidget("combo", "language filter", "All languages",
    (name) => applyLanguage(node, names[name] || "all"),
    { values: ["All languages"], serialize: false });
  picker.serialize = false;
  try {
    const data = await (await api.fetchApi("/openrouter/speech_models?language=all")).json();
    for (const lang of data.languages) names[lang.name] = lang.code;
    picker.options.values = data.languages.map((l) => l.name);
  } catch (err) {
    console.warn("[OpenRouter] languages unavailable", err);
  }
}

function addVoicePicker(node) {
  const picker = node.addWidget("combo", "voice list", "(model default)", (label) => {
    const voice = node.widgets.find((w) => w.name === "voice");
    if (voice && node.openrouterVoiceIds && label in node.openrouterVoiceIds) {
      voice.value = node.openrouterVoiceIds[label];
    }
  }, { values: ["(model default)"], serialize: false });
  picker.serialize = false;
  const model = node.widgets.find((w) => w.name === "model");
  if (model) {
    const callback = model.callback;
    model.callback = function () {
      const r = callback?.apply(this, arguments);
      loadVoices(node);
      return r;
    };
  }
  setTimeout(() => loadVoices(node), 0);
}

function statusWidget(node) {
  return {
    name: "openrouter_status",
    type: "openrouter_status",
    value: "",
    serialize: false,
    options: { serialize: false },
    computeSize(width) {
      return [width, 40];
    },
    draw(ctx, _node, width, y) {
      ctx.save();
      ctx.font = "12px sans-serif";
      ctx.fillStyle = globalThis.LiteGraph?.WIDGET_SECONDARY_TEXT_COLOR || "#aaa";
      ctx.textAlign = "left";
      ctx.fillText(node.openrouterLast || "Last run: –", 15, y + 15, width - 30);
      ctx.fillText(shared.balance, 15, y + 32, width - 30);
      ctx.restore();
    },
  };
}

app.registerExtension({
  name: "comfyui-openrouter.generate",

  setup() {
    loadBalance();
  },

  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!NODES.includes(nodeData.name)) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated?.apply(this, arguments);
      // Added after the real widgets and not serialized, so saved workflows keep
      // their widget order.
      if (nodeData.name === "OpenRouterSpeak") {
        addLanguagePicker(this);
        addVoicePicker(this);
      }
      this.addCustomWidget(statusWidget(this));
      const balanceBtn = this.addWidget("button", "refresh balance", null, () => loadBalance());
      const modelsBtn = this.addWidget("button", "refresh models", null, () => refreshModels());
      for (const w of [balanceBtn, modelsBtn]) {
        w.serialize = false;
        w.options = { ...(w.options || {}), serialize: false };
      }
      return result;
    };

    if (nodeData.name === "OpenRouterSpeak") {
      const onConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        const r = onConfigure?.apply(this, arguments);
        loadVoices(this); // a loaded workflow sets the model after creation
        return r;
      };
    }

    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const run = message?.openrouter?.[0];
      if (run) {
        this.openrouterLast = `Last run: ${money(run.cost_usd, 4)}  ·  ${run.model}`;
        loadBalance();
      }
    };
  },
});
