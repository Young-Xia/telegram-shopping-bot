"""Diagnose OpenRouter vision API issues.

Run:
  PYTHONPATH=src python scripts/diagnose_vision.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopping_bot.config import load_settings  # noqa: E402
from shopping_bot.services.openrouter import OpenRouterClient  # noqa: E402

# 16x16 PNG (solid red) to satisfy models that reject tiny images.
TINY = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAAF0lEQVR42mP8z8AARAwM"
    "DAwMhgEAEe0C/Up8WwAAAABJRU5ErkJggg=="
)


async def main() -> None:
    settings = load_settings([str(ROOT / ".env")])
    print(f"vision_model={settings.vision_model}")
    print(f"vision_base={settings.ai_vision_api_base_url}")

    client = OpenRouterClient(
        settings.ai_vision_api_key or "",
        base_url=settings.ai_vision_api_base_url or "https://openrouter.ai/api/v1",
    )
    try:
        # 1) Text-only on OpenRouter (use openrouter/free to avoid provider restrictions)
        try:
            text = await client.answer(model="openrouter/free", prompt="Reply exactly: VISION_DIAG_OK")
            print(f"text_only: OK ({text[:60]!r})")
        except Exception as exc:
            print(f"text_only: FAIL ({exc})")

        # 2) Vision tiny image - raw status
        model = settings.vision_model or "qwen/qwen3-vl-32b-instruct"
        response = await client._client.post(  # noqa: SLF001
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "What color? One word."},
                            {"type": "image_url", "image_url": {"url": TINY}},
                        ],
                    }
                ],
                "max_tokens": 20,
            },
        )
        print(f"vision_tiny status={response.status_code}")
        print(f"vision_tiny body={response.text[:500]}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
