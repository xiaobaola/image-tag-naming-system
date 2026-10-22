# -*- coding: utf-8 -*-
"""独立图片预览窗口。

* 打开时按窗口大小自适应缩放（小图不放大）
* 鼠标滚轮缩放（以光标位置为中心）
* 按住左键拖动平移
* 工具条：适应窗口 / 1:1 / 放大 / 缩小 / 关闭；ESC 关闭
"""
from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import ttk

import image_utils
from config import (
    FONT_BOLD, FONT_SMALL, PREVIEW_H, PREVIEW_MAX_SCALE,
    PREVIEW_MIN_SCALE, PREVIEW_W,
)

LOG = logging.getLogger("preview")

BG_WINDOW = "#1f2430"
BG_CANVAS = "#151a22"
FG_INFO = "#dbe3f0"


class ImagePreviewWindow(tk.Toplevel):
    """图片预览窗口（每个标签可独立打开多个）。"""

    def __init__(self, master, img_path: str, title: str = ""):
        super().__init__(master)
        self.img_path = img_path
        self.handle = None
        self.scale = 1.0
        self.offset = [0.0, 0.0]
        self._photo = None
        self._render_scale = -1.0
        self._need_fit = True
        self._drag_origin = None
        self._canvas_size = (1, 1)

        name = title or os.path.basename(img_path) or "图片"
        self.title(f"图片预览 - {name}")
        self.configure(bg=BG_WINDOW)
        self.minsize(480, 360)
        self.geometry(f"{PREVIEW_W}x{PREVIEW_H}")
        self.transient(master.winfo_toplevel())

        self._build_ui()
        self._load()

    # ======================================================================
    # UI
    # ======================================================================
    def _build_ui(self) -> None:
        bar = tk.Frame(self, bg="#2b3342")
        bar.pack(fill="x")

        tk.Label(
            bar, text=os.path.basename(self.img_path), font=FONT_BOLD,
            bg="#2b3342", fg=FG_INFO, anchor="w", padx=10, pady=8,
        ).pack(side="left")

        ttk.Button(bar, text="关闭", style="Small.TButton", command=self.destroy).pack(
            side="right", padx=(4, 10), pady=5)
        ttk.Button(bar, text="放大", style="Small.TButton",
                   command=lambda: self.zoom_at_center(1.25)).pack(side="right", padx=4, pady=5)
        ttk.Button(bar, text="缩小", style="Small.TButton",
                   command=lambda: self.zoom_at_center(1 / 1.25)).pack(side="right", padx=4, pady=5)
        ttk.Button(bar, text="1:1", style="Small.TButton",
                   command=self.reset_zoom).pack(side="right", padx=4, pady=5)
        ttk.Button(bar, text="适应窗口", style="Small.TButton",
                   command=self.fit_to_window).pack(side="right", padx=4, pady=5)

        self.canvas = tk.Canvas(self, bg=BG_CANVAS, highlightthickness=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)

        self.status = tk.StringVar(value="滚轮缩放 / 拖动平移 / ESC 关闭")
        tk.Label(
            self, textvariable=self.status, font=FONT_SMALL,
            bg=BG_WINDOW, fg=FG_INFO, anchor="w", padx=10, pady=6,
        ).pack(fill="x")

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind("<Escape>", lambda e: self.destroy())

    # ======================================================================
    # 加载
    # ======================================================================
    def _load(self) -> None:
        if not os.path.isfile(self.img_path):
            LOG.warning("预览图片不存在: %s", self.img_path)
            self.canvas.create_text(
                20, 20, anchor="nw", fill="#ff8a80", font=FONT_BOLD,
                text=f"图片不存在：\n{self.img_path}",
            )
            self.status.set("图片不存在，无法预览")
            return

        self.handle = image_utils.load_full(self.img_path)
        if self.handle is None:
            LOG.error("预览加载失败: %s", self.img_path)
            self.canvas.create_text(
                20, 20, anchor="nw", fill="#ff8a80", font=FONT_BOLD,
                text=f"无法读取图片（格式不支持或文件损坏）：\n{self.img_path}",
            )
            self.status.set("无法读取图片")
            return

        iw, ih = self.handle["size"]
        LOG.info("预览窗口打开: %s (%sx%s)", self.img_path, iw, ih)
        self._need_fit = True
        self.after(30, self.fit_to_window)

    # ======================================================================
    # 缩放 / 平移
    # ======================================================================
    def _on_canvas_configure(self, event) -> None:
        self._canvas_size = (max(event.width, 1), max(event.height, 1))
        if self._need_fit:
            self._need_fit = False
            self.fit_to_window()

    def fit_to_window(self) -> None:
        if not self.handle or not self.winfo_exists():
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            self.after(50, self.fit_to_window)
            return
        iw, ih = self.handle["size"]
        scale = min((cw - 24) / iw, (ch - 24) / ih)
        self.scale = max(PREVIEW_MIN_SCALE, min(scale, 1.0))  # 小图不放大
        self.offset = [cw / 2, ch / 2]
        LOG.debug("适应窗口: 画布 %sx%s, 比例 %.3f", cw, ch, self.scale)
        self.render(force=True)

    def reset_zoom(self) -> None:
        if not self.handle:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self.scale = 1.0
        self.offset = [cw / 2, ch / 2]
        self.render(force=True)
        LOG.debug("1:1 显示")

    def zoom_at_center(self, factor: float) -> None:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self._zoom(cw / 2, ch / 2, factor)

    def _on_wheel(self, event):
        if not self.handle:
            return "break"
        factor = 1.15 if event.delta > 0 else 1 / 1.15
        self._zoom(event.x, event.y, factor)
        return "break"

    def _zoom(self, mx: float, my: float, factor: float) -> None:
        if not self.handle:
            return
        old = self.scale
        new = max(PREVIEW_MIN_SCALE, min(old * factor, PREVIEW_MAX_SCALE))
        if abs(new - old) < 1e-6:
            return
        # 保持光标下的图像点不动
        ox, oy = self.offset
        ix = (mx - ox) / old
        iy = (my - oy) / old
        self.scale = new
        self.offset = [mx - ix * new, my - iy * new]
        self.render()
        LOG.debug("滚轮缩放: %.0f%% -> %.0f%%", old * 100, new * 100)

    def _on_press(self, event) -> None:
        self._drag_origin = (event.x, event.y, self.offset[0], self.offset[1])
        self.canvas.configure(cursor="fleur")

    def _on_drag(self, event) -> None:
        if self._drag_origin is None:
            return
        x0, y0, ox, oy = self._drag_origin
        self.offset = [ox + (event.x - x0), oy + (event.y - y0)]
        self.render()

    def _on_release(self, _event) -> None:
        self._drag_origin = None

    # ======================================================================
    # 渲染
    # ======================================================================
    def render(self, force: bool = False) -> None:
        if not self.handle:
            return
        if force or self._photo is None or abs(self._render_scale - self.scale) > 1e-6:
            photo, applied = image_utils.render(self.handle, self.scale)
            if photo is None:
                self.status.set("渲染失败")
                return
            self._photo = photo
            self._render_scale = applied

        self.canvas.delete("img")
        self.canvas.create_image(
            self.offset[0], self.offset[1], image=self._photo, anchor="center", tags="img",
        )
        iw, ih = self.handle["size"]
        self.status.set(
            f"{iw}x{ih}  |  缩放 {self._render_scale * 100:.0f}%  |  "
            f"滚轮缩放 / 拖动平移 / ESC 关闭"
        )
