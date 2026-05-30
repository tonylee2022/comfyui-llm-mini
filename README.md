[中文](README.md) | [English](README_EN.md)

# ComfyUI LLM Mini

轻量 ComfyUI 自定义节点包，支持模型提供商接入、人格面具、图像生成和 xAI 视频。

## 功能

- 先选择提供商，再刷新模型列表，在节点面板中选择具体模型。
- 提供商 下拉框只显示 `config.ini` 中的 `[provider.xxx]`。
- 支持 API Key、环境变量、Codex OAuth、xAI OAuth 凭据路径。
- 支持 OpenAI-compatible、Claude、Gemini 聊天接口。
- 支持 `persona/*.txt` 人格面具作为系统提示词。
- OpenAI/Codex 图像共用面板，但后端实现路径分开。
- 支持 xAI Imagine 与 xAI Video。

## 署名

本项目包含从 `comfyui_LLM_party` 迁移和改造的代码与行为：
https://github.com/heshengtao/comfyui_LLM_party

原始版权：
Copyright (C) 2024 heshengtao <hst97@qq.com>

`comfyui_LLM_party` 使用 GNU Affero General Public License v3.0。本项目使用同一许可证发布。

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
api_key = sk-...
base_url = http://192.168.5.1:3000/api/
```

重启 ComfyUI 后，聊天节点的 provider 下拉框会出现 `local_proxy`（可自定义名称），并与 `openai` 独立。

### Google (Gemini) 授权配置

Google 节点使用 API Key 凭据。在 `config.ini` 中填入免费申请的 API 密匙。支持全部生图、视频和聊天模型。
