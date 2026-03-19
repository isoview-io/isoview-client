from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

_CACHE_TTL = 3600  # 1 hour


def _load_spec(base_url: str, session: requests.Session) -> dict:
    cache_key = hashlib.md5(base_url.encode()).hexdigest()
    cache_path = os.path.join(tempfile.gettempdir(), f"isoview_spec_{cache_key}.json")

    if os.path.exists(cache_path):
        age = time.time() - os.path.getmtime(cache_path)
        if age < _CACHE_TTL:
            with open(cache_path) as f:
                return json.load(f)

    resp = session.get(f"{base_url}/openapi.json")
    resp.raise_for_status()
    spec = resp.json()
    with open(cache_path, "w") as f:
        json.dump(spec, f)
    return spec


def clear_cache() -> None:
    """Delete all cached OpenAPI spec files, forcing a fresh fetch on next Client init."""
    import glob as _glob
    for path in _glob.glob(os.path.join(tempfile.gettempdir(), "isoview_spec_*.json")):
        os.remove(path)


def _to_snake_case(summary: str) -> str:
    return re.sub(r"\s+", "_", summary.strip().lower())


def _dt(value: datetime | str | None) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _resolve_ref(schema: dict, schemas: dict) -> dict:
    ref = schema.get("$ref")
    if ref:
        name = ref.split("/")[-1]
        return schemas.get(name, {})
    return schema


def _resolve_response_schema(operation: dict, schemas: dict) -> dict:
    resp_200 = operation.get("responses", {}).get("200", {})
    content = resp_200.get("content", {}).get("application/json", {})
    return _resolve_ref(content.get("schema", {}), schemas)


def _is_timeseries_schema(schema: dict) -> bool:
    props = schema.get("properties", {})
    return "time_utc" in props


def _parse_datetimes(data, schema: dict, schemas: dict):
    if isinstance(data, list) and schema.get("type") == "array":
        item_schema = _resolve_ref(schema.get("items", {}), schemas)
        return [_parse_datetimes(item, item_schema, schemas) for item in data]

    if isinstance(data, dict):
        props = schema.get("properties", {})
        for key, value in data.items():
            if key not in props:
                continue
            prop_schema = _resolve_ref(props[key], schemas)
            if prop_schema.get("format") == "date-time" and isinstance(value, str):
                data[key] = datetime.fromisoformat(value)
            elif prop_schema.get("type") == "array":
                item_schema = _resolve_ref(prop_schema.get("items", {}), schemas)
                if item_schema.get("format") == "date-time":
                    data[key] = [datetime.fromisoformat(v) for v in value if isinstance(v, str)]
                else:
                    data[key] = _parse_datetimes(value, prop_schema, schemas)
            elif prop_schema.get("type") == "object":
                data[key] = _parse_datetimes(value, prop_schema, schemas)
    return data


_DF_KEYS = frozenset({"time_utc", "time_local", "values", "columns"})


def _timeseries_to_df(data: dict, utc: bool = True) -> pd.DataFrame:
    if utc:
        index = pd.DatetimeIndex(data["time_utc"], name="time")
    else:
        index = pd.to_datetime(data["time_local"], utc=True).tz_convert(data["timezone"])
        index.name = "time"
    columns = pd.MultiIndex.from_tuples([tuple(c) for c in data["columns"]])
    vals = dict(enumerate(data["values"]))
    df = pd.DataFrame(vals, index=index)
    df.columns = columns
    df.attrs = {k: v for k, v in data.items() if k not in _DF_KEYS}
    return df


def _merge_timeseries_dicts(chunks: list[dict]) -> dict:
    first = chunks[0]
    merged = {**first}
    merged["time_utc"] = list(first["time_utc"])
    merged["time_local"] = list(first["time_local"])
    merged["values"] = [list(col) for col in first["values"]]

    for chunk in chunks[1:]:
        skip = 1 if chunk["time_utc"] and merged["time_utc"] and chunk["time_utc"][0] == merged["time_utc"][-1] else 0
        merged["time_utc"].extend(chunk["time_utc"][skip:])
        merged["time_local"].extend(chunk["time_local"][skip:])
        for i, col in enumerate(chunk["values"]):
            merged["values"][i].extend(col[skip:])
    return merged


def _build_docstring(operation: dict, path_params: list, query_params: list, is_timeseries: bool) -> str:
    lines = [operation.get("description", operation.get("summary", ""))]
    lines.append("")

    if path_params or query_params or is_timeseries:
        lines.append("Args:")
        for p in path_params:
            desc = p.get("schema", {}).get("description", p.get("description", ""))
            lines.append(f"    {p['name']}: {desc}" if desc else f"    {p['name']}")
        for p in query_params:
            desc = p.get("schema", {}).get("description", p.get("description", ""))
            lines.append(f"    {p['name']}: {desc}" if desc else f"    {p['name']}")
        if is_timeseries:
            lines.append("    as_df: If True, return a pandas DataFrame instead of a dict.")

    return "\n".join(lines)


_DATETIME_PARAM_NAMES = frozenset({"start", "end", "forecasted_by", "as_of"})


