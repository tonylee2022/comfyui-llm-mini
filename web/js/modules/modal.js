import { t } from "./utils.js";
import { api } from "../../../../scripts/api.js";

const CSS_STYLE = `
.llm-mini-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(10, 10, 15, 0.7);
  backdrop-filter: blur(10px);
  z-index: 10000;
  display: flex;
  justify-content: center;
  align-items: center;
  opacity: 0;
  transition: opacity 0.25s ease-out;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}
.llm-mini-modal-overlay.active {
  opacity: 1;
}
.llm-mini-modal {
  width: 520px;
  max-width: 90%;
  max-height: 80vh;
  background: rgba(20, 20, 30, 0.95);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 16px;
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05) inset;
  display: flex;
  flex-direction: column;
  color: #f3f4f6;
  transform: scale(0.95);
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  overflow: hidden;
}
.llm-mini-modal-overlay.active .llm-mini-modal {
  transform: scale(1);
}
.llm-mini-modal-header {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.llm-mini-modal-title {
  margin: 0;
  font-size: 1.15rem;
  font-weight: 600;
  background: linear-gradient(135deg, #a78bfa, #818cf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.llm-mini-modal-close {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.4);
  font-size: 1.5rem;
  cursor: pointer;
  line-height: 1;
  padding: 0;
  transition: color 0.15s;
}
.llm-mini-modal-close:hover {
  color: #fff;
}
.llm-mini-modal-toolbar {
  padding: 12px 24px;
  background: rgba(0, 0, 0, 0.15);
  display: flex;
  gap: 16px;
  align-items: center;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.llm-mini-modal-search {
  flex: 1;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 8px 12px;
  color: #fff;
  font-size: 0.9rem;
  outline: none;
  transition: all 0.2s;
}
.llm-mini-modal-search:focus {
  border-color: #818cf8;
  background: rgba(255, 255, 255, 0.08);
  box-shadow: 0 0 0 2px rgba(129, 140, 248, 0.25);
}
.llm-mini-modal-link {
  font-size: 0.85rem;
  color: #818cf8;
  text-decoration: none;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
  transition: color 0.2s;
}
.llm-mini-modal-link:hover {
  color: #a78bfa;
}
.llm-mini-modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.llm-mini-modal-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s, border-color 0.15s;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid transparent;
}
.llm-mini-modal-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.04);
}
.llm-mini-modal-item.checked {
  background: rgba(129, 140, 248, 0.08);
  border-color: rgba(129, 140, 248, 0.2);
}
.llm-mini-modal-checkbox {
  appearance: none;
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-radius: 4px;
  outline: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  justify-content: center;
  align-items: center;
  transition: all 0.15s;
}
.llm-mini-modal-checkbox:checked {
  border-color: #818cf8;
  background: #818cf8;
}
.llm-mini-modal-checkbox:checked::after {
  content: "✓";
  color: #fff;
  font-size: 11px;
  font-weight: bold;
}
.llm-mini-modal-modelname {
  font-size: 0.95rem;
  font-family: monospace;
  color: #e5e7eb;
}
.llm-mini-modal-footer {
  padding: 16px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
.llm-mini-modal-btn {
  padding: 9px 16px;
  border-radius: 8px;
  font-size: 0.88rem;
  font-weight: 500;
  cursor: pointer;
  outline: none;
  border: none;
  transition: all 0.2s ease;
}
.llm-mini-modal-btn-cancel {
  background: rgba(255, 255, 255, 0.06);
  color: #d1d5db;
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.llm-mini-modal-btn-cancel:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}
.llm-mini-modal-btn-apply {
  background: rgba(129, 140, 248, 0.12);
  color: #a5b4fc;
  border: 1px solid rgba(129, 140, 248, 0.25);
}
.llm-mini-modal-btn-apply:hover {
  background: rgba(129, 140, 248, 0.22);
  color: #fff;
}
.llm-mini-modal-btn-save {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: #fff;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3);
}
.llm-mini-modal-btn-save:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.4);
}
.llm-mini-modal-btn-save:active {
  transform: translateY(0);
}

.llm-mini-modal-code-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 16px 0;
}
.llm-mini-modal-code-title {
  font-size: 0.95rem;
  color: rgba(255, 255, 255, 0.7);
  font-weight: 500;
}
.llm-mini-modal-code-value {
  width: 100%;
  max-width: 320px;
  box-sizing: border-box;
  font-size: 2rem;
  font-weight: 700;
  letter-spacing: 2px;
  color: #a78bfa;
  font-family: monospace;
  background: rgba(255, 255, 255, 0.04);
  padding: 14px 28px;
  border-radius: 8px;
  border: 1px dashed rgba(167, 139, 250, 0.4);
  text-align: center;
  outline: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  transition: all 0.2s ease;
}
.llm-mini-modal-code-value:hover,
.llm-mini-modal-code-value:focus {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(167, 139, 250, 0.8);
  box-shadow: 0 0 0 2px rgba(167, 139, 250, 0.2), 0 4px 12px rgba(0, 0, 0, 0.2);
}
.llm-mini-modal-buttons-row {
  display: flex;
  gap: 12px;
  width: 100%;
  justify-content: center;
  margin-top: 8px;
}
.llm-mini-modal-btn-copy {
  background: rgba(129, 140, 248, 0.12);
  color: #a5b4fc;
  border: 1px solid rgba(129, 140, 248, 0.25);
}
.llm-mini-modal-btn-copy:hover {
  background: rgba(129, 140, 248, 0.22);
  color: #fff;
}
.llm-mini-modal-btn-open {
  background: linear-gradient(135deg, #6366f1, #4f46e5);
  color: #fff;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.3);
}
.llm-mini-modal-btn-open:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(79, 70, 229, 0.4);
}
.llm-mini-modal-btn-open:active {
  transform: translateY(0);
}
.llm-mini-modal-instructions {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.5);
  text-align: center;
  line-height: 1.6;
  max-width: 90%;
  margin-bottom: 8px;
}
`;

