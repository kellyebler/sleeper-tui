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

Datadog cannot query Sleeper on its own. `sleeper-tui publish` pulls the public API and writes custom metrics, then upserts a dashboard titled **Sleeper fantasy football**.

```bash
export DD_API_KEY=...
export DD_APP_KEY=...
uv run sleeper-tui publish
```

`--dry-run` fetches Sleeper and builds the payload without calling Datadog. Re-run publish (or cron it) whenever you want scores refreshed. The dashboard includes team names, player names, standings, this week's matchups, and starter points. Use the **league** template variable if you publish more than one league.

Optional APM for the TUI process itself (latency of `bootstrap` / `load matchup`, no fantasy names). It sends OTLP straight to Datadog intake — no local Agent:

```bash
export DD_API_KEY=...
uv run sleeper-tui --monitor
```

Set `DD_SITE` if the org is not on `datadoghq.com`. `OTEL_EXPORTER_OTLP_ENDPOINT` overrides the intake URL if you already have a collector.

## Notes

Sleeper's API is read-only and needs no token. This app does not move players or set lineups.
