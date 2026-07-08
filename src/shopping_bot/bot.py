from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path

import httpx
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    MessageOrigin,
    Update,
)
from telegram.constants import ChatType, ReactionEmoji
from telegram.error import TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from shopping_bot.categories import DEFAULT_CATEGORIES
from shopping_bot.config import Settings, load_settings, provider_supports_vision
from shopping_bot.models import ProductAnalysis, SearchResult, ShoppingItem
from shopping_bot.services.notion import NotionClient
from shopping_bot.services.openrouter import OpenRouterClient, format_api_error_message
from shopping_bot.services.product_extract import ProductExtractService
from shopping_bot.services.search import (
    SearchService,
    extract_all_urls_from_text,
    extract_url_from_text,
    is_url,
    strip_urls_from_text,
)
from shopping_bot.services.vision import (
    analyze_chain_images,
    analyze_photo_file_ids,
    collect_photo_file_ids,
    download_photo_bytes,
    photo_to_data_url,
)
from shopping_bot.routing import (
    AskMediaFocus,
    Intent,
    MessageSignals,
    classify_message,
    decide_ask_media_focus,
    is_ask_bot_message,
)
from shopping_bot.text_format import format_ai_text

logger = logging.getLogger(__name__)

ASK_RESULT_PREFIX = "🔍 回答"
ASK_FOLLOWUP_PREFIX = "💬 继续回答"

# Vision fallbacks across providers.
# NOTE: Some accounts / privacy settings may block OpenAI/Google vision entirely.
VISION_FALLBACK_MODELS = [
    "qwen/qwen3-vl-32b-instruct",
]

BOT_COMMANDS = [
    BotCommand("start", "开始使用"),
    BotCommand("ask", "直接向 AI 提问"),
    BotCommand("add", "添加商品（链接或最近转发）"),
    BotCommand("save", "从回复的消息提取并保存商品"),
    BotCommand("clear", "清除 AI 对话上下文"),
    BotCommand("cancel", "取消当前添加流程"),
    BotCommand("model", "切换 AI 模型"),
    BotCommand("help", "查看帮助"),
]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _env_file() -> Path:
    return _project_root() / ".env"


def _schedule_client_close(client: object) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    result = close()
    if asyncio.iscoroutine(result):
        loop.create_task(result)


def _build_vision_client(settings: Settings, openrouter: OpenRouterClient) -> OpenRouterClient | None:
    if settings.ai_vision_api_key and settings.ai_vision_api_base_url:
        return OpenRouterClient(
            settings.ai_vision_api_key,
            base_url=settings.ai_vision_api_base_url,
        )
    if provider_supports_vision(settings.ai_api_base_url) and settings.vision_model.strip():
        return openrouter
    return None


def _reload_settings_if_stale(app: Application) -> Settings:
    """Reload .env when it changes so model/API edits apply without restart."""
    env_path = _env_file()
    try:
        mtime = env_path.stat().st_mtime if env_path.is_file() else 0.0
    except OSError:
        mtime = 0.0

    cached = app.bot_data.get("settings")
    if cached is not None and app.bot_data.get("settings_mtime") == mtime:
        return cached

    settings = load_settings(env_files=(str(env_path),) if env_path.is_file() else (".env",))
    prev: Settings | None = cached
    app.bot_data["settings"] = settings
    app.bot_data["settings_mtime"] = mtime

    if prev is not None and prev.telegram_bot_token != settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN changed in .env; restart the bot to apply it")

    main_changed = (
        prev is None
        or prev.ai_api_key != settings.ai_api_key
        or prev.ai_api_base_url != settings.ai_api_base_url
    )
    vision_creds_changed = (
        prev is None
        or prev.ai_vision_api_key != settings.ai_vision_api_key
        or prev.ai_vision_api_base_url != settings.ai_vision_api_base_url
        or main_changed
    )
    notion_changed = (
        prev is None
        or prev.notion.token != settings.notion.token
        or prev.notion.database_id != settings.notion.database_id
    )

    if main_changed:
        old_main = app.bot_data.get("openrouter")
        openrouter = OpenRouterClient(settings.ai_api_key, base_url=settings.ai_api_base_url)
        app.bot_data["openrouter"] = openrouter
        app.bot_data["product_extract"] = ProductExtractService(openrouter)
        if old_main is not None and old_main is not app.bot_data.get("vision_client"):
            _schedule_client_close(old_main)
    else:
        openrouter = app.bot_data["openrouter"]

    if vision_creds_changed:
        old_vision = app.bot_data.get("vision_client")
        vision = _build_vision_client(settings, openrouter)
        app.bot_data["vision_client"] = vision
        if (
            old_vision is not None
            and old_vision is not openrouter
            and old_vision is not vision
        ):
            _schedule_client_close(old_vision)

    if notion_changed:
        old_notion = app.bot_data.get("notion")
        app.bot_data["notion"] = NotionClient(settings.notion)
        if old_notion is not None:
            _schedule_client_close(old_notion)

    if prev is not None:
        if prev.vision_model != settings.vision_model:
            logger.info("Vision model hot-reloaded: %s -> %s", prev.vision_model, settings.vision_model)
        if prev.default_model != settings.default_model:
            logger.info("Chat model hot-reloaded: %s -> %s", prev.default_model, settings.default_model)

    return settings


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return _reload_settings_if_stale(context.application)


def _openrouter(context: ContextTypes.DEFAULT_TYPE) -> OpenRouterClient:
    _settings(context)
    return context.application.bot_data["openrouter"]


def _vision_client(context: ContextTypes.DEFAULT_TYPE) -> OpenRouterClient | None:
    _settings(context)
    return context.application.bot_data.get("vision_client")


