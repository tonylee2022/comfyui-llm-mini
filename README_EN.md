[English](README_EN.md) | [中文](README.md)

# ComfyUI LLM Mini

Lightweight ComfyUI nodes for LLM provider access, personas, image generation, and xAI video.

## Installation

1. Navigate to ComfyUI's `custom_nodes` directory:
   ```bash
   cd ComfyUI/custom_nodes
   ```
2. Clone this repository:
   ```bash
   git clone https://github.com/tonylee2022/comfyui-llm-mini.git
   ```
3. Install the dependencies:
   ```bash
   cd comfyui-llm-mini
   pip install -r requirements.txt
   ```
   *Note: If you are using the ComfyUI Portable version, please install using the embedded Python, e.g.: `..\..\..\python_embeded\python.exe -m pip install -r requirements.txt`.*

## Features

- API Chat uses model lists saved by Provider Manager and does not add a refresh button to the chat node.
- API Chat only lists chat providers with a valid API key or OAuth credential.
- API key, environment variable, Codex OAuth, and xAI OAuth credential paths.
- OpenAI-compatible, Claude, and Gemini chat providers.
- Persona `.txt` files as system prompt inputs.
- Separate OpenAI and Codex image nodes with provider-scoped backend implementations.
- xAI Imagine and xAI Video nodes.
- API Chat strips Base64 images from output history by default to keep workflow files small, with an opt-in switch to retain them.

## Configuration

Copy `config.example.ini` to `config.ini`, then fill provider API keys or run:

```bash
python oauth_login.py
```

Codex and xAI both support two OAuth login flows:

```bash
python oauth_login.py  # Default interactive mode, prompts for provider and flow
python oauth_login.py --provider codex --flow device
python oauth_login.py --provider codex --flow browser
python oauth_login.py --provider xai --flow device
python oauth_login.py --provider xai --flow browser
```

Running without arguments prompts for both provider and login flow. `browser` is the browser login / local callback PKCE flow; `redirect` remains available as an alias.

The `Credential Source` field selects the credential path. API key providers read `config.ini` first, then environment variables. OAuth providers use their saved token.

### Custom Providers

Keep `openai` for the official OpenAI endpoint. Put local proxies or third-party OpenAI-compatible services in their own named provider sections:

```ini
[provider.local_proxy]
display_name = Local Proxy
api_key = sk-...
base_url = http://192.168.5.1:3000/api/
```

Provider IDs must start with a letter or number, may contain only letters, numbers, dots, underscores, and hyphens, and are limited to 64 characters. Use `display_name` for a friendlier label.

Restart ComfyUI and the chat node provider menu will show `local_proxy` separately from `openai`.
For non-chat providers, set `supports_chat = false` so they do not appear in the API Chat node.

## Node Parameters

- In the OpenAI Image and Codex Image nodes, `model_name` means the GPT Image model. The Codex backend uses `gpt-5.5` internally as the Responses API main model and passes the image model, size, quality, and background to the `image_generation` tool.
- `seed` inputs marked as cache controls on OpenAI/Codex and xAI nodes trigger re-execution but are not sent to those APIs.

### Google (Gemini) Authorization

Google nodes use your Gemini API key. Put your free API key in the `[provider.google]` section of `config.ini`. Access all models (text/image/video).

## Attribution

This project includes code and behavior adapted from `comfyui_LLM_party`:
https://github.com/heshengtao/comfyui_LLM_party

Original copyright:
Copyright (C) 2024 heshengtao <hst97@qq.com>

`comfyui_LLM_party` is licensed under the GNU Affero General Public License v3.0. This project is distributed under the same license.
