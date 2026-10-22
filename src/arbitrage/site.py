"""Synthetic commercial site: load, rooftop PV and the price it faces.

There is no public metered data for a single C&I site, so the site is built
from public building blocks:

* load: BDEW standard load profile (via ``demandlib``) scaled to an annual
  consumption, with German public holidays of the site's federal state;
* PV: national German solar generation divided by installed capacity, i.e.
  a per-kWp profile that shares the weather (and therefore the price
  correlation) of the real market, scaled to a typical rooftop yield;
* price: the DE-LU day-ahead price on a 15-minute grid.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import holidays
import numpy as np
import pandas as pd
from demandlib import bdew

from arbitrage import data


@dataclass(frozen=True)
class SiteConfig:
    annual_consumption_kwh: float = 1_000_000.0
    load_profile: str = "g0"  # BDEW: g0 general commercial, g1 weekdays 8-18, ...
    pv_kwp: float = 400.0
    # The national profile yields ~650-720 full-load hours per year (2023-25):
    # it averages over all orientations, older modules and curtailment. A
    # south-facing rooftop in Bavaria reaches ~950 kWh/kWp (PVGIS), hence the
    # scale-up. The shape, and its correlation with prices, is kept.
    pv_yield_scale: float = 1.4
    state: str = "BY"  # federal state for public holidays


def commercial_load_kw(
    index: pd.DatetimeIndex, annual_kwh: float, profile: str = "g0", state: str = "BY"
) -> pd.Series:
    """Average power (kW) per interval of a scaled BDEW standard load profile.

    The SLPs are defined on local wall-clock time, so values are looked up by
    wall-clock time: the repeated hour when DST ends reuses the same values,
    the skipped hour in spring is dropped.
    """
    parts = []
    for year in sorted(set(index.year)):
        # demandlib calls warnings.simplefilter("error") internally; keep that
        # from leaking into the rest of the process.
        with warnings.catch_warnings():
            slp = bdew.ElecSlp(year, holidays=holidays.Germany(years=year, subdiv=state))
            scaled = slp.get_scaled_power_profiles({profile: annual_kwh})
        parts.append(scaled[profile])
    profile_kw = pd.concat(parts)
    profile_kw = profile_kw[~profile_kw.index.duplicated()]

    wall_clock = index.tz_localize(None)
    values = profile_kw.reindex(wall_clock).to_numpy()
    return pd.Series(values, index=index, name="load_kw")


def pv_kw_per_kwp(index: pd.DatetimeIndex) -> pd.Series:
    """PV output per installed kWp, from national generation and capacity."""
    start, end = index[0].date(), index[-1].date()
    solar_mw = data.fetch_public_power("Solar", start, end).reindex(index)

    capacity_gw = data.fetch_installed_solar_gw(rating="DC")
    # Linear interpolation between the capacity anchors, flat outside.
    anchors = capacity_gw.index.asi8
    capacity_mw = 1e3 * np.interp(index.asi8, anchors, capacity_gw.to_numpy())

    per_kwp = (solar_mw / capacity_mw).clip(lower=0.0, upper=1.0)
    return per_kwp.rename("pv_kw_per_kwp")


def build_site_timeseries(
    start: str | pd.Timestamp, end: str | pd.Timestamp, site: SiteConfig = SiteConfig()
) -> pd.DataFrame:
    """15-minute frame with ``price_eur_mwh``, ``load_kw`` and ``pv_kw``.

    ``start`` and ``end`` are local calendar dates, ``end`` inclusive.
    """
    index = data.quarter_hour_index(start, end)
    prices = data.to_quarter_hourly(data.fetch_day_ahead_prices(start, end))
    return pd.DataFrame(
        {
            "price_eur_mwh": prices.reindex(index),
            "load_kw": commercial_load_kw(
                index, site.annual_consumption_kwh, site.load_profile, site.state
            ),
            "pv_kw": site.pv_kwp * site.pv_yield_scale * pv_kw_per_kwp(index),
        },
        index=index,
    )
