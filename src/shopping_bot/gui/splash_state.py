"""Lightweight splash coordination (no GUI imports)."""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def logs_dir() -> Path:
    path = project_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def loading_marker() -> Path:
    return logs_dir() / ".gui-loading"


def ready_marker() -> Path:
    return logs_dir() / ".gui-ready"


def external_splash_active() -> bool:
    return loading_marker().is_file()


def mark_loading() -> None:
    loading_marker().write_text("1", encoding="utf-8")
    ready_marker().unlink(missing_ok=True)


def mark_ready() -> None:
    ready_marker().write_text("1", encoding="utf-8")


def clear_markers() -> None:
    loading_marker().unlink(missing_ok=True)
    ready_marker().unlink(missing_ok=True)
