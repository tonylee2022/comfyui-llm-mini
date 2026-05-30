[English](README_EN.md) | [中文](README.md)

# ComfyUI LLM Mini

Lightweight ComfyUI nodes for LLM provider access, personas, image generation, and xAI video.

## Features

- Provider-first API chat node with model list refresh in the node UI.
- Provider dropdown menu only displays the `[provider.xxx]` sections in `config.ini`.
- API key, environment variable, Codex OAuth, and xAI OAuth credential paths.
- OpenAI-compatible, Claude, and Gemini chat providers.
- Persona `.txt` files as system prompt inputs.
- Shared OpenAI/Codex image panel with separate backend implementations.
- xAI Imagine and xAI Video nodes.

## Attribution

This project includes code and behavior adapted from `comfyui_LLM_party`:
https://github.com/heshengtao/comfyui_LLM_party

Original copyright:
Copyright (C) 2024 heshengtao <hst97@qq.com>

`comfyui_LLM_party` is licensed under the GNU Affero General Public License v3.0. This project is distributed under the same license.

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
api_key = sk-...
base_url = http://192.168.5.1:3000/api/
```

Restart ComfyUI and the chat node provider menu will show `local_proxy` (or your custom name) separately from `openai`.

### Google (Gemini) Authorization

Google nodes use your Gemini API key. Put your free API key in the `[provider.google]` section of `config.ini`. Access all models (text/image/video).
