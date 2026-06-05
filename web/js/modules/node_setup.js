import { refreshProviderWidgets, findWidget, updateCombo } from "./utils.js";
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
  }
  
  if (nodeName === "LLMMiniLoadPersona") {
    node.size = [250, node.computeSize()[1]];
  }

  if (/Video/.test(nodeName)) {
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
