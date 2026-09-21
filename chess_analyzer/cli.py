"""Command-line interface: argument parsing, interactive menu, orchestration.

    python main.py                        interactive menu
    python main.py --player hikaru        direct, scriptable mode
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

from . import __app_name__, __version__
from .analyzer import Analyzer, compare_players, head_to_head, ratings_comparison
from .charts import export_charts, matplotlib_available
from .chess_client import ChessClient
from .config import DEFAULT_MONTHS, DEFAULT_REPORT_DIR, Settings, TIME_CLASSES
from .errors import AnalyzerError, InvalidInputError
from .models import PlayerReport
from .reports import SUPPORTED_FORMATS, write_report
from .ui import UI
from .utils import validate_username

MIN_PYTHON = (3, 9)
logger = logging.getLogger("chess_analyzer")


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="chess-analyzer",
        description=f"{__app_name__} — analyse Chess.com players from your terminal.",
        epilog=(
            "Examples:\n"
            "  python main.py\n"
            "  python main.py --player hikaru\n"
            "  python main.py --player MagnusCarlsen --months 6 --format json html\n"
            "  python main.py --compare Hikaru MagnusCarlsen\n"
            "  python main.py --puzzle\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    target = parser.add_argument_group("analysis targets")
    target.add_argument("--player", "-p", metavar="USERNAME",
                        help="Chess.com username to analyse")
    target.add_argument("--compare", "-c", nargs=2, metavar=("USER1", "USER2"),
                        help="compare two Chess.com players")
    target.add_argument("--puzzle", action="store_true",
                        help="show today's Chess.com daily puzzle and exit")

    scope = parser.add_argument_group("analysis scope")
    scope.add_argument("--months", "-m", type=int, default=DEFAULT_MONTHS,
                       help=f"number of recent months of games to analyse (default: {DEFAULT_MONTHS})")
    scope.add_argument("--time-class", choices=(*TIME_CLASSES, "all"), default="all",
                       help="only analyse games of this time class (default: all)")

    output = parser.add_argument_group("output")
    output.add_argument("--format", "-f", nargs="+", default=[], choices=SUPPORTED_FORMATS,
                        help="export report formats (default: none)")
    output.add_argument("--output", "-o", metavar="DIR", default=str(DEFAULT_REPORT_DIR),
                        help="directory for generated reports (default: ./reports)")
    output.add_argument("--charts", action="store_true",
                        help="also export PNG charts (requires matplotlib)")
    output.add_argument("--no-color", action="store_true", help="disable coloured output")

    misc = parser.add_argument_group("misc")
    misc.add_argument("--verbose", "-v", action="store_true",
                      help="verbose logging and full tracebacks")
    misc.add_argument("--version", action="version", version=f"{__app_name__} {__version__}")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


class Application:
    """Wires the UI, client and analyzer together for one session."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ui = UI(no_color=settings.no_color)
        self.client = ChessClient()
        self.analyzer = Analyzer(self.client)

    def show_intro(self) -> None:
        """Remind the user this API is completely open - no setup needed."""
        self.ui.info("Chess.com's public API needs no signup, key or token — just internet access.")

    def _run_analysis(self, label: str, func, *args, **kwargs):
        steps: list[str] = []
        self.analyzer.progress = steps.append
        try:
            with self.ui.status(label):
                result = func(*args, **kwargs)
        finally:
            self.analyzer.progress = lambda _m: None
        for step in steps:
            self.ui.success(step)
        return result

    def _export(self, report: PlayerReport, formats: Sequence[str], charts: bool) -> None:
        if not formats and not charts:
            return
        self.ui.rule("EXPORTS")
        for fmt in formats:
            try:
                path = write_report(report, fmt, self.settings.report_dir)
                self.ui.success(f"{fmt.upper()} report → {path}")
            except AnalyzerError as exc:
                self.ui.error(exc)

        if charts:
            if not matplotlib_available():
                self.ui.warn("PNG charts need matplotlib. Install it with: pip install matplotlib")
                return
            paths = export_charts(report, self.settings.report_dir)
            if paths:
                for path in paths:
                    self.ui.success(f"Chart → {path}")
            else:
                self.ui.warn("No charts could be generated for this report.")

    def analyze_player(self, username: str, formats: Sequence[str] = (), charts: bool = False) -> None:
        login = validate_username(username)
        report = self._run_analysis(
            f"Analyzing {login}", self.analyzer.analyze_player,
            login, self.settings.months, self.settings.time_class,
        )
        self.ui.render_player(report)
        self._export(report, formats, charts)

    def compare(self, first: str, second: str, formats: Sequence[str] = ()) -> None:
        one, two = validate_username(first), validate_username(second)
        if one.lower() == two.lower():
            raise InvalidInputError("Please provide two different usernames to compare.")

        reports = [
            self._run_analysis(
                f"Analyzing {login}", self.analyzer.analyze_player,
                login, self.settings.months, self.settings.time_class,
            )
            for login in (one, two)
        ]
        self.ui.render_comparison(
            reports, compare_players(reports),
            ratings_rows=ratings_comparison(reports[0], reports[1]),
            h2h=head_to_head(reports[0], reports[1]),
        )
        for report in reports:
            self._export(report, formats, charts=False)

    def show_puzzle(self) -> None:
        puzzle = self._run_analysis("Fetching today's puzzle", self.client.get_daily_puzzle)
        self.ui.render_puzzle(puzzle)

    def close(self) -> None:
        self.client.close()

    # -- interactive menu ---------------------------------------------- #

    def _ask(self, prompt: str) -> str:
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            self.ui.goodbye()
            raise SystemExit(0)

    def _ask_formats(self) -> list[str]:
        answer = self._ask(
            "Export reports? (json/csv/md/html, space separated, blank for none): "
        ).lower()
        chosen = [fmt for fmt in answer.split() if fmt in SUPPORTED_FORMATS]
        if answer and not chosen:
            self.ui.warn(f"Ignored unknown formats. Supported: {', '.join(SUPPORTED_FORMATS)}")
        return chosen

    def interactive(self) -> int:
        self.ui.banner()
        self.show_intro()

        menu = (
            "\n[bold green]MAIN MENU[/bold green]\n"
            "  [bold]1[/bold]  Analyze a player\n"
            "  [bold]2[/bold]  Compare two players\n"
            "  [bold]3[/bold]  Show today's daily puzzle\n"
            "  [bold]4[/bold]  Exit\n"
        )

        while True:
            self.ui.console.print(menu)
            choice = self._ask("Select an option [1-4]: ")
            try:
                if choice == "1":
                    username = self._ask("Chess.com username: ")
                    formats = self._ask_formats()
                    self.analyze_player(username, formats)
                elif choice == "2":
                    first = self._ask("First username: ")
                    second = self._ask("Second username: ")
                    self.compare(first, second)
                elif choice == "3":
                    self.show_puzzle()
                elif choice in ("4", "q", "quit", "exit"):
                    self.ui.goodbye()
                    return 0
                else:
                    self.ui.warn("Please choose a number between 1 and 4.")
            except AnalyzerError as exc:
                self.ui.error(exc)
                if self.settings.verbose:
                    self.ui.console.print_exception()


