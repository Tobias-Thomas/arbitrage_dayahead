"""Shared matplotlib styling so all figures in the project look alike."""

import matplotlib as mpl

# Fixed categorical order; a series keeps its color across all figures.
COLORS = {
    "price": "#2a78d6",
    "pv": "#eb6834",
    "load": "#1baf7a",
    "battery": "#6250d6",
}
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e4e3df"


def use_style() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 110,
            "figure.figsize": (10, 4),
            "figure.facecolor": "#fcfcfb",
            "axes.facecolor": "#fcfcfb",
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK_MUTED,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.titlelocation": "left",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "y",
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "lines.linewidth": 1.5,
            "xtick.color": INK_MUTED,
            "ytick.color": INK_MUTED,
            "legend.frameon": False,
        }
    )
