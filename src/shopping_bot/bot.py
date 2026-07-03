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
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from shopping_bot.categories import DEFAULT_CATEGORIES
from shopping_bot.config import Settings, load_settings, provider_supports_vision
from shopping_bot.models import ProductAnalysis, SearchResult, ShoppingItem
from shopping_bot.services.notion import NotionClient
from shopping_bot.services.openrouter import OpenRouterClient
from shopping_bot.services.product_extract import ProductExtractService
from shopping_bot.services.search import (
    SearchService,
    extract_all_urls_from_text,
    extract_url_from_text,
    is_url,
    strip_urls_from_text,
)
from shopping_bot.services.vision import analyze_chain_images, collect_photo_file_ids, photo_to_data_url

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand("start", "开始使用"),
    BotCommand("save", "AI 提取回复链并保存"),
    BotCommand("search", "AI 通用搜索"),
    BotCommand("clear", "清除 AI 对话上下文"),
    BotCommand("add", "添加商品链接"),
    BotCommand("model", "切换 AI 模型"),
    BotCommand("ask", "向 AI 提问"),
    BotCommand("cancel", "取消当前操作"),
    BotCommand("help", "查看帮助"),
]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.application.bot_data["settings"]


def _openrouter(context: ContextTypes.DEFAULT_TYPE) -> OpenRouterClient:
    return context.application.bot_data["openrouter"]


def _vision_client(context: ContextTypes.DEFAULT_TYPE) -> OpenRouterClient | None:
    return context.application.bot_data.get("vision_client")


def _vision_ready(context: ContextTypes.DEFAULT_TYPE) -> bool:
    client = _vision_client(context)
    settings = _settings(context)
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
    return context.application.bot_data["search"]


def _notion(context: ContextTypes.DEFAULT_TYPE) -> NotionClient:
    return context.application.bot_data["notion"]


def _product_extract(context: ContextTypes.DEFAULT_TYPE) -> ProductExtractService:
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
        await update.effective_message.reply_text("Sorry, this bot is private.")
    return False


def _args_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args).strip()


def _clear_flow_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "pending_item",
        "categories",
        "flow_source",
        "awaiting_category",
        "forward_payload",
        "suggested_category",
    ):
        context.user_data.pop(key, None)


def _get_chat_history(context: ContextTypes.DEFAULT_TYPE) -> list[dict[str, str]]:
    raw = context.user_data.get("chat_history")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("role") and item.get("content")]


def _append_chat_history(context: ContextTypes.DEFAULT_TYPE, role: str, content: str) -> None:
    history = _get_chat_history(context)
    history.append({"role": role, "content": content[:4000]})
    context.user_data["chat_history"] = history[-20:]


