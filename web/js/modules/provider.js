import { api } from "../../../../scripts/api.js";
import { app } from "../../../../scripts/app.js";
import { t, findWidget, updateCombo, fetchProviderInfo, refreshProviderWidgets, copyToClipboard } from "./utils.js";
import { showModelSelectionModal, showDeviceAuthModal, showLlamaCppManagerModal } from "./modal.js";

const PROVIDER_ID_PATTERN = /^[\p{L}\p{N}][\p{L}\p{N}._-]{0,63}$/u;
const CHAT_BACKENDS = ["openai_compatible", "anthropic"];

function updateAllRelatedNodes(providerId, models) {
  if (!app.graph || !app.graph._nodes) return;
  for (const node of app.graph._nodes) {
    if (node && node.widgets) {
      const providerWidget = node.widgets.find(w => w.name === "provider");
      const modelWidget = node.widgets.find(w => w.name === "model_name");
      if (providerWidget && modelWidget && providerWidget.value === providerId) {
        updateCombo(node, "model_name", models);
      }
    }
  }
}

async function refreshAllApiChatNodes() {
  if (!app.graph || !app.graph._nodes) return;
  const chatNodes = app.graph._nodes.filter((item) => item && item.comfyClass === "LLMMiniApiChat");
  await Promise.all(chatNodes.map((item) => refreshProviderWidgets(item)));
}

