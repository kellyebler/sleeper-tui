"""Pure helpers for turning Sleeper API payloads into lineup views."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

BENCH_SLOTS = frozenset({"BN", "IR", "TAXI"})
EMPTY_IDS = frozenset({"0", "", None})

SLOT_LABELS = {
    "SUPER_FLEX": "SFLX",
    "FLEX": "FLEX",
    "REC_FLEX": "W/T",
    "WRRB_FLEX": "W/R",
    "WRRBWR": "W/R",
    "IDP_FLEX": "IDP",
    "DEF": "DEF",
}

INJURY_SHORT = {
    "Questionable": "Q",
    "Doubtful": "D",
    "Out": "O",
    "IR": "IR",
    "PUP": "PUP",
    "Suspended": "SUS",
    "NA": "NA",
    "COV": "COV",
    "DNR": "DNR",
}


@dataclass(frozen=True)
class PlayerRow:
    slot: str
    player_id: str
    name: str
    team: str
    position: str
    actual: float | None
    projected: float | None
    injury: str
    empty: bool = False


@dataclass
class TeamView:
    roster_id: int
    owner_id: str | None
    team_name: str
    record: str
    points: float
    projected: bool
    proj_total: float | None = None
    starters: list[PlayerRow] = field(default_factory=list)
    bench: list[PlayerRow] = field(default_factory=list)
    reserve: list[PlayerRow] = field(default_factory=list)


@dataclass
class MatchupView:
    week: int
    season: str
    league_name: str
    league_id: str
    mine: TeamView
    opponent: TeamView | None
    user_roster_id: int | None = None
    matchup_index: int = 1
    matchup_count: int = 1


@dataclass(frozen=True)
class MatchupSummary:
    matchup_id: int | None
    left: TeamView
    right: TeamView | None
    involves_user: bool

    @property
    def roster_ids(self) -> tuple[int, ...]:
        if self.right is None:
            return (self.left.roster_id,)
        return (self.left.roster_id, self.right.roster_id)


@dataclass
class LeagueWeek:
    week: int
    season: str
    league_name: str
    league_id: str
    user_roster_id: int | None
    slate: list[MatchupSummary]
    teams: dict[int, TeamView]

    def contains_roster(self, roster_id: int) -> bool:
        return roster_id in self.teams

    def summary_for(self, roster_id: int) -> MatchupSummary | None:
        return next((item for item in self.slate if roster_id in item.roster_ids), None)

    def view_for(self, roster_id: int) -> MatchupView:
        summary = self.summary_for(roster_id)
        if summary is None:
            raise ValueError(f"No matchup found for roster {roster_id}.")
        if summary.left.roster_id == roster_id:
            mine, opponent = summary.left, summary.right
        else:
            mine, opponent = summary.right, summary.left
        if mine is None:
            raise ValueError(f"No matchup found for roster {roster_id}.")
        index = self.slate.index(summary) + 1
        return MatchupView(
            week=self.week,
            season=self.season,
            league_name=self.league_name,
            league_id=self.league_id,
            mine=mine,
            opponent=opponent,
            user_roster_id=self.user_roster_id,
            matchup_index=index,
            matchup_count=len(self.slate),
        )


@dataclass(frozen=True)
class NewsItem:
    title: str
    description: str
    analysis: str
    source: str
    published: datetime | None
    url: str = ""


@dataclass(frozen=True)
class PlayerStatus:
    player_id: str
    name: str
    team: str
    position: str
    number: str
    roster_status: str
    injury_status: str
    injury_body_part: str
    injury_notes: str
    practice: str
    depth: str
    age: str
    years_exp: str
    news_updated: datetime | None
    actual_points: float | None = None
    projected_points: float | None = None


def starter_slots(roster_positions: list[str] | None) -> list[str]:
    return [pos for pos in roster_positions or [] if pos not in BENCH_SLOTS]


def slot_label(slot: str) -> str:
    return SLOT_LABELS.get(slot, slot)


def is_empty_id(player_id: str | None) -> bool:
    return player_id in EMPTY_IDS


def scoring_stat_key(scoring_settings: dict[str, Any] | None) -> str:
    rec = float((scoring_settings or {}).get("rec") or 0)
    if rec >= 0.75:
        return "pts_ppr"
    if rec >= 0.25:
        return "pts_half_ppr"
    return "pts_std"


def player_name(player: dict[str, Any] | None, player_id: str) -> str:
    if is_empty_id(player_id):
        return "Empty"
    if not player:
        return player_id
    full = (player.get("full_name") or "").strip()
    if full:
        return full
    first = (player.get("first_name") or "").strip()
    last = (player.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    if name:
        return name
    if player.get("position") in {"DEF", "DST"}:
        return player.get("team") or player_id
    return player_id


def player_team(player: dict[str, Any] | None, player_id: str) -> str:
    if not player:
        return player_id if player_id.isalpha() else ""
    return player.get("team") or ""


def injury_code(player: dict[str, Any] | None) -> str:
    if not player:
        return ""
    status = player.get("injury_status")
    if status:
        return INJURY_SHORT.get(status, status)
    if player.get("status") in {"Injured Reserve", "PUP", "Suspended"}:
        return INJURY_SHORT.get(player["status"], player["status"][:3].upper())
    return ""


def format_record(settings: dict[str, Any] | None) -> str:
    settings = settings or {}
    wins = int(settings.get("wins") or 0)
    losses = int(settings.get("losses") or 0)
    ties = int(settings.get("ties") or 0)
    if ties:
        return f"{wins}-{losses}-{ties}"
    return f"{wins}-{losses}"


def team_name_for(user: dict[str, Any] | None, fallback: str) -> str:
    if not user:
        return fallback
    metadata = user.get("metadata") or {}
    nickname = (metadata.get("team_name") or "").strip()
    if nickname:
        return nickname
    return user.get("display_name") or user.get("username") or fallback


def bench_ids(
    players: list[str] | None,
    starters: list[str] | None,
    reserve: list[str] | None = None,
    taxi: list[str] | None = None,
) -> list[str]:
    used = {
        pid
        for pid in (*(starters or []), *(reserve or []), *(taxi or []))
        if not is_empty_id(pid)
    }
    out: list[str] = []
    for pid in players or []:
        if is_empty_id(pid) or pid in used:
            continue
        out.append(pid)
        used.add(pid)
    return out


def projected_points(
    player_id: str,
    projections: dict[str, Any] | None,
    scoring_key: str,
) -> float | None:
    if is_empty_id(player_id):
        return None
    value = ((projections or {}).get(player_id) or {}).get(scoring_key)
    return float(value) if value is not None else None


def actual_points(
    player_id: str,
    *,
    matchup: dict[str, Any] | None,
    stats: dict[str, Any] | None,
    scoring_key: str,
) -> float | None:
    if is_empty_id(player_id):
        return None

    weekly = (stats or {}).get(player_id) or {}
    played = weekly.get("gp") or scoring_key in weekly
    match_points = (matchup or {}).get("players_points") or {}

    if played:
        if player_id in match_points and match_points[player_id] is not None:
            return float(match_points[player_id])
        value = weekly.get(scoring_key)
        return float(value) if value is not None else 0.0

    live = match_points.get(player_id)
    if live:
        return float(live)
    return None


def resolve_points(
    player_id: str,
    *,
    matchup: dict[str, Any] | None,
    stats: dict[str, Any] | None,
    projections: dict[str, Any] | None,
    scoring_key: str,
) -> tuple[float | None, float | None]:
    return (
        actual_points(player_id, matchup=matchup, stats=stats, scoring_key=scoring_key),
        projected_points(player_id, projections, scoring_key),
    )


def team_total(
    matchup: dict[str, Any] | None, starters: list[PlayerRow]
) -> tuple[float, bool, float | None]:
    proj_values = [row.projected for row in starters if row.projected is not None]
    proj_total = sum(proj_values) if proj_values else None

    if matchup and matchup.get("custom_points") is not None:
        return float(matchup["custom_points"]), False, proj_total

    actuals = [row.actual for row in starters if row.actual is not None]
    official = (matchup or {}).get("points")

    if actuals:
        if official is not None:
            return float(official), False, proj_total
        return sum(actuals), False, proj_total
    if official:
        return float(official), False, proj_total
    if proj_total is not None:
        return proj_total, True, proj_total
    return 0.0, True, None


def build_row(
    slot: str,
    player_id: str | None,
    players: dict[str, Any],
    *,
    matchup: dict[str, Any] | None,
    stats: dict[str, Any],
    projections: dict[str, Any],
    scoring_key: str,
) -> PlayerRow:
    pid = player_id or "0"
    empty = is_empty_id(pid)
    player = None if empty else players.get(pid)
    actual, projected = resolve_points(
        pid,
        matchup=matchup,
        stats=stats,
        projections=projections,
        scoring_key=scoring_key,
    )
    return PlayerRow(
        slot=slot_label(slot),
        player_id="" if empty else pid,
        name=player_name(player, pid),
        team="" if empty else player_team(player, pid),
        position="" if empty else (player or {}).get("position") or "",
        actual=actual,
        projected=projected,
        injury="" if empty else injury_code(player),
        empty=empty,
    )


def find_roster(rosters: list[dict[str, Any]], user_id: str) -> dict[str, Any] | None:
    for roster in rosters:
        if roster.get("owner_id") == user_id:
            return roster
        if user_id in (roster.get("co_owners") or []):
            return roster
    return None


def find_matchup_pair(
    matchups: list[dict[str, Any]], roster_id: int
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    mine = next((item for item in matchups if item.get("roster_id") == roster_id), None)
    if not mine:
        return None, None
    matchup_id = mine.get("matchup_id")
    opponent = next(
        (
            item
            for item in matchups
            if item.get("matchup_id") == matchup_id and item.get("roster_id") != roster_id
        ),
        None,
    )
    return mine, opponent


def build_team_view(
    *,
    roster: dict[str, Any],
    user: dict[str, Any] | None,
    matchup: dict[str, Any] | None,
    roster_positions: list[str],
    players: dict[str, Any],
    stats: dict[str, Any],
    projections: dict[str, Any],
    scoring_key: str,
) -> TeamView:
    slots = starter_slots(roster_positions)
    starter_ids = list((matchup or {}).get("starters") or roster.get("starters") or [])
    while len(starter_ids) < len(slots):
        starter_ids.append("0")

    starters = [
        build_row(
            slot,
            pid,
            players,
            matchup=matchup,
            stats=stats,
            projections=projections,
            scoring_key=scoring_key,
        )
        for slot, pid in zip(slots, starter_ids, strict=False)
    ]

    reserve_ids = [pid for pid in (roster.get("reserve") or []) if not is_empty_id(pid)]
    taxi_ids = [pid for pid in (roster.get("taxi") or []) if not is_empty_id(pid)]
    pool = (matchup or {}).get("players") or roster.get("players") or []

    bench = [
        build_row(
            (players.get(pid) or {}).get("position") or "BN",
            pid,
            players,
            matchup=matchup,
            stats=stats,
            projections=projections,
            scoring_key=scoring_key,
        )
        for pid in bench_ids(pool, starter_ids, reserve_ids, taxi_ids)
    ]
    reserve = [
        build_row(
            "IR",
            pid,
            players,
            matchup=matchup,
            stats=stats,
            projections=projections,
            scoring_key=scoring_key,
        )
        for pid in reserve_ids
    ] + [
        build_row(
            "TAXI",
            pid,
            players,
            matchup=matchup,
            stats=stats,
            projections=projections,
            scoring_key=scoring_key,
        )
        for pid in taxi_ids
    ]

    points, projected, proj_total = team_total(matchup, starters)
    return TeamView(
        roster_id=int(roster["roster_id"]),
        owner_id=roster.get("owner_id"),
        team_name=team_name_for(user, f"Roster {roster.get('roster_id')}"),
        record=format_record(roster.get("settings")),
        points=points,
        projected=projected,
        proj_total=proj_total,
        starters=starters,
        bench=bench,
        reserve=reserve,
    )


def pair_matchups(
    matchups: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    grouped: dict[int | str, list[dict[str, Any]]] = {}
    for item in matchups:
        key = item.get("matchup_id")
        if key is None:
            key = f"solo-{item.get('roster_id')}"
        grouped.setdefault(key, []).append(item)

    pairs: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for key in sorted(grouped, key=lambda item: (isinstance(item, str), item)):
        group = grouped[key]
        pairs.append((group[0], group[1] if len(group) > 1 else None))
    return pairs


def build_league_week(
    *,
    week: int,
    season: str,
    league: dict[str, Any],
    user_id: str,
    rosters: list[dict[str, Any]],
    users: list[dict[str, Any]],
    matchups: list[dict[str, Any]],
    players: dict[str, Any],
    stats: dict[str, Any],
    projections: dict[str, Any],
) -> LeagueWeek:
    users_by_id = {user["user_id"]: user for user in users}
    scoring_key = scoring_stat_key(league.get("scoring_settings"))
    positions = league.get("roster_positions") or []
    matchup_by_roster = {int(item["roster_id"]): item for item in matchups if item.get("roster_id") is not None}
    user_roster = find_roster(rosters, user_id)
    user_roster_id = int(user_roster["roster_id"]) if user_roster is not None else None

    teams: dict[int, TeamView] = {}
    for roster in rosters:
        roster_id = int(roster["roster_id"])
        owner_id = roster.get("owner_id") or ""
        teams[roster_id] = build_team_view(
            roster=roster,
            user=users_by_id.get(owner_id),
            matchup=matchup_by_roster.get(roster_id),
            roster_positions=positions,
            players=players,
            stats=stats,
            projections=projections,
            scoring_key=scoring_key,
        )

    slate: list[MatchupSummary] = []
    for left_matchup, right_matchup in pair_matchups(matchups):
        left = teams.get(int(left_matchup["roster_id"]))
        if left is None:
            continue
        right = None
        if right_matchup is not None:
            right = teams.get(int(right_matchup["roster_id"]))
        involves_user = user_roster_id is not None and user_roster_id in {
            left.roster_id,
            right.roster_id if right else None,
        }
        if involves_user and right is not None and right.roster_id == user_roster_id:
            left, right = right, left
        slate.append(
            MatchupSummary(
                matchup_id=left_matchup.get("matchup_id"),
                left=left,
                right=right,
                involves_user=involves_user,
            )
        )
    slate.sort(key=lambda item: (not item.involves_user, item.matchup_id is None, item.matchup_id or 0))

    return LeagueWeek(
        week=week,
        season=season,
        league_name=league.get("name") or "League",
        league_id=str(league.get("league_id") or ""),
        user_roster_id=user_roster_id,
        slate=slate,
        teams=teams,
    )


def build_matchup_view(
    *,
    week: int,
    season: str,
    league: dict[str, Any],
    user_id: str,
    rosters: list[dict[str, Any]],
    users: list[dict[str, Any]],
    matchups: list[dict[str, Any]],
    players: dict[str, Any],
    stats: dict[str, Any],
    projections: dict[str, Any],
    focus_roster_id: int | None = None,
) -> MatchupView:
    league_week = build_league_week(
        week=week,
        season=season,
        league=league,
        user_id=user_id,
        rosters=rosters,
        users=users,
        matchups=matchups,
        players=players,
        stats=stats,
        projections=projections,
    )
    roster_id = focus_roster_id or league_week.user_roster_id
    if roster_id is None:
        raise ValueError("No roster found for this user in the selected league.")
    return league_week.view_for(roster_id)


def find_player_row(view: MatchupView | None, player_id: str) -> PlayerRow | None:
    if view is None or not player_id:
        return None
    teams = [view.mine]
    if view.opponent is not None:
        teams.append(view.opponent)
    for team in teams:
        for row in (*team.starters, *team.bench, *team.reserve):
            if row.player_id == player_id:
                return row
    return None


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return None
    if millis > 10_000_000_000:
        millis //= 1000
    try:
        return datetime.fromtimestamp(millis)
    except (OverflowError, OSError, ValueError):
        return None


def format_when(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%b %-d, %Y")


def parse_news_items(payload: list[dict[str, Any]] | None) -> list[NewsItem]:
    items: list[NewsItem] = []
    for raw in payload or []:
        meta = raw.get("metadata") or {}
        title = (meta.get("title") or "").strip()
        description = (meta.get("description") or "").strip()
        analysis = (meta.get("analysis") or "").strip()
        if not title and not description and not analysis:
            continue
        items.append(
            NewsItem(
                title=title or "Update",
                description=description,
                analysis=analysis,
                source=(raw.get("source") or "").replace("_", " "),
                published=parse_timestamp(raw.get("published")),
                url=(meta.get("url") or "").strip(),
            )
        )
    return items


def build_player_status(
    player: dict[str, Any] | None,
    player_id: str,
    row: PlayerRow | None = None,
) -> PlayerStatus:
    player = player or {}
    depth_order = player.get("depth_chart_order")
    position = (row.position if row and row.position else player.get("position")) or ""
    depth = ""
    if depth_order:
        depth = f"{position or '—'}{depth_order}"
    practice = (player.get("practice_participation") or player.get("practice_description") or "") or ""
    return PlayerStatus(
        player_id=player_id,
        name=player_name(player or None, player_id),
        team=player_team(player or None, player_id) or (row.team if row else ""),
        position=position,
        number=str(player.get("number") or ""),
        roster_status=player.get("status") or "Unknown",
        injury_status=player.get("injury_status") or "",
        injury_body_part=player.get("injury_body_part") or "",
        injury_notes=player.get("injury_notes") or "",
        practice=str(practice),
        depth=depth,
        age=str(player.get("age") or ""),
        years_exp=str(player.get("years_exp") if player.get("years_exp") is not None else ""),
        news_updated=parse_timestamp(player.get("news_updated")),
        actual_points=row.actual if row else None,
        projected_points=row.projected if row else None,
    )


def injury_line(status: PlayerStatus) -> str:
    if not status.injury_status:
        return "Healthy"
    parts = [status.injury_status]
    if status.injury_body_part:
        parts.append(status.injury_body_part)
    if status.injury_notes:
        parts.append(status.injury_notes)
    return " · ".join(parts)
