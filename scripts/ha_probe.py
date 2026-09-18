"""Probe a live Home Assistant for the real integration error.

Reads HA_BASE_URL and HA_TOKEN from the repo .env, then:
  - verifies API connectivity + reports the HA version
  - pulls the error log (REST /api/error_log, falling back to websocket
    system_log when available) and prints lines mentioning openrouter_activity
  - lists any openrouter_activity sensor states

Never prints the token. Intended for local diagnostics; keep the .env out of git.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line.startswith(("HA_BASE_URL=", "HA_TOKEN=")):
                k, _, v = line.partition("=")
                out[k] = v.strip().strip('"').strip("'")
    return out


def http_get(base: str, token: str, path: str) -> tuple[int, str]:
    url = base.rstrip("/") + path
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": _BROWSER_UA,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:  # noqa: BLE001
        return -1, f"network/conn error: {e}"


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def main() -> None:
    env = load_env()
    base = env.get("HA_BASE_URL", "").strip()
    token = env.get("HA_TOKEN", "").strip()
    if not base or not token:
        print(f"HA_BASE_URL set: {bool(base)} | HA_TOKEN set: {bool(token)}")
        print("Fill both in .env (they were missing/blank).")
        return

    # 1. connectivity + version
    status, raw = http_get(base, token, "/api/")
    print(f"GET /api/ -> HTTP {status}")
    if status == 200:
        info = json.loads(raw)
        print(f"  HA version: {info.get('version')} | location: {info.get('location_name')}")
    elif status == 401:
        print("  Token rejected (401). Check the long-lived token.")
        return
    else:
        print(f"  Could not reach HA: {raw[:300]}")
        return

    # 2. error log (REST)
    src = "rest"
    estatus, ebody = http_get(base, token, "/api/error_log")
    if estatus != 200:
        # fall back to websocket system_log
        src = "websocket"
        ebody = websocket_system_log(base, token)
    if ebody:
        lines = ebody.splitlines()
        hits = [ln for ln in lines if "openrouter" in ln.lower()]
        if hits:
            print(f"\n--- error_log ({src}) lines mentioning openrouter ({len(hits)}) ---")
            for ln in hits:
                print(ln)
            ctx = "\n".join(lines)
            for m in re.finditer(r"(?m)^.*openrouter.*$", ctx, re.I):
                print(f"[ctx] {m.group(0).strip()[:400]}")
        else:
            print(f"\n--- error_log ({src}) has {len(lines)} lines; no openrouter mentions ---")
    else:
        print(f"\n--- error_log unavailable via {src} ---")

    # 3. openrouter sensors
    sstatus, sraw = http_get(base, token, "/api/states")
    if sstatus == 200:
        states = [s for s in json.loads(sraw) if "openrouter" in s.get("entity_id", "").lower()]
        print(f"\n--- openrouter sensor states: {len(states)} ---")
        for s in states[:20]:
            print(f"  {s.get('entity_id')} = {s.get('state')}")


def websocket_system_log(base: str, token: str) -> str:
    """Best-effort fetch of system_log max-level errors over websocket."""
    try:
        import websockets.sync.client as ws_sync  # type: ignore
    except Exception:  # noqa: BLE001
        return ""
    host = base.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    try:
        with ws_sync.connect(
            f"{host}/api/websocket", open_timeout=10,
            additional_headers={"User-Agent": _BROWSER_UA},
        ) as ws:
            ws.recv()  # auth_required
            ws.send(json.dumps({"type": "auth", "access_token": token}))
            ws.recv()  # auth_ok
            ws.send(json.dumps({"id": 1, "type": "system_log/error/all", "level": "error"}))
            msg = json.loads(ws.recv())
            if msg.get("success") is True and isinstance(msg.get("result"), list):
                out = []
                for e in msg["result"]:
                    line = " ".join(
                        str(e.get(k, "")) for k in ("name", "message", "exception")
                    )
                    out.append(line)
                return "\n".join(out)
            return json.dumps(msg.get("error", msg))[:2000]
    except Exception as e:  # noqa: BLE001
        return f"websocket failed: {e}"


if __name__ == "__main__":
    main()