def _vision_ready(context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = _settings(context)
    client = context.application.bot_data.get("vision_client")
    return bool(client and settings.vision_model.strip())


def _vision_unavailable_message(context: ContextTypes.DEFAULT_TYPE) -> str:
    settings = _settings(context)
    if settings.ai_vision_api_base_url and not settings.ai_vision_api_key:
        return "请在设置中填写「视觉 API Key」。"
    if settings.ai_vision_api_key and not settings.ai_vision_api_base_url:
        return "请在设置中填写「视觉 API 地址」。"
    if not settings.vision_model.strip():
        return "请在设置中填写「视觉识别模型」。"
    if not provider_supports_vision(settings.ai_api_base_url):
        return (
            "当前对话 API 不支持图片识别（如 DeepSeek）。"
            "请在设置中填写「视觉 API 地址 / Key / 模型」（可用 OpenRouter）。"
        )
    return "图片识别暂时不可用，请稍后重试。"


def _search(context: ContextTypes.DEFAULT_TYPE) -> SearchService:
    _settings(context)
    return context.application.bot_data["search"]


def _notion(context: ContextTypes.DEFAULT_TYPE) -> NotionClient:
    _settings(context)
    return context.application.bot_data["notion"]


def _product_extract(context: ContextTypes.DEFAULT_TYPE) -> ProductExtractService:
    _settings(context)
    return context.application.bot_data["product_extract"]


def _current_model(context: ContextTypes.DEFAULT_TYPE) -> str:
    settings = _settings(context)
    return str(context.user_data.get("model") or settings.default_model)


def _vision_model(context: ContextTypes.DEFAULT_TYPE) -> str:
    settings = _settings(context)
    return str(context.user_data.get("vision_model") or settings.vision_model)


async def _acknowledge_message(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.set_message_reaction(
            chat_id=message.chat_id,
            message_id=message.message_id,
            reaction=ReactionEmoji.EYES,
        )
    except Exception:
        logger.debug("Could not set message reaction", exc_info=True)


def _is_authorized(update: Update, settings: Settings) -> bool:
    if not settings.allowed_user_ids:
        return True
    user = update.effective_user
    return bool(user and user.id in settings.allowed_user_ids)


async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if _is_authorized(update, _settings(context)):
        return True
    if update.effective_message:
        await update.effective_message.reply_text("这是私人机器人，你没有使用权限。")
    return False


def _args_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args).strip()


def _clear_flow_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear shopping / add-product flow only. Search Q&A session is independent."""
    for key in (
        "pending_item",
        "categories",
        "flow_source",
        "awaiting_category",
        "forward_payload",
        "suggested_category",
        "pending_photo_file_ids",
    ):
        context.user_data.pop(key, None)


def _get_chat_history(context: ContextTypes.DEFAULT_TYPE) -> list[dict[str, str]]:
    raw = context.user_data.get("chat_history")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("role") and item.get("content")]


def _append_chat_history(context: ContextTypes.DEFAULT_TYPE, role: str, content: str) -> None:
    history = _get_chat_history(context)
    # Keep long extractions (e.g. multi-case OCR) for follow-up questions.
    history.append({"role": role, "content": content[:12000]})
    context.user_data["chat_history"] = history[-20:]


def _clear_ask_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("ask_session", None)
    context.user_data.pop("search_session", None)
    context.user_data.pop("search_message_ids", None)


def _clear_chat_history(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear AI Q&A context only. Does not touch shopping / add-product flow."""
    context.user_data.pop("chat_history", None)
    context.user_data.pop("ask_forward_context", None)
    context.user_data.pop("ask_photo_file_ids", None)
    context.user_data.pop("ask_last_answer", None)
    _clear_ask_session(context)


def _start_ask_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["ask_session"] = {"active": True, "message_ids": []}


def _mark_ask_message(context: ContextTypes.DEFAULT_TYPE, message_id: int | None) -> None:
    if not message_id:
        return
    session = context.user_data.get("ask_session")
    if not isinstance(session, dict):
        session = {"active": True, "message_ids": []}
        context.user_data["ask_session"] = session
    session["active"] = True
    ids = session.get("message_ids")
    if not isinstance(ids, list):
        ids = []
    if message_id not in ids:
        ids.append(int(message_id))
    session["message_ids"] = ids[-50:]


def _ask_message_ids(context: ContextTypes.DEFAULT_TYPE) -> list[int]:
    session = context.user_data.get("ask_session")
    if not isinstance(session, dict) or not isinstance(session.get("message_ids"), list):
        return []
    ids: list[int] = []
    for item in session["message_ids"]:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


def _reply_is_ask_bot(message: Message, context: ContextTypes.DEFAULT_TYPE) -> bool:
    replied = message.reply_to_message
    if not replied:
        return False
    if replied.message_id in _ask_message_ids(context):
        return True
    return is_ask_bot_message(
        replied.text or replied.caption or "",
        result_prefix=ASK_RESULT_PREFIX,
        followup_prefix=ASK_FOLLOWUP_PREFIX,
    )


def _reply_is_forward(message: Message) -> bool:
    replied = message.reply_to_message
    return bool(replied and _is_forwarded(replied))


def _format_ask_message(answer: str, *, followup: bool = False) -> str:
    prefix = ASK_FOLLOWUP_PREFIX if followup else ASK_RESULT_PREFIX
    body = answer[:3600]
    footer = "💬 回复这条消息可继续提问。添加商品请用 /add。"
    return f"{prefix}\n\n{body}\n\n{footer}"[:4096]


def _extract_ask_answer_body(text: str) -> str:
    """Pull the answer body out of a bot ask message (drop prefix/footer)."""
    cleaned = (text or "").strip()
    for prefix in (ASK_RESULT_PREFIX, ASK_FOLLOWUP_PREFIX):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].lstrip("\n")
            break
    for marker in ("💬 回复这条消息可继续提问", "添加商品请用 /add"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].rstrip()
    return cleaned.strip()


