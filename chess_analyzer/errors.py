"""Exception types used across the analyzer.

Every error raised by the client/analyzer layers derives from
``AnalyzerError`` so the CLI can show a friendly message instead of a raw
traceback.
"""

from __future__ import annotations


class AnalyzerError(Exception):
    """Base class for all expected, user-facing errors."""

    hints: tuple[str, ...] = ()

    def __init__(self, message: str, hints: tuple[str, ...] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if hints is not None:
            self.hints = hints


class InvalidInputError(AnalyzerError):
    """Raised when a username or option cannot be parsed."""


class NetworkError(AnalyzerError):
    """Raised when Chess.com cannot be reached at all."""

    hints = (
        "Check that your machine is online",
        "Check proxy / firewall settings",
        "Try again in a few seconds",
    )


class NotFoundError(AnalyzerError):
    """Raised when a player does not exist (HTTP 404)."""

    hints = (
        "Check the spelling of the Chess.com username",
        "Usernames are case-insensitive but must exist exactly on Chess.com",
        "The account may have been closed or renamed",
    )


class RateLimitError(AnalyzerError):
    """Raised for HTTP 429 - too many parallel requests."""

    hints = (
        "Chess.com's public API has no hard hourly cap for sequential requests",
        "429 usually means requests arrived too close together",
        "Wait a few seconds and try again",
    )


class APIError(AnalyzerError):
    """Raised for any other non-success HTTP response."""
