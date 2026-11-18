# -*- coding: utf-8 -*-
"""
暖金游戏手账风自定义组件库 (兼容 Python 3.7 + PyQt5 5.9)
包含：
- ArtisticBannerTitle: 鎏金书法衬线艺术字大标题 ("AI 看板")
- AccountQuotaCard: 无按钮极简体力槽额度卡片 (点击卡片快速校准)
- QuotaSettingsDialog: AI 账户额度管理与自动配置中心 (支持 Codex / Antigravity / Claude Code / DeepSeek Harness / ChatGPT 显示开关与自动探测)
- SessionItemCard / TodoItemRow: 游戏卷轴对话卡与委托待办卡
"""

import time as _time
from typing import Any, Callable, Dict, List, Optional
from PyQt5 import QtCore, QtGui, QtWidgets

from ui.theme import (
    ACCOUNT_BRAND_COLORS,
    COLORS,
    PRIORITY_META,
    PROVIDER_META,
    STATUS_META,
    draw_four_point_star,
    format_countdown,
    format_relative_time,
    format_tokens,
    quota_status_color,
)


DISPLAY_NAMES = {
    "codex": "OpenAI Codex",
    "antigravity": "Antigravity",
    "claude_code": "Claude Code",
    "deepseek_harness": "DeepSeek Harness",
    "chatgpt": "ChatGPT 网页版",
}


