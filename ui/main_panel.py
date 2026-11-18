# -*- coding: utf-8 -*-
"""
暖金游戏手账风 · 双列桌面看板主窗口 ("AI 看板")
"""

import time
from typing import Any, Callable, Dict, List, Optional
from PyQt5 import QtCore, QtGui, QtWidgets

from core.startup import is_autostart_enabled, set_autostart
from core.storage import DashboardStorage
from ui.theme import (
    COLORS,
    PRIORITY_META,
    draw_four_point_star,
    format_tokens,
    render_app_pixmap,
)
from ui.widgets import (
    AccountQuotaCard,
    ArtisticBannerTitle,
    GameSectionHeader,
    GameStaminaBar,
    PaperCardFrame,
    QuotaCalibrateDialog,
    QuotaSettingsDialog,
    SessionItemCard,
    TodoItemRow,
)


class ColumnPageTray(QtWidgets.QFrame):
    """左右分栏的柔和羊皮纸内页底托"""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super(ColumnPageTray, self).__init__(parent)

    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = QtCore.QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        p.setBrush(QtGui.QColor(241, 232, 216, 175))
        p.setPen(QtGui.QPen(QtGui.QColor("#DFD0B8"), 1.0))
        p.drawRoundedRect(rect, 12.0, 12.0)
        p.end()


