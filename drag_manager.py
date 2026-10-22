# -*- coding: utf-8 -*-
"""拖拽管理模块。

统一处理两类拖拽：
* 图片标签拖拽：仓库 -> 分组、分组 -> 分组、分组 -> 仓库（删除/移除）、组内排序
* 标签组拖拽：拖动分组标题栏改变分组顺序

实现方式：
1. 起始控件检测到鼠标位移超过阈值后调用 begin_tag / begin_group；
2. 本模块创建一个半透明"影子窗口"跟随鼠标；
3. 通过 winfo_containing 命中测试 + 向上查找 DROP_KIND 属性定位放置目标；
4. 松开鼠标后先清理影子窗口，再回调主程序完成数据变更。

注意：目标组件需要提供 DROP_KIND 属性（"group" / "warehouse"）。
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Optional

from config import (
    C_ACCENT, C_PANEL, C_TAG_BORDER, C_TEXT, FONT_TAG,
)

LOG = logging.getLogger("drag")


class DragManager:
    """全局拖拽管理器（整个应用共用一个实例）。"""

    def __init__(self, app):
        self.app = app
        self.root: tk.Tk = app.root
        self.kind: Optional[str] = None
        self.payload: Optional[dict] = None
        self._ghost: Optional[tk.Toplevel] = None
        self._hover = None
        self._active = False

    # ======================================================================
    # 开始拖拽
    # ======================================================================
    def begin_tag(self, tag_widget, x_root: int, y_root: int) -> None:
        """开始拖拽一个图片标签。"""
        self._begin(
            kind="tag",
            payload={
                "tag_id": tag_widget.tag_id,
                "group_id": tag_widget.group_id,
                "widget": tag_widget,
            },
            x_root=x_root,
            y_root=y_root,
            text=tag_widget.short_text,
            image=getattr(tag_widget, "thumb_photo", None),
            source=tag_widget,
        )

    def begin_group(self, group_panel, x_root: int, y_root: int) -> None:
        """开始拖拽一个标签组（按住标题栏）。"""
        self._begin(
            kind="group",
            payload={"group_id": group_panel.group_id, "panel": group_panel},
            x_root=x_root,
            y_root=y_root,
            text=group_panel.title_text,
            image=None,
            source=group_panel,
        )

    def _begin(self, kind: str, payload: dict, x_root: int, y_root: int,
               text: str, image, source) -> None:
        self._finish()
        self.kind = kind
        self.payload = payload
        self._active = True

        try:
            ghost = tk.Toplevel(self.root)
            ghost.overrideredirect(True)
            ghost.attributes("-topmost", True)
            try:
                ghost.attributes("-alpha", 0.88)
            except tk.TclError:
                pass
            frame = tk.Frame(ghost, bg=C_TAG_BORDER, bd=0)
            frame.pack()
            label = tk.Label(
                frame,
                text=(text or "标签")[:12],
                image=image if image is not None else "",
                compound="top" if image is not None else "none",
                bg=C_PANEL, fg=C_TEXT, font=FONT_TAG,
                padx=6, pady=4, bd=0,
            )
            label.pack(padx=1, pady=1)
            ghost.geometry(f"+{x_root + 20}+{y_root + 18}")
            self._ghost = ghost
        except tk.TclError as exc:  # 影子窗口创建失败不致命
            LOG.warning("拖拽影子窗口创建失败: %s", exc)
            self._ghost = None

        self.root.bind_all("<B1-Motion>", self._on_motion, add="+")
        self.root.bind_all("<ButtonRelease-1>", self._on_release, add="+")

        if kind == "tag":
            LOG.info("拖拽开始(标签): %s | 来源分组=%s", payload["tag_id"], payload["group_id"] or "仓库")
        else:
            LOG.info("拖拽开始(标签组): %s", payload["group_id"])

    # ======================================================================
    # 拖拽过程
    # ======================================================================
    def _on_motion(self, event) -> None:
        if not self._active:
            return
        if self._ghost is not None:
            try:
                self._ghost.geometry(f"+{event.x_root + 20}+{event.y_root + 18}")
            except tk.TclError:
                pass

        target = self._target_at(event.x_root, event.y_root)
        if target is not self._hover:
            self._highlight(self._hover, False)
            self._hover = target
            self._highlight(self._hover, True)
            if target is not None:
                LOG.debug("拖拽悬停目标: %s", getattr(target, "DROP_KIND", "?"))

    def _on_release(self, event) -> None:
        if not self._active:
            return
        kind = self.kind
        payload = dict(self.payload or {})
        x_root, y_root = event.x_root, event.y_root
        target = self._target_at(x_root, y_root)

        # 先彻底清理影子窗口与全局绑定，再回调业务（业务可能销毁被拖拽控件）
        self._finish()

        try:
            if kind == "tag":
                self._drop_tag(payload, target, x_root, y_root)
            elif kind == "group":
                self._drop_group(payload, target, x_root, y_root)
        except Exception as exc:  # noqa: BLE001 - 拖拽异常不能影响主流程
            LOG.exception("拖拽落点处理异常: %s", exc)

    def _drop_tag(self, payload: dict, target, x_root: int, y_root: int) -> None:
        tag_id = payload.get("tag_id")
        source_group = payload.get("group_id")
        if target is None:
            LOG.info("拖拽取消(标签): %s 未落在有效区域", tag_id)
            return

        drop_kind = getattr(target, "DROP_KIND", None)
        if drop_kind == "group":
            index = target.index_at(x_root, y_root)
            self.app.on_tag_dropped(tag_id, source_group, target.group_id, index)
        elif drop_kind == "warehouse":
            self.app.on_tag_dropped_to_warehouse(tag_id, source_group)
        else:
            LOG.info("拖拽取消(标签): 目标类型 %s 不接受标签", drop_kind)

    def _drop_group(self, payload: dict, target, x_root: int, y_root: int) -> None:
        group_id = payload.get("group_id")
        panel = payload.get("panel")
        drop_kind = getattr(target, "DROP_KIND", None) if target is not None else None
        if drop_kind != "group":
            LOG.info("拖拽取消(标签组): %s 未落在其它标签组上", group_id)
            return
        # 落在目标组的上半部 => 插到目标之前；下半部 => 之后
        top = target.winfo_rooty()
        height = max(target.winfo_height(), 1)
        after = y_root > top + height / 2
        self.app.on_group_dropped(group_id, target.group_id, after=after, source_panel=panel)

    # ======================================================================
    # 目标查找
    # ======================================================================
    def _target_at(self, x_root: int, y_root: int):
        """命中测试：从鼠标下的控件向上查找带 DROP_KIND 的容器。"""
        try:
            widget = self.root.winfo_containing(x_root, y_root)
        except tk.TclError:
            return None
        while widget is not None:
            # 忽略影子窗口自身
            if self._ghost is not None:
                try:
                    if widget.winfo_toplevel() is self._ghost:
                        widget = getattr(widget, "master", None)
                        continue
                except tk.TclError:
                    return None
            if hasattr(widget, "DROP_KIND"):
                return widget
            widget = getattr(widget, "master", None)
        return None

    def _highlight(self, widget, on: bool) -> None:
        if widget is None:
            return
        setter = getattr(widget, "set_drop_highlight", None)
        if callable(setter):
            try:
                setter(on)
            except tk.TclError:
                pass

    # ======================================================================
    # 清理
    # ======================================================================
    def _finish(self) -> None:
        self._highlight(self._hover, False)
        self._hover = None
        self._active = False
        self.kind = None
        self.payload = None
        try:
            self.root.unbind_all("<B1-Motion>")
            self.root.unbind_all("<ButtonRelease-1>")
        except tk.TclError:
            pass
        if self._ghost is not None:
            try:
                self._ghost.destroy()
            except tk.TclError:
                pass
            self._ghost = None

    def cancel(self) -> None:
        """外部取消拖拽（例如按 ESC）。"""
        if self._active:
            LOG.info("拖拽被取消")
            self._finish()
