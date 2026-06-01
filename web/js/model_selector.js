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
  "LLMMiniProviderManager",
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

async function setupProviderManager(node) {
  const providerWidget = findWidget(node, "provider");
  const newProviderIdWidget = findWidget(node, "new_provider_id");

  // 添加 Base URL Widget
  const baseUrlWidget = node.addWidget("text", "Base URL", "", () => {}, { multiline: false });
  baseUrlWidget.serializeValue = () => undefined;

  // 添加 API Key Widget
  const apiKeyWidget = node.addWidget("text", "API Key", "", () => {}, { type: "password" });
  apiKeyWidget.serializeValue = () => undefined;

  // 添加只读的 Auth Status 看板 Widget
  const statusWidget = node.addWidget("text", "Auth Status", "", () => {}, { multiline: true });
  statusWidget.serializeValue = () => undefined;
  statusWidget.options = statusWidget.options || {};
  statusWidget.options.readonly = true;

  let pollInterval = null;

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
  }

  function startPollingStatus(provider, userCode, verificationUri) {
    stopPolling();
    pollInterval = setInterval(async () => {
      try {
        const response = await api.fetchApi(`/llm-mini/oauth/status?provider=${encodeURIComponent(provider)}`);
        if (!response.ok) return;
        const data = await response.json();
        
        if (data.status === "pending") {
          let codeText = userCode ? t(`\n🔑 Code: ${userCode}`, `\n🔑 验证码: ${userCode}`) : "";
          let uriText = verificationUri ? t(`\n🔗 Link: ${verificationUri}`, `\n🔗 链接: ${verificationUri}`) : "";
          let fallbackGuide = provider === "xai" ? t(
            `\n⚠️ If "Connection Failed" shows in browser, visit:\nhttp://127.0.0.1:56121/callback?code=[PasteCodeHere]`,
            `\n⚠️ 若网页提示“无法建立连接”，可手动访问:\nhttp://127.0.0.1:56121/callback?code=[您复制的授权码]`
          ) : "";
          statusWidget.value = t(
            `⏱️ Waiting for authentication...${codeText}${uriText}${fallbackGuide}\nExpires in: ${data.expires_in}s`,
            `⏱️ 等待网页授权中...${codeText}${uriText}${fallbackGuide}\n剩余过期时间: ${data.expires_in}秒`
          );
          node.setDirtyCanvas(true, true);
        } else if (data.status === "success") {
          statusWidget.value = t(
            `🎉 Authentication successful!\nAccount is bound and saved.`,
            `🎉 授权成功！\n已成功绑定账号，配置已写入。`
          );
          stopPolling();
          node.setDirtyCanvas(true, true);
          setTimeout(async () => {
            await refreshProvidersList();
          }, 3000);
        } else if (data.status === "failed") {
          statusWidget.value = t(
            `❌ Authentication failed!\nError: ${data.error || "Unknown error"}`,
            `❌ 授权失败！\n错误: ${data.error || "未知错误"}`
          );
          stopPolling();
          node.setDirtyCanvas(true, true);
        } else if (data.status === "cancelled") {
          statusWidget.value = t(
            `❌ Authentication cancelled by user.`,
            `❌ 授权已由用户取消。`
          );
          stopPolling();
          node.setDirtyCanvas(true, true);
        }
      } catch (err) {
        console.error("Poll oauth status error:", err);
      }
    }, 2000);
  }

  async function refreshProvidersList(selectProviderId = null) {
    try {
      const providers = await fetchProviderInfo();
      const providerIds = providers.map((item) => item.id).filter(Boolean);
      if (!providerIds.includes("custom_provider")) {
        providerIds.push("custom_provider");
      }
      
      const currentVal = selectProviderId || providerWidget.value;
      updateCombo(node, "provider", providerIds);
      if (providerIds.includes(currentVal)) {
        providerWidget.value = currentVal;
      }
      
      await loadSelectedProviderConfig();
    } catch (e) {
      console.warn("Failed to refresh providers list:", e);
    }
  }

  async function loadSelectedProviderConfig() {
    stopPolling();
    const provider = providerWidget.value;
    if (!provider || provider === "custom_provider") {
      baseUrlWidget.value = "";
      apiKeyWidget.value = "";
      statusWidget.value = t("Please enter new Provider ID to create.", "请在上方输入新 Provider ID 进行创建。");
      node.setDirtyCanvas(true, true);
      return;
    }

    statusWidget.value = t("Loading configuration...", "正在加载配置...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi(`/llm-mini/config/get?provider=${encodeURIComponent(provider)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      baseUrlWidget.value = data.base_url || "";
      if (data.has_key) {
        apiKeyWidget.value = "[CONFIGURED]";
        statusWidget.value = t(
          `🔑 Credentials configured and ready.`,
          `🔑 凭据已配置，随时可用。`
        );
      } else {
        apiKeyWidget.value = "";
        if (provider === "xai" || provider === "codex") {
          statusWidget.value = t(
            `⚠️ Credentials not configured.\nPlease enter API Key or click OAuth below to authorize.`,
            `⚠️ 凭据未配置。\n请输入 API Key 或点击下方按钮进行网页/设备码授权。`
          );
        } else if (provider === "ollama") {
          statusWidget.value = t(
            `✅ Ollama is ready (no credentials required).`,
            `✅ Ollama 已就绪（不需要凭据）。`
          );
        } else {
          statusWidget.value = t(
            `⚠️ Credentials not configured.\nPlease enter API Key and click Save Config.`,
            `⚠️ 凭据未配置。\n请输入 API Key 并点击保存配置。`
          );
        }
      }
      node.setDirtyCanvas(true, true);
    } catch (err) {
      statusWidget.value = t(`Error loading config: ${err.message}`, `加载配置失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  }

  const origCallback = providerWidget.callback;
  providerWidget.callback = function(value) {
    if (origCallback) origCallback.apply(this, arguments);
    loadSelectedProviderConfig();
  };

  const saveLabel = t("Save Config", "保存配置");
  node.addWidget("button", saveLabel, saveLabel, async () => {
    let provider = providerWidget.value;
    const newId = newProviderIdWidget ? newProviderIdWidget.value.trim() : "";
    if (provider === "custom_provider") {
      if (!newId) {
        alert(t("Please enter a new Provider ID.", "请输入新提供商 ID。"));
        return;
      }
      provider = newId;
    }

    const apiKey = apiKeyWidget.value;
    const baseUrl = baseUrlWidget.value;

    statusWidget.value = t("Saving...", "正在保存...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/config/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: provider,
          api_key: apiKey,
          base_url: baseUrl
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      
      alert(t("Configuration saved successfully.", "配置保存成功。"));
      if (newProviderIdWidget) newProviderIdWidget.value = "";
      await refreshProvidersList(provider);
    } catch (err) {
      alert(`Save failed: ${err.message}`);
      statusWidget.value = t(`Save failed: ${err.message}`, `保存失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const deleteLabel = t("Delete Config", "删除配置");
  node.addWidget("button", deleteLabel, deleteLabel, async () => {
    const provider = providerWidget.value;
    if (!provider || provider === "custom_provider") {
      alert(t("Please select a valid provider to delete.", "请选择要删除的有效提供商。"));
      return;
    }

    if (!confirm(t(`Are you sure you want to delete configuration for "${provider}"?`, `确定要删除提供商 "${provider}" 的配置吗？`))) {
      return;
    }

    statusWidget.value = t("Deleting...", "正在删除...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/config/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      alert(t("Configuration deleted successfully.", "配置删除成功。"));
      await refreshProvidersList("custom_provider");
    } catch (err) {
      alert(`Delete failed: ${err.message}`);
      statusWidget.value = t(`Delete failed: ${err.message}`, `删除失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const browserAuthLabel = t("Browser OAuth", "网页授权");
  node.addWidget("button", browserAuthLabel, browserAuthLabel, async () => {
    const provider = providerWidget.value;
    if (provider !== "xai" && provider !== "codex") {
      alert(t("OAuth is only supported by xai and codex providers.", "只有 xai 和 codex 提供商支持 OAuth 授权。"));
      return;
    }

    statusWidget.value = t("Starting Browser OAuth...", "正在启动网页授权...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, flow: "browser" })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      if (data.verification_uri) {
        statusWidget.value = t(
          `🔗 Opening browser...\nPlease authorize in the browser.\nIf it did not open, visit: ${data.verification_uri}`,
          `🔗 正在拉起浏览器...\n请在浏览器中进行授权绑定。\n如未自动打开，请手动访问: ${data.verification_uri}`
        );
        node.setDirtyCanvas(true, true);
        window.open(data.verification_uri, "_blank");
        startPollingStatus(provider, null, data.verification_uri);
      } else {
        throw new Error("No verification URI returned.");
      }
    } catch (err) {
      alert(`OAuth failed: ${err.message}`);
      statusWidget.value = t(`OAuth failed: ${err.message}`, `授权启动失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const deviceAuthLabel = t("Device Code OAuth", "设备码授权");
  node.addWidget("button", deviceAuthLabel, deviceAuthLabel, async () => {
    const provider = providerWidget.value;
    if (provider !== "xai" && provider !== "codex") {
      alert(t("OAuth is only supported by xai and codex providers.", "只有 xai 和 codex 提供商支持 OAuth 授权。"));
      return;
    }

    statusWidget.value = t("Starting Device OAuth...", "正在启动设备码授权...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, flow: "device" })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      if (data.user_code && data.verification_uri) {
        if (navigator.clipboard) {
          try {
            await navigator.clipboard.writeText(data.user_code);
          } catch (clipErr) {
            console.warn("Failed to copy user_code:", clipErr);
          }
        }
        
        statusWidget.value = t(
          `🔑 Verification Code: ${data.user_code}\n(Copied to clipboard!)\n🔗 Opening page...`,
          `🔑 验证码: ${data.user_code}\n(已自动复制到剪贴板！)\n🔗 正在打开页面...`
        );
        node.setDirtyCanvas(true, true);
        
        // 关键：先执行 window.open 打开网页，避免被 alert 阻塞中断用户点击交互流而导致被浏览器弹窗拦截器拦截
        window.open(data.verification_uri, "_blank");
        
        // 双重保障提示，即使网页被拦截，也可以手动复制看板中即将展示的链接
        alert(t(
          `Device Verification Code: ${data.user_code}\n\nThe code has been copied to your clipboard.\nClick OK to continue (if the page did not open, you can copy the authorization link from the status box).`,
          `设备授权验证码: ${data.user_code}\n\n验证码已自动复制到您的剪贴板。\n点击“确定”继续。（如果浏览器未自动打开，您可以手动复制并访问状态看板上显示的授权链接）。`
        ));
        
        startPollingStatus(provider, data.user_code, data.verification_uri);
      } else {
        throw new Error("Invalid response from device OAuth start.");
      }
    } catch (err) {
      alert(`OAuth failed: ${err.message}`);
      statusWidget.value = t(`OAuth failed: ${err.message}`, `授权启动失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });
  
  const cancelAuthLabel = t("Close Auth Process", "关闭授权进程");
  node.addWidget("button", cancelAuthLabel, cancelAuthLabel, async () => {
    const provider = providerWidget.value;
    statusWidget.value = t("Closing process...", "正在关闭授权进程...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/oauth/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      
      statusWidget.value = t("Authorization process closed.", "授权进程已成功关闭。");
      stopPolling();
      node.setDirtyCanvas(true, true);
    } catch (err) {
      alert(`Close failed: ${err.message}`);
      statusWidget.value = t(`Failed to close: ${err.message}`, `关闭失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const submitCodeLabel = t("Submit Code or Redirect URL", "手动输入授权码或回调地址");
  node.addWidget("button", submitCodeLabel, submitCodeLabel, async () => {
    const provider = providerWidget.value;
    if (provider !== "xai" && provider !== "codex") {
      alert(t("OAuth is only supported by xai and codex providers.", "只有 xai 和 codex 提供商支持 OAuth 授权。"));
      return;
    }

    const userInput = prompt(t(
      "Please enter the authorization code or paste the entire redirected URL:",
      "请输入授权码，或者直接粘贴跳转失败后的完整浏览器地址栏 URL："
    ));
    if (!userInput) return;

    let code = userInput.trim();
    if (code.includes("code=")) {
      try {
        const url = new URL(code);
        code = url.searchParams.get("code") || code;
      } catch (e) {
        const match = code.match(/[?&]code=([^&]+)/);
        if (match) code = match[1];
      }
    }

    statusWidget.value = t("Exchanging code...", "正在换取并保存凭据...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/oauth/submit-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, code })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      statusWidget.value = t(
        `🎉 Authentication successful!\nAccount is bound and saved.`,
        `🎉 授权成功！\n已成功绑定账号，配置已写入。`
      );
      stopPolling();
      node.setDirtyCanvas(true, true);
      alert(t("Authentication successful!", "授权成功！"));
      await refreshProvidersList(provider);
    } catch (err) {
      alert(`Submit failed: ${err.message}`);
      statusWidget.value = t(`Submit failed: ${err.message}`, `手动授权失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  await loadSelectedProviderConfig();
  
  // 显式指定节点合理尺寸，避免动态添加的 widgets/按钮与看板超出边界不可见
  node.size = [350, 500];
  node.setDirtyCanvas(true, true);
  
  node.onRemoved = function() {
    stopPolling();
  };
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
      if (nodeData.name === "LLMMiniProviderManager") {
        setTimeout(() => setupProviderManager(this), 50);
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
