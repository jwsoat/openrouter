"""Constants for the OpenRouter Activity integration."""

DOMAIN = "openrouter_activity"
DOMAIN_LABEL = "OpenRouter Activity"

CONF_MANAGEMENT_KEY = "management_key"
CONF_PERIOD = "period"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_NAME = "OpenRouter"
DEFAULT_PERIOD = "30d"
DEFAULT_SCAN_INTERVAL = 300  # seconds

# How many breakdown rows to keep for each "top ..." dimension.
TOP_N = 10

API_BASE = "https://openrouter.ai/api/v1"
API_QUERY = f"{API_BASE}/analytics/query"
API_META = f"{API_BASE}/analytics/meta"

# Period presets: key (stored) -> number of days the window covers (rolling).
PERIOD_PRESETS: dict[str, int] = {
    "24h": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "1y": 365,
}

# Headline metrics requested for the aggregate row AND every breakdown.
METRICS = [
    "total_usage",      # total spend in USD
    "request_count",    # number of requests (may be returned as a string)
    "tokens_total",     # native token count (may be returned as a string)
    "cache_hit_rate",   # 0..1 ratio
]

# Dimensions we show a "top N by spend" breakdown for, in display order.
TOP_DIMENSIONS = ["model", "api_key_id", "app"]