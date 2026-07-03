from __future__ import annotations

import json
import logging
import re

from shopping_bot.categories import DEFAULT_CATEGORIES
from shopping_bot.models import ProductAnalysis
from shopping_bot.services.openrouter import OpenRouterClient
from shopping_bot.services.search import extract_url_from_text, strip_urls_from_text

logger = logging.getLogger(__name__)

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "食品": ("食品", "零食", "吃", "饮料", "咖啡", "茶", "酒", "水果", "肉", "粮", "奶", "糖", "餐"),
    "日用品": ("日用", "洗护", "清洁", "纸巾", "毛巾", "化妆", "护肤", "超市", "洗发", "沐浴", "牙膏"),
    "电子产品": ("电子", "手机", "电脑", "耳机", "键盘", "数码", "充电", "平板", "相机", "显卡", "显示器"),
    "衣服": ("衣服", "鞋", "包", "裤", "裙", "衣", "帽", "袜", "穿戴", "外套", "卫衣", "T恤"),
}


def _parse_json_object(raw: str) -> dict[str, str]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = JSON_OBJECT_RE.search(text)
    if not match:
        raise ValueError("No JSON object in model response")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Model JSON is not an object")
    return {str(key): str(value).strip() for key, value in data.items() if value is not None}


def _pick_category_from_text(*parts: str, categories: list[str] | None = None) -> str:
    options = categories or list(DEFAULT_CATEGORIES)
    merged = " ".join(part for part in parts if part).lower()
    if not merged.strip():
        return "其他" if "其他" in options else options[-1]

    scores: dict[str, int] = {name: 0 for name in options}
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category not in scores:
            continue
        for keyword in keywords:
            if keyword in merged:
                scores[category] += 1

    best = max(scores.items(), key=lambda item: item[1])
    if best[1] > 0:
        return best[0]
    return "其他" if "其他" in options else options[-1]


def _normalize_category(value: str, categories: list[str]) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    for name in categories:
        if cleaned == name or cleaned in name or name in cleaned:
            return name
    return ""


def _infer_what_from_link_hint(link_hint: str) -> str:
    if not link_hint:
        return ""
    title_line = link_hint.split("\n", 1)[0].replace("链接页面标题: ", "").strip()
    if title_line:
        return f"商品页面 - {title_line[:120]}"
    return ""


def _infer_what_from_image_hint(image_hint: str) -> str:
    if not image_hint:
        return ""
    first_line = image_hint.split("\n", 1)[0].strip()
    if first_line.startswith("图片"):
        _, _, rest = first_line.partition("：")
        if rest.strip():
            return f"图片商品 - {rest.strip()[:120]}"
    return f"图片商品 - {first_line[:120]}" if first_line else ""


def _fallback_from_chain(
    thread_text: str,
    urls: list[str],
    user_note: str,
    *,
    link_hint: str = "",
    image_hint: str = "",
    categories: list[str] | None = None,
) -> ProductAnalysis:
    options = categories or list(DEFAULT_CATEGORIES)
    merged = "\n".join(
        part for part in (thread_text, user_note, link_hint, image_hint) if part
    ).strip()
    title = strip_urls_from_text(merged)
    title = re.sub(r"^[\s\-–—|:：]+|[\s\-–—|:：]+$", "", title)
    if not title and link_hint:
        title = link_hint.split("\n", 1)[0].replace("链接页面标题: ", "").strip()
    if not title and image_hint:
        first = image_hint.split("\n", 1)[0].strip()
        if "：" in first:
            title = first.split("：", 1)[1].strip()
        else:
            title = first
    if not title:
        title = urls[0] if urls else "未命名商品"

    what = (
        _infer_what_from_link_hint(link_hint)
        or _infer_what_from_image_hint(image_hint)
        or ("商品链接" if urls else "图片消息" if image_hint else "文本消息")
    )
    suggested = _pick_category_from_text(what, title, merged, categories=options)
    notes = user_note[:500] if user_note else ""
    if link_hint and "页面摘要:" in link_hint:
        snippet = link_hint.split("页面摘要:", 1)[1].strip()
        if snippet and snippet not in notes:
            notes = f"{notes}\n{snippet}".strip() if notes else snippet[:500]

    return ProductAnalysis(
        title=title[:200],
        url=urls[0] if urls else "",
        notes=notes[:2000],
        what=what[:200],
        suggested_category=suggested,
    )


