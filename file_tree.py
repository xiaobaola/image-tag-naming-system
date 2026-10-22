# -*- coding: utf-8 -*-
"""左侧 Windows 文件树模块。

功能：
* 枚举本机所有盘符根节点，文件夹双击展开 / 收起，子节点懒加载
* 图片文件可选中（jpg/png/jpeg/bmp/gif/webp），可多选
* 排序规则：文件夹在前、文件在后；文件名中的 (2)(10) 按数值从小到大；
  本次会话中"被一键命名过"的文件统一排到末尾
* 重命名后刷新目录但 **保持展开状态**，并恢复选中
"""
from __future__ import annotations

import logging
import os
import re
import string
import tkinter as tk
from tkinter import ttk
from typing import Iterable, List, Optional, Tuple

import config
from config import (
    C_BG, C_BORDER, C_PANEL, C_TEXT, C_TEXT_SUB, C_TREE_DIR, C_TREE_FILE,
    C_TREE_IMG, C_TREE_RENAMED,
    FONT_BOLD, FONT_SMALL, FONT_TREE,
)

LOG = logging.getLogger("file_tree")

PLACEHOLDER_SUFFIX = "::ph"


# --------------------------------------------------------------------------
# 排序
# --------------------------------------------------------------------------
def natural_key(name: str) -> list:
    """自然排序键：把连续数字当作整数比较，""a (2)"" < ""a (10)""。"""
    parts = re.split(r"(\d+)", name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def list_drives() -> List[str]:
    """枚举当前系统存在的盘符，如 ['C:\\', 'D:\\']。"""
    drives = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if os.path.exists(root):
                drives.append(root)
        except OSError:
            continue
    return drives


class FileTreePanel(tk.Frame):
    """Windows 文件树面板。"""

    def __init__(self, master, app):
        super().__init__(master, bg=C_PANEL, highlightbackground=C_BORDER, highlightthickness=2)
        self.app = app
        self._renamed: set = set()      # 本次会话被重命名过的文件（normcase）
        self.status_var = tk.StringVar(value="未选择文件")

        self._build()
        self.refresh_all()

    # ======================================================================
    # 构建
    # ======================================================================
    def _build(self) -> None:
        header = tk.Frame(self, bg=C_PANEL)
        header.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(
            header, text="文件树", font=FONT_BOLD, bg=C_PANEL, fg=C_TEXT, anchor="w",
        ).pack(side="left")
        ttk.Button(
            header, text="刷新", style="Small.TButton", command=self.refresh_all,
        ).pack(side="right")

        tk.Label(
            self, text=f"可选中图片（支持多选）\n"
                       f"{config.IMAGE_EXTS_TEXT}｜单击即预览\n"
                       "选中后点右侧【＋ 从文件树新建图片标签】",
            font=FONT_SMALL, bg=C_PANEL, fg=C_TEXT_SUB, anchor="w",
            justify="left", wraplength=270,
        ).pack(fill="x", padx=10, pady=(2, 6))

        body = tk.Frame(self, bg=C_PANEL)
        body.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(body, show="tree", selectmode="extended", height=20)
        self.tree.column("#0", width=200, stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vbar = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar = ttk.Scrollbar(body, orient="horizontal", command=self.tree.xview)
        hbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self.tree.tag_configure("dir", foreground=C_TREE_DIR, font=FONT_TREE)
        self.tree.tag_configure("img", foreground=C_TREE_IMG, font=FONT_TREE)
        self.tree.tag_configure("file", foreground=C_TREE_FILE, font=FONT_TREE)
        self.tree.tag_configure("renamed", foreground=C_TREE_RENAMED, font=FONT_TREE)

        self.tree.bind("<<TreeviewOpen>>", self._on_open)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-Button-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

        tk.Label(
            self, textvariable=self.status_var, font=FONT_SMALL,
            bg=C_PANEL, fg=C_TEXT_SUB, anchor="w", justify="left", wraplength=270,
        ).pack(fill="x", padx=10, pady=(0, 8))

    # ======================================================================
    # 内容填充
    # ======================================================================
    def _insert_drives(self) -> None:
        for drive in list_drives():
            iid = os.path.normpath(drive)
            try:
                self.tree.insert("", "end", iid=iid, text=drive, tags=("dir",), open=False)
                self.tree.insert(iid, "end", iid=iid + PLACEHOLDER_SUFFIX, text="加载中…")
            except tk.TclError as exc:
                LOG.warning("插入盘符失败 %s: %s", drive, exc)
        LOG.info("文件树已加载盘符: %s", ", ".join(list_drives()) or "无")

    def _scan(self, path: str) -> List[Tuple[bool, str, str]]:
        """扫描目录，返回 [(是否目录, 名称, 全路径)]，已按规则排序。"""
        dirs: List[Tuple[str, str]] = []
        files: List[Tuple[str, str]] = []
        try:
            with os.scandir(path) as iterator:
                for entry in iterator:
                    try:
                        if entry.is_dir():
                            dirs.append((entry.name, os.path.normpath(entry.path)))
                        elif entry.is_file():
                            files.append((entry.name, os.path.normpath(entry.path)))
                    except OSError:  # 单个条目失败不影响整体
                        continue
        except (PermissionError, OSError) as exc:
            LOG.warning("目录不可访问 %s: %s", path, exc)
            return []

        dirs.sort(key=lambda item: natural_key(item[0]))
        # 被命名过的文件排到最后，其余按自然排序（(2) 在 (10) 前面）
        files.sort(key=lambda item: (
            1 if os.path.normcase(item[1]) in self._renamed else 0,
            natural_key(item[0]),
        ))
        return [(True, n, p) for n, p in dirs] + [(False, n, p) for n, p in files]

    def _populate(self, node: str) -> None:
        """加载 node 的子节点（先清空原有子节点）。"""
        path = node
        try:
            for child in self.tree.get_children(node):
                self.tree.delete(child)
        except tk.TclError:
            return
        if not os.path.isdir(path):
            return

        for is_dir, name, full in self._scan(path):
            iid = full
            if self.tree.exists(iid):  # 极端情况下同名占位
                continue
            if is_dir:
                tag = "dir"
                text = name
            elif config.is_image_file(full):
                tag = "renamed" if os.path.normcase(full) in self._renamed else "img"
                text = name
            else:
                tag = "file"
                text = name
            try:
                self.tree.insert(node, "end", iid=iid, text=text, tags=(tag,))
                if is_dir:
                    self.tree.insert(iid, "end", iid=iid + PLACEHOLDER_SUFFIX, text="加载中…")
            except tk.TclError as exc:
                LOG.warning("插入节点失败 %s: %s", full, exc)

        LOG.debug("已加载目录 %s，子项 %d 个", path, len(self.tree.get_children(node)))

    # ======================================================================
    # 事件
    # ======================================================================
    def _on_open(self, _event=None) -> None:
        node = self.tree.focus()
        if not node or node.endswith(PLACEHOLDER_SUFFIX):
            return
        if os.path.isdir(node):
            self._populate(node)
            LOG.debug("展开目录: %s", node)

    def _on_select(self, _event=None) -> None:
        paths = self.get_selected_paths()
        images = [p for p in paths if config.is_image_file(p) and os.path.isfile(p)]
        if not paths:
            self.status_var.set("未选择文件")
        elif images:
            names = "、".join(os.path.basename(p) for p in images[:3])
            more = " 等" if len(images) > 3 else ""
            self.status_var.set(f"已选图片 {len(images)} 个：{names}{more}")
            LOG.info("文件树选中图片: %s", names + more)
        else:
            self.status_var.set(f"已选中 {len(paths)} 项（非图片文件）")
        self.app.on_file_tree_select(paths)

    def _on_double_click(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid.endswith(PLACEHOLDER_SUFFIX):
            return "break"
        if os.path.isdir(iid):
            if self._is_open(iid):
                self.tree.item(iid, open=False)
            else:
                self._populate(iid)
                self.tree.item(iid, open=True)
            return "break"
        if config.is_image_file(iid):
            LOG.info("文件树双击图片，打开预览: %s", iid)
            self.app.preview_path(iid)
            return "break"
        return "break"

    def _on_right_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid and not iid.endswith(PLACEHOLDER_SUFFIX):
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
        menu = tk.Menu(self, tearoff=0, font=config.FONT_NORMAL)
        menu.add_command(label="新建图片标签", command=self.app.create_tag_from_tree)
        if iid and config.is_image_file(iid):
            menu.add_command(label="预览图片", command=lambda: self.app.preview_path(iid))
        menu.add_separator()
        menu.add_command(label="刷新文件树", command=self.refresh_all)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ======================================================================
    # 查询
    # ======================================================================
    def _is_open(self, iid: str) -> bool:
        try:
            return str(self.tree.item(iid, "open")) in ("1", "True", "true")
        except tk.TclError:
            return False

    def get_selected_paths(self) -> List[str]:
        result = []
        try:
            for iid in self.tree.selection():
                if iid.endswith(PLACEHOLDER_SUFFIX):
                    continue
                if self.tree.exists(iid):
                    result.append(iid)
        except tk.TclError:
            pass
        return result

    def get_selected_image_files(self) -> List[str]:
        """返回当前选中的图片文件（保持树中的显示顺序）。"""
        selected = set(self.get_selected_paths())
        images = [p for p in selected if config.is_image_file(p) and os.path.isfile(p)]

        # 按父目录 + 树中顺序排列，保证命名编号稳定
        def sort_key(path: str):
            parent = os.path.dirname(path)
            try:
                siblings = self.tree.get_children(parent)
                return (parent, siblings.index(path) if path in siblings else 9999)
            except tk.TclError:
                return (parent, 9999)

        images.sort(key=sort_key)
        return images

    def get_first_selected_image(self) -> Optional[str]:
        images = self.get_selected_image_files()
        return images[0] if images else None

    # ======================================================================
    # 刷新 / 重命名
    # ======================================================================
    def _collect_open_paths(self) -> List[str]:
        opened: List[str] = []

        def walk(parent: str) -> None:
            try:
                children = self.tree.get_children(parent)
            except tk.TclError:
                return
            for iid in children:
                if iid.endswith(PLACEHOLDER_SUFFIX):
                    continue
                if os.path.isdir(iid) and self._is_open(iid):
                    opened.append(iid)
                    walk(iid)

        walk("")
        return opened

    def mark_renamed(self, paths: Iterable[str]) -> None:
        for path in paths:
            self._renamed.add(os.path.normcase(path))
        LOG.info("已记录重命名文件 %d 个（将排到列表末尾）", len(self._renamed))

    def refresh_all(self, select: Optional[Iterable[str]] = None,
                    keep_view: bool = False) -> None:
        """整树刷新：保持展开状态，并恢复选中项。

        keep_view=True：保持刷新前的滚动位置，不自动跳到选中项
        （一键命名后被命名的文件会排到末尾，避免视图跟着乱跳）。
        """
        open_paths = self._collect_open_paths()
        targets = list(select) if select is not None else self.get_selected_paths()
        try:
            top_frac = self.tree.yview()[0]
        except tk.TclError:
            top_frac = 0.0

        try:
            self.tree.delete(*self.tree.get_children(""))
        except tk.TclError:
            pass

        self._insert_drives()

        # 先浅后深地恢复展开
        for path in sorted(open_paths, key=len):
            self._open_path(path)

        restored = []
        for path in targets:
            try:
                if self.tree.exists(path):
                    restored.append(path)
            except tk.TclError:
                continue
        if restored:
            try:
                self.tree.selection_set(restored)
                self.tree.focus(restored[0])
                if not keep_view:
                    self.tree.see(restored[0])
            except tk.TclError:
                pass

        if keep_view:
            try:
                self.tree.update_idletasks()
                self.tree.yview_moveto(top_frac)
            except tk.TclError:
                pass

        LOG.info("文件树刷新完成：恢复展开目录 %d 个，恢复选中 %d 项，保持视图=%s",
                 len(open_paths), len(restored), keep_view)

    def _open_path(self, path: str) -> bool:
        """展开指定目录（父级必须已展开）。"""
        iid = os.path.normpath(path)
        try:
            if not self.tree.exists(iid):
                return False
            self._populate(iid)
            self.tree.item(iid, open=True)
            return True
        except tk.TclError:
            return False

    def open_directory(self, path: str) -> bool:
        """展开到指定目录（传文件则取其父目录）并滚动到该位置（不选中）。"""
        if not path:
            return False
        path = os.path.normpath(os.path.abspath(path))
        if os.path.isfile(path):
            path = os.path.dirname(path)
        if not os.path.isdir(path):
            LOG.info("目录不存在，跳转文件树失败: %s", path)
            return False

        chain = []
        folder = path
        while True:
            chain.append(folder)
            parent = os.path.dirname(folder)
            if not parent or parent == folder:
                break
            folder = parent

        opened = 0
        for item in sorted(chain, key=len):  # 父目录先展开
            if self._open_path(item):
                opened += 1
        try:
            self.update_idletasks()
            if self.tree.exists(path):
                # 优先露出目录里的第一个子项，避免目录刚好卡在可视区最底部
                children = [
                    child for child in self.tree.get_children(path)
                    if not child.endswith(PLACEHOLDER_SUFFIX)
                ]
                self.tree.see(children[0] if children else path)
                LOG.info("文件树定位到目录: %s（展开 %d 层）", path, opened)
                return True
        except tk.TclError:
            pass
        return False

    def reveal_path(self, path: str) -> None:
        """展开到某个文件所在目录并选中它（重命名后定位用）。"""
        path = os.path.normpath(path)
        folder = os.path.dirname(path)
        chain = []
        while folder:
            chain.append(folder)
            parent = os.path.dirname(folder)
            if parent == folder:
                break
            folder = parent
        for item in sorted(set(chain), key=len):
            self._open_path(item)
        try:
            if self.tree.exists(path):
                self.tree.selection_set(path)
                self.tree.focus(path)
                self.tree.see(path)
        except tk.TclError:
            pass
