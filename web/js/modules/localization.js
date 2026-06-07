import { isChineseLocale } from "./utils.js";

const localizationTimers = new WeakMap();
const translations = {
  "provider": { zh: "提供商", en: "Provider" },
  "model_name": { zh: "模型", en: "Model" },
  "system_prompt": { zh: "系统提示词", en: "System Prompt" },
  "user_prompt": { zh: "用户提示词", en: "User Prompt" },
  "temperature": { zh: "温度", en: "Temperature" },
  "max_tokens": { zh: "最大 Token", en: "Max Tokens" },
  "is_locked": { zh: "锁定缓存", en: "Lock Cache" },
  "retain_images_in_history": { zh: "历史保留图像", en: "Retain Images in History" },
  "stream": { zh: "流式输出", en: "Stream" },
  "system_prompt_input": { zh: "加载人格面具", en: "Load Persona" },
  "image": { zh: "图像", en: "Image" },
  "images": { zh: "参考图像", en: "Reference Images" },
  "image_url": { zh: "图像 URL", en: "Image URL" },
  "assistant_response": { zh: "助手回复", en: "Assistant Response" },
  "history_json": { zh: "历史记录 JSON", en: "History JSON" },
  "persona_name": { zh: "人格面具", en: "Persona" },
  "new_name": { zh: "新名称", en: "New Name" },
  "content": { zh: "面具内容", en: "Content" },
  "text": { zh: "文本", en: "Text" },
  "prompt": { zh: "提示词", en: "Prompt" },
  "execution_backend": { zh: "执行后端", en: "Execution Backend" },
  "size": { zh: "尺寸", en: "Size" },
  "quality": { zh: "质量", en: "Quality" },
  "background": { zh: "背景", en: "Background" },
  "n": { zh: "数量", en: "Quantity" },
  "seed": { zh: "随机种", en: "Seed" },
  "mask": { zh: "遮罩", en: "Mask" },
  "aspect_ratio": { zh: "宽高比", en: "Aspect Ratio" },
  "resolution": { zh: "分辨率", en: "Resolution" },
  "duration": { zh: "时长", en: "Duration" },
  "video": { zh: "视频", en: "Video" },
  "model": { zh: "模型", en: "Model" },
  "response_modalities": { zh: "响应模态", en: "Response Modalities" },
  "thinking_level": { zh: "思考级别", en: "Thinking Level" },
  "files": { zh: "参考文件", en: "Reference Files" }
};

export function translatedName(name) {
  const nameKey = name ? String(name).toLowerCase() : "";
  let translation = translations[nameKey];
  let suffix = "";
  if (!translation) {
    const match = nameKey.match(/^(.+)_([0-9]+)$/);
    if (match) {
      translation = translations[match[1]];
      suffix = ` ${match[2]}`;
    }
  }
  if (!translation) return null;
  return `${isChineseLocale() ? translation.zh : translation.en}${suffix}`;
}

function applyItemLocalization(item, includeLocalizedName = false) {
  const expected = translatedName(item?.name);
  if (!expected) return false;

  let changed = false;
  if (item.label !== expected) {
    item.label = expected;
    changed = true;
  }
  if (includeLocalizedName && item.localized_name !== expected) {
    item.localized_name = expected;
    changed = true;
  }
  return changed;
}

function localizeInputSpec(spec, expected) {
  if (Array.isArray(spec)) {
    if (!spec[1] || typeof spec[1] !== "object" || Array.isArray(spec[1])) {
      spec[1] = {};
    }
    spec[1].display_name = expected;
  } else if (spec && typeof spec === "object") {
    spec.display_name = expected;
  }
}

export function localizeVueNodeDef(nodeDef) {
  const inputGroups = nodeDef?.input || nodeDef?.inputs || {};
  for (const group of ["required", "optional"]) {
    const inputs = inputGroups[group] || {};
    for (const [name, spec] of Object.entries(inputs)) {
      const expected = translatedName(name);
      if (expected) localizeInputSpec(spec, expected);
    }
  }

  if (Array.isArray(nodeDef?.output_name)) {
    nodeDef.output_name = nodeDef.output_name.map((name) => translatedName(name) || name);
  }
}

const pendingNodes = new Set();
let localizationScheduled = false;

export function scheduleLocalization(node, delay = 20) {
  if (!node) return;
  pendingNodes.add(node);

  if (localizationScheduled) return;
  localizationScheduled = true;

  setTimeout(() => {
    localizationScheduled = false;
    const nodesToProcess = Array.from(pendingNodes);
    pendingNodes.clear();

    const apply = () => {
      let anyChangedGlobal = false;
      nodesToProcess.forEach((n) => {
        if (n) {
          const changed = applyLocalizationDirect(n);
          if (changed) anyChangedGlobal = true;
        }
      });

      if (anyChangedGlobal) {
        const firstWithGraph = nodesToProcess.find((n) => n && n.graph);
        if (firstWithGraph && firstWithGraph.graph && typeof firstWithGraph.graph.setDirtyCanvas === "function") {
          firstWithGraph.graph.setDirtyCanvas(true, true);
        } else {
          const firstWithCanvas = nodesToProcess.find((n) => n && typeof n.setDirtyCanvas === "function");
          if (firstWithCanvas) {
            firstWithCanvas.setDirtyCanvas(true, true);
          }
        }
      }
    };

    if (typeof requestAnimationFrame === "function") {
      requestAnimationFrame(apply);
    } else {
      apply();
    }
  }, delay);
}

export function applyLocalizationDirect(node) {
  let anyChanged = false;

  if (node.inputs) {
    node.inputs.forEach((input) => {
      anyChanged = applyItemLocalization(input, true) || anyChanged;
    });
  }

  if (node.outputs) {
    node.outputs.forEach((output) => {
      anyChanged = applyItemLocalization(output, true) || anyChanged;
    });
  }

  if (node.widgets) {
    node.widgets.forEach((widget) => {
      anyChanged = applyItemLocalization(widget) || anyChanged;
    });
  }

  return anyChanged;
}

export function applyLocalization(node) {
  const anyChanged = applyLocalizationDirect(node);
  if (anyChanged) {
    if (typeof node.setDirtyCanvas === "function") {
      node.setDirtyCanvas(true, true);
    }
    if (node.graph && typeof node.graph.setDirtyCanvas === "function") {
      node.graph.setDirtyCanvas(true, true);
    }
  }
}
