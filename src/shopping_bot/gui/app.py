"""GUI entry helpers — heavy UI lives in _window.py (lazy-loaded)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shopping_bot.gui._window import ShoppingBotApp


def create_app() -> ShoppingBotApp:
    from shopping_bot.gui._window import ShoppingBotApp

    return ShoppingBotApp()


def main() -> None:
    from shopping_bot.gui.launcher import run

    run()


def __getattr__(name: str):
    if name == "ShoppingBotApp":
        from shopping_bot.gui._window import ShoppingBotApp

        return ShoppingBotApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    main()
