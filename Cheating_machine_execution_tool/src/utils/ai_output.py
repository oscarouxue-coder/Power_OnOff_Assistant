"""AI诊断PC命令解码与保存证据的纯文本展示；不改变存储内容。"""
from __future__ import annotations

import codecs
import json
import locale
import os


def decode_pc_output(raw):
    """返回文本和实际使用的编码；仅全部严格解码失败时替换坏字节。"""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        # 有BOM时不尝试其它编码，避免把损坏的Unicode输出当作本地文本。
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            return raw.decode("utf-16", errors="replace"), "utf-16/replace"
    if raw.startswith(codecs.BOM_UTF8):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig/replace"

    encodings = ["utf-8"]
    if os.name == "nt":
        import ctypes
        # Python的UTF-8模式不代表Windows命令也使用UTF-8。
        for codepage in (ctypes.windll.kernel32.GetOEMCP(), ctypes.windll.kernel32.GetACP()):
            if codepage:
                encodings.append("cp" + str(codepage))
    encodings.append(locale.getpreferredencoding(False))
    for encoding in dict.fromkeys(encodings):
        try:
            return raw.decode(encoding), encoding
        except (UnicodeDecodeError, LookupError):
            continue
    # 保留无法解码的位置，并由调用方日志提示，不静默丢弃字节。
    fallback = encodings[1]
    return raw.decode(fallback, errors="replace"), fallback + "/replace"


def _display_value(value):
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            rendered = _display_value(item)
            parts.append(str(key) + ("：\n" if "\n" in rendered else "：") + rendered)
        return "\n".join(parts)
    if isinstance(value, list):
        return "\n\n".join(_display_value(item) for item in value)
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def format_diagnostic_evidence(value):
    """只解析已知证据结构，尾部现场日志和非JSON文本保持原样。"""
    original = value if isinstance(value, str) else str(value)
    tail = ""
    if isinstance(value, str):
        try:
            value, end = json.JSONDecoder().raw_decode(value.lstrip())
            tail = original.lstrip()[end:]
        except (ValueError, RecursionError):
            return original
        if not isinstance(value, list):
            return original
    if not isinstance(value, list) or not all(
        isinstance(item, dict) and ("evidence" in item or "error" in item) for item in value
    ):
        return original

    sections = []
    for index, item in enumerate(value, 1):
        lines = [f"[{index}] {item.get('tool', '采集结果')}"]
        if "error" in item:
            lines.append("采集失败：" + str(item["error"]))
        if "evidence" in item:
            content = item["evidence"]
            if item.get("tool") == "read_pc_environment" and isinstance(content, str):
                try:
                    content = json.loads(content)
                except (ValueError, RecursionError):
                    pass
            lines.append(_display_value(content))
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + tail
