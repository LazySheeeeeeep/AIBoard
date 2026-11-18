# -*- coding: utf-8 -*-
"""
本地状态持久化管理模块 (Python 3.7+ 兼容 · 生产级防丢数据加固版)
特性：
1. 标准用户数据目录持久化 (%APPDATA%\\AIBoard\\dashboard_state.json)，升级/移动程序目录不丢数据；支持便携模式与沙盒回退。
2. 自动无缝迁移旧版 d:\\LongApp\\data\\dashboard_state.json 数据。
3. 每次保存执行 flush + os.fsync 强制物理落盘 + 自动滚动备份 (.bak)，防止关机/重启断电导致待办丢失。
"""

import json
import os
import shutil
import sys
import time
import uuid
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = 4

DEFAULT_STEP_BUDGETS = {
    "codex": 120,
    "antigravity": 120,
    "claude_code": 100,
    "deepseek_harness": 150,
    "chatgpt": 0,
}


def _now_ts() -> float:
    return time.time()


def _app_root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_user_data_dir() -> str:
    """
    解析持久化存档目录：
    1. 若程序根目录存在 portable.flag，使用程序目录下的 data/（绿色便携模式）
    2. 否则优先使用 Windows 标准 %APPDATA%\\AIBoard（保证重装/更新/开机自启权限永远稳定）
    3. 若当前处于受限沙盒无法写入 %APPDATA%，自动回退到程序目录下的 data/
    """
    root_dir = _app_root_dir()
    legacy_dir = os.path.join(root_dir, "data")
    if os.path.isfile(os.path.join(root_dir, "portable.flag")):
        return legacy_dir

    appdata = os.environ.get("APPDATA")
    if appdata:
        std_dir = os.path.join(appdata, "AIBoard")
        try:
            if not os.path.exists(std_dir):
                os.makedirs(std_dir)
            probe = os.path.join(std_dir, ".write_probe")
            with open(probe, "w", encoding="utf-8") as pf:
                pf.write("ok")
            os.remove(probe)

            # 若新标准目录尚无存档，而旧项目目录已有存档，自动无损迁移过来
            std_file = os.path.join(std_dir, "dashboard_state.json")
            legacy_file = os.path.join(legacy_dir, "dashboard_state.json")
            if not os.path.isfile(std_file) and os.path.isfile(legacy_file):
                shutil.copy2(legacy_file, std_file)
            return std_dir
        except Exception:
            pass

    return legacy_dir


def _default_accounts(now: float) -> List[Dict[str, Any]]:
    return [
        {
            "id": "codex",
            "name": "OpenAI Codex",
            "subtitle": "Codex Desktop / Agent",
            "short_label": "CDX",
            "color": "#3B78CC",
            "visible": True,
            "remaining_pct": 100,
            "secondary_pct": None,
            "secondary_label": "周额度",
            "window_hours": 5.0,
            "reset_at": now + 5.0 * 3600,
            "auto_sync_log": True,
            "step_budget": 120,
            "updated_at": now,
        },
        {
            "id": "antigravity",
            "name": "Antigravity",
            "subtitle": "Gemini Antigravity",
            "short_label": "AGY",
            "color": "#8456CC",
            "visible": True,
            "remaining_pct": 100,
            "secondary_pct": None,
            "secondary_label": "",
            "window_hours": 5.0,
            "reset_at": now + 5.0 * 3600,
            "auto_sync_log": True,
            "step_budget": 120,
            "updated_at": now,
        },
        {
            "id": "claude_code",
            "name": "Claude Code",
            "subtitle": "Anthropic Claude Code",
            "short_label": "CLD",
            "color": "#D4743B",
            "visible": False,
            "remaining_pct": 100,
            "secondary_pct": None,
            "secondary_label": "",
            "window_hours": 5.0,
            "reset_at": now + 5.0 * 3600,
            "auto_sync_log": True,
            "step_budget": 100,
            "updated_at": now,
        },
        {
            "id": "deepseek_harness",
            "name": "DeepSeek Harness",
            "subtitle": "DeepSeek Harness (dsh)",
            "short_label": "DSH",
            "color": "#2A8F9D",
            "visible": False,
            "remaining_pct": 100,
            "secondary_pct": None,
            "secondary_label": "",
            "window_hours": 24.0,
            "reset_at": now + 24.0 * 3600,
            "auto_sync_log": True,
            "step_budget": 150,
            "updated_at": now,
        },
        {
            "id": "chatgpt",
            "name": "ChatGPT 网页版",
            "subtitle": "Web Plus & Pro",
            "short_label": "GPT",
            "color": "#2B996E",
            "visible": False,
            "remaining_pct": 100,
            "secondary_pct": None,
            "secondary_label": "",
            "window_hours": 3.0,
            "reset_at": now + 3.0 * 3600,
            "auto_sync_log": False,
            "step_budget": 0,
            "updated_at": now,
        },
    ]


