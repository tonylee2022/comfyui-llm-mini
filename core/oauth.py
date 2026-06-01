from __future__ import annotations

import base64
import configparser
import hashlib
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from .config import load_ini, save_ini

DEFAULT_CREDENTIALS = {
    "codex": {
        "client_id": "app_EMoamEEZ73f0CkXaXp7hrann",
        "client_secret": "",
        "auth_url": "https://auth.openai.com/oauth/authorize",
        "token_url": "https://auth.openai.com/oauth/token",
        "device_url": "https://auth.openai.com/api/accounts/deviceauth/usercode",
        "scope": "openid profile email offline_access",
    },
    "xai": {
        "client_id": "b1a00492-073a-47ea-816f-4c329264a828",
        "client_secret": "",
        "auth_url": "https://auth.x.ai/oauth2/authorize",
        "token_url": "https://auth.x.ai/oauth2/token",
        "device_url": "https://auth.x.ai/oauth2/device/code",
        "scope": "openid profile email offline_access grok-cli:access api:access",
    },
}


class CallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        return

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        
        auth_code = None
        auth_state = None
        if "code" in params:
            auth_code = params["code"][0]
            auth_state = params.get("state", [""])[0]
            body_str = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LLM Mini Authorization Success</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #121214;
            color: #e4e4e7;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .card {
            background-color: #1a1a1e;
            border: 1px solid #2e2e33;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.6);
            max-width: 420px;
        }
        .icon {
            font-size: 48px;
            margin-bottom: 20px;
        }
        h1 {
            color: #10b981;
            margin-top: 0;
            font-size: 24px;
            font-weight: 600;
        }
        p {
            color: #a1a1aa;
            font-size: 16px;
            line-height: 1.6;
            margin: 10px 0;
        }
        .close-hint {
            margin-top: 25px;
            font-size: 14px;
            color: #71717a;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">🎉</div>
        <h1>Authorization Successful</h1>
        <p>Your LLM Mini provider has been successfully authorized and configured.</p>
        <p>You can now return to ComfyUI.</p>
        <p class="close-hint">This window will close automatically in 3 seconds...</p>
    </div>
    <script>
        setTimeout(function() {
            window.close();
        }, 3000);
    </script>
</body>
</html>"""
        else:
            body_str = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>LLM Mini Authorization Failed</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #121214;
            color: #e4e4e7;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .card {
            background-color: #1a1a1e;
            border: 1px solid #2e2e33;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.6);
            max-width: 420px;
        }
        .icon {
            font-size: 48px;
            margin-bottom: 20px;
        }
        h1 {
            color: #ef4444;
            margin-top: 0;
            font-size: 24px;
            font-weight: 600;
        }
        p {
            color: #a1a1aa;
            font-size: 16px;
            line-height: 1.6;
            margin: 10px 0;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">❌</div>
        <h1>Authorization Failed</h1>
        <p>No authorization code was received.</p>
        <p>Please close this window and try again.</p>
    </div>
</body>
</html>"""
        body = body_str.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        
        if auth_code:
            self.server.auth_code = auth_code
            self.server.auth_state = auth_state


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").replace("=", "")
    return verifier, challenge


def write_tokens(provider: str, client_id: str, client_secret: str, token_data: dict, token_url: str) -> None:
    config = load_ini()
    section = f"{provider}_oauth"
    if not config.has_section(section):
        config.add_section(section)
    config[section]["client_id"] = client_id
    config[section]["client_secret"] = client_secret
    config[section]["access_token"] = token_data.get("access_token") or token_data.get("accessToken") or ""
    config[section]["refresh_token"] = token_data.get("refresh_token") or token_data.get("refreshToken") or ""
    expires = token_data.get("expires_in") or token_data.get("expiresIn") or 3600
    try:
        expires = int(expires)
    except ValueError:
        expires = 3600
    config[section]["token_expires_at"] = str(int(time.time() + expires))
    config[section]["token_url"] = token_url
    save_ini(config)


def refresh_oauth_token(provider: str) -> str | None:
    config = load_ini()
    section = f"{provider}_oauth"
    if not config.has_section(section):
        return None
    client_id = config.get(section, "client_id", fallback="")
    client_secret = config.get(section, "client_secret", fallback="")
    refresh_token = config.get(section, "refresh_token", fallback="")
    token_url = config.get(section, "token_url", fallback="")
    if not client_id or not refresh_token or not token_url:
        return None
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id}
    if client_secret:
        payload["client_secret"] = client_secret
    response = requests.post(token_url, data=payload, timeout=20)
    if response.status_code != 200:
        print(f"[LLM Mini] OAuth refresh failed for {provider}: HTTP {response.status_code} {response.text}")
        return None
    token_data = response.json()
    write_tokens(provider, client_id, client_secret, token_data, token_url)
    return token_data.get("access_token") or token_data.get("accessToken")


