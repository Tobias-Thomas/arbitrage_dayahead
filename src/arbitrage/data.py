"""Public market data from the Energy-Charts API (Fraunhofer ISE).

All series are returned on a tz-aware ``Europe/Berlin`` index. Downloads are
fetched one calendar year per request and cached as parquet under
``data/raw`` so repeated runs work offline.

API docs: https://api.energy-charts.info/
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path

import pandas as pd
import requests

API_URL = "https://api.energy-charts.info"
TZ = "Europe/Berlin"
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"

# SDAC (and with it the DE-LU day-ahead auction) moved from 60 to 15 minute
# products for delivery from this date on.
DA_15MIN_START = pd.Timestamp("2025-10-01", tz=TZ)


# Energy-Charts rate-limits aggressively; keep requests sparse and back off.
_MIN_REQUEST_INTERVAL_S = 2.0
_last_request = 0.0


def _get(endpoint: str, params: dict, retries: int = 5) -> dict:
    global _last_request
    for attempt in range(retries):
        time.sleep(max(0.0, _last_request + _MIN_REQUEST_INTERVAL_S - time.monotonic()))
        _last_request = time.monotonic()
        try:
            resp = requests.get(f"{API_URL}/{endpoint}", params=params, timeout=120)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            if attempt == retries - 1:
                raise
            response = getattr(err, "response", None)
            retry_after = response.headers.get("Retry-After") if response is not None else None
            wait = float(retry_after) if retry_after and retry_after.isdigit() else 10 * 2**attempt
            time.sleep(wait)
    raise AssertionError("unreachable")


def _is_final(year: pd.Period) -> bool:
    # Give the source a few days to publish late corrections.
    return year.end_time.tz_localize(TZ) + pd.Timedelta(days=7) < pd.Timestamp.now(TZ)


def _cached_yearly(
    name: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    fetch_year,
    use_cache: bool = True,
    max_age: pd.Timedelta = pd.Timedelta(hours=12),
) -> pd.Series:
    """Assemble a series from per-year chunks, using the parquet cache.

    ``start`` and ``end`` are local calendar dates; ``end`` is inclusive.
    Chunks of finished years are reused forever, the current year's chunk
    is refetched once it is older than ``max_age``.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    chunks = []
    for year in pd.period_range(start.to_period("Y"), end.to_period("Y"), freq="Y"):
        path = CACHE_DIR / f"{name}_{year}.parquet"
        fresh = path.exists() and (
            _is_final(year)
            or pd.Timestamp.now() - pd.Timestamp(path.stat().st_mtime, unit="s") < max_age
        )
        if use_cache and fresh:
            chunk = pd.read_parquet(path).iloc[:, 0]
        else:
            try:
                chunk = fetch_year(year)
            except requests.RequestException:
                if not path.exists():
                    raise
                warnings.warn(f"Energy-Charts unavailable, using stale cache {path.name}")
                chunk = pd.read_parquet(path).iloc[:, 0]
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                chunk.to_frame().to_parquet(path)
        chunks.append(chunk)

    series = pd.concat(chunks).sort_index()
    series = series[~series.index.duplicated(keep="last")]
    local_dates = series.index.tz_localize(None).normalize()
    return series[(local_dates >= start.normalize()) & (local_dates <= end.normalize())]


def _year_params(year: pd.Period) -> dict:
    return {"start": f"{year.year}-01-01", "end": f"{year.year}-12-31"}


def _to_series(unix_seconds: list[int], values: list, name: str) -> pd.Series:
    index = pd.to_datetime(unix_seconds, unit="s", utc=True).tz_convert(TZ)
    return pd.Series(values, index=index, name=name, dtype="float64")


