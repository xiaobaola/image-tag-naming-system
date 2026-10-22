# -*- coding: utf-8 -*-
"""中心大图预览面板（单击查看）。

交互：
* 单击右侧仓库 / 中间分组里的图片标签 -> 在本面板显示这张图（等比缩放、居中、留白）
* 单击左侧文件树里的图片文件 -> 同样在这里显示
* 双击标签仍打开独立的可缩放预览窗；本面板也提供【打开大窗】
* 面板可收起 / 展开；收起状态下单击图片会自动展开

性能：
* 同一张图只解码一次（按 路径 + mtime 缓存原图句柄），窗口缩放时只重新缩放渲染；
* 面板尺寸变化做了防抖（120ms），避免拖动窗口时疯狂重绘。
"""
from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import ttk
from typing import Optional

import config
import image_utils
from config import (
    C_BORDER, C_MISSING_TEXT, C_PANEL, C_PANEL_ALT, C_TEXT, C_TEXT_SUB,
    FONT_BOLD, FONT_SMALL,
)

LOG = logging.getLogger("center_preview")

PAD = 10                 # 图片四周留白
RESIZE_DEBOUNCE_MS = 120  # 尺寸变化防抖
COLLAPSED_HEIGHT = 46     # 收起后只保留标题栏


class CenterPreviewPanel(tk.Frame):
    """中心预览面板：单击标签 / 文件树图片，在这里看大图。"""

    def __init__(self, master, app):
        super().__init__(
            master, bg=C_PANEL, height=config.CENTER_PREVIEW_H,
            highlightbackground=C_BORDER, highlightthickness=2,
        )
        self.app = app

        # 当前展示的图片与元数据
        self._path = ""
        self._title = ""
        self._tag_id: Optional[str] = None
        self._handle: Optional[dict] = None
        self._handle_key = None
        self._photo = None            # 必须保留引用，否则图片会被回收
        self._collapsed = False
        self._resize_job = None

        self.title_var = tk.StringVar(value="")

        # 高度由自己控制（内部用 pack 放子控件，必须禁用传播）
        self.pack_propagate(False)
        self.grid_propagate(False)

        self._build()

    # ==================================================================
    # 构建
    # ==================================================================
    def _build(self) -> None:
        header = tk.Frame(self, bg=C_PANEL)
        header.pack(fill="x", padx=10, pady=(5, 3))

        tk.Label(
            header, text="图片预览", font=FONT_BOLD, bg=C_PANEL, fg=C_TEXT,
        ).pack(side="left")
        tk.Label(
            header, textvariable=self.title_var, font=FONT_SMALL,
            bg=C_PANEL, fg=C_TEXT_SUB, anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=10)

        self.collapse_btn = ttk.Button(
            header, text="收起", style="Small.TButton", command=self.toggle,
        )
        self.collapse_btn.pack(side="right")
        self.window_btn = ttk.Button(
            header, text="打开大窗", style="Small.TButton", command=self.open_window,
        )
        self.window_btn.pack(side="right", padx=6)

        self.canvas = tk.Canvas(self, bg=C_PANEL_ALT, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 7))
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Double-Button-1>", lambda e: self.open_window())

        self._update_title()

    # ==================================================================
    # 对外：显示图片
    # ==================================================================
    def show_tag(self, tag_id: str) -> None:
        """按标签显示图片（仓库 / 分组单击时调用）。"""
        tag = self.app.data.get_tag(tag_id)
        if not tag:
            LOG.warning("中心预览失败，标签不存在: %s", tag_id)
            return
        path = tag.get("img_path", "")
        remark = (tag.get("remark") or "").strip()
        title = remark or os.path.splitext(os.path.basename(path))[0]
        self.show_path(path, title=title, source=f"标签 {tag_id}", tag_id=tag_id)

    def show_path(self, path: str, title: str = "",
                  source: str = "图片", tag_id: Optional[str] = None) -> None:
        """显示指定路径的图片（文件树单击时调用）。"""
        if not path:
            return
        path = os.path.normpath(os.path.abspath(path))
        if self._collapsed:
            self.set_collapsed(False)

        if os.path.normcase(path) != os.path.normcase(self._path):
            # 换图：丢弃旧的原图句柄
            self._handle = None
            self._handle_key = None
            self._photo = None

        self._path = path
        self._title = (title or "").strip()
        self._tag_id = tag_id
        LOG.info("中心预览(%s): %s", source, path)
        self._update_title()
        self._render()

    def refresh_meta(self) -> None:
        """备注等元数据变化后刷新标题（不重新解码图片）。"""
        if not self._tag_id:
            return
        tag = self.app.data.get_tag(self._tag_id)
        if not tag:
            return
        remark = (tag.get("remark") or "").strip()
        path = tag.get("img_path", "")
        self._title = remark or os.path.splitext(os.path.basename(path))[0]
        self._update_title()

    def remap_path(self, old: str, new: str) -> None:
        """一键重命名后同步路径，避免预览指向已被改名的文件。"""
        if not self._path or not old or not new:
            return
        if os.path.normcase(os.path.abspath(self._path)) != os.path.normcase(os.path.abspath(old)):
            return
        self._path = os.path.normpath(os.path.abspath(new))
        self._handle = None
        self._handle_key = None
        self._photo = None
        LOG.info("中心预览路径同步: %s", self._path)
        self._render()

    def clear(self) -> None:
        self._path = ""
        self._title = ""
        self._tag_id = None
        self._handle = None
        self._handle_key = None
        self._photo = None
        self._update_title()
        self._render()

    # ==================================================================
    # 对外：收起 / 大窗
    # ==================================================================
    def toggle(self) -> None:
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        try:
            if collapsed:
                self.canvas.pack_forget()
                self.configure(height=COLLAPSED_HEIGHT)
                self.collapse_btn.configure(text="展开")
            else:
                self.canvas.pack(fill="both", expand=True, padx=8, pady=(0, 7))
                self.configure(height=config.CENTER_PREVIEW_H)
                self.collapse_btn.configure(text="收起")
        except tk.TclError:
            return
        self._update_title()
        if not collapsed:
            self.after(20, self._render)
        LOG.info("中心预览面板%s", "收起" if collapsed else "展开")

    def open_window(self) -> None:
        """在独立预览窗中打开当前图片（滚轮缩放 / 拖动平移）。"""
        if not self._path:
            self.app.set_status("还没有选中图片：先单击标签或文件树里的图片")
            return
        if not os.path.isfile(self._path):
            self.app.set_status("图片不存在，无法打开大窗")
            return
        self.app.preview_path(self._path)

    # ==================================================================
    # 渲染
    # ==================================================================
    def _on_resize(self, _event=None) -> None:
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except tk.TclError:
                pass
        self._resize_job = self.after(RESIZE_DEBOUNCE_MS, self._render)

    def _render(self) -> None:
        self._resize_job = None
        try:
            self.canvas.delete("all")
            self._photo = None
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            if w <= 20 or h <= 20:  # 尚未完成布局
                return

            if not self._path:
                self._draw_message(
                    "单击任意图片标签，在这里查看图片",
                    "仓库 / 分组 / 文件树都可以；双击标签打开独立预览窗",
                )
                return

            if not os.path.isfile(self._path):
                self._draw_message("图片不存在", self._short_path(self._path), C_MISSING_TEXT)
                self._update_title()
                return

            handle = self._ensure_handle()
            if handle is None:
                self._draw_message("图片无法解码", self._short_path(self._path), C_MISSING_TEXT)
                self._update_title()
                return

            iw, ih = handle["size"]
            avail_w = max(w - PAD * 2, 1)
            avail_h = max(h - PAD * 2, 1)
            # 等比适应；小图最多放大 2 倍，避免糊成一团
            scale = min(avail_w / iw, avail_h / ih, config.CENTER_PREVIEW_MAX_UPSCALE)
            photo, applied = image_utils.render(handle, scale)
            if photo is None:
                self._draw_message("图片渲染失败", self._short_path(self._path), C_MISSING_TEXT)
                return

            self._photo = photo
            pw, ph = photo.width(), photo.height()
            cx, cy = w / 2, h / 2
            self.canvas.create_rectangle(
                cx - pw / 2 - 1, cy - ph / 2 - 1,
                cx + pw / 2 + 1, cy + ph / 2 + 1,
                outline=C_BORDER,
            )
            self.canvas.create_image(cx, cy, image=photo)
            self._update_title()
            LOG.debug("中心预览渲染: %sx%s -> %sx%s (scale=%.3f)", iw, ih, pw, ph, applied)
        except tk.TclError:
            pass

    def _draw_message(self, text: str, sub: str = "", color: str = C_TEXT_SUB) -> None:
        w = max(self.canvas.winfo_width(), 60)
        h = max(self.canvas.winfo_height(), 50)
        self.canvas.create_rectangle(8, 8, w - 8, h - 8, outline=C_BORDER, dash=(4, 3))
        self.canvas.create_text(w / 2, h / 2 - 10, text=text, font=FONT_BOLD, fill=color)
        if sub:
            self.canvas.create_text(
                w / 2, h / 2 + 14, text=sub, font=FONT_SMALL,
                fill=C_TEXT_SUB, width=max(w - 40, 60), justify="center",
            )

    def _ensure_handle(self) -> Optional[dict]:
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            mtime = 0.0
        key = (os.path.normcase(self._path), mtime)
        if key == self._handle_key:
            return self._handle
        self._handle_key = key
        self._handle = image_utils.load_full(
            self._path, max_side=config.CENTER_PREVIEW_MAX_SIDE,
        )
        if self._handle is None:
            LOG.warning("中心预览无法加载图片: %s", self._path)
        return self._handle

    # ==================================================================
    # 文案
    # ==================================================================
    def _update_title(self) -> None:
        try:
            if self._collapsed:
                self.title_var.set("已收起 · 单击图片自动展开")
                return
            if not self._path:
                self.title_var.set("单击标签或文件树里的图片即可预览")
                return

            name = os.path.basename(self._path)
            stem = os.path.splitext(name)[0]
            text = f"{self._title}  ·  {name}" if self._title and self._title != stem else name
            if self._handle:
                iw, ih = self._handle["size"]
                text += f"  ·  {iw}×{ih}"
            if not os.path.isfile(self._path):
                text += "  ·  图片不存在"
            if len(text) > 76:
                text = text[:74] + "…"
            self.title_var.set(text)
        except tk.TclError:
            pass

    @staticmethod
    def _short_path(path: str) -> str:
        text = str(path or "")
        return text if len(text) <= 86 else "…" + text[-84:]
