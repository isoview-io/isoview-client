# isoview-client

Python client for the [ISOview](https://isoview.io) energy forecasting API — demand, wind, solar, LMP, and natural gas forecasts across US ISOs, returned as dicts or pandas DataFrames.

## Installation

```bash
pip install isoview-client
```

Requires Python 3.10+. Installs `requests` and `pandas` as dependencies.

## Authentication

Sign up at [isoview.io](https://isoview.io) and grab your API key from the [Portal](https://isoview.io/portal/account?tab=api).

```python
from isoview import Client

client = Client("your-api-key")
```

## How It Works

The client dynamically builds methods from the API's OpenAPI spec at init time. This means it automatically stays in sync with the API — no client updates needed when new endpoints are added. The spec is cached locally for 1 hour.

```python
# See all available methods
dir(client)

# Get help on any method
help(client.get_regional_forecast)
```

## Quick Start

```python
from isoview import Client

client = Client("your-api-key")

# Get the latest PJM demand forecast as a dict
data = client.get_regional_forecast("pjm", "demand")

# Or get it directly as a pandas DataFrame
df = client.get_regional_forecast("pjm", "demand", as_df=True)
print(df.head())
```

Timeseries endpoints accept an `as_df=True` keyword argument to return a pandas DataFrame with a UTC DatetimeIndex and MultiIndex columns like `("pjm_total", "forecast")`. Without it, you get the raw API response as a dict.

## Examples

### Regions

Forecasts for geographic regions within an ISO — demand, wind, solar, outages, and population-weighted temperature.

```python
# See what regions are available
regions = client.list_regions("pjm", "demand")
# Returns a list of dicts: [{"id": "pjm_total", "name": "PJM Total", ...}, ...]

# Latest forecast as a DataFrame
df = client.get_regional_forecast("pjm", "demand", id="pjm_total", as_df=True)

# Stitched historical forecast — what did the day-ahead forecast
# look like at 10am each day?
df = client.get_region_continuous_forecast(
    "miso", "wind",
    start="2025-01-01T00:00:00Z",
    end="2025-06-01T00:00:00Z",
    latest_hour=10,
    days_ahead=1,
    as_df=True,
)

# Probabilistic ensemble forecast (multiple scenarios)
data = client.get_ensemble_forecast("pjm", "demand", id="pjm_total")

# Day-ahead backcast for model evaluation
data = client.get_region_day_ahead_backcast("pjm", "demand")

# Everything at once — demand, wind, solar, outages, temp, LMP
data = client.get_iso_summary("pjm")
```

### Plants

Generation forecasts for individual wind and solar facilities.

```python
# Browse plants in ERCOT
plants = client.list_plants("ercot", "wind")
print(plants[0]["name"], plants[0]["capacity_mw"], "MW")

# Get a forecast as a DataFrame
df = client.get_plant_forecast("ercot", "wind", id=str(plants[0]["id"]), as_df=True)
```

### Counties

County-level electricity demand forecasts, disaggregated from regional data.

```python
counties = client.list_counties("isone")
df = client.get_county_forecast("isone", id=counties[0]["id"], as_df=True)
```

### Gas

Natural gas price forecasts for major trading hubs.

```python
hubs = client.list_gas_hubs()
df = client.get_gas_price_forecast(id=hubs[0]["id"], as_df=True)
```

### LMP

Locational Marginal Price forecasts for electricity market nodes.

```python
nodes = client.list_lmp_nodes("pjm", "dalmp")
df = client.get_lmp_forecast("pjm", "dalmp", id=nodes[0]["id"], as_df=True)
```

## Working with Responses

### Timeseries (as dict)

All forecast, continuous, ensemble, backcast, and summary endpoints return a dict by default:

```python
data = client.get_regional_forecast("pjm", "demand")

data["model"]       # 'optimized'
data["created_at"]  # datetime — when the forecast was generated
data["units"]       # 'MW'
data["timezone"]    # 'America/New_York'
data["time_utc"]    # list of datetime objects
data["columns"]     # [["pjm_total", "forecast"], ...]
data["values"]      # [[1234.5, ...], ...]
```

### Timeseries (as DataFrame)

Pass `as_df=True` to any timeseries endpoint:

```python
df = client.get_regional_forecast("pjm", "demand", as_df=True)
```

The DataFrame has a `DatetimeIndex` and `MultiIndex` columns (e.g. `("pjm_total", "forecast")`).

### Metadata

List endpoints return plain dicts:

```python
regions = client.list_regions("pjm", "demand")
for r in regions:
    print(r["id"], r["name"], r["timezone"])

plants = client.list_plants("ercot", "solar")
for p in plants:
    print(p["name"], f"{p['capacity_mw']} MW", p["state"])
```

## Automatic Chunking

Requests spanning more than 365 days are automatically split into yearly chunks and merged:

```python
df = client.get_region_day_ahead_backcast(
    "pjm", "demand",
    start="2023-01-01T00:00:00Z",
    end="2025-06-01T00:00:00Z",
    as_df=True,
)
```

## Error Handling

The client raises `requests.HTTPError` on API errors (401, 403, 422, etc.):

```python
import requests

try:
    data = client.get_regional_forecast("pjm", "demand")
except requests.HTTPError as e:
    print(e.response.status_code, e.response.text)
```

## Links

- [ISOview Portal](https://isoview.io/portal) — manage your account and API key
- [API Documentation](https://isoview.io/docs) — full reference for all endpoints
