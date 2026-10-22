# -*- coding: utf-8 -*-
"""通用 UI 组件。

包含三部分：
1. get_font / create_font —— 字体对象缓存（tkinter.font.Font 可测量文字宽度）
2. round_rect_points —— 生成"圆角矩形"多边形顶点（配合 smooth=True 使用）
3. ScrollFrame —— 纵向滚动容器
4. FlowFrame —— 自动换行（从左到右、行满换行）的流式布局容器
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Iterable, List, Optional

from config import C_BG, C_PANEL, C_BORDER, C_HEADER

# --------------------------------------------------------------------------
# 字体
# --------------------------------------------------------------------------
_font_cache: dict = {}
_font_root = None  # 字体对象绑定在 Tk 解释器上，换窗口后需重建


def get_font(spec) -> tkfont.Font:
    """按 (family, size[, weight]) 取字体对象（懒创建 + 缓存）。

    标签需要精确测量文字宽度来"自适应大小"，必须用 Font 对象而非字体元组。
    同一进程内重新创建 Tk 根窗口时，旧字体对象已失效，这里自动清空缓存重建。
    """
    global _font_root
    root = getattr(tk, "_default_root", None)
    if root is not _font_root:
        _font_cache.clear()
        _font_root = root

    key = tuple(spec)
    font = _font_cache.get(key)
    if font is None:
        family = key[0]
        size = key[1] if len(key) > 1 else 10
        weight = key[2] if len(key) > 2 else "normal"
        try:
            font = tkfont.Font(family=family, size=size, weight=weight)
        except tk.TclError:  # 字体不存在时退回默认
            font = tkfont.Font(size=size, weight=weight)
        _font_cache[key] = font
    return font


# --------------------------------------------------------------------------
# 圆角矩形
# --------------------------------------------------------------------------
def round_rect_points(x1: float, y1: float, x2: float, y2: float, r: float) -> List[float]:
    """生成圆角矩形的顶点序列，配合 create_polygon(smooth=True) 使用。"""
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def draw_round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs) -> int:
    """在画布上画一个圆角矩形，返回 item id。"""
    return canvas.create_polygon(
        round_rect_points(x1, y1, x2, y2, r),
        smooth=True, splinesteps=24, **kwargs
    )


# --------------------------------------------------------------------------
# 滚动容器
# --------------------------------------------------------------------------
class ScrollFrame(tk.Frame):
    """纵向滚动容器：内部 body 是真正放内容的 Frame。

    用法::

        sf = ScrollFrame(parent)
        sf.pack(fill="both", expand=True)
        tk.Label(sf.body, text="内容").pack()
    """

    def __init__(self, master, bg: str = C_BG, **kw):
        kw.setdefault("bg", bg)
        super().__init__(master, **kw)
        self._bg = bg

        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        # 供 main.py 的全局滚轮处理识别
        self.canvas._scroll_owner = self  # type: ignore[attr-defined]

    # -- 内部 --
    def _on_body_configure(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.canvas.itemconfigure(self._win, width=event.width)

    # -- 对外 --
    def scroll_units(self, units: int) -> None:
        try:
            self.canvas.yview_scroll(int(units), "units")
        except tk.TclError:
            pass

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def refresh_scrollregion(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


# --------------------------------------------------------------------------
# 自动换行流式布局
# --------------------------------------------------------------------------
class FlowFrame(tk.Frame):
    """流式布局容器：子控件从左到右排列，一行放不下自动换行。

    与 pack/grid 不同，这里用 place 精确排布，从而保证"自动换行 + 自适应高度"。
    """

    def __init__(self, master, hgap: int = 8, vgap: int = 8, bg: str = C_PANEL, **kw):
        kw.setdefault("bg", bg)
        super().__init__(master, **kw)
        self.hgap = hgap
        self.vgap = vgap
        self._items: List[tk.Widget] = []
        self._width = 0
        self._pending = False
        self._last_height = 0

        # 高度由自己控制（place 子控件不会撑开父容器）
        self.pack_propagate(False)
        self.grid_propagate(False)

        self.bind("<Configure>", self._on_configure)

    # ---------------- 元素管理 ----------------
    def items(self) -> List[tk.Widget]:
        return list(self._items)

    def add(self, widget: tk.Widget) -> None:
        self._items.append(widget)
        self._schedule()

    def add_all(self, widgets: Iterable[tk.Widget]) -> None:
        self._items.extend(list(widgets))
        self._schedule()

    def remove(self, widget: tk.Widget, destroy: bool = False) -> None:
        if widget in self._items:
            self._items.remove(widget)
            try:
                widget.place_forget()
                if destroy:
                    widget.destroy()
            except tk.TclError:
                pass
            self._schedule()

    def clear(self, destroy: bool = True) -> None:
        for w in list(self._items):
            try:
                w.place_forget()
                if destroy:
                    w.destroy()
            except tk.TclError:
                pass
        self._items.clear()
        self._last_height = 0
        try:
            self.configure(height=1)
        except tk.TclError:
            pass
        self._schedule()

    # ---------------- 布局 ----------------
    def _on_configure(self, event) -> None:
        if event.width != self._width:
            self._width = event.width
            self._schedule()

    def _schedule(self) -> None:
        if self._pending:
            return
        self._pending = True
        try:
            self.after_idle(self._relayout)
        except tk.TclError:
            self._pending = False

    def _relayout(self) -> None:
        self._pending = False
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        width = self._width or self.winfo_width()
        if width <= 1:  # 尚未完成几何计算，用父容器宽度兜底
            try:
                width = max(self.master.winfo_width() - 4, 320)
            except tk.TclError:
                width = 600

        x = y = 0
        row_h = 0
        for w in list(self._items):
            try:
                if not w.winfo_exists():
                    continue
                ww = w.winfo_reqwidth()
                wh = w.winfo_reqheight()
            except tk.TclError:
                continue
            if x > 0 and x + ww > width:
                x = 0
                y += row_h + self.vgap
                row_h = 0
            try:
                w.place(x=x, y=y, width=ww, height=wh)
            except tk.TclError:
                continue
            x += ww + self.hgap
            row_h = max(row_h, wh)

        total = y + row_h
        if total != self._last_height:
            self._last_height = total
            try:
                self.configure(height=max(total, 1))
            except tk.TclError:
                pass


# --------------------------------------------------------------------------
# 面板标题条（三栏复用）
# --------------------------------------------------------------------------
class PanelHeader(tk.Frame):
    """白色面板顶部标题条：粗体标题 + 右侧说明。"""

    def __init__(self, master, title: str, subtitle: str = "", **kw):
        kw.setdefault("bg", C_HEADER)
        super().__init__(master, **kw)
        self.title_label = tk.Label(
            self, text=title, font=("Microsoft YaHei UI", 12, "bold"),
            bg=C_HEADER, fg="#16233a", anchor="w", padx=10, pady=6,
        )
        self.title_label.pack(side="left")
        self.subtitle_label = tk.Label(
            self, text=subtitle, font=("Microsoft YaHei UI", 9),
            bg=C_HEADER, fg="#5b6b83", anchor="e", padx=10,
        )
        self.subtitle_label.pack(side="right")
        # 底部 1px 分隔线
        self.sep = tk.Frame(self, bg=C_BORDER, height=1)
        self.sep.pack(side="bottom", fill="x")

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.configure(text=text)

    def set_title(self, text: str) -> None:
        self.title_label.configure(text=text)


def hline(master, color: str = C_BORDER, bg: Optional[str] = None) -> tk.Frame:
    """1 像素水平分隔线。"""
    return tk.Frame(master, bg=color, height=1)
