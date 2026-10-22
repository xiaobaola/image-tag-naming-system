# -*- coding: utf-8 -*-
"""右侧标签仓库面板。

结构：
    标题「标签仓库（共 N 个）」
    备注输入框
    [＋ 从文件树新建图片标签] [选择图片]
    [保存] [清空]
    提示行
    横向自动换行 + 纵向滚动的标签区

标签仓库里放着 **全部** 图片标签（全局共享），可拖入中间任意标签组。
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from config import (
    C_BORDER, C_DROP, C_PANEL, C_PANEL_ALT, C_TEXT, C_TEXT_SUB,
    FONT_BOLD, FONT_INPUT, FONT_SMALL,
)
from image_tag import ImageTagWidget
from widgets import FlowFrame, ScrollFrame, hline

LOG = logging.getLogger("warehouse")


class TagWarehousePanel(tk.Frame):
    """图片标签仓库。"""

    DROP_KIND = "warehouse"

    def __init__(self, master, app):
        super().__init__(master, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=2)
        self.app = app
        self.current_tag_id: Optional[str] = None
        self.tag_widgets: List[ImageTagWidget] = []

        self.remark_var = tk.StringVar()
        self.count_var = tk.StringVar(value="共 0 个标签")

        self._build()
        self.rebuild()

    # ======================================================================
    # 构建
    # ======================================================================
    def _build(self) -> None:
        header = tk.Frame(self, bg=C_PANEL)
        header.pack(fill="x", padx=10, pady=(10, 2))
        tk.Label(
            header, text="标签仓库", font=FONT_BOLD, bg=C_PANEL, fg=C_TEXT, anchor="w",
        ).pack(side="left")
        tk.Label(
            header, textvariable=self.count_var, font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB,
        ).pack(side="right")

        # 备注输入
        entry_row = tk.Frame(self, bg=C_PANEL)
        entry_row.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(
            entry_row, text="备注", font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB,
        ).pack(side="left", padx=(0, 6))
        self.entry = ttk.Entry(entry_row, textvariable=self.remark_var, font=FONT_INPUT)
        self.entry.pack(side="left", fill="x", expand=True, ipady=3)
        self.entry.bind("<Return>", lambda e: self.app.save_remark())
        self.entry.bind("<Escape>", lambda e: self.clear_remark())

        # 按钮行 1：从文件树新建（首位）+ 选择图片
        btn_row1 = tk.Frame(self, bg=C_PANEL)
        btn_row1.pack(fill="x", padx=10, pady=(4, 2))
        ttk.Button(
            btn_row1, text="＋ 从文件树新建图片标签", style="Small.TButton",
            command=self.app.create_tag_from_tree,
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            btn_row1, text="选择图片", style="Small.TButton",
            command=self.app.choose_image_files,
        ).pack(side="left", padx=(6, 0))

        # 按钮行 2：保存 / 清空
        btn_row2 = tk.Frame(self, bg=C_PANEL)
        btn_row2.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Button(
            btn_row2, text="保存", style="Small.TButton",
            command=self.app.save_remark,
        ).pack(side="left")
        ttk.Button(
            btn_row2, text="清空", style="Small.TButton",
            command=self.clear_remark,
        ).pack(side="left", padx=6)

        tk.Label(
            self, text="单击标签：中间看大图｜双击：独立预览窗",
            font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB, anchor="w",
            justify="left", wraplength=355,
        ).pack(fill="x", padx=10, pady=(0, 4))

        hline(self, C_BORDER, C_PANEL).pack(fill="x", padx=6, pady=(0, 4))

        # 标签区（横向换行 + 纵向滚动）
        self.scroll = ScrollFrame(self, bg=C_PANEL_ALT)
        self.scroll.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.flow = FlowFrame(self.scroll.body, hgap=8, vgap=8, bg=C_PANEL_ALT)
        self.flow.pack(fill="x", padx=6, pady=6)

    # ======================================================================
    # 渲染
    # ======================================================================
    def rebuild(self) -> None:
        """重建仓库标签（缩略图走缓存，重建成本很低）。"""
        for widget in self.tag_widgets:
            self.flow.remove(widget, destroy=True)
        self.tag_widgets = []

        for tag_id in list(self.app.data.tags.keys()):
            try:
                widget = ImageTagWidget(self.flow, self.app, tag_id, group_id=None, bg=C_PANEL_ALT)
            except tk.TclError as exc:
                LOG.error("仓库标签渲染失败 %s: %s", tag_id, exc)
                continue
            self.flow.add(widget)
            self.tag_widgets.append(widget)

        self.count_var.set(f"共 {len(self.tag_widgets)} 个标签")
        self.flow._relayout()  # noqa: SLF001 - 立即刷新一次布局
        self.after_idle(self._safe_relayout)

        # 恢复聚焦态
        if self.current_tag_id and self.app.data.get_tag(self.current_tag_id) is None:
            self.current_tag_id = None
        self._apply_focus()

        self.scroll.refresh_scrollregion()
        LOG.debug("标签仓库渲染完成: %d 个标签", len(self.tag_widgets))

    def _safe_relayout(self) -> None:
        try:
            if self.winfo_exists():
                self.flow._relayout()  # noqa: SLF001
        except tk.TclError:
            pass

    # ======================================================================
    # 备注 / 聚焦
    # ======================================================================
    def get_remark(self) -> str:
        return (self.remark_var.get() or "").strip()

    def set_remark(self, text: str) -> None:
        self.remark_var.set(text or "")

    def clear_remark(self) -> bool:
        self.set_remark("")
        self.set_current_tag(None)
        LOG.info("已清空备注输入框")
        return True

    def set_current_tag(self, tag_id: Optional[str], fill_remark: bool = False) -> None:
        self.current_tag_id = tag_id
        if fill_remark and tag_id:
            tag = self.app.data.get_tag(tag_id)
            if tag:
                self.set_remark(tag.get("remark", ""))
                self.entry.icursor("end")
        self._apply_focus()

    def _apply_focus(self) -> None:
        for widget in self.tag_widgets:
            widget.set_focused(widget.tag_id == self.current_tag_id)

    def tag_widget(self, tag_id: str) -> Optional[ImageTagWidget]:
        for widget in self.tag_widgets:
            if widget.tag_id == tag_id:
                return widget
        return None

    def scroll_to_tag(self, tag_id: str) -> None:
        """滚动到指定标签（新建标签后定位用）。"""
        widget = self.tag_widget(tag_id)
        if widget is None:
            return
        try:
            self.update_idletasks()
            content_h = max(self.flow.winfo_height(), 1)
            y = widget.winfo_y()
            self.scroll.canvas.yview_moveto(max(0.0, min(1.0, (y - 40) / content_h)))
        except tk.TclError:
            pass

    # ======================================================================
    # 拖放支持（拖回仓库 = 从分组中移除）
    # ======================================================================
    def set_drop_highlight(self, on: bool) -> None:
        try:
            self.configure(highlightbackground=C_DROP if on else C_BORDER)
        except tk.TclError:
            pass
