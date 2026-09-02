import { api } from "../../../../scripts/api.js";
import { refreshProviderWidgets, fetchProviderInfo, findWidget, updateCombo, t } from "./utils.js";
import { showModelSelectionModal } from "./modal.js";
import { setupPersonaManager } from "./persona.js";
import { setupProviderManager } from "./provider.js";
import { scheduleLocalization } from "./localization.js";

export function isTargetNode(nodeName) {
  return typeof nodeName === "string" && nodeName.startsWith("LLMMini");
}

export function setupNodeByType(node, nodeName) {
  scheduleLocalization(node);

  if (nodeName === "LLMMiniApiChat") {
    node.size = [300, node.computeSize()[1]];
    setTimeout(() => refreshProviderWidgets(node), 50);
    setupApiChatModelTools(node);
    setupLocalUnloadPolicy(node);
  }
  
  if (nodeName === "LLMMiniLoadPersona") {
    node.size = [250, node.computeSize()[1]];
  }

  if (/Video/.test(nodeName) || /FirstLastFrame/.test(nodeName)) {
    node.size = [300, node.computeSize()[1]];
  }

  if (/(Image|Imagine|Imagen|NanoBanana)/.test(nodeName)) {
    node.size = [300, node.computeSize()[1]];
  }

  if (nodeName === "LLMMiniOpenAIImage" || nodeName === "LLMMiniCodexImage") {
    const modelWidget = findWidget(node, "model_name");
    if (modelWidget) {
      const updateModelOptions = () => {
        const models = ["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini"];
        updateCombo(node, "model_name", models);
      };
      updateModelOptions();
      const originalCallback = modelWidget.callback;
      modelWidget.callback = function (value) {
        if (originalCallback) originalCallback.apply(this, arguments);
        updateModelOptions();
      };
    }
  }

  if (nodeName === "LLMMiniTranslation") {
    const sourceLanguages = t(
      ["Auto detect", "Chinese", "English", "Japanese", "Korean", "French", "German", "Spanish", "Portuguese", "Italian", "Russian", "Arabic", "Thai", "Vietnamese"],
      ["自动检测", "中文", "英语", "日语", "韩语", "法语", "德语", "西班牙语", "葡萄牙语", "意大利语", "俄语", "阿拉伯语", "泰语", "越南语"]
    );
    const targetLanguages = sourceLanguages.slice(1);
    const tones = t(
      ["Preserve original", "Natural", "Formal", "Conversational", "Professional", "Concise", "Literary"],
      ["保持原文", "自然", "正式", "口语", "专业", "简洁", "文学"]
    );
    updateCombo(node, "source_language", sourceLanguages);
    updateCombo(node, "target_language", targetLanguages);
    updateCombo(node, "tone", tones);
    node.size = [300, node.computeSize()[1]];
    setTimeout(async () => {
      await refreshProviderWidgets(node);
      fitTranslationNodeHeight(node);
    }, 50);
    setupLocalUnloadPolicy(node, () => fitTranslationNodeHeight(node));
  }
  
  if (nodeName === "LLMMiniPersonaManager") {
    setupPersonaManager(node);
  }
  
  if (nodeName === "LLMMiniProviderManager") {
    setupProviderManager(node);
  }
  
  if (nodeName === "LLMMiniGoogleImagen") {
    const modelWidget = findWidget(node, "model_name");
    if (modelWidget) {
      const updateResolutionOptions = (model) => {
        const lowerModel = model ? model.toLowerCase() : "";
        const isFast = lowerModel.includes("fast");
        const isImagen = lowerModel.includes("imagen");
        let resolutions;
        if (isFast) {
          resolutions = ["Default"];
        } else if (isImagen) {
          resolutions = ["512", "1K", "2K"];
        } else {
          resolutions = ["512", "1K", "2K", "4K"];
        }
        const resWidget = findWidget(node, "resolution");
        const currentVal = resWidget ? resWidget.value : "";
        updateCombo(node, "resolution", resolutions);
        if (!isFast && isImagen && currentVal === "4K") {
          if (resWidget) resWidget.value = "1K";
        }
      };
      updateResolutionOptions(modelWidget.value);
      const originalCallback = modelWidget.callback;
      modelWidget.callback = function (value) {
        if (originalCallback) originalCallback.apply(this, arguments);
        updateResolutionOptions(value);
      };
    }
  }
}

function setWidgetVisible(node, widget, visible) {
  if (!widget) return;
  if (!Object.prototype.hasOwnProperty.call(widget, "__llmMiniOriginalType")) {
    widget.__llmMiniOriginalType = widget.type;
    widget.__llmMiniOriginalComputeSize = widget.computeSize;
  }
  widget.type = widget.__llmMiniOriginalType;
  widget.computeSize = widget.__llmMiniOriginalComputeSize;
  widget.hidden = !visible;
  widget.options = widget.options || {};
  widget.options.hidden = !visible;
  node.size = [node.size?.[0] || 300, node.computeSize()[1]];
  node.setDirtyCanvas(true, true);
}

function fitTranslationNodeHeight(node) {
  const applySize = () => {
    const width = node.size?.[0] || 300;
    const height = node.computeSize()[1];
    if (typeof node.setSize === "function") {
      node.setSize([width, height]);
    } else {
      node.size = [width, height];
    }
    node.setDirtyCanvas(true, true);
  };
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(applySize);
  } else {
    setTimeout(applySize, 0);
  }
}