def _prior_ask_context(message: Message, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Rebuild prior answer context for follow-ups from memory + replied message."""
    chunks: list[str] = []
    last = str(context.user_data.get("ask_last_answer") or "").strip()
    if last:
        chunks.append(last)

    replied = message.reply_to_message
    if replied:
        body = _extract_ask_answer_body(replied.text or replied.caption or "")
        if body and body not in chunks:
            # Prefer the longer copy when both exist.
            if not chunks or len(body) > len(chunks[0]):
                chunks = [body, *[c for c in chunks if c != body]]
            else:
                chunks.append(body)

    for item in _get_chat_history(context):
        if item.get("role") != "assistant":
            continue
        content = str(item.get("content") or "").strip()
        if content and content not in chunks:
            chunks.append(content)

    if not chunks:
        return ""
    merged = "\n\n----\n\n".join(chunks)
    return merged[:12000]


def _looks_like_safety_only_answer(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    lowered = cleaned.casefold()
    if len(cleaned) <= 40 and "user safety" in lowered:
        return True
    if lowered in {"safe", "unsafe", "user safety: safe", "user safety: unsafe"}:
        return True
    if lowered.startswith("user safety:") and len(cleaned) < 80:
        return True
    return False


def _remember_forward_message(context: ContextTypes.DEFAULT_TYPE, message: Message) -> None:
    import time

    chain = [message]
    context.user_data["last_forward"] = {
        "message_id": message.message_id,
        "chat_id": message.chat_id,
        "thread_text": _format_chain_for_ai(chain),
        "urls": _collect_urls_from_chain(chain),
        "photo_file_ids": collect_photo_file_ids(chain),
        "saved_at": time.time(),
    }


def _get_last_forward(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    raw = context.user_data.get("last_forward")
    return raw if isinstance(raw, dict) else None


async def _ask_ai(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    question: str,
    *,
    followup: bool = False,
) -> None:
    message = update.effective_message
    question = question.strip()
    if not question:
        await message.reply_text("请输入你想问的问题。")
        return

    _start_ask_session(context)
    status = await message.reply_text("🔍 思考中…")
    _mark_ask_message(context, status.message_id)

    forward_context = str(context.user_data.get("ask_forward_context") or "").strip()
    if len(forward_context) > 6000:
        forward_context = forward_context[:6000] + "\n…(已截断)"

    photo_ids = context.user_data.get("ask_photo_file_ids") or []
    if not isinstance(photo_ids, list):
        photo_ids = []

    meaningful_text = _extract_meaningful_thread_text(forward_context)
    media_focus = decide_ask_media_focus(
        question,
        has_photos=bool(photo_ids),
        has_text=bool(meaningful_text),
    )

    # Follow-ups use text chat + explicit prior answer context.
    # Re-sending images every turn often hits vision rate limits.
    use_vision = (
        media_focus in (AskMediaFocus.IMAGE, AskMediaFocus.BOTH)
        and bool(photo_ids)
        and not followup
    )
    vision_error = ""

    try:
        answer = ""
        if use_vision:
            vision = _vision_client(context)
            vision_model = _vision_model(context).strip()
            if not vision or not vision_model:
                await status.edit_text(f"回答失败：{_vision_unavailable_message(context)}")
                return
            try:
                data_url = await photo_to_data_url(context.bot, str(photo_ids[0]))
            except TimedOut:
                vision_error = "从 Telegram 下载图片超时，请稍后重试。"
                use_vision = False
                data_url = ""
            if media_focus == AskMediaFocus.IMAGE:
                if forward_context:
                    prompt = (
                        "用户问题主要针对图片内容，转发文字仅供参考：\n"
                        f"{forward_context}\n\n"
                        f"用户问题：{question}\n\n"
                        "请直接查看图片并回答。不要说你看不到图片。"
                    )
                else:
                    prompt = (
                        f"用户问题：{question}\n\n"
                        "请直接查看图片并回答。不要说你看不到图片。"
                    )
            else:
                prompt = (
                    "用户转发了图片和文字，请结合两者回答。\n"
                    f"文字背景：\n{forward_context}\n\n"
                    f"用户问题：{question}\n\n"
                    "请直接查看图片并回答。不要说你看不到图片。"
                )
            try:
                answer = await vision.search_with_image(
                    model=vision_model,
                    query=prompt,
                    image_url=data_url,
                    history=None,
                    fallback_models=[m for m in VISION_FALLBACK_MODELS if m != vision_model],
                )
            except Exception as exc:  # noqa: BLE001
                vision_error = str(exc)
                logger.warning("Vision ask failed", exc_info=True)
                answer = ""

            if answer and _looks_like_safety_only_answer(answer):
                vision_error = vision_error or "视觉模型只返回了安全检查结果"
                answer = ""

            if not answer:
                use_vision = False
                logger.info(
                    "Vision path unavailable (focus=%s), falling back to text chat",
                    media_focus.value,
                )

        if not use_vision:
            history = None
            if followup:
                prior = _prior_ask_context(message, context)
                if prior:
                    # Embed prior answer directly so follow-ups don't depend on
                    # fragile chat-history alone (and survive partial truncations).
                    prompt = (
                        f"【先前回答】\n{prior}\n\n"
                        f"【用户追问】\n{question}\n\n"
                        "请基于先前回答继续作答。只输出最终答案。"
                    )
                else:
                    prompt = question
                    history = _get_chat_history(context)[-8:]
            elif forward_context:
                if media_focus == AskMediaFocus.TEXT and photo_ids:
                    prompt = (
                        f"{forward_context}\n\n"
                        f"问题：{question}\n\n"
                        "请只根据上述文字/链接内容回答，不要讨论或猜测图片内容。"
                        "只输出最终答案。"
                    )
                else:
                    prompt = (
                        f"{forward_context}\n\n"
                        f"问题：{question}\n\n"
                        "只输出最终答案。"
                    )
                if vision_error and photo_ids:
                    prompt += (
                        "\n\n（说明：图片识别失败，以下仅基于文字背景作答；"
                        "如需识图请换视觉模型，如 openai/gpt-4o。）"
                    )
            else:
                prompt = question
            answer = await _openrouter(context).answer(
                model=_current_model(context),
                prompt=prompt,
                history=history,
            )
            history_user = question if followup else prompt
        else:
            history_user = f"[含图片/{media_focus.value}] {question}"

        answer = format_ai_text(answer)
        if not answer:
            if vision_error and photo_ids and not forward_context:
                raise RuntimeError(vision_error)
            raise RuntimeError("AI 返回了空内容")
        _append_chat_history(context, "user", history_user)
        _append_chat_history(context, "assistant", answer)
        context.user_data["ask_last_answer"] = answer
        sent = await status.edit_text(_format_ask_message(answer, followup=followup))
        _mark_ask_message(context, getattr(sent, "message_id", None) or status.message_id)
    except httpx.HTTPStatusError as exc:
        logger.exception("Ask AI failed")
        parsed = None
        try:
            parsed = exc.response.json()
        except Exception:
            parsed = None
        detail = format_api_error_message(
            status_code=exc.response.status_code,
            body=exc.response.text,
            parsed=parsed if isinstance(parsed, dict) else None,
        )
        await status.edit_text(f"回答失败：{detail}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ask AI failed")
        detail = str(exc)
        if len(detail) > 400 and "403" in detail:
            detail = format_api_error_message(status_code=403, body=detail)
        await status.edit_text(f"回答失败：{detail}")


async def _begin_ask_from_forward_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
) -> None:
    replied = message.reply_to_message
    if not replied:
        return
    _remember_forward_message(context, replied)

    user_question = _message_body(message).strip() or "请根据这条转发内容，简洁介绍关键信息。"
    chain = [replied]
    thread_text = _format_chain_for_ai(chain)
    urls = _collect_urls_from_chain(chain)
    photo_ids = collect_photo_file_ids(chain)
    context.user_data["ask_photo_file_ids"] = photo_ids

    # Text/link background only. Photos are sent directly to the vision model.
    parts = [thread_text]
    if urls:
        link_hint = await _build_link_hint(context, urls)
        if link_hint:
            parts.append(link_hint)
    context.user_data["ask_forward_context"] = "\n\n".join(part for part in parts if part).strip()
    await _ask_ai(update, context, user_question, followup=False)


def _chain_from_message(message: Message) -> list[Message]:
    if message.reply_to_message:
        return _collect_reply_chain(message)
    return [message]


def _message_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _message_entities(message: Message):
    if message.text and message.entities:
        return message.entities
    if message.caption and message.caption_entities:
        return message.caption_entities
    return message.entities or message.caption_entities


def _extract_url_from_message(message: Message) -> str | None:
    text = _message_text(message)
    if not text:
        return None
    entities = _message_entities(message)
    if entities:
        for entity in entities:
            if entity.type == "url":
                part = text[entity.offset : entity.offset + entity.length]
                found = extract_url_from_text(part)
                if found:
                    return found
            if entity.type == "text_link" and entity.url:
                return entity.url
    return extract_url_from_text(text)


def _extract_title_from_message(message: Message, url: str) -> str | None:
    text = _message_text(message)
    if not text:
        return None

    entities = _message_entities(message)
    if entities:
        chunks: list[str] = []
        last = 0
        for entity in sorted(entities, key=lambda item: item.offset):
            if entity.type in {"url", "text_link"}:
                if entity.offset > last:
                    chunks.append(text[last : entity.offset])
                last = entity.offset + entity.length
        chunks.append(text[last:])
        title = "".join(chunks)
    else:
        title = text.replace(url, " ")

    title = strip_urls_from_text(title)
    title = re.sub(r"^[\s\-–—|:：]+|[\s\-–—|:：]+$", "", title)
    if len(title) < 2:
        return None
    return title[:200]


def _extract_title_from_plain_text(text: str, url: str) -> str | None:
    cleaned = strip_urls_from_text(text.replace(url, " "))
    cleaned = re.sub(r"^[\s\-–—|:：]+|[\s\-–—|:：]+$", "", cleaned)
    if len(cleaned) < 2:
        return None
    return cleaned[:200]


def _message_body(message: Message) -> str:
    return _message_text(message)


def _collect_reply_chain(message: Message, limit: int = 10) -> list[Message]:
    chain = [message]
    current = message.reply_to_message
    while current and len(chain) < limit:
        chain.append(current)
        current = current.reply_to_message
    chain.reverse()
    return chain


def _collect_urls_from_chain(chain: list[Message]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for msg in chain:
        direct = _extract_url_from_message(msg)
        if direct and direct not in seen:
            urls.append(direct)
            seen.add(direct)
        for url in extract_all_urls_from_text(_message_body(msg)):
            if url not in seen:
                urls.append(url)
                seen.add(url)
    return urls


def _forward_origin_label(message: Message) -> str | None:
    origin = message.forward_origin
    if origin is None:
        return None
    if origin.type == MessageOrigin.USER:
        user = getattr(origin, "sender_user", None)
        if user is not None:
            return user.full_name
    elif origin.type == MessageOrigin.HIDDEN_USER:
        name = getattr(origin, "sender_user_name", None)
        if name:
            return name
    elif origin.type == MessageOrigin.CHAT:
        chat = getattr(origin, "sender_chat", None)
        if chat is not None:
            return chat.title or chat.full_name
    elif origin.type == MessageOrigin.CHANNEL:
        chat = getattr(origin, "chat", None)
        if chat is not None:
            return chat.title or chat.full_name
    return None


def _format_chain_for_ai(chain: list[Message]) -> str:
    parts: list[str] = []
    for idx, msg in enumerate(chain, 1):
        body = _message_body(msg)
        prefix = f"[{idx}]"
        if _is_forwarded(msg):
            origin = _forward_origin_label(msg)
            if origin:
                prefix = f"[{idx} 转发自 {origin}]"
            else:
                prefix = f"[{idx} 转发]"
        if body:
            parts.append(f"{prefix} {body}")
        elif msg.photo:
            parts.append(f"{prefix} (图片)")
        elif _is_forwarded(msg):
            parts.append(f"{prefix} (无文字)")
    return "\n\n".join(parts)


_PHOTO_ONLY_LINE_RE = re.compile(
    r"^\[\d+(?:\s+转发(?:自\s+.+)?)?\]\s*\((?:图片|无文字)\)\s*$"
)


def _extract_meaningful_thread_text(thread_text: str) -> str:
    blocks: list[str] = []
    for block in thread_text.split("\n\n"):
        cleaned = block.strip()
        if not cleaned or _PHOTO_ONLY_LINE_RE.fullmatch(cleaned):
            continue
        blocks.append(cleaned)
    return "\n\n".join(blocks).strip()


async def _build_link_hint(context: ContextTypes.DEFAULT_TYPE, urls: list[str]) -> str:
    if not urls:
        return ""
    parts: list[str] = []
    for index, url in enumerate(urls[:2], 1):
        try:
            parsed = await _search(context).parse_link(url)
            label = f"链接{index}" if len(urls) > 1 else "链接页面"
            title = parsed.title or url
            snippet = (parsed.snippet or "").strip()
            block = f"{label}标题: {title}"
            if parsed.url and parsed.url != url:
                block += f"\n最终链接: {parsed.url}"
            else:
                block += f"\n链接: {parsed.url or url}"
            if snippet:
                block += f"\n页面内容:\n{snippet[:1600]}"
            parts.append(block)
        except Exception:
            logger.warning("Could not prefetch link for AI analysis: %s", url, exc_info=True)
            parts.append(f"链接{index if len(urls) > 1 else ''}读取失败: {url}".strip())
    return "\n\n".join(parts)


def _is_forwarded(message: Message) -> bool:
    return message.forward_origin is not None


def _should_ai_extract_chain(chain: list[Message]) -> bool:
    if _collect_urls_from_chain(chain):
        return True
    if collect_photo_file_ids(chain):
        return True
    return sum(len(_message_body(msg)) for msg in chain) >= 8


def _analysis_is_saveable(analysis: ProductAnalysis) -> bool:
    if analysis.url:
        return True
    title = analysis.title.strip()
    return bool(title and title != "未命名商品")


async def _build_image_hint(context: ContextTypes.DEFAULT_TYPE, chain: list[Message]) -> str:
    photo_ids = collect_photo_file_ids(chain)
    if not photo_ids:
        return ""
    return await _build_image_hint_from_photo_ids(context, photo_ids)


async def _build_image_hint_from_photo_ids(
    context: ContextTypes.DEFAULT_TYPE,
    photo_ids: list[str],
) -> str:
    if not photo_ids:
        return ""
    client = _vision_client(context)
    if not client:
        return ""
    model = _vision_model(context)
    if not model.strip():
        return ""
    return await analyze_photo_file_ids(
        bot=context.bot,
        client=client,
        file_ids=photo_ids,
        model=model,
    )


async def _try_ai_chain_from_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    *,
    user_note: str = "",
) -> bool:
    chain = _chain_from_message(message)
    if not _should_ai_extract_chain(chain):
        return False
    await _begin_ai_chain_flow(update, context, chain, user_note=user_note)
    return True


async def _setup_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(BOT_COMMANDS)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    await update.effective_message.reply_text(
        "🛒 购物助手已就绪。\n\n"
        "🔍 询问\n"
        "• 转发消息本身不处理\n"
        "• 回复那条转发并提问 → AI 回答\n"
        "• 再回复 AI 回答 → 继续追问\n"
        "• /ask 问题 → 直接提问\n\n"
        "➕ 添加商品\n"
        "• /add 链接 或 /add 名称 链接\n"
        "• 先转发，再发 /add（用最近一条转发）\n"
        "• /save 回复一条消息后提取保存\n\n"
        "• /clear 清除 AI 上下文 · /cancel 取消添加 · /help 说明"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    await update.effective_message.reply_text(
        "📖 用法说明\n\n"
        "🔍 询问（不写 Notion）\n"
        "• 转发后，回复该转发并提问\n"
        "• 回复 AI 回答可继续追问\n"
        "• /ask 问题（不依赖转发）\n\n"
        "➕ 添加商品\n"
        "• /add 链接 或 /add 名称 链接\n"
        "• 先转发，再 /add（使用最近一条转发）\n"
        "• /save：回复消息后提取保存\n\n"
        "🛠 其他\n"
        "• /clear 只清 AI 上下文，不管添加\n"
        "• /cancel 取消添加流程\n"
        "• /model 切换模型\n\n"
        "链接相同或名称很像时，会更新已有条目。"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    had_chat = bool(_get_chat_history(context)) or bool(_ask_message_ids(context))
    _clear_chat_history(context)
    if not had_chat:
        await update.effective_message.reply_text("当前没有 AI 对话上下文。")
        return
    await update.effective_message.reply_text("已清除 AI 对话上下文。")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    if not any(
        context.user_data.get(key)
        for key in ("pending_item", "awaiting_category")
    ):
        await update.effective_message.reply_text("当前没有进行中的添加流程。")
        return
    _clear_flow_state(context)
    await update.effective_message.reply_text("已取消当前添加流程。")


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    settings = _settings(context)
    requested = _args_text(context)
    aliases = settings.model_aliases()

    if not requested:
        models = "\n".join(f"• {model}" for model in settings.models)
        await update.effective_message.reply_text(
            f"当前模型：{_current_model(context)}\n\n可选模型：\n{models}\n\n切换：/model 模型名"
        )
        return

    model = aliases.get(requested, requested)
    if model not in settings.models:
        await update.effective_message.reply_text("未知模型。发送 /model 查看可用列表。")
        return

    context.user_data["model"] = model
    await update.effective_message.reply_text(f"已切换模型：{model}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    prompt = _args_text(context)
    if message.reply_to_message and message.reply_to_message.text:
        quoted = message.reply_to_message.text
        prompt = f"请根据下面这条消息回答：\n\n{quoted}\n\n用户要求：{prompt or '请回答。'}"
    if not prompt:
        await message.reply_text("用法：/ask 你的问题\n也可以先回复某条消息，再发送 /ask。")
        return

    replied = message.reply_to_message
    if replied and (_is_forwarded(replied) or replied.photo):
        _remember_forward_message(context, replied)
        context.user_data["ask_photo_file_ids"] = collect_photo_file_ids([replied])
        text_bg = _format_chain_for_ai([replied])
        context.user_data["ask_forward_context"] = text_bg
    else:
        context.user_data.pop("ask_forward_context", None)
        context.user_data.pop("ask_photo_file_ids", None)

    await _ask_ai(update, context, prompt, followup=False)


async def reply_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message

    signals = MessageSignals(
        is_forwarded=_is_forwarded(message),
        has_reply=bool(message.reply_to_message),
        reply_is_forward=_reply_is_forward(message),
        reply_is_ask_bot=_reply_is_ask_bot(message, context),
        awaiting_category=bool(context.user_data.get("awaiting_category")),
        has_user_text=bool(_message_body(message).strip()),
    )
    intent = classify_message(signals)

    # Bare forwards stay silent: only remember material for later /add or reply-to-ask.
    if intent != Intent.RECORD_FORWARD:
        await _acknowledge_message(message, context)

    if intent == Intent.SHOPPING_CATEGORY:
        category = (message.text or message.caption or "").strip()
        await _save_with_new_category(update, context, category)
        return

    if intent == Intent.RECORD_FORWARD:
        _remember_forward_message(context, message)
        return

    if intent == Intent.ASK_START:
        await _begin_ask_from_forward_reply(update, context, message)
        return

    if intent == Intent.ASK_FOLLOWUP:
        await _ask_ai(update, context, _message_body(message), followup=True)
        return

    # IGNORE: no auto link-add, no passive product extract.
    if message.chat.type == ChatType.PRIVATE:
        return

    if not message.reply_to_message or not message.reply_to_message.text:
        return

    bot_username = (await context.bot.get_me()).username
    if not bot_username or f"@{bot_username.lower()}" not in (message.text or "").lower():
        return

    quoted = message.reply_to_message.text
    prompt = f"请根据下面这条消息回答：\n\n{quoted}\n\n用户要求：{message.text}"
    await _answer_prompt(update, context, prompt)


async def _answer_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:
    message = update.effective_message
    status = await message.reply_text(f"正在思考（{_current_model(context)}）…")
    try:
        answer = await _openrouter(context).answer(
            model=_current_model(context),
            prompt=prompt,
            history=_get_chat_history(context),
        )
        answer = format_ai_text(answer)
        _append_chat_history(context, "user", prompt)
        _append_chat_history(context, "assistant", answer)
        await status.edit_text(answer[:4096])
    except httpx.HTTPStatusError as exc:
        logger.exception("OpenRouter HTTP error")
        await status.edit_text(f"AI 请求失败：{exc.response.status_code} {exc.response.text[:500]}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenRouter request failed")
        await status.edit_text(f"AI 请求失败：{exc}")


async def _begin_link_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    *,
    source: str,
    title_override: str | None = None,
) -> None:
    status = await update.effective_message.reply_text("正在读取链接内容并提取商品信息…")
    final_url = url
    link_hint = ""
    try:
        parsed = await _search(context).parse_link(url)
        final_url = parsed.url or url
        title = title_override or parsed.title or final_url
        snippet = (parsed.snippet or "").strip()
        link_hint = f"链接页面标题: {title}\n链接: {final_url}"
        if snippet:
            link_hint += f"\n页面内容:\n{snippet[:1600]}"
        if not title_override:
            title_override = parsed.title
    except httpx.HTTPStatusError as exc:
        if not title_override:
            await status.edit_text(f"无法读取链接：{exc.response.status_code} {exc.response.text[:500]}")
            return
        link_hint = f"链接页面标题: {title_override}\n链接: {url}\n页面内容: 未能读取页面详情，已使用你提供的文字。"
    except Exception as exc:  # noqa: BLE001
        if not title_override:
            logger.exception("Link parse failed")
            await status.edit_text(f"无法读取链接：{exc}")
            return
        logger.warning("Link parse failed, using provided title", exc_info=True)
        link_hint = f"链接页面标题: {title_override}\n链接: {url}\n页面内容: 未能读取页面详情，已使用你提供的文字。"

    categories: list[str] = []
    try:
        categories = await _notion(context).list_categories()
    except Exception:
        logger.warning("Could not load Notion categories before link extract", exc_info=True)
    if not categories:
        categories = list(DEFAULT_CATEGORIES)

    thread_text = title_override or ""
    try:
        analysis = await _analyze_chain_for_product(
            context,
            thread_text,
            [final_url],
            link_hint=link_hint,
            categories=categories,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI link extract failed")
        analysis = ProductAnalysis(
            title=title_override or final_url,
            url=final_url,
            notes=(link_hint.split("页面内容:\n", 1)[-1] if "页面内容:" in link_hint else "")[:2000],
            what="商品链接",
        )

    if not _analysis_is_saveable(analysis):
        await status.edit_text("没能从链接识别出商品，请补上商品名称后再试，或改用 /add 商品名 链接。")
        return

    context.user_data["flow_source"] = source
    await _begin_category_flow(update, context, analysis, status_message=status)


async def _analyze_chain_for_product(
    context: ContextTypes.DEFAULT_TYPE,
    thread_text: str,
    urls: list[str],
    *,
    user_note: str = "",
    link_hint: str = "",
    image_hint: str = "",
    categories: list[str] | None = None,
) -> ProductAnalysis:
    if user_note.startswith("/"):
        user_note = ""

    if not link_hint and urls:
        link_hint = await _build_link_hint(context, urls)

    analysis = await _product_extract(context).extract_from_reply_chain(
        model=_current_model(context),
        thread_text=thread_text,
        urls=urls,
        user_note=user_note,
        link_hint=link_hint,
        image_hint=image_hint,
        categories=categories,
    )

    result = analysis.as_search_result()
    if not result.url and urls:
        result = SearchResult(title=result.title, url=urls[0], snippet=result.snippet)

    if result.url:
        try:
            parsed = await _search(context).parse_link(result.url)
            notes = result.snippet
            if parsed.snippet and parsed.snippet not in notes:
                notes = f"{notes}\n{parsed.snippet}".strip() if notes else parsed.snippet
            title = analysis.title
            if not title or title == result.url:
                title = parsed.title or analysis.title
            result = SearchResult(title=title, url=parsed.url or result.url, snippet=notes[:2000])
        except Exception:
            logger.warning("Could not enrich AI extract from product link", exc_info=True)
            result = SearchResult(title=analysis.title, url=result.url, snippet=result.snippet)

    return ProductAnalysis(
        title=result.title,
        url=result.url,
        notes=result.snippet,
        what=analysis.what,
        suggested_category=analysis.suggested_category,
    )


async def _begin_ai_chain_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chain: list[Message],
    *,
    user_note: str = "",
) -> None:
    status = await update.effective_message.reply_text("正在读取消息内容并提取商品信息…")
    thread_text = _format_chain_for_ai(chain)
    urls = _collect_urls_from_chain(chain)
    link_hint = await _build_link_hint(context, urls)
    image_hint = await _build_image_hint(context, chain)

    categories: list[str] = []
    try:
        categories = await _notion(context).list_categories()
    except Exception:
        logger.warning("Could not load Notion categories before extract", exc_info=True)
    if not categories:
        categories = list(DEFAULT_CATEGORIES)

    try:
        analysis = await _analyze_chain_for_product(
            context,
            thread_text,
            urls,
            user_note=user_note,
            link_hint=link_hint,
            image_hint=image_hint,
            categories=categories,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI reply-chain extract failed")
        await status.edit_text(f"无法分析这条消息：{exc}")
        return

    if not _analysis_is_saveable(analysis):
        await status.edit_text("没识别到商品信息。请确保消息里有链接、图片或商品描述。")
        return

    context.user_data["flow_source"] = "reply_chain"
    photo_ids = collect_photo_file_ids(chain)
    if photo_ids:
        context.user_data["pending_photo_file_ids"] = photo_ids
    await _begin_category_flow(update, context, analysis, status_message=status)


async def _begin_ai_chain_from_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Extract product from stored forward_payload (used by /add)."""
    payload = context.user_data.get("forward_payload")
    query = update.callback_query
    use_edit = bool(query and query.message)

    async def _status(text: str) -> Message | None:
        if use_edit and query and query.message:
            await query.edit_message_text(text)
            return query.message
        return await update.effective_message.reply_text(text)

    if not payload:
        await _status("请先转发一条消息，再发送 /add。")
        return

    thread_text = payload.get("thread_text") or ""
    urls = payload.get("urls") or []
    user_note = payload.get("user_note") or ""
    link_hint = payload.get("link_hint") or ""
    photo_ids = payload.get("photo_file_ids") or []

    status_message = await _status("正在提取商品信息…")

    if urls and not link_hint:
        if status_message:
            await status_message.edit_text("正在读取链接内容…")
        link_hint = await _build_link_hint(context, urls)
        payload["link_hint"] = link_hint
        context.user_data["forward_payload"] = payload

    status_parts: list[str] = []
    if urls:
        status_parts.append("链接")
    if photo_ids:
        status_parts.append("图片")
    status_label = "、".join(status_parts) if status_parts else "消息"
    if status_message:
        await status_message.edit_text(f"正在根据{status_label}提取商品信息…")

    image_hint = ""
    if photo_ids:
        image_hint = await _build_image_hint_from_photo_ids(context, photo_ids)
        has_other_context = bool(
            _extract_meaningful_thread_text(thread_text) or urls or link_hint
        )
        if not image_hint and not has_other_context:
            detail = (
                _vision_unavailable_message(context)
                if not _vision_ready(context)
                else "未能从图片中识别商品信息。"
            )
            if status_message:
                await status_message.edit_text(f"没识别到商品：{detail}")
            return

    categories = context.user_data.get("categories")
    if not categories:
        try:
            categories = await _notion(context).list_categories()
        except Exception:
            logger.warning("Could not load Notion categories before extract", exc_info=True)
            categories = list(DEFAULT_CATEGORIES)

    try:
        analysis = await _analyze_chain_for_product(
            context,
            thread_text,
            urls,
            user_note=user_note,
            link_hint=link_hint,
            image_hint=image_hint,
            categories=categories,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI product extract failed")
        if status_message:
            await status_message.edit_text(f"无法分析这条消息：{exc}")
        return

    if not _analysis_is_saveable(analysis):
        if status_message:
            await status_message.edit_text("没识别到商品信息。请确保转发里有链接、图片或商品描述。")
        return

    context.user_data.pop("forward_payload", None)
    context.user_data["flow_source"] = "add"
    if photo_ids:
        context.user_data["pending_photo_file_ids"] = photo_ids
    await _begin_category_flow(update, context, analysis, status_message=status_message)


def _format_product_preview(analysis: ProductAnalysis) -> str:
    lines: list[str] = []
    if analysis.what:
        lines.append(f"🧠 类型：{format_ai_text(analysis.what)}")
    lines.append(f"📦 名称：{format_ai_text(analysis.title)}")
    if analysis.url:
        lines.append(f"🔗 链接：{analysis.url}")
    if analysis.notes:
        notes = format_ai_text(analysis.notes)
        lines.append(f"📝 备注：\n{notes}" if "\n" in notes else f"📝 备注：{notes}")
    return "\n".join(lines)


def _as_product_analysis(item: ProductAnalysis | SearchResult | dict) -> ProductAnalysis:
    if isinstance(item, ProductAnalysis):
        return item
    if isinstance(item, dict):
        return ProductAnalysis(
            title=item["title"],
            url=item.get("url", ""),
            notes=item.get("notes") or item.get("snippet") or "",
            what=item.get("what", ""),
            suggested_category=item.get("suggested_category", ""),
        )
    return ProductAnalysis(title=item.title, url=item.url, notes=item.snippet)


async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    raw = _args_text(context)

    # /add with explicit link
    if raw:
        url = extract_url_from_text(raw)
        if not url:
            await message.reply_text("请提供有效的 http 或 https 链接。\n或先转发消息，再发送 /add。")
            return
        title = _extract_title_from_plain_text(raw, url)
        await _begin_link_flow(update, context, url, source="add", title_override=title)
        return

    # /add alone: use the most recent forward in this private chat
    last = _get_last_forward(context)
    if not last or last.get("chat_id") != message.chat_id:
        await message.reply_text("请先转发一条消息，再发送 /add。\n也可以：/add 链接")
        return

    context.user_data["forward_payload"] = {
        "thread_text": last.get("thread_text") or "",
        "urls": last.get("urls") or [],
        "user_note": "",
        "link_hint": "",
        "photo_file_ids": last.get("photo_file_ids") or [],
    }
    await _begin_ai_chain_from_payload(update, context)


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    if not message.reply_to_message:
        await message.reply_text("请先回复一条包含商品信息的消息，再发送 /save。")
        return
    chain = _chain_from_message(message)
    await _begin_ai_chain_flow(update, context, chain, user_note=_args_text(context))


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "back:cancel":
        _clear_flow_state(context)
        await query.edit_message_text("已取消添加。")
        return

    if data == "back:category":
        raw = context.user_data.get("pending_item")
        if not raw:
            await query.edit_message_text("已取消添加。")
            return
        context.user_data["awaiting_category"] = False
        await _begin_category_flow(update, context, _as_product_analysis(raw), edit=True)
        return

    if data.startswith("cat:"):
        category_ref = data.split(":", 1)[1]
        if category_ref == "__new__":
            context.user_data["awaiting_category"] = True
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("« 返回", callback_data="back:category")]]
            )
            await query.edit_message_text("请直接发送新的分类名称。", reply_markup=keyboard)
            return
        categories = context.user_data.get("categories") or []
        try:
            category = categories[int(category_ref)]
        except (ValueError, IndexError):
            await query.edit_message_text("分类列表已过期，请重新添加商品。")
            return
        await _save_pending_item(update, context, category)


