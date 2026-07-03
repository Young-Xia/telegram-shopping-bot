from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class ProductAnalysis:
    title: str
    url: str
    notes: str = ""
    what: str = ""
    suggested_category: str = ""

    def as_search_result(self) -> SearchResult:
        return SearchResult(title=self.title, url=self.url, snippet=self.notes)


@dataclass(frozen=True)
class ShoppingItem:
    title: str
    url: str
    category: str
    notes: str = ""
