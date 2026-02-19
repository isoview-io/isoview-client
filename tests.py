import os

import pandas as pd
import pytest

from isoview import (
    Client,
    CountyResponse,
    GasHubResponse,
    LmpNodeResponse,
    PlantResponse,
    RegionResponse,
    TimeseriesResponse,
)

API_KEY = os.environ.get("ISOVIEW_API_KEY")
if not API_KEY:
    pytest.exit("Set the ISOVIEW_API_KEY environment variable to run tests", returncode=1)


@pytest.fixture(scope="module")
def client():
    return Client(API_KEY)


# ---------------------------------------------------------------------------
# Region endpoints
# ---------------------------------------------------------------------------


class TestListRegions:
    def test_returns_list_of_region_responses(self, client: Client):
        regions = client.list_regions("pjm", "demand")
        assert isinstance(regions, list)
        assert len(regions) > 0
        r = regions[0]
        assert isinstance(r, RegionResponse)
        assert r.id
        assert r.name
        assert r.ba == "pjm"
        assert r.timezone

    def test_different_iso_and_metric(self, client: Client):
        regions = client.list_regions("ercot", "wind")
        assert len(regions) > 0
        assert all(r.ba == "ercot" for r in regions)


class TestRegionalForecast:
    def test_returns_timeseries(self, client: Client):
        ts = client.get_regional_forecast("pjm", "demand")
        assert isinstance(ts, TimeseriesResponse)
        assert ts.units
        assert ts.timezone
        assert len(ts.time_utc) > 0
        assert len(ts.time_local) == len(ts.time_utc)
        assert len(ts.values) == len(ts.columns)
        assert len(ts.columns) > 0

    def test_with_specific_region(self, client: Client):
        regions = client.list_regions("pjm", "demand")
        region_id = regions[0].id
        ts = client.get_regional_forecast("pjm", "demand", id=region_id)
        assert len(ts.columns) >= 1

    def test_to_df_utc(self, client: Client):
        ts = client.get_regional_forecast("pjm", "demand")
        df = ts.to_df()
        assert isinstance(df, pd.DataFrame)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "time"
        assert isinstance(df.columns, pd.MultiIndex)
        assert df.shape == (len(ts.time_utc), len(ts.columns))

    def test_to_df_local(self, client: Client):
        ts = client.get_regional_forecast("pjm", "demand")
        df = ts.to_df(utc=False)
        assert isinstance(df, pd.DataFrame)
        assert df.index.name == "time"
        assert df.shape == (len(ts.time_local), len(ts.columns))
        assert str(df.index.tz) == ts.timezone

    def test_repr(self, client: Client):
        ts = client.get_regional_forecast("pjm", "demand")
        r = repr(ts)
        assert "TimeseriesResponse(" in r
        assert "rows=" in r
        assert "cols=" in r
        assert ts.units in r


