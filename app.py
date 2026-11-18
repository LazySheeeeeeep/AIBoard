# -*- coding: utf-8 -*-
"""
AI BOARD (额度监控 · 对话管理 · 待办事项) 常驻桌面小插件
主程序入口 (实时文件监听 + 5秒灵敏增量同步 + 手动穿透强刷版)
"""

import os
import sys


def _bootstrap_qt_env() -> None:
    if getattr(sys, "frozen", False):
        return
    prefix = sys.prefix
    lib_bin = os.path.join(prefix, "Library", "bin")
    plugins_dir = os.path.join(prefix, "Library", "plugins")
    if os.path.isdir(lib_bin):
        cur_path = os.environ.get("PATH", "")
        if lib_bin.lower() not in cur_path.lower():
            os.environ["PATH"] = lib_bin + os.pathsep + cur_path
    if os.path.isdir(plugins_dir) and not os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugins_dir


_bootstrap_qt_env()

from typing import Any, Dict, List, Optional, Set
from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets

from core.scanner import LocalAIScanner
from core.startup import get_app_root_dir, is_autostart_enabled, set_autostart
from core.storage import DashboardStorage
from ui.main_panel import MainDashboardPanel
from ui.mini_bar import MiniFloatingWidget
from ui.theme import MAIN_STYLESHEET, create_app_icon, ensure_app_ico_file


SINGLETON_KEY = "PersonalAIDashboard_LongApp_V2"


