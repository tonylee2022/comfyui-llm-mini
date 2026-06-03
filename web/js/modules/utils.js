import { api } from "../../../../scripts/api.js";

export function currentLocale() {
  return localStorage["AGL.Locale"] || localStorage["Comfy.Settings.AGL.Locale"] || "en-US";
}

export function isChineseLocale() {
  return currentLocale().toLowerCase().startsWith("zh");
}

export function t(en, zh) {
  return isChineseLocale() ? zh : en;
}

export function findWidget(node, name) {
  return node.widgets ? node.widgets.find((w) => w.name === name) : null;
}

export function widgetValue(node, name) {
  const widget = findWidget(node, name);
  return widget ? widget.value || "" : "";
}

export function updateCombo(node, name, values) {
  const widget = findWidget(node, name);
  if (!widget || !values || !values.length) return false;
  widget.type = "combo";
  widget.options = widget.options || {};
  widget.options.values = values;
  const oldValue = widget.value;
  if (!values.includes(widget.value)) {
    widget.value = values[0];
  }
  if (widget.callback && widget.value !== oldValue) {
    widget.callback(widget.value);
  }
  node.setDirtyCanvas(true, true);
  if (node.graph) node.graph.setDirtyCanvas(true, true);
  return true;
}

export async function fetchProviderInfo() {
  const response = await api.fetchApi("/llm-mini/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) return [];
  const data = await response.json();
  return data.providers || [];
}

export function updateCredentialSourcesAndModels(node, providers) {
  const provider = widgetValue(node, "provider");
  const info = providers.find((item) => item.id === provider);
  if (!info) return;
  if (info.default_models && info.default_models.length) {
    updateCombo(node, "model_name", info.default_models);
  }
}

export async function refreshProviderWidgets(node) {
  try {
    const providers = await fetchProviderInfo();
    const providerIds = providers.map((item) => item.id).filter(Boolean);
    updateCombo(node, "provider", providerIds);
    updateCredentialSourcesAndModels(node, providers);
    const providerWidget = findWidget(node, "provider");
    if (providerWidget) {
      const originalCallback = providerWidget.callback;
      providerWidget.callback = function () {
        if (originalCallback) originalCallback.apply(this, arguments);
        updateCredentialSourcesAndModels(node, providers);
      };
    }
  } catch (error) {
    console.warn("LLM Mini provider refresh failed:", error);
  }
}

export function removeRefreshButtons(node) {
  if (!node.widgets) return;
  for (let i = node.widgets.length - 1; i >= 0; i--) {
    const w = node.widgets[i];
    if (w.type === "button" && (w.name === "Refresh Models" || w.name === "刷新模型")) node.widgets.splice(i, 1);
  }
}

export function addRefreshButton(node) {
  removeRefreshButtons(node);
  const label = t("Refresh Models", "刷新模型");
  node.addWidget("button", label, label, async () => {
    const provider = widgetValue(node, "provider") || "openai";
    try {
      const response = await api.fetchApi("/llm-mini/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (!data.models || data.models.length === 0) throw new Error(t("No models returned.", "没有返回可用模型。"));
      updateCombo(node, "model_name", data.models);
      if (!data.has_credentials && provider !== "ollama") {
        alert(t("Models loaded from defaults. Add credentials to fetch live provider models.", "已加载默认模型。请添加凭据以获取实时模型列表。"));
      }
    } catch (error) {
      alert(`LLM Mini: ${error.message}`);
    }
  });
  node.setSize(node.computeSize());
}
