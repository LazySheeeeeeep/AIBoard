# -*- coding: utf-8 -*-
"""
暖金游戏手账风 (Warm Fantasy Journal / 原神纪行·星铁委托质感) 主题系统
柔和暖羊皮纸底色 + 鎏金香槟边框 + 深可可护眼文字 + 立体触感游戏按钮
"""

import time
from typing import Optional
from PyQt5 import QtCore, QtGui


COLORS = {
    # 主面板暖羊皮纸与顶栏可可暖棕
    "bg_parchment_top": "#F7F0E4",
    "bg_parchment_bot": "#EFE5D4",
    "bg_header_top": "#46382E",
    "bg_header_bot": "#382C24",
    "bg_column": "#F2E9DA",
    "bg_card": "#FCF9F2",
    "bg_card_hover": "#FFFDF9",
    "bg_card_done": "#F3ECE0",
    "bg_input": "#FFFDF9",
    # 边框与立体阴影色
    "border_outer": "#B89B72",
    "border_gold": "#D8B882",
    "border_card": "#E2D4BE",
    "border_card_shadow": "#D4C2A6",
    "border_focus": "#D48B2A",
    # 护眼暖色文字层级
    "text_header": "#F9EFE0",
    "text_header_sub": "#D5C2A5",
    "text_primary": "#382C22",
    "text_secondary": "#7A6754",
    "text_muted": "#9E8B76",
    # 游戏感品牌与状态主色
    "gold_primary": "#D98A2B",
    "gold_light": "#F0B85A",
    "jade_green": "#2E996E",
    "cobalt_blue": "#3B78CC",
    "iris_purple": "#8456CC",
    "coral_red": "#D9534F",
}

# 对话状态印章配色：(文案, 文字色, 背景色, 描边色)
STATUS_META = {
    "running": ("✦ 进行中", "#1F6FB2", "#E3F1FC", "#9CC8EE"),
    "waiting": ("💬 待确认", "#B86B14", "#FDF0DC", "#EBC48A"),
    "completed": ("✔ 已完成", "#247A56", "#E3F5EC", "#9AD4B9"),
    "paused": ("⏸ 待继续", "#756350", "#EFE7DB", "#D4C5B1"),
    "error": ("⚠ 异常", "#B83B37", "#FCE8E7", "#E8ABA8"),
}

# 平台徽标配色：(短标签, 文字色, 背景色, 描边色)
PROVIDER_META = {
    "antigravity": ("AGY", "#6D3FB3", "#F1E9FC", "#CDB7EE"),
    "codex": ("CDX", "#2962B0", "#E6F0FC", "#ADCBE8"),
    "claude_code": ("CLD", "#B85622", "#FCEEE4", "#EABFA3"),
    "deepseek_harness": ("DSH", "#1D7480", "#E3F4F6", "#9FD3DA"),
    "chatgpt": ("GPT", "#1F7D59", "#E3F5EE", "#A5DAC4"),
}

# 待办优先级配色：(文案, 主色, 浅底色) —— 简化为「普通 / 重要」两档
PRIORITY_META = {
    "normal": ("普通", "#8C7862", "#EFE7DA"),
    "high": ("重要", "#D97724", "#FDF0DC"),
    "urgent": ("重要", "#D97724", "#FDF0DC"),
}

# 账户专属暖调谐和色彩
ACCOUNT_BRAND_COLORS = {
    "chatgpt": "#2B996E",
    "codex": "#3B78CC",
    "antigravity": "#8456CC",
    "claude_code": "#D4743B",
    "deepseek_harness": "#2A8F9D",
}


def quota_status_color(pct: int, brand_color: str) -> str:
    if pct <= 15:
        return "#D9534F"
    if pct <= 35:
        return "#D98A2B"
    return brand_color


def draw_four_point_star(
    painter: QtGui.QPainter, cx: float, cy: float, radius: float, color: QtGui.QColor
) -> None:
    """绘制热门二次元/奇幻游戏标志性的四角星芒 (✦) 装饰"""
    painter.save()
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(color)
    inner = radius * 0.28
    path = QtGui.QPainterPath()
    path.moveTo(cx, cy - radius)
    path.quadTo(cx + inner, cy - inner, cx + radius, cy)
    path.quadTo(cx + inner, cy + inner, cx, cy + radius)
    path.quadTo(cx - inner, cy + inner, cx - radius, cy)
    path.quadTo(cx - inner, cy - inner, cx, cy - radius)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def format_countdown(reset_at: Optional[float], now: Optional[float] = None) -> str:
    if not reset_at:
        return "未设周期"
    cur = now if now is not None else time.time()
    diff = int(max(0.0, float(reset_at) - cur))
    if diff <= 0:
        return "即将恢复"
    days = diff // 86400
    hours = (diff % 86400) // 3600
    mins = (diff % 3600) // 60
    if days > 0:
        return "{}天{}h 后恢复".format(days, hours)
    if hours > 0:
        return "{}h {:02d}m 后恢复".format(hours, mins)
    if mins > 0:
        return "{}m 后恢复".format(mins)
    return "{}s 后恢复".format(diff)


