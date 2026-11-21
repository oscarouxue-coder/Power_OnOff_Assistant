"""Layout-only containers for existing project controls and log widgets."""
import tkinter as tk
from tkinter import ttk

from src.ui.module_theme import MODULE_BACKGROUND


def trim_log_display(widget, *, max_lines=5000, max_chars=1024 * 1024):
    """Bound only the visible Text tail; the caller retains its complete log file."""
    lines = int(widget.index('end-1c').split('.')[0])
    if lines > max_lines:
        widget.delete('1.0', f'{lines - max_lines + 1}.0')
    chars = (widget.count('1.0', 'end-1c', 'chars') or (0,))[0]
    if chars > max_chars:
        widget.delete('1.0', f'1.0 + {chars - max_chars} chars')


def wrap_navigation(toolbar):
    """Use independent grid rows, retaining the original controls and commands."""
    widgets = toolbar.winfo_children()
    toolbar._navigation_widgets = tuple(widgets)
    for widget in widgets:
        widget.pack_forget()
    previous = []
    rows = []
    toolbar.columnconfigure(0, weight=1)
    def arrange(event):
        groups, group, used = [], [], 0
        for widget in widgets:
            width = widget.winfo_reqwidth() + 8
            if used and used + width > event.width:
                groups.append(group)
                group, used = [], 0
            group.append(widget)
            used += width
        if group:
            groups.append(group)
        signature = [tuple(map(str, group)) for group in groups]
        if signature == previous:
            return
        previous[:] = signature
        for widget in widgets:
            widget.grid_forget()
        for row in rows:
            row.grid_remove()
        for index, group in enumerate(groups):
            if index == len(rows):
                rows.append(ttk.Frame(toolbar, style='Surface.TFrame'))
            rows[index].grid(row=index, column=0, sticky='w')
            for column, widget in enumerate(group):
                widget.grid(in_=rows[index], row=0, column=column, sticky='w', padx=(0, 8), pady=2)
                widget.lift()
    toolbar.bind('<Configure>', arrange, add='+')


