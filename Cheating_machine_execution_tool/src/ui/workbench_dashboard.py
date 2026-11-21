"""Read-only workspace overview; all runtime values come from WorkspaceService."""
import tkinter as tk
from tkinter import ttk

from src.models.project_status import ProjectStatus
from src.ui.module_theme import MODULE_BACKGROUND


class WorkbenchDashboard(tk.Frame):
    def __init__(self, parent, *, select_project, new_project, open_project):
        super().__init__(parent, background=MODULE_BACKGROUND)
        style = ttk.Style(self)
        style.configure('Workbench.Surface.TFrame', background='#ffffff')
        style.configure('Workbench.Title.TLabel', background=MODULE_BACKGROUND, foreground='#17313c',
                        font=('Microsoft YaHei UI', 16, 'bold'))
        header = tk.Frame(self, background=MODULE_BACKGROUND, pady=10)
        header.pack(fill='x')
        tk.Label(header, text='总览工作台', background=MODULE_BACKGROUND, foreground='#17313c',
                 font=('Microsoft YaHei UI', 16, 'bold')).pack(side='left')
        ttk.Button(header, text='＋ 新建项目', command=new_project, style='Primary.TButton').pack(side='right')
        ttk.Button(header, text='打开项目…', command=open_project, style='Tool.TButton').pack(side='right', padx=8)
        ttk.Button(header, text='列表', command=lambda: self.set_mode('list'), style='Tool.TButton').pack(side='right')
        ttk.Button(header, text='卡片', command=lambda: self.set_mode('cards'), style='Tool.TButton').pack(side='right', padx=4)
        self.metrics = tk.StringVar(self)
        metrics = tk.Frame(self, background=MODULE_BACKGROUND)
        metrics.pack(fill='x', pady=12)
        self.metric_values = []
        for index, (title, color) in enumerate((('已打开项目', '#17313c'), ('运行/收尾中', '#078239'),
                                                ('需关注', '#c73434'), ('结果未知项目', '#a16207'))):
            metrics.columnconfigure(index, weight=1, uniform='metric')
            tile = tk.Frame(metrics, background='#ffffff', highlightthickness=1, highlightbackground='#d5dfe5', padx=12, pady=10)
            tile.grid(row=0, column=index, sticky='ew', padx=(0, 8))
            tk.Label(tile, text=title, background='#ffffff', foreground='#65717f', anchor='w').pack(fill='x')
            variable = tk.StringVar(self, value='0')
            tk.Label(tile, textvariable=variable, background='#ffffff', foreground=color,
                     font=('Microsoft YaHei UI', 19, 'bold'), anchor='w').pack(fill='x')
            self.metric_values.append(variable)
        tk.Label(self, text='▎项目运行情况', background=MODULE_BACKGROUND, foreground='#17313c',
                 font=('Microsoft YaHei UI', 11, 'bold'), anchor='w').pack(fill='x', pady=(0, 10))
        self.cards_view = tk.Frame(self, background=MODULE_BACKGROUND)
        self.cards_view.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(self.cards_view, background=MODULE_BACKGROUND, highlightthickness=0)
        card_scroll = ttk.Scrollbar(self.cards_view, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=card_scroll.set)
        card_scroll.pack(side='right', fill='y')
        self.canvas.pack(fill='both', expand=True)
        self.card_area = tk.Frame(self.canvas, background=MODULE_BACKGROUND)
        self.card_window = self.canvas.create_window(0, 0, anchor='nw', window=self.card_area)
        self.canvas.bind('<Configure>', self._reflow)
        self.card_area.bind('<Configure>', lambda event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.cards = {}
        self.order = []
        table = self.table_frame = ttk.Frame(self)
        self.table = ttk.Treeview(table, columns=('state', 'active', 'result'), show='tree headings',
                                  selectmode='browse')
        for key, title, width in (('#0', '项目名称', 240), ('state', '运行状态', 150),
                                  ('active', '活动任务', 85), ('result', '最近结果', 170)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=60, stretch=key in ('#0', 'result'))
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        self.select_project = select_project
        self.table.bind('<Double-Button-1>', self._open)
        self.table.bind('<Return>', self._open)
        self.event_area = tk.Frame(self, background='#ffffff', highlightthickness=1,
                                   highlightbackground='#d5dfe5', padx=12, pady=8)
        self.event_area.pack(fill='x', pady=(10, 0))
        event_header = tk.Frame(self.event_area, background='#ffffff')
        event_header.pack(fill='x')
        tk.Label(event_header, text='▾ 工作区事件', background='#ffffff', foreground='#17313c',
                 font=('Microsoft YaHei UI', 10, 'bold')).pack(side='left')
        self.event_toggle = ttk.Button(event_header, text='收起', command=self.toggle_events, style='Tool.TButton')
        self.event_toggle.pack(side='right')
        self.events = tk.Text(self.event_area, height=5, state='disabled', background='#f9fbfc',
                              foreground='#334155', font=('Consolas', 10), relief='flat', wrap='word')
        self.events.pack(fill='x', pady=(5, 0))
        self.empty = ttk.Label(self, text='尚未打开项目', padding=12)
        self._signature = None
        self.mode = 'cards'
        self.on_mode_changed = lambda mode: None
        self.render([])

    def toggle_events(self):
        if self.events.winfo_manager():
            self.events.pack_forget()
            self.event_toggle.configure(text='展开')
        else:
            self.events.pack(fill='x', pady=(5, 0))
            self.event_toggle.configure(text='收起')

    def append_event(self, text):
        from src.ui.workbench_panels import trim_log_display
        self.events.configure(state='normal')
        self.events.insert('end', text + '\n')
        trim_log_display(self.events, max_lines=500, max_chars=128 * 1024)
        self.events.configure(state='disabled')
        self.events.see('end')

    def set_mode(self, mode):
        self.mode = 'list' if mode == 'list' else 'cards'
        self.cards_view.pack_forget()
        self.table_frame.pack_forget()
        area = self.table_frame if self.mode == 'list' else self.cards_view
        area.pack(fill='both', expand=True, before=self.event_area)
        self.on_mode_changed(self.mode)

    def _reflow(self, event=None):
        width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self.card_window, width=width)
        from tkinter import font
        card_minimum = font.Font(root=self, name='TkDefaultFont', exists=True).measure('0') * 38 + 40
        columns = max(1, min(len(self.order) or 1, 4, int(width // card_minimum)))
        for column in range(4):
            self.card_area.columnconfigure(column, weight=1 if column < columns else 0,
                                           uniform='card' if column < columns else '')
        for index, key in enumerate(self.order):
            card = self.cards[key][0]
            card.grid(row=index // columns, column=index % columns, sticky='nsew', padx=(0, 10), pady=(0, 12))
            for label in card.winfo_children():
                if isinstance(label, tk.Label):
                    label.configure(wraplength=max(100, width // columns - 52))

    def _open(self, event=None):
        if event is not None and getattr(event, 'num', None) == 1:
            identifier = self.table.identify_row(event.y)
            if not identifier:
                return
        else:
            selection = self.table.selection()
            identifier = selection[0] if selection else None
        if identifier:
            self.select_project(identifier)

    def render(self, projects):
        # No counters survive a refresh, and no status is inferred from selection.
        signature = repr(projects)
        if signature == self._signature:
            return
        self._signature = signature
        running = sum(row['state'] in ('running', 'stopping') for row in projects)
        unknown = sum(bool(row['unknown_task_count']) for row in projects)
        attention = sum(row['state'] in ('failed', 'unknown') or row['unknown_task_count'] > 0 or
                        row['last_result'] == 'failed' for row in projects)
        self.metrics.set(f'已打开项目  {len(projects)}     运行/收尾中  {running}     '
                         f'需关注  {attention}     结果未知项目  {unknown}')
        for variable, value in zip(self.metric_values, (len(projects), running, attention, unknown)):
            variable.set(str(value))
        keys = {row['project_id'] for row in projects}
        for key in self.table.get_children():
            if key not in keys:
                self.table.delete(key)
                self.cards.pop(key)[0].destroy()
        result_labels = {'succeeded': '成功完成', 'failed': '执行失败', 'stopped': '主动停止',
                         'unknown': '结果未知', 'unchecked': '未配置结果校验', 'skipped': '未执行'}
        ordered = sorted(projects, key=lambda row: (0 if row['state'] in ('failed', 'unknown') or
                         row['unknown_task_count'] or row['last_result'] == 'failed' else
                         1 if row['state'] in ('running', 'stopping') else 2, row['name'].casefold()))
        self.order = [row['project_id'] for row in ordered]
        for index, row in enumerate(ordered):
            state = ProjectStatus(**{key: row[key] for key in ('state', 'active_task_count',
                                    'unknown_task_count', 'last_result', 'updated_at')})
            result = result_labels.get(state.last_result, '—')
            if state.last_result == 'unknown' and not state.unknown_task_count:
                result = '已核实（原结果未知）'
            values = (state.label, state.active_task_count, result)
            key = row['project_id']
            if key not in self.cards:
                card = tk.Frame(self.card_area, background='#ffffff', highlightthickness=1,
                                highlightbackground='#b6d6cf', padx=14, pady=12)
                variables = [tk.StringVar(self) for _ in range(5)]
                for n, variable in enumerate(variables):
                    tk.Label(card, textvariable=variable, background='#ffffff', foreground='#17313c' if n == 0 else '#65717f',
                             anchor='w', justify='left', font=('Microsoft YaHei UI', 11 if n == 0 else 9,
                             'bold' if n == 0 else 'normal')).pack(fill='x', pady=(0, 8))
                badge = tk.Label(card, background='#e8f5ef', foreground='#047857', anchor='w', padx=6, pady=3)
                badge.pack(fill='x')
                progress = ttk.Progressbar(card, maximum=1)
                ttk.Button(card, text='查看详情  ›', command=lambda identifier=key: self.select_project(identifier),
                           style='Tool.TButton').pack(anchor='e', pady=(8, 0))
                self.cards[key] = card, variables, badge, progress
            card, variables, badge, progress = self.cards[key]
            for variable, value in zip(variables, (row['name'], row.get('task_label', '项目任务'),
                    row.get('progress_text', '尚无开关机轮次数据'), row.get('channel_text', '尚无通道检测结果'),
                    row.get('started_text', '尚无开始时间'))):
                variable.set(value)
            danger = state.unknown_task_count or state.last_result == 'failed'
            badge.configure(text='● ' + state.label + '  ·  最近结果：' + result,
                            foreground='#b42318' if danger else '#047857' if state.state == 'running' else '#65717f',
                            background='#fbe9e7' if danger else '#e8f5ef' if state.state == 'running' else '#f1f5f9')
            card.configure(highlightbackground='#e9a2a2' if danger else '#b6d6cf')
            if row.get('fraction') is None:
                progress.pack_forget()
            else:
                progress.pack(fill='x', pady=8, before=card.winfo_children()[-1])
                progress.configure(value=row['fraction'])
            if self.table.exists(key):
                self.table.item(key, text=row['name'], values=values)
                self.table.move(key, '', index)
            else:
                self.table.insert('', index, iid=key, text=row['name'], values=values)
        if projects:
            self.empty.pack_forget()
        else:
            self.empty.pack(anchor='w')
        self._reflow()
