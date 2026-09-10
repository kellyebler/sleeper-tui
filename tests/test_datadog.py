from datetime import datetime, timezone

from sleeper_tui.datadog import (
    DASHBOARD_TITLE,
    dashboard_payload,
    season_points,
    series_from_snapshot,
    tag_value,
    week_timestamp,
)
from sleeper_tui.domain import build_league_week


LEAGUE = {
    "name": "Test League",
    "league_id": "L1",
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
        "settings": {"wins": 1, "losses": 0, "fpts": 112, "fpts_decimal": 40, "fpts_against": 90, "fpts_against_decimal": 10},
    },
    {
        "roster_id": 2,
        "owner_id": "u2",
        "starters": ["20"],
        "players": ["20"],
        "reserve": [],
        "settings": {"wins": 0, "losses": 1, "fpts": 90, "fpts_against": 112},
    },
]

USERS = [
    {"user_id": "u1", "display_name": "Kelly", "metadata": {"team_name": "Gridiron"}},
    {"user_id": "u2", "display_name": "Sam", "metadata": {}},
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
]

PLAYERS = {
    "10": {"full_name": "Josh Allen", "team": "BUF", "position": "QB"},
    "11": {"full_name": "Bench Guy", "team": "MIA", "position": "WR"},
    "20": {"full_name": "Patrick Mahomes", "team": "KC", "position": "QB"},
}

STATS = {
    "10": {"gp": 1, "pts_ppr": 22.0},
    "20": {"gp": 1, "pts_ppr": 11.0},
}

PROJECTIONS = {
    "10": {"pts_ppr": 20.1},
    "20": {"pts_ppr": 18.0},
}


def _week() -> object:
    return build_league_week(
        week=2,
        season="2026",
        league=LEAGUE,
        user_id="u1",
        rosters=ROSTERS,
        users=USERS,
        matchups=MATCHUPS,
        players=PLAYERS,
        stats=STATS,
        projections=PROJECTIONS,
    )


def test_tag_value_normalizes_names():
    assert tag_value("Gridiron Goats!") == "gridiron_goats"
    assert tag_value("Josh Allen") == "josh_allen"


def test_season_points_uses_sleeper_decimal_field():
    assert season_points({"fpts": 112, "fpts_decimal": 40}) == 112.4
    assert season_points({"fpts": 90}) == 90.0


def test_week_timestamp_uses_now_for_live_week():
    now = datetime(2026, 9, 10, 18, 30, tzinfo=timezone.utc)
    assert week_timestamp(2, current_week=2, now=now) == int(now.timestamp())
    past = week_timestamp(1, current_week=2, now=now)
    assert past < int(now.timestamp())
    assert datetime.fromtimestamp(past, tz=timezone.utc).weekday() == 3


def test_series_include_standings_matchups_and_players():
    now = datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc)
    series = series_from_snapshot(
        _week(),
        rosters=ROSTERS,
        historical={1: [{"roster_id": 1, "points": 88.2}, {"roster_id": 2, "points": 70.0}]},
        current_week=2,
        now=now,
    )
    by_metric: dict[str, list[dict]] = {}
    for item in series:
        by_metric.setdefault(item["metric"], []).append(item)

    wins = next(item for item in by_metric["sleeper.team.wins"] if "team:gridiron" in item["tags"])
    assert wins["points"][0]["value"] == 1
    points_for = next(item for item in by_metric["sleeper.team.points_for"] if "team:gridiron" in item["tags"])
    assert points_for["points"][0]["value"] == 112.4

    assert any("josh_allen" in ",".join(item["tags"]) for item in by_metric["sleeper.player.week_points"])
    assert any("matchup:gridiron_vs_sam" in item["tags"] for item in by_metric["sleeper.matchup.home_points"])

    past = next(item for item in by_metric["sleeper.team.week_points"] if "week:1" in item["tags"] and "team:gridiron" in item["tags"])
    assert past["points"][0]["value"] == 88.2
    assert past["points"][0]["timestamp"] < int(now.timestamp())

    blob = str(series)
    assert "kelly" not in blob
    assert "u1" not in blob


def test_dashboard_queries_league_variable():
    payload = dashboard_payload("Test League")
    assert payload["title"] == DASHBOARD_TITLE
    titles = [widget["definition"].get("title") or widget["definition"].get("content", "") for widget in payload["widgets"]]
    assert any("Standings" in title for title in titles)
    assert any("Matchups" in title for title in titles)
    assert any("Starters" in title for title in titles)
    rendered = str(payload)
    assert "$league" in rendered
    assert "sleeper.team.wins" in rendered
    assert "sleeper.player.week_points" in rendered
    assert payload["reflow_type"] == "auto"
    assert all("layout" not in widget for widget in payload["widgets"])
