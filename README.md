# Battery scheduling on German day-ahead prices

How much can a battery at a commercial site in Germany save, and how much of that survives when it
has to act on forecasts instead of perfect foresight? This project builds that up step by step with
`cvxpy` on public data.

| Phase | Content | Status |
|---|---|---|
| 0 | Project setup | ✅ |
| 1 | Public data via REST APIs, synthetic C&I site | ✅ |
| 2 | Day-ahead arbitrage baseline (LP vs. MILP, negative prices) | – |
| 3 | Behind-the-meter site: PV, load, peak-demand charges | – |
| 4 | Forecasts + rolling-horizon control, value of a probabilistic forecast | – |
| 5 | Write-up | – |

## Quickstart

```bash
uv sync
uv run fetch-data            # downloads 2023-01-01 .. tomorrow into data/raw (cached)
uv run pytest
uv run jupyter lab notebooks/01_data_exploration.ipynb
```

```python
from arbitrage.site import SiteConfig, build_site_timeseries

df = build_site_timeseries("2024-01-01", "2024-12-31", SiteConfig(pv_kwp=400))
# 15-min Europe/Berlin index, columns: price_eur_mwh, load_kw, pv_kw
```

## Data

| Input | Source | Notes |
|---|---|---|
| Day-ahead price DE-LU | [Energy-Charts API](https://api.energy-charts.info/) (Bundesnetzagentur / SMARD, CC BY 4.0) | Hourly until 30 Sep 2025, 15 min since the SDAC 15-minute go-live on 1 Oct 2025. Hourly prices are repeated over their four quarter hours (exact). |
| PV profile | Energy-Charts national solar generation ÷ installed DC capacity | Keeps the real weather and its correlation with prices. Scaled ×1.4 to a rooftop yield of ~900–1000 kWh/kWp (the national average is ~650–720 full-load hours). |
| Site load | BDEW standard load profile G0 via [`demandlib`](https://github.com/oemof/demandlib), Bavarian holidays | 1 GWh/yr by default, looked up by local wall-clock time across DST changes. |

Requests are fetched one calendar year at a time, throttled (the API rate-limits), and cached as
parquet. Completed years are reused forever, and the current year is refreshed after 12 h. If the API
is down, the stale cache is used with a warning.

## Layout

```
src/arbitrage/
  data.py      Energy-Charts client, caching, resolution handling
  site.py      SiteConfig, load and PV profiles, build_site_timeseries()
  plotting.py  shared figure style
  cli.py       fetch-data entry point
notebooks/01_data_exploration.ipynb
tests/
```

## Known limitations

- The synthetic load is a smooth standard profile without the noise and spikes of a real meter,
  and the national PV profile is smoother than a single rooftop. Both make forecasting easier than
  in reality.
- `pandas` is pinned below 3.1 because `demandlib` 0.2.2 turns warnings into errors and trips over
  new pandas deprecations.
