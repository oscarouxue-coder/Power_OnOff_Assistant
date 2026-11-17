"""Visual-only Tk proposal; no app imports, project files or device connections."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import struct
import tkinter as tk
from tkinter import ttk
import zlib


BG = '#eef2f5'
WHITE = '#ffffff'
TEXT = '#17202a'
MUTED = '#52606d'
BLUE = '#2563eb'
SELECTED = '#e8efff'
TEAL = '#0f766e'
NAVIGATION = ('检查并执行测试', '自动上/下电', '样机升级', '写样机参数',
              'ONU注册', '串口日志', 'DUT配置', '测试项配置', 'AI诊断')


class LayoutPreview(tk.Tk):
    def __init__(self, size='1280x800', scale=1.0, offscreen=False):
        super().__init__()
        self.withdraw()
        self.title('LineCheckAssistant · 工作区布局预览（模拟数据）')
        self.configure(background=BG)
        self.tk.call('tk', 'scaling', 96 / 72 * scale)
        self.geometry(size + ('+20000+20000' if offscreen else '+40+40'))
        self.minsize(1100, 720)
        self.scale = scale
        self.selected = 0
        self.cards = []
        self.sidebar_visible = True
        self.status = tk.StringVar(self, '')
        self.names = ['光猫 A · 稳定性测试', '路由器 B · 升级验证', '光猫 C · 环境准备']
        self.states = ['运行中 · 4 个通道', '升级中 · 2 台', '空闲 · 有未保存修改']
        self._build()
        self.deiconify()

    def label(self, parent, text='', *, size=10, bold=False, color=TEXT, **kw):
        return tk.Label(parent, text=text, font=('Microsoft YaHei UI', size,
                        'bold' if bold else 'normal'), foreground=color,
                        background=parent.cget('background'), borderwidth=0, **kw)

    def action(self, parent, text, command, *, color=TEXT, size=10):
        return tk.Button(parent, text=text, command=command, relief='flat',
                         borderwidth=0, highlightthickness=0,
                         background=parent.cget('background'), foreground=color,
                         activebackground=SELECTED, activeforeground=BLUE,
                         font=('Microsoft YaHei UI', size), cursor='hand2',
                         padx=7, pady=5, takefocus=True)

    def report(self, text):
        self.status.set('预览：' + text + '（仅模拟反馈）')

    def _build(self):
        self.topbar = tk.Frame(self, background=WHITE, padx=18, pady=9)
        self.topbar.pack(fill='x')
        self.app_title = self.label(self.topbar, 'LineCheckAssistant · 多项目工作区',
                                    size=14, bold=True)
        self.app_title.pack(side='left')
        self.top_actions = tk.Frame(self.topbar, background=WHITE)
        self.top_actions.pack(side='right')
        self.toggle = self.action(self.top_actions, '☰', self.toggle_sidebar)
        self.toggle.pack(side='left', padx=(0, 4))
        self.menu = tk.Menu(self, tearoff=False)
        for index, name in enumerate(self.names):
            self.menu.add_command(label=name, command=lambda i=index: self.select(i))
        self.menu.add_separator()
        for text in ('新建项目…', '打开项目…', '最近项目', '另存为 / 复制项目…', '重命名项目…'):
            self.menu.add_command(label=text, command=lambda t=text: self.report(t))
        self.project_button = self.action(self.top_actions, '项目 ▾', self.open_menu)
        self.project_button.pack(side='left', padx=3)
        for text in ('保存', 'AI / 远程接入', '更新'):
            self.action(self.top_actions, text, lambda t=text: self.report(t)).pack(side='left', padx=3)

        self.status_label = self.label(self, color=MUTED, anchor='w')
        self.status_label.configure(textvariable=self.status)
        self.status_label.pack(side='bottom', fill='x', padx=16)
        self.body = tk.Frame(self, background=BG)
        self.body.pack(fill='both', expand=True, padx=16, pady=(16, 8))
        self.sidebar = tk.Frame(self.body, background=WHITE, width=230)
        self.sidebar.pack(side='left', fill='y', padx=(0, 16))
        self.sidebar.pack_propagate(False)
        side_header = tk.Frame(self.sidebar, background=WHITE, padx=14, pady=12)
        side_header.pack(fill='x')
        self.label(side_header, '项目', size=12, bold=True).pack(side='left')
        self.action(side_header, '＋ 新建', lambda: self.report('新建项目'), color=BLUE).pack(side='right')
        for index, (name, state) in enumerate(zip(self.names, self.states)):
            card = tk.Frame(self.sidebar, background=WHITE, padx=12, pady=12,
                            highlightthickness=1, highlightbackground=WHITE, takefocus=True)
            card.pack(fill='x', padx=10, pady=(0, 6))
            title = self.label(card, name + (' *' if index == 2 else ''), size=11,
                               bold=index == 0, anchor='w', justify='left', wraplength=184)
            title.pack(fill='x')
            state_label = self.label(card, ('●  ' if index < 2 else '') + state, size=9,
                                     color=(TEAL, BLUE, MUTED)[index], anchor='w',
                                     wraplength=184, justify='left')
            state_label.pack(fill='x', pady=(10, 0))
            self.cards.append((card, title, state_label))
            for widget in (card, title, state_label):
                widget.bind('<Button-1>', lambda event, i=index: self.select(i))
                widget.bind('<Button-3>', lambda event, i=index: self.context_menu(event, i))
            card.bind('<Return>', lambda event, i=index: self.select(i))
        side_footer = tk.Frame(self.sidebar, background=WHITE, padx=8, pady=10)
        side_footer.pack(side='bottom', fill='x')
        self.action(side_footer, '打开已有项目…', lambda: self.report('打开已有项目'),
                    color=BLUE, size=9).pack(side='left')
        self.action(side_footer, '最近 ▾', self.open_menu, color=BLUE, size=9).pack(side='right')

        self.content = tk.Frame(self.body, background=BG)
        self.content.pack(fill='both', expand=True)
        self.header = tk.Frame(self.content, background=WHITE, padx=18, pady=12)
        self.header.pack(fill='x', pady=(0, 16))
        self.project_title = self.label(self.header, size=14, bold=True,
                                        anchor='w', justify='left')
        self.project_title.pack(fill='x')
        self.nav = tk.Frame(self.header, background=WHITE)
        self.nav.pack(fill='x', pady=(5, 0))
        self.nav_buttons = [self.action(self.nav, text, lambda t=text: self.report(t),
                                       color=MUTED, size=9) for text in NAVIGATION]
        self.nav.bind('<Configure>', self.reflow)
        self.header.bind('<Configure>', lambda event: self.project_title.configure(
            wraplength=max(100, event.width - 36)))
        self._build_context()
        self.select(0)
        self.bind('<Control-s>', lambda event: self.report('保存当前项目'))

    def _build_context(self):
        # Existing form structure shown only as context; outside the red-box change.
        context = tk.Frame(self.content, background=BG)
        context.pack(fill='both', expand=True)
        channels = tk.Frame(context, background=WHITE, padx=18, pady=16, width=270)
        channels.pack(side='left', fill='y', padx=(0, 16))
        channels.pack_propagate(False)
        self.label(channels, '1  选择测试通道', size=12, bold=True).pack(anchor='w', pady=(0, 12))
        self.channel_vars = []
        for i in range(1, 5):
            variable = tk.BooleanVar(self, value=i <= 4)
            self.channel_vars.append(variable)
            tk.Checkbutton(channels, text=f'通道 {i}   VLAN{100+i} / COM{i}',
                           variable=variable, font=('Microsoft YaHei UI', 10),
                           background=WHITE, activebackground=WHITE, foreground=TEXT,
                           borderwidth=0, highlightthickness=0, anchor='w',
                           justify='left', wraplength=224,
                           command=lambda: self.report('通道选择')).pack(fill='x', pady=5)
        self.form_viewport = tk.Frame(context, background=BG)
        self.form_viewport.pack(fill='both', expand=True)
        self.form_scrollbar = ttk.Scrollbar(self.form_viewport, orient='vertical')
        self.form_scrollbar.pack(side='right', fill='y')
        self.form_canvas = tk.Canvas(self.form_viewport, background=BG,
                                     borderwidth=0, highlightthickness=0,
                                     yscrollcommand=self.form_scrollbar.set)
        self.form_canvas.pack(fill='both', expand=True)
        self.form_scrollbar.configure(command=self.form_canvas.yview)
        self.form_column = tk.Frame(self.form_canvas, background=BG)
        self.form_canvas_item = self.form_canvas.create_window(0, 0, anchor='nw', window=self.form_column)
        self.form_canvas.bind('<Configure>', lambda event: self.form_canvas.itemconfigure(
            self.form_canvas_item, width=event.width))
        self.form_column.bind('<Configure>', lambda event: self.form_canvas.configure(
            scrollregion=self.form_canvas.bbox('all')))
        self.form = tk.Frame(self.form_column, background=WHITE, padx=18, pady=16)
        self.form.pack(fill='x', pady=(0, 16))
        self.label(self.form, '2  配置测试参数', size=12, bold=True).pack(anchor='w')
        self.label(self.form, '修改自动保存', color=MUTED, size=9).pack(anchor='w', pady=(2, 6))
        self.parameters = tk.Frame(self.form, background=WHITE)
        self.parameters.pack(fill='x')
        self.label(self.parameters, '程控电源串口').grid(row=0, column=0, sticky='w', pady=4)
        ttk.Combobox(self.parameters, values=['COM102'], state='readonly', width=12).grid(
            row=0, column=1, sticky='ew', padx=(8, 0))
        self.parameters.winfo_children()[-1].set('COM102')
        self.label(self.parameters, '样机管理 IP').grid(row=1, column=0, sticky='w', pady=4)
        address = ttk.Entry(self.parameters, width=16)
        address.insert(0, '192.168.1.1')
        address.grid(row=1, column=1, sticky='ew', padx=(8, 0))
        self.parameters.columnconfigure(1, weight=1)
        self.table = tk.Frame(self.form, background=WHITE)
        self.table.pack(fill='x', pady=(6, 0))
        for column, title in enumerate(('通道', 'VLAN', 'COM')):
            self.label(self.table, title, color=MUTED, size=9).grid(row=0, column=column, sticky='w', pady=5)
            self.table.columnconfigure(column, weight=1)
        for row in range(1, 5):
            for column, text in enumerate((f'通道 {row}', f'VLAN{100+row} [Up]', f'COM{row}')):
                self.label(self.table, text).grid(row=row, column=column, sticky='w', pady=2)
        self._build_run_card()
        self.utility = tk.Frame(self.form_column, background=BG)
        self.utility.pack(fill='x', pady=(0, 6))
        self.label(self.utility, '管理员权限已就绪', color=TEAL, size=9).pack(side='left')
        self.action(self.utility, '刷新串口/网卡', lambda: self.report('刷新串口/网卡'),
                    color=MUTED, size=9).pack(side='right')
        log = self.log_card = tk.Frame(self.form_column, background=WHITE, padx=18, pady=14)
        log.pack(fill='both', expand=True)
        self.label(log, '执行日志', size=12, bold=True).pack(anchor='w')
        self.log_text = self.label(log, '10:02:08  [光猫 A] 已启动测试，配置版本已固定\n\n'
                                       '10:02:09  [光猫 A] 通道 1 · 第 36 轮开始',
                                   color=MUTED, size=9, justify='left', anchor='nw')
        self.log_text.pack(fill='both', expand=True, pady=(14, 0))
        log.bind('<Configure>', lambda event: self.log_text.configure(wraplength=max(100, event.width - 36)))

    def _build_run_card(self):
        self.run_card = tk.Frame(self.form_column, background=WHITE, padx=18, pady=12)
        self.run_card.pack(fill='x', pady=(0, 12))
        self.run_title = self.label(self.run_card, '3  环境检查与开关机测试',
                                    size=12, bold=True, anchor='w', justify='left')
        self.run_title.pack(fill='x')
        self.run_status = self.label(self.run_card, color=TEAL, size=9,
                                     anchor='w', justify='left')
        self.run_status.pack(fill='x', pady=(5, 3))
        self.run_progress = ttk.Progressbar(self.run_card, maximum=100, value=36)
        self.run_progress.pack(fill='x')
        self.run_overview = self.label(self.run_card, size=9, color=MUTED,
                                       anchor='w', justify='left')
        self.run_overview.pack(fill='x', pady=(4, 0))
        self.run_actions = tk.Frame(self.run_card, background=WHITE)
        self.run_actions.pack(fill='x', pady=(5, 0))
        self.run_start = self.action(self.run_actions, '检查并执行测试',
                                     lambda: self.report('检查并执行测试'), color=TEAL, size=9)
        self.run_start.pack(side='right')
        self.run_stop = self.action(self.run_actions, '停止测试',
                                    lambda: self.report('停止测试'), color=MUTED, size=9)
        self.run_stop.pack(side='right', padx=(0, 8))
        self.run_card.bind('<Configure>', self.wrap_run_card)

    def wrap_run_card(self, event=None):
        width = max(100, self.run_card.winfo_width() - 36)
        for label in (self.run_title, self.run_status, self.run_overview):
            label.configure(wraplength=width)

    def reveal(self, widget):
        self.update_idletasks()
        self.form_canvas.yview_moveto(widget.winfo_y() / max(1, self.form_column.winfo_height()))
        self.update_idletasks()

    def select(self, index):
        self.selected = index
        self.project_title.configure(text=self.names[index] + (' *' if index == 2 else ''))
        active = index == 0
        self.run_status.configure(text=('开关机测试状态：运行中    开关机测试进度：第 36 / 100 轮'
                                        if active else '开关机测试状态：未运行    开关机测试进度：等待开始'))
        self.run_progress.configure(value=36 if active else 0)
        self.run_overview.configure(text=('通道 1 通过 · 通道 2 通过 · 通道 3 执行中 · 通道 4 等待'
                                          if active else '通道概览：等待开始'))
        self.run_stop.configure(state='normal' if active else 'disabled')
        for i, (card, title, state) in enumerate(self.cards):
            background = SELECTED if i == index else WHITE
            card.configure(background=background, highlightbackground=background)
            title.configure(background=background, font=('Microsoft YaHei UI', 11,
                                                                        'bold' if i == index else 'normal'))
            state.configure(background=background)
        self.status.set('')

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        if self.sidebar_visible:
            self.sidebar.pack(side='left', fill='y', padx=(0, 16), before=self.content)
        else:
            self.sidebar.pack_forget()

    def open_menu(self):
        self.menu.tk_popup(self.project_button.winfo_rootx(),
                           self.project_button.winfo_rooty() + self.project_button.winfo_height())

    def context_menu(self, event, index):
        self.select(index)
        self.menu.tk_popup(event.x_root, event.y_root)

    def reflow(self, event=None):
        width = self.nav.winfo_width()
        row, column, occupied = 0, 0, 0
        for button in self.nav_buttons:
            requested = button.winfo_reqwidth() + 3
            if column and occupied + requested > width:
                row, column, occupied = row + 1, 0, 0
            button.grid(row=row, column=column, sticky='w', padx=(0, 3))
            occupied += requested
            column += 1


def capture_client(window, output):
    """Capture this preview's own native window via WM_PRINT, without screen input."""
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT,
                              wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    hwnd = user.GetParent(window.winfo_id())
    width, height = window.winfo_width(), window.winfo_height()
    dc = user.GetDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc, width, height)
    old = gdi.SelectObject(memory, bitmap)
    try:
        if not user.PrintWindow(hwnd, memory, 3):
            raise RuntimeError('Native preview capture failed')
        gdi.SelectObject(memory, old)
        info = struct.pack('<IiiHHIIiiII', 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        buffer = ctypes.create_string_buffer(width * height * 4)
        if gdi.GetDIBits(memory, bitmap, 0, height, buffer, info, 0) != height:
            raise RuntimeError('Native preview bitmap read failed')
        raw = buffer.raw
        if len(set(raw)) < 8:
            raise RuntimeError('Native preview capture was blank; no image was written')
        rows = []
        for y in range(height):
            bgra = raw[y * width * 4:(y + 1) * width * 4]
            rgb = bytearray(width * 3)
            rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
            rows.append(b'\0' + rgb)
        def chunk(kind, payload):
            return struct.pack('!I', len(payload)) + kind + payload + struct.pack('!I', zlib.crc32(kind + payload))
        png = b'\x89PNG\r\n\x1a\n'
        png += chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress(b''.join(rows))) + chunk(b'IEND', b'')
        Path(output).write_bytes(png)
    finally:
        gdi.SelectObject(memory, old)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd, dc)


