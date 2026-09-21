"""Small, dependency-free helpers shared across the package."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Sequence

from .errors import InvalidInputError

# Chess.com usernames: letters, digits, underscore and hyphen, 3-25 chars.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{3,25}$")

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: Human-readable descriptions of Chess.com's game result codes, copied
#: verbatim from the official Published-Data API documentation.
RESULT_DESCRIPTIONS: dict[str, str] = {
    "win": "Win",
    "checkmated": "Checkmated",
    "agreed": "Draw agreed",
    "repetition": "Draw by repetition",
    "timeout": "Timeout",
    "resigned": "Resigned",
    "stalemate": "Stalemate",
    "lose": "Lose",
    "insufficient": "Insufficient material",
    "50move": "Draw by 50-move rule",
    "abandoned": "Abandoned",
    "kingofthehill": "Opponent king reached the hill",
    "threecheck": "Checked for the 3rd time",
    "timevsinsufficient": "Draw by timeout vs insufficient material",
    "bughousepartnerlose": "Bughouse partner lost",
}

#: Which result codes count as a win / loss / draw for the player who has them.
_WIN_CODES = {"win"}
_DRAW_CODES = {"agreed", "repetition", "stalemate", "insufficient", "50move",
               "timevsinsufficient"}
# Everything else (checkmated, timeout, resigned, abandoned, lose,
# kingofthehill, threecheck, bughousepartnerlose) counts as a loss.


def is_valid_username(username: str) -> bool:
    """Return True if ``username`` matches Chess.com's username pattern."""
    return bool(_USERNAME_RE.match(username.strip()))


def validate_username(username: str) -> str:
    """Return the cleaned username or raise :class:`InvalidInputError`."""
    cleaned = username.strip().lstrip("@")
    if not cleaned:
        raise InvalidInputError("No username was entered.")
    if not is_valid_username(cleaned):
        raise InvalidInputError(
            f"'{cleaned}' is not a valid Chess.com username.",
            hints=(
                "Usernames are 3-25 characters: letters, digits, _ and -",
                "Check the exact spelling shown on the player's profile page",
            ),
        )
    return cleaned


def classify_result(code: str) -> str:
    """Classify a Chess.com result code as ``win``, ``draw`` or ``loss``."""
    if code in _WIN_CODES:
        return "win"
    if code in _DRAW_CODES:
        return "draw"
    return "loss"


def describe_result(code: str) -> str:
    """Human-readable description of a result code."""
    return RESULT_DESCRIPTIONS.get(code, code.replace("_", " ").title())


def format_timestamp(value: int | None) -> str:
    """Render a Unix timestamp as ``YYYY-MM-DD``, or ``N/A``."""
    if not value:
        return "N/A"
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d")


def days_since(value: int | None) -> int | None:
    """Whole days elapsed since a Unix timestamp, or None."""
    if not value:
        return None
    then = datetime.fromtimestamp(value, tz=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - then).days)


def weekday_of(value: int) -> str:
    """Three-letter weekday name for a Unix timestamp, in UTC."""
    return WEEKDAYS[datetime.fromtimestamp(value, tz=timezone.utc).weekday()]


def month_key_of(value: int) -> str:
    """``YYYY-MM`` key for a Unix timestamp, in UTC."""
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m")


def human_number(value: int | float | None) -> str:
    """Format a number with thousands separators."""
    if value is None:
        return "N/A"
    return f"{value:,}"


def percentage(part: float, whole: float) -> float:
    """Safe percentage calculation that never divides by zero."""
    return (part / whole * 100.0) if whole else 0.0


def truncate(text: str | None, limit: int = 60) -> str:
    """Shorten ``text`` to ``limit`` characters with an ellipsis."""
    if not text:
        return "N/A"
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# Opening classification from Chess.com's ECO URL
# --------------------------------------------------------------------------- #


