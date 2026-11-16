// OpenRouter Generate: shows the last run's cost and the remaining balance,
// with "refresh balance" and "refresh models" buttons. Plain JS, no build step.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE = "OpenRouterGenerate";
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
    }
  } catch (err) {
    shared.balance = `Models: error (${err.message || err})`;
  }
  redraw();
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
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated?.apply(this, arguments);
      // Added after the real widgets and not serialized, so saved workflows keep
      // their widget order.
      this.addCustomWidget(statusWidget(this));
      const balanceBtn = this.addWidget("button", "refresh balance", null, () => loadBalance());
      const modelsBtn = this.addWidget("button", "refresh models", null, () => refreshModels());
      for (const w of [balanceBtn, modelsBtn]) {
        w.serialize = false;
        w.options = { ...(w.options || {}), serialize: false };
      }
      return result;
    };

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
