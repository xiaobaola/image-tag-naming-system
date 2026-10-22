# -*- coding: utf-8 -*-
"""预设 / 标签组 业务逻辑模块。

* 5 套预设互斥单选：同一时刻只有一套预设生效。
* 每套预设独立保存自己的标签组，互不干扰。
* 标签对象本身全局共享（标签仓库只有一份），预设里保存的是 tag_id 引用。
* 分组的排序、标签的加入/移除/组内排序、选中状态都集中在这里，UI 只负责渲染。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from config import PRESET_COUNT
from data_store import DataStore

LOG = logging.getLogger("preset")


class PresetManager:
    """预设与标签组的唯一业务入口。"""

    def __init__(self, store: DataStore):
        self.store = store

    # ======================================================================
    # 预设
    # ======================================================================
    @property
    def presets(self) -> List[dict]:
        return self.store.presets

    @property
    def count(self) -> int:
        return len(self.store.presets)

    def active_index(self) -> int:
        index = self.store.active_preset
        if not (0 <= index < len(self.store.presets)):
            index = 0
        return index

    def active_preset(self) -> dict:
        return self.store.presets[self.active_index()]

    def preset_name(self, index: int) -> str:
        if 0 <= index < len(self.store.presets):
            return self.store.presets[index]["name"]
        return f"预设{index + 1}"

    def switch(self, index: int) -> bool:
        """互斥切换预设（单选）。"""
        if not (0 <= index < self.count):
            LOG.warning("切换到不存在的预设: %s", index)
            return False
        if index == self.store.active_preset:
            LOG.debug("预设未变化: 预设%d", index + 1)
            return False
        self.store.active_preset = index
        preset = self.active_preset()
        LOG.info("预设切换 -> 预设%d(%s)，分组数=%d", index + 1, preset["name"], len(preset["groups"]))
        return True

    def rename_preset(self, index: int, name: str) -> bool:
        if not (0 <= index < self.count):
            return False
        name = (name or "").strip()
        if not name:
            return False
        self.store.presets[index]["name"] = name
        LOG.info("重命名预设%d -> %s", index + 1, name)
        return True

    # ======================================================================
    # 标签组
    # ======================================================================
    def groups(self) -> List[dict]:
        return self.active_preset()["groups"]

    def get_group(self, group_id: str) -> Optional[dict]:
        for preset in self.store.presets:
            for group in preset["groups"]:
                if group["group_id"] == group_id:
                    return group
        return None

    def get_active_group(self, group_id: str) -> Optional[dict]:
        for group in self.groups():
            if group["group_id"] == group_id:
                return group
        return None

    def group_index(self, group_id: str) -> int:
        for i, group in enumerate(self.groups()):
            if group["group_id"] == group_id:
                return i
        return -1

    def create_group(self, name: str = "") -> dict:
        preset = self.active_preset()
        group = self.store._make_group(len(preset["groups"]), name)  # noqa: SLF001 - 同一数据层
        preset["groups"].append(group)
        LOG.info("新建标签组: %s（预设: %s，当前共 %d 组）",
                 group["name"], preset["name"], len(preset["groups"]))
        return group

    def rename_group(self, group_id: str, name: str) -> bool:
        group = self.get_active_group(group_id)
        name = (name or "").strip()
        if group is None or not name:
            return False
        LOG.info("重命名标签组: %s -> %s", group["name"], name)
        group["name"] = name
        return True

    def delete_group(self, group_id: str) -> bool:
        preset = self.active_preset()
        for i, group in enumerate(preset["groups"]):
            if group["group_id"] == group_id:
                if len(preset["groups"]) <= 1:
                    LOG.warning("至少保留一个标签组，删除被拒绝")
                    return False
                preset["groups"].pop(i)
                LOG.info("删除标签组: %s（预设: %s）", group["name"], preset["name"])
                return True
        return False

    def move_group(self, group_id: str, to_index: int) -> bool:
        """标签组拖拽排序。"""
        preset = self.active_preset()
        groups = preset["groups"]
        old = -1
        for i, group in enumerate(groups):
            if group["group_id"] == group_id:
                old = i
                break
        if old < 0:
            LOG.warning("排序失败，找不到标签组: %s", group_id)
            return False
        group = groups.pop(old)
        to_index = max(0, min(int(to_index), len(groups)))
        groups.insert(to_index, group)
        LOG.info("标签组排序: %s 从位置 %d 移到 %d", group["name"], old + 1, to_index + 1)
        return old != to_index

    # ======================================================================
    # 标签与分组的关联
    # ======================================================================
    def add_tag(self, group_id: str, tag_id: str, index: Optional[int] = None) -> Tuple[bool, str]:
        """把仓库标签加入分组（已存在则忽略）。"""
        group = self.get_active_group(group_id)
        if group is None:
            return False, "目标标签组不存在"
        if tag_id not in self.store.tags:
            return False, "标签不存在"
        if tag_id in group["tag_ids"]:
            return False, "该标签已在本组"
        if index is None or index < 0 or index > len(group["tag_ids"]):
            index = len(group["tag_ids"])
        group["tag_ids"].insert(index, tag_id)
        LOG.info("标签加入分组: %s -> %s（位置 %d）", tag_id, group["name"], index + 1)
        return True, "已加入"

    def remove_tag(self, group_id: str, tag_id: str) -> bool:
        group = self.get_active_group(group_id)
        if group is None or tag_id not in group["tag_ids"]:
            return False
        group["tag_ids"].remove(tag_id)
        if tag_id in group["selected_ids"]:
            group["selected_ids"].remove(tag_id)
        LOG.info("标签移出分组: %s <- %s", tag_id, group["name"])
        return True

    def move_tag(self, tag_id: str, source_group_id: Optional[str],
                 target_group_id: str, index: Optional[int] = None) -> Tuple[bool, str, bool]:
        """拖拽移动 / 组内排序。

        返回 (是否成功, 说明, 数据是否发生变化)。
        """
        target = self.get_active_group(target_group_id)
        if target is None:
            return False, "目标标签组不存在", False
        if tag_id not in self.store.tags:
            return False, "标签不存在", False

        ids = target["tag_ids"]

        # --- 情况一：组内排序 ---
        if source_group_id == target_group_id:
            if tag_id not in ids:
                return False, "标签不在该组", False
            old = ids.index(tag_id)
            ids.pop(old)
            if index is None or index > len(ids):
                index = len(ids)
            if index > old:
                index -= 1
            ids.insert(index, tag_id)
            changed = old != index
            LOG.info("组内排序: %s 在 [%s] 从 %d 移到 %d", tag_id, target["name"], old + 1, index + 1)
            return True, "组内排序完成", changed

        # --- 情况二：跨组移动（源组必须移除） ---
        source = self.get_active_group(source_group_id) if source_group_id else None
        was_selected = False
        if source is not None and tag_id in source["tag_ids"]:
            was_selected = tag_id in source["selected_ids"]
            source["tag_ids"].remove(tag_id)
            if tag_id in source["selected_ids"]:
                source["selected_ids"].remove(tag_id)
            LOG.info("跨组拖拽: 源组 [%s] 已移除 %s", source["name"], tag_id)

        if tag_id in ids:  # 目标组已有：合并，不做重复插入
            LOG.info("目标组 [%s] 已存在该标签，执行合并", target["name"])
            return True, "目标组已有该标签，已合并", True

        if index is None or index < 0 or index > len(ids):
            index = len(ids)
        ids.insert(index, tag_id)
        if was_selected:  # 选中状态跟随标签移动
            target["selected_ids"].append(tag_id)
        LOG.info("跨组拖拽: 目标组 [%s] 已加入 %s（位置 %d，选中=%s）",
                 target["name"], tag_id, index + 1, was_selected)
        return True, "已移动", True

    # ======================================================================
    # 选中状态
    # ======================================================================
    def is_selected(self, group_id: str, tag_id: str) -> bool:
        group = self.get_group(group_id)
        return bool(group and tag_id in group["selected_ids"])

    def toggle_selected(self, group_id: str, tag_id: str) -> bool:
        """点击标签切换选中 / 取消选中，返回切换后的状态。"""
        group = self.get_active_group(group_id)
        if group is None or tag_id not in group["tag_ids"]:
            return False
        if tag_id in group["selected_ids"]:
            group["selected_ids"].remove(tag_id)
            selected = False
        else:
            group["selected_ids"].append(tag_id)
            selected = True
        LOG.info("标签选中变更: [%s] %s(%s) -> %s",
                 group["name"], self.store.display_text(tag_id), tag_id,
                 "选中" if selected else "取消选中")
        return selected

    def set_selected(self, group_id: str, tag_id: str, selected: bool) -> None:
        group = self.get_active_group(group_id)
        if group is None or tag_id not in group["tag_ids"]:
            return
        if selected and tag_id not in group["selected_ids"]:
            group["selected_ids"].append(tag_id)
        elif not selected and tag_id in group["selected_ids"]:
            group["selected_ids"].remove(tag_id)

    def selected_ids(self) -> List[str]:
        """按 [组从上到下] + [组内从左到右] 的顺序返回选中的 tag_id（去重）。"""
        ordered: List[str] = []
        for group in self.groups():
            for tag_id in group["tag_ids"]:
                if tag_id in group["selected_ids"] and tag_id not in ordered:
                    ordered.append(tag_id)
        return ordered

    def group_of_tag(self, tag_id: str) -> Optional[str]:
        for group in self.groups():
            if tag_id in group["tag_ids"]:
                return group["group_id"]
        return None

    def prune_missing_tags(self) -> int:
        """清理所有分组中指向已不存在标签的引用（防御性）。"""
        removed = 0
        for preset in self.store.presets:
            for group in preset["groups"]:
                before = len(group["tag_ids"])
                group["tag_ids"] = [t for t in group["tag_ids"] if t in self.store.tags]
                group["selected_ids"] = [t for t in group["selected_ids"] if t in group["tag_ids"]]
                removed += before - len(group["tag_ids"])
        if removed:
            LOG.warning("清理悬空标签引用 %d 条", removed)
        return removed

    def preset_count_hint(self) -> str:
        return f"共 {PRESET_COUNT} 套互斥预设，当前：{self.active_preset()['name']}"
