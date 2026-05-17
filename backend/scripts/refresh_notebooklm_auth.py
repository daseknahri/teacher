from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import subprocess
import sys

import httpx


def _default_auth_path(profile: str) -> Path:
    return Path.home() / ".notebooklm" / "profiles" / profile / "storage_state.json"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the deployed app's NotebookLM auth by uploading a fresh local "
            "storage_state.json and optionally running a live smoke test."
        )
    )
    parser.add_argument("--app-url", required=True, help="App base URL, for example https://teacher.ibnbatoutaweb.com")
    parser.add_argument("--email", required=True, help="Owner account email for the app")
    parser.add_argument("--password", help="Owner password. If omitted, you will be prompted securely.")
    parser.add_argument("--profile", default="default", help="Local NotebookLM profile name. Default: default")
    parser.add_argument(
        "--auth-file",
        help="Path to local storage_state.json. Defaults to %%USERPROFILE%%\\.notebooklm\\profiles\\<profile>\\storage_state.json",
    )
    parser.add_argument(
        "--run-login",
        action="store_true",
        help="Run `python -m notebooklm login` locally before uploading the auth file.",
    )
    parser.add_argument(
        "--skip-smoke-test",
        action="store_true",
        help="Upload the auth file but skip the live NotebookLM smoke test.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="HTTP timeout in seconds. Default: 60",
    )
    return parser.parse_args()


def _run_local_login() -> None:
    print("Running local NotebookLM login...")
    result = subprocess.run([sys.executable, "-m", "notebooklm", "login"])
    if result.returncode != 0:
        raise SystemExit(f"NotebookLM login failed with exit code {result.returncode}.")


def _login_to_app(client: httpx.Client, app_url: str, email: str, password: str) -> str:
    resp = client.post(
        f"{app_url.rstrip('/')}/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    payload = resp.json()
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise SystemExit("Login succeeded but no access_token was returned.")
    return token


def main() -> int:
    args = _parse_args()
    password = args.password or getpass.getpass("Owner password: ")
    auth_path = Path(args.auth_file).expanduser() if args.auth_file else _default_auth_path(args.profile)

    if args.run_login:
        _run_local_login()

    if not auth_path.exists():
        raise SystemExit(f"Auth file not found: {auth_path}")

    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"Failed to read auth JSON from {auth_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("cookies"), list) or not isinstance(payload.get("origins"), list):
        raise SystemExit("Auth file does not look like a valid Playwright storage_state.json.")

    with httpx.Client(timeout=args.timeout, follow_redirects=True) as client:
        token = _login_to_app(client, args.app_url, args.email, password)
        headers = {"Authorization": f"Bearer {token}"}

        with auth_path.open("rb") as handle:
            upload_resp = client.post(
                f"{args.app_url.rstrip('/')}/ops/notebooklm/auth/upload",
                headers=headers,
                files={"file": (auth_path.name, handle, "application/json")},
            )
        upload_resp.raise_for_status()
        upload_payload = upload_resp.json()

        print("NotebookLM auth uploaded.")
        print(f"Ready: {upload_payload.get('ready')}")
        print(f"Auth file path on server: {upload_payload.get('auth_path')}")
        print(f"Cookies detected on server: {upload_payload.get('cookies_count')}")

        if args.skip_smoke_test:
            return 0

        smoke_resp = client.post(
            f"{args.app_url.rstrip('/')}/ops/notebooklm/smoke-test",
            headers=headers,
        )
        smoke_resp.raise_for_status()
        smoke_payload = smoke_resp.json()
        smoke = smoke_payload.get("smoke") or {}

        print("")
        print("Smoke test:")
        print(f"  Ready: {smoke_payload.get('ready')}")
        print(f"  Result: {'Success' if smoke.get('ok') else 'Failed'}")
        print(f"  Answer: {smoke.get('answer') or '-'}")
        if smoke.get("error_message"):
            print(f"  Error: {smoke.get('error_message')}")

        return 0 if smoke.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
