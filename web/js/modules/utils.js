import { api } from "../../../../scripts/api.js";

export function currentLocale() {
  return localStorage["AGL.Locale"] || 
         localStorage["Comfy.Settings.AGL.Locale"] || 
         localStorage["Comfy.Locale"] || 
         localStorage["Comfy.Settings.Comfy.Locale"] || 
         navigator.language || 
         "en-US";
}

export function isChineseLocale() {
  const locale = currentLocale();
  return locale.toLowerCase().startsWith("zh");
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
  if (!widget || !Array.isArray(values)) return false;
  widget.type = "combo";
  
  widget.options = widget.options || {};
  if (!widget.options.values) {
    widget.options.values = [];
  }
  
  // Vue 响应式安全修复：通过清空并 push 来进行“就地修改”（In-place mutation）
  // 这样可以保留 Vue 3 的 Proxy 代理对象，同时触发数组变动监听，避免直接覆盖引用导致响应式失效
  widget.options.values.length = 0;
  widget.options.values.push(...values);
  
  const oldValue = widget.value;
  if (!values.includes(widget.value)) {
    widget.value = values[0] || "";
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
    const providers = (await fetchProviderInfo()).filter((item) => item.chat_available);
    const providerIds = providers.map((item) => item.id).filter(Boolean);
    updateCombo(node, "provider", providerIds);
    if (providerIds.length) {
      updateCredentialSourcesAndModels(node, providers);
    } else {
      updateCombo(node, "model_name", []);
    }
    const providerWidget = findWidget(node, "provider");
    if (providerWidget) {
      providerWidget.__llmMiniProviders = providers;
      if (!Object.prototype.hasOwnProperty.call(providerWidget, "__llmMiniOriginalCallback")) {
        providerWidget.__llmMiniOriginalCallback = providerWidget.callback;
        providerWidget.callback = function () {
          if (this.__llmMiniOriginalCallback) this.__llmMiniOriginalCallback.apply(this, arguments);
          updateCredentialSourcesAndModels(node, this.__llmMiniProviders || []);
        };
      }
    }
  } catch (error) {
    console.warn("LLM Mini provider refresh failed:", error);
  }
}