class MainDashboardPanel(QtWidgets.QWidget):
    switchToMiniRequested = QtCore.pyqtSignal()
    refreshRequested = QtCore.pyqtSignal()
    toggleTopRequested = QtCore.pyqtSignal(bool)
    hideToTrayRequested = QtCore.pyqtSignal()
    geometrySaved = QtCore.pyqtSignal(int, int, int, int)
    settingsUpdated = QtCore.pyqtSignal()

    HEADER_HEIGHT = 48

    def __init__(
        self,
        storage: DashboardStorage,
        always_on_top: bool = True,
        auto_detect_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super(MainDashboardPanel, self).__init__(parent)
        self.storage = storage
        self._always_on_top = always_on_top
        self._auto_detect_fn = auto_detect_fn
        self._drag_offset = None  # type: Optional[QtCore.QPoint]
        self._scan_data = {}  # type: Dict[str, Any]
        self._selected_todo_prio = "normal"

        ui_cfg = self.storage.get_ui()
        self._session_filter = str(ui_cfg.get("session_filter") or "all")

        self._apply_window_flags()
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(600, 450)

        size_cfg = ui_cfg.get("panel_size") or [680, 590]
        saved_w, saved_h = int(size_cfg[0]), int(size_cfg[1])
        if saved_w < 580:
            saved_w, saved_h = 680, 590
            self.storage.update_ui(panel_size=[saved_w, saved_h])

        screen_avail = QtWidgets.QApplication.desktop().availableGeometry()
        init_w = min(saved_w, max(600, screen_avail.width() - 40))
        init_h = min(saved_h, max(470, screen_avail.height() - 60))
        self.resize(init_w, init_h)

        self._init_ui()

    def _apply_window_flags(self) -> None:
        flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool
        if self._always_on_top:
            flags |= QtCore.Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def set_always_on_top(self, on_top: bool) -> None:
        if self._always_on_top == on_top:
            self._sync_pin_btn_style()
            return
        was_visible = self.isVisible()
        self._always_on_top = on_top
        self._apply_window_flags()
        self._sync_pin_btn_style()
        if was_visible:
            self.show()

    def _init_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(3, 3, 3, 3)
        outer.setSpacing(0)

        # --------------------------------------------------------------
        # 1. 顶部深可可鎏金横幅栏：艺术大标题「AI 看板」(无冗余副栏与顶栏设置钮)
        # --------------------------------------------------------------
        self.header_widget = QtWidgets.QWidget()
        self.header_widget.setFixedHeight(self.HEADER_HEIGHT)
        h_layout = QtWidgets.QHBoxLayout(self.header_widget)
        h_layout.setContentsMargins(14, 6, 12, 6)
        h_layout.setSpacing(7)

        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setFixedSize(28, 28)
        dpr = max(2.0, float(self.devicePixelRatioF()))
        icon_lbl.setPixmap(render_app_pixmap(28, dpr=dpr))
        h_layout.addWidget(icon_lbl)

        self.art_title = ArtisticBannerTitle()
        h_layout.addWidget(self.art_title)
        h_layout.addStretch(1)

        mini_btn = QtWidgets.QPushButton("MINI · 迷你")
        mini_btn.setToolTip("一键收起为桌面迷你悬浮胶囊 / 悬浮球")
        mini_btn.setCursor(QtCore.Qt.PointingHandCursor)
        mini_btn.setFixedHeight(27)
        mini_btn.setStyleSheet(
            "QPushButton { background-color: #E89B3C; color: #261E18; border: none; border-radius: 7px; padding: 0px 11px; font-size: 11px; font-weight: bold; }"
            "QPushButton:hover { background-color: #F3AC52; }"
        )
        mini_btn.clicked.connect(self.switchToMiniRequested.emit)
        h_layout.addWidget(mini_btn)

        self.refresh_btn = self._make_header_btn("⟳", "立即扫描本地会话与活跃数据")
        self.refresh_btn.clicked.connect(self.refreshRequested.emit)
        h_layout.addWidget(self.refresh_btn)

        self.pin_btn = self._make_header_btn("📌", "切换窗口始终置顶")
        self.pin_btn.clicked.connect(lambda: self.toggleTopRequested.emit(not self._always_on_top))
        self._sync_pin_btn_style()
        h_layout.addWidget(self.pin_btn)

        close_btn = self._make_header_btn("×", "收起到右下角系统托盘")
        close_btn.clicked.connect(self.hideToTrayRequested.emit)
        h_layout.addWidget(close_btn)

        outer.addWidget(self.header_widget)

        # --------------------------------------------------------------
        # 2. 中部双列书页主体 (左列：额度 + 对话 | 右列：个人待办)
        # --------------------------------------------------------------
        body = QtWidgets.QWidget()
        body_layout = QtWidgets.QHBoxLayout(body)
        body_layout.setContentsMargins(11, 10, 11, 10)
        body_layout.setSpacing(10)

        # ==================== 左列：AI 额度 + AI 对话 ====================
        left_tray = ColumnPageTray()
        left_col = QtWidgets.QVBoxLayout(left_tray)
        left_col.setContentsMargins(9, 8, 9, 8)
        left_col.setSpacing(7)

        # 左上：AI 账户额度 + 右上角专属「⚙ 设置」按钮
        self.quota_header = GameSectionHeader("AI 账户额度")
        quota_cfg_btn = QtWidgets.QPushButton("⚙ 设置")
        quota_cfg_btn.setObjectName("GamePillBtn")
        quota_cfg_btn.setCursor(QtCore.Qt.PointingHandCursor)
        quota_cfg_btn.setFixedHeight(21)
        quota_cfg_btn.setToolTip("管理显示的 AI 账户 (Codex / Antigravity / Claude Code / DeepSeek Harness) 及自动配置")
        quota_cfg_btn.clicked.connect(self._open_quota_settings)
        self.quota_header.right_layout.addWidget(quota_cfg_btn)
        left_col.addWidget(self.quota_header)

        self.quota_list_layout = QtWidgets.QVBoxLayout()
        self.quota_list_layout.setSpacing(5)
        left_col.addLayout(self.quota_list_layout)

        # 左下：AI 对话情况管理 (无「登记」按钮，给列表预留最大空间)
        self.session_header = GameSectionHeader("AI 对话情况")
        left_col.addWidget(self.session_header)

        # 动态平台筛选胶囊条
        self.filter_bar_widget = QtWidgets.QWidget()
        self.filter_row = QtWidgets.QHBoxLayout(self.filter_bar_widget)
        self.filter_row.setContentsMargins(0, 0, 0, 0)
        self.filter_row.setSpacing(4)
        left_col.addWidget(self.filter_bar_widget)

        self.session_scroll = QtWidgets.QScrollArea()
        self.session_scroll.setWidgetResizable(True)
        self.session_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.session_scroll_widget = QtWidgets.QWidget()
        self.session_scroll_widget.setStyleSheet("background: transparent;")
        self.session_vlayout = QtWidgets.QVBoxLayout(self.session_scroll_widget)
        self.session_vlayout.setContentsMargins(0, 1, 2, 2)
        self.session_vlayout.setSpacing(6)
        self.session_list_layout = QtWidgets.QVBoxLayout()
        self.session_list_layout.setSpacing(6)
        self.session_vlayout.addLayout(self.session_list_layout)
        self.session_vlayout.addStretch(1)
        self.session_scroll.setWidget(self.session_scroll_widget)
        left_col.addWidget(self.session_scroll, 1)

        body_layout.addWidget(left_tray, 1)

        # ==================== 右列：个人待办事项 ====================
        right_tray = ColumnPageTray()
        right_col = QtWidgets.QVBoxLayout(right_tray)
        right_col.setContentsMargins(9, 8, 9, 8)
        right_col.setSpacing(7)

        self.todo_header = GameSectionHeader("个人待办事项")
        self.clear_done_btn = QtWidgets.QPushButton("清理已完成")
        self.clear_done_btn.setObjectName("GamePillBtn")
        self.clear_done_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.clear_done_btn.setFixedHeight(21)
        self.clear_done_btn.clicked.connect(self._handle_clear_done_todos)
        self.todo_header.right_layout.addWidget(self.clear_done_btn)
        right_col.addWidget(self.todo_header)

        # 双行宽敞新增待办区（简化为「普通 / 重要」两档）
        input_card = PaperCardFrame(bg_color="#FCF9F2", radius=10)
        in_layout = QtWidgets.QVBoxLayout(input_card)
        in_layout.setContentsMargins(9, 8, 9, 8)
        in_layout.setSpacing(6)

        self.todo_input = QtWidgets.QLineEdit()
        self.todo_input.setPlaceholderText("写下新的待办事项，按回车直接添加...")
        self.todo_input.returnPressed.connect(self._handle_add_todo)
        in_layout.addWidget(self.todo_input)

        in_bot = QtWidgets.QHBoxLayout()
        in_bot.setSpacing(6)
        self._prio_chip_btns = {}  # type: Dict[str, QtWidgets.QPushButton]
        for pkey in ("normal", "high"):
            plabel, _pcol, _pbg = PRIORITY_META[pkey]
            pb = QtWidgets.QPushButton(plabel)
            pb.setCursor(QtCore.Qt.PointingHandCursor)
            pb.setFixedSize(46, 24)
            pb.clicked.connect(lambda _c=False, k=pkey: self._select_todo_prio(k))
            self._prio_chip_btns[pkey] = pb
            in_bot.addWidget(pb)

        in_bot.addStretch()
        add_todo_btn = QtWidgets.QPushButton("＋ 新增待办")
        add_todo_btn.setObjectName("GameGoldBtn")
        add_todo_btn.setCursor(QtCore.Qt.PointingHandCursor)
        add_todo_btn.setFixedHeight(26)
        add_todo_btn.clicked.connect(self._handle_add_todo)
        in_bot.addWidget(add_todo_btn)
        in_layout.addLayout(in_bot)

        right_col.addWidget(input_card)
        self._refresh_prio_chip_styles()

        # 待办滚动列表
        self.todo_scroll = QtWidgets.QScrollArea()
        self.todo_scroll.setWidgetResizable(True)
        self.todo_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.todo_scroll_widget = QtWidgets.QWidget()
        self.todo_scroll_widget.setStyleSheet("background: transparent;")
        self.todo_vlayout = QtWidgets.QVBoxLayout(self.todo_scroll_widget)
        self.todo_vlayout.setContentsMargins(0, 1, 2, 2)
        self.todo_vlayout.setSpacing(6)
        self.todo_list_layout = QtWidgets.QVBoxLayout()
        self.todo_list_layout.setSpacing(6)
        self.todo_vlayout.addLayout(self.todo_list_layout)
        self.todo_vlayout.addStretch(1)
        self.todo_scroll.setWidget(self.todo_scroll_widget)
        right_col.addWidget(self.todo_scroll, 1)

        body_layout.addWidget(right_tray, 1)
        outer.addWidget(body, 1)

        # 右下角悬浮不占行高的窗口自由缩放手柄
        self._size_grip = QtWidgets.QSizeGrip(self)
        self._size_grip.setFixedSize(14, 14)
        self._size_grip.setStyleSheet("background: transparent;")
        self._position_size_grip()

    def _position_size_grip(self) -> None:
        if hasattr(self, "_size_grip"):
            self._size_grip.move(self.width() - 16, self.height() - 16)
            self._size_grip.raise_()

    def _make_header_btn(self, text: str, tooltip: str) -> QtWidgets.QPushButton:
        btn = QtWidgets.QPushButton(text)
        btn.setToolTip(tooltip)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setFixedSize(27, 27)
        btn.setStyleSheet(
            "QPushButton { background-color: rgba(255,248,235,22); color: #EAD7BA; border: 1px solid rgba(225,192,140,70); border-radius: 7px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: rgba(240,180,86,75); color: #FFFFFF; border-color: #F0C274; }"
        )
        return btn

    def set_refreshing_state(self, state: str) -> None:
        """state: 'idle' | 'busy' | 'done'，给用户清晰的同步视觉反馈"""
        if not hasattr(self, "refresh_btn"):
            return
        if state == "busy":
            self.refresh_btn.setText("…")
            self.refresh_btn.setStyleSheet(
                "QPushButton { background-color: #6B4D2B; color: #FFE0A3; border: 1px solid #E8B563; border-radius: 7px; font-size: 13px; font-weight: bold; }"
            )
        elif state == "done":
            self.refresh_btn.setText("✓")
            self.refresh_btn.setStyleSheet(
                "QPushButton { background-color: #1F5E43; color: #A7F3D0; border: 1px solid #34D399; border-radius: 7px; font-size: 13px; font-weight: bold; }"
            )
            QtCore.QTimer.singleShot(900, lambda: self.set_refreshing_state("idle"))
        else:
            self.refresh_btn.setText("⟳")
            self.refresh_btn.setStyleSheet(
                "QPushButton { background-color: rgba(255,248,235,22); color: #EAD7BA; border: 1px solid rgba(225,192,140,70); border-radius: 7px; font-size: 13px; font-weight: bold; }"
                "QPushButton:hover { background-color: rgba(240,180,86,75); color: #FFFFFF; border-color: #F0C274; }"
            )

    def _sync_pin_btn_style(self) -> None:
        if not hasattr(self, "pin_btn"):
            return
        if self._always_on_top:
            self.pin_btn.setStyleSheet(
                "QPushButton { background-color: #6B4D2B; color: #FFE0A3; border: 1px solid #E8B563; border-radius: 7px; font-size: 13px; }"
            )
        else:
            self.pin_btn.setStyleSheet(
                "QPushButton { background-color: rgba(255,248,235,22); color: #EAD7BA; border: 1px solid rgba(225,192,140,70); border-radius: 7px; font-size: 13px; }"
                "QPushButton:hover { background-color: rgba(240,180,86,75); color: #FFFFFF; }"
            )

    def _select_todo_prio(self, prio_key: str) -> None:
        self._selected_todo_prio = prio_key
        self._refresh_prio_chip_styles()

    def _refresh_prio_chip_styles(self) -> None:
        for key, btn in self._prio_chip_btns.items():
            _lbl, col, bg = PRIORITY_META[key]
            if key == self._selected_todo_prio:
                btn.setStyleSheet(
                    "QPushButton {{ background-color: {}; color: #FFFFFF; border: 1px solid {}; border-radius: 6px; font-size: 11px; font-weight: bold; }}".format(
                        col, col
                    )
                )
            else:
                btn.setStyleSheet(
                    "QPushButton {{ background-color: {}; color: {}; border: 1px solid #DFD0B8; border-radius: 6px; font-size: 11px; font-weight: bold; }}"
                    "QPushButton:hover {{ border-color: {}; }}".format(bg, col, col)
                )

    def _set_active_tab(self, tab_key: str) -> None:
        self.storage.update_ui(active_tab=tab_key)
        self.render_all(self._scan_data)

    def _set_session_filter(self, fkey: str) -> None:
        self._session_filter = fkey
        self.storage.update_ui(session_filter=fkey)
        self._render_sessions()

    # ------------------------------------------------------------------
    # 数据渲染逻辑
    # ------------------------------------------------------------------
    def render_all(self, scan_data: Optional[Dict[str, Any]] = None) -> None:
        if scan_data is not None:
            self._scan_data = scan_data

        self._render_quotas()
        self._render_sessions()
        self._render_todos()

    def _render_quotas(self) -> None:
        self._clear_layout(self.quota_list_layout)
        visible_accounts = self.storage.get_accounts(only_visible=True)

        if not visible_accounts:
            empty_q = QtWidgets.QLabel("未勾选展示的账户，点击右上角「⚙ 设置」选择开启")
            empty_q.setAlignment(QtCore.Qt.AlignCenter)
            empty_q.setStyleSheet(
                "color: #9A8772; padding: 10px; background: #FAF5EC; border: 1px dashed #D8C7AE; border-radius: 8px; font-size: 11px;"
            )
            self.quota_list_layout.addWidget(empty_q)
            return

        stats_map = {
            "codex": self._scan_data.get("codex_stats", {}),
            "antigravity": self._scan_data.get("antigravity_stats", {}),
            "claude_code": self._scan_data.get("claude_stats", {}),
            "deepseek_harness": self._scan_data.get("deepseek_stats", {}),
        }

        for acc in visible_accounts:
            aid = str(acc.get("id", ""))
            act_text = ""
            if aid in stats_map:
                st = stats_map[aid]
                w_steps = int(st.get("window_steps", 0))
                act_text = "{}步".format(w_steps)

            card = AccountQuotaCard(acc, act_text)
            card.calibrateClicked.connect(self._on_quota_calibrate)
            self.quota_list_layout.addWidget(card)

    def build_merged_sessions(self) -> List[Dict[str, Any]]:
        raw_auto = list(self._scan_data.get("sessions", []))
        merged = []  # type: List[Dict[str, Any]]

        for item in raw_auto:
            s = dict(item)
            key = str(s.get("key", ""))
            ov = self.storage.get_session_override(key)
            if ov.get("hidden"):
                continue

            s["pinned"] = bool(ov.get("pinned", False))
            s["display_title"] = ov["custom_title"] if ov.get("custom_title") else s.get("title", "")

            if ov.get("status"):
                s["effective_status"] = ov["status"]
                s["has_manual_status"] = True
            else:
                s["effective_status"] = s.get("status", "completed")
                s["has_manual_status"] = False

            merged.append(s)

        status_priority = {"running": 0, "waiting": 1, "error": 2, "paused": 3, "completed": 4}
        merged.sort(
            key=lambda x: (
                0 if x.get("pinned") else 1,
                0 if x.get("effective_status") in ("running", "waiting") else 1,
                -float(x.get("updated_at") or 0),
                status_priority.get(str(x.get("effective_status")), 4),
            )
        )
        return merged

    def _rebuild_filter_bar(self, merged: List[Dict[str, Any]]) -> None:
        self._clear_layout(self.filter_row)
        vis_ids = {str(a.get("id")) for a in self.storage.get_accounts(only_visible=True)}
        present_providers = {str(s.get("provider")) for s in merged}

        chips = [("all", "全部"), ("active", "进行中")]
        for pid, plabel in (
            ("codex", "Codex"),
            ("antigravity", "AGY"),
            ("claude_code", "Claude"),
            ("deepseek_harness", "DSH"),
        ):
            if pid in vis_ids or pid in present_providers:
                chips.append((pid, plabel))

        valid_keys = {k for k, _ in chips}
        if self._session_filter not in valid_keys:
            self._session_filter = "all"

        for fkey, flabel in chips:
            fb = QtWidgets.QPushButton(flabel)
            fb.setCursor(QtCore.Qt.PointingHandCursor)
            fb.setFixedHeight(21)
            if fkey == self._session_filter:
                fb.setStyleSheet(
                    "QPushButton { background-color: #D98A2B; color: #FFFFFF; border: 1px solid #B86E16; border-radius: 7px; padding: 0px 8px; font-size: 11px; font-weight: bold; }"
                )
            else:
                fb.setStyleSheet(
                    "QPushButton { background-color: #FCF8F0; color: #7A6754; border: 1px solid #DDD0BA; border-radius: 7px; padding: 0px 8px; font-size: 11px; font-weight: bold; }"
                    "QPushButton:hover { color: #382C22; border-color: #C89A54; background-color: #FFFFFF; }"
                )
            fb.clicked.connect(lambda _c=False, k=fkey: self._set_session_filter(k))
            self.filter_row.addWidget(fb)

        self.filter_row.addStretch()

        hidden_count = sum(
            1
            for v in self.storage.state.get("session_overrides", {}).values()
            if isinstance(v, dict) and v.get("hidden")
        )
        if hidden_count > 0:
            unhide_btn = QtWidgets.QPushButton("恢复({})".format(hidden_count))
            unhide_btn.setObjectName("SoftBtn")
            unhide_btn.setStyleSheet("font-size: 10px; color: #8A7662;")
            unhide_btn.setCursor(QtCore.Qt.PointingHandCursor)
            unhide_btn.clicked.connect(self._restore_hidden_sessions)
            self.filter_row.addWidget(unhide_btn)

    def _render_sessions(self) -> None:
        self._clear_layout(self.session_list_layout)
        merged = self.build_merged_sessions()
        self._rebuild_filter_bar(merged)

        active_total = sum(
            1 for s in merged if s.get("effective_status") in ("running", "waiting")
        )
        self.session_header.set_title(
            "AI 对话情况", "活跃 {} / 共 {}".format(active_total, len(merged))
        )

        filtered = []
        for s in merged:
            if self._session_filter == "active":
                if s.get("effective_status") not in ("running", "waiting", "error"):
                    continue
            elif self._session_filter != "all":
                if s.get("provider") != self._session_filter:
                    continue
            filtered.append(s)

        if not filtered:
            empty_lbl = QtWidgets.QLabel("暂无匹配的对话记录")
            empty_lbl.setAlignment(QtCore.Qt.AlignCenter)
            empty_lbl.setStyleSheet(
                "color: #9A8772; padding: 18px; background: #FAF5EC; border: 1px dashed #D8C7AE; border-radius: 9px;"
            )
            self.session_list_layout.addWidget(empty_lbl)
            return

        for s in filtered[:60]:
            card = SessionItemCard(s)
            card.actionTriggered.connect(self._on_session_action)
            self.session_list_layout.addWidget(card)

    def _render_todos(self) -> None:
        self._clear_layout(self.todo_list_layout)
        todos = self.storage.get_todos()
        total_cnt = len(todos)
        pending_cnt = sum(1 for t in todos if not t.get("done"))
        done_cnt = total_cnt - pending_cnt

        self.todo_header.set_title("个人待办事项", "待办 {}".format(pending_cnt))
        self.clear_done_btn.setVisible(done_cnt > 0)

        if not todos:
            empty_lbl = QtWidgets.QLabel("🎉 待办已全部清空！在上方输入可添加新事项")
            empty_lbl.setAlignment(QtCore.Qt.AlignCenter)
            empty_lbl.setWordWrap(True)
            empty_lbl.setStyleSheet(
                "color: #8A7662; padding: 22px; background: #FAF5EC; border: 1px dashed #D8C7AE; border-radius: 9px;"
            )
            self.todo_list_layout.addWidget(empty_lbl)
            return

        for item in todos:
            row = TodoItemRow(item)
            row.toggleRequested.connect(self._on_todo_toggle)
            row.deleteRequested.connect(self._on_todo_delete)
            row.pinRequested.connect(self._on_todo_pin)
            row.priorityCycleRequested.connect(self._on_todo_prio)
            row.editRequested.connect(self._on_todo_edit)
            self.todo_list_layout.addWidget(row)

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.deleteLater()

    # ------------------------------------------------------------------
    # 交互事件处理
    # ------------------------------------------------------------------
    def _on_quota_calibrate(self, account_id: str) -> None:
        target = None
        for a in self.storage.get_accounts(only_visible=False):
            if a.get("id") == account_id:
                target = a
                break
        if not target:
            return
        dlg = QuotaCalibrateDialog(target, self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            res = dlg.get_result()
            self.storage.update_account_quota(
                account_id,
                remaining_pct=res["remaining_pct"],
                window_hours=res["window_hours"],
                reset_in_minutes=res["reset_in_minutes"],
                auto_sync_log=res["auto_sync_log"],
                step_budget=res["step_budget"],
            )
            self.storage.mark_manual_calibration(account_id, anchor_pct=res["remaining_pct"])
            self._render_quotas()
            self.settingsUpdated.emit()

    def _open_quota_settings(self) -> None:
        diag = self._scan_data.get("diagnostics", {})
        cpaths = self.storage.get_custom_paths()
        ui_cfg = self.storage.get_ui()
        interval = int(ui_cfg.get("scan_interval_sec") or 15)
        cur_auto = is_autostart_enabled()
        boot_mini = bool(ui_cfg.get("boot_in_mini_mode", False))
        dlg = QuotaSettingsDialog(
            accounts=self.storage.get_accounts(only_visible=False),
            diagnostics=diag,
            custom_paths=cpaths,
            scan_interval_sec=interval,
            autostart_enabled=cur_auto,
            boot_in_mini_mode=boot_mini,
            data_dir_path=self.storage.data_dir,
            auto_detect_fn=self._auto_detect_fn,
            parent=self,
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            res = dlg.get_result()
            for aid, uinfo in res["accounts"].items():
                self.storage.update_account_quota(
                    aid,
                    remaining_pct=uinfo["remaining_pct"] if uinfo["pct_changed"] else None,
                    window_hours=uinfo["window_hours"],
                    visible=uinfo["visible"],
                )
                if uinfo["pct_changed"]:
                    self.storage.mark_manual_calibration(aid, anchor_pct=uinfo["remaining_pct"])
            cp = res["custom_paths"]
            self.storage.set_custom_paths(
                codex_dirs=cp.get("codex_dirs"),
                antigravity_dirs=cp.get("antigravity_dirs"),
                claude_dirs=cp.get("claude_dirs"),
                deepseek_dirs=cp.get("deepseek_dirs"),
            )
            self.storage.update_ui(
                scan_interval_sec=res["scan_interval_sec"],
                boot_in_mini_mode=bool(res["boot_in_mini_mode"]),
            )
            want_auto = bool(res["autostart_enabled"])
            if want_auto != cur_auto:
                set_autostart(want_auto)
            self._render_quotas()
            self._render_sessions()
            self.settingsUpdated.emit()
            self.refreshRequested.emit()

    def _on_session_action(self, session_key: str, action: str) -> None:
        if action.startswith("status:"):
            st = action.split(":", 1)[1]
            self.storage.set_session_override(session_key, status=st)
        elif action == "toggle_pin":
            cur = bool(self.storage.get_session_override(session_key).get("pinned", False))
            self.storage.set_session_override(session_key, pinned=not cur)
        elif action == "hide":
            self.storage.set_session_override(session_key, hidden=True)
        elif action == "delete_manual":
            self.storage.delete_manual_session(session_key)
        elif action == "rename":
            new_name, ok = QtWidgets.QInputDialog.getText(
                self, "自定义对话备注标题", "输入便于你识别的任务名称 (留空恢复默认):"
            )
            if ok:
                self.storage.set_session_override(session_key, custom_title=new_name)

        self._render_sessions()
        self.settingsUpdated.emit()

    def _restore_hidden_sessions(self) -> None:
        self.storage.restore_hidden_sessions()
        self._render_sessions()
        self.settingsUpdated.emit()

    def _handle_add_todo(self) -> None:
        txt = self.todo_input.text().strip()
        if not txt:
            return
        self.storage.add_todo(txt, priority=self._selected_todo_prio)
        self.todo_input.clear()
        self._render_todos()
        self.settingsUpdated.emit()

    def _on_todo_toggle(self, todo_id: str) -> None:
        self.storage.toggle_todo(todo_id)
        self._render_todos()
        self.settingsUpdated.emit()

    def _on_todo_delete(self, todo_id: str) -> None:
        self.storage.delete_todo(todo_id)
        self._render_todos()
        self.settingsUpdated.emit()

    def _on_todo_pin(self, todo_id: str, pinned: bool) -> None:
        self.storage.update_todo(todo_id, pinned=pinned)
        self._render_todos()

    def _on_todo_prio(self, todo_id: str, next_prio: str) -> None:
        self.storage.update_todo(todo_id, priority=next_prio)
        self._render_todos()

    def _on_todo_edit(self, todo_id: str, new_text: str) -> None:
        self.storage.update_todo(todo_id, text=new_text)
        self._render_todos()

    def _handle_clear_done_todos(self) -> None:
        self.storage.clear_completed_todos()
        self._render_todos()
        self.settingsUpdated.emit()

    # ------------------------------------------------------------------
    # 游戏纪行风羊皮纸主框 + 深可可鎏金顶冠自绘
    # ------------------------------------------------------------------
    def paintEvent(self, _event: QtGui.QPaintEvent) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        w = float(self.width())
        h = float(self.height())
        outer_r = 15.0
        body_rect = QtCore.QRectF(2.0, 2.0, w - 4.0, h - 4.0)

        bg_grad = QtGui.QLinearGradient(0, self.HEADER_HEIGHT, 0, h)
        bg_grad.setColorAt(0.0, QtGui.QColor(COLORS["bg_parchment_top"]))
        bg_grad.setColorAt(1.0, QtGui.QColor(COLORS["bg_parchment_bot"]))
        p.setBrush(QtGui.QBrush(bg_grad))
        p.setPen(QtCore.Qt.NoPen)
        p.drawRoundedRect(body_rect, outer_r, outer_r)

        p.save()
        clip_path = QtGui.QPainterPath()
        clip_path.addRoundedRect(body_rect, outer_r, outer_r)
        p.setClipPath(clip_path)

        hdr_h = float(self.HEADER_HEIGHT + 3)
        hdr_rect = QtCore.QRectF(2.0, 2.0, w - 4.0, hdr_h)
        hdr_grad = QtGui.QLinearGradient(0, 0, w, hdr_h)
        hdr_grad.setColorAt(0.0, QtGui.QColor("#342A23"))
        hdr_grad.setColorAt(1.0, QtGui.QColor("#2B221C"))
        p.setBrush(QtGui.QBrush(hdr_grad))
        p.drawRect(hdr_rect)

        p.setPen(QtGui.QPen(QtGui.QColor(240, 164, 68, 95), 1.2))
        p.drawLine(QtCore.QPointF(2.0, hdr_h + 1.0), QtCore.QPointF(w - 2.0, hdr_h + 1.0))
        p.restore()

        p.setBrush(QtCore.Qt.NoBrush)
        p.setPen(QtGui.QPen(QtGui.QColor("#C8B598"), 1.3))
        p.drawRoundedRect(body_rect, outer_r, outer_r)
        p.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and event.pos().y() <= self.HEADER_HEIGHT + 4:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
        super(MainDashboardPanel, self).mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._drag_offset is not None and (event.buttons() & QtCore.Qt.LeftButton):
            self.move(event.globalPos() - self._drag_offset)
        super(MainDashboardPanel, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self.geometrySaved.emit(self.x(), self.y(), self.width(), self.height())
        super(MainDashboardPanel, self).mouseReleaseEvent(event)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super(MainDashboardPanel, self).resizeEvent(event)
        self._position_size_grip()
        if self.isVisible():
            self.geometrySaved.emit(self.x(), self.y(), self.width(), self.height())
