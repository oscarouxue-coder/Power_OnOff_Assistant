"""Local opt-in repair: no real pip installs, application restarts or device I/O."""
import importlib.metadata
import os
from pathlib import Path
import queue
import runpy
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from src.core import feishu_dependency_install as install
from src.core import source_restart as restart
from src.core.feishu_stream import FeishuStream
from src.models.dependency_repair import MaintenanceGate, MissingFeishuSdkError, RepairResult, maintenance_operation
from src.services.feishu_dependency_repair import FeishuDependencyRepair
from src.ui.feishu_setup_window import FeishuSetupWindow
from src.ui.feishu_dependency_controller import repair_host_busy, FeishuDependencyController

ROOT = Path(__file__).resolve().parents[1]
QT_ENTRY = ROOT / 'run_dutpilot_qt.py'


def wheel(folder, name='lark-oapi', version='1.7.5'):
    path = Path(folder) / (name.replace('-', '_') + '-' + version + '-py3-none-any.whl')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name.replace('-', '_') + '-' + version + '.dist-info/METADATA',
                         f'Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n')
    return path


class ErrorAndChoiceTests(unittest.TestCase):
    def view(self):
        view = object.__new__(FeishuSetupWindow)
        view.status, view.emit, view.on_install_sdk, view.dialog_parent = Mock(), Mock(), Mock(), Mock()
        return view

    def test_missing_sdk_raises_typed_error_before_thread_or_network(self):
        transport = FeishuStream('id', 'secret', Mock(), Mock())
        with patch('src.core.feishu_stream.importlib.util.find_spec', return_value=None):
            with self.assertRaises(MissingFeishuSdkError):
                transport.start()
        self.assertIsNone(transport.thread)

    def test_ok_and_close_do_not_install(self):
        view = self.view()
        with patch('src.ui.feishu_setup_window.MissingFeishuSdkDialog') as dialog:
            dialog.return_value.show.return_value = False
            view.error(MissingFeishuSdkError())
        view.on_install_sdk.assert_not_called()
        self.assertIn('跳过安装', view.emit.call_args.args[0])

    def test_install_is_explicit_single_local_callback(self):
        view = self.view()
        with patch('src.ui.feishu_setup_window.MissingFeishuSdkDialog') as dialog:
            dialog.return_value.show.return_value = True
            view.error(MissingFeishuSdkError())
        view.on_install_sdk.assert_called_once_with()

    def test_non_dependency_error_keeps_original_messagebox(self):
        view = self.view()
        with patch('src.ui.feishu_setup_window.MissingFeishuSdkDialog') as dialog, \
                patch('src.ui.feishu_setup_window.messagebox.showerror') as show:
            view.error(ValueError('凭据错误'))
        dialog.assert_not_called()
        view.on_install_sdk.assert_not_called()
        self.assertEqual(show.call_args.args[1], '凭据错误')

    def test_frozen_exe_never_offers_pip(self):
        view = self.view()
        with patch.object(sys, 'frozen', True, create=True), \
                patch('src.ui.feishu_setup_window.MissingFeishuSdkDialog') as dialog, \
                patch('src.ui.feishu_setup_window.messagebox.showerror') as show:
            view.error(MissingFeishuSdkError())
        dialog.assert_not_called()
        view.on_install_sdk.assert_not_called()
        self.assertIn('便携ZIP', show.call_args.args[1])


class GateAndRepairTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'Windows environment mutex')
    def test_new_source_instance_is_rejected_while_same_environment_is_repairing(self):
        from scripts.source_environment_guard import ensure_source_environment_available, repair_identity
        from src.core.dingtalk_stream import InstanceLease
        with tempfile.TemporaryDirectory(prefix='repair-mutex-') as prefix:
            ensure_source_environment_available(prefix)
            lease = InstanceLease(repair_identity(prefix))
            lease.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, '正在安装'):
                    ensure_source_environment_available(prefix)
            finally:
                lease.close()
            ensure_source_environment_available(prefix)

    def test_frozen_source_guard_does_not_inspect_or_install_environment(self):
        from scripts.source_environment_guard import ensure_source_environment_available
        with patch.object(sys, 'frozen', True, create=True), patch('scripts.source_environment_guard.ctypes.WinDLL', create=True) as dll:
            ensure_source_environment_available()
        dll.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows source entry')
    def test_source_entry_refuses_before_app_import_or_main_when_repair_owns_environment(self):
        import ctypes
        main = Mock(return_value=0)
        with patch.object(sys, 'argv', [QT_ENTRY.name]), \
                patch('scripts.source_environment_guard.ensure_source_environment_available', side_effect=RuntimeError('正在安装')), \
                patch.object(sys, 'stderr', None), \
                patch.object(ctypes.windll.user32, 'MessageBoxW') as notice, \
                patch.dict(sys.modules, {'src.ui.qt.application': Mock(run_workspace=main)}):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(QT_ENTRY), run_name='__main__')
        self.assertEqual(caught.exception.code, 1)
        notice.assert_called_once()
        main.assert_not_called()

    def test_source_entry_keeps_gateway_arguments_and_calls_main_when_not_repairing(self):
        main = Mock(return_value=0)
        project = '工程 副本/project.linecheck.json'
        with patch.object(sys, 'argv', [QT_ENTRY.name, project, '--gateway-slot', '5']), \
                patch.dict(os.environ, {}, clear=False), \
                patch('scripts.source_environment_guard.ensure_source_environment_available') as available, \
                patch.dict(sys.modules, {'src.ui.qt.application': Mock(run_workspace=main)}):
            with self.assertRaises(SystemExit) as caught:
                runpy.run_path(str(QT_ENTRY), run_name='__main__')
            self.assertEqual(caught.exception.code, 0)
            self.assertEqual(os.environ['LINECHECK_GATEWAY_SLOT'], '5')
        available.assert_called_once()
        main.assert_called_once_with(str(Path.cwd() / project))

    def test_inflight_operation_blocks_repair_and_new_work_is_blocked_during_repair(self):
        gate = MaintenanceGate()
        calls = []
        class Business:
            maintenance = gate
            @maintenance_operation
            def execute(self, fail=False):
                calls.append('entered')
                with self_test.assertRaises(RuntimeError):
                    gate.begin()
                if fail:
                    raise ValueError('failure')
        self_test = self
        business = Business()
        business.execute()
        with self.assertRaises(ValueError):
            business.execute(True)
        self.assertEqual(gate.operations, 0)
        gate.begin()
        with self.assertRaises(RuntimeError):
            business.execute()
        self.assertEqual(len(calls), 2)
        gate.end()
        business.execute()

    def test_activity_refuses_before_environment_check_install_or_restart(self):
        installer, gate = Mock(), MaintenanceGate()
        service = FeishuDependencyRepair(ROOT, gate, installer)
        def busy():
            self.assertFalse(gate.active)  # A refused repair must not transiently block a running task.
            return True
        with patch('src.services.feishu_dependency_repair.source_environment') as check:
            with self.assertRaisesRegex(RuntimeError, '结束当前'):
                service.start(busy)
        installer.assert_not_called()
        check.assert_not_called()
        self.assertFalse(gate.active)

    def test_success_keeps_maintenance_until_close_and_prevents_duplicate_click(self):
        blocker = threading.Event()
        installer = Mock(side_effect=lambda root, emit: blocker.wait(2))
        gate, lease = MaintenanceGate(), Mock()
        service = FeishuDependencyRepair(ROOT, gate, installer, Mock(return_value=lease))
        with patch('src.services.feishu_dependency_repair.source_environment'):
            service.start(lambda: False)
            try:
                with self.assertRaises(RuntimeError):
                    service.start(lambda: False)
            finally:
                blocker.set()
                service.thread.join(3)
        self.assertEqual(service.events.get_nowait(), RepairResult(True, '飞书SDK安装及验证成功，正在准备安全重启'))
        self.assertTrue(gate.active)
        installer.assert_called_once()
        service.release()
        lease.close.assert_called_once()
        self.assertFalse(gate.active)

    def test_failure_reports_once_and_allows_retry_after_ui_releases(self):
        gate = MaintenanceGate()
        service = FeishuDependencyRepair(ROOT, gate, Mock(side_effect=RuntimeError('断网')), Mock(return_value=Mock()))
        with patch('src.services.feishu_dependency_repair.source_environment'):
            service.start(lambda: False)
            service.thread.join(3)
        result = service.events.get_nowait()
        self.assertFalse(result.ok)
        self.assertIn('断网', result.message)
        self.assertFalse(service.ready)
        service.release()
        self.assertFalse(gate.active)

    def test_source_preflight_failure_releases_maintenance(self):
        gate = MaintenanceGate()
        service = FeishuDependencyRepair(ROOT, gate)
        with patch('src.services.feishu_dependency_repair.source_environment', side_effect=ValueError('不是虚拟环境')):
            with self.assertRaises(ValueError):
                service.start(lambda: False)
        self.assertFalse(gate.active)
        self.assertIsNone(service.thread)

    def test_host_activity_is_read_without_stop_callbacks(self):
        app = SimpleNamespace(running=True, _on_app_close=Mock(), _stop_power_test=Mock())
        self.assertTrue(repair_host_busy(app))
        app._on_app_close.assert_not_called()
        app._stop_power_test.assert_not_called()
        app.running = False
        self.assertFalse(repair_host_busy(app))
        app.ai_assistant = SimpleNamespace(service=SimpleNamespace(idle=False), dialog=SimpleNamespace(background=set()))
        self.assertTrue(repair_host_busy(app))

    def test_real_business_adapters_reject_before_any_work(self):
        from src.services.ai_conversation_service import AiConversationService
        from src.services.ai_diagnostic_service import AiDiagnosticService
        from src.services.capability_service import CapabilityService
        from src.services.ai_session_router import AiSessionRouter
        gate = MaintenanceGate()
        gate.begin()
        for cls, method, args in ((AiConversationService, 'send', ('id', 'question')),
                                  (AiDiagnosticService, 'submit', ('question', 1)),
                                  (CapabilityService, 'execute', ('firmware.upgrade', {}, None)),
                                  (AiSessionRouter, 'send', ('question', None))):
            obj = object.__new__(cls)
            obj.maintenance = gate
            with self.subTest(cls=cls.__name__), self.assertRaisesRegex(RuntimeError, '任务未启动'):
                getattr(obj, method)(*args)

    def test_catalog_marks_repair_as_human_control_not_ai_business(self):
        from src.services.capability_catalog import business_catalog
        item = next(r for r in business_catalog() if r['feature_id'] == 'remote.feishu_sdk_repair')
        self.assertEqual(item['status'], 'manual_control')
        self.assertIn('AI不可', item['reason'])

    def test_all_existing_task_sources_refuse_without_cancellation(self):
        samples = [
            dict(power_test_running=True), dict(onu_query_running=True),
            dict(_capability_reservations={'job'}), dict(_project_info_query_count=1),
            dict(_background_workers=[Mock(is_alive=Mock(return_value=True))]),
            dict(_sample_upgrade_run=SimpleNamespace(finished=False)),
            dict(_pipeline_ui=SimpleNamespace(idle=lambda: False)),
            dict(app_update_dialog=SimpleNamespace(jobs={'download'})),
            dict(feishu_notifications=SimpleNamespace(busy=True)),
            dict(test_item_pretest_controls=SimpleNamespace(running=True)),
        ]
        for attributes in samples:
            with self.subTest(attributes=tuple(attributes)):
                self.assertTrue(repair_host_busy(SimpleNamespace(**attributes)))

    def test_pipeline_and_capability_admission_reject_maintenance(self):
        from line_check_assistant.app import LineCheckAssistant
        from src.ui.capability_ui_bridge import CapabilityUiBridge
        gate = MaintenanceGate()
        gate.begin()
        app = SimpleNamespace(_source_maintenance_gate=gate, _log=Mock())
        self.assertFalse(LineCheckAssistant._pipeline_admit_action(app))
        bridge = object.__new__(CapabilityUiBridge)
        bridge.app = app
        self.assertFalse(bridge._admissible(Mock()))


