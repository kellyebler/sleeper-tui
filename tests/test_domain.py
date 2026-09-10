from sleeper_tui.domain import (
    bench_ids,
    build_league_week,
    build_matchup_view,
    build_player_status,
    find_matchup_pair,
    find_player_row,
    find_roster,
    format_record,
    injury_line,
    parse_news_items,
    player_name,
    resolve_points,
    scoring_stat_key,
    starter_slots,
    team_total,
)
from sleeper_tui.domain import PlayerRow


def test_starter_slots_drop_bench_and_ir():
    assert starter_slots(["QB", "RB", "FLEX", "BN", "BN", "IR"]) == ["QB", "RB", "FLEX"]


def test_scoring_stat_key():
    assert scoring_stat_key({"rec": 1}) == "pts_ppr"
    assert scoring_stat_key({"rec": 0.5}) == "pts_half_ppr"
    assert scoring_stat_key({"rec": 0}) == "pts_std"


def test_player_name_prefers_full_name_and_handles_empty():
    assert player_name({"full_name": "Josh Allen"}, "1") == "Josh Allen"
    assert player_name({"first_name": "Josh", "last_name": "Allen"}, "1") == "Josh Allen"
    assert player_name({"position": "DEF", "team": "BUF"}, "BUF") == "BUF"
    assert player_name(None, "0") == "Empty"


def test_bench_excludes_starters_reserve_and_empties():
    assert bench_ids(["1", "2", "3", "0"], ["1"], reserve=["3"]) == ["2"]


def test_resolve_points_returns_actual_and_projection():
    assert resolve_points(
        "1",
        matchup={"players_points": {"1": 18.4}},
        stats={"1": {"gp": 1, "pts_ppr": 17.0}},
        projections={"1": {"pts_ppr": 20.0}},
        scoring_key="pts_ppr",
    ) == (18.4, 20.0)

    assert resolve_points(
        "2",
        matchup={"players_points": {"2": 4.1}},
        stats={},
        projections={"2": {"pts_ppr": 12.0}},
        scoring_key="pts_ppr",
    ) == (4.1, 12.0)

    assert resolve_points(
        "3",
        matchup={"players_points": {"3": 0.0}},
        stats={},
        projections={"3": {"pts_ppr": 14.2}},
        scoring_key="pts_ppr",
    ) == (None, 14.2)


def test_team_total_uses_official_points_when_games_started():
    starters = [
        PlayerRow("QB", "1", "A", "BUF", "QB", 20.0, 22.0, ""),
        PlayerRow("RB", "2", "B", "SF", "RB", None, 10.0, ""),
    ]
    assert team_total({"points": 20.0}, starters) == (20.0, False, 32.0)


def test_format_record():
    assert format_record({"wins": 3, "losses": 1}) == "3-1"
    assert format_record({"wins": 2, "losses": 2, "ties": 1}) == "2-2-1"


def test_find_roster_includes_co_owners():
    rosters = [{"roster_id": 1, "owner_id": "a", "co_owners": ["b"]}]
    assert find_roster(rosters, "b")["roster_id"] == 1


def test_find_matchup_pair():
    matchups = [
        {"roster_id": 1, "matchup_id": 4, "points": 10},
        {"roster_id": 2, "matchup_id": 4, "points": 8},
        {"roster_id": 3, "matchup_id": 5, "points": 1},
    ]
    mine, opp = find_matchup_pair(matchups, 1)
    assert mine["roster_id"] == 1
    assert opp["roster_id"] == 2


def test_build_matchup_view():
    view = build_matchup_view(
        week=1,
        season="2026",
        league={
            "name": "Test League",
            "league_id": "L1",
            "roster_positions": ["QB", "RB", "BN"],
            "scoring_settings": {"rec": 1},
        },
        user_id="u1",
        rosters=[
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
        ],
        users=[
            {"user_id": "u1", "display_name": "Kelly", "metadata": {"team_name": "Gridiron"}},
            {"user_id": "u2", "display_name": "Sam", "metadata": {}},
        ],
        matchups=[
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
        ],
        players={
            "10": {"full_name": "Josh Allen", "team": "BUF", "position": "QB"},
            "11": {"full_name": "Bench Guy", "team": "MIA", "position": "WR"},
            "20": {"full_name": "Patrick Mahomes", "team": "KC", "position": "QB"},
        },
        stats={
            "10": {"gp": 1, "pts_ppr": 22.0},
            "11": {"gp": 1, "pts_ppr": 3.0},
            "20": {"gp": 1, "pts_ppr": 11.0},
        },
        projections={
            "10": {"pts_ppr": 20.1},
            "11": {"pts_ppr": 8.0},
            "20": {"pts_ppr": 19.4},
        },
    )
    assert view.mine.team_name == "Gridiron"
    assert view.mine.starters[0].name == "Josh Allen"
    assert view.mine.starters[0].actual == 22.0
    assert view.mine.starters[0].projected == 20.1
    assert view.mine.bench[0].name == "Bench Guy"
    assert view.opponent is not None
    assert view.opponent.starters[0].name == "Patrick Mahomes"
    assert view.mine.points == 22.0
    assert view.mine.proj_total == 20.1
    assert find_player_row(view, "11").name == "Bench Guy"
    assert view.matchup_count == 1


