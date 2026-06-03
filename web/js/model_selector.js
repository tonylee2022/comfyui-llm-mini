import { app } from "../../../scripts/app.js";
import { TARGET_NODES, setupNodeByType } from "./modules/node_setup.js";

app.registerExtension({
  name: "ComfyUI.LLMMini.ModelSelector",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!TARGET_NODES.has(nodeData.name)) return;
    const original = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = original ? original.apply(this, arguments) : undefined;
      setupNodeByType(this, nodeData.name);
      return result;
    };
  },
});
