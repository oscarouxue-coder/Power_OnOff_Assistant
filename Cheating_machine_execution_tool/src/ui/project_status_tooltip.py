"""On-demand project status details, without persistent explanatory controls."""
import tkinter as tk
from src.ui.module_theme import apply_module_theme


class ProjectStatusTooltip:
    def __init__(self, tree, detail):
        self.tree, self.detail = tree, detail
        self.popup = None
        self.pending = None
        self.row = ''
        tree.bind('<Motion>', self.motion, add='+')
        for event in ('<Leave>', '<ButtonPress>', '<Unmap>', '<Destroy>'):
            tree.bind(event, self.hide, add='+')

    def motion(self, event):
        row = self.tree.identify_row(event.y)
        if row == self.row:
            return
        self.hide()
        self.row = row
        if row:
            self.pending = self.tree.after(400, self.show)

    def show(self):
        self.pending = None
        if not self.row or not self.tree.exists(self.row):
            return
        text = self.detail(self.row)
        self.popup = tk.Toplevel(self.tree)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        tk.Label(self.popup, text=text, justify='left', padx=10, pady=8, wraplength=420).pack()
        apply_module_theme(self.popup)
        self.popup.geometry('+' + str(self.tree.winfo_rootx() + 15) + '+' + str(self.tree.winfo_rooty() + 40))
        self.popup.deiconify()

    def hide(self, event=None):
        if self.pending is not None:
            self.tree.after_cancel(self.pending)
            self.pending = None
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None
        self.row = ''
