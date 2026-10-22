# -*- coding: utf-8 -*-
"""中间标签工作区：预设切换栏 + 若干标签组（TagGroupPanel）。

TagGroupPanel：
* 标题栏可拖动排序（拖标题即拖整组）
* 组内标签自动换行、可点击选中、可拖出、可接收拖入
* 右键标题栏：重命名 / 删除 / 上移 / 下移
"""
from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import List, Optional

from config import (
    C_ACCENT, C_BG, C_BORDER, C_DROP, C_HEADER, C_PANEL, C_TEXT, C_TEXT_SUB,
    FONT_BOLD, FONT_NORMAL, FONT_SMALL,
)
from image_tag import ImageTagWidget
from widgets import FlowFrame, ScrollFrame

LOG = logging.getLogger("tag_group")

HEADER_DRAG_THRESHOLD = 5


class TagGroupPanel(tk.Frame):
    """一个标签组面板。"""

    DROP_KIND = "group"

    def __init__(self, master, app, group: dict, index: int):
        super().__init__(
            master, bg=C_PANEL,
            highlightbackground=C_BORDER, highlightthickness=2, bd=0,
        )
        self.app = app
        self.group = group
        self.group_id = group["group_id"]
        self.index = index
        self.title_text = ""
        self._tag_widgets: List[ImageTagWidget] = []
        self._press = None
        self._dragging = False

        self._build_header()
        self._build_body()
        self.refresh_tags()

    # ======================================================================
    # 构建
    # ======================================================================
    def _build_header(self) -> None:
        self.header = tk.Frame(self, bg=C_HEADER, cursor="fleur")
        self.header.pack(fill="x")

        self.title_label = tk.Label(
            self.header, text="", font=FONT_BOLD, bg=C_HEADER, fg=C_TEXT,
            anchor="w", padx=10, pady=5, cursor="fleur",
        )
        self.title_label.pack(side="left")

        self.hint_label = tk.Label(
            self.header, text="⠿ 拖标题排序", font=FONT_SMALL,
            bg=C_HEADER, fg=C_TEXT_SUB, padx=10, cursor="fleur",
        )
        self.hint_label.pack(side="right")

        for widget in (self.header, self.title_label, self.hint_label):
            widget.bind("<ButtonPress-1>", self._on_header_press)
            widget.bind("<B1-Motion>", self._on_header_motion)
            widget.bind("<ButtonRelease-1>", self._on_header_release)
            widget.bind("<Button-3>", self._on_header_menu)
            widget.bind("<Double-Button-1>", lambda e: self._rename_group())

    def _build_body(self) -> None:
        self.empty_hint = tk.Label(
            self, text="把右侧图片标签拖到这里（单击选中 / 预览）",
            font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB, anchor="w",
        )
        self.body = FlowFrame(self, hgap=8, vgap=8, bg=C_PANEL)
        self.body.pack(fill="x", padx=6, pady=6)

    # ======================================================================
    # 渲染
    # ======================================================================
    def _title(self) -> str:
        group = self.group
        return f"组 {self.index + 1}｜{group['name']}（{len(group['tag_ids'])} 个标签）"

    def refresh_tags(self) -> None:
        """按数据重建组内标签控件。"""
        self.title_text = self._title()
        try:
            self.title_label.configure(text=self.title_text)
        except tk.TclError:
            return

        for widget in self._tag_widgets:
            self.body.remove(widget, destroy=True)
        self._tag_widgets = []

        for tag_id in list(self.group["tag_ids"]):
            if self.app.data.get_tag(tag_id) is None:
                LOG.warning("分组 %s 中标签 %s 已失效，跳过渲染", self.group_id, tag_id)
                continue
            try:
                widget = ImageTagWidget(self.body, self.app, tag_id, group_id=self.group_id, bg=C_PANEL)
            except tk.TclError as exc:
                LOG.error("创建标签控件失败 %s: %s", tag_id, exc)
                continue
            self.body.add(widget)
            self._tag_widgets.append(widget)

        if self._tag_widgets:
            self.empty_hint.pack_forget()
        else:
            self.empty_hint.pack(fill="x", padx=12, pady=(0, 8), before=self.body)

        # 立即重排一次（首帧时宽度可能还没算好，Configure 事件会再纠正）
        self.after_idle(self._safe_relayout)
        LOG.debug("分组 [%s] 渲染 %d 个标签", self.group["name"], len(self._tag_widgets))

    def _safe_relayout(self) -> None:
        try:
            if self.winfo_exists():
                self.body._relayout()  # noqa: SLF001 - 立即重排一次，避免首帧空白
        except tk.TclError:
            pass

    def refresh_selection(self) -> None:
        for widget in self._tag_widgets:
            widget.refresh_selection()

    def update_title(self) -> None:
        self.title_text = self._title()
        self.title_label.configure(text=self.title_text)

    # ======================================================================
    # 拖放支持
    # ======================================================================
    def set_drop_highlight(self, on: bool) -> None:
        try:
            self.configure(highlightbackground=C_DROP if on else C_BORDER)
            self.header.configure(bg=C_ACCENT if on else C_HEADER)
            self.title_label.configure(bg=C_ACCENT if on else C_HEADER,
                                       fg="white" if on else C_TEXT)
            self.hint_label.configure(bg=C_ACCENT if on else C_HEADER,
                                      fg="#eaf1ff" if on else C_TEXT_SUB)
        except tk.TclError:
            pass

    def index_at(self, x_root: int, y_root: int) -> int:
        """根据鼠标位置计算插入索引（按行分组，行内按横向中点判断）。"""
        widgets = [w for w in self._tag_widgets if w.winfo_exists()]
        if not widgets:
            return 0

        # 按 top 坐标归并成行
        rows = []  # [(top, [widgets])]
        for widget in widgets:
            top = widget.winfo_rooty()
            if rows and abs(rows[-1][0] - top) <= 4:
                rows[-1][1].append(widget)
            else:
                rows.append((top, [widget]))

        for top, row in rows:
            height = max(w.winfo_height() for w in row)
            if y_root < top + height / 2:  # 落在这一行
                for widget in row:
                    if x_root < widget.winfo_rootx() + widget.winfo_width() / 2:
                        return widgets.index(widget)
                return widgets.index(row[-1]) + 1
        return len(widgets)

    # ======================================================================
    # 标题栏拖拽 / 菜单
    # ======================================================================
    def _on_header_press(self, event) -> None:
        self._press = (event.x_root, event.y_root)
        self._dragging = False

    def _on_header_motion(self, event) -> None:
        if self._press is None or self._dragging:
            return
        dx = abs(event.x_root - self._press[0])
        dy = abs(event.y_root - self._press[1])
        if max(dx, dy) >= HEADER_DRAG_THRESHOLD:
            self._dragging = True
            self.app.drag.begin_group(self, event.x_root, event.y_root)

    def _on_header_release(self, _event) -> None:
        self._press = None
        self._dragging = False

    def _on_header_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0, font=FONT_NORMAL)
        menu.add_command(label="重命名标签组", command=self._rename_group)
        menu.add_command(label="新建标签组", command=self.app.create_group)
        menu.add_separator()
        menu.add_command(label="上移", command=lambda: self.app.move_group_step(self.group_id, -1))
        menu.add_command(label="下移", command=lambda: self.app.move_group_step(self.group_id, 1))
        menu.add_separator()
        menu.add_command(label="删除标签组", command=self._delete_group)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _rename_group(self) -> None:
        name = simpledialog.askstring(
            "重命名标签组", "请输入标签组名称：",
            initialvalue=self.group["name"], parent=self.winfo_toplevel(),
        )
        if name:
            self.app.rename_group(self.group_id, name)

    def _delete_group(self) -> None:
        if len(self.app.presets.groups()) <= 1:
            messagebox.showinfo("提示", "至少要保留一个标签组。", parent=self.winfo_toplevel())
            return
        if messagebox.askyesno(
            "删除标签组",
            f"确定删除「{self.group['name']}」吗？\n组内标签不会被删除，仍保留在右侧仓库。",
            parent=self.winfo_toplevel(),
        ):
            self.app.delete_group(self.group_id)