class ScanWorker(QtCore.QThread):
    """后台非阻塞扫描线程，支持 force_refresh 强制清空缓存重读最新磁盘字节"""

    scanFinished = QtCore.pyqtSignal(dict, bool)

    def __init__(
        self,
        scanner: LocalAIScanner,
        custom_paths: Dict[str, list],
        win_hours: Dict[str, float],
        enabled_providers: Set[str],
        force_refresh: bool = False,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super(ScanWorker, self).__init__(parent)
        self.scanner = scanner
        self.custom_paths = custom_paths
        self.win_hours = win_hours
        self.enabled_providers = enabled_providers
        self.force_refresh = force_refresh

    def run(self) -> None:
        try:
            res = self.scanner.scan_all(
                extra_codex_dirs=self.custom_paths.get("codex_dirs", []),
                extra_agy_dirs=self.custom_paths.get("antigravity_dirs", []),
                extra_claude_dirs=self.custom_paths.get("claude_dirs", []),
                extra_deepseek_dirs=self.custom_paths.get("deepseek_dirs", []),
                codex_window_hours=self.win_hours.get("codex", 5.0),
                agy_window_hours=self.win_hours.get("antigravity", 5.0),
                claude_window_hours=self.win_hours.get("claude_code", 5.0),
                deepseek_window_hours=self.win_hours.get("deepseek_harness", 24.0),
                enabled_providers=self.enabled_providers,
                force_refresh=self.force_refresh,
            )
        except Exception as exc:
            res = {
                "scanned_at": 0,
                "sessions": [],
                "antigravity_stats": {},
                "codex_stats": {},
                "claude_stats": {},
                "deepseek_stats": {},
                "codex_rate_limit": None,
                "diagnostics": {"error": str(exc), "detected": {}},
            }
        self.scanFinished.emit(res, self.force_refresh)


class DashboardController(QtCore.QObject):
    """双模式常驻挂件、实时文件监控与系统托盘总控制器"""

    def __init__(self, app: QtWidgets.QApplication, is_boot_launch: bool = False) -> None:
        super(DashboardController, self).__init__()
        self.app = app
        self.storage = DashboardStorage()
        self.scanner = LocalAIScanner()
        self._worker = None  # type: Optional[ScanWorker]
        self._pending_force_scan = False
        self._latest_scan = {}  # type: Dict[str, Any]

        ui_cfg = self.storage.get_ui()
        always_top = bool(ui_cfg.get("always_on_top", True))
        orb_style = bool(ui_cfg.get("mini_orb_style", False))

        self.main_panel = MainDashboardPanel(
            self.storage,
            always_on_top=always_top,
            auto_detect_fn=self.run_quick_detect,
        )
        self.mini_widget = MiniFloatingWidget(always_on_top=always_top, orb_style=orb_style)

        self._restore_positions()
        self._connect_signals()
        self._init_tray(always_top)
        self._init_singleton_server()

        # 实时文件系统变更监视器 + 700ms 去抖动触发器
        self.fs_watcher = QtCore.QFileSystemWatcher(self)
        self.fs_debounce = QtCore.QTimer(self)
        self.fs_debounce.setSingleShot(True)
        self.fs_debounce.setInterval(700)
        self.fs_debounce.timeout.connect(lambda: self.trigger_scan(force=False))
        self.fs_watcher.directoryChanged.connect(self._on_fs_changed)
        self.fs_watcher.fileChanged.connect(self._on_fs_changed)

        self.app.aboutToQuit.connect(self._flush_on_exit)
        self.app.commitDataRequest.connect(self._on_commit_data)

        self.scan_timer = QtCore.QTimer(self)
        self.scan_timer.timeout.connect(lambda: self.trigger_scan(force=False))
        self._apply_scan_interval()

        self.countdown_timer = QtCore.QTimer(self)
        self.countdown_timer.timeout.connect(self._on_countdown_tick)
        self.countdown_timer.start(20 * 1000)

        self._sync_all_views()
        boot_mini = bool(ui_cfg.get("boot_in_mini_mode", False))
        initial_mode = str(ui_cfg.get("mode") or "expanded")
        if (is_boot_launch and boot_mini) or initial_mode == "mini":
            self.show_mini_mode()
        else:
            self.show_expanded_mode()

        QtCore.QTimer.singleShot(80, lambda: self.trigger_scan(force=True))

    def _on_fs_changed(self, _path: str) -> None:
        if not self.fs_debounce.isActive():
            self.fs_debounce.start()

    def _update_watched_paths(self, diagnostics: Dict[str, Any]) -> None:
        """动态将本地 AI 工具目录与活跃会话子目录挂载进 QFileSystemWatcher 实现近乎零延迟响应"""
        watch_targets = []  # type: List[str]
        for key in ("codex_dirs", "antigravity_dirs", "claude_dirs", "deepseek_dirs"):
            for base_d in diagnostics.get(key) or []:
                if os.path.isdir(base_d):
                    watch_targets.append(base_d)
                    # 同时监听一级会话目录与 SQLite WAL 文件
                    for sub_name in ("sessions", "projects"):
                        sub_p = os.path.join(base_d, sub_name)
                        if os.path.isdir(sub_p):
                            watch_targets.append(sub_p)
                    try:
                        for entry in os.listdir(base_d)[:20]:
                            ep = os.path.join(base_d, entry)
                            if entry.lower().endswith((".sqlite", ".sqlite-wal", ".db")) or entry.lower() == "session_index.jsonl":
                                watch_targets.append(ep)
                            elif key == "antigravity_dirs" and os.path.isdir(ep):
                                log_d = os.path.join(ep, ".system_generated", "logs")
                                if os.path.isdir(log_d):
                                    watch_targets.append(log_d)
                    except Exception:
                        pass

        cur_watched = set(self.fs_watcher.directories() + self.fs_watcher.files())
        to_add = [p for p in watch_targets if p not in cur_watched]
        if to_add:
            try:
                self.fs_watcher.addPaths(to_add[:60])
            except Exception:
                pass

    def _flush_on_exit(self) -> None:
        try:
            self.storage.save()
        except Exception:
            pass

    def _on_commit_data(self, _manager: QtGui.QSessionManager) -> None:
        self._flush_on_exit()

    def _restore_positions(self) -> None:
        screen = self.app.desktop().availableGeometry()
        ui_cfg = self.storage.get_ui()

        p_pos = ui_cfg.get("panel_pos")
        if isinstance(p_pos, list) and len(p_pos) == 2:
            px = max(screen.left() + 6, min(int(p_pos[0]), screen.right() - self.main_panel.width() - 8))
            py = max(screen.top() + 6, min(int(p_pos[1]), screen.bottom() - self.main_panel.height() - 8))
            self.main_panel.move(px, py)
        else:
            self.main_panel.move(
                screen.right() - self.main_panel.width() - 24,
                screen.top() + 48,
            )

        m_pos = ui_cfg.get("mini_pos")
        if isinstance(m_pos, list) and len(m_pos) == 2:
            mx = max(screen.left() + 4, min(int(m_pos[0]), screen.right() - 72))
            my = max(screen.top() + 4, min(int(m_pos[1]), screen.bottom() - 72))
            self.mini_widget.move(mx, my)
        else:
            self.mini_widget.move(
                screen.right() - self.mini_widget.width() - 24,
                screen.top() + 28,
            )

    def _connect_signals(self) -> None:
        self.main_panel.switchToMiniRequested.connect(self.show_mini_mode)
        self.main_panel.refreshRequested.connect(lambda: self.trigger_scan(force=True))
        self.main_panel.toggleTopRequested.connect(self.set_always_on_top)
        self.main_panel.hideToTrayRequested.connect(self.hide_to_tray)
        self.main_panel.geometrySaved.connect(self._save_panel_geometry)
        self.main_panel.settingsUpdated.connect(self._on_settings_updated)

        self.mini_widget.expandRequested.connect(self.show_expanded_mode)
        self.mini_widget.refreshRequested.connect(lambda: self.trigger_scan(force=True))
        self.mini_widget.toggleTopRequested.connect(self.set_always_on_top)
        self.mini_widget.toggleAutostartRequested.connect(self.toggle_autostart)
        self.mini_widget.orbStyleChanged.connect(self._save_orb_style)
        self.mini_widget.quitRequested.connect(self.quit_app)
        self.mini_widget.positionChanged.connect(self._save_mini_pos)

    def _init_tray(self, always_top: bool) -> None:
        self.tray = QtWidgets.QSystemTrayIcon(create_app_icon(64), self)
        self.tray.setToolTip("AI BOARD 常驻桌面看板 (点击切换显示)")

        menu = QtWidgets.QMenu()
        act_exp = menu.addAction("📊 展开 AI BOARD 看板")
        act_exp.triggered.connect(self.show_expanded_mode)

        act_pill = menu.addAction("💊 切换为「胶囊窄条」")
        act_pill.triggered.connect(lambda: self._switch_mini_variant(False))

        act_orb = menu.addAction("● 切换为「高清圆形图标」")
        act_orb.triggered.connect(lambda: self._switch_mini_variant(True))

        act_ref = menu.addAction("⟳ 立即强制同步")
        act_ref.triggered.connect(lambda: self.trigger_scan(force=True))

        menu.addSeparator()
        self.tray_top_act = menu.addAction("📌 窗口始终置顶")
        self.tray_top_act.setCheckable(True)
        self.tray_top_act.setChecked(always_top)
        self.tray_top_act.triggered.connect(self.set_always_on_top)

        self.tray_boot_act = menu.addAction("🚀 开机自动启动")
        self.tray_boot_act.setCheckable(True)
        self.tray_boot_act.setChecked(is_autostart_enabled())
        self.tray_boot_act.triggered.connect(self.toggle_autostart)

        menu.addSeparator()
        act_quit = menu.addAction("✕ 退出 AI BOARD")
        act_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _switch_mini_variant(self, orb: bool) -> None:
        self.mini_widget.set_orb_style(orb)
        self._save_orb_style(orb)
        self.show_mini_mode()

    def toggle_autostart(self, enabled: bool) -> None:
        ok, msg = set_autostart(enabled)
        self.tray_boot_act.setChecked(is_autostart_enabled())
        if ok:
            self.tray.showMessage("AI BOARD 常驻设置", msg, QtWidgets.QSystemTrayIcon.Information, 1800)

    def _save_orb_style(self, orb: bool) -> None:
        self.storage.update_ui(mini_orb_style=bool(orb))

    def _init_singleton_server(self) -> None:
        QtNetwork.QLocalServer.removeServer(SINGLETON_KEY)
        self.local_server = QtNetwork.QLocalServer(self)
        self.local_server.newConnection.connect(self._on_new_instance_wakeup)
        self.local_server.listen(SINGLETON_KEY)

    def _on_new_instance_wakeup(self) -> None:
        conn = self.local_server.nextPendingConnection()
        msg = b""
        if conn:
            conn.waitForReadyRead(150)
            msg = bytes(conn.readAll())
            conn.close()
        if b"REPLACE" in msg:
            self.quit_app()
            return
        self.show_expanded_mode()

    def _on_tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QtWidgets.QSystemTrayIcon.Trigger,
            QtWidgets.QSystemTrayIcon.DoubleClick,
        ):
            if self.main_panel.isVisible():
                self.show_mini_mode()
            else:
                self.show_expanded_mode()

    def show_expanded_mode(self) -> None:
        self.mini_widget.hide()
        self.main_panel.show()
        self.main_panel.raise_()
        self.main_panel.activateWindow()
        self.storage.update_ui(mode="expanded")
        self.trigger_scan(force=False)

    def show_mini_mode(self) -> None:
        self.main_panel.hide()
        self._sync_mini_summary()
        self.mini_widget.show()
        self.mini_widget.raise_()
        self.storage.update_ui(mode="mini")

    def hide_to_tray(self) -> None:
        self.main_panel.hide()
        self.mini_widget.hide()
        self.tray.showMessage(
            "AI BOARD 仍在后台常驻",
            "点击右下角托盘图标可随时唤出面板或切换迷你悬浮图标。",
            QtWidgets.QSystemTrayIcon.Information,
            2200,
        )

    def set_always_on_top(self, on_top: bool) -> None:
        self.storage.update_ui(always_on_top=on_top)
        self.tray_top_act.setChecked(on_top)
        self.main_panel.set_always_on_top(on_top)
        self.mini_widget.set_always_on_top(on_top)

    def _save_panel_geometry(self, x: int, y: int, w: int, h: int) -> None:
        self.storage.update_ui(panel_pos=[x, y], panel_size=[w, h])

    def _save_mini_pos(self, x: int, y: int) -> None:
        self.storage.update_ui(mini_pos=[x, y])

    def _apply_scan_interval(self) -> None:
        sec = max(3, int(self.storage.get_ui().get("scan_interval_sec") or 5))
        self.scan_timer.start(sec * 1000)

    def _on_settings_updated(self) -> None:
        self.tray_boot_act.setChecked(is_autostart_enabled())
        self._apply_scan_interval()
        self._sync_mini_summary()

    def _on_countdown_tick(self) -> None:
        changed = self.storage.check_and_roll_resets()
        if changed or self.main_panel.isVisible():
            self.main_panel._render_quotas()
        self._sync_mini_summary()

    def run_quick_detect(self) -> Dict[str, Any]:
        cp = self.storage.get_custom_paths()
        scan_res = self.scanner.scan_all(
            extra_codex_dirs=cp.get("codex_dirs", []),
            extra_agy_dirs=cp.get("antigravity_dirs", []),
            extra_claude_dirs=cp.get("claude_dirs", []),
            extra_deepseek_dirs=cp.get("deepseek_dirs", []),
            force_refresh=True,
        )
        return scan_res.get("diagnostics", {})

    def trigger_scan(self, force: bool = False) -> None:
        if force:
            self.main_panel.set_refreshing_state("busy")

        if self._worker is not None and self._worker.isRunning():
            if force:
                self._pending_force_scan = True
            return

        cpaths = dict(self.storage.get_custom_paths())
        all_accs = self.storage.get_accounts(only_visible=False)
        win_hours = {str(a["id"]): float(a.get("window_hours", 5.0)) for a in all_accs}
        enabled = {str(a["id"]) for a in all_accs if a.get("visible", True)}

        self._worker = ScanWorker(
            self.scanner,
            cpaths,
            win_hours,
            enabled,
            force_refresh=force,
            parent=self,
        )
        self._worker.scanFinished.connect(self._on_scan_finished)
        self._worker.start()

    def _on_scan_finished(self, scan_data: Dict[str, Any], was_forced: bool) -> None:
        self._latest_scan = scan_data
        self.storage.apply_scanned_quota_hints(scan_data)
        self._sync_all_views()
        self._update_watched_paths(scan_data.get("diagnostics", {}))

        if was_forced:
            self.main_panel.set_refreshing_state("done")

        if self._pending_force_scan:
            self._pending_force_scan = False
            QtCore.QTimer.singleShot(50, lambda: self.trigger_scan(force=True))

    def _sync_all_views(self) -> None:
        self.main_panel.render_all(self._latest_scan)
        self._sync_mini_summary()

    def _sync_mini_summary(self) -> None:
        accounts = self.storage.get_accounts(only_visible=False)
        merged_sessions = self.main_panel.build_merged_sessions()
        active_cnt = sum(
            1 for s in merged_sessions if s.get("effective_status") in ("running", "waiting")
        )
        todos = self.storage.get_todos()
        pending_todos = sum(1 for t in todos if not t.get("done"))
        self.mini_widget.update_summary(
            accounts, active_cnt, len(merged_sessions), pending_todos
        )

    def quit_app(self) -> None:
        self.scan_timer.stop()
        self.countdown_timer.stop()
        self._flush_on_exit()
        self.tray.hide()
        self.app.quit()