def _check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        required = ".".join(str(part) for part in MIN_PYTHON)
        current = ".".join(str(part) for part in sys.version_info[:3])
        sys.stderr.write(
            f"[ERROR] {__app_name__} requires Python {required} or newer (found {current}).\n"
        )
        raise SystemExit(2)


def main(argv: Sequence[str] | None = None) -> int:
    """Program entry point. Returns a process exit code."""
    _check_python_version()

    parser = build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    settings = Settings(
        months=args.months,
        time_class=args.time_class,
        verbose=args.verbose,
        no_color=args.no_color,
        report_dir=Path(args.output).expanduser().resolve(),
    )

    app = Application(settings)
    ui = app.ui

    try:
        direct = bool(args.player or args.compare or args.puzzle)
        if direct:
            ui.banner()
            app.show_intro()

        if args.player:
            app.analyze_player(args.player, args.format, args.charts)
        if args.compare:
            app.compare(args.compare[0], args.compare[1], args.format)
        if args.puzzle:
            app.show_puzzle()

        if not direct:
            return app.interactive()
        return 0

    except AnalyzerError as exc:
        ui.error(exc)
        if args.verbose:
            ui.console.print_exception()
        return 1
    except KeyboardInterrupt:
        ui.console.print("\n[yellow]Cancelled by user.[/yellow]")
        return 130
    except Exception as exc:  # noqa: BLE001 - last line of defence
        ui.error(
            "An unexpected internal error occurred.",
            hints=(f"Details: {type(exc).__name__}: {exc}",
                  "Re-run with --verbose to see the full traceback"),
        )
        if args.verbose:
            ui.console.print_exception()
        return 1
    finally:
        app.close()