class ControllerTests(unittest.TestCase):
    def controller(self, result):
        gate = MaintenanceGate()
        gate.begin()
        controller = object.__new__(FeishuDependencyController)
        controller.app = SimpleNamespace(_log=Mock(), after=Mock())
        controller.service = SimpleNamespace(events=queue.Queue(), busy=False, gate=gate, release=Mock(side_effect=gate.end))
        controller.service.events.put(result)
        controller.status, controller.buttons, controller.window = Mock(), Mock(), Mock()
        controller.restart_requested = False
        return controller

    def test_failed_install_keeps_app_and_shows_retry_without_restart(self):
        controller = self.controller(RepairResult(False, '下载失败'))
        controller.app._on_app_close = Mock()
        with patch('src.ui.feishu_dependency_controller.ttk.Button') as button:
            controller.poll()
        controller.app._on_app_close.assert_not_called()
        self.assertFalse(controller.restart_requested)
        self.assertFalse(controller.service.gate.active)
        self.assertEqual([call.kwargs['text'] for call in button.call_args_list], ['重试', '关闭'])

    def test_success_requests_close_once_but_does_not_spawn_from_ui(self):
        controller = self.controller(RepairResult(True, '验证成功'))
        controller.app._on_app_close = Mock(side_effect=lambda: setattr(controller.app, '_app_closing', True))
        controller.poll()
        controller.app._on_app_close.assert_called_once()
        self.assertTrue(controller.restart_requested)
        self.assertTrue(controller.service.gate.active)
        self.assertIsNone(controller.window)

    def test_close_veto_keeps_app_and_cancels_restart_request(self):
        controller = self.controller(RepairResult(True, '验证成功'))
        controller.app._on_app_close = Mock()
        with patch('src.ui.feishu_dependency_controller.messagebox.showwarning'):
            controller.poll()
        self.assertFalse(controller.restart_requested)
        self.assertFalse(controller.service.gate.active)

    def test_root_close_is_blocked_while_installer_owns_environment(self):
        from line_check_assistant.app import LineCheckAssistant
        repair = SimpleNamespace(prevents_close=True)
        app = SimpleNamespace(_feishu_dependency_controller=repair)
        with patch('line_check_assistant.app.messagebox.showinfo') as show:
            LineCheckAssistant._on_app_close(app)
        show.assert_called_once()
        self.assertNotIn('_app_closing', vars(app))


