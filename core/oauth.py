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

    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.server.auth_state = params.get("state", [""])[0]
            body = (
                b"<html><body><h1>Authorization received</h1>"
                b"<p>You can close this window and return to the terminal.</p></body></html>"
            )
        else:
            body = (
                b"<html><body><h1>Authorization failed</h1>"
                b"<p>No authorization code was received.</p></body></html>"
            )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


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
    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
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
