import { app } from "../../../scripts/app.js";
import { TARGET_NODES, setupNodeByType } from "./modules/node_setup.js";
import { applyLocalization } from "./modules/localization.js";

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

    // 确保在加载保存的工作流（刷新页面）并反序列化配置后，重新应用本地化翻译
    const originalConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const result = originalConfigure ? originalConfigure.apply(this, arguments) : undefined;
      applyLocalization(this);
      // 针对 Nodes 2.0 异步渲染，使用延时再次确保翻译生效
      setTimeout(() => {
        applyLocalization(this);
        if (app.canvas) {
          app.canvas.setDirty(true, true);
        }
      }, 50);
      return result;
    };

    // 终极保底：在每次节点渲染时，确保应用最新的本地化翻译（以防 ComfyUI 动态修改端口）
    const originalDrawForeground = nodeType.prototype.onDrawForeground;
    nodeType.prototype.onDrawForeground = function (ctx, canvas) {
      applyLocalization(this);
      if (originalDrawForeground) {
        return originalDrawForeground.apply(this, arguments);
      }
    };
  },
  
  // 扩展生命周期钩子：当任何节点被创建并添加到图表中时调用
  nodeCreated(node) {
    if (TARGET_NODES.has(node.comfyClass)) {
      const triggerUpdate = (n) => {
        applyLocalization(n);
        if (app.canvas) {
          app.canvas.setDirty(true, true);
          if (typeof app.canvas.draw === "function") {
            app.canvas.draw(true, true);
          }
        }
      };
      triggerUpdate(node);
      setTimeout(() => triggerUpdate(node), 50);
      setTimeout(() => triggerUpdate(node), 150);
      setTimeout(() => triggerUpdate(node), 350);
      setTimeout(() => triggerUpdate(node), 800);
    }
  },

  // 扩展生命周期钩子：当整个工作流数据被反序列化并载入配置完成后调用（例如重新加载/刷新页面）
  afterConfigure() {
    if (app.graph && app.graph._nodes) {
      for (const node of app.graph._nodes) {
        if (node && TARGET_NODES.has(node.comfyClass)) {
          const triggerUpdate = (n) => {
            applyLocalization(n);
            if (app.canvas) {
              app.canvas.setDirty(true, true);
              if (typeof app.canvas.draw === "function") {
                app.canvas.draw(true, true);
              }
            }
          };
          triggerUpdate(node);
          setTimeout(() => triggerUpdate(node), 100);
          setTimeout(() => triggerUpdate(node), 300);
          setTimeout(() => triggerUpdate(node), 600);
          setTimeout(() => triggerUpdate(node), 1200);
          setTimeout(() => triggerUpdate(node), 2000);
        }
      }
    }
  }
});
