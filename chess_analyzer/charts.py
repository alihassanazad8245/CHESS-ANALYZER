"""Optional PNG chart export.

``matplotlib`` is **not** a required dependency. If it is not installed,
:func:`export_charts` returns an empty list and the CLI tells the user how to
enable the feature. Terminal charts always work regardless.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .models import PlayerReport
from .reports import safe_slug

logger = logging.getLogger(__name__)


def matplotlib_available() -> bool:
    """Return True when PNG export is possible in this environment."""
    try:  # pragma: no cover - depends on the environment
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def export_charts(report: PlayerReport, output_dir: Path) -> list[Path]:
    """Write PNG charts for ``report`` and return the created paths."""
    if not matplotlib_available():
        return []

    import matplotlib
    matplotlib.use("Agg")  # headless backend: no GUI window is ever opened
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_slug(report.username)
    created: list[Path] = []

    def save(fig, suffix: str) -> None:
        path = output_dir / f"{stem}-{suffix}.png"
        fig.tight_layout()
        fig.savefig(path, dpi=130)
        plt.close(fig)
        created.append(path)

    try:
        if report.rating_trend:
            dates = [d for d, _ in report.rating_trend]
            ratings = [v for _, v in report.rating_trend]
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.plot(dates, ratings, marker="o", color="#2e7d32")
            ax.set_ylabel("Rating")
            ax.set_title(f"Rating trend ({report.favorite_time_class.title()})")
            ax.tick_params(axis="x", rotation=45)
            ax.grid(alpha=0.3)
            save(fig, "rating-trend")

        if report.wins or report.losses or report.draws:
            fig, ax = plt.subplots(figsize=(5, 5))
            labels = ["Wins", "Losses", "Draws"]
            values = [report.wins, report.losses, report.draws]
            colors = ["#2e7d32", "#c62828", "#9e9e9e"]
            nonzero = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
            ax.pie([v for _, v, _ in nonzero], labels=[l for l, _, _ in nonzero],
                   colors=[c for _, _, c in nonzero], autopct="%1.0f%%", startangle=90)
            ax.set_title("Game results")
            save(fig, "results")

        top = (report.openings_as_white + report.openings_as_black)
        top = sorted(top, key=lambda o: o.games, reverse=True)[:8]
        if top:
            fig, ax = plt.subplots(figsize=(7, 4.5))
            rows = top[::-1]
            ax.barh([o.name for o in rows], [o.games for o in rows], color="#2e7d32")
            ax.set_xlabel("Games")
            ax.set_title("Most played openings")
            save(fig, "openings")

        if report.monthly_activity:
            months = [m for m, _ in report.monthly_activity]
            counts = [c for _, c in report.monthly_activity]
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(months, counts, color="#4caf50")
            ax.set_ylabel("Games played")
            ax.set_title("Activity per month")
            ax.tick_params(axis="x", rotation=45)
            save(fig, "activity")
    except Exception as exc:  # noqa: BLE001 - charts must never break a run
        logger.debug("Chart export failed: %s", exc)

    return created
