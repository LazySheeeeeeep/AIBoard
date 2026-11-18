# -*- coding: utf-8 -*-
"""
本地 AI 会话与额度实时同步扫描引擎 (Python 3.7+ 兼容 · 实时强同步版)
核心突破：
1. 完美攻克 Codex 桌面端 SQLite WAL 模式 (.sqlite-wal) 实时快照读取，毫秒级同步最新会话与官方对话标题。
2. 攻克 Windows NTFS 长连接追加写入句柄 mtime 不刷新问题，支持 force_refresh 穿透重读与近期活跃文件直读。
3. 严格分离「对话名称 (title)」与「上一条用户提问 (last_prompt)」。
4. 输出精确步骤时间戳序列，赋能额度「锚点 + 实时增量扣减」与官方 rate_limits 实时同步。
"""

import base64
import calendar
import glob
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple


SENSITIVE_FILENAMES = {
    "auth.json",
    "credentials.json",
    ".credentials.json",
    "config.toml",
    ".env",
    "cookies",
    "login data",
    "api_key",
}

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

USER_REQ_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL | re.IGNORECASE)
XML_BLOCK_STRIP_RE = re.compile(
    r"<(ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|SYSTEM_MESSAGE|environment_context|permissions instructions|INSTRUCTIONS|local-command-caveat|command-name|command-message|command-args|local-command-stdout)>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)
ANY_TAG_RE = re.compile(r"</?[A-Za-z0-9_:-]+[^>]*>")
ISO_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|([+-])(\d{2}):?(\d{2}))?$"
)

SPOKEN_PREFIX_RE = re.compile(
    r"^(?:你好[，,。！!\s]*|嗨[，,。！!\s]*)*"
    r"(?:我想制作一个|我想做一个|我想写一个|我想开发一个|帮我制作一个|帮我做一个|帮我写一个|帮我开发一个|"
    r"请你帮我|请帮我|能不能帮我|麻烦帮我|你可以帮我|帮我看看|帮我查一下|帮我检查一下|帮我|"
    r"请问一下|请问|我想让你|我发现|现在能不能帮我|现在帮我|我想|请你|请)\s*"
)

UUID_EXACT_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
UUID_SEARCH_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
B64_CAND_RE = re.compile(r"^[A-Za-z0-9+/=_-]{16,}$")


