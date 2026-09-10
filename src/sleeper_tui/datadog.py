"""Publish Sleeper league snapshots as Datadog custom metrics and a dashboard."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx

from sleeper_tui.domain import LeagueWeek, TeamView

DASHBOARD_TITLE = "Sleeper fantasy football"
GAUGE = 3
SERIES_CHUNK = 400
HOST_RESOURCE = [{"name": "sleeper-tui", "type": "host"}]

_TAG_UNSAFE = re.compile(r"[^a-z0-9_./-]+")


def tag_value(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    text = _TAG_UNSAFE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_.")
    return text[:200] or "unknown"


def metric_tags(**pairs: Any) -> list[str]:
    tags = [f"{key}:{tag_value(value)}" for key, value in pairs.items() if value is not None and value != ""]
    tags.append("service:sleeper-tui")
    return tags


def week_timestamp(week: int, *, current_week: int, now: datetime) -> int:
    """Stable Thursday 20:00 UTC for past weeks; `now` for the live week."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    if week == current_week:
        return int(now.timestamp())
    days_since_thursday = (now.weekday() - 3) % 7
    this_thursday = now.replace(hour=20, minute=0, second=0, microsecond=0) - timedelta(days=days_since_thursday)
    return int((this_thursday - timedelta(weeks=current_week - week)).timestamp())


def season_points(settings: dict[str, Any] | None, prefix: str = "fpts") -> float:
    settings = settings or {}
    whole = float(settings.get(prefix) or 0)
    decimal = settings.get(f"{prefix}_decimal")
    if decimal is None:
        return whole
    return whole + float(decimal) / 100.0


def _point(metric: str, value: float | int, timestamp: int, tags: list[str]) -> dict[str, Any]:
    return {
        "metric": metric,
        "type": GAUGE,
        "points": [{"timestamp": timestamp, "value": float(value)}],
        "tags": tags,
        "resources": HOST_RESOURCE,
    }


def _team_tags(league_week: LeagueWeek, team: TeamView, **extra: Any) -> list[str]:
    return metric_tags(
        league=league_week.league_name,
        league_id=league_week.league_id,
        season=league_week.season,
        team=team.team_name,
        roster_id=team.roster_id,
        **extra,
    )


def series_from_snapshot(
    week: LeagueWeek,
    *,
    rosters: list[dict[str, Any]],
    historical: dict[int, list[dict[str, Any]]],
    current_week: int,
    now: datetime,
) -> list[dict[str, Any]]:
    live_ts = week_timestamp(current_week, current_week=current_week, now=now)
    series: list[dict[str, Any]] = [
        _point(
            "sleeper.nfl.week",
            current_week,
            live_ts,
            metric_tags(league=week.league_name, league_id=week.league_id, season=week.season),
        )
    ]

    rosters_by_id = {int(item["roster_id"]): item for item in rosters if item.get("roster_id") is not None}
    for team in week.teams.values():
        settings = (rosters_by_id.get(team.roster_id) or {}).get("settings") or {}
        tags = _team_tags(week, team)
        series.append(_point("sleeper.team.wins", int(settings.get("wins") or 0), live_ts, tags))
        series.append(_point("sleeper.team.losses", int(settings.get("losses") or 0), live_ts, tags))
        series.append(_point("sleeper.team.ties", int(settings.get("ties") or 0), live_ts, tags))
        series.append(_point("sleeper.team.points_for", season_points(settings, "fpts"), live_ts, tags))
        series.append(_point("sleeper.team.points_against", season_points(settings, "fpts_against"), live_ts, tags))

        live_tags = _team_tags(week, team, week=week.week)
        series.append(_point("sleeper.team.week_points", team.points, live_ts, live_tags))
        if team.proj_total is not None:
            series.append(_point("sleeper.team.week_projected", team.proj_total, live_ts, live_tags))

        for row in team.starters:
            if row.empty:
                continue
            player_tags = _team_tags(
                week,
                team,
                week=week.week,
                player=row.name,
                position=row.position,
                nfl_team=row.team,
                slot=row.slot,
            )
            if row.actual is not None:
                series.append(_point("sleeper.player.week_points", row.actual, live_ts, player_tags))
            if row.projected is not None:
                series.append(_point("sleeper.player.week_projected", row.projected, live_ts, player_tags))

    for summary in week.slate:
        if summary.right is None:
            continue
        match_tags = metric_tags(
            league=week.league_name,
            league_id=week.league_id,
            season=week.season,
            week=week.week,
            matchup=f"{summary.left.team_name} vs {summary.right.team_name}",
            home=summary.left.team_name,
            away=summary.right.team_name,
        )
        series.append(_point("sleeper.matchup.home_points", summary.left.points, live_ts, match_tags))
        series.append(_point("sleeper.matchup.away_points", summary.right.points, live_ts, match_tags))

    teams_by_roster = {roster_id: team.team_name for roster_id, team in week.teams.items()}
    for past_week, matchups in historical.items():
        if past_week == current_week:
            continue
        ts = week_timestamp(past_week, current_week=current_week, now=now)
        for item in matchups:
            roster_id = item.get("roster_id")
            if roster_id is None or item.get("points") is None:
                continue
            name = teams_by_roster.get(int(roster_id), f"Roster {roster_id}")
            tags = metric_tags(
                league=week.league_name,
                league_id=week.league_id,
                season=week.season,
                team=name,
                roster_id=roster_id,
                week=past_week,
            )
            series.append(_point("sleeper.team.week_points", float(item["points"]), ts, tags))
    return series