def opening_name_from_eco_url(eco_url: str | None) -> str:
    """Turn a Chess.com opening URL into a readable opening name.

    ``https://www.chess.com/openings/Italian-Game-Classical-4...-Nf6`` becomes
    ``Italian Game Classical``. Chess.com encodes variation moves in the URL
    tail as tokens containing digits or dots; everything from the first such
    token onward is dropped so many close variations collapse into one family.
    """
    if not eco_url:
        return "Unknown opening"
    slug = eco_url.rstrip("/").rsplit("/", 1)[-1]
    words = slug.split("-")

    family_words: list[str] = []
    for word in words:
        if any(ch.isdigit() for ch in word):
            break
        family_words.append(word)

    name = " ".join(family_words).strip() or " ".join(words[:4])
    return name or "Unknown opening"


def opening_family(eco_url: str | None, max_words: int = 3) -> str:
    """A shorter grouping key than :func:`opening_name_from_eco_url`."""
    full = opening_name_from_eco_url(eco_url)
    return " ".join(full.split()[:max_words]) or full


# --------------------------------------------------------------------------- #
# Lightweight PGN parsing (headers + move count only - no engine needed)
# --------------------------------------------------------------------------- #

_HEADER_RE = re.compile(r'\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]')
_MOVE_NUMBER_RE = re.compile(r"\b(\d+)\.")


def parse_pgn_headers(pgn: str | None) -> dict[str, str]:
    """Extract ``[Tag "Value"]`` header pairs from a PGN string."""
    if not pgn:
        return {}
    return {tag: value for tag, value in _HEADER_RE.findall(pgn)}


def _move_text_only(pgn: str) -> str:
    """Strip PGN header tags, returning only the movetext section."""
    # Header lines are "[Tag "Value"]"; movetext starts at the first line
    # that isn't a header. A blank line normally separates them, but be
    # defensive and just drop every header-shaped line.
    lines = [ln for ln in pgn.splitlines() if not ln.strip().startswith("[")]
    return "\n".join(lines)


def count_full_moves(pgn: str | None) -> int:
    """Estimate the number of full moves (move pairs) played in a game.

    Counts the highest move-number token in the PGN movetext. This is a
    simple, reliable proxy for game length without needing a chess engine.
    """
    if not pgn:
        return 0
    numbers = [int(n) for n in _MOVE_NUMBER_RE.findall(_move_text_only(pgn))]
    return max(numbers) if numbers else 0


def opening_moves_preview(pgn: str | None, plies: int = 6) -> str:
    """Return the first few SAN moves of a game as a short preview string.

    Strips PGN headers, comments, and move numbers, keeping only the move
    tokens themselves (e.g. ``1. e4 e5 2. Nf3 Nc6`` -> ``e4 e5 Nf3 Nc6``).
    """
    if not pgn:
        return ""
    body = _move_text_only(pgn)
    body = re.sub(r"\{[^}]*\}", " ", body)          # comments
    body = re.sub(r"\$\d+", " ", body)               # NAGs
    body = re.sub(r"\d+\.(\.\.)?", " ", body)         # move numbers
    body = re.sub(r"(1-0|0-1|1/2-1/2|\*)\s*$", "", body.strip())
    tokens = [t for t in body.split() if t]
    return " ".join(tokens[:plies])


# --------------------------------------------------------------------------- #
# Terminal chart helpers
# --------------------------------------------------------------------------- #

_BLOCKS = " ▏▎▍▌▋▊▉█"
_SPARKS = "▁▂▃▄▅▆▇█"


def bar(value: float, maximum: float, width: int = 24) -> str:
    """Build a smooth Unicode bar using eighth-block characters."""
    if maximum <= 0 or value <= 0:
        return ""
    exact = max(0.0, min(float(width), value / maximum * width))
    full = int(exact)
    remainder = exact - full
    partial = _BLOCKS[int(remainder * 8)] if full < width else ""
    rendered = ("█" * full) + partial
    return rendered if rendered.strip() else "▏"


def sparkline(values: Sequence[float]) -> str:
    """Render a compact single-line trend for a series of values."""
    numbers = [float(v) for v in values]
    if not numbers:
        return ""
    low, high = min(numbers), max(numbers)
    if high == low:
        return _SPARKS[3] * len(numbers)
    span = high - low
    return "".join(_SPARKS[int((v - low) / span * (len(_SPARKS) - 1))] for v in numbers)
