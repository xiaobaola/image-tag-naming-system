# -*- coding: utf-8 -*-
"""图片标签命名系统 —— 主程序。

三栏布局：
    左：Windows 文件树（选图片 / 单击预览 / 启动定位上次目录）
    中：5 套互斥预设 + 标签组工作区 + 单击预览面板 + 命名预览
    右：标签仓库（新建图片标签 / 选择图片 / 标签横向换行 + 纵向滚动）

启动方式：
    在 PyCharm 中直接运行本文件，或命令行执行： python main.py
"""
from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import List, Optional

import config
from config import (
    C_ACCENT, C_ACCENT_DARK, C_BG, C_BORDER, C_PANEL, C_TEXT, C_TEXT_SUB,
    FONT_BOLD, FONT_BUTTON, FONT_MONO, FONT_SMALL, FONT_TREE,
    IMAGE_EXTS_TEXT,
)
from center_preview import CenterPreviewPanel
from data_store import DataStore
from drag_manager import DragManager
from file_tree import FileTreePanel
from image_preview import ImagePreviewWindow
from image_tag import ImageTagWidget
from preset_manager import PresetManager
from tag_group import TagWorkspace
from tag_warehouse import TagWarehousePanel

LOG = logging.getLogger("main")


class ImageTagApp:
    """应用主控制器：持有数据、视图与全部业务动作。"""

    def __init__(self):
        config.setup_logging()
        LOG.info("=" * 72)
        LOG.info("启动 %s v%s", config.APP_TITLE, config.APP_VERSION)
        self._set_taskbar_identity()

        # ---------------- 主窗口 ----------------
        self.root = tk.Tk()
        self.root.title(f"{config.APP_TITLE} v{config.APP_VERSION}")
        self._place_window()
        self.root.minsize(config.WINDOW_MIN_W, config.WINDOW_MIN_H)
        self.root.configure(bg=C_BG)
        self._icon_photo = None
        self._apply_icon()

        # 提前创建，避免任何早期回调引用未定义
        self.name_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="就绪")
        self.timestamp_var = tk.BooleanVar(value=True)   # 命名时是否追加时间戳（默认开）
        self.last_dir = os.path.expanduser("~")
        self._current_folder = ""      # 命名时参照的目录（日志用）

        # ---------------- 数据 / 业务 ----------------
        self.data = DataStore(config.DATA_FILE)
        self.data.load()
        if self.data.last_dir and os.path.isdir(self.data.last_dir):
            self.last_dir = self.data.last_dir
        self.presets = PresetManager(self.data)
        self.presets.prune_missing_tags()
        self.drag = DragManager(self)

        # ---------------- 界面 ----------------
        self._build_style()
        self._build_layout()
        self._bind_global()

        self.refresh_all()
        self._restore_last_folder()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(15000, self._tick)

        LOG.info("界面初始化完成，最小窗口 %dx%d", config.WINDOW_MIN_W, config.WINDOW_MIN_H)

    # ======================================================================
    # 样式
    # ======================================================================
    @staticmethod
    def _set_taskbar_identity() -> None:
        """让 Windows 任务栏使用本应用自己的图标与分组，而不是 Python 图标。"""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"ImageTagNamer.{config.APP_VERSION}"
            )
        except Exception as exc:  # noqa: BLE001 - 非 Windows 或被策略禁用时忽略
            LOG.debug("设置任务栏标识失败: %s", exc)

    def _apply_icon(self) -> None:
        """窗口 / 任务栏 / 后续 Toplevel（预览窗）统一使用应用图标。"""
        ico, png = config.APP_ICON_ICO, config.APP_ICON_PNG
        if os.path.isfile(ico):
            try:
                self.root.iconbitmap(ico)
                self.root.iconbitmap(default=ico)   # 之后创建的预览窗也继承
                LOG.info("已设置窗口图标: %s", ico)
            except tk.TclError as exc:
                LOG.warning("设置窗口图标（ico）失败: %s", exc)
        else:
            LOG.warning("图标文件不存在: %s", ico)
        if os.path.isfile(png):
            try:
                self._icon_photo = tk.PhotoImage(file=png)   # 必须保留引用，否则会被回收
                self.root.iconphoto(True, self._icon_photo)
            except tk.TclError as exc:
                LOG.warning("设置窗口图标（png）失败: %s", exc)

    def _place_window(self) -> None:
        """初始尺寸不超出屏幕，并居中显示。"""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w = min(config.WINDOW_W, max(config.WINDOW_MIN_W, sw - 60))
        h = min(config.WINDOW_H, max(600, sh - 90))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 20)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        LOG.info("屏幕 %dx%d，窗口 %dx%d+%d+%d", sw, sh, w, h, x, y)

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=FONT_BUTTON, padding=(10, 5))
        style.configure("Small.TButton", font=FONT_BUTTON, padding=(8, 4))
        style.configure(
            "Accent.TButton", font=FONT_BUTTON, padding=(10, 5),
            foreground="#ffffff", background=C_ACCENT,
        )
        style.map(
            "Accent.TButton",
            background=[("active", C_ACCENT_DARK), ("pressed", C_ACCENT_DARK)],
            foreground=[("disabled", "#e5e7eb")],
        )
        style.configure(
            "Preset.TRadiobutton", font=FONT_BOLD,
            background=C_PANEL, foreground=C_TEXT, padding=(4, 2),
        )
        style.map(
            "Preset.TRadiobutton",
            background=[("active", C_PANEL)],
            foreground=[("selected", C_ACCENT_DARK)],
        )
        style.configure(
            "Treeview", font=FONT_TREE, rowheight=24,
            background="#ffffff", fieldbackground="#ffffff", foreground=C_TEXT,
        )
        style.map("Treeview", background=[("selected", "#cfe2ff")], foreground=[("selected", "#10233f")])
        style.configure("Treeview.Heading", font=FONT_BOLD)

    # ======================================================================
    # 布局
    # ======================================================================
    def _build_layout(self) -> None:
        """三栏布局：左右两栏固定宽度，中间栏自适应剩余宽度。"""
        outer = tk.Frame(self.root, bg=C_BG)
        outer.pack(fill="both", expand=True, padx=8, pady=8)

        # ---- 左：文件树（固定宽度，内容不得撑宽） ----
        left = tk.Frame(outer, bg=C_BG, width=config.COL_LEFT_MIN)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.file_tree = FileTreePanel(left, self)
        self.file_tree.pack(fill="both", expand=True)

        # ---- 右：标签仓库（固定宽度，内容不得撑宽） ----
        right = tk.Frame(outer, bg=C_BG, width=config.COL_RIGHT_MIN)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self.warehouse = TagWarehousePanel(right, self)
        self.warehouse.pack(fill="both", expand=True)

        # ---- 中：标签工作区 + 命名预览（占据剩余空间） ----
        center = tk.Frame(outer, bg=C_BG)
        center.pack(side="left", fill="both", expand=True, padx=8)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(0, weight=1)
        self.workspace = TagWorkspace(center, self)
        self.workspace.grid(row=0, column=0, sticky="nsew")

        # 单击图片 -> 在中心区域直接看大图（固定高度，可收起）
        self.center_preview = CenterPreviewPanel(center, self)
        self.center_preview.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        self._build_output_bar(center).grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_output_bar(self, parent) -> tk.Frame:
        bar = tk.Frame(parent, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=2)

        row1 = tk.Frame(bar, bg=C_PANEL)
        row1.pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(
            row1, text="命名预览", font=FONT_BOLD, bg=C_PANEL, fg=C_TEXT,
        ).pack(side="left")
        tk.Label(
            row1,
            text="组序→组内序 | 下划线连接 | 可选时间戳",
            font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB, wraplength=190, justify="left",
        ).pack(side="left", padx=8)
        tk.Label(
            row1, textvariable=self.status_var, font=FONT_SMALL,
            bg=C_PANEL, fg=C_ACCENT_DARK, anchor="e", justify="right", wraplength=180,
        ).pack(side="right")

        # 选项行：是否追加时间戳（默认勾选；用经典 Checkbutton 显示对勾 ✓）
        row_opt = tk.Frame(bar, bg=C_PANEL)
        row_opt.pack(fill="x", padx=10, pady=(0, 2))
        self.timestamp_cb = tk.Checkbutton(
            row_opt, text="添加时间戳", variable=self.timestamp_var,
            command=self.update_output, font=FONT_BUTTON,
            bg=C_PANEL, fg=C_TEXT, activebackground=C_PANEL,
            activeforeground=C_TEXT, selectcolor="#ffffff",
            bd=0, highlightthickness=0, cursor="hand2",
            padx=2, pady=0,
        )
        self.timestamp_cb.pack(side="left")
        tk.Label(
            row_opt, text="勾选后末尾追加 yyyyMMddhhmm；取消则只用标签拼接",
            font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB,
        ).pack(side="left", padx=8)

        row2 = tk.Frame(bar, bg=C_PANEL)
        row2.pack(fill="x", padx=10, pady=(0, 8))
        self.name_entry = tk.Entry(
            row2, textvariable=self.name_var, font=FONT_MONO,
            state="readonly", readonlybackground="#f7fbff",
            bd=1, relief="solid", fg=C_TEXT,
        )
        self.name_entry.pack(side="left", fill="x", expand=True, ipady=6)

        ttk.Button(
            row2, text="一键命名", style="Accent.TButton", command=self.rename_selected_files,
        ).pack(side="right", padx=(8, 0))
        ttk.Button(
            row2, text="复制", style="Small.TButton", command=self.copy_name,
        ).pack(side="right", padx=(6, 0))
        return bar

    def _bind_global(self) -> None:
        self.root.bind_all("<MouseWheel>", self._on_global_wheel, add="+")
        self.root.bind("<Control-s>", lambda e: self.save_data())
        self.root.bind("<Control-S>", lambda e: self.save_data())
        self.root.bind("<F5>", lambda e: self.file_tree.refresh_all())
        self.root.bind("<Escape>", lambda e: self.drag.cancel())

    def _on_global_wheel(self, event):
        """统一滚轮：向上找到所属滚动容器后滚动。"""
        widget = event.widget
        while widget is not None:
            if isinstance(widget, ttk.Treeview):
                return  # 交给 Treeview 自身
            owner = getattr(widget, "_scroll_owner", None)
            if owner is not None:
                steps = int(-event.delta / 120) or (-1 if event.delta > 0 else 1)
                owner.scroll_units(steps * 3)
                return "break"
            widget = getattr(widget, "master", None)

    # ======================================================================
    # 通用
    # ======================================================================
    def set_status(self, text: str) -> None:
        try:
            self.status_var.set(text)
        except tk.TclError:
            pass

    def save_data(self) -> None:
        self.data.save()

    def refresh_all(self) -> None:
        """全量刷新（数据变更后调用）。"""
        self.warehouse.rebuild()
        self.workspace.rebuild()
        self.center_preview.refresh_meta()
        self.update_output()
        self.set_status(self.data.stats())

    def _restore_last_folder(self) -> None:
        """启动时把文件树定位到上次打开的图片文件夹。"""
        if not self.last_dir or not os.path.isdir(self.last_dir):
            LOG.info("没有上次打开的文件夹可恢复")
            return
        if self.file_tree.open_directory(self.last_dir):
            LOG.info("启动定位上次文件夹: %s", self.last_dir)
            self.set_status(f"已定位到上次文件夹：{os.path.basename(self.last_dir) or self.last_dir}")

    def remember_folder(self, folder: str) -> None:
        """记录上次打开的图片文件夹（退出时随标签数据一起保存）。"""
        if not folder or not os.path.isdir(folder):
            return
        if self.data.set_last_dir(folder):
            self.last_dir = os.path.normpath(os.path.abspath(folder))

    # ======================================================================
    # 命名串
    # ======================================================================
    def build_name(self) -> str:
        """按规则拼接：备注(或文件名) 用下划线连接，可选末尾追加时间戳。"""
        ids = self.presets.selected_ids()
        parts: List[str] = []
        for tag_id in ids:
            text = self.data.display_text(tag_id).strip()
            if text:
                parts.append(text)
        with_stamp = bool(self.timestamp_var.get())
        if with_stamp:
            parts.append(datetime.now().strftime("%Y%m%d%H%M"))
        name = "_".join(parts)
        LOG.debug("拼接命名串: %s（选中标签 %d 个，时间戳=%s）",
                  name, len(ids), "开" if with_stamp else "关")
        return name

    def update_output(self) -> None:
        try:
            self.name_var.set(self.build_name())
        except tk.TclError:
            pass

    def copy_name(self) -> None:
        self.update_output()
        name = self.name_var.get()
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(name)
            LOG.info("复制命名串到剪贴板: %s", name)
            self.set_status("命名串已复制到剪贴板")
        except tk.TclError as exc:
            LOG.error("复制失败: %s", exc)

    def _tick(self) -> None:
        """定时刷新时间戳，保证预览串中的时间是最新的。"""
        try:
            self.update_output()
            self.root.after(15000, self._tick)
        except tk.TclError:
            pass

    # ======================================================================
    # 图片标签的创建 / 编辑 / 删除
    # ======================================================================
    def add_tag_from_path(self, path: str, remark: str = "") -> Optional[dict]:
        if not path:
            return None
        path = os.path.normpath(os.path.abspath(path))
        if not os.path.isfile(path):
            LOG.warning("图片文件不存在，忽略: %s", path)
            messagebox.showwarning("文件不存在", f"找不到图片文件：\n{path}", parent=self.root)
            return None
        if not config.is_image_file(path):
            LOG.warning("非图片文件，忽略: %s", path)
            messagebox.showwarning(
                "不支持的格式",
                f"只支持以下图片格式：\n{IMAGE_EXTS_TEXT}",
                parent=self.root,
            )
            return None

        remark = (remark or "").strip()
        existing = self.data.find_tag_by_path(path)
        if existing is not None:
            LOG.info("图片已存在标签，复用: %s", path)
            if (existing.get("remark") or "") != remark:
                self.data.update_remark(existing["tag_id"], remark)
                self.data.save()
                self.refresh_all()
            self.warehouse.set_current_tag(existing["tag_id"], fill_remark=True)
            self.warehouse.scroll_to_tag(existing["tag_id"])
            self.set_status(f"该图片已有标签：{self.data.display_text(existing['tag_id'])}")
            return existing

        tag = self.data.add_tag(path, remark)
        self.data.save()
        self.warehouse.rebuild()
        self.warehouse.set_current_tag(tag["tag_id"])
        self.warehouse.scroll_to_tag(tag["tag_id"])
        self.update_output()
        self.set_status(f"已新建图片标签：{self.data.display_text(tag['tag_id'])}")
        return tag

    def create_tag_from_tree(self) -> None:
        """右栏【＋ 从文件树新建图片标签】按钮（选中项来自左侧文件树）。"""
        files = self.file_tree.get_selected_image_files()
        if not files:
            LOG.warning("未选中图片文件，无法新建标签")
            messagebox.showwarning(
                "新建图片标签",
                f"请先在左侧文件树中选中图片文件（{IMAGE_EXTS_TEXT}）。",
                parent=self.root,
            )
            return
        remark = self.warehouse.get_remark()
        created = 0
        for path in files:
            if self.add_tag_from_path(path, remark):
                created += 1
        LOG.info("从文件树新建图片标签 %d 个（备注=%r）", created, remark)

    def choose_image_files(self) -> None:
        """右栏【选择图片】按钮：唤起 Windows 文件选择框。"""
        paths = filedialog.askopenfilenames(
            title="选择图片",
            initialdir=self.last_dir if os.path.isdir(self.last_dir) else None,
            filetypes=config.IMAGE_FILE_TYPES,
            parent=self.root,
        )
        if not paths:
            LOG.info("【选择图片】已取消")
            return
        self.remember_folder(os.path.dirname(paths[0]))
        remark = self.warehouse.get_remark()
        for path in paths:
            self.add_tag_from_path(path, remark)
        LOG.info("【选择图片】导入 %d 个文件（备注=%r）", len(paths), remark)

    def save_remark(self) -> None:
        """右栏【保存】按钮：更新当前标签备注 / 用选中图片创建标签。"""
        text = self.warehouse.get_remark()
        current = self.warehouse.current_tag_id
        if current and self.data.get_tag(current):
            self.data.update_remark(current, text)
            self.data.save()
            self.refresh_all()
            self.warehouse.set_current_tag(current, fill_remark=True)
            LOG.info("保存备注: %s -> %r", current, text)
            self.set_status("备注已保存")
            return

        files = self.file_tree.get_selected_image_files()
        if files:
            self.add_tag_from_path(files[0], text)
            return

        LOG.info("保存备注失败：既没有聚焦标签，也没有选中图片")
        messagebox.showinfo(
            "保存",
            "请先选择图片：\n"
            "1) 点击右栏【选择图片】导入并生成标签；\n"
            "2) 或在左侧文件树选中图片后点击【新建图片标签】；\n"
            "3) 或先单击仓库里已有标签，再输入备注后保存。",
            parent=self.root,
        )

    def edit_remark(self, tag_id: str) -> None:
        tag = self.data.get_tag(tag_id)
        if not tag:
            return
        new_text = simpledialog.askstring(
            "编辑备注",
            "输入标签备注（留空则拼接时自动使用图片文件名）：",
            initialvalue=tag.get("remark", ""),
            parent=self.root,
        )
        if new_text is None:
            return
        self.data.update_remark(tag_id, new_text)
        self.data.save()
        self.refresh_all()
        self.set_status("备注已更新")

    def delete_tag(self, tag_id: str) -> None:
        tag = self.data.get_tag(tag_id)
        if not tag:
            return
        text = self.data.display_text(tag_id)
        if not messagebox.askyesno(
            "删除标签",
            f"确定从标签仓库删除「{text}」吗？\n"
            "（所有预设分组中的引用会一并移除，图片文件本身不会被删除）",
            parent=self.root,
        ):
            return
        self.data.delete_tag(tag_id)
        self.data.save()
        self.refresh_all()
        self.set_status(f"已删除标签：{text}")

    def remove_tag_from_group(self, tag_id: str, group_id: str) -> None:
        if self.presets.remove_tag(group_id, tag_id):
            self.data.save()
            self.workspace.rebuild()
            self.update_output()
            self.set_status("已从标签组移除（标签仍在仓库）")

    # ======================================================================
    # 标签点击 / 拖拽回调
    # ======================================================================
    def on_tag_clicked(self, widget: ImageTagWidget) -> None:
        if not widget.group_id:
            return
        new_state = self.presets.toggle_selected(widget.group_id, widget.tag_id)
        widget.selected = new_state
        widget.refresh_selection()
        self.update_output()
        self.data.save()
        self.set_status(f"{'选中' if new_state else '取消选中'}：{widget.display_text}")
        self.center_preview.show_tag(widget.tag_id)

    def on_tag_focused(self, widget: ImageTagWidget) -> None:
        """仓库标签单击：聚焦并把备注回填到输入框。"""
        self.warehouse.set_current_tag(widget.tag_id, fill_remark=True)
        self.center_preview.show_tag(widget.tag_id)
        LOG.info("聚焦仓库标签: %s（备注=%r）", widget.tag_id, widget.remark)
        self.set_status(f"正在编辑：{widget.display_text}（修改备注后点【保存】）")

    def on_tag_dropped(self, tag_id: str, source_group_id: Optional[str],
                       target_group_id: str, index: int) -> None:
        ok, msg, changed = self.presets.move_tag(tag_id, source_group_id, target_group_id, index)
        LOG.info(
            "拖拽落点(标签): tag=%s 源组=%s 目标组=%s 位置=%d -> %s",
            tag_id, source_group_id or "仓库", target_group_id, index, msg,
        )
        if not ok:
            self.set_status(f"拖拽失败：{msg}")
            return
        if changed:
            self.workspace.rebuild()
            self.update_output()
            self.data.save()
        self.set_status(msg)

    def on_tag_dropped_to_warehouse(self, tag_id: str, source_group_id: Optional[str]) -> None:
        if not source_group_id:
            LOG.info("标签本来就来自仓库，忽略拖回操作: %s", tag_id)
            return
        if self.presets.remove_tag(source_group_id, tag_id):
            self.data.save()
            self.workspace.rebuild()
            self.update_output()
            LOG.info("拖回仓库 = 从标签组移除: %s", tag_id)
            self.set_status("已从标签组移除（标签仍保留在仓库）")

    def on_group_dropped(self, group_id: str, target_group_id: str,
                         after: bool, source_panel=None) -> None:
        panels = self.workspace.group_panels()
        target_index = None
        for i, panel in enumerate(panels):
            if panel.group_id == target_group_id:
                target_index = i
                break
        if target_index is None:
            return
        if after:
            target_index += 1
        old = self.presets.group_index(group_id)
        if old >= 0 and old < target_index:
            target_index -= 1
        changed = self.presets.move_group(group_id, target_index)
        LOG.info(
            "拖拽落点(标签组): %s -> 目标=%s after=%s 计算索引=%d 变化=%s",
            group_id, target_group_id, after, target_index, changed,
        )
        if changed:
            self.data.save()
        self.workspace.rebuild()
        self.set_status("标签组顺序已更新" if changed else "标签组顺序未变化")

    def move_group_step(self, group_id: str, delta: int) -> None:
        index = self.presets.group_index(group_id)
        if index < 0:
            return
        new_index = index + delta
        if not (0 <= new_index < len(self.presets.groups())):
            return
        if self.presets.move_group(group_id, new_index):
            self.data.save()
        self.workspace.rebuild()

    # ======================================================================
    # 预设 / 标签组
    # ======================================================================
    def switch_preset(self, index: int) -> None:
        if not self.presets.switch(index):
            self.workspace.refresh_preset_labels()
            return
        self.workspace.rebuild()
        self.update_output()
        self.data.save()
        self.set_status(f"当前预设：{self.presets.active_preset()['name']}")

    def rename_preset(self, index: int, name: str) -> None:
        if self.presets.rename_preset(index, name):
            self.data.save()
            self.workspace.refresh_preset_labels()
            self.set_status(f"预设已重命名为：{name}")

    def create_group(self) -> None:
        group = self.presets.create_group()
        self.data.save()
        self.workspace.rebuild()
        self.set_status(f"已新建：{group['name']}")

    def rename_group(self, group_id: str, name: str) -> None:
        if self.presets.rename_group(group_id, name):
            self.data.save()
            self.workspace.rebuild()
            self.set_status(f"标签组已重命名为：{name}")

    def delete_group(self, group_id: str) -> None:
        if self.presets.delete_group(group_id):
            self.data.save()
            self.workspace.rebuild()
            self.update_output()
            self.set_status("标签组已删除")

    # ======================================================================
    # 预览
    # ======================================================================
    def open_preview(self, tag_id: str) -> None:
        tag = self.data.get_tag(tag_id)
        if not tag:
            LOG.warning("预览失败，标签不存在: %s", tag_id)
            return
        text = self.data.display_text(tag_id)
        LOG.info("打开预览窗口: %s (%s)", text, tag.get("img_path"))
        ImagePreviewWindow(self.root, tag.get("img_path", ""), title=text)

    def preview_path(self, path: str) -> None:
        ImagePreviewWindow(self.root, path, title=os.path.basename(path))

    # ======================================================================
    # 文件树回调
    # ======================================================================
    def on_file_tree_select(self, paths: List[str]) -> None:
        LOG.debug("文件树选中 %d 项", len(paths))
        if not paths:
            return
        images = [p for p in paths if config.is_image_file(p) and os.path.isfile(p)]
        if images:
            self.remember_folder(os.path.dirname(images[0]))
        panel = getattr(self, "center_preview", None)
        if images and panel is not None:
            # 单击文件树里的图片，也在中心区域直接看大图
            panel.show_path(
                images[0],
                title=os.path.splitext(os.path.basename(images[0]))[0],
                source="文件树",
            )
        if len(paths) == 1 and os.path.isfile(paths[0]):
            self.set_status(f"已选：{os.path.basename(paths[0])}")

    # ======================================================================
    # 一键命名（真实重命名）
    # ======================================================================
    def rename_selected_files(self) -> None:
        files = self.file_tree.get_selected_image_files()
        if not files:
            LOG.warning("一键命名失败：文件树未选中图片文件")
            messagebox.showwarning(
                "一键命名",
                f"请先在左侧文件树中选中要重命名的图片文件（{IMAGE_EXTS_TEXT}）。",
                parent=self.root,
            )
            return

        if not self.presets.selected_ids():
            # 不做模态确认（避免弹窗被遮挡后“点了没反应”），只提示并继续：
            # 命名预览里已经能看到结果，所见即所得。
            if self.timestamp_var.get():
                LOG.warning("一键命名：当前没有选中标签，文件名将只包含时间戳")
                self.set_status("未选中标签，文件名仅含时间戳")
            else:
                LOG.warning("一键命名：没有选中标签且未勾选时间戳，文件名将使用“未命名”")
                self.set_status("未选中标签且未加时间戳，将命名为“未命名”")

        base = config.sanitize_filename(self.build_name())
        self.update_output()
        LOG.info("开始一键命名，基准名=%s，待处理文件 %d 个", base, len(files))

        mapping = {}
        reserved = set()

        for i, src in enumerate(files):
            folder, filename = os.path.split(src)
            _, ext = os.path.splitext(filename)
            seq = i + 1
            dst = src
            while True:
                candidate = base if seq == 1 else f"{base} ({seq})"
                dst = os.path.join(folder, candidate + ext)
                same = os.path.normcase(dst) == os.path.normcase(src)
                taken = os.path.normcase(dst) in reserved
                exists = os.path.exists(dst) and not same
                if same or (not taken and not exists):
                    break
                seq += 1

            if os.path.normcase(dst) == os.path.normcase(src):
                LOG.info("文件名已一致，跳过: %s", src)
                continue

            try:
                os.rename(src, dst)
            except OSError as exc:
                LOG.error("重命名失败: %s -> %s (%s)", src, dst, exc)
                messagebox.showerror("重命名失败", f"{src}\n\n{exc}", parent=self.root)
                continue

            reserved.add(os.path.normcase(dst))
            mapping[src] = dst
            LOG.info("文件重命名: %s -> %s", os.path.basename(src), os.path.basename(dst))
            changed = self.data.remap_paths(src, dst)
            self.center_preview.remap_path(src, dst)
            if changed:
                LOG.info("同步标签路径 %d 个: %s", len(changed), "、".join(changed))

        if not mapping:
            self.set_status("没有文件需要重命名")
            LOG.info("一键命名结束：没有发生实际重命名")
            return

        self.data.save()
        new_paths = list(mapping.values())
        self.file_tree.mark_renamed(new_paths)
        # 保持原有滚动位置：重命名后的文件按规则排到末尾，不让视图跟着跳过去
        self.file_tree.refresh_all(select=new_paths, keep_view=True)
        self.refresh_all()                             # 标签缩略图按新路径重载
        LOG.info("一键命名完成，共重命名 %d 个文件", len(mapping))
        self.set_status(f"已重命名 {len(mapping)} 个文件")

    # ======================================================================
    # 关闭
    # ======================================================================
    def on_close(self) -> None:
        LOG.info("程序退出，正在保存数据…")
        self.data.save()
        LOG.info("已保存: %s", config.DATA_FILE)
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = ImageTagApp()
    app.run()


if __name__ == "__main__":
    main()
