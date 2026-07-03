from __future__ import annotations

import os
from dotenv import load_dotenv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _int_csv(value: str | None) -> set[int]:
    ids: set[int] = set()
    for item in _csv(value):
        try:
            ids.add(int(item))
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram user id in ALLOWED_TELEGRAM_USER_IDS: {item}") from exc
    return ids


@dataclass(frozen=True)
class NotionConfig:
    token: str
    database_id: str
    title_property: str
    url_property: str
    category_property: str
    status_property: str
    status_property_type: str
    default_status: str
    notes_property: str | None
    added_at_property: str | None


DEFAULT_AI_API_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_VISION_MODEL = "google/gemini-2.5-flash"

_DEPRECATED_VISION_MODELS: dict[str, str] = {
    "google/gemini-2.0-flash-001": DEFAULT_VISION_MODEL,
    "google/gemini-2.0-flash": DEFAULT_VISION_MODEL,
    "google/gemini-2.0-flash-exp": DEFAULT_VISION_MODEL,
    "google/gemini-2.0-flash-exp:free": DEFAULT_VISION_MODEL,
}


def normalize_vision_model(model: str) -> str:
    cleaned = model.strip()
    if not cleaned:
        return cleaned
    return _DEPRECATED_VISION_MODELS.get(cleaned, cleaned)


# (host fragment, default chat model, default vision model or "" if unsupported)
_PROVIDER_DEFAULTS: tuple[tuple[str, str, str], ...] = (
    ("openrouter.ai", "openrouter/free", DEFAULT_VISION_MODEL),
    ("api.openai.com", "gpt-4o-mini", "gpt-4o"),
    ("deepseek.com", "deepseek-chat", ""),
    ("groq.com", "llama-3.3-70b-versatile", ""),
)


def provider_supports_vision(base_url: str) -> bool:
    lowered = base_url.lower()
    for marker, _chat, vision in _PROVIDER_DEFAULTS:
        if marker in lowered:
            return bool(vision)
    return True


def infer_ai_defaults(base_url: str) -> tuple[str, str]:
    lowered = base_url.lower()
    for marker, chat_model, vision_model in _PROVIDER_DEFAULTS:
        if marker in lowered:
            return chat_model, vision_model
    return "gpt-4o-mini", "gpt-4o-mini"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    allowed_user_ids: set[int]
    ai_api_key: str
    ai_api_base_url: str
    ai_vision_api_key: str | None
    ai_vision_api_base_url: str | None
    default_model: str
    vision_model: str
    models: list[str]
    search_provider: str
    google_cse_api_key: str | None
    google_cse_id: str | None
    search_result_count: int
    notion: NotionConfig

    @property
    def openrouter_api_key(self) -> str:
        """Backward-compatible alias for older code paths."""
        return self.ai_api_key

    def model_aliases(self) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for model in self.models:
            aliases[model] = model
            aliases[model.rsplit("/", 1)[-1]] = model
        return aliases


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip("\ufeff")
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        cleaned = cleaned[1:-1].strip()
    return cleaned or None


def require_env(name: str) -> str:
    value = _clean_env(os.getenv(name))
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def optional_env(name: str) -> str | None:
    return _clean_env(os.getenv(name))


def load_settings(env_files: Iterable[str] = (".env",)) -> Settings:
    for env_file in env_files:
        path = Path(env_file)
        if path.is_file():
            # Always prefer values from the project .env over stale process env.
            load_dotenv(path, override=True)

    ai_api_key = optional_env("AI_API_KEY") or require_env("OPENROUTER_API_KEY")
    ai_api_base_url = (
        optional_env("AI_API_BASE_URL")
        or optional_env("OPENROUTER_API_BASE_URL")
        or DEFAULT_AI_API_BASE_URL
    )
    ai_vision_api_key = optional_env("AI_VISION_API_KEY")
    ai_vision_api_base_url = optional_env("AI_VISION_API_BASE_URL")

    chat_default, main_vision_default = infer_ai_defaults(ai_api_base_url)
    default_model = (
        optional_env("AI_DEFAULT_MODEL")
        or optional_env("OPENROUTER_DEFAULT_MODEL")
        or chat_default
    )

    if ai_vision_api_base_url and ai_vision_api_key:
        _, vision_default = infer_ai_defaults(ai_vision_api_base_url)
        if not vision_default:
            vision_default = DEFAULT_VISION_MODEL
    elif provider_supports_vision(ai_api_base_url):
        vision_default = main_vision_default
    else:
        vision_default = ""

    vision_model = normalize_vision_model(
        optional_env("AI_VISION_MODEL")
        or optional_env("OPENROUTER_VISION_MODEL")
        or vision_default
    )
    models = _csv(optional_env("AI_MODELS") or optional_env("OPENROUTER_MODELS")) or [default_model]
    if default_model not in models:
        models.insert(0, default_model)

    return Settings(
        telegram_bot_token=require_env("TELEGRAM_BOT_TOKEN"),
        allowed_user_ids=_int_csv(os.getenv("ALLOWED_TELEGRAM_USER_IDS")),
        ai_api_key=ai_api_key,
        ai_api_base_url=ai_api_base_url.rstrip("/"),
        ai_vision_api_key=ai_vision_api_key,
        ai_vision_api_base_url=ai_vision_api_base_url.rstrip("/") if ai_vision_api_base_url else None,
        default_model=default_model,
        vision_model=vision_model,
        models=models,
        search_provider=os.getenv("SEARCH_PROVIDER", "duckduckgo").strip().lower(),
        google_cse_api_key=optional_env("GOOGLE_CSE_API_KEY"),
        google_cse_id=optional_env("GOOGLE_CSE_ID"),
        search_result_count=int(os.getenv("SEARCH_RESULT_COUNT", "5")),
        notion=NotionConfig(
            token=require_env("NOTION_TOKEN"),
            database_id=require_env("NOTION_DATABASE_ID"),
            title_property=os.getenv("NOTION_TITLE_PROPERTY", "名称"),
            url_property=os.getenv("NOTION_URL_PROPERTY", "链接"),
            category_property=os.getenv("NOTION_CATEGORY_PROPERTY", "分类"),
            status_property=os.getenv("NOTION_STATUS_PROPERTY", "状态"),
            status_property_type=os.getenv("NOTION_STATUS_PROPERTY_TYPE", "status"),
            default_status=os.getenv("NOTION_DEFAULT_STATUS", "未开始"),
            notes_property=os.getenv("NOTION_NOTES_PROPERTY", "备注") or None,
            added_at_property=os.getenv("NOTION_ADDED_AT_PROPERTY", "Added At") or None,
        ),
    )