def _clear_chat_history(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("chat_history", None)


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
    try:
        parsed = await _search(context).parse_link(urls[0])
        return f"链接页面标题: {parsed.title}\n页面摘要: {parsed.snippet[:400]}"
    except Exception:
        logger.warning("Could not prefetch link for AI analysis", exc_info=True)
        return ""


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
    client = _vision_client(context)
    if not client:
        return ""
    model = _vision_model(context)
    if not model.strip():
        return ""
    return await analyze_chain_images(
        bot=context.bot,
        client=client,
        chain=chain,
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
        "购物助手已就绪。\n\n"
        "• 直接转发（文字、链接或照片）→ 选择「搜索 / 添加商品 / 取消」\n"
        "• 回复消息 / /save → AI 阅读回复链后直接选分类\n"
        "• 直接粘贴「文字 + 链接」→ 快速保存\n"
        "• /search 问题 → AI 通用搜索（与购物无关）\n"
        "• /clear → 清除 AI 对话上下文\n"
        "• /cancel → 取消当前操作"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    await update.effective_message.reply_text(
        "常用功能：\n"
        "1. 直接转发给 bot（文字、链接或照片）→ 选择「搜索 / 添加商品 / 取消」\n"
        "2. 回复某条消息或 /save → AI 阅读回复链，直接选分类\n"
        "3. 直接粘贴「描述 + 链接」\n"
        "4. /search 问题 → AI 通用搜索（不写入 Notion，不涉及购物）\n"
        "5. /clear → 清除 /search、/ask 的对话上下文\n"
        "6. /model → 切换 AI 模型\n"
        "7. /ask 问题 → 提问\n"
        "8. /cancel → 取消当前购物流程"
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    had_chat = bool(_get_chat_history(context))
    had_flow = any(
        context.user_data.get(key)
        for key in ("pending_item", "awaiting_category", "forward_payload")
    )
    _clear_chat_history(context)
    _clear_flow_state(context)
    if not had_chat and not had_flow:
        await update.effective_message.reply_text("当前没有需要清除的上下文。")
        return
    parts: list[str] = []
    if had_chat:
        parts.append("AI 对话上下文")
    if had_flow:
        parts.append("未完成的购物流程")
    await update.effective_message.reply_text(f"已清除：{'、'.join(parts)}。")


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    if not any(
        context.user_data.get(key)
        for key in ("pending_item", "awaiting_category")
    ):
        await update.effective_message.reply_text("当前没有进行中的操作。")
        return
    _clear_flow_state(context)
    await update.effective_message.reply_text("已取消当前操作。")


async def model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    settings = _settings(context)
    requested = _args_text(context)
    aliases = settings.model_aliases()

    if not requested:
        models = "\n".join(f"- {model}" for model in settings.models)
        await update.effective_message.reply_text(
            f"Current model: {_current_model(context)}\n\nAvailable:\n{models}"
        )
        return

    model = aliases.get(requested, requested)
    if model not in settings.models:
        await update.effective_message.reply_text(
            "Unknown model. Use /model to see configured models."
        )
        return

    context.user_data["model"] = model
    await update.effective_message.reply_text(f"Model switched to: {model}")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    prompt = _args_text(context)
    if message.reply_to_message and message.reply_to_message.text:
        quoted = message.reply_to_message.text
        prompt = f"Answer this quoted Telegram message:\n\n{quoted}\n\nUser instruction: {prompt or 'Answer it.'}"
    if not prompt:
        await message.reply_text("Send /ask <question>, or reply to a message with /ask.")
        return
    await _answer_prompt(update, context, prompt)


async def reply_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    if context.user_data.get("awaiting_category"):
        category = (message.text or message.caption or "").strip()
        await _save_with_new_category(update, context, category)
        return

    if _is_forwarded(message) or message.photo:
        chain = _chain_from_message(message)
        if not _should_ai_extract_chain(chain):
            await message.reply_text("转发的消息里没有可识别的文字、链接或图片。")
            return
        user_note = _message_body(message) if message.reply_to_message else ""
        await _begin_forward_menu(update, context, chain, user_note=user_note)
        return

    if message.reply_to_message:
        if await _try_ai_chain_from_message(
            update,
            context,
            message,
            user_note=_message_body(message),
        ):
            return

    url = _extract_url_from_message(message)
    if url:
        title = _extract_title_from_message(message, url)
        await _begin_link_flow(update, context, url, source="paste", title_override=title)
        return

    if message.chat.type == ChatType.PRIVATE:
        return

    if not message.reply_to_message or not message.reply_to_message.text:
        return

    bot_username = (await context.bot.get_me()).username
    if not bot_username or f"@{bot_username.lower()}" not in (message.text or "").lower():
        return

    quoted = message.reply_to_message.text
    prompt = f"Answer this quoted Telegram message:\n\n{quoted}\n\nUser instruction: {message.text}"
    await _answer_prompt(update, context, prompt)


async def _answer_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE, prompt: str) -> None:
    message = update.effective_message
    status = await message.reply_text(f"Thinking with {_current_model(context)}...")
    try:
        answer = await _openrouter(context).answer(
            model=_current_model(context),
            prompt=prompt,
            history=_get_chat_history(context),
        )
        _append_chat_history(context, "user", prompt)
        _append_chat_history(context, "assistant", answer)
        await status.edit_text(answer[:4096])
    except httpx.HTTPStatusError as exc:
        logger.exception("OpenRouter HTTP error")
        await status.edit_text(f"Model request failed: {exc.response.status_code} {exc.response.text[:500]}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenRouter request failed")
        await status.edit_text(f"Model request failed: {exc}")


async def _begin_link_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    *,
    source: str,
    title_override: str | None = None,
) -> None:
    status = await update.effective_message.reply_text(
        "正在识别商品信息…" if title_override else "正在读取商品信息…"
    )
    snippet = ""
    final_url = url
    try:
        parsed = await _search(context).parse_link(url)
        final_url = parsed.url or url
        snippet = parsed.snippet
        if not title_override:
            title_override = parsed.title
    except httpx.HTTPStatusError as exc:
        if not title_override:
            await status.edit_text(f"无法读取链接: {exc.response.status_code} {exc.response.text[:500]}")
            return
        snippet = "未能读取页面详情，已使用你提供的文字作为商品名。"
    except Exception as exc:  # noqa: BLE001
        if not title_override:
            logger.exception("Link parse failed")
            await status.edit_text(f"无法读取链接: {exc}")
            return
        logger.warning("Link parse failed, using provided title", exc_info=True)
        snippet = "未能读取页面详情，已使用你提供的文字作为商品名。"

    result = SearchResult(
        title=title_override or final_url,
        url=final_url,
        snippet=snippet,
    )
    context.user_data["flow_source"] = source
    analysis = ProductAnalysis(title=result.title, url=result.url, notes=result.snippet)
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
    status = await update.effective_message.reply_text("AI 正在阅读回复链并分析…")
    thread_text = _format_chain_for_ai(chain)
    urls = _collect_urls_from_chain(chain)
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
            image_hint=image_hint,
            categories=categories,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI reply-chain extract failed")
        await status.edit_text(f"无法分析回复链: {exc}")
        return

    if not _analysis_is_saveable(analysis):
        await status.edit_text("无法识别商品信息，请确保消息包含链接、图片或文字描述。")
        return

    context.user_data["flow_source"] = "reply_chain"
    await _begin_category_flow(update, context, analysis, status_message=status)


def _forward_action_keyboard(*, after_search: bool = False) -> InlineKeyboardMarkup:
    if after_search:
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➕ 添加商品", callback_data="forward:add")],
                [InlineKeyboardButton("取消", callback_data="forward:cancel")],
            ]
        )
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔍 搜索", callback_data="forward:search"),
                InlineKeyboardButton("➕ 添加商品", callback_data="forward:add"),
            ],
            [InlineKeyboardButton("取消", callback_data="forward:cancel")],
        ]
    )


