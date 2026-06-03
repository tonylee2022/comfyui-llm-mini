import { isChineseLocale } from "./utils.js";

export function applyLocalization(node) {
  const isZh = isChineseLocale();
  const translations = {
    "provider": { zh: "提供商", en: "Provider" },
    "model_name": { zh: "模型", en: "Model" },
    "system_prompt": { zh: "系统提示词", en: "System Prompt" },
    "user_prompt": { zh: "用户提示词", en: "User Prompt" },
    "temperature": { zh: "温度", en: "Temperature" },
    "max_tokens": { zh: "最大 Token", en: "Max Tokens" },
    "is_locked": { zh: "锁定缓存", en: "Lock Cache" },
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

  if (node.inputs) {
    node.inputs.forEach((input) => {
      const tVal = translations[input.name];
      if (tVal) {
        input.label = isZh ? tVal.zh : tVal.en;
      }
    });
  }
  if (node.outputs) {
    node.outputs.forEach((output) => {
      const tVal = translations[output.name];
      if (tVal) {
        output.label = isZh ? tVal.zh : tVal.en;
      }
    });
  }
  if (node.widgets) {
    node.widgets.forEach((widget) => {
      const tVal = translations[widget.name];
      if (tVal) {
        widget.label = isZh ? tVal.zh : tVal.en;
      }
    });
  }
}