class TagWorkspace(tk.Frame):
    """中间工作区：预设互斥单选 + 标签组列表（纵向滚动）。"""

    def __init__(self, master, app):
        super().__init__(master, bg=C_BG)
        self.app = app
        self.panels: List[TagGroupPanel] = []
        self.radios: List[ttk.Radiobutton] = []
        self._build_toolbar()

        self.scroll = ScrollFrame(self, bg=C_BG)
        self.scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.rebuild()

    # ======================================================================
    def _build_toolbar(self) -> None:
        bar = tk.Frame(self, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=2)
        bar.pack(fill="x", padx=8, pady=8)

        tk.Label(
            bar, text="预设", font=FONT_BOLD, bg=C_PANEL, fg=C_TEXT,
        ).pack(side="left", padx=(10, 6), pady=7)

        self.preset_var = tk.IntVar(value=self.app.presets.active_index())
        for i in range(self.app.presets.count):
            rb = ttk.Radiobutton(
                bar, text=self.app.presets.preset_name(i), value=i,
                variable=self.preset_var, style="Preset.TRadiobutton",
                command=self._on_preset_changed,
            )
            rb.pack(side="left", padx=2)
            rb.bind("<Button-3>", lambda e, idx=i: self._rename_preset(idx))
            self.radios.append(rb)

        ttk.Button(
            bar, text="＋ 新建组", style="Small.TButton",
            command=self._create_group,
        ).pack(side="right", padx=8, pady=4)

    # ======================================================================
    def _on_preset_changed(self) -> None:
        self.app.switch_preset(self.preset_var.get())

    def _create_group(self) -> None:
        self.app.create_group()

    def _rename_preset(self, index: int) -> None:
        name = simpledialog.askstring(
            "重命名预设", f"请输入「预设{index + 1}」的新名称：",
            initialvalue=self.app.presets.preset_name(index),
            parent=self.winfo_toplevel(),
        )
        if name:
            self.app.rename_preset(index, name)

    # ======================================================================
    def rebuild(self) -> None:
        """按当前预设重建所有分组面板（预设切换 / 数据变更后调用）。"""
        for panel in self.panels:
            try:
                panel.destroy()
            except tk.TclError:
                pass
        self.panels = []

        groups = self.app.presets.groups()
        for i, group in enumerate(groups):
            panel = TagGroupPanel(self.scroll.body, self.app, group, i)
            panel.pack(fill="x", pady=(0, 10))
            self.panels.append(panel)

        self.preset_var.set(self.app.presets.active_index())
        self.refresh_preset_labels()
        self.scroll.refresh_scrollregion()
        LOG.debug("工作区重建完成: 预设=%s, 分组数=%d",
                  self.app.presets.active_preset()["name"], len(self.panels))

    def refresh_preset_labels(self) -> None:
        for i, rb in enumerate(self.radios):
            try:
                rb.configure(text=self.app.presets.preset_name(i))
            except tk.TclError:
                pass
        self.preset_var.set(self.app.presets.active_index())

    def refresh_selection(self) -> None:
        for panel in self.panels:
            panel.refresh_selection()

    def group_panels(self) -> List[TagGroupPanel]:
        return list(self.panels)

    def panel_by_id(self, group_id: str) -> Optional[TagGroupPanel]:
        for panel in self.panels:
            if panel.group_id == group_id:
                return panel
        return None

    def scroll_to_top(self) -> None:
        self.scroll.scroll_to_top()
