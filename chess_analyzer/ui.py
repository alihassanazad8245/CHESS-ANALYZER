"""Terminal presentation layer built on ``rich``."""

from __future__ import annotations

from typing import Any, Sequence

from rich.align import Align
from rich.box import HEAVY, ROUNDED, SIMPLE
from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from . import __app_name__, __author__, __instagram__, __tagline__, __version__
from .errors import AnalyzerError
from .models import PlayerReport
from .utils import bar, human_number, sparkline, truncate

BANNER = r"""
   ██████╗██╗  ██╗███████╗███████╗███████╗
  ██╔════╝██║  ██║██╔════╝██╔════╝██╔════╝
  ██║     ███████║█████╗  ███████╗███████╗
  ██║     ██╔══██║██╔══╝  ╚════██║╚════██║
  ╚██████╗██║  ██║███████╗███████║███████║
   ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
        ♜ ♞ ♝ ♛ ♚ ♝ ♞ ♜   A N A L Y Z E R
"""

_PIECE_BY_TIME_CLASS = {"bullet": "⚡", "blitz": "🔥", "rapid": "🐢", "daily": "📮"}


class UI:
    """All terminal output flows through this class."""

    def __init__(self, no_color: bool = False) -> None:
        self.console = Console(no_color=no_color, highlight=False, soft_wrap=False)
        self.no_color = no_color

    SIDE_BY_SIDE_WIDTH = 104
    _RANK_COLOURS = ("bright_green", "green", "yellow", "bright_yellow")

    # ------------------------------------------------------------------ #
    # Generic messages
    # ------------------------------------------------------------------ #

    def banner(self) -> None:
        header = Text(BANNER.strip("\n"), style="bold green" if not self.no_color else "")
        subtitle = Text.assemble(
            (f"{__app_name__} ", "bold white"),
            (f"v{__version__}", "dim"),
            ("  •  ", "dim"),
            (__tagline__, "italic green"),
        )
        self.console.print(
            Panel(Group(Align.center(header), Align.center(subtitle)),
                  box=HEAVY, border_style="green", padding=(0, 2))
        )

    def rule(self, title: str) -> None:
        self.console.print()
        self.console.print(Rule(f"[bold green]{title}[/bold green]", style="green"))

    def success(self, message: str) -> None:
        self.console.print(f"[bold green]\\[OK][/bold green] {message}")

    def info(self, message: str) -> None:
        self.console.print(f"[bold blue]\\[i][/bold blue] {message}")

    def warn(self, message: str) -> None:
        self.console.print(f"[bold yellow]\\[!][/bold yellow] {message}")

    def error(self, error: AnalyzerError | str, hints: Sequence[str] = ()) -> None:
        if isinstance(error, AnalyzerError):
            message, hint_list = error.message, list(error.hints)
        else:
            message, hint_list = str(error), list(hints)

        body = Text(message, style="bold red")
        if hint_list:
            body.append("\n\nPlease check:\n", style="white")
            for hint in hint_list:
                body.append(f"  • {hint}\n", style="dim white")

        self.console.print(Panel(body, title="[bold red]ERROR[/bold red]",
                                  border_style="red", box=ROUNDED))

    def status(self, message: str):
        return self.console.status(f"[green]{message}…[/green]", spinner="dots")

    def goodbye(self) -> None:
        """Print a friendly sign-off with a credit line, shown when the app exits."""
        text = Text()
        text.append("Thanks for using Chess Analyzer!\n", style="bold green")
        text.append(f"Built by {__author__}  ", style="white")
        text.append(f"· Instagram: @{__instagram__}", style="dim cyan")
        self.console.print()
        self.console.print(Panel(text, box=ROUNDED, border_style="green", padding=(0, 2)))

    # ------------------------------------------------------------------ #
    # Shared building blocks
    # ------------------------------------------------------------------ #

    def _kv_table(self, rows: Sequence[tuple[str, Any]], title: str | None = None,
                  key_width: int = 22) -> Table:
        table = Table(box=None, show_header=False, title=title, title_style="bold green",
                      show_edge=False, pad_edge=False, padding=(0, 1, 0, 0), expand=False)
        table.add_column("Field", style="dim green", no_wrap=True, width=key_width)
        table.add_column("Value", style="white", overflow="fold", min_width=24)
        for key, value in rows:
            table.add_row(key, str(value))
        return table

    def _side_by_side(self, left: Table, right: Table) -> None:
        if self.console.width < self.SIDE_BY_SIDE_WIDTH:
            self.console.print(left)
            self.console.print(right)
            return
        grid = Table.grid(padding=(0, 4))
        grid.add_column()
        grid.add_column()
        grid.add_row(left, right)
        self.console.print(grid)

    def _rank_colour(self, index: int, total: int) -> str:
        if total <= 1:
            return self._RANK_COLOURS[0]
        step = index * len(self._RANK_COLOURS) // total
        return self._RANK_COLOURS[min(step, len(self._RANK_COLOURS) - 1)]

    def bar_chart(self, title: str, data: Sequence[tuple[str, float]], suffix: str = "",
                  width: int = 30, label_width: int = 16, trend: bool = False) -> None:
        if not data:
            self.console.print(f"[dim]{title}: no data available[/dim]")
            return

        width = max(10, min(width, self.console.width - label_width - 18))
        maximum = max(value for _, value in data) or 1
        values = [
            f"{v:,.1f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"{v:,}"
            for _, v in data
        ]
        value_width = max(len(v) for v in values) + len(suffix)

        body = Text()
        for index, ((label, value), shown) in enumerate(zip(data, values)):
            colour = self._rank_colour(index, len(data))
            body.append(f"{truncate(label, label_width):<{label_width}} ", style="white")
            body.append(f"{bar(value, maximum, width):<{width}} ", style=colour)
            body.append(f"{shown + suffix:>{value_width}}\n", style="bold white")

        if trend and len(data) > 2:
            body.append("\nTrend  ", style="dim white")
            body.append(sparkline([v for _, v in data]), style="bright_green")

        self.console.print(Panel(body, title=f"[bold]{title}[/bold]",
                                  border_style="green", box=ROUNDED))

    def _gauge(self, value: int, maximum: int, width: int = 34) -> Text:
        colour = "green" if value >= maximum * 0.7 else "yellow" if value >= maximum * 0.45 else "red"
        filled = bar(value, maximum, width)
        gauge = Text()
        gauge.append(filled, style=f"bold {colour}")
        gauge.append("░" * max(0, width - len(filled)), style="dim")
        return gauge

    # ------------------------------------------------------------------ #
    # Player rendering
    # ------------------------------------------------------------------ #

    def render_player(self, r: PlayerReport) -> None:
        self._profile(r)
        self._ratings(r)
        self._results(r)
        self._openings(r)
        self._activity(r)
        self._streaks_and_length(r)
        self._rivalries(r)
        self._performance(r)
        self._footer(r.warnings, r.api_requests, r.generated_at)

    def _profile(self, r: PlayerReport) -> None:
        self.rule("PLAYER PROFILE")
        title_tag = f" [{r.title}]" if r.title else ""
        left = self._kv_table([
            ("Username", f"{r.username}{title_tag}"),
            ("Name", r.name or "N/A"),
            ("Country", r.country_code),
            ("Location", r.location or "N/A"),
            ("Profile URL", r.profile_url),
            ("Account status", r.status),
            ("Streamer", "Yes" if r.is_streamer else "No"),
        ])
        joined = f"{r.joined}" + (f"  ({r.account_age_days:,} days ago)" if r.account_age_days else "")
        online = f"{r.last_online}" + (
            f"  ({r.days_since_online} days ago)" if r.days_since_online is not None else ""
        )
        right = self._kv_table([
            ("Joined Chess.com", joined),
            ("Last online", online),
            ("Followers", human_number(r.followers)),
            ("Favorite time class", r.favorite_time_class.title()),
            ("Months analysed", str(r.months_analyzed)),
            ("Games analysed", human_number(r.games_analyzed)),
            ("Sampled range", r.date_range),
        ])
        self._side_by_side(left, right)

    def _ratings(self, r: PlayerReport) -> None:
        self.rule("RATINGS BY TIME CLASS")
        if not r.ratings:
            self.console.print("[dim]No rated game history available.[/dim]")
            return

        table = Table(box=ROUNDED, border_style="green", header_style="bold green")
        table.add_column("Time class")
        table.add_column("Current", justify="right")
        table.add_column("Best", justify="right")
        table.add_column("Best date")
        table.add_column("W / L / D", justify="right")
        table.add_column("Win rate", justify="right")
        for rating in r.ratings:
            icon = _PIECE_BY_TIME_CLASS.get(rating.time_class, "")
            table.add_row(
                f"{icon} {rating.time_class.title()}".strip(),
                human_number(rating.current) if rating.current else "N/A",
                human_number(rating.best) if rating.best else "N/A",
                rating.best_date,
                f"{rating.wins}/{rating.losses}/{rating.draws}",
                f"{rating.win_rate}%",
            )
        self.console.print(table)

        if r.rating_trend:
            self.bar_chart(
                f"Rating trend ({r.favorite_time_class.title()}, sampled games)",
                r.rating_trend, width=26, label_width=12, trend=True,
            )

    def _results(self, r: PlayerReport) -> None:
        self.rule("GAME RESULTS")
        if not r.games_analyzed:
            self.console.print("[dim]No games available for the selected window.[/dim]")
            return

        left = self._kv_table([
            ("Total games", human_number(r.games_analyzed)),
            ("Record (W/L/D)", f"{r.wins} / {r.losses} / {r.draws}"),
            ("Overall win rate", f"{r.win_rate}%"),
            ("As White", f"{r.white_games} games, {r.white_win_rate}% wins"),
            ("As Black", f"{r.black_games} games, {r.black_win_rate}% wins"),
        ], title="Overview")
        right = self._kv_table(
            [(tc.title(), human_number(n)) for tc, n in r.time_class_split] or [("N/A", "0")],
            title="Games by time class",
        )
        self._side_by_side(left, right)

        if r.win_reasons:
            self.bar_chart("How wins happened", r.win_reasons, width=22, label_width=20)
        if r.loss_reasons:
            self.bar_chart("How losses happened", r.loss_reasons, width=22, label_width=20)

    def _openings(self, r: PlayerReport) -> None:
        self.rule("OPENING REPERTOIRE")
        if not r.openings_as_white and not r.openings_as_black:
            self.console.print("[dim]No opening data available.[/dim]")
            return

        def table_for(title: str, openings) -> Table:
            t = Table(box=ROUNDED, border_style="green", header_style="bold green", title=title,
                      title_style="bold green")
            t.add_column("Opening", style="white")
            t.add_column("Games", justify="right")
            t.add_column("Win rate", justify="right")
            for o in openings[:6]:
                t.add_row(truncate(o.name, 28), str(o.games), f"{o.win_rate}%")
            return t

        if r.openings_as_white:
            self.console.print(table_for("As White", r.openings_as_white))
        if r.openings_as_black:
            self.console.print(table_for("As Black", r.openings_as_black))
        self.console.print(
            f"[dim]Opening diversity: {r.opening_diversity}% (Analyzer Metric — "
            f"higher means a wider repertoire)[/dim]"
        )

    def _activity(self, r: PlayerReport) -> None:
        self.rule("ACTIVITY")
        if r.monthly_activity:
            self.bar_chart("Games per month", r.monthly_activity, width=26, label_width=10)
        if r.weekday_activity:
            self.bar_chart("Games per weekday (UTC)", r.weekday_activity, width=26, label_width=10)

    def _streaks_and_length(self, r: PlayerReport) -> None:
        self.rule("STREAKS & GAME LENGTH")
        s = r.streaks
        left = self._kv_table([
            ("Longest win streak", f"{s.longest_win_streak} games"),
            ("Longest loss streak", f"{s.longest_loss_streak} games"),
            ("Current streak", f"{s.current_streak_length} {s.current_streak_type}(s)"
                if s.current_streak_type != "none" else "N/A"),
        ], title="Streaks")
        right = self._kv_table([
            ("Average game length", f"{r.avg_game_length} moves" if r.avg_game_length else "N/A"),
            ("Longest game", f"{r.longest_game} moves" if r.longest_game else "N/A"),
            ("Shortest game", f"{r.shortest_game} moves" if r.shortest_game else "N/A"),
            ("Average accuracy", f"{r.avg_accuracy}% ({r.accuracy_sample_size} games)"
                if r.avg_accuracy is not None else "No Game Review data"),
        ], title="Game length & accuracy")
        self._side_by_side(left, right)

    def _rivalries(self, r: PlayerReport) -> None:
        if not r.top_opponents:
            return
        self.rule("RIVALRIES  (opponents faced more than once)")
        table = Table(box=ROUNDED, border_style="green", header_style="bold green")
        table.add_column("Opponent", style="white")
        table.add_column("Games", justify="right")
        table.add_column("Record (W/L/D)", justify="right")
        for opp in r.top_opponents:
            table.add_row(opp.username, str(opp.games), f"{opp.wins}/{opp.losses}/{opp.draws}")
        self.console.print(table)

    def _performance(self, r: PlayerReport) -> None:
        self.rule("PERFORMANCE INDEX  (Analyzer Metric — not an official Chess.com rating)")
        p = r.performance
        colour = "green" if p.total >= 70 else "yellow" if p.total >= 45 else "red"

        table = Table(box=SIMPLE, show_header=True, header_style="bold green")
        table.add_column("Dimension", style="white", width=22)
        table.add_column("Score", justify="right", width=8)
        table.add_column("Rating")
        for label, score, maximum in p.breakdown:
            table.add_row(label, f"{score}/{maximum}", f"[{colour}]{bar(score, maximum, 20)}[/]")

        headline = Text()
        headline.append("Overall estimate  ", style="white")
        headline.append_text(self._gauge(p.total, 100))
        headline.append(f"  {p.total}/100", style=f"bold {colour}")
        headline.append(f"\nGrade             {p.grade}\n", style=f"bold {colour}")

        content: list[Any] = [headline, table]
        if p.notes:
            notes = Text("\nObservations:\n", style="bold white")
            for note in p.notes:
                notes.append(f"  • {note}\n", style="yellow")
            content.append(notes)

        self.console.print(Panel(Group(*content), border_style=colour, box=ROUNDED,
                                  title="[bold]PLAYER PERFORMANCE INDEX[/bold]"))

    # ------------------------------------------------------------------ #
    # Comparison
    # ------------------------------------------------------------------ #

    def render_comparison(self, players: Sequence[PlayerReport], rows: Sequence[dict[str, Any]],
                          ratings_rows: Sequence[dict[str, Any]] | None = None,
                          h2h: Any = None) -> None:
        one, two = players[0], players[1]
        self._vs_header(one, two)
        self._comparison_table(players, rows)
        if ratings_rows:
            self._ratings_comparison(one, two, ratings_rows)
        self._win_rate_bars(one, two)
        self._head_to_head(one, two, h2h)
        self._comparison_summary(players, rows)

    def _comparison_summary(self, players: Sequence[PlayerReport], rows: Sequence[dict[str, Any]]) -> None:
        wins = [row["winner"] for row in rows if row["winner"] not in ("Tie", "-")]
        if not wins:
            return
        leader = max(set(wins), key=wins.count)
        self.console.print(Panel(
            Text(f"{leader} leads on {wins.count(leader)} of {len(wins)} compared metrics.",
                 style="bold green"),
            border_style="green", box=ROUNDED, title="[bold]OVERALL SUMMARY[/bold]",
        ))

    def _vs_header(self, one: PlayerReport, two: PlayerReport) -> None:
        self.rule("HEAD-TO-HEAD MATCHUP")
        left = Text(f"{one.username}", style="bold bright_cyan", justify="center")
        if one.title:
            left.append(f"  [{one.title}]", style="dim")
        right = Text(f"{two.username}", style="bold bright_magenta", justify="center")
        if two.title:
            right.append(f"  [{two.title}]", style="dim")

        grid = Table.grid(expand=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_column(justify="center", width=5, no_wrap=True)
        grid.add_column(justify="center", ratio=1)
        grid.add_row(left, Text("VS", style="bold yellow", justify="center"), right)
        self.console.print(Panel(grid, box=ROUNDED, border_style="green", padding=(0, 2)))

    def _comparison_table(self, players: Sequence[PlayerReport], rows: Sequence[dict[str, Any]]) -> None:
        table = Table(box=ROUNDED, border_style="green", header_style="bold green")
        table.add_column("Metric", style="white", width=24)
        table.add_column(players[0].username, justify="right", style="bright_cyan")
        table.add_column(players[1].username, justify="right", style="bright_magenta")
        table.add_column("Leader", style="bold green")

        for row in rows:
            values = [
                f"{v}%" if row["metric"] == "Win rate (sample)" else
                (human_number(v) if isinstance(v, int) else str(v))
                for v in row["values"]
            ]
            table.add_row(row["metric"], *values, str(row["winner"]))
        self.console.print(table)

    def _ratings_comparison(self, one: PlayerReport, two: PlayerReport,
                            ratings_rows: Sequence[dict[str, Any]]) -> None:
        self.rule("RATINGS BY FORMAT  (career totals, not just the sample)")
        table = Table(box=ROUNDED, border_style="green", header_style="bold green")
        table.add_column("Format")
        table.add_column(f"{one.username}\nrating", justify="right", style="bright_cyan")
        table.add_column("games", justify="right", style="bright_cyan")
        table.add_column("win %", justify="right", style="bright_cyan")
        table.add_column(f"{two.username}\nrating", justify="right", style="bright_magenta")
        table.add_column("games", justify="right", style="bright_magenta")
        table.add_column("win %", justify="right", style="bright_magenta")

        any_data = False
        for row in ratings_rows:
            p1, p2 = row["one"], row["two"]
            icon = _PIECE_BY_TIME_CLASS.get(row["time_class"], "")
            label = f"{icon} {row['time_class'].title()}".strip()
            if p1:
                any_data = True
            if p2:
                any_data = True
            table.add_row(
                label,
                human_number(p1["current"]) if p1 else "—", str(p1["games"]) if p1 else "—",
                f"{p1['win_rate']}%" if p1 else "—",
                human_number(p2["current"]) if p2 else "—", str(p2["games"]) if p2 else "—",
                f"{p2['win_rate']}%" if p2 else "—",
            )
        if any_data:
            self.console.print(table)
        else:
            self.console.print("[dim]No rated games found for either player.[/dim]")

    def _win_rate_bars(self, one: PlayerReport, two: PlayerReport) -> None:
        self.rule("WIN RATE & PERFORMANCE")
        metrics = [
            ("Win rate", one.win_rate, two.win_rate, "%"),
            ("Performance Index", float(one.performance.total), float(two.performance.total), "/100"),
        ]
        body = Text()
        width = 28
        for label, v1, v2, suffix in metrics:
            maximum = max(v1, v2, 1.0)
            body.append(f"{label}\n", style="bold white")
            body.append(f"  {one.username:<16}", style="bright_cyan")
            body.append(f"{bar(v1, maximum, width):<{width}} ", style="bright_cyan")
            body.append(f"{v1:g}{suffix}\n", style="bold bright_cyan")
            body.append(f"  {two.username:<16}", style="bright_magenta")
            body.append(f"{bar(v2, maximum, width):<{width}} ", style="bright_magenta")
            body.append(f"{v2:g}{suffix}\n\n", style="bold bright_magenta")

        self.console.print(Panel(body, box=ROUNDED, border_style="green",
                                  title="[bold]Side-by-side[/bold]"))

    def _head_to_head(self, one: PlayerReport, two: PlayerReport, record: Any) -> None:
        self.rule("DIRECT MATCHES  (games played against each other)")
        if record is None or record.games == 0:
            self.console.print(Panel(
                Text(
                    f"{one.username} and {two.username} have not played each other "
                    f"in the analysed game sample.\nTry a larger --months window if "
                    f"you believe they have played before.",
                    style="yellow",
                ),
                box=ROUNDED, border_style="yellow",
            ))
            return

        total = record.games
        if record.wins > record.losses:
            leader_text = f"{one.username} leads head-to-head"
            colour = "bright_cyan"
        elif record.losses > record.wins:
            leader_text = f"{two.username} leads head-to-head"
            colour = "bright_magenta"
        else:
            leader_text = "Head-to-head is tied"
            colour = "yellow"

        body = Text()
        body.append(f"Games played against each other: {total}\n\n", style="bold white")
        body.append(f"  {one.username:<16}", style="bright_cyan")
        body.append(f"{bar(record.wins, total, 24):<24} ", style="bright_cyan")
        body.append(f"{record.wins} win(s)\n", style="bold bright_cyan")
        body.append(f"  {two.username:<16}", style="bright_magenta")
        body.append(f"{bar(record.losses, total, 24):<24} ", style="bright_magenta")
        body.append(f"{record.losses} win(s)\n", style="bold bright_magenta")
        body.append(f"  {'Draws':<16}", style="white")
        body.append(f"{bar(record.draws, total, 24):<24} ", style="white")
        body.append(f"{record.draws}\n\n", style="bold white")
        body.append(leader_text, style=f"bold {colour}")

        self.console.print(Panel(body, box=ROUNDED, border_style=colour,
                                  title="[bold]HEAD-TO-HEAD RECORD[/bold]"))

    # ------------------------------------------------------------------ #
    # Daily puzzle
    # ------------------------------------------------------------------ #

    def render_puzzle(self, puzzle: dict[str, Any]) -> None:
        from .utils import format_timestamp

        self.rule("CHESS.COM DAILY PUZZLE")
        self.console.print(self._kv_table([
            ("Title", puzzle.get("title", "N/A")),
            ("Published", format_timestamp(puzzle.get("publish_time"))),
            ("URL", puzzle.get("url", "N/A")),
            ("FEN", puzzle.get("fen", "N/A")),
        ]))
        self.console.print("[dim]Open the URL above to solve it on Chess.com.[/dim]")

    # ------------------------------------------------------------------ #
    # Footer
    # ------------------------------------------------------------------ #

    def _footer(self, warnings: Sequence[str], api_requests: int, generated_at: str) -> None:
        if warnings:
            text = Text()
            for warning in warnings:
                text.append(f"• {warning}\n", style="yellow")
            self.console.print(Panel(text, title="[bold yellow]NOTES[/bold yellow]",
                                      border_style="yellow", box=ROUNDED))
        self.console.print(
            f"[dim]Scan completed {generated_at} • {api_requests} API requests • "
            f"analyzer v{__version__}[/dim]"
        )
