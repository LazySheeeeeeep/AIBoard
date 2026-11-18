# -*- coding: utf-8 -*-
"""
针对存储模块、四大本地 AI 工具自动扫描引擎 (Codex + Antigravity + Claude Code + DeepSeek Harness)
及双模式 PyQt5 UI 的自动化单元测试
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import app as app_entry  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402
from core.scanner import LocalAIScanner, clean_title_text, parse_timestamp  # noqa: E402
from core.storage import DashboardStorage  # noqa: E402
from ui.main_panel import MainDashboardPanel  # noqa: E402
from ui.mini_bar import MiniFloatingWidget  # noqa: E402


class TestDashboardSuite(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp(dir=ROOT_DIR, prefix="_tmp_test_")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_timestamp_and_title_cleaner(self) -> None:
        ts_z = parse_timestamp("2026-11-16T02:40:28Z")
        ts_offset = parse_timestamp("2026-11-16T10:40:28+08:00")
        self.assertIsNotNone(ts_z)
        self.assertAlmostEqual(ts_z, ts_offset, delta=1.0)

        raw_prompt = (
            "<USER_REQUEST>\n帮我重构桌面看板模块\n</USER_REQUEST>\n"
            "<ADDITIONAL_METADATA>time</ADDITIONAL_METADATA>"
        )
        self.assertEqual(clean_title_text(raw_prompt), "帮我重构桌面看板模块")

    def test_storage_accounts_visibility_and_todos(self) -> None:
        st = DashboardStorage(data_dir=os.path.join(self.tmp_dir, "state_data"))
        all_accs = st.get_accounts(only_visible=False)
        vis_accs = st.get_accounts(only_visible=True)
        self.assertEqual(len(all_accs), 5)
        # 默认仅显示 codex 和 antigravity，chatgpt 默认隐藏
        vis_ids = {a["id"] for a in vis_accs}
        self.assertEqual(vis_ids, {"codex", "antigravity"})

        # 测试开启 claude_code 与 deepseek_harness
        st.set_account_visible("claude_code", True)
        st.set_account_visible("deepseek_harness", True)
        self.assertEqual(len(st.get_accounts(only_visible=True)), 4)

        # 测试周期自动回满
        st.update_account_quota("codex", remaining_pct=45)
        for a in st.state["accounts"]:
            if a["id"] == "codex":
                a["reset_at"] = time.time() - 10
        st.check_and_roll_resets()
        self.assertEqual(
            [a for a in st.get_accounts() if a["id"] == "codex"][0]["remaining_pct"], 100
        )

        added = st.add_todo("完成四平台扫描测试", priority="urgent")
        self.assertIsNotNone(added)

        # 测试极端重启断电导致主 JSON 损坏时，自动从 .bak 无损找回待办事项！
        st.add_todo("这条重要待办在断电重启后绝不能丢", priority="high")
        with open(st.file_path, "w", encoding="utf-8") as bad_f:
            bad_f.write("{corrupted_json")
        st_reloaded = DashboardStorage(data_dir=os.path.join(self.tmp_dir, "state_data"))
        recovered_texts = [t["text"] for t in st_reloaded.get_todos()]
        self.assertIn("完成四平台扫描测试", recovered_texts)

        st_reloaded.toggle_todo(added["id"])
        self.assertEqual(st_reloaded.clear_completed_todos(), 1)

    def test_scanner_four_platforms(self) -> None:
        now = time.time()
        iso_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))

        # 1. Antigravity (测试对话名称提炼 vs 最新一条 last_prompt 分离)
        agy_brain = os.path.join(self.tmp_dir, "mock_agy")
        conv_dir = os.path.join(agy_brain, "conv-1", ".system_generated", "logs")
        os.makedirs(conv_dir)
        with open(os.path.join(conv_dir, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "USER_INPUT", "status": "DONE", "created_at": iso_now, "content": "<USER_REQUEST>我想制作一个个人桌面小插件，这个小插件是一个看板</USER_REQUEST>"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"type": "PLANNER_RESPONSE", "status": "DONE", "created_at": iso_now, "input_tokens": 1000, "output_tokens": 200}) + "\n")
            f.write(json.dumps({"type": "USER_INPUT", "status": "DONE", "created_at": iso_now, "content": "<USER_REQUEST>把标题改成英文并修复更新延迟</USER_REQUEST>"}, ensure_ascii=False) + "\n")

        # 2. OpenAI Codex (含 WAL 模式数据库快照测试)
        codex_root = os.path.join(self.tmp_dir, "mock_codex")
        sess_dir = os.path.join(codex_root, "sessions", "2026", "11", "16")
        os.makedirs(sess_dir)
        rollout_path = os.path.join(sess_dir, "rollout-abc.jsonl")
        with open(rollout_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": iso_now, "type": "session_meta", "payload": {"id": "thread-abc", "cwd": "D:\\LongApp"}}) + "\n")
            f.write(json.dumps({"timestamp": iso_now, "type": "event_msg", "payload": {"type": "user_message", "message": "第一句初始化项目"}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"timestamp": iso_now, "type": "event_msg", "payload": {"type": "user_message", "message": "检查 WAL 锁导致的同步延迟"}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"timestamp": iso_now, "type": "event_msg", "payload": {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 5000}, "last_token_usage": {"total_tokens": 5000}}, "rate_limits": {"primary": {"used_percent": 25.0, "window_minutes": 300, "resets_at": now + 3600}}}}) + "\n")
            f.write(json.dumps({"timestamp": iso_now, "type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")

        db_path = os.path.join(codex_root, "state.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, cwd TEXT, rollout_path TEXT, updated_at INTEGER, archived INTEGER)")
        conn.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)", ("thread-abc", "Codex 优化任务", "D:\\LongApp", rollout_path, int(now), 0))
        conn.commit()
        # 故意保持 conn 打开不关闭，模拟 Codex 桌面端正在占用 WAL 数据库！

        # 3. Claude Code
        claude_root = os.path.join(self.tmp_dir, "mock_claude")
        cl_proj = os.path.join(claude_root, "projects", "d--LongApp")
        os.makedirs(cl_proj)
        with open(os.path.join(cl_proj, "sess-cl-1.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "summary", "summary": "架构设计审查"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"type": "user", "sessionId": "cl-1", "cwd": "D:\\LongApp", "timestamp": iso_now, "message": {"role": "user", "content": "用 Claude 检查架构设计"}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"type": "assistant", "sessionId": "cl-1", "timestamp": iso_now, "message": {"role": "assistant", "content": [{"type": "text", "text": "没问题"}], "usage": {"input_tokens": 800, "output_tokens": 400}}}) + "\n")

        # 4. DeepSeek Harness
        dsh_root = os.path.join(self.tmp_dir, "mock_dsh")
        dsh_s1 = os.path.join(dsh_root, "sessions", "projA", "s-plain")
        dsh_s2 = os.path.join(dsh_root, "sessions", "projA", "s-zstd")
        os.makedirs(dsh_s1)
        os.makedirs(dsh_s2)
        with open(os.path.join(dsh_s1, "events.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": iso_now, "role": "user", "content": "DeepSeek Harness 性能压测"}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"timestamp": iso_now, "role": "assistant", "usage": {"total_tokens": 2100}}) + "\n")
        with open(os.path.join(dsh_s2, "events.jsonl.zst"), "wb") as bf:
            bf.write(b"\x28\xb5\x2f\xfd\x00\x11\x22\x33")

        scanner = LocalAIScanner()
        agy_sessions, _agy_stats = scanner._scan_antigravity([agy_brain], now, now - 3600, now - 3600)
        cdx_sessions, _cdx_stats, _cdx_rl = scanner._scan_codex([codex_root], now, now - 3600, now - 3600)
        cl_sessions, cl_stats = scanner._scan_claude([claude_root], now, now - 3600, now - 3600)
        ds_sessions, ds_stats = scanner._scan_deepseek_harness([dsh_root], now, now - 3600, now - 3600)
        conn.close()

        self.assertEqual(agy_sessions[0]["title"], "个人桌面小插件")
        self.assertEqual(agy_sessions[0]["last_prompt"], "把标题改成英文并修复更新延迟")

        self.assertEqual(cdx_sessions[0]["title"], "Codex 优化任务")
        self.assertEqual(cdx_sessions[0]["last_prompt"], "检查 WAL 锁导致的同步延迟")

        self.assertEqual(len(cl_sessions), 1)
        self.assertEqual(cl_sessions[0]["title"], "架构设计审查")
        self.assertEqual(cl_sessions[0]["last_prompt"], "用 Claude 检查架构设计")
        self.assertEqual(cl_stats["window_tokens"], 1200)

        self.assertEqual(len(ds_sessions), 2)
        self.assertEqual(ds_stats["window_tokens"], 2100)

        # 5. 测试锚点后新增步数动态实时扣减额度百分比
        st_quota = DashboardStorage(data_dir=os.path.join(self.tmp_dir, "quota_delta_test"))
        st_quota.update_account_quota("antigravity", remaining_pct=80, step_budget=100)
        st_quota.mark_manual_calibration("antigravity", anchor_pct=80)
        # 模拟校准后又新产生了 12 步调用 -> 应自动实时同步为 80 - 12 = 68%
        future_steps = [time.time() + i + 1 for i in range(12)]
        st_quota.apply_scanned_quota_hints(
            {"antigravity_stats": {"window_steps": 12, "recent_step_ts": future_steps}}
        )
        agy_acc = [a for a in st_quota.get_accounts() if a["id"] == "antigravity"][0]
        self.assertEqual(agy_acc["remaining_pct"], 68)

    def test_sidebar_title_extraction_codex_and_antigravity(self) -> None:
        """测试：Codex session_index.jsonl 优先覆盖伪装在 threads.title 里的原始 prompt，以及 Antigravity Protobuf 标题解码"""
        import base64
        from core.scanner import decode_protobuf_uuid_titles

        def _pb_ld(field_no: int, data: bytes) -> bytes:
            tag = (field_no << 3) | 2
            length = len(data)
            out = bytearray([tag])
            while length >= 0x80:
                out.append((length & 0x7F) | 0x80)
                length >>= 7
            out.append(length)
            out.extend(data)
            return bytes(out)

        # 构造模拟 Antigravity state.vscdb Base64 Protobuf (含内层 base64 TrajectorySummary 与 file:// URI 干扰)
        test_uuid = "4289cb93-c792-479c-a538-0fb38a23da55"
        inner_summary = (
            _pb_ld(1, "个人桌面 AI 看板开发".encode("utf-8"))
            + _pb_ld(2, "file:///d:/LongApp".encode("utf-8"))
        )
        inner_b64 = base64.b64encode(inner_summary)
        entry_msg = _pb_ld(1, test_uuid.encode("utf-8")) + _pb_ld(2, inner_b64)
        top_pb_b64 = base64.b64encode(_pb_ld(1, entry_msg)).decode("ascii")

        decoded = decode_protobuf_uuid_titles(top_pb_b64)
        self.assertEqual(decoded.get(test_uuid), "个人桌面 AI 看板开发")

        # 构造模拟 Codex：threads.title 被塞入了原始长 prompt，而 session_index.jsonl 有真实会话标题
        now = time.time()
        iso_now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        c_root = os.path.join(self.tmp_dir, "mock_codex_idx")
        s_dir = os.path.join(c_root, "sessions", "2026", "11", "18")
        os.makedirs(s_dir)
        tid = "019eb9cc-8c38-7751-ba00-9b1534f9bb8c"
        raw_long_prompt = "我想让你帮我详细检查一下后端所有的微服务日志以及数据库连接池超时的问题并给出修复代码"
        r_path = os.path.join(s_dir, "rollout-2026-11-18T10-00-00-{}.jsonl".format(tid))
        with open(r_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": iso_now, "type": "event_msg", "payload": {"type": "user_message", "message": raw_long_prompt}}, ensure_ascii=False) + "\n")
            f.write(json.dumps({"timestamp": iso_now, "type": "event_msg", "payload": {"type": "task_complete"}}) + "\n")

        db_p = os.path.join(c_root, "state_5.sqlite")
        conn = sqlite3.connect(db_p)
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, first_user_message TEXT, cwd TEXT, rollout_path TEXT, updated_at INTEGER, archived INTEGER)")
        # 模拟 Codex 把原始长 prompt 直接存进了 threads.title！
        conn.execute("INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?)", (tid, raw_long_prompt, raw_long_prompt, "D:\\LongApp", r_path, int(now), 0))
        conn.commit()
        conn.close()

        with open(os.path.join(c_root, "session_index.jsonl"), "w", encoding="utf-8") as idxf:
            idxf.write(json.dumps({"id": tid, "thread_name": "微服务连接池超时修复", "updated_at": iso_now}, ensure_ascii=False) + "\n")

        scanner = LocalAIScanner()
        sessions, _st, _rl = scanner._scan_codex([c_root], now, now - 3600, now - 3600)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["title"], "微服务连接池超时修复")
        self.assertEqual(sessions[0]["last_prompt"], raw_long_prompt)

    def test_todo_edit_survives_auto_refresh(self) -> None:
        """回归测试：编辑对话框打开期间触发自动刷新，不得崩溃，且编辑结果必须保存成功"""
        from PyQt5 import QtCore, QtGui
        from ui.widgets import TodoItemRow

        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        st = DashboardStorage(data_dir=os.path.join(self.tmp_dir, "edit_state"))
        panel = MainDashboardPanel(st, always_on_top=True)
        panel.render_all({})
        panel.show()
        qapp.processEvents()

        target_id = st.get_todos()[0]["id"]
        state = {"refresh_returned": False, "modal_seen": False}

        def refresh_while_dialog_open() -> None:
            panel.render_all({})  # 模拟 5 秒自动扫描刷新
            state["refresh_returned"] = True

        def finish_dialog() -> None:
            dlg = QtWidgets.QApplication.activeModalWidget()
            state["modal_seen"] = dlg is not None
            if dlg is not None:
                dlg.setTextValue("改名成功")
                dlg.accept()

        QtCore.QTimer.singleShot(150, refresh_while_dialog_open)
        QtCore.QTimer.singleShot(500, finish_dialog)

        row = panel.findChildren(TodoItemRow)[0]
        ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonDblClick,
            QtCore.QPointF(5, 5),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        row.mouseDoubleClickEvent(ev)  # 阻塞直到对话框关闭；旧实现会在此处抛 RuntimeError 闪退
        qapp.processEvents()

        self.assertTrue(state["modal_seen"])
        self.assertTrue(state["refresh_returned"])
        texts = {t["id"]: t["text"] for t in st.get_todos()}
        self.assertEqual(texts[target_id], "改名成功")
        panel.close()

    def test_ui_widgets_smoke(self) -> None:
        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        st = DashboardStorage(data_dir=os.path.join(self.tmp_dir, "ui_state"))
        panel = MainDashboardPanel(st, always_on_top=True)
        mini = MiniFloatingWidget(always_on_top=True)

        fake_scan = {
            "scanned_at": time.time(),
            "sessions": [
                {
                    "key": "codex:t1",
                    "id": "t1",
                    "provider": "codex",
                    "provider_label": "Codex",
                    "title": "重构数据库连接池",
                    "status": "running",
                    "status_detail": "Agent 执行中",
                    "updated_at": time.time(),
                    "created_at": time.time(),
                    "step_count": 5,
                    "total_tokens": 12400,
                    "workspace": "LongApp",
                    "is_manual": False,
                }
            ],
            "antigravity_stats": {"window_steps": 8, "today_steps": 12, "window_tokens": 24000},
            "codex_stats": {"window_steps": 5, "today_steps": 5, "window_tokens": 12400},
            "claude_stats": {"window_steps": 3, "today_steps": 3, "window_tokens": 6000},
            "deepseek_stats": {"window_steps": 0, "today_steps": 0, "window_tokens": 0},
            "codex_rate_limit": {"event_ts": time.time(), "primary_remaining_pct": 72.0},
            "diagnostics": {
                "antigravity_count": 3,
                "codex_count": 94,
                "claude_count": 2,
                "deepseek_count": 0,
                "detected": {"codex": True, "antigravity": True, "claude_code": True, "deepseek_harness": False},
            },
        }
        st.apply_scanned_quota_hints(fake_scan)
        panel.render_all(fake_scan)
        mini.update_summary(st.get_accounts(), 1, 1, 2)
        panel.close()
        mini.close()
        self.assertIsNotNone(qapp)


if __name__ == "__main__":
    unittest.main()
