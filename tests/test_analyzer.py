"""Test suite for Chess Analyzer.

Everything here is offline: the HTTP layer is exercised through a fake
``requests.Response`` so the tests never touch the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chess_analyzer.analyzer import Analyzer, compare_players
from chess_analyzer.chess_client import ChessClient
from chess_analyzer.errors import InvalidInputError, NotFoundError, RateLimitError
from chess_analyzer.models import PlayerReport
from chess_analyzer.reports import SUPPORTED_FORMATS, safe_slug, write_report
from chess_analyzer.utils import (
    classify_result,
    count_full_moves,
    describe_result,
    is_valid_username,
    opening_family,
    opening_moves_preview,
    opening_name_from_eco_url,
    parse_pgn_headers,
    percentage,
    validate_username,
)

# --------------------------------------------------------------------------- #
# Username validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["hikaru", "Magnus_Carlsen", "abc", "a" * 25, "the-king-99"])
def test_valid_usernames_accepted(name: str) -> None:
    assert is_valid_username(name)


@pytest.mark.parametrize("name", ["", "ab", "a" * 26, "has space", "weird!char"])
def test_invalid_usernames_rejected(name: str) -> None:
    assert not is_valid_username(name)


def test_validate_username_strips_at_sign() -> None:
    assert validate_username("@hikaru") == "hikaru"


def test_validate_username_raises_for_bad_input() -> None:
    with pytest.raises(InvalidInputError):
        validate_username("no")


# --------------------------------------------------------------------------- #
# Result classification
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("code,expected", [
    ("win", "win"),
    ("checkmated", "loss"),
    ("resigned", "loss"),
    ("timeout", "loss"),
    ("agreed", "draw"),
    ("stalemate", "draw"),
    ("repetition", "draw"),
    ("kingofthehill", "loss"),
])
def test_classify_result(code: str, expected: str) -> None:
    assert classify_result(code) == expected


def test_describe_result_known_and_unknown() -> None:
    assert describe_result("checkmated") == "Checkmated"
    assert describe_result("weird_code") == "Weird Code"


def test_percentage_handles_zero_division() -> None:
    assert percentage(5, 0) == 0.0
    assert percentage(1, 4) == 25.0


# --------------------------------------------------------------------------- #
# Opening name extraction
# --------------------------------------------------------------------------- #


def test_opening_name_from_eco_url_strips_variation() -> None:
    url = "https://www.chess.com/openings/Italian-Game-Classical-4...-Nf6"
    assert opening_name_from_eco_url(url) == "Italian Game Classical"


def test_opening_name_from_eco_url_handles_missing() -> None:
    assert opening_name_from_eco_url(None) == "Unknown opening"
    assert opening_name_from_eco_url("") == "Unknown opening"


def test_opening_family_truncates_to_max_words() -> None:
    url = "https://www.chess.com/openings/Queens-Gambit-Declined-Exchange-Variation"
    assert opening_family(url, max_words=2) == "Queens Gambit"


# --------------------------------------------------------------------------- #
# PGN parsing
# --------------------------------------------------------------------------- #

SAMPLE_PGN = (
    '[Event "Live Chess"]\n[Site "Chess.com"]\n[Date "2026.01.15"]\n'
    '[White "hikaru"]\n[Black "magnuscarlsen"]\n[Result "1-0"]\n'
    '[ECO "C50"]\n[TimeControl "180"]\n[Termination "hikaru won by checkmate"]\n\n'
    '1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 1-0'
)


def test_parse_pgn_headers_extracts_tags() -> None:
    headers = parse_pgn_headers(SAMPLE_PGN)
    assert headers["White"] == "hikaru"
    assert headers["ECO"] == "C50"
    assert headers["Termination"] == "hikaru won by checkmate"


def test_parse_pgn_headers_handles_empty() -> None:
    assert parse_pgn_headers(None) == {}
    assert parse_pgn_headers("") == {}


def test_count_full_moves() -> None:
    assert count_full_moves(SAMPLE_PGN) == 6
    assert count_full_moves(None) == 0
    assert count_full_moves("") == 0


def test_opening_moves_preview_strips_numbers_and_result() -> None:
    preview = opening_moves_preview(SAMPLE_PGN, plies=4)
    assert preview == "e4 e5 Nf3 Nc6"


# --------------------------------------------------------------------------- #
# HTTP error mapping
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _client_returning(response: FakeResponse) -> ChessClient:
    client = ChessClient()
    client.session.get = lambda *a, **k: response  # type: ignore[assignment]
    return client


def test_404_maps_to_not_found_error() -> None:
    client = _client_returning(FakeResponse(404))
    with pytest.raises(NotFoundError):
        client.get_player("nobody-here")


def test_429_maps_to_rate_limit_error() -> None:
    client = _client_returning(FakeResponse(429))
    with pytest.raises(RateLimitError):
        client.get_player("someone")


def test_player_stats_404_degrades_to_empty_dict() -> None:
    client = _client_returning(FakeResponse(404))
    assert client.get_player_stats("someone") == {}


def test_archive_urls_404_degrades_to_empty_list() -> None:
    client = _client_returning(FakeResponse(404))
    assert client.get_archive_urls("someone") == []


# --------------------------------------------------------------------------- #
# Analysis logic
# --------------------------------------------------------------------------- #


def _game(white_user, black_user, white_result, black_result, *, eco=None, end_time=1700000000,
          pgn=None, time_class="rapid", rules="chess", white_rating=1500, black_rating=1500,
          accuracies=None):
    return {
        "white": {"username": white_user, "result": white_result, "rating": white_rating},
        "black": {"username": black_user, "result": black_result, "rating": black_rating},
        "time_class": time_class,
        "rules": rules,
        "end_time": end_time,
        "eco": eco or "https://www.chess.com/openings/Italian-Game",
        "pgn": pgn or SAMPLE_PGN,
        "accuracies": accuracies,
    }


def _base_report() -> PlayerReport:
    return PlayerReport(username="tester", favorite_time_class="rapid")


def test_populate_from_games_computes_basic_record() -> None:
    games = [
        _game("tester", "opp1", "win", "checkmated", end_time=1700000000),
        _game("opp2", "tester", "resigned", "win", end_time=1700003600),
        _game("tester", "opp1", "agreed", "agreed", end_time=1700007200),
    ]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "all")  # type: ignore[arg-type]

    assert report.games_analyzed == 3
    assert report.wins == 2
    assert report.losses == 0
    assert report.draws == 1
    assert report.white_games == 2
    assert report.black_games == 1


def test_populate_from_games_skips_variants() -> None:
    games = [
        _game("tester", "opp1", "win", "checkmated", rules="chess960"),
        _game("tester", "opp1", "win", "checkmated", rules="chess"),
    ]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "all")  # type: ignore[arg-type]
    assert report.games_analyzed == 1
    assert report.variant_games_skipped == 1


def test_populate_from_games_filters_by_time_class() -> None:
    games = [
        _game("tester", "opp1", "win", "checkmated", time_class="blitz"),
        _game("tester", "opp1", "win", "checkmated", time_class="rapid"),
    ]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "blitz")  # type: ignore[arg-type]
    assert report.games_analyzed == 1
    assert report.time_class_split == [("blitz", 1)]


def test_streaks_detects_longest_win_streak() -> None:
    games = [
        _game("tester", "o", "win", "checkmated", end_time=1700000000 + i)
        for i in range(4)
    ] + [_game("tester", "o", "resigned", "win", end_time=1700000100)]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "all")  # type: ignore[arg-type]
    assert report.streaks.longest_win_streak == 4
    assert report.streaks.current_streak_type == "loss"


def test_opponents_only_includes_repeats() -> None:
    games = [
        _game("tester", "rival", "win", "checkmated", end_time=1700000000),
        _game("rival", "tester", "resigned", "win", end_time=1700000100),
        _game("tester", "stranger", "win", "checkmated", end_time=1700000200),
    ]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "all")  # type: ignore[arg-type]
    names = [o.username for o in report.top_opponents]
    assert "rival" in names
    assert "stranger" not in names


def test_accuracy_averages_available_games() -> None:
    games = [
        _game("tester", "o", "win", "checkmated", accuracies={"white": 90.0, "black": 80.0}),
        _game("tester", "o", "win", "checkmated", accuracies=None),
    ]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "all")  # type: ignore[arg-type]
    assert report.avg_accuracy == 90.0
    assert report.accuracy_sample_size == 1


def test_score_player_handles_no_games() -> None:
    report = _base_report()
    score = Analyzer._score_player(report)
    assert score.total == 0
    assert score.grade == "N/A"


def test_score_player_bounded_and_graded() -> None:
    games = [_game("tester", "o", "win", "checkmated", end_time=1700000000 + i * 100) for i in range(20)]
    report = _base_report()
    Analyzer(client=None)._populate_from_games(report, games, "all")  # type: ignore[arg-type]
    report.months_analyzed = 1
    score = Analyzer._score_player(report)
    assert 0 <= score.total <= 100
    assert sum(m for _, _, m in score.breakdown) == 100


def test_compare_players_picks_a_leader() -> None:
    one = PlayerReport(username="alice", followers=100, win_rate=60.0)
    two = PlayerReport(username="bob", followers=10, win_rate=40.0)
    rows = compare_players([one, two])
    win_rate_row = next(r for r in rows if r["metric"] == "Win rate (sample)")
    assert win_rate_row["winner"] == "alice"
    assert compare_players([one]) == []


def test_head_to_head_finds_direct_record() -> None:
    from chess_analyzer.analyzer import head_to_head
    from chess_analyzer.models import OpponentStat

    one = PlayerReport(username="alice")
    two = PlayerReport(username="bob")
    one.opponent_index = {"bob": OpponentStat(username="bob", games=3, wins=2, losses=1, draws=0)}
    record = head_to_head(one, two)
    assert record is not None and record.wins == 2 and record.losses == 1


def test_head_to_head_inverts_from_other_side() -> None:
    from chess_analyzer.analyzer import head_to_head
    from chess_analyzer.models import OpponentStat

    one = PlayerReport(username="alice")
    two = PlayerReport(username="bob")
    # Only bob's report has the record: bob beat alice twice.
    two.opponent_index = {"alice": OpponentStat(username="alice", games=2, wins=2, losses=0, draws=0)}
    record = head_to_head(one, two)
    assert record is not None
    assert record.wins == 0 and record.losses == 2  # from alice's perspective, she lost both


def test_head_to_head_returns_none_when_never_played() -> None:
    from chess_analyzer.analyzer import head_to_head

    one = PlayerReport(username="alice")
    two = PlayerReport(username="bob")
    assert head_to_head(one, two) is None


def test_ratings_comparison_handles_missing_time_classes() -> None:
    from chess_analyzer.analyzer import ratings_comparison
    from chess_analyzer.models import RatingStat

    one = PlayerReport(username="alice", ratings=[RatingStat(time_class="blitz", current=1500, games=50, win_rate=55.0)])
    two = PlayerReport(username="bob", ratings=[RatingStat(time_class="bullet", current=1200, games=20, win_rate=45.0)])
    rows = ratings_comparison(one, two)
    time_classes = {r["time_class"] for r in rows}
    assert time_classes == {"blitz", "bullet"}
    blitz_row = next(r for r in rows if r["time_class"] == "blitz")
    assert blitz_row["one"]["current"] == 1500
    assert blitz_row["two"] is None


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


def test_safe_slug_blocks_path_traversal() -> None:
    for hostile in ["../../etc/passwd", "..\\..\\windows", "$(whoami)"]:
        slug = safe_slug(hostile)
        assert "/" not in slug and "\\" not in slug and ".." not in slug


@pytest.mark.parametrize("fmt", SUPPORTED_FORMATS)
def test_write_report_creates_readable_files(tmp_path: Path, fmt: str) -> None:
    report = PlayerReport(username="hikaru", games_analyzed=10, win_rate=70.0)
    path = write_report(report, fmt, tmp_path)
    assert path.exists() and path.stat().st_size > 0
    content = path.read_text(encoding="utf-8")
    if fmt == "json":
        assert json.loads(content)["username"] == "hikaru"
    else:
        assert "hikaru" in content


def test_write_report_rejects_unknown_format(tmp_path: Path) -> None:
    from chess_analyzer.errors import AnalyzerError

    report = PlayerReport(username="hikaru")
    with pytest.raises(AnalyzerError):
        write_report(report, "pdf", tmp_path)


def test_html_report_escapes_injected_markup(tmp_path: Path) -> None:
    report = PlayerReport(username="hikaru", name="<script>alert(1)</script>")
    content = write_report(report, "html", tmp_path).read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in content


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def test_cli_parser_accepts_documented_flags() -> None:
    from chess_analyzer.cli import build_parser

    args = build_parser().parse_args(
        ["--player", "hikaru", "--months", "6", "--time-class", "blitz", "--format", "json"]
    )
    assert args.player == "hikaru"
    assert args.months == 6
    assert args.time_class == "blitz"
    assert args.format == ["json"]


def test_cli_compare_requires_two_distinct_usernames() -> None:
    from chess_analyzer.cli import main

    assert main(["--compare", "hikaru", "hikaru"]) == 1
