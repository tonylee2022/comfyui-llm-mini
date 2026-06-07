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
4. Copy the example configuration file to `config.ini`:
   ```bash
   cp config.example.ini config.ini
   ```
   *(For Windows systems, use `copy config.example.ini config.ini`)*

## Features

- API Chat uses model lists saved by Provider Manager and can also refresh/configure the current provider model list directly from the chat node.
- API Chat only lists chat providers with a valid API key or OAuth credential.
- API key, environment variable, Codex OAuth, and xAI OAuth credential paths.
- OpenAI-compatible, Claude, Gemini, xAI, and Codex chat providers.
- Persona `.txt` files as system prompt inputs.
- Separate OpenAI and Codex image nodes with provider-scoped backend implementations.
- xAI Imagine and xAI Video nodes.
- Google Veo 2, Veo 3, and Veo 3 First-Last-Frame video generation nodes.
- API Chat strips Base64 images from output history by default to keep workflow files small, with an opt-in `retain_images_in_history` switch to retain them.

## Configuration

The recommended entry point is the `Provider Manager` node inside the ComfyUI canvas. Use it for API keys, OAuth authorization, model list management, and custom provider setup.

### Provider Manager

1. Add a `Provider Manager` node.
2. Select an existing provider, or select `custom_provider` and enter a new Provider ID.
3. Fill `Base URL`, `API Key`, and enable the chat/image/video capabilities you need.
4. Click `Save Config`. API Chat only lists chat-capable providers with valid credentials.
5. For Codex or xAI, use `Browser OAuth` or `Device Code OAuth` directly in the node. Device codes are shown in a popup where they can be copied into the authorization page.
6. Click `Refresh & Configure Model List` to fetch available models, then select the models you want to keep. You can apply the selection temporarily to the current canvas or save it as the provider's static default list.
7. Use `Custom Model ID` to add model names that are usable but not returned by the provider model-list endpoint.

API Chat also includes the same model-list shortcut for the currently selected chat provider. Use Provider Manager for full provider creation, deletion, OAuth, and capability configuration.

### File And CLI Fallbacks

If you prefer manual configuration, copy `config.example.ini` to `config.ini` and fill provider API keys there.

Codex and xAI OAuth also keep a command-line fallback:

```bash
python oauth_login.py  # Default interactive mode, prompts for provider and flow
python oauth_login.py --provider codex --flow device
python oauth_login.py --provider codex --flow browser
python oauth_login.py --provider xai --flow device
python oauth_login.py --provider xai --flow browser
```

Running without arguments prompts for both provider and login flow. `device` is device-code authorization. `browser` is the browser login / local callback PKCE flow; `redirect` remains available as an alias. For normal use, prefer Provider Manager instead of running these commands manually.

API key providers read `config.ini` first, then environment variables. OAuth providers use their saved token.

### Custom Providers

Create custom providers from `Provider Manager`:

1. Select `custom_provider` in the `provider` menu.
2. Enter a new Provider ID in `new_provider_id`.
3. Fill the service `Base URL` and `API Key`.
4. Select `Chat Backend`. Use `openai_compatible` for OpenAI-compatible APIs and `anthropic` for Anthropic-compatible APIs.
5. Enable or disable `Chat`, `Image`, and `Video` according to the service capability.
6. Click `Save Config`. The Provider ID will appear in the provider list; if `Chat` is enabled and credentials are valid, it will also appear in API Chat.

Provider IDs must start with a letter or number, may contain only letters, numbers, dots, underscores, and hyphens, and are limited to 64 characters. Keep `openai` for the official OpenAI endpoint; do not overwrite it with third-party OpenAI-compatible services.

## Node Parameters

- In the OpenAI Image and Codex Image nodes, `model_name` means the GPT Image model. The Codex backend uses `gpt-5.5` internally as the Responses API main model and passes the image model, size, quality, and background to the `image_generation` tool.
- `seed` inputs marked as cache controls on OpenAI/Codex and xAI nodes trigger re-execution but are not sent to those APIs.

### Google (Gemini & Veo) Authorization & Video Generation

- **Authorization**: Google nodes use your Gemini API key. Put your free API key in the `[provider.google]` section of `config.ini` to access all text/image generation models.
- **Google Veo Video Generation**: Supports **Google Veo 2 Video Generation**, **Google Veo 3 Video Generation**, and **Google Veo 3 First-Last-Frame** (generates transitional videos by interpolating start and end reference frames). Note: Due to Gemini API limits, `generate_audio` and `enhance_prompt` parameters are not configurable on Veo 3 nodes (defaults are automatically used internally).

## Attribution

This project includes code and behavior adapted from `comfyui_LLM_party`:
https://github.com/heshengtao/comfyui_LLM_party

Original copyright:
Copyright (C) 2024 heshengtao <hst97@qq.com>

`comfyui_LLM_party` is licensed under the GNU Affero General Public License v3.0. This project is distributed under the same license.
