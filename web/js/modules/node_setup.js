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
