from __future__ import annotations

import re
from pathlib import Path

from shopping_bot.gui.paths import env_example_path, env_path

ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

DEFAULT_VISION_MODEL = "google/gemini-2.0-flash-001"

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
    ("OPENROUTER_API_KEY", "OpenRouter API Key", True, True, "sk-or-v1-..."),
    ("OPENROUTER_DEFAULT_MODEL", "默认对话模型", False, False, "留空则使用 openrouter/free"),
    (
        "OPENROUTER_VISION_MODEL",
        "视觉识别模型",
        False,
        False,
        f"转发/发送照片时使用。须支持 vision，默认 {DEFAULT_VISION_MODEL}",
    ),
    (
        "OPENROUTER_MODELS",
        "可选模型列表",
        False,
        False,
        "可选。逗号分隔，供 /model 切换；留空则使用默认模型",
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


def load_merged_env() -> dict[str, str]:
    merged = parse_env_file(env_example_path())
    merged.update(parse_env_file(env_path()))
    if not merged.get("OPENROUTER_VISION_MODEL", "").strip():
        merged["OPENROUTER_VISION_MODEL"] = DEFAULT_VISION_MODEL
    return merged


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
    merged = {**example, **values}

    lines: list[str] = ["# Telegram Shopping Bot — saved from GUI"]
    written: set[str] = set()

    if env_example_path().is_file():
        for raw in env_example_path().read_text(encoding="utf-8").splitlines():
            stripped = raw.strip()
            match = ENV_LINE_RE.match(stripped) if stripped and not stripped.startswith("#") else None
            if match:
                key = match.group(1)
                lines.append(f"{key}={_quote(merged.get(key, ''))}")
                written.add(key)
            elif stripped.startswith("#") or not stripped:
                if not lines or lines[-1] != raw:
                    lines.append(raw)

    for key in ordered_env_keys():
        if key in written:
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
