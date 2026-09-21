"""The analysis engine.

Raw Chess.com JSON goes in, :mod:`.models` report objects come out. This
module performs no network I/O and no rendering, which keeps it easy to test.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Callable, Iterable, Sequence

from .chess_client import ChessClient
from .config import STANDARD_RULES
from .models import (
    OpeningStat,
    OpponentStat,
    PerformanceIndex,
    PlayerReport,
    RatingStat,
    StreakInfo,
)
from .utils import (
    classify_result,
    count_full_moves,
    days_since,
    describe_result,
    format_timestamp,
    human_number,
    month_key_of,
    opening_family,
    percentage,
    weekday_of,
    WEEKDAYS,
)

logger = logging.getLogger(__name__)

ProgressHook = Callable[[str], None]


def _noop(_message: str) -> None:
    """Default progress hook that discards messages."""


def _win_rate(wins: int, total: int) -> float:
    return round(percentage(wins, total), 1)


class Analyzer:
    """Coordinates API calls and turns the responses into a :class:`PlayerReport`."""

    def __init__(self, client: ChessClient, progress: ProgressHook | None = None) -> None:
        self.client = client
        self.progress = progress or _noop

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def analyze_player(
        self, username: str, months: int, time_class_filter: str = "all"
    ) -> PlayerReport:
        """Analyse one Chess.com player's profile, stats and recent games."""
        self.progress("Fetching player profile")
        profile = self.client.get_player(username)

        report = PlayerReport(
            username=profile.get("username", username),
            player_id=profile.get("player_id", 0),
            title=profile.get("title") or "",
            name=profile.get("name") or "",
            status=profile.get("status", "basic"),
            country_code=(profile.get("country") or "").rstrip("/").rsplit("/", 1)[-1] or "N/A",
            location=profile.get("location") or "",
            profile_url=profile.get("url", ""),
            joined=format_timestamp(profile.get("joined")),
            account_age_days=days_since(profile.get("joined")),
            last_online=format_timestamp(profile.get("last_online")),
            days_since_online=days_since(profile.get("last_online")),
            followers=profile.get("followers", 0),
            is_streamer=bool(profile.get("is_streamer")),
        )

        self.progress("Fetching rating statistics")
        stats = self.client.get_player_stats(report.username)
        report.ratings = self._rating_stats(stats)
        if report.ratings:
            report.favorite_time_class = max(
                report.ratings, key=lambda r: r.games
            ).time_class if any(r.games for r in report.ratings) else report.ratings[0].time_class

        self.progress("Fetching game archives")
        archive_urls = self.client.get_archive_urls(report.username)
        if not archive_urls:
            report.warnings.append("This player has no game archives to analyse.")
            report.performance = self._score_player(report)
            report.api_requests = self.client.requests_made
            return report

        selected = archive_urls[-months:]
        report.months_analyzed = len(selected)

        games: list[dict[str, Any]] = []
        for index, url in enumerate(selected, start=1):
            self.progress(f"Analyzing games ({index}/{len(selected)} months)")
            games.extend(self.client.get_archive_games(url))

        self._populate_from_games(report, games, time_class_filter)
        report.performance = self._score_player(report)
        report.api_requests = self.client.requests_made
        return report

    # ------------------------------------------------------------------ #
    # Rating stats (from /stats)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _rating_stats(stats: dict[str, Any]) -> list[RatingStat]:
        """Build one :class:`RatingStat` per game type Chess.com has data for."""
        results: list[RatingStat] = []
        for key, block in stats.items():
            if not key.startswith("chess_") or not isinstance(block, dict):
                continue
            time_class = key.split("_", 1)[1]
            record = block.get("record", {}) or {}
            wins, losses, draws = record.get("win", 0), record.get("loss", 0), record.get("draw", 0)
            total = wins + losses + draws
            best = block.get("best", {}) or {}
            results.append(RatingStat(
                time_class=time_class,
                current=(block.get("last") or {}).get("rating", 0),
                best=best.get("rating", 0),
                best_date=format_timestamp(best.get("date")),
                wins=wins, losses=losses, draws=draws,
                win_rate=_win_rate(wins, total),
                games=total,
            ))
        order = {"bullet": 0, "blitz": 1, "rapid": 2, "daily": 3}
        results.sort(key=lambda r: order.get(r.time_class, 99))
        return results

    # ------------------------------------------------------------------ #
    # Game-by-game aggregation
    # ------------------------------------------------------------------ #

    def _populate_from_games(
        self, report: PlayerReport, games: Sequence[dict[str, Any]], time_class_filter: str
    ) -> None:
        """Fill every game-derived field on ``report`` from the raw sample."""
        username_lower = report.username.lower()

        variant_skipped = 0
        rows: list[dict[str, Any]] = []
        for game in games:
            if game.get("rules", STANDARD_RULES) != STANDARD_RULES:
                variant_skipped += 1
                continue
            if time_class_filter != "all" and game.get("time_class") != time_class_filter:
                continue

            white, black = game.get("white") or {}, game.get("black") or {}
            is_white = white.get("username", "").lower() == username_lower
            mine, theirs = (white, black) if is_white else (black, white)
            if mine.get("username", "").lower() != username_lower:
                continue  # defensive: player not actually in this game

            rows.append({
                "is_white": is_white,
                "result_code": mine.get("result", ""),
                "rating_after": mine.get("rating", 0),
                "opponent": theirs.get("username", "unknown"),
                "time_class": game.get("time_class", "unknown"),
                "end_time": game.get("end_time", 0),
                "opening": opening_family(game.get("eco")),
                "moves": count_full_moves(game.get("pgn")),
                "accuracy": (game.get("accuracies") or {}).get("white" if is_white else "black"),
            })

        report.variant_games_skipped = variant_skipped
        report.games_analyzed = len(rows)
        if not rows:
            report.warnings.append(
                "No standard-chess games matched the selected time period or time class."
            )
            return

        rows.sort(key=lambda r: r["end_time"])
        timestamps = [r["end_time"] for r in rows if r["end_time"]]
        if timestamps:
            report.date_range = f"{format_timestamp(min(timestamps))} to {format_timestamp(max(timestamps))}"

        self._score_results(report, rows)
        self._color_split(report, rows)
        self._openings(report, rows)
        self._rating_trend(report, rows)
        self._activity(report, rows)
        self._streaks(report, rows)
        self._game_length(report, rows)
        self._accuracy(report, rows)
        self._opponents(report, rows)

        if len(archive_month_keys := {month_key_of(r["end_time"]) for r in rows if r["end_time"]}) < report.months_analyzed:
            report.warnings.append("Some analysed months had no standard-chess games.")
        if variant_skipped:
            report.warnings.append(
                f"Skipped {variant_skipped} variant game(s) (Chess960, bughouse, etc.)."
            )

    @staticmethod
    def _score_results(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        outcomes = Counter(classify_result(r["result_code"]) for r in rows)
        report.wins, report.losses, report.draws = outcomes["win"], outcomes["loss"], outcomes["draw"]
        report.win_rate = _win_rate(report.wins, len(rows))

        win_reasons: Counter[str] = Counter()
        loss_reasons: Counter[str] = Counter()
        for row in rows:
            code = row["result_code"]
            bucket = classify_result(code)
            if bucket == "win":
                win_reasons[describe_result(code)] += 1
            elif bucket == "loss":
                loss_reasons[describe_result(code)] += 1
        report.win_reasons = win_reasons.most_common(6)
        report.loss_reasons = loss_reasons.most_common(6)

    @staticmethod
    def _color_split(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        as_white = [r for r in rows if r["is_white"]]
        as_black = [r for r in rows if not r["is_white"]]
        report.white_games = len(as_white)
        report.black_games = len(as_black)
        report.white_win_rate = _win_rate(
            sum(1 for r in as_white if classify_result(r["result_code"]) == "win"), len(as_white)
        )
        report.black_win_rate = _win_rate(
            sum(1 for r in as_black if classify_result(r["result_code"]) == "win"), len(as_black)
        )
        split = Counter(r["time_class"] for r in rows)
        report.time_class_split = split.most_common()

    @staticmethod
    def _openings(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        def build(subset: list[dict[str, Any]]) -> list[OpeningStat]:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in subset:
                grouped.setdefault(row["opening"], []).append(row)
            stats = []
            for name, games in grouped.items():
                outcomes = Counter(classify_result(g["result_code"]) for g in games)
                stats.append(OpeningStat(
                    name=name, games=len(games),
                    wins=outcomes["win"], losses=outcomes["loss"], draws=outcomes["draw"],
                    win_rate=_win_rate(outcomes["win"], len(games)),
                    as_white=sum(1 for g in games if g["is_white"]),
                    as_black=sum(1 for g in games if not g["is_white"]),
                ))
            stats.sort(key=lambda s: s.games, reverse=True)
            return stats[:10]

        report.openings_as_white = build([r for r in rows if r["is_white"]])
        report.openings_as_black = build([r for r in rows if not r["is_white"]])

        all_openings = Counter(r["opening"] for r in rows)
        total = sum(all_openings.values())
        if total and len(all_openings) > 1:
            # Simpson diversity index, normalised to 0-100 (100 = maximally varied).
            simpson = 1 - sum((n / total) ** 2 for n in all_openings.values())
            max_possible = 1 - (1 / len(all_openings))
            report.opening_diversity = round(
                percentage(simpson, max_possible) if max_possible else 0.0, 1
            )

    @staticmethod
    def _rating_trend(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        favorite = report.favorite_time_class
        pool = [r for r in rows if r["time_class"] == favorite] or rows
        trend = [(format_timestamp(r["end_time"]), r["rating_after"]) for r in pool if r["rating_after"]]
        # Keep the chart readable: at most 20 evenly spaced points.
        if len(trend) > 20:
            step = len(trend) / 20
            trend = [trend[int(i * step)] for i in range(20)]
        report.rating_trend = trend

    @staticmethod
    def _activity(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        months: Counter[str] = Counter()
        weekdays: Counter[str] = Counter()
        for row in rows:
            if not row["end_time"]:
                continue
            months[month_key_of(row["end_time"])] += 1
            weekdays[weekday_of(row["end_time"])] += 1
        report.monthly_activity = sorted(months.items())[-12:]
        report.weekday_activity = [(day, weekdays.get(day, 0)) for day in WEEKDAYS]

    @staticmethod
    def _streaks(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        info = StreakInfo()
        current_type, current_len = "none", 0
        longest_win = longest_loss = 0
        for row in rows:
            outcome = classify_result(row["result_code"])
            if outcome == current_type:
                current_len += 1
            else:
                current_type, current_len = outcome, 1
            if current_type == "win":
                longest_win = max(longest_win, current_len)
            elif current_type == "loss":
                longest_loss = max(longest_loss, current_len)
        info.longest_win_streak = longest_win
        info.longest_loss_streak = longest_loss
        info.current_streak_type = current_type
        info.current_streak_length = current_len
        report.streaks = info

    @staticmethod
    def _game_length(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        lengths = [r["moves"] for r in rows if r["moves"] > 0]
        if lengths:
            report.avg_game_length = round(sum(lengths) / len(lengths), 1)
            report.longest_game = max(lengths)
            report.shortest_game = min(lengths)

    @staticmethod
    def _accuracy(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        values = [r["accuracy"] for r in rows if isinstance(r["accuracy"], (int, float))]
        if values:
            report.avg_accuracy = round(sum(values) / len(values), 1)
            report.accuracy_sample_size = len(values)

    @staticmethod
    def _opponents(report: PlayerReport, rows: list[dict[str, Any]]) -> None:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["opponent"], []).append(row)

        full_index: dict[str, OpponentStat] = {}
        for name, games in grouped.items():
            outcomes = Counter(classify_result(g["result_code"]) for g in games)
            full_index[name.lower()] = OpponentStat(
                username=name, games=len(games),
                wins=outcomes["win"], losses=outcomes["loss"], draws=outcomes["draw"],
            )
        report.opponent_index = full_index

        repeats = [stat for stat in full_index.values() if stat.games > 1]
        repeats.sort(key=lambda s: s.games, reverse=True)
        report.top_opponents = repeats[:8]

    # ------------------------------------------------------------------ #
    # Analyzer Metric: Performance Index (unofficial)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _score_player(report: PlayerReport) -> PerformanceIndex:
        """Compute the unofficial Performance Index.

        This is an *Analyzer Metric* produced by this tool from public game
        data. It is not a Chess.com rating and should not be treated as one.
        """
        breakdown: list[tuple[str, int, int]] = []
        notes: list[str] = []

        if not report.games_analyzed:
            return PerformanceIndex(total=0, grade="N/A", breakdown=[], notes=["No games available to score."])

        # Win rate (30)
        win_score = round(min(30.0, report.win_rate / 100 * 30))
        breakdown.append(("Win rate", int(win_score), 30))

        # Rating trend (20): compare first vs last third of the sampled trend.
        trend_score = 10
        values = [v for _, v in report.rating_trend]
        if len(values) >= 6:
            third = max(1, len(values) // 3)
            start_avg = sum(values[:third]) / third
            end_avg = sum(values[-third:]) / third
            delta = end_avg - start_avg
            if delta > 40:
                trend_score = 20
            elif delta > 10:
                trend_score = 16
            elif delta > -10:
                trend_score = 10
            else:
                trend_score = 4
                notes.append("Rating has trended downward over the sampled games.")
        breakdown.append(("Rating trend", trend_score, 20))

        # Consistency (15): fewer/shorter losing streaks scores higher.
        loss_streak = report.streaks.longest_loss_streak
        if loss_streak <= 2:
            consistency = 15
        elif loss_streak <= 4:
            consistency = 10
        elif loss_streak <= 7:
            consistency = 5
        else:
            consistency = 2
            notes.append(f"Longest losing streak in the sample was {loss_streak} games.")
        breakdown.append(("Consistency", consistency, 15))

        # Activity (15): games analysed relative to the sampled window.
        games_per_month = report.games_analyzed / max(1, report.months_analyzed)
        if games_per_month >= 40:
            activity = 15
        elif games_per_month >= 15:
            activity = 11
        elif games_per_month >= 5:
            activity = 7
        else:
            activity = 3
        breakdown.append(("Activity level", activity, 15))

        # Opening diversity (10)
        diversity = round(min(10.0, report.opening_diversity / 100 * 10))
        breakdown.append(("Opening diversity", int(diversity), 10))
        if report.opening_diversity and report.opening_diversity < 25:
            notes.append("Opening repertoire is narrow - most games use the same opening.")

        # Accuracy (10) - only scored if Chess.com has computed accuracies.
        if report.avg_accuracy is not None:
            acc_score = round(min(10.0, max(0.0, (report.avg_accuracy - 50) / 5)))
            breakdown.append(("Move accuracy", int(acc_score), 10))
        else:
            breakdown.append(("Move accuracy", 5, 10))
            notes.append("No Game Review accuracy data available for the sampled games.")

        total = sum(score for _, score, _ in breakdown)
        if total >= 85:
            grade = "A - Elite form"
        elif total >= 70:
            grade = "B - Strong"
        elif total >= 55:
            grade = "C - Solid"
        elif total >= 35:
            grade = "D - Inconsistent"
        else:
            grade = "E - Needs work"

        return PerformanceIndex(total=total, grade=grade, breakdown=breakdown, notes=notes[:5])


def compare_players(reports: Iterable[PlayerReport]) -> list[dict[str, Any]]:
    """Build headline comparison rows for two analysed players."""
    players = list(reports)
    if len(players) < 2:
        return []

    def best_rating(p: PlayerReport) -> int:
        return max((r.current for r in p.ratings), default=0)

    def lifetime_games(p: PlayerReport) -> int:
        return sum(r.games for r in p.ratings)

    metrics: list[tuple[str, Callable[[PlayerReport], Any]]] = [
        ("Best current rating", best_rating),
        ("Lifetime games played", lifetime_games),
        ("Games in this analysis", lambda p: p.games_analyzed),
        ("Win rate (sample)", lambda p: p.win_rate),
        ("Longest win streak", lambda p: p.streaks.longest_win_streak),
        ("Performance Index", lambda p: p.performance.total),
        ("Followers", lambda p: p.followers),
    ]

    rows: list[dict[str, Any]] = []
    for label, getter in metrics:
        values = [getter(player) for player in players]
        best = max(values)
        winner = "Tie" if values.count(best) > 1 else players[values.index(best)].username
        rows.append({"metric": label, "values": values, "winner": winner})

    favorites = [p.favorite_time_class for p in players]
    rows.append({"metric": "Favorite time class", "values": favorites, "winner": "-"})
    return rows


def ratings_comparison(one: PlayerReport, two: PlayerReport) -> list[dict[str, Any]]:
    """Build a per-time-class rating comparison using each player's lifetime stats.

    Uses the authoritative totals from Chess.com's ``/stats`` endpoint (not the
    sampled game window), so "games played" here reflects real career totals.
    """
    order = {"bullet": 0, "blitz": 1, "rapid": 2, "daily": 3}
    one_by_class = {r.time_class: r for r in one.ratings}
    two_by_class = {r.time_class: r for r in two.ratings}
    classes = sorted(set(one_by_class) | set(two_by_class), key=lambda c: order.get(c, 99))

    rows = []
    for time_class in classes:
        r1, r2 = one_by_class.get(time_class), two_by_class.get(time_class)
        rows.append({
            "time_class": time_class,
            "one": {"current": r1.current, "games": r1.games, "win_rate": r1.win_rate} if r1 else None,
            "two": {"current": r2.current, "games": r2.games, "win_rate": r2.win_rate} if r2 else None,
        })
    return rows


def head_to_head(one: PlayerReport, two: PlayerReport) -> "OpponentStat | None":
    """Return ``one``'s record against ``two`` from the analysed game sample.

    Looks in both players' opponent indexes (a game between them shows up in
    each side's own monthly archive), so a hit on either side is enough. When
    only ``two``'s side has the record, it is inverted to describe ``one``'s
    perspective. Returns ``None`` if the sample shows no games between them.
    """
    key_two, key_one = two.username.lower(), one.username.lower()

    direct = one.opponent_index.get(key_two)
    if direct:
        return direct

    inverse = two.opponent_index.get(key_one)
    if inverse:
        return OpponentStat(
            username=two.username, games=inverse.games,
            wins=inverse.losses, losses=inverse.wins, draws=inverse.draws,
        )
    return None