async def _reply_or_edit(
    update: Update,
    text: str,
    *,
    edit: bool = False,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)


def _category_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    categories = context.user_data.get("categories") or DEFAULT_CATEGORIES
    suggested = context.user_data.get("suggested_category") or ""
    keyboard = []
    for idx, name in enumerate(categories[:20]):
        label = f"⭐ {name}" if suggested and name == suggested else name[:60]
        keyboard.append([InlineKeyboardButton(label, callback_data=f"cat:{idx}")])
    keyboard.append([InlineKeyboardButton("新建分类", callback_data="cat:__new__")])
    keyboard.append([InlineKeyboardButton("取消", callback_data="back:cancel")])
    return InlineKeyboardMarkup(keyboard)


async def _begin_category_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    result: ProductAnalysis | SearchResult,
    *,
    edit: bool = False,
    status_message: Message | None = None,
) -> None:
    analysis = _as_product_analysis(result)
    context.user_data["pending_item"] = asdict(analysis)
    context.user_data["suggested_category"] = analysis.suggested_category
    context.user_data.pop("awaiting_category", None)
    try:
        categories = await _notion(context).list_categories()
    except httpx.HTTPStatusError as exc:
        logger.exception("Failed to load Notion categories")
        if exc.response.status_code == 401:
            await _reply_or_edit(
                update,
                "Notion 未授权 (401)：token 无效或 bot 未重启。\n"
                "请更新 .env 里的 NOTION_TOKEN，然后在控制面板中重启机器人。",
                edit=edit,
            )
            return
        categories = []
    except Exception:
        logger.exception("Failed to load Notion categories")
        categories = []
    if not categories:
        categories = list(DEFAULT_CATEGORIES)
    context.user_data["categories"] = categories

    header = "确认保存到清单？"
    if analysis.suggested_category and analysis.suggested_category in categories:
        header = f"确认保存到清单？\n⭐ 推荐分类：{analysis.suggested_category}"
    text = (
        f"{header}\n\n{_format_product_preview(analysis)}\n\n"
        "选分类。链接相同或名称很像时会更新已有条目："
    )
    markup = _category_keyboard(context)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif status_message:
        await status_message.edit_text(text, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def _save_with_new_category(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category: str,
) -> None:
    if not category:
        await update.effective_message.reply_text("分类名称不能为空，请重新输入。")
        return
    context.user_data["awaiting_category"] = False
    await _save_pending_item(update, context, category)


async def _save_pending_item(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    category: str,
) -> None:
    raw = context.user_data.get("pending_item")
    if not raw:
        target = update.callback_query.message if update.callback_query else update.effective_message
        await target.reply_text("没有待保存的商品。请重新转发，或回复消息后发送 /save。")
        return

    analysis = _as_product_analysis(raw)
    item = ShoppingItem(
        title=format_ai_text(analysis.title),
        url=analysis.url,
        category=category,
        notes=format_ai_text(analysis.notes),
    )
    photo_file_ids = context.user_data.pop("pending_photo_file_ids", []) or []
    images: list[tuple[str, bytes, str]] = []
    for idx, file_id in enumerate(photo_file_ids[:3], 1):
        try:
            raw = await download_photo_bytes(context.bot, file_id)
            images.append((f"photo_{idx}.jpg", raw, "image/jpeg"))
        except Exception:
            logger.warning("Could not download Telegram photo %s for Notion", file_id, exc_info=True)
    try:
        result = await _notion(context).add_item(item, images=images or None)
    except httpx.HTTPStatusError as exc:
        logger.exception("Notion HTTP error")
        if exc.response.status_code == 401:
            text = (
                "Notion 保存失败：API token 无效 (401)。\n\n"
                "请按以下步骤修复：\n"
                "1. 打开 https://www.notion.so/my-integrations\n"
                "2. 进入你的 Integration → Secrets → 复制 Internal Integration Secret\n"
                "3. 打开购物清单数据库 → 右上角 ⋯ → Connections → 添加该 Integration\n"
                "4. 更新 .env 里的 NOTION_TOKEN（新 token 以 ntn_ 开头）\n"
                "5. 在控制面板中重启机器人\n\n"
                "注意：如果点了 Regenerate，必须用新 token，旧 token 会立刻失效。"
            )
        else:
            text = f"Notion 保存失败：{exc.response.status_code} {exc.response.text[:500]}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Notion save failed")
        text = f"Notion 保存失败：{exc}"
    else:
        _clear_flow_state(context)
        action = "✅ 已更新清单" if result.updated else "✅ 已保存到清单"
        text = f"{action}：[{category}] {item.title}"
        if result.attached_images:
            text += f"\n🖼 已附加 {result.attached_images} 张图片"
        elif images:
            text += "\n⚠️ 商品已保存，但图片上传失败"
        if result.page_url:
            text += f"\n{result.page_url}"

    if update.callback_query:
        await update.callback_query.edit_message_text(text)
    else:
        await update.effective_message.reply_text(text)