export async function setupProviderManager(node) {
  const canonicalUnloadPolicies = ["after_run", "keep_warm", "idle"];
  const localizedUnloadPolicies = t(canonicalUnloadPolicies, ["执行后卸载", "保持驻留", "空闲后卸载"]);
  const unloadPolicyValue = (value) => ({
    "执行后卸载": "after_run",
    "保持驻留": "keep_warm",
    "空闲后卸载": "idle"
  })[value] || (canonicalUnloadPolicies.includes(value) ? value : "after_run");
  const unloadPolicyLabel = (value) => localizedUnloadPolicies[canonicalUnloadPolicies.indexOf(unloadPolicyValue(value))];
  let currentProvidersData = [];
  let chatBackendConfigurable = true;
  let activeDeviceAuthModal = null;
  const providerWidget = findWidget(node, "provider");
  const newProviderIdWidget = findWidget(node, "new_provider_id");

  // 添加 Base URL Widget
  const baseUrlWidget = node.addWidget("text", "Base URL", "", () => {}, { multiline: false });
  baseUrlWidget.serializeValue = () => undefined;

  // 添加 API Key Widget
  const apiKeyWidget = node.addWidget("text", "API Key", "", () => {}, { type: "password" });
  apiKeyWidget.serializeValue = () => undefined;

  const chatBackendWidget = node.addWidget("combo", "Chat Backend", "openai_compatible", () => {}, {
    values: CHAT_BACKENDS
  });
  chatBackendWidget.serializeValue = () => undefined;

  const supportsChatWidget = node.addWidget("toggle", t("Chat", "聊天"), true, () => {});
  supportsChatWidget.serializeValue = () => undefined;

  const supportsImageWidget = node.addWidget("toggle", t("Image", "图像"), false, () => {});
  supportsImageWidget.serializeValue = () => undefined;

  const supportsVideoWidget = node.addWidget("toggle", t("Video", "视频"), false, () => {});
  supportsVideoWidget.serializeValue = () => undefined;

  // 添加只读的 Auth Status 看板 Widget
  const statusWidget = node.addWidget("text", "Auth Status", "", () => {}, { multiline: true });
  statusWidget.serializeValue = () => undefined;
  statusWidget.options = statusWidget.options || {};
  statusWidget.options.readonly = true;

  const llamaExecutableWidget = node.addWidget("text", "llama-server", "", () => {}, { multiline: false });
  const llamaModelsDirWidget = node.addWidget("text", t("Models Directory", "模型目录"), "", () => {}, { multiline: false });
  const llamaContextWidget = node.addWidget("number", t("Context Size", "上下文长度"), 32768, () => {}, { min: 512, max: 1048576, step: 512, precision: 0 });
  const llamaGpuLayersWidget = node.addWidget("number", t("GPU Layers", "GPU 层数"), 999, () => {}, { min: 0, max: 9999, step: 1, precision: 0 });
  const llamaModelsMaxWidget = node.addWidget("number", t("Max Loaded Models", "最大驻留模型数"), 1, () => {}, { min: 1, max: 32, step: 1, precision: 0 });
  const llamaUnloadWidget = node.addWidget("combo", t("Default Unload Policy", "默认卸载策略"), unloadPolicyLabel("after_run"), () => {}, {
    values: localizedUnloadPolicies
  });
  const llamaIdleWidget = node.addWidget("number", t("Idle Unload Seconds", "空闲卸载秒数"), 600, () => {}, { min: 1, max: 86400, step: 1, precision: 0 });
  const llamaMemoryWidget = node.addWidget("combo", t("ComfyUI Memory Policy", "ComfyUI 显存策略"), "auto", () => {}, {
    values: ["auto", "keep"]
  });
  const llamaConfigWidgets = [
    llamaExecutableWidget, llamaModelsDirWidget, llamaContextWidget, llamaGpuLayersWidget,
    llamaModelsMaxWidget, llamaUnloadWidget, llamaIdleWidget, llamaMemoryWidget
  ];
  llamaConfigWidgets.forEach((widget) => { widget.serializeValue = () => undefined; });

  function setWidgetVisible(widget, visible) {
    if (!Object.prototype.hasOwnProperty.call(widget, "__llmMiniOriginalType")) {
      widget.__llmMiniOriginalType = widget.type;
      widget.__llmMiniOriginalComputeSize = widget.computeSize;
    }
    widget.type = widget.__llmMiniOriginalType;
    widget.computeSize = widget.__llmMiniOriginalComputeSize;
    widget.hidden = !visible;
    widget.options = widget.options || {};
    widget.options.hidden = !visible;
  }

  function toggleLlamaWidgets() {
    const visible = providerWidget.value === "llama_cpp";
    llamaConfigWidgets.forEach((widget) => setWidgetVisible(widget, visible));
    node.size = [350, node.computeSize()[1]];
    node.setDirtyCanvas(true, true);
  }

  function applyLlamaStatus(status) {
    const settings = status.settings || {};
    llamaExecutableWidget.value = settings.executable || "";
    llamaModelsDirWidget.value = settings.models_dir || settings.resolved_models_dir || "";
    llamaContextWidget.value = Number(settings.context_size || 32768);
    llamaGpuLayersWidget.value = Number(settings.n_gpu_layers ?? 999);
    llamaModelsMaxWidget.value = Number(settings.models_max || 1);
    llamaUnloadWidget.value = unloadPolicyLabel(settings.default_unload_policy || "after_run");
    llamaIdleWidget.value = Number(settings.idle_unload_seconds || 600);
    llamaMemoryWidget.value = settings.comfy_memory_policy || "auto";
    const env = status.environment || {};
    const loaded = (status.models || []).filter((item) => item.status?.value === "loaded" || item.loaded === true).length;
    statusWidget.value = [
      status.running ? t(`✅ llama.cpp router running (PID ${status.pid || "?"})`, `✅ llama.cpp router 正在运行（PID ${status.pid || "?"}）`) : t("⏹️ llama.cpp router stopped", "⏹️ llama.cpp router 未启动"),
      env.executable ? t(`Executable (${env.executable_source || "unknown"}): ${env.executable}`, `可执行文件（${env.executable_source || "未知来源"}）：${env.executable}`) : t("Executable: not found", "可执行文件：未找到"),
      t(`Private runtime: ${env.private_runtime_installed ? "installed" : "not installed"}`, `节点私有运行时：${env.private_runtime_installed ? "已安装" : "未安装"}`),
      t(`GGUF: ${env.gguf_count || 0}, mmproj: ${env.mmproj_count || 0}, loaded: ${loaded}`, `GGUF：${env.gguf_count || 0}，mmproj：${env.mmproj_count || 0}，已加载：${loaded}`),
      env.router_capable === false && env.executable ? t("⚠️ Router API flags were not detected.", "⚠️ 未检测到 Router API 参数。") : "",
      status.error || ""
    ].filter(Boolean).join("\n");
    node.setDirtyCanvas(true, true);
  }

  let pollInterval = null;

  function stopPolling() {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    if (activeDeviceAuthModal) {
      activeDeviceAuthModal.close();
      activeDeviceAuthModal = null;
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
          let codeText = userCode ? t(
            "\nDevice code is shown in the authorization popup.",
            "\n设备码已显示在授权弹窗中。"
          ) : "";
          let uriText = verificationUri && !userCode ? t(`\n🔗 Link: ${verificationUri}`, `\n🔗 链接: ${verificationUri}`) : "";
          let fallbackGuide = provider === "xai" && !userCode ? t(
            `\n⚠️ If "Connection Failed" shows in browser, visit:\nhttp://127.0.0.1:56121/callback?code=[PasteCodeHere]`,
            `\n⚠️ 若网页提示“无法建立连接”，可手动访问:\nhttp://127.0.0.1:56121/callback?code=[您复制的授权码]`
          ) : "";
          let errorText = data.error ? `\n❌ ${data.error}` : "";
          statusWidget.value = userCode ? t(
            `⏱️ Waiting for device authentication...${codeText}${errorText}\nExpires in: ${data.expires_in}s`,
            `⏱️ 等待设备授权中...${codeText}${errorText}\n剩余过期时间: ${data.expires_in}秒`
          ) : t(
            `⏱️ Waiting for authentication...${uriText}${fallbackGuide}${errorText}\nExpires in: ${data.expires_in}s`,
            `⏱️ 等待网页授权中...${uriText}${fallbackGuide}${errorText}\n剩余过期时间: ${data.expires_in}秒`
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

  function credentialStatusMessage(status, provider) {
    if (!status) {
      return t(
        `Credentials: ${provider ? "loading" : "unknown"}`,
        `凭据状态：${provider ? "正在读取" : "未知"}`
      );
    }

    if (status.no_credentials_required) {
      return t(
        `✅ No credentials required.`,
        `✅ 不需要凭据。`
      );
    }

    let apiKeyLine = "";
    if (status.api_key_configured) {
      if (status.api_key_source === "env") {
        apiKeyLine = t(
          `API Key: configured (environment variable)`,
          `API Key：已配置（环境变量）`
        );
      } else {
        apiKeyLine = t(
          `API Key: configured (config.ini)`,
          `API Key：已配置（config.ini）`
        );
      }
    } else {
      apiKeyLine = t(
        `API Key: not configured`,
        `API Key：未配置`
      );
    }

    const lines = [apiKeyLine];
    if (status.oauth_supported) {
      lines.push(status.oauth_configured ? t(
        `OAuth: authorized`,
        `OAuth：已授权`
      ) : t(
        `OAuth: not authorized`,
        `OAuth：未授权`
      ));
    }

    if (!status.configured) {
      lines.push(status.oauth_supported ? t(
        `Please enter API Key or use OAuth authorization below.`,
        `请输入 API Key，或使用下方 OAuth 授权。`
      ) : t(
        `Please enter API Key and click Save Config.`,
        `请输入 API Key 并点击保存配置。`
      ));
    }

    return `${status.configured ? "✅" : "⚠️"} ${lines.join("\n")}`;
  }

  async function refreshProvidersList(selectProviderId = null) {
    try {
      const providers = await fetchProviderInfo();
      currentProvidersData = providers;
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
      await refreshAllApiChatNodes();
    } catch (e) {
      console.warn("Failed to refresh providers list:", e);
    }
  }

  async function loadSelectedProviderConfig() {
    stopPolling();
    const provider = providerWidget.value;
    toggleLlamaWidgets();
    if (!provider || provider === "custom_provider") {
      baseUrlWidget.value = "";
      apiKeyWidget.value = "";
      chatBackendWidget.value = "openai_compatible";
      chatBackendConfigurable = true;
      supportsChatWidget.value = true;
      supportsImageWidget.value = false;
      supportsVideoWidget.value = false;
      statusWidget.value = t("Please enter new Provider ID to create.", "请在上方输入新 Provider ID 进行创建。");
      node.setDirtyCanvas(true, true);
      return;
    }

    statusWidget.value = t("Loading configuration...", "正在加载配置...");
    node.setDirtyCanvas(true, true);

    try {
      if (provider === "llama_cpp") {
        baseUrlWidget.value = t("Managed automatically", "由项目自动管理");
        apiKeyWidget.value = "";
        chatBackendWidget.value = "openai_compatible";
        chatBackendConfigurable = false;
        supportsChatWidget.value = true;
        supportsImageWidget.value = false;
        supportsVideoWidget.value = false;
        const llamaResponse = await api.fetchApi("/llm-mini/llama/status");
        const llamaStatus = await llamaResponse.json();
        if (!llamaResponse.ok) throw new Error(llamaStatus.error || `HTTP ${llamaResponse.status}`);
        applyLlamaStatus(llamaStatus);
        return;
      }
      const response = await api.fetchApi(`/llm-mini/config/get?provider=${encodeURIComponent(provider)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      
      const rawBaseUrl = data.base_url || "";
      if (provider === "google" && !rawBaseUrl) {
        baseUrlWidget.value = t("Leave blank (Google GenAI SDK)", "无需填写（Google GenAI SDK）");
      } else {
        baseUrlWidget.value = rawBaseUrl;
      }

      const backend = data.backend || "openai_compatible";
      if (CHAT_BACKENDS.includes(backend)) {
        chatBackendWidget.value = backend;
        chatBackendConfigurable = true;
      } else {
        chatBackendWidget.value = "openai_compatible";
        chatBackendConfigurable = false;
      }

      const credentialStatus = data.credential_status || {
        api_key_configured: data.has_key === true,
        api_key_source: data.has_key === true ? "config" : "none",
        oauth_supported: provider === "xai" || provider === "codex",
        oauth_configured: false,
        configured: data.has_key === true,
        no_credentials_required: provider === "ollama"
      };

      if (credentialStatus.api_key_configured && credentialStatus.api_key_source === "config") {
        apiKeyWidget.value = "[CONFIGURED]";
      } else {
        apiKeyWidget.value = "";
      }
      statusWidget.value = credentialStatusMessage(credentialStatus, provider);
      supportsChatWidget.value = data.supports_chat !== false;
      supportsImageWidget.value = data.supports_image === true;
      supportsVideoWidget.value = data.supports_video === true;
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
    let originalProvider = "";
    const newId = newProviderIdWidget ? newProviderIdWidget.value.trim() : "";
    if (provider === "custom_provider") {
      if (!newId) {
        alert(t("Please enter a new Provider ID.", "请输入新提供商 ID。"));
        return;
      }
      if (!PROVIDER_ID_PATTERN.test(newId)) {
        alert(t(
          "Provider ID must start with a Chinese character, letter, or number and contain only Chinese characters, letters, numbers, dots, underscores, or hyphens (maximum 64 characters).",
          "提供商 ID 必须以中文、字母或数字开头，仅可包含中文、字母、数字、点、下划线或连字符，最长 64 个字符。"
        ));
        return;
      }
      provider = newId;
    } else if (newId) {
      if (!PROVIDER_ID_PATTERN.test(newId)) {
        alert(t(
          "Provider ID must start with a Chinese character, letter, or number and contain only Chinese characters, letters, numbers, dots, underscores, or hyphens (maximum 64 characters).",
          "提供商 ID 必须以中文、字母或数字开头，仅可包含中文、字母、数字、点、下划线或连字符，最长 64 个字符。"
        ));
        return;
      }
      if (newId !== provider) {
        originalProvider = provider;
        provider = newId;
      }
    }

    const apiKey = apiKeyWidget.value;
    let baseUrl = baseUrlWidget.value;
    const googleBaseUrlPlaceholders = [
      "无需填写（Google GenAI SDK）",
      "Leave blank (Google GenAI SDK)"
    ];
    if (provider === "google" && googleBaseUrlPlaceholders.includes(baseUrl)) {
      baseUrl = "";
    }

    statusWidget.value = t("Saving...", "正在保存...");
    node.setDirtyCanvas(true, true);

    try {
      if (provider === "llama_cpp") {
        if (newId) throw new Error(t("The built-in llama_cpp provider cannot be renamed.", "内置 llama_cpp 提供商不能重命名。"));
        const llamaResponse = await api.fetchApi("/llm-mini/llama/config/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            executable: String(llamaExecutableWidget.value || "").trim(),
            models_dir: String(llamaModelsDirWidget.value || "").trim(),
            context_size: Number(llamaContextWidget.value),
            n_gpu_layers: Number(llamaGpuLayersWidget.value),
            models_max: Number(llamaModelsMaxWidget.value),
            default_unload_policy: unloadPolicyValue(llamaUnloadWidget.value),
            idle_unload_seconds: Number(llamaIdleWidget.value),
            comfy_memory_policy: llamaMemoryWidget.value
          })
        });
        const llamaData = await llamaResponse.json();
        if (!llamaResponse.ok) throw new Error(llamaData.error || `HTTP ${llamaResponse.status}`);
        alert(t("llama.cpp configuration saved.", "llama.cpp 配置已保存。"));
        await loadSelectedProviderConfig();
        return;
      }
      const response = await api.fetchApi("/llm-mini/config/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: provider,
          original_provider: originalProvider,
          api_key: apiKey,
          base_url: baseUrl,
          ...(chatBackendConfigurable ? { backend: chatBackendWidget.value } : {}),
          supports_chat: supportsChatWidget.value === true,
          supports_image: supportsImageWidget.value === true,
          supports_video: supportsVideoWidget.value === true
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
    if (provider === "llama_cpp") {
      alert(t("The built-in llama_cpp provider cannot be deleted.", "内置 llama_cpp 提供商不能删除。"));
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

    const authWindow = window.open("about:blank", "_blank");

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
        if (authWindow) {
          authWindow.location.href = data.verification_uri;
        } else {
          window.open(data.verification_uri, "_blank");
        }
        startPollingStatus(provider, null, data.verification_uri);
      } else {
        throw new Error("No verification URI returned.");
      }
    } catch (err) {
      if (authWindow) authWindow.close();
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

    const authWindow = window.open("about:blank", "_blank");

    try {
      const response = await api.fetchApi("/llm-mini/oauth/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, flow: "device" })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      if (data.user_code && data.verification_uri) {
        statusWidget.value = t(
          "Waiting for device authentication...\nThe device code is in the popup.\nOpening authorization page...",
          "等待设备授权中...\n设备码在弹窗中。\n正在打开授权页面..."
        );
        node.setDirtyCanvas(true, true);

        if (authWindow) {
          authWindow.location.href = data.verification_uri;
        } else {
          window.open(data.verification_uri, "_blank");
        }

        startPollingStatus(provider, data.user_code, data.verification_uri);

        activeDeviceAuthModal = showDeviceAuthModal(
          provider,
          data.user_code,
          data.verification_uri,
          () => {
            activeDeviceAuthModal = null;
          }
        );
      } else {
        throw new Error("Invalid response from device OAuth start.");
      }
    } catch (err) {
      if (authWindow) authWindow.close();
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

  const llamaCheckLabel = t("Check llama.cpp", "检查 llama.cpp");
  node.addWidget("button", llamaCheckLabel, llamaCheckLabel, async () => {
    if (providerWidget.value !== "llama_cpp") {
      alert(t("Select the llama_cpp provider first.", "请先选择 llama_cpp 提供商。"));
      return;
    }
    statusWidget.value = t("Checking llama.cpp...", "正在检查 llama.cpp...");
    node.setDirtyCanvas(true, true);
    try {
      const response = await api.fetchApi("/llm-mini/llama/status");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      applyLlamaStatus(data);
    } catch (error) {
      statusWidget.value = t(`Check failed: ${error.message}`, `检查失败：${error.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const llamaHelpLabel = t("Copy Install Help", "复制安装帮助");
  node.addWidget("button", llamaHelpLabel, llamaHelpLabel, async () => {
    if (providerWidget.value !== "llama_cpp") {
      alert(t("Select the llama_cpp provider first.", "请先选择 llama_cpp 提供商。"));
      return;
    }
    try {
      const response = await api.fetchApi("/llm-mini/llama/install-help?backend=auto&shell=auto");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      const text = [...(data.warnings || []), ...(data.private_install_commands || []), "", ...(data.commands || []), ...(data.config_examples || [])].join("\n");
      copyToClipboard(text);
      alert(t("Installation help copied. Commands were not executed.", "安装帮助已复制，未执行任何命令。"));
    } catch (error) {
      alert(t(`Copy failed: ${error.message}`, `复制失败：${error.message}`));
    }
  });

  const llamaStartLabel = t("Start llama.cpp", "启动 llama.cpp");
  node.addWidget("button", llamaStartLabel, llamaStartLabel, async () => {
    if (providerWidget.value !== "llama_cpp") {
      alert(t("Select the llama_cpp provider first.", "请先选择 llama_cpp 提供商。"));
      return;
    }
    try {
      const response = await api.fetchApi("/llm-mini/llama/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      await loadSelectedProviderConfig();
    } catch (error) {
      alert(t(`Start failed: ${error.message}`, `启动失败：${error.message}`));
    }
  });

  const llamaStopLabel = t("Stop llama.cpp", "停止 llama.cpp");
  node.addWidget("button", llamaStopLabel, llamaStopLabel, async () => {
    if (providerWidget.value !== "llama_cpp") {
      alert(t("Select the llama_cpp provider first.", "请先选择 llama_cpp 提供商。"));
      return;
    }
    try {
      const response = await api.fetchApi("/llm-mini/llama/stop", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      await loadSelectedProviderConfig();
    } catch (error) {
      alert(t(`Stop failed: ${error.message}`, `停止失败：${error.message}`));
    }
  });

  const llamaModelsLabel = t("Manage llama.cpp Models", "管理 llama.cpp 模型");
  node.addWidget("button", llamaModelsLabel, llamaModelsLabel, async () => {
    if (providerWidget.value !== "llama_cpp") {
      alert(t("Select the llama_cpp provider first.", "请先选择 llama_cpp 提供商。"));
      return;
    }
    try {
      const response = await api.fetchApi("/llm-mini/llama/status");
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      showLlamaCppManagerModal(data, applyLlamaStatus);
    } catch (error) {
      alert(t(`Load failed: ${error.message}`, `加载失败：${error.message}`));
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

  const refreshModelsLabel = t("Refresh & Configure Model List", "刷新并配置模型列表");
  node.addWidget("button", refreshModelsLabel, refreshModelsLabel, async () => {
    const provider = providerWidget.value;
    if (!provider || provider === "custom_provider") {
      alert(t("Please select a valid provider first.", "请先选择一个有效的提供商。"));
      return;
    }
    if (provider === "llama_cpp") {
      try {
        const response = await api.fetchApi("/llm-mini/llama/status");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        showLlamaCppManagerModal(data, applyLlamaStatus);
      } catch (error) {
        alert(t(`Refresh failed: ${error.message}`, `刷新失败：${error.message}`));
      }
      return;
    }

    statusWidget.value = t("Fetching model list...", "正在获取模型列表...");
    node.setDirtyCanvas(true, true);

    try {
      const response = await api.fetchApi("/llm-mini/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      if (!data.models || data.models.length === 0) throw new Error(t("No models returned.", "没有返回可用模型。"));

      statusWidget.value = t("Models loaded successfully.", "模型列表拉取成功。");
      node.setDirtyCanvas(true, true);

      const providers = await fetchProviderInfo();
      const pInfo = providers.find(p => p.id === provider);
      let existingModels = pInfo && pInfo.default_models ? [...pInfo.default_models] : [];
      existingModels = existingModels.filter(m => m !== "click Refresh Models" && m !== "点击刷新模型");

      showModelSelectionModal(
        provider,
        data.models,
        existingModels,
        // onSave (保存为配置并同步更新当前画布节点)
        (selectedList) => {
          updateAllRelatedNodes(provider, selectedList);
          statusWidget.value = t("Static default models saved and applied.", "静态默认模型已保存并更新到节点。");
          node.setDirtyCanvas(true, true);
        },
        // onApply (仅临时更新当前画布节点)
        (selectedList) => {
          updateAllRelatedNodes(provider, selectedList);
          statusWidget.value = t("Models temporarily applied to nodes.", "模型列表已临时应用到节点。");
          node.setDirtyCanvas(true, true);
        }
      );
    } catch (err) {
      alert(`Refresh failed: ${err.message}`);
      statusWidget.value = t(`Refresh failed: ${err.message}`, `刷新模型失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const customModelInput = node.addWidget("text", t("Custom Model ID", "自定义模型 ID"), "", () => {}, { multiline: false });
  customModelInput.serializeValue = () => undefined;

  const addModelLabel = t("Add Custom Model", "添加自定义模型");
  node.addWidget("button", addModelLabel, addModelLabel, async () => {
    const provider = providerWidget.value;
    if (!provider || provider === "custom_provider") {
      alert(t("Please select a valid provider first.", "请先选择一个有效的提供商。"));
      return;
    }
    if (provider === "llama_cpp") {
      alert(t("Place GGUF files in the configured models directory, then refresh the llama.cpp model list.", "请将 GGUF 文件放入配置的模型目录，然后刷新 llama.cpp 模型列表。"));
      return;
    }
    const newModel = customModelInput.value.trim();
    if (!newModel) {
      alert(t("Please enter a model ID.", "请输入模型 ID。"));
      return;
    }

    statusWidget.value = t("Adding model...", "正在添加模型...");
    node.setDirtyCanvas(true, true);

    try {
      // 现场从服务器拉取最新的配置，彻底避免本地缓存未就绪时的覆盖 Bug
      const providers = await fetchProviderInfo();
      const pInfo = providers.find(p => p.id === provider);
      let existingModels = pInfo && pInfo.default_models ? [...pInfo.default_models] : [];
      existingModels = existingModels.filter(m => m !== "click Refresh Models" && m !== "点击刷新模型");

      if (existingModels.includes(newModel)) {
        alert(t("Model ID already exists.", "该模型 ID 已存在。"));
        statusWidget.value = t("Model already exists.", "模型已存在。");
        node.setDirtyCanvas(true, true);
        return;
      }

      existingModels.push(newModel);

      const response = await api.fetchApi("/llm-mini/config/save-default-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: provider,
          default_models: existingModels
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);

      // 顺便更新本地的 currentProvidersData 缓存
      if (typeof currentProvidersData !== "undefined" && currentProvidersData) {
        const localPInfo = currentProvidersData.find(p => p.id === provider);
        if (localPInfo) {
          localPInfo.default_models = existingModels;
        }
      }

      updateAllRelatedNodes(provider, existingModels);

      statusWidget.value = t(`Model "${newModel}" added successfully!`, `模型 "${newModel}" 添加成功！`);
      customModelInput.value = "";
      node.setDirtyCanvas(true, true);
      alert(t(`Model "${newModel}" added and saved as default.`, `模型 "${newModel}" 已添加并保存为默认静态列表。`));
    } catch (err) {
      alert(`Add failed: ${err.message}`);
      statusWidget.value = t(`Add failed: ${err.message}`, `添加失败: ${err.message}`);
      node.setDirtyCanvas(true, true);
    }
  });

  const originalConfigure = node.onConfigure;
  node.onConfigure = function() {
    const r = originalConfigure ? originalConfigure.apply(this, arguments) : undefined;
    setTimeout(() => {
      loadSelectedProviderConfig();
    }, 100);
    return r;
  };

  await loadSelectedProviderConfig();
  
  node.size = [350, node.computeSize()[1]];
  node.setDirtyCanvas(true, true);
  
  node.onRemoved = function() {
    stopPolling();
  };
}
