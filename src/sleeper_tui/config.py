from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


def config_path() -> Path:
    return Path.home() / ".config" / "sleeper-tui" / "config.json"


def cache_dir() -> Path:
    path = Path.home() / ".cache" / "sleeper-tui"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppConfig:
    username: str = ""
    user_id: str = ""
    league_id: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        target = path or config_path()
        if not target.exists():
            return cls()
        data = json.loads(target.read_text())
        return cls(
            username=data.get("username") or "",
            user_id=data.get("user_id") or "",
            league_id=data.get("league_id") or "",
        )

    def save(self, path: Path | None = None) -> None:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2) + "\n")