def dashboard_payload(league_name: str) -> dict[str, Any]:
    scope = "$league"
    return {
        "title": DASHBOARD_TITLE,
        "description": "League standings, weekly matchups, and starter scores from the Sleeper API. Refresh with `sleeper-tui publish`.",
        "layout_type": "ordered",
        "reflow_type": "auto",
        "template_variables": [
            {"name": "league", "prefix": "league", "available_values": [], "default": tag_value(league_name)},
        ],
        "widgets": [
            _note_widget(
                "Sleeper fantasy",
                "Custom metrics from `sleeper-tui publish`. Use the **league** variable to switch leagues. "
                "Re-run publish (or cron it) to refresh scores. Time range **Past 2 months** shows the season chart.",
            ),
            _query_value("NFL week", f"max:sleeper.nfl.week{{{scope}}}"),
            _table(
                "Standings",
                [
                    ("wins", f"max:sleeper.team.wins{{{scope}}} by {{team}}"),
                    ("losses", f"max:sleeper.team.losses{{{scope}}} by {{team}}"),
                    ("PF", f"max:sleeper.team.points_for{{{scope}}} by {{team}}"),
                    ("PA", f"max:sleeper.team.points_against{{{scope}}} by {{team}}"),
                ],
                sort="wins",
            ),
            _table(
                "This week's scores",
                [
                    ("pts", f"max:sleeper.team.week_points{{{scope}}} by {{team}}"),
                    ("proj", f"max:sleeper.team.week_projected{{{scope}}} by {{team}}"),
                ],
            ),
            _table(
                "Matchups",
                [
                    ("home", f"max:sleeper.matchup.home_points{{{scope}}} by {{matchup}}"),
                    ("away", f"max:sleeper.matchup.away_points{{{scope}}} by {{matchup}}"),
                ],
                sort="home",
            ),
            _timeseries("Weekly team scores", f"max:sleeper.team.week_points{{{scope}}} by {{team}}"),
            _table(
                "Starters this week",
                [
                    ("pts", f"max:sleeper.player.week_points{{{scope}}} by {{player,position,team}}"),
                    ("proj", f"max:sleeper.player.week_projected{{{scope}}} by {{player,position,team}}"),
                ],
            ),
            _toplist("Top scorers", f"top(max:sleeper.player.week_points{{{scope}}} by {{player}}, 10, 'max', 'desc')"),
        ],
    }


def _widget(definition: dict[str, Any]) -> dict[str, Any]:
    # reflow_type=auto rejects layout; Datadog places widgets itself.
    return {"definition": definition}


def _note_widget(title: str, text: str) -> dict[str, Any]:
    return _widget(
        {
            "type": "note",
            "content": f"### {title}\n\n{text}",
            "background_color": "navy",
            "font_size": "14",
            "show_tick": False,
        }
    )


def _query_value(title: str, query: str) -> dict[str, Any]:
    return _widget(
        {
            "title": title,
            "type": "query_value",
            "autoscale": False,
            "precision": 0,
            "requests": [
                {
                    "queries": [
                        {
                            "data_source": "metrics",
                            "name": "query1",
                            "query": query,
                            "aggregator": "max",
                        }
                    ],
                    "formulas": [{"formula": "query1"}],
                    "response_format": "scalar",
                }
            ],
        }
    )


