"""Gather HA diagnostics + enable debug logging for the integration."""

from __future__ import annotations

import json
from pathlib import Path

import websockets.sync.client as ws

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        for k in ("HA_BASE_URL", "HA_TOKEN"):
            if line.startswith(k + "="):
                out[k] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return out


def main() -> None:
    env = load_env()
    base, token = env["HA_BASE_URL"], env["HA_TOKEN"]
    host = base.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    with ws.connect(f"{host}/api/websocket", open_timeout=15,
                    additional_headers={"User-Agent": UA}) as sock:
        sock.recv()
        sock.send(json.dumps({"type": "auth", "access_token": token}))
        sock.recv()

        def call(mid: int, mtype: str, **kw):
            sock.send(json.dumps({"id": mid, "type": mtype, **kw}))
            while True:
                r = json.loads(sock.recv())
                if r.get("id") == mid:
                    return r

        cfg = call(1, "config/core/check_config")
        print("== config/core/check_config (truncated) ==")
        print(json.dumps(cfg.get("result", cfg.get("error")))[:300])

        # logger level for the integration
        r = call(2, "logger/set_level",
                 level={"custom_components.openrouter_activity": "DEBUG"})
        print("\n== logger/set_level ==", "ok" if r.get("success") else r.get("error"))

        # errors present now
        r = call(3, "system_log/error/all")
        errs = r.get("result") or []
        print(f"\n== system_log errors: {len(errs)} ==")
        for e in errs[:15]:
            print(" -", e.get("name"), "|", e.get("message", "")[:150])


if __name__ == "__main__":
    main()