"""Sensor entities exposing OpenRouter usage analytics."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_DOLLAR, PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OpenRouterCoordinator

SCAN_INTERVAL = timedelta(seconds=30)


def _label(value: dict[str, Any] | None) -> str | None:
    """Human-friendly label; None when the breakdown had no data."""
    if not value:
        return None
    label = value.get("label")
    return str(label) if label not in (None, "") else None


def _fmt_spend(value: float) -> str:
    return f"${value:,.2f}"


class OpenRouterSensor(CoordinatorEntity, SensorEntity):
    """A single analytics value backed by the coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OpenRouterCoordinator,
        entry: ConfigEntry,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_extra_state_attributes = self._compute_attributes()

    def _handle_coordinator_update(self) -> None:
        """Refresh dynamic attributes whenever the coordinator updates."""
        self._attr_extra_state_attributes = self._compute_attributes()
        super()._handle_coordinator_update()

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data

    @property
    def native_value(self) -> Any:
        return self._extract_value()

    def _extract_value(self) -> Any:
        key = self.entity_description.key
        data = self._data
        if key == "total_spend":
            return round(float(data["total_spend"]), 4)
        if key == "total_requests":
            return int(data["total_requests"])
        if key == "total_tokens":
            return int(data["total_tokens"])
        if key == "cache_hit_rate":
            return round(float(data["cache_hit_rate"]), 2)
        if key == "blended_cost_per_mtok":
            return round(float(data["blended_cost_per_mtok"]), 4)
        if key == "top_model":
            return _label(data["top"].get("model"))
        if key == "top_api_key":
            return _label(data["top"].get("api_key_id"))
        if key == "top_app":
            return _label(data["top"].get("app"))
        if key == "updated":
            return data["updated_at"]
        if key == "window":
            return (
                f"{data['window_start'].date()} to {data['window_end'].date()}"
            )
        return None

    def _compute_attributes(self) -> dict[str, Any]:
        key = self.entity_description.key
        if key in ("top_model", "top_api_key", "top_app"):
            dim_lookup = {
                "top_model": "model",
                "top_api_key": "api_key_id",
                "top_app": "app",
            }
            bucket = self._data.get("top", {}).get(dim_lookup[key]) or {}
            rows = bucket.get("rows") or []
            return {
                "name": bucket.get("label"),
                "spend": round(float(bucket.get("spend", 0.0)), 4),
                "requests": int(bucket.get("requests", 0)),
                "tokens": int(bucket.get("tokens", 0)),
                "ranked": [self._row_to_attr(r, dim_lookup[key]) for r in rows],
                "truncated": len(rows) == 10,
            }
        return {}

    @staticmethod
    def _row_to_attr(row: dict[str, Any], dim: str) -> dict[str, Any]:
        return {
            "name": row.get(dim),
            "spend": round(float(row.get("total_usage") or 0.0), 4),
            "requests": int(float(row.get("request_count") or 0) or 0),
            "tokens": int(float(row.get("tokens_total") or 0) or 0),
            "cache_hit_rate": round(float(row.get("cache_hit_rate") or 0.0) * 100, 2),
        }


SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key="total_spend",
        name="Total Spend",
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:cash-multiple",
    ),
    SensorEntityDescription(
        key="blended_cost_per_mtok",
        name="Blended Cost per Million Tokens",
        native_unit_of_measurement=CURRENCY_DOLLAR,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        icon="mdi:percent",
    ),
    SensorEntityDescription(
        key="total_requests",
        name="Total Requests",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:counter",
    ),
    SensorEntityDescription(
        key="total_tokens",
        name="Token Volume",
        native_unit_of_measurement="tokens",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:form-textbox",
    ),
    SensorEntityDescription(
        key="cache_hit_rate",
        name="Cache Hit Rate",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:database-check",
    ),
    SensorEntityDescription(
        key="top_model",
        name="Top Model",
        icon="mdi:brain",
    ),
    SensorEntityDescription(
        key="top_api_key",
        name="Top API Key",
        icon="mdi:key-chain-variant",
    ),
    SensorEntityDescription(
        key="top_app",
        name="Top App",
        icon="mdi:apps",
    ),
    SensorEntityDescription(
        key="updated",
        name="Last Updated",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="window",
        name="Stats Window",
        icon="mdi:calendar-range",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: OpenRouterCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        OpenRouterSensor(coordinator, entry, desc) for desc in SENSOR_DESCRIPTIONS
    )