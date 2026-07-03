from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    appearance: str
    page_bg: str
    sidebar: str
    card: str
    card_border: str
    text_muted: str
    text_primary: str
    nav_text: str
    log_bg: str
    accent: str
    accent_hover: str
    success: str
    success_hover: str
    danger: str
    danger_hover: str
    warn: str
    btn_secondary: str
    btn_secondary_hover: str
    btn_secondary_text: str


PALETTES: dict[str, ThemePalette] = {
    "dark": ThemePalette(
        appearance="dark",
        page_bg="#0b1220",
        sidebar="#0f172a",
        card="#1e293b",
        card_border="#334155",
        text_muted="#94a3b8",
        text_primary="#f1f5f9",
        nav_text="#e2e8f0",
        log_bg="#020617",
        accent="#38bdf8",
        accent_hover="#0ea5e9",
        success="#4ade80",
        success_hover="#22c55e",
        danger="#f87171",
        danger_hover="#ef4444",
        warn="#fbbf24",
        btn_secondary="#475569",
        btn_secondary_hover="#64748b",
        btn_secondary_text="#f8fafc",
    ),
    "light": ThemePalette(
        appearance="light",
        page_bg="#f1f5f9",
        sidebar="#ffffff",
        card="#ffffff",
        card_border="#cbd5e1",
        text_muted="#64748b",
        text_primary="#0f172a",
        nav_text="#334155",
        log_bg="#ffffff",
        accent="#0284c7",
        accent_hover="#0369a1",
        success="#16a34a",
        success_hover="#15803d",
        danger="#dc2626",
        danger_hover="#b91c1c",
        warn="#d97706",
        btn_secondary="#cbd5e1",
        btn_secondary_hover="#94a3b8",
        btn_secondary_text="#0f172a",
    ),
}

FONT_FAMILY = "Microsoft YaHei UI"
