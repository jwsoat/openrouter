"""Config flow for the OpenRouter Activity integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

from .const import (
    CONF_MANAGEMENT_KEY,
    CONF_PERIOD,
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PERIOD_PRESETS,
)
from .coordinator import validate_management_key

_LOGGER = logging.getLogger(__name__)

PERIOD_DESCRIPTIONS = {
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
    "90d": "Last 90 days",
    "1y": "Last year",
}


async def _try_connect(hass: HomeAssistant, key: str) -> tuple[bool, str | None, str]:
    """Validate a management key; return (ok, error_translation_key, detail)."""
    session = hass.helpers.aiohttp_client.async_get_clientsession(hass)
    ok, error_key, msg = await validate_management_key(session, key)
    return ok, error_key, msg


class OpenRouterActivityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for OpenRouter Activity."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                ok, error_key, detail = await _try_connect(
                    self.hass, user_input[CONF_MANAGEMENT_KEY]
                )
                if ok:
                    name = user_input.get(CONF_NAME) or DEFAULT_NAME
                    return self.async_create_entry(
                        title=name,
                        data={CONF_MANAGEMENT_KEY: user_input[CONF_MANAGEMENT_KEY]},
                        options={
                            CONF_PERIOD: user_input.get(CONF_PERIOD, DEFAULT_PERIOD),
                            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        },
                    )
                # Log the real reason at ERROR so it lands in the system log.
                _LOGGER.error(
                    "OpenRouter key validation failed (base=%s): %s",
                    error_key,
                    detail,
                )
                errors["base"] = error_key or "invalid_key"
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Unexpected error in OpenRouter Activity config flow submit"
                )
                errors["base"] = "cannot_connect"

        data_schema = vol.Schema(
            {
                vol.Required(CONF_MANAGEMENT_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                        autocomplete="off",
                    )
                ),
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Optional(CONF_PERIOD, default=DEFAULT_PERIOD): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(PERIOD_DESCRIPTIONS.keys()),
                        translation_key="period",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm(user_input)

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            ok, error_key = await _try_connect(self.hass, user_input[CONF_MANAGEMENT_KEY])
            if ok:
                entry = self._get_reauth_entry()
                self.hass.config_entries.async_update_entry(
                    entry, data={CONF_MANAGEMENT_KEY: user_input[CONF_MANAGEMENT_KEY]}
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            errors["base"] = error_key or "invalid_key"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MANAGEMENT_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD,
                            autocomplete="off",
                        )
                    )
                }
            ),
            errors=errors,
        )


class OpenRouterActivityOptionsFlow(OptionsFlowWithConfigEntry):
    """Options flow: choose the stats window and refresh cadence."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            interval = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(
                data={
                    CONF_PERIOD: user_input[CONF_PERIOD],
                    CONF_SCAN_INTERVAL: max(60, min(interval, 86400)),
                }
            )

        current_period = self.config_entry.options.get(CONF_PERIOD, DEFAULT_PERIOD)
        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PERIOD, default=current_period): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(PERIOD_PRESETS.keys()),
                            translation_key="period",
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=60,
                            max=86400,
                            mode=selector.NumberSelectorMode.BOX,
                            unit="s",
                        )
                    ),
                }
            ),
        )


async def async_get_options_flow(
    config_entry: ConfigEntry,
) -> OptionsFlowWithConfigEntry:
    return OpenRouterActivityOptionsFlow(config_entry)