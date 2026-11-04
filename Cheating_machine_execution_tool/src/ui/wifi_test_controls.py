"""测试项WiFi页新增选项；只管理控件状态和输入，不执行网络操作。"""
import tkinter as tk
from tkinter import ttk


MODES = {'分别验证频段': 'per_band', '双频合一': 'unified'}


class WifiTestControls:
    def __init__(self, frame, wifi, mark_dirty, band_controls, advanced_widgets, background):
        self.mode = tk.StringVar(master=frame, value=next((k for k, v in MODES.items()
                                if v == wifi.connection_test_mode), wifi.connection_test_mode))
        self.auto = tk.IntVar(master=frame, value=int(wifi.security_source == 'auto'))
        self.ping = tk.IntVar(master=frame, value=int(wifi.wireless_ping_enable))
        self.target = tk.StringVar(master=frame, value=wifi.wireless_ping_target)
        tk.Label(frame, text='连接测试模式', bg=background).grid(row=0, column=2, sticky='w', padx=(24, 12))
        ttk.Combobox(frame, textvariable=self.mode, values=tuple(MODES), state='readonly', width=28).grid(
            row=0, column=3, sticky='w')
        tk.Checkbutton(frame, text='自动识别认证参数', variable=self.auto, onvalue=1, offvalue=0,
                       bg=background, activebackground=background, highlightthickness=0).grid(
            row=3, column=2, columnspan=2, sticky='w', padx=(24, 0))
        ping_frame = tk.Frame(frame, bg=background)
        ping_frame.grid(row=5, column=0, columnspan=4, sticky='w', pady=(12, 4))
        tk.Checkbutton(ping_frame, text='启用无线 Ping', variable=self.ping, onvalue=1, offvalue=0,
                       bg=background, activebackground=background, highlightthickness=0).grid(row=0, column=0)
        tk.Label(ping_frame, text='Ping目标地址', bg=background).grid(row=0, column=1, padx=(20, 8))
        self.target_entry = ttk.Entry(ping_frame, textvariable=self.target, width=38)
        self.target_entry.grid(row=0, column=2)
        tk.Label(frame, text='无线Ping支持IPv4 / 域名；每项4包，至少1个回复通过。',
                 bg=background, wraplength=760, justify='left').grid(
            row=6, column=0, columnspan=4, sticky='w', pady=(4, 0))

        def update(*_args):
            unified = MODES.get(self.mode.get()) == 'unified'
            for widget in band_controls:
                widget.configure(state='disabled' if unified else 'normal')
            for widget in advanced_widgets:
                if self.auto.get():
                    widget.grid_remove()
                else:
                    widget.grid()
            self.target_entry.configure(state='normal' if self.ping.get() else 'disabled')
            mark_dirty()

        self._update = update
        for variable in (self.mode, self.auto, self.ping, self.target):
            variable.trace_add('write', update)
        # 构建本身不标记脏；初始化显示状态与后续变化保持一致。
        for widget in band_controls:
            widget.configure(state='disabled' if MODES.get(self.mode.get()) == 'unified' else 'normal')
        if self.auto.get():
            for widget in advanced_widgets:
                widget.grid_remove()
        self.target_entry.configure(state='normal' if self.ping.get() else 'disabled')

    def capture(self):
        return {'connection_test_mode': MODES.get(self.mode.get(), self.mode.get()),
                'security_source': 'auto' if self.auto.get() else 'manual',
                'wireless_ping_enable': int(self.ping.get()),
                'wireless_ping_target': self.target.get().strip()}

    def load(self, wifi):
        self.mode.set(next((k for k, v in MODES.items() if v == wifi.connection_test_mode), wifi.connection_test_mode))
        self.auto.set(int(wifi.security_source == 'auto'))
        self.ping.set(int(wifi.wireless_ping_enable))
        self.target.set(wifi.wireless_ping_target)
