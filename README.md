[中文](README.md) | [English](README_EN.md)

# ComfyUI LLM Mini

轻量 ComfyUI 自定义节点包，支持模型提供商接入、人格面具、图像生成和 xAI 视频。

## 安装

1. 进入 ComfyUI 的 `custom_nodes` 目录：
   ```bash
   cd ComfyUI/custom_nodes
   ```
2. 克隆本仓库：
   ```bash
   git clone https://github.com/tonylee2022/comfyui-llm-mini.git
   ```
3. 安装依赖：
   ```bash
   cd comfyui-llm-mini
   pip install -r requirements.txt
   ```
   *注意：如果使用的是 ComfyUI 独立便携版本（Portable），请使用其内部 Python 解释器安装，例如运行：`..\..\..\python_embeded\python.exe -m pip install -r requirements.txt`。*
4. 复制示例配置文件为 `config.ini`：
   ```bash
   cp config.example.ini config.ini
   ```
   *(Windows 系统请使用 `copy config.example.ini config.ini`)*

## 功能

- API Chat 使用提供商管理器中保存的模型列表，也可在聊天节点内快速刷新并配置当前提供商的模型列表。
- API Chat 的提供商下拉框只显示已配置有效 API Key 或 OAuth 凭据的聊天提供商。
- 支持 API Key、环境变量、Codex OAuth、xAI OAuth 凭据路径。
- 支持 OpenAI-compatible、Claude、Gemini、xAI 和 Codex 聊天接口。
- 支持项目托管的 llama.cpp 本地 GGUF 文本/视觉模型，以及按次、常驻或空闲卸载策略。
- 支持 `persona/*.txt` 人格面具作为系统提示词。
- 提供独立的“翻译”节点，可选择提供商、模型、输入语言、输出语言、语气和语气程度。
- OpenAI 与 Codex 图像使用独立节点，后端按提供商拆分。
- 支持 xAI Imagine 与 xAI Video。
- 支持 Google Veo 2、Veo 3 以及 Veo 3 首尾帧视频生成。
- API Chat 默认从输出历史中移除 Base64 图像，避免工作流文件过大；可通过节点上的 `retain_images_in_history` 参数开关选择保留。

## 配置

推荐直接在 ComfyUI 画布中添加 `Provider Manager`（提供商配置管理器）节点完成配置。它是日常配置入口，适合添加 API Key、OAuth 授权、刷新模型列表和维护自定义提供商。

### 提供商配置管理器

1. 添加 `Provider Manager` 节点。
2. 在 `provider` 中选择已有提供商，或选择 `custom_provider` 并填写新的 Provider ID。
3. 填写 `Base URL`、`API Key`，并按需要设置聊天、图像、视频能力。
4. 点击 `Save Config` 保存配置。API Chat 的 provider 下拉框只会显示已配置有效凭据且支持聊天的提供商。
5. 对 Codex 或 xAI，可直接点击 `网页授权` 或 `设备码授权` 完成 OAuth。设备码会在弹窗中显示，可复制后粘贴到授权页面。
6. 点击 `刷新并配置模型列表` 拉取模型列表，在弹窗中勾选需要保留的模型。可选择“仅临时应用”到当前画布，或“保存为静态列表”写入配置。
7. 可通过 `自定义模型 ID` 添加接口未返回但可用的模型名，并保存到该提供商的默认模型列表。

API Chat 节点也提供同样的模型列表快捷配置入口，用于刷新并配置当前聊天提供商的模型列表；完整的提供商新增、删除、OAuth 和能力声明仍建议在 Provider Manager 中完成。

### llama.cpp 本地模型

llama.cpp 运行时私有安装到本插件的 `runtime/llama_cpp`（已被 Git 忽略），GGUF 仍共享放在 `ComfyUI/models/LLM`。通过 ComfyUI-Manager 首次安装节点时，根目录 `install.py` 会自动检测平台并尝试安装固定、已校验版本；失败不会阻止节点安装，可稍后在 Provider Manager 中重试。Provider Manager 只有在用户确认点击“安装 / 升级 llama.cpp”后才会下载或编译，不会随 ComfyUI 启动静默执行。发现优先级为“配置的绝对路径 → 节点私有运行时 → `PATH`”。

```bash
python3 llama_cpp_setup.py check
python3 llama_cpp_setup.py print-install
python3 llama_cpp_setup.py print-install --backend auto
python3 llama_cpp_setup.py print-install --backend cuda --shell bash
python3 llama_cpp_setup.py install-runtime --backend auto --dry-run
python3 llama_cpp_setup.py install-runtime --backend auto
```

- WSL/Linux：使用 Linux 原生运行时；检测到 NVIDIA 驱动、CUDA Toolkit 和 `nvcc` 时，从固定版本源码构建 CUDA，否则选择官方 Vulkan（系统有 `vulkaninfo`）或 CPU 包。
- Windows Portable：在插件目录执行 `..\..\..\python_embeded\python.exe llama_cpp_setup.py install-runtime --backend auto`。
- Windows Desktop：用该桌面版实际启动 ComfyUI 的 Python 执行同一命令。NVIDIA 环境使用经过 SHA256 校验的官方 Windows CUDA 预编译包。
- `--offline` 只使用已校验的下载缓存；`--force` 原子替换已有私有运行时。安装器不下载模型。
- 节点更新不会自动升级运行时。Provider Manager 可显式安装、升级或修复：有活动请求时拒绝操作，安装期间阻止新请求，校验通过后才原子替换旧运行时。

