"""Real Tk contracts for the channel list, without app initialization or devices."""
import gc
import ctypes
import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from line_check_assistant import app as a


class _ChannelInteractionContract:
    def make_list(self):
        return tk.Listbox(
            self.root, width=34, height=16, font=a.CHANNEL_LIST_FONT,
            selectborderwidth=3, exportselection=False,
        )

    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.close_root)
        self.root.geometry('560x650+20+20')
        self.lb = self.make_list()
        self.lb.pack(fill='both', expand=True)
        self.context = SimpleNamespace(
            channel_list=self.lb,
            channels=[a.ChannelConfig(section=f'channel_{i}', enabled=False) for i in range(1, 17)],
            current_index=0, _last_selected_index=0,
            _capture_channel=Mock(), _capture_current_channel=Mock(),
            _load_current_channel=Mock(), _persist_config=Mock(),
            _rebuild_channel_config_rows=Mock(), _serial_port_for_channel=lambda c: '',
            channel_context_menu=Mock(),
        )
        for name in (
            '_channel_list_label', '_channel_list_row_at', '_on_channel_list_press',
            '_on_channel_list_click', '_on_channel_list_double_click',
            '_on_channel_list_context_menu', '_on_channel_selected',
            '_toggle_selected_channel_enabled', '_toggle_channel_enabled',
            '_refresh_channel_list_item', '_apply_power_test_channel_color',
            '_select_channel_index',
        ):
            setattr(self.context, name, MethodType(getattr(a.LineCheckAssistant, name), self.context))
        for c in self.context.channels:
            self.lb.insert(tk.END, self.context._channel_list_label(c))
        self.lb.selection_set(0)
        self.selection_events = []

        def selected(event):
            self.selection_events.append(self.lb.curselection())
            self.context._on_channel_selected(event)

        self.lb.bind('<<ListboxSelect>>', selected)
        for sequence, method in (
            ('<Button-1>', '_on_channel_list_press'),
            ('<ButtonRelease-1>', '_on_channel_list_click'),
            ('<Double-Button-1>', '_on_channel_list_double_click'),
            ('<Button-3>', '_on_channel_list_context_menu'),
            ('<space>', '_toggle_selected_channel_enabled'),
        ):
            self.lb.bind(sequence, getattr(self.context, method))
        self.root.update()
        self.lb.focus_force()
        self.root.update()
        self.selection_events.clear()

    def close_root(self):
        self.root.destroy()
        self.lb = self.context = self.root = None
        gc.collect()

    def click(self, index, x=90):
        self.lb.see(index)
        self.root.update()
        box = self.lb.bbox(index)
        y = box[1] + box[3] // 2
        self.lb.event_generate('<ButtonPress-1>', x=x, y=y)
        self.lb.event_generate('<ButtonRelease-1>', x=x, y=y)
        self.root.update()

    def test_click_and_refresh_keep_one_selection_callback(self):
        self.click(2)
        self.assertEqual(self.lb.curselection(), (2,))
        self.assertEqual(self.context.current_index, 2)
        self.assertEqual(self.selection_events, [(2,)])
        self.assertFalse(self.context.channels[2].enabled)
        self.context._refresh_channel_list_item(2)
        self.root.update()
        self.assertEqual(self.lb.curselection(), (2,))
        self.assertEqual(self.selection_events, [(2,)])

    def test_marker_space_and_double_click_use_existing_toggle(self):
        self.click(1, x=8)
        self.assertTrue(self.context.channels[1].enabled)
        self.lb.event_generate('<space>')
        self.root.update()
        self.assertFalse(self.context.channels[1].enabled)
        box = self.lb.bbox(1)
        self.context._on_channel_list_double_click(SimpleNamespace(x=90, y=box[1]+box[3]//2))
        self.root.update()
        self.assertTrue(self.context.channels[1].enabled)
        self.assertEqual(self.context._persist_config.call_count, 3)

    def test_arrow_key_changes_current_channel_once(self):
        self.click(2)
        self.selection_events.clear()
        self.lb.event_generate('<Down>')
        self.root.update()
        self.assertEqual(self.lb.curselection(), (3,))
        self.assertEqual(self.context.current_index, 3)
        self.assertEqual(self.selection_events, [(3,)])

    def test_real_double_click_uses_existing_toggle_once(self):
        box = self.lb.bbox(3)
        y = box[1] + box[3]//2
        for time in (1000, 1100):
            self.lb.event_generate('<ButtonPress-1>', x=90, y=y, time=time)
            self.lb.event_generate('<ButtonRelease-1>', x=90, y=y, time=time+10)
            self.root.update()
        self.assertTrue(self.context.channels[3].enabled)
        self.assertEqual(self.context._persist_config.call_count, 1)

    def test_home_end_and_mouse_wheel_keep_rows_reachable(self):
        self.click(2)
        for key, index in (('<Control-End>', 15), ('<Control-Home>', 0)):
            self.lb.event_generate(key)
            self.root.update()
            self.assertEqual(self.lb.curselection(), (index,))
        self.root.geometry('560x220')
        self.root.update()
        self.lb.event_generate('<MouseWheel>', delta=-120)
        self.root.update()
        self.assertGreater(self.lb.yview()[0], 0)
        self.lb.see(15)
        self.root.update()
        self.assertIsNotNone(self.lb.bbox(15))

    def test_programmatic_selection_does_not_call_business_callback(self):
        self.context._select_channel_index(4)
        self.root.update()
        self.assertEqual(self.lb.curselection(), (4,))
        self.assertEqual(self.selection_events, [])
        self.lb.delete(4)
        self.lb.insert(4, 'channel_5 updated')
        self.lb.selection_set(4)
        self.root.update()
        self.assertEqual(self.selection_events, [])

    def test_row_gutter_and_trailing_blank_do_not_select_or_toggle(self):
        box = self.lb.bbox(2)
        for y in (box[1]-1, self.lb.bbox(15)[1]+self.lb.bbox(15)[3]+10):
            with self.subTest(y=y):
                before = self.lb.curselection()
                self.lb.event_generate('<ButtonPress-1>', x=8, y=y)
                self.lb.event_generate('<ButtonRelease-1>', x=8, y=y)
                self.root.update()
                self.assertEqual(self.lb.curselection(), before)
        self.context._persist_config.assert_not_called()

    def test_right_click_selects_row_and_preserves_log_menu(self):
        box = self.lb.bbox(4)
        self.lb.event_generate('<Button-3>', x=90, y=box[1]+box[3]//2)
        self.root.update()
        self.assertEqual(self.context.current_index, 4)
        self.assertEqual(self.lb.curselection(), (4,))
        self.context.channel_context_menu.tk_popup.assert_called_once()
        self.context.channel_context_menu.grab_release.assert_called_once()
        self.context._persist_config.assert_not_called()


class NativeChannelListContractTests(_ChannelInteractionContract, unittest.TestCase):
    """Keep the old native control as the interaction reference."""


class FlatChannelListContractTests(_ChannelInteractionContract, unittest.TestCase):
    def make_list(self):
        from src.ui.channel_list import ChannelList
        return ChannelList(
            self.root, font=a.CHANNEL_LIST_FONT, background=a.COLOR_SURFACE_SUBTLE,
            foreground=a.COLOR_TEXT, selectforeground=a.COLOR_PRIMARY_DARK,
            highlightbackground=a.COLOR_BORDER, highlightcolor=a.COLOR_PRIMARY,
        )


class ChannelListAppearanceTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry('1000x650+20+20')
        self.addCleanup(self.root.destroy)

    def make_list(self, parent):
        from src.ui.channel_list import ChannelList
        return ChannelList(
            parent, font=a.CHANNEL_LIST_FONT, background=a.COLOR_SURFACE_SUBTLE,
            foreground=a.COLOR_TEXT, selectforeground=a.COLOR_PRIMARY_DARK,
            highlightbackground=a.COLOR_BORDER, highlightcolor=a.COLOR_PRIMARY,
        )

    def test_both_themes_match_old_font_spacing_width_and_text_inset(self):
        for theme in ('vista', 'clam'):
            with self.subTest(theme=theme):
                tk.ttk.Style(self.root).theme_use(theme)
                old = tk.Listbox(self.root, font=a.CHANNEL_LIST_FONT, width=34, height=16,
                                 selectborderwidth=3, borderwidth=0, highlightthickness=1)
                new = self.make_list(self.root)
                for widget in (old, new):
                    widget.insert(tk.END, 'channel_14', 'channel_15')
                    widget.pack(side='left', anchor='n')
                self.root.update()
                self.assertEqual(new._font.actual()['size'], 13)
                self.assertEqual(old.winfo_reqwidth(), new.winfo_reqwidth())
                self.assertEqual(old.bbox(1)[1]-old.bbox(0)[1], new.bbox(1)[1]-new.bbox(0)[1])
                self.assertEqual(old.bbox(0)[2:], new.bbox(0)[2:])
                self.assertEqual(old.winfo_rooty()+old.bbox(0)[1], new._tree.winfo_rooty()+new.bbox(0)[1])
                self.assertEqual(old.bbox(0)[0], new._tree.winfo_x()+new.bbox(0)[0])
                old.destroy()
                new.destroy()

    @unittest.skipUnless(sys.platform == 'win32', 'Actual Windows render pixels require Win32')
    def test_selected_blurred_refocused_pixels_are_flat_in_both_themes(self):
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetDC.argtypes = [ctypes.c_void_p]
        user32.GetDC.restype = ctypes.c_void_p
        user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        gdi32.GetPixel.restype = ctypes.c_uint32
        color = a.COLOR_SURFACE_SUBTLE.lstrip('#')
        expected = int(color[0:2], 16) | int(color[2:4], 16) << 8 | int(color[4:6], 16) << 16
        for theme in ('vista', 'clam'):
            tk.ttk.Style(self.root).theme_use(theme)
            widget = self.make_list(self.root)
            widget.pack(side='left', anchor='n')
            entry = tk.ttk.Entry(self.root)
            entry.pack(side='left')
            widget.insert(tk.END, 'channel_14', 'channel_15')
            widget.selection_set(0)
            self.root.lift()
            for state, target in (('selected', widget), ('blurred', entry), ('refocused', widget)):
                with self.subTest(theme=theme, state=state):
                    target.focus_force()
                    self.root.update()
                    # Allow native activation and WM_PAINT to finish before
                    # reading the actual child-window client pixels.
                    self.root.after(50, self.root.quit)
                    self.root.mainloop()
                    tree = widget._tree
                    self.assertEqual(widget.curselection(), (0,))
                    self.assertEqual(self.root.focus_get(), tree if target is widget else target)
                    self.assertEqual(widget.cget('highlightbackground'), a.COLOR_PRIMARY if target is widget else a.COLOR_BORDER)
                    dc = user32.GetDC(tree.winfo_id())
                    self.assertTrue(dc)
                    try:
                        for x in (1, tree.winfo_width()//2, tree.winfo_width()-2):
                            for y in (0, 1, widget.row_height//2, widget.row_height-2, widget.row_height-1):
                                self.assertEqual(gdi32.GetPixel(dc, x, y), expected, (theme, state, x, y))
                    finally:
                        user32.ReleaseDC(tree.winfo_id(), dc)
            widget.destroy()
            entry.destroy()

    def test_main_ui_normal_and_minimum_sizes_show_text_buttons_and_last_row(self):
        import test_resource_options as resources
        configure_theme = a.LineCheckAssistant._configure_theme
        for theme in ('vista', 'clam'):
            with self.subTest(theme=theme):
                def configure(root):
                    configure_theme(root)
                    tk.ttk.Style(root).theme_use(theme)

                fixture = resources.ResourceOptionsTkTests()
                try:
                    with patch.object(a.LineCheckAssistant, '_configure_theme', configure):
                        fixture.setUp()
                    root = fixture.root
                    lb = root.channel_list
                    lb.delete(0, tk.END)
                    for i in range(1, 17):
                        lb.insert(tk.END, f'☑ channel_{i}  VLAN{100+i} / COM{i}')
                    root.deiconify()
                    for size in ('1200x780', '1040x700'):
                        root.geometry(size)
                        root.update()
                        for index in range(16):
                            lb.see(index)
                            root.update()
                            x, y, w, h = lb.bbox(index)
                            self.assertGreaterEqual(y, 0)
                            self.assertLessEqual(y+h, lb._tree.winfo_height())
                            self.assertLessEqual(x+w, lb._tree.winfo_width())
                        buttons = [w for w in fixture.descendants(lb.master) if isinstance(w, tk.ttk.Button)]
                        self.assertEqual(len(buttons), 2)
                        for button in buttons:
                            self.assertTrue(button.winfo_ismapped())
                            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), root.winfo_rooty()+root.winfo_height())
                        self.assertEqual(lb.curselection(), ())
                finally:
                    fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
