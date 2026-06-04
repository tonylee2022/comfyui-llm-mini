import { api } from "../../../../scripts/api.js";
import { t, findWidget, updateCombo } from "./utils.js";

export async function fetchPersonaContent(name) {
  const response = await api.fetchApi("/llm-mini/persona/get", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) return "";
  const data = await response.json();
  return data.content || "";
}

export function updatePersonaCombos(node, personas, selectName) {
  updateCombo(node, "persona_name", personas);
  if (selectName && personas.includes(selectName)) {
    const w = findWidget(node, "persona_name");
    if (w) w.value = selectName;
  }
}

export function refreshAllPersonaNodes(graph, personas) {
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

export async function setupPersonaManager(node) {
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

  const originalConfigure = node.onConfigure;
  node.onConfigure = function() {
    const r = originalConfigure ? originalConfigure.apply(this, arguments) : undefined;
    setTimeout(async () => {
      if (nameWidget && nameWidget.value) {
        const content = await fetchPersonaContent(nameWidget.value);
        if (contentWidget) contentWidget.value = content;
        if (newNameWidget) newNameWidget.value = nameWidget.value;
        node.setDirtyCanvas && node.setDirtyCanvas(true, true);
      }
    }, 100);
    return r;
  };

  node.setSize(node.computeSize());
}