def get_oauth_token(provider: str, refresh_margin: int = 86400) -> str | None:
    config = load_ini()
    section = f"{provider}_oauth"
    if not config.has_section(section):
        return None
    token = config.get(section, "access_token", fallback="")
    try:
        expires_at = int(config.get(section, "token_expires_at", fallback="0"))
    except ValueError:
        expires_at = 0
    if not token:
        return None
    if time.time() > expires_at - refresh_margin:
        return refresh_oauth_token(provider) or token
    return token


def resolve_oauth_marker(api_key: str, provider_hint: str, base_url: str, model_name: str) -> tuple[str, str, str]:
    marker = (api_key or "").strip().lower()
    provider = provider_hint
    if marker in {"oauth", "xai_oauth", "codex_oauth"}:
        if marker == "xai_oauth":
            provider = "xai"
        elif marker == "codex_oauth":
            provider = "codex"
        elif "x.ai" in (base_url or "") or "grok" in (model_name or "").lower():
            provider = "xai"
        else:
            provider = "codex"
        token = get_oauth_token(provider)
        if token:
            api_key = token
            if provider == "xai" and not base_url:
                base_url = "https://api.x.ai/v1/"
            elif provider == "codex" and not base_url:
                base_url = "https://chatgpt.com/backend-api/"
    return api_key, base_url, provider


def run_redirect_flow(provider: str, custom_client_id: str = "", custom_client_secret: str = "") -> None:
    creds = DEFAULT_CREDENTIALS[provider]
    client_id = custom_client_id or creds["client_id"]
    client_secret = custom_client_secret or creds["client_secret"]
    port = 56121 if provider == "xai" else 1455
    redirect_uri = f"http://127.0.0.1:{port}/callback" if provider == "xai" else "http://localhost:1455/auth/callback"
    server = HTTPServer(("0.0.0.0", port), CallbackHandler)
    server.auth_code = None
    server.auth_state = None
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_hex(16)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": creds["scope"],
    }
    if provider == "codex":
        params["audience"] = "https://api.openai.com/v1"
    url = f"{creds['auth_url']}?{urllib.parse.urlencode(params)}"
    print(f"\nStarting browser login / redirect PKCE flow for {provider}.")
    print(f"Open this URL if the browser does not open automatically:\n{url}\n")
    webbrowser.open(url)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    manual_code = [None]

    def read_manual_code() -> None:
        try:
            code = input("If the browser cannot redirect back, paste the authorization code here and press Enter: ").strip()
            if code:
                manual_code[0] = code
        except (EOFError, KeyboardInterrupt):
            return

    input_thread = threading.Thread(target=read_manual_code, daemon=True)
    input_thread.start()

    print(f"Listening on local port {port} for the browser callback.")
    print("Waiting for authorization. Press Ctrl+C to cancel.")
    try:
        while server.auth_code is None and manual_code[0] is None:
            time.sleep(0.5)
    except KeyboardInterrupt as exc:
        server.shutdown()
        raise RuntimeError("Browser authorization was cancelled.") from exc
    finally:
        time.sleep(1.0)
        server.shutdown()

    if manual_code[0] is not None:
        server.auth_code = manual_code[0]
    if not server.auth_code:
        raise RuntimeError("No authorization code received.")
    if server.auth_state and server.auth_state != state:
        raise RuntimeError("OAuth state mismatch; refusing to exchange the authorization code.")

    print("Authorization code received. Exchanging it for tokens...")
    payload = {
        "grant_type": "authorization_code",
        "code": server.auth_code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    if client_secret:
        payload["client_secret"] = client_secret
    response = requests.post(creds["token_url"], data=payload, timeout=20)
    response.raise_for_status()
    write_tokens(provider, client_id, client_secret, response.json(), creds["token_url"])
    print("Browser OAuth login completed and tokens were saved.")


def run_device_code_flow(provider: str, custom_client_id: str = "", custom_client_secret: str = "") -> None:
    creds = DEFAULT_CREDENTIALS[provider]
    client_id = custom_client_id or creds["client_id"]
    client_secret = custom_client_secret or creds["client_secret"]
    print(f"\nStarting device code flow for {provider}.")
    if provider == "codex":
        code_resp = requests.post(creds["device_url"], json={"client_id": client_id}, timeout=20)
        code_resp.raise_for_status()
        data = code_resp.json()
        user_code = data["user_code"]
        print(f"Open https://auth.openai.com/codex/device and enter code: {user_code}")
        webbrowser.open(f"https://auth.openai.com/codex/device?user_code={user_code}")
        poll_payload = {"client_id": client_id, "device_auth_id": data["device_auth_id"], "user_code": user_code}
        start = time.time()
        while time.time() - start < 900:
            time.sleep(int(data.get("interval", 5)))
            poll = requests.post("https://auth.openai.com/api/accounts/deviceauth/token", json=poll_payload, timeout=20)
            if poll.status_code == 200:
                token_data = poll.json()
                exchange = requests.post(
                    creds["token_url"],
                    data={
                        "grant_type": "authorization_code",
                        "client_id": client_id,
                        "code": token_data["authorization_code"],
                        "code_verifier": token_data["code_verifier"],
                        "redirect_uri": "https://auth.openai.com/deviceauth/callback",
                    },
                    timeout=20,
                )
                exchange.raise_for_status()
                write_tokens(provider, client_id, client_secret, exchange.json(), creds["token_url"])
                return
        raise TimeoutError("Device authorization timed out.")

    payload = {"client_id": client_id, "scope": creds["scope"]}
    if client_secret:
        payload["client_secret"] = client_secret
    code_resp = requests.post(creds["device_url"], data=payload, timeout=20)
    code_resp.raise_for_status()
    data = code_resp.json()
    print(f"Open {data.get('verification_uri')} and enter code: {data.get('user_code')}")
    if data.get("verification_uri_complete"):
        webbrowser.open(data["verification_uri_complete"])
    poll_payload = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": data["device_code"],
        "client_id": client_id,
    }
    if client_secret:
        poll_payload["client_secret"] = client_secret
    start = time.time()
    while time.time() - start < int(data.get("expires_in", 300)):
        time.sleep(int(data.get("interval", 5)))
        poll = requests.post(creds["token_url"], data=poll_payload, timeout=20)
        if poll.status_code == 200:
            write_tokens(provider, client_id, client_secret, poll.json(), creds["token_url"])
            return
    raise TimeoutError("Device authorization timed out.")