def _default_todos(now: float) -> List[Dict[str, Any]]:
    return [
        {
            "id": uuid.uuid4().hex[:10],
            "text": "欢迎使用 AI BOARD！双击待办文字可编辑，所有数据实时落盘重启不丢失",
            "done": False,
            "priority": "high",
            "pinned": True,
            "created_at": now,
            "completed_at": None,
        },
        {
            "id": uuid.uuid4().hex[:10],
            "text": "点击左上角「⚙ 设置」可管理开机自启、Claude Code 与 DeepSeek Harness",
            "done": False,
            "priority": "normal",
            "pinned": False,
            "created_at": now + 1,
            "completed_at": None,
        },
    ]


class DashboardStorage(object):
    """带自动容灾备份与强制物理落盘的本地 JSON 状态存储管理器"""

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self.data_dir = data_dir or resolve_user_data_dir()
        self.file_path = os.path.join(self.data_dir, "dashboard_state.json")
        self.backup_path = self.file_path + ".bak"
        self.state = {}  # type: Dict[str, Any]
        self.load()

    def _build_default_state(self) -> Dict[str, Any]:
        now = _now_ts()
        return {
            "version": SCHEMA_VERSION,
            "accounts": _default_accounts(now),
            "session_overrides": {},
            "manual_sessions": [],
            "todos": _default_todos(now),
            "ui": {
                "mode": "expanded",
                "mini_orb_style": False,
                "boot_in_mini_mode": False,
                "always_on_top": True,
                "active_tab": "all",
                "session_filter": "all",
                "panel_pos": None,
                "panel_size": [680, 590],
                "mini_pos": None,
                "scan_interval_sec": 5,
            },
            "custom_paths": {
                "codex_dirs": [],
                "antigravity_dirs": [],
                "claude_dirs": [],
                "deepseek_dirs": [],
            },
        }

    def _read_json_safely(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "todos" in data:
                return data
        except Exception:
            return None
        return None

    def load(self) -> None:
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        if not os.path.exists(self.file_path) and not os.path.exists(self.backup_path):
            self.state = self._build_default_state()
            self.save()
            return

        # 优先读取主文件，若主文件因极端断电损坏，自动从 .bak 备份无损恢复！
        loaded = self._read_json_safely(self.file_path)
        recovered_from_bak = False
        if loaded is None:
            loaded = self._read_json_safely(self.backup_path)
            recovered_from_bak = loaded is not None

        if loaded is None:
            self.state = self._build_default_state()
            self.save()
            return

        old_version = int(loaded.get("version") or 1)
        default = self._build_default_state()

        for key, val in default.items():
            if key not in loaded:
                loaded[key] = val
            elif isinstance(val, dict) and isinstance(loaded[key], dict):
                for sub_k, sub_v in val.items():
                    if sub_k not in loaded[key]:
                        loaded[key][sub_k] = sub_v

        acc_by_id = {str(a.get("id")): a for a in loaded.get("accounts", []) if isinstance(a, dict)}
        merged_accounts = []  # type: List[Dict[str, Any]]
        for def_acc in default["accounts"]:
            aid = def_acc["id"]
            if aid in acc_by_id:
                cur_acc = acc_by_id[aid]
                for dk, dv in def_acc.items():
                    if dk not in cur_acc:
                        cur_acc[dk] = dv
                if old_version < 2 and aid == "chatgpt":
                    cur_acc["visible"] = False
                if old_version < 4 and aid != "chatgpt" and int(cur_acc.get("step_budget") or 0) == 0:
                    cur_acc["step_budget"] = DEFAULT_STEP_BUDGETS.get(aid, 120)
                merged_accounts.append(cur_acc)
            else:
                merged_accounts.append(def_acc)

        if old_version < 4 and int(loaded.get("ui", {}).get("scan_interval_sec") or 15) == 15:
            loaded["ui"]["scan_interval_sec"] = 5

        loaded["accounts"] = merged_accounts
        loaded["version"] = SCHEMA_VERSION
        self.state = loaded
        self.check_and_roll_resets()
        if old_version < SCHEMA_VERSION or recovered_from_bak:
            self.save()

    def save(self) -> None:
        """强制 fsync 物理落盘 + 滚动 .bak 备份 + 原子重命名，确保重启/断电绝不丢待办"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        payload = json.dumps(self.state, ensure_ascii=False, indent=2)
        tmp_path = self.file_path + ".tmp"

        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        # 保留上一个完好版本到 .bak
        if os.path.isfile(self.file_path):
            try:
                if os.path.getsize(self.file_path) > 10:
                    shutil.copy2(self.file_path, self.backup_path)
            except Exception:
                pass

        try:
            os.replace(tmp_path, self.file_path)
        except OSError:
            if os.path.exists(self.file_path):
                os.remove(self.file_path)
            os.rename(tmp_path, self.file_path)

    # ------------------------------------------------------------------
    # 模块 1：AI 账户额度与显示管理
    # ------------------------------------------------------------------
    def get_accounts(self, only_visible: bool = False) -> List[Dict[str, Any]]:
        self.check_and_roll_resets()
        accs = self.state.get("accounts", [])
        if only_visible:
            return [a for a in accs if a.get("visible", True)]
        return accs

    def set_account_visible(self, account_id: str, visible: bool) -> None:
        for acc in self.state.get("accounts", []):
            if acc.get("id") == account_id:
                acc["visible"] = bool(visible)
                self.save()
                break

    def check_and_roll_resets(self) -> bool:
        now = _now_ts()
        changed = False
        for acc in self.state.get("accounts", []):
            window_sec = max(float(acc.get("window_hours", 5.0)), 0.25) * 3600.0
            reset_at = acc.get("reset_at")
            if not reset_at:
                acc["reset_at"] = now + window_sec
                changed = True
                continue
            reset_at = float(reset_at)
            if now >= reset_at:
                elapsed = now - reset_at
                periods = int(elapsed // window_sec) + 1
                acc["reset_at"] = reset_at + periods * window_sec
                acc["remaining_pct"] = 100
                acc["manual_override_ts"] = 0
                acc["manual_anchor_pct"] = 100
                acc["updated_at"] = now
                changed = True
        if changed:
            self.save()
        return changed

    def update_account_quota(
        self,
        account_id: str,
        remaining_pct: Optional[int] = None,
        delta_pct: Optional[int] = None,
        window_hours: Optional[float] = None,
        reset_in_minutes: Optional[float] = None,
        auto_sync_log: Optional[bool] = None,
        step_budget: Optional[int] = None,
        visible: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        now = _now_ts()
        for acc in self.state.get("accounts", []):
            if acc.get("id") != account_id:
                continue
            if remaining_pct is not None:
                acc["remaining_pct"] = max(0, min(100, int(round(remaining_pct))))
            if delta_pct is not None:
                cur = int(acc.get("remaining_pct", 100))
                acc["remaining_pct"] = max(0, min(100, cur + int(delta_pct)))
            if window_hours is not None and window_hours > 0:
                acc["window_hours"] = float(window_hours)
            if reset_in_minutes is not None and reset_in_minutes >= 0:
                acc["reset_at"] = now + float(reset_in_minutes) * 60.0
            if auto_sync_log is not None:
                acc["auto_sync_log"] = bool(auto_sync_log)
            if step_budget is not None:
                acc["step_budget"] = max(0, int(step_budget))
            if visible is not None:
                acc["visible"] = bool(visible)
            acc["updated_at"] = now
            self.save()
            return acc
        return None

    def apply_scanned_quota_hints(self, scan_summary: Dict[str, Any]) -> bool:
        """
        实时同步本地扫描到的额度与活跃步数：
        1. 若 Codex 日志存在比上次手动校准更新的官方 rate_limits，100% 同步官方百分比与重置时间；
        2. 否则按「手动校准锚点 + 后续新增步数扣减」（无手动锚点则按当前窗口实时步数扣减）动态同步！
        """
        now = _now_ts()
        changed = False
        codex_rl = scan_summary.get("codex_rate_limit")

        stats_key_map = {
            "codex": "codex_stats",
            "antigravity": "antigravity_stats",
            "claude_code": "claude_stats",
            "deepseek_harness": "deepseek_stats",
        }

        for acc in self.state.get("accounts", []):
            acc_id = str(acc.get("id") or "")
            if not acc.get("auto_sync_log", True):
                continue

            manual_ts = float(acc.get("manual_override_ts") or 0.0)
            used_official_rl = False

            # 1. 优先采用 Codex 官方日志中的 rate_limits
            if acc_id == "codex" and codex_rl:
                event_ts = float(codex_rl.get("event_ts") or 0.0)
                primary_rem = codex_rl.get("primary_remaining_pct")
                primary_reset = codex_rl.get("primary_reset_at")
                secondary_rem = codex_rl.get("secondary_remaining_pct")

                if primary_rem is not None and event_ts >= manual_ts:
                    used_official_rl = True
                    new_pct = max(0, min(100, int(round(primary_rem))))
                    if acc.get("remaining_pct") != new_pct:
                        acc["remaining_pct"] = new_pct
                        changed = True
                    if primary_reset and primary_reset > now:
                        if abs(float(acc.get("reset_at") or 0) - primary_reset) > 30:
                            acc["reset_at"] = float(primary_reset)
                            changed = True
                if secondary_rem is not None:
                    sec_val = max(0, min(100, int(round(secondary_rem))))
                    if acc.get("secondary_pct") != sec_val:
                        acc["secondary_pct"] = sec_val
                        changed = True

            if used_official_rl:
                continue

            # 2. 锚点 + 实时步数增量动态扣减 (适用于 Antigravity / Claude / DSH 及手动校准后的增量同步)
            budget = int(acc.get("step_budget") or 0)
            stats_key = stats_key_map.get(acc_id)
            if budget <= 0 or not stats_key or stats_key not in scan_summary:
                continue

            st_obj = scan_summary[stats_key]
            step_ts_list = st_obj.get("recent_step_ts")
            win_sec = max(0.25, float(acc.get("window_hours") or 5.0)) * 3600.0
            win_start = now - win_sec

            if isinstance(step_ts_list, list):
                valid_steps = sorted(float(t) for t in step_ts_list if float(t) >= win_start)
            else:
                valid_steps = []

            if manual_ts > win_start:
                anchor_pct = int(acc.get("manual_anchor_pct", acc.get("remaining_pct", 100)))
                steps_after_anchor = sum(1 for t in valid_steps if t > manual_ts)
                est_rem = max(
                    0,
                    min(100, int(round(anchor_pct - 100.0 * steps_after_anchor / float(budget)))),
                )
            else:
                win_steps = len(valid_steps) if isinstance(step_ts_list, list) else int(st_obj.get("window_steps", 0))
                est_rem = max(
                    0, min(100, int(round(100.0 * (1.0 - win_steps / float(budget)))))
                )
                # 自动将恢复时间对齐到本轮窗口首条消息 + 周期时长
                if valid_steps:
                    natural_reset = valid_steps[0] + win_sec
                    if natural_reset > now and abs(float(acc.get("reset_at") or 0) - natural_reset) > 60:
                        acc["reset_at"] = natural_reset
                        changed = True

            if acc.get("remaining_pct") != est_rem:
                acc["remaining_pct"] = est_rem
                changed = True

        if changed:
            self.save()
        return changed

    def mark_manual_calibration(self, account_id: str, anchor_pct: Optional[int] = None) -> None:
        now = _now_ts()
        for acc in self.state.get("accounts", []):
            if acc.get("id") == account_id:
                acc["manual_override_ts"] = now
                if anchor_pct is not None:
                    acc["manual_anchor_pct"] = max(0, min(100, int(round(anchor_pct))))
                else:
                    acc["manual_anchor_pct"] = int(acc.get("remaining_pct", 100))
                self.save()
                break

    # ------------------------------------------------------------------
    # 模块 2：AI 对话状态覆盖
    # ------------------------------------------------------------------
    def get_session_override(self, session_key: str) -> Dict[str, Any]:
        return self.state.get("session_overrides", {}).get(session_key, {})

    def set_session_override(
        self,
        session_key: str,
        status: Optional[str] = None,
        pinned: Optional[bool] = None,
        hidden: Optional[bool] = None,
        custom_title: Optional[str] = None,
    ) -> None:
        overrides = self.state.setdefault("session_overrides", {})
        cur = overrides.setdefault(session_key, {})
        if status is not None:
            if status == "auto":
                cur.pop("status", None)
            else:
                cur["status"] = status
        if pinned is not None:
            cur["pinned"] = bool(pinned)
        if hidden is not None:
            cur["hidden"] = bool(hidden)
        if custom_title is not None:
            cur["custom_title"] = custom_title.strip()
        self.save()

    def restore_hidden_sessions(self) -> int:
        overrides = self.state.get("session_overrides", {})
        count = 0
        for val in overrides.values():
            if val.get("hidden"):
                val["hidden"] = False
                count += 1
        if count:
            self.save()
        return count

    def get_manual_sessions(self) -> List[Dict[str, Any]]:
        return self.state.get("manual_sessions", [])

    def delete_manual_session(self, key: str) -> None:
        items = self.state.get("manual_sessions", [])
        self.state["manual_sessions"] = [x for x in items if x.get("key") != key]
        self.save()

    # ------------------------------------------------------------------
    # 模块 3：个人待办事项 CRUD
    # ------------------------------------------------------------------
    def get_todos(self) -> List[Dict[str, Any]]:
        todos = list(self.state.get("todos", []))
        prio_rank = {"high": 0, "urgent": 0, "normal": 1}
        todos.sort(
            key=lambda x: (
                1 if x.get("done") else 0,
                0 if x.get("pinned") else 1,
                prio_rank.get(x.get("priority", "normal"), 1),
                -float(x.get("created_at") or 0),
            )
        )
        return todos

    def add_todo(self, text: str, priority: str = "normal") -> Optional[Dict[str, Any]]:
        clean = text.strip()
        if not clean:
            return None
        now = _now_ts()
        norm_prio = "high" if priority in ("high", "urgent") else "normal"
        item = {
            "id": uuid.uuid4().hex[:10],
            "text": clean,
            "done": False,
            "priority": norm_prio,
            "pinned": False,
            "created_at": now,
            "completed_at": None,
        }
        self.state.setdefault("todos", []).insert(0, item)
        self.save()
        return item

    def toggle_todo(self, todo_id: str) -> Optional[bool]:
        now = _now_ts()
        for item in self.state.get("todos", []):
            if item.get("id") == todo_id:
                new_done = not bool(item.get("done"))
                item["done"] = new_done
                item["completed_at"] = now if new_done else None
                self.save()
                return new_done
        return None

    def update_todo(
        self,
        todo_id: str,
        text: Optional[str] = None,
        priority: Optional[str] = None,
        pinned: Optional[bool] = None,
    ) -> bool:
        for item in self.state.get("todos", []):
            if item.get("id") == todo_id:
                if text is not None and text.strip():
                    item["text"] = text.strip()
                if priority in ("normal", "high", "urgent"):
                    item["priority"] = "high" if priority in ("high", "urgent") else "normal"
                if pinned is not None:
                    item["pinned"] = bool(pinned)
                self.save()
                return True
        return False

    def delete_todo(self, todo_id: str) -> bool:
        before = len(self.state.get("todos", []))
        self.state["todos"] = [x for x in self.state.get("todos", []) if x.get("id") != todo_id]
        if len(self.state["todos"]) != before:
            self.save()
            return True
        return False

    def clear_completed_todos(self) -> int:
        todos = self.state.get("todos", [])
        remaining = [x for x in todos if not x.get("done")]
        removed = len(todos) - len(remaining)
        if removed > 0:
            self.state["todos"] = remaining
            self.save()
        return removed

    # ------------------------------------------------------------------
    # UI 与路径配置
    # ------------------------------------------------------------------
    def get_ui(self) -> Dict[str, Any]:
        return self.state.setdefault("ui", {})

    def update_ui(self, **kwargs: Any) -> None:
        ui = self.state.setdefault("ui", {})
        changed = False
        for k, v in kwargs.items():
            if ui.get(k) != v:
                ui[k] = v
                changed = True
        if changed:
            self.save()

    def get_custom_paths(self) -> Dict[str, List[str]]:
        cp = self.state.setdefault("custom_paths", {})
        for k in ("codex_dirs", "antigravity_dirs", "claude_dirs", "deepseek_dirs"):
            cp.setdefault(k, [])
        return cp

    def set_custom_paths(
        self,
        codex_dirs: Optional[List[str]] = None,
        antigravity_dirs: Optional[List[str]] = None,
        claude_dirs: Optional[List[str]] = None,
        deepseek_dirs: Optional[List[str]] = None,
    ) -> None:
        cp = self.get_custom_paths()
        if codex_dirs is not None:
            cp["codex_dirs"] = [p.strip() for p in codex_dirs if p.strip()]
        if antigravity_dirs is not None:
            cp["antigravity_dirs"] = [p.strip() for p in antigravity_dirs if p.strip()]
        if claude_dirs is not None:
            cp["claude_dirs"] = [p.strip() for p in claude_dirs if p.strip()]
        if deepseek_dirs is not None:
            cp["deepseek_dirs"] = [p.strip() for p in deepseek_dirs if p.strip()]
        self.save()
