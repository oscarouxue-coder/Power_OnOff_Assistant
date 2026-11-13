"""轻量排版的内容保真与真实Tk选择复制验证，无模型/设备操作。"""
import gc
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.ui.ai_chat_markdown import configure_markdown_tags, insert_markdown, parse_markdown


def visible(text):
    return "".join(line.marker + "".join(value for value, _ in line.spans) + "\n"
                   for line in parse_markdown(text))


class MarkdownContentTests(unittest.TestCase):
    def test_headings_bold_lists_quote_and_inline_code(self):
        source = "# 修改结果\n## **配置内容**\n- **位置**：`C:\\配置\\test.ini`\n2. 重新加载\n> 请确认"
        self.assertEqual(visible(source),
                         "修改结果\n配置内容\n• 位置：C:\\配置\\test.ini\n2. 重新加载\n│ 请确认\n")
        lines = parse_markdown(source)
        self.assertEqual([line.kind for line in lines], ["h1", "h2", "list", "list", "quote"])
        self.assertIn(("位置", ("md_bold",)), lines[2].spans)
        self.assertIn((r"C:\配置\test.ini", ("md_inline_code",)), lines[2].spans)

    def test_fenced_code_keeps_spaces_blank_lines_tabs_and_literal_markup(self):
        payload = "  [project_info]\n\n\n\tproject_name = NP7287XGS\n# **原文** `路径`\n"
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                self.assertEqual(visible(fence + "ini\n" + payload + fence), payload)
                self.assertTrue(all(not tags for line in parse_markdown(fence + "\n" + payload + fence)
                                    for _, tags in line.spans))

    def test_code_closing_fence_must_match_character_length_and_whole_line(self):
        source = "````text\n```\n~~~\n```` suffix\n原文\n`````"
        self.assertEqual(visible(source), "```\n~~~\n```` suffix\n原文\n")

    def test_crlf_code_payload_preserves_original_line_endings(self):
        payload = "  first\r\n\r\n\tsecond\r\n"
        self.assertEqual(visible("```text\r\n" + payload + "```\r\n正文"), payload + "正文\n")

    def test_unclosed_code_keeps_entire_suffix_literal(self):
        source = "```python\n# **不是标题**\n\n\n    value = `literal`"
        self.assertEqual(visible(source), source + "\n")

    def test_unmatched_inline_markers_are_kept(self):
        for source in ("**未闭合", "`未闭合", "**尾部空格 **", "正文 *斜体*", "变量 __name__",
                       "***粗斜体***", "* * *", "- - -"):
            with self.subTest(source=source):
                self.assertEqual(visible(source), source + "\n")

    def test_inline_code_has_priority_over_bold_and_supports_backtick_runs(self):
        self.assertEqual(visible("`**原文**` 和 **命令 `echo **`** 与 ``a`b``"),
                         "**原文** 和 命令 echo ** 与 a`b\n")

    def test_table_link_image_html_are_preserved_without_partial_formatting(self):
        for source in ("| **字段** | `值` |", "| --- | --- |",
                       "[**说明**](https://example.test)", "![`图片`](preview.png)",
                       '<b title="**原文**">内容</b>'):
            with self.subTest(source=source):
                self.assertEqual(visible(source), source + "\n")

    def test_windows_path_punctuation_and_unicode_are_not_rewritten(self):
        for path in (r"C:\测试文件\a_b.ini", r"\\server\配置\a.ini", r"C:\_config\#1.ini",
                     r"C:\**\file.log", "型号NP7287XGS😀"):
            self.assertEqual(visible(path), path + "\n")
            self.assertEqual(visible("`" + path + "`"), path + "\n")

    def test_only_consecutive_blank_lines_outside_code_are_compacted(self):
        self.assertEqual(visible("第一段\n\n\n\n第二段"), "第一段\n\n第二段\n")
        self.assertEqual(visible("保留  \n  原文\n\n末尾\n"), "保留  \n  原文\n\n末尾\n\n")

    def test_indented_lists_and_multidigit_numbers_keep_markers(self):
        lines = parse_markdown("- 第一层\n  * 第二层\n\t123) 编号")
        self.assertEqual([(line.indent, line.marker) for line in lines], [(0, "• "), (2, "• "), (4, "123) ")])


class MarkdownWidgetTests(unittest.TestCase):
    def setUp(self):
        gc.collect()
        self.root = tk.Tk()
        self.root.geometry("940x660")
        self.output = tk.Text(self.root, wrap="word")
        self.output.pack(fill="both", expand=True)
        self.output.tag_configure("body_assistant", font=("Microsoft YaHei UI", 11), foreground="#17202a")
        self.output.tag_configure("body_question", font=("Microsoft YaHei UI", 11), foreground="#17202a")
        self.output.tag_configure("body_error", font=("Microsoft YaHei UI", 11), foreground="#b42318")
        self.output.tag_configure("message_assistant", background="#edf8f5", lmargin1=12, lmargin2=12)
        configure_markdown_tags(self.output, "Microsoft YaHei UI")

    def tearDown(self):
        self.root.destroy()
        del self.output, self.root
        gc.collect()

    def test_display_tags_preserve_semantic_colors_and_selection_priority(self):
        for body in ("body_assistant", "body_question", "body_error"):
            self.output.delete("1.0", "end")
            insert_markdown(self.output, "## **标题**\n- **重点** `路径`\n```\n  code\n```", body)
            self.output.tag_add("message_assistant", "1.0", "end-1c")
            self.assertEqual(self.output.get("1.0", "end-1c"), "标题\n• 重点 路径\n  code\n")
            for tag in (body, "md_h2", "md_bold", "md_inline_code", "md_code"):
                self.assertTrue(self.output.tag_ranges(tag), tag)
            for tag in ("md_h2", "md_bold", "md_inline_code", "md_code"):
                self.assertEqual(self.output.tag_cget(tag, "foreground"), "")
            self.assertEqual(self.output.tag_names()[-1], "sel")
            fonts = [self.output.tag_cget(tag, "font") for tag in self.output.tag_names("1.0")
                     if self.output.tag_cget(tag, "font")]
            self.assertIn("12", fonts[-1])

    def test_hanging_indent_wrap_and_clipboard_keep_long_path_and_code_exact(self):
        path = "E:/" + "很长的中文目录/" * 16 + "test_project_config.ini"
        payload = "\tvalue = '  **原文**  '\n\n  echo C:\\配置\\test.ini\n"
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                ttk.Style(self.root).theme_use(theme)
                self.output.configure(state="normal")
                self.output.delete("1.0", "end")
                insert_markdown(self.output, "12. `" + path + "`\n```text\n" + payload + "```", "body_assistant")
                self.output.tag_add("message_assistant", "1.0", "end-1c")
                self.output.configure(state="disabled")
                self.root.update()
                self.assertEqual(self.output.get("1.0", "end-1c"), "12. " + path + "\n" + payload)
                tag = next(tag for tag in self.output.tag_names("1.0") if tag.startswith("md_indent_"))
                self.assertGreater(int(self.output.tag_cget(tag, "lmargin2")),
                                   int(self.output.tag_cget(tag, "lmargin1")))
                self.assertGreater(int(self.output.count("1.0", "2.0", "displaylines")[0]), 1)
                self.output.tag_add("sel", "2.0", "end-1c")
                self.output.event_generate("<<Copy>>")
                self.root.update()
                self.assertEqual(self.root.clipboard_get(), payload)
                self.assertEqual(self.output.tag_names()[-1], "sel")


if __name__ == "__main__":
    unittest.main()
