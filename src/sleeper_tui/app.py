from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Input, Label, Select, Static

from sleeper_tui.api import SleeperClient, SleeperError, UserNotFound
from sleeper_tui.config import AppConfig
from sleeper_tui.domain import (
    LeagueWeek,
    MatchupSummary,
    MatchupView,
    NewsItem,
    PlayerRow,
    PlayerStatus,
    TeamView,
    build_league_week,
    build_player_status,
    find_player_row,
    format_when,
    injury_line,
    parse_news_items,
)

INJURY_STYLES = {
    "Q": "bold yellow",
    "D": "bold red",
    "O": "bold red",
    "IR": "bold red",
    "PUP": "bold red",
    "SUS": "bold red",
}


def format_points(value: float | None, projected: bool = False) -> Text:
    if value is None:
        return Text("—", style="dim")
    text = f"{value:.1f}"
    if projected:
        return Text(text, style="cyan")
    return Text(text, style="bold")


def format_diff(actual: float | None, projected: float | None) -> Text | None:
    if actual is None or projected is None:
        return None
    delta = actual - projected
    sign = "+" if delta >= 0 else ""
    style = "green" if delta >= 0 else "red"
    return Text(f"{sign}{delta:.1f}", style=style)


def format_injury(code: str) -> Text:
    if not code:
        return Text("")
    return Text(code, style=INJURY_STYLES.get(code, "yellow"))