let styleInjected = false;

function injectStyles() {
  if (styleInjected) return;
  const styleEl = document.createElement("style");
  styleEl.textContent = CSS_STYLE;
  document.head.appendChild(styleEl);
  styleInjected = true;
}

export function showModelSelectionModal(provider, models, currentlyConfiguredModels = [], onSave, onApply) {
  injectStyles();

  // 避免重复打开
  const existing = document.getElementById("llm-mini-models-modal-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "llm-mini-models-modal-overlay";
  overlay.className = "llm-mini-modal-overlay";

  const modal = document.createElement("div");
  modal.className = "llm-mini-modal";
  overlay.appendChild(modal);

  // Title section
  const header = document.createElement("div");
  header.className = "llm-mini-modal-header";
  const title = document.createElement("h3");
  title.className = "llm-mini-modal-title";
  title.textContent = `${t("Choose Static Default Models", "选择静态默认模型")} (${provider})`;
  header.appendChild(title);
  const closeButton = document.createElement("button");
  closeButton.className = "llm-mini-modal-close";
  closeButton.textContent = "×";
  header.appendChild(closeButton);
  modal.appendChild(header);

  // Toolbar (Search + Select All)
  const toolbar = document.createElement("div");
  toolbar.className = "llm-mini-modal-toolbar";
  toolbar.innerHTML = `
    <input type="text" class="llm-mini-modal-search" placeholder="${t("Search models...", "搜索模型...")}" />
    <span class="llm-mini-modal-link select-all">${t("Select All", "全选")}</span>
    <span class="llm-mini-modal-link deselect-all">${t("Clear All", "清空")}</span>
  `;
  modal.appendChild(toolbar);

  // List of models
  const body = document.createElement("div");
  body.className = "llm-mini-modal-body";
  modal.appendChild(body);

  const modelElements = [];
  const currentlyConfiguredSet = new Set(currentlyConfiguredModels || []);
  const selectedModels = new Set();

  // 预勾选已配置的模型
  if (currentlyConfiguredModels && currentlyConfiguredModels.length) {
    currentlyConfiguredModels.forEach(m => {
      if (models.includes(m)) {
        selectedModels.add(m);
      }
    });
  }

  models.forEach((modelName) => {
    const isConfigured = currentlyConfiguredSet.has(modelName);
    const item = document.createElement("div");
    item.className = isConfigured ? "llm-mini-modal-item checked" : "llm-mini-modal-item";
    item.dataset.model = modelName;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "llm-mini-modal-checkbox";
    checkbox.checked = isConfigured;

    const nameSpan = document.createElement("span");
    nameSpan.className = "llm-mini-modal-modelname";
    nameSpan.textContent = modelName;

    item.appendChild(checkbox);
    item.appendChild(nameSpan);
    body.appendChild(item);

    modelElements.push({ element: item, modelName, checkbox });


    // Item click handler
    item.addEventListener("click", (e) => {
      if (e.target !== checkbox) {
        checkbox.checked = !checkbox.checked;
      }
      if (checkbox.checked) {
        item.classList.add("checked");
        selectedModels.add(modelName);
      } else {
        item.classList.remove("checked");
        selectedModels.delete(modelName);
      }
    });
  });

  // Search input handler
  const searchInput = toolbar.querySelector(".llm-mini-modal-search");
  searchInput.addEventListener("input", (e) => {
    const query = e.target.value.toLowerCase().trim();
    modelElements.forEach(({ element, modelName }) => {
      if (modelName.toLowerCase().includes(query)) {
        element.style.display = "flex";
      } else {
        element.style.display = "none";
      }
    });
  });

  // Select all handler
  toolbar.querySelector(".select-all").addEventListener("click", () => {
    modelElements.forEach(({ element, checkbox, modelName }) => {
      if (element.style.display !== "none") {
        checkbox.checked = true;
        element.classList.add("checked");
        selectedModels.add(modelName);
      }
    });
  });

  // Clear all handler
  toolbar.querySelector(".deselect-all").addEventListener("click", () => {
    modelElements.forEach(({ element, checkbox, modelName }) => {
      if (element.style.display !== "none") {
        checkbox.checked = false;
        element.classList.remove("checked");
        selectedModels.delete(modelName);
      }
    });
  });

  // Footer section
  const footer = document.createElement("div");
  footer.className = "llm-mini-modal-footer";
  footer.innerHTML = `
    <button class="llm-mini-modal-btn llm-mini-modal-btn-cancel">${t("Cancel", "取消")}</button>
    <button class="llm-mini-modal-btn llm-mini-modal-btn-apply">${t("Apply Temporarily", "仅临时应用")}</button>
    <button class="llm-mini-modal-btn llm-mini-modal-btn-save">${t("Save as Static List", "保存为静态列表")}</button>
  `;
  modal.appendChild(footer);

  const closeModal = () => {
    overlay.classList.remove("active");
    setTimeout(() => overlay.remove(), 250);
  };

  header.querySelector(".llm-mini-modal-close").addEventListener("click", closeModal);
  footer.querySelector(".llm-mini-modal-btn-cancel").addEventListener("click", closeModal);

  // Apply temporarily handler
  footer.querySelector(".llm-mini-modal-btn-apply").addEventListener("click", () => {
    const list = Array.from(selectedModels);
    if (list.length === 0) {
      alert(t("Please select at least one model.", "请至少选择一个模型。"));
      return;
    }
    onApply(list);
    closeModal();
  });

  // Save to static handler
  footer.querySelector(".llm-mini-modal-btn-save").addEventListener("click", async () => {
    const list = Array.from(selectedModels);
    if (list.length === 0) {
      alert(t("Please select at least one model.", "请至少选择一个模型。"));
      return;
    }
    const saveBtn = footer.querySelector(".llm-mini-modal-btn-save");
    const originalText = saveBtn.textContent;
    saveBtn.textContent = t("Saving...", "保存中...");
    saveBtn.disabled = true;

    try {
      const response = await api.fetchApi("/llm-mini/config/save-default-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: provider,
          default_models: list
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      
      onSave(list);
      closeModal();
      alert(t("Static default models saved successfully!", "静态默认模型保存成功！下次加载将作为默认菜单选项。"));
    } catch (err) {
      alert(`Save failed: ${err.message}`);
      saveBtn.textContent = originalText;
      saveBtn.disabled = false;
    }
  });

  // Append & Show
  document.body.appendChild(overlay);
  // Force reflow for CSS transition
  overlay.offsetWidth;
  overlay.classList.add("active");
}

function selectDeviceCode(input) {
  input.focus();
  input.select();
  input.setSelectionRange(0, input.value.length);
}

async function copyDeviceCode(text, input) {
  if (!text) return false;
  selectDeviceCode(input);
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.warn("Navigator clipboard copy failed, falling back:", err);
    }
  }
  try {
    return document.execCommand("copy");
  } catch (err) {
    console.error("Fallback copy failed:", err);
    return false;
  }
}

