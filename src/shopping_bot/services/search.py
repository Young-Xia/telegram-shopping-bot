from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from urllib.parse import urlparse

import httpx

from shopping_bot.models import SearchResult

import re

logger = logging.getLogger(__name__)

URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)


def is_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def extract_url_from_text(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    if is_url(text):
        return text
    match = URL_IN_TEXT_RE.search(text)
    if not match:
        return None
    candidate = match.group(0).rstrip(".,;:)\"'")
    return candidate if is_url(candidate) else None


def strip_urls_from_text(value: str) -> str:
    cleaned = URL_IN_TEXT_RE.sub(" ", value)
    return WHITESPACE_RE.sub(" ", cleaned).strip(" \t\n\r-–—|:;,.")


def extract_all_urls_from_text(value: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in URL_IN_TEXT_RE.findall(value):
        candidate = match.rstrip(".,;:)\"'")
        if is_url(candidate) and candidate not in seen:
            urls.append(candidate)
            seen.add(candidate)
    return urls


def _clean_html_text(value: str) -> str:
    value = TAG_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    return html.unescape(value).strip()


def _meta_content(text: str, *keys: str) -> str:
    wanted = {key.lower() for key in keys}
    for tag in META_TAG_RE.findall(text):
        attrs: dict[str, str] = {}
        for key, value in re.findall(r'([a-zA-Z_:.-]+)\s*=\s*["\']([^"\']*)["\']', tag):
            attrs[key.lower()] = value.strip()
        name = (attrs.get("property") or attrs.get("name") or "").lower()
        if name not in wanted:
            continue
        content = attrs.get("content", "").strip()
        if content:
            return _clean_html_text(content)
    return ""


def _iter_json_nodes(raw: object):
    if isinstance(raw, dict):
        yield raw
        graph = raw.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from _iter_json_nodes(item)
        for value in raw.values():
            if isinstance(value, (dict, list)):
                yield from _iter_json_nodes(value)
    elif isinstance(raw, list):
        for item in raw:
            yield from _iter_json_nodes(item)


def _product_from_json_ld(text: str) -> dict[str, str]:
    for block in JSON_LD_RE.findall(text):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in _iter_json_nodes(data):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if not any(str(item).lower() == "product" for item in types if item):
                continue
            info: dict[str, str] = {}
            if node.get("name"):
                info["title"] = _clean_html_text(str(node["name"]))
            if node.get("description"):
                info["snippet"] = _clean_html_text(str(node["description"]))
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                currency = offers.get("priceCurrency") or ""
                if price:
                    info["price"] = f"{currency} {price}".strip()
            if node.get("image"):
                image = node["image"]
                if isinstance(image, list):
                    image = image[0]
                if isinstance(image, dict):
                    image = image.get("url") or image.get("@id")
                if image:
                    info["image_url"] = str(image)
            if info:
                return info
    return {}


def _normalize_title(title: str, url: str) -> str:
    title = _clean_html_text(title)
    for suffix in (" - 淘宝", " - 天猫", " - 京东", " - 拼多多", " - Amazon", " | Taobao"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    if not title or title == url:
        host = urlparse(url).netloc
        return host or url
    return title


def _build_notes(snippet: str, price: str, image_url: str) -> str:
    parts: list[str] = []
    if price:
        parts.append(f"价格: {price}")
    if snippet:
        parts.append(f"简介: {snippet}")
    if image_url:
        parts.append(f"图片: {image_url}")
    return "\n".join(parts)


def _ddgs_client():
    try:
        from ddgs import DDGS

        return DDGS
    except ImportError:
        from duckduckgo_search import DDGS

        return DDGS


class SearchService:
    def __init__(
        self,
        result_count: int,
        *,
        provider: str = "duckduckgo",
        google_api_key: str | None = None,
        google_cx: str | None = None,
    ) -> None:
        self._result_count = min(max(result_count, 1), 10)
        self._provider = provider.strip().lower()
        self._google_api_key = google_api_key
        self._google_cx = google_cx
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True)

    async def search_products(self, query: str) -> list[SearchResult]:
        if self._provider == "google" and self._google_api_key and self._google_cx:
            try:
                return await self.google_search(query)
            except httpx.HTTPStatusError as exc:
                logger.warning("Google search failed (%s), falling back to DuckDuckGo", exc.response.status_code)
        return await self.duckduckgo_search(query)

    async def duckduckgo_search(self, query: str) -> list[SearchResult]:
        def _run() -> list[SearchResult]:
            ddgs_cls = _ddgs_client()
            last_error: Exception | None = None
            for attempt in range(3):
                rows: list[SearchResult] = []
                try:
                    with ddgs_cls() as ddgs:
                        for item in ddgs.text(query, max_results=self._result_count):
                            title = str(item.get("title") or "").strip()
                            url = str(item.get("href") or item.get("link") or "").strip()
                            if title and url:
                                rows.append(
                                    SearchResult(
                                        title=title,
                                        url=url,
                                        snippet=str(item.get("body") or item.get("snippet") or ""),
                                    )
                                )
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.warning("DuckDuckGo search attempt %s failed: %s", attempt + 1, exc)
                    time.sleep(0.6 * (attempt + 1))
                    continue
                if rows:
                    return rows
                time.sleep(0.6 * (attempt + 1))
            if last_error:
                raise last_error
            return []

        return await asyncio.to_thread(_run)

    async def google_search(self, query: str) -> list[SearchResult]:
        if not self._google_api_key or not self._google_cx:
            raise RuntimeError("Google Custom Search is not configured")
        response = await self._client.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": self._google_api_key,
                "cx": self._google_cx,
                "q": query,
                "num": self._result_count,
            },
        )
        response.raise_for_status()
        data = response.json()
        results: list[SearchResult] = []
        for item in data.get("items", []):
            link = item.get("link")
            title = item.get("title")
            if link and title:
                results.append(
                    SearchResult(
                        title=str(title),
                        url=str(link),
                        snippet=str(item.get("snippet") or ""),
                    )
                )
        return results

    async def parse_link(self, url: str) -> SearchResult:
        try:
            return await asyncio.wait_for(self._fetch_and_parse_link(url), timeout=25.0)
        except asyncio.TimeoutError:
            logger.warning("Link parse timed out for %s", url)
            return SearchResult(
                title=url,
                url=url,
                snippet="页面读取超时，仍可保存链接并手动分类。",
            )

    async def _fetch_and_parse_link(self, url: str) -> SearchResult:
        response = await self._client.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()
        final_url = str(response.url)
        text = response.text[:800_000]

        product = _product_from_json_ld(text)
        title = (
            product.get("title")
            or _meta_content(text, "og:title", "twitter:title")
            or (_clean_html_text(TITLE_RE.search(text).group(1)) if TITLE_RE.search(text) else "")
            or (_clean_html_text(H1_RE.search(text).group(1)) if H1_RE.search(text) else "")
        )
        title = _normalize_title(title, final_url)

        snippet = (
            product.get("snippet")
            or _meta_content(text, "og:description", "description", "twitter:description")
            or ""
        )
        price = product.get("price") or _meta_content(text, "product:price:amount", "og:price:amount")
        currency = _meta_content(text, "product:price:currency", "og:price:currency")
        if price and currency and currency not in price:
            price = f"{currency} {price}".strip()

        image_url = product.get("image_url") or _meta_content(text, "og:image", "twitter:image")
        notes = _build_notes(snippet, price, image_url)

        return SearchResult(title=title, url=final_url, snippet=notes or snippet)

    async def close(self) -> None:
        await self._client.aclose()