class Client:
    """Python client for the ISOview REST API.

    Dynamically builds methods from the OpenAPI spec at ``{base_url}/openapi.json``.

    Args:
        api_key: Your ISOview API key.
        base_url: Base URL of the API (default ``https://api.isoview.io/v1``).
    """

    _MAX_RANGE = timedelta(days=365)

    def __init__(self, api_key: str, base_url: str = "https://api.isoview.io/v1"):
        self._api_key = api_key
        self._base_url = base_url
        self._session = requests.Session()
        self._session.headers["X-API-Key"] = api_key
        self._method_names: list[str] = []

        spec = _load_spec(base_url, self._session)
        self._build_methods(spec)

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        resp = self._session.get(f"{self._base_url}{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _build_methods(self, spec: dict) -> None:
        schemas = spec.get("components", {}).get("schemas", {})

        # First pass: collect all raw names to detect duplicates
        operations = []
        name_counts: dict[str, int] = {}
        for path, path_item in spec["paths"].items():
            for http_method, operation in path_item.items():
                if http_method not in ("get", "post", "put", "patch", "delete"):
                    continue
                raw_name = _to_snake_case(operation["summary"])
                name_counts[raw_name] = name_counts.get(raw_name, 0) + 1
                operations.append((path, http_method, operation, raw_name))

        # Second pass: disambiguate duplicates using the first path segment
        for path, http_method, operation, raw_name in operations:
            if name_counts[raw_name] > 1:
                # Use first path segment as prefix: /region/... -> "region", /plant/... -> "plant"
                prefix = path.strip("/").split("/")[0]
                if prefix and prefix not in raw_name:
                    parts = raw_name.split("_", 1)
                    name = f"{parts[0]}_{prefix}_{parts[1]}" if len(parts) > 1 else f"{raw_name}_{prefix}"
                else:
                    name = raw_name
            else:
                name = raw_name

            # Normalize: replace hyphens with underscores for valid Python identifiers
            name = name.replace("-", "_")

            params = operation.get("parameters", [])
            path_params = [p for p in params if p["in"] == "path"]
            query_params = [p for p in params if p["in"] == "query"]

            resp_schema = _resolve_response_schema(operation, schemas)
            is_timeseries = _is_timeseries_schema(resp_schema)
            is_list = resp_schema.get("type") == "array"
            has_chunking = any(p["name"] in ("start", "end") for p in query_params)

            method = self._make_method(
                path, path_params, query_params,
                is_timeseries, is_list, has_chunking,
                resp_schema, schemas,
            )
            method.__name__ = name
            method.__qualname__ = f"Client.{name}"
            method.__doc__ = _build_docstring(operation, path_params, query_params, is_timeseries)
            setattr(self, name, method)
            self._method_names.append(name)

    def _make_method(self, path_template, path_params, query_params,
                     is_timeseries, is_list, has_chunking, resp_schema, schemas):

        def method(*args, **kwargs):
            # Map positional args to path params
            path_values = {}
            for i, pp in enumerate(path_params):
                if i < len(args):
                    path_values[pp["name"]] = args[i]
                elif pp["name"] in kwargs:
                    path_values[pp["name"]] = kwargs.pop(pp["name"])

            as_df = kwargs.pop("as_df", False) if is_timeseries else False

            # Build query params
            qp = {}
            for p in query_params:
                val = kwargs.get(p["name"])
                if val is not None:
                    if p.get("schema", {}).get("format") == "date-time" or p["name"] in _DATETIME_PARAM_NAMES:
                        val = _dt(val)
                    qp[p["name"]] = val

            url_path = path_template.format(**path_values)

            if has_chunking and kwargs.get("start") is not None and kwargs.get("end") is not None:
                return self._chunked_request(url_path, qp, kwargs["start"], kwargs["end"],
                                             as_df, resp_schema, schemas)

            data = self._get(url_path, qp if qp else None)
            data = _parse_datetimes(data, resp_schema, schemas)

            if as_df and is_timeseries:
                return _timeseries_to_df(data)
            return data

        return method

    def _chunked_request(self, path, params, start, end, as_df, resp_schema, schemas):
        start_val = _dt(start)
        end_val = _dt(end)
        start_dt = datetime.fromisoformat(start_val) if isinstance(start_val, str) else start_val
        end_dt = datetime.fromisoformat(end_val) if isinstance(end_val, str) else end_val

        if (end_dt - start_dt) > self._MAX_RANGE:
            chunks = []
            chunk_start = start_dt
            while chunk_start < end_dt:
                chunk_end = min(chunk_start + self._MAX_RANGE, end_dt)
                chunk_params = {**params, "start": chunk_start.isoformat(), "end": chunk_end.isoformat()}
                clean = {k: v for k, v in chunk_params.items() if v is not None}
                try:
                    data = self._get(path, clean)
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 422:
                        chunk_start = chunk_end
                        continue
                    raise
                data = _parse_datetimes(data, resp_schema, schemas)
                chunks.append(data)
                chunk_start = chunk_end
            if not chunks:
                raise ValueError(f"No data available for the requested time range ({start_dt} to {end_dt})")
            merged = _merge_timeseries_dicts(chunks)
            if as_df:
                return _timeseries_to_df(merged)
            return merged

        clean = {k: v for k, v in params.items() if v is not None}
        data = self._get(path, clean if clean else None)
        data = _parse_datetimes(data, resp_schema, schemas)
        if as_df:
            return _timeseries_to_df(data)
        return data

    def __dir__(self):
        return sorted(set(super().__dir__() + self._method_names))

    def __repr__(self):
        return f"Client(base_url={self._base_url!r}, methods={len(self._method_names)})"