class SetupScreen(Screen[str]):
    BINDINGS = [Binding("escape", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-wrap"):
            with Vertical(id="setup-card"):
                yield Label("sleeper-tui", id="setup-title")
                yield Label("Enter your Sleeper username", id="setup-sub")
                yield Input(placeholder="username", id="username")
                yield Label("", id="setup-error")
                yield Button("Continue", id="setup-go", variant="success")

    def on_mount(self) -> None:
        self.query_one("#username", Input).focus()

    def set_error(self, message: str) -> None:
        self.query_one("#setup-error", Label).update(message)

    @on(Input.Submitted, "#username")
    @on(Button.Pressed, "#setup-go")
    def submit(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        if not username:
            self.set_error("Username is required.")
            return
        self.dismiss(username)


def _status_text(status: PlayerStatus) -> Text:
    header = Text.assemble(
        (status.name, "bold"),
        (f"  {status.position}" if status.position else "", "cyan"),
        (f"  {status.team}" if status.team else "", "dim"),
        (f"  #{status.number}" if status.number else "", "dim"),
    )
    lines = [
        ("Status", status.roster_status or "—"),
        ("Injury", injury_line(status)),
        ("Practice", status.practice or "—"),
        ("Depth", status.depth or "—"),
    ]
    if status.age:
        lines.append(("Age", status.age))
    if status.years_exp:
        lines.append(("Exp", f"{status.years_exp} yr"))
    actual = "—" if status.actual_points is None else f"{status.actual_points:.1f}"
    proj = "—" if status.projected_points is None else f"{status.projected_points:.1f}"
    lines.append(("Actual", actual))
    lines.append(("Proj", proj))
    diff = format_diff(status.actual_points, status.projected_points)
    if status.news_updated:
        lines.append(("Updated", format_when(status.news_updated)))

    body = Text()
    body.append_text(header)
    body.append("\n\n")
    for label, value in lines:
        style = "bold red" if label == "Injury" and value != "Healthy" else ""
        if label == "Actual" and status.actual_points is not None:
            style = "bold"
        if label == "Proj":
            style = "cyan"
        body.append(f"{label:<9}", style="dim")
        body.append(f"{value}", style=style)
        if label == "Actual" and diff is not None:
            body.append("  ")
            body.append_text(diff)
        body.append("\n")
    return body


def _news_text(items: list[NewsItem], message: str | None = None) -> Text:
    if message:
        return Text(message, style="dim")
    if not items:
        return Text("No recent news.", style="dim")
    text = Text()
    for index, item in enumerate(items):
        if index:
            text.append("\n")
        meta = "  ·  ".join(part for part in (format_when(item.published), item.source) if part)
        if meta:
            text.append(f"{meta}\n", style="dim")
        text.append(f"{item.title}\n", style="bold")
        if item.description:
            text.append(f"{item.description}\n")
        if item.analysis and item.analysis != item.description:
            text.append(f"{item.analysis}\n", style="italic")
    return text


class PlayerScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close", show=False),
        Binding("enter", "dismiss", "Close", show=False),
    ]

    def __init__(
        self,
        status: PlayerStatus,
        client: SleeperClient,
    ) -> None:
        super().__init__()
        self.status = status
        self.client = client

    def compose(self) -> ComposeResult:
        with Vertical(id="player-card"):
            yield Static(_status_text(self.status), id="player-status")
            yield Label("Latest news", id="news-heading")
            with VerticalScroll(id="news-scroll"):
                yield Static("Loading news…", id="player-news")
            yield Label("esc close", id="player-hint")

    def on_mount(self) -> None:
        self.load_news()

    @work(exclusive=True)
    async def load_news(self) -> None:
        news = self.query_one("#player-news", Static)
        try:
            payload = await self.client.player_news(self.status.player_id)
            news.update(_news_text(parse_news_items(payload)))
        except SleeperError as exc:
            news.update(_news_text([], message=str(exc)))


class HeaderBar(Static):
    def compose(self) -> ComposeResult:
        with Horizontal(id="title-row"):
            yield Label("sleeper-tui", id="title")
            yield Label("", id="subtitle")
        with Horizontal(id="controls"):
            yield Select[str]((), prompt="League", id="league-select")
            yield Button("<", id="week-prev", compact=True)
            yield Label("Week —", id="week-label")
            yield Button(">", id="week-next", compact=True)
            yield Label("", id="status")


class Scoreboard(Static):
    def compose(self) -> ComposeResult:
        with Horizontal(id="board"):
            yield Static(id="mine-score", classes="score")
            yield Static("vs", id="vs")
            yield Static(id="opp-score", classes="score")

    def show(self, view: MatchupView | None) -> None:
        mine_box = self.query_one("#mine-score", Static)
        opp_box = self.query_one("#opp-score", Static)
        if view is None:
            mine_box.update("")
            opp_box.update("")
            return

        mine = view.mine
        opp = view.opponent
        mine_box.update(
            self._team_block(
                mine,
                winning=bool(opp and mine.points > opp.points and not mine.projected),
                yours=view.user_roster_id == mine.roster_id,
            )
        )
        if opp is None:
            opp_box.update(Text("No opponent this week", style="dim"))
            return
        opp_box.update(
            self._team_block(
                opp,
                winning=opp.points > mine.points and not opp.projected,
                yours=view.user_roster_id == opp.roster_id,
            )
        )

    @staticmethod
    def _team_block(team: TeamView, *, winning: bool, yours: bool = False) -> Text:
        name_style = "bold green" if winning else "bold"
        title = team.team_name
        if yours:
            title = f"{title}  ·  you"
        block = Text.assemble(
            (f"{title}\n", name_style),
            (f"{team.record}   ", "dim"),
            format_points(team.points, team.projected),
        )
        if team.proj_total is not None and not team.projected:
            block.append("\n")
            block.append(f"proj {team.proj_total:.1f}", style="cyan")
        return block


class WeekSlate(Vertical):
    def compose(self) -> ComposeResult:
        yield Label("Week matchups", id="slate-heading")
        yield Label("Enter a game to open the lineup", id="slate-sub")
        yield DataTable(id="week-slate", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        table = self.query_one("#week-slate", DataTable)
        table.add_columns("Home", "Rec", "Pts", "Proj", "", "Away", "Rec", "Pts", "Proj", "")
        table.cursor_type = "row"

    def show(self, slate: list[MatchupSummary], selected_roster_id: int | None) -> None:
        table = self.query_one("#week-slate", DataTable)
        table.clear()
        selected_key: str | None = None
        for item in slate:
            key = str(item.left.roster_id)
            if selected_roster_id in item.roster_ids:
                selected_key = key
            away = item.right
            left_win = bool(away and item.left.points > away.points and not item.left.projected)
            right_win = bool(away and away.points > item.left.points and not away.projected)
            table.add_row(
                Text(item.left.team_name, style="bold green" if left_win else "bold"),
                Text(item.left.record, style="dim"),
                format_points(item.left.points, item.left.projected),
                format_points(item.left.proj_total, projected=True),
                Text("vs", style="dim"),
                Text(away.team_name if away else "Bye", style="bold green" if right_win else ("dim" if away is None else "bold")),
                Text(away.record if away else "", style="dim"),
                format_points(away.points, away.projected) if away else Text("—", style="dim"),
                format_points(away.proj_total, projected=True) if away else Text("—", style="dim"),
                Text("YOU", style="bold cyan") if item.involves_user else Text(""),
                key=key,
            )
        if selected_key and table.row_count:
            try:
                table.move_cursor(row=table.get_row_index(selected_key))
            except Exception:
                pass


class TeamPanel(Vertical):
    def __init__(self, kind: str) -> None:
        super().__init__(classes=kind)
        self.kind = kind

    def compose(self) -> ComposeResult:
        prefix = self.kind
        yield Label("Starters", classes="section", id=f"{prefix}-starters-label")
        yield DataTable(id=f"{prefix}-starters", cursor_type="row", zebra_stripes=True)
        yield Label("Bench", classes="section", id=f"{prefix}-bench-label")
        yield DataTable(id=f"{prefix}-bench", cursor_type="row", zebra_stripes=True)

    def on_mount(self) -> None:
        for table_id in (f"{self.kind}-starters", f"{self.kind}-bench"):
            table = self.query_one(f"#{table_id}", DataTable)
            table.add_columns("Slot", "Player", "Tm", "Proj", "Pts", "")
            table.cursor_type = "row"

    def render_team(self, team: TeamView | None, *, opponent: bool = False) -> None:
        title = "Opponent starters" if opponent else "Starters"
        bench_title = "Opponent bench" if opponent else "Bench"
        if team is not None:
            title = f"{title} · {team.team_name}"
            extra = len(team.reserve)
            if extra:
                bench_title = f"{bench_title} · {len(team.bench)}  IR/Taxi {extra}"
            else:
                bench_title = f"{bench_title} · {len(team.bench)}"
        self.query_one(f"#{self.kind}-starters-label", Label).update(title)
        self.query_one(f"#{self.kind}-bench-label", Label).update(bench_title)
        self._fill(f"{self.kind}-starters", team.starters if team else [])
        bench_rows = (*(team.bench if team else []), *(team.reserve if team else []))
        self._fill(f"{self.kind}-bench", list(bench_rows))

    def _fill(self, table_id: str, rows: list[PlayerRow]) -> None:
        table = self.query_one(f"#{table_id}", DataTable)
        table.clear()
        if not rows:
            table.add_row(
                Text("—", style="dim"),
                Text("None", style="dim"),
                "",
                Text("—", style="dim"),
                Text("—", style="dim"),
                "",
                key="empty",
            )
            return
        for index, row in enumerate(rows):
            name = Text(row.name, style="dim" if row.empty else "")
            table.add_row(
                Text(row.slot, style="dim"),
                name,
                Text(row.team or "—", style="dim"),
                format_points(row.projected, projected=True),
                format_points(row.actual),
                format_injury(row.injury),
                key=row.player_id or f"empty-{index}",
            )


class SleeperApp(App[None]):
    CSS_PATH = "app.tcss"
    TITLE = "sleeper-tui"
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("left", "prev_week", "Prev week"),
        Binding("right", "next_week", "Next week"),
        Binding("n", "next_week", "Next week", show=False),
        Binding("p", "prev_week", "Prev week", show=False),
        Binding("u", "change_user", "User"),
        Binding("m", "toggle_slate", "Matchups"),
        Binding("[", "prev_matchup", "Prev game"),
        Binding("]", "next_matchup", "Next game"),
        Binding("enter", "open_selected", "Open", show=True),
    ]

    username: reactive[str] = reactive("")
    user_id: reactive[str] = reactive("")
    league_id: reactive[str] = reactive("")
    week: reactive[int] = reactive(1)
    season: reactive[str] = reactive("")

    def __init__(
        self,
        username: str | None = None,
        league_id: str | None = None,
        week: int | None = None,
        *,
        config: AppConfig | None = None,
        client: SleeperClient | None = None,
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self._config_path = config_path
        self.config = config or AppConfig.load(config_path)
        if username:
            self.config.username = username
        if league_id:
            self.config.league_id = league_id
        self._week_override = week
        self.client = client or SleeperClient()
        self.leagues: list[dict[str, Any]] = []
        self.players: dict[str, Any] = {}
        self.week_data: LeagueWeek | None = None
        self.view: MatchupView | None = None
        self.selected_roster_id: int | None = None
        self._bootstrapped = False

    def compose(self) -> ComposeResult:
        yield HeaderBar()
        with Vertical(id="lineup"):
            yield Scoreboard()
            with Horizontal(id="boards"):
                yield TeamPanel("you")
                yield TeamPanel("opp")
        yield WeekSlate(id="slate")
        yield Label("", id="toast")
        yield Footer()

    async def on_mount(self) -> None:
        if not self.config.username:
            self.call_after_refresh(self._ask_username)
            return
        self.bootstrap()

    async def on_unmount(self) -> None:
        await self.client.aclose()

    def _ask_username(self) -> None:
        self.push_screen(SetupScreen(), self._on_username)

    def _on_username(self, username: str | None) -> None:
        if not username:
            self.exit()
            return
        self.config.username = username
        self.config.user_id = ""
        self.bootstrap()

    def action_change_user(self) -> None:
        self.push_screen(SetupScreen(), self._on_username)

    def action_open_selected(self) -> None:
        if self._showing_slate():
            self._open_slate_selection()
            return
        self.action_open_selected_player()

    def action_open_selected_player(self) -> None:
        focused = self.focused
        if not isinstance(focused, DataTable) or not focused.row_count:
            return
        if focused.id == "week-slate":
            self._open_slate_selection()
            return
        try:
            row_key, _ = focused.coordinate_to_cell_key(focused.cursor_coordinate)
        except Exception:
            return
        player_id = getattr(row_key, "value", None) or str(row_key)
        self.open_player(str(player_id))

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "week-slate":
            self.open_matchup(str(event.row_key.value))
            return
        player_id = event.row_key.value
        if player_id:
            self.open_player(str(player_id))

    def action_toggle_slate(self) -> None:
        if self._showing_slate():
            self._show_lineup()
            return
        self._show_slate()

    def action_prev_matchup(self) -> None:
        self._cycle_matchup(-1)

    def action_next_matchup(self) -> None:
        self._cycle_matchup(1)

    def _showing_slate(self) -> bool:
        return bool(self.query_one("#slate").display)

    def _show_slate(self) -> None:
        self.query_one("#lineup").display = False
        self.query_one("#slate").display = True
        self._render_slate()
        self.query_one("#week-slate", DataTable).focus()

    def _show_lineup(self) -> None:
        self.query_one("#slate").display = False
        self.query_one("#lineup").display = True

    def _cycle_matchup(self, step: int) -> None:
        if not self.week_data or not self.week_data.slate:
            return
        current = self.selected_roster_id or self.week_data.user_roster_id
        index = next(
            (i for i, item in enumerate(self.week_data.slate) if current in item.roster_ids),
            0,
        )
        nxt = self.week_data.slate[(index + step) % len(self.week_data.slate)]
        self.show_roster(nxt.left.roster_id)
        if self._showing_slate():
            self._render_slate()

    def _open_slate_selection(self) -> None:
        table = self.query_one("#week-slate", DataTable)
        if not table.row_count:
            return
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        except Exception:
            return
        self.open_matchup(str(getattr(row_key, "value", None) or row_key))

    def open_matchup(self, roster_id: str) -> None:
        if not roster_id or roster_id.startswith("empty"):
            return
        try:
            self.show_roster(int(roster_id))
        except ValueError:
            return
        self._show_lineup()

    def show_roster(self, roster_id: int) -> None:
        if self.week_data is None or not self.week_data.contains_roster(roster_id):
            return
        self.selected_roster_id = roster_id
        self.view = self.week_data.view_for(roster_id)
        self._render()

    def open_player(self, player_id: str) -> None:
        if not player_id or player_id.startswith("empty"):
            return
        if isinstance(self.screen, PlayerScreen):
            return
        player = self.players.get(player_id)
        row = find_player_row(self.view, player_id)
        status = build_player_status(player, player_id, row)
        self.push_screen(PlayerScreen(status, self.client))

    def action_refresh(self) -> None:
        if not self.user_id:
            self.bootstrap()
            return
        self.load_matchup()

    def action_prev_week(self) -> None:
        if self.week > 1:
            self.week = self.week - 1
            self.load_matchup()

    def action_next_week(self) -> None:
        if self.week < 18:
            self.week = self.week + 1
            self.load_matchup()

    @on(Button.Pressed, "#week-prev")
    def _week_prev(self) -> None:
        self.action_prev_week()

    @on(Button.Pressed, "#week-next")
    def _week_next(self) -> None:
        self.action_next_week()

    @on(Select.Changed, "#league-select")
    def _league_changed(self, event: Select.Changed) -> None:
        if event.value is Select.BLANK or not self._bootstrapped:
            return
        league_id = str(event.value)
        if league_id == self.league_id:
            return
        self.league_id = league_id
        self.config.league_id = league_id
        self.config.save(self._config_path)
        self.selected_roster_id = None
        self.load_matchup()

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Label).update(message)

    def _set_toast(self, message: str) -> None:
        self.query_one("#toast", Label).update(message)

    def _set_week_label(self) -> None:
        self.query_one("#week-label", Label).update(f"Week {self.week}")
        subtitle = f"{self.season} · NFL"
        if self.view is not None and self.view.matchup_count:
            subtitle = f"{subtitle} · game {self.view.matchup_index}/{self.view.matchup_count}"
        self.query_one("#subtitle", Label).update(subtitle)

    def _fill_leagues(self) -> None:
        select = self.query_one("#league-select", Select)
        options = [(league.get("name") or league["league_id"], league["league_id"]) for league in self.leagues]
        select.set_options(options)
        if self.league_id:
            select.value = self.league_id

    def _render(self) -> None:
        self._set_week_label()
        self.query_one(Scoreboard).show(self.view)
        you = self.query_one("TeamPanel.you", TeamPanel)
        opp = self.query_one("TeamPanel.opp", TeamPanel)
        if self.view is None:
            you.render_team(None)
            opp.render_team(None, opponent=True)
            return
        you.render_team(self.view.mine)
        opp.render_team(self.view.opponent, opponent=True)
        if self._showing_slate():
            self._render_slate()

    def _render_slate(self) -> None:
        heading = self.query_one("#slate-heading", Label)
        heading.update(f"Week {self.week} matchups")
        self.query_one(WeekSlate).show(self.week_data.slate if self.week_data else [], self.selected_roster_id)

    @work(exclusive=True, group="bootstrap")
    async def bootstrap(self) -> None:
        self._bootstrapped = False
        self._set_toast("")
        self._set_status("Loading leagues…")
        try:
            user, state, players = await asyncio.gather(
                self.client.user(self.config.username),
                self.client.nfl_state(),
                self.client.players(),
            )
            self.username = user["username"]
            self.user_id = user["user_id"]
            self.config.username = self.username
            self.config.user_id = self.user_id
            self.season = str(state.get("league_season") or state.get("season") or "")
            self.week = self._week_override or int(state.get("display_week") or state.get("week") or 1)
            self.players = players
            self.leagues = await self.client.leagues(self.user_id, self.season)
        except UserNotFound as exc:
            self._set_status("")
            self._set_toast(str(exc))
            self.call_after_refresh(self._ask_username)
            return
        except SleeperError as exc:
            self._set_status("Error")
            self._set_toast(str(exc))
            return

        if not self.leagues:
            self._set_status("")
            self._set_toast(f"No NFL leagues for {self.username} in {self.season}.")
            return

        preferred = self.config.league_id
        if preferred and any(league["league_id"] == preferred for league in self.leagues):
            self.league_id = preferred
        else:
            in_season = next(
                (league for league in self.leagues if league.get("status") == "in_season"),
                self.leagues[0],
            )
            self.league_id = in_season["league_id"]
            self.config.league_id = self.league_id

        self.config.save(self._config_path)
        self._fill_leagues()
        self._bootstrapped = True
        self._week_override = None
        self.load_matchup()

    @work(exclusive=True, group="matchup")
    async def load_matchup(self) -> None:
        if not self.league_id or not self.user_id:
            return
        self._set_toast("")
        self._set_status("Loading matchup…")
        self._set_week_label()
        try:
            league, rosters, users, matchups, stats, projections = await asyncio.gather(
                self.client.league(self.league_id),
                self.client.rosters(self.league_id),
                self.client.users(self.league_id),
                self.client.matchups(self.league_id, self.week),
                self.client.stats(self.season, self.week),
                self.client.projections(self.season, self.week),
            )
            self.week_data = build_league_week(
                week=self.week,
                season=self.season,
                league=league,
                user_id=self.user_id,
                rosters=rosters,
                users=users,
                matchups=matchups,
                players=self.players,
                stats=stats,
                projections=projections,
            )
            focus = self.selected_roster_id
            if focus is None or not self.week_data.contains_roster(focus):
                focus = self.week_data.user_roster_id
            if focus is None:
                raise ValueError("No roster found for this user in the selected league.")
            self.selected_roster_id = focus
            self.view = self.week_data.view_for(focus)
        except (SleeperError, ValueError, TypeError) as exc:
            self.week_data = None
            self.view = None
            self._render()
            self._set_status("Error")
            self._set_toast(str(exc))
            return

        self._render()
        stamp = datetime.now().strftime("%-I:%M %p")
        suffix = "proj" if self.view.mine.projected else "live"
        if self.view.mine.proj_total is not None and not self.view.mine.projected:
            suffix = f"{suffix} · proj {self.view.mine.proj_total:.1f}"
        self._set_status(f"{stamp} · {suffix}")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "publish":
        from sleeper_tui.publish import publish_main

        raise SystemExit(publish_main(sys.argv[2:]))

    parser = argparse.ArgumentParser(
        prog="sleeper-tui",
        description="Sleeper fantasy football TUI. Stays local unless you run `sleeper-tui publish` with your own Datadog keys.",
    )
    parser.add_argument("-u", "--username", help="Sleeper username")
    parser.add_argument("-l", "--league", help="League ID")
    parser.add_argument("-w", "--week", type=int, help="Week number")
    args = parser.parse_args()
    SleeperApp(username=args.username, league_id=args.league, week=args.week).run()


if __name__ == "__main__":
    main()
