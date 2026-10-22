# -*- coding: utf-8 -*-
"""全局配置模块。

集中存放：路径常量、窗口尺寸、图片扩展名、标签尺寸、配色、字体、日志初始化。
所有其它模块统一从这里读取常量，避免魔法数字散落各处。
"""
from __future__ import annotations

import logging
import os
import sys

# --------------------------------------------------------------------------
# 应用信息
# --------------------------------------------------------------------------
APP_TITLE = "图片标签命名系统"
APP_VERSION = "2.0"

# --------------------------------------------------------------------------
# 路径相关
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resource_path(relative: str) -> str:
    """资源路径：源码运行取项目目录，PyInstaller 打包后取临时解包目录。"""
    base = getattr(sys, "_MEIPASS", BASE_DIR)
    return os.path.join(base, relative)


ASSETS_DIR = os.path.join(BASE_DIR, "assets")
APP_ICON_PNG = resource_path(os.path.join("assets", "app_icon.png"))
APP_ICON_ICO = resource_path(os.path.join("assets", "app_icon.ico"))
DATA_FILE = os.path.join(BASE_DIR, "tag_data.json")          # 标签数据文件
THUMB_CACHE_DIR = os.path.join(BASE_DIR, ".thumb_cache")     # 缩略图磁盘缓存目录

# --------------------------------------------------------------------------
# 窗口尺寸：最小 1200 x 800，可缩放 / 最大化
# --------------------------------------------------------------------------
WINDOW_W = 1480
WINDOW_H = 920
WINDOW_MIN_W = 1200
WINDOW_MIN_H = 800

# 三栏宽度约束（中栏随窗口伸缩）
COL_LEFT_MIN = 300
COL_CENTER_MIN = 560
COL_RIGHT_MIN = 400

# --------------------------------------------------------------------------
# 图片
# --------------------------------------------------------------------------
IMAGE_EXTS = (".jpg", ".jpeg", ".jpe", ".png", ".bmp", ".gif", ".webp")
IMAGE_EXTS_TEXT = "jpg/png/jpeg/bmp/gif/webp"
IMAGE_FILE_TYPES = [
    ("图片文件", "*.jpg *.jpeg *.jpe *.png *.bmp *.gif *.webp"),
    ("所有文件", "*.*"),
]

# 标签缩略图最大尺寸（等比例压缩，绝不原图渲染）
THUMB_MAX_W = 92
THUMB_MAX_H = 68
# 标签内边距 5px
TAG_PADDING = 5
TAG_RADIUS = 11          # 圆角半径
TAG_GAP = 2              # 缩略图与备注文字间距
TAG_MIN_W = 66           # 标签最小宽度
TAG_TEXT_MAX_CHARS = 8   # 标签内备注最多显示的字数

# 预览窗口
PREVIEW_W = 980
PREVIEW_H = 740
PREVIEW_MIN_SCALE = 0.02
PREVIEW_MAX_SCALE = 8.0

# 中心大图预览面板（单击标签 / 文件树图片时显示）
CENTER_PREVIEW_H = 210        # 展开时的固定高度
CENTER_PREVIEW_MAX_UPSCALE = 2.0  # 小图最多放大倍数
CENTER_PREVIEW_MAX_SIDE = 2600    # 单击预览最多解码的原图边长（超大图先缩小）

# 预设数量（互斥单选）
PRESET_COUNT = 5

# --------------------------------------------------------------------------
# 字体：系统功能文字加粗加大；标签内图片下方备注更小
# --------------------------------------------------------------------------
FONT_FAMILY = "Microsoft YaHei UI"

FONT_APP_TITLE = (FONT_FAMILY, 13, "bold")
FONT_PANEL_TITLE = (FONT_FAMILY, 12, "bold")
FONT_BOLD = (FONT_FAMILY, 11, "bold")
FONT_BUTTON = (FONT_FAMILY, 10, "bold")
FONT_NORMAL = (FONT_FAMILY, 10)
FONT_INPUT = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 9)         # 辅助说明文字
FONT_TAG = (FONT_FAMILY, 9)          # 标签内备注（小字）
FONT_TINY = (FONT_FAMILY, 8)
FONT_MONO = ("Consolas", 13, "bold")  # 命名预览（等宽，便于校对）
FONT_TREE = (FONT_FAMILY, 10)

# --------------------------------------------------------------------------
# 配色
# --------------------------------------------------------------------------
C_BG = "#e8eef7"             # 主背景
C_PANEL = "#ffffff"          # 面板背景
C_PANEL_ALT = "#f5f8fc"      # 次级面板背景
C_BORDER = "#c3d0e4"         # 边框
C_HEADER = "#dce8f8"         # 面板标题条
C_ACCENT = "#2563eb"         # 主题蓝
C_ACCENT_DARK = "#1d4ed8"
C_ACCENT_LIGHT = "#dbeafe"
C_TEXT = "#16233a"
C_TEXT_SUB = "#5b6b83"
C_DROP = "#f97316"           # 拖拽高亮

C_TAG_BG = "#ffffff"
C_TAG_BORDER = "#aec4e4"
C_TAG_HOVER_BG = "#eef5ff"
C_TAG_SEL_BG = "#fff3cd"     # 选中：亮色标记
C_TAG_SEL_BORDER = "#f59e0b"
C_TAG_SEL_TEXT = "#7c4a03"
C_TAG_FOCUS_BORDER = "#2563eb"

C_MISSING_BG = "#f3f4f6"
C_MISSING_BORDER = "#9aa5b1"
C_MISSING_TEXT = "#b91c1c"

# 文件树配色
C_TREE_DIR = "#1d4ed8"
C_TREE_IMG = "#0f766e"
C_TREE_FILE = "#6b7280"
C_TREE_RENAMED = "#b45309"


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------
def is_image_file(path: str) -> bool:
    """判断是否是支持的图片文件（按扩展名）。"""
    return bool(path) and path.lower().endswith(IMAGE_EXTS)


def setup_logging(level: int = logging.INFO) -> None:
    """初始化控制台日志（PyCharm Run 窗口可见）。"""
    # 避免个别字符导致控制台编码异常（保留控制台自身编码，PyCharm 为 UTF-8）
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(errors="replace")
        except Exception:  # noqa: BLE001 - 控制台不支持时忽略
            pass

    fmt = "%(asctime)s [%(levelname)-7s] %(name)-14s | %(message)s"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    # 第三方库降噪
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("PIL.Image").setLevel(logging.WARNING)


def ensure_dir(path: str) -> None:
    """确保目录存在（失败不抛异常）。"""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass


def sanitize_filename(name: str) -> str:
    """把任意文字转成 Windows 合法文件名片段。"""
    bad = '\\/:*?"<>|\r\n\t'
    out = "".join("_" if ch in bad else ch for ch in (name or ""))
    out = out.strip().strip(".").strip()
    # Windows 保留名
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    if out.upper() in reserved:
        out = "_" + out
    return out or "未命名"
