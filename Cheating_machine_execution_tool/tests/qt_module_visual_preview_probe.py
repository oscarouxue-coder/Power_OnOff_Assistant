"""Native checks of five review windows assembled from the actual Qt dialogs."""
import os
from pathlib import Path
import unittest

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QPushButton
from qt_test_guard import install_qt_test_scope

from src.ui.qt.module_visual_preview import MODULES, ModuleVisualPreview
from src.ui.qt.theme import apply_theme
from src.ui.qt.visual_preview import VisualPreview


SCREENSHOTS = ('serial', 'upgrade', 'dut', 'configuration', 'channels')


class ModuleVisualPreviewTests(unittest.TestCase):
    def test_real_controls_and_fixture_match_in_both_layouts(self):
        scope = install_qt_test_scope(self)
        apply_theme(scope.app)
        workbench = VisualPreview()
        self.addCleanup(workbench.close)
        workbench.show()
        entry = next(control for control in workbench.findChildren(QPushButton)
                     if control.text() == '业务窗口预览…')
        entry.click()
        preview = workbench.findChild(ModuleVisualPreview)
        self.assertIsNotNone(preview)
        self.addCleanup(preview.close)
        preview.resize(1060, 840)
        self.assertTrue(preview.isVisible())
        for index, (name, kind) in enumerate(MODULES):
            with self.subTest(module=name):
                preview.modules.setCurrentIndex(index)
                before, after = (preview.versions.widget(n) for n in range(2))
                self.assertIsInstance(before, kind)
                self.assertIsInstance(after, kind)
                self.assertEqual(before.windowTitle(), after.windowTitle())
                self.assertEqual(before.feedback.text(), after.feedback.text())
                self._check_fixture(index, before, after)
                for variant in range(2):
                    preview.variant_buttons.button(variant).click()
                    QTest.qWait(40)
                    self.assertTrue(preview.versions.widget(variant).isVisible())
                    self._capture(preview, index, variant, narrow=False)
                preview.resize(640, 520)
                QTest.qWait(40)
                self.assertLessEqual(preview.width(), 640)
                control = after.stop_button if index in (0, 1, 2) else after.save_button
                self.assertTrue(control.isVisible())
                self.assertTrue(preview.rect().contains(control.mapTo(preview, control.rect().bottomRight())))
                self._capture(preview, index, 1, narrow=True)
                preview.resize(1060, 840)

    def _check_fixture(self, index, before, after):
        if index == 0:
            self.assertEqual(after.tabs.count(), 2)
            self.assertEqual(before.views['vlan116']['output'].toPlainText(), after.views['vlan116']['output'].toPlainText())
            self.assertTrue(after.views['vlan118']['status'].property('previewIssue'))
            self.assertFalse(after.views['vlan118']['input'].isEnabled())
        elif index == 1:
            self.assertEqual(before.results.toPlainText(), after.results.toPlainText())
            self.assertIn('等待设备启动超时', after.results.toPlainText())
            self.assertEqual(after.password.echoMode(), QLineEdit.EchoMode.Password)
        elif index == 2:
            self.assertEqual(after.tabs.count(), 6)
            self.assertEqual(before.status.toPlainText(), after.status.toPlainText())
            for tab in range(6):
                after.tabs.setCurrentIndex(tab)
                self.assertEqual(len(after.targets), 3)
            after.tabs.setCurrentIndex(0)
        elif index == 3:
            self.assertEqual(before.tabs.count(), after.tabs.count())
            self.assertEqual(before.draft.values, after.draft.values)
        else:
            self.assertEqual(len(after.rows), 16)
            self.assertEqual(before.rows[0].source.text(), after.rows[0].source.text())
            self.assertTrue(after.rows[0].source.isReadOnly())

    def _capture(self, preview, index, variant, *, narrow):
        folder = os.environ.get('DUTPILOT_MODULE_PREVIEW_DIRECTORY')
        scale = preview.devicePixelRatioF()
        if folder and ((scale == 1 and not narrow) or (scale == 1.5 and narrow)):
            suffix = '-narrow' if narrow else ''
            version = 'after' if variant else 'before'
            path = Path(folder) / f'{SCREENSHOTS[index]}-{version}{suffix}.png'
            self.assertTrue(preview.grab().save(str(path)), str(path))
