# sleeper-tui

A terminal UI for [Sleeper](https://sleeper.com) fantasy football. It reads the public API and shows your starters, bench, and weekly matchup.

## Run

```bash
uv sync
uv run sleeper-tui
```

On first launch it asks for your Sleeper username. That is stored in `~/.config/sleeper-tui/config.json`.

```bash
uv run sleeper-tui -u yourname
uv run sleeper-tui -u yourname -l LEAGUE_ID -w 1
```

The NFL player map is cached for 24 hours in `~/.cache/sleeper-tui/` (Sleeper asks that this file not be fetched more than once a day).

## Keys

| Key | Action |
| --- | --- |
| `←` / `→` or `p` / `n` | Previous / next week |
| `m` | Week scoreboard of every matchup |
| `[` / `]` | Previous / next game this week |
| `enter` or click a player | Status and latest news |
| `enter` or click a scoreboard row | Open that lineup |
| `esc` | Close player details |
| `r` | Refresh |
| `u` | Switch Sleeper username |
| `q` | Quit |

Use the league dropdown to jump between leagues. **Proj** is Sleeper's weekly projection; **Pts** is live / official scoring once the player has started. The player card shows both, plus the difference.

## Datadog

The TUI never talks to Datadog on its own. Anyone who wants a board can publish into **their own** Datadog account. Use your API and application keys; do not share them.

```bash
export DD_API_KEY=...
export DD_APP_KEY=...
uv run sleeper-tui publish
```

That reads the public Sleeper API from your machine and upserts a dashboard titled **Sleeper fantasy football** in the org those keys belong to. `--dry-run` builds the payload without calling Datadog. Re-run publish to refresh scores. The dashboard includes team names, player names, standings, this week's matchups, and starter points. Use the **league** template variable if you publish more than one league. Set `DD_SITE` if the org is not on `datadoghq.com`.

## Notes

Sleeper's API is read-only and needs no token. This app does not move players or set lineups.
