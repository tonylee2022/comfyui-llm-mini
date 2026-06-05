import { app } from "../../../scripts/app.js";
import { isTargetNode, setupNodeByType } from "./modules/node_setup.js";
import { localizeVueNodeDef, scheduleLocalization } from "./modules/localization.js";

app.registerExtension({
  name: "ComfyUI.LLMMini.ModelSelector",
  beforeRegisterVueAppNodeDefs(nodeDefs) {
    for (const nodeDef of nodeDefs) {
      if (nodeDef && isTargetNode(nodeDef.name)) {
        localizeVueNodeDef(nodeDef);
      }
    }
  },

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!isTargetNode(nodeData.name)) return;
    
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = original ? original.apply(this, arguments) : undefined;
      setupNodeByType(this, nodeData.name);
      return result;
    };

    // 确保在加载保存的工作流（刷新页面）并反序列化配置后，重新应用本地化翻译
    const originalConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = originalConfigure ? originalConfigure.apply(this, arguments) : undefined;
      scheduleLocalization(this, 50);
      return result;
    };

    const originalInputAdded = nodeType.prototype.onInputAdded;
    nodeType.prototype.onInputAdded = function () {
      const result = originalInputAdded ? originalInputAdded.apply(this, arguments) : undefined;
      scheduleLocalization(this);
      return result;
    };
  },
  
  // 扩展生命周期钩子：当任何节点被创建并添加到图表中时调用
  nodeCreated(node) {
    if (isTargetNode(node.comfyClass)) {
      scheduleLocalization(node, 50);
    }
  },

  // Nodes 2.0 synchronizes slots while loading a workflow, then invokes this hook.
  loadedGraphNode(node) {
    if (isTargetNode(node.comfyClass)) {
      scheduleLocalization(node);
    }
  },

  // Apply once more after all workflow nodes and slots have finished loading.
  afterConfigureGraph() {
    if (app.graph && app.graph._nodes) {
      for (const node of app.graph._nodes) {
        if (node && isTargetNode(node.comfyClass)) {
          scheduleLocalization(node, 100);
        }
      }
    }
  }
});
