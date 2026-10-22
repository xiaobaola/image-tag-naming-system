# -*- coding: utf-8 -*-
"""图片加载工具模块。

职责：
1. 生成标签缩略图（等比例压缩到限定尺寸），并做 **内存缓存 + 磁盘缩略缓存**，
   避免超大原图参与渲染导致界面卡顿 / 内存爆炸。
2. 为预览窗口提供原图句柄，并按缩放比例渲染出可显示的 PhotoImage。
3. 统一处理"图片不存在 / 无法解码"的情况，交由标签控件绘制占位图。

优先使用 Pillow；若环境没有 Pillow，自动降级为 tkinter 原生 PhotoImage
（原生方式只支持 png/gif 等格式，且缩放为整数倍率）。
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import tkinter as tk
from typing import Optional, Tuple

from config import THUMB_CACHE_DIR, ensure_dir

LOG = logging.getLogger("image_utils")

# --------------------------------------------------------------------------
# 后端探测
# --------------------------------------------------------------------------
try:  # pragma: no cover - 取决于运行环境
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
    try:
        RESAMPLE = Image.Resampling.LANCZOS  # Pillow >= 9.1
    except AttributeError:  # pragma: no cover
        RESAMPLE = Image.LANCZOS
except Exception:  # noqa: BLE001 - 未安装 Pillow
    Image = None  # type: ignore[assignment]
    ImageTk = None  # type: ignore[assignment]
    PIL_AVAILABLE = False
    RESAMPLE = None

LOG.info("图片后端: %s", "Pillow" if PIL_AVAILABLE else "tkinter 原生（建议 pip install pillow）")

# 预览窗口最多加载的原图边长（超过则先等比缩小，避免占用过多内存）
PREVIEW_MAX_SIDE = 6000

# 内存缩略图缓存：key -> {"photo", "size", "ok", "reason"}
_thumb_cache: dict = {}
_thumb_root = None  # PhotoImage 绑定在 Tk 解释器上，换窗口后缓存失效
_THUMB_CACHE_LIMIT = 500


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------
def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _disk_cache_file(path: str, max_w: int, max_h: int) -> str:
    """缩略图磁盘缓存文件路径（按 路径+mtime+尺寸 计算，图片变更自动失效）。"""
    raw = f"{_norm(path)}|{_mtime(path)}|{max_w}x{max_h}"
    name = hashlib.md5(raw.encode("utf-8")).hexdigest() + ".png"
    return os.path.join(THUMB_CACHE_DIR, name)


def _fail(reason: str) -> dict:
    return {"photo": None, "size": (0, 0), "ok": False, "reason": reason}


# --------------------------------------------------------------------------
# 缩略图
# --------------------------------------------------------------------------
def make_thumbnail(path: str, max_w: int, max_h: int) -> dict:
    """生成（或复用缓存的）缩略图。

    返回::

        {"photo": PhotoImage | None, "size": (w, h), "ok": bool, "reason": str}

    说明：无论原图多大，返回的 PhotoImage 都不会超过 (max_w, max_h)。
    """
    global _thumb_root
    root = getattr(tk, "_default_root", None)
    if root is not _thumb_root:
        _thumb_cache.clear()
        _thumb_root = root

    if not path:
        return _fail("未绑定图片")
    if not os.path.isfile(path):
        LOG.warning("图片缺失: %s", path)
        return _fail("图片不存在")

    key = (_norm(path), _mtime(path), max_w, max_h)
    cached = _thumb_cache.get(key)
    if cached is not None:
        return cached

    if PIL_AVAILABLE:
        result = _make_thumbnail_pil(path, max_w, max_h)
    else:
        result = _make_thumbnail_tk(path, max_w, max_h)

    if len(_thumb_cache) > _THUMB_CACHE_LIMIT:  # 简单防膨胀
        _thumb_cache.clear()
        LOG.debug("缩略图内存缓存已清空")
    _thumb_cache[key] = result
    return result


def _make_thumbnail_pil(path: str, max_w: int, max_h: int) -> dict:
    cache_path = _disk_cache_file(path, max_w, max_h)
    # 1) 先尝试磁盘缩略缓存
    if os.path.isfile(cache_path):
        try:
            with Image.open(cache_path) as im:
                im.load()
                photo = ImageTk.PhotoImage(im.copy())
            LOG.debug("命中缩略缓存: %s -> %s", path, os.path.basename(cache_path))
            return {"photo": photo, "size": (photo.width(), photo.height()), "ok": True, "reason": ""}
        except Exception as exc:  # noqa: BLE001 - 缓存损坏则删除重建
            LOG.warning("缩略缓存损坏，重建: %s (%s)", cache_path, exc)
            try:
                os.remove(cache_path)
            except OSError:
                pass

    # 2) 读取原图并等比压缩（不渲染原图）
    try:
        with Image.open(path) as im:
            im.load()
            work = im.copy()
    except Exception as exc:  # noqa: BLE001
        LOG.error("图片打开失败: %s (%s)", path, exc)
        return _fail(f"无法解码: {exc}")

    try:
        work.thumbnail((max_w, max_h), RESAMPLE)  # 等比压缩到框内
        if work.mode not in ("RGB", "RGBA"):
            work = work.convert("RGBA")
        photo = ImageTk.PhotoImage(work)
        size = (photo.width(), photo.height())
        # 3) 写磁盘缩略缓存（失败不影响使用）
        try:
            ensure_dir(THUMB_CACHE_DIR)
            work.save(cache_path, "PNG")
        except Exception as exc:  # noqa: BLE001
            LOG.debug("写缩略缓存失败: %s", exc)
        LOG.debug("生成缩略图: %s -> %sx%s", path, size[0], size[1])
        return {"photo": photo, "size": size, "ok": True, "reason": ""}
    except Exception as exc:  # noqa: BLE001
        LOG.error("缩略图生成失败: %s (%s)", path, exc)
        return _fail(f"缩略失败: {exc}")


def _make_thumbnail_tk(path: str, max_w: int, max_h: int) -> dict:
    """无 Pillow 时的降级实现：tk.PhotoImage + 整数倍 subsample。"""
    try:
        img = tk.PhotoImage(file=path)
    except tk.TclError as exc:
        LOG.error("原生解码失败（建议安装 Pillow）: %s (%s)", path, exc)
        return _fail("无法解码（建议安装 Pillow）")

    factor = max(1, math.ceil(max(img.width() / max_w, img.height() / max_h)))
    if factor > 1:
        try:
            img = img.subsample(factor, factor)
        except tk.TclError:
            pass
    LOG.debug("原生生成缩略图: %s -> %sx%s", path, img.width(), img.height())
    return {"photo": img, "size": (img.width(), img.height()), "ok": True, "reason": ""}


# --------------------------------------------------------------------------
# 原图（预览用）
# --------------------------------------------------------------------------
def load_full(path: str, max_side: int = PREVIEW_MAX_SIDE) -> Optional[dict]:
    """加载原图句柄。

    max_side：超过该边长时先等比缩小（预览窗用 6000，中心预览面板用更小的值，
    避免单击一张超大图就要解码整张原图）。

    返回::

        {"backend": "pil"|"tk", "pil": Image | None, "photo": PhotoImage | None, "size": (w, h)}

    失败返回 None。
    """
    if not path or not os.path.isfile(path):
        LOG.warning("预览失败，图片不存在: %s", path)
        return None

    if PIL_AVAILABLE:
        try:
            with Image.open(path) as im:
                im.load()
                work = im.copy()
            if work.mode not in ("RGB", "RGBA"):
                work = work.convert("RGBA")
            # 超大图先等比缩小，防止内存占用过高
            if max(work.size) > max_side:
                ratio = max_side / max(work.size)
                new_size = (max(1, int(work.width * ratio)), max(1, int(work.height * ratio)))
                work = work.resize(new_size, RESAMPLE)
                LOG.info("原图过大，已预缩放至 %sx%s: %s", new_size[0], new_size[1], path)
            LOG.info("加载原图: %s (%sx%s)", path, work.width, work.height)
            return {"backend": "pil", "pil": work, "photo": None, "size": (work.width, work.height)}
        except Exception as exc:  # noqa: BLE001
            LOG.error("原图加载失败: %s (%s)", path, exc)
            return None

    try:
        photo = tk.PhotoImage(file=path)
        LOG.info("原生加载原图: %s (%sx%s)", path, photo.width(), photo.height())
        return {"backend": "tk", "pil": None, "photo": photo, "size": (photo.width(), photo.height())}
    except tk.TclError as exc:
        LOG.error("原生原图解码失败: %s (%s)", path, exc)
        return None


def render(handle: Optional[dict], scale: float) -> Tuple[Optional[tk.PhotoImage], float]:
    """按比例渲染预览图。

    返回 (photo, 实际生效比例)。失败返回 (None, 0)。
    """
    if not handle:
        return None, 0.0
    scale = max(0.01, float(scale))
    iw, ih = handle["size"]

    if handle["backend"] == "pil":
        w = max(1, min(int(round(iw * scale)), 16000))
        h = max(1, min(int(round(ih * scale)), 16000))
        try:
            im = handle["pil"].resize((w, h), RESAMPLE)
            return ImageTk.PhotoImage(im), w / iw
        except Exception as exc:  # noqa: BLE001
            LOG.error("预览渲染失败: %s", exc)
            return None, 0.0

    # 原生后端：只支持整数倍 zoom / subsample
    base: tk.PhotoImage = handle["photo"]
    try:
        if scale >= 1.0:
            z = int(min(round(scale), 4))
            return (base.zoom(z, z), float(z)) if z > 1 else (base, 1.0)
        f = int(min(max(math.ceil(1.0 / scale), 1), 8))
        return (base.subsample(f, f), 1.0 / f) if f > 1 else (base, 1.0)
    except tk.TclError as exc:
        LOG.error("预览渲染失败(原生): %s", exc)
        return None, 0.0


def clear_thumb_cache() -> None:
    """清空内存缩略图缓存（重命名后强制重新读取时可调用）。"""
    _thumb_cache.clear()
    LOG.info("缩略图内存缓存已清空")
