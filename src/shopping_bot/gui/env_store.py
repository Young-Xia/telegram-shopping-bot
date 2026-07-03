from __future__ import annotations

import re
from pathlib import Path

from shopping_bot.gui.paths import env_example_path, env_path

try:
    from shopping_bot.config import (
        DEFAULT_AI_API_BASE_URL,
        DEFAULT_VISION_MODEL,
        infer_ai_defaults,
        normalize_vision_model,
        provider_supports_vision,
    )
except ImportError:
    DEFAULT_AI_API_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_VISION_MODEL = "google/gemini-2.5-flash"

    def normalize_vision_model(model: str) -> str:
        cleaned = model.strip()
        legacy = {
            "google/gemini-2.0-flash-001": DEFAULT_VISION_MODEL,
            "google/gemini-2.0-flash": DEFAULT_VISION_MODEL,
        }
        return legacy.get(cleaned, cleaned)

    def infer_ai_defaults(base_url: str) -> tuple[str, str]:
        lowered = base_url.lower()
        if "deepseek.com" in lowered:
            return "deepseek-chat", ""
        if "openai.com" in lowered:
            return "gpt-4o-mini", "gpt-4o"
        if "openrouter.ai" in lowered:
            return "openrouter/free", DEFAULT_VISION_MODEL
        return "gpt-4o-mini", "gpt-4o-mini"

    def provider_supports_vision(base_url: str) -> bool:
        return bool(infer_ai_defaults(base_url)[1])

ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

DEFAULT_VISION_MODEL = "google/gemini-2.5-flash"

_LEGACY_AI_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("AI_API_KEY", "OPENROUTER_API_KEY"),
    ("AI_API_BASE_URL", "OPENROUTER_API_BASE_URL"),
    ("AI_DEFAULT_MODEL", "OPENROUTER_DEFAULT_MODEL"),
    ("AI_VISION_MODEL", "OPENROUTER_VISION_MODEL"),
    ("AI_MODELS", "OPENROUTER_MODELS"),
)

# (env_key, label, required, secret, hint)
CORE_SETUP_FIELDS: list[tuple[str, str, bool, bool, str]] = [
    ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token", True, True, "从 @BotFather 获取"),
    (
        "ALLOWED_TELEGRAM_USER_IDS",
        "允许使用的 Telegram 用户 ID",
        False,
        False,
        "可选。逗号分隔多个 ID；留空表示任何人可用，无需填写。",
    ),
    ("NOTION_TOKEN", "Notion Integration Token", True, True, "ntn_ 或 secret_ 开头"),
    ("NOTION_DATABASE_ID", "Notion 数据库 ID", True, False, "32 位 ID"),
]

AI_SETUP_FIELDS: list[tuple[str, str, bool, bool, str]] = [
    (
        "AI_API_BASE_URL",
        "AI API 地址",
        False,
        False,
        "OpenAI 兼容接口。OpenRouter: https://openrouter.ai/api/v1 · OpenAI: https://api.openai.com/v1 · DeepSeek: https://api.deepseek.com/v1",
    ),
    (
        "AI_API_KEY",
        "AI API Key",
        True,
        True,
        "对应服务商的 Key（OpenRouter / OpenAI / DeepSeek / 其他兼容接口）",
    ),
    (
        "AI_DEFAULT_MODEL",
        "默认对话模型",
        False,
        False,
        "留空则按 API 地址自动推断（DeepSeek→deepseek-chat，OpenAI→gpt-4o-mini 等）",
    ),
    (
        "AI_MODELS",
        "可选模型列表",
        False,
        False,
        "可选。逗号分隔，供 /model 切换；留空则使用默认对话模型",
    ),
    (
        "AI_VISION_API_BASE_URL",
        "视觉 API 地址（可选）",
        False,
        False,
        "主 API 不支持图片时必填。例：OpenRouter https://openrouter.ai/api/v1",
    ),
    (
        "AI_VISION_API_KEY",
        "视觉 API Key（可选）",
        False,
        True,
        "与视觉 API 地址对应的 Key（DeepSeek 对话 + OpenRouter 识图 是常见组合）",
    ),
    (
        "AI_VISION_MODEL",
        "视觉识别模型",
        False,
        False,
        f"须支持 vision。OpenRouter 可用 {DEFAULT_VISION_MODEL}；留空则按视觉 API 推断",
    ),
]