async def on_shutdown(app: Application) -> None:
    clients = [app.bot_data["openrouter"]]
    vision = app.bot_data.get("vision_client")
    if vision is not None and vision is not app.bot_data["openrouter"]:
        clients.append(vision)
    await asyncio.gather(*(client.close() for client in clients), app.bot_data["search"].close(), app.bot_data["notion"].close())


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error", exc_info=context.error)


def build_application() -> Application:
    env_path = _env_file()
    settings = load_settings(env_files=(str(env_path),) if env_path.is_file() else (".env",))
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        # Telegram file downloads can be slow/flaky; allow longer reads.
        .request(
            HTTPXRequest(
                connect_timeout=20.0,
                read_timeout=90.0,
                write_timeout=30.0,
                pool_timeout=30.0,
            )
        )
        .post_init(_setup_bot_commands)
        .post_shutdown(on_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    try:
        app.bot_data["settings_mtime"] = env_path.stat().st_mtime if env_path.is_file() else 0.0
    except OSError:
        app.bot_data["settings_mtime"] = 0.0
    openrouter = OpenRouterClient(
        settings.ai_api_key,
        base_url=settings.ai_api_base_url,
    )
    app.bot_data["openrouter"] = openrouter
    app.bot_data["vision_client"] = _build_vision_client(settings, openrouter)
    app.bot_data["product_extract"] = ProductExtractService(openrouter)
    app.bot_data["search"] = SearchService(
        settings.search_result_count,
        provider=settings.search_provider,
        google_api_key=settings.google_cse_api_key,
        google_cx=settings.google_cse_id,
    )
    app.bot_data["notion"] = NotionClient(settings.notion)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("save", save_command))
    app.add_handler(CommandHandler("model", model_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION | filters.PHOTO) & ~filters.COMMAND, reply_text_handler))
    app.add_error_handler(on_error)
    return app


def _configure_logging() -> None:
    project_root = Path(__file__).resolve().parents[2]
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)

    class _FlushFileHandler(logging.FileHandler):
        def emit(self, record: logging.LogRecord) -> None:
            super().emit(record)
            self.flush()

    handlers: list[logging.Handler] = [
        _FlushFileHandler(log_dir / "bot.log", encoding="utf-8"),
    ]
    if sys.stdout is not None and sys.stdout.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _write_pid_file() -> None:
    project_root = Path(__file__).resolve().parents[2]
    pid_path = project_root / "logs" / "bot.pid"
    pid_path.parent.mkdir(exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")


def main() -> None:
    _configure_logging()
    _write_pid_file()
    app = build_application()
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
