# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`isoview-client` is a Python client library for the ISOview energy forecasting API. It dynamically generates methods from the API's OpenAPI spec at init time, so there are no hardcoded endpoint definitions — all methods are built at runtime in `Client._build_methods()`.

## Commands

```bash
# Install in development mode
pip install -e .

# Run tests (requires a live API key)
ISOVIEW_API_KEY=your-key pytest tests.py -v

# Run a single test
ISOVIEW_API_KEY=your-key pytest tests.py::TestRegionalForecast::test_returns_dict -v

# Build package
python -m build
```

## Architecture

The entire client is two files:

- **`isoview/client.py`** — The `Client` class and all supporting logic. On init, it fetches `/openapi.json` (cached to `/tmp` for 1 hour via `_load_spec`), then `_build_methods` iterates over every path/operation in the spec to dynamically create Python methods via `_make_method`. Method names are derived from the OpenAPI `summary` field, converted to snake_case. Duplicate names are disambiguated using the first URL path segment.
- **`isoview/__init__.py`** — Re-exports `Client` and `clear_cache`.

Key runtime behaviors:
- **Dynamic method generation**: Methods don't exist in source code. They are closures created by `_make_method` and attached via `setattr`. Path parameters become positional args; query parameters become keyword args.
- **Timeseries detection**: `_is_timeseries_schema` checks if the response schema has a `time_utc` property. Timeseries methods accept `as_df=True` to return a pandas DataFrame with DatetimeIndex and MultiIndex columns.
- **Automatic chunking**: When `start`/`end` span >365 days, `_chunked_request` splits into yearly chunks, merges results via `_merge_timeseries_dicts`, and skips 422 errors from individual chunks.
- **Datetime parsing**: `_parse_datetimes` walks the response recursively using the OpenAPI schema to convert `date-time` formatted strings to Python `datetime` objects.

## Testing

Tests are integration tests that hit the live API — there are no mocks. Every test class covers a different endpoint category (regions, plants, counties, gas, LMP). The `client` fixture is module-scoped so the OpenAPI spec is fetched once per test run.