def _metric_query(name: str, query: str) -> dict[str, Any]:
    return {
        "data_source": "metrics",
        "name": name,
        "query": query,
        "aggregator": "max",
    }


def _table(
    title: str,
    columns: list[tuple[str, str]],
    *,
    sort: str = "pts",
) -> dict[str, Any]:
    queries = [_metric_query(f"query{index}", query) for index, (_, query) in enumerate(columns, start=1)]
    return _widget(
        {
            "title": title,
            "type": "query_table",
            "has_search_bar": "auto",
            "requests": [
                {
                    "queries": queries,
                    "formulas": [{"formula": f"query{i}", "alias": alias} for i, (alias, _) in enumerate(columns, start=1)],
                    "sort": {
                        "count": 20,
                        "order_by": [
                            {
                                "type": "formula",
                                "index": next((i for i, (alias, _) in enumerate(columns) if alias == sort), 0),
                                "order": "desc",
                            }
                        ],
                    },
                    "response_format": "scalar",
                }
            ],
        }
    )


def _timeseries(title: str, query: str) -> dict[str, Any]:
    return _widget(
        {
            "title": title,
            "type": "timeseries",
            "requests": [
                {
                    "queries": [_metric_query("query1", query)],
                    "formulas": [{"formula": "query1"}],
                    "response_format": "timeseries",
                    "display_type": "line",
                }
            ],
        }
    )


def _toplist(title: str, query: str) -> dict[str, Any]:
    return _widget(
        {
            "title": title,
            "type": "toplist",
            "requests": [
                {
                    "queries": [_metric_query("query1", query)],
                    "formulas": [{"formula": "query1"}],
                    "response_format": "scalar",
                    "sort": {"count": 10, "order_by": [{"type": "formula", "index": 0, "order": "desc"}]},
                }
            ],
        }
    )


@dataclass(frozen=True)
class DatadogSite:
    api_key: str
    app_key: str
    site: str = "datadoghq.com"

    @property
    def api_base(self) -> str:
        return f"https://api.{self.site}"

    @property
    def app_base(self) -> str:
        return f"https://app.{self.site}"

    def dashboard_url(self, dashboard_id: str) -> str:
        return f"{self.app_base}/dashboard/{quote(dashboard_id)}"

    @classmethod
    def from_env(cls, site: str | None = None) -> DatadogSite:
        api_key = os.environ.get("DD_API_KEY", "").strip()
        app_key = os.environ.get("DD_APP_KEY", "").strip()
        if not api_key or not app_key:
            raise DatadogConfigError(
                "Set DD_API_KEY and DD_APP_KEY to publish a dashboard. "
                "Create an app key at Organization Settings → Application Keys."
            )
        return cls(api_key=api_key, app_key=app_key, site=(site or os.environ.get("DD_SITE") or "datadoghq.com").strip())


class DatadogConfigError(RuntimeError):
    pass


class DatadogClient:
    def __init__(self, site: DatadogSite, client: httpx.Client | None = None) -> None:
        self.site = site
        self._http = client or httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def _headers(self) -> dict[str, str]:
        return {
            "DD-API-KEY": self.site.api_key,
            "DD-APPLICATION-KEY": self.site.app_key,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._http.request(method, f"{self.site.api_base}{path}", headers=self._headers(), **kwargs)
        if response.status_code >= 400:
            detail = response.text[:300].replace(self.site.api_key, "***").replace(self.site.app_key, "***")
            raise DatadogConfigError(f"Datadog {method} {path} failed ({response.status_code}): {detail}")
        return response

    def submit_series(self, series: list[dict[str, Any]]) -> int:
        sent = 0
        for index in range(0, len(series), SERIES_CHUNK):
            chunk = series[index : index + SERIES_CHUNK]
            self._request("POST", "/api/v2/series", json={"series": chunk})
            sent += len(chunk)
        return sent

    def upsert_dashboard(self, payload: dict[str, Any]) -> str:
        existing = self._find_dashboard(payload["title"])
        if existing:
            self._request("PUT", f"/api/v1/dashboard/{existing}", json=payload)
            return existing
        created = self._request("POST", "/api/v1/dashboard", json=payload).json()
        return str(created["id"])

    def _find_dashboard(self, title: str) -> str | None:
        data = self._request("GET", "/api/v1/dashboard").json()
        for item in data.get("dashboards") or []:
            if item.get("title") == title:
                return str(item["id"])
        return None

