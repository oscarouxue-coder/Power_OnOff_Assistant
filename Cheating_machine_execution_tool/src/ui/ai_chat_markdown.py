"""Tk presentation of the original AI Markdown display fragments."""
from tkinter import font as tkfont

from src.utils.ai_chat_markdown import MarkdownLine, parse_markdown


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
