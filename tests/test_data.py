import numpy as np
import pandas as pd
import pytest
import requests

from arbitrage import data, site

TZ = data.TZ


def test_quarter_hour_index_handles_dst():
    assert len(data.quarter_hour_index("2025-03-30", "2025-03-30")) == 92
    assert len(data.quarter_hour_index("2025-10-26", "2025-10-26")) == 100
    assert len(data.quarter_hour_index("2025-06-01", "2025-06-02")) == 192


def test_to_quarter_hourly_repeats_hourly_prices():
    index = pd.date_range("2024-05-01", periods=3, freq="h", tz=TZ)
    hourly = pd.Series([10.0, np.nan, -5.0], index=index, name="price")

    out = data.to_quarter_hourly(hourly)

    assert len(out) == 12
    assert (out.iloc[0:4] == 10.0).all()
    assert out.iloc[4:8].isna().all()  # a missing price is not papered over
    assert (out.iloc[8:12] == -5.0).all()


def test_to_quarter_hourly_across_15min_switch():
    hourly = pd.Series(
        [1.0, 2.0], index=pd.date_range("2025-09-30 22:00", periods=2, freq="h", tz=TZ)
    )
    quarterly = pd.Series(
        [3.0, 4.0, 5.0, 6.0],
        index=pd.date_range("2025-10-01 00:00", periods=4, freq="15min", tz=TZ),
    )

    out = data.to_quarter_hourly(pd.concat([hourly, quarterly]))

    assert out.index.freqstr == "15min"
    assert out.tolist() == [1.0] * 4 + [2.0] * 4 + [3.0, 4.0, 5.0, 6.0]


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE_DIR", tmp_path)
    return tmp_path


def _fake_year(year: pd.Period) -> pd.Series:
    index = data.quarter_hour_index(f"{year.year}-01-01", f"{year.year}-12-31")
    return pd.Series(float(year.year), index=index, name="x")


def test_cached_yearly_filters_range_and_caches(cache_dir):
    calls = []

    def fetch(year):
        calls.append(year.year)
        return _fake_year(year)

    out = data._cached_yearly("x", "2023-12-31", "2024-01-01", fetch)

    assert calls == [2023, 2024]
    assert len(out) == 2 * 96
    assert out.index[0] == pd.Timestamp("2023-12-31", tz=TZ)
    assert out.index[-1] == pd.Timestamp("2024-01-01 23:45", tz=TZ)

    data._cached_yearly("x", "2023-12-31", "2024-01-01", fetch)
    assert calls == [2023, 2024]  # second call served from parquet


def test_cached_yearly_falls_back_to_stale_cache(cache_dir):
    day = f"{pd.Timestamp.now(TZ).year}-01-01"
    data._cached_yearly("x", day, day, _fake_year)

    def offline(year):
        raise requests.ConnectionError

    with pytest.warns(UserWarning, match="stale cache"):
        out = data._cached_yearly("x", day, day, offline, max_age=pd.Timedelta(0))
    assert len(out) == 96


def test_load_profile_matches_annual_consumption():
    index = data.quarter_hour_index("2024-01-01", "2024-12-31")

    load = site.commercial_load_kw(index, annual_kwh=1_000_000)

    assert load.notna().all()
    # Off by at most the DST hour that is skipped in spring and repeated in autumn.
    assert load.sum() / 4 == pytest.approx(1_000_000, rel=1e-3)
