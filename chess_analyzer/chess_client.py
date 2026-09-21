"""Thin, defensive wrapper around the Chess.com Published-Data API.

The API needs no key, no signup, and no authentication of any kind. Chess.com
asks only that requests be made serially (not in parallel) and carry a
descriptive ``User-Agent``. This client honours both: one session, one
request at a time, every failure mapped onto a typed :mod:`.errors` exception.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import API_BASE_URL, REQUEST_TIMEOUT, USER_AGENT
from .errors import APIError, NetworkError, NotFoundError, RateLimitError

logger = logging.getLogger(__name__)

JSONDict = dict[str, Any]


class ChessClient:
    """Client for the public Chess.com Published-Data API."""

    def __init__(self, timeout: tuple[float, float] | None = None) -> None:
        self.timeout = timeout or REQUEST_TIMEOUT
        self.requests_made = 0
        self._cache: dict[str, Any] = {}

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })

    # ------------------------------------------------------------------ #
    # Low-level request handling
    # ------------------------------------------------------------------ #

    def _get(self, path_or_url: str) -> requests.Response:
        """Perform one GET request and translate errors into exceptions."""
        url = path_or_url if path_or_url.startswith("http") else f"{API_BASE_URL}{path_or_url}"
        logger.debug("GET %s", url)

        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.exceptions.Timeout as exc:
            raise NetworkError(
                "Chess.com did not respond in time.",
                hints=("The connection may be slow", "Try again in a few moments"),
            ) from exc
        except requests.exceptions.SSLError as exc:
            raise NetworkError(
                "The secure connection to Chess.com failed.",
                hints=("A proxy or antivirus may be intercepting HTTPS traffic",),
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError("Could not reach api.chess.com.") from exc
        except requests.exceptions.RequestException as exc:  # pragma: no cover
            raise NetworkError(f"Network request failed: {exc}") from exc

        self.requests_made += 1
        self._raise_for_status(response, url)
        return response

    @staticmethod
    def _raise_for_status(response: requests.Response, url: str) -> None:
        """Map a non-success HTTP status onto a typed exception."""
        status = response.status_code
        if status < 400:
            return
        if status == 404:
            raise NotFoundError("The requested Chess.com resource does not exist.")
        if status == 410:
            raise NotFoundError(
                "This resource is permanently unavailable on Chess.com.",
                hints=("The account or archive may have been removed",),
            )
        if status == 429:
            raise RateLimitError("Chess.com throttled this request (429 Too Many Requests).")
        if status >= 500:
            raise APIError(
                f"Chess.com returned a server error ({status}).",
                hints=("This is a problem on Chess.com's side",),
            )
        raise APIError(f"Unexpected response from Chess.com ({status}) for {url}.")

    def get_json(self, path_or_url: str, cache: bool = True) -> Any:
        """GET a single JSON document, optionally served from cache."""
        if cache and path_or_url in self._cache:
            return self._cache[path_or_url]
        data = self._get(path_or_url).json()
        if cache:
            self._cache[path_or_url] = data
        return data

    # ------------------------------------------------------------------ #
    # Player endpoints
    # ------------------------------------------------------------------ #

    def get_player(self, username: str) -> JSONDict:
        """Fetch a player's public profile."""
        try:
            return self.get_json(f"/player/{username}")
        except NotFoundError as exc:
            raise NotFoundError(
                f"Chess.com player '{username}' was not found.",
                hints=(
                    "Check the spelling of the username",
                    "The account may have been closed or never existed",
                ),
            ) from exc

    def get_player_stats(self, username: str) -> JSONDict:
        """Fetch a player's ratings and win/loss record, per game type."""
        try:
            return self.get_json(f"/player/{username}/stats")
        except NotFoundError:
            return {}

    def get_archive_urls(self, username: str) -> list[str]:
        """List every monthly archive URL available for this player."""
        try:
            data = self.get_json(f"/player/{username}/games/archives")
        except NotFoundError:
            return []
        return list(data.get("archives", [])) if isinstance(data, dict) else []

    def get_archive_games(self, archive_url: str) -> list[JSONDict]:
        """Fetch every finished game in one monthly archive."""
        try:
            data = self.get_json(archive_url)
        except (NotFoundError, APIError):
            return []
        return list(data.get("games", [])) if isinstance(data, dict) else []

    def get_daily_puzzle(self) -> JSONDict:
        """Fetch today's Chess.com daily puzzle."""
        return self.get_json("/puzzle", cache=False)

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> "ChessClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
