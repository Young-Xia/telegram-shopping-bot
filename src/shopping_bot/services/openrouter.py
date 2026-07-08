from __future__ import annotations

import json

import httpx

OUTPUT_STYLE_RULES = (
    "输出规则（必须遵守）：\n"
    "1. 只输出最终答案，禁止输出思考过程、分析草稿、自我提醒、对提示词的复述。\n"
    "2. 禁止出现这类句子：我们需要理解、在对话历史中、输出风格必须、首先回顾、所以我要、作为…医生。\n"
    "3. 特别简单直白，短句优先。先给结论，再补必要细节。\n"
    "4. 人人都懂的词不要翻译；只有生僻专业术语才用「中文（English）」。\n"
    "5. 可用 emoji 和 • 列表；禁止使用 markdown（不要 *、**、#、`、[]() 链接语法）。\n"
    "6. 不确定就直接说不确定，不要编造。"
)

SEARCH_SYSTEM_PROMPT = (
    "你是通用信息助手。用中文准确回答用户问题。\n"
    "不要提及购物清单、Notion、保存商品或本 bot 的其他功能。\n"
    f"{OUTPUT_STYLE_RULES}"
)

ASK_SYSTEM_PROMPT = (
    "你是私人 Telegram 机器人里的中文助手。\n"
    "根据用户问题和对话历史直接作答。\n"
    f"{OUTPUT_STYLE_RULES}"
)


def format_api_error_message(
    *,
    status_code: int | None = None,
    body: str = "",
    parsed: dict | None = None,
) -> str:
    """Turn provider JSON errors into short Chinese messages for Telegram."""
    message = ""
    if parsed:
        err = parsed.get("error")
        if isinstance(err, dict):
            message = str(err.get("message") or err)
        elif err:
            message = str(err)
    if not message and body:
        try:
            data = json.loads(body)
            if isinstance(data, dict):
                return format_api_error_message(status_code=status_code, parsed=data)
        except Exception:
            message = body[:300]
    lowered = message.casefold()
    provider_name: str | None = None
    if parsed and isinstance(parsed.get("error"), dict):
        meta = parsed["error"].get("metadata")
        if isinstance(meta, dict) and meta.get("provider_name") is not None:
            provider_name = str(meta.get("provider_name") or "") or None

    if status_code == 403 and (
        "terms of service" in lowered or "prohibited" in lowered or "tos" in lowered
    ):
        if provider_name is None:
            return (
                "OpenRouter 拒绝了请求（403）：账户的隐私/数据策略未允许任何模型提供商。"
                "请打开 openrouter.ai/settings/privacy ，"
                "允许 OpenAI、Google、Anthropic 等提供商（尤其是支持识图的）。"
                "改完后无需换模型，重启 bot 再试。"
            )
        return (
            "视觉/图片请求被模型提供商拒绝（403，内容安全或服务条款）。"
            "可换一张图、在设置里换视觉模型（如 openai/gpt-4o），或只基于文字提问。"
        )
    if status_code == 404 and (
        "no endpoints available" in lowered
        and ("guardrail" in lowered or "data policy" in lowered or "settings/privacy" in lowered)
    ):
        return (
            "OpenRouter 当前没有可用端点：你设置了过严的 guardrail/data policy。"
            "请打开 openrouter.ai/settings/privacy ，放宽隐私限制并允许至少一个提供商"
            "（OpenAI/Google/Anthropic 其一），保存后重试。"
        )
    if status_code == 429:
        return "请求太频繁（429），请稍后再试。"
    if status_code:
        short = message[:200].strip() if message else "未知错误"
        return f"API 错误 {status_code}：{short}"
    return (message or "AI API 请求失败")[:300]


def normalize_openrouter_model(model: str) -> str:
    """Accept both raw OpenRouter ids and OpenClaw-style openrouter/<id> refs."""
    if not model.startswith("openrouter/"):
        return model
    candidate = model.removeprefix("openrouter/")
    if "/" not in candidate:
        return model
    return candidate


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
    ) -> None:
        self._api_key = api_key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in base_url:
            headers["HTTP-Referer"] = "https://localhost/telegram-shopping-bot"
            headers["X-Title"] = "Telegram Shopping Bot"
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(60.0),
            headers=headers,
        )

    @staticmethod
    def _extract_message_text(message: dict) -> str:
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item.strip():
                    parts.append(item.strip())
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("content")
                    if text and str(text).strip():
                        parts.append(str(text).strip())
            joined = "\n".join(parts).strip()
            if joined:
                return joined
        for key in ("reasoning_content", "reasoning"):
            value = message.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    async def _chat_once(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, str]:
        """Returns (text, error_detail). text is empty on soft failure."""
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": normalize_openrouter_model(model),
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        if response.status_code >= 400:
            parsed: dict | None = None
            try:
                parsed = response.json()
            except Exception:
                parsed = None
            detail = format_api_error_message(
                status_code=response.status_code,
                body=response.text,
                parsed=parsed if isinstance(parsed, dict) else None,
            )
            return "", detail
        data = response.json()
        if data.get("error"):
            err = data["error"]
            if isinstance(err, dict):
                return "", str(err.get("message") or err)[:300]
            return "", str(err)[:300]
        choices = data.get("choices") or []
        if not choices:
            return "", "AI API returned no choices"
        choice = choices[0] or {}
        text = self._extract_message_text(choice.get("message") or {})
        if not text:
            finish = choice.get("finish_reason") or choice.get("finishReason") or "unknown"
            return "", f"AI API returned an empty answer (finish_reason={finish})"
        return text, ""

    async def _chat(
        self,
        *,
        model: str,
        messages: list[dict],
        max_tokens: int = 1200,
        temperature: float = 0.3,
        fallback_models: list[str] | None = None,
    ) -> str:
        models = [model, *(fallback_models or [])]
        seen: set[str] = set()
        errors: list[str] = []
        for candidate in models:
            cleaned = candidate.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            text, err = await self._chat_once(
                model=cleaned,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if text:
                return text
            errors.append(f"{cleaned}: {err or 'unknown error'}")
            # One quick retry on the same model for transient empty payloads.
            text, err = await self._chat_once(
                model=cleaned,
                messages=messages,
                max_tokens=max_tokens,
                temperature=max(temperature, 0.5),
            )
            if text:
                return text
            if err:
                errors.append(f"{cleaned} retry: {err}")
        raise RuntimeError("；".join(errors) or "AI API returned no choices")

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
        return await self._chat(model=model, messages=messages, max_tokens=2500)

    async def extract_json(self, *, model: str, prompt: str) -> str:
        return await self._chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是购物清单数据提取助手。根据消息和商品页面信息提取结构化字段。"
                        "只返回合法 JSON，不要 markdown，不要解释。"
                        "字段值要特别简单；人人都懂的词不翻译；"
                        "只有不常见专业术语才用「中文（English）」；不要使用 *、**、#、`。"
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
        fallback_models: list[str] | None = None,
    ) -> str:
        # Free vision endpoints are unreliable with long multimodal histories.
        # Prefer a single image turn; pass history only when explicitly needed.
        messages: list[dict] = [{"role": "system", "content": SEARCH_SYSTEM_PROMPT}]
        if history:
            messages.extend(history[-4:])
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": query},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        )
        return await self._chat(
            model=model,
            messages=messages,
            temperature=0.4,
            fallback_models=fallback_models,
        )

    async def close(self) -> None:
        await self._client.aclose()
