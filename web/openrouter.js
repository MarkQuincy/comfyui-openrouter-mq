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
        if (node.type === "OpenRouterVideo") loadVideoInfo(node);
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

// Speak node: the "language" widget narrows the model dropdown to models that suit the
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

// The Speak node's own "language" widget (saved with the workflow) filters the model list.
function hookLanguage(node) {
  const lang = node.widgets?.find((w) => w.name === "language");
  if (!lang) return;
  const callback = lang.callback;
  lang.callback = function (value) {
    const r = callback?.apply(this, arguments);
    applyLanguage(node, value);
    return r;
  };
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

// Video node: allowed lengths/resolutions of the selected model and a price estimate.
// OpenRouter gives prices without a unit; video models are priced per second
// (e.g. Seedance), so the estimate is price x duration and says so.
function videoLines(node) {
  const d = node.openrouterVideo;
  if (!d) return ["Model info: loading…"];
  const durs = d.durations.filter((x) => x > 0);
  const contiguous = durs.length > 2 && durs[durs.length - 1] - durs[0] === durs.length - 1;
  const lengths = !durs.length ? "not listed"
    : contiguous ? `${durs[0]}–${durs[durs.length - 1]} s` : durs.join(", ") + " s";
  const auto = d.durations.includes(-1) ? " (or auto)" : "";
  const res = d.resolutions.length ? d.resolutions.join(", ") : "resolutions not listed";
  const lines = [`Lengths: ${lengths}${auto} · ${res}`];
  const prices = Object.values(d.prices);
  if (!prices.length) return [...lines, "Price: not listed for this model"];
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const range = (a, b) => (a === b ? `$${a.toFixed(4)}` : `$${a.toFixed(4)}–$${b.toFixed(4)}`);
  const tiers = prices.length > 1 ? ` (${prices.length} tiers)` : "";
  lines.push(`Price: ${range(lo, hi)} per s${tiers}`);
  const secs = node.widgets?.find((w) => w.name === "duration")?.value || 0;
  lines.push(secs > 0 ? `Estimate for ${secs} s: ≈ ${range(lo * secs, hi * secs)}`
    : "Duration 0 = model default: set seconds for an estimate");
  return lines;
}

function videoInfoWidget(node) {
  return {
    name: "openrouter_video_info",
    type: "openrouter_video_info",
    value: "",
    serialize: false,
    options: { serialize: false },
    computeSize(width) {
      return [width, 16 * videoLines(node).length + 6];
    },
    draw(ctx, _node, width, y) {
      ctx.save();
      ctx.font = "12px sans-serif";
      ctx.fillStyle = globalThis.LiteGraph?.WIDGET_TEXT_COLOR || "#ddd";
      ctx.textAlign = "left";
      videoLines(node).forEach((line, i) => ctx.fillText(line, 15, y + 14 + 16 * i, width - 30));
      ctx.restore();
    },
  };
}

async function loadVideoInfo(node) {
  const model = node.widgets?.find((w) => w.name === "model")?.value;
  if (!model) return;
  try {
    const url = `/openrouter/video_model?model=${encodeURIComponent(model)}`;
    node.openrouterVideo = await (await api.fetchApi(url)).json();
    const durs = node.openrouterVideo.durations.filter((x) => x > 0);
    const duration = node.widgets.find((w) => w.name === "duration");
    if (duration && durs.length) {
      duration.options = { ...duration.options, max: durs[durs.length - 1] };
      if (duration.value !== 0 && !durs.includes(duration.value)) {
        // Nearest allowed length, so the estimate matches what will be sent.
        duration.value = durs.reduce((a, b) =>
          Math.abs(b - duration.value) < Math.abs(a - duration.value) ? b : a);
      }
    }
  } catch (err) {
    node.openrouterVideo = { durations: [], resolutions: [], aspect_ratios: [], prices: {} };
  }
  node.setSize([node.size[0], node.computeSize()[1]]);
  redraw();
}

function hookVideo(node) {
  for (const name of ["model", "duration"]) {
    const w = node.widgets?.find((x) => x.name === name);
    if (!w) continue;
    const callback = w.callback;
    w.callback = function () {
      const r = callback?.apply(this, arguments);
      if (name === "model") loadVideoInfo(node);
      else redraw();
      return r;
    };
  }
  node.addCustomWidget(videoInfoWidget(node));
  setTimeout(() => loadVideoInfo(node), 0);
}

// Cost Report node: draws the report text on the node after each run.
function reportWidget(node) {
  return {
    name: "openrouter_report",
    type: "openrouter_report",
    value: "",
    serialize: false,
    options: { serialize: false },
    computeSize(width) {
      const lines = (node.openrouterReport || "Run to see the report.").split("\n");
      return [width, 16 * lines.length + 8];
    },
    draw(ctx, _node, width, y) {
      ctx.save();
      ctx.font = "12px monospace";
      ctx.fillStyle = globalThis.LiteGraph?.WIDGET_TEXT_COLOR || "#ddd";
      ctx.textAlign = "left";
      const lines = (node.openrouterReport || "Run to see the report.").split("\n");
      lines.forEach((line, i) => ctx.fillText(line, 15, y + 14 + 16 * i, width - 30));
      ctx.restore();
    },
  };
}

app.registerExtension({
  name: "comfyui-openrouter.report",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "OpenRouterCostReport") return;
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = onNodeCreated?.apply(this, arguments);
      this.addCustomWidget(reportWidget(this));
      return r;
    };
    const onExecuted = nodeType.prototype.onExecuted;
    nodeType.prototype.onExecuted = function (message) {
      onExecuted?.apply(this, arguments);
      const text = message?.openrouter_report?.[0];
      if (text) {
        this.openrouterReport = text;
        this.setSize([this.size[0], this.computeSize()[1]]);
        redraw();
      }
    };
  },
});

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
        hookLanguage(this);
        addVoicePicker(this);
      }
      if (nodeData.name === "OpenRouterVideo") hookVideo(this);
      this.addCustomWidget(statusWidget(this));
      const balanceBtn = this.addWidget("button", "refresh balance", null, () => loadBalance());
      const modelsBtn = this.addWidget("button", "refresh models", null, () => refreshModels());
      for (const w of [balanceBtn, modelsBtn]) {
        w.serialize = false;
        w.options = { ...(w.options || {}), serialize: false };
      }
      return result;
    };

    if (nodeData.name === "OpenRouterVideo") {
      const onConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        const r = onConfigure?.apply(this, arguments);
        loadVideoInfo(this); // a loaded workflow sets the model after creation
        return r;
      };
    }

    if (nodeData.name === "OpenRouterSpeak") {
      const onConfigure = nodeType.prototype.onConfigure;
      nodeType.prototype.onConfigure = function () {
        const r = onConfigure?.apply(this, arguments);
        // A loaded workflow sets language/model after creation: re-apply the filter.
        const lang = this.widgets?.find((w) => w.name === "language")?.value;
        if (lang && lang !== "All languages") applyLanguage(this, lang);
        else loadVoices(this);
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
