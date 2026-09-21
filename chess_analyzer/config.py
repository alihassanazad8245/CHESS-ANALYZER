"""Centralised configuration.

Chess.com's Published-Data API is fully open: no API key, no signup, no
token. The only courtesy Chess.com asks for is a descriptive ``User-Agent``
so they can contact you if something goes wrong - never an email address
baked into public source, so this points at the project repository instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import __repo__, __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"

API_BASE_URL = "https://api.chess.com/pub"
USER_AGENT = f"chess-analyzer/{__version__} (+{__repo__})"

#: Network timeout (connect, read) in seconds.
REQUEST_TIMEOUT: tuple[float, float] = (5.0, 20.0)

#: Default number of most-recent monthly archives sampled per player.
DEFAULT_MONTHS = 3

#: Hard ceiling so "--months all" can never trigger runaway API calls.
MAX_MONTHS = 24

#: Chess rule variants worth analysing as "standard" chess.
STANDARD_RULES = "chess"

TIME_CLASSES = ("bullet", "blitz", "rapid", "daily")


@dataclass(slots=True)
class Settings:
    """Runtime settings for a single analyzer session."""

    months: int = DEFAULT_MONTHS
    time_class: str = "all"
    verbose: bool = False
    no_color: bool = False
    report_dir: Path = DEFAULT_REPORT_DIR

    def __post_init__(self) -> None:
        if self.months <= 0:
            self.months = MAX_MONTHS
        self.months = min(self.months, MAX_MONTHS)
