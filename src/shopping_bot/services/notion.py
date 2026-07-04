from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from shopping_bot.categories import (
    CATEGORY_COLORS,
    CATEGORY_PROPERTY_NAME,
    DEFAULT_CATEGORIES,
    IMAGES_ALIASES,
    IMAGES_PROPERTY_NAME,
    NOTES_ALIASES,
    NOTES_PROPERTY_NAME,
    TITLE_ALIASES,
    URL_ALIASES,
    URL_PROPERTY_NAME,
)
from shopping_bot.config import NotionConfig
from shopping_bot.models import SaveResult, ShoppingItem

logger = logging.getLogger(__name__)

CATEGORY_PROPERTY_CANDIDATES = ("Category", "category", "分类", "类别")
STATUS_PROPERTY_CANDIDATES = ("Status", "status", "状态", "狀態")
NOTION_API_VERSION = "2022-06-28"
NOTION_FILE_UPLOAD_API_VERSION = "2025-09-03"
ImagePayload = tuple[str, bytes, str]
TITLE_SIMILARITY_THRESHOLD = 0.82
URL_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "spm",
}


@dataclass(frozen=True)
class _ExistingItem:
    page_id: str
    page_url: str
    title: str
    url: str
    notes: str


class NotionClient:
    def __init__(self, config: NotionConfig) -> None:
        self._config = config
        self._schema: dict[str, dict[str, Any]] | None = None
        self._client = httpx.AsyncClient(
            base_url="https://api.notion.com/v1",
            timeout=httpx.Timeout(60.0),
            headers={
                "Authorization": f"Bearer {config.token}",
                "Notion-Version": NOTION_API_VERSION,
            },
        )

    def _auth_headers(self, *, version: str = NOTION_API_VERSION) -> dict[str, str]:
        return {
            "Authorization": self._client.headers["Authorization"],
            "Notion-Version": version,
        }

    def _json_headers(self, *, version: str = NOTION_API_VERSION) -> dict[str, str]:
        return {
            **self._auth_headers(version=version),
            "Content-Type": "application/json",
        }

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

    def _pick_status_property(self, schema: dict[str, dict[str, Any]]) -> str | None:
        for kind in ("status", "select"):
            for name in (self._config.status_property, *STATUS_PROPERTY_CANDIDATES):
                if name and name in schema and schema[name].get("type") == kind:
                    return name
        for name, prop in schema.items():
            if prop.get("type") == "status":
                return name
        return None

    def _pick_category_property(self, schema: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
        status_prop = self._pick_status_property(schema)

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
            headers=self._json_headers(),
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
            headers=self._json_headers(),
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

    async def ensure_images_property(self) -> str | None:
        preferred = self._config.images_property or IMAGES_PROPERTY_NAME
        schema = await self._load_schema()
        existing = self._pick_named_property(schema, preferred, IMAGES_ALIASES, "files")
        if existing:
            return existing
        return await self._ensure_property(preferred, {"files": {}})

    async def ensure_category_option(self, category: str) -> None:
        category = category.strip()
        if not category:
            return
        prop_name = await self.ensure_category_areas()
        schema = await self._load_schema()
        if prop_name not in schema:
            self._invalidate_schema()
            schema = await self._load_schema()
        if prop_name not in schema:
            picked_name, _picked_kind = self._pick_category_property(schema)
            if not picked_name:
                logger.warning("Notion category property %r was not found after ensuring it", prop_name)
                return
            prop_name = picked_name

        prop = schema[prop_name]
        kind = prop.get("type")
        if kind == "multi_select":
            existing_names = [
                str(option["name"]) for option in (prop.get("multi_select") or {}).get("options") or []
            ]
            if category not in existing_names:
                logger.info("Notion multi_select category %r will be created when saving the page", category)
            return
        if kind != "select":
            logger.warning("Notion category property %r is %r, not select/multi_select", prop_name, kind)
            return

        existing_names = [str(option["name"]) for option in (prop.get("select") or {}).get("options") or []]
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

    @staticmethod
    def _guess_image_meta(filename: str, content: bytes, content_type: str) -> tuple[str, str]:
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", filename.rsplit(".", 1)[0] + ".png"
        if content.startswith(b"GIF87a") or content.startswith(b"GIF89a"):
            return "image/gif", filename.rsplit(".", 1)[0] + ".gif"
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp", filename.rsplit(".", 1)[0] + ".webp"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", filename.rsplit(".", 1)[0] + ".jpg"
        return content_type or "image/jpeg", filename

    async def _upload_image(self, *, filename: str, content: bytes, content_type: str) -> str:
        content_type, filename = self._guess_image_meta(filename, content, content_type)
        create = await self._client.post(
            "/file_uploads",
            headers=self._json_headers(version=NOTION_FILE_UPLOAD_API_VERSION),
            json={
                "mode": "single_part",
                "filename": filename,
                "content_type": content_type,
            },
        )
        if create.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Notion file upload create failed ({create.status_code}): {create.text[:500]}",
                request=create.request,
                response=create,
            )
        file_upload_id = str(create.json()["id"])

        # Do not set Content-Type here; httpx must add multipart boundary automatically.
        send = await self._client.post(
            f"/file_uploads/{file_upload_id}/send",
            headers=self._auth_headers(version=NOTION_FILE_UPLOAD_API_VERSION),
            files={"file": (filename, content, content_type)},
        )
        if send.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Notion file upload send failed ({send.status_code}): {send.text[:500]}",
                request=send.request,
                response=send,
            )
        return file_upload_id

    async def _set_page_images(
        self,
        page_id: str,
        prop_name: str,
        uploads: list[tuple[str, str]],
    ) -> None:
        if not uploads:
            return
        files_payload = [
            {
                "name": filename,
                "type": "file_upload",
                "file_upload": {"id": file_upload_id},
            }
            for filename, file_upload_id in uploads
        ]
        response = await self._client.patch(
            f"/pages/{page_id}",
            headers=self._json_headers(version=NOTION_FILE_UPLOAD_API_VERSION),
            json={"properties": {prop_name: {"files": files_payload}}},
        )
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Notion image property update failed ({response.status_code}): {response.text[:500]}",
                request=response.request,
                response=response,
            )

    @staticmethod
    def _plain_text(rich_text: list[dict[str, Any]] | None) -> str:
        if not rich_text:
            return ""
        return "".join(str(part.get("plain_text") or "") for part in rich_text).strip()

    @staticmethod
    def _normalize_title(title: str) -> str:
        cleaned = re.sub(r"^\[[^\]]+\]\s*", "", (title or "").strip())
        cleaned = re.sub(r"\s+", " ", cleaned).casefold()
        return cleaned

    @staticmethod
    def _normalize_url(url: str) -> str:
        raw = (url or "").strip()
        if not raw:
            return ""
        parsed = urlparse(raw)
        if not parsed.scheme:
            parsed = urlparse(f"https://{raw}")
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in URL_TRACKING_PARAMS
        ]
        path = parsed.path.rstrip("/") or ""
        return urlunparse(
            (
                (parsed.scheme or "https").casefold(),
                (parsed.netloc or "").casefold(),
                path,
                "",
                urlencode(query),
                "",
            )
        )

    @classmethod
    def _title_similarity(cls, left: str, right: str) -> float:
        a = cls._normalize_title(left)
        b = cls._normalize_title(right)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        return SequenceMatcher(None, a, b).ratio()

    @classmethod
    def _match_score(cls, item: ShoppingItem, existing: _ExistingItem) -> float:
        item_url = cls._normalize_url(item.url)
        existing_url = cls._normalize_url(existing.url)
        if item_url and existing_url and item_url == existing_url:
            return 1.0

        title_score = cls._title_similarity(item.title, existing.title)
        if title_score < TITLE_SIMILARITY_THRESHOLD:
            return 0.0

        # Different product links with only vaguely similar titles should not merge.
        if item_url and existing_url and item_url != existing_url and title_score < 0.92:
            return 0.0

        notes_bonus = 0.0
        if item.notes and existing.notes:
            notes_bonus = 0.05 * SequenceMatcher(
                None,
                item.notes.casefold(),
                existing.notes.casefold(),
            ).ratio()
        return min(1.0, title_score + notes_bonus)

    async def _list_existing_items(
        self,
        *,
        title_prop: str,
        url_prop: str | None,
        notes_prop: str | None,
        limit: int = 200,
    ) -> list[_ExistingItem]:
        results: list[_ExistingItem] = []
        cursor: str | None = None
        while len(results) < limit:
            payload: dict[str, Any] = {"page_size": min(100, limit - len(results))}
            if cursor:
                payload["start_cursor"] = cursor
            response = await self._client.post(
                f"/databases/{self._config.database_id}/query",
                headers=self._json_headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            for page in data.get("results") or []:
                props = page.get("properties") or {}
                title = self._plain_text((props.get(title_prop) or {}).get("title"))
                url = ""
                if url_prop:
                    url = str((props.get(url_prop) or {}).get("url") or "")
                notes = ""
                if notes_prop:
                    notes = self._plain_text((props.get(notes_prop) or {}).get("rich_text"))
                results.append(
                    _ExistingItem(
                        page_id=str(page.get("id") or ""),
                        page_url=str(page.get("url") or ""),
                        title=title,
                        url=url,
                        notes=notes,
                    )
                )
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not cursor:
                break
        return results

    async def _find_similar_item(
        self,
        item: ShoppingItem,
        *,
        title_prop: str,
        url_prop: str | None,
        notes_prop: str | None,
    ) -> _ExistingItem | None:
        existing_items = await self._list_existing_items(
            title_prop=title_prop,
            url_prop=url_prop,
            notes_prop=notes_prop,
        )
        best: _ExistingItem | None = None
        best_score = 0.0
        for existing in existing_items:
            if not existing.page_id:
                continue
            score = self._match_score(item, existing)
            if score > best_score:
                best = existing
                best_score = score
        if best and best_score >= TITLE_SIMILARITY_THRESHOLD:
            logger.info(
                "Matched existing Notion item %s (score=%.2f, title=%r)",
                best.page_id,
                best_score,
                best.title,
            )
            return best
        return None

    def _item_properties(
        self,
        item: ShoppingItem,
        *,
        schema: dict[str, dict[str, Any]],
        title_prop: str,
        url_prop: str | None,
        notes_prop_name: str | None,
        include_status: bool,
        include_date: bool,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        title_text = item.title[:2000]
        category_prop, category_kind = self._pick_category_property(schema)
        if item.category and not category_prop:
            prefix = f"[{item.category}] "
            if not title_text.startswith(prefix):
                title_text = f"{prefix}{title_text}"[:2000]

        properties[title_prop] = {"title": [{"text": {"content": title_text}}]}

        if url_prop and item.url:
            properties[url_prop] = {"url": item.url}

        if category_prop and category_kind and item.category:
            if category_kind == "multi_select":
                properties[category_prop] = {"multi_select": [{"name": item.category}]}
            else:
                properties[category_prop] = {"select": {"name": item.category}}

        if include_status:
            status_prop = self._pick_status_property(schema)
            if status_prop:
                properties[status_prop] = self._status_value(schema, status_prop)

        if notes_prop_name and item.notes:
            properties[notes_prop_name] = {
                "rich_text": [{"text": {"content": item.notes[:2000]}}]
            }

        if include_date:
            date_prop = self._config.added_at_property if self._config.added_at_property in schema else None
            if not date_prop:
                for name, prop in schema.items():
                    if prop.get("type") == "date":
                        date_prop = name
                        break
            if date_prop:
                properties[date_prop] = {"date": {"start": datetime.now(timezone.utc).isoformat()}}

        return properties

    async def _attach_images(
        self,
        page_id: str,
        images: list[ImagePayload] | None,
        images_prop_name: str | None,
    ) -> int:
        if not images or not page_id or not images_prop_name:
            return 0
        uploads: list[tuple[str, str]] = []
        for filename, content, content_type in images:
            try:
                file_upload_id = await self._upload_image(
                    filename=filename,
                    content=content,
                    content_type=content_type,
                )
                uploads.append((filename, file_upload_id))
            except httpx.HTTPStatusError:
                logger.exception("Notion image upload failed for %s", filename)
            except Exception:
                logger.exception("Notion image upload failed for %s", filename)
        if not uploads:
            return 0
        try:
            await self._set_page_images(page_id, images_prop_name, uploads)
            return len(uploads)
        except httpx.HTTPStatusError:
            logger.exception("Notion image property update failed for page %s", page_id)
        except Exception:
            logger.exception("Notion image property update failed for page %s", page_id)
        return 0

    async def add_item(self, item: ShoppingItem, *, images: list[ImagePayload] | None = None) -> SaveResult:
        if item.category:
            await self.ensure_category_option(item.category)
        await self.ensure_url_property()
        notes_prop_name = await self.ensure_notes_property()
        images_prop_name = await self.ensure_images_property() if images else None

        schema = await self._load_schema()
        title_prop = self._pick_named_property(schema, self._config.title_property, TITLE_ALIASES, "title")
        if not title_prop:
            raise RuntimeError("Notion database has no title property")
        url_prop = self._pick_named_property(schema, self._config.url_property, URL_ALIASES, "url")

        existing = await self._find_similar_item(
            item,
            title_prop=title_prop,
            url_prop=url_prop,
            notes_prop=notes_prop_name,
        )

        if existing:
            properties = self._item_properties(
                item,
                schema=schema,
                title_prop=title_prop,
                url_prop=url_prop,
                notes_prop_name=notes_prop_name,
                include_status=False,
                include_date=False,
            )
            response = await self._client.patch(
                f"/pages/{existing.page_id}",
                headers=self._json_headers(),
                json={"properties": properties},
            )
            if response.status_code >= 400:
                detail = response.text[:800]
                raise httpx.HTTPStatusError(
                    f"Notion update failed ({response.status_code}): {detail}",
                    request=response.request,
                    response=response,
                )
            data = response.json()
            page_id = str(data.get("id") or existing.page_id)
            page_url = str(data.get("url") or existing.page_url)
            attached_images = await self._attach_images(page_id, images, images_prop_name)
            return SaveResult(page_url=page_url, attached_images=attached_images, updated=True)

        properties = self._item_properties(
            item,
            schema=schema,
            title_prop=title_prop,
            url_prop=url_prop,
            notes_prop_name=notes_prop_name,
            include_status=True,
            include_date=True,
        )
        response = await self._client.post(
            "/pages",
            headers=self._json_headers(),
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
        data = response.json()
        page_id = str(data.get("id") or "")
        page_url = str(data.get("url") or "")
        attached_images = await self._attach_images(page_id, images, images_prop_name)
        return SaveResult(page_url=page_url, attached_images=attached_images, updated=False)

    async def close(self) -> None:
        await self._client.aclose()
