"""飞书外发边界：仅清理输出，不改变本地日志和模型上下文。"""
import configparser
import json
import re
from pathlib import Path

from src.core.feishu_client import post_payload


POST_BYTE_LIMIT = 28000
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)\r?$")
CODE_LANGUAGES = frozenset(("PYTHON", "C", "CPP", "GO", "JAVA", "KOTLIN", "SWIFT", "PHP",
                            "RUBY", "RUST", "JAVASCRIPT", "TYPESCRIPT", "BASH", "SHELL", "SQL",
                            "JSON", "XML", "YAML", "HTML", "THRIFT"))


def _reply_nodes(text, markdown):
    if not markdown:
        return [dict(tag="text", text=text)]
    lines = text.splitlines(keepends=True)
    nodes, prose = [], []
    index = 0
    while index < len(lines):
        fence = FENCE.fullmatch(lines[index].rstrip("\n"))
        if not fence or (fence[1][0] == "`" and "`" in fence[2]):
            prose.append(lines[index])
            index += 1
            continue
        close = re.compile(r"^ {0,3}" + re.escape(fence[1][0]) +
                           "{" + str(len(fence[1])) + r",}[ \t]*\r?$")
        end = next((n for n in range(index + 1, len(lines))
                    if close.fullmatch(lines[n].rstrip("\n"))), None)
        if prose:
            nodes.append(dict(tag="md", text="".join(prose)))
            prose.clear()
        if end is None:
            # 与本地工作台一致：未闭合代码围栏及后文完整显示为原文。
            nodes.append(dict(tag="text", text="".join(lines[index:])))
            break
        node = dict(tag="code_block", text="".join(lines[index + 1:end]))
        language = fence[2].strip().upper()
        if language in CODE_LANGUAGES:
            node["language"] = language
        nodes.append(node)
        index = end + 1
    if prose:
        nodes.append(dict(tag="md", text="".join(prose)))
    return nodes


def reply_posts(chat_id, title, text, *, markdown=True):
    """仅生成显示投影；按段落/行分段并保留代码负载，不改写会话原文。"""
    def post(nodes, heading):
        return {"zh_cn": dict(title=heading, content=[[node] for node in nodes])}

    def fits(nodes):
        # 为最终分段编号预留空间，大小计算与requests的真实序列化一致。
        payload = post_payload(chat_id, post(nodes, "[999999/999999] " + title), "0" * 32)
        return len(json.dumps(payload, ensure_ascii=True).encode("utf-8")) <= POST_BYTE_LIMIT

    if not fits([dict(tag="text", text="")]):
        raise ValueError("飞书回复标题过长")
    chunks, current = [], []
    for node in _reply_nodes(text, markdown):
        if fits(current + [node]):
            current.append(node)
            continue
        if current:
            chunks.append(current)
            current = []
        remaining = node["text"]
        while remaining:
            if fits([dict(node, text=remaining)]):
                current = [dict(node, text=remaining)]
                break
            low, high = 0, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if fits([dict(node, text=remaining[:middle])]):
                    low = middle
                else:
                    high = middle - 1
            if not low:
                raise ValueError("飞书回复无法分段")
            boundary = remaining.rfind("\n\n", 0, low)
            if boundary >= 0:
                low = boundary + 2
            else:
                boundary = remaining.rfind("\n", 0, low)
                if boundary >= 0:
                    low = boundary + 1
            chunks.append([dict(node, text=remaining[:low])])
            remaining = remaining[low:]
    if current:
        chunks.append(current)
    if len(chunks) > 999999:
        raise ValueError("飞书回复分段过多")
    return [post(nodes, (f"[{index + 1}/{len(chunks)}] " if len(chunks) > 1 else "") + title)
            for index, nodes in enumerate(chunks)]


def sanitize(text, project_path, secrets=(), conversation=None):
    hidden = list(secrets)
    if conversation is not None:
        text = conversation.redactor.text(text)
        with conversation.diagnostic.lock:
            hidden.extend(t.password for t in conversation.diagnostic.targets.values())
        for profile in conversation.store.profiles():
            hidden.append(conversation.store.key(profile))
    for path in Path(project_path).parent.glob("*.ini"):
        parser = configparser.RawConfigParser()
        with path.open(encoding="utf-8-sig") as stream:
            parser.read_file(stream)
        for section in parser.sections():
            for key, value in parser.items(section):
                if (re.search(r"password|passwd|secret|token|psk|verification_code|^key$|webhook", key, re.I)
                        and not re.search(r"_(flag|enable|enabled|mode|length|timeout|retry)$", key, re.I)):
                    hidden.append(value.strip())
    for value in sorted(set(filter(None, hidden)), key=len, reverse=True):
        text = text.replace(value, "<凭据已隐藏>")
    text = re.sub(r"(?i)(access_token|tenant_access_token|session|ticket|app_secret)=([^\s&]+)",
                  r"\1=<凭据已隐藏>", text)
    return re.sub(r"<at\b", "[at", text, flags=re.I)
