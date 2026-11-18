# -*- coding: utf-8 -*-
"""
AI BOARD 命令行一键配置向导 (无需启动 GUI)
用法:
    python app.py --setup            交互式配置 (自动探测本机 AI 工具 + 开机自启)
    python app.py --setup --yes      全部使用推荐默认值，无交互
    python app.py --disable-autostart
"""

import sys
from typing import List

from core.scanner import LocalAIScanner
from core.startup import is_autostart_enabled, set_autostart
from core.storage import DashboardStorage


PROVIDER_NAMES = [
    ("codex", "OpenAI Codex", "codex_count"),
    ("antigravity", "Gemini Antigravity", "antigravity_count"),
    ("claude_code", "Claude Code", "claude_count"),
    ("deepseek_harness", "DeepSeek Harness", "deepseek_count"),
]


def _safe_print(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def _ask_yes(question: str, default_yes: bool, auto_yes: bool) -> bool:
    if auto_yes or not sys.stdin or not sys.stdin.isatty():
        return default_yes
    hint = "[Y/n]" if default_yes else "[y/N]"
    try:
        ans = input("{} {} ".format(question, hint)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default_yes
    if not ans:
        return default_yes
    return ans in ("y", "yes", "是", "1")


def run_setup(argv: List[str]) -> int:
    auto_yes = ("--yes" in argv) or ("-y" in argv)

    _safe_print("")
    _safe_print("==============================================")
    _safe_print("   AI BOARD  ·  一键配置向导 / Quick Setup")
    _safe_print("==============================================")

    storage = DashboardStorage()
    _safe_print("[1/3] 数据存档目录: {}".format(storage.data_dir))

    _safe_print("[2/3] 正在扫描本机 AI 工具 ...")
    scanner = LocalAIScanner()
    result = scanner.scan_all(force_refresh=True)
    diag = result.get("diagnostics", {})
    detected = diag.get("detected", {})

    any_found = False
    for aid, name, cnt_key in PROVIDER_NAMES:
        found = bool(detected.get(aid))
        cnt = int(diag.get(cnt_key, 0) or 0)
        mark = "[✓]" if found else "[ ]"
        tail = "已检测到 {} 个会话".format(cnt) if found else "未检测到"
        _safe_print("      {} {:<20} {}".format(mark, name, tail))
        storage.set_account_visible(aid, found)
        any_found = any_found or found

    if not any_found:
        # 一个都没检测到时，至少保留 Codex 与 Antigravity 两张卡片方便手动记录
        storage.set_account_visible("codex", True)
        storage.set_account_visible("antigravity", True)
        _safe_print("      未检测到任何本地工具，已默认显示 Codex / Antigravity 卡片 (可手动校准)")

    show_gpt = _ask_yes("      是否显示「ChatGPT 网页版」手动额度卡片?", False, auto_yes)
    storage.set_account_visible("chatgpt", show_gpt)

    _safe_print("[3/3] 开机自启设置")
    want_auto = _ask_yes("      是否开机自动启动 AI BOARD?", True, auto_yes)
    ok, msg = set_autostart(want_auto)
    _safe_print("      {}".format(msg if ok else "失败: " + msg))

    if want_auto:
        mini = _ask_yes("      开机后是否以迷你悬浮窗形态启动?", False, auto_yes)
        storage.update_ui(boot_in_mini_mode=mini)

    storage.save()
    _safe_print("")
    _safe_print("配置完成！运行 `aiboard` (或双击桌面快捷方式) 即可启动看板。")
    _safe_print("之后可随时运行 `aiboard setup` 重新配置。")
    _safe_print("")
    return 0


def run_disable_autostart() -> int:
    ok, msg = set_autostart(False)
    _safe_print(msg)
    return 0 if ok else 1


def print_status() -> int:
    _safe_print("autostart: {}".format("on" if is_autostart_enabled() else "off"))
    storage = DashboardStorage()
    _safe_print("data dir : {}".format(storage.data_dir))
    for acc in storage.get_accounts():
        _safe_print(
            "  {:<18} visible={!s:<5} remaining={}%".format(
                acc.get("name"), bool(acc.get("visible")), acc.get("remaining_pct")
            )
        )
    return 0
