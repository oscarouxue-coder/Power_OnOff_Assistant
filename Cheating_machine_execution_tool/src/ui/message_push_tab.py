"""测试项配置中的消息推送页签。"""
import queue
import threading
from tkinter import Checkbutton, Frame, Label, StringVar, ttk, messagebox

from src.services.message_push_config_service import send_test_message


class MessagePushTab:
    def __init__(self, notebook, values, mark_dirty, *, background, foreground, log=lambda message: None):
        self.log = log
        self.running = False
        self.results = queue.Queue()
        self.frame = Frame(notebook, background=background, padx=20, pady=20)
        notebook.add(self.frame, text="消息推送")
        self.variables = {key: StringVar(master=self.frame, value=value)
                          for key, value in values.items()}
        self.frame.columnconfigure(1, weight=1)
        for row, (key, label) in enumerate((
            ("dingtalk_flag", "启用钉钉推送"), ("webhook", "Webhook 地址"),
            ("secret", "加签密钥"), ("at_all", "@所有人"),
        )):
            variable = self.variables[key]
            if key in {"dingtalk_flag", "at_all"}:
                Checkbutton(self.frame, text=label, variable=variable,
                            onvalue="1", offvalue="0", background=background,
                            foreground=foreground, activebackground=background).grid(
                                row=row, column=0, columnspan=2, sticky="w", pady=10)
            else:
                Label(self.frame, text=label, background=background,
                      foreground=foreground).grid(row=row, column=0, sticky="w", padx=(0, 16), pady=10)
                ttk.Entry(self.frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=10)
            variable.trace_add("write", mark_dirty)
        Label(self.frame, text="修改后点击底部“保存”。试发使用当前输入，无需保存且不受推送开关限制；按当前设置 @所有人。",
              background=background, foreground=foreground).grid(
                  row=4, column=0, columnspan=2, sticky="w", pady=(20, 0))
        self.test_button = ttk.Button(self.frame, text="发送测试消息", command=self.send_test)
        self.test_button.grid(row=5, column=0, sticky="w", pady=16)
        self.status = StringVar(master=self.frame, value="尚未测试")
        Label(self.frame, textvariable=self.status, background=background,
              foreground=foreground, wraplength=650, justify='left').grid(row=5, column=1, sticky='w')

    def send_test(self):
        if self.running:
            return
        values = self.capture()
        self.running = True
        self.test_button.configure(state='disabled')
        self.status.set('正在发送测试消息…')
        self.log('[消息推送] 开始试发：POST https://oapi.dingtalk.com/robot/send（凭据省略），使用当前页面配置。')
        try:
            threading.Thread(target=self._send_worker, args=(values,), daemon=True).start()
        except Exception:
            self.results.put((False, '无法启动发送线程，请重试。'))
        self.frame.after(100, self._poll_result)

    def _send_worker(self, values):
        try:
            send_test_message(values)
        except (ValueError, RuntimeError) as exc:
            self.results.put((False, str(exc)))
        except Exception:
            self.results.put((False, '发送异常，结果未知；请检查群消息。'))
        else:
            self.results.put((True, '发送成功（钉钉已接受），请在群中确认收到测试消息。'))

    def _poll_result(self):
        try:
            success, detail = self.results.get_nowait()
        except queue.Empty:
            self.frame.after(100, self._poll_result)
            return
        self.running = False
        self.test_button.configure(state='normal')
        self.status.set(detail)
        self.log(f"[消息推送] 试发{'成功' if success else '失败'}：{detail}")

    def can_close(self):
        if self.running:
            messagebox.showinfo('正在发送', '测试消息正在发送，请等待结果后关闭。', parent=self.frame)
            return False
        return True

    def capture(self):
        return {key: variable.get() for key, variable in self.variables.items()}

    def load(self, values):
        for key, variable in self.variables.items():
            variable.set(values[key])