class ScrollColumn(tk.Frame):
    """A width-constrained, vertically scrolling column with local wheel routing."""
    def __init__(self, parent, *, changed=lambda: None):
        super().__init__(parent, background=MODULE_BACKGROUND)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=MODULE_BACKGROUND, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.scroll.grid(row=0, column=1, sticky='ns')
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.content = ttk.Frame(self.canvas, style='App.TFrame')
        self.window_id = self.canvas.create_window(0, 0, anchor='nw', window=self.content)
        self.changed = changed
        self.canvas.bind('<Configure>', self._resize)
        self.content.bind('<Configure>', self._resize)

    def _resize(self, event=None):
        width = self.canvas.winfo_width()
        if int(float(self.canvas.itemcget(self.window_id, 'width'))) != width:
            self.canvas.itemconfigure(self.window_id, width=width)
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        self._wheel_bindings(self)
        self.changed()

    def _wheel_bindings(self, widget):
        if not vars(widget).get('_workbench_wheel_bound'):
            widget._workbench_wheel_bound = True
            if widget.winfo_class() not in ('Text', 'Treeview', 'TCombobox', 'TSpinbox') and '_tree' not in vars(widget):
                widget.bind('<MouseWheel>', self._wheel, add='+')
        for child in widget.winfo_children():
            self._wheel_bindings(child)

    def _wheel(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')
        return 'break'


class WorkbenchPanels(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, background=MODULE_BACKGROUND)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.config_area = ScrollColumn(self)
        self.config_area.grid(row=0, column=1, sticky='nsew', padx=(12, 0))
        self.config_canvas = self.config_area.canvas
        self.config_content = self.config_area.content
        self.config_window = self.config_area.window_id
        self.panes = tk.PanedWindow(self, orient='vertical', sashwidth=7, sashrelief='flat',
                                   background=MODULE_BACKGROUND, borderwidth=0)
        self.panes.grid(row=0, column=0, sticky='nsew')
        top = tk.Frame(self.panes, background=MODULE_BACKGROUND)
        self.main_host = top
        top.grid_propagate(False)
        self.panes.add(top, minsize=140, stretch='always')
        self.action_host = ttk.Frame(top, style='Surface.TFrame', padding=(12, 8))
        self.action_host.grid(row=0, column=0, sticky='ew', columnspan=2)
        top.rowconfigure(1, weight=1)
        top.columnconfigure(0, weight=1)
        self.main_scroll = ScrollColumn(top, changed=self._fit_sash)
        self.main_scroll.grid(row=1, column=0, sticky='nsew')
        self.canvas, self.content = self.main_scroll.canvas, self.main_scroll.content
        self.window_id = self.main_scroll.window_id
        self.log_host = ttk.Frame(self.panes, style='Surface.TFrame')
        self.log_host.pack_propagate(False)
        self.panes.add(self.log_host, minsize=120, stretch='always')
        self.config_visible = True
        self.log_visible = True
        self._user_sash = False
        self.bind('<Configure>', self._layout)
        self.panes.bind('<Map>', self._fit_sash)
        self.panes.bind('<ButtonPress-1>', self._sash_press)

    def _layout(self, event):
        from tkinter import font
        minimum = font.Font(root=self, name='TkDefaultFont', exists=True).measure('0') * 34 + 32
        width = min(minimum, max(200, event.width * .34))
        if vars(self).get('_config_width') != int(width):
            self._config_width = int(width)
            self.columnconfigure(1, minsize=int(width))
        self._fit_sash()

    def _sash_press(self, event):
        if self.panes.identify(event.x, event.y):
            self._user_sash = True

    def _fit_sash(self, event=None):
        if self._user_sash or not self.log_visible or not self.panes.winfo_ismapped():
            return
        height = self.panes.winfo_height()
        if height < 200:
            return
        key = height, self.content.winfo_reqheight(), self.action_host.winfo_reqheight()
        if vars(self).get('_sash_layout') == key:
            return
        self._sash_layout = key
        desired = min(int(height * .70), max(140, self.content.winfo_reqheight() + self.action_host.winfo_reqheight()))
        # Set preferred sizes through geometry requests. A synchronous
        # sash_place during layout races Tk's own deferred stretch pass.
        self.main_host.configure(height=desired)
        self.log_host.configure(height=max(120, height - desired - int(self.panes.cget('sashwidth'))))

    def attach_config(self, card, header, bodies, summary):
        self.config_bodies = bodies
        self.summary = summary
        self.config_summary = tk.StringVar(self)
        self.summary_label = ttk.Label(card, textvariable=self.config_summary, style='CardHint.TLabel', wraplength=600)
        self.summary_label.bind('<Configure>', lambda event: self.summary_label.configure(
            wraplength=max(100, event.width - 4)))
        self.config_toggle = ttk.Button(header, text='收起配置', command=self.toggle_config, style='Tool.TButton')
        self.config_toggle.pack(side='right', padx=8)

    def refresh_summary(self):
        if not self.config_visible:
            self.config_summary.set(self.summary())

    def toggle_config(self):
        self.config_visible = not self.config_visible
        if self.config_visible:
            self.summary_label.pack_forget()
            for widget, options in self.config_bodies:
                widget.pack(**options)
        else:
            self.config_summary.set(self.summary())
            for widget, _ in self.config_bodies:
                widget.pack_forget()
            self.summary_label.pack(fill='x', pady=(8, 0))
        self.config_toggle.configure(text='收起配置' if self.config_visible else '编辑配置')

    def attach_log(self, header, body):
        self.log_body = body
        self.log_toggle = ttk.Button(header, text='收起日志', command=self.toggle_log, style='Secondary.TButton')
        self.log_toggle.pack(side='right', padx=8)

    def toggle_log(self):
        self.log_visible = not self.log_visible
        self.log_toggle.configure(text='收起日志' if self.log_visible else '展开日志')
        if self.log_visible:
            self.log_body.pack(fill='both', expand=True)
            self.panes.paneconfigure(self.log_host, minsize=120, height='')
            self._user_sash = False
            self._sash_layout = None
            self._fit_sash()
        else:
            self.log_body.pack_forget()
            self.panes.paneconfigure(self.log_host, minsize=48, height=48)
