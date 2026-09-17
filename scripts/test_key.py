"""Standalone probe for the OpenRouter Analytics API.

Reads OPENROUTER_MANAGEMENT_KEY from .env (same dir as this script, or
./.env from the repo root) and replays the EXACT requests the Home Assistant
integration makes, printing the raw status + body so you can see what
OpenRouter actually says.

Usage:
    python scripts/test_key.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import urllib.request
    import urllib.error
except ImportError:  # pragma: no cover
    raise

API_QUERY = "https://openrouter.ai/api/v1/analytics/query"
ROOT = Path(__file__).resolve().parent.parent  # repo root


def load_key() -> str:
    env_file = ROOT / ".env"
    key = ""
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPENROUTER_MANAGEMENT_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not key or "REPLACE_ME" in key:
        print("No key set. Edit .env and set OPENROUTER_MANAGEMENT_KEY=<your key>")
        raise SystemExit(1)
    return key


def ts_format(dt: datetime, style: str) -> str:
    """Expose the two timestamp formats to compare against the API."""
    if style == "z":          # what the fix uses: +00:00 -> Z
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.isoformat()      # what the original code used: ...+00:00


def post(payload: dict, key: str) -> tuple[int, str]:
    req = urllib.request.Request(
        API_QUERY,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # noqa: BLE001
        return -1, f"network error: {e}"


def main() -> None:
    key = load_key()
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(hours=1)

    for style in ("z", "iso"):
        payload = {
            "metrics": ["request_count"],
            "time_range": {
                "start": ts_format(start, style),
                "end": ts_format(end, style),
            },
            "limit": 1,
        }
        status, body = post(payload, key)
        print(f"--- timestamp format: {style}  ->  {ts_format(start, style)}")
        print(f"HTTP {status}")
        print(body if body else "(empty body)")
        print()

    # Full metric set over a 7-day window, Z-format (what sensors use).
    start7 = end - timedelta(days=7)
    payload = {
        "metrics": ["total_usage", "request_count", "tokens_total", "cache_hit_rate"],
        "time_range": {
            "start": ts_format(start7, "z"),
            "end": ts_format(end, "z"),
        },
        "limit": 10,
        "dimensions": ["model"],
    }
    status, body = post(payload, key)
    print("--- full query (7d, dimensions=[model]) Z-format ---")
    print(f"HTTP {status}")
    print(body if body else "(empty body)")

    print()
    if status == 200:
        print("SUCCESS: key works, API accepts the request. Integration should now work.")
    elif status == 403:
        print("FAIL: 403 -> this is NOT a management key (or lacks Analytics access).")
    elif status == 400:
        print("FAIL: 400 -> malformed request. The API rejected our payload.")
    elif status == 401:
        print("FAIL: 401 -> OpenRouter did not recognize the key.")
    else:
        print(f"Unexpected result (HTTP {status}). Inspect the body above.")


if __name__ == "__main__":
    main()