def test_week_slate_and_switching_focus():
    league = {
        "name": "Test League",
        "league_id": "L1",
        "roster_positions": ["QB", "BN"],
        "scoring_settings": {"rec": 1},
    }
    rosters = [
        {"roster_id": 1, "owner_id": "u1", "starters": ["10"], "players": ["10"], "reserve": [], "settings": {"wins": 1, "losses": 0}},
        {"roster_id": 2, "owner_id": "u2", "starters": ["20"], "players": ["20"], "reserve": [], "settings": {"wins": 0, "losses": 1}},
        {"roster_id": 3, "owner_id": "u3", "starters": ["30"], "players": ["30"], "reserve": [], "settings": {"wins": 2, "losses": 0}},
        {"roster_id": 4, "owner_id": "u4", "starters": ["40"], "players": ["40"], "reserve": [], "settings": {"wins": 0, "losses": 2}},
    ]
    users = [
        {"user_id": "u1", "display_name": "Kelly", "metadata": {"team_name": "Gridiron"}},
        {"user_id": "u2", "display_name": "Sam", "metadata": {}},
        {"user_id": "u3", "display_name": "Ava", "metadata": {"team_name": "Night Owls"}},
        {"user_id": "u4", "display_name": "Bo", "metadata": {}},
    ]
    matchups = [
        {"roster_id": 1, "matchup_id": 1, "starters": ["10"], "players": ["10"], "points": 22.0, "players_points": {"10": 22.0}},
        {"roster_id": 2, "matchup_id": 1, "starters": ["20"], "players": ["20"], "points": 11.0, "players_points": {"20": 11.0}},
        {"roster_id": 3, "matchup_id": 2, "starters": ["30"], "players": ["30"], "points": 8.0, "players_points": {"30": 8.0}},
        {"roster_id": 4, "matchup_id": 2, "starters": ["40"], "players": ["40"], "points": 15.0, "players_points": {"40": 15.0}},
    ]
    week = build_league_week(
        week=1,
        season="2026",
        league=league,
        user_id="u1",
        rosters=rosters,
        users=users,
        matchups=matchups,
        players={
            "10": {"full_name": "Josh Allen", "team": "BUF", "position": "QB"},
            "20": {"full_name": "Patrick Mahomes", "team": "KC", "position": "QB"},
            "30": {"full_name": "Lamar Jackson", "team": "BAL", "position": "QB"},
            "40": {"full_name": "Jalen Hurts", "team": "PHI", "position": "QB"},
        },
        stats={
            "10": {"gp": 1, "pts_ppr": 22.0},
            "20": {"gp": 1, "pts_ppr": 11.0},
            "30": {"gp": 1, "pts_ppr": 8.0},
            "40": {"gp": 1, "pts_ppr": 15.0},
        },
        projections={
            "10": {"pts_ppr": 20.1},
            "20": {"pts_ppr": 19.4},
            "30": {"pts_ppr": 21.0},
            "40": {"pts_ppr": 18.0},
        },
    )
    assert [item.left.team_name for item in week.slate] == ["Gridiron", "Night Owls"]
    assert week.slate[0].involves_user is True
    assert week.slate[1].right is not None
    assert week.slate[1].right.team_name == "Bo"
    other = week.view_for(3)
    assert other.mine.team_name == "Night Owls"
    assert other.opponent is not None
    assert other.opponent.starters[0].name == "Jalen Hurts"
    assert other.matchup_index == 2
    assert other.matchup_count == 2


def test_player_status_and_news():
    status = build_player_status(
        {
            "full_name": "Mykel Williams",
            "team": "SF",
            "position": "DE",
            "number": 98,
            "status": "Active",
            "injury_status": "PUP",
            "injury_body_part": "Knee - ACL",
            "injury_notes": "Surgery",
            "depth_chart_order": 2,
            "age": 23,
            "years_exp": 1,
            "news_updated": 1788207614855,
        },
        "12602",
        PlayerRow("DE", "12602", "Mykel Williams", "SF", "DE", None, 6.2, "PUP"),
    )
    assert status.name == "Mykel Williams"
    assert status.depth == "DE2"
    assert injury_line(status) == "PUP · Knee - ACL · Surgery"
    assert status.actual_points is None
    assert status.projected_points == 6.2
    assert status.news_updated is not None

    news = parse_news_items(
        [
            {
                "source": "rotowire",
                "published": 1788207614853,
                "metadata": {
                    "title": "Placed on PUP",
                    "description": "Knee injury.",
                    "analysis": "Expected to miss time.",
                },
            },
            {"source": "x", "metadata": {}},
        ]
    )
    assert len(news) == 1
    assert news[0].title == "Placed on PUP"
    assert news[0].source == "rotowire"
