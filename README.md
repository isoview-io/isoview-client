# isoview

Python client for the [ISOview](https://isoview.io) energy forecasting API — demand, wind, solar, LMP, and natural gas forecasts across US ISOs, returned as pandas DataFrames.

## Installation

```bash
pip install isoview
```

Requires Python 3.10+. Installs `requests` and `pandas` as dependencies.

## Authentication

Sign up at [isoview.io](https://isoview.io) and grab your API key from the [Portal](https://isoview.io/portal/account?tab=api).

```python
from isoview import Client

client = Client("your-api-key")
```

## Quick Start

```python
from isoview import Client

client = Client("your-api-key")

# Get the latest PJM demand forecast
ts = client.get_regional_forecast("pjm", "demand")

# Convert to a pandas DataFrame
df = ts.df
print(df.head())
```

Every forecast method returns a `TimeseriesResponse` with a `.df` property that gives you a ready-to-use DataFrame — DatetimeIndex in local time, MultiIndex columns like `("pjm_total", "forecast")`.

## Examples

### Regions

Forecasts for geographic regions within an ISO — demand, wind, solar, outages, and population-weighted temperature.

```python
# See what regions are available
regions = client.list_regions("pjm", "demand")

# Latest forecast for a specific region
ts = client.get_regional_forecast("pjm", "demand", id="pjm_total")

# Stitched historical forecast — what did the day-ahead forecast
# look like at 10am each day?
ts = client.get_regional_continuous_forecast(
    "miso", "wind",
    start="2025-01-01T00:00:00Z",
    end="2025-06-01T00:00:00Z",
    latest_hour=10,
    days_ahead=1,
)

# Probabilistic ensemble forecast (multiple scenarios)
ts = client.get_regional_ensemble_forecast("pjm", "demand", id="pjm_total")

# Day-ahead backcast for model evaluation
ts = client.get_regional_backcast("pjm", "demand")

# Everything at once — demand, wind, solar, outages, temp, LMP
ts = client.get_iso_summary("pjm")
```

### Plants

Generation forecasts for individual wind and solar facilities.

```python
# Browse plants in ERCOT
plants = client.list_plants("ercot", "wind")
print(plants[0].name, plants[0].capacity_mw, "MW")

# Get a forecast
ts = client.get_plant_forecast("ercot", "wind", id=str(plants[0].id))
df = ts.df
```

### Counties

County-level electricity demand forecasts, disaggregated from regional data.

```python
counties = client.list_counties("isone")
ts = client.get_county_forecast("isone", id=counties[0].id)
```

### Gas

Natural gas price forecasts for major trading hubs.

```python
hubs = client.list_gas_hubs()
ts = client.get_gas_forecast(id=hubs[0].id)
```

### LMP

Locational Marginal Price forecasts for electricity market nodes.

```python
nodes = client.list_lmp_nodes("pjm", "dalmp")
ts = client.get_lmp_forecast("pjm", "dalmp", id=nodes[0].id)
```

## Working with Responses

### Timeseries

All forecast, continuous, ensemble, backcast, and summary endpoints return a `TimeseriesResponse`:

```python
ts = client.get_regional_forecast("pjm", "demand")

ts.model       # 'optimized'
ts.created_at  # datetime — when the forecast was generated
ts.units       # 'MW'
ts.timezone    # 'America/New_York'

# The good stuff — a pandas DataFrame
df = ts.df
```

The DataFrame has a `DatetimeIndex` in local time and `MultiIndex` columns (e.g. `("pjm_total", "forecast")`).

### Metadata

List endpoints return typed objects you can inspect directly:

```python
regions = client.list_regions("pjm", "demand")
for r in regions:
    print(r.id, r.name, r.timezone)

plants = client.list_plants("ercot", "solar")
for p in plants:
    print(p.name, f"{p.capacity_mw} MW", p.state)
```

## Supported ISOs

| Code | Name |
|------|------|
| `pjm` | PJM Interconnection |
| `miso` | Midcontinent ISO |
| `spp` | Southwest Power Pool |
| `ercot` | Electric Reliability Council of Texas |
| `caiso` | California ISO |
| `nyiso` | New York ISO |
| `isone` | ISO New England |

## Error Handling

The client raises `requests.HTTPError` on API errors (401, 403, 422, etc.):

```python
import requests

try:
    ts = client.get_regional_forecast("pjm", "demand")
except requests.HTTPError as e:
    print(e.response.status_code, e.response.text)
```

## Links

- [ISOview Portal](https://isoview.io/portal) — manage your account and API key
- [API Documentation](https://isoview.io/docs) — full reference for all endpoints
