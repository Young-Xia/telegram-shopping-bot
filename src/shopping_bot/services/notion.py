from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from shopping_bot.categories import (
    CATEGORY_COLORS,
    CATEGORY_PROPERTY_NAME,
    DEFAULT_CATEGORIES,
    NOTES_ALIASES,
    NOTES_PROPERTY_NAME,
    TITLE_ALIASES,
    URL_ALIASES,
    URL_PROPERTY_NAME,
)
from shopping_bot.config import NotionConfig
from shopping_bot.models import ShoppingItem

CATEGORY_PROPERTY_CANDIDATES = ("Category", "category", "分类", "类别")


class NotionClient:
    def __init__(self, config: NotionConfig) -> None:
        self._config = config
        self._schema: dict[str, dict[str, Any]] | None = None
        self._client = httpx.AsyncClient(
            base_url="https://api.notion.com/v1",
            timeout=httpx.Timeout(30.0),
            headers={
                "Authorization": f"Bearer {config.token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
        )

    def _invalidate_schema(self) -> None:
        self._schema = None

    async def _load_schema(self) -> dict[str, dict[str, Any]]:
        if self._schema is not None:
            return self._schema
        response = await self._client.get(f"/databases/{self._config.database_id}")
        response.raise_for_status()
        self._schema = response.json().get("properties", {})
        return self._schema

    def _pick_property(self, schema: dict[str, dict[str, Any]], preferred: str | None, kind: str) -> str | None:
        if preferred and preferred in schema and schema[preferred].get("type") == kind:
            return preferred
        for name, prop in schema.items():
            if prop.get("type") == kind:
                return name
        return None

    def _pick_named_property(
        self,
        schema: dict[str, dict[str, Any]],
        preferred: str | None,
        aliases: tuple[str, ...],
        kind: str,
    ) -> str | None:
        for name in (preferred, *aliases):
            if name and name in schema and schema[name].get("type") == kind:
                return name
        return self._pick_property(schema, preferred, kind)

    def _pick_category_property(self, schema: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
        status_prop = self._pick_property(schema, self._config.status_property, "status")
        if not status_prop:
            status_prop = self._pick_property(schema, self._config.status_property, "select")

        candidates = [self._config.category_property, CATEGORY_PROPERTY_NAME, *CATEGORY_PROPERTY_CANDIDATES]
        seen: set[str] = set()
        for name in candidates:
            if not name or name in seen:
                continue
            seen.add(name)
            if name not in schema:
                continue
            kind = schema[name].get("type")
            if kind in {"select", "multi_select"} and name != status_prop:
                return name, kind
        return None, None

    def _status_value(self, schema: dict[str, dict[str, Any]], prop_name: str) -> dict[str, Any]:
        prop = schema[prop_name]
        kind = prop.get("type")
        if kind not in {"status", "select"}:
            raise RuntimeError(f"Property {prop_name!r} is not status/select")
        options = (prop.get(kind) or {}).get("options") or []
        names = [str(o["name"]) for o in options if o.get("name")]
        chosen = self._config.default_status if self._config.default_status in names else (names[0] if names else None)
        if not chosen:
            raise RuntimeError(f"Status property {prop_name!r} has no options")
        return {kind: {"name": chosen}}

    def _select_options_payload(self, existing: list[dict[str, Any]], names: list[str]) -> list[dict[str, Any]]:
        by_name = {str(item["name"]): item for item in existing if item.get("name")}
        payload: list[dict[str, Any]] = []
        for name in names:
            if name in by_name:
                option = by_name[name]
                payload.append(
                    {
                        "id": option["id"],
                        "name": name,
                        "color": option.get("color") or CATEGORY_COLORS.get(name, "default"),
                    }
                )
            else:
                payload.append({"name": name, "color": CATEGORY_COLORS.get(name, "default")})
        for name, option in by_name.items():
            if name not in names:
                payload.append(
                    {
                        "id": option["id"],
                        "name": name,
                        "color": option.get("color") or "default",
                    }
                )
        return payload

    async def _patch_select_options(self, prop_name: str, option_names: list[str]) -> None:
        schema = await self._load_schema()
        prop = schema[prop_name]
        existing = (prop.get("select") or {}).get("options") or []
        payload = self._select_options_payload(existing, option_names)
        response = await self._client.patch(
            f"/databases/{self._config.database_id}",
            json={"properties": {prop_name: {"select": {"options": payload}}}},
        )
        response.raise_for_status()
        self._invalidate_schema()

    async def _ensure_property(self, prop_name: str, prop_type: dict[str, Any]) -> str:
        schema = await self._load_schema()
        if prop_name in schema:
            return prop_name
        response = await self._client.patch(
            f"/databases/{self._config.database_id}",
            json={"properties": {prop_name: prop_type}},
        )
        response.raise_for_status()
        self._invalidate_schema()
        return prop_name

    async def ensure_category_areas(self) -> str:
        schema = await self._load_schema()
        prop_name, kind = self._pick_category_property(schema)
        if prop_name and kind == "select":
            existing_names = [
                str(option["name"]) for option in (schema[prop_name].get("select") or {}).get("options") or []
            ]
            merged = list(dict.fromkeys([*DEFAULT_CATEGORIES, *existing_names]))
            await self._patch_select_options(prop_name, merged)
            return prop_name

        if prop_name and kind == "multi_select":
            return prop_name

        options = [{"name": name, "color": CATEGORY_COLORS.get(name, "default")} for name in DEFAULT_CATEGORIES]
        return await self._ensure_property(CATEGORY_PROPERTY_NAME, {"select": {"options": options}})

    async def ensure_url_property(self) -> str:
        schema = await self._load_schema()
        existing = self._pick_named_property(schema, self._config.url_property, URL_ALIASES, "url")
        if existing:
            return existing
        return await self._ensure_property(URL_PROPERTY_NAME, {"url": {}})

    async def ensure_notes_property(self) -> str | None:
        schema = await self._load_schema()
        existing = self._pick_named_property(schema, self._config.notes_property, NOTES_ALIASES, "rich_text")
        if existing:
            return existing
        return await self._ensure_property(NOTES_PROPERTY_NAME, {"rich_text": {}})

    async def ensure_category_option(self, category: str) -> None:
        category = category.strip()
        if not category:
            return
        prop_name = await self.ensure_category_areas()
        schema = await self._load_schema()
        prop = schema[prop_name]
        existing_names = [
            str(option["name"]) for option in (prop.get("select") or {}).get("options") or []
        ]
        if category in existing_names:
            return
        await self._patch_select_options(prop_name, [*existing_names, category])

    async def list_categories(self) -> list[str]:
        await self.ensure_category_areas()
        schema = await self._load_schema()
        prop_name, kind = self._pick_category_property(schema)
        if not prop_name or not kind:
            return list(DEFAULT_CATEGORIES)
        prop = schema[prop_name]
        options = (prop.get(kind) or {}).get("options") or []
        names = [str(option["name"]) for option in options if option.get("name")]
        return sorted(names) if names else list(DEFAULT_CATEGORIES)

    async def add_item(self, item: ShoppingItem) -> str:
        if item.category:
            await self.ensure_category_option(item.category)
        await self.ensure_url_property()
        notes_prop_name = await self.ensure_notes_property()

        schema = await self._load_schema()
        properties: dict[str, Any] = {}

        title_prop = self._pick_named_property(schema, self._config.title_property, TITLE_ALIASES, "title")
        if not title_prop:
            raise RuntimeError("Notion database has no title property")

        title_text = item.title[:2000]
        category_prop, category_kind = self._pick_category_property(schema)
        if item.category and not category_prop:
            prefix = f"[{item.category}] "
            if not title_text.startswith(prefix):
                title_text = f"{prefix}{title_text}"[:2000]

        url_prop = self._pick_named_property(schema, self._config.url_property, URL_ALIASES, "url")
        properties[title_prop] = {"title": [{"text": {"content": title_text}}]}

        if url_prop and item.url:
            properties[url_prop] = {"url": item.url}

        if category_prop and category_kind and item.category:
            if category_kind == "multi_select":
                properties[category_prop] = {"multi_select": [{"name": item.category}]}
            else:
                properties[category_prop] = {"select": {"name": item.category}}

        status_prop = self._pick_property(schema, self._config.status_property, "status")
        if not status_prop:
            status_prop = self._pick_property(schema, self._config.status_property, "select")
        if status_prop:
            properties[status_prop] = self._status_value(schema, status_prop)

        if notes_prop_name and item.notes:
            properties[notes_prop_name] = {
                "rich_text": [{"text": {"content": item.notes[:2000]}}]
            }

        date_prop = self._config.added_at_property if self._config.added_at_property in schema else None
        if not date_prop:
            for name, prop in schema.items():
                if prop.get("type") == "date":
                    date_prop = name
                    break
        if date_prop:
            properties[date_prop] = {"date": {"start": datetime.now(timezone.utc).isoformat()}}

        response = await self._client.post(
            "/pages",
            json={
                "parent": {"database_id": self._config.database_id},
                "properties": properties,
            },
        )
        if response.status_code >= 400:
            detail = response.text[:800]
            raise httpx.HTTPStatusError(
                f"Notion save failed ({response.status_code}): {detail}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        data = response.json()
        return str(data.get("url") or "")

    async def close(self) -> None:
        await self._client.aclose()
