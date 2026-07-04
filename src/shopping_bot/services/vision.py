from __future__ import annotations

import base64
import logging

import httpx
from telegram import Bot, Message

from shopping_bot.services.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

DESCRIBE_PROMPT = (
    "用中文描述图片中的商品或物品。包括：名称、品牌、包装文字、价格标签、"
    "规格参数等可见信息。若有多件物品，分别列出。简洁准确，不要臆测看不见的内容。"
    "不要使用 markdown（不要 *、**、#、`）。"
)


def collect_photo_file_ids(chain: list[Message]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for msg in chain:
        if not msg.photo:
            continue
        file_id = msg.photo[-1].file_id
        if file_id in seen:
            continue
        ids.append(file_id)
        seen.add(file_id)
    return ids


async def photo_to_data_url(bot: Bot, file_id: str) -> str:
    tg_file = await bot.get_file(file_id)
    raw = await tg_file.download_as_bytearray()
    encoded = base64.b64encode(bytes(raw)).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


async def download_photo_bytes(bot: Bot, file_id: str) -> bytes:
    tg_file = await bot.get_file(file_id)
    return bytes(await tg_file.download_as_bytearray())


async def analyze_photo_file_ids(
    *,
    bot: Bot,
    client: OpenRouterClient,
    file_ids: list[str],
    model: str,
    limit: int = 2,
) -> str:
    if not file_ids:
        return ""

    parts: list[str] = []
    for idx, file_id in enumerate(file_ids[:limit], 1):
        try:
            data_url = await photo_to_data_url(bot, file_id)
            description = await client.describe_image(
                model=model,
                image_url=data_url,
                prompt=DESCRIBE_PROMPT,
            )
            if description:
                label = f"图片{idx}" if len(file_ids) > 1 else "图片"
                parts.append(f"{label}：{description}")
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:300]
            logger.warning(
                "Image analysis failed for file_id=%s: %s %s",
                file_id,
                exc.response.status_code,
                detail,
                exc_info=True,
            )
        except Exception:
            logger.warning("Image analysis failed for file_id=%s", file_id, exc_info=True)
    return "\n\n".join(parts)


async def analyze_chain_images(
    *,
    bot: Bot,
    client: OpenRouterClient,
    chain: list[Message],
    model: str,
    limit: int = 2,
) -> str:
    return await analyze_photo_file_ids(
        bot=bot,
        client=client,
        file_ids=collect_photo_file_ids(chain),
        model=model,
        limit=limit,
    )
