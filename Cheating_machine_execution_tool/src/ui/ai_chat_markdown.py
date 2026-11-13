"""AI正文的轻量Markdown投影；仅生成显示片段，不修改消息或执行链接。"""
from dataclasses import dataclass
import re
from tkinter import font as tkfont


@dataclass(frozen=True)
class MarkdownLine:
    spans: tuple
    kind: str = "paragraph"
    indent: int = 0
    marker: str = ""


FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\n]*)$")
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$")
LIST = re.compile(r"^([ \t]*)([-+*]|\d+[.)])[ \t]+(.*)$")
# 未支持的链接/图片/HTML作为原文整体保留，避免部分隐藏其中的标记。
PROTECTED = re.compile(r"!?\[[^\]\n]*\]\([^\n]*?\)|<[^>\n]+>")


def _inline(text, bold=False):
    """代码先于强调解析；不支持的格式与未闭合分隔符保持可见。"""
    spans = []
    plain = []
    tags = ("md_bold",) if bold else ()

    def flush():
        if plain:
            spans.append(("".join(plain), tags))
            plain.clear()

    index = 0
    while index < len(text):
        protected = PROTECTED.match(text, index)
        if protected:
            plain.append(protected.group())
            index = protected.end()
            continue
        if text[index:index + 2] in (r"\*", r"\`", r"\_", r"\#"):
            # 不移除反斜杠，避免把Windows路径中的\_、\#误当转义改写。
            plain.append(text[index:index + 2])
            index += 2
            continue
        if text.startswith("***", index):
            # 斜体/粗斜体不在本模块支持范围内，不解释三颗及更多星号。
            run = re.match(r"\*+", text[index:]).group()
            plain.append(run)
            index += len(run)
            continue
        if text[index] == "`":
            run = re.match(r"`+", text[index:]).group()
            closing = re.search(r"(?<!`)" + run + r"(?!`)", text[index + len(run):])
            if closing:
                end = index + len(run) + closing.start()
                flush()
                spans.append((text[index + len(run):end], tags + ("md_inline_code",)))
                index = end + len(run)
                continue
            plain.append(text[index:])
            break
        if not bold and text.startswith("**", index):
            # 寻找代码区之外的结束标记，代码中的星号不参与强调配对。
            end = index + 2
            while end < len(text):
                protected = PROTECTED.match(text, end)
                if protected:
                    end = protected.end()
                    continue
                if text[end] == "\\":
                    end += 2
                    continue
                if text[end] == "`":
                    run = re.match(r"`+", text[end:]).group()
                    closing = re.search(r"(?<!`)" + run + r"(?!`)", text[end + len(run):])
                    if closing:
                        end += len(run) + closing.end()
                        continue
                if text.startswith("**", end):
                    break
                end += 1
            content = text[index + 2:end]
            if end < len(text) and content and content == content.strip():
                flush()
                spans.extend(_inline(content, bold=True))
                index = end + 2
                continue
            plain.append(text[index:])
            break
        plain.append(text[index])
        index += 1
    flush()
    return tuple(spans)


def parse_markdown(text):
    """返回显示行；仅压缩代码区以外的连续空行，代码负载不做行内解析。"""
    lines = text.split("\n")
    result = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = FENCE.match(line)
        if fence and not (fence[1][0] == "`" and "`" in fence[2]):
            close = re.compile(r"^ {0,3}" + re.escape(fence[1][0]) +
                               "{" + str(len(fence[1])) + r",}[ \t]*\r?$")
            end = next((n for n in range(index + 1, len(lines)) if close.match(lines[n])), None)
            if end is None:
                # 不完整代码块整体按原文显示，不继续解释内部命令。
                result.extend(MarkdownLine(((value, ()),)) for value in lines[index:])
                break
            for n in range(index + 1, end):
                kind = "code"
                if n == index + 1:
                    kind += "_first"
                if n == end - 1:
                    kind += "_last"
                result.append(MarkdownLine(((lines[n], ()),), kind))
            index = end + 1
            continue
        if not line.strip():
            if not result or result[-1].kind != "blank":
                result.append(MarkdownLine((("", ()),), "blank"))
        elif (line.lstrip().startswith("|") and line.rstrip().endswith("|")) or re.match(
                r"^ {0,3}(?:\*[ \t]*){3,}$|^ {0,3}(?:-[ \t]*){3,}$|^ {0,3}(?:_[ \t]*){3,}$", line):
            result.append(MarkdownLine(((line, ()),)))
        elif HEADING.match(line):
            heading = HEADING.match(line)
            result.append(MarkdownLine(_inline(heading[2]), "h1" if len(heading[1]) == 1 else "h2"))
        elif LIST.match(line):
            item = LIST.match(line)
            marker = "• " if item[2] in "-+*" else item[2] + " "
            result.append(MarkdownLine(_inline(item[3]), "list",
                                       len(item[1].expandtabs(4)), marker))
        elif re.match(r"^ {0,3}>[ \t]?", line):
            quote = re.sub(r"^ {0,3}>[ \t]?", "", line, count=1)
            result.append(MarkdownLine(_inline(quote), "quote", marker="│ "))
        else:
            result.append(MarkdownLine(_inline(line)))
        index += 1
    return tuple(result)


def configure_markdown_tags(output, family):
    """局部样式不指定文字颜色，继续继承问题/错误等消息语义色。"""
    output.tag_configure("md_paragraph", spacing1=2, spacing2=3, spacing3=4)
    output.tag_configure("md_h1", font=(family, 13, "bold"), spacing1=10, spacing3=6)
    output.tag_configure("md_h2", font=(family, 12, "bold"), spacing1=9, spacing3=5)
    output.tag_configure("md_bold", font=(family, 11, "bold"))
    output.tag_configure("md_inline_code", font=("Consolas", 11), background="#e5edf0")
    output.tag_raise("md_h1", "md_bold")
    output.tag_raise("md_h2", "md_bold")
    tab_width = tkfont.Font(root=output, family="Consolas", size=11).measure("    ")
    output.tag_configure("md_code", font=("Consolas", 11), background="#e5edf0",
                         lmargin1=24, lmargin2=24, rmargin=24,
                         spacing1=0, spacing2=2, spacing3=0, tabs=(tab_width,))
    output.tag_configure("md_code_first", spacing1=7)
    output.tag_configure("md_code_last", spacing3=7)
    output.tag_configure("md_blank", font=(family, 4), spacing1=0, spacing2=0, spacing3=0)
    output.tag_raise("sel")


def insert_markdown(output, text, body_tag):
    """插入可选择/复制的正文；视觉折行由Text完成，不插入换行字符。"""
    body_font = tkfont.Font(root=output, font=output.tag_cget(body_tag, "font"))
    for line in parse_markdown(text):
        tags = (body_tag, "md_paragraph")
        if line.kind.startswith("code"):
            tags += ("md_code",)
            if "first" in line.kind:
                tags += ("md_code_first",)
            if "last" in line.kind:
                tags += ("md_code_last",)
        elif line.kind in ("h1", "h2", "blank"):
            tags += ("md_" + line.kind,)
        elif line.kind in ("list", "quote"):
            margin = 12 + min(line.indent, 24) * body_font.measure(" ")
            hanging = margin + body_font.measure(line.marker)
            tag = f"md_indent_{margin}_{hanging}"
            output.tag_configure(tag, lmargin1=margin, lmargin2=hanging)
            output.tag_lower(tag, "sel")
            tags += (tag,)
        if line.marker:
            output.insert("end", line.marker, tags)
        for value, inline_tags in line.spans:
            output.insert("end", value, tags + inline_tags)
        output.insert("end", "\n", tags)