# 全局 OAuth 授权状态存储
OAUTH_STATES: dict[str, dict] = {}


def start_async_oauth_flow(provider: str, flow_type: str) -> dict:
    provider = provider.strip().lower()
    if provider not in DEFAULT_CREDENTIALS:
        raise ValueError(f"Unsupported OAuth provider: {provider}")
    
    # 如果该提供商当前有正在进行的 pending 授权，先将其状态改为已取消，让原线程优雅终止
    if provider in OAUTH_STATES and OAUTH_STATES[provider].get("status") == "pending":
        OAUTH_STATES[provider]["status"] = "cancelled"
        OAUTH_STATES[provider]["error"] = "Cancelled due to new authorization request."
        time.sleep(0.6)
        
    OAUTH_STATES[provider] = {
        "status": "pending",
        "user_code": "",
        "verification_uri": "",
        "expires_in": 300,
        "start_time": time.time(),
        "error": ""
    }
    
    if flow_type == "device":
        return _start_async_device_flow(provider)
    else:
        return _start_async_browser_flow(provider)


def _start_async_device_flow(provider: str) -> dict:
    creds = DEFAULT_CREDENTIALS[provider]
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]
    
    if provider == "codex":
        code_resp = requests.post(creds["device_url"], json={"client_id": client_id}, timeout=20)
        code_resp.raise_for_status()
        data = code_resp.json()
        user_code = data["user_code"]
        verification_uri = f"https://auth.openai.com/codex/device?user_code={user_code}"
        expires_in = 900
        poll_url = "https://auth.openai.com/api/accounts/deviceauth/token"
        poll_payload = {"client_id": client_id, "device_auth_id": data["device_auth_id"], "user_code": user_code}
    else:  # xai
        payload = {"client_id": client_id, "scope": creds["scope"]}
        if client_secret:
            payload["client_secret"] = client_secret
        code_resp = requests.post(creds["device_url"], data=payload, timeout=20)
        code_resp.raise_for_status()
        data = code_resp.json()
        user_code = data.get("user_code", "")
        verification_uri = data.get("verification_uri_complete") or data.get("verification_uri", "")
        expires_in = int(data.get("expires_in", 300))
        poll_url = creds["token_url"]
        poll_payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": data["device_code"],
            "client_id": client_id,
        }
        if client_secret:
            poll_payload["client_secret"] = client_secret

    OAUTH_STATES[provider].update({
        "user_code": user_code,
        "verification_uri": verification_uri,
        "expires_in": expires_in,
        "start_time": time.time(),
    })

    def background_device_poll():
        start = time.time()
        interval = int(data.get("interval", 5))
        while time.time() - start < expires_in:
            if OAUTH_STATES.get(provider, {}).get("status") != "pending":
                break
            time.sleep(interval)
            try:
                poll = requests.post(poll_url, json=poll_payload if provider == "codex" else None, data=None if provider == "codex" else poll_payload, timeout=20)
                if poll.status_code == 200:
                    token_data = poll.json()
                    if provider == "codex":
                        exchange = requests.post(
                            creds["token_url"],
                            data={
                                "grant_type": "authorization_code",
                                "client_id": client_id,
                                "code": token_data["authorization_code"],
                                "code_verifier": token_data["code_verifier"],
                                "redirect_uri": "https://auth.openai.com/deviceauth/callback",
                            },
                            timeout=20,
                        )
                        exchange.raise_for_status()
                        write_tokens(provider, client_id, client_secret, exchange.json(), creds["token_url"])
                    else:  # xai
                        write_tokens(provider, client_id, client_secret, token_data, creds["token_url"])
                    OAUTH_STATES[provider]["status"] = "success"
                    break
            except Exception:
                pass
        else:
            OAUTH_STATES[provider]["status"] = "failed"
            OAUTH_STATES[provider]["error"] = "Device authorization timed out."

    threading.Thread(target=background_device_poll, daemon=True).start()
    return OAUTH_STATES[provider]


