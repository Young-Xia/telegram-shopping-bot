"""Fast launcher — no tkinter splash (conflicts with CustomTkinter)."""

from __future__ import annotations

import sys

from shopping_bot.gui.splash_state import clear_markers, external_splash_active, mark_loading


def _log_boot(message: str) -> None:
    try:
        from pathlib import Path

        log_file = Path(__file__).resolve().parents[3] / "logs" / "gui-startup.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except Exception:
        pass


def _hide_console_window() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _wait_for_external_splash(timeout: float = 3.0) -> bool:
    if external_splash_active():
        return True
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if external_splash_active():
            return True
        time.sleep(0.05)
    return False


def _load_app():
    from shopping_bot.gui._window import ShoppingBotApp

    return ShoppingBotApp()


def run() -> None:
    _hide_console_window()
    _log_boot("launcher: start")
    _wait_for_external_splash()
    if not external_splash_active():
        mark_loading()
    try:
        app = _load_app()
        _log_boot("launcher: app created")
    except Exception:
        import traceback
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        log_file = root / "logs" / "gui-startup.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(traceback.format_exc(), encoding="utf-8")
        clear_markers()
        raise
    try:
        app.mainloop()
    finally:
        clear_markers()


def notify_gui_ready() -> None:
    from shopping_bot.gui.splash_state import mark_ready

    mark_ready()


if __name__ == "__main__":
    run()
