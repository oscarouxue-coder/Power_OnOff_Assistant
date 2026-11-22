"""Exercise copied pre-migration projects in the guarded native workbench."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from PySide6.QtWidgets import QFileDialog, QMessageBox

import qt_workbench_probe
from validation.pyside6_migration_20261118.archived_projects import check_archived_projects as archive


class ArchivedWindowTests(qt_workbench_probe.QtProjectWorkspaceTests):
    def setUp(self):
        profile = tempfile.TemporaryDirectory(prefix='archived-ui-profile-')
        self.addCleanup(profile.cleanup)
        root = Path(profile.name)
        env = patch.dict(os.environ, LOCALAPPDATA=str(root / 'local'), APPDATA=str(root / 'roaming'),
                         PROGRAMDATA=str(root / 'machine'), LINECHECK_GATEWAY_SLOT='')
        env.start()
        self.addCleanup(env.stop)
        super().setUp()

    def test_copied_projects_in_workspace(self):
        receipt = json.loads((archive.STAGES / 'backup_receipt.json').read_text(encoding='utf-8-sig'))
        bundle = Path(receipt['directory']) / 'data.zip'
        self.assertEqual(archive.digest_file(bundle), receipt['data_zip_sha256'])
        projects = archive.restore(bundle, self.root)
        blocked = []
        archive.block_external_io(blocked)
        with patch('serial.Serial', side_effect=AssertionError('unexpected serial open')) as serial:
            for directory in projects:
                self.check_project(directory)
            serial.assert_not_called()
        self.assertFalse(blocked)
        self.assertEqual(len(projects), 2)
        self.assertEqual(archive.digest_file(bundle), receipt['data_zip_sha256'])

    def check_project(self, directory):
        descriptor = directory / archive.PROJECT_FILE
        expected = json.loads(descriptor.read_text(encoding='utf-8'))
        pid = expected['project_id']
        original = archive.inventory(directory / 'draft/Auto_power_on_off_tool/config')
        controls = self.controller
        def open_copy():
            with patch.object(QFileDialog, 'getOpenFileName', return_value=(str(descriptor), '')):
                controls.open_action.trigger()
            self.wait_for(lambda: controls._current() is not None and controls._current().project_id == pid)
        def close_copy():
            with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                controls.close_action.trigger()
            self.wait_for(lambda: all(row.project_id != pid for row in self.window.projects))

        open_copy()
        self.assertEqual(self.window.detail.name.text(), expected['name'])
        tabs = self.window.detail.tabs
        for index, windows in ((2, controls.upgrade_windows), (3, controls.parameter_writer.windows),
                               (4, controls.onu_query.windows), (5, controls.serial_windows), (6, controls.dut_windows)):
            with self.subTest(module=tabs.tabText(index)):
                self.assertTrue(tabs.isTabEnabled(index))
                tabs.setCurrentIndex(index)
                self.wait_for(lambda: pid in windows and not getattr(windows[pid], 'busy', False))
                self.assertTrue(windows[pid].isVisible())
                windows[pid].close()
                self.wait_for(lambda: pid not in windows)
        self.window.detail.edit_button.click()
        self.wait_for(lambda: pid in controls.configuration_editors)
        editor = controls.configuration_editors[pid]
        self.assertTrue(editor.isVisible())
        editor.close()
        self.wait_for(lambda: pid not in controls.configuration_editors)
        self.wait_for(controls.save_action.isEnabled)
        controls.save_action.trigger()
        self.wait_for(lambda: json.loads(descriptor.read_text(encoding='utf-8'))['revision'] != expected['revision'])
        close_copy()
        open_copy()
        self.assertEqual(archive.inventory(directory / 'draft/Auto_power_on_off_tool/config'), original)
        self.assertEqual(controls._current().active_task_count, 0)
        close_copy()
