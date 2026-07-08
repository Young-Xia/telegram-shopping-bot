from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class Intent(str, Enum):
    """High-level message intent for the private shopping bot."""

    # Shopping: user is typing a new category name.
    SHOPPING_CATEGORY = "shopping_category"
    # Bare forward: remember as material only, do not call AI or add.
    RECORD_FORWARD = "record_forward"
    # Reply to a forwarded message: start Q&A with forward as prompt context.
    ASK_START = "ask_start"
    # Reply to an AI ask answer: continue Q&A.
    ASK_FOLLOWUP = "ask_followup"
    # Everything else (plain text, non-forward photo, etc.).
    IGNORE = "ignore"


class AskMediaFocus(str, Enum):
    """Which part of a mixed image+text forward the user question targets."""

    IMAGE = "image"
    TEXT = "text"
    BOTH = "both"


_IMAGE_FOCUS_RE = re.compile(
    r"(图片|照片|截图|看图|识图|图上|图中|图片里|画面|识字|"
    r"图里|拍的是什么|识别图|提取图|翻译图|图上写|图内|"
    r"ocr|image|photo|picture|screenshot)",
    re.IGNORECASE,
)

_IMAGE_STRONG_RE = re.compile(
    r"(图片里|图中|图上|翻译图|识图|看图|截图里|照片里|图内文字|图上写)",
    re.IGNORECASE,
)

_TEXT_FOCUS_RE = re.compile(
    r"(文字|这段话|消息里|转发里|链接|上文|文字内容|根据文|"
    r"不要看图|忽略图|别看图|仅文|总结这段|翻译这段|翻译上文|"
    r"文字部分|标题|caption|描述|备注|链接里)",
    re.IGNORECASE,
)


def decide_ask_media_focus(
    question: str,
    *,
    has_photos: bool,
    has_text: bool,
) -> AskMediaFocus:
    """Pick image vs text path for mixed forwards based on the user's instruction."""
    if not has_photos:
        return AskMediaFocus.TEXT
    if not has_text:
        return AskMediaFocus.IMAGE

    q = question.strip()
    if _IMAGE_STRONG_RE.search(q):
        return AskMediaFocus.IMAGE

    image_hits = len(_IMAGE_FOCUS_RE.findall(q))
    text_hits = len(_TEXT_FOCUS_RE.findall(q))

    if text_hits > image_hits:
        return AskMediaFocus.TEXT
    if image_hits > text_hits:
        return AskMediaFocus.IMAGE

    lowered = q.casefold()
    if any(k in lowered for k in ("不要看图", "忽略图", "别看图", "仅文", "文字部分")):
        return AskMediaFocus.TEXT
    if any(k in lowered for k in ("图片", "照片", "截图")):
        return AskMediaFocus.IMAGE
    if "翻译" in lowered:
        return AskMediaFocus.TEXT
    if any(word in lowered for word in ("总结", "概括", "搜索", "查询", "介绍")):
        return AskMediaFocus.BOTH
    return AskMediaFocus.BOTH


@dataclass(frozen=True)
class MessageSignals:
    is_forwarded: bool
    has_reply: bool
    reply_is_forward: bool
    reply_is_ask_bot: bool
    awaiting_category: bool
    has_user_text: bool


def classify_message(signals: MessageSignals) -> Intent:
    """Classify a non-command message. Commands (/add, /ask, /clear) are handled separately."""
    if signals.awaiting_category:
        return Intent.SHOPPING_CATEGORY

    # A forwarded message itself is only stored for later /add or reply-to-ask.
    if signals.is_forwarded:
        return Intent.RECORD_FORWARD

    if signals.has_reply:
        if signals.reply_is_ask_bot:
            return Intent.ASK_FOLLOWUP
        if signals.reply_is_forward:
            return Intent.ASK_START
        return Intent.IGNORE

    return Intent.IGNORE


def is_ask_bot_message(text: str, *, result_prefix: str, followup_prefix: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    return (
        cleaned.startswith(result_prefix)
        or cleaned.startswith(followup_prefix)
        or cleaned.startswith("💬")
        or cleaned.startswith("🔍")
    )
