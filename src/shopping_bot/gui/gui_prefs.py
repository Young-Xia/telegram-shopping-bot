"""Persist lightweight GUI preferences (theme, panel heights, etc.)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shopping_bot.gui.paths import project_root

_PREFS_FILE = project_root() / "logs" / "gui-prefs.json"


def _load_raw() -> dict[str, Any]:
    if not _PREFS_FILE.is_file():
        return {}
    try:
        data = json.loads(_PREFS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_raw(data: dict[str, Any]) -> None:
    _PREFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PREFS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_height(key: str, default: int) -> int:
    value = _load_raw().get(key, default)
    if isinstance(value, (int, float)):
        return int(value)
    return default


def set_height(key: str, height: int) -> None:
    data = _load_raw()
    data[key] = int(height)
    _save_raw(data)


def get_theme(default: str = "dark") -> str:
    value = _load_raw().get("theme", default)
    return value if value in {"dark", "light"} else default


def set_theme(theme: str) -> None:
    if theme not in {"dark", "light"}:
        return
    data = _load_raw()
    data["theme"] = theme
    _save_raw(data)
