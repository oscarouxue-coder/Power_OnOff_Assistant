"""Single main window with collapsible project sidebar and persistent project views."""
from pathlib import Path
import os
import queue
import time
import threading
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from src.models.project import PROJECT_FILE
from src.services.project_execution import project_busy, project_resources
from src.services.workspace_service import WorkspaceService
from src.ui.application_icon import apply_application_icon, set_taskbar_application_id
from src.ui.module_theme import MODULE_BACKGROUND, apply_module_theme


class ProjectWorkspace(tk.Tk):
    def __init__(self, source_root, *, service=None, instance=None, view_factory=None):
        set_taskbar_application_id()
        super().__init__()
        apply_application_icon(self)
        from line_check_assistant.app import MAIN_WINDOW_TITLE
        self.title(MAIN_WINDOW_TITLE)
        self.geometry('1480x900')
        self.minsize(1100, 720)
        self.configure(background=MODULE_BACKGROUND)
        self.events = queue.Queue()
        self.service = service or WorkspaceService(source_root, emit=self.events.put)
        self.service.emit = self.service.projects.emit = self.events.put
        self._source_maintenance_gate = self.service.maintenance
        self.instance = instance
        self.inventory_events = queue.Queue()
        self.inventory_worker = None
        self.views = {}
        self.selected = None
        self.sidebar_visible = True
        self.closing = False
        self.tickets = {}
        self.next_status = 0
        self.view_factory = view_factory
        self._build()
        self.protocol('WM_DELETE_WINDOW', self.close_application)
        self.bind('<Control-s>', lambda event: self.save_project())
        self.bind('<Control-o>', lambda event: self.open_project())
        self.bind('<Control-n>', lambda event: self.new_project())
        self.bind('<ButtonPress-1>', lambda event: self.lift(), add='+')
        self._poll_id = self.after(100, self._poll)
        if self.service.recent_error:
            self.status.set(self.service.recent_error)
        if service is None:
            self.refresh_inventory()

    def refresh_inventory(self):
        if self.inventory_worker is not None and self.inventory_worker.is_alive():
            return
        def read():
            from src.core.network_adapter import read_adapter_identities
            try:
                self.inventory_events.put((True, read_adapter_identities()))
            except Exception:
                self.inventory_events.put((False, ()))
        self.inventory_worker = threading.Thread(target=read, name='workspace-adapter-inventory', daemon=True)
        self.inventory_worker.start()

    def _build(self):
        toolbar = tk.Frame(self, background=MODULE_BACKGROUND)
        toolbar.pack(fill='x', padx=12, pady=(10, 0))
        ttk.Button(toolbar, text='☰ 项目', command=self.toggle_sidebar).pack(side='left')
        self.project_menu = tk.Menu(self, tearoff=False)
        menu_button = ttk.Menubutton(toolbar, text='项目 ▾', menu=self.project_menu)
        menu_button.pack(side='left', padx=8)
        self.project_menu.configure(postcommand=self._update_menu)
        self.project_menu.add_command(label='新建项目…', command=self.new_project, accelerator='Ctrl+N')
        self.project_menu.add_command(label='打开项目…', command=self.open_project, accelerator='Ctrl+O')
        self.recent_menu = tk.Menu(self.project_menu, tearoff=False)
        self.project_menu.add_cascade(label='最近项目', menu=self.recent_menu)
        self.switch_menu = tk.Menu(self.project_menu, tearoff=False)
        self.project_menu.add_cascade(label='切换项目', menu=self.switch_menu)
        self.project_menu.add_separator()
        self.project_menu.add_command(label='保存项目', command=self.save_project, accelerator='Ctrl+S')
        self.project_menu.add_command(label='另存为 / 复制项目…', command=self.duplicate_project)
        self.project_menu.add_command(label='重命名项目…', command=self.rename_project)
        self.project_menu.add_command(label='导入旧配置目录…', command=self.import_project)
        self.project_menu.add_command(label='打开项目目录', command=self.open_directory)
        self.project_menu.add_command(label='关闭项目', command=self.close_project)
        self.project_menu.add_command(label='从最近列表移除', command=self.forget_project)
        self.project_menu.add_separator()
        self.project_menu.add_command(label='远程可访问项目…', command=self.remote_project_range)
        self.project_menu.add_command(label='选择导入的接入配置…', command=self.imported_connection)
        self.project_menu.add_command(label='多实例 / 统一网关…', command=self.open_instance_management)
        self.project_menu.add_command(label='核实未知任务…', command=self.resolve_unknown)
        ttk.Button(toolbar, text='保存', command=self.save_project).pack(side='left')
        self.project_title = tk.StringVar(self, value='')
        ttk.Label(toolbar, textvariable=self.project_title).pack(side='left', padx=18)
        ttk.Button(toolbar, text='AI / 远程接入', command=self.open_ai).pack(side='right')
        self.body = tk.Frame(self, background=MODULE_BACKGROUND)
        self.body.pack(fill='both', expand=True, padx=10, pady=10)
        self.sidebar = tk.Frame(self.body, background=MODULE_BACKGROUND, width=230)
        self.sidebar.pack(side='left', fill='y', padx=(0, 10))
        self.sidebar.pack_propagate(False)
        self.tree = ttk.Treeview(self.sidebar, columns=('state',), show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='项目')
        self.tree.heading('state', text='状态')
        self.tree.column('#0', width=145, minwidth=90)
        self.tree.column('state', width=70, minwidth=60, stretch=False)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._tree_selected)
        self.tree.bind('<Button-3>', self._context_menu)
        buttons = tk.Frame(self.sidebar, background=MODULE_BACKGROUND)
        buttons.pack(fill='x', pady=(8, 0))
        ttk.Button(buttons, text='新建', command=self.new_project).pack(side='left')
        ttk.Button(buttons, text='打开…', command=self.open_project).pack(side='right')
        self.content = tk.Frame(self.body, background=MODULE_BACKGROUND)
        self.content.pack(fill='both', expand=True)
        self.status = tk.StringVar(self, value='')
        ttk.Label(self, textvariable=self.status).pack(fill='x', padx=14, pady=(0, 6))
        apply_module_theme(self)

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        if self.sidebar_visible:
            self.sidebar.pack(side='left', fill='y', padx=(0, 10), before=self.content)
        else:
            self.sidebar.pack_forget()

    def _update_menu(self):
        self.recent_menu.delete(0, 'end')
        self.switch_menu.delete(0, 'end')
        for item in self.service.recent:
            self.recent_menu.add_command(label=item['name'], command=lambda path=item['path']: self.open_project(path))
        for project in self.service.list_projects():
            self.switch_menu.add_command(label=project['name'],
                command=lambda key=project['project_id']: self.select_project(key))

    def _context_menu(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            self.select_project(row)
            self._update_menu()
            self.project_menu.tk_popup(event.x_root, event.y_root)

    def _tree_selected(self, event=None):
        selected = self.tree.selection()
        if selected:
            self.select_project(selected[0])

    def current_view(self):
        return self.views.get(self.selected)

    def select_project(self, identifier):
        if self.closing or identifier not in self.views:
            return
        for key, view in self.views.items():
            if key != identifier:
                view.pack_forget()
        view = self.views[identifier]
        view.pack(fill='both', expand=True)
        self.selected = identifier
        if self.tree.selection() != (identifier,):
            self.tree.selection_set(identifier)
        self.project_title.set(view.project_context.identity.name)
        self.status.set('已切换到 ' + view.project_context.identity.name)

    def _add_project(self, context):
        identifier = context.identity.project_id
        if identifier in self.views:
            self.select_project(identifier)
            return
        from line_check_assistant.app import LineCheckAssistant
        factory = self.view_factory or LineCheckAssistant
        existing_children = set(self.content.winfo_children())
        try:
            self.service.remember(context)
            view = factory(self.content, project_context=context, workspace=self)
            view._project_closed_callback = self._project_closed
            self.views[identifier] = view
            self.tree.insert('', 'end', iid=identifier, text=context.identity.name, values=('空闲',))
        except BaseException:
            self.views.pop(identifier, None)
            for child in set(self.content.winfo_children()) - existing_children:
                child.destroy()
            self.service.projects.close(context)
            raise
        self.select_project(identifier)

    def new_project(self):
        if self.closing:
            return
        name = simpledialog.askstring('新建项目', '项目名称', parent=self)
        if not name:
            return
        directory = filedialog.askdirectory(title='选择空的项目文件夹', parent=self)
        if directory:
            self._perform(lambda: self._add_project(self.service.projects.create(directory, name)))

    def open_project(self, path=None):
        if self.closing:
            return
        path = path or filedialog.askopenfilename(title='打开项目', parent=self,
            filetypes=[('LineCheckAssistant 项目', PROJECT_FILE)])
        if path:
            self._perform(lambda: self._add_project(self.service.projects.open(path)))

    def import_project(self):
        if self.closing:
            return
        source = filedialog.askdirectory(title='选择旧程序目录或配置目录', parent=self)
        if not source:
            return
        name = simpledialog.askstring('导入旧项目', '新项目名称', parent=self)
        if not name:
            return
        destination = filedialog.askdirectory(title='选择新的空项目文件夹', parent=self)
        if destination:
            def run():
                context = self.service.projects.create(destination, name, import_directory=source)
                try:
                    legacy_root = Path(source)
                    if legacy_root.name == 'config':
                        legacy_root = legacy_root.parent
                    if legacy_root.name.lower() == 'auto_power_on_off_tool':
                        legacy_root = legacy_root.parent
                    self.service.projects.import_history(context, legacy_root)
                    self.service.import_connections(legacy_root)
                    self._add_project(context)
                except BaseException:
                    self.service.projects.close(context)
                    raise
            self._perform(run)

    def imported_connection(self):
        candidates = self.service.connection_candidates()
        dialog = tk.Toplevel(self)
        dialog.title('选择导入的接入配置')
        selected = tk.StringVar(dialog)
        combo = ttk.Combobox(dialog, textvariable=selected, values=[c['label'] for c in candidates], state='readonly', width=55)
        combo.pack(padx=16, pady=16)
        def save():
            candidate = next((c for c in candidates if c['label'] == selected.get()), None)
            if candidate is not None and self._perform(lambda: self.service.use_connection(candidate)) is not False:
                dialog.destroy()
        ttk.Button(dialog, text='选择', command=save).pack(side='right', padx=16, pady=12)
        apply_module_theme(dialog)

    def flush_draft(self, view):
        editor = vars(view).get('_project_editor_save')
        dirty = vars(view).get('_project_editor_dirty')
        window = vars(view).get('test_item_config_window')
        if (view.project_context.root / 'ui' / 'editor_recovery.json').exists() and (window is None or not window.winfo_exists()):
            raise ValueError('请先打开测试项配置并恢复页面草稿，再保存项目')
        if editor and window is not None and window.winfo_exists() and dirty and dirty():
            if not editor(confirm=False, quiet=True, commit=False):
                raise ValueError('测试项输入校验或草稿写入失败，项目未保存')
        view._cancel_pending_onu_registration_save()
        view._cancel_pending_sample_upgrade_save()
        view._persist_config()
        view._save_onu_registration_config()
        view._save_sample_upgrade_settings()

    def is_dirty(self, view):
        if vars(view).get('onu_save_after_id') is not None or vars(view).get('sample_upgrade_save_after_id') is not None:
            return True
        if (view.project_context.root / 'ui' / 'editor_recovery.json').exists():
            return True
        dirty = vars(view).get('_project_editor_dirty')
        window = vars(view).get('test_item_config_window')
        if window is not None and window.winfo_exists() and dirty and dirty():
            return True
        return self.service.projects.dirty(view.project_context)

    def save_project(self, view=None):
        view = view or self.current_view()
        if view is None:
            return False
        def save():
            self.flush_draft(view)
            self.service.projects.save(view.project_context)
            view._project_discard_on_close = False
            recovery = vars(view).get('_project_editor_recovery')
            if recovery:
                recovery.clear()
            view._log('[项目管理] 已保存项目配置；运行任务继续使用原配置快照。')
            view._refresh_saved_project_name()
            self.service.remember(view.project_context)
            return True
        return self._perform(save)

    def duplicate_project(self):
        view = self.current_view()
        if view is None:
            return
        if self.is_dirty(view):
            if not messagebox.askyesno('保存后另存为', '先保存当前项目配置，再创建独立副本？', parent=self):
                return
            if not self.save_project(view):
                return
        destination = filedialog.askdirectory(title='另存为：选择空项目文件夹', parent=self)
        if destination:
            self._perform(lambda: self._add_project(self.service.projects.duplicate(view.project_context, destination)))

    def rename_project(self):
        view = self.current_view()
        if view is None:
            return
        name = simpledialog.askstring('重命名项目', '项目名称', initialvalue=view.project_context.identity.name, parent=self)
        if name:
            def rename():
                self.flush_draft(view)
                self.service.projects.rename(view.project_context, name)
                self.service.remember(view.project_context)
                self.project_title.set(name)
                view._refresh_saved_project_name()
            self._perform(rename)

    def open_directory(self):
        view = self.current_view()
        if view is not None:
            self._perform(lambda: os.startfile(str(view.project_context.root)))

    def forget_project(self):
        view = self.current_view()
        if view is not None:
            self._perform(lambda: self.service.forget(view.project_context.root))
            self.status.set('已从最近列表移除；项目文件保留')

    def open_ai(self):
        if self.closing:
            return
        view = self.current_view()
        if view is not None:
            view._open_ai_assistant()

    def remote_project_range(self):
        dialog = tk.Toplevel(self)
        dialog.title('本机确认远程项目范围')
        dialog.transient(self)
        values = {}
        for key, view in self.views.items():
            value = tk.BooleanVar(dialog, value=key in self.service.remote_projects)
            values[key] = value
            tk.Checkbutton(dialog, text=view.project_context.identity.name + ' · ' + key[:8], variable=value,
                background=MODULE_BACKGROUND, activebackground=MODULE_BACKGROUND).pack(anchor='w', padx=16, pady=5)
        def save():
            selected = [key for key, value in values.items() if value.get()]
            if messagebox.askyesno('确认远程项目范围',
                '允许远程选择已勾选项目；各项目仍须通过原身份、通道、能力和权限检查。取消勾选不停止已准入设备任务。是否保存？',
                parent=dialog, default='no'):
                if self._perform(lambda: self.service.set_remote_projects(selected)) is not False:
                    dialog.destroy()
        ttk.Button(dialog, text='保存', command=save).pack(side='right', padx=16, pady=12)
        apply_module_theme(dialog)

    def open_instance_management(self):
        if self.closing:
            return
        existing = vars(self).get('_management_window')
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            return
        from src.ui.ai_multi_instance_tab import MultiInstanceTab
        window = self._management_window = tk.Toplevel(self)
        window.title('多实例 / 统一网关')
        window.geometry('1040x780')
        panel = MultiInstanceTab(window, self.service.management())
        def close():
            panel.dispose()
            window.destroy()
        window.protocol('WM_DELETE_WINDOW', close)
        apply_module_theme(window)

    def resolve_unknown(self):
        entries = self.service.resources.unknown_gui()
        dialog = tk.Toplevel(self)
        dialog.title('本机核实原未知任务')
        selected = tk.StringVar(dialog)
        labels = [label + ' · ' + owner for owner, label in entries]
        ttk.Combobox(dialog, textvariable=selected, values=labels, width=70, state='readonly').pack(padx=16, pady=12)
        evidence = tk.Text(dialog, height=5, width=70)
        evidence.pack(padx=16, pady=6)
        def save():
            index = labels.index(selected.get()) if selected.get() in labels else -1
            if index < 0:
                return
            owner = entries[index][0]
            if messagebox.askyesno('确认已核实现场结果', '仅记录核实依据并解除原任务保护，不自动重试。是否确认？', parent=dialog, default='no'):
                if self._perform(lambda: self.service.resolve_gui_unknown(owner, evidence.get('1.0', 'end').strip())) is not False:
                    project_id = owner.split(':')[1]
                    if not any(key.startswith('gui:' + project_id + ':') for key, _ in self.service.resources.unknown_gui()):
                        view = self.views.get(project_id)
                        rename = vars(view).get('adapter_rename_dialog') if view is not None else None
                        if rename is not None:
                            rename.uncertain = False
                    dialog.destroy()
        ttk.Button(dialog, text='记录并解除保护', command=save).pack(side='right', padx=16, pady=12)
        apply_module_theme(dialog)

    def _approve_close(self, view):
        if self.is_dirty(view):
            answer = messagebox.askyesnocancel('关闭项目', '项目“' + view.project_context.identity.name + '”有未保存修改，是否保存？', parent=self)
            if answer is None:
                return False
            if answer and not self.save_project(view):
                return False
            if not answer:
                # Decide now, mutate only after all close confirmations succeed.
                view._project_discard_on_close = True
        return True

    def close_project(self, view=None, *, approved=False):
        view = view or self.current_view()
        if view is None:
            return
        if not approved and not self._approve_close(view):
            return
        if not approved and project_busy(view):
            if not messagebox.askyesno('安全停止并关闭项目',
                '项目“' + view.project_context.identity.name + '”仍有活动任务。请求安全停止并等待收尾后关闭？', parent=self, default='no'):
                return
        view._on_app_close()

    def _project_closed(self, view):
        context = view.project_context
        for owner, entry in tuple(self.tickets.items()):
            if entry['view'] is view:
                self.service.resources.release(owner, uncertain=entry.get('uncertain', False))
                del self.tickets[owner]
        if vars(view).get('_project_discard_on_close'):
            try:
                (context.root / 'ui' / 'editor_recovery.json').unlink(missing_ok=True)
                self.service.projects.discard(context)
            except Exception:
                self.events.put('[项目管理] 关闭时未能丢弃草稿；已保存版本未改变，草稿保留供下次核对：' + context.identity.name)
        self.service.projects.close(context)
        self.views.pop(context.identity.project_id, None)
        if self.tree.exists(context.identity.project_id):
            self.tree.delete(context.identity.project_id)
        was_selected = self.selected == context.identity.project_id
        if was_selected:
            self.selected = None
        if was_selected and self.views and not self.closing:
            self.select_project(next(iter(self.views)))
        elif not self.views:
            self.project_title.set('')

    def admit_operation(self, view, operation):
        if self.closing or vars(view).get('_app_closing'):
            return None
        owner = None
        try:
            view._capture_current_channel()
            if operation != 'start' and self.is_dirty(view):
                view._log('[项目管理] 配置存在未保存修改，请先保存项目后启动新的设备任务。')
                messagebox.showwarning('请先保存项目', '项目“' + view.project_context.identity.name + '”有未保存修改，请保存后再启动。', parent=self)
                return None
            context = view.project_context
            owner = 'gui:' + context.identity.project_id + ':' + uuid.uuid4().hex
            self.service.resources.acquire(owner, context.identity.project_id, context.identity.name, project_resources(view, operation))
            rename = vars(view).get('adapter_rename_dialog')
            if operation == 'submit' and rename is not None:
                self.service.resources.acquire(owner, context.identity.project_id, context.identity.name, ['adapter:' + rename.old_name])
            snapshot = self.service.projects.snapshot(context)
            self.tickets[owner] = dict(view=view, snapshot=snapshot, operation=operation, started=time.monotonic(), tracking=False, uncertain=False)
            view._project_run_root = snapshot
            if operation == '_on_start':
                view._project_legacy_root = snapshot / 'Auto_power_on_off_tool'
            view._log('[项目管理] 任务准入：' + operation + '；项目=' + context.identity.name + '；配置版本=' + context.identity.revision)
            return owner
        except Exception as exc:
            if owner is not None:
                self.tickets.pop(owner, None)
                self.service.resources.release(owner)
            view._log('[项目管理] 任务未启动：' + str(exc))
            messagebox.showwarning('项目任务未启动', str(exc), parent=self)
            return None

    def track_operation(self, view, owner):
        if owner in self.tickets:
            self.tickets[owner]['tracking'] = True

    def reserve_actual(self, view, keys):
        owners = [owner for owner, entry in self.tickets.items() if entry['view'] is view and not entry['tracking']]
        if not owners:
            return False

        try:
            context = view.project_context
            for owner in owners:
                self.service.resources.acquire(owner, context.identity.project_id, context.identity.name, keys)
            return True
        except Exception as exc:
            view._log('[项目管理] 实际目标资源占用，任务未启动：' + str(exc))
            messagebox.showwarning('实际目标资源占用', str(exc), parent=self)
            return False


    def synchronize_adapter_names(self, origin, old_name, new_name, result):
        warnings = []
        for adapter in result.adapters:
            self.service.resources.register_adapter(adapter.alias, adapter.interface_guid)
            if adapter.alias == new_name:
                self.service.resources.register_adapter(old_name, adapter.interface_guid)
        for view in tuple(self.views.values()):
            if view is origin:
                continue
            if any(channel.vlan_name == old_name or channel.adapter_alias == old_name for channel in view.channels):
                try:
                    warning = view._on_adapter_renamed('', old_name, new_name, result, _from_workspace=True)
                    if warning:
                        warnings.append(view.project_context.identity.name + '：' + warning)
                except Exception:
                    warnings.append(view.project_context.identity.name + '：网卡引用同步未完成，请核对并保存该项目')
        return warnings

    def close_application(self):
        if self.closing:
            return
        repair = vars(self).get('_feishu_dependency_controller')
        if repair is not None and repair.prevents_close:
            messagebox.showinfo('正在安装飞书SDK', '请等待安装结束，当前不会退出程序。', parent=self)
            return
        if any(project_busy(view) for view in self.views.values()):
            if not messagebox.askyesno('退出工作区', '仍有项目运行。请求各项目安全停止并等待全部收尾后退出？', parent=self, default='no'):
                return
        for view in tuple(self.views.values()):
            if not self._approve_close(view):
                return
        self.closing = True
        self._app_closing = True
        if self.instance:
            self.instance.closing_requested.set()
        for view in tuple(self.views.values()):
            self.close_project(view, approved=True)
        self.service.begin_close()

    def _on_app_close(self):
        self.close_application()

    def _log(self, text):
        self.events.put(text)

    def install_feishu_sdk(self):
        from src.ui.feishu_dependency_controller import FeishuDependencyController
        controller = vars(self).get('_feishu_dependency_controller')
        if controller is None:
            controller = self._feishu_dependency_controller = FeishuDependencyController(
                self, self.service.source_root, self.service.maintenance)
        controller.start()

    def _perform(self, action):
        if self.closing:
            self.status.set('工作区正在安全退出，本次操作未执行')
            return False
        try:
            return action()
        except Exception as exc:
            self.status.set('项目操作失败：' + str(exc))
            messagebox.showerror('项目操作失败', str(exc), parent=self)
            return False

    def _poll(self):
        try:
            while not self.inventory_events.empty():
                ready, identities = self.inventory_events.get_nowait()
                for identity in identities:
                    self.service.resources.register_adapter(identity.alias, identity.interface_guid)
                self.service.resources.inventory_ready = ready
                if not ready:
                    self.events.put('[项目管理] 网卡身份读取失败，相关任务未放行；请刷新串口/网卡后重试')
            for _ in range(50):
                try:
                    text = self.events.get_nowait()
                except queue.Empty:
                    break
                self.status.set(text)
                with (self.service.directory / 'workspace.log').open('a', encoding='utf-8') as stream:
                    stream.write(text + '\n')
            if self.instance is not None:
                for _ in range(10):
                    try:
                        request = self.instance.requests.get_nowait()
                    except queue.Empty:
                        break
                    if request['project']:
                        self.open_project(request['project'])
                    self.deiconify()
                    self.lift()
            for owner, entry in tuple(self.tickets.items()):
                if entry['tracking'] and time.monotonic() - entry['started'] > .2 and not project_busy(entry['view']):
                    rename = vars(entry['view']).get('adapter_rename_dialog')
                    uncertain = entry['uncertain'] or bool(rename is not None and rename.uncertain)
                    self.service.resources.release(owner, uncertain=uncertain)
                    del self.tickets[owner]
            if time.monotonic() >= self.next_status:
                self.next_status = time.monotonic() + .5
                if not self.closing:
                    self.service.synchronize_platforms()
                for identifier, view in tuple(self.views.items()):
                    dirty = self.is_dirty(view)
                    name = view.project_context.identity.name + (' *' if dirty else '')
                    self.tree.item(identifier, text=name, values=('停止中' if vars(view).get('_app_closing') else '运行中' if project_busy(view) else '空闲',))
            if self.closing and not self.views and self.service.idle:
                self.service.close()
                if self.instance:
                    self.instance.close()
                self.destroy()
                return
        except Exception as exc:
            self.status.set('工作区状态更新失败：' + str(exc))
        self._poll_id = self.after(100, self._poll)

    def destroy(self):
        identifier = vars(self).get('_poll_id')
        if identifier:
            try:
                self.after_cancel(identifier)
            except tk.TclError:
                pass
        super().destroy()
