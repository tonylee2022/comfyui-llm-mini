from __future__ import annotations

import argparse
import os
import shutil
import subprocess

from core.oauth import run_device_code_flow, run_redirect_flow


def main() -> None:
    parser = argparse.ArgumentParser(description="ComfyUI LLM Mini OAuth login helper")
    parser.add_argument("--provider", choices=["xai", "codex"], help="Provider to authorize")
    parser.add_argument("--flow", choices=["device", "browser", "redirect"], help="Authorization flow to use (for xai/codex)")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--client-secret", default="")
    args = parser.parse_args()

    print("==================================================")
    print("      ComfyUI LLM Mini OAuth login helper")
    print("==================================================")

    provider = args.provider
    if not provider:
        print("1. xAI")
        print("2. Codex / OpenAI")
        choice = input("Select provider (1-2): ").strip()
        if choice == "1":
            provider = "xai"
        elif choice == "2":
            provider = "codex"
        else:
            provider = ""

    if provider not in {"xai", "codex"}:
        raise SystemExit("Invalid provider.")

    # 常规 xAI / Codex OAuth 登录流程
    flow = args.flow
    if not flow:
        print(f"\nSelected provider: {provider}")
        print("1. Device code login")
        print("2. Browser login / redirect PKCE")
        choice = input("Select authorization flow (1-2): ").strip()
        flow = "device" if choice == "1" else "browser" if choice == "2" else ""
    if flow not in {"device", "browser", "redirect"}:
        raise SystemExit("Invalid authorization flow.")

    if flow in {"browser", "redirect"}:
        run_redirect_flow(provider, args.client_id, args.client_secret)
    else:
        run_device_code_flow(provider, args.client_id, args.client_secret)
    print("OAuth login completed.")


if __name__ == "__main__":
    main()
