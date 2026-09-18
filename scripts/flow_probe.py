"""Drive the OpenRouter Activity config flow over the HA websocket API.

Reproduces exactly what happens when you press submit:
  - starts a config_flow for handler 'openrouter_activity'
  - submits the management key from .env (same payload the form sends)
  - prints the raw flow result (success / per-field errors / unknown)
and pulls any matching system_log errors.

Local diagnostic tool. Reads secrets from .env; never prints them.
"""

from __future__ import annotations

import json
from pathlib import Path

import websockets.sync.client as ws

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

HANDLER = "openrouter_activity"


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        for k in ("HA_BASE_URL", "HA_TOKEN", "OPENROUTER_MANAGEMENT_KEY"):
            if line.startswith(k + "="):
                out[k] = line.split("=", 1)[1].strip().strip('"').strip("'")
    return out


def main() -> None:
    env = load_env()
    base = env.get("HA_BASE_URL", "")
    token = env.get("HA_TOKEN", "")
    key = env.get("OPENROUTER_MANAGEMENT_KEY", "")

    if not all((base, token, key)) or "REPLACE_ME" in key:
        print("Missing HA_BASE_URL / HA_TOKEN / real OPENROUTER_MANAGEMENT_KEY in .env")
        return

    host = base.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    with ws.connect(
        f"{host}/api/websocket", open_timeout=15,
        additional_headers={"User-Agent": BROWSER_UA},
    ) as sock:
        sock.recv()  # auth_required
        sock.send(json.dumps({"type": "auth", "access_token": token}))
        auth = json.loads(sock.recv())
        print("auth ok:", auth.get("type") == "auth_ok")
        if auth.get("type") != "auth_ok":
            print(auth)
            return

        def call(msg_id: int, mtype: str, **kw) -> dict:
            sock.send(json.dumps({"id": msg_id, "type": mtype, **kw}))
            while True:
                r = json.loads(sock.recv())
                if r.get("id") == msg_id:
                    return r

        # 1. current system_log errors mentioning openrouter
        r = call(1, "system_log/error/all")
        errs = r.get("result") or []
        hits = [e for e in errs if "openrouter" in str(e).lower()]
        print(f"\nsystem_log errors referencing openrouter: {len(hits)}")
        for e in hits[:10]:
            print("  -", e.get("name"), "|", e.get("message", "")[:200])
            exc = e.get("exception") or ""
            if exc:
                print("    exception:", exc[:400])

        # 2. start the flow
        print(f"\nconfig_flow/init handler={HANDLER} ...")
        r = call(2, "config_flow/init", handler=HANDLER)
        if not r.get("success"):
            print("init failed:", r.get("error"))
            return
        flow = r["result"]
        flow_id = flow["flow_id"]
        step_id = flow["step_id"]
        data_schema = flow.get("data_schema") or {}
        print(f"flow_id={flow_id} step_id={step_id}")

        fields = {}
        for f in data_schema.get("fields", []):
            name = f["name"]
            if name == "management_key":
                fields[name] = key
            elif name == "name":
                fields[name] = "probe-test"
            else:  # period / any select
                first = (f.get("options") or [{}])[0]
                fields[name] = first.get("value")
                break
        print("submitting fields:", list(fields.keys()))

        # 3. submit (the submit button)
        sock.send(json.dumps({
            "id": 3,
            "type": "config_flow/step",
            "flow_id": flow_id,
            "user_input": fields,
        }))
        # results may arrive as an event first, then the response
        result = None
        while True:
            r = json.loads(sock.recv())
            if r.get("id") == 3:
                result = r
                break
        print("\n=== flow step result ===")
        print(json.dumps(result, indent=2)[:2000])

        if result.get("success") and result.get("result", {}).get("type") == "create_entry":
            print("\nENTRY CREATED - setup seeded by this probe (can be deleted if unwanted).")

        # 4. re-check system_log for the traceback now reported
        r = call(4, "system_log/error/all")
        errs = r.get("result") or []
        hits = [e for e in errs if "openrouter" in str(e).lower()]
        print(f"\nsystem_log errors referencing openrouter AFTER submit: {len(hits)}")
        for e in hits[:10]:
            print("  -", e.get("name"), "|", e.get("message", "")[:300])
            exc = e.get("exception") or ""
            if exc:
                print("    exception:", exc[:800])


if __name__ == "__main__":
    main()