class ProductExtractService:
    def __init__(self, client: OpenRouterClient) -> None:
        self._client = client

    async def extract_from_reply_chain(
        self,
        *,
        model: str,
        thread_text: str,
        urls: list[str],
        user_note: str = "",
        link_hint: str = "",
        image_hint: str = "",
        categories: list[str] | None = None,
    ) -> ProductAnalysis:
        if (
            not thread_text.strip()
            and not urls
            and not user_note.strip()
            and not link_hint.strip()
            and not image_hint.strip()
        ):
            raise ValueError("Reply chain is empty")

        options = categories or list(DEFAULT_CATEGORIES)
        category_list = "、".join(options)
        effective_thread = (
            thread_text.strip()
            or image_hint.strip()
            or link_hint.strip()
            or "(无文字，请根据图片或链接线索判断)"
        )

        prompt = (
            "你是购物清单助手。请阅读 Telegram 消息、回复链、图片识别结果和商品链接页面信息，"
            "准确判断这是什么商品/物品。\n\n"
            "要求：\n"
            "1. what：用一句话说明类型和品类（例如：淘宝商品-无线蓝牙耳机、京东-厨房收纳盒、拼多多-运动鞋）\n"
            "2. title：简短清晰的中文商品名（不要包含链接；优先用页面标题、图片识别或消息里的商品名）\n"
            "3. notes：价格、规格、购买理由、备注等要点，用简洁中文\n"
            "4. url：从提供的链接里选最合适的一条商品链接；没有则留空字符串\n"
            f"5. category：从以下分类中选最合适的一个：{category_list}\n\n"
            f"回复链内容（从旧到新）：\n{effective_thread}\n\n"
            f"检测到的链接：\n{chr(10).join(urls) if urls else '(无)'}\n\n"
            f"链接页面线索（优先参考）：\n{link_hint or '(未读取)'}\n\n"
            f"图片识别结果（优先参考）：\n{image_hint or '(无)'}\n\n"
            f"用户最新补充：\n{user_note or '(无)'}\n\n"
            "只返回 JSON，不要 markdown，不要解释：\n"
            '{"what":"...", "title":"...", "notes":"...", "url":"...", "category":"..."}'
        )
        try:
            raw = await self._client.extract_json(model=model, prompt=prompt)
            data = _parse_json_object(raw)
            title = data.get("title", "").strip()
            notes = data.get("notes", "").strip()
            what = data.get("what", "").strip()
            url = data.get("url", "").strip() or (urls[0] if urls else "")
            if url and not extract_url_from_text(url):
                url = urls[0] if urls else ""
            if not title:
                raise ValueError("Empty title from model")
            if not what:
                what = (
                    _infer_what_from_link_hint(link_hint)
                    or _infer_what_from_image_hint(image_hint)
                    or "未能明确判断类型"
                )
            suggested = _normalize_category(data.get("category", ""), options)
            if not suggested:
                suggested = _pick_category_from_text(
                    what, title, notes, link_hint, image_hint, categories=options
                )
            return ProductAnalysis(
                title=title[:200],
                url=url,
                notes=notes[:2000],
                what=what[:200],
                suggested_category=suggested,
            )
        except Exception:
            logger.warning("AI product extract failed, using fallback", exc_info=True)
            return _fallback_from_chain(
                thread_text,
                urls,
                user_note,
                link_hint=link_hint,
                image_hint=image_hint,
                categories=options,
            )