SETUP_FIELDS: list[tuple[str, str, bool, bool, str]] = CORE_SETUP_FIELDS + AI_SETUP_FIELDS

ADVANCED_FIELDS: list[tuple[str, str, bool, bool, str]] = [
    ("SEARCH_PROVIDER", "搜索提供商", False, False, "duckduckgo 或 google"),
    ("SEARCH_RESULT_COUNT", "搜索结果数量", False, False, "5"),
    ("GOOGLE_CSE_API_KEY", "Google CSE API Key", False, True, "仅 google 搜索需要"),
    ("GOOGLE_CSE_ID", "Google CSE ID", False, False, "仅 google 搜索需要"),
    ("NOTION_TITLE_PROPERTY", "Notion 名称列", False, False, "名称"),
    ("NOTION_URL_PROPERTY", "Notion 链接列", False, False, "链接"),
    ("NOTION_CATEGORY_PROPERTY", "Notion 分类列", False, False, "分类"),
    ("NOTION_STATUS_PROPERTY", "Notion 状态列", False, False, "状态"),
    ("NOTION_STATUS_PROPERTY_TYPE", "状态列类型", False, False, "status 或 select"),
    ("NOTION_DEFAULT_STATUS", "默认状态", False, False, "未开始"),
    ("NOTION_NOTES_PROPERTY", "Notion 备注列", False, False, "备注"),
    ("NOTION_ADDED_AT_PROPERTY", "Notion 添加时间列", False, False, "Added At"),
]


def missing_required_fields(values: dict[str, str]) -> list[str]:
    missing: list[str] = []
    for key, label, required, *_rest in SETUP_FIELDS:
        if required and not values.get(key, "").strip():
            missing.append(label)
    return missing