将 GGUF 放入默认的 `ComfyUI/models/LLM`，或在 Provider Manager 选择 `llama_cpp` 后设置绝对模型目录。视觉模型应放在独立子目录中，主 GGUF 与文件名以 `mmproj` 开头的投影 GGUF 放在一起。Provider Manager 提供“检查 llama.cpp”“复制安装帮助”“安装 / 升级 llama.cpp”、启动/停止、刷新、加载和卸载；router 仅监听 `127.0.0.1`，使用动态端口和临时 API Key。

API Chat 和翻译节点选择 `llama_cpp` 后会显示本地卸载策略：`after_run` 在活动请求归零后卸载，`keep_warm` 保持驻留，`idle` 在配置的空闲时间后卸载。节点默认使用 `after_run`；旧工作流中的 `inherit` 会迁移为该策略。默认显存策略 `auto` 仅在预计显存不足时尝试释放 ComfyUI 模型；设为 `keep` 可禁止主动释放。

### 文件和命令行备用配置

如果需要手工维护配置，可复制 `config.example.ini` 为 `config.ini` 并填写对应提供商的 API Key。

Codex 和 xAI 的 OAuth 也保留命令行备用入口：

```bash
python oauth_login.py  默认交互模式，交互会提示你选择provider和flow
python oauth_login.py --provider codex --flow device
python oauth_login.py --provider codex --flow browser
python oauth_login.py --provider xai --flow device
python oauth_login.py --provider xai --flow browser
```

不带参数运行时会交互选择提供商和登录方式。`device` 是设备码授权；`browser` 是浏览器登录/本地回调 PKCE 模式；`redirect` 作为同义参数保留。普通使用优先使用 Provider Manager，不需要手动运行这些命令。

API Key 路径优先读取 `config.ini`，再读取环境变量；OAuth 路径使用保存的 token。

### 自定义提供商

自定义提供商建议通过 `Provider Manager` 创建：

1. 在 `provider` 下拉框中选择 `custom_provider`。
2. 在 `new_provider_id` 中填写新的 Provider ID。
3. 填写该服务的 `Base URL` 和 `API Key`。
4. 选择 `Chat Backend`。OpenAI-compatible 接口使用 `openai_compatible`，Anthropic-compatible 接口使用 `anthropic`。
5. 按服务能力打开或关闭 `Chat`、`Image`、`Video`。
6. 点击 `Save Config` 保存。保存后该 Provider ID 会出现在提供商列表中；如果启用了 `Chat` 且凭据有效，也会出现在 API Chat 节点中。

Provider ID 必须以字母或数字开头，只能包含字母、数字、点、下划线和连字符，最长 64 个字符。不要把第三方 OpenAI-compatible 服务直接覆盖到 `openai`，`openai` 保留给 OpenAI 官方地址。

## 节点参数说明

- `翻译`节点直接接收和输出文本，使用已配置的聊天提供商完成翻译。切换提供商时，模型列表会联动切换为该提供商在插件配置中的默认模型，不会请求远程模型列表。输入语言可选择自动检测，节点名称和语言下拉选项只跟随 ComfyUI 前端语言设置。
- OpenAI Image 与 Codex Image 的 `model_name` 都表示 GPT Image 图像模型；Codex 后端固定使用 `gpt-5.5` 作为 Responses API 主模型，并把图像模型、尺寸、质量和背景传给 `image_generation` 工具。
- xAI 图像节点默认使用 `grok-imagine-image-2.0`，并保留 `grok-imagine-image-quality` 与 `grok-imagine-image`。2.0 图像生成支持 `medium`（默认）和 `low` 质量；xAI 当前编辑文档未定义 `quality` 参数，因此编辑节点暂不发送该值。
- OpenAI/Codex 与 xAI 节点中标注为缓存控制的 `seed` 只用于触发重新执行，不会发送给对应 API。

### Google (Gemini & Veo) 授权与视频生成

- **授权配置**：Google 节点使用 API Key 凭据。在 `config.ini` 中填入免费申请的 API 密钥。支持全部生图和聊天模型。
- **Google Veo 视频生成**：支持 **Google Veo 2 视频生成**、**Google Veo 3 视频生成** 和 **Google Veo 3 首尾帧视频生成**（通过插值开始和结束参考图生成中间过渡视频）。注意：由于 Gemini API 的接口限制，不支持 `generate_audio` 与 `enhance_prompt` 音画控制参数（后台默认自动启用推荐选项）。

## 署名

本项目包含从 `comfyui_LLM_party` 迁移和改造的代码与行为：
https://github.com/heshengtao/comfyui_LLM_party

原始版权：
Copyright (C) 2024 heshengtao <hst97@qq.com>

`comfyui_LLM_party` 使用 GNU Affero General Public License v3.0。本项目使用同一许可证发布。
