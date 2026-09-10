"""Pull Sleeper league data and publish a Datadog dashboard."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from typing import Any

from sleeper_tui.api import SleeperClient, SleeperError, UserNotFound
from sleeper_tui.config import AppConfig
from sleeper_tui.datadog import (
    DatadogClient,
    DatadogConfigError,
    DatadogSite,
    dashboard_payload,
    series_from_snapshot,
)
from sleeper_tui.domain import build_league_week, find_roster


async def load_snapshot(
    client: SleeperClient,
    *,
    username: str,
    league_id: str | None,
    week: int | None,
) -> tuple[Any, list[dict[str, Any]], dict[int, list[dict[str, Any]]], int]:
    user, state, players = await asyncio.gather(
        client.user(username),
        client.nfl_state(),
        client.players(),
    )
    user_id = user["user_id"]
    season = str(state.get("league_season") or state.get("season") or "")
    current_week = week or int(state.get("display_week") or state.get("week") or 1)
    leagues = await client.leagues(user_id, season)
    if not leagues:
        raise SleeperError(f"No NFL leagues for that user in {season}.")

    selected = None
    if league_id:
        selected = next((item for item in leagues if item.get("league_id") == league_id), None)
    if selected is None:
        selected = next((item for item in leagues if item.get("status") == "in_season"), leagues[0])
    league_id = str(selected["league_id"])

    league, rosters, users, live_matchups, stats, projections = await asyncio.gather(
        client.league(league_id),
        client.rosters(league_id),
        client.users(league_id),
        client.matchups(league_id, current_week),
        client.stats(season, current_week),
        client.projections(season, current_week),
    )
    if find_roster(rosters, user_id) is None:
        raise SleeperError("No roster found for this user in the selected league.")

    historical: dict[int, list[dict[str, Any]]] = {current_week: live_matchups}
    if current_week > 1:
        past = await asyncio.gather(*(client.matchups(league_id, past_week) for past_week in range(1, current_week)))
        historical.update({past_week: payload for past_week, payload in enumerate(past, start=1)})

    snapshot = build_league_week(
        week=current_week,
        season=season,
        league=league,
        user_id=user_id,
        rosters=rosters,
        users=users,
        matchups=live_matchups,
        players=players,
        stats=stats,
        projections=projections,
    )
    return snapshot, rosters, historical, current_week


def publish_league(
    *,
    username: str | None,
    league_id: str | None,
    week: int | None,
    site: str | None,
    dry_run: bool,
) -> int:
    config = AppConfig.load()
    name = username or config.username
    if not name:
        raise SystemExit("Pass --username or run the TUI once so a username is saved.")

    async def _load():
        client = SleeperClient()
        try:
            return await load_snapshot(client, username=name, league_id=league_id or config.league_id or None, week=week)
        finally:
            await client.aclose()

    try:
        snapshot, rosters, historical, current_week = asyncio.run(_load())
    except UserNotFound:
        raise SystemExit("No Sleeper user found for that username.") from None
    except SleeperError as exc:
        raise SystemExit(str(exc)) from exc

    series = series_from_snapshot(
        snapshot,
        rosters=rosters,
        historical=historical,
        current_week=current_week,
        now=datetime.now(timezone.utc),
    )
    dashboard = dashboard_payload(snapshot.league_name)
    if dry_run:
        print(f"{snapshot.league_name} · {snapshot.season} week {snapshot.week}")
        print(f"{len(series)} Datadog metrics ready")
        print(f"Dashboard title: {dashboard['title']}")
        return 0

    try:
        creds = DatadogSite.from_env(site)
    except DatadogConfigError as exc:
        raise SystemExit(str(exc)) from exc

    client = DatadogClient(creds)
    try:
        sent = client.submit_series(series)
        dashboard_id = client.upsert_dashboard(dashboard)
    except DatadogConfigError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        client.close()

    print(f"Published {sent} metrics for {snapshot.league_name} week {snapshot.week}")
    print(creds.dashboard_url(dashboard_id))
    return 0


def add_publish_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-u", "--username", help="Sleeper username")
    parser.add_argument("-l", "--league", help="League ID")
    parser.add_argument("-w", "--week", type=int, help="Week number")
    parser.add_argument("--site", help="Datadog site (default DD_SITE or datadoghq.com)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch Sleeper and build metrics without calling Datadog")


def publish_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sleeper-tui publish",
        description="Push Sleeper league rankings, matchups, and players to your Datadog account",
    )
    add_publish_parser(parser)
    args = parser.parse_args(argv)
    return publish_league(
        username=args.username,
        league_id=args.league,
        week=args.week,
        site=args.site,
        dry_run=args.dry_run,
    )