def _start_async_browser_flow(provider: str) -> dict:
    creds = DEFAULT_CREDENTIALS[provider]
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]
    port = 56121 if provider == "xai" else 1455
    redirect_uri = f"http://127.0.0.1:{port}/callback" if provider == "xai" else "http://localhost:1455/auth/callback"
    
    server = HTTPServer(("0.0.0.0", port), CallbackHandler)
    server.auth_code = None
    server.auth_state = None
    
    # 关键：立刻在同步线程中启动并运行本地 HTTPServer 服务，确保端口在向前发回 URL 和 window.open 之前已绝对处于监听 serve 状态
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_hex(16)
    
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": creds["scope"],
    }
    if provider == "codex":
        params["audience"] = "https://api.openai.com/v1"
    url = f"{creds['auth_url']}?{urllib.parse.urlencode(params)}"
    
    OAUTH_STATES[provider].update({
        "verification_uri": url,
        "expires_in": 300,
        "start_time": time.time(),
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    })

    def background_browser_server():
        start = time.time()
        while time.time() - start < 300:
            if OAUTH_STATES.get(provider, {}).get("status") != "pending":
                break
            if server.auth_code is not None:
                # 留出 1.0 秒时间，确保 HTTPServer 将网页接收成功的 HTML 响应完全发回给浏览器后再进行后续操作和 shutdown
                time.sleep(1.0)
                if server.auth_state and server.auth_state != state:
                    OAUTH_STATES[provider]["status"] = "failed"
                    OAUTH_STATES[provider]["error"] = "OAuth state mismatch."
                    break
                try:
                    payload = {
                        "grant_type": "authorization_code",
                        "code": server.auth_code,
                        "client_id": client_id,
                        "redirect_uri": redirect_uri,
                        "code_verifier": verifier,
                    }
                    if client_secret:
                        payload["client_secret"] = client_secret
                    response = requests.post(creds["token_url"], data=payload, timeout=20)
                    response.raise_for_status()
                    write_tokens(provider, client_id, client_secret, response.json(), creds["token_url"])
                    OAUTH_STATES[provider]["status"] = "success"
                except Exception as e:
                    OAUTH_STATES[provider]["status"] = "failed"
                    OAUTH_STATES[provider]["error"] = f"Token exchange failed: {e}"
                break
            time.sleep(0.5)
        else:
            OAUTH_STATES[provider]["status"] = "failed"
            OAUTH_STATES[provider]["error"] = "Browser login timed out."
            
        server.shutdown()

    threading.Thread(target=background_browser_server, daemon=True).start()
    return OAUTH_STATES[provider]


def exchange_manual_code(provider: str, code: str) -> None:
    provider = provider.strip().lower()
    state = OAUTH_STATES.get(provider)
    if not state or state.get("status") != "pending":
        raise RuntimeError("No active authorization flow found for this provider.")
    
    creds = DEFAULT_CREDENTIALS[provider]
    client_id = state.get("client_id") or creds["client_id"]
    client_secret = state.get("client_secret") or creds["client_secret"]
    redirect_uri = state.get("redirect_uri")
    verifier = state.get("code_verifier")
    
    if not redirect_uri or not verifier:
        raise RuntimeError("Flow context missing. Please restart the authorization.")
    
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }
    if client_secret:
        payload["client_secret"] = client_secret
        
    response = requests.post(creds["token_url"], data=payload, timeout=20)
    response.raise_for_status()
    
    write_tokens(provider, client_id, client_secret, response.json(), creds["token_url"])
    OAUTH_STATES[provider]["status"] = "success"