class ArtisticBannerTitle(QtWidgets.QWidget):
    """
    现代极简几何英文品牌标题 ([AI] BOARD //)
    采用德国工业几何字体 Bahnschrift + 宽字距排版，摒弃传统描边金字，清爽高级。
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(ArtisticBannerTitle, self).__init__(parent)
        self.setFixedHeight(34)
        self.setMinimumWidth(190)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

        cy = self.height() * 0.5

        # 1. 左侧暖琥珀胶囊 Tag: "AI"
        tag_rect = QtCore.QRectF(2.0, cy - 11.0, 32.0, 22.0)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#F0A444"))
        p.drawRoundedRect(tag_rect, 6.0, 6.0)

        ai_font = QtGui.QFont("Bahnschrift")
        ai_font.setPixelSize(14)
        ai_font.setBold(True)
        ai_font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 0.8)
        p.setFont(ai_font)
        p.setPen(QtGui.QColor("#281F19"))
        p.drawText(tag_rect, QtCore.Qt.AlignCenter, "AI")

        # 2. 右侧宽字距几何主标题: "BOARD"
        board_font = QtGui.QFont("Bahnschrift")
        board_font.setPixelSize(20)
        board_font.setWeight(QtGui.QFont.DemiBold)
        board_font.setLetterSpacing(QtGui.QFont.AbsoluteSpacing, 2.8)
        p.setFont(board_font)
        p.setPen(QtGui.QColor("#FAF4EB"))

        text_x = 42.0
        fm = QtGui.QFontMetricsF(board_font)
        text_w = fm.width("BOARD")
        text_rect = QtCore.QRectF(text_x, 0.0, text_w + 10.0, float(self.height()))
        p.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, "BOARD")

        # 3. 极简现代几何斜切双线点缀 "//"
        slash_x = text_x + text_w + 8.0
        slash_pen = QtGui.QPen(QtGui.QColor(240, 164, 68, 150), 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        p.setPen(slash_pen)
        p.drawLine(QtCore.QPointF(slash_x, cy + 6.0), QtCore.QPointF(slash_x + 5.0, cy - 6.0))
        p.setPen(QtGui.QPen(QtGui.QColor(250, 244, 235, 75), 1.8, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        p.drawLine(QtCore.QPointF(slash_x + 6.5, cy + 6.0), QtCore.QPointF(slash_x + 11.5, cy - 6.0))

        p.end()


class ElidedLabel(QtWidgets.QLabel):
    """根据当前实际宽度动态省略长文本，确保窄列排版永不溢出"""

    def __init__(self, text: str = "", parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(ElidedLabel, self).__init__(parent)
        self._full_text = text
        self.setMinimumWidth(36)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._update_elided()

    def full_text(self) -> str:
        return self._full_text

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super(ElidedLabel, self).resizeEvent(event)
        self._update_elided()

    def _update_elided(self) -> None:
        fm = QtGui.QFontMetrics(self.font())
        avail = max(24, self.width() - 2)
        self.setText(fm.elidedText(self._full_text, QtCore.Qt.ElideRight, avail))


class GameSectionHeader(QtWidgets.QWidget):
    """带鎏金四角星芒与渐隐分割线的游戏任务栏标题头"""

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(GameSectionHeader, self).__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self.setFixedHeight(26)

        self.right_layout = QtWidgets.QHBoxLayout(self)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(4)
        self.right_layout.addStretch(1)

    def set_title(self, title: str, subtitle: str = "") -> None:
        self._title = title
        self._subtitle = subtitle
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        cy = self.height() * 0.5
        # 现代圆角胶囊竖条指示器
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#E09434"))
        p.drawRoundedRect(QtCore.QRectF(2.0, cy - 7.0, 4.2, 14.0), 2.1, 2.1)

        font = p.font()
        font.setBold(True)
        font.setPixelSize(13)
        p.setFont(font)
        p.setPen(QtGui.QColor(COLORS["text_primary"]))

        fm = QtGui.QFontMetrics(font)
        title_x = 12
        p.drawText(
            QtCore.QRect(title_x, 0, 200, self.height()),
            QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
            self._title,
        )
        cur_x = title_x + fm.width(self._title) + 8

        if self._subtitle:
            sub_f = p.font()
            sub_f.setBold(False)
            sub_f.setPixelSize(11)
            p.setFont(sub_f)
            p.setPen(QtGui.QColor(COLORS["text_muted"]))
            sub_fm = QtGui.QFontMetrics(sub_f)
            p.drawText(
                QtCore.QRect(cur_x, 1, 130, self.height()),
                QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                self._subtitle,
            )
            cur_x += sub_fm.width(self._subtitle) + 8

        line_end = max(cur_x, self.width() - 75)
        if line_end > cur_x + 12:
            grad = QtGui.QLinearGradient(cur_x, cy, line_end, cy)
            grad.setColorAt(0.0, QtGui.QColor(205, 175, 125, 160))
            grad.setColorAt(1.0, QtGui.QColor(205, 175, 125, 0))
            p.setPen(QtGui.QPen(QtGui.QBrush(grad), 1.2))
            p.drawLine(QtCore.QPointF(cur_x, cy), QtCore.QPointF(line_end, cy))

        p.end()


class QuotaRingBadge(QtWidgets.QWidget):
    """抗锯齿环形能量徽章"""

    def __init__(
        self,
        label: str = "AI",
        pct: int = 100,
        brand_color: str = "#3B78CC",
        diameter: int = 30,
        dark_bg: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(QuotaRingBadge, self).__init__(parent)
        self._label = label
        self._pct = max(0, min(100, int(pct)))
        self._brand_color = brand_color
        self._dark_bg = dark_bg
        self.setFixedSize(diameter, diameter)

    def set_data(self, label: str, pct: int, brand_color: str) -> None:
        self._label = label
        self._pct = max(0, min(100, int(pct)))
        self._brand_color = brand_color
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        tw = max(16, int(round(self.width() * dpr)))
        th = max(16, int(round(self.height() * dpr)))
        ss = tw * 4

        img = QtGui.QImage(ss, ss, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(0)

        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.HighQualityAntialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

        d = float(ss)
        stroke = d * 0.118
        margin = stroke / 2.0 + d * 0.04
        rect = QtCore.QRectF(margin, margin, d - 2.0 * margin, d - 2.0 * margin)

        p.setPen(QtCore.Qt.NoPen)
        inner_bg = QtGui.QColor("#332720") if self._dark_bg else QtGui.QColor("#F5EDE0")
        p.setBrush(inner_bg)
        p.drawEllipse(rect)

        track_hex = "#574538" if self._dark_bg else "#E3D6C1"
        track_pen = QtGui.QPen(QtGui.QColor(track_hex), stroke, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        p.setPen(track_pen)
        p.drawEllipse(rect)

        active_hex = quota_status_color(self._pct, self._brand_color)
        if self._pct > 0:
            arc_pen = QtGui.QPen(QtGui.QColor(active_hex), stroke, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
            p.setPen(arc_pen)
            span_angle = int(-360.0 * (self._pct / 100.0) * 16)
            p.drawArc(rect, 90 * 16, span_angle)

        txt_col = "#FAF0E1" if self._dark_bg else "#3F3126"
        p.setPen(QtGui.QColor(txt_col))
        font = QtGui.QFont("Bahnschrift")
        font.setBold(True)
        font.setPixelSize(max(24, int(round(d * 0.285))))
        p.setFont(font)
        p.drawText(QtCore.QRectF(0.0, 0.0, d, d), QtCore.Qt.AlignCenter, self._label)
        p.end()

        scaled = img.scaled(tw, th, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        pix = QtGui.QPixmap.fromImage(scaled)
        pix.setDevicePixelRatio(dpr)

        wp = QtGui.QPainter(self)
        wp.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        wp.drawPixmap(0, 0, pix)
        wp.end()


class GameStaminaBar(QtWidgets.QWidget):
    """热门游戏体力槽/经验条：带凹槽描边与镜面高光反射条"""

    def __init__(
        self,
        pct: int = 100,
        brand_color: str = "#3B78CC",
        bar_height: int = 8,
        warn_on_low: bool = True,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(GameStaminaBar, self).__init__(parent)
        self._pct = max(0, min(100, int(pct)))
        self._brand_color = brand_color
        self._warn_on_low = warn_on_low
        self.setFixedHeight(bar_height)

    def set_value(self, pct: int, brand_color: Optional[str] = None) -> None:
        self._pct = max(0, min(100, int(pct)))
        if brand_color:
            self._brand_color = brand_color
        self.update()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        r = h / 2.0

        groove = QtCore.QRectF(0.5, 0.5, w - 1.0, h - 1.0)
        p.setBrush(QtGui.QColor("#EAE0CE"))
        p.setPen(QtGui.QPen(QtGui.QColor("#D5C4AA"), 1.0))
        p.drawRoundedRect(groove, r, r)

        if self._pct > 0:
            inner_w = max(h - 2.0, (w - 2.0) * (self._pct / 100.0))
            fill_rect = QtCore.QRectF(1.0, 1.0, inner_w, h - 2.0)
            col_hex = (
                quota_status_color(self._pct, self._brand_color)
                if self._warn_on_low
                else self._brand_color
            )
            base_c = QtGui.QColor(col_hex)
            bright_c = base_c.lighter(122)

            grad = QtGui.QLinearGradient(0, 0, inner_w, 0)
            grad.setColorAt(0.0, base_c)
            grad.setColorAt(1.0, bright_c)

            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QBrush(grad))
            p.drawRoundedRect(fill_rect, r - 1.0, r - 1.0)

            gloss_rect = QtCore.QRectF(2.5, 1.6, max(2.0, inner_w - 3.0), (h - 2.0) * 0.38)
            p.setBrush(QtGui.QColor(255, 255, 255, 78))
            p.drawRoundedRect(gloss_rect, gloss_rect.height() / 2.0, gloss_rect.height() / 2.0)

        p.end()


class PaperCardFrame(QtWidgets.QFrame):
    """象牙暖白微立体羊皮纸卡片"""

    def __init__(
        self,
        bg_color: str = "#FCF9F2",
        accent_stripe: str = "",
        radius: int = 10,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(PaperCardFrame, self).__init__(parent)
        self._bg_color = bg_color
        self._accent_stripe = accent_stripe
        self._hovered = False
        self._radius = float(radius)
        self.setAttribute(QtCore.Qt.WA_Hover, True)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super(PaperCardFrame, self).enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super(PaperCardFrame, self).leaveEvent(event)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        r = self._radius

        shadow_rect = QtCore.QRectF(0.8, 2.0, w - 1.6, h - 2.5)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#D9C8AE"))
        p.drawRoundedRect(shadow_rect, r, r)

        card_rect = QtCore.QRectF(0.8, 0.8, w - 1.6, h - 2.6)
        bg = "#FFFFFF" if self._hovered else self._bg_color
        border = "#DCA24A" if self._hovered else "#E2D4BE"
        p.setBrush(QtGui.QColor(bg))
        p.setPen(QtGui.QPen(QtGui.QColor(border), 1.1))
        p.drawRoundedRect(card_rect, r, r)

        if self._accent_stripe:
            stripe_rect = QtCore.QRectF(3.5, 6.5, 3.6, max(6.0, h - 14.0))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(self._accent_stripe))
            p.drawRoundedRect(stripe_rect, 1.8, 1.8)

        p.end()


class QuotaCalibrateDialog(QtWidgets.QDialog):
    """单个账户快速滑块校准弹窗（点击某张额度卡片时打开）"""

    def __init__(
        self, account: Dict[str, Any], parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super(QuotaCalibrateDialog, self).__init__(parent)
        self.account = account
        self.setWindowTitle("校准额度 - " + str(account.get("name", "")))
        self.setWindowFlags(
            QtCore.Qt.Dialog | QtCore.Qt.WindowTitleHint | QtCore.Qt.WindowCloseButtonHint
        )
        self.setFixedWidth(340)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 15, 16, 15)
        layout.setSpacing(10)

        title_lbl = QtWidgets.QLabel("✦ " + str(self.account.get("name", "")))
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #382C22;")
        layout.addWidget(title_lbl)

        pct_row = QtWidgets.QHBoxLayout()
        pct_row.addWidget(QtWidgets.QLabel("当前剩余额度:"))
        self.pct_val_lbl = QtWidgets.QLabel("{}%".format(int(self.account.get("remaining_pct", 100))))
        self.pct_val_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #D98A2B;")
        pct_row.addStretch()
        pct_row.addWidget(self.pct_val_lbl)
        layout.addLayout(pct_row)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(self.account.get("remaining_pct", 100)))
        self.slider.valueChanged.connect(lambda v: self.pct_val_lbl.setText("{}%".format(v)))
        layout.addWidget(self.slider)

        preset_row = QtWidgets.QHBoxLayout()
        preset_row.setSpacing(5)
        for val, txt in ((100, "满额"), (80, "80%"), (60, "60%"), (40, "40%"), (20, "20%"), (0, "0%")):
            btn = QtWidgets.QPushButton(txt)
            btn.setObjectName("GamePillBtn")
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, v=val: self.slider.setValue(v))
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)

        self.window_combo = QtWidgets.QComboBox()
        window_options = [
            ("3 小时窗口", 3.0),
            ("5 小时窗口 (Codex / Claude / AGY)", 5.0),
            ("24 小时每日重置", 24.0),
            ("7 天周度窗口", 168.0),
            ("30 天月度窗口", 720.0),
        ]
        cur_win = float(self.account.get("window_hours", 5.0))
        sel_idx = 1
        for i, (label, hours) in enumerate(window_options):
            self.window_combo.addItem(label, hours)
            if abs(cur_win - hours) < 0.2:
                sel_idx = i
        self.window_combo.setCurrentIndex(sel_idx)
        form.addRow("恢复周期:", self.window_combo)

        rem_sec = max(0.0, float(self.account.get("reset_at") or 0) - _time.time())
        rem_min_default = int(round(rem_sec / 60.0))

        reset_box = QtWidgets.QHBoxLayout()
        self.hours_spin = QtWidgets.QSpinBox()
        self.hours_spin.setRange(0, 999)
        self.hours_spin.setSuffix(" 小时")
        self.hours_spin.setValue(rem_min_default // 60)

        self.mins_spin = QtWidgets.QSpinBox()
        self.mins_spin.setRange(0, 59)
        self.mins_spin.setSuffix(" 分钟")
        self.mins_spin.setValue(rem_min_default % 60)

        reset_box.addWidget(self.hours_spin)
        reset_box.addWidget(self.mins_spin)
        form.addRow("距下次恢复:", reset_box)

        acc_id = str(self.account.get("id", ""))
        self.auto_sync_chk = QtWidgets.QCheckBox("优先同步本地日志探测到的额度信息")
        self.auto_sync_chk.setChecked(bool(self.account.get("auto_sync_log", acc_id != "chatgpt")))

        self.budget_spin = QtWidgets.QSpinBox()
        self.budget_spin.setRange(0, 5000)
        self.budget_spin.setSpecialValueText("不按步数折算")
        self.budget_spin.setSuffix(" 步/周期")
        self.budget_spin.setValue(int(self.account.get("step_budget") or 0))

        if acc_id != "chatgpt":
            form.addRow("周期步数预算:", self.budget_spin)

        layout.addLayout(form)
        if acc_id != "chatgpt":
            layout.addWidget(self.auto_sync_chk)

        btn_row = QtWidgets.QHBoxLayout()
        reset_full_btn = QtWidgets.QPushButton("⚡ 满额重置")
        reset_full_btn.setObjectName("GamePillBtn")
        reset_full_btn.setCursor(QtCore.Qt.PointingHandCursor)
        reset_full_btn.clicked.connect(self._fill_and_reset_timer)
        btn_row.addWidget(reset_full_btn)

        btn_row.addStretch()
        cancel_btn = QtWidgets.QPushButton("取消")
        cancel_btn.setObjectName("SoftBtn")
        cancel_btn.clicked.connect(self.reject)

        ok_btn = QtWidgets.QPushButton("保存")
        ok_btn.setObjectName("GameGoldBtn")
        ok_btn.setCursor(QtCore.Qt.PointingHandCursor)
        ok_btn.clicked.connect(self.accept)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _fill_and_reset_timer(self) -> None:
        self.slider.setValue(100)
        win_h = float(self.window_combo.currentData() or 5.0)
        total_m = int(round(win_h * 60.0))
        self.hours_spin.setValue(total_m // 60)
        self.mins_spin.setValue(total_m % 60)

    def get_result(self) -> Dict[str, Any]:
        win_h = float(self.window_combo.currentData() or 5.0)
        total_mins = self.hours_spin.value() * 60 + self.mins_spin.value()
        return {
            "remaining_pct": self.slider.value(),
            "window_hours": win_h,
            "reset_in_minutes": float(total_mins),
            "auto_sync_log": self.auto_sync_chk.isChecked(),
            "step_budget": self.budget_spin.value(),
        }


class QuotaSettingsDialog(QtWidgets.QDialog):
    """
    AI 账户额度统一管理与自动配置弹窗（由「AI 账户额度」小框右上角按钮打开）
    支持：
    - Codex / Antigravity / Claude Code / DeepSeek Harness / ChatGPT 显示开关
    - 一键自动探测并配置本机工具目录与启用状态
    - 各账户剩余百分比、恢复周期快速调整与附加路径配置
    """

    def __init__(
        self,
        accounts: List[Dict[str, Any]],
        diagnostics: Dict[str, Any],
        custom_paths: Dict[str, List[str]],
        scan_interval_sec: int,
        autostart_enabled: bool = False,
        boot_in_mini_mode: bool = False,
        data_dir_path: str = "",
        auto_detect_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(QuotaSettingsDialog, self).__init__(parent)
        self.setWindowTitle("AI BOARD 设置与常驻管理")
        self.setFixedWidth(495)
        self._accounts = [dict(a) for a in accounts]
        self._diagnostics = dict(diagnostics or {})
        self._custom_paths = dict(custom_paths or {})
        self._scan_interval = int(scan_interval_sec or 15)
        self._autostart_enabled = bool(autostart_enabled)
        self._boot_in_mini = bool(boot_in_mini_mode)
        self._data_dir_path = data_dir_path
        self._auto_detect_fn = auto_detect_fn
        self._row_controls = {}  # type: Dict[str, Dict[str, Any]]
        self._init_ui()

    def _init_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # 顶部：标题 + 一键自动配置按钮
        top_bar = QtWidgets.QHBoxLayout()
        hdr_lbl = QtWidgets.QLabel("✦ 账户显示开关与额度配置")
        hdr_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #382C22;")
        top_bar.addWidget(hdr_lbl)
        top_bar.addStretch()

        auto_btn = QtWidgets.QPushButton("⚡ 一键自动检测并配置")
        auto_btn.setObjectName("GameGoldBtn")
        auto_btn.setCursor(QtCore.Qt.PointingHandCursor)
        auto_btn.setToolTip("自动扫描本机 Codex / Antigravity / Claude Code / DeepSeek Harness 目录并勾选已就绪账户")
        auto_btn.clicked.connect(self._run_auto_configure)
        top_bar.addWidget(auto_btn)
        root.addLayout(top_bar)

        self.auto_hint_lbl = QtWidgets.QLabel("勾选需要展示在看板上的 AI 账户，未勾选的账户将自动隐藏以节省空间。")
        self.auto_hint_lbl.setWordWrap(True)
        self.auto_hint_lbl.setStyleSheet("font-size: 11px; color: #7A6754;")
        root.addWidget(self.auto_hint_lbl)

        # 中部：5 个账户配置卡片列表
        detected_map = self._diagnostics.get("detected", {})
        cnt_map = {
            "codex": self._diagnostics.get("codex_count", 0),
            "antigravity": self._diagnostics.get("antigravity_count", 0),
            "claude_code": self._diagnostics.get("claude_count", 0),
            "deepseek_harness": self._diagnostics.get("deepseek_count", 0),
        }

        win_choices = [("3h", 3.0), ("5h", 5.0), ("24h", 24.0), ("7天", 168.0), ("30天", 720.0)]

        for acc in self._accounts:
            aid = str(acc.get("id", ""))
            card = PaperCardFrame(bg_color="#FCF9F2", radius=9)
            clayout = QtWidgets.QVBoxLayout(card)
            clayout.setContentsMargins(10, 7, 10, 7)
            clayout.setSpacing(5)

            r1 = QtWidgets.QHBoxLayout()
            r1.setSpacing(8)
            vis_chk = QtWidgets.QCheckBox(DISPLAY_NAMES.get(aid, str(acc.get("name", ""))))
            vis_chk.setChecked(bool(acc.get("visible", True)))
            vis_chk.setStyleSheet("font-size: 13px; font-weight: bold; color: #382C22;")
            r1.addWidget(vis_chk)

            status_lbl = QtWidgets.QLabel()
            if aid == "chatgpt":
                status_lbl.setText("手动记录模式")
                status_lbl.setStyleSheet("font-size: 10px; color: #8A7662;")
            else:
                is_det = bool(detected_map.get(aid))
                scnt = int(cnt_map.get(aid, 0))
                if is_det:
                    status_lbl.setText("✔ 已自动关联本地 ({} 会话)".format(scnt))
                    status_lbl.setStyleSheet("font-size: 10px; font-weight: bold; color: #247A56;")
                else:
                    status_lbl.setText("未检测到默认目录 (可在下方指定)")
                    status_lbl.setStyleSheet("font-size: 10px; color: #9E8B76;")
            r1.addStretch()
            r1.addWidget(status_lbl)
            clayout.addLayout(r1)

            r2 = QtWidgets.QHBoxLayout()
            r2.setSpacing(6)
            r2.addWidget(QtWidgets.QLabel("剩余:"))

            pct_spin = QtWidgets.QSpinBox()
            pct_spin.setRange(0, 100)
            pct_spin.setSuffix("%")
            pct_spin.setValue(int(acc.get("remaining_pct", 100)))
            pct_spin.setFixedWidth(68)
            r2.addWidget(pct_spin)

            r2.addWidget(QtWidgets.QLabel("周期:"))
            win_combo = QtWidgets.QComboBox()
            cur_w = float(acc.get("window_hours", 5.0))
            w_idx = 1
            for idx, (w_lbl, w_val) in enumerate(win_choices):
                win_combo.addItem(w_lbl, w_val)
                if abs(cur_w - w_val) < 0.2:
                    w_idx = idx
            win_combo.setCurrentIndex(w_idx)
            win_combo.setFixedWidth(66)
            r2.addWidget(win_combo)

            full_btn = QtWidgets.QPushButton("满额100%")
            full_btn.setObjectName("GamePillBtn")
            full_btn.setCursor(QtCore.Qt.PointingHandCursor)
            full_btn.clicked.connect(lambda _c=False, sp=pct_spin: sp.setValue(100))
            r2.addStretch()
            r2.addWidget(full_btn)
            clayout.addLayout(r2)

            self._row_controls[aid] = {
                "visible": vis_chk,
                "status_lbl": status_lbl,
                "pct": pct_spin,
                "win": win_combo,
                "orig_pct": int(acc.get("remaining_pct", 100)),
            }
            root.addWidget(card)

        # 高级路径区：完整包含 Codex / Antigravity / Claude Code / DeepSeek Harness 四个目录与浏览按钮
        adv_box = PaperCardFrame(bg_color="#F6EFE2", radius=9)
        adv_layout = QtWidgets.QFormLayout(adv_box)
        adv_layout.setContentsMargins(10, 8, 10, 8)
        adv_layout.setSpacing(6)

        def _dir_hint(diag_key: str, fallback: str) -> str:
            dirs = self._diagnostics.get(diag_key) or []
            if dirs:
                return "自动识别: " + str(dirs[0])
            return fallback

        self.codex_dir_edit = QtWidgets.QLineEdit("; ".join(self._custom_paths.get("codex_dirs", [])))
        self.codex_dir_edit.setPlaceholderText(_dir_hint("codex_dirs", "默认自动探测 ~/.codex"))
        adv_layout.addRow("Codex 目录:", self._wrap_dir_picker(self.codex_dir_edit))

        self.agy_dir_edit = QtWidgets.QLineEdit("; ".join(self._custom_paths.get("antigravity_dirs", [])))
        self.agy_dir_edit.setPlaceholderText(
            _dir_hint("antigravity_dirs", "默认自动探测 ~/.gemini/antigravity/brain")
        )
        adv_layout.addRow("Antigravity 目录:", self._wrap_dir_picker(self.agy_dir_edit))

        self.claude_dir_edit = QtWidgets.QLineEdit("; ".join(self._custom_paths.get("claude_dirs", [])))
        self.claude_dir_edit.setPlaceholderText(_dir_hint("claude_dirs", "默认自动探测 ~/.claude"))
        adv_layout.addRow("Claude 目录:", self._wrap_dir_picker(self.claude_dir_edit))

        self.ds_dir_edit = QtWidgets.QLineEdit("; ".join(self._custom_paths.get("deepseek_dirs", [])))
        self.ds_dir_edit.setPlaceholderText(_dir_hint("deepseek_dirs", "默认自动探测 $DSH_HOME / ~/.dsh"))
        adv_layout.addRow("DSH 目录:", self._wrap_dir_picker(self.ds_dir_edit))

        self.interval_spin = QtWidgets.QSpinBox()
        self.interval_spin.setRange(5, 300)
        self.interval_spin.setSuffix(" 秒")
        self.interval_spin.setValue(max(5, self._scan_interval))
        adv_layout.addRow("自动刷新间隔:", self.interval_spin)
        root.addWidget(adv_box)

        # 常驻与开机自启 + 持久化存档目录卡片
        boot_box = PaperCardFrame(bg_color="#FCF9F2", radius=9)
        boot_layout = QtWidgets.QVBoxLayout(boot_box)
        boot_layout.setContentsMargins(10, 8, 10, 8)
        boot_layout.setSpacing(5)

        boot_row1 = QtWidgets.QHBoxLayout()
        self.autostart_chk = QtWidgets.QCheckBox("🚀 开机自动启动 (登录 Windows 后自动常驻桌面)")
        self.autostart_chk.setChecked(self._autostart_enabled)
        self.autostart_chk.setStyleSheet("font-weight: bold; color: #382C22;")
        boot_row1.addWidget(self.autostart_chk)
        boot_row1.addStretch()
        boot_layout.addLayout(boot_row1)

        boot_row2 = QtWidgets.QHBoxLayout()
        self.boot_mini_chk = QtWidgets.QCheckBox("开机自启时默认收起为迷你形态 (圆形图标 / 窄条)")
        self.boot_mini_chk.setChecked(self._boot_in_mini)
        self.boot_mini_chk.setStyleSheet("color: #5C4938;")
        boot_row2.addWidget(self.boot_mini_chk)
        boot_row2.addStretch()

        if self._data_dir_path:
            open_data_btn = QtWidgets.QPushButton("📂 打开存档目录")
            open_data_btn.setObjectName("GamePillBtn")
            open_data_btn.setCursor(QtCore.Qt.PointingHandCursor)
            open_data_btn.setToolTip("待办事项实时保存在: " + self._data_dir_path)
            open_data_btn.clicked.connect(self._open_data_folder)
            boot_row2.addWidget(open_data_btn)
        boot_layout.addLayout(boot_row2)
        root.addWidget(boot_box)

        # 底部确认栏
        btns = QtWidgets.QHBoxLayout()
        btns.addStretch()
        c_btn = QtWidgets.QPushButton("取消")
        c_btn.setObjectName("SoftBtn")
        c_btn.clicked.connect(self.reject)

        s_btn = QtWidgets.QPushButton("保存并应用")
        s_btn.setObjectName("GameGoldBtn")
        s_btn.setCursor(QtCore.Qt.PointingHandCursor)
        s_btn.clicked.connect(self.accept)
        btns.addWidget(c_btn)
        btns.addWidget(s_btn)
        root.addLayout(btns)

    def _wrap_dir_picker(self, line_edit: QtWidgets.QLineEdit) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        lay.addWidget(line_edit, 1)

        pick_btn = QtWidgets.QPushButton("浏览")
        pick_btn.setObjectName("GamePillBtn")
        pick_btn.setCursor(QtCore.Qt.PointingHandCursor)
        pick_btn.setFixedHeight(26)
        pick_btn.clicked.connect(lambda _c=False, le=line_edit: self._pick_folder_into(le))
        lay.addWidget(pick_btn)
        return box

    def _pick_folder_into(self, line_edit: QtWidgets.QLineEdit) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "选择数据目录")
        if folder:
            cur = line_edit.text().strip()
            line_edit.setText((cur + "; " + folder) if cur else folder)

    def _run_auto_configure(self) -> None:
        if self._auto_detect_fn is not None:
            fresh_diag = self._auto_detect_fn() or {}
            self._diagnostics = fresh_diag

        detected = self._diagnostics.get("detected", {})
        cnt_map = {
            "codex": self._diagnostics.get("codex_count", 0),
            "antigravity": self._diagnostics.get("antigravity_count", 0),
            "claude_code": self._diagnostics.get("claude_count", 0),
            "deepseek_harness": self._diagnostics.get("deepseek_count", 0),
        }
        enabled_names = []  # type: List[str]
        for aid, ctrls in self._row_controls.items():
            if aid == "chatgpt":
                continue
            is_det = bool(detected.get(aid))
            scnt = int(cnt_map.get(aid, 0))
            if is_det:
                ctrls["visible"].setChecked(True)
                ctrls["status_lbl"].setText("✔ 已自动配置 ({} 会话)".format(scnt))
                ctrls["status_lbl"].setStyleSheet("font-size: 10px; font-weight: bold; color: #247A56;")
                enabled_names.append(DISPLAY_NAMES.get(aid, aid))
            else:
                ctrls["status_lbl"].setText("本机暂未检测到默认目录")
                ctrls["status_lbl"].setStyleSheet("font-size: 10px; color: #9E8B76;")

        if enabled_names:
            self.auto_hint_lbl.setText(
                "✔ 自动检测完成！已关联并勾选：{}（点击右下角「保存并应用」生效）".format("、".join(enabled_names))
            )
            self.auto_hint_lbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #247A56;")
        else:
            self.auto_hint_lbl.setText("未检测到额外工具默认目录，可在下方手动填写自定义目录。")

    def _open_data_folder(self) -> None:
        if self._data_dir_path:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self._data_dir_path))

    def get_result(self) -> Dict[str, Any]:
        acc_updates = {}  # type: Dict[str, Dict[str, Any]]
        for aid, ctrls in self._row_controls.items():
            new_pct = ctrls["pct"].value()
            acc_updates[aid] = {
                "visible": ctrls["visible"].isChecked(),
                "remaining_pct": new_pct,
                "pct_changed": new_pct != ctrls["orig_pct"],
                "window_hours": float(ctrls["win"].currentData() or 5.0),
            }
        return {
            "accounts": acc_updates,
            "custom_paths": {
                "codex_dirs": [x.strip() for x in self.codex_dir_edit.text().split(";") if x.strip()],
                "antigravity_dirs": [x.strip() for x in self.agy_dir_edit.text().split(";") if x.strip()],
                "claude_dirs": [x.strip() for x in self.claude_dir_edit.text().split(";") if x.strip()],
                "deepseek_dirs": [x.strip() for x in self.ds_dir_edit.text().split(";") if x.strip()],
            },
            "scan_interval_sec": self.interval_spin.value(),
            "autostart_enabled": self.autostart_chk.isChecked(),
            "boot_in_mini_mode": self.boot_mini_chk.isChecked(),
        }


class AccountQuotaCard(PaperCardFrame):
    """
    无按钮极简版 AI 额度体力槽卡片
    去掉了 + / - 按钮，整洁清爽，点击整张卡片即可快速校准该账户额度。
    """

    calibrateClicked = QtCore.pyqtSignal(str)

    def __init__(
        self,
        account: Dict[str, Any],
        activity_text: str = "",
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(AccountQuotaCard, self).__init__(radius=9, parent=parent)
        self.account_id = str(account.get("id", ""))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self._init_ui()
        self.update_card(account, activity_text)

    def _init_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(9, 6, 9, 6)
        root.setSpacing(4)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(7)

        self.ring = QuotaRingBadge(diameter=28, dark_bg=False)
        top.addWidget(self.ring)

        self.name_lbl = QtWidgets.QLabel()
        self.name_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #382C22;")
        top.addWidget(self.name_lbl)

        self.sub_lbl = ElidedLabel()
        self.sub_lbl.setStyleSheet("font-size: 11px; color: #8A7662;")
        top.addWidget(self.sub_lbl, 1)

        self.pct_lbl = QtWidgets.QLabel("100%")
        self.pct_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        top.addWidget(self.pct_lbl)

        root.addLayout(top)

        self.bar = GameStaminaBar(bar_height=7)
        root.addWidget(self.bar)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.pos()):
            self.calibrateClicked.emit(self.account_id)
        super(AccountQuotaCard, self).mouseReleaseEvent(event)

    def update_card(self, account: Dict[str, Any], activity_text: str = "") -> None:
        aid = str(account.get("id", ""))
        pct = int(account.get("remaining_pct", 100))
        brand = ACCOUNT_BRAND_COLORS.get(aid, str(account.get("color", "#3B78CC")))
        short = str(account.get("short_label", "AI"))

        self.ring.set_data(short, pct, brand)
        disp_name = DISPLAY_NAMES.get(aid, str(account.get("name", "")))
        self.name_lbl.setText(disp_name)

        cd_text = format_countdown(account.get("reset_at"))
        if activity_text:
            self.sub_lbl.set_full_text("· {} · {}".format(activity_text, cd_text))
        else:
            self.sub_lbl.set_full_text("· " + cd_text)

        active_col = quota_status_color(pct, brand)
        sec_pct = account.get("secondary_pct")
        if sec_pct is not None:
            self.pct_lbl.setText(
                "{}% <span style='font-size:10px;color:#8C7862;'>(周{}%)</span>".format(pct, int(sec_pct))
            )
        else:
            self.pct_lbl.setText("{}%".format(pct))
        self.pct_lbl.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: {};".format(active_col)
        )

        self.bar.set_value(pct, brand)
        tip = [
            "✦ {} (剩余 {}%)".format(disp_name, pct),
            "恢复时间: {}".format(cd_text),
        ]
        if activity_text:
            tip.append("本地活跃: {}".format(activity_text))
        tip.append("点击此卡片可单独调整额度滑块与恢复时间")
        self.setToolTip("\n".join(tip))


class SessionItemCard(PaperCardFrame):
    """窄列优化版：AI 对话卷轴卡片"""

    actionTriggered = QtCore.pyqtSignal(str, str)

    def __init__(
        self, session: Dict[str, Any], parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        super(SessionItemCard, self).__init__(radius=9, parent=parent)
        self.session = session
        self.session_key = str(session.get("key", ""))
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 6)
        layout.setSpacing(3)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)

        provider = str(self.session.get("provider", "antigravity"))
        p_short, p_fg, p_bg, p_bd = PROVIDER_META.get(
            provider, ("AI", "#2962B0", "#E6F0FC", "#ADCBE8")
        )

        badge = QtWidgets.QLabel(p_short)
        badge.setAlignment(QtCore.Qt.AlignCenter)
        badge.setFixedSize(32, 19)
        badge.setStyleSheet(
            "background-color:{}; color:{}; border:1px solid {}; border-radius:5px; font-size:10px; font-weight:bold;".format(
                p_bg, p_fg, p_bd
            )
        )
        top.addWidget(badge)

        title_str = str(self.session.get("display_title") or self.session.get("title") or "未命名对话")
        if self.session.get("pinned"):
            title_str = "⤒ " + title_str

        self.title_lbl = ElidedLabel(title_str)
        self.title_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #382C22;")
        top.addWidget(self.title_lbl, 1)

        rel_time_str = format_relative_time(self.session.get("updated_at"))
        time_lbl = QtWidgets.QLabel(rel_time_str)
        time_lbl.setStyleSheet("font-size: 10px; color: #9A8772;")
        top.addWidget(time_lbl)

        eff_status = str(self.session.get("effective_status") or self.session.get("status") or "completed")
        st_text, st_fg, st_bg, st_bd = STATUS_META.get(eff_status, STATUS_META["completed"])

        status_btn = QtWidgets.QPushButton(st_text)
        status_btn.setCursor(QtCore.Qt.PointingHandCursor)
        status_btn.setFixedHeight(20)
        status_btn.setStyleSheet(
            "QPushButton {{ background-color:{}; color:{}; border:1px solid {}; border-radius:9px; padding:0px 7px; font-size:10px; font-weight:bold; }}"
            "QPushButton:hover {{ background-color:{}; color:#FFFFFF; }}".format(
                st_bg, st_fg, st_bd, st_fg
            )
        )
        status_btn.clicked.connect(self._show_context_menu)
        top.addWidget(status_btn)

        layout.addLayout(top)

        # 第二行小字：优先展示上一条用户发送的 Prompt
        last_prompt = str(self.session.get("last_prompt") or "").strip()
        detail = str(self.session.get("status_detail") or "")
        ws = str(self.session.get("workspace") or "")
        steps = int(self.session.get("step_count") or 0)

        if last_prompt:
            sub_str = "▸ " + last_prompt
            sub_col = "#6E5B49"
        else:
            meta_parts = []
            if detail:
                meta_parts.append(detail)
            if ws:
                meta_parts.append(ws)
            if steps > 0:
                meta_parts.append("{}步".format(steps))
            sub_str = " · ".join(meta_parts) if meta_parts else rel_time_str
            sub_col = "#8A7662"

        sub_lbl = ElidedLabel(sub_str)
        sub_lbl.setStyleSheet("font-size: 11px; color: {};".format(sub_col))
        layout.addWidget(sub_lbl)

        toks = int(self.session.get("total_tokens") or 0)
        tip_lines = [
            "对话名称: {}".format(title_str),
        ]
        if last_prompt:
            tip_lines.append("上一条提问: {}".format(last_prompt))
        tip_lines.extend(
            [
                "平台: {} ({})".format(self.session.get("provider_label") or provider, rel_time_str),
                "状态: {} ({})".format(st_text, detail or "自动识别"),
            ]
        )
        if ws:
            tip_lines.append("目录: {}".format(ws))
        if steps or toks:
            tip_lines.append("用量: {} 步 / {} tokens".format(steps, format_tokens(toks)))
        tip_lines.append("点击右侧状态印章或右键卡片可修改状态 / 置顶 / 归档")
        self.setToolTip("\n".join(tip_lines))

    def contextMenuEvent(self, _event: QtGui.QContextMenuEvent) -> None:
        self._show_context_menu()

    def _show_context_menu(self) -> None:
        menu = QtWidgets.QMenu(self)
        act_done = menu.addAction("✔ 标记为「已完成」")
        act_run = menu.addAction("✦ 标记为「进行中」")
        act_wait = menu.addAction("💬 标记为「待确认/跟进」")
        act_auto = None if self.session.get("is_manual") else menu.addAction("🔄 恢复自动识别状态")

        menu.addSeparator()
        pin_label = "取消置顶" if self.session.get("pinned") else "⤒ 置顶此对话"
        act_pin = menu.addAction(pin_label)
        act_rename = menu.addAction("✏️ 修改备注标题...")

        if self.session.get("is_manual"):
            act_del = menu.addAction("🗑 删除此记录")
            act_hide = None
        else:
            act_hide = menu.addAction("🙈 归档隐藏此条")
            act_del = None

        chosen = menu.exec_(QtGui.QCursor.pos())
        if not chosen:
            return
        if chosen == act_done:
            self.actionTriggered.emit(self.session_key, "status:completed")
        elif chosen == act_run:
            self.actionTriggered.emit(self.session_key, "status:running")
        elif chosen == act_wait:
            self.actionTriggered.emit(self.session_key, "status:waiting")
        elif act_auto and chosen == act_auto:
            self.actionTriggered.emit(self.session_key, "status:auto")
        elif chosen == act_pin:
            self.actionTriggered.emit(self.session_key, "toggle_pin")
        elif chosen == act_rename:
            self.actionTriggered.emit(self.session_key, "rename")
        elif act_hide and chosen == act_hide:
            self.actionTriggered.emit(self.session_key, "hide")
        elif act_del and chosen == act_del:
            self.actionTriggered.emit(self.session_key, "delete_manual")


class GameQuestCheckbox(QtWidgets.QWidget):
    """游戏日常委托印章式勾选框"""

    toggled = QtCore.pyqtSignal()

    def __init__(self, checked: bool = False, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(GameQuestCheckbox, self).__init__(parent)
        self._checked = bool(checked)
        self._hovered = False
        self.setFixedSize(22, 22)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super(GameQuestCheckbox, self).enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super(GameQuestCheckbox, self).leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._checked = not self._checked
            self.update()
            self.toggled.emit()

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = QtCore.QRectF(2.0, 2.0, 18.0, 18.0)

        if self._checked:
            grad = QtGui.QLinearGradient(2, 2, 20, 20)
            grad.setColorAt(0.0, QtGui.QColor("#3BB282"))
            grad.setColorAt(1.0, QtGui.QColor("#268C62"))
            p.setPen(QtGui.QPen(QtGui.QColor("#1E7551"), 1.0))
            p.setBrush(QtGui.QBrush(grad))
            p.drawRoundedRect(rect, 6.0, 6.0)

            pen = QtGui.QPen(
                QtGui.QColor("#FFFFFF"), 2.2, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin
            )
            p.setPen(pen)
            p.drawLine(QtCore.QPointF(6.5, 11.2), QtCore.QPointF(9.6, 14.3))
            p.drawLine(QtCore.QPointF(9.6, 14.3), QtCore.QPointF(15.5, 7.6))
        else:
            p.setBrush(QtGui.QColor("#FFFDF9"))
            bd_col = "#D98A2B" if self._hovered else "#C7B293"
            p.setPen(QtGui.QPen(QtGui.QColor(bd_col), 1.6))
            p.drawRoundedRect(rect, 6.0, 6.0)
            if self._hovered:
                draw_four_point_star(p, 11.0, 11.0, 3.8, QtGui.QColor(217, 138, 43, 120))
        p.end()


class PinTopButton(QtWidgets.QWidget):
    """
    标准常用「置顶」矢量图标按钮（顶部横线 + 向上箭头 ⤒，告别五角星收藏图标）
    支持激活高亮态与悬停反馈。
    """

    clicked = QtCore.pyqtSignal()

    def __init__(self, pinned: bool = False, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(PinTopButton, self).__init__(parent)
        self._pinned = bool(pinned)
        self._hovered = False
        self.setFixedSize(22, 20)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self.setToolTip("取消置顶" if self._pinned else "置顶此待办")

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super(PinTopButton, self).enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super(PinTopButton, self).leaveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super(PinTopButton, self).mouseReleaseEvent(event)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        bg_rect = QtCore.QRectF(1.0, 1.0, w - 2.0, h - 2.0)

        if self._pinned:
            p.setBrush(QtGui.QColor("#FDF0DC"))
            p.setPen(QtGui.QPen(QtGui.QColor("#E5A94C"), 1.1))
            p.drawRoundedRect(bg_rect, 5.0, 5.0)
            icon_col = QtGui.QColor("#D47A18")
            stroke_w = 1.9
        elif self._hovered:
            p.setBrush(QtGui.QColor("#EAE0CE"))
            p.setPen(QtCore.Qt.NoPen)
            p.drawRoundedRect(bg_rect, 5.0, 5.0)
            icon_col = QtGui.QColor("#382C22")
            stroke_w = 1.7
        else:
            icon_col = QtGui.QColor("#9A8772")
            stroke_w = 1.5

        pen = QtGui.QPen(icon_col, stroke_w, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
        p.setPen(pen)

        cx = w * 0.5
        # 1. 顶部置顶横杠
        p.drawLine(QtCore.QPointF(cx - 4.8, 4.5), QtCore.QPointF(cx + 4.8, 4.5))
        # 2. 向上箭头主干
        p.drawLine(QtCore.QPointF(cx, 15.5), QtCore.QPointF(cx, 7.2))
        # 3. 向上箭头两翼
        p.drawLine(QtCore.QPointF(cx - 3.8, 10.6), QtCore.QPointF(cx, 7.0))
        p.drawLine(QtCore.QPointF(cx + 3.8, 10.6), QtCore.QPointF(cx, 7.0))

        p.end()


class TodoItemRow(PaperCardFrame):
    """个人待办事项卡片：支持勾选完成、普通/重要两档切换、常用置顶图标、双击编辑与删除"""

    toggleRequested = QtCore.pyqtSignal(str)
    deleteRequested = QtCore.pyqtSignal(str)
    pinRequested = QtCore.pyqtSignal(str, bool)
    priorityCycleRequested = QtCore.pyqtSignal(str, str)
    editRequested = QtCore.pyqtSignal(str, str)
    editDialogRequested = QtCore.pyqtSignal(str, str)

    def __init__(
        self, todo: Dict[str, Any], parent: Optional[QtWidgets.QWidget] = None
    ) -> None:
        done = bool(todo.get("done"))
        raw_prio = str(todo.get("priority", "normal"))
        norm_prio = "high" if raw_prio in ("high", "urgent") else "normal"
        _p_lbl, p_col, _p_bg = PRIORITY_META[norm_prio]
        bg = COLORS["bg_card_done"] if done else COLORS["bg_card"]
        stripe = "#C9BCA6" if done else p_col
        super(TodoItemRow, self).__init__(bg_color=bg, accent_stripe=stripe, radius=9, parent=parent)
        self.todo = todo
        self.todo_id = str(todo.get("id", ""))
        self._norm_prio = norm_prio
        self._init_ui()

    def _init_ui(self) -> None:
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(12, 7, 7, 7)
        row.setSpacing(6)

        done = bool(self.todo.get("done"))
        chk = GameQuestCheckbox(checked=done)
        chk.toggled.connect(lambda: self.toggleRequested.emit(self.todo_id))
        row.addWidget(chk, 0, QtCore.Qt.AlignTop)

        txt = str(self.todo.get("text", ""))
        self.text_lbl = QtWidgets.QLabel(txt)
        self.text_lbl.setWordWrap(True)
        font = self.text_lbl.font()
        font.setStrikeOut(done)
        self.text_lbl.setFont(font)
        color_hex = "#9E8B76" if done else "#382C22"
        self.text_lbl.setStyleSheet("color: {}; font-size: 12px; line-height: 1.35;".format(color_hex))
        self.text_lbl.setToolTip("双击文字可直接修改内容")
        row.addWidget(self.text_lbl, 1)

        p_label, p_color, p_bg = PRIORITY_META[self._norm_prio]
        next_prio = "normal" if self._norm_prio == "high" else "high"

        prio_btn = QtWidgets.QPushButton(p_label)
        prio_btn.setCursor(QtCore.Qt.PointingHandCursor)
        prio_btn.setToolTip("点击切换「普通 / 重要」")
        prio_btn.setFixedSize(34, 20)
        prio_btn.setStyleSheet(
            "QPushButton {{ background-color: {}; color: {}; border: 1px solid {}; border-radius: 5px; font-size: 10px; font-weight: bold; padding: 0px; }}"
            "QPushButton:hover {{ background-color: {}; color: #FFFFFF; }}".format(
                p_bg, p_color, p_color, p_color
            )
        )
        prio_btn.clicked.connect(
            lambda: self.priorityCycleRequested.emit(self.todo_id, next_prio)
        )
        row.addWidget(prio_btn, 0, QtCore.Qt.AlignTop)

        pinned = bool(self.todo.get("pinned"))
        pin_btn = PinTopButton(pinned=pinned)
        pin_btn.clicked.connect(lambda: self.pinRequested.emit(self.todo_id, not pinned))
        row.addWidget(pin_btn, 0, QtCore.Qt.AlignTop)

        del_btn = QtWidgets.QPushButton("×")
        del_btn.setObjectName("SoftBtn")
        del_btn.setFixedSize(20, 20)
        del_btn.setCursor(QtCore.Qt.PointingHandCursor)
        del_btn.setToolTip("删除待办")
        del_btn.clicked.connect(lambda: self.deleteRequested.emit(self.todo_id))
        row.addWidget(del_btn, 0, QtCore.Qt.AlignTop)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        # 不在条目内部弹对话框：条目会随自动刷新被销毁，对话框必须由长期存活的主面板持有。
        if event.button() == QtCore.Qt.LeftButton:
            self.editDialogRequested.emit(self.todo_id, str(self.todo.get("text", "")))
            return
        super(TodoItemRow, self).mouseDoubleClickEvent(event)
