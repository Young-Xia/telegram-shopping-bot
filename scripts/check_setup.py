from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopping_bot.config import load_settings  # noqa: E402
from shopping_bot.services.notion import NotionClient  # noqa: E402
from shopping_bot.services.openrouter import OpenRouterClient  # noqa: E402
from shopping_bot.services.search import SearchService  # noqa: E402


PLACEHOLDERS = {"replace_me", "123456:replace_me", "sk-or-v1-replace_me", "secret_replace_me"}


def _reject_placeholders(settings) -> None:
    pairs = {
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "AI_API_KEY": settings.ai_api_key,
        "NOTION_TOKEN": settings.notion.token,
        "NOTION_DATABASE_ID": settings.notion.database_id,
    }
    bad = [name for name, value in pairs.items() if not value or value in PLACEHOLDERS or "replace_me" in value]
    if bad:
        joined = ", ".join(bad)
        raise RuntimeError(f"These .env values still look like placeholders: {joined}")


import re

PLACEHOLDERS = {"replace_me", "123456:replace_me", "sk-or-v1-replace_me", "secret_replace_me"}
TELEGRAM_TOKEN_RE = re.compile(r"^\d{8,12}:[A-Za-z0-9_-]{30,}$")


def _validate_telegram_token(token: str) -> None:
    if ":" not in token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN must contain a colon (:).\n"
            "Example: TELEGRAM_BOT_TOKEN=7123456789:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        )
    bot_id, secret = token.split(":", 1)
    issues: list[str] = []
    if not bot_id.isdigit():
        issues.append("part before ':' must be numbers only (bot id)")
    elif not (8 <= len(bot_id) <= 12):
        issues.append(f"bot id length looks unusual ({len(bot_id)} digits)")
    if not secret:
        issues.append("part after ':' is empty")
    elif len(secret) < 20:
        issues.append(f"token secret looks too short ({len(secret)} chars)")
    elif not re.fullmatch(r"[A-Za-z0-9_-]+", secret):
        issues.append("token secret contains invalid characters (only letters, numbers, _ and - allowed)")
    if issues:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN format looks wrong.\n"
            + "\n".join(f"- {item}" for item in issues)
            + "\n- Get API Token from @BotFather -> /mybots -> your bot -> API Token\n"
            "- Do NOT paste @bot_username or t.me link\n"
            "- .env line: TELEGRAM_BOT_TOKEN=7123456789:AAH... (no quotes)"
        )


async def check_telegram(token: str) -> None:
    _validate_telegram_token(token)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        if response.status_code == 401:
            raise RuntimeError(
                "Telegram rejected the bot token (401 Unauthorized).\n"
                f"- Token length: {len(token)} chars\n"
                "- In @BotFather, open your bot and copy API Token again\n"
                "- If you clicked 'Revoke', you must paste the NEW token\n"
                "- Save .env as plain UTF-8, one line: TELEGRAM_BOT_TOKEN=...\n"
                "- Do not paste bot username (@xxx_bot), only the token"
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data)
        user = data["result"]
        print(f"OK Telegram bot: @{user.get('username')}")


async def check_ai_api(client: OpenRouterClient, model: str, base_url: str) -> None:
    answer = await client.answer(model=model, prompt="Reply exactly: BOT_CHECK_OK")
    if "BOT_CHECK_OK" not in answer.upper():
        print(f"WARN AI API answer unexpected (continuing): {answer[:120]}")
    else:
        print(f"OK AI API ({base_url}): {model}")


async def check_search(search: SearchService, provider: str) -> None:
    results = await search.search_products("wireless mouse")
    if not results:
        raise RuntimeError("Search returned no results")
    print(f"OK Search ({provider}): {len(results)} result(s), first={results[0].title[:40]}")


async def check_notion(notion: NotionClient) -> None:
    categories = await notion.list_categories()
    suffix = f": {', '.join(categories[:5])}" if categories else " (no categories yet)"
    print(f"OK Notion database categories{suffix}")


async def check_notion_write(notion: NotionClient) -> None:
    from shopping_bot.models import ShoppingItem

    page_url = await notion.add_item(
        ShoppingItem(
            title="BOT_CHECK_DELETE_ME",
            url="https://example.com/bot-check",
            category="其他",
            notes="Auto test row — safe to delete.",
        )
    )
    print(f"OK Notion write test page created{f': {page_url}' if page_url else ''}")


async def check_notion_write(notion: NotionClient) -> None:
    from shopping_bot.models import ShoppingItem

    page_url = await notion.add_item(
        ShoppingItem(
            title="BOT_CHECK_DELETE_ME",
            url="https://example.com/bot-check",
            category="其他",
            notes="Auto test row — safe to delete.",
        )
    )
    print(f"OK Notion write test page created{f': {page_url}' if page_url else ''}")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Verify shopping bot configuration.")
    parser.add_argument(
        "--write-test",
        action="store_true",
        help="Create a test row in Notion (BOT_CHECK_DELETE_ME). Off by default.",
    )
    args = parser.parse_args()

    settings = load_settings([str(ROOT / ".env")])
    openrouter = OpenRouterClient(settings.ai_api_key, base_url=settings.ai_api_base_url)
    search = SearchService(
        settings.search_result_count,
        provider=settings.search_provider,
        google_api_key=settings.google_cse_api_key,
        google_cx=settings.google_cse_id,
    )
    notion = NotionClient(settings.notion)
    errors: list[str] = []
    checks: list[tuple[str, object]] = [
        ("Telegram", check_telegram(settings.telegram_bot_token)),
        ("AI API", check_ai_api(openrouter, settings.default_model, settings.ai_api_base_url)),
        ("Search", check_search(search, settings.search_provider)),
        ("Notion", check_notion(notion)),
    ]
    if args.write_test:
        checks.append(("Notion write", check_notion_write(notion)))
    try:
        _reject_placeholders(settings)
        for label, coro in checks:
            try:
                await coro
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{label}: {exc}")
    finally:
        await openrouter.close()
        await search.close()
        await notion.close()

    if errors:
        print("\nSome checks failed:")
        for err in errors:
            print(f"\n{err}")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
