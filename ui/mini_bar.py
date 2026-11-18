# -*- coding: utf-8 -*-
"""
高清 4x 超采样 (SSAA) 迷你悬浮胶囊 / 圆形图标悬浮球窗口
专门针对 Windows 高分屏抗锯齿深度优化：
- 圆形图标采用 4x 物理分辨率离屏超采样渲染 + SmoothTransformation 下采样，边缘与文字如矢量般锐利清晰
- 支持记忆圆形球/胶囊条形态，右键菜单支持一键切换开机自启
"""

from typing import Any, Dict, List, Optional
from PyQt5 import QtCore, QtGui, QtWidgets

from core.startup import is_autostart_enabled
from ui.theme import ACCOUNT_BRAND_COLORS, quota_status_color
from ui.widgets import QuotaRingBadge


class MiniFloatingWidget(QtWidgets.QWidget):
    expandRequested = QtCore.pyqtSignal()
    refreshRequested = QtCore.pyqtSignal()
    toggleTopRequested = QtCore.pyqtSignal(bool)
    toggleAutostartRequested = QtCore.pyqtSignal(bool)
    orbStyleChanged = QtCore.pyqtSignal(bool)
    quitRequested = QtCore.pyqtSignal()
    positionChanged = QtCore.pyqtSignal(int, int)

    ORB_LOGICAL_SIZE = 68

    def __init__(
        self,
        always_on_top: bool = True,
        orb_style: bool = False,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(MiniFloatingWidget, self).__init__(parent)
        self._always_on_top = always_on_top
        self._orb_style = bool(orb_style)
        self._drag_offset = None  # type: Optional[QtCore.QPoint]
        self._press_global = None  # type: Optional[QtCore.QPoint]
        self._accounts_cache = []  # type: List[Dict[str, Any]]
        self._active_sessions = 0
        self._pending_todos = 0
        self._hovered = False

        self._apply_window_flags()
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_Hover, True)
        self.setCursor(QtCore.Qt.OpenHandCursor)

        self._init_ui()
        self._apply_style_geometry()

    def _apply_window_flags(self) -> None:
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        if self._always_on_top:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def set_always_on_top(self, on_top: bool) -> None:
        if self._always_on_top == on_top:
            return
        was_visible = self.isVisible()
        self._always_on_top = on_top
        self._apply_window_flags()
        if was_visible:
            self.show()

    def set_orb_style(self, orb: bool) -> None:
        if self._orb_style != bool(orb):
            self._orb_style = bool(orb)
            self._apply_style_geometry()

    def _init_ui(self) -> None:
        self.pill_container = QtWidgets.QWidget(self)
        self.pill_row = QtWidgets.QHBoxLayout(self.pill_container)
        self.pill_row.setContentsMargins(10, 6, 8, 6)
        self.pill_row.setSpacing(6)

        self.rings_layout = QtWidgets.QHBoxLayout()
        self.rings_layout.setSpacing(5)
        self.pill_row.addLayout(self.rings_layout)

        self.sep = QtWidgets.QFrame()
        self.sep.setFixedSize(1, 20)
        self.sep.setStyleSheet("background-color: #6B5645;")
        self.pill_row.addWidget(self.sep)

        self.stat_lbl = QtWidgets.QLabel("0 | ☑0")
        self.stat_lbl.setStyleSheet("font-size: 12px; font-weight: bold; color: #FAF0E1;")
        self.pill_row.addWidget(self.stat_lbl)

        # 快捷切换为圆形悬浮球的紧凑按钮
        orb_btn = QtWidgets.QPushButton("●")
        orb_btn.setToolTip("缩为高清圆形悬浮图标")
        orb_btn.setCursor(QtCore.Qt.PointingHandCursor)
        orb_btn.setFixedSize(22, 22)
        orb_btn.setStyleSheet(
            "QPushButton { background-color: rgba(255,248,235,28); color: #F0B456; border: 1px solid rgba(240,180,86,95); border-radius: 11px; font-size: 10px; padding: 0px; }"
            "QPushButton:hover { background-color: #E89B3C; color: #261E18; }"
        )
        orb_btn.clicked.connect(self._switch_to_orb)
        self.pill_row.addWidget(orb_btn)

        expand_btn = QtWidgets.QPushButton("⤢")
        expand_btn.setToolTip("展开 AI BOARD 双栏看板 (也可双击浮窗)")
        expand_btn.setCursor(QtCore.Qt.PointingHandCursor)
        expand_btn.setFixedSize(26, 26)
        expand_btn.setStyleSheet(
            "QPushButton { background-color: #E89B3C; color: #261E18; border: none; border-radius: 13px; font-size: 13px; font-weight: bold; padding: 0px; }"
            "QPushButton:hover { background-color: #F3AC52; }"
        )
        expand_btn.clicked.connect(self.expandRequested.emit)
        self.pill_row.addWidget(expand_btn)

    def _switch_to_orb(self) -> None:
        self._orb_style = True
        self._apply_style_geometry()
        self.orbStyleChanged.emit(True)

    def _apply_style_geometry(self) -> None:
        if self._orb_style:
            self.pill_container.setVisible(False)
            self.setFixedSize(self.ORB_LOGICAL_SIZE, self.ORB_LOGICAL_SIZE)
        else:
            self.pill_container.setVisible(True)
            ring_cnt = len(self._accounts_cache)
            pill_w = max(190, 166 + ring_cnt * 35)
            self.setFixedSize(pill_w, 46)
            self.pill_container.setGeometry(0, 0, pill_w, 46)
        self.update()

    def update_summary(
        self,
        accounts: List[Dict[str, Any]],
        active_sessions: int,
        total_sessions: int,
        pending_todos: int,
    ) -> None:
        vis_accounts = [a for a in accounts if a.get("visible", True)]
        self._accounts_cache = vis_accounts
        self._active_sessions = int(active_sessions)
        self._pending_todos = int(pending_todos)

        while self.rings_layout.count():
            child = self.rings_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        for acc in vis_accounts:
            aid = str(acc.get("id", ""))
            short = str(acc.get("short_label", "AI"))
            pct = int(acc.get("remaining_pct", 100))
            col = ACCOUNT_BRAND_COLORS.get(aid, str(acc.get("color", "#3B78CC")))
            ring = QuotaRingBadge(short, pct, col, diameter=30, dark_bg=True)
            self.rings_layout.addWidget(ring)

        self.sep.setVisible(len(vis_accounts) > 0)

        if active_sessions > 0:
            self.stat_lbl.setText(
                "<span style='color:#F5C26B;'>⚡{}</span> <span style='color:#8A725E;'>|</span> ☑{}".format(
                    active_sessions, pending_todos
                )
            )
        else:
            self.stat_lbl.setText(
                "<span style='color:#D5C2A5;'>💬{}</span> <span style='color:#8A725E;'>|</span> ☑{}".format(
                    total_sessions, pending_todos
                )
            )

        tip_lines = ["AI BOARD · 迷你悬浮模式 (单击/双击展开主看板)"]
        for a in vis_accounts:
            tip_lines.append("• {}: 剩余 {}%".format(a.get("name"), a.get("remaining_pct", 100)))
        tip_lines.append("• 活跃对话: {} 个 | 待办事项: {} 项".format(active_sessions, pending_todos))
        tip_lines.append("右键可切换「胶囊窄条 / 圆形图标」及开机自启")
        self.setToolTip("\n".join(tip_lines))
        self._apply_style_geometry()

    def enterEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = True
        self.update()
        super(MiniFloatingWidget, self).enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hovered = False
        self.update()
        super(MiniFloatingWidget, self).leaveEvent(event)

    # ------------------------------------------------------------------
    # 4x 超采样离屏抗锯齿绘制，彻底消除圆形边缘与细字锯齿感
    # ------------------------------------------------------------------
    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        target_w = max(1, int(round(self.width() * dpr)))
        target_h = max(1, int(round(self.height() * dpr)))

        if not self._orb_style:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setRenderHint(QtGui.QPainter.HighQualityAntialiasing, True)
            rect = QtCore.QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
            grad = QtGui.QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QtGui.QColor(56, 45, 37, 248))
            grad.setColorAt(1.0, QtGui.QColor(39, 31, 25, 250))
            p.setBrush(QtGui.QBrush(grad))
            border_c = "#F0B456" if self._hovered else "#B8986C"
            p.setPen(QtGui.QPen(QtGui.QColor(border_c), 1.4))
            p.drawRoundedRect(rect, 21.5, 21.5)
            p.end()
            return

        # 圆形悬浮球：使用 4x 物理超采样画布绘制再平滑缩放回窗口物理分辨率
        ss_factor = 4
        ss_size = max(256, target_w * ss_factor)
        img = QtGui.QImage(ss_size, ss_size, QtGui.QImage.Format_ARGB32_Premultiplied)
        img.fill(0)

        sp = QtGui.QPainter(img)
        sp.setRenderHint(QtGui.QPainter.Antialiasing, True)
        sp.setRenderHint(QtGui.QPainter.HighQualityAntialiasing, True)
        sp.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

        S = float(ss_size)
        # 1. 外围柔和环境阴影光晕，消除透明窗体硬边锯齿
        halo_grad = QtGui.QRadialGradient(S * 0.5, S * 0.52, S * 0.49)
        halo_grad.setColorAt(0.0, QtGui.QColor(20, 15, 10, 90))
        halo_grad.setColorAt(0.84, QtGui.QColor(20, 15, 10, 48))
        halo_grad.setColorAt(1.0, QtGui.QColor(20, 15, 10, 0))
        sp.setPen(QtCore.Qt.NoPen)
        sp.setBrush(QtGui.QBrush(halo_grad))
        sp.drawEllipse(QtCore.QRectF(0.0, 0.0, S, S))

        # 2. 主圆盘底面
        pad = S * 0.065
        disc_rect = QtCore.QRectF(pad, pad, S - 2.0 * pad, S - 2.0 * pad)
        disc_grad = QtGui.QLinearGradient(0, pad, 0, S - pad)
        disc_grad.setColorAt(0.0, QtGui.QColor("#3E322A"))
        disc_grad.setColorAt(1.0, QtGui.QColor("#261E19"))
        sp.setBrush(QtGui.QBrush(disc_grad))
        ring_border = "#F4BA62" if self._hovered else "#B8986C"
        sp.setPen(QtGui.QPen(QtGui.QColor(ring_border), S * 0.022))
        sp.drawEllipse(disc_rect)

        # 3. 外圈多账户高清能量圆弧
        arc_pad = S * 0.135
        arc_rect = QtCore.QRectF(arc_pad, arc_pad, S - 2.0 * arc_pad, S - 2.0 * arc_pad)
        arc_stroke = S * 0.062
        n = len(self._accounts_cache)
        if n > 0:
            gap_deg = 16.0 if n > 1 else 0.0
            seg_span = (360.0 - n * gap_deg) / float(n)
            for i, acc in enumerate(self._accounts_cache):
                aid = str(acc.get("id", ""))
                start_deg = 90.0 - i * (seg_span + gap_deg)
                sp.setPen(
                    QtGui.QPen(QtGui.QColor("#4F3F34"), arc_stroke, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
                )
                sp.drawArc(arc_rect, int(start_deg * 16), int(-seg_span * 16))
                pct = int(acc.get("remaining_pct", 100))
                if pct > 0:
                    def_col = ACCOUNT_BRAND_COLORS.get(aid, "#3B78CC")
                    c_hex = quota_status_color(pct, def_col)
                    sp.setPen(
                        QtGui.QPen(QtGui.QColor(c_hex), arc_stroke, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
                    )
                    sp.drawArc(arc_rect, int(start_deg * 16), int(-seg_span * (pct / 100.0) * 16))

        # 4. 中心现代几何琥珀胶囊 "AI" + 下方高清晰数字
        pill_w = S * 0.34
        pill_h = S * 0.175
        pill_rect = QtCore.QRectF((S - pill_w) * 0.5, S * 0.275, pill_w, pill_h)
        sp.setPen(QtCore.Qt.NoPen)
        sp.setBrush(QtGui.QColor("#F0A444"))
        sp.drawRoundedRect(pill_rect, pill_h * 0.38, pill_h * 0.38)

        ai_f = QtGui.QFont("Bahnschrift")
        ai_f.setPixelSize(int(round(S * 0.135)))
        ai_f.setBold(True)
        sp.setFont(ai_f)
        sp.setPen(QtGui.QColor("#261E18"))
        sp.drawText(pill_rect, QtCore.Qt.AlignCenter, "AI")

        num_f = QtGui.QFont("Bahnschrift")
        num_f.setPixelSize(int(round(S * 0.19)))
        num_f.setBold(True)
        sp.setFont(num_f)
        if self._active_sessions > 0:
            sp.setPen(QtGui.QColor("#7CC2FF"))
            num_txt = "{}·{}".format(self._active_sessions, self._pending_todos)
        else:
            sp.setPen(QtGui.QColor("#FAF3E8"))
            num_txt = str(self._pending_todos)
        sp.drawText(
            QtCore.QRectF(0.0, S * 0.47, S, S * 0.28),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter,
            num_txt,
        )
        sp.end()

        downsampled = img.scaled(
            target_w, target_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        pix = QtGui.QPixmap.fromImage(downsampled)
        pix.setDevicePixelRatio(dpr)

        wp = QtGui.QPainter(self)
        wp.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        wp.drawPixmap(0, 0, pix)
        wp.end()

    # ------------------------------------------------------------------
    # 交互与右键菜单
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            self._press_global = event.globalPos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
        super(MiniFloatingWidget, self).mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_offset is not None and (event.buttons() & QtCore.Qt.LeftButton):
            self.move(event.globalPos() - self._drag_offset)
        super(MiniFloatingWidget, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.setCursor(QtCore.Qt.OpenHandCursor)
            screen = QtWidgets.QApplication.desktop().availableGeometry(self)
            x = max(screen.left() + 4, min(self.x(), screen.right() - self.width() - 4))
            y = max(screen.top() + 4, min(self.y(), screen.bottom() - self.height() - 4))
            if x != self.x() or y != self.y():
                self.move(x, y)
            self.positionChanged.emit(self.x(), self.y())

            if self._orb_style and self._press_global is not None:
                dist = (event.globalPos() - self._press_global).manhattanLength()
                if dist <= 4:
                    self.expandRequested.emit()
            self._drag_offset = None
            self._press_global = None
        super(MiniFloatingWidget, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.expandRequested.emit()
        super(MiniFloatingWidget, self).mouseDoubleClickEvent(event)

    def contextMenuEvent(self, _event: QtGui.QContextMenuEvent) -> None:
        menu = QtWidgets.QMenu(self)
        act_expand = menu.addAction("⤢ 展开 AI BOARD 看板")
        style_txt = "💊 切换为「胶囊窄条」形态" if self._orb_style else "● 切换为「高清圆形图标」形态"
        act_style = menu.addAction(style_txt)
        act_refresh = menu.addAction("⟳ 立即扫描刷新")
        menu.addSeparator()

        act_top = menu.addAction("📌 窗口始终置顶")
        act_top.setCheckable(True)
        act_top.setChecked(self._always_on_top)

        act_boot = menu.addAction("🚀 开机自动启动")
        act_boot.setCheckable(True)
        act_boot.setChecked(is_autostart_enabled())

        menu.addSeparator()
        act_quit = menu.addAction("✕ 退出 AI BOARD")

        chosen = menu.exec_(QtGui.QCursor.pos())
        if chosen == act_expand:
            self.expandRequested.emit()
        elif chosen == act_style:
            self._orb_style = not self._orb_style
            self._apply_style_geometry()
            self.orbStyleChanged.emit(self._orb_style)
        elif chosen == act_refresh:
            self.refreshRequested.emit()
        elif chosen == act_top:
            self.toggleTopRequested.emit(act_top.isChecked())
        elif chosen == act_boot:
            self.toggleAutostartRequested.emit(act_boot.isChecked())
        elif chosen == act_quit:
            self.quitRequested.emit()