async def _begin_forward_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chain: list[Message],
    *,
    user_note: str = "",
) -> None:
    if user_note.startswith("/"):
        user_note = ""
    thread_text = _format_chain_for_ai(chain)
    urls = _collect_urls_from_chain(chain)
    photo_ids = collect_photo_file_ids(chain)
    link_hint = await _build_link_hint(context, urls)

    status = None
    if photo_ids:
        status = await update.effective_message.reply_text("正在识别图片…")
    image_hint = await _build_image_hint(context, chain) if photo_ids else ""

    context.user_data["forward_payload"] = {
        "thread_text": thread_text,
        "urls": urls,
        "user_note": user_note,
        "link_hint": link_hint,
        "image_hint": image_hint,
        "photo_file_ids": photo_ids,
    }

    preview_lines: list[str] = []
    if thread_text.strip():
        preview_lines.append(thread_text.strip()[:350])
    if image_hint:
        preview_lines.append(f"图片识别: {image_hint[:350]}")
    elif photo_ids and not _vision_ready(context):
        preview_lines.append(f"⚠ {_vision_unavailable_message(context)}")
    elif link_hint:
        preview_lines.append(link_hint.split("\n", 1)[0])
    if urls:
        preview_lines.append(f"链接: {urls[0]}")
    preview = "\n".join(preview_lines) or "（无文字）"

    text = f"收到转发消息：\n\n{preview}\n\n请选择操作："
    markup = _forward_action_keyboard()
    if status:
        await status.edit_text(text, reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def _begin_ai_chain_from_payload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    payload = context.user_data.get("forward_payload")
    if not payload:
        await query.edit_message_text("已过期，请重新转发。")
        return

    await query.edit_message_text("AI 正在阅读回复链并分析…")
    thread_text = payload["thread_text"]
    urls = payload.get("urls") or []
    user_note = payload.get("user_note") or ""
    link_hint = payload.get("link_hint") or ""
    image_hint = payload.get("image_hint") or ""

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
        logger.exception("AI reply-chain extract failed")
        await query.edit_message_text(f"无法分析回复链: {exc}")
        return

    if not _analysis_is_saveable(analysis):
        await query.edit_message_text("无法识别商品信息，请确保消息包含链接、图片或文字描述。")
        return

    context.user_data.pop("forward_payload", None)
    context.user_data["flow_source"] = "forward"
    await _begin_category_flow(update, context, analysis, edit=True)


def _format_product_preview(analysis: ProductAnalysis) -> str:
    lines: list[str] = []
    if analysis.what:
        lines.append(f"AI 判断：{analysis.what}")
    lines.append(f"商品: {analysis.title}")
    if analysis.url:
        lines.append(f"链接: {analysis.url}")
    if analysis.notes:
        lines.append(analysis.notes)
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
    if not raw:
        await update.effective_message.reply_text("用法: /add 商品名 链接\n或 /add 链接")
        return
    url = extract_url_from_text(raw)
    if not url:
        await update.effective_message.reply_text("请提供有效的 http(s) 链接。")
        return
    title = _extract_title_from_plain_text(raw, url)
    await _begin_link_flow(update, context, url, source="add", title_override=title)


async def save_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    if not message.reply_to_message:
        await message.reply_text("请「回复」一条包含商品信息的消息，然后发送 /save。")
        return
    chain = _chain_from_message(message)
    await _begin_ai_chain_flow(update, context, chain, user_note=_args_text(context))


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    message = update.effective_message
    await _acknowledge_message(message, context)
    query = _args_text(context)
    if not query:
        await message.reply_text("用法: /search 你的问题\n（通用 AI 搜索，与购物功能无关）")
        return

    if extract_url_from_text(query):
        await message.reply_text(
            "保存链接请转发给 bot 或使用 /add。\n/search 仅用于 AI 搜索。"
        )
        return

    status = await message.reply_text(f"搜索中：{query}…")
    try:
        history = _get_chat_history(context)
        answer = await _openrouter(context).search_query(
            model=_current_model(context),
            query=query,
            history=history,
        )
        _append_chat_history(context, "user", query)
        _append_chat_history(context, "assistant", answer)
        await status.edit_text(answer[:4096])
    except httpx.HTTPStatusError as exc:
        logger.exception("OpenRouter search failed")
        await status.edit_text(f"搜索失败: {exc.response.status_code} {exc.response.text[:500]}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Search failed")
        await status.edit_text(f"搜索失败: {exc}")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == "back:cancel":
        _clear_flow_state(context)
        await query.edit_message_text("已取消。")
        return

    if data == "forward:cancel":
        context.user_data.pop("forward_payload", None)
        await query.edit_message_text("已取消。")
        return

    if data == "forward:search":
        payload = context.user_data.get("forward_payload")
        if not payload:
            await query.edit_message_text("已过期，请重新转发。")
            return

        search_text = payload["thread_text"].strip()
        meaningful_text = _extract_meaningful_thread_text(search_text)
        urls = payload.get("urls") or []
        image_hint = payload.get("image_hint") or ""
        photo_ids = payload.get("photo_file_ids") or []
        vision_client = _vision_client(context)

        if not photo_ids and not meaningful_text and not urls and not image_hint:
            await query.edit_message_text("转发内容里没有可搜索的文字或图片。")
            return

        await query.edit_message_text("搜索中…")
        try:
            history = _get_chat_history(context)
            if photo_ids:
                if not vision_client:
                    await query.edit_message_text(
                        f"搜索失败：{_vision_unavailable_message(context)}",
                        reply_markup=_forward_action_keyboard(),
                    )
                    return
                data_url = await photo_to_data_url(context.bot, photo_ids[0])
                prompt = "请根据图片介绍其中的商品或物品，包括名称、用途、特点等。用中文直接回答。"
                if image_hint:
                    prompt = f"{prompt}\n\n已有初步识别：\n{image_hint}"
                if meaningful_text:
                    prompt = f"{prompt}\n\n用户文字说明：\n{meaningful_text}"
                if urls:
                    prompt = f"{prompt}\n\n相关链接：{urls[0]}"
                answer = await vision_client.search_with_image(
                    model=_vision_model(context),
                    query=prompt,
                    image_url=data_url,
                    history=history,
                )
                search_label = meaningful_text[:500] or image_hint[:500] or "(图片)"
            else:
                if not search_text and image_hint:
                    search_text = f"请介绍以下图片中的商品或物品：\n{image_hint}"
                if not search_text and urls:
                    search_text = f"请介绍这个链接的内容: {urls[0]}"
                answer = await _openrouter(context).search_query(
                    model=_current_model(context),
                    query=(meaningful_text or search_text)[:2000],
                    history=history,
                )
                search_label = (meaningful_text or search_text)[:500]
            _append_chat_history(context, "user", search_label)
            _append_chat_history(context, "assistant", answer)
            await query.edit_message_text(
                f"🔍 搜索结果\n\n{answer[:3800]}",
                reply_markup=_forward_action_keyboard(after_search=True),
            )
        except httpx.HTTPStatusError as exc:
            logger.exception("OpenRouter search failed")
            await query.edit_message_text(
                f"搜索失败: {exc.response.status_code} {exc.response.text[:500]}",
                reply_markup=_forward_action_keyboard(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Search failed")
            await query.edit_message_text(
                f"搜索失败: {exc}",
                reply_markup=_forward_action_keyboard(),
            )
        return

    if data == "forward:add":
        await _begin_ai_chain_from_payload(update, context)
        return

    if data == "back:category":
        raw = context.user_data.get("pending_item")
        if not raw:
            await query.edit_message_text("已取消。")
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
            await query.edit_message_text("请输入新的分类名称。", reply_markup=keyboard)
            return
        categories = context.user_data.get("categories") or []
        try:
            category = categories[int(category_ref)]
        except (ValueError, IndexError):
            await query.edit_message_text("分类已过期，请重新开始。")
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

    header = "确认保存？"
    if analysis.suggested_category and analysis.suggested_category in categories:
        header = f"确认保存？\n推荐分类：{analysis.suggested_category}"
    text = f"{header}\n\n{_format_product_preview(analysis)}\n\n请选择分类："
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
        await update.effective_message.reply_text("分类不能为空。")
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
        await target.reply_text("没有待保存的商品，请重新转发链接或使用 /save。")
        return

    analysis = _as_product_analysis(raw)
    item = ShoppingItem(
        title=analysis.title,
        url=analysis.url,
        category=category,
        notes=analysis.notes,
    )
    try:
        page_url = await _notion(context).add_item(item)
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
            text = f"Notion save failed: {exc.response.status_code} {exc.response.text[:500]}"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Notion save failed")
        text = f"Notion save failed: {exc}"
    else:
        _clear_flow_state(context)
        text = f"已保存到 Notion：[{category}] {item.title}"
        if page_url:
            text += f"\n{page_url}"

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
    settings = load_settings()
    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(_setup_bot_commands)
        .post_shutdown(on_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    openrouter = OpenRouterClient(
        settings.ai_api_key,
        base_url=settings.ai_api_base_url,
    )
    app.bot_data["openrouter"] = openrouter
    if settings.ai_vision_api_key and settings.ai_vision_api_base_url:
        app.bot_data["vision_client"] = OpenRouterClient(
            settings.ai_vision_api_key,
            base_url=settings.ai_vision_api_base_url,
        )
    elif provider_supports_vision(settings.ai_api_base_url) and settings.vision_model.strip():
        app.bot_data["vision_client"] = openrouter
    else:
        app.bot_data["vision_client"] = None
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
    app.add_handler(CommandHandler("search", search_command))
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