def _notify_existing_instance(replace_existing: bool = True) -> bool:
    sock = QtNetwork.QLocalSocket()
    sock.connectToServer(SINGLETON_KEY)
    if sock.waitForConnected(220):
        payload = b"REPLACE" if replace_existing else b"WAKE"
        sock.write(payload)
        sock.waitForBytesWritten(200)
        sock.disconnectFromServer()
        if replace_existing:
            QtCore.QThread.msleep(220)
            return False
        return True
    return False


_CRASH_LOG_HANDLE = None  # keep faulthandler's file handle alive for the whole process


def _install_crash_guard() -> None:
    """
    PyQt5 会在「槽函数里出现未捕获异常」时直接 abort 整个进程（pythonw 下表现为无声闪退）。
    这里改为：把异常写进 %APPDATA%\\AIBoard\\crash.log 并继续运行；
    同时开启 faulthandler 记录原生层崩溃，方便远程排查。
    """
    import datetime
    import traceback

    from core.storage import resolve_user_data_dir

    try:
        log_dir = resolve_user_data_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "crash.log")
    except Exception:
        return

    def _hook(exc_type, exc, tb) -> None:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n[{}] Unhandled exception\n".format(datetime.datetime.now().isoformat(timespec="seconds")))
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    sys.excepthook = _hook

    global _CRASH_LOG_HANDLE
    try:
        import faulthandler

        _CRASH_LOG_HANDLE = open(log_path, "a", encoding="utf-8")
        faulthandler.enable(file=_CRASH_LOG_HANDLE, all_threads=True)
    except Exception:
        pass


