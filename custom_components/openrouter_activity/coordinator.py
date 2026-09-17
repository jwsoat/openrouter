"""Data coordinator that queries the OpenRouter Analytics API."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    API_QUERY,
    CONF_MANAGEMENT_KEY,
    CONF_PERIOD,
    CONF_SCAN_INTERVAL,
    DEFAULT_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    METRICS,
    PERIOD_PRESETS,
    TOP_DIMENSIONS,
    TOP_N,
)

_LOGGER = logging.getLogger(__name__)

# A point before any OpenRouter usage, used for an "all time" window.
_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _num(value: Any) -> float:
    """Counts can arrive as int, float, or string - coerce defensively."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def period_window(period: str) -> tuple[datetime, datetime]:
    """Return (start, end) UTC datetimes for a rolling preset window."""
    days = PERIOD_PRESETS.get(period, PERIOD_PRESETS[DEFAULT_PERIOD])
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = max(end - timedelta(days=days), _EPOCH)
    return start, end


async def _post(session: aiohttp.ClientSession, api_key: str, payload: dict) -> dict:
    """POST one analytics query and return the parsed JSON response."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with session.post(
            API_QUERY, headers=headers, json=payload, timeout=timeout
        ) as resp:
            text = await resp.text()
            body = json.loads(text) if text else {}
    except asyncio.TimeoutError as err:
        raise UpdateFailed("OpenRouter Analytics request timed out") from err
    except (aiohttp.ClientError, json.JSONDecodeError) as err:
        raise UpdateFailed(f"Network error calling OpenRouter Analytics: {err}") from err

    if resp.status != 200:
        message = "Unknown error"
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            message = body["error"].get("message") or message
        _LOGGER.warning("Analytics query failed (%s): %s", resp.status, message)
        if resp.status in (401, 403):
            raise ConfigEntryAuthFailed(
                f"OpenRouter returned {resp.status}: {message}"
            )
        raise UpdateFailed(f"OpenRouter Analytics query failed ({resp.status}): {message}")

    data = body.get("data") or {}
    return data.get("data") or []


async def validate_management_key(
    session: aiohttp.ClientSession, api_key: str
) -> tuple[bool, str | None, str]:
    """Check a key against the Analytics API; return (ok, error_key, message).

    Used by the config flow to reject keys before the entry is created.
    Runs a single aggregate query over an empty one-hour window.
    """
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    payload = {
        "metrics": ["request_count"],
        "time_range": {
            "start": (end - timedelta(hours=1)).isoformat(),
            "end": end.isoformat(),
        },
        "limit": 1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with session.post(
            API_QUERY, headers=headers, json=payload, timeout=timeout
        ) as resp:
            text = await resp.text()
            body = json.loads(text) if text else {}
    except asyncio.TimeoutError as err:
        _LOGGER.warning("OpenRouter key validation timed out")
        return False, "cannot_connect", "timed out"
    except aiohttp.ClientError as err:
        _LOGGER.warning("OpenRouter key validation network error: %s", err)
        return False, "cannot_connect", str(err)
    except Exception as err:  # noqa: BLE001
        _LOGGER.exception("Unexpected error validating OpenRouter management key")
        return False, "invalid_key", str(err)

    if resp.status == 200:
        return True, None, ""
    message = "Unknown error"
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        message = body["error"].get("message") or message
    if resp.status in (401, 403):
        return False, "not_management_key", message
    if resp.status in (408, 500, 502, 503):
        return False, "cannot_connect", message
    return False, "invalid_key", message


class OpenRouterCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch OpenRouter usage analytics on a schedule."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.api_key: str = entry.data[CONF_MANAGEMENT_KEY]
        super().__init__(
            hass,
            _LOGGER,
            name=f"OpenRouter Activity {entry.title}",
            update_interval=timedelta(
                seconds=int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
            ),
        )

    @property
    def period(self) -> str:
        return self.entry.options.get(CONF_PERIOD, DEFAULT_PERIOD)

    def reconfigure_options(self) -> None:
        """Apply option changes (period / scan interval) without a reload."""
        self.update_interval = timedelta(
            seconds=int(
                self.entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            )
        )

    async def _async_update_data(self) -> dict[str, Any]:
        session = self.hass.helpers.aiohttp_client.async_get_clientsession(self.hass)
        start, end = period_window(self.period)
        time_range = {"start": start.isoformat(), "end": end.isoformat()}

        aggregate = {
            "metrics": list(METRICS),
            "time_range": time_range,
            "limit": 1,
        }
        top_payloads = {
            dim: {
                "metrics": list(METRICS),
                "dimensions": [dim],
                "time_range": time_range,
                "order_by": {"field": "total_usage", "direction": "desc"},
                "limit": TOP_N,
            }
            for dim in TOP_DIMENSIONS
        }

        results = await asyncio.gather(
            _post(session, self.api_key, aggregate),
            *[_post(session, self.api_key, top_payloads[d]) for d in TOP_DIMENSIONS],
            return_exceptions=True,
        )
        for res in results:
            if isinstance(res, Exception):
                raise res

        agg_rows: list[dict] = results[0]
        agg = agg_rows[0] if agg_rows else {}

        spend = _num(agg.get("total_usage"))
        requests = _num(agg.get("request_count"))
        tokens = _num(agg.get("tokens_total"))
        cache = _num(agg.get("cache_hit_rate"))
        blended = (spend / tokens * 1e6) if tokens > 0 else 0.0

        top: dict[str, Any] = {}
        for i, dim in enumerate(TOP_DIMENSIONS):
            rows = results[i + 1] if isinstance(results[i + 1], list) else []
            label = str(rows[0].get(dim)) if rows and rows[0].get(dim) else None
            top[dim] = {
                "label": label,
                "rows": rows,
                "spend": _num(rows[0].get("total_usage")) if rows else 0.0,
                "requests": _num(rows[0].get("request_count")) if rows else 0.0,
                "tokens": _num(rows[0].get("tokens_total")) if rows else 0.0,
                "cache_hit_rate": _num(rows[0].get("cache_hit_rate")) if rows else 0.0,
            }

        return {
            "period": self.period,
            "window_start": start,
            "window_end": end,
            "total_spend": spend,
            "total_requests": requests,
            "total_tokens": tokens,
            "cache_hit_rate": cache * 100.0,  # expose as percent
            "blended_cost_per_mtok": blended,
            "top": top,
            "updated_at": datetime.now(timezone.utc),
        }