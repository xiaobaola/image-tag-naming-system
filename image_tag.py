# -*- coding: utf-8 -*-
"""图片标签控件。

一个标签 = 圆角矩形 + 缩略图 + 备注文字（小字）。

交互：
* 单击（分组内）：切换选中 / 取消选中（亮色标记），同时在中心预览区显示大图
* 单击（仓库内）：聚焦该标签，把备注回填到右侧输入框，并在中心预览区显示大图
* 双击：打开图片预览窗口
* 右键：预览 / 编辑备注 / 删除 / 从本组移除
* 按住拖动：交给 DragManager 处理（拖入分组、跨组移动、拖回仓库移除）

尺寸：宽高由"缩略图尺寸 + 文字宽度 + 四周 5px padding"自适应决定。
"""
from __future__ import annotations

import logging
import tkinter as tk

import config
import image_utils
from config import (
    C_ACCENT, C_MISSING_BG, C_MISSING_BORDER, C_MISSING_TEXT,
    C_PANEL, C_TAG_BG, C_TAG_BORDER, C_TAG_FOCUS_BORDER, C_TAG_HOVER_BG,
    C_TAG_SEL_BG, C_TAG_SEL_BORDER, C_TAG_SEL_TEXT, C_TEXT,
    FONT_TAG, FONT_TINY,
    TAG_GAP, TAG_MIN_W, TAG_PADDING, TAG_RADIUS, TAG_TEXT_MAX_CHARS,
    THUMB_MAX_H, THUMB_MAX_W,
)
from widgets import draw_round_rect, get_font

LOG = logging.getLogger("image_tag")

DRAG_THRESHOLD = 6  # 鼠标位移超过该像素才判定为拖拽


