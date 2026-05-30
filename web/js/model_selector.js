import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const TARGET_NODES = new Set([
  "LLMMiniApiChat",
  "LLMMiniLoadPersona",
  "LLMMiniOpenAICodexImage",
  "LLMMiniXAIImagine",
  "LLMMiniXAIVideo",
  "LLMMiniXAIVideoReference",
  "LLMMiniXAIVideoEdit",
  "LLMMiniXAIVideoExtend",
  "LLMMiniPersonaManager",
  "LLMMiniGoogleImagen",
  "LLMMiniGoogleGeminiNanoBanana",
  "LLMMiniGoogleGeminiNanoBananaPro",
  "LLMMiniGoogleGeminiNanoBanana2",
]);

function currentLocale() {
  return localStorage["AGL.Locale"] || localStorage["Comfy.Settings.AGL.Locale"] || "en-US";
}

function isChineseLocale() {
  return currentLocale().toLowerCase().startsWith("zh");
}

function t(en, zh) {
  return isChineseLocale() ? zh : en;
}

function findWidget(node, name) {
  return node.widgets ? node.widgets.find((w) => w.name === name) : null;
}

function widgetValue(node, name) {
  const widget = findWidget(node, name);
  return widget ? widget.value || "" : "";
}

function updateCombo(node, name, values) {
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

async function fetchProviderInfo() {
  const response = await api.fetchApi("/llm-mini/providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!response.ok) return [];
  const data = await response.json();
  return data.providers || [];
}

function updateCredentialSourcesAndModels(node, providers) {
  const provider = widgetValue(node, "provider");
  const info = providers.find((item) => item.id === provider);
  if (!info) return;
  if (info.credential_sources) {
    updateCombo(node, "credential_source", info.credential_sources);
  }
  if (info.default_models && info.default_models.length) {
    updateCombo(node, "model_name", info.default_models);
  }
}

async function refreshProviderWidgets(node) {
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

function removeRefreshButtons(node) {
  if (!node.widgets) return;
  for (let i = node.widgets.length - 1; i >= 0; i--) {
    const w = node.widgets[i];
    if (w.type === "button" && (w.name === "Refresh Models" || w.name === "刷新模型")) node.widgets.splice(i, 1);
  }
}

function addRefreshButton(node) {
  removeRefreshButtons(node);
  const label = t("Refresh Models", "刷新模型");
  node.addWidget("button", label, label, async () => {
      const provider = widgetValue(node, "provider") || "openai";
      const credentialSource = widgetValue(node, "credential_source") || "api key";
      try {
        const response = await api.fetchApi("/llm-mini/models", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider, credential_source: credentialSource }),
        });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (!data.models || data.models.length === 0) throw new Error(t("No models returned.", "没有返回可用模型。"));
      if (data.credential_sources) updateCombo(node, "credential_source", data.credential_sources);
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

async function fetchPersonaContent(name) {
  const response = await api.fetchApi("/llm-mini/persona/get", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) return "";
  const data = await response.json();
  return data.content || "";
}

function updatePersonaCombos(node, personas, selectName) {
  updateCombo(node, "persona_name", personas);
  if (selectName && personas.includes(selectName)) {
    const w = findWidget(node, "persona_name");
    if (w) w.value = selectName;
  }
}

function refreshAllPersonaNodes(graph, personas) {
  if (!graph) return;
  const loadNodes = graph.findNodesByType("LLMMiniLoadPersona");
  if (loadNodes) {
    loadNodes.forEach((n) => {
      updatePersonaCombos(n, personas, n.widgets ? n.widgets.find((w) => w.name === "persona_name")?.value : null);
    });
  }
  const managerNodes = graph.findNodesByType("LLMMiniPersonaManager");
  if (managerNodes) {
    managerNodes.forEach((n) => {
      const nameW = n.widgets ? n.widgets.find((w) => w.name === "persona_name") : null;
      updatePersonaCombos(n, personas, nameW ? nameW.value : null);
    });
  }
}

async function setupPersonaManager(node) {
  const nameWidget = findWidget(node, "persona_name");
  const newNameWidget = findWidget(node, "new_name");
  const contentWidget = findWidget(node, "content");
  
  if (nameWidget) {
    if (nameWidget.value) {
      const content = await fetchPersonaContent(nameWidget.value);
      if (contentWidget) contentWidget.value = content;
      if (newNameWidget) newNameWidget.value = nameWidget.value;
    }
    
    const originalCallback = nameWidget.callback;
    nameWidget.callback = async function (value) {
      if (originalCallback) originalCallback.apply(this, arguments);
      if (value) {
        const content = await fetchPersonaContent(value);
        if (contentWidget) contentWidget.value = content;
        if (newNameWidget) newNameWidget.value = value;
      }
    };
  }
  
  const saveLabel = t("Save Persona", "保存面具");
  node.addWidget("button", saveLabel, saveLabel, async () => {
    const currentName = nameWidget ? nameWidget.value : "";
    let saveName = newNameWidget ? newNameWidget.value.trim() : "";
    if (!saveName) {
      saveName = currentName;
    }
    const saveContent = contentWidget ? contentWidget.value : "";
    if (!saveName) {
      alert(t("Please enter a persona name.", "请输入人格面具名称。"));
      return;
    }
    try {
      const response = await api.fetchApi("/llm-mini/persona/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: saveName, content: saveContent }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      alert(t("Persona saved successfully.", "人格面具保存成功。"));
      if (data.personas) {
        refreshAllPersonaNodes(node.graph, data.personas);
        updatePersonaCombos(node, data.personas, saveName);
        if (newNameWidget) newNameWidget.value = "";
      }
    } catch (error) {
      alert(`LLM Mini: ${error.message}`);
    }
  });

  const deleteLabel = t("Delete Persona", "删除面具");
  node.addWidget("button", deleteLabel, deleteLabel, async () => {
    const deleteName = nameWidget ? nameWidget.value : "";
    if (!deleteName) {
      alert(t("No persona selected to delete.", "未选择要删除的人格面具。"));
      return;
    }
    if (!confirm(t(`Are you sure you want to delete persona "${deleteName}"?`, `确定要删除人格面具 "${deleteName}" 吗？`))) {
      return;
    }
    try {
      const response = await api.fetchApi("/llm-mini/persona/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: deleteName }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      alert(t("Persona deleted successfully.", "人格面具删除成功。"));
      if (data.personas) {
        const nextSelect = data.personas[0] || "";
        refreshAllPersonaNodes(node.graph, data.personas);
        updatePersonaCombos(node, data.personas, nextSelect);
        if (nextSelect) {
          const content = await fetchPersonaContent(nextSelect);
          if (contentWidget) contentWidget.value = content;
          if (newNameWidget) newNameWidget.value = nextSelect;
        } else {
          if (contentWidget) contentWidget.value = "";
          if (newNameWidget) newNameWidget.value = "";
        }
      }
    } catch (error) {
      alert(`LLM Mini: ${error.message}`);
    }
  });

  node.setSize(node.computeSize());
}

function applyLocalization(node) {
  const isZh = isChineseLocale();
  const translations = {
    "provider": { zh: "提供商", en: "Provider" },
    "model_name": { zh: "模型", en: "Model" },
    "system_prompt": { zh: "系统提示词", en: "System Prompt" },
    "user_prompt": { zh: "用户提示词", en: "User Prompt" },
    "temperature": { zh: "温度", en: "Temperature" },
    "max_tokens": { zh: "最大 Token", en: "Max Tokens" },
    "is_locked": { zh: "锁定缓存", en: "Lock Cache" },
    "credential_source": { zh: "凭据来源", en: "Credential Source" },
    "stream": { zh: "流式输出", en: "Stream" },
    "system_prompt_input": { zh: "加载人格面具", en: "Load Persona" },
    "image": { zh: "图像", en: "Image" },
    "images": { zh: "参考图像", en: "Reference Images" },
    "image_url": { zh: "图像 URL", en: "Image URL" },
    "assistant_response": { zh: "助手回复", en: "Assistant Response" },
    "history_json": { zh: "历史记录 JSON", en: "History JSON" },
    "persona_name": { zh: "人格面具", en: "Persona" },
    "new_name": { zh: "新名称", en: "New Name" },
    "content": { zh: "面具内容", en: "Content" },
    "text": { zh: "文本", en: "Text" },
    "prompt": { zh: "提示词", en: "Prompt" },
    "execution_backend": { zh: "执行后端", en: "Execution Backend" },
    "size": { zh: "尺寸", en: "Size" },
    "quality": { zh: "质量", en: "Quality" },
    "background": { zh: "背景", en: "Background" },
    "n": { zh: "数量", en: "Quantity" },
    "seed": { zh: "随机种", en: "Seed" },
    "mask": { zh: "遮罩", en: "Mask" },
    "aspect_ratio": { zh: "宽高比", en: "Aspect Ratio" },
    "resolution": { zh: "分辨率", en: "Resolution" },
    "duration": { zh: "时长", en: "Duration" },
    "video": { zh: "视频", en: "Video" },
    "model": { zh: "模型", en: "Model" },
    "response_modalities": { zh: "响应模态", en: "Response Modalities" },
    "thinking_level": { zh: "思考级别", en: "Thinking Level" },
    "files": { zh: "参考文件", en: "Reference Files" }
  };

  if (node.inputs) {
    node.inputs.forEach((input) => {
      const t = translations[input.name];
      if (t) {
        input.label = isZh ? t.zh : t.en;
      }
    });
  }
  if (node.outputs) {
    node.outputs.forEach((output) => {
      const t = translations[output.name];
      if (t) {
        output.label = isZh ? t.zh : t.en;
      }
    });
  }
  if (node.widgets) {
    node.widgets.forEach((widget) => {
      const t = translations[widget.name];
      if (t) {
        widget.label = isZh ? t.zh : t.en;
      }
    });
  }
}

app.registerExtension({
  name: "ComfyUI.LLMMini.ModelSelector",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!TARGET_NODES.has(nodeData.name)) return;
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = original ? original.apply(this, arguments) : undefined;
      setTimeout(() => applyLocalization(this), 20);
      if (nodeData.name === "LLMMiniApiChat") {
        this.size = [300, 380];
        setTimeout(() => refreshProviderWidgets(this), 50);
        setTimeout(() => {
          addRefreshButton(this);
          this.size = [300, 380];
        }, 100);
      }
      if (nodeData.name === "LLMMiniLoadPersona") {
        this.size = [250, this.computeSize()[1]];
      }
      if (nodeData.name === "LLMMiniPersonaManager") {
        setTimeout(() => setupPersonaManager(this), 50);
      }
      if (nodeData.name === "LLMMiniGoogleImagen") {
        const modelWidget = findWidget(this, "model_name");
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
            const resWidget = findWidget(this, "resolution");
            const currentVal = resWidget ? resWidget.value : "";
            updateCombo(this, "resolution", resolutions);
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
      return result;
    };
  },
});
