from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text

from sleeper_tui.app import PlayerScreen, SleeperApp
from sleeper_tui.config import AppConfig
from sleeper_tui.domain import injury_line


LEAGUE = {
    "name": "Test League",
    "league_id": "L1",
    "status": "in_season",
    "roster_positions": ["QB", "RB", "BN"],
    "scoring_settings": {"rec": 1},
}

ROSTERS = [
    {
        "roster_id": 1,
        "owner_id": "u1",
        "starters": ["10"],
        "players": ["10", "11"],
        "reserve": [],
        "settings": {"wins": 1, "losses": 0},
    },
    {
        "roster_id": 2,
        "owner_id": "u2",
        "starters": ["20"],
        "players": ["20"],
        "reserve": [],
        "settings": {"wins": 0, "losses": 1},
    },
    {
        "roster_id": 3,
        "owner_id": "u3",
        "starters": ["30"],
        "players": ["30"],
        "reserve": [],
        "settings": {"wins": 2, "losses": 0},
    },
    {
        "roster_id": 4,
        "owner_id": "u4",
        "starters": ["40"],
        "players": ["40"],
        "reserve": [],
        "settings": {"wins": 0, "losses": 2},
    },
]

USERS = [
    {"user_id": "u1", "display_name": "Kelly", "metadata": {"team_name": "Gridiron"}},
    {"user_id": "u2", "display_name": "Sam", "metadata": {}},
    {"user_id": "u3", "display_name": "Ava", "metadata": {"team_name": "Night Owls"}},
    {"user_id": "u4", "display_name": "Bo", "metadata": {}},
]

MATCHUPS = [
    {
        "roster_id": 1,
        "matchup_id": 1,
        "starters": ["10"],
        "players": ["10", "11"],
        "points": 22.0,
        "players_points": {"10": 22.0, "11": 3.0},
    },
    {
        "roster_id": 2,
        "matchup_id": 1,
        "starters": ["20"],
        "players": ["20"],
        "points": 11.0,
        "players_points": {"20": 11.0},
    },
    {
        "roster_id": 3,
        "matchup_id": 2,
        "starters": ["30"],
        "players": ["30"],
        "points": 8.0,
        "players_points": {"30": 8.0},
    },
    {
        "roster_id": 4,
        "matchup_id": 2,
        "starters": ["40"],
        "players": ["40"],
        "points": 15.0,
        "players_points": {"40": 15.0},
    },
]

PLAYERS = {
    "10": {
        "full_name": "Josh Allen",
        "team": "BUF",
        "position": "QB",
        "number": 17,
        "status": "Active",
        "injury_status": None,
        "age": 30,
        "years_exp": 8,
        "depth_chart_order": 1,
    },
    "11": {"full_name": "Bench Guy", "team": "MIA", "position": "WR", "status": "Active"},
    "20": {"full_name": "Patrick Mahomes", "team": "KC", "position": "QB", "status": "Active"},
    "30": {"full_name": "Lamar Jackson", "team": "BAL", "position": "QB", "status": "Active"},
    "40": {"full_name": "Jalen Hurts", "team": "PHI", "position": "QB", "status": "Active"},
}