class ImageTagWidget(tk.Canvas):
    """单个图片标签控件（Canvas 绘制，方便圆角 + 图片 + 文字混合排版）。"""

    DROP_KIND = None  # 标签自身不是放置目标

    def __init__(self, master, app, tag_id: str, group_id: str = None, bg: str = C_PANEL):
        self.app = app
        self.tag_id = tag_id
        self.group_id = group_id                 # None = 位于右侧仓库
        self.is_warehouse = group_id is None

        tag = app.data.get_tag(tag_id) or {}
        self.img_path = tag.get("img_path", "")
        self.remark = tag.get("remark", "")
        self.display_text = app.data.display_text(tag_id) or "（空标签）"
        self.short_text = self._shorten(self.display_text)
        self.selected = bool(group_id and app.presets.is_selected(group_id, tag_id))
        self._focused = False
        self._hover = False

        # 拖拽 / 点击状态
        self._press = None
        self._dragging = False
        self._suppress_toggle = False

        # 缩略图（等比例压缩，缓存复用）
        thumb = image_utils.make_thumbnail(self.img_path, THUMB_MAX_W, THUMB_MAX_H)
        self.thumb_photo = thumb["photo"]
        self.thumb_ok = thumb["ok"]
        self.thumb_reason = thumb.get("reason", "")
        tw, th = thumb["size"] if thumb["ok"] else (THUMB_MAX_W, THUMB_MAX_H)

        # 自适应尺寸：图片/文字取大者 + 四周 padding
        font = get_font(FONT_TAG)
        text_w = font.measure(self.short_text) + 6
        self._text_h = font.metrics("linespace")
        width = max(tw, text_w, TAG_MIN_W) + TAG_PADDING * 2
        height = TAG_PADDING * 2 + th + TAG_GAP + self._text_h
        # 注意：不能用 self._w / self._h，tkinter 内部用它保存控件路径名
        self._tag_w, self._tag_h = width, height
        self._thumb_size = (tw, th)

        super().__init__(
            master, width=width, height=height, bg=bg,
            highlightthickness=0, bd=0, takefocus=0,
        )
        self._draw()
        self._bind_events()

        if not self.thumb_ok:
            LOG.warning("标签 %s 图片不可用(%s): %s", tag_id, self.thumb_reason, self.img_path)
        else:
            LOG.debug("渲染标签 %s: 缩略图 %sx%s, 标签 %sx%s",
                      tag_id, tw, th, width, height)

    # ======================================================================
    # 绘制
    # ======================================================================
    @staticmethod
    def _shorten(text: str) -> str:
        text = (text or "").strip()
        if len(text) > TAG_TEXT_MAX_CHARS:
            return text[: TAG_TEXT_MAX_CHARS - 1] + "…"
        return text or "（无备注）"

    def _colors(self):
        """按状态返回 (填充色, 描边色, 描边宽度, 文字色)。"""
        if self.selected:
            return C_TAG_SEL_BG, C_TAG_SEL_BORDER, 3, C_TAG_SEL_TEXT
        if self._focused:
            return C_TAG_HOVER_BG, C_TAG_FOCUS_BORDER, 2, C_TEXT
        if self._hover:
            return C_TAG_HOVER_BG, C_ACCENT, 2, C_TEXT
        return C_TAG_BG, C_TAG_BORDER, 1, C_TEXT

    def _draw(self) -> None:
        self.delete("all")
        w, h = self._tag_w, self._tag_h
        fill, outline, lw, text_color = self._colors()

        draw_round_rect(
            self, lw, lw, w - lw, h - lw, TAG_RADIUS,
            fill=fill, outline=outline, width=lw,
        )

        tw, th = self._thumb_size
        cx = w / 2
        top = TAG_PADDING
        if self.thumb_ok and self.thumb_photo is not None:
            self.create_image(cx, top + th / 2, image=self.thumb_photo, tags="thumb")
        else:
            # 占位图：灰色区域 + "图片不存在" 提示
            x1, y1 = cx - tw / 2, top
            x2, y2 = cx + tw / 2, top + th
            self.create_rectangle(
                x1, y1, x2, y2, fill=C_MISSING_BG,
                outline=C_MISSING_BORDER, dash=(3, 2),
            )
            self.create_text(
                cx, top + th / 2, text="图片不存在",
                font=FONT_TINY, fill=C_MISSING_TEXT, tags="miss",
            )

        self.create_text(
            cx, top + th + TAG_GAP + self._text_h / 2,
            text=self.short_text, font=FONT_TAG, fill=text_color, tags="label",
        )

        if self.selected:  # 右上角勾选徽标
            r = 8
            bx, by = w - r - 3, r + 3
            self.create_oval(bx - r, by - r, bx + r, by + r, fill=C_ACCENT, outline="")
            self.create_text(bx, by, text="✓", fill="white", font=("Microsoft YaHei UI", 8, "bold"))

    # ======================================================================
    # 事件
    # ======================================================================
    def _bind_events(self) -> None:
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Double-Button-1>", self._on_double_click)
        self.bind("<Button-3>", self._on_right_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self.configure(cursor="hand2")
        self._draw()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self.configure(cursor="")
        self._draw()

    def _on_press(self, event) -> None:
        self._press = (event.x_root, event.y_root)
        self._dragging = False

    def _on_motion(self, event) -> None:
        if self._press is None or self._dragging:
            return
        dx = abs(event.x_root - self._press[0])
        dy = abs(event.y_root - self._press[1])
        if max(dx, dy) >= DRAG_THRESHOLD:
            self._dragging = True
            self.configure(cursor="fleur")
            LOG.debug("检测到拖拽手势: 标签 %s", self.tag_id)
            self.app.drag.begin_tag(self, event.x_root, event.y_root)

    def _on_release(self, event) -> None:
        was_dragging = self._dragging
        self._press = None
        self._dragging = False
        self.configure(cursor="hand2" if self._hover else "")
        if was_dragging:
            return  # 落点处理由 DragManager 完成

        if self._suppress_toggle:
            self._suppress_toggle = False
            return

        if self.is_warehouse:
            self.app.on_tag_focused(self)
        else:
            self.app.on_tag_clicked(self)

    def _on_double_click(self, _event) -> None:
        # 双击 = 单击一次 + 打开预览（抑制第二次释放时的重复切换）
        self._suppress_toggle = True
        self._press = None
        self._dragging = False
        LOG.info("双击标签，打开预览: %s", self.tag_id)
        self.app.open_preview(self.tag_id)

    def _on_right_click(self, event) -> None:
        menu = tk.Menu(self, tearoff=0, font=config.FONT_NORMAL)
        menu.add_command(label="预览图片", command=lambda: self.app.open_preview(self.tag_id))
        menu.add_command(label="编辑备注", command=lambda: self.app.edit_remark(self.tag_id))
        if not self.is_warehouse:
            menu.add_separator()
            menu.add_command(
                label="取消选中" if self.selected else "选中该标签",
                command=lambda: self.app.on_tag_clicked(self),
            )
            menu.add_command(
                label="从本组移除",
                command=lambda: self.app.remove_tag_from_group(self.tag_id, self.group_id),
            )
        menu.add_separator()
        menu.add_command(label="删除标签（从仓库）", command=lambda: self.app.delete_tag(self.tag_id))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ======================================================================
    # 外部刷新
    # ======================================================================
    def refresh_selection(self) -> None:
        """数据层变化后刷新选中态（不重建控件）。"""
        if self.group_id:
            self.selected = self.app.presets.is_selected(self.group_id, self.tag_id)
        else:
            self.selected = False
        self._draw()

    def set_focused(self, focused: bool) -> None:
        if self._focused != bool(focused):
            self._focused = bool(focused)
            self._draw()