export function showDeviceAuthModal(provider, userCode, verificationUri, onCancel) {
  injectStyles();

  // 避免重复打开
  const existing = document.getElementById("llm-mini-device-auth-modal-overlay");
  if (existing) existing.remove();

  const overlay = document.createElement("div");
  overlay.id = "llm-mini-device-auth-modal-overlay";
  overlay.className = "llm-mini-modal-overlay";

  const modal = document.createElement("div");
  modal.className = "llm-mini-modal";
  modal.style.width = "450px";
  overlay.appendChild(modal);

  // Header
  const header = document.createElement("div");
  header.className = "llm-mini-modal-header";
  const title = document.createElement("h3");
  title.className = "llm-mini-modal-title";
  title.textContent = `${t("Device Authorization", "设备码授权")} (${provider})`;
  header.appendChild(title);

  const closeButton = document.createElement("button");
  closeButton.className = "llm-mini-modal-close";
  closeButton.textContent = "×";
  header.appendChild(closeButton);
  modal.appendChild(header);

  // Body
  const body = document.createElement("div");
  body.className = "llm-mini-modal-body";

  const codeContainer = document.createElement("div");
  codeContainer.className = "llm-mini-modal-code-container";

  const codeTitle = document.createElement("div");
  codeTitle.className = "llm-mini-modal-code-title";
  codeTitle.textContent = t("Your Device Verification Code:", "您的设备授权验证码：");
  codeContainer.appendChild(codeTitle);

  const codeValue = document.createElement("input");
  codeValue.className = "llm-mini-modal-code-value";
  codeValue.type = "text";
  codeValue.readOnly = true;
  codeValue.value = userCode;
  codeValue.title = t("Click to select all", "点击全选");
  codeValue.addEventListener("focus", () => selectDeviceCode(codeValue));
  codeValue.addEventListener("click", () => selectDeviceCode(codeValue));
  codeContainer.appendChild(codeValue);

  const instructions = document.createElement("div");
  instructions.className = "llm-mini-modal-instructions";
  instructions.textContent = t(
    "Click Copy Code, then paste it on the authorization page.",
    "点击复制验证码，然后粘贴到授权页面。"
  );
  codeContainer.appendChild(instructions);

  const buttonsRow = document.createElement("div");
  buttonsRow.className = "llm-mini-modal-buttons-row";

  // 复制按钮
  const copyBtn = document.createElement("button");
  copyBtn.className = "llm-mini-modal-btn llm-mini-modal-btn-copy";
  copyBtn.textContent = t("Copy Code", "复制验证码");
  copyBtn.addEventListener("click", async () => {
    const success = await copyDeviceCode(userCode, codeValue);
    if (success) {
      copyBtn.textContent = t("Copied!", "已复制！");
      copyBtn.style.background = "rgba(52, 211, 153, 0.15)";
      copyBtn.style.color = "#34d399";
      copyBtn.style.borderColor = "rgba(52, 211, 153, 0.3)";
      setTimeout(() => {
        copyBtn.textContent = t("Copy Code", "复制验证码");
        copyBtn.style.background = "";
        copyBtn.style.color = "";
        copyBtn.style.borderColor = "";
      }, 2000);
    } else {
      alert(t("Copy failed. The code is selected, press Ctrl+C to copy it.", "复制失败。验证码已选中，请按 Ctrl+C 复制。"));
    }
  });
  buttonsRow.appendChild(copyBtn);

  // 打开页面按钮
  const openBtn = document.createElement("button");
  openBtn.className = "llm-mini-modal-btn llm-mini-modal-btn-open";
  openBtn.textContent = t("Open Auth Page", "打开授权页面");
  openBtn.addEventListener("click", () => {
    window.open(verificationUri, "_blank");
  });
  buttonsRow.appendChild(openBtn);

  codeContainer.appendChild(buttonsRow);
  body.appendChild(codeContainer);
  modal.appendChild(body);

  // Footer
  const footer = document.createElement("div");
  footer.className = "llm-mini-modal-footer";

  const cancelBtn = document.createElement("button");
  cancelBtn.className = "llm-mini-modal-btn llm-mini-modal-btn-cancel";
  cancelBtn.textContent = t("Close", "关闭");
  footer.appendChild(cancelBtn);
  modal.appendChild(footer);

  const closeModal = () => {
    overlay.classList.remove("active");
    setTimeout(() => overlay.remove(), 250);
    if (onCancel) onCancel();
  };

  closeButton.addEventListener("click", closeModal);
  cancelBtn.addEventListener("click", closeModal);

  // Append & Show
  document.body.appendChild(overlay);
  overlay.offsetWidth;
  overlay.classList.add("active");
  setTimeout(() => selectDeviceCode(codeValue), 50);

  return {
    close: () => {
      overlay.classList.remove("active");
      setTimeout(() => overlay.remove(), 250);
    }
  };
}

