"""Print Notion database property names and types (no secrets)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopping_bot.config import load_settings  # noqa: E402


async def main() -> None:
    settings = load_settings([str(ROOT / ".env")])
    cfg = settings.notion
    async with httpx.AsyncClient(
        base_url="https://api.notion.com/v1",
        timeout=30.0,
        headers={
            "Authorization": f"Bearer {cfg.token}",
            "Notion-Version": "2022-06-28",
        },
    ) as client:
        response = await client.get(f"/databases/{cfg.database_id}")
        response.raise_for_status()
        data = response.json()
        print("Database title:", " ".join(t.get("plain_text", "") for t in data.get("title", [])))
        print("\nProperties:")
        for name, prop in data.get("properties", {}).items():
            kind = prop.get("type")
            extra = ""
            if kind in {"select", "status", "multi_select"}:
                options = (prop.get(kind) or {}).get("options") or []
                option_names = [o.get("name") for o in options if o.get("name")]
                extra = f" options={option_names[:10]}"
            print(f"  - {name!r}: {kind}{extra}")

        # Try a minimal write to see exact 400 message
        print("\nConfigured mapping:")
        print(f"  title={cfg.title_property!r}, url={cfg.url_property!r}, category={cfg.category_property!r}")
        print(f"  status={cfg.status_property!r} ({cfg.status_property_type}), default={cfg.default_status!r}")

        test_payload = {
            "parent": {"database_id": cfg.database_id},
            "properties": {
                cfg.title_property: {"title": [{"text": {"content": "BOT_SCHEMA_TEST"}}]},
            },
        }
        test = await client.post("/pages", json=test_payload)
        print("\nMinimal write test:", test.status_code)
        if test.status_code >= 400:
            print(json.dumps(test.json(), indent=2, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
