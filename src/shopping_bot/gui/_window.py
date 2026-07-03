from __future__ import annotations

import sys
import threading
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from shopping_bot.gui.env_store import (
    ADVANCED_FIELDS,
    AI_SETUP_FIELDS,
    CORE_SETUP_FIELDS,
    DEFAULT_VISION_MODEL,
    create_env_from_example,
    load_merged_env,
    missing_required_fields,
    patch_env,
    save_env,
)
from shopping_bot.gui.paths import env_path, project_root
from shopping_bot.gui.gui_prefs import get_theme, set_theme
from shopping_bot.gui.resizable_textbox import ResizableTextbox
from shopping_bot.gui.themes import FONT_FAMILY, PALETTES, ThemePalette
from shopping_bot.gui.tutorial import BOT_TUTORIAL_ZH, SETUP_GUIDE_ZH


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
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


_FONT_CACHE: dict[tuple[int, str], ctk.CTkFont] = {}


def _pm():
    from shopping_bot.gui import process_manager as pm

    return pm


def _font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    key = (size, weight)
    cached = _FONT_CACHE.get(key)
    if cached is None:
        cached = ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
        _FONT_CACHE[key] = cached
    return cached


class SecretEntry(ctk.CTkFrame):
    def __init__(self, master, palette: ThemePalette, placeholder: str = "", **kwargs) -> None:
        super().__init__(master, fg_color="transparent", **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self._visible = False
        self.entry = ctk.CTkEntry(
            self,
            placeholder_text=placeholder,
            show="•",
            height=40,
            font=_font(13),
            border_width=1,
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.toggle = ctk.CTkButton(
            self,
            text="👁",
            width=44,
            height=40,
            fg_color=palette.btn_secondary,
            hover_color=palette.btn_secondary_hover,
            text_color=palette.btn_secondary_text,
            font=_font(13),
            command=self._toggle_visibility,
        )
        self.toggle.grid(row=0, column=1, padx=(8, 0))

    def _toggle_visibility(self) -> None:
        self._visible = not self._visible
        self.entry.configure(show="" if self._visible else "•")

    def get(self) -> str:
        return self.entry.get().strip()

    def set(self, value: str) -> None:
        self.entry.delete(0, "end")
        if value:
            self.entry.insert(0, value)


class FieldRow(ctk.CTkFrame):
    def __init__(
        self,
        master,
        key: str,
        label: str,
        palette: ThemePalette,
        *,
        required: bool = True,
        secret: bool = False,
        hint: str = "",
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.key = key
        self.grid_columnconfigure(0, weight=1)

        title = label if required else f"{label}（可选）"
        self._title_label = ctk.CTkLabel(
            self,
            text=title,
            anchor="w",
            font=_font(14, weight="bold"),
            text_color=palette.text_primary,
        )
        self._title_label.grid(row=0, column=0, sticky="w")
        self._hint_label = None
        if hint:
            self._hint_label = ctk.CTkLabel(
                self,
                text=hint,
                anchor="w",
                text_color=palette.text_muted,
                font=_font(12),
                wraplength=620,
                justify="left",
            )
            self._hint_label.grid(row=1, column=0, sticky="w", pady=(2, 6))
        widget_row = 2 if hint else 1
        if secret:
            self.widget = SecretEntry(self, palette)
        else:
            self.widget = ctk.CTkEntry(self, height=40, font=_font(13), border_width=1)
        self.widget.grid(row=widget_row, column=0, sticky="ew", pady=(0, 14))

    def apply_theme(self, palette: ThemePalette) -> None:
        self._title_label.configure(text_color=palette.text_primary)
        if self._hint_label is not None:
            self._hint_label.configure(text_color=palette.text_muted)
        if isinstance(self.widget, SecretEntry):
            self.widget.toggle.configure(
                fg_color=palette.btn_secondary,
                hover_color=palette.btn_secondary_hover,
                text_color=palette.btn_secondary_text,
            )

    def get(self) -> str:
        if isinstance(self.widget, SecretEntry):
            return self.widget.get()
        return self.widget.get().strip()

    def set(self, value: str) -> None:
        if isinstance(self.widget, SecretEntry):
            self.widget.set(value)
        else:
            self.widget.delete(0, "end")
            if value:
                self.widget.insert(0, value)


class ShoppingBotApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.withdraw()
        _enable_dpi_awareness()
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)

        self.title("Telegram 购物机器人")
        self.geometry("1020x760")
        self.minsize(900, 680)

        self._theme_name = get_theme("dark")
        self.palette = PALETTES[self._theme_name]
        ctk.set_appearance_mode(self.palette.appearance)
        ctk.set_default_color_theme("blue")

        self._field_rows: dict[str, FieldRow] = {}
        self._card_frames: list[ctk.CTkFrame] = []
        self._section_frames: list[ctk.CTkFrame] = []
        self._muted_labels: list[ctk.CTkLabel] = []
        self._primary_labels: list[ctk.CTkLabel] = []
        self._secondary_buttons: list[ctk.CTkButton] = []
        self._current_page = "control"
        self._log_job: str | None = None
        self._status_job: str | None = None
        self._busy = False
        self._setup_built = False
        self._logs_built = False
        self._cached_env: dict[str, str] | None = None
        self._last_status = None
        self._control_frame: ctk.CTkFrame | None = None
        self._tools_built = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_pages_shell()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after_idle(self._build_initial_pages)

    def _bootstrap_deferred(self) -> None:
        threading.Thread(target=self._load_env_background, daemon=True).start()
        self._refresh_status_async()

    def _load_env_background(self) -> None:
        try:
            values = load_merged_env()
        except Exception:
            values = {}
        self.after(0, lambda: self._on_env_loaded(values))

    def _on_env_loaded(self, values: dict[str, str]) -> None:
        self._cached_env = values
        if self._setup_built:
            self._apply_env_to_fields(values)
            self._update_setup_message()
        self._load_vision_model_field(values)
        self._schedule_status_poll()

    def _apply_env_to_fields(self, values: dict[str, str]) -> None:
        for key, row in self._field_rows.items():
            row.set(values.get(key, ""))

    def _update_setup_message(self) -> None:
        if not hasattr(self, "setup_message"):
            return
        if env_path().is_file():
            self.setup_message.configure(
                text=f"已加载 {env_path()}",
                text_color=self.palette.text_muted,
            )
        else:
            self.setup_message.configure(
                text="尚未创建 .env，请填写下方配置并保存，或从模板创建。",
                text_color=self.palette.warn,
            )

    # ── Layout ─────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        p = self.palette
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color=p.sidebar)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        logo = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo.pack(fill="x", padx=22, pady=(28, 20))
        ctk.CTkLabel(logo, text="🛒", font=_font(36)).pack(anchor="w")
        title_label = ctk.CTkLabel(
            logo,
            text="购物机器人",
            font=_font(22, weight="bold"),
            text_color=p.text_primary,
        )
        title_label.pack(anchor="w")
        self._primary_labels.append(title_label)
        subtitle = ctk.CTkLabel(
            logo,
            text="Telegram × Notion × AI",
            text_color=p.text_muted,
            font=_font(12),
        )
        subtitle.pack(anchor="w", pady=(4, 0))
        self._muted_labels.append(subtitle)

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for page_id, label in (
            ("control", "▶  运行控制"),
            ("setup", "⚙  初始设置"),
            ("logs", "📋  运行日志"),
        ):
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                height=44,
                fg_color="transparent",
                hover_color=p.card,
                text_color=p.nav_text,
                font=_font(14),
                command=lambda pid=page_id: self._show_page(pid),
            )
            btn.pack(fill="x", padx=14, pady=4)
            self.nav_buttons[page_id] = btn

        bottom = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=18, pady=18)

        self.theme_btn = ctk.CTkButton(
            bottom,
            text=self._theme_button_text(),
            height=36,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(12),
            command=self._toggle_theme,
        )
        self.theme_btn.pack(fill="x", pady=(0, 12))
        self._secondary_buttons.append(self.theme_btn)

        self.status_dot = ctk.CTkLabel(bottom, text="●", text_color=p.text_muted, font=_font(16))
        self.status_dot.pack(anchor="w")
        self.status_label = ctk.CTkLabel(
            bottom,
            text="检测中…",
            text_color=p.text_muted,
            font=_font(12),
            wraplength=180,
            justify="left",
        )
        self.status_label.pack(anchor="w", pady=(2, 0))
        self._muted_labels.extend([self.status_dot, self.status_label])

    def _build_pages_shell(self) -> None:
        p = self.palette
        self.pages = ctk.CTkFrame(self, fg_color=p.page_bg, corner_radius=0)
        self.pages.grid(row=0, column=1, sticky="nsew")
        self.pages.grid_columnconfigure(0, weight=1)
        self.pages.grid_rowconfigure(0, weight=1)

        self.page_frames: dict[str, ctk.CTkFrame | None] = {
            "control": None,
            "setup": None,
            "logs": None,
        }
        self._loading_label = ctk.CTkLabel(
            self.pages,
            text="加载中…",
            font=_font(16),
            text_color=p.text_muted,
        )
        self._loading_label.place(relx=0.5, rely=0.5, anchor="center")
        self._muted_labels.append(self._loading_label)

    def _dismiss_loading_shell(self) -> None:
        label = getattr(self, "_loading_label", None)
        if label is not None:
            if label in self._muted_labels:
                self._muted_labels.remove(label)
            label.destroy()
            self._loading_label = None

    def _build_initial_pages(self) -> None:
        self._dismiss_loading_shell()
        self.page_frames["control"] = self._build_control_page()
        self._show_page("control")
        self.after_idle(self._build_control_tools)
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        from shopping_bot.gui.launcher import notify_gui_ready

        notify_gui_ready()
        self.after(1, self._bootstrap_deferred)

    def _ensure_setup_page(self) -> None:
        if self._setup_built:
            return
        self._dismiss_loading_shell()
        self.page_frames["setup"] = self._build_setup_page()
        self._setup_built = True
        if self._cached_env is not None:
            self._apply_env_to_fields(self._cached_env)
            self._update_setup_message()
        elif self._current_page == "setup":
            self.load_settings()

    def _ensure_logs_page(self) -> None:
        if self._logs_built:
            return
        self._dismiss_loading_shell()
        self.page_frames["logs"] = self._build_logs_page()
        self._logs_built = True
        if self._current_page == "logs":
            self.refresh_logs()
            self._schedule_log_poll()

    def _card(self, master, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
        p = self.palette
        outer = ctk.CTkFrame(
            master,
            fg_color=p.card,
            corner_radius=16,
            border_width=1,
            border_color=p.card_border,
        )
        self._card_frames.append(outer)
        header = ctk.CTkLabel(
            outer,
            text=title,
            font=_font(16, weight="bold"),
            anchor="w",
            text_color=p.text_primary,
        )
        header.pack(fill="x", padx=22, pady=(18, 8))
        self._primary_labels.append(header)
        body = ctk.CTkFrame(outer, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        body.grid_columnconfigure(0, weight=1)
        return outer, body

    def _build_control_page(self) -> ctk.CTkFrame:
        p = self.palette
        frame = ctk.CTkFrame(self.pages, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 12))
        title = ctk.CTkLabel(
            header,
            text="运行控制",
            font=_font(28, weight="bold"),
            text_color=p.text_primary,
        )
        title.pack(anchor="w")
        self._primary_labels.append(title)
        sub = ctk.CTkLabel(
            header,
            text="启动、停止或重启 Telegram 购物机器人后台进程",
            text_color=p.text_muted,
            font=_font(13),
        )
        sub.pack(anchor="w", pady=(4, 0))
        self._muted_labels.append(sub)

        self._control_scroll = ctk.CTkScrollableFrame(
            frame,
            fg_color=p.page_bg,
            scrollbar_fg_color=p.card,
            scrollbar_button_color=p.btn_secondary,
            scrollbar_button_hover_color=p.btn_secondary_hover,
        )
        self._control_scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 12))
        self._control_scroll.grid_columnconfigure(0, weight=1)

        status_card, card = self._card(self._control_scroll, "机器人状态")
        status_card.pack(fill="x", padx=8, pady=8)

        self.control_status = ctk.CTkLabel(
            card,
            text="正在检测…",
            font=_font(19, weight="bold"),
            anchor="w",
            text_color=p.text_primary,
        )
        self.control_status.grid(row=0, column=0, sticky="w", pady=(0, 6))
        self._primary_labels.append(self.control_status)
        self.control_detail = ctk.CTkLabel(
            card,
            text="",
            text_color=p.text_muted,
            font=_font(13),
            anchor="w",
            justify="left",
        )
        self.control_detail.grid(row=1, column=0, sticky="w", pady=(0, 16))
        self._muted_labels.append(self.control_detail)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew")
        btn_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_start = ctk.CTkButton(
            btn_row,
            text="▶  启动",
            height=48,
            fg_color=p.success,
            hover_color=p.success_hover,
            font=_font(15, weight="bold"),
            command=lambda: self._run_action(self._do_start, busy_text="正在启动机器人…"),
        )
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_stop = ctk.CTkButton(
            btn_row,
            text="■  停止",
            height=48,
            fg_color=p.danger,
            hover_color=p.danger_hover,
            font=_font(15, weight="bold"),
            command=lambda: self._run_action(self._do_stop, busy_text="正在停止机器人…"),
        )
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=8)

        self.btn_restart = ctk.CTkButton(
            btn_row,
            text="↻  重启",
            height=48,
            fg_color=p.accent,
            hover_color=p.accent_hover,
            font=_font(15, weight="bold"),
            command=lambda: self._run_action(self._do_restart, busy_text="正在重启机器人…"),
        )
        self.btn_restart.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        ai_card, ai_body = self._card(self._control_scroll, "AI 模型")
        ai_card.pack(fill="x", padx=8, pady=(8, 0))
        ai_body.grid_columnconfigure(0, weight=1)

        vision_label = ctk.CTkLabel(
            ai_body,
            text="视觉识别模型（可选）",
            anchor="w",
            font=_font(14, weight="bold"),
            text_color=p.text_primary,
        )
        vision_label.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._primary_labels.append(vision_label)

        vision_hint = ctk.CTkLabel(
            ai_body,
            text=f"转发/发送照片时使用，须支持 vision。留空则默认 {DEFAULT_VISION_MODEL}",
            anchor="w",
            text_color=p.text_muted,
            font=_font(12),
            wraplength=720,
            justify="left",
        )
        vision_hint.grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._muted_labels.append(vision_hint)

        vision_row = ctk.CTkFrame(ai_body, fg_color="transparent")
        vision_row.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        vision_row.grid_columnconfigure(0, weight=1)

        self.vision_model_entry = ctk.CTkEntry(
            vision_row,
            height=40,
            font=_font(13),
            border_width=1,
            placeholder_text=DEFAULT_VISION_MODEL,
        )
        self.vision_model_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.btn_save_vision = ctk.CTkButton(
            vision_row,
            text="💾  保存",
            width=100,
            height=40,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(13),
            command=self._save_vision_model,
        )
        self.btn_save_vision.grid(row=0, column=1, sticky="e")
        self._secondary_buttons.append(self.btn_save_vision)
        self._load_vision_model_field()

        self._tools_container = ctk.CTkFrame(self._control_scroll, fg_color="transparent")
        self._tools_container.pack(fill="x")

        self.control_message = ctk.CTkLabel(
            self._control_scroll,
            text="",
            text_color=p.text_muted,
            font=_font(13),
            wraplength=720,
            justify="left",
        )
        self.control_message.pack(fill="x", padx=8, pady=(8, 20))
        self._muted_labels.append(self.control_message)
        self._control_frame = frame
        return frame

    def _build_control_tools(self) -> None:
        if self._tools_built or not self._control_frame:
            return
        p = self.palette

        tutorial_card, tutorial_body = self._card(self._tools_container, "使用教程")
        tutorial_card.pack(fill="x", padx=8, pady=(8, 0))
        self.tutorial_box = ResizableTextbox(
            tutorial_body,
            pref_key="control_tutorial_height",
            default_height=260,
            resize_style="grip_bottom",
            fg_color=p.log_bg,
            border_color=p.card_border,
            border_width=1,
            font=_font(12),
            text_color=p.text_primary,
            activate_scrollbars=True,
        )
        self.tutorial_box.pack(fill="x")
        self.tutorial_box.insert("1.0", BOT_TUTORIAL_ZH)
        self.tutorial_box.configure(state="disabled")

        tools_card, tools = self._card(self._tools_container, "工具")
        tools_card.pack(fill="x", padx=8, pady=8)
        tool_row = ctk.CTkFrame(tools, fg_color="transparent")
        tool_row.pack(fill="x")
        tool_row.grid_columnconfigure((0, 1), weight=1)

        install_btn = ctk.CTkButton(
            tool_row,
            text="📦  安装 / 更新依赖",
            height=42,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(13),
            command=lambda: self._run_action(self._do_install_deps),
        )
        install_btn.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._secondary_buttons.append(install_btn)

        open_btn = ctk.CTkButton(
            tool_row,
            text="📁  打开项目目录",
            height=42,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(13),
            command=self._open_project_dir,
        )
        open_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._secondary_buttons.append(open_btn)
        self._tools_built = True

    def _build_setup_page(self) -> ctk.CTkFrame:
        p = self.palette
        frame = ctk.CTkFrame(self.pages, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        setup_title = ctk.CTkLabel(
            header,
            text="初始设置",
            font=_font(28, weight="bold"),
            text_color=p.text_primary,
        )
        setup_title.pack(anchor="w")
        self._primary_labels.append(setup_title)
        setup_sub = ctk.CTkLabel(
            header,
            text="填写 API 密钥与 Notion 配置，保存后即可启动机器人",
            text_color=p.text_muted,
            font=_font(13),
        )
        setup_sub.pack(anchor="w", pady=(4, 0))
        self._muted_labels.append(setup_sub)

        scroll = ctk.CTkScrollableFrame(
            frame,
            fg_color=p.page_bg,
            scrollbar_fg_color=p.card,
            scrollbar_button_color=p.btn_secondary,
            scrollbar_button_hover_color=p.btn_secondary_hover,
        )
        scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 8))
        scroll.grid_columnconfigure(0, weight=1)
        self._setup_scroll = scroll

        def _add_field_section(
            row: int,
            title: str,
            fields: list[tuple[str, str, bool, bool, str]],
        ) -> int:
            card = ctk.CTkFrame(
                scroll,
                fg_color=p.card,
                corner_radius=16,
                border_width=1,
                border_color=p.card_border,
            )
            card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
            card.grid_columnconfigure(0, weight=1)
            self._section_frames.append(card)
            card_title = ctk.CTkLabel(
                card,
                text=title,
                font=_font(16, weight="bold"),
                anchor="w",
                text_color=p.text_primary,
            )
            card_title.grid(row=0, column=0, sticky="w", padx=22, pady=(18, 8))
            self._primary_labels.append(card_title)
            body = ctk.CTkFrame(card, fg_color="transparent")
            body.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))
            body.grid_columnconfigure(0, weight=1)
            for key, label, required, secret, hint in fields:
                field_row = FieldRow(
                    body,
                    key,
                    label,
                    p,
                    required=required,
                    secret=secret,
                    hint=hint,
                )
                field_row.pack(fill="x")
                self._field_rows[key] = field_row
            return row + 1

        next_row = _add_field_section(0, "基础配置", CORE_SETUP_FIELDS)
        next_row = _add_field_section(next_row, "AI 模型", AI_SETUP_FIELDS)

        self.advanced_frame = ctk.CTkFrame(
            scroll,
            fg_color=p.card,
            corner_radius=16,
            border_width=1,
            border_color=p.card_border,
        )
        self.advanced_frame.grid(row=next_row, column=0, sticky="ew", pady=(0, 12))
        self.advanced_frame.grid_columnconfigure(0, weight=1)
        self._section_frames.append(self.advanced_frame)
        self.advanced_visible = False

        adv_header = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        adv_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
        adv_header.grid_columnconfigure(0, weight=1)
        adv_title = ctk.CTkLabel(
            adv_header,
            text="高级选项",
            font=_font(16, weight="bold"),
            anchor="w",
            text_color=p.text_primary,
        )
        adv_title.grid(row=0, column=0, sticky="w", padx=6)
        self._primary_labels.append(adv_title)
        self.advanced_toggle_btn = ctk.CTkButton(
            adv_header,
            text="展开",
            width=72,
            height=32,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(12),
            command=self._toggle_advanced,
        )
        self.advanced_toggle_btn.grid(row=0, column=1, sticky="e")
        self._secondary_buttons.append(self.advanced_toggle_btn)

        self.advanced_body = ctk.CTkFrame(self.advanced_frame, fg_color="transparent")
        self.advanced_body.grid_columnconfigure(0, weight=1)
        for key, label, required, secret, hint in ADVANCED_FIELDS:
            row = FieldRow(
                self.advanced_body,
                key,
                label,
                p,
                required=required,
                secret=secret,
                hint=hint,
            )
            row.pack(fill="x")
            self._field_rows[key] = row
        self.advanced_body.grid_remove()

        actions = ctk.CTkFrame(scroll, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        actions.grid_columnconfigure((0, 1, 2), weight=1)

        ctk.CTkButton(
            actions,
            text="💾  保存配置",
            height=46,
            fg_color=p.accent,
            hover_color=p.accent_hover,
            text_color="#ffffff",
            font=_font(14, weight="bold"),
            command=self.save_settings,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))

        check_btn = ctk.CTkButton(
            actions,
            text="🔍  测试连接",
            height=46,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(14),
            command=self._start_check,
        )
        check_btn.grid(row=0, column=1, sticky="ew", padx=8)
        self._secondary_buttons.append(check_btn)

        template_btn = ctk.CTkButton(
            actions,
            text="📄  从模板创建 .env",
            height=46,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(14),
            command=self._create_from_example,
        )
        template_btn.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self._secondary_buttons.append(template_btn)

        self.setup_message = ctk.CTkLabel(
            scroll,
            text="",
            text_color=p.text_muted,
            font=_font(13),
            wraplength=720,
            justify="left",
        )
        self.setup_message.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self._muted_labels.append(self.setup_message)

        self.check_output = ctk.CTkTextbox(
            scroll,
            height=120,
            fg_color=p.log_bg,
            border_color=p.card_border,
            border_width=1,
            font=_font(12),
            text_color=p.text_primary,
        )
        self.check_output.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.check_output.configure(state="disabled")
        self.check_output.grid_remove()
        self._check_output_visible = False

        self._setup_guide_footer = ctk.CTkFrame(frame, fg_color="transparent")
        self._setup_guide_footer.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 16))

        self._setup_guide_btn = ctk.CTkButton(
            self._setup_guide_footer,
            text="📖  查看配置教程",
            height=42,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(13),
            command=self._toggle_setup_guide,
        )
        self._setup_guide_btn.pack(fill="x", pady=(0, 8))
        self._secondary_buttons.append(self._setup_guide_btn)

        self._setup_guide_container = ctk.CTkFrame(
            self._setup_guide_footer,
            fg_color=p.card,
            corner_radius=16,
            border_width=1,
            border_color=p.card_border,
        )
        self._setup_guide_container.pack_forget()
        self._setup_guide_container.grid_columnconfigure(0, weight=1)
        self._section_frames.append(self._setup_guide_container)

        guide_title = ctk.CTkLabel(
            self._setup_guide_container,
            text="配置教程",
            font=_font(16, weight="bold"),
            anchor="w",
            text_color=p.text_primary,
        )
        guide_title.grid(row=0, column=0, sticky="w", padx=22, pady=(18, 8))
        self._primary_labels.append(guide_title)

        guide_body = ctk.CTkFrame(self._setup_guide_container, fg_color="transparent")
        guide_body.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))
        guide_body.grid_columnconfigure(0, weight=1)

        self.setup_guide = ResizableTextbox(
            guide_body,
            pref_key="setup_guide_height",
            default_height=220,
            min_height=120,
            max_height=360,
            resize_style="slider",
            fg_color=p.log_bg,
            border_color=p.card_border,
            border_width=1,
            font=_font(12),
            text_color=p.text_primary,
            activate_scrollbars=True,
        )
        self.setup_guide.pack(fill="x")
        self.setup_guide.insert("1.0", SETUP_GUIDE_ZH)
        self.setup_guide.configure(state="disabled")
        self._setup_guide_visible = False
        return frame

    def _build_logs_page(self) -> ctk.CTkFrame:
        p = self.palette
        frame = ctk.CTkFrame(self.pages, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        header.grid_columnconfigure(0, weight=1)
        log_title = ctk.CTkLabel(
            header,
            text="运行日志",
            font=_font(28, weight="bold"),
            text_color=p.text_primary,
        )
        log_title.grid(row=0, column=0, sticky="w")
        self._primary_labels.append(log_title)
        log_sub = ctk.CTkLabel(
            header,
            text="logs/bot.log",
            text_color=p.text_muted,
            font=_font(13),
        )
        log_sub.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._muted_labels.append(log_sub)

        btn_row = ctk.CTkFrame(header, fg_color="transparent")
        btn_row.grid(row=0, column=1, rowspan=2, sticky="e")
        self.auto_log_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(btn_row, text="自动刷新", variable=self.auto_log_var, font=_font(12)).pack(
            side="left", padx=(0, 10)
        )
        refresh_btn = ctk.CTkButton(
            btn_row,
            text="刷新",
            width=76,
            height=36,
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
            font=_font(12),
            command=self.refresh_logs,
        )
        refresh_btn.pack(side="left")
        self._secondary_buttons.append(refresh_btn)

        self.log_box = ctk.CTkTextbox(
            frame,
            fg_color=p.log_bg,
            border_color=p.card_border,
            border_width=1,
            font=_font(12),
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=28, pady=(8, 24))
        return frame

    # ── Navigation ───────────────────────────────────────────────────────────

    def _show_page(self, page_id: str) -> None:
        p = self.palette

        if page_id == "setup":
            self._ensure_setup_page()
        elif page_id == "logs":
            self._ensure_logs_page()
        elif page_id == "control" and self.page_frames["control"] is None:
            return

        self._current_page = page_id

        for pid, frame in self.page_frames.items():
            if frame is None:
                continue
            if pid == page_id:
                frame.grid(row=0, column=0, sticky="nsew")
            else:
                frame.grid_remove()

        for pid, btn in self.nav_buttons.items():
            if pid == page_id:
                btn.configure(
                    fg_color=p.accent,
                    hover_color=p.accent_hover,
                    text_color="#ffffff",
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    hover_color=p.card,
                    text_color=p.nav_text,
                )

        if page_id == "logs" and self._logs_built:
            self.refresh_logs()
            self._schedule_log_poll()
        else:
            self._cancel_log_poll()

    def _theme_button_text(self) -> str:
        return "🌙  切换深色" if self._theme_name == "light" else "☀  切换浅色"

    def _toggle_theme(self) -> None:
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        self.palette = PALETTES[self._theme_name]
        ctk.set_appearance_mode(self.palette.appearance)
        set_theme(self._theme_name)
        self.theme_btn.configure(text=self._theme_button_text())
        self._apply_theme()
        self._show_page(self._current_page)

    def _apply_theme(self) -> None:
        p = self.palette
        self.configure(fg_color=p.page_bg)
        self.sidebar.configure(fg_color=p.sidebar)
        self.pages.configure(fg_color=p.page_bg)
        self.theme_btn.configure(
            fg_color=p.btn_secondary,
            hover_color=p.btn_secondary_hover,
            text_color=p.btn_secondary_text,
        )

        for frame in self._card_frames:
            frame.configure(fg_color=p.card, border_color=p.card_border)
        for frame in self._section_frames:
            frame.configure(fg_color=p.card, border_color=p.card_border)

        for label in self._primary_labels:
            if label is not self.control_status:
                label.configure(text_color=p.text_primary)

        for label in self._muted_labels:
            if label is not self.status_dot:
                label.configure(text_color=p.text_muted)

        for row in self._field_rows.values():
            row.apply_theme(p)

        for btn in self._secondary_buttons:
            btn.configure(
                fg_color=p.btn_secondary,
                hover_color=p.btn_secondary_hover,
                text_color=p.btn_secondary_text,
            )

        self.btn_start.configure(
            fg_color=p.success,
            hover_color=p.success_hover,
            text_color="#ffffff",
        )
        self.btn_stop.configure(
            fg_color=p.danger,
            hover_color=p.danger_hover,
            text_color="#ffffff",
        )
        self.btn_restart.configure(
            fg_color=p.accent,
            hover_color=p.accent_hover,
            text_color="#ffffff",
        )

        if hasattr(self, "check_output"):
            self.check_output.configure(
                fg_color=p.log_bg,
                border_color=p.card_border,
                text_color=p.text_primary,
            )
        if hasattr(self, "log_box"):
            self.log_box.configure(
                fg_color=p.log_bg,
                border_color=p.card_border,
                text_color=p.text_primary,
            )
        if hasattr(self, "tutorial_box"):
            self.tutorial_box.apply_theme(
                p,
                fg_color=p.log_bg,
                border_color=p.card_border,
                text_color=p.text_primary,
            )
        if hasattr(self, "_control_scroll"):
            self._control_scroll.configure(
                fg_color=p.page_bg,
                scrollbar_fg_color=p.card,
                scrollbar_button_color=p.btn_secondary,
                scrollbar_button_hover_color=p.btn_secondary_hover,
            )
        if hasattr(self, "vision_model_entry"):
            self.vision_model_entry.configure(
                border_color=p.card_border,
                text_color=p.text_primary,
            )
        if hasattr(self, "_setup_scroll"):
            self._setup_scroll.configure(
                fg_color=p.page_bg,
                scrollbar_fg_color=p.card,
                scrollbar_button_color=p.btn_secondary,
                scrollbar_button_hover_color=p.btn_secondary_hover,
            )
        if hasattr(self, "setup_guide"):
            self.setup_guide.apply_theme(
                p,
                fg_color=p.log_bg,
                border_color=p.card_border,
                text_color=p.text_primary,
            )
        self._refresh_status_async(force=True)

    def _toggle_setup_guide(self) -> None:
        if not self._setup_built:
            self._ensure_setup_page()
        self._setup_guide_visible = not self._setup_guide_visible
        if self._setup_guide_visible:
            self._setup_guide_container.pack(fill="x")
            self._setup_guide_btn.configure(text="📖  收起配置教程")
        else:
            self._setup_guide_container.pack_forget()
            self._setup_guide_btn.configure(text="📖  查看配置教程")

    def _toggle_advanced(self) -> None:
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced_body.grid(row=1, column=0, sticky="ew", padx=22, pady=(0, 18))
            self.advanced_toggle_btn.configure(text="收起")
        else:
            self.advanced_body.grid_remove()
            self.advanced_toggle_btn.configure(text="展开")

    # ── Settings ─────────────────────────────────────────────────────────────

    def load_settings(self) -> None:
        values = load_merged_env()
        self._cached_env = values
        if self._setup_built:
            self._apply_env_to_fields(values)
            self._update_setup_message()
        self._load_vision_model_field(values)

    def _load_vision_model_field(self, values: dict[str, str] | None = None) -> None:
        if not hasattr(self, "vision_model_entry"):
            return
        merged = values if values is not None else load_merged_env()
        model = merged.get("OPENROUTER_VISION_MODEL", "").strip() or DEFAULT_VISION_MODEL
        self.vision_model_entry.delete(0, "end")
        self.vision_model_entry.insert(0, model)

    def _save_vision_model(self) -> None:
        model = self.vision_model_entry.get().strip() or DEFAULT_VISION_MODEL
        try:
            path = patch_env({"OPENROUTER_VISION_MODEL": model})
        except OSError as exc:
            self.control_message.configure(
                text=f"保存失败: {exc}",
                text_color=self.palette.danger,
            )
            return
        if self._cached_env is not None:
            self._cached_env["OPENROUTER_VISION_MODEL"] = model
        if self._setup_built and "OPENROUTER_VISION_MODEL" in self._field_rows:
            self._field_rows["OPENROUTER_VISION_MODEL"].set(model)
        self.control_message.configure(
            text=f"视觉模型已保存到 {path}，修改后请重启机器人生效。",
            text_color=self.palette.success,
        )

    def save_settings(self) -> None:
        if not self._setup_built:
            self._ensure_setup_page()
        values = {key: row.get() for key, row in self._field_rows.items()}
        missing = missing_required_fields(values)
        if missing:
            self.setup_message.configure(
                text=f"请先填写必填项：{', '.join(missing)}",
                text_color=self.palette.warn,
            )
            return
        path = save_env(values)
        self._cached_env = values
        self.setup_message.configure(text=f"配置已保存到 {path}", text_color=self.palette.success)

    def _create_from_example(self) -> None:
        if not self._setup_built:
            self._ensure_setup_page()
        try:
            path = create_env_from_example()
        except FileNotFoundError as exc:
            self.setup_message.configure(text=str(exc), text_color=self.palette.danger)
            return
        self.load_settings()
        self.setup_message.configure(
            text=f"已从模板创建 {path}，请填写密钥后保存。",
            text_color=self.palette.accent,
        )

    # ── Bot control ──────────────────────────────────────────────────────────

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self.btn_start, self.btn_stop, self.btn_restart):
            btn.configure(state=state)
        if not busy:
            self._update_control_buttons()

    def _update_control_buttons(self) -> None:
        if self._busy:
            return
        status = self._last_status or _pm().get_bot_status()
        if status.running:
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_restart.configure(state="normal")
        else:
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.btn_restart.configure(state="normal")

    def _run_action(
        self,
        func: Callable[[], tuple[bool, str]],
        *,
        busy_text: str = "",
    ) -> None:
        if self._busy:
            return
        if busy_text:
            self.control_message.configure(text=busy_text, text_color=self.palette.accent)
        self._set_busy(True)

        def worker() -> None:
            try:
                ok, message = func()
            except Exception as exc:  # noqa: BLE001
                ok, message = False, str(exc)
            self.after(0, lambda: self._finish_action(ok, message))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_action(self, ok: bool, message: str) -> None:
        self._set_busy(False)
        color = self.palette.success if ok else self.palette.danger
        if self._current_page == "control":
            self.control_message.configure(text=message, text_color=color)
        elif self._current_page == "setup":
            self.setup_message.configure(text=message, text_color=color)
        _pm().invalidate_process_cache()
        self._refresh_status_async(force=True)
        if self._current_page == "logs" and self._logs_built:
            self.refresh_logs()

    def _do_start(self) -> tuple[bool, str]:
        return _pm().start_bot()

    def _do_stop(self) -> tuple[bool, str]:
        return _pm().stop_bot()

    def _do_restart(self) -> tuple[bool, str]:
        return _pm().restart_bot()

    def _do_install_deps(self) -> tuple[bool, str]:
        return _pm().ensure_dependencies()

    def _start_check(self) -> None:
        if not self._setup_built:
            self._ensure_setup_page()
        values = {key: row.get() for key, row in self._field_rows.items()}
        missing = missing_required_fields(values)
        if missing:
            self.setup_message.configure(
                text=f"请先填写必填项：{', '.join(missing)}",
                text_color=self.palette.warn,
            )
            return
        save_env(values)
        self._run_action(self._do_check)

    def _do_check(self) -> tuple[bool, str]:
        from shopping_bot.gui.check_runner import run_setup_checks

        ok, output = run_setup_checks()
        self.after(0, lambda: self._show_check_output(output, ok))
        return ok, "连接测试完成，请查看下方结果。"

    def _show_check_output(self, output: str, ok: bool) -> None:
        if not self._check_output_visible:
            self.check_output.grid()
            self._check_output_visible = True
        self.check_output.configure(state="normal")
        self.check_output.delete("1.0", "end")
        self.check_output.insert("1.0", output)
        self.check_output.configure(state="disabled")
        self.setup_message.configure(
            text="全部检查通过 ✓" if ok else "部分检查未通过，请根据下方日志修复。",
            text_color=self.palette.success if ok else self.palette.danger,
        )

    def _apply_status(self, status) -> None:
        self._last_status = status
        p = self.palette
        if status.running:
            self.status_dot.configure(text_color=p.success)
            self.status_label.configure(text=f"运行中 · PID {', '.join(map(str, status.pids))}")
            self.control_status.configure(text="●  机器人运行中", text_color=p.success)
            self.control_detail.configure(
                text=f"检测到 {status.count} 个进程\nPID: {', '.join(map(str, status.pids))}"
            )
        else:
            self.status_dot.configure(text_color=p.text_muted)
            self.status_label.configure(text="已停止")
            self.control_status.configure(text="○  机器人已停止", text_color=p.text_primary)
            self.control_detail.configure(text="点击「启动」在后台运行机器人")
        self._update_control_buttons()

    def _refresh_status_async(self, *, force: bool = False) -> None:
        def worker() -> None:
            pm = _pm()
            if force:
                pm.invalidate_process_cache()
            status = pm.get_bot_status()
            self.after(0, lambda s=status: self._apply_status(s))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_status(self) -> None:
        self._refresh_status_async(force=True)

    def _schedule_status_poll(self) -> None:
        self._refresh_status_async()
        self._status_job = self.after(4000, self._schedule_status_poll)

    def refresh_logs(self) -> None:
        text = _pm().read_log_tail()
        self.log_box.delete("1.0", "end")
        self.log_box.insert("1.0", text)
        self.log_box.see("end")

    def _schedule_log_poll(self) -> None:
        if self.auto_log_var.get() and self._current_page == "logs":
            self.refresh_logs()
        self._log_job = self.after(2000, self._schedule_log_poll)

    def _cancel_log_poll(self) -> None:
        if self._log_job:
            self.after_cancel(self._log_job)
            self._log_job = None

    def _open_project_dir(self) -> None:
        path = project_root()
        import os
        import subprocess
        import sys

        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)

    def _on_close(self) -> None:
        if self._status_job:
            self.after_cancel(self._status_job)
        self._cancel_log_poll()
        self.destroy()


def main() -> None:
    from shopping_bot.gui.launcher import run

    run()


if __name__ == "__main__":
    main()
