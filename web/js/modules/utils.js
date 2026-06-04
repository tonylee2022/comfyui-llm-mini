import { api } from "../../../../scripts/api.js";
import { showModelSelectionModal } from "./modal.js";

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
  const result = locale.toLowerCase().startsWith("zh");
  console.log("[LLM Mini] isChineseLocale check. Detected locale:", locale, "Result:", result);
  return result;
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
  if (!widget.options.values) {
    widget.options.values = [];
  }
  
  // Vue 响应式安全修复：通过清空并 push 来进行“就地修改”（In-place mutation）
  // 这样可以保留 Vue 3 的 Proxy 代理对象，同时触发数组变动监听，避免直接覆盖引用导致响应式失效
  widget.options.values.length = 0;
  widget.options.values.push(...values);
  
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
  console.log("[LLM Mini] addRefreshButton called for node:", node.title || node.name);
  node.addWidget("button", label, label, async () => {
    console.log("[LLM Mini] Refresh Models button clicked! Node:", node);
    const provider = widgetValue(node, "provider") || "openai";
    console.log("[LLM Mini] Selected provider:", provider);
    try {
      const response = await api.fetchApi("/llm-mini/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider }),
      });
      const data = await response.json();
      console.log("[LLM Mini] Received models from server:", data);
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (!data.models || data.models.length === 0) throw new Error(t("No models returned.", "没有返回可用模型。"));
      
      if (!data.has_credentials && provider !== "ollama") {
        alert(t("Models loaded from defaults. Add credentials to fetch live provider models.", "已加载默认模型。请添加凭据以获取实时模型列表。"));
      }
      
      const modelWidget = findWidget(node, "model_name");
      const currentlyConfigured = modelWidget && modelWidget.options && modelWidget.options.values ? [...modelWidget.options.values] : [];

      // 打开精美的多选选择框
      showModelSelectionModal(
        provider,
        data.models,
        currentlyConfigured,
        // onSave (保存为静态配置并更新当前界面)
        (selectedList) => {
          updateCombo(node, "model_name", selectedList);
        },
        // onApply (仅临时更新当前界面)
        (selectedList) => {
          updateCombo(node, "model_name", selectedList);
        }
      );
    } catch (error) {
      console.error("[LLM Mini] Refresh models failed:", error);
      alert(`LLM Mini: ${error.message}`);
    }
  });
  node.setSize(node.computeSize());
}
