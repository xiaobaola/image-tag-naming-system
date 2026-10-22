# -*- coding: utf-8 -*-
"""数据持久化模块（tag_data.json）。

结构::

    {
      "version": 2,
      "active_preset": 0,
      "last_dir": "D:/pic",
      "tags": [
        {"tag_id": "t001", "img_path": "D:/pic/01.png", "remark": "图纸A", "created_at": "..."}
      ],
      "presets": [
        {"preset_id": "p1", "name": "预设1", "groups": [
            {"group_id": "g1", "name": "标签组 1",
             "tag_ids": ["t001"], "selected_ids": ["t001"]}
        ]}
      ]
    }

要点：
* 标签只保存 **图片绝对路径 + 备注文字**，绝不把图片 base64 塞进 JSON。
* 标签全局共享；标签组归属各自预设，5 套预设互不干扰。
* 加载时对脏数据做修复（缺字段、悬空 tag_id、重复 id 等），保证不崩溃。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional

from config import PRESET_COUNT

LOG = logging.getLogger("data_store")


class DataStore:
    """标签 / 预设 / 分组 的唯一数据源。"""

    VERSION = 2

    def __init__(self, path: str):
        self.path = path
        self.tags: Dict[str, dict] = {}      # tag_id -> 标签字典（dict 保序 = 仓库顺序）
        self.presets: List[dict] = []        # 5 套预设
        self.active_preset: int = 0
        self.last_dir: str = ""            # 上次打开的图片文件夹（启动时文件树定位用）
        self._tag_seq = 0
        self._group_seq = 0
        self._preset_seq = 0

    # ======================================================================
    # 初始化 / 修复
    # ======================================================================
    def _reset_defaults(self) -> None:
        self.tags = {}
        self.presets = []
        self.active_preset = 0
        self.last_dir = ""
        self._tag_seq = 0
        self._group_seq = 0
        self._preset_seq = 0
        for i in range(PRESET_COUNT):
            self.presets.append(self._make_preset(i))

    def _make_preset(self, index: int) -> dict:
        self._preset_seq += 1
        preset = {
            "preset_id": f"p{self._preset_seq:02d}",
            "name": f"预设{index + 1}",
            "groups": [],
        }
        preset["groups"].append(self._make_group(index))
        return preset

    def _make_group(self, index: int = 0, name: str = "") -> dict:
        self._group_seq += 1
        return {
            "group_id": f"g{self._group_seq:03d}",
            "name": name or f"标签组 {index + 1}",
            "tag_ids": [],
            "selected_ids": [],
        }

    def _alloc_tag_id(self) -> str:
        self._tag_seq += 1
        return f"t{self._tag_seq:03d}"

    def _sync_tag_seq(self, tag_id: str) -> None:
        if tag_id.startswith("t") and tag_id[1:].isdigit():
            self._tag_seq = max(self._tag_seq, int(tag_id[1:]))

    def _sync_group_seq(self, group_id: str) -> None:
        digits = "".join(ch for ch in group_id if ch.isdigit())
        if digits:
            self._group_seq = max(self._group_seq, int(digits))

    # ======================================================================
    # 读写
    # ======================================================================
    def load(self) -> bool:
        """从磁盘加载。文件不存在 / 损坏时使用默认数据，返回是否成功读取。"""
        self._reset_defaults()
        if not os.path.isfile(self.path):
            LOG.info("数据文件不存在，使用默认数据并创建: %s", self.path)
            self.save()
            return False

        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict):
                raise ValueError("根节点不是 JSON 对象")
        except Exception as exc:  # noqa: BLE001
            LOG.error("数据文件解析失败(%s)，已备份并重建: %s", exc, self.path)
            try:
                backup = self.path + ".broken_" + datetime.now().strftime("%Y%m%d%H%M%S")
                shutil.copy2(self.path, backup)
                LOG.warning("损坏文件已备份为: %s", backup)
            except OSError:
                pass
            self._reset_defaults()
            self.save()
            return False

        self._load_tags(raw.get("tags"))
        self._load_presets(raw.get("presets"))
        try:
            self.active_preset = int(raw.get("active_preset", 0))
        except (TypeError, ValueError):
            self.active_preset = 0
        self.active_preset = min(max(self.active_preset, 0), len(self.presets) - 1)

        last_dir = str(raw.get("last_dir") or "").strip()
        self.last_dir = os.path.normpath(last_dir) if last_dir and os.path.isdir(last_dir) else ""

        LOG.info(
            "数据加载完成: 标签 %d 个，预设 %d 套，当前预设=%d",
            len(self.tags), len(self.presets), self.active_preset + 1,
        )
        self._log_preset_summary()
        return True

    def _load_tags(self, tags_raw) -> None:
        if isinstance(tags_raw, dict):  # 兼容 {"t001": {...}} 写法
            tags_raw = [dict(v, tag_id=k) for k, v in tags_raw.items() if isinstance(v, dict)]
        if not isinstance(tags_raw, list):
            return

        for item in tags_raw:
            if not isinstance(item, dict):
                continue
            img_path = str(item.get("img_path") or "").strip()
            if not img_path:
                LOG.warning("跳过没有 img_path 的标签数据: %s", item)
                continue
            tag_id = str(item.get("tag_id") or "").strip()
            if not tag_id or tag_id in self.tags:
                tag_id = self._alloc_tag_id()
                while tag_id in self.tags:  # 极端情况下避免 id 撞车
                    tag_id = self._alloc_tag_id()
            self._sync_tag_seq(tag_id)
            self.tags[tag_id] = {
                "tag_id": tag_id,
                "img_path": os.path.normpath(img_path),
                "remark": str(item.get("remark") or "").strip(),
                "created_at": str(item.get("created_at") or ""),
            }

    def _load_presets(self, presets_raw) -> None:
        presets: List[dict] = []
        if isinstance(presets_raw, list):
            for raw in presets_raw[:PRESET_COUNT]:
                if not isinstance(raw, dict):
                    continue
                index = len(presets)
                preset = {
                    "preset_id": str(raw.get("preset_id") or f"p{index + 1:02d}"),
                    "name": str(raw.get("name") or f"预设{index + 1}"),
                    "groups": [],
                }
                for g_raw in (raw.get("groups") or []):
                    if not isinstance(g_raw, dict):
                        continue
                    group = self._repair_group(g_raw, preset, len(preset["groups"]))
                    preset["groups"].append(group)
                if not preset["groups"]:
                    preset["groups"].append(self._make_group(index))
                presets.append(preset)

        # 补齐到 5 套，保证"5 组互斥预设"
        while len(presets) < PRESET_COUNT:
            presets.append(self._make_preset(len(presets)))

        self.presets = presets
        self._preset_seq = max(self._preset_seq, len(presets))

    def _repair_group(self, g_raw: dict, preset: dict, index: int) -> dict:
        gid = str(g_raw.get("group_id") or "").strip()
        if not gid:
            gid = self._make_group(index)["group_id"]
        else:
            self._sync_group_seq(gid)

        # 过滤悬空 tag_id 并去重（保序）
        tag_ids: List[str] = []
        seen = set()
        for tid in (g_raw.get("tag_ids") or []):
            tid = str(tid)
            if tid in self.tags and tid not in seen:
                seen.add(tid)
                tag_ids.append(tid)
            elif tid not in self.tags:
                LOG.warning("预设[%s] 分组[%s] 中标签 %s 不存在，已剔除", preset["name"], gid, tid)

        selected: List[str] = []
        for tid in (g_raw.get("selected_ids") or []):
            tid = str(tid)
            if tid in tag_ids and tid not in selected:
                selected.append(tid)

        return {
            "group_id": gid,
            "name": str(g_raw.get("name") or f"标签组 {index + 1}"),
            "tag_ids": tag_ids,
            "selected_ids": selected,
        }

    def save(self) -> bool:
        """原子写入：先写临时文件再替换，避免中途崩溃损坏数据。"""
        payload = {
            "version": self.VERSION,
            "active_preset": self.active_preset,
            "last_dir": self.last_dir,
            "tags": list(self.tags.values()),
            "presets": self.presets,
        }
        tmp = self.path + ".tmp"
        try:
            ensure_parent = os.path.dirname(os.path.abspath(self.path))
            if ensure_parent:
                os.makedirs(ensure_parent, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            LOG.debug("数据已保存: %s（标签 %d 个）", self.path, len(self.tags))
            return True
        except Exception as exc:  # noqa: BLE001
            LOG.error("保存数据失败: %s", exc)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            return False

    # ======================================================================
    # 标签 API
    # ======================================================================
    def set_last_dir(self, folder: str) -> bool:
        """记录上次打开的图片文件夹（只改内存，随 save() 落盘）。"""
        if not folder or not os.path.isdir(folder):
            return False
        folder = os.path.normpath(os.path.abspath(folder))
        if os.path.normcase(folder) == os.path.normcase(self.last_dir or ""):
            return False
        self.last_dir = folder
        LOG.debug("记录上次打开的文件夹: %s", folder)
        return True

    def new_tag_id(self) -> str:
        return self._alloc_tag_id()

    def add_tag(self, img_path: str, remark: str = "") -> dict:
        """新建图片标签（只存路径 + 备注）。"""
        abspath = os.path.normpath(os.path.abspath(img_path))
        tag = {
            "tag_id": self.new_tag_id(),
            "img_path": abspath,
            "remark": (remark or "").strip(),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.tags[tag["tag_id"]] = tag
        LOG.info("新增图片标签: %s | 备注=%r", abspath, tag["remark"])
        return tag

    def get_tag(self, tag_id: str) -> Optional[dict]:
        return self.tags.get(tag_id)

    def find_tag_by_path(self, img_path: str) -> Optional[dict]:
        target = os.path.normcase(os.path.abspath(img_path))
        for tag in self.tags.values():
            if os.path.normcase(os.path.abspath(tag.get("img_path", ""))) == target:
                return tag
        return None

    def update_remark(self, tag_id: str, remark: str) -> bool:
        tag = self.tags.get(tag_id)
        if not tag:
            return False
        tag["remark"] = (remark or "").strip()
        LOG.info("更新标签备注: %s -> %r", tag_id, tag["remark"])
        return True

    def display_text(self, tag_id: str) -> str:
        """拼接用文字：优先备注，备注为空则取图片文件名（不含后缀）。"""
        tag = self.tags.get(tag_id)
        if not tag:
            return ""
        remark = (tag.get("remark") or "").strip()
        if remark:
            return remark
        stem = os.path.splitext(os.path.basename(tag.get("img_path", "")))[0]
        return stem or "未命名"

    def groups_containing(self, tag_id: str) -> List[str]:
        """返回包含该标签的分组 id 列表（用于删除日志）。"""
        result = []
        for preset in self.presets:
            for group in preset["groups"]:
                if tag_id in group["tag_ids"]:
                    result.append(f"{preset['name']}/{group['name']}")
        return result

    def delete_tag(self, tag_id: str) -> bool:
        """删除标签，并从所有预设的所有分组中清理。"""
        tag = self.tags.pop(tag_id, None)
        if not tag:
            return False
        removed_from = []
        for preset in self.presets:
            for group in preset["groups"]:
                if tag_id in group["tag_ids"]:
                    group["tag_ids"].remove(tag_id)
                    removed_from.append(f"{preset['name']}/{group['name']}")
                if tag_id in group["selected_ids"]:
                    group["selected_ids"].remove(tag_id)
        LOG.info("删除标签: %s (%s)，涉及分组: %s",
                 tag_id, tag.get("img_path"), "、".join(removed_from) or "无")
        return True

    def all_tags(self) -> List[dict]:
        return list(self.tags.values())

    # ======================================================================
    # 文件重命名后的路径同步
    # ======================================================================
    def remap_paths(self, old_path: str, new_path: str) -> List[str]:
        """文件（或文件夹）重命名后同步标签里的绝对路径。

        返回被修改的 tag_id 列表。
        """
        if not old_path or not new_path:
            return []
        old_abs = os.path.normpath(os.path.abspath(old_path))
        new_abs = os.path.normpath(os.path.abspath(new_path))
        old_cmp = os.path.normcase(old_abs)
        changed: List[str] = []

        for tag in self.tags.values():
            img_path = tag.get("img_path") or ""
            if not img_path:
                continue
            img_abs = os.path.normpath(os.path.abspath(img_path))
            img_cmp = os.path.normcase(img_abs)

            if img_cmp == old_cmp:  # 重命名的正是这张图
                tag["img_path"] = new_abs
                changed.append(tag["tag_id"])
                LOG.info("标签路径同步(文件): %s | %s -> %s", tag["tag_id"], old_abs, new_abs)
            elif img_cmp.startswith(old_cmp + os.sep):  # 重命名的是所在文件夹
                rel = os.path.relpath(img_abs, old_abs)
                tag["img_path"] = os.path.normpath(os.path.join(new_abs, rel))
                changed.append(tag["tag_id"])
                LOG.info("标签路径同步(目录): %s | %s -> %s", tag["tag_id"], img_path, tag["img_path"])
        return changed

    # ======================================================================
    # 调试
    # ======================================================================
    def _log_preset_summary(self) -> None:
        for i, preset in enumerate(self.presets):
            groups = "、".join(
                f"{g['name']}[{len(g['tag_ids'])}]" for g in preset["groups"]
            )
            LOG.debug("预设%d(%s): %s", i + 1, preset["name"], groups or "无分组")

    def stats(self) -> str:
        selected = sum(len(g["selected_ids"]) for p in self.presets for g in p["groups"])
        return f"标签 {len(self.tags)} 个 / 预设 {len(self.presets)} 套 / 选中 {selected} 个"