def parse_timestamp(val: Any) -> Optional[float]:
    """兼容 Unix 秒/毫秒数字及 ISO-8601 字符串 (含 Z 与 +08:00 偏移)"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        fval = float(val)
        if fval > 1e12:
            return fval / 1000.0
        if fval > 1e8:
            return fval
        return None
    if not isinstance(val, str):
        return None

    s = val.strip()
    if not s:
        return None
    if s.isdigit():
        num = float(s)
        return num / 1000.0 if num > 1e12 else num

    m = ISO_TS_RE.match(s)
    if not m:
        return None
    year, month, day, hour, minute, second = [int(m.group(i)) for i in range(1, 7)]
    frac_str = m.group(7)
    frac = float("0." + frac_str[:6]) if frac_str else 0.0
    tz_part = m.group(8)

    try:
        dt_tuple = (year, month, day, hour, minute, second)
        if not tz_part:
            base_ts = time.mktime(dt_tuple + (0, 0, -1))
            return base_ts + frac
        utc_ts = float(calendar.timegm(dt_tuple)) + frac
        if tz_part == "Z":
            return utc_ts
        sign = 1 if m.group(9) == "+" else -1
        tz_h = int(m.group(10))
        tz_m = int(m.group(11))
        offset_sec = sign * (tz_h * 3600 + tz_m * 60)
        return utc_ts - offset_sec
    except Exception:
        return None


def clean_prompt_text(raw: str, max_len: int = 90) -> str:
    """提取干净的单行用户提问文本 (用于展示「上一条 Prompt」)"""
    if not raw:
        return ""
    m = USER_REQ_RE.search(raw)
    if m:
        text = m.group(1)
    else:
        text = XML_BLOCK_STRIP_RE.sub(" ", raw)
        text = ANY_TAG_RE.sub(" ", text)

    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        lower = s.lower()
        if (
            lower.startswith("# agents.md")
            or lower.startswith("<environment_context")
            or lower.startswith("cwd:")
            or lower.startswith("shell:")
            or lower.startswith("## skills")
            or lower.startswith("caveat: the messages below")
        ):
            continue
        lines.append(s)
        if len(" ".join(lines)) >= max_len:
            break

    merged = re.sub(r"\s+", " ", " ".join(lines)).strip(" -#*>`")
    if len(merged) > max_len:
        return merged[: max_len - 1].rstrip() + "…"
    return merged


# 保持旧函数名兼容单元测试导入
def clean_title_text(raw: str, max_len: int = 54) -> str:
    return clean_prompt_text(raw, max_len=max_len)


def summarize_conversation_title(first_prompt_raw: str, workspace: str = "", max_len: int = 24) -> str:
    """
    当会话没有独立的官方标题时，从开篇第一条提问智能提炼简短「对话名称」
    去除口语化指令前缀，截取核心主题名词短语，避免直接显示冗长原句。
    """
    cleaned = clean_prompt_text(first_prompt_raw, max_len=80)
    if not cleaned:
        return ("项目 · " + workspace) if workspace else ""

    stripped = SPOKEN_PREFIX_RE.sub("", cleaned).strip()
    if not stripped:
        stripped = cleaned

    # 按常见中文/英文标点切分首句主题
    parts = [p.strip() for p in re.split(r"[，,。；;！!？?\n]+", stripped) if p.strip()]
    if not parts:
        topic = stripped
    else:
        topic = parts[0]
        # 若首段过短（如仅 2~4 个字），补上第二小段增强辨识度
        if len(topic) < 5 and len(parts) > 1:
            topic = topic + " · " + parts[1]

    topic = SPOKEN_PREFIX_RE.sub("", topic).strip(" ：:、-")
    if len(topic) > max_len:
        topic = topic[: max_len - 1].rstrip() + "…"
    return topic or cleaned[:max_len]


def _is_genuine_title(candidate: str, first_prompt: str = "") -> bool:
    """
    判断数据库里的 title 是否是真正的「会话标题」，而非客户端在新建会话时直接塞进去的原始第一条 Prompt。
    """
    cand = candidate.strip()
    if not cand:
        return False
    # 若包含多行或明显超长，通常是塞进去的原始 prompt
    if "\n" in cand or len(cand) > 42:
        return False
    # 若以明显的口语化对话提问开头且较长，说明是 prompt 原文而非总结标题
    if len(cand) > 18 and SPOKEN_PREFIX_RE.match(cand):
        return False
    if first_prompt:
        fp_norm = re.sub(r"\s+", "", clean_prompt_text(first_prompt, max_len=80))
        c_norm = re.sub(r"\s+", "", cand.rstrip(".…"))
        # 如果候选标题就是第一条 prompt 的前缀拷贝（且第一条 prompt 自身较长），说明它只是截断的 prompt
        if fp_norm and c_norm and len(fp_norm) > 16 and fp_norm.startswith(c_norm[: min(len(c_norm), 16)]):
            if abs(len(fp_norm) - len(c_norm)) <= 4 or len(c_norm) >= 22:
                return False
    return True


# ----------------------------------------------------------------------
# 纯 Python 零依赖 Protobuf Wire 解析器 (用于读取 Antigravity 侧边栏会话标题)
# ----------------------------------------------------------------------
def _read_varint(buf: bytes, pos: int, end: int) -> Tuple[Optional[int], int]:
    result = 0
    shift = 0
    while pos < end and shift <= 63:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
    return None, pos


def _iter_pb_fields(buf: bytes, start: int = 0, end: Optional[int] = None) -> Optional[List[Tuple[int, int, bytes]]]:
    """尝试将字节流解析为合法 Protobuf wire 字段序列；若非合法 protobuf 返回 None"""
    if end is None:
        end = len(buf)
    if end <= start:
        return None
    pos = start
    fields = []  # type: List[Tuple[int, int, bytes]]
    while pos < end:
        tag, pos = _read_varint(buf, pos, end)
        if tag is None or tag == 0:
            return None
        field_no = tag >> 3
        wire_type = tag & 0x07
        if field_no <= 0 or field_no > 536870911:
            return None
        if wire_type == 0:  # varint
            val, pos = _read_varint(buf, pos, end)
            if val is None:
                return None
        elif wire_type == 1:  # 64-bit
            if pos + 8 > end:
                return None
            pos += 8
        elif wire_type == 5:  # 32-bit
            if pos + 4 > end:
                return None
            pos += 4
        elif wire_type == 2:  # length-delimited
            length, pos = _read_varint(buf, pos, end)
            if length is None or length < 0 or pos + length > end:
                return None
            fields.append((field_no, wire_type, buf[pos : pos + length]))
            pos += length
        else:
            return None
    return fields


def _is_plausible_agy_title(s: str) -> bool:
    t = s.strip()
    if len(t) < 2 or len(t) > 100 or "\n" in t or "\r" in t:
        return False
    if UUID_EXACT_RE.match(t):
        return False
    low = t.lower()
    if (
        "://" in low
        or low.startswith(("file:", "type.googleapis.com", "/users/", "/home/", "c:\\", "d:\\", "e:\\"))
        or "\\" in t
        or low.endswith((".jsonl", ".pb", ".md", ".py", ".ts", ".js", ".git"))
    ):
        return False
    # 排除纯大写状态枚举名、base64 密文块或十六进制哈希
    if re.match(r"^[A-Z0-9_]{4,}$", t):
        return False
    if re.match(r"^[0-9a-fA-F]{16,}$", t):
        return False
    if len(t) >= 20 and " " not in t and all(ord(c) < 128 for c in t) and B64_CAND_RE.match(t):
        return False
    # 不含不可打印控制字符
    if any(ord(c) < 32 for c in t):
        return False
    return True


def _collect_pb_strings_recursive(blob: bytes, out_uuids: List[str], out_titles: List[str], depth: int = 0) -> None:
    if depth > 5 or not blob:
        return

    # 1. 先尝试当作嵌套 Protobuf 子消息继续展开
    sub_fields = _iter_pb_fields(blob)
    if sub_fields is not None and len(sub_fields) > 0:
        # 注意：短纯文本有时碰巧也能合乎某个 varint/len 边界，先检查是否直接是纯正可读短句或 UUID
        try:
            as_utf8 = blob.decode("utf-8")
            if UUID_EXACT_RE.match(as_utf8):
                out_uuids.append(as_utf8.lower())
                return
            # 若包含中文或空格且没有任何控制字符，说明它本身就是最终文本而非子消息
            if all(ord(c) >= 32 for c in as_utf8) and (
                any(ord(c) > 127 for c in as_utf8) or " " in as_utf8
            ):
                if _is_plausible_agy_title(as_utf8):
                    out_titles.append(as_utf8.strip())
                return
        except UnicodeDecodeError:
            pass

        for _fno, _wt, payload in sub_fields:
            _collect_pb_strings_recursive(payload, out_uuids, out_titles, depth + 1)
        return

    # 2. 叶子节点：尝试解码为 UTF-8 字符串（并兼容 UnifiedStateSync 内层 Base64 嵌套 Protobuf！）
    try:
        text = blob.decode("utf-8").strip()
    except UnicodeDecodeError:
        return

    if UUID_EXACT_RE.match(text):
        out_uuids.append(text.lower())
        return

    # 检查是否是内层 Base64 编码的 Protobuf 消息（如 UnifiedStateSync 中 value 为 base64 字符串）
    if len(text) >= 16 and " " not in text and all(ord(c) < 128 for c in text) and B64_CAND_RE.match(text):
        try:
            pad_len = (-len(text)) % 4
            padded = text + ("=" * pad_len)
            inner_bytes = base64.b64decode(padded)
            if inner_bytes and _iter_pb_fields(inner_bytes):
                _collect_pb_strings_recursive(inner_bytes, out_uuids, out_titles, depth + 1)
                return
        except Exception:
            pass

    if _is_plausible_agy_title(text):
        out_titles.append(text)


def decode_protobuf_uuid_titles(raw_val: Any) -> Dict[str, str]:
    """从 Antigravity state.vscdb (Base64/JSON) 或 .pb 二进制块中提取 {conv_uuid: sidebar_title}"""
    mapping = {}  # type: Dict[str, str]
    if not raw_val:
        return mapping

    raw_bytes = None  # type: Optional[bytes]
    if isinstance(raw_val, bytes):
        # 可能是 UTF-8 的 JSON 或 Base64，也可能是直接的二进制 Protobuf
        try:
            as_str = raw_val.decode("utf-8").strip()
            raw_val = as_str
        except UnicodeDecodeError:
            raw_bytes = raw_val

    if isinstance(raw_val, str):
        s = raw_val.strip()
        if not s:
            return mapping
        if s.startswith(("{", "[")):
            try:
                jobj = json.loads(s)
                if isinstance(jobj, dict):
                    for k, v in jobj.items():
                        if UUID_EXACT_RE.match(str(k)):
                            if isinstance(v, str) and _is_plausible_agy_title(v):
                                mapping[str(k).lower()] = v.strip()
                            elif isinstance(v, dict):
                                t = v.get("title") or v.get("summary") or v.get("name")
                                if isinstance(t, str) and _is_plausible_agy_title(t):
                                    mapping[str(k).lower()] = t.strip()
                            elif isinstance(v, str):
                                sub_u, sub_t = [], []  # type: List[str], List[str]
                                _collect_pb_strings_recursive(v.encode("utf-8"), sub_u, sub_t)
                                if sub_t:
                                    mapping[str(k).lower()] = sub_t[0]
                    if mapping:
                        return mapping
            except Exception:
                pass

        try:
            pad_len = (-len(s)) % 4
            raw_bytes = base64.b64decode(s + ("=" * pad_len))
        except Exception:
            return mapping

    if not raw_bytes:
        return mapping

    top_fields = _iter_pb_fields(raw_bytes)
    if not top_fields:
        return mapping

    for _fno, _wt, entry_blob in top_fields:
        uuids = []  # type: List[str]
        titles = []  # type: List[str]
        _collect_pb_strings_recursive(entry_blob, uuids, titles, depth=0)
        if uuids and titles:
            mapping[uuids[0]] = titles[0]

    return mapping


def _local_day_start_ts(now: float) -> float:
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst))


def _dedup_existing_dirs(candidates: List[str]) -> List[str]:
    result = []
    seen = set()  # type: Set[str]
    for p in candidates:
        if not p:
            continue
        expanded = os.path.abspath(os.path.expanduser(p))
        norm = os.path.normcase(expanded)
        if norm in seen:
            continue
        try:
            if os.path.isdir(expanded):
                seen.add(norm)
                result.append(expanded)
        except Exception:
            continue
    return result


def _actual_file_signature(file_path: str) -> Optional[Tuple[float, int]]:
    """获取文件最新签名；在 Windows 上用二进制流 seek(0, 2) 获取真实实时字节长度，绕过目录项缓存滞后"""
    try:
        st = os.stat(file_path)
        real_size = st.st_size
        # 对最近可能活跃的文件，用底层文件流测量真实末端位置
        if time.time() - st.st_mtime < 14400:
            try:
                with open(file_path, "rb") as bf:
                    bf.seek(0, os.SEEK_END)
                    real_size = bf.tell()
            except Exception:
                pass
        return (st.st_mtime, real_size)
    except Exception:
        return None


class LocalAIScanner(object):
    """本地多平台 AI 会话及额度活跃度实时扫描器"""

    def __init__(self) -> None:
        self._file_cache = {}  # type: Dict[str, Tuple[float, int, Dict[str, Any]]]

    def clear_cache(self) -> None:
        self._file_cache.clear()

    # ------------------------------------------------------------------
    # 四大工具目录自动探测
    # ------------------------------------------------------------------
    def discover_antigravity_dirs(self, extra_dirs: Optional[List[str]] = None) -> List[str]:
        home = os.path.expanduser("~")
        candidates = [os.path.join(home, ".gemini", "antigravity", "brain")]
        if extra_dirs:
            candidates.extend(extra_dirs)
        return _dedup_existing_dirs(candidates)

    def discover_codex_dirs(self, extra_dirs: Optional[List[str]] = None) -> List[str]:
        home = os.path.expanduser("~")
        local_app = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        roaming_app = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")

        candidates = [
            os.path.join(home, ".codex"),
            os.path.join(roaming_app, "Codex"),
            os.path.join(roaming_app, "OpenAI", "Codex"),
        ]
        codex_env = os.environ.get("CODEX_HOME")
        if codex_env:
            candidates.insert(0, codex_env)

        pkg_pattern = os.path.join(local_app, "Packages", "OpenAI.Codex_*")
        try:
            for pkg_dir in glob.glob(pkg_pattern):
                candidates.extend(
                    [
                        os.path.join(pkg_dir, "LocalCache", "Roaming", ".codex"),
                        os.path.join(pkg_dir, "LocalCache", "Roaming", "Codex"),
                        os.path.join(pkg_dir, "LocalCache", "Local", ".codex"),
                        os.path.join(pkg_dir, "LocalState"),
                        os.path.join(pkg_dir, "RoamingState"),
                    ]
                )
        except Exception:
            pass

        if extra_dirs:
            candidates.extend(extra_dirs)
        return _dedup_existing_dirs(candidates)

    def discover_claude_dirs(self, extra_dirs: Optional[List[str]] = None) -> List[str]:
        home = os.path.expanduser("~")
        roaming_app = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        candidates = [
            os.path.join(home, ".claude"),
            os.path.join(roaming_app, "Claude"),
        ]
        claude_env = os.environ.get("CLAUDE_CONFIG_DIR")
        if claude_env:
            candidates.insert(0, claude_env)
        if extra_dirs:
            candidates.extend(extra_dirs)
        return _dedup_existing_dirs(candidates)

    def discover_deepseek_dirs(self, extra_dirs: Optional[List[str]] = None) -> List[str]:
        home = os.path.expanduser("~")
        roaming_app = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        local_app = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        candidates = []  # type: List[str]
        dsh_env = os.environ.get("DSH_HOME") or os.environ.get("DEEPSEEK_HARNESS_HOME")
        if dsh_env:
            candidates.append(dsh_env)
        candidates.extend(
            [
                os.path.join(home, ".dsh"),
                os.path.join(home, ".deepseek-harness"),
                os.path.join(home, ".deepseek"),
                os.path.join(home, ".config", "dsh"),
                os.path.join(home, ".config", "deepseek-harness"),
                os.path.join(roaming_app, "dsh"),
                os.path.join(roaming_app, "deepseek-harness"),
                os.path.join(local_app, "dsh"),
                os.path.join(local_app, "deepseek-harness"),
            ]
        )
        if extra_dirs:
            candidates.extend(extra_dirs)
        return _dedup_existing_dirs(candidates)

    # ------------------------------------------------------------------
    # 主扫描入口
    # ------------------------------------------------------------------
    def scan_all(
        self,
        extra_codex_dirs: Optional[List[str]] = None,
        extra_agy_dirs: Optional[List[str]] = None,
        extra_claude_dirs: Optional[List[str]] = None,
        extra_deepseek_dirs: Optional[List[str]] = None,
        agy_window_hours: float = 5.0,
        codex_window_hours: float = 5.0,
        claude_window_hours: float = 5.0,
        deepseek_window_hours: float = 24.0,
        enabled_providers: Optional[Set[str]] = None,
        force_refresh: bool = False,
        max_sessions: int = 80,
    ) -> Dict[str, Any]:
        if force_refresh:
            self._file_cache.clear()

        now = time.time()
        day_start = _local_day_start_ts(now)

        agy_dirs = self.discover_antigravity_dirs(extra_agy_dirs)
        codex_dirs = self.discover_codex_dirs(extra_codex_dirs)
        claude_dirs = self.discover_claude_dirs(extra_claude_dirs)
        deepseek_dirs = self.discover_deepseek_dirs(extra_deepseek_dirs)

        agy_sessions, agy_stats = self._scan_antigravity(
            agy_dirs, now, day_start, now - max(agy_window_hours, 0.25) * 3600.0
        )
        codex_sessions, codex_stats, codex_rl = self._scan_codex(
            codex_dirs, now, day_start, now - max(codex_window_hours, 0.25) * 3600.0
        )
        claude_sessions, claude_stats = self._scan_claude(
            claude_dirs, now, day_start, now - max(claude_window_hours, 0.25) * 3600.0
        )
        deepseek_sessions, deepseek_stats = self._scan_deepseek_harness(
            deepseek_dirs, now, day_start, now - max(deepseek_window_hours, 0.25) * 3600.0
        )

        all_sessions = []  # type: List[Dict[str, Any]]
        for p_id, s_list in (
            ("codex", codex_sessions),
            ("antigravity", agy_sessions),
            ("claude_code", claude_sessions),
            ("deepseek_harness", deepseek_sessions),
        ):
            if enabled_providers is None or p_id in enabled_providers:
                all_sessions.extend(s_list)

        all_sessions.sort(key=lambda s: float(s.get("updated_at") or 0), reverse=True)
        if len(all_sessions) > max_sessions:
            all_sessions = all_sessions[:max_sessions]

        has_ds_env = bool(os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DSH_HOME"))

        return {
            "scanned_at": now,
            "sessions": all_sessions,
            "antigravity_stats": agy_stats,
            "codex_stats": codex_stats,
            "claude_stats": claude_stats,
            "deepseek_stats": deepseek_stats,
            "codex_rate_limit": codex_rl,
            "diagnostics": {
                "antigravity_dirs": agy_dirs,
                "codex_dirs": codex_dirs,
                "claude_dirs": claude_dirs,
                "deepseek_dirs": deepseek_dirs,
                "antigravity_count": len(agy_sessions),
                "codex_count": len(codex_sessions),
                "claude_count": len(claude_sessions),
                "deepseek_count": len(deepseek_sessions),
                "detected": {
                    "codex": bool(codex_dirs),
                    "antigravity": bool(agy_dirs),
                    "claude_code": bool(claude_dirs),
                    "deepseek_harness": bool(deepseek_dirs) or has_ds_env,
                },
            },
        }

    # ------------------------------------------------------------------
    # 1. Antigravity 会话与活跃度解析
    # ------------------------------------------------------------------
    def _scan_antigravity(
        self,
        brain_dirs: List[str],
        now: float,
        day_start: float,
        win_start: float,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        sessions = []  # type: List[Dict[str, Any]]
        today_steps = 0
        window_steps = 0
        today_tokens = 0
        window_tokens = 0
        active_count = 0
        recent_step_ts = []  # type: List[float]

        # 先从 Antigravity 全局 UI 索引 (state.vscdb trajectorySummaries & agyhub_summaries_proto.pb) 读取官方会话标题
        sidebar_titles = self._read_antigravity_sidebar_titles(brain_dirs)

        for brain_dir in brain_dirs:
            try:
                entries = os.listdir(brain_dir)
            except Exception:
                continue

            for conv_id in entries:
                if conv_id.startswith(".") or conv_id.lower() == "tempmediastorage":
                    continue
                conv_dir = os.path.join(brain_dir, conv_id)
                if not os.path.isdir(conv_dir):
                    continue

                log_dir = os.path.join(conv_dir, ".system_generated", "logs")
                transcript_path = os.path.join(log_dir, "transcript.jsonl")
                if not os.path.isfile(transcript_path):
                    transcript_path = os.path.join(log_dir, "transcript_full.jsonl")
                if not os.path.isfile(transcript_path):
                    continue

                parsed = self._parse_agy_transcript_cached(transcript_path, conv_id, conv_dir)
                if not parsed:
                    continue

                for step_ts, tok in parsed.get("step_events", []):
                    if step_ts >= day_start:
                        today_steps += 1
                        today_tokens += tok
                    if step_ts >= win_start:
                        window_steps += 1
                        window_tokens += tok
                        recent_step_ts.append(step_ts)

                status, status_detail = self._eval_agy_live_status(parsed, now)
                if status == "running":
                    active_count += 1

                # 优先采用 Antigravity 侧边栏官方会话标题，其次采用 Artifact 标题 / 精炼主题名
                idx_title = sidebar_titles.get(conv_id.lower(), "")
                final_title = idx_title or parsed["title"]

                sessions.append(
                    {
                        "key": "agy:" + conv_id,
                        "id": conv_id,
                        "provider": "antigravity",
                        "provider_label": "Antigravity",
                        "title": final_title,
                        "last_prompt": parsed.get("last_prompt", ""),
                        "status": status,
                        "status_detail": status_detail,
                        "updated_at": parsed["updated_at"],
                        "created_at": parsed["created_at"],
                        "step_count": len(parsed.get("step_events", [])),
                        "total_tokens": parsed.get("total_tokens", 0),
                        "workspace": "",
                        "is_manual": False,
                    }
                )

        return sessions, {
            "today_steps": today_steps,
            "window_steps": window_steps,
            "today_tokens": today_tokens,
            "window_tokens": window_tokens,
            "recent_step_ts": recent_step_ts,
            "active_sessions": active_count,
            "total_sessions": len(sessions),
        }

    def _parse_agy_transcript_cached(
        self, file_path: str, conv_id: str, conv_dir: str
    ) -> Optional[Dict[str, Any]]:
        sig = _actual_file_signature(file_path)
        if not sig:
            return None

        cache_key = "agy_file:" + file_path
        cached = self._file_cache.get(cache_key)
        if cached and cached[0] == sig[0] and cached[1] == sig[1]:
            return cached[2]

        first_prompt_raw = ""
        last_prompt_clean = ""
        created_at = sig[0]
        updated_at = sig[0]
        total_tokens = 0
        step_events = []  # type: List[Tuple[float, int]]

        last_step_type = ""
        last_step_status = ""
        last_has_tool_calls = False
        last_has_ask_question = False

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue

                    step_ts = parse_timestamp(obj.get("created_at")) or sig[0]
                    if idx == 0:
                        created_at = step_ts
                    if step_ts > updated_at:
                        updated_at = step_ts

                    stype = str(obj.get("type") or "")
                    sstatus = str(obj.get("status") or "")

                    if stype == "USER_INPUT":
                        raw_c = str(obj.get("content") or "")
                        if not first_prompt_raw:
                            first_prompt_raw = raw_c
                        p_clean = clean_prompt_text(raw_c, max_len=90)
                        if p_clean:
                            last_prompt_clean = p_clean

                    if stype == "PLANNER_RESPONSE":
                        in_tok = int(obj.get("input_tokens") or 0)
                        out_tok = int(obj.get("output_tokens") or 0)
                        tok_sum = in_tok + out_tok
                        total_tokens += tok_sum
                        step_events.append((step_ts, tok_sum))

                    tcalls = obj.get("tool_calls")
                    has_tc = bool(isinstance(tcalls, list) and len(tcalls) > 0)
                    has_ask = False
                    if has_tc:
                        for tc in tcalls:
                            if isinstance(tc, dict) and tc.get("name") == "ask_question":
                                has_ask = True
                                break

                    last_step_type = stype
                    last_step_status = sstatus
                    last_has_tool_calls = has_tc
                    last_has_ask_question = has_ask
        except Exception:
            return None

        # 对话名称：优先采用会话目录下 Artifact 文档标题，否则从首条需求智能提炼简短主题名
        md_title = self._fallback_md_title(conv_dir)
        conv_title = (
            md_title
            or summarize_conversation_title(first_prompt_raw)
            or ("Antigravity · " + conv_id[:8])
        )

        data = {
            "title": conv_title,
            "last_prompt": last_prompt_clean,
            "created_at": created_at,
            "updated_at": updated_at,
            "total_tokens": total_tokens,
            "step_events": step_events,
            "last_step_type": last_step_type,
            "last_step_status": last_step_status,
            "last_has_tool_calls": last_has_tool_calls,
            "last_has_ask_question": last_has_ask_question,
        }
        self._file_cache[cache_key] = (sig[0], sig[1], data)
        return data

    def _fallback_md_title(self, conv_dir: str) -> str:
        for fname in ("task.md", "implementation_plan.md", "walkthrough.md"):
            fpath = os.path.join(conv_dir, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        for _ in range(10):
                            line = f.readline()
                            if not line:
                                break
                            s = line.strip()
                            if s.startswith("#"):
                                return clean_prompt_text(s.lstrip("#").strip(), max_len=32)
                except Exception:
                    pass
        return ""

    def _read_antigravity_sidebar_titles(self, brain_dirs: List[str]) -> Dict[str, str]:
        """
        从 Antigravity 客户端真实的侧边栏状态库中读取官方会话标题：
        1. %APPDATA%\\Antigravity*\\User\\globalStorage\\state.vscdb -> ItemTable (trajectorySummaries)
        2. ~/.gemini/antigravity/ 下的 agyhub_summaries_proto.pb 等摘要缓存
        """
        titles_map = {}  # type: Dict[str, str]
        roaming = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")

        # 1. 扫描可能存在的 .pb 摘要索引文件
        pb_candidates = []  # type: List[str]
        for bdir in brain_dirs:
            agy_root = os.path.dirname(bdir.rstrip("\\/"))
            if os.path.isdir(agy_root):
                for pat in ("*summaries*.pb", os.path.join("daemon", "*summaries*.pb")):
                    try:
                        pb_candidates.extend(glob.glob(os.path.join(agy_root, pat)))
                    except Exception:
                        pass

        for pb_path in pb_candidates:
            try:
                st = os.stat(pb_path)
                ckey = "agy_pb:" + pb_path
                cached = self._file_cache.get(ckey)
                if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                    titles_map.update(cached[2])
                    continue
                with open(pb_path, "rb") as f:
                    raw_pb = f.read()
                parsed_map = decode_protobuf_uuid_titles(raw_pb)
                self._file_cache[ckey] = (st.st_mtime, st.st_size, parsed_map)
                titles_map.update(parsed_map)
            except Exception:
                pass

        # 2. WAL 安全快照读取 state.vscdb 中的 trajectorySummaries
        vscdb_candidates = []  # type: List[str]
        for app_folder in (
            "Antigravity",
            "Antigravity IDE",
            "Antigravity 2.0",
            os.path.join("Google", "Antigravity"),
        ):
            p = os.path.join(roaming, app_folder, "User", "globalStorage", "state.vscdb")
            if os.path.isfile(p):
                vscdb_candidates.append(p)

        for db_path in vscdb_candidates:
            wal_path = db_path + "-wal"
            shm_path = db_path + "-shm"
            try:
                st_main = os.stat(db_path)
                wal_m, wal_s = (0.0, 0)
                if os.path.isfile(wal_path):
                    sw = os.stat(wal_path)
                    wal_m, wal_s = (sw.st_mtime, sw.st_size)
                sig_m = max(st_main.st_mtime, wal_m)
                sig_s = st_main.st_size + wal_s
            except Exception:
                continue

            ckey = "agy_vscdb:" + db_path
            cached = self._file_cache.get(ckey)
            if cached and cached[0] == sig_m and cached[1] == sig_s:
                titles_map.update(cached[2])
                continue

            snap_dir = None
            conn = None
            db_map = {}  # type: Dict[str, str]
            try:
                snap_dir = tempfile.mkdtemp(prefix="aiboard_vscdb_")
                snap_db = os.path.join(snap_dir, "state.vscdb")
                shutil.copy2(db_path, snap_db)
                if os.path.isfile(wal_path):
                    shutil.copy2(wal_path, snap_db + "-wal")
                if os.path.isfile(shm_path):
                    shutil.copy2(shm_path, snap_db + "-shm")

                conn = sqlite3.connect(snap_db, timeout=0.5)
                cur = conn.cursor()
                cur.execute(
                    "SELECT value FROM ItemTable WHERE key LIKE '%trajectorySummaries%' OR key LIKE '%conversationSummaries%'"
                )
                for (val,) in cur.fetchall():
                    db_map.update(decode_protobuf_uuid_titles(val))
                conn.close()
                conn = None
                self._file_cache[ckey] = (sig_m, sig_s, db_map)
                titles_map.update(db_map)
            except Exception:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            finally:
                if snap_dir and os.path.isdir(snap_dir):
                    shutil.rmtree(snap_dir, ignore_errors=True)

        return titles_map

    def _eval_agy_live_status(self, parsed: Dict[str, Any], now: float) -> Tuple[str, str]:
        age_sec = max(0.0, now - float(parsed.get("updated_at") or 0))
        ltype = parsed.get("last_step_type", "")
        lstatus = parsed.get("last_step_status", "")
        has_tc = parsed.get("last_has_tool_calls", False)
        has_ask = parsed.get("last_has_ask_question", False)

        if lstatus == "ERROR":
            return "error", "执行中断"
        if has_ask:
            return "waiting", "等待确认选项"
        if lstatus == "RUNNING" and age_sec < 600:
            return "running", "工具运行中"
        if (ltype in ("USER_INPUT", "GENERIC") or (ltype == "PLANNER_RESPONSE" and has_tc)) and age_sec < 240:
            return "running", "AI 正在处理"
        if ltype == "PLANNER_RESPONSE" and not has_tc:
            return "completed", "已完成回复"
        if age_sec < 90:
            return "running", "刚刚活跃"
        if has_tc or ltype == "GENERIC":
            return "paused", "待继续"
        return "completed", "已就绪"

    # ------------------------------------------------------------------
    # 2. OpenAI Codex 桌面端 / CLI 会话与额度解析 (支持 WAL 实时合并快照)
    # ------------------------------------------------------------------
    def _scan_codex(
        self,
        codex_dirs: List[str],
        now: float,
        day_start: float,
        win_start: float,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[Dict[str, Any]]]:
        sessions_by_id = {}  # type: Dict[str, Dict[str, Any]]
        thread_meta_map = {}  # type: Dict[str, Dict[str, Any]]
        session_index_titles = {}  # type: Dict[str, str]
        rollout_to_tid = {}  # type: Dict[str, str]

        today_steps = 0
        window_steps = 0
        today_tokens = 0
        window_tokens = 0
        recent_step_ts = []  # type: List[float]
        latest_rate_limit = None  # type: Optional[Dict[str, Any]]

        # 1. 读取 session_index.jsonl (存储官方/自定义会话标题 thread_name) 与 SQLite WAL 快照
        for cdir in codex_dirs:
            idx_map = self._read_codex_session_index(cdir)
            session_index_titles.update(idx_map)

            db_threads = self._read_codex_sqlite_threads_wal_safe(cdir)
            for tid, meta in db_threads.items():
                thread_meta_map[tid] = meta
                rpath = meta.get("rollout_path")
                if rpath:
                    rollout_to_tid[os.path.normcase(os.path.abspath(rpath))] = tid

        # 2. 收集全部会话 JSONL 文件
        jsonl_files = []  # type: List[str]
        seen_files = set()  # type: Set[str]

        for cdir in codex_dirs:
            for sub in ("sessions", "archived_sessions"):
                sub_dir = os.path.join(cdir, sub)
                if not os.path.isdir(sub_dir):
                    continue
                for root, _dirs, files in os.walk(sub_dir):
                    for fn in files:
                        if not fn.lower().endswith(".jsonl"):
                            continue
                        if fn.lower() in SENSITIVE_FILENAMES:
                            continue
                        full_p = os.path.abspath(os.path.join(root, fn))
                        norm_p = os.path.normcase(full_p)
                        if norm_p not in seen_files:
                            seen_files.add(norm_p)
                            jsonl_files.append(full_p)

        for rpath_norm, tid in rollout_to_tid.items():
            raw_rpath = thread_meta_map[tid].get("rollout_path", "")
            if raw_rpath and rpath_norm not in seen_files and os.path.isfile(raw_rpath):
                seen_files.add(rpath_norm)
                jsonl_files.append(os.path.abspath(raw_rpath))

        for fpath in jsonl_files:
            parsed = self._parse_codex_jsonl_cached(fpath)
            if not parsed:
                continue

            norm_fp = os.path.normcase(fpath)
            sid = parsed.get("session_id") or rollout_to_tid.get(norm_fp) or ""
            if not sid:
                m_uuid = UUID_SEARCH_RE.findall(os.path.basename(fpath))
                sid = m_uuid[-1] if m_uuid else os.path.splitext(os.path.basename(fpath))[0]
            sid_low = sid.lower()
            db_meta = thread_meta_map.get(sid) or thread_meta_map.get(sid_low) or {}

            for ev_ts, tok in parsed.get("step_events", []):
                if ev_ts >= day_start:
                    today_steps += 1
                    today_tokens += tok
                if ev_ts >= win_start:
                    window_steps += 1
                    window_tokens += tok
                    recent_step_ts.append(ev_ts)

            rl = parsed.get("rate_limit")
            if rl:
                if latest_rate_limit is None or rl["event_ts"] >= latest_rate_limit["event_ts"]:
                    latest_rate_limit = dict(rl)

            cwd = db_meta.get("cwd") or parsed.get("cwd") or ""
            workspace_name = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
            first_p = str(parsed.get("first_prompt") or db_meta.get("first_user_message") or "")

            # 会话标题优先级：
            # 1) session_index.jsonl 中的 thread_name (客户端侧边栏正式名称 / 重命名)
            # 2) rollout 日志中的 thread_name_updated 事件标题
            # 3) SQLite threads.title（仅当它确实是独立标题而非直接拷贝的原始长 prompt 时！）
            # 4) 从首句意图智能浓缩出的简短主题词
            idx_name = session_index_titles.get(sid) or session_index_titles.get(sid_low) or ""
            meta_name = str(parsed.get("meta_title") or "").strip()
            db_name = str(db_meta.get("title") or "").strip()

            chosen_official = ""
            for cand in (idx_name, meta_name, db_name):
                if cand and _is_genuine_title(cand, first_p):
                    chosen_official = clean_prompt_text(cand, max_len=36)
                    break

            conv_title = (
                chosen_official
                or parsed.get("auto_title")
                or summarize_conversation_title(db_name or first_p, workspace=workspace_name)
                or (("Codex · " + workspace_name) if workspace_name else ("Codex · " + sid[:8]))
            )
            last_prompt = str(parsed.get("last_prompt") or "")

            updated_at = max(
                float(parsed.get("updated_at") or 0), float(db_meta.get("updated_at") or 0)
            )
            status, status_detail = self._eval_codex_live_status(parsed, updated_at, now)

            sessions_by_id[sid] = {
                "key": "codex:" + sid,
                "id": sid,
                "provider": "codex",
                "provider_label": "Codex",
                "title": conv_title,
                "last_prompt": last_prompt,
                "status": status,
                "status_detail": status_detail,
                "updated_at": updated_at,
                "created_at": float(parsed.get("created_at") or updated_at),
                "step_count": len(parsed.get("step_events", [])),
                "total_tokens": max(int(parsed.get("total_tokens", 0)), int(db_meta.get("tokens_used") or 0)),
                "workspace": workspace_name,
                "is_manual": False,
            }

        # 补充仅存在于 SQLite threads 表中的新线程
        for tid, meta in thread_meta_map.items():
            if tid in sessions_by_id or meta.get("archived"):
                continue
            upd = float(meta.get("updated_at") or 0)
            age = max(0.0, now - upd)
            st_code = "running" if age < 180 else "completed"
            st_desc = "活跃线程" if st_code == "running" else "已保存会话"
            if upd >= win_start:
                window_steps += 1
                recent_step_ts.append(upd)
            if upd >= day_start:
                today_steps += 1
            cwd = meta.get("cwd") or ""
            ws_name = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
            raw_db_t = str(meta.get("title") or "").strip()
            raw_first_m = str(meta.get("first_user_message") or "").strip()
            idx_t = session_index_titles.get(tid) or session_index_titles.get(tid.lower()) or ""
            if idx_t and _is_genuine_title(idx_t, raw_first_m):
                t_final = clean_prompt_text(idx_t, max_len=36)
            elif raw_db_t and _is_genuine_title(raw_db_t, raw_first_m):
                t_final = clean_prompt_text(raw_db_t, max_len=36)
            else:
                t_final = summarize_conversation_title(raw_db_t or raw_first_m, workspace=ws_name)
            sessions_by_id[tid] = {
                "key": "codex:" + tid,
                "id": tid,
                "provider": "codex",
                "provider_label": "Codex",
                "title": t_final or (("Codex · " + ws_name) if ws_name else ("Codex · " + tid[:8])),
                "last_prompt": clean_prompt_text(raw_first_m or raw_db_t, max_len=90),
                "status": st_code,
                "status_detail": st_desc,
                "updated_at": upd,
                "created_at": float(meta.get("created_at") or upd),
                "step_count": 1,
                "total_tokens": int(meta.get("tokens_used") or 0),
                "workspace": ws_name,
                "is_manual": False,
            }

        if not sessions_by_id:
            for cdir in codex_dirs:
                hist_path = os.path.join(cdir, "history.jsonl")
                if os.path.isfile(hist_path):
                    for item in self._parse_codex_history_fallback(hist_path):
                        sessions_by_id[item["id"]] = item

        if latest_rate_limit:
            p_reset = latest_rate_limit.get("primary_reset_at")
            if p_reset and p_reset <= now:
                latest_rate_limit["primary_remaining_pct"] = 100.0
            s_reset = latest_rate_limit.get("secondary_reset_at")
            if s_reset and s_reset <= now:
                latest_rate_limit["secondary_remaining_pct"] = 100.0

        session_list = list(sessions_by_id.values())
        active_cnt = sum(1 for s in session_list if s.get("status") == "running")

        return session_list, {
            "today_steps": today_steps,
            "window_steps": window_steps,
            "today_tokens": today_tokens,
            "window_tokens": window_tokens,
            "recent_step_ts": recent_step_ts,
            "active_sessions": active_cnt,
            "total_sessions": len(session_list),
        }, latest_rate_limit

    def _read_codex_session_index(self, codex_dir: str) -> Dict[str, str]:
        """读取 ~/.codex/session_index.jsonl 中的正式会话标题 (thread_name)"""
        idx_path = os.path.join(codex_dir, "session_index.jsonl")
        if not os.path.isfile(idx_path):
            return {}
        sig = _actual_file_signature(idx_path)
        if not sig:
            return {}
        ckey = "codex_sidx:" + idx_path
        cached = self._file_cache.get(ckey)
        if cached and cached[0] == sig[0] and cached[1] == sig[1]:
            return cached[2]

        out = {}  # type: Dict[str, str]
        try:
            with open(idx_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    s = line.strip()
                    if not s:
                        continue
                    try:
                        obj = json.loads(s)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    tid = str(obj.get("id") or obj.get("thread_id") or obj.get("session_id") or "").strip()
                    tname = str(obj.get("thread_name") or obj.get("title") or obj.get("name") or "").strip()
                    if tid and tname:
                        out[tid] = tname
                        out[tid.lower()] = tname
        except Exception:
            return {}

        self._file_cache[ckey] = (sig[0], sig[1], out)
        return out

    def _read_codex_sqlite_threads_wal_safe(self, codex_dir: str) -> Dict[str, Dict[str, Any]]:
        """
        将 SQLite 主文件与 .sqlite-wal / .sqlite-shm 一起复制到临时目录再查询，
        彻底解决 Codex 桌面端 WAL 未刷回主库导致读不到最新对话与标题的问题！
        """
        result = {}  # type: Dict[str, Dict[str, Any]]
        db_candidates = []  # type: List[str]
        try:
            for fn in os.listdir(codex_dir):
                if fn.lower().endswith((".sqlite", ".db", ".sqlite3")):
                    db_candidates.append(os.path.join(codex_dir, fn))
            sqlite_sub = os.path.join(codex_dir, "sqlite")
            if os.path.isdir(sqlite_sub):
                for fn in os.listdir(sqlite_sub):
                    if fn.lower().endswith((".sqlite", ".db", ".sqlite3")):
                        db_candidates.append(os.path.join(sqlite_sub, fn))
        except Exception:
            return result

        for db_path in db_candidates:
            # 组合主库与 -wal 的状态签名做轻量缓存，只要 -wal 字节数或时间一变立即重新快照
            wal_path = db_path + "-wal"
            shm_path = db_path + "-shm"
            try:
                st_main = os.stat(db_path)
                wal_mtime, wal_size = (0.0, 0)
                if os.path.isfile(wal_path):
                    st_wal = os.stat(wal_path)
                    wal_mtime, wal_size = (st_wal.st_mtime, st_wal.st_size)
                db_sig_mtime = max(st_main.st_mtime, wal_mtime)
                db_sig_size = st_main.st_size + wal_size
            except Exception:
                continue

            cache_key = "codex_db:" + db_path
            cached = self._file_cache.get(cache_key)
            if cached and cached[0] == db_sig_mtime and cached[1] == db_sig_size:
                result.update(cached[2])
                continue

            snap_dir = None
            conn = None
            db_records = {}  # type: Dict[str, Dict[str, Any]]
            try:
                snap_dir = tempfile.mkdtemp(prefix="aiboard_dbsnap_")
                base_name = os.path.basename(db_path)
                snap_db = os.path.join(snap_dir, base_name)
                shutil.copy2(db_path, snap_db)
                if os.path.isfile(wal_path):
                    shutil.copy2(wal_path, snap_db + "-wal")
                if os.path.isfile(shm_path):
                    shutil.copy2(shm_path, snap_db + "-shm")

                conn = sqlite3.connect(snap_db, timeout=0.5)
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='threads'")
                if cur.fetchone():
                    cur.execute("PRAGMA table_info(threads)")
                    cols = {row[1] for row in cur.fetchall()}
                    if "id" in cols:
                        want_cols = [
                            c
                            for c in (
                                "id",
                                "title",
                                "first_user_message",
                                "cwd",
                                "rollout_path",
                                "updated_at",
                                "created_at",
                                "archived",
                                "tokens_used",
                            )
                            if c in cols
                        ]
                        order_clause = " ORDER BY updated_at DESC" if "updated_at" in cols else ""
                        cur.execute(
                            "SELECT {} FROM threads{} LIMIT 120".format(", ".join(want_cols), order_clause)
                        )
                        for row in cur.fetchall():
                            rec = dict(zip(want_cols, row))
                            tid = str(rec.get("id") or "")
                            if not tid:
                                continue
                            db_records[tid] = {
                                "id": tid,
                                "title": str(rec.get("title") or ""),
                                "first_user_message": str(rec.get("first_user_message") or ""),
                                "cwd": str(rec.get("cwd") or ""),
                                "rollout_path": str(rec.get("rollout_path") or ""),
                                "updated_at": parse_timestamp(rec.get("updated_at")) or 0.0,
                                "created_at": parse_timestamp(rec.get("created_at")) or 0.0,
                                "archived": bool(rec.get("archived")),
                                "tokens_used": int(rec.get("tokens_used") or 0),
                            }
                conn.close()
                conn = None
                self._file_cache[cache_key] = (db_sig_mtime, db_sig_size, db_records)
                result.update(db_records)
            except Exception:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            finally:
                if snap_dir and os.path.isdir(snap_dir):
                    shutil.rmtree(snap_dir, ignore_errors=True)

        return result

    def _parse_codex_jsonl_cached(self, file_path: str) -> Optional[Dict[str, Any]]:
        sig = _actual_file_signature(file_path)
        if not sig:
            return None

        cache_key = "codex_file:" + file_path
        cached = self._file_cache.get(cache_key)
        if cached and cached[0] == sig[0] and cached[1] == sig[1]:
            return cached[2]

        session_id = ""
        cwd = ""
        meta_title = ""
        first_prompt_raw = ""
        last_prompt_clean = ""
        created_at = sig[0]
        updated_at = sig[0]
        total_tokens = 0
        prev_cum_tokens = 0
        step_events = []  # type: List[Tuple[float, int]]
        rate_limit = None  # type: Optional[Dict[str, Any]]
        last_signal = ""

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue

                    ev_ts = (
                        parse_timestamp(obj.get("timestamp"))
                        or parse_timestamp(obj.get("created_at"))
                        or sig[0]
                    )
                    if idx == 0:
                        created_at = ev_ts
                    if ev_ts > updated_at:
                        updated_at = ev_ts

                    top_type = str(obj.get("type") or "")
                    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}

                    if top_type in ("session_meta", "thread_name_updated"):
                        session_id = str(payload.get("id") or obj.get("id") or session_id)
                        cwd = str(payload.get("cwd") or obj.get("cwd") or cwd)
                        t_cand = payload.get("title") or payload.get("thread_name") or obj.get("title")
                        if t_cand:
                            meta_title = str(t_cand)
                        continue
                    if idx == 0 and obj.get("id") and not top_type:
                        session_id = str(obj.get("id"))
                        cwd = str(obj.get("cwd") or cwd)

                    if top_type == "event_msg":
                        ptype = str(payload.get("type") or "")
                        if ptype == "user_message":
                            msg = str(payload.get("message") or "")
                            if not first_prompt_raw:
                                first_prompt_raw = msg
                            p_clean = clean_prompt_text(msg, max_len=90)
                            if p_clean:
                                last_prompt_clean = p_clean
                            last_signal = "user"
                        elif ptype in ("thread_name_updated", "session_configured"):
                            t_cand = payload.get("thread_name") or payload.get("title")
                            if t_cand:
                                meta_title = str(t_cand)
                        elif ptype in ("task_started", "turn_started"):
                            last_signal = "tool_call"
                        elif ptype == "agent_message":
                            last_signal = "assistant"
                            step_events.append((ev_ts, 0))
                        elif ptype in ("task_complete", "turn_complete"):
                            last_signal = "complete"
                        elif ptype == "turn_aborted":
                            last_signal = "aborted"
                        elif ptype in ("exec_approval_request", "apply_patch_approval_request"):
                            last_signal = "approval"
                        elif ptype == "error":
                            last_signal = "error"
                        elif ptype == "token_count":
                            info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
                            tot_u = info.get("total_token_usage") if isinstance(info.get("total_token_usage"), dict) else {}
                            last_u = info.get("last_token_usage") if isinstance(info.get("last_token_usage"), dict) else {}
                            cum_tok = int(tot_u.get("total_tokens") or 0)
                            delta_tok = int(last_u.get("total_tokens") or 0)
                            if cum_tok > 0:
                                if delta_tok <= 0 and cum_tok >= prev_cum_tokens:
                                    delta_tok = cum_tok - prev_cum_tokens
                                prev_cum_tokens = cum_tok
                                total_tokens = max(total_tokens, cum_tok)
                            if delta_tok > 0:
                                step_events.append((ev_ts, delta_tok))

                            rl_raw = payload.get("rate_limits") or info.get("rate_limits")
                            parsed_rl = self._extract_codex_rate_limit(rl_raw, ev_ts)
                            if parsed_rl:
                                rate_limit = parsed_rl
                        continue

                    item = payload if top_type == "response_item" else obj
                    itype = str(item.get("type") or "")
                    role = str(item.get("role") or "")

                    if role == "user":
                        txt = self._extract_content_text(item.get("content"))
                        cand = clean_prompt_text(txt, max_len=90)
                        if cand:
                            if not first_prompt_raw:
                                first_prompt_raw = txt
                            last_prompt_clean = cand
                        last_signal = "user"
                    elif role == "assistant":
                        last_signal = "assistant"
                        step_events.append((ev_ts, 0))
                    elif itype in (
                        "function_call",
                        "custom_tool_call",
                        "local_shell_call",
                        "function_call_output",
                        "custom_tool_call_output",
                    ):
                        last_signal = "tool_call"

                    rl_top = obj.get("rate_limits") or payload.get("rate_limits")
                    if isinstance(rl_top, dict):
                        parsed_rl = self._extract_codex_rate_limit(rl_top, ev_ts)
                        if parsed_rl:
                            rate_limit = parsed_rl
        except Exception:
            return None

        compact_steps = []  # type: List[Tuple[float, int]]
        for ts_val, tok_val in step_events:
            if tok_val > 0 or not compact_steps or abs(ts_val - compact_steps[-1][0]) > 2.0:
                compact_steps.append((ts_val, tok_val))

        ws_base = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
        auto_title = summarize_conversation_title(first_prompt_raw, workspace=ws_base)

        data = {
            "session_id": session_id,
            "cwd": cwd,
            "meta_title": meta_title,
            "auto_title": auto_title,
            "first_prompt": first_prompt_raw,
            "last_prompt": last_prompt_clean,
            "created_at": created_at,
            "updated_at": updated_at,
            "total_tokens": total_tokens,
            "step_events": compact_steps,
            "rate_limit": rate_limit,
            "last_signal": last_signal,
        }
        self._file_cache[cache_key] = (sig[0], sig[1], data)
        return data

    def _extract_content_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    btype = str(block.get("type") or "")
                    if btype in ("input_text", "text", "output_text"):
                        txt = str(block.get("text") or "")
                        if txt and not txt.lstrip().startswith("<environment_context"):
                            parts.append(txt)
            return "\n".join(parts)
        return ""

    def _extract_codex_rate_limit(self, rl_raw: Any, event_ts: float) -> Optional[Dict[str, Any]]:
        if not isinstance(rl_raw, dict):
            return None
        primary = rl_raw.get("primary")
        secondary = rl_raw.get("secondary")
        if not isinstance(primary, dict) and not isinstance(secondary, dict):
            return None

        out = {"event_ts": event_ts}  # type: Dict[str, Any]
        if isinstance(primary, dict) and primary.get("used_percent") is not None:
            used = float(primary.get("used_percent") or 0.0)
            out["primary_remaining_pct"] = max(0.0, min(100.0, 100.0 - used))
            out["primary_window_min"] = int(primary.get("window_minutes") or 300)
            reset_ts = parse_timestamp(primary.get("resets_at"))
            if not reset_ts and primary.get("resets_in_seconds") is not None:
                reset_ts = event_ts + float(primary.get("resets_in_seconds"))
            out["primary_reset_at"] = reset_ts

        if isinstance(secondary, dict) and secondary.get("used_percent") is not None:
            s_used = float(secondary.get("used_percent") or 0.0)
            out["secondary_remaining_pct"] = max(0.0, min(100.0, 100.0 - s_used))
            s_reset = parse_timestamp(secondary.get("resets_at"))
            if not s_reset and secondary.get("resets_in_seconds") is not None:
                s_reset = event_ts + float(secondary.get("resets_in_seconds"))
            out["secondary_reset_at"] = s_reset

        return out if len(out) > 1 else None

    def _eval_codex_live_status(
        self, parsed: Dict[str, Any], updated_at: float, now: float
    ) -> Tuple[str, str]:
        age_sec = max(0.0, now - updated_at)
        sig = parsed.get("last_signal", "")

        if sig == "error":
            return "error", "执行中断"
        if sig == "approval":
            return "waiting", "等待审批"
        if sig == "complete":
            return "completed", "已完成"
        if sig == "aborted":
            return "paused", "已中止"
        if sig in ("user", "tool_call") and age_sec < 240:
            return "running", "Agent 执行中"
        if sig == "assistant":
            return ("running", "输出回复中") if age_sec < 30 else ("completed", "已完成")
        if age_sec < 60:
            return "running", "刚刚活跃"
        if sig in ("user", "tool_call"):
            return "paused", "待继续"
        return "completed", "已就绪"

    def _parse_codex_history_fallback(self, hist_path: str) -> List[Dict[str, Any]]:
        grouped = {}  # type: Dict[str, Dict[str, Any]]
        try:
            with open(hist_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    sid = str(obj.get("session_id") or "")
                    if not sid:
                        continue
                    ts = parse_timestamp(obj.get("ts")) or 0.0
                    raw_txt = str(obj.get("text") or "")
                    p_clean = clean_prompt_text(raw_txt, max_len=90)
                    if sid not in grouped:
                        grouped[sid] = {
                            "key": "codex:" + sid,
                            "id": sid,
                            "provider": "codex",
                            "provider_label": "Codex",
                            "title": summarize_conversation_title(raw_txt) or ("Codex · " + sid[:8]),
                            "last_prompt": p_clean,
                            "status": "completed",
                            "status_detail": "历史记录",
                            "updated_at": ts,
                            "created_at": ts,
                            "step_count": 1,
                            "total_tokens": 0,
                            "workspace": "",
                            "is_manual": False,
                        }
                    else:
                        grouped[sid]["updated_at"] = max(grouped[sid]["updated_at"], ts)
                        grouped[sid]["step_count"] += 1
                        if p_clean:
                            grouped[sid]["last_prompt"] = p_clean
        except Exception:
            pass
        return list(grouped.values())

    # ------------------------------------------------------------------
    # 3. Claude Code 会话与活跃解析 (~/.claude/projects/**/*.jsonl)
    # ------------------------------------------------------------------
    def _scan_claude(
        self,
        claude_dirs: List[str],
        now: float,
        day_start: float,
        win_start: float,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        sessions = []  # type: List[Dict[str, Any]]
        today_steps = 0
        window_steps = 0
        today_tokens = 0
        window_tokens = 0
        active_count = 0
        recent_step_ts = []  # type: List[float]

        for cdir in claude_dirs:
            proj_root = os.path.join(cdir, "projects")
            if not os.path.isdir(proj_root):
                continue
            for root, _dirs, files in os.walk(proj_root):
                for fn in files:
                    lower = fn.lower()
                    if not lower.endswith(".jsonl") or lower.startswith("agent-"):
                        continue
                    if lower in SENSITIVE_FILENAMES:
                        continue
                    fpath = os.path.join(root, fn)
                    parsed = self._parse_claude_jsonl_cached(fpath)
                    if not parsed or not parsed.get("has_messages"):
                        continue

                    for ev_ts, tok in parsed.get("step_events", []):
                        if ev_ts >= day_start:
                            today_steps += 1
                            today_tokens += tok
                        if ev_ts >= win_start:
                            window_steps += 1
                            window_tokens += tok
                            recent_step_ts.append(ev_ts)

                    upd = float(parsed["updated_at"])
                    age = max(0.0, now - upd)
                    last_role = parsed.get("last_role", "")
                    has_tool = parsed.get("last_has_tool_use", False)
                    if (last_role == "user" or has_tool) and age < 240:
                        status, detail = "running", "Claude 执行中"
                        active_count += 1
                    elif age < 45:
                        status, detail = "running", "刚刚活跃"
                        active_count += 1
                    else:
                        status, detail = "completed", "已完成"

                    sid = parsed.get("session_id") or os.path.splitext(fn)[0]
                    cwd = parsed.get("cwd") or ""
                    ws_name = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
                    sessions.append(
                        {
                            "key": "claude:" + sid,
                            "id": sid,
                            "provider": "claude_code",
                            "provider_label": "Claude Code",
                            "title": parsed["title"] or ("Claude · " + (ws_name or sid[:8])),
                            "last_prompt": parsed.get("last_prompt", ""),
                            "status": status,
                            "status_detail": detail,
                            "updated_at": upd,
                            "created_at": parsed["created_at"],
                            "step_count": len(parsed.get("step_events", [])),
                            "total_tokens": parsed.get("total_tokens", 0),
                            "workspace": ws_name,
                            "is_manual": False,
                        }
                    )

        return sessions, {
            "today_steps": today_steps,
            "window_steps": window_steps,
            "today_tokens": today_tokens,
            "window_tokens": window_tokens,
            "recent_step_ts": recent_step_ts,
            "active_sessions": active_count,
            "total_sessions": len(sessions),
        }

    def _parse_claude_jsonl_cached(self, file_path: str) -> Optional[Dict[str, Any]]:
        sig = _actual_file_signature(file_path)
        if not sig:
            return None

        cache_key = "claude_file:" + file_path
        cached = self._file_cache.get(cache_key)
        if cached and cached[0] == sig[0] and cached[1] == sig[1]:
            return cached[2]

        session_id = ""
        cwd = ""
        summary_title = ""
        first_prompt_raw = ""
        last_prompt_clean = ""
        created_at = sig[0]
        updated_at = sig[0]
        total_tokens = 0
        step_events = []  # type: List[Tuple[float, int]]
        last_role = ""
        last_has_tool_use = False
        has_messages = False

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue

                    ev_ts = parse_timestamp(obj.get("timestamp")) or sig[0]
                    if idx == 0:
                        created_at = ev_ts
                    if ev_ts > updated_at:
                        updated_at = ev_ts

                    if obj.get("sessionId"):
                        session_id = str(obj["sessionId"])
                    if obj.get("cwd"):
                        cwd = str(obj["cwd"])

                    rec_type = str(obj.get("type") or "")
                    if rec_type in ("summary", "custom-title"):
                        s_txt = str(obj.get("summary") or obj.get("customTitle") or "")
                        if s_txt.strip():
                            summary_title = clean_prompt_text(s_txt, max_len=36)
                        continue

                    msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}

                    if rec_type == "user" and not obj.get("isMeta"):
                        has_messages = True
                        last_role = "user"
                        last_has_tool_use = False
                        txt = self._extract_content_text(msg.get("content"))
                        cand = clean_prompt_text(txt, max_len=90)
                        if cand:
                            if not first_prompt_raw:
                                first_prompt_raw = txt
                            last_prompt_clean = cand
                    elif rec_type == "assistant":
                        has_messages = True
                        last_role = "assistant"
                        usage = msg.get("usage") if isinstance(msg.get("usage"), dict) else {}
                        tok = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
                        total_tokens += tok
                        step_events.append((ev_ts, tok))
                        content = msg.get("content")
                        last_has_tool_use = bool(
                            isinstance(content, list)
                            and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
                        )
        except Exception:
            return None

        ws_base = os.path.basename(cwd.rstrip("\\/")) if cwd else ""
        conv_title = summary_title or summarize_conversation_title(first_prompt_raw, workspace=ws_base)

        data = {
            "session_id": session_id,
            "cwd": cwd,
            "title": conv_title,
            "last_prompt": last_prompt_clean,
            "created_at": created_at,
            "updated_at": updated_at,
            "total_tokens": total_tokens,
            "step_events": step_events,
            "last_role": last_role,
            "last_has_tool_use": last_has_tool_use,
            "has_messages": has_messages,
        }
        self._file_cache[cache_key] = (sig[0], sig[1], data)
        return data

    # ------------------------------------------------------------------
    # 4. DeepSeek Harness 会话与活跃解析 ($DSH_HOME / ~/.dsh)
    # ------------------------------------------------------------------
    def _scan_deepseek_harness(
        self,
        ds_dirs: List[str],
        now: float,
        day_start: float,
        win_start: float,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        sessions = []  # type: List[Dict[str, Any]]
        today_steps = 0
        window_steps = 0
        today_tokens = 0
        window_tokens = 0
        active_count = 0
        recent_step_ts = []  # type: List[float]

        for ddir in ds_dirs:
            sess_root = os.path.join(ddir, "sessions")
            scan_target = sess_root if os.path.isdir(sess_root) else ddir
            for root, _dirs, files in os.walk(scan_target):
                for fn in files:
                    lower = fn.lower()
                    if lower in SENSITIVE_FILENAMES:
                        continue
                    if not lower.endswith((".jsonl", ".zst")):
                        continue
                    fpath = os.path.join(root, fn)
                    parsed = self._parse_deepseek_session_cached(fpath)
                    if not parsed:
                        continue

                    for ev_ts, tok in parsed.get("step_events", []):
                        if ev_ts >= day_start:
                            today_steps += 1
                            today_tokens += tok
                        if ev_ts >= win_start:
                            window_steps += 1
                            window_tokens += tok
                            recent_step_ts.append(ev_ts)

                    upd = float(parsed["updated_at"])
                    age = max(0.0, now - upd)
                    if age < 180 or parsed.get("last_signal") == "running":
                        status, detail = "running", "DSH 运行中"
                        active_count += 1
                    else:
                        status, detail = "completed", "已完成"

                    sid = parsed["session_id"]
                    sessions.append(
                        {
                            "key": "dsh:" + sid,
                            "id": sid,
                            "provider": "deepseek_harness",
                            "provider_label": "DeepSeek Harness",
                            "title": parsed["title"],
                            "last_prompt": parsed.get("last_prompt", ""),
                            "status": status,
                            "status_detail": detail,
                            "updated_at": upd,
                            "created_at": parsed["created_at"],
                            "step_count": len(parsed.get("step_events", [])),
                            "total_tokens": parsed.get("total_tokens", 0),
                            "workspace": parsed.get("workspace", ""),
                            "is_manual": False,
                        }
                    )

        return sessions, {
            "today_steps": today_steps,
            "window_steps": window_steps,
            "today_tokens": today_tokens,
            "window_tokens": window_tokens,
            "recent_step_ts": recent_step_ts,
            "active_sessions": active_count,
            "total_sessions": len(sessions),
        }

    def _parse_deepseek_session_cached(self, file_path: str) -> Optional[Dict[str, Any]]:
        sig = _actual_file_signature(file_path)
        if not sig or sig[1] == 0:
            return None

        cache_key = "dsh_file:" + file_path
        cached = self._file_cache.get(cache_key)
        if cached and cached[0] == sig[0] and cached[1] == sig[1]:
            return cached[2]

        parent_name = os.path.basename(os.path.dirname(file_path))
        base_id = os.path.splitext(os.path.basename(file_path))[0]
        session_id = parent_name if parent_name not in ("sessions", ".dsh") else base_id

        try:
            with open(file_path, "rb") as bf:
                head = bf.read(4)
        except Exception:
            return None

        if head == ZSTD_MAGIC or file_path.lower().endswith(".zst"):
            proj_dir = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
            ws = proj_dir if proj_dir and proj_dir not in ("sessions", ".dsh") else ""
            data = {
                "session_id": session_id,
                "title": ("DSH · " + ws) if ws else ("DSH 会话 · " + session_id[:12]),
                "last_prompt": "",
                "workspace": ws,
                "created_at": sig[0],
                "updated_at": sig[0],
                "total_tokens": 0,
                "step_events": [(sig[0], 0)],
                "last_signal": "",
            }
            self._file_cache[cache_key] = (sig[0], sig[1], data)
            return data

        meta_title = ""
        first_prompt_raw = ""
        last_prompt_clean = ""
        ws = ""
        created_at = sig[0]
        updated_at = sig[0]
        total_tokens = 0
        step_events = []  # type: List[Tuple[float, int]]
        last_signal = ""

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue

                    ev_ts = (
                        parse_timestamp(obj.get("timestamp"))
                        or parse_timestamp(obj.get("created_at"))
                        or sig[0]
                    )
                    if idx == 0:
                        created_at = ev_ts
                    if ev_ts > updated_at:
                        updated_at = ev_ts

                    if obj.get("cwd"):
                        ws = os.path.basename(str(obj["cwd"]).rstrip("\\/"))
                    if obj.get("title"):
                        meta_title = clean_prompt_text(str(obj["title"]), max_len=36)

                    role = str(obj.get("role") or obj.get("type") or "")
                    if role in ("user", "user_message"):
                        raw_txt = str(obj.get("content") or obj.get("message") or obj.get("text") or "")
                        cand = clean_prompt_text(raw_txt, max_len=90)
                        if cand:
                            if not first_prompt_raw:
                                first_prompt_raw = raw_txt
                            last_prompt_clean = cand
                    elif role in ("assistant", "agent_message", "model"):
                        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
                        tok = int(usage.get("total_tokens") or 0)
                        if tok <= 0:
                            tok = int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)
                        total_tokens += tok
                        step_events.append((ev_ts, tok))
                        last_signal = "done"
        except Exception:
            return None

        if not step_events:
            step_events.append((updated_at, 0))

        conv_title = (
            meta_title
            or summarize_conversation_title(first_prompt_raw, workspace=ws)
            or ("DSH 会话 · " + session_id[:12])
        )

        data = {
            "session_id": session_id,
            "title": conv_title,
            "last_prompt": last_prompt_clean,
            "workspace": ws,
            "created_at": created_at,
            "updated_at": updated_at,
            "total_tokens": total_tokens,
            "step_events": step_events,
            "last_signal": last_signal,
        }
        self._file_cache[cache_key] = (sig[0], sig[1], data)
        return data