class InstallationTests(unittest.TestCase):
    def test_same_environment_other_process_is_rejected_without_exposing_arguments(self):
        import psutil
        current = Mock(pid=1)
        current.parents.return_value = current.children.return_value = []
        other = Mock(pid=2, info={'name': 'python.exe'})
        other.exe.return_value = sys.executable
        other.cmdline.return_value = [sys.executable, 'secret-argument']
        with patch.object(psutil, 'Process', return_value=current), patch.object(psutil, 'process_iter', return_value=[other]):
            with self.assertRaisesRegex(ValueError, '其他程序实例') as caught:
                install.assert_environment_unoccupied()
        self.assertNotIn('secret', str(caught.exception))

    def test_verified_different_venv_is_allowed_even_with_shared_base_python(self):
        import psutil
        current = Mock(pid=1)
        current.parents.return_value = current.children.return_value = []
        with tempfile.TemporaryDirectory() as folder:
            current_env = Path(folder) / 'current'
            other_env = Path(folder) / 'other'
            (other_env / 'Scripts').mkdir(parents=True)
            (other_env / 'pyvenv.cfg').touch()
            launcher = Mock()
            launcher.name.return_value = 'python.exe'
            launcher.exe.return_value = str(other_env / 'Scripts/python.exe')
            launcher.cmdline.return_value = [launcher.exe.return_value]
            other = Mock(pid=2, info={'name': 'python.exe'})
            other.exe.return_value = getattr(sys, '_base_executable', sys.executable)
            other.cmdline.return_value = [other.exe.return_value]
            other.parents.return_value = [launcher]
            with patch.object(sys, 'prefix', str(current_env)), \
                    patch.object(sys, 'executable', str(current_env / 'Scripts/python.exe')), \
                    patch.object(sys, '_base_executable', other.exe.return_value), \
                    patch.object(psutil, 'Process', return_value=current), \
                    patch.object(psutil, 'process_iter', return_value=[other]):
                install.assert_environment_unoccupied()

    def test_existing_lock_contains_target_and_no_unlocked_requirement(self):
        versions = install.locked_versions(ROOT)
        self.assertEqual(versions['lark-oapi'], '1.7.5')
        self.assertEqual(versions['websockets'], '15.0.1')

    def test_rejects_global_and_frozen_python_before_changes(self):
        with patch.object(sys, 'prefix', sys.base_prefix):
            with self.assertRaisesRegex(ValueError, '虚拟环境'):
                install.source_environment(ROOT)
        with patch.object(sys, 'frozen', True, create=True):
            with self.assertRaisesRegex(ValueError, 'EXE'):
                install.source_environment(ROOT)

    def test_source_environment_requires_the_qt_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            venv = root / 'venv'
            venv.mkdir()
            (venv / 'pyvenv.cfg').write_text('include-system-site-packages = false\n', encoding='utf-8')
            (root / 'requirements-build.txt').write_bytes((ROOT / 'requirements-build.txt').read_bytes())
            with patch.object(sys, 'prefix', str(venv)), patch.object(sys, 'platform', 'win32'), \
                    patch.object(sys, 'version_info', (3, 9, 10)), \
                    patch.object(install.struct, 'calcsize', return_value=8):
                with self.assertRaisesRegex(ValueError, '源码入口不存在'):
                    install.source_environment(root)
                (root / QT_ENTRY.name).touch()
                self.assertEqual(install.source_environment(root), root)

    def test_wheels_must_be_locked_exactly_and_contain_sdk(self):
        with tempfile.TemporaryDirectory() as folder:
            path = wheel(folder)
            self.assertEqual(install.checked_wheels(folder, {'lark-oapi': '1.7.5'})[0][0], 'lark-oapi')
            with self.assertRaisesRegex(ValueError, '锁定'):
                install.checked_wheels(folder, {'lark-oapi': '1.0'})
            path.unlink()
            wheel(folder, 'unlisted', '1.0')
            with self.assertRaisesRegex(ValueError, '锁定'):
                install.checked_wheels(folder, {'lark-oapi': '1.7.5'})

    def test_sdist_is_never_installed(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'package.tar.gz').write_bytes(b'not a wheel')
            with self.assertRaisesRegex(ValueError, '非wheel'):
                install.checked_wheels(folder, {'lark-oapi': '1.7.5'})

    def test_success_downloads_then_installs_locked_wheels_offline_then_checks(self):
        commands, logs = [], []
        def runner(args, **kwargs):
            commands.append(args)
            if 'download' in args:
                folder = args[args.index('--dest') + 1]
                wheel(folder)
                wheel(folder, 'httpx', '0.28.1')
                text = Path(args[args.index('--constraint') + 1]).read_text()
                self.assertIn('lark-oapi==1.7.5', text)
                self.assertNotIn('-r ', text)
            return SimpleNamespace(returncode=0, stdout=b'')
        with patch.object(install, 'source_environment', return_value=ROOT), \
                patch.object(install, 'assert_environment_unoccupied'), \
                patch.object(install.importlib.metadata, 'version', side_effect=importlib.metadata.PackageNotFoundError):
            install.install_feishu(ROOT, logs.append, runner)
        self.assertEqual(len(commands), 4)
        self.assertEqual(commands[0][0], sys.executable)
        self.assertIn('--only-binary=:all:', commands[0])
        self.assertIn('--no-index', commands[1])
        self.assertIn('--no-deps', commands[1])
        self.assertIn('lark_oapi.ws.client', commands[2][-1])
        self.assertEqual(commands[3][-2:], ['pip', 'check'])
        self.assertIn('成功', logs[-1])

    def test_failed_download_never_installs_or_claims_success(self):
        runner = Mock(return_value=SimpleNamespace(returncode=1, stdout=b'ProxyError https://user:secret@index.invalid'))
        logs = []
        with patch.object(install, 'source_environment', return_value=ROOT), patch.object(install, 'assert_environment_unoccupied'):
            with self.assertRaisesRegex(RuntimeError, '代理') as caught:
                install.install_feishu(ROOT, logs.append, runner)
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('secret', '\n'.join(logs))
        runner.assert_called_once()

    def test_import_or_pip_check_failure_never_returns_success(self):
        for failure_stage in (2, 3):
            count = [0]
            def runner(args, **kwargs):
                stage = count[0]
                count[0] += 1
                if 'download' in args:
                    wheel(args[args.index('--dest') + 1])
                return SimpleNamespace(returncode=1 if stage == failure_stage else 0, stdout=b'conflicting dependencies')
            with self.subTest(stage=failure_stage), patch.object(install, 'source_environment', return_value=ROOT), \
                    patch.object(install, 'assert_environment_unoccupied'):
                with self.assertRaises(RuntimeError):
                    install.install_feishu(ROOT, Mock(), runner)

    def test_other_instance_refuses_before_network(self):
        runner = Mock()
        with patch.object(install, 'source_environment', return_value=ROOT), \
                patch.object(install, 'assert_environment_unoccupied', side_effect=ValueError('其他实例')):
            with self.assertRaisesRegex(ValueError, '其他实例'):
                install.install_feishu(ROOT, Mock(), runner)
        runner.assert_not_called()

    def test_timeout_reports_stage_without_raw_output(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired(['pip'], 1, output=b'secret'))
        with self.assertRaisesRegex(RuntimeError, '下载超时') as caught:
            install.run_checked(['python', '-m', 'pip'], '下载', Mock(), runner=runner)
        self.assertNotIn('secret', str(caught.exception))


