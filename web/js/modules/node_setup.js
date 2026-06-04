import { refreshProviderWidgets, addRefreshButton, findWidget, updateCombo } from "./utils.js";
import { setupPersonaManager } from "./persona.js";
import { setupProviderManager } from "./provider.js";
import { applyLocalization } from "./localization.js";

export const TARGET_NODES = new Set([
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

export function setupNodeByType(node, nodeName) {
  setTimeout(() => applyLocalization(node), 20);

  if (nodeName === "LLMMiniApiChat") {
    node.size = [300, node.computeSize()[1]];
    setTimeout(() => refreshProviderWidgets(node), 50);
  }
  
  if (nodeName === "LLMMiniLoadPersona") {
    node.size = [250, node.computeSize()[1]];
  }

  if (["LLMMiniXAIVideo", "LLMMiniXAIVideoReference", "LLMMiniXAIVideoEdit", "LLMMiniXAIVideoExtend"].includes(nodeName)) {
    node.size = [300, node.computeSize()[1]];
  }

  const imageNodes = [
    "LLMMiniOpenAICodexImage",
    "LLMMiniXAIImagine",
    "LLMMiniGoogleImagen",
    "LLMMiniGoogleGeminiNanoBanana",
    "LLMMiniGoogleGeminiNanoBananaPro",
    "LLMMiniGoogleGeminiNanoBanana2"
  ];
  if (imageNodes.includes(nodeName)) {
    node.size = [300, node.computeSize()[1]];
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
