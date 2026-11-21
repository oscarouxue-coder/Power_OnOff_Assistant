"""Preserve the real Qt test guard and retain exception details for the temporary report fixture."""
import sys
import traceback
from unittest.mock import patch
from qt_workbench_probe import QtProjectWorkspaceTests


class TracedHandoff(QtProjectWorkspaceTests):
    def trace_operation(self, method):
        original = self.controller.adapter._emit

        def record(message, *args, **kwargs):
            error = sys.exc_info()[1]
            if error is not None:
                print('WORKSPACE_COMMAND_FAILURE', message, flush=True)
                traceback.print_exception(type(error), error, error.__traceback__, file=sys.stdout)
            return original(message, *args, **kwargs)

        with patch.object(self.controller.adapter, '_emit', side_effect=record):
            method()

    def test_report_handoff_with_command_trace(self):
        self.trace_operation(self.test_qt_ai_report_handoff_confirms_legacy_target_without_sending)

    def test_manual_upgrade_with_command_trace(self):
        self.trace_operation(self.test_qt_full_upgrade_without_power_requires_manual_restart_acknowledgement)

    def test_background_refresh_with_exclusive_fixture_file(self):
        import ctypes
        from ctypes import wintypes
        import os
        from PySide6.QtWidgets import QMessageBox

        self.controller.submit('create', self.root / 'locked', '模拟文件共享')
        self.wait_for(lambda: len(self.window.projects) == 1)
        identifier = self.window.selected_project
        context = self.controller.adapter._service.projects.opened[identifier]
        target = context.config_dir / 'test_project_config.ini'
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        receipts = []
        take = self.controller.adapter.take_updates

        def observe():
            projects, logs, results = take()
            receipts.extend(r for r in results if r.operation == 'refresh')
            return projects, logs, results

        with patch.object(self.controller.adapter, 'take_updates', side_effect=observe), \
                patch.object(QMessageBox, 'warning', return_value=QMessageBox.StandardButton.Ok) as warning:
            handle = kernel.CreateFileW(str(target), 0x80000000, 0, None, 3, 0x80, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self.wait_for(lambda: any(r.error for r in receipts))
                self.assertIn('PermissionError', next(r.error for r in receipts if r.error))
                self.assertEqual([r.project_id for r in self.window.projects], [identifier])
                self.assertEqual(warning.called, os.environ.get('DUTPILOT_EXPECT_REFRESH_MODAL') == '1')
            finally:
                self.assertTrue(kernel.CloseHandle(handle))
            receipts.clear()
            self.wait_for(lambda: any(not r.error for r in receipts))
            self.assertEqual(self.window.selected_project, identifier)
            print('BACKGROUND_REFRESH', 'modal=' + str(warning.called), 'recovered=True')
