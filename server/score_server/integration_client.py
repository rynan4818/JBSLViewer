"""Read-only jbsl-web integration client. Cursor persistence belongs to the caller's DB transaction."""

from urllib.parse import urlsplit

import httpx


class ScoreFeed:
    def __init__(self, base_url: str, token: str, *, transport=None):
        parsed = urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
            raise ValueError("Invalid score server URL")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        ):
            raise ValueError("HTTPS is required outside loopback")
        self.client = httpx.Client(
            base_url=base_url.rstrip("/") + "/",
            timeout=15,
            trust_env=False,
            follow_redirects=False,
            transport=transport,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
        )

    def page(self, after: int, *, league_id: int | None = None, limit=100):
        params = {"after": after, "limit": limit}
        if league_id is not None:
            params["leagueId"] = league_id
        response = self.client.get("integration/v1/changes", params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("schemaVersion") != 1 or not isinstance(data.get("items"), list):
            raise ValueError("Unsupported changes response")
        return data

    def consume_page(self, after: int, commit_page, *, league_id=None):
        """commit_page(events, next_cursor) MUST atomically upsert events and save next_cursor.

        If the callback raises, no acknowledgement is sent and this page remains replayable.
        On Django use transaction.atomic() around the upserts AND cursor update.
        """
        page = self.page(after, league_id=league_id)
        commit_page(page["items"], page["nextCursor"])
        return page["nextCursor"], page["hasMore"]

    def leaderboard(self, league_id: int):
        if type(league_id) is not int or league_id <= 0:
            raise ValueError("league_id must be positive")
        response = self.client.get(f"integration/v1/leagues/{league_id}/leaderboard")
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