class RestartTests(unittest.TestCase):
    def test_helper_failure_uses_native_notice_without_tk(self):
        from scripts import restart_source_after_exit as helper
        with patch.object(sys, 'argv', ['restart_source_after_exit.py']), \
                patch('ctypes.windll.user32.MessageBoxW') as notice:
            self.assertEqual(helper.main(), 1)
        parent, message, title, icon = notice.call_args.args
        self.assertIsNone(parent)
        self.assertIn('手动启动', message)
        self.assertEqual(title, '重启未完成')
        self.assertEqual(icon, 0x10)

    def test_real_helper_waits_for_parent_exit_and_launches_fake_entry_once(self):
        with tempfile.TemporaryDirectory(prefix='重启 path ') as directory:
            folder = Path(directory).resolve()
            marker, armed, release = (folder / name for name in ('marker.txt', 'armed.txt', 'release.txt'))
            entry, parent_script = folder / QT_ENTRY.name, folder / 'parent.py'
            entry.write_text("from pathlib import Path\nimport sys\nwith Path(sys.argv[1]).open('a') as f: f.write('started\\n')\n", encoding='utf-8')
            helper = ROOT / 'scripts/restart_source_after_exit.py'
            parent_script.write_text(
                "import os,sys,subprocess,time,psutil\nfrom pathlib import Path\n"
                "helper,entry,marker,armed,release=sys.argv[1:]\n"
                "subprocess.Popen([sys.executable,'-B',helper,str(os.getpid()),str(psutil.Process().create_time()),"
                "str(Path(entry).parent),sys.executable,entry,marker],creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
                "Path(armed).touch()\nlimit=time.monotonic()+15\n"
                "while not Path(release).exists() and time.monotonic()<limit: time.sleep(.02)\n", encoding='utf-8')
            parent = subprocess.Popen([sys.executable, '-B', str(parent_script), str(helper), str(entry),
                                       str(marker), str(armed), str(release)],
                                      creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                limit = time.monotonic() + 10
                while not armed.exists() and time.monotonic() < limit:
                    time.sleep(.02)
                self.assertTrue(armed.exists())
                self.assertIsNone(parent.poll())
                self.assertFalse(marker.exists())
                release.touch()
                parent.wait(timeout=10)
                limit = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < limit:
                    time.sleep(.02)
                self.assertEqual(marker.read_text(), 'started\n')
            finally:
                release.touch()
                if parent.poll() is None:
                    parent.wait(timeout=10)

    def test_app_handoff_runs_only_after_mainloop_returns(self):
        import line_check_assistant.app as module
        events = []
        repair = SimpleNamespace(restart_requested=True, arguments=['--gateway-slot', '3'], cwd=str(ROOT))
        app = SimpleNamespace(_feishu_dependency_controller=repair, mainloop=lambda: events.append('mainloop_return'))
        helper = Mock(side_effect=lambda *a, **kw: events.append('helper'))
        with patch.dict(os.environ, {'LINECHECK_LEGACY_SINGLE_PROJECT': '1'}), patch.object(module, 'LineCheckAssistant', return_value=app), patch.object(restart, 'launch_restart_helper', helper):
            module.main()
        self.assertEqual(events, ['mainloop_return', 'helper'])
        helper.assert_called_once_with(module.APP_DIR, repair.arguments, cwd=repair.cwd)
        repair.restart_requested = False
        helper.reset_mock()
        with patch.dict(os.environ, {'LINECHECK_LEGACY_SINGLE_PROJECT': '1'}), patch.object(module, 'LineCheckAssistant', return_value=app), patch.object(restart, 'launch_restart_helper', helper):
            module.main()
        helper.assert_not_called()

    def test_workspace_handoff_runs_after_mainloop_and_closes_single_instance(self):
        import line_check_assistant.app as module
        events = []
        repair = SimpleNamespace(restart_requested=True, arguments=['project.linecheck.json'], cwd=str(ROOT))
        workspace = SimpleNamespace(_feishu_dependency_controller=repair, mainloop=lambda: events.append('mainloop_return'))
        instance = Mock()
        instance.start.return_value = True
        helper = Mock(side_effect=lambda *a, **kw: events.append('helper'))
        with patch.dict(os.environ, {'LINECHECK_LEGACY_SINGLE_PROJECT': '0'}), \
                patch('src.core.workspace_instance.WorkspaceInstance', return_value=instance), \
                patch('src.ui.project_workspace.ProjectWorkspace', return_value=workspace), \
                patch.object(restart, 'launch_restart_helper', helper):
            module.main()
        self.assertEqual(events, ['mainloop_return', 'helper'])
        helper.assert_called_once_with(module.APP_DIR, repair.arguments, cwd=repair.cwd)
        instance.close.assert_called_once()

    def test_helper_preserves_interpreter_cwd_and_business_args_without_debugger(self):
        with tempfile.TemporaryDirectory(prefix='中文 path ') as folder:
            root = Path(folder).resolve()
            (root / 'scripts').mkdir()
            (root / 'scripts/restart_source_after_exit.py').touch()
            entry = root / QT_ENTRY.name
            popen = Mock()
            with self.assertRaisesRegex(RuntimeError, '源码重启入口不可用'):
                restart.launch_restart_helper(root, popen=popen)
            popen.assert_not_called()
            entry.touch()
            with patch.object(sys, 'argv', [QT_ENTRY.name, '--gateway-slot', '4']), \
                    patch.dict(os.environ, {'PYTHONPATH': 'debugpy', 'PYTHONHOME': 'wrong'}):
                restart.launch_restart_helper(root, popen=popen)
            args = popen.call_args.args[0]
            self.assertEqual(args[0], sys.executable)
            self.assertEqual(args[-4:], [sys.executable, str(entry), '--gateway-slot', '4'])
            self.assertEqual(args[5], os.getcwd())
            self.assertNotIn('PYTHONPATH', popen.call_args.kwargs['env'])

    def test_waits_for_old_process_before_launching_once(self):
        events = []
        previous = Mock()
        previous.create_time.return_value = 1.0
        previous.wait.side_effect = lambda **kw: events.append('exited')
        popen = Mock(side_effect=lambda *a, **kw: events.append('spawned'))
        command = [sys.executable, str(QT_ENTRY), '--gateway-slot', '2']
        restart.wait_and_restart(123, 1.0, str(ROOT), command, Mock(return_value=previous), popen)
        self.assertEqual(events, ['exited', 'spawned'])
        popen.assert_called_once()

    def test_timeout_never_starts_second_copy(self):
        import psutil
        previous, popen = Mock(), Mock()
        previous.create_time.return_value = 1.0
        previous.wait.side_effect = psutil.TimeoutExpired(120)
        with self.assertRaisesRegex(RuntimeError, '原程序尚未退出'):
            restart.wait_and_restart(123, 1.0, str(ROOT), [sys.executable, str(QT_ENTRY)],
                                     Mock(return_value=previous), popen)
        popen.assert_not_called()

    def test_already_exited_or_reused_pid_does_not_wait_on_unrelated_process(self):
        import psutil
        popen = Mock()
        command = [sys.executable, str(QT_ENTRY)]
        restart.wait_and_restart(123, 1.0, str(ROOT), command, Mock(side_effect=psutil.NoSuchProcess(123)), popen)
        popen.assert_called_once()
        previous = Mock()
        previous.create_time.return_value = 2.0
        restart.wait_and_restart(123, 1.0, str(ROOT), command, Mock(return_value=previous), Mock())
        previous.wait.assert_not_called()


class DialogTests(unittest.TestCase):
    def test_real_two_button_dialog_choices_and_close_on_both_themes(self):
        import tkinter as tk
        from tkinter import ttk
        from tk_test_windows import OffscreenTkWindows
        from src.ui.feishu_dependency_dialog import MissingFeishuSdkDialog
        with OffscreenTkWindows() as windows:
            root = tk.Tk()
            try:
                for theme in ('vista', 'clam'):
                    ttk.Style(root).theme_use(theme)
                    for choice in ('ok', 'install', 'close'):
                        dialog = MissingFeishuSdkDialog(root)
                        self.assertEqual(dialog.install_button.cget('text'), '安装并重启')
                        self.assertEqual(dialog.ok_button.cget('text'), '确定')
                        self.assertEqual(dialog.window.cget('background'), '#eef2f5')
                        if choice == 'close':
                            action = lambda: root.tk.call(dialog.window.protocol('WM_DELETE_WINDOW'))
                        else:
                            action = dialog.install_button.invoke if choice == 'install' else dialog.ok_button.invoke
                        root.after(30, action)
                        self.assertEqual(dialog.show(), choice == 'install')
                windows.assert_offscreen()
            finally:
                root.destroy()


if __name__ == '__main__':
    unittest.main()
