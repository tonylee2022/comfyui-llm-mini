import { api } from "../../../../scripts/api.js";
import { t, findWidget, updateCombo } from "./utils.js";

async function fetchPersonaRecord(name) {
  const response = await api.fetchApi("/llm-mini/persona/get", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

export async function fetchPersonaContent(name) {
  const record = await fetchPersonaRecord(name);
  return record.content || "";
}

export function updatePersonaCombos(node, personas, selectName) {
  updateCombo(node, "persona_name", personas);
  if (selectName && personas.includes(selectName)) {
    const widget = findWidget(node, "persona_name");
    if (widget) widget.value = selectName;
  }
}

export function refreshAllPersonaNodes(graph, personas) {
  if (!graph) return;
  const loadNodes = graph.findNodesByType("LLMMiniLoadPersona");
  if (loadNodes) {
    loadNodes.forEach((node) => {
      const nameWidget = node.widgets ? node.widgets.find((widget) => widget.name === "persona_name") : null;
      updatePersonaCombos(node, personas, nameWidget ? nameWidget.value : null);
    });
  }
  const managerNodes = graph.findNodesByType("LLMMiniPersonaManager");
  if (managerNodes) {
    managerNodes.forEach((node) => {
      const nameWidget = node.widgets ? node.widgets.find((widget) => widget.name === "persona_name") : null;
      updatePersonaCombos(node, personas, nameWidget ? nameWidget.value : null);
    });
  }
}

export async function setupPersonaManager(node) {
  const nameWidget = findWidget(node, "persona_name");
  const newNameWidget = findWidget(node, "new_name");
  const contentWidget = findWidget(node, "content");
  const sourceWidget = node.addWidget("text", t("Persona Source", "模板来源"), "", () => {}, { multiline: false });
  sourceWidget.serializeValue = () => undefined;
  sourceWidget.disabled = true;

  let currentPersona = { source: "missing", overrides_builtin: false };
  let deleteButton = null;

  const updateSource = (record) => {
    currentPersona = record || { source: "missing", overrides_builtin: false };
    if (currentPersona.source === "builtin") {
      sourceWidget.value = t("Built-in (read-only)", "内置（只读）");
    } else if (currentPersona.source === "local" && currentPersona.overrides_builtin) {
      sourceWidget.value = t("Local override", "本地覆盖");
    } else if (currentPersona.source === "local") {
      sourceWidget.value = t("Local", "本地");
    } else {
      sourceWidget.value = t("Not found", "未找到");
    }
    if (deleteButton) deleteButton.disabled = currentPersona.source !== "local";
  };

  const loadPersona = async (name) => {
    if (!name) {
      if (contentWidget) contentWidget.value = "";
      if (newNameWidget) newNameWidget.value = "";
      updateSource(null);
      return;
    }
    const record = await fetchPersonaRecord(name);
    if (contentWidget) contentWidget.value = record.content || "";
    if (newNameWidget) newNameWidget.value = name;
    updateSource(record);
  };

  if (nameWidget) {
    if (nameWidget.value) {
      try {
        await loadPersona(nameWidget.value);
      } catch (error) {
        updateSource(null);
        alert(`LLM Mini: ${error.message}`);
      }
    }

    const originalCallback = nameWidget.callback;
    nameWidget.callback = async function (value) {
      if (originalCallback) originalCallback.apply(this, arguments);
      try {
        await loadPersona(value);
      } catch (error) {
        updateSource(null);
        alert(`LLM Mini: ${error.message}`);
      }
    };
  }

  const saveLabel = t("Save Persona", "保存面具");
  node.addWidget("button", saveLabel, saveLabel, async () => {
    const currentName = nameWidget ? nameWidget.value : "";
    let saveName = newNameWidget ? newNameWidget.value.trim() : "";
    if (!saveName) saveName = currentName;
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
      alert(data.overrides_builtin
        ? t("Saved as a local override. The built-in persona was not changed.", "已保存为本地覆盖，内置人格面具未被修改。")
        : t("Local persona saved successfully.", "本地人格面具保存成功。"));
      if (data.personas) {
        refreshAllPersonaNodes(node.graph, data.personas);
        updatePersonaCombos(node, data.personas, saveName);
        await loadPersona(saveName);
      }
    } catch (error) {
      alert(`LLM Mini: ${error.message}`);
    }
  });

  const deleteLabel = t("Delete Persona", "删除面具");
  deleteButton = node.addWidget("button", deleteLabel, deleteLabel, async () => {
    const deleteName = nameWidget ? nameWidget.value : "";
    if (!deleteName) {
      alert(t("No persona selected to delete.", "未选择要删除的人格面具。"));
      return;
    }
    if (currentPersona.source !== "local") {
      alert(t("Built-in personas are read-only. Save to create a local override.", "内置人格面具为只读；编辑后保存会创建本地覆盖。"));
      return;
    }
    const confirmMessage = currentPersona.overrides_builtin
      ? t(`Delete the local override for "${deleteName}" and restore the built-in persona?`, `删除“${deleteName}”的本地覆盖并恢复内置版本？`)
      : t(`Are you sure you want to delete local persona "${deleteName}"?`, `确定要删除本地人格面具“${deleteName}”？`);
    if (!confirm(confirmMessage)) return;
    try {
      const response = await api.fetchApi("/llm-mini/persona/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: deleteName }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      alert(data.restored_builtin
        ? t("Local override deleted. The built-in persona has been restored.", "本地覆盖已删除，内置人格面具已恢复。")
        : t("Local persona deleted successfully.", "本地人格面具删除成功。"));
      if (data.personas) {
        const nextSelect = data.personas.includes(deleteName) ? deleteName : (data.personas[0] || "");
        refreshAllPersonaNodes(node.graph, data.personas);
        updatePersonaCombos(node, data.personas, nextSelect);
        await loadPersona(nextSelect);
      }
    } catch (error) {
      alert(`LLM Mini: ${error.message}`);
    }
  });
  deleteButton.disabled = currentPersona.source !== "local";

  const originalConfigure = node.onConfigure;
  node.onConfigure = function() {
    const result = originalConfigure ? originalConfigure.apply(this, arguments) : undefined;
    setTimeout(async () => {
      if (nameWidget && nameWidget.value) {
        try {
          await loadPersona(nameWidget.value);
          node.setDirtyCanvas && node.setDirtyCanvas(true, true);
        } catch (error) {
          updateSource(null);
        }
      }
    }, 100);
    return result;
  };

  node.setSize(node.computeSize());
}