def main() -> int:
    # 命令行子命令：一键配置 / 关闭自启 / 状态查看（无需启动 GUI）
    if "--setup" in sys.argv or "setup" in sys.argv[1:2]:
        from core.setup_cli import run_setup
        return run_setup(sys.argv)
    if "--disable-autostart" in sys.argv:
        from core.setup_cli import run_disable_autostart
        return run_disable_autostart()
    if "--status" in sys.argv or "status" in sys.argv[1:2]:
        from core.setup_cli import print_status
        return print_status()

    _install_crash_guard()
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    base_font = QtGui.QFont("Bahnschrift", 9)
    base_font.setStyleStrategy(QtGui.QFont.PreferAntialias)
    app.setFont(base_font)
    app.setApplicationName("AI BOARD")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(create_app_icon(64))
    app.setStyleSheet(MAIN_STYLESHEET)

    if not getattr(sys, "frozen", False):
        ico_file = os.path.join(get_app_root_dir(), "assets", "ai_board.ico")
        if not os.path.isfile(ico_file):
            ensure_app_ico_file(ico_file)

    is_boot = "--autostart" in sys.argv
    if _notify_existing_instance(replace_existing=not is_boot):
        return 0

    _controller = DashboardController(app, is_boot_launch=is_boot)
    app._dashboard_controller = _controller  # type: ignore
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
