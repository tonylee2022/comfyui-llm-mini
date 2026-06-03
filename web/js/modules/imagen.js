import { findWidget, updateCombo } from "./utils.js";

export function setupGoogleImagenNode(node) {
  const modelWidget = findWidget(node, "model_name");
  if (!modelWidget) {
    return;
  }

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
    if (!isFast && isImagen && currentVal === "4K" && resWidget) {
      resWidget.value = "1K";
    }
  };

  updateResolutionOptions(modelWidget.value);
  const originalCallback = modelWidget.callback;
  modelWidget.callback = function (value) {
    if (originalCallback) {
      originalCallback.apply(this, arguments);
    }
    updateResolutionOptions(value);
  };
}
