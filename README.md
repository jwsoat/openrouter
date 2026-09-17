# OpenRouter Activity (HACS)

Home Assistant integration that surfaces your OpenRouter **usage analytics** as
sensors. On first setup it asks for a **management key** (not a regular API key)
and then polls the OpenRouter Analytics API on a schedule.

## What you get

For the selected time window (24h / 7d / 30d / 90d / 1y), one set of sensors per
Home Assistant device:

| Sensor | Example |
|---|---|
| `sensor.openrouter_total_spend` | `$42.50` |
| `sensor.openrouter_total_requests` | `1304` |
| `sensor.openrouter_token_volume` | `18,203,445` |
| `sensor.openrouter_cache_hit_rate` | `61.3 %` |
| `sensor.openrouter_blended_cost_per_million_tokens` | `$2.33` |
| `sensor.openrouter_top_model` | `openrouter/owl-alpha` |
| `sensor.openrouter_top_api_key` | `batch-pipeline` |
| `sensor.openrouter_top_app` | `claude-code` |
| `sensor.openrouter_last_updated` | timestamp |
| `sensor.openrouter_stats_window` | `2026-08-01 to 2026-08-31` |

The three "top …" sensors also carry a `_ranked` attribute with the full top-10
breakdown (name, spend, requests, tokens, cache hit rate) for dashboards and
automations.

### Multiple time windows at once
Because each config entry is independent, add the integration **more than once**,
giving each entry a different name and period (e.g. "Last 24h" and "Last 90d").
You then get the same set of sensors per window to compare.

## Requirements

- A Home Assistant version that supports `Selector` config/options flows
  (2023.6 or newer).
- An **OpenRouter management key**: https://openrouter.ai/settings/management-keys
  Regular inference keys return `403` from the Analytics API and will be
  rejected during setup.

## Install

Via HACS (custom repository):

1. HACS → ⋮ → **Custom repositories**
2. `https://github.com/jwsoat/openrouter`, category **Integration**
3. Click install, then reload Home Assistant.

Or manually: copy the `custom_components/openrouter_activity/` folder into your
HA `config/custom_components/` directory and restart.

## Set up

1. Settings → Devices & Services → **Add Integration** → **OpenRouter Activity**
2. Paste your management key, give the instance a name, pick a stats window.
3. Configure the affected entity under **Options** to change the window or the
   update interval (60 s – 24 h, default 5 min).

The key is stored in the entry's encrypted data (not the options), read-only
usage, and only ever sent to `openrouter.ai`.

## How stats are computed

Backed by [POST /api/v1/analytics/query](https://openrouter.ai/docs/api/api-reference/analytics/query-analytics-data):

- **Total spend** = `total_usage` (USD)
- **Token volume** = `tokens_total`
- **Cache hit rate** = `cache_hit_rate` × 100
- **Blended $/M tokens** = `total_usage / tokens_total × 1e6`
- **Top model / key / app** = the winner of the `model`, `api_key_id`, and `app`
  dimensions, each ordered by `total_usage` (top 10 kept in attributes).

The window is a rolling window ending at each refresh (`time_range` is always
set explicitly, as the API requires). Count metrics are parsed defensively
because OpenRouter may return them as strings.

## API notes / caveats

- Analytics queries **must** use a management key; a normal key gets `403`.
  If the stored key stops working, the integration triggers a **reauthentication**
  flow automatically.
- Response counts (`request_count`, `tokens_total`) can come back as strings —
  handled at read time.
- If `metadata.truncated` is true the top-N list is incomplete (only relevant
  beyond 10 rows per dimension, which is not expected).
- Spend values are a snapshot of your billing period accounts; treat them as
  indicative, not invoiced billing.

## Troubleshooting

- **"This key cannot access Analytics"** — you pasted a regular API key. Create a
  management key at openrouter.ai/settings/management-keys.
- **"Unknown error occurred" on setup (0.1.0)** — the flow couldn't report the
  underlying cause. Update to **0.1.1**, which converts this into a readable
  error and logs the real reason. If it still fails, check the ERROR line in
  Settings → System → Logs (or `config/home-assistant.log`) under
  `custom_components.openrouter_activity` and share it.
- **No values after setup** — if the account has no usage in the selected window
  the total sensors read zero and the top-* sensors read "unknown".
- Enable debug logging:
  ```yaml
  logger:
    default: warning
    logs:
      custom_components.openrouter_activity: debug
  ```

## License

MIT