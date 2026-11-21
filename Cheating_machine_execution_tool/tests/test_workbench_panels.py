import tkinter as tk
from tkinter import ttk
import unittest

from tk_test_windows import install_offscreen_windows
from src.ui.workbench_panels import WorkbenchPanels, trim_log_display


class WorkbenchPanelsTests(unittest.TestCase):
    def setUp(self):
        install_offscreen_windows(self)
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)

    def test_form_wheel_scrolls_the_page_without_editing_values(self):
        from line_check_assistant.app import LineCheckAssistant
        from src.ui.workbench_panels import ScrollColumn

        LineCheckAssistant._configure_theme(self.root)
        dialog = tk.Toplevel(self.root)
        dialog.geometry('310x230')
        page = ScrollColumn(dialog)
        page.pack(fill='both', expand=True)
        values = tuple(str(n) for n in range(80))
        changes = []
        for kind in ('readonly', 'normal', 'spin'):
            variable = tk.StringVar(dialog, '4')
            if kind == 'spin':
                field = ttk.Spinbox(page.content, from_=0, to=79, textvariable=variable)
            else:
                field = ttk.Combobox(page.content, values=values, state=kind, textvariable=variable)
            field.pack()
            variable.trace_add('write', lambda *_: changes.append(True))
            dialog.update()
            spacer = ttk.Frame(page.content, height=700)
            spacer.pack()
            dialog.update()
            for focus in (dialog, field):
                focus.focus_force()
                dialog.update()
                page.canvas.yview_moveto(0)
                field.event_generate('<MouseWheel>', delta=-120)
                self.assertGreater(page.canvas.yview()[0], 0)
                field.event_generate('<MouseWheel>', delta=120)
                self.assertEqual(page.canvas.yview()[0], 0)
                self.assertEqual(field.get(), '4')
                self.assertEqual(changes, [])
            if kind == 'spin':
                field.event_generate('<Up>')
                self.assertEqual(field.get(), '5')
                x, y = field.winfo_width() - 5, field.winfo_height() // 4
                self.assertIn('uparrow', field.identify(x, y))
                field.event_generate('<ButtonPress-1>', x=x, y=y)
                field.event_generate('<ButtonRelease-1>', x=x, y=y)
                self.assertEqual(field.get(), '6')
            else:
                field.tk.call('ttk::combobox::Post', field)
                dialog.update()
                listing = f'{field}.popdown.f.l'
                field.tk.call('event', 'generate', listing, '<MouseWheel>', '-delta', -120)
                self.assertGreater(float(field.tk.call(listing, 'yview')[0]), 0)
                self.assertEqual(field.get(), '4')
                self.assertEqual(changes, [])
                field.tk.call(listing, 'selection', 'clear', 0, 'end')
                field.tk.call(listing, 'selection', 'set', 8)
                field.tk.call('event', 'generate', listing, '<Return>')
                self.assertEqual(field.get(), '8')
            changes.clear()
            spacer.destroy()
            field.destroy()

    def test_high_volume_display_retains_bounded_tail(self):
        text = tk.Text(self.root)
        text.insert('end', ''.join(f'消息 {n}\n' for n in range(12000)))
        trim_log_display(text)
        self.assertLessEqual(int(text.index('end-1c').split('.')[0]), 5000)
        self.assertNotIn('消息 0\n', text.get('1.0', 'end'))
        self.assertIn('消息 11999', text.get('1.0', 'end'))

    def test_large_single_line_and_empty_display_are_bounded(self):
        text = tk.Text(self.root)
        trim_log_display(text)
        text.insert('end', 'x' * 10000 + 'TAIL')
        trim_log_display(text, max_chars=100)
        self.assertEqual(text.get('1.0', 'end-1c'), 'x' * 96 + 'TAIL')

    def test_small_window_scrolls_to_existing_controls_and_logs_resize(self):
        self.root.geometry('500x500')
        panel = WorkbenchPanels(self.root)
        panel.pack(fill='both', expand=True)
        ttk.Label(panel.content, text='existing').pack()
        last = ttk.Button(panel.content, text='existing-last')
        last.pack(pady=(900, 0))
        self.root.update()
        self.assertGreater(panel.content.winfo_height(), panel.canvas.winfo_height())
        panel.canvas.yview_moveto(1)
        self.root.update()
        self.assertAlmostEqual(panel.canvas.yview()[1], 1, places=2)
        position = panel.panes.sash_coord(0)
        panel.panes.event_generate('<ButtonPress-1>', x=10, y=position[1] + 2)
        self.root.update()
        self.assertAlmostEqual(panel.panes.sash_coord(0)[1], position[1], delta=5)
        panel.panes.event_generate('<B1-Motion>', x=10, y=212)
        self.root.update()
        panel.panes.event_generate('<ButtonRelease-1>', x=10, y=212)
        self.root.update()
        self.assertAlmostEqual(panel.panes.sash_coord(0)[1], 210, delta=5)
        ttk.Label(panel.content, text='late status').pack()
        self.root.update()
        self.assertAlmostEqual(panel.panes.sash_coord(0)[1], 210, delta=5)
