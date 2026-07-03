from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def env_path() -> Path:
    return project_root() / ".env"


def env_example_path() -> Path:
    return project_root() / ".env.example"


def venv_python() -> Path:
    return project_root() / ".venv" / "Scripts" / "python.exe"


def venv_pythonw() -> Path:
    return project_root() / ".venv" / "Scripts" / "pythonw.exe"


def log_path() -> Path:
    return project_root() / "logs" / "bot.log"
