from __future__ import annotations

import httpx

SEARCH_SYSTEM_PROMPT = (
    "你是通用信息搜索助手。用中文直接、准确地回答用户问题。"
    "不要提及购物清单、Notion、保存商品或本 bot 的其他功能。"
    "不要编造实时网页数据；不确定就说明。"
)

ASK_SYSTEM_PROMPT = "You are a concise helpful assistant inside a private Telegram bot."


def normalize_openrouter_model(model: str) -> str:
    """Accept both raw OpenRouter ids and OpenClaw-style openrouter/<id> refs."""
    if not model.startswith("openrouter/"):
        return model
    candidate = model.removeprefix("openrouter/")
    if "/" not in candidate:
        return model
    return candidate


class OpenRouterClient:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url="https://openrouter.ai/api/v1",
            timeout=httpx.Timeout(60.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://localhost/telegram-shopping-bot",
                "X-Title": "Telegram Shopping Bot",
            },
        )

    async def _chat(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int = 1200,
        temperature: float = 0.3,
    ) -> str:
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": normalize_openrouter_model(model),
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not content:
            raise RuntimeError("OpenRouter returned an empty answer")
        return str(content).strip()

    async def answer(
        self,
        *,
        model: str,
        prompt: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = [{"role": "system", "content": ASK_SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        return await self._chat(model=model, messages=messages)

    async def extract_json(self, *, model: str, prompt: str) -> str:
        return await self._chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是购物清单数据提取助手。根据 Telegram 消息和商品页面信息，"
                        "准确判断商品类型并提取结构化字段。只返回合法 JSON，不要 markdown，不要解释。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0.1,
        )

    async def search_query(
        self,
        *,
        model: str,
        query: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages = [{"role": "system", "content": SEARCH_SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": query})
        return await self._chat(model=model, messages=messages, temperature=0.4)

    async def describe_image(
        self,
        *,
        model: str,
        image_url: str,
        prompt: str,
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        return await self._chat(model=model, messages=messages, max_tokens=600, temperature=0.2)

    async def search_with_image(
        self,
        *,
        model: str,
        query: str,
        image_url: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict] = [{"role": "system", "content": SEARCH_SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": query},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        )
        return await self._chat(model=model, messages=messages, temperature=0.4)

    async def close(self) -> None:
        await self._client.aclose()