export function showLlamaCppManagerModal(initialStatus, onChanged) {
  injectStyles();
  document.getElementById("llm-mini-llama-modal-overlay")?.remove();

  const overlay = document.createElement("div");
  overlay.id = "llm-mini-llama-modal-overlay";
  overlay.className = "llm-mini-modal-overlay";
  const modal = document.createElement("div");
  modal.className = "llm-mini-modal";
  overlay.appendChild(modal);

  const header = document.createElement("div");
  header.className = "llm-mini-modal-header";
  const title = document.createElement("h3");
  title.className = "llm-mini-modal-title";
  title.textContent = t("llama.cpp Local Models", "llama.cpp 本地模型");
  const closeButton = document.createElement("button");
  closeButton.className = "llm-mini-modal-close";
  closeButton.textContent = "×";
  header.append(title, closeButton);
  modal.appendChild(header);

  const body = document.createElement("div");
  body.className = "llm-mini-modal-body";
  modal.appendChild(body);

  const footer = document.createElement("div");
  footer.className = "llm-mini-modal-footer";
  const refreshButton = document.createElement("button");
  refreshButton.className = "llm-mini-modal-btn llm-mini-modal-btn-apply";
  refreshButton.textContent = t("Refresh", "刷新");
  const closeFooterButton = document.createElement("button");
  closeFooterButton.className = "llm-mini-modal-btn llm-mini-modal-btn-cancel";
  closeFooterButton.textContent = t("Close", "关闭");
  footer.append(refreshButton, closeFooterButton);
  modal.appendChild(footer);

  let status = initialStatus || {};
  const request = async (path, model = null) => {
    const response = await api.fetchApi(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(model ? { model } : {})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  };

  const refresh = async (reload = false) => {
    body.textContent = t("Loading...", "正在加载...");
    try {
      if (reload) await request("/llm-mini/llama/models/refresh");
      const response = await api.fetchApi("/llm-mini/llama/status");
      status = await response.json();
      if (!response.ok) throw new Error(status.error || `HTTP ${response.status}`);
      render();
      if (onChanged) onChanged(status);
    } catch (error) {
      body.textContent = t(`Failed: ${error.message}`, `失败：${error.message}`);
    }
  };

  const render = () => {
    body.textContent = "";
    const summary = document.createElement("div");
    summary.className = "llm-mini-modal-instructions";
    summary.style.textAlign = "left";
    summary.textContent = status.running
      ? t(`Router is running (PID ${status.pid || "?"}).`, `Router 正在运行（PID ${status.pid || "?"}）。`)
      : t("Router is stopped. Start it before managing models.", "Router 未启动，请先启动后管理模型。");
    body.appendChild(summary);

    const models = Array.isArray(status.models) ? status.models : [];
    if (!models.length) {
      const empty = document.createElement("div");
      empty.className = "llm-mini-modal-instructions";
      empty.textContent = t("No GGUF models reported by the router.", "Router 未发现 GGUF 模型。");
      body.appendChild(empty);
      return;
    }

    models.forEach((model) => {
      const modelId = String(model.id || model.model || "");
      const loaded = model.status?.value === "loaded" || model.loaded === true;
      const modalities = model.architecture?.input_modalities || [];
      const active = Number(status.active_requests?.[modelId] || 0);
      const row = document.createElement("div");
      row.className = "llm-mini-modal-item";
      row.style.cursor = "default";
      const label = document.createElement("span");
      label.className = "llm-mini-modal-modelname";
      label.style.flex = "1";
      label.textContent = `${modelId} · ${loaded ? t("loaded", "已加载") : t("unloaded", "未加载")} · ${modalities.join("/") || "text"}${active ? ` · active ${active}` : ""}`;
      const action = document.createElement("button");
      action.className = `llm-mini-modal-btn ${loaded ? "llm-mini-modal-btn-cancel" : "llm-mini-modal-btn-apply"}`;
      action.textContent = loaded ? t("Unload", "卸载") : t("Load", "加载");
      action.disabled = active > 0;
      action.addEventListener("click", async () => {
        action.disabled = true;
        try {
          await request(`/llm-mini/llama/models/${loaded ? "unload" : "load"}`, modelId);
          await refresh(false);
        } catch (error) {
          alert(t(`Operation failed: ${error.message}`, `操作失败：${error.message}`));
          action.disabled = false;
        }
      });
      row.append(label, action);
      body.appendChild(row);
    });
  };

  const close = () => {
    overlay.classList.remove("active");
    setTimeout(() => overlay.remove(), 250);
  };
  closeButton.addEventListener("click", close);
  closeFooterButton.addEventListener("click", close);
  refreshButton.addEventListener("click", () => refresh(true));
  document.body.appendChild(overlay);
  overlay.offsetWidth;
  overlay.classList.add("active");
  render();
  return { close };
}