def check_layout(window):
    window.update()
    window.reflow()
    window.update_idletasks()
    for button in window.nav_buttons:
        assert button.winfo_ismapped(), button.cget('text')
        assert button.winfo_x() + button.winfo_width() <= window.nav.winfo_width(), button.cget('text')
    assert window.app_title.winfo_rootx() + window.app_title.winfo_width() <= window.top_actions.winfo_rootx()
    assert window.header.winfo_y() + window.header.winfo_height() <= window.content.winfo_height()
    assert window.parameters.winfo_width() >= window.parameters.winfo_reqwidth()
    assert window.form.winfo_y() < window.run_card.winfo_y() < window.log_card.winfo_y()
    assert window.run_title.cget('text') == '3  环境检查与开关机测试'
    window.reveal(window.run_card)
    for widget in (window.run_title, window.run_status, window.run_progress,
                   window.run_start, window.run_stop):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() >= window.form_canvas.winfo_rooty()
        assert widget.winfo_rooty() + widget.winfo_height() <= (
            window.form_canvas.winfo_rooty() + window.form_canvas.winfo_height())
    window.run_stop.invoke()
    assert '停止测试' in window.status.get()
    window.reveal(window.log_card)
    assert window.log_text.winfo_rooty() < window.form_canvas.winfo_rooty() + window.form_canvas.winfo_height()
    window.form_canvas.yview_moveto(0)
    window.toggle_sidebar()
    window.update()
    assert not window.sidebar.winfo_manager()
    window.select(1)
    assert window.selected == 1
    assert window.run_stop.cget('state') == 'disabled'
    assert '未运行' in window.run_status.cget('text')
    window.toggle_sidebar()
    window.select(0)
    window.update()
    assert window.cards[0][0].cget('background') == SELECTED
    assert window.run_stop.cget('state') == 'normal'
    assert window.run_progress.cget('value') == 36
    window.select(2)
    assert window.project_title.cget('text').endswith(' *')
    window.names[2] = '这是一个用于核对换行和完整显示的较长项目名称 · 环境准备与并行测试'
    window.select(2)
    window.update()
    assert window.project_title.winfo_reqheight() <= window.project_title.winfo_height()
    window.select(0)
    return {'size': [window.winfo_width(), window.winfo_height()], 'font_scale': window.scale,
            'navigation_rows': max(int(button.grid_info()['row']) for button in window.nav_buttons) + 1,
            'result': 'PASS'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--size', default='1280x800')
    parser.add_argument('--scale', type=float, default=1.0)
    parser.add_argument('--show-run-card', action='store_true')
    args = parser.parse_args()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    if args.check:
        results = []
        for scale in (1.0, 1.5):
            for size in ('1280x800', '1100x720'):
                window = LayoutPreview(size, scale, offscreen=True)
                try:
                    results.append(check_layout(window))
                finally:
                    window.destroy()
        print(json.dumps(results, ensure_ascii=False))
        return
    window = LayoutPreview(args.size, args.scale)
    if args.capture:
        try:
            window.after(500, window.quit)
            window.mainloop()
            window.reflow()
            window.update()
            if args.show_run_card:
                window.reveal(window.run_card)
                window.update()
            capture_client(window, args.capture)
            print(json.dumps({'capture': str(args.capture), 'size': args.size,
                              'font_scale': args.scale,
                              'show_run_card': args.show_run_card}, ensure_ascii=False))
        finally:
            window.destroy()
    else:
        if args.show_run_card:
            window.after_idle(lambda: window.reveal(window.run_card))
        window.mainloop()


if __name__ == '__main__':
    main()
