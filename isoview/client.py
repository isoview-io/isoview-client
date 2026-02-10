from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Iso = Literal["pjm", "miso", "spp", "ercot", "caiso", "nyiso", "isone"]
RegionMetric = Literal["demand", "wind", "solar", "outage", "poptemp"]
PlantType = Literal["wind", "solar"]
LmpType = Literal["dalmp", "rtlmp"]
ForecastModel = Literal["optimized", "iso", "normal"]
ContinuousModel = Literal["optimized", "iso"]
EnsembleModel = Literal["euro_ens", "euro_ec46", "euro_seas5"]

# ---------------------------------------------------------------------------
# Response dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TimeseriesResponse:
    """Standardized timeseries data returned by forecast, continuous, ensemble, backcast, and summary endpoints."""

    model: str | None
    created_at: datetime | None
    units: str
    timezone: str
    time_utc: list[datetime]
    time_local: list[datetime]
    columns: list[list[str]]
    values: list[list[float | None]]

    @property
    def df(self) -> pd.DataFrame:
        """Return the timeseries as a pandas DataFrame with a local-time DatetimeIndex and MultiIndex columns."""
        # Normalize to UTC first then convert to local tz so mixed offsets
        # (e.g. across DST boundaries in chunked responses) are handled correctly.
        index = pd.to_datetime(self.time_local, utc=True).tz_convert(self.timezone)
        index.name = "time"
        columns = pd.MultiIndex.from_tuples([tuple(c) for c in self.columns])
        # API returns values as columns × timestamps; transpose to rows × columns
        data = dict(enumerate(self.values))
        df = pd.DataFrame(data, index=index)
        df.columns = columns
        return df


@dataclass
class RegionResponse:
    """Metadata for a geographic forecast region within a Balancing Authority."""

    id: str
    name: str
    region_type: str
    ba: str
    timezone: str


@dataclass
class TimelineEntry:
    """A single milestone or significant event in a power plant's operational history."""

    date: datetime
    event: str


@dataclass
class PlantResponse:
    """Comprehensive metadata for a power generation plant."""

    id: str | int
    name: str
    plant_type: str
    capacity_mw: float
    ba: str
    operations_begin_date: str
    state: str
    latitude: float
    longitude: float
    status: str
    summary: str | None = None
    timeline: list[TimelineEntry] = field(default_factory=list)


@dataclass
class CountyResponse:
    """Metadata and geographic boundary for a US county."""

    id: str
    name: str
    state: str
    geojson: dict


@dataclass
class GasHubResponse:
    """Metadata for a natural gas trading hub or pricing region."""

    id: str
    name: str
    timezone: str
    point: dict


