"""``uv run fetch-data``: download and cache all public inputs."""

import argparse

import pandas as pd

from arbitrage import site


def fetch_data() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    tomorrow = (pd.Timestamp.now(site.data.TZ) + pd.Timedelta(days=1)).date()
    parser.add_argument("--start", default="2023-01-01", help="first local date")
    parser.add_argument("--end", default=str(tomorrow), help="last local date (inclusive)")
    args = parser.parse_args()

    df = site.build_site_timeseries(args.start, args.end)
    print(f"{len(df):,} quarter hours from {df.index[0]} to {df.index[-1]}")
    print(f"missing values:\n{df.isna().sum().to_string()}")
    print(f"cached in {site.data.CACHE_DIR}")
