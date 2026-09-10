from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from opentelemetry.trace import StatusCode

from sleeper_tui.config import cache_dir
from sleeper_tui.telemetry import parameterize_path, trace_http_client, trace_operation

BASE_URL = "https://api.sleeper.app/v1"
PLAYERS_TTL_SECONDS = 24 * 60 * 60


class SleeperError(RuntimeError):
    pass


class UserNotFound(SleeperError):
    pass


class SleeperClient:
    def __init__(self, cache: Path | None = None) -> None:
        self.cache = cache or cache_dir()
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=45.0,
            headers={"User-Agent": "sleeper-tui/0.1"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        template = parameterize_path(path)
        with trace_http_client("GET", template) as span:
            try:
                response = await self._http.get(path, params=params)
                span.set_attribute("http.response.status_code", response.status_code)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                span.set_attribute("http.response.status_code", exc.response.status_code)
                span.set_status(StatusCode.ERROR, f"HTTPStatusError: {exc.response.status_code} for {template}")
                if exc.response.status_code == 404:
                    raise SleeperError(f"Sleeper returned 404 for {template}") from exc
                raise SleeperError(f"Sleeper request failed ({exc.response.status_code})") from exc
            except httpx.HTTPError as exc:
                raise SleeperError(f"Could not reach Sleeper: {exc}") from exc
            return response.json()

    async def user(self, username_or_id: str) -> dict[str, Any]:
        data = await self._get(f"/user/{username_or_id}")
        if not data or not data.get("user_id"):
            raise UserNotFound("No Sleeper user found for that username")
        return data

    async def nfl_state(self) -> dict[str, Any]:
        return await self._get("/state/nfl")

    async def leagues(self, user_id: str, season: str) -> list[dict[str, Any]]:
        return await self._get(f"/user/{user_id}/leagues/nfl/{season}")

    async def league(self, league_id: str) -> dict[str, Any]:
        return await self._get(f"/league/{league_id}")

    async def rosters(self, league_id: str) -> list[dict[str, Any]]:
        return await self._get(f"/league/{league_id}/rosters")

    async def users(self, league_id: str) -> list[dict[str, Any]]:
        return await self._get(f"/league/{league_id}/users")

    async def matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        return await self._get(f"/league/{league_id}/matchups/{week}")

    async def stats(self, season: str, week: int) -> dict[str, Any]:
        return await self._get(f"/stats/nfl/regular/{season}/{week}")

    async def projections(self, season: str, week: int) -> dict[str, Any]:
        return await self._get(f"/projections/nfl/regular/{season}/{week}")

    async def players(self) -> dict[str, Any]:
        path = self.cache / "players-nfl.json"
        cached = path.exists() and time.time() - path.stat().st_mtime < PLAYERS_TTL_SECONDS
        with trace_operation("load players") as span:
            span.set_attribute("sleeper.cache.hit", cached)
            if cached:
                return json.loads(path.read_text())
            data = await self._get("/players/nfl")
            path.write_text(json.dumps(data))
            return data

    async def player_news(self, player_id: str, limit: int = 8) -> list[dict[str, Any]]:
        template = "/players/nfl/{player_id}/news"
        with trace_operation("load player news") as operation:
            operation.set_attribute("sleeper.player.id", player_id)
            with trace_http_client("GET", template) as span:
                try:
                    response = await self._http.get(
                        f"https://api.sleeper.app/players/nfl/{player_id}/news",
                        params={"limit": limit},
                    )
                    span.set_attribute("http.response.status_code", response.status_code)
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise SleeperError(f"Could not load player news: {exc}") from exc
                data = response.json()
                items = data if isinstance(data, list) else []
                operation.set_attribute("sleeper.news.count", len(items))
                return items