class TestRegionalContinuousForecast:
    def test_returns_timeseries(self, client: Client):
        ts = client.get_regional_continuous_forecast(
            "miso", "demand", latest_hour=10, days_ahead=1,
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0

    def test_returns_timeseries_with_date_range(self, client: Client):
        regions = client.list_regions("miso", "demand")
        region_id = regions[0].id
        ts = client.get_regional_continuous_forecast(
            "miso", "demand",
            id=region_id,
            start="2026-01-01T00:00:00Z",
            end="2026-02-01T00:00:00Z",
            latest_hour=10,
            days_ahead=1,
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0


class TestRegionalEnsembleForecast:
    def test_returns_timeseries(self, client: Client):
        regions = client.list_regions("pjm", "demand")
        region_id = regions[0].id
        ts = client.get_regional_ensemble_forecast(
            "pjm", "demand", id=region_id, model="euro_ens",
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.columns) > 1  # multiple ensemble members


class TestRegionalBackcast:
    def test_returns_timeseries(self, client: Client):
        ts = client.get_regional_backcast("pjm", "demand")
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0

    def test_chunked_request_over_one_year(self, client: Client):
        """Requests spanning > 1 year are automatically chunked into 1-year API calls."""
        regions = client.list_regions("pjm", "demand")
        region_id = regions[0].id
        ts = client.get_regional_backcast(
            "pjm", "demand",
            id=region_id,
            start="2026-01-01T00:00:00Z",
            end="2026-02-15T00:00:00Z",
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0
        # No duplicate timestamps
        assert len(ts.time_utc) == len(set(ts.time_utc))
        # DataFrame should work correctly
        df = ts.to_df()
        assert df.shape[0] == len(ts.time_utc)


class TestIsoSummary:
    def test_returns_timeseries(self, client: Client):
        ts = client.get_iso_summary("pjm")
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.columns) > 1  # multiple metrics in summary


# ---------------------------------------------------------------------------
# Plant endpoints
# ---------------------------------------------------------------------------


class TestListPlants:
    def test_returns_list_of_plant_responses(self, client: Client):
        plants = client.list_plants("ercot", "wind")
        assert isinstance(plants, list)
        assert len(plants) > 0
        p = plants[0]
        assert isinstance(p, PlantResponse)
        assert p.name
        assert p.capacity_mw > 0
        assert p.ba == "ercot"
        assert p.latitude
        assert p.longitude

class TestPlantForecast:
    def test_returns_timeseries(self, client: Client):
        plants = client.list_plants("ercot", "wind")
        plant_id = plants[0].id
        ts = client.get_plant_forecast("ercot", "wind", id=str(plant_id))
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.values) > 0


class TestPlantContinuousForecast:
    def test_returns_timeseries(self, client: Client):
        plants = client.list_plants("ercot", "wind")
        plant_id = plants[0].id
        ts = client.get_plant_continuous_forecast(
            "ercot", "wind", id=str(plant_id), latest_hour=10, days_ahead=1,
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0


class TestPlantBackcast:
    def test_returns_timeseries(self, client: Client):
        plants = client.list_plants("ercot", "wind")
        plant_id = plants[0].id
        ts = client.get_plant_backcast("ercot", "wind", id=str(plant_id))
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0


# ---------------------------------------------------------------------------
# County endpoints
# ---------------------------------------------------------------------------


class TestListCounties:
    def test_returns_list_of_county_responses(self, client: Client):
        counties = client.list_counties("pjm")
        assert isinstance(counties, list)
        assert len(counties) > 0
        c = counties[0]
        assert isinstance(c, CountyResponse)
        assert c.id
        assert c.name
        assert c.state
        assert isinstance(c.geojson, dict)


class TestCountyForecast:
    def test_returns_timeseries(self, client: Client):
        counties = client.list_counties("isone")
        county_id = counties[0].id
        ts = client.get_county_forecast("isone", id=county_id)
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.values) > 0


class TestCountyContinuousForecast:
    def test_returns_timeseries(self, client: Client):
        counties = client.list_counties("isone")
        county_id = counties[0].id
        ts = client.get_county_continuous_forecast(
            "isone", id=county_id, latest_hour=10, days_ahead=1,
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0


# ---------------------------------------------------------------------------
# Gas endpoints
# ---------------------------------------------------------------------------


class TestListGasHubs:
    def test_returns_list_of_gas_hub_responses(self, client: Client):
        hubs = client.list_gas_hubs()
        assert isinstance(hubs, list)
        assert len(hubs) > 0
        h = hubs[0]
        assert isinstance(h, GasHubResponse)
        assert h.id
        assert h.name
        assert h.timezone
        assert isinstance(h.point, dict)


class TestGasForecast:
    def test_returns_timeseries(self, client: Client):
        ts = client.get_gas_forecast()
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.values) > 0


class TestGasContinuousForecast:
    def test_returns_timeseries(self, client: Client):
        hubs = client.list_gas_hubs()
        hub_id = hubs[0].id
        ts = client.get_gas_continuous_forecast(
            id=hub_id, latest_hour=10, days_ahead=1,
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0


# ---------------------------------------------------------------------------
# LMP endpoints
# ---------------------------------------------------------------------------


class TestListLmpNodes:
    def test_returns_list_of_lmp_node_responses(self, client: Client):
        nodes = client.list_lmp_nodes("pjm", "dalmp")
        assert isinstance(nodes, list)
        assert len(nodes) > 0
        n = nodes[0]
        assert isinstance(n, LmpNodeResponse)
        assert n.id
        assert n.name
        assert n.ba == "pjm"
        assert n.timezone


class TestLmpForecast:
    def test_returns_timeseries(self, client: Client):
        nodes = client.list_lmp_nodes("pjm", "dalmp")
        node_id = nodes[0].id
        ts = client.get_lmp_forecast("pjm", "dalmp", id=node_id)
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.values) > 0


class TestLmpContinuousForecast:
    def test_returns_timeseries(self, client: Client):
        nodes = client.list_lmp_nodes("pjm", "dalmp")
        node_id = nodes[0].id
        ts = client.get_lmp_continuous_forecast(
            "pjm", "dalmp", id=node_id, latest_hour=10, days_ahead=1,
        )
        assert isinstance(ts, TimeseriesResponse)
        assert len(ts.time_utc) > 0
