"""Recover raw editor inputs, including temporarily invalid values, without executing."""
import json
from pathlib import Path
import tkinter as tk

from src.services.project_store import atomic_json
from src.ui import project_dialogs as messagebox


class EditorRecovery:
    def __init__(self, view, dialog, mark_dirty):
        self.view, self.dialog, self.mark_dirty = view, dialog, mark_dirty
        self.path = view.project_context.root / 'ui' / 'editor_recovery.json'
        self.pending = None
        self.restoring = False
        self.dialog.bind('<Destroy>', self._destroyed, add='+')
        self.restore()

    def _destroyed(self, event):
        if event.widget is self.dialog and self.pending is not None:
            self.dialog.after_cancel(self.pending)
            self.pending = None

    def widgets(self):
        result = {}
        def visit(widget, prefix=''):
            for index, child in enumerate(widget.winfo_children()):
                key = prefix + '/' + str(index)
                kind = child.winfo_class()
                if kind in ('Entry', 'TEntry', 'TCombobox', 'Text', 'Checkbutton', 'Spinbox', 'TSpinbox'):
                    if str(child.cget('state')) != 'disabled':
                        result[key] = child
                visit(child, key)
        visit(self.dialog)
        return result

    def changed(self):
        if self.restoring:
            return
        if self.pending is not None:
            self.dialog.after_cancel(self.pending)
        self.pending = self.dialog.after(300, self.flush)

    def flush(self):
        if self.pending is not None:
            self.dialog.after_cancel(self.pending)
        self.pending = None
        values = {}
        for key, widget in self.widgets().items():
            if widget.winfo_class() == 'Checkbutton':
                variable = widget.cget('variable')
                value = self.dialog.getvar(variable) if variable else ''
            elif widget.winfo_class() == 'Text':
                value = widget.get('1.0', 'end-1c')
            else:
                value = widget.get()
            values[key] = value
        control = vars(self.view).get('_project_editor_order')
        layout = control['layout']() if control else None
        atomic_json(self.path, dict(project_id=self.view.project_context.identity.project_id, values=values, order_layout=layout))

    def restore(self):
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            if value['project_id'] != self.view.project_context.identity.project_id:
                raise ValueError('恢复草稿不属于当前项目')
            if not messagebox.askyesno('恢复页面草稿', '发现上次未保存的测试项页面输入，是否恢复？', parent=self.dialog):
                self.clear()
                return
            self.restoring = True
            control = vars(self.view).get('_project_editor_order')
            layout = value.get('order_layout')
            if control and layout is not None:
                from line_check_assistant.test_item_config_store import OrderConfig, OrderItem, ExpectedSegment
                control['load'](OrderConfig(items=[OrderItem(expected_segments=[ExpectedSegment('') for _ in range(count)])
                                                  for count in layout]))
            widgets = self.widgets()
            for key, raw in value['values'].items():
                widget = widgets.get(key)
                if widget is None:
                    continue
                kind = widget.winfo_class()
                if kind == 'Checkbutton':
                    variable = widget.cget('variable')
                    if variable:
                        self.dialog.setvar(variable, raw)
                elif kind == 'Text':
                    widget.delete('1.0', 'end')
                    widget.insert('1.0', raw)
                elif kind == 'TCombobox':
                    widget.set(raw)
                else:
                    variable = widget.cget('textvariable')
                    if variable:
                        self.dialog.setvar(variable, raw)
                    else:
                        widget.delete(0, 'end')
                        widget.insert(0, raw)
            self.mark_dirty()
            self.view._log('[项目管理] 已恢复测试项页面草稿；未保存配置、未启动设备任务。')
        except (OSError, ValueError, KeyError, tk.TclError):
            messagebox.showwarning('草稿恢复失败', '页面恢复草稿无法完整读取，原文件保留。请核对输入后再保存。', parent=self.dialog)
        finally:
            self.restoring = False

    def clear(self):
        if self.pending is not None:
            self.dialog.after_cancel(self.pending)
            self.pending = None
        self.path.unlink(missing_ok=True)
