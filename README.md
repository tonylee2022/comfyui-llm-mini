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

## 功能

- API Chat 使用提供商管理器中保存的模型列表，不在聊天节点内提供刷新按钮。
- API Chat 的提供商下拉框只显示已配置有效 API Key 或 OAuth 凭据的聊天提供商。
- 支持 API Key、环境变量、Codex OAuth、xAI OAuth 凭据路径。
- 支持 OpenAI-compatible、Claude、Gemini 聊天接口。
- 支持 `persona/*.txt` 人格面具作为系统提示词。
- OpenAI 与 Codex 图像使用独立节点，后端按提供商拆分。
- 支持 xAI Imagine 与 xAI Video。
- API Chat 默认从输出历史中移除 Base64 图像，避免工作流文件过大；可通过节点开关保留。

## 配置

复制 `config.example.ini` 为 `config.ini`，填写对应提供商的 API Key，或运行：

```bash
python oauth_login.py
```

Codex 和 xAI 都支持两种 OAuth 登录方式：

```bash
python oauth_login.py  默认交互模式，交互会提示你选择provider和flow
python oauth_login.py --provider codex --flow device
python oauth_login.py --provider codex --flow browser
python oauth_login.py --provider xai --flow device
python oauth_login.py --provider xai --flow browser
```

不带参数运行时会交互选择提供商和登录方式。`browser` 是浏览器登录/本地回调 PKCE 模式；`redirect` 作为同义参数保留。

`凭据来源` 用来选择凭据路径。API key 路径优先读取 `config.ini`，再读取环境变量；OAuth 路径使用保存的 token。

### 自定义提供商

不要把本地代理或第三方 OpenAI-compatible 服务直接塞进 `openai`。`openai` 保留给 OpenAI 官方地址。自定义服务请在 `config.ini` 中新增独立段名：

```ini
[provider.local_proxy]
display_name = Local Proxy
api_key = sk-...
base_url = http://192.168.5.1:3000/api/
```

Provider ID 必须以字母或数字开头，只能包含字母、数字、点、下划线和连字符，最长 64 个字符。`display_name` 可使用更友好的显示名称。

重启 ComfyUI 后，聊天节点的 provider 下拉框会出现 `local_proxy`，并与 `openai` 独立。
如需配置非聊天提供商，可设置 `supports_chat = false`，这样它不会出现在 API Chat 节点中。

## 节点参数说明

- OpenAI Image 与 Codex Image 的 `model_name` 都表示 GPT Image 图像模型；Codex 后端固定使用 `gpt-5.5` 作为 Responses API 主模型，并把图像模型、尺寸、质量和背景传给 `image_generation` 工具。
- OpenAI/Codex 与 xAI 节点中标注为缓存控制的 `seed` 只用于触发重新执行，不会发送给对应 API。

### Google (Gemini) 授权配置

Google 节点使用 API Key 凭据。在 `config.ini` 中填入免费申请的 API 密匙。支持全部生图、视频和聊天模型。

## 署名

本项目包含从 `comfyui_LLM_party` 迁移和改造的代码与行为：
https://github.com/heshengtao/comfyui_LLM_party

原始版权：
Copyright (C) 2024 heshengtao <hst97@qq.com>

`comfyui_LLM_party` 使用 GNU Affero General Public License v3.0。本项目使用同一许可证发布。