function setupLocalUnloadPolicy(node, afterVisibilityChange = null) {
  const policyWidget = findWidget(node, "local_unload_policy");
  if (!policyWidget) return;
  const canonicalPolicies = ["after_run", "keep_warm", "idle"];
  const policyValues = t(
    canonicalPolicies,
    ["执行后卸载", "保持驻留", "空闲后卸载"]
  );
  const canonicalize = (value) => ({
    "执行后卸载": "after_run",
    "保持驻留": "keep_warm",
    "空闲后卸载": "idle",
    "inherit": "after_run"
  })[value] || (canonicalPolicies.includes(value) ? value : "after_run");
  const localize = (value) => policyValues[canonicalPolicies.indexOf(canonicalize(value))];
  policyWidget.options = policyWidget.options || {};
  policyWidget.options.values = policyValues;
  policyWidget.value = localize(policyWidget.value);
  policyWidget.serializeValue = () => canonicalize(policyWidget.value);
  node.__llmMiniProviderChanged = (provider) => {
    policyWidget.value = localize(policyWidget.value);
    setWidgetVisible(node, policyWidget, provider === "llama_cpp");
    if (afterVisibilityChange) afterVisibilityChange();
  };
  node.__llmMiniProviderChanged(findWidget(node, "provider")?.value);
}

function updateChatNodesForProvider(node, provider, models) {
  const nodes = node.graph && node.graph._nodes ? node.graph._nodes : [node];
  for (const item of nodes) {
    if (!item || item.comfyClass !== "LLMMiniApiChat") continue;
    const providerWidget = findWidget(item, "provider");
    if (providerWidget && Array.isArray(providerWidget.__llmMiniProviders)) {
      const cachedProvider = providerWidget.__llmMiniProviders.find((entry) => entry && entry.id === provider);
      if (cachedProvider) cachedProvider.default_models = models;
    }
    if (providerWidget && providerWidget.value === provider) {
      updateCombo(item, "model_name", models);
      item.size = [300, item.computeSize()[1]];
    }
  }
}

function configuredModelsFromProviders(providers, provider) {
  const info = providers.find((item) => item && item.id === provider);
  const models = info && Array.isArray(info.default_models) ? [...info.default_models] : [];
  return models.filter((model) => model !== "click Refresh Models" && model !== "点击刷新模型");
}

function currentChatProvider(node) {
  const providerWidget = findWidget(node, "provider");
  return providerWidget ? String(providerWidget.value || "").trim() : "";
}

function setupApiChatModelTools(node) {
  if (node.__llmMiniModelToolsReady) return;
  node.__llmMiniModelToolsReady = true;

  const label = t("Refresh & Configure Model List", "刷新并配置模型列表");
  node.addWidget("button", label, label, async () => {
    const provider = currentChatProvider(node);
    if (!provider) {
      alert(t("Please select a provider first.", "请先选择一个提供商。"));
      return;
    }

    try {
      const response = await api.fetchApi("/llm-mini/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      const models = Array.isArray(data.models) ? data.models.filter(Boolean) : [];
      if (!models.length) throw new Error(t("No models returned.", "没有返回可用模型。"));

      const providers = await fetchProviderInfo();
      const existingModels = configuredModelsFromProviders(providers, provider);

      showModelSelectionModal(
        provider,
        models,
        existingModels,
        (selectedList) => {
          updateChatNodesForProvider(node, provider, selectedList);
        },
        (selectedList) => {
          updateChatNodesForProvider(node, provider, selectedList);
          alert(t("Models temporarily applied to chat nodes.", "模型列表已临时应用到聊天节点。"));
        }
      );
    } catch (err) {
      alert(t(`Refresh failed: ${err.message}`, `刷新模型失败：${err.message}`));
    }
  });

  const customModelInput = node.addWidget("text", t("Custom Model ID", "自定义模型 ID"), "", () => {}, { multiline: false });
  customModelInput.serializeValue = () => undefined;

  const addModelLabel = t("Add Custom Model", "添加自定义模型");
  node.addWidget("button", addModelLabel, addModelLabel, async () => {
    const provider = currentChatProvider(node);
    if (!provider) {
      alert(t("Please select a provider first.", "请先选择一个提供商。"));
      return;
    }
    if (provider === "llama_cpp") {
      alert(t("Place GGUF files in the configured llama.cpp models directory, then refresh the list.", "请将 GGUF 文件放入已配置的 llama.cpp 模型目录，然后刷新列表。"));
      return;
    }
    const newModel = String(customModelInput.value || "").trim();
    if (!newModel) {
      alert(t("Please enter a model ID.", "请输入模型 ID。"));
      return;
    }

    try {
      const providers = await fetchProviderInfo();
      const existingModels = configuredModelsFromProviders(providers, provider);
      if (existingModels.includes(newModel)) {
        alert(t("Model ID already exists.", "该模型 ID 已存在。"));
        return;
      }

      const updatedModels = [...existingModels, newModel];
      const saveResponse = await api.fetchApi("/llm-mini/config/save-default-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, default_models: updatedModels })
      });
      const saveData = await saveResponse.json();
      if (!saveResponse.ok) throw new Error(saveData.error || `HTTP ${saveResponse.status}`);

      updateChatNodesForProvider(node, provider, updatedModels);
      customModelInput.value = "";
      alert(t(`Model "${newModel}" added and saved as default.`, `模型 "${newModel}" 已添加并保存为默认静态列表。`));
    } catch (err) {
      alert(t(`Add failed: ${err.message}`, `添加失败：${err.message}`));
    }
  });

  node.size = [300, node.computeSize()[1]];
}