def _unquote(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
        inner = cleaned[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return cleaned


def _quote(value: str) -> str:
    if not value:
        return ""
    if re.fullmatch(r"[\w\-./:@+,]+", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ENV_LINE_RE.match(stripped)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    return values


def _migrate_legacy_ai_env(merged: dict[str, str]) -> dict[str, str]:
    for new_key, old_key in _LEGACY_AI_ENV_KEYS:
        if not merged.get(new_key, "").strip() and merged.get(old_key, "").strip():
            merged[new_key] = merged[old_key]
    base_url = merged.get("AI_API_BASE_URL", "").strip() or DEFAULT_AI_API_BASE_URL
    merged["AI_API_BASE_URL"] = base_url
    chat_default, main_vision = infer_ai_defaults(base_url)
    if not merged.get("AI_DEFAULT_MODEL", "").strip():
        merged["AI_DEFAULT_MODEL"] = chat_default
    vision_base = merged.get("AI_VISION_API_BASE_URL", "").strip()
    vision_key = merged.get("AI_VISION_API_KEY", "").strip()
    if vision_base and vision_key and not merged.get("AI_VISION_MODEL", "").strip():
        _, vision_default = infer_ai_defaults(vision_base)
        merged["AI_VISION_MODEL"] = normalize_vision_model(vision_default or DEFAULT_VISION_MODEL)
    elif provider_supports_vision(base_url) and not merged.get("AI_VISION_MODEL", "").strip():
        merged["AI_VISION_MODEL"] = normalize_vision_model(main_vision)
    elif merged.get("AI_VISION_MODEL", "").strip():
        merged["AI_VISION_MODEL"] = normalize_vision_model(merged["AI_VISION_MODEL"])
    return merged


def _strip_legacy_ai_keys(values: dict[str, str]) -> dict[str, str]:
    cleaned = dict(values)
    if cleaned.get("AI_API_KEY", "").strip():
        for _, old_key in _LEGACY_AI_ENV_KEYS:
            cleaned.pop(old_key, None)
    return cleaned


def apply_ai_defaults(values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Fill empty model fields from API base URL; return notes for the GUI."""
    merged = dict(values)
    notes: list[str] = []
    base_url = merged.get("AI_API_BASE_URL", "").strip() or DEFAULT_AI_API_BASE_URL
    merged["AI_API_BASE_URL"] = base_url
    chat_default, main_vision = infer_ai_defaults(base_url)
    if not merged.get("AI_DEFAULT_MODEL", "").strip():
        merged["AI_DEFAULT_MODEL"] = chat_default
        notes.append(f"默认对话模型已自动设为 {chat_default}")
    if not merged.get("AI_MODELS", "").strip():
        merged["AI_MODELS"] = merged["AI_DEFAULT_MODEL"]
        notes.append("可选模型列表已自动设为默认对话模型")

    vision_base = merged.get("AI_VISION_API_BASE_URL", "").strip()
    vision_key = merged.get("AI_VISION_API_KEY", "").strip()
    if vision_base and vision_key:
        _, vision_default = infer_ai_defaults(vision_base)
        if not vision_default:
            vision_default = DEFAULT_VISION_MODEL
        if not merged.get("AI_VISION_MODEL", "").strip():
            merged["AI_VISION_MODEL"] = vision_default
            notes.append(f"视觉识别模型已自动设为 {vision_default}")
        else:
            old = merged["AI_VISION_MODEL"]
            merged["AI_VISION_MODEL"] = normalize_vision_model(old)
            if merged["AI_VISION_MODEL"] != old:
                notes.append(f"视觉识别模型已更新为 {merged['AI_VISION_MODEL']}")
    elif provider_supports_vision(base_url):
        if not merged.get("AI_VISION_MODEL", "").strip() and main_vision:
            merged["AI_VISION_MODEL"] = normalize_vision_model(main_vision)
            notes.append(f"视觉识别模型已自动设为 {merged['AI_VISION_MODEL']}")
        elif merged.get("AI_VISION_MODEL", "").strip():
            old = merged["AI_VISION_MODEL"]
            merged["AI_VISION_MODEL"] = normalize_vision_model(old)
            if merged["AI_VISION_MODEL"] != old:
                notes.append(f"视觉识别模型已更新为 {merged['AI_VISION_MODEL']}")
    elif merged.get("AI_VISION_MODEL", "").strip():
        old = merged["AI_VISION_MODEL"]
        merged["AI_VISION_MODEL"] = normalize_vision_model(old)
        if merged["AI_VISION_MODEL"] != old:
            notes.append(f"视觉识别模型已更新为 {merged['AI_VISION_MODEL']}")
    elif not merged.get("AI_VISION_MODEL", "").strip():
        notes.append("当前对话 API 不支持图片，请填写视觉 API 地址、Key 和模型")
    return merged, notes


def load_merged_env() -> dict[str, str]:
    merged = parse_env_file(env_example_path())
    merged.update(parse_env_file(env_path()))
    return _migrate_legacy_ai_env(merged)


def patch_env(updates: dict[str, str]) -> Path:
    merged = load_merged_env()
    merged.update(updates)
    return save_env(merged)


def ordered_env_keys() -> list[str]:
    keys: list[str] = []
    for path in (env_example_path(), env_path()):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            match = ENV_LINE_RE.match(line.strip())
            if match:
                key = match.group(1)
                if key not in keys:
                    keys.append(key)
    for key, *_ in SETUP_FIELDS + ADVANCED_FIELDS:
        if key not in keys:
            keys.append(key)
    return keys


def save_env(values: dict[str, str]) -> Path:
    target = env_path()
    example = parse_env_file(env_example_path())
    merged = _strip_legacy_ai_keys({**example, **values})

    lines: list[str] = ["# Telegram Shopping Bot — saved from GUI"]
    written: set[str] = set()
    legacy_keys = {old for _, old in _LEGACY_AI_ENV_KEYS}

    if env_example_path().is_file():
        for raw in env_example_path().read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            match = ENV_LINE_RE.match(stripped) if stripped and not stripped.startswith("#") else None
            if match:
                key = match.group(1)
                if key in legacy_keys and merged.get("AI_API_KEY", "").strip():
                    continue
                lines.append(f"{key}={_quote(merged.get(key, ''))}")
                written.add(key)
            elif stripped.startswith("#") or not stripped:
                if not lines or lines[-1] != raw:
                    lines.append(raw)

    for key in ordered_env_keys():
        if key in written or key in legacy_keys:
            continue
        lines.append(f"{key}={_quote(merged.get(key, ''))}")

    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def create_env_from_example() -> Path:
    example = env_example_path()
    target = env_path()
    if not example.is_file():
        raise FileNotFoundError("缺少 .env.example")
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    return target