class FakeClient:
    async def aclose(self) -> None:
        return None

    async def user(self, username_or_id: str) -> dict[str, Any]:
        return {"username": username_or_id, "user_id": "u1", "display_name": username_or_id}

    async def nfl_state(self) -> dict[str, Any]:
        return {"week": 1, "display_week": 1, "league_season": "2026", "season": "2026"}

    async def leagues(self, user_id: str, season: str) -> list[dict[str, Any]]:
        return [LEAGUE]

    async def league(self, league_id: str) -> dict[str, Any]:
        return LEAGUE

    async def rosters(self, league_id: str) -> list[dict[str, Any]]:
        return ROSTERS

    async def users(self, league_id: str) -> list[dict[str, Any]]:
        return USERS

    async def matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        return MATCHUPS

    async def stats(self, season: str, week: int) -> dict[str, Any]:
        return {
            "10": {"gp": 1, "pts_ppr": 22.0},
            "11": {"gp": 1, "pts_ppr": 3.0},
            "20": {"gp": 1, "pts_ppr": 11.0},
            "30": {"gp": 1, "pts_ppr": 8.0},
            "40": {"gp": 1, "pts_ppr": 15.0},
        }

    async def projections(self, season: str, week: int) -> dict[str, Any]:
        return {
            "10": {"pts_ppr": 20.1},
            "11": {"pts_ppr": 8.0},
            "20": {"pts_ppr": 19.4},
            "30": {"pts_ppr": 21.0},
            "40": {"pts_ppr": 18.0},
        }

    async def players(self) -> dict[str, Any]:
        return PLAYERS

    async def player_news(self, player_id: str, limit: int = 8) -> list[dict[str, Any]]:
        return [
            {
                "source": "rotowire",
                "published": 1788556909000,
                "metadata": {
                    "title": "Josh Allen - Logs one appearance in preseason",
                    "description": "Allen made one appearance during the Bills' three-game preseason schedule.",
                    "analysis": "He looks ready for Week 1.",
                },
            }
        ]


def _plain(cell: object) -> str:
    if isinstance(cell, Text):
        return cell.plain
    return str(cell)


def test_app_renders_lineup_and_matchup(tmp_path) -> None:
    app = SleeperApp(
        config=AppConfig(username="kelly", user_id="u1", league_id="L1"),
        client=FakeClient(),  # type: ignore[arg-type]
        config_path=tmp_path / "config.json",
    )

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view is not None
            assert app.view.mine.starters[0].name == "Josh Allen"
            josh = app.query_one("#you-starters").get_row_at(0)
            assert _plain(josh[1]) == "Josh Allen"
            assert _plain(josh[3]) == "20.1"
            assert _plain(josh[4]) == "22.0"
            assert _plain(app.query_one("#opp-starters").get_row_at(0)[1]) == "Patrick Mahomes"
            assert _plain(app.query_one("#you-bench").get_row_at(0)[1]) == "Bench Guy"

    asyncio.run(run())


def test_selecting_player_opens_status_and_news(tmp_path) -> None:
    app = SleeperApp(
        config=AppConfig(username="kelly", user_id="u1", league_id="L1"),
        client=FakeClient(),  # type: ignore[arg-type]
        config_path=tmp_path / "config.json",
    )

    async def run() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#you-starters")
            table.focus()
            table.action_select_cursor()
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert isinstance(app.screen, PlayerScreen)
            assert app.screen.status.name == "Josh Allen"
            assert injury_line(app.screen.status) == "Healthy"
            assert app.screen.status.actual_points == 22.0
            assert app.screen.status.projected_points == 20.1
            news = app.screen.query_one("#player-news")
            assert "Logs one appearance" in _plain(getattr(news, "renderable", None) or news.render())
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, PlayerScreen)

    asyncio.run(run())


def test_week_scoreboard_and_matchup_switch(tmp_path) -> None:
    app = SleeperApp(
        config=AppConfig(username="kelly", user_id="u1", league_id="L1"),
        client=FakeClient(),  # type: ignore[arg-type]
        config_path=tmp_path / "config.json",
    )

    async def run() -> None:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.view is not None
            assert app.view.mine.team_name == "Gridiron"
            app.action_toggle_slate()
            await pilot.pause()
            assert app.query_one("#slate").display
            slate = app.query_one("#week-slate")
            assert slate.row_count == 2
            assert _plain(slate.get_row_at(0)[0]) == "Gridiron"
            assert _plain(slate.get_row_at(1)[0]) == "Night Owls"
            app.action_next_matchup()
            await pilot.pause()
            assert app.view.mine.team_name == "Night Owls"
            assert _plain(app.query_one("#you-starters").get_row_at(0)[1]) == "Lamar Jackson"
            app.action_toggle_slate()
            await pilot.pause()
            assert not app.query_one("#slate").display
            app.action_prev_matchup()
            await pilot.pause()
            assert app.view.mine.team_name == "Gridiron"

    asyncio.run(run())
