"""Typed result containers produced by the analysis engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import __version__


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class RatingStat:
    """Current and best rating for one time class (bullet/blitz/rapid/daily)."""

    time_class: str
    current: int = 0
    best: int = 0
    best_date: str = "N/A"
    wins: int = 0
    losses: int = 0
    draws: int = 0
    win_rate: float = 0.0
    games: int = 0


@dataclass(slots=True)
class OpeningStat:
    """One opening family and how the player performed with it."""

    name: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    win_rate: float = 0.0
    as_white: int = 0
    as_black: int = 0


@dataclass(slots=True)
class OpponentStat:
    """Head-to-head record against one recurring opponent."""

    username: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


@dataclass(slots=True)
class StreakInfo:
    """Longest and current streaks across the analysed sample."""

    longest_win_streak: int = 0
    longest_loss_streak: int = 0
    current_streak_type: str = "none"
    current_streak_length: int = 0


@dataclass(slots=True)
class PerformanceIndex:
    """Unofficial 0-100 performance estimate.

    This is an *Analyzer Metric* computed by this tool from public game
    data. Chess.com does not publish any such score.
    """

    total: int = 0
    grade: str = "N/A"
    breakdown: list[tuple[str, int, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlayerReport:
    """Complete analysis of one Chess.com player."""

    username: str
    player_id: int = 0
    title: str = ""
    name: str = ""
    status: str = "basic"
    country_code: str = "N/A"
    location: str = ""
    profile_url: str = ""
    joined: str = "N/A"
    account_age_days: int | None = None
    last_online: str = "N/A"
    days_since_online: int | None = None
    followers: int = 0
    is_streamer: bool = False

    ratings: list[RatingStat] = field(default_factory=list)
    favorite_time_class: str = "N/A"

    months_analyzed: int = 0
    date_range: str = "N/A"
    games_analyzed: int = 0
    variant_games_skipped: int = 0

    wins: int = 0
    losses: int = 0
    draws: int = 0
    win_rate: float = 0.0

    white_games: int = 0
    white_win_rate: float = 0.0
    black_games: int = 0
    black_win_rate: float = 0.0

    win_reasons: list[tuple[str, int]] = field(default_factory=list)
    loss_reasons: list[tuple[str, int]] = field(default_factory=list)

    openings_as_white: list[OpeningStat] = field(default_factory=list)
    openings_as_black: list[OpeningStat] = field(default_factory=list)
    opening_diversity: float = 0.0

    rating_trend: list[tuple[str, int]] = field(default_factory=list)
    monthly_activity: list[tuple[str, int]] = field(default_factory=list)
    weekday_activity: list[tuple[str, int]] = field(default_factory=list)
    time_class_split: list[tuple[str, int]] = field(default_factory=list)

    streaks: StreakInfo = field(default_factory=StreakInfo)

    avg_game_length: float = 0.0
    longest_game: int = 0
    shortest_game: int = 0

    avg_accuracy: float | None = None
    accuracy_sample_size: int = 0

    top_opponents: list[OpponentStat] = field(default_factory=list)
    opponent_index: dict[str, OpponentStat] = field(default_factory=dict)

    performance: PerformanceIndex = field(default_factory=PerformanceIndex)

    warnings: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=_now)
    analyzer_version: str = __version__
    api_requests: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise the report to plain JSON-compatible types."""
        data = asdict(self)
        data["report_type"] = "player"
        return data
