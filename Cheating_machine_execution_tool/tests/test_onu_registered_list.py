import tkinter as tk
from tkinter import ttk
import unittest
from tk_test_windows import install_offscreen_windows

from src.models.onu_batch_delete import OnuBatchDeleteResult, OnuDeleteItemResult
from src.models.onu_registration_models import OltConnection, RegisteredOnu
from src.ui.module_theme import MODULE_BACKGROUND
from src.ui.onu_registered_list import RegisteredOnuList, confirm_batch_delete


def targets(count=3):
    return tuple(RegisteredOnu("C600", "gpon_olt-1/1/1", f"gpon_onu-1/1/1:{index}", index,
                               "working", f"TEST{index:08X}", "TEST-TYPE") for index in range(1, count + 1))


class RegisteredListTests(unittest.TestCase):
    def setUp(self):
        self.test_windows = install_offscreen_windows(self)
        self.root = tk.Tk()
        self.root.geometry("1000x600")
        self.widget = RegisteredOnuList(self.root)
        self.widget.pack(fill="both", expand=True)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def test_default_empty_selection_and_selection_order(self):
        self.widget.set_candidates(targets())
        self.assertEqual(self.widget.selected(), ())
        self.widget.rows[2][2].invoke()
        self.widget.rows[0][2].invoke()
        self.assertEqual(self.widget.selected(), (targets()[0], targets()[2]))
        self.assertEqual(self.widget.count_var.get(), "已选 2 / 3 台")

    def test_selection_buttons_share_query_toolbar_and_follow_query_on_same_row(self):
        for theme in ("vista", "clam"):
            ttk.Style(self.root).theme_use(theme)
            dialog = tk.Toplevel(self.root)
            dialog.geometry("1000x400")
            actions = tk.Frame(dialog)
            actions.pack(fill="x")
            query = ttk.Button(actions, text="查询已注册 ONU")
            query.pack(side="left")
            widget = RegisteredOnuList(dialog, actions_parent=actions)
            widget.pack(fill="both", expand=True)
            widget.set_candidates(targets())
            self.root.update()
            self.assertEqual(widget.select_all_button.master, query.master)
            self.assertEqual(widget.clear_button.master, query.master)
            self.assertEqual(query.winfo_y(), widget.select_all_button.winfo_y())
            self.assertEqual(query.winfo_y(), widget.clear_button.winfo_y())
            self.assertLess(query.winfo_x(), widget.select_all_button.winfo_x())
            self.assertLess(widget.select_all_button.winfo_x(), widget.clear_button.winfo_x())
            widget.select_all_button.invoke()
            self.assertEqual(widget.selected(), targets())
            dialog.destroy()

    def test_select_all_clear_and_busy_lock(self):
        self.widget.set_candidates(targets())
        self.widget.select_all_button.invoke()
        self.assertEqual(self.widget.selected(), targets())
        self.widget.set_enabled(False)
        self.widget.clear_button.invoke()
        self.widget.rows[0][2].invoke()
        self.widget.select_all(False)
        self.assertEqual(self.widget.selected(), targets())
        self.widget.set_enabled(True)
        self.widget.clear_button.invoke()
        self.assertEqual(self.widget.selected(), ())

    def test_requery_discards_old_selections_and_results(self):
        self.widget.set_candidates(targets())
        self.widget.select_all(True)
        self.widget.show_results(OnuBatchDeleteResult((OnuDeleteItemResult(targets()[0], "failed", "结果待核实"),)))
        self.widget.set_candidates(targets(1))
        self.assertEqual(self.widget.selected(), ())
        self.assertFalse(self.widget.finished)
        self.assertEqual(self.widget.rows[0][3].cget("text"), "")
        self.widget.rows[0][2].invoke()
        self.assertEqual(self.widget.selected(), targets(1))

    def test_empty_result_rows_do_not_take_space_and_populate_only_after_deletion(self):
        for theme in ("vista", "clam"):
            ttk.Style(self.root).theme_use(theme)
            self.widget.set_candidates(targets())
            self.root.update()
            first, second = self.widget.rows[:2]
            self.assertFalse(first[3].winfo_ismapped())
            self.assertEqual(second[2].winfo_y() - first[2].winfo_y(), first[2].winfo_height())
            self.assertLessEqual(first[2].winfo_height(), 30)
            self.widget.show_results(OnuBatchDeleteResult((OnuDeleteItemResult(first[0], "failed", "结果待核实"),)))
            self.root.update()
            self.assertTrue(first[3].winfo_ismapped())
            self.assertFalse(second[3].winfo_ismapped())

    def test_each_result_is_visible_and_finished_batch_cannot_be_reselected(self):
        self.widget.set_candidates(targets())
        self.widget.select_all(True)
        result = OnuBatchDeleteResult(tuple(OnuDeleteItemResult(target, status, status + " detail")
                                            for target, status in zip(targets(), ("success", "failed", "not_executed"))))
        self.widget.show_results(result)
        self.widget.set_enabled(True)
        self.widget.select_all(True)
        self.assertEqual(self.widget.selected(), ())
        for row, label in zip(self.widget.rows, ("成功", "失败", "未执行")):
            self.assertTrue(row[3].cget("text").startswith(label))
            self.assertEqual(str(row[2].cget("state")), "disabled")

    def test_vista_and_clam_native_checks_scroll_and_minimum_layout(self):
        style = ttk.Style(self.root)
        for theme in ("vista", "clam"):
            with self.subTest(theme=theme):
                self.assertIn(theme, style.theme_names())
                style.theme_use(theme)
                self.root.geometry("1000x400")
                self.widget.set_candidates(targets(128))
                self.root.update()
                for _target, _variable, check, _result in self.widget.rows:
                    self.assertEqual(check.winfo_class(), "Checkbutton")
                    self.assertEqual(check.cget("background"), MODULE_BACKGROUND)
                self.assertGreater(self.widget.canvas.bbox("all")[3], self.widget.canvas.winfo_height())
                self.widget.canvas.yview_moveto(1)
                self.root.update()
                self.assertAlmostEqual(self.widget.canvas.yview()[1], 1.0)
                self.assertLessEqual(self.widget.clear_button.winfo_rooty() + self.widget.clear_button.winfo_height(),
                                     self.root.winfo_rooty() + self.root.winfo_height())
                self.widget.rows[-1][2].invoke()
                self.assertEqual(self.widget.selected(), (targets(128)[-1],))

    def _confirm(self, action, count=128):
        errors = []

        def inspect_and_close():
            dialogs = [child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel)]
            dialog = dialogs[0]
            try:
                descendants = []

                def collect(widget):
                    descendants.append(widget)
                    for child in widget.winfo_children():
                        collect(child)

                collect(dialog)
                self.assertEqual(dialog.title(), "确认删除选中 ONU（危险）")
                self.assertFalse(any(isinstance(widget, (tk.Label, ttk.Label)) for widget in descendants))
                text = next(widget for widget in descendants if isinstance(widget, tk.Text))
                self.assertEqual(str(text.cget("state")), "disabled")
                self.assertIn(targets(count)[-1].onu_interface, text.get("1.0", "end"))
                self.assertIn(targets(count)[-1].serial_number, text.get("1.0", "end"))
                if action == "enter":
                    # 使用绑定脚本直接触发默认回车路径，无需系统焦点或鼠标。
                    dialog.tk.call("eval", dialog.bind("<Return>").replace("%#", "0").replace("%b", "0"))
                else:
                    next(widget for widget in descendants if isinstance(widget, ttk.Button)
                         and widget.cget("text") == action).invoke()
            except BaseException as exc:
                errors.append(exc)
                if dialog.winfo_exists():
                    dialog.destroy()

        self.root.after(30, inspect_and_close)
        result = confirm_batch_delete(self.root, "C600", OltConnection("192.0.2.1", "192.0.2.2", "test", "test"),
                                      "gpon_olt-1/1/1", targets(count))
        if errors:
            raise errors[0]
        return result

    def test_confirmation_has_full_scrollable_readonly_list_and_cancel(self):
        self.assertFalse(self._confirm("取消"))

    def test_confirmation_requires_explicit_confirm(self):
        self.assertTrue(self._confirm("确认删除", count=1))

    def test_confirmation_enter_defaults_to_cancel(self):
        self.assertFalse(self._confirm("enter"))


if __name__ == "__main__":
    unittest.main()