def fetch_day_ahead_prices(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    bidding_zone: str = "DE-LU",
    use_cache: bool = True,
) -> pd.Series:
    """Day-ahead auction prices in EUR/MWh at native resolution.

    The series is hourly before :data:`DA_15MIN_START` and quarter-hourly
    after it; use :func:`to_quarter_hourly` to put it on a uniform grid.
    """

    def fetch_year(year: pd.Period) -> pd.Series:
        data = _get("price", {"bzn": bidding_zone, **_year_params(year)})
        return _to_series(data["unix_seconds"], data["price"], "price_eur_mwh")

    return _cached_yearly(f"price_{bidding_zone}", start, end, fetch_year, use_cache)


def fetch_public_power(
    production_type: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    country: str = "de",
    use_cache: bool = True,
) -> pd.Series:
    """National generation/load in MW (15 min), e.g. ``"Solar"`` or ``"Load"``."""

    def fetch_year(year: pd.Period) -> pd.Series:
        data = _get("public_power", {"country": country, **_year_params(year)})
        by_name = {p["name"]: p["data"] for p in data["production_types"]}
        if production_type not in by_name:
            raise KeyError(f"{production_type!r} not in {sorted(by_name)}")
        return _to_series(data["unix_seconds"], by_name[production_type], "mw")

    slug = production_type.lower().replace(" ", "_")
    return _cached_yearly(f"power_{country}_{slug}", start, end, fetch_year, use_cache)


def fetch_installed_solar_gw(country: str = "de", rating: str = "DC") -> pd.Series:
    """Installed solar capacity in GW, one value per year.

    ``rating`` is ``"DC"`` (module peak power, i.e. kWp) or ``"AC"``
    (inverter power).

    Values for completed years are taken as year-end capacity; the current
    year's value is the capacity as of the source's last update. The index
    holds the timestamps these values refer to.
    """
    path = CACHE_DIR / f"installed_solar_{country}_{rating}.parquet"
    age = pd.Timestamp.now() - pd.Timestamp(path.stat().st_mtime, unit="s") if path.exists() else None
    if age is not None and age < pd.Timedelta(days=7):
        return pd.read_parquet(path).iloc[:, 0]
    try:
        data = _get(
            "installed_power",
            {"country": country, "time_step": "yearly", "installation_decommission": "false"},
        )
    except requests.RequestException:
        if age is None:
            raise
        warnings.warn(f"Energy-Charts unavailable, using stale cache {path.name}")
        return pd.read_parquet(path).iloc[:, 0]
    values = next(p["data"] for p in data["production_types"] if p["name"] == f"Solar {rating}")
    now = pd.Timestamp.now(TZ).normalize()
    stamps, gws = [], []
    for year, gw in zip(data["time"], values):
        if gw is None:
            continue
        year_end = pd.Timestamp(f"{year}-12-31", tz=TZ)
        stamps.append(min(year_end, now))
        gws.append(gw)
    series = pd.Series(gws, index=pd.DatetimeIndex(stamps), name="solar_installed_gw")
    path.parent.mkdir(parents=True, exist_ok=True)
    series.to_frame().to_parquet(path)
    return series


def quarter_hour_index(start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DatetimeIndex:
    """15-minute index covering local calendar days ``start`` to ``end`` (inclusive)."""
    first = pd.Timestamp(start).tz_localize(TZ)
    last = (pd.Timestamp(end) + pd.Timedelta(days=1)).tz_localize(TZ)
    return pd.date_range(first, last, freq="15min", inclusive="left")


def to_quarter_hourly(series: pd.Series) -> pd.Series:
    """Upsample a mixed hourly/15-min price series to a uniform 15-min grid.

    Hourly prices apply to all four quarter hours of their delivery hour, so
    forward-filling within the hour is exact, not an approximation.
    """
    last = series.index[-1]
    if last < DA_15MIN_START:
        last += pd.Timedelta(minutes=45)
    index = pd.date_range(series.index[0], last, freq="15min")
    # method="ffill" only fills labels missing from the source, so genuinely
    # missing prices (NaN) stay missing.
    return series.reindex(index, method="ffill", limit=3)
