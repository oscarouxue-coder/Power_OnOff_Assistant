"""Tk wiring for channel recovery; execution lives in the service."""
import tkinter as tk
from tkinter import messagebox


def bind_resume_menu(app, tile, channel):
    def available(session):
        pipeline = getattr(app, 'pipeline_window', None)
        return (session is not None and session.can_resume(channel) and
                not (session.original_done and pipeline is not None and pipeline.is_running()))

    def resume():
        session = getattr(app, 'power_test_resume_session', None)
        if not available(session):
            app._log(f'[通道续跑] 通道 {channel} 当前不可续跑：请等待线程退出，或检查停止/执行状态。')
            return
        completed = session.completed[channel]
        if not messagebox.askyesno(
                '确认通道续跑',
                f'仅对通道 {channel} 执行上下电测试。\n'
                f'保留已完成的 {completed} 轮，从第 {completed + 1}/'
                f'{session.request.number_of_tests} 轮继续。\n'
                '将核对原配置及三项版本，不重跑前面的全流程任务。\n\n是否继续？', parent=app):
            return
        if session is not getattr(app, 'power_test_resume_session', None) or not available(session):
            app._log(f'[通道续跑] 通道 {channel} 状态已变化，跳过。')
            return
        if session.submit(channel):
            _poll_recovery(app, session)
        else:
            app._log(f'[通道续跑] 通道 {channel} 已有任务或状态变化，跳过重复启动。')

    def popup(event):
        previous = getattr(app, '_power_resume_context_menu', None)
        if previous is not None:
            previous.destroy()
        menu = tk.Menu(app, tearoff=False)
        app._power_resume_context_menu = menu
        session = getattr(app, 'power_test_resume_session', None)
        menu.add_command(label='重新开始（从失败轮次继续）', command=resume,
                         state='normal' if available(session) else 'disabled')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return 'break'

    tile.bind('<Button-3>', popup)


def _poll_recovery(app, session):
    if session is not getattr(app, 'power_test_resume_session', None):
        return
    pipeline = getattr(app, 'pipeline_window', None)
    pipeline_running = pipeline is not None and pipeline.is_running()
    if session.is_recovering:
        app.stop_power_test_button.configure(state='disabled' if session.stop_event.is_set() else 'normal')
        app.after(100, lambda: _poll_recovery(app, session))
    elif not pipeline_running:
        app.stop_power_test_button.configure(state='disabled')