def format_relative_time(ts: Optional[float], now: Optional[float] = None) -> str:
    if not ts or ts <= 0:
        return "未知"
    cur = now if now is not None else time.time()
    diff = int(cur - float(ts))
    if diff < 30:
        return "刚刚"
    if diff < 3600:
        return "{}分钟前".format(max(1, diff // 60))
    if diff < 86400:
        return "{}小时前".format(diff // 3600)
    days = diff // 86400
    if days == 1:
        return "昨天 " + time.strftime("%H:%M", time.localtime(float(ts)))
    if days < 7:
        return "{}天前".format(days)
    return time.strftime("%m-%d %H:%M", time.localtime(float(ts)))


def format_tokens(num: int) -> str:
    n = int(num or 0)
    if n <= 0:
        return "0"
    if n >= 1000000:
        return "{:.1f}M".format(n / 1000000.0)
    if n >= 1000:
        return "{:.1f}k".format(n / 1000.0)
    return str(n)


def _paint_bento_logo(p: QtGui.QPainter, s: float) -> None:
    """在 [0, s] x [0, s] 浮点坐标系内绘制高精度现代几何 Bento 图标"""
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setRenderHint(QtGui.QPainter.HighQualityAntialiasing, True)

    margin = s * 0.04
    rect = QtCore.QRectF(margin, margin, s - 2.0 * margin, s - 2.0 * margin)
    grad = QtGui.QLinearGradient(0, 0, s, s)
    grad.setColorAt(0.0, QtGui.QColor("#3C312A"))
    grad.setColorAt(1.0, QtGui.QColor("#241D18"))
    p.setBrush(QtGui.QBrush(grad))
    p.setPen(QtGui.QPen(QtGui.QColor("#C8A878"), max(1.2, s * 0.032)))
    r = s * 0.25
    p.drawRoundedRect(rect, r, r)

    pad = s * 0.21
    gap = s * 0.075
    inner_w = s - 2.0 * pad
    inner_h = s - 2.0 * pad
    col_w = (inner_w - gap) * 0.48
    right_w = inner_w - col_w - gap
    cell_r = max(2.0, s * 0.08)

    p.setPen(QtCore.Qt.NoPen)

    # 左上：暖琥珀橙
    top_h = (inner_h - gap) * 0.45
    p.setBrush(QtGui.QColor("#F2A644"))
    p.drawRoundedRect(QtCore.QRectF(pad, pad, col_w, top_h), cell_r, cell_r)

    # 左下：晴空钴蓝
    bot_y = pad + top_h + gap
    bot_h = inner_h - top_h - gap
    p.setBrush(QtGui.QColor("#589CE0"))
    p.drawRoundedRect(QtCore.QRectF(pad, bot_y, col_w, bot_h), cell_r, cell_r)

    # 右列：温润象牙白 + 翠绿完成点
    rx = pad + col_w + gap
    p.setBrush(QtGui.QColor("#FAF3E8"))
    p.drawRoundedRect(QtCore.QRectF(rx, pad, right_w, inner_h), cell_r, cell_r)

    dot_r = right_w * 0.21
    p.setBrush(QtGui.QColor("#32A877"))
    p.drawEllipse(QtCore.QPointF(rx + right_w * 0.5, pad + inner_h * 0.31), dot_r, dot_r)

    line_w = right_w * 0.54
    line_h = s * 0.05
    p.setBrush(QtGui.QColor("#C4B299"))
    p.drawRoundedRect(
        QtCore.QRectF(rx + (right_w - line_w) * 0.5, pad + inner_h * 0.60, line_w, line_h),
        line_h * 0.5,
        line_h * 0.5,
    )


def render_app_pixmap(logical_size: int = 28, dpr: float = 2.0) -> QtGui.QPixmap:
    """使用 4x 超采样 (SSAA) + HiDPI devicePixelRatio 渲染刀锋级清晰图标位图"""
    eff_dpr = max(1.0, float(dpr))
    target_px = max(16, int(round(logical_size * eff_dpr)))
    super_px = max(256, target_px * 4)

    img = QtGui.QImage(super_px, super_px, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QtGui.QPainter(img)
    _paint_bento_logo(p, float(super_px))
    p.end()

    scaled = img.scaled(
        target_px, target_px, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
    )
    pix = QtGui.QPixmap.fromImage(scaled)
    pix.setDevicePixelRatio(eff_dpr)
    return pix


def create_app_icon(size: int = 64) -> QtGui.QIcon:
    """生成包含 16~256px 全分辨率帧的高清多尺寸 QIcon"""
    icon = QtGui.QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        pix = render_app_pixmap(sz, dpr=1.0)
        icon.addPixmap(pix)
    return icon


def ensure_app_ico_file(ico_path: str) -> bool:
    """自动生成多尺寸高清 Windows 原生 .ico 图标文件，用于快捷方式与 .exe 打包"""
    import os
    try:
        out_dir = os.path.dirname(os.path.abspath(ico_path))
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir)

        super_px = 512
        img = QtGui.QImage(super_px, super_px, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QtGui.QPainter(img)
        _paint_bento_logo(p, float(super_px))
        p.end()

        png_tmp = ico_path + ".tmp.png"
        img.save(png_tmp, "PNG")
        try:
            from PIL import Image
            pil_img = Image.open(png_tmp)
            pil_img.save(
                ico_path,
                format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
            pil_img.close()
        finally:
            if os.path.exists(png_tmp):
                os.remove(png_tmp)
        return os.path.isfile(ico_path)
    except Exception:
        return False


MAIN_STYLESHEET = """
QWidget {
    font-family: "Bahnschrift", "Segoe UI Semibold", "Microsoft YaHei UI", "Segoe UI", sans-serif;
    color: #382C22;
    font-size: 12px;
}

QToolTip {
    background-color: #3B2E25;
    color: #FAF3E8;
    border: 1px solid #C8A978;
    padding: 6px 9px;
    border-radius: 6px;
    font-size: 12px;
}

QScrollArea {
    background: transparent;
    border: none;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 3px 0px 3px 0px;
}

QScrollBar::handle:vertical {
    background: #D3C1A6;
    min-height: 28px;
    border-radius: 3px;
}

QScrollBar::handle:vertical:hover {
    background: #B89E7A;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QLineEdit {
    background-color: #FFFDF9;
    border: 1px solid #D6C5AC;
    border-bottom: 2px solid #C7B293;
    border-radius: 8px;
    padding: 6px 10px;
    color: #382C22;
    font-size: 12px;
    selection-background-color: #E5A94C;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border: 1px solid #D98A2B;
    border-bottom: 2px solid #B86E16;
    background-color: #FFFFFF;
}

QComboBox {
    background-color: #FCF7EE;
    border: 1px solid #D6C5AC;
    border-bottom: 2px solid #C4AE8E;
    border-radius: 7px;
    padding: 4px 8px;
    color: #4A3B2F;
    font-weight: bold;
}

QComboBox:hover {
    border-color: #C89648;
    background-color: #FFFDF9;
}

QComboBox::drop-down {
    border: none;
    width: 18px;
}

QComboBox QAbstractItemView {
    background-color: #FCF8F0;
    border: 1px solid #C8A978;
    selection-background-color: #E5A94C;
    selection-color: #FFFFFF;
    color: #382C22;
    padding: 4px;
}

QSpinBox {
    background-color: #FFFDF9;
    border: 1px solid #D6C5AC;
    border-radius: 6px;
    padding: 4px 6px;
    color: #382C22;
}

QMenu {
    background-color: #FCF8F0;
    border: 1px solid #C4A574;
    padding: 5px;
}

QMenu::item {
    padding: 6px 18px;
    border-radius: 5px;
    color: #382C22;
    font-size: 12px;
}

QMenu::item:selected {
    background-color: #E8A849;
    color: #FFFFFF;
}

QMenu::separator {
    height: 1px;
    background: #E2D4BE;
    margin: 4px 6px;
}

/* 热门游戏风：琥珀鎏金立体主按钮 */
QPushButton#GameGoldBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F0B456, stop:1 #DE922B);
    border: 1px solid #C47A18;
    border-bottom: 3px solid #A6610D;
    border-radius: 8px;
    color: #FFFDF9;
    font-weight: bold;
    font-size: 12px;
    padding: 5px 13px;
}

QPushButton#GameGoldBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #F6C26B, stop:1 #E89F38);
}

QPushButton#GameGoldBtn:pressed {
    background-color: #CE8320;
    border-bottom: 1px solid #A6610D;
    padding-top: 7px;
}

/* 热门游戏风：奶油羊皮纸微立体胶囊按钮 */
QPushButton#GamePillBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFDF9, stop:1 #F2E7D5);
    border: 1px solid #D3C0A3;
    border-bottom: 2px solid #BFA886;
    border-radius: 8px;
    color: #544334;
    font-weight: bold;
    font-size: 11px;
    padding: 2px 8px;
}

QPushButton#GamePillBtn:hover {
    background-color: #FFFFFF;
    border-color: #D4943A;
    color: #B86E14;
}

QPushButton#GamePillBtn:pressed {
    background-color: #EAE0CE;
    border-bottom: 1px solid #BFA886;
}

/* 柔和无边框图标/次级按钮 */
QPushButton#SoftBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    color: #8A7662;
    font-weight: bold;
    padding: 2px 6px;
}

QPushButton#SoftBtn:hover {
    background-color: #EAE0CE;
    color: #382C22;
}

QDialog {
    background-color: #F6EFE2;
}
"""
