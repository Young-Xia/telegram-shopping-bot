"""Textbox with user-adjustable height (drag grip or slider)."""

from __future__ import annotations

from typing import Literal

import customtkinter as ctk

from shopping_bot.gui.gui_prefs import get_height, set_height
from shopping_bot.gui.themes import ThemePalette

ResizeStyle = Literal["grip_bottom", "grip_top", "slider"]


class ResizableTextbox(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        pref_key: str,
        default_height: int = 260,
        min_height: int = 120,
        max_height: int = 720,
        resize_style: ResizeStyle = "grip_bottom",
        font=None,
        **textbox_kwargs,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._pref_key = pref_key
        self._min_height = min_height
        self._max_height = max_height
        self._resize_style = resize_style
        self._height = get_height(pref_key, default_height)
        self._drag_start_y = 0
        self._drag_start_height = self._height
        self._slider: ctk.CTkSlider | None = None
        self._height_label: ctk.CTkLabel | None = None
        self._grip: ctk.CTkFrame | None = None
        self._grip_label: ctk.CTkLabel | None = None

        if resize_style == "slider":
            self._build_slider_header(font)
            self.textbox = ctk.CTkTextbox(
                self,
                height=self._height,
                font=font,
                **textbox_kwargs,
            )
            self.textbox.pack(fill="x")
            return

        if resize_style == "grip_top":
            self._build_grip(font, label="⋮⋮  向下拖动扩大 · 向上拖动缩小")
            self.textbox = ctk.CTkTextbox(
                self,
                height=self._height,
                font=font,
                **textbox_kwargs,
            )
            self.textbox.pack(fill="x")
            return

        self.textbox = ctk.CTkTextbox(
            self,
            height=self._height,
            font=font,
            **textbox_kwargs,
        )
        self.textbox.pack(fill="x")
        self._build_grip(font, label="⋮⋮  向下拖动扩大 · 向上拖动缩小")

    def _build_slider_header(self, font) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", pady=(0, 8))
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="显示高度",
            font=font,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        self._slider = ctk.CTkSlider(
            header,
            from_=self._min_height,
            to=self._max_height,
            number_of_steps=(self._max_height - self._min_height) // 10,
            command=self._on_slider,
        )
        self._slider.set(self._height)
        self._slider.grid(row=0, column=1, sticky="ew")

        self._height_label = ctk.CTkLabel(
            header,
            text=f"{self._height}px",
            width=52,
            anchor="e",
            font=font,
        )
        self._height_label.grid(row=0, column=2, sticky="e", padx=(10, 0))
        self._slider.bind("<ButtonRelease-1>", self._save_height)

    def _build_grip(self, font, *, label: str) -> None:
        self._grip = ctk.CTkFrame(self, height=14, corner_radius=4, cursor="sb_v_double_arrow")
        if self._resize_style == "grip_top":
            self._grip.pack(fill="x", pady=(0, 6))
        else:
            self._grip.pack(fill="x", pady=(6, 0))

        self._grip_label = ctk.CTkLabel(
            self._grip,
            text=label,
            height=14,
            font=font,
            cursor="sb_v_double_arrow",
        )
        self._grip_label.pack(fill="x")
        for widget in (self._grip, self._grip_label):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._end_drag)

    def _on_slider(self, value: float) -> None:
        new_height = int(max(self._min_height, min(self._max_height, round(value))))
        if new_height == self._height:
            return
        self._height = new_height
        self.textbox.configure(height=new_height)
        if self._height_label is not None:
            self._height_label.configure(text=f"{new_height}px")

    def _save_height(self, _event=None) -> None:
        set_height(self._pref_key, self._height)

    def _start_drag(self, event) -> None:
        self._drag_start_y = event.y_root
        self._drag_start_height = self._height

    def _on_drag(self, event) -> None:
        delta = event.y_root - self._drag_start_y
        new_height = int(
            max(self._min_height, min(self._max_height, self._drag_start_height + delta))
        )
        if new_height == self._height:
            return
        self._height = new_height
        self.textbox.configure(height=new_height)

    def _end_drag(self, _event) -> None:
        set_height(self._pref_key, self._height)

    def apply_theme(self, palette: ThemePalette, **textbox_kwargs) -> None:
        self.textbox.configure(**textbox_kwargs)
        if self._grip is not None:
            self._grip.configure(fg_color=palette.btn_secondary)
        if self._grip_label is not None:
            self._grip_label.configure(
                text_color=palette.text_muted,
                fg_color=palette.btn_secondary,
            )
        if self._slider is not None:
            self._slider.configure(
                progress_color=palette.accent,
                button_color=palette.accent,
                button_hover_color=palette.accent_hover,
                fg_color=palette.card_border,
            )
        if self._height_label is not None:
            self._height_label.configure(text_color=palette.text_muted)

    def insert(self, index: str, text: str) -> None:
        self.textbox.insert(index, text)

    def configure(self, **kwargs) -> None:
        self.textbox.configure(**kwargs)

    def grid_remove(self) -> None:
        super().grid_remove()

    def grid(self, **kwargs) -> None:
        super().grid(**kwargs)

    def pack(self, **kwargs) -> None:
        super().pack(**kwargs)

    def pack_forget(self) -> None:
        super().pack_forget()