@dataclass
class LmpNodeResponse:
    """Metadata for a Locational Marginal Price (LMP) node or hub."""

    id: str
    name: str
    ba: str
    timezone: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dt(value: datetime | str | None) -> str | None:
    """Convert a datetime or string to an ISO-format string suitable for query params."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class Client:
    """Python client for the ISOview REST API.

    Args:
        api_key: Your ISOview API key.
        base_url: Base URL of the API (default ``https://api.isoview.io/v1``).
    """

    def __init__(self, api_key: str, base_url: str = "https://api.isoview.io/v1"):
        self._api_key = api_key
        self._base_url = base_url
        self._session = requests.Session()
        self._session.headers["X-API-Key"] = api_key

    # -- internal helpers ---------------------------------------------------

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        resp = self._session.get(f"{self._base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _parse_timeseries(data: dict) -> TimeseriesResponse:
        created_at_raw = data.get("created_at")
        return TimeseriesResponse(
            model=data.get("model"),
            created_at=datetime.fromisoformat(created_at_raw) if created_at_raw else None,
            units=data["units"],
            timezone=data["timezone"],
            time_utc=[datetime.fromisoformat(t) for t in data["time_utc"]],
            time_local=[datetime.fromisoformat(t) for t in data["time_local"]],
            columns=data["columns"],
            values=data["values"],
        )

    @staticmethod
    def _parse_region(data: dict) -> RegionResponse:
        return RegionResponse(
            id=data["id"],
            name=data["name"],
            region_type=data["region_type"],
            ba=data["ba"],
            timezone=data["timezone"],
        )

    @staticmethod
    def _parse_plant(data: dict) -> PlantResponse:
        timeline = [
            TimelineEntry(
                date=datetime.fromisoformat(e["date"]),
                event=e["event"],
            )
            for e in data.get("timeline", [])
        ]
        return PlantResponse(
            id=data["id"],
            name=data["name"],
            plant_type=data["plant_type"],
            capacity_mw=data["capacity_mw"],
            ba=data["ba"],
            operations_begin_date=data["operations_begin_date"],
            state=data["state"],
            latitude=data["latitude"],
            longitude=data["longitude"],
            status=data["status"],
            summary=data.get("summary"),
            timeline=timeline,
        )

    @staticmethod
    def _parse_county(data: dict) -> CountyResponse:
        return CountyResponse(
            id=data["id"],
            name=data["name"],
            state=data["state"],
            geojson=data["geojson"],
        )

    @staticmethod
    def _parse_gas_hub(data: dict) -> GasHubResponse:
        return GasHubResponse(
            id=data["id"],
            name=data["name"],
            timezone=data["timezone"],
            point=data["point"],
        )

    @staticmethod
    def _parse_lmp_node(data: dict) -> LmpNodeResponse:
        return LmpNodeResponse(
            id=data["id"],
            name=data["name"],
            ba=data["ba"],
            timezone=data["timezone"],
        )

    _MAX_RANGE = timedelta(days=365)

    def _chunked_timeseries(
        self,
        path: str,
        params: dict,
        start: datetime | str | None,
        end: datetime | str | None,
    ) -> TimeseriesResponse:
        """Fetch a timeseries, automatically splitting into 1-year chunks if the range exceeds the API limit."""

        def _clean(p: dict) -> dict:
            return {k: v for k, v in p.items() if v is not None}

        if start is not None and end is not None:
            start_dt = datetime.fromisoformat(start) if isinstance(start, str) else start
            end_dt = datetime.fromisoformat(end) if isinstance(end, str) else end

            if (end_dt - start_dt) > self._MAX_RANGE:
                chunks: list[TimeseriesResponse] = []
                chunk_start = start_dt
                while chunk_start < end_dt:
                    chunk_end = min(chunk_start + self._MAX_RANGE, end_dt)
                    chunk_params = {**params, "start": chunk_start.isoformat(), "end": chunk_end.isoformat()}
                    data = self._get(path, _clean(chunk_params))
                    chunks.append(self._parse_timeseries(data))
                    chunk_start = chunk_end
                return self._merge_timeseries(chunks)

        full_params = {**params, "start": _dt(start), "end": _dt(end)}
        data = self._get(path, _clean(full_params))
        return self._parse_timeseries(data)

    @staticmethod
    def _merge_timeseries(chunks: list[TimeseriesResponse]) -> TimeseriesResponse:
        """Merge multiple TimeseriesResponse chunks into one, deduplicating boundary timestamps."""
        first = chunks[0]
        all_time_utc: list[datetime] = list(first.time_utc)
        all_time_local: list[datetime] = list(first.time_local)
        all_values: list[list[float | None]] = [list(col) for col in first.values]

        for chunk in chunks[1:]:
            skip = 1 if chunk.time_utc and all_time_utc and chunk.time_utc[0] == all_time_utc[-1] else 0
            all_time_utc.extend(chunk.time_utc[skip:])
            all_time_local.extend(chunk.time_local[skip:])
            for i, col in enumerate(chunk.values):
                all_values[i].extend(col[skip:])

        return TimeseriesResponse(
            model=first.model,
            created_at=first.created_at,
            units=first.units,
            timezone=first.timezone,
            time_utc=all_time_utc,
            time_local=all_time_local,
            columns=first.columns,
            values=all_values,
        )

    # -----------------------------------------------------------------------
    # Region endpoints
    # -----------------------------------------------------------------------

    def list_regions(self, iso: Iso, metric: RegionMetric) -> list[RegionResponse]:
        """List all available regions for a forecast metric within an ISO.

        Returns metadata for each region including unique ID, name, region type,
        ISO, and local timezone.
        """
        data = self._get(f"/region/{iso}/{metric}/list")
        return [self._parse_region(item) for item in data]

    def get_regional_forecast(
        self,
        iso: Iso,
        metric: RegionMetric,
        *,
        model: ForecastModel | None = None,
        id: str | None = None,
        forecasted_by: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve the latest forecast timeseries for one or more regions.

        Args:
            iso: ISO identifier.
            metric: Forecast metric type.
            model: Weather model — 'optimized' (default), 'iso', or 'normal'.
            id: Specific region ID, or omit for all regions in the BA.
            forecasted_by: Only return forecasts created at or before this UTC timestamp.
        """
        params = {"model": model, "id": id, "forecasted_by": _dt(forecasted_by)}
        data = self._get(f"/region/{iso}/{metric}/forecast", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    def get_regional_continuous_forecast(
        self,
        iso: Iso,
        metric: RegionMetric,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        id: str | None = None,
        model: ContinuousModel | None = None,
        latest_hour: int | None = None,
        days_ahead: int | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a continuous "stitched" forecast for a region, ISO, and time period.

        Combines forecasts from consecutive model runs into a seamless timeseries.
        For each day, selects the forecast published at *latest_hour* (local time)
        with a lead time of *days_ahead* days.

        Args:
            iso: ISO identifier.
            metric: Forecast metric type.
            start: Start of the time range (inclusive, ISO 8601).
            end: End of the time range (inclusive, ISO 8601).
            id: Specific region ID, or omit for all regions.
            model: 'optimized' (default) or 'iso'.
            latest_hour: Local hour (0–23) for model-run selection.
            days_ahead: Forecast horizon in days (1–14).
        """
        params = {
            "id": id,
            "model": model,
            "latest_hour": latest_hour,
            "days_ahead": days_ahead,
        }
        return self._chunked_timeseries(f"/region/{iso}/{metric}/continuous", params, start, end)

    def get_regional_ensemble_forecast(
        self,
        iso: Iso,
        metric: RegionMetric,
        *,
        id: str,
        model: EnsembleModel | None = None,
        forecasted_by: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve probabilistic ensemble forecasts for a specific region.

        Returns multiple forecast scenarios (members) from probabilistic weather
        models representing the range of possible outcomes.

        Args:
            iso: ISO identifier.
            metric: Forecast metric type.
            id: Region ID (required for ensemble forecasts).
            model: Ensemble model — 'euro_ens' (default), 'euro_ec46', or 'euro_seas5'.
            forecasted_by: Only return forecasts created at or before this UTC timestamp.
        """
        params = {"id": id, "model": model, "forecasted_by": _dt(forecasted_by)}
        data = self._get(f"/region/{iso}/{metric}/ensemble", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    def get_regional_backcast(
        self,
        iso: Iso,
        metric: RegionMetric,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        id: str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a continuous historical series of day-ahead backcasted forecasts.

        Args:
            iso: ISO identifier.
            metric: Forecast metric type.
            start: Start of the time range (inclusive, ISO 8601).
            end: End of the time range (inclusive, ISO 8601).
            id: Specific region ID, or omit for all regions.
        """
        params = {"id": id}
        return self._chunked_timeseries(f"/region/{iso}/{metric}/backcast", params, start, end)

    def get_iso_summary(
        self,
        iso: Iso,
        *,
        as_of: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a comprehensive summary of all forecast metrics for an ISO.

        Returns the latest forecast and actual data for all active regions across
        demand, wind, solar, outages, population-weighted temperature, and day-ahead LMP.

        Args:
            iso: ISO identifier.
            as_of: Retrieve forecasts as they appeared at this UTC timestamp.
        """
        params = {"as_of": _dt(as_of)}
        data = self._get(f"/region/{iso}/summary", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    # -----------------------------------------------------------------------
    # Plant endpoints
    # -----------------------------------------------------------------------

    def list_plants(self, iso: Iso, type: PlantType) -> list[PlantResponse]:
        """List all active power generation plants of a specific type within an ISO.

        Returns metadata including capacity, coordinates, operational dates, and timeline.
        """
        data = self._get(f"/plant/{iso}/{type}/list")
        return [self._parse_plant(item) for item in data]

    def get_plant_forecast(
        self,
        iso: Iso,
        type: PlantType,
        *,
        model: ForecastModel | None = None,
        id: str | None = None,
        forecasted_by: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve generation forecast timeseries for wind or solar plants.

        Forecasts represent theoretical generation potential and do not account for
        curtailment, transmission constraints, or maintenance outages.

        Args:
            iso: ISO identifier.
            type: Plant type — 'wind' or 'solar'.
            model: Weather model — 'optimized' (default), 'iso', or 'normal'.
            id: Specific plant ID, or omit for all plants in the BA.
            forecasted_by: Only return forecasts created at or before this UTC timestamp.
        """
        params = {"model": model, "id": id, "forecasted_by": _dt(forecasted_by)}
        data = self._get(f"/plant/{iso}/{type}/forecast", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    def get_plant_continuous_forecast(
        self,
        iso: Iso,
        type: PlantType,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        id: str | None = None,
        model: ContinuousModel | None = None,
        latest_hour: int | None = None,
        days_ahead: int | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a continuous "stitched" generation forecast for wind or solar plants.

        Creates a seamless historical timeseries by combining forecasts from
        consecutive model runs.

        Args:
            iso: ISO identifier.
            type: Plant type — 'wind' or 'solar'.
            start: Start of the time range (inclusive, ISO 8601).
            end: End of the time range (inclusive, ISO 8601).
            id: Specific plant ID, or omit for all plants.
            model: 'optimized' (default) or 'iso'.
            latest_hour: Local hour (0–23) for model-run selection.
            days_ahead: Forecast horizon in days (1–14).
        """
        params = {
            "id": id,
            "model": model,
            "latest_hour": latest_hour,
            "days_ahead": days_ahead,
        }
        return self._chunked_timeseries(f"/plant/{iso}/{type}/continuous", params, start, end)

    # -----------------------------------------------------------------------
    # County endpoints
    # -----------------------------------------------------------------------

    def list_counties(self, iso: Iso) -> list[CountyResponse]:
        """List all US counties within a specific ISO.

        Returns metadata including county name, state, and GeoJSON boundary geometry.
        Counties can span multiple Balancing Authorities.
        """
        data = self._get(f"/county/{iso}/list")
        return [self._parse_county(item) for item in data]

    def get_county_forecast(
        self,
        iso: Iso,
        *,
        model: ForecastModel | None = None,
        id: str | None = None,
        forecasted_by: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve electricity demand forecast timeseries for one or more counties.

        County forecasts are derived by disaggregating regional forecasts using
        population weighting, historical load patterns, and local weather data.

        Args:
            iso: ISO identifier.
            model: Weather model — 'optimized' (default), 'iso', or 'normal'.
            id: Specific county ID, or omit for all counties in the ISO.
            forecasted_by: Only return forecasts created at or before this UTC timestamp.
        """
        params = {"model": model, "id": id, "forecasted_by": _dt(forecasted_by)}
        data = self._get(f"/county/{iso}/forecast", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    def get_county_continuous_forecast(
        self,
        iso: Iso,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        id: str | None = None,
        model: ContinuousModel | None = None,
        latest_hour: int | None = None,
        days_ahead: int | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a continuous "stitched" demand forecast for one or more counties.

        Args:
            iso: ISO identifier.
            start: Start of the time range (inclusive, ISO 8601).
            end: End of the time range (inclusive, ISO 8601).
            id: Specific county ID, or omit for all counties.
            model: 'optimized' (default) or 'iso'.
            latest_hour: Local hour (0–23) for model-run selection.
            days_ahead: Forecast horizon in days (1–14).
        """
        params = {
            "id": id,
            "model": model,
            "latest_hour": latest_hour,
            "days_ahead": days_ahead,
        }
        return self._chunked_timeseries(f"/county/{iso}/continuous", params, start, end)

    # -----------------------------------------------------------------------
    # Gas endpoints
    # -----------------------------------------------------------------------

    def list_gas_hubs(self) -> list[GasHubResponse]:
        """List all supported natural gas trading hubs and pricing regions.

        Returns metadata including hub identifier, name, geographic coordinates,
        and local timezone.
        """
        data = self._get("/gas/list")
        return [self._parse_gas_hub(item) for item in data]

    def get_gas_forecast(
        self,
        *,
        model: ForecastModel | None = None,
        id: str | None = None,
        forecasted_by: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve natural gas price forecasts for trading hubs.

        Returns daily natural gas price predictions.

        Args:
            model: Weather model — 'optimized' (default), 'iso', or 'normal'.
            id: Specific hub ID, or omit for all available hubs.
            forecasted_by: Only return forecasts created at or before this UTC timestamp.
        """
        params = {"model": model, "id": id, "forecasted_by": _dt(forecasted_by)}
        data = self._get("/gas/forecast", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    def get_gas_continuous_forecast(
        self,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        id: str | None = None,
        model: ContinuousModel | None = None,
        latest_hour: int | None = None,
        days_ahead: int | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a continuous "stitched" natural gas price forecast series.

        Args:
            start: Start of the time range (inclusive, ISO 8601).
            end: End of the time range (inclusive, ISO 8601).
            id: Specific hub ID, or omit for all hubs.
            model: 'optimized' (default) or 'iso'.
            latest_hour: Local hour (0–23) for model-run selection.
            days_ahead: Forecast horizon in days (1–14).
        """
        params = {
            "id": id,
            "model": model,
            "latest_hour": latest_hour,
            "days_ahead": days_ahead,
        }
        return self._chunked_timeseries("/gas/continuous", params, start, end)

    # -----------------------------------------------------------------------
    # LMP endpoints
    # -----------------------------------------------------------------------

    def list_lmp_nodes(self, iso: Iso, type: LmpType) -> list[LmpNodeResponse]:
        """List all available LMP nodes for a market type within an ISO.

        Returns metadata including node ID, name, Balancing Authority, and timezone.
        Currently only Day-Ahead LMP (dalmp) is supported.
        """
        data = self._get(f"/lmp/{iso}/{type}/list")
        return [self._parse_lmp_node(item) for item in data]

    def get_lmp_forecast(
        self,
        iso: Iso,
        type: LmpType,
        *,
        model: ForecastModel | None = None,
        id: str | None = None,
        forecasted_by: datetime | str | None = None,
    ) -> TimeseriesResponse:
        """Retrieve LMP forecast timeseries for specific nodes or hubs.

        Returns hourly electricity price forecasts based on demand, generation,
        and transmission models.

        Args:
            iso: ISO identifier.
            type: LMP market type — 'dalmp' or 'rtlmp'.
            model: Weather model — 'optimized' (default), 'iso', or 'normal'.
            id: Specific node ID, or omit for all nodes in the BA.
            forecasted_by: Only return forecasts created at or before this UTC timestamp.
        """
        params = {"model": model, "id": id, "forecasted_by": _dt(forecasted_by)}
        data = self._get(f"/lmp/{iso}/{type}/forecast", {k: v for k, v in params.items() if v is not None})
        return self._parse_timeseries(data)

    def get_lmp_continuous_forecast(
        self,
        iso: Iso,
        type: LmpType,
        *,
        start: datetime | str | None = None,
        end: datetime | str | None = None,
        id: str | None = None,
        model: ContinuousModel | None = None,
        latest_hour: int | None = None,
        days_ahead: int | None = None,
    ) -> TimeseriesResponse:
        """Retrieve a continuous "stitched" LMP forecast for backtesting trading strategies.

        Args:
            iso: ISO identifier.
            type: LMP market type — 'dalmp' or 'rtlmp'.
            start: Start of the time range (inclusive, ISO 8601).
            end: End of the time range (inclusive, ISO 8601).
            id: Specific node ID, or omit for all nodes.
            model: 'optimized' (default) or 'iso'.
            latest_hour: Local hour (0–23) for model-run selection.
            days_ahead: Forecast horizon in days (1–14).
        """
        params = {
            "id": id,
            "model": model,
            "latest_hour": latest_hour,
            "days_ahead": days_ahead,
        }
        return self._chunked_timeseries(f"/lmp/{iso}/{type}/continuous", params, start, end)
